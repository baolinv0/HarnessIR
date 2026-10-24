"""Regression checks for post-inference source bindings and worker startup."""
from pathlib import Path

from PIL import Image
import pytest

from hre.models import HREError, file_sha256
from hre.v3 import spatial, worker


def _asset(path, role):
    with Image.open(path) as image:
        return {"role": role, "path": str(path), "sha256": file_sha256(path),
                "width": image.width, "height": image.height, "mode": image.mode}


@pytest.fixture
def bounded_edit(tmp_path):
    source, mask, native = (tmp_path / name for name in ("source.png", "mask.png", "native.png"))
    Image.new("RGB", (32, 32), "red").save(source)
    edit_mask = Image.new("L", (32, 32))
    edit_mask.paste(255, (8, 8, 24, 24))
    edit_mask.save(mask)
    Image.new("RGB", (32, 32), "blue").save(native)
    spec = {"geometry": {"policy": "pad", "grid": 32}, "alpha_policy": "require_opaque",
            "spatial": {"mode": "crop_and_fuse", "mask_path": str(mask),
                        "mask_sha256": file_sha256(mask), "context_pixels": 64, "feather_pixels": 0}}
    request = {"inputs": [_asset(source, "source")], "canvas": {"width": 32, "height": 32},
               "spatial": spec["spatial"]}
    result = {"outputs": [_asset(native, "output")], "observation": {}}
    return request, spec, result


def test_bound_crop_and_fuse_preserves_frozen_outside_pixels(tmp_path, bounded_edit):
    request, spec, result = bounded_edit
    prepared = spatial.prepare_request(request, spec, tmp_path / "round")
    delivered = spatial.deliver_outputs(result, prepared, spec, tmp_path / "delivered")
    with Image.open(delivered["deliveries"][0]["path"]) as image:
        assert image.getpixel((0, 0)) == (255, 0, 0)
        assert image.getpixel((16, 16)) == (0, 0, 255)
    assert delivered["deliveries"][0]["postprocessing"]["outside_pixels_hard_preserved"] is True


@pytest.mark.parametrize("changed", ["source", "mask", "prepared"])
def test_delivery_rejects_inputs_changed_during_inference(tmp_path, bounded_edit, changed):
    request, spec, result = bounded_edit
    prepared = spatial.prepare_request(request, spec, tmp_path / "round")
    if changed == "mask":
        Image.new("L", (32, 32), 255).save(spec["spatial"]["mask_path"])
    else:
        asset = request["inputs"][0] if changed == "source" else prepared["inputs"][0]
        Image.new("RGB", (32, 32), "green").save(asset["path"])
    with pytest.raises(HREError, match="input_modified"):
        spatial.deliver_outputs(result, prepared, spec, tmp_path / "delivered")
    assert not list((tmp_path / "delivered").glob("delivered_*.png"))
    assert file_sha256(Path(result["outputs"][0]["path"])) == result["outputs"][0]["sha256"]


def test_preparation_rejects_changed_edit_mask(tmp_path, bounded_edit):
    request, spec, _ = bounded_edit
    Image.new("L", (32, 32), 255).save(spec["spatial"]["mask_path"])
    with pytest.raises(HREError, match="input_modified"):
        spatial.prepare_request(request, spec, tmp_path / "round")


def test_delivery_rejects_changed_geometry_plan(tmp_path, bounded_edit):
    request, spec, result = bounded_edit
    prepared = spatial.prepare_request(request, spec, tmp_path / "round")
    prepared["geometry_plan"]["feather_pixels"] = 4
    with pytest.raises(HREError, match="geometry_plan_changed"):
        spatial.deliver_outputs(result, prepared, spec, tmp_path / "delivered")


@pytest.mark.parametrize("settings,code", [
    ({"timeout_seconds": 0}, "worker_timeout_invalid"),
    ({"timeout_seconds": float("inf")}, "worker_timeout_invalid"),
    ({"timeout_seconds": float("nan")}, "worker_timeout_invalid"),
    ({"cwd": "/definitely-not-an-existing-hre-worker-directory"}, "worker_cwd_invalid"),
])
def test_invalid_worker_settings_never_spawn_a_process(monkeypatch, settings, code):
    def must_not_spawn(*args, **kwargs):
        pytest.fail("Invalid configuration spawned a process before validation")
    monkeypatch.setattr(worker.subprocess, "Popen", must_not_spawn)
    with pytest.raises(HREError, match=code):
        worker.WorkerClient({"command": ["python", "-m", "hre.v3.worker", "--serve"], **settings})
