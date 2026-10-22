"""Native editor contract tests use fake dependencies, never a GPU/model."""
from copy import deepcopy
from contextlib import nullcontext
import json
from pathlib import Path
import sys
from types import SimpleNamespace

from PIL import Image
import pytest

from hre.models import HREError, file_sha256, sha256_bytes
from hre.native_editor import run_native_editor, ADAPTER_VERSION


def request(tmp_path, profile="qwen21"):
    editor = tmp_path / "bundle" / "editor"
    editor.mkdir(parents=True)
    Image.new("RGB", (32, 24), (50, 60, 70)).save(editor / "A.png")
    Image.new("RGB", (18, 12), (90, 100, 110)).save(editor / "B.png")
    prompt = "Adjust A using B's tones without changing scene contents."
    (editor / "edit_prompt.txt").write_text(prompt)
    (editor / "condition.json").write_text(json.dumps({
        "profile_id": profile, "status": "ok", "edit_prompt": prompt,
        "canvas": {"source": "A", "width": 32, "height": 24}}))
    qwen = profile == "qwen21"
    settings = dict(model_id="Qwen/Qwen-Image-2.1" if qwen else "FireRedTeam/FireRed-Image-Edit-1.1",
                    revision="a" * 40, seed=42, num_inference_steps=40, true_cfg_scale=1.0 if qwen else 4.0,
                    negative_prompt="" if qwen else " ", device="cuda", torch_dtype="bfloat16")
    if qwen:
        settings.update(output_resolution=2048, use_kv_cache=True)
    executor = dict(executor_id="hre-native-diffusers", model_display_name="Qwen-Image-2.1" if qwen else "FireRed-Image-Edit 1.1",
                    model_exact_version=settings["revision"], transport="api", pipeline_version="test-diffusers",
                    adapter_version=ADAPTER_VERSION, settings=settings)
    assets = [{"role": role, "sha256": file_sha256(editor / name), "width": width, "height": height}
              for role, name, width, height in [("prediction", "A.png", 32, 24), ("reference", "B.png", 18, 12)]]
    return dict(schema_version="hre_worker_request_v1", kind="execute", executor=executor,
                bundle_path=str(editor.parent), output_dir=str(tmp_path / "outputs"),
                request={"stage": "execute", "request_sha256": "b" * 64,
                         "payload": {"edit_prompt": prompt}, "input_assets": assets})


@pytest.fixture
def fake_models(monkeypatch):
    observed = {"loads": [], "calls": [], "images": [Image.new("RGB", (32, 24), (75, 75, 75))]}
    class Generator:
        def __init__(self, device):
            self.device = device
        def manual_seed(self, value):
            self.seed = value
            return self
    class Pipeline:
        @classmethod
        def from_pretrained(cls, *args, **kwargs):
            observed["loads"].append((cls.__name__, args, kwargs))
            return cls()
        def to(self, device):
            observed["device"] = device
            return self
        def __call__(self, **kwargs):
            observed["calls"].append(kwargs)
            return SimpleNamespace(images=observed["images"])
    class QwenImage21Pipeline(Pipeline):
        pass
    class QwenImageEditPlusPipeline(Pipeline):
        pass
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        bfloat16="bf16", float16="fp16", float32="fp32", Generator=Generator, inference_mode=nullcontext))
    monkeypatch.setitem(sys.modules, "diffusers", SimpleNamespace(
        __version__="test-diffusers", QwenImage21Pipeline=QwenImage21Pipeline,
        QwenImageEditPlusPipeline=QwenImageEditPlusPipeline))
    return observed


@pytest.mark.parametrize("profile,pipeline", [("qwen21", "QwenImage21Pipeline"),
                                             ("firered11", "QwenImageEditPlusPipeline")])
def test_native_editor_uses_frozen_pipeline_and_A_canvas_once(tmp_path, fake_models, profile, pipeline):
    value = request(tmp_path, profile)
    result = run_native_editor(value)
    assert len(fake_models["loads"]) == len(fake_models["calls"]) == 1
    cls, args, kwargs = fake_models["loads"][0]
    assert cls == pipeline and args == (value["executor"]["settings"]["model_id"],)
    assert kwargs == {"revision": "a" * 40, "local_files_only": True, "torch_dtype": "bf16"}
    call = fake_models["calls"][0]
    assert [image.size for image in call["image"]] == [(32, 24), (18, 12)]
    assert (call["width"], call["height"]) == (32, 24)
    assert call["num_images_per_prompt"] == 1
    assert call["generator"].seed == 42
    metadata = result["metadata"]
    assert metadata["actual_generation_count"] == 1 and metadata["provider_order"] == 0
    receipt = metadata["executor_observation"]
    assert receipt["executor"] == value["executor"]
    assert receipt["input_sha256"] == {"A": value["request"]["input_assets"][0]["sha256"],
                                       "B": value["request"]["input_assets"][1]["sha256"]}
    assert receipt["prompt_sha256"] == sha256_bytes(call["prompt"].encode())
    assert receipt["output_sha256"] == file_sha256(Path(result["image_path"]))
    from hre.reference_execution import validate_observation_shape
    validate_observation_shape(receipt)


def test_unexpected_multiple_outputs_are_preserved_and_counted(tmp_path, fake_models):
    fake_models["images"].append(Image.new("RGB", (32, 24), "red"))
    result = run_native_editor(request(tmp_path))
    metadata = result["metadata"]
    assert len(fake_models["calls"]) == 1
    assert metadata["actual_generation_count"] == metadata["executor_observation"]["actual_generation_count"] == 2
    assert len(metadata["extras"]) == 1
    assert metadata["extras"][0]["provider_order"] == 1
    assert metadata["extras"][0]["complete"] is True
    assert Path(metadata["extras"][0]["source"]).exists()


@pytest.mark.parametrize("mutation,code", [
    (lambda e: e["settings"].pop("revision"), "native_settings_invalid"),
    (lambda e: e["settings"].update(num_images_per_prompt=2), "native_settings_invalid"),
    (lambda e: e["settings"].update(unrecognized=True), "native_settings_invalid"),
    (lambda e: e["settings"].update(model_id="FireRedTeam/FireRed-Image-Edit-1.0"), "native_model_mismatch"),
    (lambda e: e.update(pipeline_version="different"), "native_executor_mismatch"),
])
def test_unfrozen_or_incompatible_settings_fail_before_load(tmp_path, fake_models, mutation, code):
    value = request(tmp_path)
    mutation(value["executor"])
    with pytest.raises(HREError, match=code):
        run_native_editor(value)
    assert fake_models["loads"] == [] and fake_models["calls"] == []


def test_changed_input_bytes_fail_before_model_load(tmp_path, fake_models):
    value = request(tmp_path)
    Image.new("RGB", (32, 24), "black").save(Path(value["bundle_path"]) / "editor" / "A.png")
    with pytest.raises(HREError, match="native_input_mismatch"):
        run_native_editor(value)
    assert fake_models["loads"] == []


def test_model_exception_does_not_call_again_or_fabricate_result(tmp_path, fake_models):
    fake_models["images"] = []
    with pytest.raises(HREError, match="native_output_missing"):
        run_native_editor(request(tmp_path))
    assert len(fake_models["calls"]) == 1
