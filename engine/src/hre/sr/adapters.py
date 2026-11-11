"""Offline invocation of the three fixed SR model deployments."""
from __future__ import annotations

from copy import deepcopy
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from PIL import Image

from ..models import HREError, file_sha256
from ..storage import read_json
from ..v3.common import digest, require
from ..v3.runner_journal import immutable_json


VERSION = "hre_sr_native_v02.1"
RECONSTRUCTION_REVISION = "a4abfb2979a7bbff3f69f58f58ae324608821e27"
SEESR_REVISION = "b13b8ac3bbcc6b9a6baa970ee5349628070877ee"
QWEN_PROMPT = ("Super-resolve this low-resolution image to the requested output canvas. "
               "Preserve the same scene, identities, lettering, object positions, colors and lighting. "
               "Restore legible structure conservatively without inventing objects, text or texture.")
RECONSTRUCTION_SETTINGS = {"tile": 0, "tile_pad": 10, "pre_pad": 0, "fp32": True, "gpu_id": 0}
SEESR_SETTINGS = {
    "prompt": "", "added_prompt": "clean, high-resolution, 8k",
    "negative_prompt": "dotted, noise, blur, lowres, smooth", "mixed_precision": "fp16",
    "guidance_scale": 5.5, "conditioning_scale": 1.0, "blending_alpha": 1.0,
    "num_inference_steps": 50, "process_size": 512, "vae_decoder_tiled_size": 224,
    "vae_encoder_tiled_size": 1024, "latent_tiled_size": 96, "latent_tiled_overlap": 4,
    "upscale": 4, "sample_times": 1, "align_method": "adain", "start_steps": 999,
    "start_point": "lr", "save_prompts": True,
}
QWEN_SETTINGS = {"num_inference_steps": 40, "true_cfg_scale": 1.0, "negative_prompt": "",
                 "num_images_per_prompt": 1, "output_resolution": 1024, "use_kv_cache": True}
_HASH_CACHE: dict[str, tuple[tuple, str]] = {}


def _deployment_hash(path: Path) -> str:
    stat = path.stat()
    key = str(path.resolve())
    signature = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    previous = _HASH_CACHE.get(key)
    if previous is not None and previous[0] == signature:
        return previous[1]
    checksum = file_sha256(path)
    after = path.stat()
    require(signature == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
            "sr_deployment_modified", "Deployment file changed while hashing")
    _HASH_CACHE[key] = (signature, checksum)
    return checksum


def _settings(supplied: dict, defaults: dict, key: str) -> dict:
    require(isinstance(supplied, dict) and not set(supplied) - set(defaults),
            "sr_model_config_invalid", f"Unknown {key} setting")
    result = {**defaults, **supplied}
    for name, default in defaults.items():
        value = result[name]
        if type(default) is bool:
            valid = type(value) is bool
        elif type(default) is int:
            valid = type(value) is int and value >= 0
        elif type(default) is float:
            valid = type(value) in {int, float} and math.isfinite(value) and value > 0
        else:
            valid = isinstance(value, str)
        require(valid, "sr_model_config_invalid", f"Invalid {key}.{name}")
    return result


