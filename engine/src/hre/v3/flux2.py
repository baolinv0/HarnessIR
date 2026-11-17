"""The pinned, distilled FLUX.2 Klein 4B image editing path."""
from __future__ import annotations

import inspect
from pathlib import Path

from ..models import HREError, file_sha256
from .common import load_images, model_identity, package_versions, require, runtime_get, save_outputs

MODEL_ID = "black-forest-labs/FLUX.2-klein-4B"


def generate(request: dict, condition: dict, config: dict, output_dir: Path) -> dict:
    require(config.get("settings", {}) == {}, "flux2_settings_invalid",
            "The distilled 4B profile uses its fixed four-step guidance-free recipe")
    identity = model_identity(config, MODEL_ID)
    device = config.get("device", "cuda:0")
    dtype = config.get("torch_dtype", "bfloat16")
    require(isinstance(device, str) and (device == "cpu" or device.startswith("cuda"))
            and dtype in {"bfloat16", "float16", "float32"}, "flux2_runtime_invalid", "Invalid device or dtype")
    width, height = request["canvas"]["width"], request["canvas"]["height"]
    require(width > 0 and height > 0 and width % 16 == height % 16 == 0,
            "flux2_canvas_invalid", "FLUX.2 Klein requires a 16-pixel grid")
    images = load_images(request, "RGB")
    require(not list(output_dir.glob("native_*.png")), "native_output_exists", "Use a fresh native output directory")

    try:
        import diffusers
        import torch
        from diffusers import Flux2KleinPipeline
    except ImportError as exc:
        raise HREError("flux2_dependency_missing", "Deploy a Diffusers build with Flux2KleinPipeline") from exc
    require(config.get("pipeline_version") == diffusers.__version__, "flux2_pipeline_version_mismatch",
            "Installed Diffusers differs from the frozen version")
    source_hash = file_sha256(Path(inspect.getfile(Flux2KleinPipeline)))
    runtime = {"adapter_version": "hre.flux2.klein4b.v1", "model_identity": identity,
               "device": device, "torch_dtype": dtype, "pipeline_version": diffusers.__version__,
               "pipeline_source_sha256": source_hash}

    def load():
        return Flux2KleinPipeline.from_pretrained(
            identity["local_path"], local_files_only=True, torch_dtype=getattr(torch, dtype),
        ).to(device)

    pipeline = runtime_get(runtime, load)
    settings = {"width": width, "height": height, "num_inference_steps": 4, "guidance_scale": 1.0,
                "num_images_per_prompt": 1}
    with torch.inference_mode():
        result = pipeline(image=images[0] if len(images) == 1 else images, prompt=condition["text"],
                          generator=torch.Generator(device=device).manual_seed(request["seed"]), **settings)
    return save_outputs(result.images, output_dir, {
        **runtime, "packages": package_versions(), "settings": {**settings, "seed": request["seed"]},
        "input_roles": [row["role"] for row in request["inputs"]], "image_calls_attempted": 1,
        "image_calls_completed": 1, "prompt_rewrite_during_execution": False, "fallback_used": False,
    })
