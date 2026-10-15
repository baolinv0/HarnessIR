"""Synthetic cache inspection fixtures only; no models or restoration ran."""
import copy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from hir_manual.cache import EvidenceCache
from hir_manual.offline_monitor import scan_offline_cache
from hir_manual.storage import read_json, sha256_file, write_json
from hir_manual.tool_registry import CANONICALIZER_VERSION, load_profile, make_contract
from local_fixtures import face_evidence, synthetic_registry


@pytest.fixture
def setup(tmp_path):
    dataset = tmp_path / "runtime/prepared"
    dataset.mkdir(parents=True)
    image = dataset / "input.png"
    Image.new("RGB", (64, 48), (20, 30, 40)).save(image)
    row = {"image_id": "fixture", "canonical_path": "input.png", "original_path": "input.png", "canonical_sha256": sha256_file(image), "original_sha256": sha256_file(image), "canonicalizer_version": CANONICALIZER_VERSION, "width": 64, "height": 48}
    write_json(dataset / "manifest.json", {"images": [row], "source_count": 2, "rejected": [{"image_id": "unsupported_fixture", "status": "unsupported_input", "reason": "synthetic multipage input"}]})
    profile = load_profile("gpu_full_v1")
    profile.configuration_status = "deployed_synthetic_fixture"
    write_json(tmp_path / "preprocessing/configs/gpu_full.json", profile)
    base = synthetic_registry(tmp_path)
    entries = {}
    aliases = {"PP-OCRv6_medium_det+PP-OCRv6_medium_rec": "PP-OCRv6_medium_det+rec", "SCRFD_det_10g.onnx": "SCRFD_det_10g"}
    for tool, parameters in profile.tools.items():
        entry = copy.deepcopy(base)
        entry.update(model_name=aliases.get(parameters["model"], parameters["model"]))
        entry["backend"].update(implementation=parameters["implementation"], device=parameters["device"], precision=parameters["precision"])
        # Real monitor validates remote metadata without requiring Linux paths
        # to exist on Windows; this explicit fixture exercises that separation.
        entry["python_executable"] = "/synthetic_remote/venv/bin/python"
        entries[tool] = entry
    write_json(tmp_path / "preprocessing/registry/gpu_full_v1.json", {"registry_status": "synthetic_only", "automatic_download": False, "tools": entries})
    return tmp_path, dataset, row, profile, entries


def publish(setup, tool="T2_FACE"):
    from preprocessing.adapters.common import full_view
    from preprocessing.adapters.depth import write_depth
    from preprocessing.adapters.segmentation import write_segmentation
    root, dataset, row, profile, entries = setup
    contract = make_contract(row["canonical_sha256"], tool, profile, entries[tool], canonicalizer_version=row["canonicalizer_version"])
    directory = root / "runtime/synthetic_results" / tool
    evidence = face_evidence(directory, contract)
    evidence.update(tool_id=tool, image_id=row["image_id"], original_sha256=row["original_sha256"], evidence_profile_id="gpu_full_v1", formal_eligible=True, model_name=entries[tool]["model_name"])
    if tool == "T1_OCR":
        evidence["data"] = {"items": [], "native_result_path": "raw/faces.json"}
    elif tool == "T3_DEPTH":
        data, assets, warnings = write_depth(np.ones((48, 64), dtype=np.float32), directory, "full", "near")
        evidence.update(data=data, assets=assets)
    elif tool == "T4_SEGMENTATION":
        data, assets, warnings = write_segmentation([], profile.tools[tool]["prompt_set"], directory, full_view(64, 48), (64, 48))
        evidence.update(data=data, assets=assets)
    write_json(directory / "evidence.json", evidence)
    cache = EvidenceCache(root / "Data/annotations/cache")
    with cache.lock(tool, __import__("hir_manual.cache", fromlist=["make_cache_key"]).make_cache_key(contract)):
        cached = cache.publish(contract, directory)
    return cached


def scan(setup, batch=None):
    root, dataset, *_ = setup
    return scan_offline_cache(root, dataset, root / "runtime/monitor/status.json", batch)


def record(status, tool):
    return next(r for r in status["records"] if r["tool_id"] == tool)


def test_legal_empty_is_successful_evidence_not_complete_restoration(setup):
    directory = publish(setup)
    before = {p: sha256_file(p) for p in directory.rglob("*") if p.is_file()}
    status = scan(setup)
    assert record(status, "T2_FACE")["status"] == "empty"
    assert status["accepted_gpu_results"] == 1 and status["complete"] is False
    assert status["restoration_output_count"] == 0 and status["imports_performed"] == 0
    assert status["read_only"] and not status["case_states_modified"]
    assert len(status["unsupported_original_inputs"]) == 1
    assert before == {p: sha256_file(p) for p in directory.rglob("*") if p.is_file()}


