"""Software-only tests of the dev8/test16 study gates, never model-quality results."""
from copy import deepcopy
import json
from pathlib import Path

from PIL import Image
import pytest

from hre.models import HREError, file_sha256
from hre.storage import read_json, write_json
from hre.sr.contracts import FIXTURE_MARKER, METHODS, SLOTS
from hre.sr.study import _real_development_ready, create_study, freeze_study, run_study, study_report


def fixture_config():
    return {"mode": "fixture", "fixture_marker": FIXTURE_MARKER,
            "fixture": {"judge": {"improved": ["C1"], "ranking": ["C1", "C2", "C3"]}}}


def manifest(tmp_path, *, with_gt=False):
    value = {"study_id": "software_study", "seed": 13, "dev": [], "test": []}
    for index in range(24):
        cid = f"image_{index:02d}"
        source = tmp_path / (cid + ".png")
        Image.new("RGB", (9, 11), (20 + index * 5, 40, 60)).save(source)
        row = {"case_id": cid, "source": {"path": str(source)}, "rois": [{"id": "detail", "box": [1, 2, 8, 9]}]}
        if with_gt and index == 0:
            gt = tmp_path / "forbidden_offline_truth.png"
            Image.new("RGB", (36, 44), (230, 240, 250)).save(gt)
            row["ground_truth"] = {"path": str(gt)}
        value["dev" if index < 8 else "test"].append(row)
    return value


def proxy_selection(case_id="image_00", artifact_sha256="0" * 64):
    return {"methods": [METHODS[0]], "observations": [{"case_id": case_id, "artifact_sha256": artifact_sha256,
             "failure": "Recorded candidate detail did not preserve the source structure.",
             "why_method": "Inspect downsample consistency alongside the separate content assessment."}]}


def test_study_creation_freezes_exact_dev8_test16_and_global_seed(tmp_path):
    root = tmp_path / "study"
    result = create_study(root, manifest(tmp_path), fixture_config())
    assert result["phases"]["dev"]["planned"] == 8
    assert result["phases"]["test"]["planned"] == 16
    assert result["phases"]["dev"]["terminal"] == result["phases"]["test"]["terminal"] == 0
    assert result["conditions_frozen"] is False
    assert result["test_gate"] == "pending_real_dev8_and_selection"
    assert result["x1_experiments"] == "pending_after_sr"
    study = read_json(root / "study.json")
    rows = study["phases"]["dev"] + study["phases"]["test"]
    assert len({row["source"]["pixel_sha256"] for row in rows}) == 24
    assert {row["spec"]["seed"] for row in rows} == {13}
    assert not (root / "cases").exists()


@pytest.mark.parametrize("phase,change", [("dev", -1), ("dev", 1), ("test", -1), ("test", 1)])
def test_study_requires_exact_phase_cardinality(tmp_path, phase, change):
    value = manifest(tmp_path)
    if change < 0:
        value[phase].pop()
    else:
        value[phase].append(deepcopy(value[phase][-1]))
    with pytest.raises(HREError, match="sr_study_size"):
        create_study(tmp_path / "study", value, fixture_config())


@pytest.mark.parametrize("seed", [True, -1, 1.5, float("nan"), float("inf"), 2**32])
def test_study_seed_is_strict_finite_and_shared(tmp_path, seed):
    value = manifest(tmp_path)
    value["seed"] = seed
    with pytest.raises(HREError):
        create_study(tmp_path / "study", value, fixture_config())


@pytest.mark.parametrize("phase", ["dev", "test"])
def test_study_case_ids_are_unique_across_both_phases(tmp_path, phase):
    value = manifest(tmp_path)
    value[phase][-1]["case_id"] = value["dev"][0]["case_id"]
    with pytest.raises(HREError, match="sr_study_duplicate"):
        create_study(tmp_path / "study", value, fixture_config())


@pytest.mark.parametrize("phase", ["dev", "test"])
@pytest.mark.parametrize("encoding", ["BMP", "opaque_RGBA"])
def test_reencoded_equal_pixels_cannot_fill_multiple_study_slots(tmp_path, phase, encoding):
    value = manifest(tmp_path)
    original = Path(value["dev"][0]["source"]["path"])
    recoded = tmp_path / ("reencoded_source.bmp" if encoding == "BMP" else "reencoded_source.png")
    with Image.open(original) as image:
        (image if encoding == "BMP" else image.convert("RGBA")).save(recoded)
    assert file_sha256(original) != file_sha256(recoded)
    value[phase][-1]["source"]["path"] = str(recoded)
    with pytest.raises(HREError, match="sr_study_overlap"):
        create_study(tmp_path / "study", value, fixture_config())