def normalise_models(models: dict) -> dict:
    require(isinstance(models, dict) and not set(models) - {"reconstruction", "seesr", "qwen"},
            "sr_model_config_invalid", "Configure only reconstruction, seesr and qwen")
    result = {}
    paths = {
        "reconstruction": {"python", "repo", "checkpoint", "runtime_lock"},
        "seesr": {"python", "repo", "pretrained_model_path", "seesr_model_path", "ram_ft_path", "bert_path", "runtime_lock"},
        "qwen": {"local_path", "deployment_manifest", "runtime_lock"},
    }
    defaults = {"reconstruction": RECONSTRUCTION_SETTINGS, "seesr": SEESR_SETTINGS, "qwen": QWEN_SETTINGS}
    for key in defaults:
        value = deepcopy(models.get(key, {}))
        allowed = paths[key] | {"revision", "settings"}
        allowed |= {"model_id", "pipeline_version", "device", "torch_dtype"} if key == "qwen" else {"timeout_seconds"}
        require(isinstance(value, dict) and not set(value) - allowed,
                "sr_model_config_invalid", f"Unknown {key} configuration key")
        for name in paths[key]:
            path = value.setdefault(name, "")
            require(isinstance(path, str), "sr_model_config_invalid", f"{key}.{name} must be a local path")
            if path:
                require("://" not in path, "sr_model_config_invalid", "Model deployments must be local")
                value[name] = str(Path(path).expanduser().absolute())
        value["settings"] = _settings(value.get("settings", {}), defaults[key], key)
        if key == "qwen":
            value.setdefault("revision", "")
            value.setdefault("model_id", "Qwen/Qwen-Image-2.1")
            value.setdefault("pipeline_version", "")
            value.setdefault("device", "cuda")
            value.setdefault("torch_dtype", "bfloat16")
            require(value["model_id"] == "Qwen/Qwen-Image-2.1" and value["device"] == "cuda"
                    and value["torch_dtype"] in {"bfloat16", "float16", "float32"}
                    and isinstance(value["pipeline_version"], str), "sr_model_config_invalid", "Unsupported Qwen deployment")
            require(isinstance(value["revision"], str) and (not value["revision"]
                    or re.fullmatch(r"[0-9a-f]{40}", value["revision"])),
                    "sr_model_config_invalid", "Qwen revision must be a frozen 40-character hash")
            require(value["settings"]["num_inference_steps"] > 0 and value["settings"]["output_resolution"] > 0
                    and value["settings"]["num_images_per_prompt"] == 1,
                    "sr_model_config_invalid", "Qwen needs positive steps/resolution and one output")
        else:
            revision = RECONSTRUCTION_REVISION if key == "reconstruction" else SEESR_REVISION
            value.setdefault("revision", revision)
            require(value["revision"] == revision, "sr_model_config_invalid", f"Use the inspected {key} revision")
            timeout = value.setdefault("timeout_seconds", 1800 if key == "reconstruction" else 3600)
            require(type(timeout) in {int, float} and math.isfinite(timeout) and timeout > 0,
                    "sr_model_config_invalid", "timeout_seconds must be finite and positive")
        if key == "reconstruction":
            require(value["settings"]["fp32"] is True, "sr_model_config_invalid", "The reconstruction profile freezes fp32")
        if key == "seesr":
            settings = value["settings"]
            require((settings["process_size"], settings["upscale"], settings["sample_times"]) == (512, 4, 1)
                    and settings["mixed_precision"] in {"no", "fp16", "bf16"}
                    and settings["align_method"] in {"wavelet", "adain", "nofix"}
                    and settings["start_point"] in {"lr", "noise"} and settings["save_prompts"] is True
                    and all(settings[name] > 0 for name in ("num_inference_steps", "vae_decoder_tiled_size",
                                                            "vae_encoder_tiled_size", "latent_tiled_size"))
                    and settings["latent_tiled_overlap"] < settings["latent_tiled_size"],
                    "sr_model_config_invalid", "Unsupported SeeSR native geometry or settings")
        result[key] = value
    return result


def _file(path: str | Path, blockers: list[str], label: str) -> dict:
    candidate = Path(path) if path else None
    if candidate is None or not candidate.is_file():
        blockers.append(f"Missing {label}")
        return {"path": str(path), "status": "missing"}
    return {"path": str(candidate.absolute()), "sha256": _deployment_hash(candidate), "size": candidate.stat().st_size}


def _tree(path: str, blockers: list[str], label: str, required: tuple[str, ...] = (),
          weighted: tuple[str, ...] = ()) -> dict:
    directory = Path(path) if path else None
    if directory is None or not directory.is_dir():
        blockers.append(f"Missing {label} directory")
        return {"path": path, "status": "missing"}
    for name in required:
        if not (directory / name).exists():
            blockers.append(f"Missing {label}/{name}")
    for name in weighted:
        if not any(item.is_file() and item.suffix in {".safetensors", ".bin", ".pth"}
                   for item in (directory / name).rglob("*")):
            blockers.append(f"Missing weight files in {label}/{name}")
    files = [{"path": item.relative_to(directory).as_posix(), "sha256": _deployment_hash(item), "size": item.stat().st_size}
             for item in sorted(directory.rglob("*")) if item.is_file() and ".git" not in item.relative_to(directory).parts]
    if not files:
        blockers.append(f"Empty {label} directory")
    return {"path": str(directory.absolute()), "files": files, "manifest_sha256": digest(files)}


