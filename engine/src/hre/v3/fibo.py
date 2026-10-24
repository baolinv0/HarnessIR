"""FIBO 2.0 Dev editing with native Thales payloads and an explicit local VLM.

The official VGL package supplies prompts, payload validation and normalization;
the transport is HarnessIR's single-call OpenAI-compatible client.  No official
gateway call, provider fallback, implicit caption call or text-to-image fallback
is made.  Local source checkouts and local weights are deployment prerequisites.
"""
from __future__ import annotations

import base64
from collections import Counter
from copy import deepcopy
from hashlib import sha256
import io
import json
import math
import os
from pathlib import Path
import re
import threading

from PIL import Image

from ..models import HREError, file_sha256
from .common import (chat, digest, load_images, model_identity, package_versions,
                     require, render_instruction, runtime_get, save_outputs)
from .official_checkout import import_context, verified_checkout
from .native_sources import verify_module


MODEL_ID = "briaai/Fibo-2.0-dev"
ADAPTER_VERSION = "hre.v3.fibo.1"
INSPECTED_VGL_COMMIT = "8211c2cdbc4c1a2bd78b51e40ffbc8e6c751f6f8"
INSPECTED_DIFFUSERS_COMMIT = "aaf57d03a3edfbd9de457d2872417a92f149a91d"
DEFAULT_NEGATIVE_PROMPT = (
    '{"short_description":"","objects":[],"background_setting":"","lighting":{},'
    '"aesthetics":{},"photographic_characteristics":{},"style_medium":"",'
    '"context":"","artistic_style":""}'
)


def _conditioning_identity(request):
    from .dispatch import request_binding
    return request_binding(request)


def _pixel_identity(image):
    value = sha256(f"{image.mode}:{image.width}:{image.height}:".encode() + image.tobytes()).hexdigest()
    return {"width": image.width, "height": image.height, "mode": image.mode, "pixel_sha256": value}


def _standard_schema(node):
    """Translate the official Gemini dialect without weakening its required fields."""
    if isinstance(node, list):
        return [_standard_schema(item) for item in node]
    if not isinstance(node, dict):
        return node
    result = {}
    for key, value in node.items():
        if key == "nullable":
            continue
        if key == "type" and isinstance(value, str):
            result[key] = value.lower()
        elif key == "properties":
            result[key] = {name: _standard_schema(schema) for name, schema in value.items()}
        else:
            result[key] = _standard_schema(value)
    if node.get("nullable") and isinstance(result.get("type"), str):
        result["type"] = [result["type"], "null"]
    if "properties" in result:
        result["additionalProperties"] = False
    return result


def _strict_json(text):
    def no_constant(value):
        raise ValueError(f"Non-finite JSON value: {value}")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        return json.loads(text, parse_constant=no_constant, object_pairs_hook=unique_object)
    except (ValueError, TypeError) as exc:
        raise HREError("fibo_vgl_invalid", "VGL must be one strict JSON object; no repairs or retries are applied") from exc


def _validate_raw(raw, schema):
    from jsonschema import Draft202012Validator
    Draft202012Validator.check_schema(schema)
    errors = sorted(Draft202012Validator(schema).iter_errors(raw), key=lambda error: str(list(error.path)))
    if errors:
        first = errors[0]
        path = "/" + "/".join(map(str, first.path))
        raise HREError("fibo_vgl_schema", f"Native VGL schema rejected {path}: {first.message}")
    require(isinstance(raw.get("edit_instruction"), str) and raw["edit_instruction"].strip(),
            "fibo_vgl_instruction", "Image editing requires a nonempty edit_instruction")


def _reference_audit(vgl, count):
    instruction = vgl["edit_instruction"]
    references = Counter(re.findall(r"<image_(\d+)>", instruction))
    require(all(str(int(slot)) == slot and 1 <= int(slot) <= count for slot in references),
            "fibo_reference_invalid", "edit_instruction references an image slot that is not attached")
    if count > 1:
        require(references == Counter({str(slot): 1 for slot in range(1, count + 1)}),
                "fibo_reference_invalid", "The native multi-image instruction must mention every <image_N> exactly once")
    caption = {key: value for key, value in vgl.items() if key != "edit_instruction"}
    require(not re.search(r"<image_\d+>", json.dumps(caption, ensure_ascii=False)),
            "fibo_caption_reference", "The target scene caption must describe the result without source image tokens")
    return {"input_count": count, "instruction_image_references": dict(references),
            "caption_has_source_tokens": False, "reference_slots_valid": True}


