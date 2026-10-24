"""Real adapter wiring with controlled local model/endpoint doubles, no GPUs.

These tests establish call protocols and failure evidence, not image quality or
that upstream checkpoints were executed.  The upstream API was inspected
separately; local checkout fixtures also exercise source-lock enforcement.
"""
from contextlib import nullcontext
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from PIL import Image
import pytest

from hre.models import HREError, file_sha256
from hre.v3 import common, firered, qwen


def make_request(tmp_path, profile="qwen21", reference=False):
    paths = []
    for index, role in enumerate(["source", "appearance_reference"] if reference else ["source"]):
        path = tmp_path / f"{role}.png"
        Image.new("RGBA", (64, 64), (20 + 20 * index, 40, 60, 127 + 128 * index)).save(path)
        paths.append({"role": role, "path": str(path), "sha256": file_sha256(path),
                      "width": 64, "height": 64, "mode": "RGBA"})
    return {"schema_version": "hre_model_request_v3", "request_id": "test-request",
            "profile_id": profile, "task_mode": "reference_enhance" if reference else "restoration",
            "strategy": "native", "brief": "Reduce the motion smear while keeping the lettering.",
            "intent": None, "inputs": paths, "canvas": {"width": 64, "height": 64},
            "spatial": {"mode": "full_frame"}, "seed": 43}


def editor_config(tmp_path, profile="qwen21"):
    path = tmp_path / (profile + "-weights")
    path.mkdir(exist_ok=True)
    settings = {"num_inference_steps": 40, "true_cfg_scale": 1.0 if profile == "qwen21" else 4.0,
                "negative_prompt": "" if profile == "qwen21" else " ", "num_images_per_prompt": 1}
    if profile == "qwen21":
        settings.update(output_resolution=1024, use_kv_cache=True)
    return {"model_id": qwen.MODEL_ID if profile == "qwen21" else firered.MODEL_ID,
            "local_path": str(path), "revision": "a" * 40, "device": "cpu", "torch_dtype": "bfloat16",
            "pipeline_version": "test-runtime", "settings": settings}


@pytest.fixture
def fake_models(monkeypatch):
    observed = {"loads": [], "calls": [], "pe_loads": [], "pe_calls": [],
                "raw": '<think>observe source</think>{"rewritten_prompt":"Remove motion smear; retain lettering.","ratio_follow":"<image1>","wh_ratio":""}',
                "outputs": [Image.new("RGBA", (64, 64), (80, 90, 100, 128))]}

    class Generator:
        def __init__(self, device):
            self.device = device
        def manual_seed(self, seed):
            self.seed = seed
            return self

    class Pipeline:
        vae_scale_factor = 8
        config = SimpleNamespace(sample_sigmas=None)
        @classmethod
        def from_pretrained(cls, *args, **kwargs):
            observed["loads"].append((cls.__name__, args, kwargs))
            return cls()
        def to(self, device):
            self.device = device
            return self
        def __call__(self, **kwargs):
            observed["calls"].append(kwargs)
            if observed.get("image_error"):
                raise RuntimeError("simulated device failure")
            return SimpleNamespace(images=observed["outputs"])

    class QwenImage21Pipeline(Pipeline):
        vae_scale_factor = 16
    class QwenImageEditPlusPipeline(Pipeline):
        pass

    class InputBatch(dict):
        def to(self, device):
            observed["pe_input_device"] = device
            return self
    class Tokenizer:
        eos_token_id = 7
        def decode(self, tokens, **kwargs):
            observed["decode_kwargs"] = kwargs
            return observed["raw"]
    class Processor:
        tokenizer = Tokenizer()
        def apply_chat_template(self, messages, **kwargs):
            observed["messages"] = messages
            observed["template_kwargs"] = kwargs
            return InputBatch(input_ids=SimpleNamespace(shape=(1, 10)))
        def create_mm_token_type_ids(self, ids):
            return "actual-mm-types"
    class AutoProcessor:
        @classmethod
        def from_pretrained(cls, *args, **kwargs):
            observed["pe_loads"].append(("processor", args, kwargs))
            return Processor()
    class Generated:
        def __getitem__(self, item):
            assert item == (0, slice(10, None))
            return SimpleNamespace(shape=(21,))
    class Model:
        device = "cpu"
        def to(self, device):
            self.device = device
            return self
        def eval(self):
            return self
        def generate(self, **kwargs):
            observed["pe_calls"].append(kwargs)
            if observed.get("pe_error"):
                raise RuntimeError("simulated compiler failure")
            return Generated()
    class AutoModelForImageTextToText:
        @classmethod
        def from_pretrained(cls, *args, **kwargs):
            observed["pe_loads"].append(("model", args, kwargs))
            return Model()

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        bfloat16="bf16", float16="fp16", float32="fp32", Generator=Generator,
        manual_seed=lambda seed: observed.update(pe_seed=seed), inference_mode=nullcontext))
    monkeypatch.setitem(sys.modules, "diffusers", SimpleNamespace(
        __version__="test-runtime", QwenImage21Pipeline=QwenImage21Pipeline,
        QwenImageEditPlusPipeline=QwenImageEditPlusPipeline))
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(
        AutoProcessor=AutoProcessor, AutoModelForImageTextToText=AutoModelForImageTextToText))
    # Protocol spies are not real upstream source.  Source verification itself
    # is exercised separately with a deliberate mismatch below.
    for module in (qwen, firered):
        monkeypatch.setattr(module, "verify_module", lambda module, relative: {
            "relative_path": relative, "verification": "controlled_test_double"})
    common.runtime_clear()
    yield observed
    common.runtime_clear()


