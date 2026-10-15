"""Synthetic audit-rendering tests; they do not establish model/edit quality."""
import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from hir_manual.offline_gallery import render_gallery
from hir_manual.service import Controller
from hir_manual.storage import read_json, sha256_file, write_json
from hir_manual.tool_registry import load_profile, make_contract
from local_fixtures import face_evidence, synthetic_registry


@pytest.fixture
def gallery_batch(tmp_path, photo, fixture_json):
    batch = tmp_path / "runtime/batch"
    ctl = Controller(batch / "workflow")
    state = ctl.new(photo, "Preserve source composition; synthetic audit fixture only")
    case = ctl.case(state.case_id)
    diagnosis = fixture_json("diagnosis")
    diagnosis["tool_plan"] = []
    diagnosis["content"] = '<script>alert("unsafe")</script> & synthetic fixture'
    assert ctl.import_json(state.case_id, ctl.current_task(state.case_id).task_id, diagnosis, "fixture").accepted
    canonical = batch / "inputs/canonical.png"
    canonical.parent.mkdir(parents=True)
    shutil.copyfile(case.path("input/canonical.png"), canonical)
    sample = {"sample_id": "fixture", "stratum": "synthetic", "canonical_path": str(canonical), "canonical_sha256": sha256_file(canonical), "original_sha256": sha256_file(photo), "width": 64, "height": 48}
    write_json(batch / "manifest.json", {"images": [sample]})
    write_json(batch / "diagnostic_results.json", {"records": [{"sample_id": "fixture", "case_id": state.case_id}]})
    return tmp_path, batch, ctl, state, sample


def render(data, status=None):
    root, batch, *_ = data
    output = root / "runtime/report"
    path = render_gallery(root, batch, output, status)
    return path.read_text(encoding="utf-8"), read_json(output / "summary.json")


def test_self_contained_escaped_and_missing_is_not_success(gallery_batch):
    text, summary = render(gallery_batch)
    assert '<script>alert("unsafe")</script>' not in text
    assert "&lt;script&gt;" in text
    assert "data:image/jpeg;base64," in text
    assert "Content-Security-Policy" in text
    assert '<script' not in text
    assert summary["input_count"] == summary["diagnoses"] == 1
    assert summary["harness_output_count"] == summary["direct_output_count"] == 0
    assert summary["records"][0]["restoration_success"] is None
    assert summary["records"][0]["tools"]["T1_OCR"] == "pending"
    assert "未完成" in text


def test_unvalidated_raw_map_is_never_read(gallery_batch):
    root, batch, *_ = gallery_batch
    records = [{"image_id": "fixture", "tool_id": "T3_DEPTH", "status": "pending", "evidence_dir": str(root / "outside_missing"), "source_paths": ['<img src=x onerror="attack">']}]
    text, summary = render(gallery_batch, {"records": records})
    assert summary["validated_evidence_count"] == 0
    assert summary["records"][0]["tools"]["T3_DEPTH"] == "pending"
    assert "&lt;img src=x" in text
    assert '<img src=x' not in text


def test_claimed_validated_missing_contract_is_rejected(gallery_batch):
    root, batch, *_ = gallery_batch
    records = [{"image_id": "fixture", "tool_id": "T2_FACE", "status": "validated", "evidence_dir": str(root / "missing")}]
    text, summary = render(gallery_batch, {"records": records})
    assert summary["validated_evidence_count"] == 0
    assert summary["records"][0]["tools"]["T2_FACE"] == "rejected"


def valid_face(data):
    root, batch, ctl, state, sample = data
    entry = synthetic_registry(root)
    contract = make_contract(sample["canonical_sha256"], "T2_FACE", load_profile(), entry)
    directory = root / "Data/annotations/cache/fixture_face"
    face_evidence(directory, contract)
    write_json(directory / "contract.json", contract)
    return directory


