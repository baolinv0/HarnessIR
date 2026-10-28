"""Optional native compiler/editor workers for ``hre lab`` command models.

Run in each model's own Python environment, for example::

    python -m hre.stage_lab.native_workers flux3 --request request.json --output response.json

Workers: flux3 (PUP + official editor), fibo (bria-vgl + Diffusers),
qwen_pe (official prompt_rewrite code), qwen21 (Diffusers), firered
(official text Recaption + Diffusers). Imports are lazy; the lab itself does
not require torch, Diffusers, vLLM or model weights. Install the corresponding
official runtime separately. ``parameters.native_repo`` points at a checked-out
FLUX/Qwen/FireRed repository when it is not installed. ``checkpoint``, ``device``,
``dtype``, ``seed``, ``load`` and ``inference`` configure the runtime. FLUX also
accepts ``weights_dir``, ``model_variant``, ``dit_path`` and ``pup_checkpoint``.

Native compilers receive context.instruction, an upstream plan, or the supplied
prompt. Editors consume an upstream compile result without silently recompiling
it. Outputs retain the actual generated size; no resize or blending is applied.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import sys
import warnings
from typing import Any

from .prompts import parse_condition


WORKERS = ("flux3", "fibo", "qwen_pe", "qwen21", "firered")
FIBO_NEGATIVE_EDIT = {
    "short_description": "", "objects": [], "background_setting": "",
    "lighting": {}, "aesthetics": {}, "photographic_characteristics": {},
    "style_medium": "", "context": "", "artistic_style": "",
}


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


def _upstream(request: dict, stage: str) -> list[dict]:
    return [item for item in request.get("context", {}).get("upstream", [])
            if item.get("stage") == stage]


def instruction(request: dict) -> str:
    """Extract the operation, not a surrounding JSON-output task template."""
    context = request.get("context", {})
    if request.get("prompt_override"):
        return request["prompt"]
    for key in ("instruction", "edit_prompt", "action"):
        if context.get(key):
            return _text(context[key])
    plans = _upstream(request, "plan")
    if plans:
        item = plans[-1]
        data = item.get("data") or {}
        if isinstance(data, dict):
            for key in ("edit_prompt", "instruction"):
                if data.get(key):
                    return _text(data[key])
        return item.get("text") or _text(data)
    return request["prompt"]


def compiled_condition(request: dict) -> tuple[str, dict, bool]:
    """Return exact native prompt, structured condition and whether compiled."""
    items = _upstream(request, "compile")
    context = request.get("context", {})
    if request.get("prompt_override"):
        return request["prompt"], {"native_prompt": request["prompt"]}, bool(items or context.get("condition") is not None)
    if items:
        data = items[-1].get("data")
        raw = items[-1].get("text", "")
    elif context.get("condition") is not None:
        data, raw = context["condition"], ""
    else:
        return instruction(request), {}, False
    condition = parse_condition(data, raw)
    if condition:
        return condition[0], condition[1], True
    raise ValueError("Selected compile result has no native prompt. Supply context.condition or select another result.")


def _setup(params: dict, worker: str) -> None:
    repo = params.get("native_repo")
    if repo:
        root = Path(repo).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"native_repo does not exist: {root}")
        sys.path.insert(0, str(root))
        if (root / "src").is_dir():
            sys.path.insert(0, str(root / "src"))
        if worker in ("qwen_pe", "qwen21"):
            sys.path.insert(0, str(root / "prompt_rewrite"))
    if worker == "flux3" and params.get("weights_dir"):
        os.environ["WEIGHTS_DIR"] = str(Path(params["weights_dir"]).expanduser().resolve())


def _images(request: dict) -> list:
    from PIL import Image, ImageOps
    result = []
    for item in request.get("images", []):
        if item.get("role") in ("A", "B"):
            with Image.open(item["path"]) as im:
                result.append(ImageOps.exif_transpose(im).convert("RGB"))
    if not result:
        raise ValueError("Native reference editing requires image A (and optionally B).")
    return result


def _result(text: str = "", data: Any = None, images: list[str] | None = None,
            **metadata: Any) -> dict:
    return {"text": text, "data": data, "images": images or [], "usage": {}, "metadata": metadata}


def _save(image, output: Path) -> list[str]:
    target = output.parent / "output.png"
    image.save(target)
    return [str(target.resolve())]


def _torch(params: dict):
    import torch
    dtype = getattr(torch, params.get("dtype", "bfloat16"))
    device = params.get("device", "cuda")
    generator_device = "cpu" if str(device).startswith("mps") else device
    seed = int(params.get("seed", 42))
    return torch, dtype, device, torch.Generator(generator_device).manual_seed(seed)


def _load_pipeline(cls, checkpoint: str, params: dict, *, dtype_keyword="torch_dtype"):
    torch, dtype, device, generator = _torch(params)
    kwargs = dict(params.get("load", {}))
    kwargs[dtype_keyword] = dtype
    pipe = cls.from_pretrained(checkpoint, **kwargs)
    if params.get("cpu_offload"):
        pipe.enable_model_cpu_offload()
    elif "device_map" not in kwargs:
        pipe.to(device)
    return pipe, torch, generator


def _flux3(request: dict, output: Path, params: dict) -> dict:
    images = _images(request)
    if request["stage"] == "compile":
        from flux3.pup import Upsampler, MODEL
        checkpoint = params.get("pup_checkpoint", MODEL)
        upsampler = Upsampler(checkpoint, float(params.get("pup_memory", .85)))
        prompt = upsampler(instruction(request), images, params.get("boxes"))
        template = json.dumps(upsampler.prompts, ensure_ascii=False, sort_keys=True)
        return _result(prompt, {"native_prompt": prompt}, worker="flux3_pup", checkpoint=checkpoint,
                       system_prompts_sha256=hashlib.sha256(template.encode()).hexdigest())
    from flux3.generate import Models, generate
    from flux3.pipeline import dit_path, WEIGHTS
    prompt, condition, compiled = compiled_condition(request)
    variant = params.get("model_variant", "distilled")
    use_pup = bool(params.get("use_pup", not compiled))
    checkpoint = params.get("dit_path") or str(dit_path(variant, params.get("quant", "")))
    pup = params.get("pup_checkpoint", str(WEIGHTS / "pup")) if use_pup else None
    models = Models({variant: checkpoint}, pup=pup, pup_memory=float(params.get("pup_memory", .35)),
                    offload=bool(params.get("cpu_offload", False)))
    kwargs = dict(params.get("inference", {}))
    kwargs.setdefault("seed", int(params.get("seed", 42)))
    # A selected compile output is sent unchanged unless explicitly re-PUP'd.
    kwargs["pup"] = use_pup
    if params.get("boxes") is not None:
        kwargs.setdefault("boxes", params["boxes"])
    image, record = generate(models, variant, prompt, images=images, **kwargs)
    return _result(images=_save(image, output), data=record, worker="flux3", checkpoint=checkpoint,
                   native_record=record, compiled_input=compiled)


def _fibo(request: dict, output: Path, params: dict) -> dict:
    images = _images(request)
    if request["stage"] == "compile":
        from bria_vgl import modify, DEFAULT_LLM
        from bria_vgl.dialects.thales import EditImages, EditImageWithMask
        kwargs = dict(params.get("compiler", {}))
        kwargs.setdefault("llm", DEFAULT_LLM)
        kwargs.setdefault("seed", int(params.get("seed", 42)))
        if params.get("mask"):
            if len(images) != 1:
                raise ValueError("The bria-vgl Mask workflow accepts one image; A+B+Mask is not this interface.")
            from PIL import Image
            payload = EditImageWithMask(prompt=instruction(request), image=images[0],
                                        mask=Image.open(params["mask"]).convert("L"))
        else:
            payload = EditImages(prompt=instruction(request), images=images)
        scene = modify(payload, **kwargs)
        data = scene.model_dump(exclude_none=True)
        return _result(_text(data), {"vgl": data}, worker="bria_vgl", compiler_options=kwargs)
    from diffusers import BriaFibo2Pipeline
    prompt, condition, compiled = compiled_condition(request)
    if not compiled:
        # Native direct baseline uses bria-vgl; retain its actual output.
        built = _fibo({**request, "stage": "compile"}, output, params)
        condition = built["data"]
        prompt = _text(condition["vgl"])
    checkpoint = params.get("checkpoint", "briaai/Fibo-2.0-dev")
    pipe, torch, generator = _load_pipeline(BriaFibo2Pipeline, checkpoint, params, dtype_keyword="dtype")
    kwargs = {"num_inference_steps": 50, "guidance_scale": 5.0,
              "negative_prompt": _text(FIBO_NEGATIVE_EDIT), **params.get("inference", {})}
    fonts = params.get("fonts")
    if fonts is None:
        names = ["Aileron-Regular.otf", "DejaVuSans.ttf"]
        local = Path(checkpoint)
        if local.is_dir():
            fonts = [str(local / "fonts" / name) for name in names]
        else:
            from huggingface_hub import hf_hub_download
            fonts = [hf_hub_download(checkpoint, name, subfolder="fonts") for name in names]
    kwargs.setdefault("fonts", fonts)
    if params.get("mask"):
        if len(images) != 1:
            raise ValueError("This worker supports the single-image Mask route, not unverified A+B+Mask composition.")
        from PIL import Image
        kwargs["mask"] = Image.open(params["mask"]).convert("L")
    with torch.inference_mode():
        image = pipe(prompt=prompt, image=images if len(images) > 1 else images[0],
                     generator=generator, **kwargs).images[0]
    return _result(images=_save(image, output), data={"native_prompt": prompt, **condition},
                   worker="fibo", checkpoint=checkpoint, inference=kwargs, seed=params.get("seed", 42))


def _qwen_pe(request: dict, output: Path, params: dict) -> dict:
    if request["stage"] != "compile":
        raise ValueError("qwen_pe is a compile worker. Use qwen21 for image execution.")
    # Reuse the official sampling / multimodal formatting implementation.
    core = importlib.import_module("pe_core")
    runner = importlib.import_module("run_transformers")
    from transformers import AutoModelForImageTextToText, AutoProcessor
    torch, dtype, device, _ = _torch(params)
    checkpoint = params.get("checkpoint", "Qwen/Qwen-Image-2.1-PE-I2I")
    system_path = params.get("system_prompt")
    if system_path is None and not (Path(checkpoint) / "system_prompt.txt").is_file():
        from huggingface_hub import hf_hub_download
        system_path = hf_hub_download(checkpoint, "system_prompt.txt")
    system = core.load_system_prompt(system_path, checkpoint)
    profile = core.get_profile("edit")
    processor = AutoProcessor.from_pretrained(checkpoint)
    load_options = {"dtype": dtype, "low_cpu_mem_usage": True, **params.get("load", {})}
    model = AutoModelForImageTextToText.from_pretrained(checkpoint, **load_options).to(device).eval()
    image_paths = [Path(x["path"]) for x in request.get("images", []) if x.get("role") in ("A", "B")]
    if not image_paths:
        raise ValueError("PE-I2I requires input images.")
    images = [core.load_image(p, params.get("image_max_pixels", profile.image_max_pixels)) for p in image_paths]
    sampling = {name: params.get(name, getattr(profile, name)) for name in
                ("max_new_tokens", "temperature", "top_p", "top_k", "presence_penalty")}
    # The official model needs thinking enabled, but the lab records only its answer.
    _, answer = runner.rewrite(model, processor, core.build_messages(system, instruction(request), images),
                               seed=int(params.get("seed", 42)), **sampling)
    data = core.parse_answer(answer, profile)
    data["rewritten_prompt"] = data.pop("positive_prompt")
    return _result(answer, data, worker="qwen_pe", checkpoint=checkpoint, sampling=sampling,
                   system_prompt_sha256=hashlib.sha256(system.encode()).hexdigest())


def _canvas(condition: dict, images: list, kwargs: dict) -> dict:
    """Honor explicit sizes first, then PE's canvas fields without resampling input."""
    if "width" in kwargs or "height" in kwargs:
        return kwargs
    follow = condition.get("ratio_follow", "")
    if follow:
        match = re.fullmatch(r"<image(\d+)>", follow)
        if not match or not 1 <= int(match[1]) <= len(images):
            raise ValueError(f"Invalid PE canvas reference: {follow!r}")
        kwargs["width"], kwargs["height"] = images[int(match[1]) - 1].size
    elif condition.get("wh_ratio"):
        sizes = {"1:1": (2048, 2048), "4:3": (2400, 1792), "3:4": (1792, 2400),
                 "3:2": (2528, 1696), "2:3": (1696, 2528), "16:9": (2752, 1536), "9:16": (1536, 2752)}
        ratio = condition["wh_ratio"]
        if ratio not in sizes:
            raise ValueError(f"PE returned {ratio!r}; set inference.width and inference.height explicitly.")
        kwargs["width"], kwargs["height"] = sizes[ratio]
    return kwargs