def _checkout(config: dict, blockers: list[str], script: str) -> dict:
    repo = Path(config["repo"]) if config["repo"] else None
    if repo is None or not repo.is_dir():
        blockers.append("Missing official source checkout")
        return {"path": config["repo"], "revision": config["revision"], "status": "missing"}
    try:
        head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
        dirty = subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=no"], text=True).strip()
        if head != config["revision"] or dirty:
            blockers.append("Official checkout revision differs or tracked files are modified")
    except (subprocess.SubprocessError, OSError):
        blockers.append("Cannot verify official source checkout")
        head, dirty = None, None
    return {"path": str(repo.absolute()), "revision": head, "dirty": dirty,
            "script": _file(repo / script, blockers, script)}


_PROBE = r'''
import importlib, importlib.metadata, json, sys
kind, bert = sys.argv[1:]
names = {"reconstruction": ["torch", "torchvision", "basicsr", "realesrgan", "cv2"],
         "seesr": ["torch", "torchvision", "diffusers", "transformers", "accelerate", "xformers", "cv2"],
         "qwen": ["torch", "diffusers", "transformers", "accelerate"]}[kind]
result = {"python_version": sys.version, "packages": {}, "errors": []}
for name in names:
    try:
        module = importlib.import_module(name)
        result["packages"][name] = getattr(module, "__version__", None)
    except Exception as error:
        result["errors"].append(name + ": " + type(error).__name__)
try:
    import torch
    result["cuda_available"] = bool(torch.cuda.is_available())
    result["cuda_version"] = torch.version.cuda
except Exception:
    result["cuda_available"] = False
if kind == "seesr":
    try:
        from transformers import BertTokenizer
        BertTokenizer.from_pretrained(bert, local_files_only=True)
    except Exception as error:
        result["errors"].append("bert tokenizer: " + type(error).__name__)
if kind in {"reconstruction", "seesr"}:
    try:
        importlib.import_module("inference_realesrgan" if kind == "reconstruction" else "test_seesr")
    except Exception as error:
        result["errors"].append("official script imports: " + type(error).__name__)
if kind == "qwen":
    try:
        from diffusers import QwenImage21Pipeline
        result["pipeline_source"] = importlib.import_module(QwenImage21Pipeline.__module__).__file__
    except Exception as error:
        result["errors"].append("QwenImage21Pipeline: " + type(error).__name__)
print(json.dumps(result))
'''


def _environment(seed: int = 0) -> dict:
    return {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1",
            "PYTHONHASHSEED": str(seed % (2**32)), "TOKENIZERS_PARALLELISM": "false"}


def _inspect(key: str, config: dict) -> dict:
    blockers = []
    identity = {"adapter": VERSION, "adapter_sha256": file_sha256(Path(__file__)), "config_sha256": digest(config),
                "weight_identity_basis": "operator_deployed_local_files_fully_hashed",
                "launcher": _file(Path(__file__).with_name("_official.py"), blockers, "SR official launcher")}
    python = config.get("python", sys.executable)
    identity["python"] = _file(python, blockers, "Python executable")
    if python and not os.access(python, os.X_OK):
        blockers.append("Python is not executable")
    if config["runtime_lock"]:
        identity["runtime_lock"] = _file(config["runtime_lock"], blockers, "runtime lock")
    if key == "reconstruction":
        identity["model_id"] = "RealESRNet_x4plus"
        identity["checkpoint"] = _file(config["checkpoint"], blockers, "RealESRNet_x4plus checkpoint")
        identity["checkout"] = _checkout(config, blockers, "inference_realesrgan.py")
    elif key == "seesr":
        identity["model_id"] = "SeeSR"
        identity["checkout"] = _checkout(config, blockers, "test_seesr.py")
        identity["base"] = _tree(config["pretrained_model_path"], blockers, "SD2 base",
                                 ("scheduler", "text_encoder", "tokenizer", "vae", "feature_extractor"), ("text_encoder", "vae"))
        identity["seesr"] = _tree(config["seesr_model_path"], blockers, "SeeSR checkpoint", ("unet", "controlnet"), ("unet", "controlnet"))
        identity["dape"] = _file(config["ram_ft_path"], blockers, "DAPE checkpoint")
        identity["ram"] = _file(Path(config["repo"]) / "preset/models/ram_swin_large_14m.pth" if config["repo"] else "",
                                 blockers, "RAM base checkpoint")
        identity["bert"] = _tree(config["bert_path"], blockers, "bert-base-uncased tokenizer", ("vocab.txt",))
    else:
        identity["model_id"] = config["model_id"]
        identity["revision"] = config["revision"]
        identity["weights"] = _tree(config["local_path"], blockers, "Qwen checkpoint", ("model_index.json",), (".",))
        identity["deployment_manifest"] = _file(config["deployment_manifest"], blockers, "Qwen deployment manifest")
        if not config["revision"] or not config["pipeline_version"]:
            blockers.append("Qwen revision and pipeline_version are required")
    if python and Path(python).is_file() and os.access(python, os.X_OK):
        try:
            probe = subprocess.run([python, "-c", _PROBE, key, config.get("bert_path", "")],
                                   cwd=config.get("repo") or None, env=_environment(), capture_output=True, text=True, timeout=45)
            require(probe.returncode == 0, "sr_probe_failed", "Python deployment probe failed")
            runtime = json.loads(probe.stdout.strip().splitlines()[-1])
            identity["runtime"] = runtime
            blockers.extend(runtime["errors"])
            if not runtime["cuda_available"]:
                blockers.append("CUDA is unavailable in the configured Python runtime")
            if key == "qwen" and runtime["packages"].get("diffusers") != config["pipeline_version"]:
                blockers.append("Qwen Diffusers version differs from pipeline_version")
            if key == "qwen" and runtime.get("pipeline_source"):
                from ..v3.native_sources import verify_source_file
                identity["pipeline_source"] = verify_source_file(Path(runtime["pipeline_source"]), "pipelines/qwenimage21/pipeline_qwenimage21.py")
        except (HREError, OSError, ValueError, IndexError, subprocess.SubprocessError):
            blockers.append("Unable to inspect Python dependencies and CUDA")
    return {"status": "blocked" if blockers else "ready", "identity": identity, "blockers": blockers}


