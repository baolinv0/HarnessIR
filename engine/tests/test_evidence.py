import io

import numpy as np
import pytest
from PIL import Image

from hir_manual.cases import create_case
from hir_manual.evidence import missing_evidence, register_evidence
from hir_manual.storage import CasePaths, read_json, sha256_file, write_json


@pytest.fixture
def evidence_case(tmp_path, photo):
    state = create_case(tmp_path, photo, "restore", {})
    state.required_tools = ["T1_OCR", "T2_FACE", "T3_DEPTH", "T4_SEGMENTATION"]
    case = CasePaths(state.case_id, tmp_path)
    write_json(case.path("state.json"), state)
    return case, state


def manifest(case, fixture_json, tool="T1_OCR"):
    data = fixture_json("evidence")
    data.update(tool_id=tool, input_sha256=sha256_file(case.path("input/canonical.png")), source_width=64, source_height=48, tool_width=64, tool_height=48, detections=[])
    return data


def asset(case, path, kind, dimensions=None):
    return {"path": path, "sha256": sha256_file(case.path(path)), "kind": kind, "width": dimensions[0] if dimensions else None, "height": dimensions[1] if dimensions else None}


def submit(case, data):
    path = case.path("tools/upload.json")
    write_json(path, data)
    return register_evidence(case, path)


def test_zero_detections_and_immutable_archive_no_state_write(evidence_case, fixture_json):
    case, state = evidence_case
    before = case.path("state.json").read_bytes()
    result = submit(case, manifest(case, fixture_json))
    assert result.status == "ok" and result.detections == []
    assert case.path("state.json").read_bytes() == before
    archived = list(case.path("tools/T1_OCR/versions").glob("*/evidence.json"))
    assert len(archived) == 1 and read_json(archived[0]) == result.model_dump()
    assert missing_evidence(state) == state.required_tools
    state.received_tools = ["T1_OCR", "T3_DEPTH"]
    assert missing_evidence(state) == ["T2_FACE", "T4_SEGMENTATION"]


@pytest.mark.parametrize("change", [{"input_sha256": "a" * 64}, {"source_width": 63}, {"tool_id": "T5_UNKNOWN"}, {"source_to_tool": [[1, 0, 0], [0, 0, 0], [0, 0, 1]]}, {"source_to_tool": [[1, 0, 0], [0, 1, 0], [0, .1, 1]]}])
def test_source_dimensions_and_affine_rejected(evidence_case, fixture_json, change):
    case, _ = evidence_case
    data = manifest(case, fixture_json)
    data.update(change)
    with pytest.raises(ValueError):
        submit(case, data)


def test_tool_must_be_in_locked_plan(evidence_case, fixture_json):
    case, state = evidence_case
    state.required_tools = []
    write_json(case.path("state.json"), state)
    with pytest.raises(ValueError, match="plan"):
        submit(case, manifest(case, fixture_json))


def test_reversed_bbox_rejected(evidence_case, fixture_json):
    case, _ = evidence_case
    data = manifest(case, fixture_json)
    data["detections"] = fixture_json("evidence")["detections"]
    data["detections"][0]["bbox_norm"] = [.8, .1, .2, .4]
    with pytest.raises(ValueError, match="bbox"):
        submit(case, data)


def test_tool_error_is_valid_metadata_for_controller_to_block(evidence_case, fixture_json):
    case, _ = evidence_case
    data = manifest(case, fixture_json, "T3_DEPTH")
    data.update(status="error", error="model unavailable")
    assert submit(case, data).error == "model unavailable"
    data["error"] = None
    with pytest.raises(ValueError, match="error"):
        submit(case, data)


def depth(case, fixture_json, values=None):
    data = manifest(case, fixture_json, "T3_DEPTH")
    raw = case.path("tools/depth.npy")
    np.save(raw, np.ones((48, 64), dtype=np.float32) if values is None else values, allow_pickle=True)
    Image.new("RGB", (64, 48), "blue").save(case.path("tools/depth.png"))
    data["assets"] = [asset(case, "tools/depth.npy", "raw_data"), asset(case, "tools/depth.png", "map", (64, 48))]
    data["data"] = {"depth_kind": "relative", "legend": {"near": "yellow", "far": "blue"}}
    return data


@pytest.mark.parametrize("values", [np.array([[object()]], dtype=object), np.ones((48, 64), dtype=np.float64), np.ones((2, 3), dtype=np.float32), np.full((48, 64), np.inf, dtype=np.float32)])
def test_depth_pickle_dtype_shape_and_finite_values(evidence_case, fixture_json, values):
    case, _ = evidence_case
    with pytest.raises(ValueError):
        submit(case, depth(case, fixture_json, values))