def _qwen21(request: dict, output: Path, params: dict) -> dict:
    if request["stage"] == "compile":
        pe_params = {**params, "checkpoint": params.get("pe_checkpoint", "Qwen/Qwen-Image-2.1-PE-I2I")}
        return _qwen_pe(request, output, pe_params)
    from diffusers import QwenImage21Pipeline
    images = _images(request)
    prompt, condition, compiled = compiled_condition(request)
    checkpoint = params.get("checkpoint", "Qwen/Qwen-Image-2.1")
    pipe, torch, generator = _load_pipeline(QwenImage21Pipeline, checkpoint, params)
    kwargs = _canvas(condition, images, {"num_inference_steps": 40, **params.get("inference", {})})
    with torch.inference_mode():
        image = pipe(prompt=prompt, image=images, generator=generator, **kwargs).images[0]
    return _result(images=_save(image, output), data={"native_prompt": prompt, "condition": condition},
                   worker="qwen21", checkpoint=checkpoint, inference=kwargs, compiled_input=compiled,
                   seed=params.get("seed", 42))


def _firered(request: dict, output: Path, params: dict) -> dict:
    if request["stage"] == "compile":
        from agent.recaption import recaption
        from agent.config import GEMINI_MODEL_NAME
        n_images = len([x for x in request.get("images", []) if x.get("role") in ("A", "B")])
        original = instruction(request)
        with warnings.catch_warnings(record=True) as seen:
            warnings.simplefilter("always", RuntimeWarning)
            prompt = recaption(original, [[i] for i in range(n_images)],
                               target_length=int(params.get("target_length", 512)))
        failures = [str(w.message) for w in seen if issubclass(w.category, RuntimeWarning)
                    and ("Skipping recaption" in str(w.message) or "Falling back" in str(w.message))]
        if failures:
            raise RuntimeError("FireRed Recaption failed: " + "; ".join(failures))
        provider = os.environ.get("RECAPTION_PROVIDER", "gemini").lower()
        compiler_model = (GEMINI_MODEL_NAME if provider == "gemini" else
                          os.environ.get("OPENAI_COMPATIBLE_MODEL", "MiniMax-M2.7"))
        return _result(prompt, {"native_prompt": prompt}, worker="firered_recaption", text_only=True,
                       changed=prompt != original, recaption_provider=provider, compiler_model=compiler_model)
    from diffusers import QwenImageEditPlusPipeline
    images = _images(request)
    if len(images) > 3:
        raise ValueError("Use the official multi-image Agent preprocessing before this worker for >3 images.")
    prompt, condition, compiled = compiled_condition(request)
    checkpoint = params.get("checkpoint", "FireRedTeam/FireRed-Image-Edit-1.1")
    pipe, torch, generator = _load_pipeline(QwenImageEditPlusPipeline, checkpoint, params)
    kwargs = {"num_inference_steps": 40, "true_cfg_scale": 4.0, "negative_prompt": " ",
              "num_images_per_prompt": 1, **params.get("inference", {})}
    with torch.inference_mode():
        image = pipe(prompt=prompt, image=images, generator=generator, **kwargs).images[0]
    return _result(images=_save(image, output), data={"native_prompt": prompt},
                   worker="firered", checkpoint=checkpoint, inference=kwargs,
                   compiled_input=compiled, seed=params.get("seed", 42))


def run_native(worker: str, request: dict, output: Path) -> dict:
    if worker not in WORKERS:
        raise ValueError(f"Unknown native worker {worker!r}; choose {', '.join(WORKERS)}")
    if request.get("stage") not in ("compile", "execute"):
        raise ValueError("Native workers support compile/execute. Use a VLM provider for diagnose/plan/judge.")
    params = request.get("parameters", {})
    _setup(params, worker)
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    function = {"flux3": _flux3, "fibo": _fibo, "qwen_pe": _qwen_pe,
                "qwen21": _qwen21, "firered": _firered}[worker]
    try:
        return function(request, output, params)
    except ImportError as exc:
        raise RuntimeError(f"{worker} native runtime is missing {exc.name!r}. Run this worker in its official "
                           "environment and set parameters.native_repo when using a repository checkout.") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("worker", choices=WORKERS)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    request = json.loads(args.request.read_text(encoding="utf-8"))
    for item in request.get("images", []):
        path = Path(item["path"])
        if not path.is_absolute():
            item["path"] = str((args.request.parent / path).resolve())
    try:
        result = run_native(args.worker, request, args.output)
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
