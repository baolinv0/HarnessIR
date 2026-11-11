"""Crash-window recovery and strictly offline oracle accounting."""
import os
from pathlib import Path

from PIL import Image
import pytest

from hre.models import HREError, file_sha256
from hre.storage import read_json
from hre.sr import adapters, runtime
from hre.sr.contracts import FIXTURE_MARKER


def case(tmp_path, *, improved=None, baseline_content="pass"):
    source = tmp_path / "source.png"
    Image.new("RGB", (17, 13), (40, 81, 123)).save(source)
    config = {"mode": "fixture", "fixture_marker": FIXTURE_MARKER,
              "fixture": {"judge": {"improved": ["C1"] if improved is None else improved,
                                    "content": {"C0": baseline_content}}}}
    root = tmp_path / "case"
    runtime.create_case(root, {"source": {"path": str(source)}, "case_id": "example"}, config)
    return root


def oracle_for(root, *, improved=("C1",), baseline=True, best="C1"):
    case_data = read_json(root / "case.json")
    state = runtime.report(root)
    return {"schema_version": "hre_sr_oracle_v02", "case_id": "example",
            "source_sha256": case_data["source"]["sha256"], "source_pixel_sha256": case_data["source"]["pixel_sha256"],
            "method_version": "explicit_synthetic_labels_v1",
            "candidates": {slot: {"sha256": record["output"]["sha256"], "content_preserved": baseline if slot == "C0" else True,
                                   "improved_over_y0": slot in improved}
                           for slot, record in state["candidates"].items() if record["status"] == "valid"}, "best_slot": best}


def test_orphan_submission_marker_is_abandonable_without_resubmission(tmp_path, monkeypatch):
    root = case(tmp_path)
    original_commit = runtime.Journal.commit
    dispatched = []
    original_dispatch = runtime._fixture_candidate

    def dispatch(request, *args):
        dispatched.append(request["slot"])
        return original_dispatch(request, *args)

    def interrupt(self, state, event, details=None):
        if event == "operation_submitted":
            raise KeyboardInterrupt("after submitted marker, before journal append")
        return original_commit(self, state, event, details)

    monkeypatch.setattr(runtime, "_fixture_candidate", dispatch)
    monkeypatch.setattr(runtime.Journal, "commit", interrupt)
    with pytest.raises(KeyboardInterrupt):
        runtime.run_case(root)
    assert (root / "operations/model_C0/submitted.json").is_file()
    assert dispatched == []
    monkeypatch.setattr(runtime.Journal, "commit", original_commit)
    with pytest.raises(HREError, match="submission|submitted|reconciliation"):
        runtime.run_case(root)
    reconciled = runtime.reconcile_unknown(root, "model_C0", "Operator abandons the uncertain attempt")
    assert reconciled["operations"]["model_C0"]["status"] == "abandoned"
    final = runtime.run_case(root)
    assert final["selected_output"] is None
    assert final["candidates"]["C0"]["status"] == "failed"
    assert dispatched == ["C1", "C2", "C3"]


def test_report_oracle_computes_pool_and_selection_without_online_change(tmp_path):
    root = case(tmp_path)
    runtime.run_case(root)
    before = {p.relative_to(root): file_sha256(p) for p in root.rglob("*") if p.is_file()}
    labels = oracle_for(root)
    result = runtime.report(root, labels)
    assert result["accounting"]["pool_oracle_quality_coverage"] is True
    assert result["accounting"]["selection_failure"] is False
    assert result["accounting"]["offline_oracle"]["selected_matches_best"] is True
    assert result["accounting"]["offline_oracle"]["online_use"] is False
    assert before == {p.relative_to(root): file_sha256(p) for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("kind", ["fallback", "unresolved"])
def test_offline_labels_separate_available_pool_from_avoidable_selection(tmp_path, kind):
    root = case(tmp_path, improved=[], baseline_content="uncertain" if kind == "unresolved" else "pass")
    runtime.run_case(root)
    result = runtime.report(root, oracle_for(root))
    assert result["accounting"]["pool_oracle_quality_coverage"] is True
    assert result["accounting"]["selection_failure"] is True
    assert result["accounting"]["offline_oracle"]["avoidable_" + kind] is True


def test_nonbest_eligible_selection_is_separate_from_pool_selection_failure(tmp_path):
    root = case(tmp_path)
    runtime.run_case(root)
    result = runtime.report(root, oracle_for(root, improved=("C1", "C2"), best="C2"))
    assert result["accounting"]["selection_failure"] is False
    assert result["accounting"]["offline_oracle"]["selected_matches_best"] is False


@pytest.mark.parametrize("mutation", ["source", "candidate", "missing", "boolean", "best", "baseline_self", "private"])
def test_offline_oracle_rejects_unbound_incomplete_or_inconsistent_labels(tmp_path, mutation):
    root = case(tmp_path)
    runtime.run_case(root)
    labels = oracle_for(root)
    if mutation == "source":
        labels["source_sha256"] = "0" * 64
    elif mutation == "candidate":
        labels["candidates"]["C1"]["sha256"] = "0" * 64
    elif mutation == "missing":
        del labels["candidates"]["C2"]
    elif mutation == "boolean":
        labels["candidates"]["C1"]["content_preserved"] = 1
    elif mutation == "best":
        labels["best_slot"] = "C3"
    elif mutation == "baseline_self":
        labels["candidates"]["C0"]["improved_over_y0"] = True
    else:
        labels["private_path"] = "/not/online/gt.png"
    with pytest.raises(HREError):
        runtime.report(root, labels)


def test_deployment_hash_reuses_only_unchanged_file_metadata(tmp_path, monkeypatch):
    path = tmp_path / "weights.pth"
    path.write_bytes(b"abcd")
    calls = []
    original = adapters.file_sha256

    def counted(candidate):
        calls.append(str(candidate))
        return original(candidate)

    monkeypatch.setattr(adapters, "file_sha256", counted)
    first = adapters._deployment_hash(path)
    assert adapters._deployment_hash(path) == first
    assert len(calls) == 1
    stat = path.stat()
    path.write_bytes(b"dcba")
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert adapters._deployment_hash(path) != first
    assert len(calls) == 2


def test_candidate_mutation_during_judge_call_is_detected_before_selection(tmp_path, monkeypatch):
    root = case(tmp_path)
    original = runtime.evidence.invoke_judge

    def mutate_after_observation(case_data, request, bundle):
        result = original(case_data, request, bundle)
        if request["arm"] == "evidence":
            Image.new("RGB", (68, 52), "red").save(root / "operations/model_C1/delivered.png")
        return result

    monkeypatch.setattr(runtime.evidence, "invoke_judge", mutate_after_observation)
    with pytest.raises(HREError, match="artifact"):
        runtime.run_case(root)
    assert not (root / "decision.json").exists()
