"""Qwen-Image-2.1 and its real, local PE-I2I compiler.

The PE implementation uses the official pinned ``pe_core`` helpers for message
construction and parsing.  Generation follows the upstream Transformers
reference, with offline loading and the unparsed generation retained.  The image
executor is the original 2.1 checkpoint, never 2511 or Turbo under the same ID.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import importlib
import math
from pathlib import Path
import time

from ..models import HREError
from .common import (
    load_images, model_identity, package_versions, render_instruction, require,
    runtime_get, save_outputs,
)
from .official_checkout import import_context, verified_checkout
from .native_sources import DIFFUSERS_COMMIT, verify_module


MODEL_ID = "Qwen/Qwen-Image-2.1"
PE_MODEL_ID = "Qwen/Qwen-Image-2.1-PE-I2I"
ADAPTER_VERSION = "hre.v3.qwen.1"
PE_REFERENCE_COMMIT = "ab96caa944157ca28a4f36b695c3047549f48f98"


def _request(request: dict) -> None:
    require(request.get("schema_version") == "hre_model_request_v3" and request.get("profile_id") == "qwen21",
            "qwen_request_invalid", "Qwen requires a qwen21 v3 request")
    roles = [item.get("role") for item in request.get("inputs", [])]
    expected = ["source"] if request.get("task_mode") == "restoration" else ["source", "appearance_reference"]
    require(request.get("task_mode") in {"restoration", "reference_enhance"} and roles == expected,
            "qwen_inputs_invalid", "Use the ordered source, then optional appearance reference")
    require(request.get("spatial", {}).get("mode", "full_frame") != "native_mask",
            "qwen_native_mask_unsupported", "Qwen 2.1 has no native hard-mask argument; use the shared spatial adapter")
    require(request.get("spatial", {}).get("mode", "full_frame") == "full_frame",
            "qwen_spatial_unsupported", "Prepare shared crop/fuse before Qwen execution; other native spatial modes are unsupported")
    require(type(request.get("seed")) is int and request["seed"] >= 0,
            "qwen_seed_invalid", "A nonnegative integer seed is required")


def _device_dtype(config: dict) -> tuple[str, str]:
    device, dtype = config.get("device", "cuda"), config.get("torch_dtype", "bfloat16")
    require(isinstance(device, str) and bool(device), "qwen_runtime_invalid", "Set an explicit device")
    require(dtype in {"bfloat16", "float16", "float32"}, "qwen_runtime_invalid", "Unsupported torch dtype")
    return device, dtype


def _evidence_error(code: str, message: str, observation: dict, native_output: dict):
    error = HREError(code, message)
    error.observation = observation
    error.native_output = native_output
    raise error


def _pe_generation(model, processor, messages: list, settings: dict, seed: int) -> tuple[str, int, int]:
    """One real generate call, matching the audited edit reference path."""
    import torch

    inputs = processor.apply_chat_template(
        messages, add_generation_prompt=True, tokenize=True, return_dict=True,
        return_tensors="pt", enable_thinking=True,
    ).to(model.device)
    if "mm_token_type_ids" not in inputs and hasattr(processor, "create_mm_token_type_ids"):
        inputs["mm_token_type_ids"] = processor.create_mm_token_type_ids(inputs["input_ids"])
    prompt_length = inputs["input_ids"].shape[1]
    temperature = settings["temperature"]
    torch.manual_seed(seed)
    with torch.inference_mode():
        output = model.generate(
            **inputs, max_new_tokens=settings["max_new_tokens"],
            do_sample=temperature > 0,
            temperature=temperature if temperature > 0 else None,
            top_p=settings["top_p"] if temperature > 0 else None,
            top_k=settings["top_k"] if temperature > 0 else None,
            pad_token_id=processor.tokenizer.eos_token_id,
        )
    generated = output[0, prompt_length:]
    text = processor.tokenizer.decode(generated, skip_special_tokens=True)
    return text, int(prompt_length), int(generated.shape[0])


def compile_condition(request: dict, config: dict) -> dict:
    """Run the actual locally deployed PE-I2I once; never substitute a generic VLM."""
    _request(request)
    require(config.get("backend") in {"qwen_pe_i2i", "qwen_pe_i2i_transformers", "transformers"},
            "qwen_compiler_backend", "Select the built-in qwen_pe_i2i Transformers compiler")
    identity = model_identity(config, PE_MODEL_ID)
    root, upstream = verified_checkout(config, ("prompt_rewrite/pe_core.py", "prompt_rewrite/run_transformers.py"))
    device, dtype = _device_dtype(config)
    # Validate source hashes before loading a model or running an upstream helper.
    load_images(request)
    instruction = render_instruction(request)
    with import_context(root, ("pe_core",), ("prompt_rewrite",)):
        core = importlib.import_module("pe_core")
        require(Path(core.__file__).resolve().is_relative_to(root), "upstream_import_mismatch", "PE helper came from another checkout")
        profile = core.get_profile("edit")
        settings = {
            "temperature": profile.temperature, "top_p": profile.top_p,
            "top_k": profile.top_k, "presence_penalty": profile.presence_penalty,
            "max_new_tokens": profile.max_new_tokens, "image_max_pixels": profile.image_max_pixels,
        }
        supplied = config.get("settings", {})
        require(isinstance(supplied, dict) and not set(supplied) - set(settings),
                "qwen_pe_settings_invalid", "Unknown PE-I2I sampling setting")
        settings.update(supplied)
        require(type(settings["temperature"]) in {int, float} and math.isfinite(settings["temperature"]) and settings["temperature"] >= 0,
                "qwen_pe_settings_invalid", "temperature must be finite and nonnegative")
        require(type(settings["top_p"]) in {int, float} and math.isfinite(settings["top_p"]) and 0 < settings["top_p"] <= 1,
                "qwen_pe_settings_invalid", "top_p must be in (0, 1]")
        require(type(settings["top_k"]) is int and settings["top_k"] >= 0
                and type(settings["max_new_tokens"]) is int and settings["max_new_tokens"] > 0
                and type(settings["image_max_pixels"]) is int and settings["image_max_pixels"] >= 0,
                "qwen_pe_settings_invalid", "Invalid PE token or pixel limit")
        require(settings["presence_penalty"] == 0, "qwen_pe_settings_invalid",
                "The edit compiler uses the official zero presence penalty, not the T2I penalty")
        system_path = config.get("system_prompt_path")
        require(system_path is None or (isinstance(system_path, str) and system_path and Path(system_path).is_absolute()),
                "qwen_pe_system_prompt_missing", "system_prompt_path must be an absolute local file when supplied")
        system_prompt_path = Path(system_path) if system_path else Path(identity["local_path"]) / "system_prompt.txt"
        require(system_prompt_path.is_file(), "qwen_pe_system_prompt_missing", "Deploy the PE-I2I system_prompt.txt with its checkpoint")
        try:
            system_prompt = core.load_system_prompt(system_path, identity["local_path"])
        except (OSError, UnicodeError, SystemExit) as exc:
            raise HREError("qwen_pe_system_prompt_missing", "The pinned PE-I2I system prompt could not be loaded") from exc
        require(isinstance(system_prompt, str) and system_prompt.strip(), "qwen_pe_system_prompt_missing", "PE-I2I system prompt is empty")
        images = [core.load_image(Path(asset["path"]), settings["image_max_pixels"]) for asset in request["inputs"]]
        load_images(request)  # A changed file must not survive the upstream helper's second read.
        messages = core.build_messages(system_prompt, instruction, images)

        def load_runtime():
            import torch
            from transformers import AutoModelForImageTextToText, AutoProcessor

            processor = AutoProcessor.from_pretrained(identity["local_path"], local_files_only=True, trust_remote_code=False)
            model = AutoModelForImageTextToText.from_pretrained(
                identity["local_path"], dtype=getattr(torch, dtype), low_cpu_mem_usage=True,
                local_files_only=True, trust_remote_code=False,
            ).to(device).eval()
            return model, processor

        model, processor = runtime_get({"adapter": ADAPTER_VERSION, "kind": "pe_i2i", "identity": identity,
                                        "device": device, "dtype": dtype, "upstream": upstream}, load_runtime)
        observation = {
            "compiler_id": "Qwen-Image-2.1/PE-I2I", "implementation_id": ADAPTER_VERSION,
            "backend": "local_transformers", "model_identity": identity, **upstream,
            "reference_implementation_commit": PE_REFERENCE_COMMIT,
            "system_prompt_sha256": sha256(system_prompt_path.read_bytes()).hexdigest(),
            "effective_system_prompt_sha256": sha256(system_prompt.encode("utf-8")).hexdigest(),
            "system_prompt_override": system_path is not None,
            "settings": {**settings, "enable_thinking": True, "seed": request["seed"], "device": device, "torch_dtype": dtype},
            "input_roles": [asset["role"] for asset in request["inputs"]],
            "input_modes": [image.mode for image in images],
            "input_sizes": [list(image.size) for image in images],
            "input_instruction": instruction,
            "calls_attempted": 1, "calls_completed": 0, "fallback_used": False,
            "packages": package_versions(),
        }
        started = time.monotonic()
        try:
            raw, input_tokens, output_tokens = _pe_generation(model, processor, messages, settings, request["seed"])
        except Exception as exc:
            observation["elapsed_seconds"] = time.monotonic() - started
            if isinstance(exc, HREError):
                exc.observation = observation
                raise
            error = HREError("qwen_pe_generation_failed", "PE-I2I generation failed; no retry or fallback occurred")
            error.observation = observation
            raise error from exc
        observation.update(calls_completed=1, elapsed_seconds=time.monotonic() - started,
                           input_tokens=input_tokens, output_tokens=output_tokens)
        try:
            thinking, answer = core.split_thinking(raw)
            parsed = core.parse_answer(answer, profile)
            require(isinstance(parsed, dict), "qwen_pe_parse_failed", "Official PE parser returned no record")
        except Exception as exc:
            error = HREError("qwen_pe_parse_failed", "The official PE parser failed; the original generation is retained")
            error.observation = observation
            error.native_output = {"raw_generation": raw}
            raise error from exc
        native = {**parsed, "raw_generation": raw, "thinking": thinking, "raw_answer": answer,
                  "raw_generation_sha256": sha256(raw.encode("utf-8")).hexdigest()}
        observation["parser"] = {"implementation": "official_pe_core.parse_answer",
                                 "json_repair_available": getattr(core, "json_repair", None) is not None}
        if parsed.get("parse_ok") is not True or not isinstance(parsed.get("positive_prompt"), str) or not parsed["positive_prompt"].strip():
            _evidence_error("qwen_pe_parse_failed", "The actual PE-I2I answer did not parse; no image was generated", observation, native)
        if parsed.get("ratio_follow") not in {"<image1>", "image1"} or parsed.get("wh_ratio") != "":
            _evidence_error("qwen_pe_canvas_mismatch", "PE-I2I did not retain the source canvas; no silent correction was made", observation, native)
        return {"text": parsed["positive_prompt"], "condition_kind": "semantic_instruction",
                "native_output": native, "observation": observation, "warnings": []}


def generate(request: dict, condition: dict, config: dict, output_dir: Path) -> dict:
    """One real QwenImage21Pipeline invocation, preserving all native RGBA outputs."""
    _request(request)
    identity = model_identity(config, MODEL_ID)
    device, dtype = _device_dtype(config)
    require(isinstance(condition.get("text"), str) and condition["text"].strip(),
            "qwen_condition_invalid", "An accepted nonempty editing condition is required")
    defaults = {"num_inference_steps": 40, "true_cfg_scale": 1.0, "negative_prompt": "",
                "num_images_per_prompt": 1, "output_resolution": 2048, "use_kv_cache": True}
    supplied = config.get("settings", {})
    require(isinstance(supplied, dict) and not set(supplied) - set(defaults),
            "qwen_settings_invalid", "Only documented Qwen 2.1 settings are supported")
    # Canvas and conditioning resolution must never inherit an upstream default.
    require("output_resolution" in supplied and "use_kv_cache" in supplied,
            "qwen_settings_invalid", "Explicitly freeze output_resolution and use_kv_cache")
    settings = {**defaults, **supplied}
    require(type(settings["num_inference_steps"]) is int and settings["num_inference_steps"] > 0
            and type(settings["output_resolution"]) is int and settings["output_resolution"] > 0
            and type(settings["num_images_per_prompt"]) is int and settings["num_images_per_prompt"] == 1,
            "qwen_settings_invalid", "Use positive steps/resolution and request exactly one image")
    require(type(settings["true_cfg_scale"]) in {int, float} and math.isfinite(settings["true_cfg_scale"]) and settings["true_cfg_scale"] > 0
            and isinstance(settings["negative_prompt"], str) and type(settings["use_kv_cache"]) is bool,
            "qwen_settings_invalid", "Invalid CFG, negative prompt or KV-cache setting")
    images = load_images(request, "RGBA")
    output_dir = Path(output_dir).resolve()
    require(not output_dir.exists() or output_dir.is_dir(), "native_output_exists", "Output destination must be a directory")
    output_dir.mkdir(parents=True, exist_ok=True)
    require(not list(output_dir.glob("native_*.png")), "native_output_exists", "Use a fresh native output directory before generation")
    width, height = request["canvas"]["width"], request["canvas"]["height"]
    require(type(width) is int and type(height) is int and width > 0 and height > 0 and width % 32 == height % 32 == 0,
            "qwen_canvas_unsupported", "Qwen 2.1 needs a canvas divisible by 32; prepare geometry before execution")
    try:
        import torch
        import diffusers
    except ImportError as exc:
        raise HREError("qwen_dependency_missing", "Deploy the locked Qwen torch/Diffusers runtime before execution") from exc
    require(config.get("pipeline_version") == diffusers.__version__, "qwen_pipeline_version_mismatch",
            "Installed Diffusers differs from the frozen pipeline_version")
    pipeline_class = getattr(diffusers, "QwenImage21Pipeline", None)
    require(pipeline_class is not None, "qwen_dependency_missing", "This Diffusers build lacks QwenImage21Pipeline")
    source = verify_module(importlib.import_module(pipeline_class.__module__),
                           "pipelines/qwenimage21/pipeline_qwenimage21.py")

    def factory():
        return pipeline_class.from_pretrained(
            identity["local_path"], local_files_only=True, torch_dtype=getattr(torch, dtype),
        ).to(device)

    pipe = runtime_get({"adapter": ADAPTER_VERSION, "kind": "image", "identity": identity,
                        "device": device, "dtype": dtype, "pipeline_version": diffusers.__version__,
                        "pipeline_source": source}, factory)
    pipeline_config = getattr(pipe, "config", None)
    configured_sigmas = (pipeline_config.get("sample_sigmas") if isinstance(pipeline_config, dict)
                         else getattr(pipeline_config, "sample_sigmas", None))
    require(configured_sigmas is None, "qwen_checkpoint_schedule_mismatch",
            "The original Qwen 2.1 adapter cannot silently use a configured Turbo sampling schedule")
    generator = torch.Generator(device=device).manual_seed(request["seed"])
    kwargs = {**settings, "image": images, "prompt": condition["text"], "width": width, "height": height,
              "generator": generator}
    observation = {
        "adapter_version": ADAPTER_VERSION, "model_identity": identity, "pipeline_class": "QwenImage21Pipeline",
        "packages": {**package_versions(), "diffusers": diffusers.__version__},
        "upstream_code": {"pipeline": source}, "inspected_diffusers_commit": DIFFUSERS_COMMIT,
        "settings": {**deepcopy(settings), "width": width, "height": height, "seed": request["seed"],
                     "device": device, "torch_dtype": dtype},
        "input_roles": [asset["role"] for asset in request["inputs"]], "input_modes": [image.mode for image in images],
        "input_sizes": [list(image.size) for image in images], "prompt_sha256": sha256(condition["text"].encode()).hexdigest(),
        "image_calls_attempted": 1, "image_calls_completed": 0, "prompt_rewrite_during_execution": False,
        "fallback_used": False, "output_normalization": "none_native_outputs_preserved",
    }
    started = time.monotonic()
    try:
        with torch.inference_mode():
            result = pipe(**kwargs)
    except Exception as exc:
        observation["elapsed_seconds"] = time.monotonic() - started
        error = HREError("qwen_generation_failed", "Qwen generation failed; no automatic retry or parameter change occurred")
        error.observation = observation
        raise error from exc
    observation.update(image_calls_completed=1, elapsed_seconds=time.monotonic() - started)
    try:
        return save_outputs(getattr(result, "images", None), output_dir, observation)
    except HREError as exc:
        exc.observation = observation
        raise
