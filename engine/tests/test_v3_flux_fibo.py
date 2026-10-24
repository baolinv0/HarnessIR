"""CPU contract checks; no claim that fake pipelines test image quality/GPU code."""
from contextlib import nullcontext
from copy import deepcopy
import base64
from hashlib import sha256
import io
import json
from pathlib import Path
import sys
import threading
from types import ModuleType, SimpleNamespace

from PIL import Image
import pytest

from hre.models import HREError
from hre.v3 import fibo, flux
from hre.v3.common import digest


@pytest.fixture
def official_schema():
    path = Path(__file__).parent / "fixtures" / "v3_thales_edit_schema.json"
    return json.loads(path.read_text())


@pytest.fixture
def vgl():
    return {"short_description": "A red bicycle against a white wall.", "objects": [],
            "background_setting": "The original white wall.",
            "lighting": {"conditions": "soft daylight", "direction": "from the left", "shadows": "soft shadows"},
            "aesthetics": {"composition": "unchanged centered composition", "color_scheme": "neutral", "mood_atmosphere": "calm"},
            "photographic_characteristics": {"depth_of_field": "deep", "focus": "sharp", "camera_angle": "eye level", "lens_focal_length": "standard"},
            "style_medium": "photograph", "text_render": [], "context": "restored photograph", "artistic_style": "",
            "edit_instruction": "Remove compression artifacts while retaining the bicycle, wall and original framing."}


def asset(tmp_path, name, size=(64, 48), role="source"):
    path = tmp_path / (name + ".png")
    Image.new("RGB", size, (30, 60, 90)).save(path)
    return {"role": role, "path": str(path), "sha256": sha256(path.read_bytes()).hexdigest(),
            "width": size[0], "height": size[1], "mode": "RGB"}


def request(tmp_path, profile="fibo2_dev", reference=False):
    images = [asset(tmp_path, "source")]
    if reference:
        images.append(asset(tmp_path, "reference", (48, 64), "appearance_reference"))
    return {"schema_version": "hre_model_request_v3", "request_id": "test", "profile_id": profile,
            "task_mode": "reference_enhance" if reference else "restoration", "strategy": "native",
            "brief": "Remove compression artifacts.", "intent": None, "inputs": images,
            "canvas": {"width": 64, "height": 48}, "spatial": {"mode": "full_frame"}, "seed": 42}


def condition(schema, vgl, mask=None):
    schema = fibo._standard_schema(schema)
    return {"text": json.dumps(vgl), "condition_kind": "fibo2_thales_edit_vgl", "native_output": {
        "raw_vgl": deepcopy(vgl), "normalized_vgl": deepcopy(vgl), "validated_response_schema": schema,
        "schema_sha256": digest(schema), "mask": mask}}


def fake_torch(monkeypatch):
    module = ModuleType("torch")
    module.inference_mode = nullcontext
    class Generator:
        def __init__(self, device):
            self.device = device
        def manual_seed(self, seed):
            self.seed = seed
            return self
    module.Generator = Generator
    monkeypatch.setitem(sys.modules, "torch", module)


def test_complete_native_schema_and_unknown_fields(official_schema, vgl):
    schema = fibo._standard_schema(official_schema)
    fibo._validate_raw(vgl, schema)
    assert set(schema["required"]) == set(vgl)
    assert schema["properties"]["photographic_characteristics"]["type"] == ["object", "null"]
    incomplete = deepcopy(vgl)
    del incomplete["lighting"]["direction"]
    with pytest.raises(HREError, match="direction"):
        fibo._validate_raw(incomplete, schema)
    extra = deepcopy(vgl)
    extra["objects"] = [{"description": "bicycle", "location": "center", "relationship": "against the wall"}]
    with pytest.raises(HREError):
        fibo._validate_raw(extra, schema)
    extra = deepcopy(vgl)
    extra["exposure_ev"] = 1.0
    with pytest.raises(HREError, match="exposure_ev"):
        fibo._validate_raw(extra, schema)


@pytest.mark.parametrize("text", ['{"x":1,"x":2}', '{"x":NaN}', '```json\n{}\n```'])
def test_vgl_rejects_ambiguous_json(text):
    with pytest.raises(HREError):
        fibo._strict_json(text)