PE_CORE = '''from pathlib import Path
import json
from types import SimpleNamespace
from PIL import Image
json_repair = None
def get_profile(task):
    assert task == "edit"
    return SimpleNamespace(temperature=1.0, top_p=.95, top_k=20, presence_penalty=0., max_new_tokens=24000, image_max_pixels=1048576)
def load_system_prompt(explicit, ckpt):
    return Path(explicit or Path(ckpt)/"system_prompt.txt").read_text().strip()
def load_image(path, max_pixels):
    return Image.open(path).convert("RGB")
def build_messages(system, prompt, images):
    return [{"role":"system","content":system},{"role":"user","content":[{"type":"image","image":im} for im in images]+[{"type":"text","text":prompt}]}]
def split_thinking(raw):
    if "</think>" in raw:
        thought,answer=raw.split("</think>",1)
        return thought.replace("<think>",""),answer
    return "",raw
def parse_answer(answer, profile):
    try:
        value=json.loads(answer)
        return {"positive_prompt":value["rewritten_prompt"],"wh_ratio":value.get("wh_ratio",""),"ratio_follow":value.get("ratio_follow",""),"parse_ok":True}
    except (ValueError,KeyError):
        return {"positive_prompt":answer,"wh_ratio":"","ratio_follow":"","parse_ok":False}
'''


@pytest.fixture
def upstream(tmp_path):
    root = tmp_path / "upstream"
    (root / "prompt_rewrite").mkdir(parents=True)
    (root / "agent").mkdir()
    (root / "prompt_rewrite" / "pe_core.py").write_text(PE_CORE)
    (root / "prompt_rewrite" / "run_transformers.py").write_text("# Controlled upstream reference fixture.\n")
    (root / "agent" / "__init__.py").write_text('raise RuntimeError("Must not import the Gemini ROI pipeline")\n')
    (root / "agent" / "config.py").write_text("RECAPTION_TARGET_LENGTH = 512\n")
    (root / "agent" / "recaption.py").write_text('''from agent.config import RECAPTION_TARGET_LENGTH
_SYSTEM_PROMPT = "Official instruction-only template, length {target_len}"
def build_reference_map(groups):
    return {old+1:index+1 for index,group in enumerate(groups) for old in group}
def _replace_image_refs(text,mapping):
    return text
''')
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=Adapter Test", "-c", "user.email=test@example.invalid",
                    "commit", "-qm", "fixture"], check=True)
    revision = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    return {"upstream_path": str(root), "upstream_revision": revision}


