from pathlib import Path
from PIL import Image
import pytest
from hre.assets import canonicalize_image
from hre.models import file_sha256
from hre.geometry import check_geometry


def asset(root, name, size, role="prediction"):
    source = root / (name + ".source.png")
    Image.new("RGB", size, (80, 100, 120)).save(source)
    binding = {"case_id": "case1", "case_revision": 0, "task_id": "task1", "round": 0, "generation_id": "g1", "prediction_sha256": "a" * 64, "reference_sha256": "b" * 64} if role == "candidate" else None
    return canonicalize_image(source, root / (name + ".png"), role, {"assume_srgb": True}, asset_id=name, candidate_binding=binding)


def test_strict_dimensions_and_corrupt_output(tmp_path):
    a = asset(tmp_path, "A", (20, 10))
    c = asset(tmp_path, "C", (40, 20), "candidate")
    assert check_geometry(a, c, {"mode": "strict"}, case_root=tmp_path)["status"] == "fail"
    (tmp_path / c["path"]).write_bytes(b"corrupt")
    with pytest.raises(Exception): check_geometry(a, c, {"mode": "strict"}, case_root=tmp_path)


def test_exact_scale_retains_master_and_report_has_no_content_guarantee(tmp_path):
    a = asset(tmp_path, "A", (20, 10))
    c = asset(tmp_path, "C", (40, 20), "candidate")
    source_hash = file_sha256(tmp_path / c["path"])
    gate = check_geometry(a, c, {"mode": "aspect_preserving_resize", "max_aspect_ratio_error": .005}, case_root=tmp_path)
    assert gate["status"] == "pass"
    assert gate["derived_asset"]["width"] == 20
    assert file_sha256(tmp_path / c["path"]) == source_hash
    assert gate["derived_asset"]["candidate_binding"] == c["candidate_binding"]
    assert "VLM" in (tmp_path / gate["report_path"]).read_text()


def test_near_aspect_mismatch_rejected_without_warp(tmp_path):
    a = asset(tmp_path, "A", (1000, 1000))
    c = asset(tmp_path, "C", (1001, 1000), "candidate")
    gate = check_geometry(a, c, {"mode": "aspect_preserving_resize", "max_aspect_ratio_error": .005}, case_root=tmp_path)
    assert gate["status"] == "fail"
    assert gate["derived_asset"] is None
