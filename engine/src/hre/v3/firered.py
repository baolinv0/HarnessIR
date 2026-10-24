"""FireRed 1.1 image execution and strict, local text-only Recaption.

The compiler loads the official template and reference-map helpers from a
pinned checkout.  It deliberately does not call the upstream provider factory:
that factory defaults to external services and the upstream wrapper retries or
silently falls back.  All changes to that execution policy are recorded.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import importlib
import math
from pathlib import Path
import re
import sys
import time
from types import ModuleType

from ..models import HREError
from .common import (
    chat, load_images, model_identity, package_versions, render_instruction,
    require, runtime_get, save_outputs,
)
from .official_checkout import import_context, verified_checkout
from .native_sources import DIFFUSERS_COMMIT, verify_module


MODEL_ID = "FireRedTeam/FireRed-Image-Edit-1.1"
ADAPTER_VERSION = "hre.v3.firered.1"
RECAPTION_REFERENCE_COMMIT = "456d010bd3f9bd727f1ab7fe60838caf6ee479e6"


def _request(request: dict) -> None:
    require(request.get("schema_version") == "hre_model_request_v3" and request.get("profile_id") == "firered11",
            "firered_request_invalid", "FireRed requires a firered11 v3 request")
    roles = [item.get("role") for item in request.get("inputs", [])]
    expected = ["source"] if request.get("task_mode") == "restoration" else ["source", "appearance_reference"]
    require(request.get("task_mode") in {"restoration", "reference_enhance"} and roles == expected,
            "firered_inputs_invalid", "Use the ordered source, then optional appearance reference")
    require(request.get("spatial", {}).get("mode", "full_frame") != "native_mask",
            "firered_native_mask_unsupported", "FireRed has no native hard-mask argument; use the shared spatial adapter")
    require(request.get("spatial", {}).get("mode", "full_frame") == "full_frame",
            "firered_spatial_unsupported", "Prepare shared crop/fuse before FireRed execution; other native spatial modes are unsupported")
    require(type(request.get("seed")) is int and request["seed"] >= 0,
            "firered_seed_invalid", "A nonnegative integer seed is required")


def compile_condition(request: dict, config: dict) -> dict:
    """Execute official Recaption's text mechanism through one explicit endpoint."""
    _request(request)
    require(config.get("backend") in {"firered_recaption", "firered_recaption_local", "openai_compatible"},
            "firered_compiler_backend", "Select the built-in firered_recaption compiler")
    root, upstream = verified_checkout(config, ("agent/recaption.py", "agent/config.py"))
    load_images(request)  # Validate bindings; the rewriter itself does not see pixels.
    instruction = render_instruction(request)
    settings = config.get("settings", {})
    require(isinstance(settings, dict) and not set(settings) - {"target_length"},
            "firered_recaption_settings_invalid", "Use target_length here and sampling settings in endpoint.settings")
    target_length = settings.get("target_length", 512)
    require(type(target_length) is int and target_length > 0,
            "firered_recaption_settings_invalid", "Recaption target_length must be a positive integer")
    endpoint = deepcopy(config.get("endpoint"))
    require(isinstance(endpoint, dict) and endpoint.get("base_url") and endpoint.get("model"),
            "firered_endpoint_required", "Configure the local OpenAI-compatible endpoint explicitly; there is no cloud default")
    endpoint_settings = endpoint.get("settings", {})
    require(isinstance(endpoint_settings, dict), "firered_recaption_settings_invalid", "endpoint.settings must be an object")
    endpoint["settings"] = {"temperature": 0.4, "max_tokens": 4096, **endpoint_settings}
    if "max_completion_tokens" in endpoint_settings and "max_tokens" not in endpoint_settings:
        endpoint["settings"].pop("max_tokens")
    with import_context(root, ("agent",)):
        # Import only the two text helpers.  The upstream package __init__ imports
        # a Gemini ROI pipeline that is unrelated to 1/2-image Recaption.
        package = ModuleType("agent")
        package.__path__ = [str(root / "agent")]
        package.__file__ = str(root / "agent" / "__init__.py")
        sys.modules["agent"] = package
        recaption = importlib.import_module("agent.recaption")
        require(Path(recaption.__file__).resolve().is_relative_to(root), "upstream_import_mismatch", "Recaption came from another checkout")
        group_indices = [[index] for index in range(len(request["inputs"]))]
        ref_map = recaption.build_reference_map(group_indices)
        instruction_fixed = recaption._replace_image_refs(instruction, ref_map)
        mapping = {f"original_image_{original}": f"composite_image_{composite}" for original, composite in ref_map.items()}
        system_prompt = recaption._SYSTEM_PROMPT.format(target_len=target_length)
        user_prompt = (
            f"Original instruction:\n{instruction_fixed}\n\n"
            f"Image grouping mapping (original image number → composite image number):\n{mapping}\n\n"
            f"Please output the rewritten instruction (approximately {target_length} words/characters)."
        )
    observation = {
        "compiler_id": "FireRed-Image-Edit/Recaption",
        "implementation_id": "firered_official_template_local_provider",
        "adapter_version": ADAPTER_VERSION, **upstream,
        "reference_implementation_commit": RECAPTION_REFERENCE_COMMIT,
        "execution_policy": "strict_single_call",
        "upstream_behavior_changes": ["explicit_endpoint", "cloud_defaults_removed", "automatic_retries_disabled", "silent_fallback_disabled"],
        "system_prompt_sha256": sha256(system_prompt.encode()).hexdigest(),
        "settings": {"target_length": target_length, **endpoint["settings"]},
        "input_instruction": instruction_fixed, "group_indices": group_indices,
        "images_supplied": False, "crop_and_stitch_invoked": False,
        "calls_attempted": 1, "calls_completed": 0, "fallback_used": False,
        "packages": package_versions(),
    }
    try:
        response = chat(endpoint, [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ])
    except HREError as exc:
        exc.observation = observation
        raise
    observation.update(response)
    raw_text = response["text"]
    text = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL).strip()
    native = {"raw_text": raw_text, "final_instruction": text, "group_indices": group_indices,
              "raw_response": response.get("raw_response"), "images_supplied": False}
    if response.get("finish_reason") == "length" or "<think>" in text or not text:
        error = HREError("firered_recaption_incomplete", "Recaption returned a truncated or empty instruction; no fallback occurred")
        error.observation, error.native_output = observation, native
        raise error
    return {"text": text, "condition_kind": "edit_instruction", "native_output": native,
            "observation": observation, "warnings": []}


