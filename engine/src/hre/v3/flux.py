"""FLUX 3 Klein: one explicit PUP compilation, followed by image-only execution.

Optional model dependencies are imported at execution time.  The adapter uses
the upstream modular pipeline, rather than treating it as DiffusionPipeline.
No model downloads, provider fallback, prompt retries or output resizing occur.
"""
from __future__ import annotations

import base64
from copy import deepcopy
from hashlib import sha256
import io
import math
from pathlib import Path
import re
import threading

from .common import (chat, load_images, model_identity, package_versions, require,
                     render_instruction, runtime_get, save_outputs)
from .native_sources import verify_module


MODEL_ID = "black-forest-labs/flux-3-image-klein"
PUP_ID = "black-forest-labs/flux-3-image-klein-pup"
ADAPTER_VERSION = "hre.v3.flux.1"
INSPECTED_DIFFUSERS_COMMIT = "aaf57d03a3edfbd9de457d2872417a92f149a91d"


def _conditioning_identity(request):
    # Seeds may change for an explicitly requested resample; image evidence and
    # edit intent may not change underneath an already compiled condition.
    from .dispatch import request_binding
    return request_binding(request)


def _code_identity(module):
    return verify_module(module, "modular_pipelines/flux3/prompt_upsampler.py")


def _pixel_identity(image):
    digest = sha256()
    digest.update(f"{image.mode}:{image.width}:{image.height}:".encode())
    digest.update(image.tobytes())
    return {"width": image.width, "height": image.height, "mode": image.mode,
            "pixel_sha256": digest.hexdigest()}