def test_fibo_reference_slots_and_target_caption(vgl):
    vgl["edit_instruction"] = "Use <image_1> as the source and <image_2> only for its tone."
    assert fibo._reference_audit(vgl, 2)["reference_slots_valid"]
    for bad in ("Use <image_1> and <image_1>.", "Use <image_1> and <image_3>."):
        vgl["edit_instruction"] = bad
        with pytest.raises(HREError):
            fibo._reference_audit(vgl, 2)
    vgl["edit_instruction"] = "Use <image_1> and <image_2>."
    vgl["short_description"] = "A photograph copied from <image_2>."
    with pytest.raises(HREError):
        fibo._reference_audit(vgl, 2)


def test_fibo_binary_mask_and_reference_exclusion(tmp_path):
    req = request(tmp_path)
    mask = Image.new("L", (64, 48), 127)
    mask.putpixel((0, 0), 128)
    path = tmp_path / "mask.png"
    mask.save(path)
    req["spatial"] = {"mode": "native_mask", "mask_path": str(path)}
    images, binary, record = fibo._inputs_and_mask(req)
    assert len(images) == 1 and binary.getpixel((0, 0)) == 255 and binary.getpixel((1, 0)) == 0
    assert record["threshold"] == 128
    req["inputs"].append(asset(tmp_path, "ref", role="appearance_reference"))
    req["task_mode"] = "reference_enhance"
    with pytest.raises(HREError, match="mutually exclusive"):
        fibo._inputs_and_mask(req)
    req["spatial"] = {"mode": "full_frame"}
    req["inputs"] *= 3
    with pytest.raises(HREError, match="1..4"):
        fibo._inputs_and_mask(req)


def test_flux_boxes_do_not_silently_clip(tmp_path):
    req = request(tmp_path, "flux3_klein")
    box = {"id": "object_a", "desc": "bicycle", "from": "ref_image_0",
           "src_bbox": [0.1, 0.2, 0.5, 0.6], "tgt_bbox": [0.1, 0.2, 0.5, 0.6]}
    req["spatial"] = {"mode": "bbox", "boxes": [box]}
    assert flux._boxes(req) == [box]
    box["src_bbox"][0] = -0.1
    with pytest.raises(HREError):
        flux._boxes(req)
    box["src_bbox"][0] = 0.1
    box["from"] = "ref_image_1"
    with pytest.raises(HREError):
        flux._boxes(req)


def test_flux_external_compile_one_plain_text_call(tmp_path, monkeypatch):
    req = request(tmp_path, "flux3_klein", reference=True)
    helpers = SimpleNamespace(prepare_references=lambda images: [image.resize((32, 32)) for image in images],
                              SYSTEM_PROMPTS={"i2i": "native edit system"},
                              I2I_SCAFFOLD={False: "Edit instruction: {instruction}"})
    monkeypatch.setattr(flux, "_pup_helpers", lambda: helpers)
    monkeypatch.setattr(flux, "_code_identity", lambda _: {"verified": True})
    calls = []
    def chat(endpoint, messages, response_schema=None):
        calls.append((endpoint, messages, response_schema))
        return {"text": "Fix artifacts in the first image, keeping its composition.", "raw_response": {"response": "raw"},
                "calls_attempted": 1, "calls_completed": 1, "finish_reason": "stop"}
    monkeypatch.setattr(flux, "chat", chat)
    compiled = flux.compile_condition(req, {"backend": "flux3_external_vlm_local", "endpoint": {"model": "local-vlm"}})
    assert len(calls) == 1 and calls[0][2] is None
    assert len(calls[0][1][1]["content"]) == 3
    assert "appearance reference" in calls[0][1][1]["content"][-1]["text"]
    assert compiled["native_output"]["raw_text"] == compiled["text"]
    assert compiled["observation"]["raw_response"] == {"response": "raw"}
    assert compiled["observation"]["pup_calls"] == 0