def test_depth_mask_allows_only_declared_invalid_pixels(evidence_case, fixture_json):
    case, _ = evidence_case
    values = np.ones((48, 64), dtype=np.float32)
    values[0, 0] = np.nan
    data = depth(case, fixture_json, values)
    mask = np.zeros((48, 64), dtype=np.uint8)
    mask[0, 0] = 1
    np.save(case.path("tools/invalid.npy"), mask)
    data["assets"].append(asset(case, "tools/invalid.npy", "raw_data"))
    data["data"]["invalid_mask"] = "tools/invalid.npy"
    assert submit(case, data).status == "ok"
    data["data"]["depth_kind"] = "pretend_metric"
    with pytest.raises(ValueError, match="depth_kind"):
        submit(case, data)


def test_successful_depth_requires_map_and_raw(evidence_case, fixture_json):
    case, _ = evidence_case
    with pytest.raises(ValueError):
        submit(case, manifest(case, fixture_json, "T3_DEPTH"))


def segmentation(case, fixture_json):
    data = manifest(case, fixture_json, "T4_SEGMENTATION")
    Image.fromarray(np.zeros((48, 64), dtype=np.uint8)).save(case.path("tools/labels.png"))
    Image.new("RGB", (64, 48), "black").save(case.path("tools/seg_map.png"))
    data["assets"] = [asset(case, "tools/labels.png", "raw_data"), asset(case, "tools/seg_map.png", "map", (64, 48))]
    data["data"] = {"labels": [{"id": 0, "label": "background"}], "background_id": 0, "ignore_id": None}
    return data


def test_segmentation_label_table_and_lossless_ids(evidence_case, fixture_json):
    case, _ = evidence_case
    data = segmentation(case, fixture_json)
    assert submit(case, data).status == "ok"
    data["data"]["labels"][0]["id"] = 4
    with pytest.raises(ValueError, match="label"):
        submit(case, data)


def test_segmentation_rgb_and_jpeg_rejected(evidence_case, fixture_json):
    case, _ = evidence_case
    data = segmentation(case, fixture_json)
    Image.new("RGB", (64, 48)).save(case.path("tools/labels.jpg"))
    data["assets"][0] = asset(case, "tools/labels.jpg", "raw_data")
    with pytest.raises(ValueError):
        submit(case, data)


def test_asset_hash_and_declared_map_dimensions_checked(evidence_case, fixture_json):
    case, _ = evidence_case
    data = depth(case, fixture_json)
    data["assets"][1]["width"] = 12
    with pytest.raises(ValueError, match="dimensions"):
        submit(case, data)
    data = depth(case, fixture_json)
    data["assets"][0]["sha256"] = "a" * 64
    with pytest.raises(ValueError, match="hash"):
        submit(case, data)


def test_external_bundle_copied_and_paths_rewritten(evidence_case, fixture_json, tmp_path):
    case, _ = evidence_case
    folder = tmp_path / "bundle"
    folder.mkdir()
    data = manifest(case, fixture_json)
    raw = folder / "ocr.json"
    write_json(raw, {"detections": []})
    data["assets"] = [{"path": "ocr.json", "sha256": sha256_file(raw), "kind": "json", "width": None, "height": None}]
    path = folder / "evidence.json"
    write_json(path, data)
    result = register_evidence(case, path)
    assert result.assets[0].path.startswith("tools/T1_OCR/assets/")
    assert case.path(result.assets[0].path).read_bytes() == raw.read_bytes()


def test_asset_path_traversal_rejected(evidence_case, fixture_json):
    case, _ = evidence_case
    data = manifest(case, fixture_json)
    data["assets"] = [{"path": "../secret.json", "sha256": "a" * 64, "kind": "json", "width": None, "height": None}]
    with pytest.raises(ValueError):
        submit(case, data)


def test_npy_header_size_cannot_force_large_allocation(evidence_case, fixture_json):
    case, _ = evidence_case
    data = depth(case, fixture_json)
    stream = io.BytesIO()
    np.lib.format.write_array_header_1_0(stream, {"descr": "<f4", "fortran_order": False, "shape": (100_000, 100_000)})
    case.path("tools/depth.npy").write_bytes(stream.getvalue())
    data["assets"][0] = asset(case, "tools/depth.npy", "raw_data")
    with pytest.raises(ValueError, match="pixel limit"):
        submit(case, data)


def test_tool_error_controller_blocks_with_metadata(tmp_path, photo, fixture_json):
    from hir_manual.service import Controller

    ctl = Controller(tmp_path)
    state = ctl.new(photo, "restore")
    request = ctl.current_task(state.case_id)
    diagnosis = fixture_json("diagnosis")
    diagnosis["tool_plan"] = [{"tool": "T1_OCR", "reason": "check text"}]
    assert ctl.import_json(state.case_id, request.task_id, diagnosis, "fixture").accepted
    case = CasePaths(state.case_id, tmp_path)
    data = manifest(case, fixture_json)
    data.update(status="error", error="offline OCR missing")
    upload = case.path("tools/upload.json")
    write_json(upload, data)
    state = ctl.register_evidence(case.case_id, upload)
    assert state.operation_status == "blocked"
    assert state.block_reason == "offline OCR missing"
    assert state.received_tools == []