@pytest.mark.parametrize("key", ["origin_path", "original_path", "path"])
def test_source_mutation_blocks_study_execution(tmp_path, key):
    root = tmp_path / "study"
    create_study(root, manifest(tmp_path), fixture_config())
    frozen_source = read_json(root / "study.json")["phases"]["test"][0]["source"]
    Image.new("RGB", (9, 11), "magenta").save(frozen_source[key], format="PNG")
    with pytest.raises(HREError, match="sr_study_source_modified"):
        run_study(root, "dev")
    assert not (root / "cases").exists()


def test_study_manifest_mutation_is_detected(tmp_path):
    root = tmp_path / "study"
    create_study(root, manifest(tmp_path), fixture_config())
    frozen = read_json(root / "study.json")
    frozen["seed"] += 1
    write_json(root / "study.json", frozen)
    with pytest.raises(HREError, match="sr_study_modified"):
        study_report(root)


@pytest.mark.parametrize("mode", ["fixture", "real"])
def test_test16_cannot_run_before_real_development_freeze(tmp_path, mode):
    root = tmp_path / "study"
    config = fixture_config() if mode == "fixture" else {"mode": "real", "models": {}}
    create_study(root, manifest(tmp_path), config)
    with pytest.raises(HREError, match="sr_study_not_frozen"):
        run_study(root, "test")
    assert not (root / "cases" / "test").exists()


def test_unrun_real_development_cannot_be_frozen(tmp_path):
    root = tmp_path / "study"
    create_study(root, manifest(tmp_path), {"mode": "real", "models": {}})
    with pytest.raises(HREError, match="sr_development_incomplete"):
        freeze_study(root, proxy_selection())
    assert not (root / "conditions.json").exists()


def test_fixture_dev8_executes_but_gt_stays_offline_and_real_gate_stays_closed(tmp_path):
    root = tmp_path / "study"
    value = manifest(tmp_path, with_gt=True)
    create_study(root, value, fixture_config())
    result = run_study(root, "dev")
    assert result["phases"]["dev"]["terminal"] == 8
    assert result["phases"]["dev"]["real_completed"] == 0
    assert result["phases"]["test"]["terminal"] == 0
    assert result["conditions_frozen"] is False
    assert result["quality_claims"] is False
    assert len(list((root / "results" / "dev").glob("*.json"))) == 8
    study = read_json(root / "study.json")
    gt = study["phases"]["dev"][0]["offline_ground_truth"]
    assert gt["online_use"] is False
    case_root = root / "cases" / "dev" / "image_00"
    case = read_json(case_root / "case.json")
    assert "ground_truth" not in case["task"] and "offline_ground_truth" not in case["task"]
    for arm in ("visual", "evidence"):
        request = read_json(case_root / "operations" / ("judge_" + arm) / "request.json")
        encoded = json.dumps(request)
        assert gt["path"] not in encoded and "forbidden_offline_truth" not in encoded
    with pytest.raises(HREError, match="sr_fixture_not_development"):
        freeze_study(root, proxy_selection())
    with pytest.raises(HREError, match="sr_study_not_frozen"):
        run_study(root, "test")
    assert run_study(root, "dev") == result


def test_blocked_real_dev8_records_failures_without_advancing_test_gate(tmp_path):
    root = tmp_path / "study"
    create_study(root, manifest(tmp_path), {"mode": "real", "models": {}})
    result = run_study(root, "dev")
    assert result["phases"]["dev"]["terminal"] == 8
    assert result["phases"]["dev"]["real_completed"] == 0
    assert result["phases"]["test"]["terminal"] == 0
    assert result["conditions_frozen"] is False
    assert result["test_gate"] == "pending_real_dev8_and_selection"
    for case in result["phases"]["dev"]["cases"].values():
        assert case["status"] == "unresolved" and case["selected_slot"] is None
        accounting = case["accounting"]
        assert accounting["real_model_calls"] == accounting["real_judge_calls"] == 0
        assert accounting["produced_count"] == accounting["valid_count"] == 0
        assert accounting["candidate_failures"] == {slot: "blocked" for slot in SLOTS}
    with pytest.raises(HREError, match="sr_development_incomplete"):
        freeze_study(root, proxy_selection())
    assert not (root / "conditions.json").exists()