def test_flux_exec_no_pup_one_call_all_outputs(tmp_path, monkeypatch):
    fake_torch(monkeypatch)
    req = request(tmp_path, "flux3_klein", reference=True)
    calls = []
    class Pipe:
        blocks = SimpleNamespace(sub_blocks={"denoise": SimpleNamespace(sub_blocks={})})
        image_processor = SimpleNamespace(preprocess=lambda *args, **kw: (SimpleNamespace(shape=(1, 3, 48, 64)), {"reference_crop": None}))
        def __call__(self, **kwargs):
            calls.append(kwargs)
            self.image_processor.preprocess(kwargs["image"][0], resize_mode="fill")
            return [Image.new("RGB", (64, 48)), Image.new("RGB", (64, 48))]
    pipe = Pipe()
    monkeypatch.setattr(flux, "model_identity", lambda *_: {"verified": True})
    monkeypatch.setattr(flux, "runtime_get", lambda *_: {"pipe": pipe, "lock": threading.RLock(), "blocks": ["denoise"], "sources": {}})
    cfg = {"device": "cpu", "settings": {"geometry_policy": "explicit_canvas"}}
    cond = {"text": "Frozen instruction.", "condition_kind": "flux3_i2i_instruction",
            "native_output": {"conditioning_request_sha256": flux._conditioning_identity(req)}}
    result = flux.generate(req, cond, cfg, tmp_path / "outputs")
    assert len(calls) == 1 and calls[0]["prompt"] == cond["text"]
    assert "boxes" not in calls[0] and "guidance_scale" not in calls[0] and "negative_prompt" not in calls[0]
    assert calls[0]["width"] == 64 and calls[0]["height"] == 48
    assert [image.size for image in calls[0]["image"]] == [(64, 48), (48, 64)]
    assert len(result["outputs"]) == result["observation"]["actual_generation_count"] == 2
    assert result["observation"]["pup_calls"] == 0
    pipe.blocks.sub_blocks["prompt_upsampler"] = SimpleNamespace(sub_blocks={})
    with pytest.raises(HREError, match="PUP"):
        flux.generate(req, cond, cfg, tmp_path / "unexpected-pup")
    assert len(calls) == 1


def test_fibo_exec_native_mask_one_call(tmp_path, monkeypatch, official_schema, vgl):
    fake_torch(monkeypatch)
    req = request(tmp_path)
    maskpath = tmp_path / "mask.png"
    Image.new("L", (64, 48), 255).save(maskpath)
    req["spatial"] = {"mode": "native_mask", "mask_path": str(maskpath)}
    _, _, mask_record = fibo._inputs_and_mask(req)
    compiled = condition(official_schema, vgl, mask_record)
    compiled["native_output"]["conditioning_request_sha256"] = fibo._conditioning_identity(req)
    # A resample reuses the frozen condition with new round paths and seed.
    copied_mask = tmp_path / "resample-mask.png"
    copied_mask.write_bytes(maskpath.read_bytes())
    req["spatial"]["mask_path"] = str(copied_mask)
    req["seed"] = 43
    assert compiled["native_output"]["conditioning_request_sha256"] == fibo._conditioning_identity(req)
    calls = []
    class Pipe:
        image_processor = SimpleNamespace(preprocess=lambda images, **kw: ([SimpleNamespace(shape=(1, 3, 48, 64))], images))
        def __call__(self, **kwargs):
            calls.append(kwargs)
            self.image_processor.preprocess(kwargs["image"], height=kwargs["height"], width=kwargs["width"], mask=kwargs.get("mask"))
            return SimpleNamespace(images=[Image.new("RGB", (64, 48))])
    monkeypatch.setattr(fibo, "model_identity", lambda *_: {"verified": True})
    monkeypatch.setattr(fibo, "runtime_get", lambda *_: {"pipe": Pipe(), "lock": threading.RLock(), "sources": {}})
    result = fibo.generate(req, compiled, {"device": "cpu", "settings": {}}, tmp_path / "output")
    assert len(calls) == 1 and calls[0]["mask"].mode == "L"
    assert calls[0]["generator"].seed == 43
    assert calls[0]["negative_prompt"] == fibo.DEFAULT_NEGATIVE_PROMPT
    assert calls[0]["num_inference_steps"] == 50 and calls[0]["guidance_scale"] == 5.0
    assert "true_cfg_scale" not in calls[0] and "strength" not in calls[0]
    assert result["observation"]["native_preprocess"][0]["masked"] is True
    assert result["observation"]["native_mask_is_output_pixel_lock"] is False
    assert len(result["outputs"]) == 1