def compiler_config(tmp_path, upstream):
    path = tmp_path / "pe-weights"
    path.mkdir(exist_ok=True)
    (path / "system_prompt.txt").write_text("The deployed PE-I2I system prompt.")
    return {"backend": "qwen_pe_i2i", "model_id": qwen.PE_MODEL_ID, "local_path": str(path),
            "revision": "b" * 40, "device": "cpu", "torch_dtype": "bfloat16", "settings": {}, **upstream}


@pytest.mark.parametrize("profile,module,cls,mode", [
    ("qwen21", qwen, "QwenImage21Pipeline", "RGBA"),
    ("firered11", firered, "QwenImageEditPlusPipeline", "RGB"),
])
@pytest.mark.parametrize("reference", [False, True])
def test_editors_use_real_call_protocol_once_and_preserve_native_outputs(tmp_path, fake_models, profile, module, cls, mode, reference):
    request = make_request(tmp_path, profile, reference)
    config = editor_config(tmp_path, profile)
    fake_models["outputs"].append(Image.new("RGB", (64, 64), "red"))
    result = module.generate(request, {"text": "Accepted final instruction"}, config, tmp_path / "outputs")
    assert len(fake_models["calls"]) == len(fake_models["loads"]) == 1
    name, args, kwargs = fake_models["loads"][0]
    assert name == cls and args == (config["local_path"],)
    assert kwargs["local_files_only"] is True and kwargs["torch_dtype"] == "bf16"
    call = fake_models["calls"][0]
    assert [image.mode for image in call["image"]] == [mode] * len(request["inputs"])
    assert call["prompt"] == "Accepted final instruction" and call["generator"].seed == 43
    assert call["num_images_per_prompt"] == 1 and (call["width"], call["height"]) == (64, 64)
    if profile == "qwen21":
        assert call["image"][0].getpixel((0, 0))[3] == 127
        assert call["output_resolution"] == 1024 and call["use_kv_cache"] is True
    else:
        assert call["true_cfg_scale"] == 4 and call["negative_prompt"] == " "
        assert "use_kv_cache" not in call
    assert [item["mode"] for item in result["outputs"]] == ["RGBA", "RGB"]
    with Image.open(result["outputs"][0]["path"]) as native:
        assert native.getpixel((0, 0))[3] == 128
    assert result["observation"]["image_calls_completed"] == 1
    assert result["observation"]["actual_generation_count"] == 2
    assert result["observation"]["prompt_rewrite_during_execution"] is False


def test_qwen_requires_explicit_condition_resolution_and_cache(tmp_path, fake_models):
    config = editor_config(tmp_path)
    config["settings"].pop("output_resolution")
    with pytest.raises(HREError, match="qwen_settings_invalid"):
        qwen.generate(make_request(tmp_path), {"text": "restore"}, config, tmp_path / "outputs")
    assert fake_models["loads"] == []


@pytest.mark.parametrize("module,profile", [(qwen, "qwen21"), (firered, "firered11")])
def test_wrong_checkpoint_and_native_mask_are_rejected_before_load(tmp_path, fake_models, module, profile):
    request, config = make_request(tmp_path, profile), editor_config(tmp_path, profile)
    config["model_id"] = "another/checkpoint"
    with pytest.raises(HREError, match="model_identity_mismatch"):
        module.generate(request, {"text": "restore"}, config, tmp_path / "out")
    config = editor_config(tmp_path, profile)
    request["spatial"]["mode"] = "native_mask"
    with pytest.raises(HREError, match="native_mask_unsupported"):
        module.generate(request, {"text": "restore"}, config, tmp_path / "out")
    request["spatial"] = {"mode": "bbox", "boxes": []}
    with pytest.raises(HREError, match="spatial_unsupported"):
        module.generate(request, {"text": "restore"}, config, tmp_path / "out")
    assert fake_models["loads"] == []


