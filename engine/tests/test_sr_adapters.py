from pathlib import Path
import json
from types import SimpleNamespace

from PIL import Image
import pytest

from hre.models import HREError, file_sha256
from hre.sr import adapters
from hre.sr._official import guard_image


def request(tmp_path, slot="C0"):
    source = tmp_path / "input.png"
    Image.new("RGB", (256, 256), (64, 90, 128)).save(source)
    asset = {"path": str(source), "sha256": file_sha256(source), "width": 256, "height": 256, "mode": "RGB"}
    key = {"C0": "reconstruction", "C1": "reconstruction", "C2": "seesr", "C3": "qwen"}[slot]
    return {"slot": slot, "model_key": key,
            "seed": 41, "input": asset, "source": asset,
            "deployment": {"verified": "fixture", "config_sha256": adapters.digest(configuration()[key])},
            "geometry": {"lr": [256, 256], "padded_lr": [256, 256], "native_hr": [1024, 1024],
                         "target_hr": [1024, 1024], "crop": [0, 0, 1024, 1024]}}


def configuration():
    return adapters.normalise_models({
        "reconstruction": {"python": "/runtime/reconstruction/python", "repo": "/models/Real-ESRGAN",
                           "checkpoint": "/weights/RealESRNet_x4plus.pth"},
        "seesr": {"python": "/runtime/seesr/python", "repo": "/models/SeeSR", "pretrained_model_path": "/weights/sd2",
                  "seesr_model_path": "/weights/SeeSR", "ram_ft_path": "/weights/dape.pth", "bert_path": "/weights/bert"}})


def test_real_reconstruction_command_is_official_x4_not_gan(tmp_path):
    config = configuration()["reconstruction"]
    req = request(tmp_path)
    first = adapters.command(req, config, tmp_path / "native")
    second = adapters.command({**req, "slot": "C1"}, config, tmp_path / "native")
    assert first == second
    assert first[first.index("--model_name") + 1] == "RealESRNet_x4plus"
    assert first[first.index("--outscale") + 1] == "4"
    assert first[first.index("--model_path") + 1] == "/weights/RealESRNet_x4plus.pth"
    assert first[first.index("--suffix") + 1] == ""
    assert "--fp32" in first and "--face_enhance" not in first
    assert first[0] == "/runtime/reconstruction/python"


def test_seesr_command_has_independent_runtime_frozen_native_args(tmp_path):
    config = configuration()["seesr"]
    argv = adapters.command(request(tmp_path, "C2"), config, tmp_path / "native")
    assert argv[0] == "/runtime/seesr/python"
    assert argv[2] == "seesr"
    assert argv[8] == "/weights/bert"
    for flag, value in (("--upscale", "4"), ("--process_size", "512"), ("--sample_times", "1"),
                        ("--seed", "41"), ("--align_method", "adain"), ("--start_point", "lr")):
        assert argv[argv.index(flag) + 1] == value
    assert "--save_prompts" in argv


@pytest.mark.parametrize("models", [
    {"unknown": {}}, {"reconstruction": {"settings": {"tile": True}}},
    {"reconstruction": {"settings": {"outscale": 2}}}, {"seesr": {"settings": {"upscale": 2}}},
    {"seesr": {"settings": {"sample_times": 2}}}, {"qwen": {"settings": {"true_cfg_scale": float("nan")}}},
    {"qwen": {"revision": False}}, {"reconstruction": {"timeout_seconds": float("inf")}},
    {"reconstruction": {"checkpoint": "https://remote/model.pth"}},
])
def test_model_boundary_rejects_unsupported_or_nonfinite_values(models):
    with pytest.raises(HREError):
        adapters.normalise_models(models)


def test_empty_deployment_blocks_without_synthetic_success(monkeypatch):
    monkeypatch.setattr(adapters.sys, "executable", "/absent/runtime/python")
    report = adapters.inspect_deployments({})
    assert set(report) == {"reconstruction", "seesr", "qwen"}
    assert all(value["status"] == "blocked" and value["blockers"] for value in report.values())


@pytest.mark.parametrize("size,mode,color", [((1020, 1024), "RGB", (20, 30, 40)), ((1024, 1024), "RGBA", (20, 30, 40, 80))])
def test_seesr_guard_stops_wrong_native_before_upstream_resize(tmp_path, size, mode, color):
    with pytest.raises(RuntimeError, match="before official output resize"):
        guard_image(Image.new(mode, size, color), (1024, 1024), tmp_path)
    report = json.loads((tmp_path / "native_validation.json").read_text())
    assert report["status"] == "failed"
    assert report["native_size"] == list(size)
    with Image.open(tmp_path / "native_before_color.png") as native:
        assert native.size == size and native.mode == mode


def test_native_guard_preserves_valid_native_bytes(tmp_path):
    native = Image.new("RGB", (1024, 1024), (20, 30, 40))
    guard_image(native, native.size, tmp_path)
    assert json.loads((tmp_path / "native_validation.json").read_text())["status"] == "passed"
    with Image.open(tmp_path / "native_before_color.png") as saved:
        assert saved.tobytes() == native.tobytes()


def test_zero_exit_without_model_output_is_failure(tmp_path, monkeypatch):
    req = request(tmp_path)
    monkeypatch.setattr(adapters, "_inspect", lambda *args: {"status": "ready", "identity": req["deployment"], "blockers": []})
    monkeypatch.setattr(adapters.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))
    with pytest.raises(HREError) as exc:
        adapters.run_candidate(req, {"mode": "real", "models": configuration()}, tmp_path / "native")
    assert exc.value.code == "sr_native_output_missing"
    assert exc.value.observation["calls_completed"] == 0
    assert (tmp_path / "native" / "invocation.json").is_file()


def test_changed_deployment_stops_before_subprocess(tmp_path, monkeypatch):
    req = request(tmp_path)
    monkeypatch.setattr(adapters, "_inspect", lambda *args: {"status": "ready", "identity": {"changed": True}, "blockers": []})
    monkeypatch.setattr(adapters.subprocess, "run", lambda *args, **kwargs: pytest.fail("Must not submit mutated deployment"))
    with pytest.raises(HREError) as exc:
        adapters.run_candidate(req, {"mode": "real", "models": configuration()}, tmp_path / "native")
    assert exc.value.code == "sr_deployment_modified"


def test_qwen_receives_lr_conditioning_and_distinct_hr_canvas(tmp_path, monkeypatch):
    from hre.v3 import qwen
    req = request(tmp_path, "C3")
    monkeypatch.setattr(adapters, "_inspect", lambda *args: {"status": "ready", "identity": req["deployment"], "blockers": []})
    captured = {}

    def generate(native, condition, config, output):
        captured.update(native=native, condition=condition, config=config)
        return {"outputs": [], "observation": {"fixture": True}}

    monkeypatch.setattr(qwen, "generate", generate)
    adapters.run_candidate(req, {"mode": "real", "models": configuration()}, tmp_path / "native")
    assert captured["native"]["canvas"] == {"width": 1024, "height": 1024}
    assert captured["native"]["inputs"][0]["width"] == 256
    assert captured["native"]["inputs"][0]["sha256"] == req["input"]["sha256"]
    assert captured["config"] == configuration()["qwen"]