def _image_part(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return {"type": "image_url", "image_url": {
        "url": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")}}


def _boxes(request):
    spatial = request.get("spatial", {"mode": "full_frame"})
    require(spatial.get("mode") in {"full_frame", "bbox"}, "flux_spatial_unsupported",
            "FLUX supports semantic full-frame or bbox conditioning, not a native pixel mask")
    if spatial["mode"] != "bbox":
        return None
    boxes = spatial.get("boxes")
    require(isinstance(boxes, list) and bool(boxes), "flux_boxes_invalid", "bbox mode needs a nonempty box list")
    seen = set()
    for row in boxes:
        require(isinstance(row, dict) and set(row) == {"id", "desc", "from", "src_bbox", "tgt_bbox"},
                "flux_boxes_invalid", "Edit boxes require id, desc, from, src_bbox and tgt_bbox")
        require(isinstance(row["id"], str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", row["id"])
                and row["id"] not in seen, "flux_boxes_invalid", "Box IDs must be valid and unique")
        seen.add(row["id"])
        require(isinstance(row["desc"], str) and row["desc"].strip(), "flux_boxes_invalid", "Each box needs a description")
        origin = row["from"]
        require(isinstance(origin, str) and re.fullmatch(r"ref_image_\d+|target", origin),
                "flux_boxes_invalid", "Invalid source image token")
        if origin != "target":
            require(int(origin.rsplit("_", 1)[1]) < len(request["inputs"]),
                    "flux_boxes_invalid", "Box references an image which is not attached")
        for key in ("src_bbox", "tgt_bbox"):
            box = row[key]
            if box is None:
                continue
            require(isinstance(box, list) and len(box) == 4 and
                    all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in box)
                    and box[0] < box[2] and box[1] < box[3], "flux_boxes_invalid",
                    "Boxes must be ordered [y_min,x_min,y_max,x_max] in 0..1; coordinates are not silently clipped")
        require((origin == "target") == (row["src_bbox"] is None)
                and (row["src_bbox"] is not None or row["tgt_bbox"] is not None),
                "flux_boxes_invalid", "Box provenance and null source/target geometry disagree")
    return deepcopy(boxes)


def _pup_helpers():
    # The precise helper source is recorded because these are versioned upstream
    # implementation helpers, not a promise of a stable public API.
    from diffusers.modular_pipelines.flux3 import prompt_upsampler
    names = ("prepare_references", "boxes_to_canvas", "format_layout_request", "reconcile_boxes",
             "split_caption", "valid_canvas_box", "SYSTEM_PROMPTS", "I2I_SCAFFOLD")
    require(all(hasattr(prompt_upsampler, name) for name in names), "flux_pipeline_incompatible",
            "The installed FLUX3 prompt upsampler does not expose the inspected native protocol")
    _code_identity(prompt_upsampler)
    return prompt_upsampler


def _prepare_prompt(request, helpers):
    images = load_images(request)
    require(1 <= len(images) <= 10, "flux_inputs_invalid", "FLUX3 requires 1 to 10 ordered images")
    boxes = _boxes(request)
    prepared = helpers.prepare_references(images)
    locked = helpers.boxes_to_canvas(boxes) if boxes else None
    if locked:
        require(all(helpers.valid_canvas_box(row[key]) is not None for row in locked
                    for key in ("src_bbox", "tgt_bbox") if row[key] is not None),
                "flux_boxes_invalid", "A box collapses or is invalid on the official 0..1000 coordinate grid")
    instruction = render_instruction(request)
    if locked:
        instruction = helpers.format_layout_request(instruction, locked)
    mode = "i2i_bbox" if locked else "i2i"
    scaffold = helpers.I2I_SCAFFOLD[bool(locked)].format(instruction=instruction)
    return prepared, locked, mode, helpers.SYSTEM_PROMPTS[mode], scaffold


def _finish_condition(raw, locked, mode, helpers, input_count=None):
    require(isinstance(raw, str) and bool(raw.strip()), "flux_condition_empty", "PUP returned an empty condition")
    raw = raw.strip()
    final = helpers.reconcile_boxes(raw, locked) if locked else raw
    warnings = []
    native = {"mode": mode, "raw_text": raw, "final_text": final,
              "locked_boxes": deepcopy(locked), "reconciliation_applied": bool(locked)}
    if locked:
        caption, rows = helpers.split_caption(final)
        require(isinstance(caption, str) and caption.strip() and isinstance(rows, list),
                "flux_bbox_condition_invalid", "Native bbox condition must contain prose followed by a JSON array")
        by_id = {row.get("id"): row for row in rows if isinstance(row, dict)}
        for row in locked:
            observed = by_id.get(row["id"])
            require(isinstance(observed, dict) and all(observed.get(k) == row.get(k)
                    for k in ("id", "from", "src_bbox", "tgt_bbox")),
                    "flux_bbox_condition_invalid", "Native reconciliation did not preserve the frozen boxes")
            require(f"<{row['id']}>" in caption, "flux_bbox_condition_invalid",
                    "PUP omitted a frozen box entity from its instruction")
        native.update(caption=caption, boxes=rows)
        if input_count is not None:
            require(all(not str(row.get("from", "")).startswith("ref_image_") or
                        int(row["from"].rsplit("_", 1)[1]) < input_count for row in rows),
                    "flux_bbox_condition_invalid", "PUP referenced an unattached image in its box table")
        if len(rows) > len(locked):
            warnings.append("PUP added box entities; inspect the saved native table for unintended content changes.")
        warnings.append("FLUX bbox is semantic/layout conditioning, not an outside-ROI pixel lock.")
    return final, native, warnings


def _compile_condition(request: dict, config: dict, call_state: dict) -> dict:
    """Compile through the official local PUP or an explicitly selected local VLM."""
    require(request.get("profile_id") == "flux3_klein", "flux_profile_invalid", "Expected flux3_klein")
    backend = config.get("backend")
    require(backend in {"flux3_pup_local", "flux3_external_vlm_local"}, "flux_compiler_invalid",
            "Select flux3_pup_local or flux3_external_vlm_local explicitly")
    helpers = _pup_helpers()
    prepared, locked, mode, system_prompt, scaffold = _prepare_prompt(request, helpers)
    settings = config.get("settings", {})
    permitted_settings = {"max_new_tokens"} if backend == "flux3_pup_local" else set()
    require(isinstance(settings, dict) and not set(settings) - permitted_settings,
            "flux_compiler_settings", "Only max_new_tokens is configurable for native FLUX PUP")
    max_tokens = settings.get("max_new_tokens", 3584)
    require(type(max_tokens) is int and max_tokens > 0, "flux_compiler_settings", "max_new_tokens must be positive")
    identity = None
    if backend == "flux3_pup_local":
        identity = model_identity(config, PUP_ID)

        def factory():
            import torch
            from transformers import AutoProcessor, Qwen3_5ForConditionalGeneration
            dtype = getattr(torch, config.get("torch_dtype", "bfloat16"))
            processor = AutoProcessor.from_pretrained(config["local_path"], local_files_only=True)
            model = Qwen3_5ForConditionalGeneration.from_pretrained(
                config["local_path"], torch_dtype=dtype, local_files_only=True).to(config.get("device", "cuda")).eval()
            return {"processor": processor, "model": model, "lock": threading.RLock()}

        runtime = runtime_get({"adapter": ADAPTER_VERSION, "kind": "pup", "identity": identity,
                               "device": config.get("device", "cuda"), "dtype": config.get("torch_dtype", "bfloat16")}, factory)
        import torch
        content = [{"type": "image", "image": image} for image in prepared] + [{"type": "text", "text": scaffold}]
        messages = [{"role": "system", "content": [{"type": "text", "text": system_prompt}]},
                    {"role": "user", "content": content}]
        with runtime["lock"], torch.inference_mode():
            inputs = runtime["processor"].apply_chat_template(
                messages, add_generation_prompt=True, tokenize=True, return_dict=True,
                return_tensors="pt", enable_thinking=False).to(runtime["model"].device)
            call_state.update(calls_attempted=1)
            generated = runtime["model"].generate(**inputs, max_new_tokens=max_tokens, do_sample=False)
            call_state.update(calls_completed=1)
            generated_tokens = generated[0, inputs["input_ids"].shape[1]:]
            observed = {"model": PUP_ID, "calls_attempted": 1, "calls_completed": 1,
                        "generated_token_count": int(generated_tokens.shape[0]),
                        "decoding": {"max_new_tokens": max_tokens, "do_sample": False, "enable_thinking": False}}
            call_state.update(observed)
            try:
                raw = runtime["processor"].decode(generated_tokens, skip_special_tokens=True).strip()
            except Exception as exc:
                exc.observation = {**observed, "compiler_id": backend}
                exc.native_output = {"generated_token_ids": generated_tokens.tolist(), "mode": mode}
                raise
            eos = getattr(runtime["model"].generation_config, "eos_token_id", None)
            eos = eos if isinstance(eos, (list, tuple)) else [eos]
            length_limited = (observed["generated_token_count"] >= max_tokens and
                              (not observed["generated_token_count"] or int(generated_tokens[-1]) not in eos))
            observed["finish_reason"] = "length" if length_limited else "stop"
            call_state.update(text=raw, finish_reason=observed["finish_reason"])
    else:
        endpoint = config.get("endpoint")
        require(isinstance(endpoint, dict), "flux_compiler_endpoint", "A local VLM endpoint is required")
        messages = [{"role": "system", "content": system_prompt},
                    {"role": "user", "content": [_image_part(image) for image in prepared] +
                     [{"type": "text", "text": scaffold}]}]
        call_state.update(calls_attempted=1)
        observed = chat(endpoint, messages, response_schema=None)
        call_state.update(observed)
        raw = observed["text"]
    try:
        require(observed.get("finish_reason") != "length", "flux_condition_truncated",
                "VLM exhausted its output limit; no retry or hidden prompt repair is applied")
        final, native, warnings = _finish_condition(raw, locked, mode, helpers, len(prepared))
    except Exception as exc:
        exc.observation = {**observed, "compiler_id": backend, "adapter_version": ADAPTER_VERSION,
                           "pup_calls": int(backend == "flux3_pup_local")}
        exc.native_output = {"raw_text": raw, "mode": mode, "locked_boxes": locked,
                             "system_prompt": system_prompt, "user_prompt": scaffold}
        raise
    if backend == "flux3_external_vlm_local":
        warnings.append("Condition was compiled by the configured VLM with the native protocol, not by the official PUP weights.")
    native.update(system_prompt=system_prompt, user_prompt=scaffold,
                  conditioning_request_sha256=_conditioning_identity(request),
                  prepared_inputs=[_pixel_identity(image) for image in prepared])
    return {"text": final, "condition_kind": "flux3_i2i_bbox_record" if locked else "flux3_i2i_instruction",
            "native_output": native, "warnings": warnings,
            "observation": {**observed, "compiler_id": backend, "adapter_version": ADAPTER_VERSION,
                            "model_identity": identity, "pup_calls": int(backend == "flux3_pup_local"),
                            "native_protocol_vlm_calls": 1, "fallback": None,
                            "upstream_code": _code_identity(helpers), "packages": package_versions()}}


def compile_condition(request: dict, config: dict) -> dict:
    """Record whether a failed compilation actually submitted its one model call."""
    state = {"compiler_id": config.get("backend"), "calls_attempted": 0, "calls_completed": 0}
    try:
        return _compile_condition(request, config, state)
    except Exception as exc:
        if not isinstance(getattr(exc, "observation", None), dict):
            exc.observation = deepcopy(state)
        if getattr(exc, "native_output", None) is None and state.get("text"):
            exc.native_output = {"raw_text": state["text"]}
        raise


def _contains_pup(blocks):
    children = getattr(blocks, "sub_blocks", {})
    return any(name == "prompt_upsampler" or _contains_pup(child) for name, child in children.items())


def _load_editor(config, identity):
    import torch
    import diffusers
    from diffusers.modular_pipelines import modular_pipeline
    from diffusers.modular_pipelines.flux3 import (modular_blocks_flux3_distilled, image_processor,
                                                 encoders, before_denoise)
    require(diffusers.__version__ == config["pipeline_version"], "flux_pipeline_version",
            "Installed Diffusers version differs from the frozen editor config")
    require(hasattr(diffusers, "ModularPipeline"), "flux_pipeline_missing", "ModularPipeline is unavailable")
    sources = {name: verify_module(module, relative) for name, module, relative in (
        ("modular_pipeline", modular_pipeline, "modular_pipelines/modular_pipeline.py"),
        ("blocks", modular_blocks_flux3_distilled, "modular_pipelines/flux3/modular_blocks_flux3_distilled.py"),
        ("image_processor", image_processor, "modular_pipelines/flux3/image_processor.py"),
        ("encoders", encoders, "modular_pipelines/flux3/encoders.py"),
        ("before_denoise", before_denoise, "modular_pipelines/flux3/before_denoise.py"))}
    original = diffusers.ModularPipeline.from_pretrained(config["local_path"], local_files_only=True,
                                                        trust_remote_code=False)
    blocks = original.blocks
    require(getattr(blocks, "model_name", None) == "flux3-distilled", "flux_checkpoint_variant",
            "The selected local model is not the FLUX3 distilled modular pipeline")
    require("prompt_upsampler" in blocks.sub_blocks, "flux_pup_split_failed",
            "Expected native PUP block was not found; refuse an unknown pipeline layout")
    blocks.sub_blocks.pop("prompt_upsampler")
    require(not _contains_pup(blocks), "flux_pup_split_failed", "PUP remains in the image execution blocks")
    pipe = blocks.init_pipeline(config["local_path"])
    component_specs = pipe._component_specs
    local_root = Path(config["local_path"]).resolve()
    for name, spec in component_specs.items():
        if spec.default_creation_method == "from_pretrained":
            require(spec.pretrained_model_name_or_path and
                    Path(spec.pretrained_model_name_or_path).resolve() == local_root,
                    "flux_component_missing", f"Deploy {name} inside the local checkpoint; external cache fallback is disabled")
    pipe.load_components(dtype=getattr(torch, config["torch_dtype"]), local_files_only=True)
    require(all(getattr(pipe, name, None) is not None for name in component_specs),
            "flux_component_missing", "Some required local FLUX components could not be loaded")
    pipe.to(config["device"])
    require(not _contains_pup(pipe.blocks), "flux_pup_split_failed", "Initialized editor contains a second PUP")
    return {"pipe": pipe, "lock": threading.RLock(), "blocks": list(blocks.sub_blocks), "sources": sources}


def generate(request: dict, condition: dict, config: dict, output_dir: Path) -> dict:
    """Run one distilled image call using the already frozen native condition."""
    require(request.get("profile_id") == "flux3_klein", "flux_profile_invalid", "Expected flux3_klein")
    boxes = _boxes(request)
    expected_kind = "flux3_i2i_bbox_record" if boxes else "flux3_i2i_instruction"
    require(condition.get("condition_kind") == expected_kind
            and isinstance(condition.get("text"), str) and condition["text"].strip(),
            "flux_condition_invalid", "A completed FLUX native condition is required")
    require(condition.get("native_output", {}).get("conditioning_request_sha256") == _conditioning_identity(request),
            "flux_condition_request_mismatch", "Source, canvas, spatial constraints or edit intent changed after compilation")
    output_dir = Path(output_dir).resolve()
    require(not output_dir.exists() or output_dir.is_dir(), "native_output_exists", "Output destination must be a directory")
    output_dir.mkdir(parents=True, exist_ok=True)
    require(not list(output_dir.glob("native_*.png")), "native_output_exists", "Use a fresh native output directory before generation")
    identity = model_identity(config, MODEL_ID)
    settings = config.get("settings", {})
    require(isinstance(settings, dict) and not set(settings) - {
        "num_inference_steps", "num_images_per_prompt", "max_sequence_length", "geometry_policy"},
        "flux_editor_settings", "FLUX distilled does not accept CFG, negative_prompt, strength or unknown settings")
    steps = settings.get("num_inference_steps", 16)
    require(type(steps) is int and 4 <= steps <= 16, "flux_editor_settings", "Distilled FLUX steps must be within 4..16")
    require(settings.get("num_images_per_prompt", 1) == 1, "flux_editor_settings", "Request exactly one image")
    sequence_length = settings.get("max_sequence_length", 8192)
    require(type(sequence_length) is int and sequence_length > 0, "flux_editor_settings", "Invalid token limit")
    policy = settings.get("geometry_policy", "explicit_canvas")
    require(policy == "explicit_canvas", "flux_geometry_policy",
            "This task contract requires explicit_canvas; native automatic output geometry is a separate experiment")
    images = load_images(request)
    require(1 <= len(images) <= 10, "flux_inputs_invalid", "FLUX requires 1 to 10 images")
    kwargs = {"prompt": condition["text"], "image": images, "num_inference_steps": steps,
              "num_images_per_prompt": 1, "max_sequence_length": sequence_length, "output": "images"}
    if policy == "explicit_canvas":
        width, height = request["canvas"]["width"], request["canvas"]["height"]
        require(type(width) is int and type(height) is int and min(width, height) > 0
                and width % 16 == 0 and height % 16 == 0,
                "flux_canvas_unsupported", "Explicit FLUX canvas must be positive multiples of 16")
        kwargs.update(width=width, height=height)
    runtime = runtime_get({"adapter": ADAPTER_VERSION, "kind": "editor", "config": config,
                           "identity": identity}, lambda: _load_editor(config, identity))
    import torch
    kwargs["generator"] = torch.Generator(device=config["device"]).manual_seed(request["seed"])
    pipe = runtime["pipe"]
    trace = []
    with runtime["lock"]:
        require(not _contains_pup(pipe.blocks), "flux_second_pup", "Editor unexpectedly contains a PUP stage")
        original_preprocess = pipe.image_processor.preprocess

        def observe_preprocess(*args, **kw):
            output = original_preprocess(*args, **kw)
            tensor, post = output
            trace.append({"resize_mode": kw.get("resize_mode", "fill"),
                          "tensor_shape": list(tensor.shape), "reference_crop": post.get("reference_crop")})
            return output

        pipe.image_processor.preprocess = observe_preprocess
        try:
            with torch.inference_mode():
                outputs = pipe(**kwargs)
        finally:
            pipe.image_processor.preprocess = original_preprocess
    require(isinstance(outputs, (list, tuple)) and bool(outputs), "flux_output_invalid",
            "ModularPipeline did not return an image list for output=images")
    observation = {"adapter_version": ADAPTER_VERSION, "model_identity": identity,
                   "image_calls_attempted": 1, "image_calls_completed": 1,
                   "actual_generation_count": len(outputs), "pup_calls": 0,
                   "image_blocks": runtime["blocks"], "geometry_policy": policy,
                   "upstream_code": runtime["sources"],
                   "input_geometry": [_pixel_identity(image) for image in images],
                   "native_preprocess": trace, "num_inference_steps": steps,
                   "max_sequence_length": sequence_length, "seed": request["seed"],
                   "packages": package_versions(), "postprocessing": "upstream native decode/crop only"}
    return save_outputs(outputs, output_dir, observation)
