"""Synthetic worker/array fixtures for orchestration; no GPU inference passed."""
import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from hir_manual.remote_batch import ORDER, run_batch, validate_dataset, verify_shutdown_record
from hir_manual.storage import read_json, sha256_file, write_json
from hir_manual.tool_models import WorkerResult
from hir_manual.tool_registry import CANONICALIZER_VERSION, load_profile
from local_fixtures import face_evidence, synthetic_registry


@pytest.fixture
def server(tmp_path, monkeypatch):
    dataset = tmp_path / "prepared_dataset"
    rows = []
    for i in range(5):
        image_id = "synthetic_" + str(i)
        original = dataset / "originals" / (image_id + ".png")
        canonical = dataset / "canonical" / (image_id + ".png")
        original.parent.mkdir(parents=True, exist_ok=True)
        canonical.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (64, 48), (20 + i, 30, 40)).save(original)
        canonical.write_bytes(original.read_bytes())
        rows.append({"image_id": image_id, "canonical_path": canonical.relative_to(dataset).as_posix(), "original_path": original.relative_to(dataset).as_posix(), "canonical_sha256": sha256_file(canonical), "original_sha256": sha256_file(original), "canonicalizer_version": CANONICALIZER_VERSION, "width": 64, "height": 48})
    write_json(dataset / "manifest.json", {"images": rows, "pilot_ids": [r["image_id"] for r in rows], "fixture_only": True})
    profile = load_profile("gpu_full_v1")
    profile.configuration_status = "deployed_synthetic_test_only"
    profile.keep_worker_alive = False
    write_json(tmp_path / "preprocessing/configs/gpu_full.json", profile)
    base = synthetic_registry(tmp_path)
    entries = {}
    aliases = {"PP-OCRv6_medium_det+PP-OCRv6_medium_rec": "PP-OCRv6_medium_det+rec", "SCRFD_det_10g.onnx": "SCRFD_det_10g"}
    for tool in ORDER:
        entry = copy.deepcopy(base)
        parameters = profile.tools[tool]
        entry.update(ready=False, model_name=aliases.get(parameters["model"], parameters["model"]))
        entry["backend"].update(device=parameters["device"], precision=parameters["precision"], implementation=parameters["implementation"])
        entries[tool] = entry
    write_json(tmp_path / "preprocessing/registry/gpu_full_v1.json", {"registry_status": "synthetic_fixture_only", "automatic_download": False, "tools": entries})
    deadline = datetime.now(timezone.utc) + timedelta(minutes=110)
    receipt = tmp_path / "runtime/remote/shutdown_record.json"
    write_json(receipt, {"verified": True, "deadline_utc": deadline.isoformat(), "method": "synthetic_scheduler_fixture", "verification": {"fixture_only": True}})
    calls = []

    def synthetic_worker(job, registry, work_dir, profile, root, require_ready=True):
        from preprocessing.adapters.common import full_view
        from preprocessing.adapters.depth import write_depth
        from preprocessing.adapters.segmentation import write_segmentation
        calls.append((job.tool_id, job.image_id, require_ready))
        directory = Path(work_dir) / "result"
        config = read_json(Path(work_dir) / "runner_config.json")
        manifest = face_evidence(directory, job.cache_contract)
        manifest.update(tool_id=job.tool_id, image_id=job.image_id, evidence_profile_id=job.evidence_profile_id, model_name=registry.tools[job.tool_id]["model_name"], original_sha256=config["original_sha256"], formal_eligible=profile.formal_eligible)
        if job.tool_id == "T1_OCR":
            manifest["data"] = {"items": [], "native_result_path": "raw/faces.json"}
        elif job.tool_id == "T3_DEPTH":
            values = np.tile(np.linspace(0, 1, 64, dtype=np.float32), (48, 1))
            data, assets, warnings = write_depth(values, directory, "full", "near")
            manifest.update(data=data, assets=assets)
        elif job.tool_id == "T4_SEGMENTATION":
            data, assets, warnings = write_segmentation([], profile.tools[job.tool_id]["prompt_set"], directory, full_view(64, 48), (64, 48))
            manifest.update(data=data, assets=assets)
        write_json(directory / "evidence.json", manifest)
        write_json(directory / "worker_done.json", {"evidence_sha256": sha256_file(directory / "evidence.json"), "artifact_hashes": [{"path": a["path"], "sha256": a["sha256"]} for a in manifest["assets"]]})
        return WorkerResult(status="completed", returncode=0, pid=12345, elapsed_ms=3, peak_rss_mb=8, process_released=True, log_dir=str(Path(work_dir) / "logs"), output_dir=str(directory))

    monkeypatch.setattr("hir_manual.tool_service.run_worker", synthetic_worker)
    monkeypatch.setattr("hir_manual.remote_batch._gpu_sample", lambda: {"at": "synthetic_fixture", "scope": "synthetic_device_wide", "devices": [{"index": 0, "uuid": "synthetic", "memory_used_mib": 10, "memory_total_mib": 24000}], "processes": [], "available": True})
    return tmp_path, dataset, receipt, rows, calls