def _changed_paths(before, after, path=""):
    """A reviewable snapshot diff, not an assertion of semantic equivalence."""
    if isinstance(before, dict) and isinstance(after, dict):
        changed = []
        for key in sorted(set(before) | set(after)):
            child = path + "/" + key.replace("~", "~0").replace("/", "~1")
            if key not in before or key not in after:
                changed.append(child)
            else:
                changed.extend(_changed_paths(before[key], after[key], child))
        return changed
    if before == after:
        return []
    return [path or "/"]


def _inputs_and_mask(request):
    images = load_images(request, mode="RGB")
    require(1 <= len(images) <= 4, "fibo_inputs_invalid",
            "The native Thales compiler accepts 1..4 inputs; the image pipeline's 5-input ceiling is not this adapter's contract")
    spatial = request.get("spatial", {"mode": "full_frame"})
    require(spatial.get("mode") in {"full_frame", "native_mask"}, "fibo_spatial_unsupported",
            "Use full_frame or a single-image native_mask for this adapter")
    if spatial["mode"] != "native_mask":
        return images, None, None
    require(len(images) == 1 and request.get("task_mode") == "restoration", "fibo_mask_reference_conflict",
            "Native mask and multiple reference images are mutually exclusive")
    path = Path(spatial.get("mask_path", ""))
    require(path.is_absolute() and path.is_file(), "fibo_mask_missing", "Supply a local source-sized mask")
    original_hash = file_sha256(path)
    if spatial.get("mask_sha256"):
        require(original_hash == spatial["mask_sha256"], "fibo_mask_modified", "Frozen mask bytes changed")
    with Image.open(path) as mask_image:
        mask_image.load()
        require(mask_image.size == images[0].size, "fibo_mask_size", "Native mask must match the first input exactly")
        mask = mask_image.convert("L").point(lambda value: 255 if value >= 128 else 0)
    require(mask.getbbox() is not None, "fibo_mask_empty", "Native mask has no editable pixels")
    return images, mask, {"path": str(path), "sha256": original_hash,
                          "binary_mask": _pixel_identity(mask), "threshold": 128,
                          "meaning": "white=regenerate; grey-before-encoding; no output pixel composite"}