def test_empty_detection_distinct_from_failure(gallery_batch):
    directory = valid_face(gallery_batch)
    record = {"image_id": "fixture", "tool_id": "T2_FACE", "status": "validated", "evidence_dir": str(directory)}
    text, summary = render(gallery_batch, {"records": [record]})
    assert summary["validated_evidence_count"] == 1
    assert summary["records"][0]["tools"]["T2_FACE"] == "empty"
    assert "未检测到对象" in text
    assert "synthetic_fixture_no_model_called" in text
    (directory / "maps/faces.png").write_bytes(b"tampered")
    text, summary = render(gallery_batch, {"records": [record]})
    assert summary["records"][0]["tools"]["T2_FACE"] == "rejected"
    assert summary["validated_evidence_count"] == 0


def test_array_and_contract_must_belong_to_same_photo(gallery_batch):
    directory = valid_face(gallery_batch)
    record = {"image_id": "fixture", "tool_id": "T2_FACE", "status": "validated", "evidence_dir": str(directory)}
    manifest = read_json(directory / "evidence.json")
    manifest["input_sha256"] = "a" * 64
    write_json(directory / "evidence.json", manifest)
    text, summary = render(gallery_batch, {"records": [record]})
    assert summary["records"][0]["tools"]["T2_FACE"] == "rejected"


def test_only_accepted_round_output_and_actual_instruction_are_displayed(gallery_batch, fixture_json):
    root, batch, ctl, state, sample = gallery_batch
    composition = fixture_json("composition")
    composition["instruction"] = "Synthetic edited fixture. Preserve source framing and original geometry. <img src=x onerror=evil>"
    assert ctl.import_json(state.case_id, ctl.current_task(state.case_id).task_id, composition, "fixture").accepted
    output = root / "changed_fixture.png"
    Image.new("RGB", (64, 48), (70, 80, 90)).save(output)
    assert ctl.import_image(state.case_id, ctl.current_task(state.case_id).task_id, output, "fixture").accepted
    # A stray image neither accepted nor transaction-linked is not an output.
    Image.new("RGB", (64, 48), (255, 0, 0)).save(ctl.case(state.case_id).path("final/stray.png"))
    text, summary = render(gallery_batch)
    assert summary["harness_output_count"] == 1
    assert summary["independent_verifier_count"] == 0
    assert summary["records"][0]["restoration_success"] is None
    assert "&lt;img src=x onerror=evil&gt;" in text
    assert "stray.png" not in text
    assert "首轮指令" in text
    assert "Harness · Round 1" in text


def test_identical_input_copy_is_not_counted_as_restoration(gallery_batch, fixture_json):
    root, batch, ctl, state, sample = gallery_batch
    assert ctl.import_json(state.case_id, ctl.current_task(state.case_id).task_id, fixture_json("composition"), "fixture").accepted
    canonical = ctl.case(state.case_id).path("input/canonical.png")
    assert ctl.import_image(state.case_id, ctl.current_task(state.case_id).task_id, canonical, "fixture").accepted
    text, summary = render(gallery_batch)
    assert summary["harness_output_count"] == 0
    assert "Unchanged source copy" in text


def test_input_hash_change_disables_evidence(gallery_batch):
    root, batch, ctl, state, sample = gallery_batch
    directory = valid_face(gallery_batch)
    Path(sample["canonical_path"]).write_bytes(b"changed input")
    record = {"image_id": "fixture", "tool_id": "T2_FACE", "status": "validated", "evidence_dir": str(directory)}
    text, summary = render(gallery_batch, {"records": [record]})
    assert summary["validated_evidence_count"] == 0
    assert "Canonical input hash changed" in text


def test_paths_outside_workspace_are_rejected(gallery_batch):
    root, batch, *_ = gallery_batch
    with pytest.raises(ValueError, match="escapes"):
        render_gallery(root, batch, root.parent / "outside/report")
    record = {"image_id": "fixture", "tool_id": "T3_DEPTH", "status": "validated", "evidence_dir": str(root.parent / "outside")}
    text, summary = render(gallery_batch, {"records": [record]})
    assert summary["records"][0]["tools"]["T3_DEPTH"] == "rejected"