def inspect_deployments(models: dict) -> dict:
    models = normalise_models(models)
    return {key: _inspect(key, value) for key, value in models.items()}


def command(request: dict, config: dict, output_dir: Path) -> list[str]:
    """The exact executable argv, retained in each operation's invocation receipt."""
    key = request["model_key"]
    require(key in {"reconstruction", "seesr"}, "sr_native_invalid", "Qwen uses its native adapter")
    source = request["input"]["path"]
    width, height = request["geometry"]["native_hr"]
    argv = [config["python"], str(Path(__file__).with_name("_official.py").resolve()), key,
            config["repo"], str(request["seed"]), str(width), str(height), str(output_dir)]
    argv += [config.get("bert_path", ""), "--"]
    if key == "reconstruction":
        argv += ["--model_name", "RealESRNet_x4plus", "--model_path", config["checkpoint"],
                 "--input", source, "--output", str(output_dir), "--outscale", "4", "--suffix", "", "--ext", "png"]
        settings = config["settings"]
        for name in ("tile", "tile_pad", "pre_pad"):
            argv += ["--" + name, str(settings[name])]
        argv += ["--fp32", "--gpu-id", str(settings["gpu_id"])]
    else:
        for name in ("pretrained_model_path", "seesr_model_path", "ram_ft_path"):
            argv += ["--" + name, config[name]]
        argv += ["--image_path", source, "--output_dir", str(output_dir), "--seed", str(request["seed"])]
        for name, value in config["settings"].items():
            argv += ["--" + name] if type(value) is bool and value else ["--" + name, str(value)]
    return argv


def _asset(path: Path) -> dict:
    value = {"path": str(path.resolve()), "sha256": file_sha256(path)}
    try:
        with Image.open(path) as image:
            image.load()
            value.update(width=image.width, height=image.height, mode=image.mode)
    except (OSError, ValueError):
        value.update(width=None, height=None, mode=None)
    return value


