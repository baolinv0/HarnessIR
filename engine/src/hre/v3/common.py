"""Small, dependency-light primitives shared by the four native adapters."""
from __future__ import annotations

import base64
import gc
import importlib.metadata
import io
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from PIL import Image

from ..models import HREError, canonical_json, file_sha256, sha256_bytes
from ..storage import read_json


def require(condition, code: str, message: str) -> None:
    if not condition:
        raise HREError(code, message)


def digest(value) -> str:
    return sha256_bytes(canonical_json(value))


def package_versions() -> dict:
    result = {}
    for package in ("torch", "diffusers", "transformers", "accelerate", "Pillow", "bria-vgl"):
        try:
            result[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            result[package] = None
    return result


def model_identity(config: dict, expected_id: str) -> dict:
    require(config.get("model_id") == expected_id, "model_identity_mismatch",
            f"Expected {expected_id}; an alternative checkpoint needs its own run identity")
    revision = config.get("revision")
    require(isinstance(revision, str) and re.fullmatch(r"[0-9a-fA-F]{40}", revision),
            "revision_required", "Freeze a 40-character upstream checkpoint revision")
    path = Path(config.get("local_path", "")).expanduser().resolve()
    require(bool(config.get("local_path")) and path.is_dir(), "local_weights_missing",
            f"Deploy the checkpoint locally before running: {config.get('local_path')}")
    identity = {"model_id": expected_id, "revision": revision.lower(), "local_path": str(path),
                "revision_verification": "declared_local_checkpoint"}
    manifest_path = config.get("deployment_manifest")
    if manifest_path:
        manifest = read_json(Path(manifest_path))
        require(manifest.get("model_id") == expected_id and manifest.get("revision") == revision.lower(),
                "deployment_mismatch", "Deployment manifest identity differs from runtime configuration")
        require(Path(manifest.get("local_path", "")).resolve() == path, "deployment_mismatch",
                "Deployment manifest belongs to another local checkpoint directory")
        records = manifest.get("files", [])
        require(bool(records), "deployment_mismatch", "Deployment manifest has no files")
        for record in records:
            relative = Path(record["path"])
            require(not relative.is_absolute() and ".." not in relative.parts, "deployment_mismatch", "Unsafe checkpoint component path")
            # Hugging Face cache snapshots legitimately link to ../blobs. The
            # declared logical path stays inside the checkpoint; hash the target.
            candidate = path / relative
            require(candidate.is_file(), "deployment_mismatch",
                    "A declared checkpoint component is missing")
            stat = candidate.stat()
            require(stat.st_size == record["size"], "deployment_mismatch", f"Checkpoint size changed: {record['path']}")
            # Full hashes are calculated by `models lock`. Re-hash changed files;
            # a startup need not reread tens of GB for every single image.
            if stat.st_mtime_ns != record.get("mtime_ns") or config.get("verify_weight_hashes", False):
                require(file_sha256(candidate) == record["sha256"], "deployment_mismatch",
                        f"Checkpoint bytes changed: {record['path']}")
        identity.update(deployment_manifest_sha256=file_sha256(Path(manifest_path)),
                        revision_verification="local_deployment_manifest",
                        upstream_authenticity=manifest.get("upstream_authenticity", "operator_declared"))
    return identity


def load_images(request: dict, mode: str | None = None) -> list[Image.Image]:
    images = []
    for asset in request["inputs"]:
        path = Path(asset["path"])
        require(path.is_file() and file_sha256(path) == asset["sha256"], "input_modified",
                f"Frozen {asset['role']} bytes changed")
        with Image.open(path) as image:
            image.load()
            require(image.size == (asset["width"], asset["height"]), "input_modified",
                    "Frozen image dimensions changed")
            images.append(image.convert(mode) if mode else image.copy())
    return images


_runtime_key = None
_runtime_value = None


def runtime_clear() -> None:
    global _runtime_key, _runtime_value
    value = _runtime_value
    _runtime_key, _runtime_value = None, None
    # Do not invoke an arbitrary pipeline .close(): many Diffusers objects expose
    # proxy attributes. Dropping this process's cached reference is sufficient.
    del value
    gc.collect()
    torch = sys.modules.get("torch")
    if torch is not None and getattr(torch, "cuda", None) is not None and torch.cuda.is_available():
        torch.cuda.empty_cache()


def runtime_get(key, factory: Callable):
    """One explicitly identified heavy runtime per worker process."""
    global _runtime_key, _runtime_value
    identity = digest(key)
    if _runtime_key == identity and _runtime_value is not None:
        return _runtime_value
    runtime_clear()
    value = factory()
    _runtime_key, _runtime_value = identity, value
    return value


def image_message(path: str | Path) -> dict:
    # Canonical PNG avoids trusting a filename MIME extension or EXIF rotation.
    with Image.open(path) as image:
        data = io.BytesIO()
        image.convert("RGB").save(data, format="PNG")
    encoded = base64.b64encode(data.getvalue()).decode("ascii")
    return {"type": "image_url", "image_url": {"url": "data:image/png;base64," + encoded}}


def chat(config: dict, messages: list, response_schema: dict | None = None) -> dict:
    """Exactly one explicit OpenAI-compatible HTTP request; no provider defaults.

    A caller records its attempt before entering this function. A transport
    failure is never retried here, since the remote call may already have run.
    """
    base = config.get("base_url", "")
    parsed = urlsplit(base)
    require(parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username
            and not parsed.password and not parsed.query and not parsed.fragment,
            "endpoint_required", "Set an explicit HTTP(S) base_url without credentials/query")
    model = config.get("model")
    require(isinstance(model, str) and model.strip(), "endpoint_required", "Set the deployed model name")
    settings = dict(config.get("settings", {}))
    allowed = {"temperature", "top_p", "max_tokens", "max_completion_tokens", "seed",
               "presence_penalty", "frequency_penalty", "stop", "reasoning_effort"}
    require(not set(settings) - allowed, "unsupported_chat_setting",
            "Unknown chat settings: " + ", ".join(sorted(set(settings) - allowed)))
    body = {"model": model, "messages": messages, **settings, "stream": False}
    if response_schema is not None:
        # json_object is broadly supported by local servers; validate the actual
        # schema locally. It is never applied to ordinary PUP/Recaption text.
        mode = config.get("response_format", "json_object")
        require(mode in {"json_object", "json_schema", "none"}, "invalid_response_format", str(mode))
        if mode == "json_schema":
            body["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "hre_response", "strict": True, "schema": response_schema}}
        elif mode == "json_object":
            body["response_format"] = {"type": "json_object"}
    timeout = config.get("timeout_seconds", 600)
    require(type(timeout) in {int, float} and math.isfinite(timeout) and timeout > 0,
            "invalid_timeout", "HTTP timeout must be a positive number")
    headers = {"Content-Type": "application/json"}
    key_env = config.get("api_key_env")
    if key_env:
        require(isinstance(key_env, str) and key_env in os.environ, "api_key_missing",
                f"Configured credential environment variable is unset: {key_env}")
        headers["Authorization"] = "Bearer " + os.environ[key_env]
    request_bytes = canonical_json(body)
    request = Request(base.rstrip("/") + "/chat/completions", data=request_bytes, headers=headers, method="POST")
    started = time.monotonic()
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except HTTPError as exc:
        raise HREError("chat_http_error", f"Configured endpoint returned HTTP {exc.code}; no automatic retry") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise HREError("chat_transport_unknown", "Chat request outcome unknown; no automatic retry") from exc
    try:
        result = json.loads(raw)
        choices = result["choices"]
        require(isinstance(choices, list) and len(choices) == 1, "chat_output_invalid", "Expected exactly one completion")
        text = choices[0]["message"]["content"]
        require(isinstance(text, str) and text.strip(), "chat_output_invalid", "Empty or non-text completion")
    except (KeyError, ValueError, TypeError) as exc:
        raise HREError("chat_output_invalid", "The configured endpoint returned an invalid completion") from exc
    return {"text": text, "model": result.get("model"), "model_requested": model,
            "usage": result.get("usage"), "response_id": result.get("id"),
            "finish_reason": choices[0].get("finish_reason"), "calls_attempted": 1, "calls_completed": 1,
            "request_sha256": sha256_bytes(request_bytes), "raw_response": result,
            "raw_response_sha256": sha256_bytes(raw), "elapsed_seconds": time.monotonic() - started,
            "endpoint": base, "fallback_used": False}


def save_outputs(images, output_dir: Path, observation: dict) -> dict:
    require(isinstance(images, (list, tuple)) and len(images) > 0, "native_output_missing",
            "The single native pipeline invocation returned no images")
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    require(not list(output_dir.glob("native_*.png")), "native_output_exists", "Use a fresh native output directory")
    outputs = []
    for index, image in enumerate(images):
        require(isinstance(image, Image.Image), "native_output_invalid", "Expected PIL image outputs")
        path = output_dir / f"native_{index:03d}.png"
        image.save(path)
        outputs.append({"path": str(path), "sha256": file_sha256(path), "width": image.width,
                        "height": image.height, "mode": image.mode, "provider_order": index})
    return {"outputs": outputs, "observation": {**observation,
            "actual_generation_count": len(outputs), "requested_image_count": 1,
            "returned_image_count": len(outputs)}}


_GUIDANCE = {
    "qwen21": "Express the required changes together in concise semantic instructions. Keep the specified subject/background and lighting relationships coherent; do not add new goals.",
    "firered11": "Express one coherent edit, anchoring identity, lettering and fine structures to the source. Describe the required local or global changes explicitly without inventing details.",
    "flux3_klein": "Use the native image-edit instruction format: describe required changes and a compact preservation clause. For bounded edits retain the rest of the scene; do not invent a new composition.",
    "fibo2_dev": "Represent the intended output in the complete native VGL scene and edit_instruction. Keep corresponding scene attributes consistent with the instruction, and retain source content and illumination geometry.",
}


def render_instruction(request: dict) -> str:
    strategy = request["strategy"]
    parts = [request["brief"].strip()]
    if request["task_mode"] == "reference_enhance":
        parts.append("The first input is the source and determines all content, identity, text, composition and geometry. The second input is an unaligned appearance reference only: transfer the requested brightness, colour and tone relationships, never its objects or textures. Preserve the first input canvas.")
    else:
        parts.append("Restore the first input while preserving its identity, text, content and geometry. Remove only the requested degradations. Recover supported edge structure without inventing legible text or new objects. Preserve the source canvas.")
    if strategy != "native":
        intent = request.get("intent")
        require(isinstance(intent, dict), "intent_required", "Shared/model-aware compilation requires an accepted intent")
        for target in sorted(intent.get("targets", []), key=lambda item: item.get("priority", 999)):
            parts.append(f"Target [{target.get('id', '')}] in {target.get('region', 'whole image')}: {target['instruction']}")
        for relation in intent.get("region_relations", []):
            parts.append(f"Relation {relation.get('subject', '')} / {relation.get('object', '')}: {relation['instruction']}")
        if intent.get("protected_content"):
            parts.append("Preserve: " + "; ".join(intent["protected_content"]))
        if intent.get("uncertainties"):
            parts.append("Uncertain details; do not guess: " + "; ".join(intent["uncertainties"]))
    else:
        require(request.get("intent") is None, "native_intent_forbidden", "Native strategy cannot receive derived Harness intent")
    if strategy == "model_aware":
        parts.append(_GUIDANCE[request["profile_id"]])
    return "\n".join(parts)