@pytest.mark.parametrize("module,profile", [(qwen, "qwen21"), (firered, "firered11")])
def test_editor_failure_has_attempt_evidence_and_never_retries(tmp_path, fake_models, module, profile):
    fake_models["image_error"] = True
    with pytest.raises(HREError, match="generation_failed") as failure:
        module.generate(make_request(tmp_path, profile), {"text": "restore"}, editor_config(tmp_path, profile), tmp_path / "out")
    assert len(fake_models["calls"]) == 1
    assert failure.value.observation["image_calls_attempted"] == 1
    assert failure.value.observation["image_calls_completed"] == 0
    assert not list((tmp_path / "out").glob("native_*.png"))


@pytest.mark.parametrize("reference", [False, True])
def test_qwen_pe_invokes_local_checkpoint_preserves_raw_and_uses_official_parser(tmp_path, upstream, fake_models, reference):
    request = make_request(tmp_path, reference=reference)
    result = qwen.compile_condition(request, compiler_config(tmp_path, upstream))
    assert len(fake_models["pe_calls"]) == 1 and len(fake_models["pe_loads"]) == 2
    assert all(kwargs["local_files_only"] is True for _, _, kwargs in fake_models["pe_loads"])
    assert fake_models["template_kwargs"]["enable_thinking"] is True
    assert fake_models["pe_calls"][0]["mm_token_type_ids"] == "actual-mm-types"
    assert fake_models["pe_calls"][0]["top_k"] == 20
    assert result["text"] == "Remove motion smear; retain lettering."
    assert result["native_output"]["raw_generation"] == fake_models["raw"]
    assert result["native_output"]["positive_prompt"] == result["text"]
    assert result["native_output"]["ratio_follow"] == "<image1>"
    assert result["observation"]["input_modes"] == ["RGB"] * len(request["inputs"])
    assert result["observation"]["calls_completed"] == 1
    assert "pe_core" not in sys.modules
    assert fake_models["calls"] == []


@pytest.mark.parametrize("raw,code", [
    ("An unstructured incomplete answer", "qwen_pe_parse_failed"),
    ('{"rewritten_prompt":"edit reference","ratio_follow":"<image2>","wh_ratio":""}', "qwen_pe_canvas_mismatch"),
    ('{"rewritten_prompt":"make a wide scene","ratio_follow":"","wh_ratio":"16:9"}', "qwen_pe_canvas_mismatch"),
])
def test_qwen_pe_does_not_silently_repair_invalid_native_condition(tmp_path, upstream, fake_models, raw, code):
    fake_models["raw"] = raw
    with pytest.raises(HREError, match=code) as failure:
        qwen.compile_condition(make_request(tmp_path), compiler_config(tmp_path, upstream))
    assert failure.value.native_output["raw_generation"] == raw
    assert failure.value.observation["calls_completed"] == 1
    assert len(fake_models["pe_calls"]) == 1 and fake_models["calls"] == []


def test_modified_official_helper_is_rejected_before_loading_compiler(tmp_path, upstream, fake_models):
    path = Path(upstream["upstream_path"]) / "prompt_rewrite" / "pe_core.py"
    path.write_text(path.read_text() + "\n# changed after pinned commit\n")
    with pytest.raises(HREError, match="upstream_source_modified"):
        qwen.compile_condition(make_request(tmp_path), compiler_config(tmp_path, upstream))
    assert fake_models["pe_loads"] == [] and fake_models["pe_calls"] == []


def test_missing_pe_system_prompt_is_a_structured_error_before_load(tmp_path, upstream, fake_models):
    config = compiler_config(tmp_path, upstream)
    (Path(config["local_path"]) / "system_prompt.txt").unlink()
    with pytest.raises(HREError, match="qwen_pe_system_prompt_missing"):
        qwen.compile_condition(make_request(tmp_path), config)
    assert fake_models["pe_loads"] == [] and fake_models["pe_calls"] == []