def pilot_path(root, dataset):
    return root / "runtime/remote_batches" / sha256_file(dataset / "manifest.json")[:16] / "pilot/summary.json"


def test_authorized_alternative_reuses_only_exact_three_tool_proof(server):
    """Synthetic orchestration only, never reported as real GPU inference."""
    root, dataset, receipt, rows, calls = server
    original = run_batch(root, dataset, "pilot")
    old_path = pilot_path(root, dataset)
    old_sha = sha256_file(old_path)
    profile = load_profile("gpu_full_v1", root).model_copy(deep=True)
    profile.evidence_profile_id = "gpu_yoloe26l_v1"
    profile.formal_eligible = False
    profile.tools["T4_SEGMENTATION"].update(model="YOLOE-26l-seg", implementation="ultralytics_yoloe_text")
    write_json(root / "preprocessing/configs/gpu_yoloe26l.json", profile)
    registry = read_json(root / "preprocessing/registry/gpu_full_v1.json")
    entry = registry["tools"]["T4_SEGMENTATION"]
    entry.update(model_name="YOLOE-26l-seg", ready=False, warmup_evidence=None)
    entry["backend"]["implementation"] = "ultralytics_yoloe_text"
    write_json(root / "preprocessing/registry/gpu_yoloe26l_v1.json", registry)
    calls.clear()
    alternate = run_batch(root, dataset, "pilot", profile_id="gpu_yoloe26l_v1")
    assert alternate["complete"] and alternate["cache_hits_this_run"] == 15
    assert alternate["model_executions_this_run"] == 5
    assert len(calls) == 5 and all(item[0] == "T4_SEGMENTATION" for item in calls)
    assert sha256_file(old_path) == old_sha and original["profile"]["formal_eligible"] is True
    alt_path = old_path.parent.parent / "gpu_yoloe26l_v1/pilot/summary.json"
    assert read_json(alt_path)["profile"]["formal_eligible"] is False
    with pytest.raises(ValueError, match="pilot summary|different frozen"):
        run_batch(root, dataset, "all", pilot_review=review(root, dataset), profile_id="gpu_yoloe26l_v1")


def review(root, dataset):
    path = root / "synthetic_review.json"
    write_json(path, {"accepted": True, "reviewed_by": "synthetic fixture; no real photo review", "pilot_summary_sha256": sha256_file(pilot_path(root, dataset))})
    return path


def test_reviewed_subset_is_bounded_and_cannot_claim_full_dataset(server):
    root, dataset, receipt, rows, calls = server
    run_batch(root, dataset, "pilot")
    before = sha256_file(pilot_path(root, dataset))
    selected = [rows[0]["image_id"], rows[3]["image_id"]]
    with pytest.raises(ValueError, match="pilot-review"):
        run_batch(root, dataset, "all", image_ids=selected)
    calls.clear()
    result = run_batch(root, dataset, "all", pilot_review=review(root, dataset), image_ids=selected)
    assert result["complete"] and not result["full_dataset_complete"]
    assert result["scope"] == "reviewed_subset" and result["selected_image_count"] == 2
    assert len(result["results"]) == 8 and result["cache_hits_this_run"] == 8 and not calls
    assert {r["image_id"] for r in result["results"]} == set(selected)
    assert sha256_file(pilot_path(root, dataset)) == before
    per_tool = run_batch(root, dataset, "all", pilot_review=review(root, dataset), image_ids=selected, tool_ids=["T4_SEGMENTATION"])
    assert per_tool["complete"] and not per_tool["full_dataset_complete"]
    assert per_tool["scope"] == "reviewed_tool_subset" and len(per_tool["results"]) == 2
    assert per_tool["requested_tool_ids"] == ["T4_SEGMENTATION"] and not calls
    for bad_tools in ([], ["unknown"], ["T4_SEGMENTATION","T4_SEGMENTATION"]):
        with pytest.raises(ValueError, match="Tool selection"):
            run_batch(root, dataset, "all", pilot_review=review(root, dataset), image_ids=selected, tool_ids=bad_tools)
    with pytest.raises(ValueError, match="Tool selection"):
        run_batch(root, dataset, "pilot", tool_ids=["T4_SEGMENTATION"])
    for bad in ([selected[0], selected[0]], ["unknown_image"], []):
        with pytest.raises(ValueError, match="Selection requires"):
            run_batch(root, dataset, "all", pilot_review=review(root, dataset), image_ids=bad)
    with pytest.raises(ValueError, match="Selection requires"):
        run_batch(root, dataset, "pilot", image_ids=selected)