def test_float_depth_direction_and_native_grid_are_visible(gallery_batch):
    from preprocessing.adapters.depth import write_depth
    root, batch, ctl, state, sample = gallery_batch
    entry = synthetic_registry(root)
    entry["model_name"] = "Depth-Anything-V2-Small"
    entry["backend"]["implementation"] = "depth_anything_author_api"
    contract = make_contract(sample["canonical_sha256"], "T3_DEPTH", load_profile(), entry)
    directory = root / "Data/annotations/cache/fixture_depth"
    manifest = face_evidence(directory, contract)
    values = np.tile(np.linspace(0, 1, 64, dtype=np.float32), (48, 1))
    data, assets, warnings = write_depth(values, directory, "full", contract["parameters"]["larger_is"])
    manifest.update(tool_id="T3_DEPTH", model_name="Depth-Anything-V2-Small", data=data, assets=assets, quality_warnings=warnings)
    write_json(directory / "evidence.json", manifest)
    write_json(directory / "contract.json", contract)
    record = {"image_id": "fixture", "tool_id": "T3_DEPTH", "status": "validated", "evidence_dir": str(directory)}
    text, summary = render(gallery_batch, {"records": [record]})
    assert summary["records"][0]["tools"]["T3_DEPTH"] == "validated"
    assert "float32 相对深度" in text
    assert "更近" in text
    assert "不表示米制距离" in text
    assert "view_to_canonical" in text
    np.save(directory / data["depth_path"], values.astype(np.uint8), allow_pickle=False)
    text, summary = render(gallery_batch, {"records": [record]})
    assert summary["records"][0]["tools"]["T3_DEPTH"] == "rejected"


def test_native_overlapping_masks_and_class_legend_are_visible(gallery_batch):
    from preprocessing.adapters.common import full_view
    from preprocessing.adapters.segmentation import write_segmentation
    root, batch, ctl, state, sample = gallery_batch
    entry = synthetic_registry(root)
    entry["model_name"] = "YOLOE-26n-seg"
    entry["backend"]["implementation"] = "ultralytics_yoloe_text"
    profile = load_profile()
    contract = make_contract(sample["canonical_sha256"], "T4_SEGMENTATION", profile, entry)
    directory = root / "Data/annotations/cache/fixture_seg"
    manifest = face_evidence(directory, contract)
    labels = profile.tools["T4_SEGMENTATION"]["prompt_set"]["labels"]
    records = [{"id": "a", "prompt_index": 0, "label": labels[0], "score": .9, "bbox": [0, 0, 32, 48], "mask": np.tile(np.arange(64) < 32, (48, 1))}, {"id": "b", "prompt_index": 1, "label": labels[1], "score": .8, "bbox": [16, 0, 64, 48], "mask": np.tile(np.arange(64) >= 16, (48, 1))}]
    data, assets, warnings = write_segmentation(records, profile.tools["T4_SEGMENTATION"]["prompt_set"], directory, full_view(64, 48), (64, 48))
    manifest.update(tool_id="T4_SEGMENTATION", model_name="YOLOE-26n-seg", data=data, assets=assets, quality_warnings=warnings)
    write_json(directory / "evidence.json", manifest)
    write_json(directory / "contract.json", contract)
    record = {"image_id": "fixture", "tool_id": "T4_SEGMENTATION", "status": "validated", "evidence_dir": str(directory)}
    text, summary = render(gallery_batch, {"records": [record]})
    assert summary["records"][0]["tools"]["T4_SEGMENTATION"] == "validated"
    assert "实例可重叠" in text
    assert "重叠像素 768" in text
    assert "unassigned/unknown" in text
    assert "score_desc_then_prompt_index_then_instance_id" in text
    assert labels[0] in text and labels[1] in text


def test_pending_task_prompt_tampering_is_visible(gallery_batch):
    root, batch, ctl, state, sample = gallery_batch
    task = ctl.current_task(state.case_id)
    ctl.case(state.case_id).path(task.prompt_file).write_text("INJECTED NEW PROMPT", encoding="utf-8")
    text, summary = render(gallery_batch)
    assert "待执行任务提示词哈希改变" in text
    assert "INJECTED NEW PROMPT" not in text