def test_complete_requires_all_four_tools_and_accounted_original_inputs(setup):
    for tool in ("T1_OCR", "T2_FACE", "T3_DEPTH", "T4_SEGMENTATION"):
        publish(setup, tool)
    status = scan(setup)
    assert status["complete"] and status["accepted_gpu_results"] == 4
    assert status["counts"] == {"empty": 3, "validated": 1}
    root, dataset, *_ = setup
    manifest = read_json(dataset / "manifest.json")
    manifest["source_count"] = 99
    write_json(dataset / "manifest.json", manifest)
    assert not scan(setup)["complete"]


def test_tampered_contract_and_corrupt_assets_are_rejected(setup):
    cached = publish(setup)
    contract = read_json(cached / "contract.json")
    contract["canonicalizer_version"] = "wrong_version"
    write_json(cached / "contract.json", contract)
    assert record(scan(setup), "T2_FACE")["status"] == "rejected"


def test_corrupt_asset_is_not_false_empty(setup):
    cached = publish(setup)
    (cached / "maps/faces.png").write_bytes(b"damaged PNG")
    status = scan(setup)
    assert record(status, "T2_FACE")["status"] == "rejected"
    assert status["accepted_gpu_results"] == 0


def test_missing_ready_or_partial_commit_is_pending(setup):
    cached = publish(setup)
    ready = (cached / "ready.json").read_bytes()
    (cached / "ready.json").unlink()
    assert record(scan(setup), "T2_FACE")["status"] == "pending"
    (cached / "ready.json").write_bytes(ready)
    (cached / "interrupted.part").write_bytes(b"partial")
    assert record(scan(setup), "T2_FACE")["status"] == "pending"


def test_registry_without_ready_never_promotes_matching_cache(setup):
    publish(setup)
    root, dataset, *_ = setup
    path = root / "preprocessing/registry/gpu_full_v1.json"
    registry = read_json(path)
    registry["tools"]["T2_FACE"]["ready"] = False
    write_json(path, registry)
    status = scan(setup)
    assert record(status, "T2_FACE")["status"] == "pending"
    assert not status["complete"] and status["accepted_gpu_results"] == 0


def test_cpu_evidence_and_missing_gpu_registry_do_not_count(setup):
    root, dataset, row, profile, entries = setup
    entry = synthetic_registry(root)
    contract = make_contract(row["canonical_sha256"], "T2_FACE", load_profile(), entry, canonicalizer_version=row["canonicalizer_version"])
    directory = root / "runtime/cpu_fixture"
    evidence = face_evidence(directory, contract)
    evidence["original_sha256"] = row["original_sha256"]
    write_json(directory / "evidence.json", evidence)
    cache = EvidenceCache(root / "Data/annotations/cache")
    cache.publish(contract, directory)
    status = scan(setup)
    assert status["accepted_gpu_results"] == 0 and record(status, "T2_FACE")["status"] == "pending"
    (root / "preprocessing/registry/gpu_full_v1.json").unlink()
    status = scan(setup)
    assert status["frozen_gpu_metadata"]["status"] == "pending"
    assert all(r["status"] == "pending" for r in status["records"])


def test_raw_flat_files_are_only_discovered_without_array_loading(setup, monkeypatch):
    root, dataset, *_ = setup
    raw = root / "Data/annotations/cache/t3_depth/fixture.npy"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"not a real NPY; synthetic untrusted file")
    (raw.parent / "incomplete.part").write_bytes(b"unfinished")
    monkeypatch.setattr(np, "load", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("raw external array must not be loaded")))
    status = scan(setup)
    assert status["accepted_gpu_results"] == 0
    assert len(status["flat_discoveries"]) == 2
    assert all(r["status"] == "discovered-but-unvalidated" for r in status["flat_discoveries"])


def test_source_sha_and_version_fail_before_cache_acceptance(setup):
    publish(setup)
    root, dataset, row, *_ = setup
    (dataset / row["canonical_path"]).write_bytes(b"changed input")
    status = scan(setup)
    assert status["accepted_gpu_results"] == 0
    assert all(r["status"] == "rejected" for r in status["records"])


def test_validation_memory_wait_never_claims_bad_or_empty_map(setup, monkeypatch):
    publish(setup, "T3_DEPTH")
    monkeypatch.setattr("hir_manual.offline_monitor.psutil.virtual_memory", lambda: SimpleNamespace(available=16 * 1024**2))
    monkeypatch.setattr("hir_manual.offline_monitor.validate_local_evidence", lambda *_: (_ for _ in ()).throw(AssertionError("memory wait must not force array evaluation")))
    status = scan(setup)
    assert record(status, "T3_DEPTH")["status"] == "pending"
    assert record(status, "T3_DEPTH")["reason"] == "validation_memory_wait"
    assert status["accepted_gpu_results"] == 0


def test_gallery_subset_preserves_full_dataset_counts(setup):
    root, dataset, *_ = setup
    publish(setup)
    batch = root / "runtime/gallery_subset"
    write_json(batch / "manifest.json", {"images": [{"sample_id": "not_in_dataset"}]})
    status = scan(setup, batch)
    assert status["records"] == []
    assert len(status["all_records"]) == 4 and status["accepted_gpu_results"] == 1
