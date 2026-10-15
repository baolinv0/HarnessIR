"""Synthetic segmentation/venv regressions; no model quality is asserted."""
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from hir_manual.local_evidence import validate_local_evidence
from hir_manual.storage import read_json, sha256_file, write_json
from hir_manual.tool_registry import load_profile, make_contract
from local_fixtures import face_evidence, synthetic_registry
from preprocessing.adapters.common import full_view
from preprocessing.adapters.segmentation import write_segmentation


def fixture(directory, width=64, height=48):
    entry = synthetic_registry(directory)
    entry["model_name"] = "YOLOE-26n-seg"
    entry["backend"]["implementation"] = "ultralytics_yoloe_text"
    profile = load_profile()
    # The fixture remains synthetic CPU adapter data, but explicitly freezes
    # the 31-label formal taxonomy to exercise the former label-count memory
    # multiplier; no CPU model is presented as SAM3 or GPU evidence.
    large_prompt = load_profile("gpu_full_v1").tools["T4_SEGMENTATION"]["prompt_set"]
    profile.tools["T4_SEGMENTATION"]["prompt_set"] = large_prompt
    profile.tools["T4_SEGMENTATION"]["prompt_set_id"] = large_prompt["prompt_set_id"]
    contract = make_contract("a" * 64, "T4_SEGMENTATION", profile, entry)
    directory = directory / "synthetic_segmentation"
    manifest = face_evidence(directory, contract, width, height)
    labels = profile.tools["T4_SEGMENTATION"]["prompt_set"]["labels"]
    records = [{"id": "a", "prompt_index": 0, "label": labels[0], "score": .9, "bbox": [0, 0, width // 2, height], "mask": np.tile(np.arange(width) < width // 2, (height, 1))}, {"id": "b", "prompt_index": 1, "label": labels[1], "score": .8, "bbox": [width // 4, 0, width, height], "mask": np.tile(np.arange(width) >= width // 4, (height, 1))}]
    data, assets, warnings = write_segmentation(records, profile.tools["T4_SEGMENTATION"]["prompt_set"], directory, full_view(width, height), (width, height))
    manifest.update(tool_id="T4_SEGMENTATION", model_name="YOLOE-26n-seg", data=data, assets=assets, quality_warnings=warnings)
    write_json(directory / "evidence.json", manifest)
    return directory, contract, manifest


def rehash(directory, manifest, relative):
    next(a for a in manifest["assets"] if a["path"] == relative)["sha256"] = sha256_file(directory / relative)
    write_json(directory / "evidence.json", manifest)


def test_only_three_constant_full_frame_buffers_for_31_classes(tmp_path, monkeypatch):
    directory, contract, manifest = fixture(tmp_path)
    allocations = []
    real = np.zeros
    def zeros(shape, *args, **kwargs):
        result = real(shape, *args, **kwargs)
        if tuple(result.shape) == (48, 64):
            allocations.append((result.dtype, result.nbytes))
        return result
    monkeypatch.setattr("hir_manual.local_evidence.np.zeros", zeros)
    validate_local_evidence(directory, contract)
    assert len(manifest["data"]["label_names"]) == 31
    assert len(allocations) == 3
    assert [dtype for dtype, _ in allocations] == [np.dtype("uint16"), np.dtype("uint8"), np.dtype("bool")]
    assert sum(size for _, size in allocations) == 48 * 64 * 4


@pytest.mark.parametrize("width,height", [(4096, 512), (1_048_577, 1)])
def test_temporary_threshold_and_preview_checks_are_bounded_chunks(tmp_path, monkeypatch, width, height):
    directory, contract, manifest = fixture(tmp_path, width=width, height=height)
    finite_sizes, compare_sizes, isin_sizes = [], [], []
    finite, equal, isin = np.isfinite, np.array_equal, np.isin
    def tracked_finite(value, *args, **kwargs):
        finite_sizes.append(np.asarray(value).size)
        return finite(value, *args, **kwargs)
    def tracked_equal(left, right, *args, **kwargs):
        compare_sizes.extend([np.asarray(left).size, np.asarray(right).size])
        return equal(left, right, *args, **kwargs)
    def tracked_isin(value, *args, **kwargs):
        isin_sizes.append(np.asarray(value).size)
        return isin(value, *args, **kwargs)
    monkeypatch.setattr("hir_manual.local_evidence.np.isfinite", tracked_finite)
    monkeypatch.setattr("hir_manual.local_evidence.np.array_equal", tracked_equal)
    monkeypatch.setattr("hir_manual.local_evidence.np.isin", tracked_isin)
    validate_local_evidence(directory, contract)
    assert max(finite_sizes) <= 1_048_576
    assert max(isin_sizes) <= 1_048_576
    assert max(compare_sizes) <= 3 * 1_048_576  # RGB preview, not a full RGB grid.


def test_cross_class_union_cannot_swap_even_with_rehashed_native_json(tmp_path):
    directory, contract, manifest = fixture(tmp_path)
    relative = manifest["data"]["native_result_path"]
    native = read_json(directory / relative)
    native["regions"][0]["union_path"] = native["regions"][1]["union_path"]
    write_json(directory / relative, native)
    rehash(directory, manifest, relative)
    with pytest.raises(ValueError, match="Class union/instance association"):
        validate_local_evidence(directory, contract)


def test_normalized_mask_tamper_must_still_match_native_threshold(tmp_path):
    directory, contract, manifest = fixture(tmp_path)
    relative = manifest["data"]["native_masks"][0]["mask_path"]
    values = np.asarray(Image.open(directory / relative)).copy()
    values[0, 0] = 0
    Image.fromarray(values).save(directory / relative)
    rehash(directory, manifest, relative)
    with pytest.raises(ValueError, match="threshold does not reproduce"):
        validate_local_evidence(directory, contract)


def test_preview_cannot_claim_wrong_palette_colour(tmp_path):
    directory, contract, manifest = fixture(tmp_path)
    relative = manifest["data"]["preview_path"]
    values = np.asarray(Image.open(directory / relative)).copy()
    values[0, 0] = [1, 2, 3]
    Image.fromarray(values).save(directory / relative)
    rehash(directory, manifest, relative)
    with pytest.raises(ValueError, match="Preview colours/labels"):
        validate_local_evidence(directory, contract)


def test_score_priority_change_requires_different_overlap_display(tmp_path):
    directory, contract, manifest = fixture(tmp_path)
    relative = manifest["data"]["native_result_path"]
    native = read_json(directory / relative)
    manifest["data"]["native_masks"][0]["score"] = .1
    native["instances"][0]["score"] = .1
    write_json(directory / relative, native)
    rehash(directory, manifest, relative)
    with pytest.raises(ValueError, match="Display labels do not follow"):
        validate_local_evidence(directory, contract)


def test_overlap_and_unassigned_ratio_are_both_checked(tmp_path):
    directory, contract, manifest = fixture(tmp_path)
    relative = manifest["data"]["native_result_path"]
    native = read_json(directory / relative)
    overlap = native["overlap_path"]
    values = np.asarray(Image.open(directory / overlap)).copy()
    values[0, 20] = 0
    Image.fromarray(values).save(directory / overlap)
    rehash(directory, manifest, overlap)
    with pytest.raises(ValueError, match="Native overlap map"):
        validate_local_evidence(directory, contract)
    values[0, 20] = 255
    Image.fromarray(values).save(directory / overlap)
    rehash(directory, manifest, overlap)
    manifest["data"]["unassigned_ratio"] = .5
    write_json(directory / "evidence.json", manifest)
    with pytest.raises(ValueError, match="Unassigned display area"):
        validate_local_evidence(directory, contract)


def test_native_float_nan_cannot_hide_in_chunk(tmp_path):
    directory, contract, manifest = fixture(tmp_path)
    native = read_json(directory / manifest["data"]["native_result_path"])
    relative = native["instances"][0]["native_mask_path"]
    values = np.load(directory / relative, allow_pickle=False)
    values = values.astype(np.float32)
    values[-1, -1] = np.nan
    np.save(directory / relative, values, allow_pickle=False)
    rehash(directory, manifest, relative)
    with pytest.raises(ValueError, match="threshold does not reproduce"):
        validate_local_evidence(directory, contract)


def test_venv_python_path_does_not_resolve_to_base_interpreter(tmp_path, monkeypatch):
    from preprocessing import prepare_models
    environment = tmp_path / "isolated_sdk"
    executable = environment / "bin/python"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"synthetic existing venv executable; never launched")
    monkeypatch.setattr(prepare_models.sys, "platform", "linux")
    monkeypatch.setattr(Path, "resolve", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("venv interpreter must not follow its symlink")))
    monkeypatch.setattr(prepare_models.subprocess, "run", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("existing isolated environment must not be recreated")))
    result = prepare_models.isolated_python(environment, tmp_path / "base_python")
    assert result == executable.absolute()
    assert result.parent.name == "bin" and result.parent.parent.name == "isolated_sdk"