def test_submission_flags_alone_cannot_certify_real_development():
    invented = {"execution_kind": "real", "status": "selected", "operations": {}, "candidates": {},
                "evidence": {}, "judgements": {}, "accounting": {"real_model_calls": 4, "real_judge_calls": 2}}
    for key in ["model_" + slot for slot in SLOTS] + ["judge_visual", "judge_evidence"]:
        invented["operations"][key] = {"submitted": True, "status": "complete"}
    assert _real_development_ready(invented) is False


def synthetic_invocation_report():
    result = {"execution_kind": "real", "status": "unresolved", "operations": {}, "candidates": {}, "judgements": {}}
    for slot in SLOTS:
        result["operations"]["model_" + slot] = {"submitted": True, "status": "complete"}
        attempt_key = "image_calls_attempted" if slot == "C3" else "calls_attempted"
        result["candidates"][slot] = {"observation": {attempt_key: 1, "fixture": False}}
    for arm in ("visual", "evidence"):
        result["operations"]["judge_" + arm] = {"submitted": True, "status": "complete"}
        result["judgements"][arm] = {"observation": {"calls_attempted": 1}}
    return result


def test_ready_predicate_accepts_complete_synthetic_invocation_records():
    result = synthetic_invocation_report()
    assert _real_development_ready(result) is True
    result["operations"]["model_C2"]["status"] = "failed"
    assert _real_development_ready(result) is True


@pytest.mark.parametrize("observation", [{}, {"calls_attempted": 0}, {"calls_attempted": True},
                                         {"calls_attempted": 1, "fixture": True}])
def test_ready_predicate_rejects_missing_or_fixture_invocation_observations(observation):
    result = synthetic_invocation_report()
    result["candidates"]["C2"]["observation"] = observation
    assert _real_development_ready(result) is False


@pytest.mark.parametrize("key,status", [("model_C0", "blocked"), ("model_C2", "unknown"),
                                       ("judge_visual", "submitted"), ("judge_evidence", "abandoned")])
def test_ready_predicate_rejects_nonterminal_or_unexecuted_operations(key, status):
    result = synthetic_invocation_report()
    result["operations"][key]["status"] = status
    assert _real_development_ready(result) is False


def test_uncommitted_conditions_file_does_not_open_test_gate(tmp_path):
    root = tmp_path / "study"
    create_study(root, manifest(tmp_path), {"mode": "real", "models": {}})
    write_json(root / "conditions.json", {"schema_version": "hre_sr_study_freeze_v02", "real_development_complete": True,
                                         "study_sha256": file_sha256(root / "study.json"), "selected_methods": list(METHODS)})
    with pytest.raises(HREError, match="sr_study_not_frozen"):
        run_study(root, "test")
    assert not (root / "cases").exists()


@pytest.mark.parametrize("mode,code", [("fixture", "sr_study_conditions_changed"), ("real", "sr_development_incomplete")])
def test_forged_conditions_without_real_dev_results_cannot_open_test_gate(tmp_path, mode, code):
    root = tmp_path / "study"
    config = fixture_config() if mode == "fixture" else {"mode": "real", "models": {}}
    create_study(root, manifest(tmp_path), config)
    study_sha = file_sha256(root / "study.json")
    write_json(root / "conditions.json", {"schema_version": "hre_sr_study_freeze_v02", "real_development_complete": True,
                                         "study_sha256": study_sha, "development_results": {}, "selected_methods": list(METHODS)})
    write_json(root / "conditions.identity.json", {"study_sha256": study_sha,
                                                  "conditions_sha256": file_sha256(root / "conditions.json")})
    with pytest.raises(HREError, match=code):
        run_study(root, "test")
    assert not (root / "cases").exists()


@pytest.mark.parametrize("selection", [
    {"methods": [], "observations": [{}]},
    {"methods": [METHODS[0], METHODS[0]], "observations": [{}]},
    {"methods": ["unknown_metric"], "observations": [{}]},
    {"methods": [METHODS[0]], "observations": []},
])
def test_proxy_selection_requires_implemented_methods_and_observed_failures(tmp_path, selection):
    root = tmp_path / "study"
    create_study(root, manifest(tmp_path), fixture_config())
    with pytest.raises(HREError, match="sr_study_selection"):
        freeze_study(root, selection)