def run_candidate(request: dict, config: dict, output_dir: Path, *, verified_deployments: dict | None = None) -> dict:
    require(config.get("mode") == "real", "sr_native_invalid", "Native models require an explicit real deployment")
    key = request["model_key"]
    require(key == {"C0": "reconstruction", "C1": "reconstruction", "C2": "seesr", "C3": "qwen"}.get(request["slot"]),
            "sr_native_invalid", "The recipe and model deployment differ")
    models = normalise_models(config["models"])
    inspected = _inspect(key, models[key]) if verified_deployments is None else verified_deployments[key]
    require(inspected["status"] == "ready", "sr_deployment_blocked", "; ".join(inspected["blockers"]))
    require(inspected["identity"] == request["deployment"], "sr_deployment_modified", "Model deployment changed since case creation")
    require(inspected["identity"].get("config_sha256") == digest(models[key]), "sr_deployment_modified", "Inspected model configuration changed")
    if verified_deployments is not None:
        identity = inspected["identity"]
        require(file_sha256(Path(__file__)) == identity["adapter_sha256"], "sr_deployment_modified", "SR adapter changed")
        for name in ("python", "launcher", "runtime_lock"):
            if name in identity:
                item = identity[name]
                require(Path(item["path"]).is_file() and file_sha256(Path(item["path"])) == item["sha256"],
                        "sr_deployment_modified", f"Frozen {name} changed")
        if key != "qwen":
            blockers = []
            current = _checkout(models[key], blockers, "inference_realesrgan.py" if key == "reconstruction" else "test_seesr.py")
            require(not blockers and current == identity["checkout"], "sr_deployment_modified", "Official source checkout changed")
    for asset in (request["input"], request["source"]):
        require(Path(asset["path"]).is_file() and file_sha256(Path(asset["path"])) == asset["sha256"],
                "sr_input_modified", "SR conditioning/source bytes changed")
    require(type(request["seed"]) is int and 0 <= request["seed"] < 2**63, "sr_native_invalid", "Invalid SR seed")
    output_dir = Path(output_dir).resolve()
    require(not output_dir.exists() or not any(output_dir.iterdir()), "sr_native_exists", "Native output directory must be fresh")
    output_dir.mkdir(parents=True, exist_ok=True)
    if key == "qwen":
        from ..v3.qwen import generate
        native = {"schema_version": "hre_model_request_v3", "profile_id": "qwen21", "task_mode": "restoration",
                  "spatial": {"mode": "full_frame"}, "seed": request["seed"],
                  "canvas": dict(zip(("width", "height"), request["geometry"]["native_hr"])),
                  "inputs": [{**request["input"], "role": "source"}]}
        immutable_json(output_dir / "invocation.json", {"native_request": native, "condition": QWEN_PROMPT,
                                                        "config": models[key], "adapter_version": VERSION})
        return generate(native, {"text": QWEN_PROMPT}, models[key], output_dir)
    argv = command(request, models[key], output_dir)
    invocation = {"argv": argv, "cwd": models[key]["repo"], "adapter_version": VERSION,
                  "offline_environment": {k: _environment(request["seed"])[k] for k in
                                          ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE", "PYTHONHASHSEED")},
                  "seed": request["seed"], "native_hr": request["geometry"]["native_hr"]}
    immutable_json(output_dir / "invocation.json", invocation)
    observation = {**invocation, "calls_attempted": 1, "calls_completed": 0, "token_usage": None,
                   "cost_usd": None, "fallback_used": False, "fixture": False}
    started = time.monotonic()
    log = output_dir / "process.log"
    try:
        with log.open("wb") as stream:
            result = subprocess.run(argv, cwd=models[key]["repo"], env=_environment(request["seed"]),
                                    stdout=stream, stderr=subprocess.STDOUT, timeout=models[key]["timeout_seconds"])
        observation.update(returncode=result.returncode, elapsed_seconds=time.monotonic() - started,
                           process_log={"path": str(log), "sha256": file_sha256(log)})
        guard = output_dir / "native_validation.json"
        if guard.is_file() and read_json(guard).get("status") == "failed":
            observation["native_contract_error"] = read_json(guard)
            observation.update(calls_completed=1, official_cli_completed=False)
            return {"outputs": [_asset(output_dir / "native_before_color.png")], "observation": observation}
        require(result.returncode == 0, "sr_native_failed", "Official model invocation failed; inspect process.log")
        product = output_dir / (("sample00/" if key == "seesr" else "") + Path(request["input"]["path"]).stem + ".png")
        require(product.is_file(), "sr_native_output_missing", "Official CLI produced no output, even if it exited with zero")
        observation["calls_completed"] = 1
        if key == "seesr":
            require(guard.is_file() and read_json(guard).get("status") == "passed", "sr_native_guard_missing", "SeeSR native geometry guard did not run")
            observation["native_before_color"] = _asset(output_dir / "native_before_color.png")
        return {"outputs": [_asset(product)], "observation": observation}
    except (HREError, OSError, subprocess.TimeoutExpired) as exc:
        observation.update(elapsed_seconds=time.monotonic() - started)
        if log.is_file():
            observation["process_log"] = {"path": str(log), "sha256": file_sha256(log)}
        error = exc if isinstance(exc, HREError) else HREError(
            "sr_native_timeout_unknown" if isinstance(exc, subprocess.TimeoutExpired) else "sr_native_failed", str(exc))
        error.observation = observation
        raise error