@pytest.mark.parametrize("module,profile", [(qwen, "qwen21"), (firered, "firered11")])
def test_existing_native_output_cannot_trigger_a_second_generation(tmp_path, fake_models, module, profile):
    request, config = make_request(tmp_path, profile), editor_config(tmp_path, profile)
    output = tmp_path / "out"
    module.generate(request, {"text": "restore"}, config, output)
    with pytest.raises(HREError, match="native_output_exists"):
        module.generate(request, {"text": "restore"}, config, output)
    assert len(fake_models["calls"]) == 1


@pytest.mark.parametrize("module,profile", [(qwen, "qwen21"), (firered, "firered11")])
def test_output_path_conflict_is_rejected_before_model_load(tmp_path, fake_models, module, profile):
    request, config = make_request(tmp_path, profile), editor_config(tmp_path, profile)
    output = tmp_path / "out"
    output.write_text("existing unrelated file")
    with pytest.raises(HREError, match="native_output_exists"):
        module.generate(request, {"text": "restore"}, config, output)
    assert fake_models["loads"] == [] and fake_models["calls"] == []


@pytest.mark.parametrize("module,profile", [(qwen, "qwen21"), (firered, "firered11")])
def test_unverified_pipeline_code_is_rejected_before_model_load(tmp_path, fake_models, monkeypatch, module, profile):
    from hre.v3.native_sources import verify_module
    monkeypatch.setattr(module, "verify_module", verify_module)
    request, config = make_request(tmp_path, profile), editor_config(tmp_path, profile)
    with pytest.raises(HREError, match="native_source_mismatch"):
        module.generate(request, {"text": "restore"}, config, tmp_path / "out")
    assert fake_models["loads"] == [] and fake_models["calls"] == []


def test_firered_recaption_is_one_text_call_without_cloud_defaults_or_roi_import(tmp_path, upstream, monkeypatch):
    observed = []
    def local_chat(config, messages, response_schema=None):
        observed.append((config, messages, response_schema))
        return {"text": "<think>reasoning</think>Reduce the motion smear.", "model": "local-qwen",
                "calls_attempted": 1, "calls_completed": 1, "finish_reason": "stop", "raw_response": {"id": "local-1"}}
    monkeypatch.setattr(firered, "chat", local_chat)
    request = make_request(tmp_path, "firered11", reference=True)
    config = {"backend": "firered_recaption", **upstream,
              "endpoint": {"base_url": "http://127.0.0.1:8000/v1", "model": "local-qwen", "settings": {}}}
    result = firered.compile_condition(request, config)
    assert len(observed) == 1
    endpoint, messages, schema = observed[0]
    assert endpoint["settings"] == {"temperature": .4, "max_tokens": 4096}
    assert all(isinstance(message["content"], str) for message in messages)
    assert schema is None and result["text"] == "Reduce the motion smear."
    assert result["native_output"]["raw_text"].startswith("<think>")
    assert result["observation"]["images_supplied"] is False
    assert result["observation"]["crop_and_stitch_invoked"] is False
    assert result["observation"]["fallback_used"] is False
    assert "agent" not in sys.modules
    missing = deepcopy(config)
    missing.pop("endpoint")
    with pytest.raises(HREError, match="firered_endpoint_required"):
        firered.compile_condition(request, missing)
    assert len(observed) == 1


def test_firered_recaption_failure_preserves_attempt_without_returning_original(tmp_path, upstream, monkeypatch):
    calls = []
    def failed(*args, **kwargs):
        calls.append(1)
        raise HREError("chat_transport_unknown", "failure")
    monkeypatch.setattr(firered, "chat", failed)
    config = {"backend": "firered_recaption", **upstream,
              "endpoint": {"base_url": "http://127.0.0.1:8000/v1", "model": "local-qwen"}}
    with pytest.raises(HREError, match="chat_transport_unknown") as failure:
        firered.compile_condition(make_request(tmp_path, "firered11"), config)
    assert calls == [1]
    assert failure.value.observation["calls_attempted"] == 1
    assert failure.value.observation["calls_completed"] == 0