def test_fibo_compile_native_payload_transport_and_failed_response_receipt(tmp_path, monkeypatch, official_schema, vgl):
    """Exercise transport/accounting with a payload double; native schema is real."""
    req = request(tmp_path, reference=True)
    vgl["edit_instruction"] = "Preserve <image_1> content and use <image_2> only for the requested tone."
    payloads = []
    class EditImages:
        def __init__(self, **values):
            self.__dict__.update(values)
            payloads.append(self)
        def to_request(self):
            return SimpleNamespace(prompts=tmp_path / "native_prompt", context={"user_prompt": self.prompt},
                response_schema=official_schema, images=self.images, temperature=.2, max_output_tokens=7000,
                system_prompt=None, final_prompt=None)
        def parse(self, text):
            return SimpleNamespace(model_dump=lambda **kwargs: json.loads(text))
    class EditImageWithMask(EditImages):
        def __init__(self, **values):
            super().__init__(**values)
            self.images = [Image.composite(Image.new("RGB", self.image.size, (128, 128, 128)), self.image, self.mask)]
    modules = {}
    for name in ("bria_vgl", "bria_vgl.dialects", "bria_vgl.dialects.thales", "bria_vgl.dialects.thales.model",
                 "bria_vgl.dialects.thales.payloads", "bria_vgl.prompting", "bria_vgl.utils", "bria_vgl.utils.images"):
        module = ModuleType(name)
        module.__path__ = []
        modules[name] = module
        monkeypatch.setitem(sys.modules, name, module)
    modules["bria_vgl.dialects.thales.model"].ThalesVGL = object
    modules["bria_vgl.dialects.thales.payloads"].EditImages = EditImages
    modules["bria_vgl.dialects.thales.payloads"].EditImageWithMask = EditImageWithMask
    modules["bria_vgl.prompting"].render_prompts = lambda directory, context, *args: ("official native system", context["user_prompt"])
    def encode(image):
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG")
        return base64.b64encode(buffer.getvalue()).decode("ascii")
    modules["bria_vgl.utils.images"].to_base64_jpeg = encode
    monkeypatch.setattr(fibo, "verified_checkout", lambda *_: (tmp_path, {"upstream_revision": fibo.INSPECTED_VGL_COMMIT}))
    monkeypatch.setattr(fibo, "import_context", lambda *args, **kwargs: nullcontext())
    calls = []
    response = {"text": json.dumps(vgl), "raw_response": {"response_id": "fixture-response"},
                "calls_attempted": 1, "calls_completed": 1, "finish_reason": "stop"}
    def chat(endpoint, messages, response_schema=None):
        calls.append((endpoint, messages, response_schema))
        return deepcopy(response)
    monkeypatch.setattr(fibo, "chat", chat)
    cfg = {"backend": "fibo2_thales_local_openai", "upstream_revision": fibo.INSPECTED_VGL_COMMIT,
           "endpoint": {"base_url": "http://127.0.0.1:8000/v1", "model": "local-vlm"}, "settings": {}}
    compiled = fibo.compile_condition(req, cfg)
    assert len(calls) == 1 and len(payloads) == 1 and isinstance(payloads[0], EditImages)
    assert len(calls[0][1][1]["content"]) == 3
    assert calls[0][0]["settings"]["max_tokens"] == 7000
    assert calls[0][2] == fibo._standard_schema(official_schema)
    assert compiled["native_output"]["schema_added_to_transport_prompt"] is True
    assert compiled["native_output"]["consistency_audit"]["reference_slots_valid"]
    assert compiled["observation"]["official_gateway_calls"] == 0
    assert compiled["observation"]["raw_response"] == response["raw_response"]
    response["text"] = '{"short_description":"incomplete"}'
    with pytest.raises(HREError) as failure:
        fibo.compile_condition(req, cfg)
    assert len(calls) == 2  # One submitted call for each invocation, no repair attempt.
    assert failure.value.observation["calls_completed"] == 1
    assert failure.value.native_output["raw_text"] == response["text"]


def test_local_preflight_failure_has_no_compiler_call(tmp_path):
    req = request(tmp_path)
    with pytest.raises(HREError) as error:
        fibo.compile_condition(req, {"backend": "fibo2_thales_local_openai", "upstream_revision": "wrong"})
    assert error.value.observation["calls_attempted"] == error.value.observation["calls_completed"] == 0