def test_prepared_photos_hash_geometry_version_and_traversal(server):
    root, dataset, receipt, rows, calls = server
    manifest = validate_dataset(dataset)
    assert len(manifest["images"]) == 5
    original = dataset / rows[0]["original_path"]
    original.write_bytes(b"changed source")
    with pytest.raises(ValueError, match="SHA256"):
        validate_dataset(dataset)
    assert calls == []


def test_canonical_dimension_and_version_are_not_silently_changed(server):
    root, dataset, receipt, rows, calls = server
    manifest = read_json(dataset / "manifest.json")
    manifest["images"][0]["width"] = 65
    write_json(dataset / "manifest.json", manifest)
    with pytest.raises(ValueError, match="original-size"):
        validate_dataset(dataset)
    manifest["images"][0]["width"] = 64
    manifest["images"][0]["canonicalizer_version"] = "unrecorded"
    write_json(dataset / "manifest.json", manifest)
    with pytest.raises(ValueError, match="canonicalizer"):
        validate_dataset(dataset)


def test_missing_or_different_shutdown_receipt_blocks_before_inference(server):
    root, dataset, receipt, rows, calls = server
    with pytest.raises(ValueError, match="differs"):
        run_batch(root, dataset, "pilot", shutdown_deadline=(datetime.now(timezone.utc) + timedelta(minutes=100)).isoformat())
    record = read_json(receipt)
    record["verified"] = False
    write_json(receipt, record)
    with pytest.raises(ValueError, match="verified shutdown"):
        run_batch(root, dataset, "pilot")
    assert calls == []


def test_five_by_four_actual_stub_runs_then_resume_same_contract(server):
    root, dataset, receipt, rows, calls = server
    summary = run_batch(root, dataset, "pilot")
    assert summary["complete"] and summary["actual_inference_confirmed_count"] == 20
    assert [c[0] for c in calls] == [tool for tool in ORDER for _ in range(5)]
    assert all(c[2] is False for c in calls)
    assert sum(r["status"] == "empty" for r in summary["results"]) == 15
    assert all(r["process_released"] is True for r in summary["results"])
    assert all(r["gpu"]["peak_is_sampled"] is True for r in summary["results"])
    assert all("actual_run_evidence_dir" in r for r in summary["results"])
    resumed = run_batch(root, dataset, "pilot")
    assert resumed["complete"]
    assert len(calls) == 20
    assert all(r["cache_hit"] for r in resumed["results"])
    index = read_json(Path(resumed["validated_results_zip"]).parent / "results_manifest.json")
    assert index["bundle_kind"] == "unbound_cache_results"
    assert index["bundle_id"] is None and index["local_import_authorized"] is False


def test_full_requires_literal_visual_review_bound_to_current_pilot(server):
    root, dataset, receipt, rows, calls = server
    run_batch(root, dataset, "pilot")
    with pytest.raises(ValueError, match="requires a pilot-review"):
        run_batch(root, dataset, "all")
    review_path = review(root, dataset)
    reviewed = read_json(review_path)
    reviewed["accepted"] = "true"
    write_json(review_path, reviewed)
    with pytest.raises(ValueError, match="explicit visual review"):
        run_batch(root, dataset, "all", pilot_review=review_path)
    reviewed["accepted"] = True
    reviewed["pilot_summary_sha256"] = "0" * 64
    write_json(review_path, reviewed)
    with pytest.raises(ValueError, match="explicit visual review"):
        run_batch(root, dataset, "all", pilot_review=review_path)
    summary = run_batch(root, dataset, "all", pilot_review=review(root, dataset))
    assert summary["complete"] and len(summary["results"]) == 20
    assert len(calls) == 20  # The already-tested same-contract pilot is reused.