def generate(request: dict, condition: dict, config: dict, output_dir: Path) -> dict:
    """Call the pinned FireRed 1.1 pipeline once, without the upstream demo loop."""
    _request(request)
    identity = model_identity(config, MODEL_ID)
    device, dtype = config.get("device", "cuda"), config.get("torch_dtype", "bfloat16")
    require(isinstance(device, str) and device and dtype in {"bfloat16", "float16", "float32"},
            "firered_runtime_invalid", "Configure a device and supported torch dtype")
    require(isinstance(condition.get("text"), str) and condition["text"].strip(),
            "firered_condition_invalid", "An accepted nonempty editing condition is required")
    defaults = {"num_inference_steps": 40, "true_cfg_scale": 4.0, "negative_prompt": " ", "num_images_per_prompt": 1}
    supplied = config.get("settings", {})
    require(isinstance(supplied, dict) and not set(supplied) - set(defaults),
            "firered_settings_invalid", "Unknown FireRed 1.1 setting; optimized/LoRA variants need separate identities")
    settings = {**defaults, **supplied}
    require(type(settings["num_inference_steps"]) is int and settings["num_inference_steps"] > 0
            and type(settings["num_images_per_prompt"]) is int and settings["num_images_per_prompt"] == 1,
            "firered_settings_invalid", "Use positive steps and request exactly one image")
    require(type(settings["true_cfg_scale"]) in {int, float} and math.isfinite(settings["true_cfg_scale"]) and settings["true_cfg_scale"] > 0
            and isinstance(settings["negative_prompt"], str), "firered_settings_invalid", "Invalid CFG or negative prompt")
    images = load_images(request, "RGB")
    output_dir = Path(output_dir).resolve()
    require(not output_dir.exists() or output_dir.is_dir(), "native_output_exists", "Output destination must be a directory")
    output_dir.mkdir(parents=True, exist_ok=True)
    require(not list(output_dir.glob("native_*.png")), "native_output_exists", "Use a fresh native output directory before generation")
    width, height = request["canvas"]["width"], request["canvas"]["height"]
    require(type(width) is int and type(height) is int and width > 0 and height > 0 and width % 16 == height % 16 == 0,
            "firered_canvas_unsupported", "Prepare a canvas divisible by 16 before FireRed execution")
    try:
        import torch
        import diffusers
    except ImportError as exc:
        raise HREError("firered_dependency_missing", "Deploy the locked FireRed torch/Diffusers runtime before execution") from exc
    require(config.get("pipeline_version") == diffusers.__version__, "firered_pipeline_version_mismatch",
            "Installed Diffusers differs from the frozen pipeline_version")
    pipeline_class = getattr(diffusers, "QwenImageEditPlusPipeline", None)
    require(pipeline_class is not None, "firered_dependency_missing", "This Diffusers build lacks QwenImageEditPlusPipeline")
    source = verify_module(importlib.import_module(pipeline_class.__module__),
                           "pipelines/qwenimage/pipeline_qwenimage_edit_plus.py")

    def factory():
        return pipeline_class.from_pretrained(
            identity["local_path"], local_files_only=True, torch_dtype=getattr(torch, dtype),
        ).to(device)

    pipe = runtime_get({"adapter": ADAPTER_VERSION, "identity": identity, "device": device,
                        "dtype": dtype, "pipeline_version": diffusers.__version__, "pipeline_source": source}, factory)
    vae_scale = getattr(pipe, "vae_scale_factor", 8)
    require(type(vae_scale) is int and vae_scale > 0, "firered_pipeline_invalid", "The deployed VAE scale factor is invalid")
    factor = vae_scale * 2
    require(width % factor == height % factor == 0,
            "firered_canvas_unsupported", "The explicit canvas is not representable by this deployed pipeline")
    kwargs = {**settings, "image": images, "prompt": condition["text"], "width": width, "height": height,
              "generator": torch.Generator(device=device).manual_seed(request["seed"])}
    observation = {
        "adapter_version": ADAPTER_VERSION, "model_identity": identity,
        "pipeline_class": "QwenImageEditPlusPipeline", "packages": {**package_versions(), "diffusers": diffusers.__version__},
        "upstream_code": {"pipeline": source}, "inspected_diffusers_commit": DIFFUSERS_COMMIT,
        "settings": {**deepcopy(settings), "width": width, "height": height, "seed": request["seed"],
                     "device": device, "torch_dtype": dtype},
        "input_roles": [asset["role"] for asset in request["inputs"]], "input_modes": [image.mode for image in images],
        "input_sizes": [list(image.size) for image in images], "prompt_sha256": sha256(condition["text"].encode()).hexdigest(),
        "image_calls_attempted": 1, "image_calls_completed": 0, "prompt_rewrite_during_execution": False,
        "crop_and_stitch_invoked": False, "optimized_demo_invoked": False,
        "fallback_used": False, "output_normalization": "none_native_outputs_preserved",
    }
    started = time.monotonic()
    try:
        with torch.inference_mode():
            result = pipe(**kwargs)
    except Exception as exc:
        observation["elapsed_seconds"] = time.monotonic() - started
        error = HREError("firered_generation_failed", "FireRed generation failed; no automatic retry or parameter change occurred")
        error.observation = observation
        raise error from exc
    observation.update(image_calls_completed=1, elapsed_seconds=time.monotonic() - started)
    try:
        return save_outputs(getattr(result, "images", None), output_dir, observation)
    except HREError as exc:
        exc.observation = observation
        raise