def _compile_condition(request: dict, config: dict, call_state: dict) -> dict:
    """Use the pinned official edit payload and exactly one configured VLM call."""
    require(request.get("profile_id") == "fibo2_dev", "fibo_profile_invalid", "Expected fibo2_dev")
    require(config.get("backend") == "fibo2_thales_local_openai", "fibo_compiler_invalid",
            "Select fibo2_thales_local_openai explicitly")
    require(config.get("upstream_revision", "").lower() == INSPECTED_VGL_COMMIT,
            "fibo_vgl_version", "This adapter implements the inspected Thales checkout; audit upgrades separately")
    endpoint = deepcopy(config.get("endpoint"))
    require(isinstance(endpoint, dict), "fibo_compiler_endpoint", "An explicit local OpenAI-compatible VLM endpoint is required")
    settings = config.get("settings", {})
    require(isinstance(settings, dict) and not set(settings) - {"source_vgl"},
            "fibo_compiler_settings", "Only an optional source_vgl snapshot is accepted by the Thales compiler")
    images, mask, mask_record = _inputs_and_mask(request)
    root, provenance = verified_checkout(config, ("src/bria_vgl",))
    # bria_vgl's public package imports LiteLLM even when only payloads are used.
    # Its documented switch prevents an incidental remote cost-map fetch at import.
    # The actual model request below never enters LiteLLM or the VGL gateway.
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    with import_context(root, ("bria_vgl",), search_paths=("src",)):
        from bria_vgl.dialects.thales.model import ThalesVGL
        from bria_vgl.dialects.thales.payloads import EditImages, EditImageWithMask
        from bria_vgl.prompting import render_prompts
        from bria_vgl.utils.images import to_base64_jpeg

        source_vgl = None
        source_snapshot = None
        if settings.get("source_vgl") is not None:
            source = settings["source_vgl"]
            require(isinstance(source, dict), "fibo_source_vgl", "source_vgl must be a structured snapshot")
            # Reject extra fields before the native model could silently drop them.
            schema = ThalesVGL.model_json_schema()
            def forbid_extra(node):
                if isinstance(node, dict):
                    if "properties" in node:
                        node["additionalProperties"] = False
                    for value in node.values():
                        forbid_extra(value)
                elif isinstance(node, list):
                    for value in node:
                        forbid_extra(value)
            forbid_extra(schema)
            from jsonschema import Draft202012Validator
            errors = list(Draft202012Validator(schema).iter_errors(source))
            require(not errors, "fibo_source_vgl", "source_vgl does not satisfy the native Thales scene schema")
            source_vgl = ThalesVGL.model_validate(source)
            source_snapshot = source_vgl.model_dump(exclude_none=True)
        instruction = render_instruction(request)
        if mask is None:
            payload = EditImages(prompt=instruction, images=images, input_image_vgl=source_vgl)
        else:
            payload = EditImageWithMask(prompt=instruction, image=images[0], mask=mask, input_image_vgl=source_vgl)
        native_request = payload.to_request()
        system, user = render_prompts(native_request.prompts, native_request.context, None,
                                      native_request.system_prompt, native_request.final_prompt)
        schema = _standard_schema(native_request.response_schema)
        official_user = user
        schema_in_prompt = endpoint.get("response_format", "json_object") != "json_schema"
        if schema_in_prompt:
            # JSON-object-only transports lack the original gateway's schema
            # constraint. Deliver the same complete schema as explicit context.
            user += ("\n\nReturn one JSON object satisfying every required field of this response schema. "
                     "Use null only where the schema permits it; do not omit required inapplicable fields.\n" +
                     json.dumps(schema, ensure_ascii=False, separators=(",", ":")))
        image_parts, sent_images = [], []
        for image in native_request.images:
            encoded = to_base64_jpeg(image)
            transmitted = base64.b64decode(encoded, validate=True)
            with Image.open(io.BytesIO(transmitted)) as jpeg:
                sent_images.append({"width": jpeg.width, "height": jpeg.height, "mode": jpeg.mode,
                                    "encoded_sha256": sha256(transmitted).hexdigest(), "encoding": "JPEG"})
            image_parts.append({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + encoded}})
        # The original Request's generation defaults are explicit and reviewable;
        # caller-supplied endpoint values override them without a provider switch.
        chat_settings = {"temperature": native_request.temperature, "top_p": 1.0, "seed": request["seed"],
                         **endpoint.get("settings", {})}
        if "max_tokens" not in chat_settings and "max_completion_tokens" not in chat_settings:
            chat_settings["max_tokens"] = native_request.max_output_tokens
        endpoint["settings"] = chat_settings
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": [{"type": "text", "text": user}, *image_parts]}]
        call_state.update(calls_attempted=1)
        observed = chat(endpoint, messages, response_schema=schema)
        call_state.update(observed)
        try:
            require(observed.get("finish_reason") != "length", "fibo_vgl_truncated",
                    "VLM exhausted its output limit; no prompt repair or retry is automatic")
            raw = _strict_json(observed["text"])
            _validate_raw(raw, schema)
            reference_audit = _reference_audit(raw, len(images))
            try:
                scene = payload.parse(observed["text"])
            except Exception as exc:
                raise HREError("fibo_vgl_native_parse", "The official Thales parser rejected the complete VGL response") from exc
            normalized = scene.model_dump(exclude_none=True)
            require(isinstance(normalized.get("edit_instruction"), str) and normalized["edit_instruction"].strip(),
                    "fibo_vgl_instruction", "The native normalization removed the edit instruction")
            final = json.dumps(normalized, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        except Exception as exc:
            exc.observation = {**observed, "compiler_id": config["backend"], "adapter_version": ADAPTER_VERSION,
                               "upstream_code": provenance, "caption_calls": 0, "official_gateway_calls": 0}
            exc.native_output = {"raw_text": observed["text"], "system_prompt": system, "user_prompt": user,
                                 "official_response_schema": native_request.response_schema,
                                 "validated_response_schema": schema, "mask": mask_record}
            raise
        prompt_directory = str(native_request.prompts.relative_to(root))
    audit = {**reference_audit, "complete_schema_valid": True, "native_parser_valid": True,
             "normalization_changed_paths": _changed_paths(raw, normalized),
             "source_snapshot_changed_paths": _changed_paths(source_snapshot, normalized) if source_snapshot else None,
             "edit_instruction": normalized["edit_instruction"],
             "target_scene": {key: value for key, value in normalized.items() if key != "edit_instruction"},
             "requested_instruction": instruction, "frozen_intent": deepcopy(request.get("intent")),
             "semantic_consistency": "requires visual/semantic review; structural validation is not a semantic proof"}
    warnings = ["Compiler uses the configured local VLM with official Thales prompts/schema; it is not the official default Gemini backend.",
                "The scene caption and edit_instruction require semantic review; both are saved in consistency_audit."]
    if mask is not None:
        warnings.append("FIBO native mask greys out the editable area before encoding; it does not lock output pixels outside the mask.")
    return {"text": final, "condition_kind": "fibo2_thales_edit_vgl",
            "native_output": {"raw_text": observed["text"], "raw_vgl": raw, "normalized_vgl": normalized,
                              "conditioning_request_sha256": _conditioning_identity(request),
                              "source_vgl": source_snapshot, "source_vgl_sha256": digest(source_snapshot) if source_snapshot else None,
                              "system_prompt": system, "user_prompt": user, "prompt_directory": prompt_directory,
                              "official_user_prompt": official_user, "schema_added_to_transport_prompt": schema_in_prompt,
                              "official_response_schema": native_request.response_schema,
                              "validated_response_schema": schema, "schema_sha256": digest(schema),
                              "transmitted_images": sent_images, "mask": mask_record, "consistency_audit": audit},
            "observation": {**observed, "compiler_id": config["backend"], "adapter_version": ADAPTER_VERSION,
                            "upstream_code": provenance, "packages": package_versions(),
                            "payload_class": type(payload).__name__, "caption_calls": 0,
                            "official_gateway_calls": 0, "fallback": None,
                            "decoding": chat_settings, "compiler_input_limit": 4, "pipeline_input_limit": 5},
            "warnings": warnings}


def compile_condition(request: dict, config: dict) -> dict:
    """Record whether a failed compilation actually submitted its one VLM call."""
    state = {"compiler_id": config.get("backend"), "calls_attempted": 0, "calls_completed": 0}
    try:
        return _compile_condition(request, config, state)
    except Exception as exc:
        if not isinstance(getattr(exc, "observation", None), dict):
            exc.observation = deepcopy(state)
        if getattr(exc, "native_output", None) is None and state.get("text"):
            exc.native_output = {"raw_text": state["text"]}
        raise


def _load_editor(config):
    import diffusers
    import torch
    from diffusers import BriaFibo2Pipeline
    from diffusers.pipelines.bria_fibo2 import pipeline_bria_fibo2, image_processor
    require(diffusers.__version__ == config["pipeline_version"], "fibo_pipeline_version",
            "Installed Diffusers version differs from the frozen editor config")
    require(pipeline_bria_fibo2.DEFAULT_NEGATIVE_PROMPT == DEFAULT_NEGATIVE_PROMPT, "fibo_pipeline_incompatible",
            "Installed FIBO pipeline differs from the inspected native CFG protocol")
    sources = {name: verify_module(module, relative) for name, module, relative in (
        ("pipeline", pipeline_bria_fibo2, "pipelines/bria_fibo2/pipeline_bria_fibo2.py"),
        ("image_processor", image_processor, "pipelines/bria_fibo2/image_processor.py"))}
    pipe = BriaFibo2Pipeline.from_pretrained(config["local_path"], torch_dtype=getattr(torch, config["torch_dtype"]),
                                           local_files_only=True).to(config["device"])
    require(getattr(pipe, "max_num_images", None) == 5, "fibo_pipeline_incompatible", "Unexpected FIBO input protocol")
    return {"pipe": pipe, "lock": threading.RLock(), "sources": sources}


def generate(request: dict, condition: dict, config: dict, output_dir: Path) -> dict:
    """Run one native edit call, preserving every output and its actual geometry."""
    require(request.get("profile_id") == "fibo2_dev", "fibo_profile_invalid", "Expected fibo2_dev")
    require(condition.get("condition_kind") == "fibo2_thales_edit_vgl", "fibo_condition_invalid",
            "A completed native Thales edit condition is required")
    output_dir = Path(output_dir).resolve()
    require(not output_dir.exists() or output_dir.is_dir(), "native_output_exists", "Output destination must be a directory")
    output_dir.mkdir(parents=True, exist_ok=True)
    require(not list(output_dir.glob("native_*.png")), "native_output_exists", "Use a fresh native output directory before generation")
    native = condition.get("native_output", {})
    require(native.get("conditioning_request_sha256") == _conditioning_identity(request),
            "fibo_condition_request_mismatch", "Source, canvas, mask or edit intent changed after compilation")
    schema = native.get("validated_response_schema")
    require(isinstance(schema, dict) and digest(schema) == native.get("schema_sha256"), "fibo_condition_invalid",
            "The frozen native schema is missing or changed")
    raw = native.get("raw_vgl")
    _validate_raw(raw, schema)
    normalized = _strict_json(condition["text"])
    require(normalized == native.get("normalized_vgl"), "fibo_condition_invalid", "Compiled native text and VGL differ")
    identity = model_identity(config, MODEL_ID)
    images, mask, mask_record = _inputs_and_mask(request)
    _reference_audit(normalized, len(images))
    def mask_identity(value):
        return {key: item for key, item in value.items() if key != "path"} if value else None
    require(mask_identity(mask_record) == mask_identity(native.get("mask")),
            "fibo_condition_mask_mismatch", "Compiler and editor mask differ")
    settings = config.get("settings", {})
    require(isinstance(settings, dict) and not set(settings) - {
        "num_inference_steps", "guidance_scale", "num_images_per_prompt", "negative_prompt", "fonts", "render_text_images"},
        "fibo_editor_settings", "Unknown FIBO setting; true_cfg_scale and img2img strength are not native parameters")
    steps, guidance = settings.get("num_inference_steps", 50), settings.get("guidance_scale", 5.0)
    require(type(steps) is int and steps > 0, "fibo_editor_settings", "num_inference_steps must be positive")
    require(type(guidance) in (int, float) and math.isfinite(guidance) and guidance >= 0,
            "fibo_editor_settings", "guidance_scale must be a finite nonnegative number")
    require(settings.get("num_images_per_prompt", 1) == 1, "fibo_editor_settings", "Request exactly one native output")
    negative = settings.get("negative_prompt", DEFAULT_NEGATIVE_PROMPT)
    require(isinstance(negative, str), "fibo_editor_settings", "negative_prompt must be text")
    render_text = settings.get("render_text_images", True)
    require(type(render_text) is bool, "fibo_editor_settings", "render_text_images must be boolean")
    fonts = settings.get("fonts", [])
    require(isinstance(fonts, list) and all(isinstance(path, str) for path in fonts),
            "fibo_fonts_invalid", "fonts must be a list of local font paths")
    font_records = []
    for name in fonts:
        path = Path(name)
        require(path.is_absolute() and path.is_file(), "fibo_fonts_missing", "Deploy every configured font locally")
        font_records.append({"path": str(path), "sha256": file_sha256(path)})
    width, height = request["canvas"]["width"], request["canvas"]["height"]
    require(type(width) is int and type(height) is int and min(width, height) > 0 and width % 16 == 0 and height % 16 == 0,
            "fibo_canvas_unsupported", "Explicit FIBO canvas must use positive multiples of 16")
    runtime = runtime_get({"adapter": ADAPTER_VERSION, "kind": "editor", "config": config,
                           "identity": identity}, lambda: _load_editor(config))
    import torch
    kwargs = {"prompt": condition["text"], "image": images, "height": height, "width": width,
              "num_inference_steps": steps, "guidance_scale": guidance, "negative_prompt": negative,
              "num_images_per_prompt": 1, "render_text_images": render_text, "fonts": fonts,
              "generator": torch.Generator(device=config["device"]).manual_seed(request["seed"]),
              "output_type": "pil", "return_dict": True}
    if mask is not None:
        kwargs["mask"] = mask
    pipe, trace = runtime["pipe"], []
    with runtime["lock"]:
        original_preprocess = pipe.image_processor.preprocess

        def observe_preprocess(*args, **kw):
            result = original_preprocess(*args, **kw)
            tensors, encoder_images = result
            trace.append({"vae_tensor_shapes": [list(tensor.shape) for tensor in tensors],
                          "text_encoder_images": [_pixel_identity(image) for image in encoder_images],
                          "requested_width": kw.get("width"), "requested_height": kw.get("height"),
                          "area": kw.get("area"), "text_encoder_image_size": kw.get("text_encoder_image_size"),
                          "masked": kw.get("mask") is not None})
            return result

        pipe.image_processor.preprocess = observe_preprocess
        try:
            with torch.inference_mode():
                result = pipe(**kwargs)
        finally:
            pipe.image_processor.preprocess = original_preprocess
    outputs = result.images
    observation = {"adapter_version": ADAPTER_VERSION, "model_identity": identity,
                   "image_calls_attempted": 1, "image_calls_completed": 1,
                   "packages": package_versions(), "upstream_code": runtime["sources"],
                   "inspected_diffusers_commit": INSPECTED_DIFFUSERS_COMMIT,
                   "input_geometry": [_pixel_identity(image) for image in images], "native_preprocess": trace,
                   "geometry_policy": "explicit_canvas; native single-image crop or per-reference training aspect size",
                   "mask": mask_record, "native_mask_is_output_pixel_lock": False,
                   "num_inference_steps": steps, "guidance_scale": guidance, "negative_prompt": negative,
                   "render_text_images": render_text, "fonts": font_records,
                   "text_font_policy": "Pillow built-in font, then ordered configured fallback fonts",
                   "seed": request["seed"], "compiler_input_limit": 4, "pipeline_input_limit": 5,
                   "postprocessing": "upstream native decode only; no adapter resize or mask composite"}
    return save_outputs(outputs, output_dir, observation)