def test_review_cannot_hide_corrupt_cache_or_changed_actual_run(server):
    root, dataset, receipt, rows, calls = server
    summary = run_batch(root, dataset, "pilot")
    review_path = review(root, dataset)
    result = summary["results"][0]
    (Path(result["actual_run_evidence_dir"]) / "evidence.json").write_bytes(b"changed actual inference record")
    with pytest.raises(ValueError, match="Actual pilot-run evidence changed"):
        run_batch(root, dataset, "all", pilot_review=review_path)


def test_oom_or_timeout_stop_once_and_do_not_mark_empty(server, monkeypatch):
    root, dataset, receipt, rows, calls = server
    def failure(job, registry, work_dir, profile, root, require_ready=True):
        calls.append(job.job_id)
        return WorkerResult(status="failed", error_code="oom", message="synthetic OOM fixture", pid=12345, process_released=True, log_dir=str(Path(work_dir) / "logs"), output_dir=str(Path(work_dir) / "result"))
    monkeypatch.setattr("hir_manual.tool_service.run_worker", failure)
    summary = run_batch(root, dataset, "pilot")
    assert not summary["complete"] and len(calls) == 1
    assert summary["results"][0]["status"] == "failed"
    assert summary["results"][0]["error_code"] == "oom"
    assert summary["results"][0]["io_attempts"] == 1
    assert read_json(Path(summary["validated_results_zip"]).parent / "results_manifest.json")["entries"] == []
    resumed = run_batch(root, dataset, "pilot")
    assert len(calls) == 1 and resumed["results"][0]["retry_blocked"] is True


def test_shutdown_return_window_stops_without_extending_receipt(server):
    root, dataset, receipt, rows, calls = server
    original = read_json(receipt)
    original["deadline_utc"] = (datetime.now(timezone.utc) + timedelta(minutes=16)).isoformat()
    write_json(receipt, original)
    before = receipt.read_bytes()
    summary = run_batch(root, dataset, "pilot")
    assert summary["stopped_reason"] == "shutdown_return_window"
    assert not summary["complete"] and calls == []
    assert receipt.read_bytes() == before


def test_unsupported_shutdown_uses_compute_limit_but_does_not_claim_shutdown(server):
    root, dataset, receipt, rows, calls = server
    record = {"verified": False, "status": "unsupported", "compute_deadline_utc": (datetime.now(timezone.utc) + timedelta(minutes=16)).isoformat(), "verification": {"synthetic_container_no_shutdown": True}}
    write_json(receipt, record)
    summary = run_batch(root, dataset, "pilot")
    assert summary["shutdown_verified"] is False
    assert summary["shutdown_deadline_utc"] is None
    assert summary["compute_deadline_utc"]
    assert summary["stopped_reason"] == "shutdown_return_window"
    assert calls == []


@pytest.mark.parametrize("failure,expected_calls", [(ValueError("invalid model output"), 1), (OSError(__import__("errno").EACCES, "denied"), 1), (OSError(__import__("errno").EAGAIN, "transient fixture"), 2)])
def test_only_transient_io_retries_once(server, monkeypatch, failure, expected_calls):
    root, dataset, receipt, rows, calls = server
    def fail(*args):
        calls.append("synthetic_failure")
        raise failure
    monkeypatch.setattr("hir_manual.remote_batch._run_one", fail)
    summary = run_batch(root, dataset, "pilot")
    assert not summary["complete"] and len(calls) == expected_calls
    assert summary["results"][0]["io_attempts"] == expected_calls


def test_missing_later_tool_does_not_block_earlier_pilot_probes(server):
    root, dataset, receipt, rows, calls = server
    registry_path = root / "preprocessing/registry/gpu_full_v1.json"
    registry = read_json(registry_path)
    registry["tools"]["T4_SEGMENTATION"]["python_executable"] = None
    write_json(registry_path, registry)
    summary = run_batch(root, dataset, "pilot")
    assert not summary["complete"]
    assert len(calls) == 15
    assert [c[0] for c in calls] == [tool for tool in ORDER[:3] for _ in range(5)]
    assert summary["results"][-1]["tool_id"] == "T4_SEGMENTATION"
    assert summary["results"][-1]["error_code"] == "model_missing"
    assert summary["actual_inference_confirmed_count"] == 15
