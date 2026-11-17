"""One native SGLang image edit with the v3 request and receipt contract."""
from __future__ import annotations

import base64
import io
import json
import math
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

from PIL import Image

from ..models import file_sha256, sha256_bytes
from ..storage import atomic_write
from .common import require

MODEL_ID = "MiniMaxAI/MiniMax-H3-Image"


def endpoint_config(config: dict) -> dict:
    base = config.get("base_url", "")
    url = urlsplit(base)
    require(url.scheme in {"http", "https"} and url.hostname and not url.username and not url.password
            and not url.query and not url.fragment and url.path.rstrip("/") in {"", "/v1"},
            "h3_endpoint_invalid", "Supply a direct SGLang origin or its /v1 path without credentials")
    revision = config.get("revision")
    require(config.get("model_id") == MODEL_ID and isinstance(revision, str)
            and re.fullmatch(r"[0-9a-fA-F]{40}", revision),
            "h3_identity_invalid", "Freeze the deployed H3 checkpoint revision")
    timeout = config.get("timeout_seconds", 600)
    require(type(timeout) in {int, float} and math.isfinite(timeout) and timeout > 0,
            "h3_timeout_invalid", "Set a positive finite timeout")
    settings = config.get("settings", {})
    require(isinstance(settings, dict) and set(settings) <= {"min_generation_area"},
            "h3_settings_invalid", "Only min_generation_area is configurable for this distilled profile")
    area = settings.get("min_generation_area", 4194304)
    require(type(area) is int and 1024 <= area <= 16777216,
            "h3_settings_invalid", "Invalid min_generation_area")
    key_name = config.get("api_key_env")
    require(key_name is None or (isinstance(key_name, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key_name)),
            "h3_key_invalid", "Use an environment variable name for H3 authentication")
    return {"endpoint": url.scheme + "://" + url.netloc + "/v1/images/edits",
            "revision": revision.lower(), "timeout_seconds": timeout,
            "min_generation_area": area, "api_key_env": key_name}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _post(endpoint: str, fields: dict, images: list[bytes], timeout: float, api_key: str) -> dict:
    boundary = uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    for index, image in enumerate(images, 1):
        parts.extend([
            (f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="picture_{index}.png"\r\n'
             'Content-Type: image/png\r\n\r\n').encode(), image, b"\r\n",
        ])
    parts.append(f"--{boundary}--\r\n".encode())
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    request = Request(endpoint, data=b"".join(parts), headers=headers, method="POST")
    with build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
        return json.load(response)


def generate(request: dict, condition: dict, config: dict, output_dir: Path) -> dict:
    deployment = endpoint_config(config)
    width, height = request["canvas"]["width"], request["canvas"]["height"]
    require(width >= 32 and height >= 32 and width % 32 == height % 32 == 0,
            "h3_canvas_invalid", "H3 output dimensions must be multiples of 32")
    key_name = deployment["api_key_env"]
    key = os.environ.get(key_name, "") if key_name else ""
    require(not key_name or bool(key), "h3_key_missing", "The explicit H3 API key environment variable is empty")
    inputs = []
    for asset in request["inputs"]:
        data = Path(asset["path"]).read_bytes()
        require(sha256_bytes(data) == asset["sha256"], "input_modified", "Frozen H3 input changed")
        with Image.open(io.BytesIO(data)) as image:
            require(image.format == "PNG" and image.size == (asset["width"], asset["height"]),
                    "h3_input_invalid", "Expected a frozen PNG matching the v3 input receipt")
        inputs.append(data)
    output_dir.mkdir(parents=True, exist_ok=True)
    require(not list(output_dir.glob("native_*.png")), "native_output_exists", "Use a fresh native output directory")
    fields = {"prompt": condition["text"], "size": f"{width}x{height}", "seed": request["seed"],
              "generator_device": "cpu", "response_format": "b64_json",
              "min_generation_area": deployment["min_generation_area"]}
    started = time.monotonic()
    payload = _post(deployment["endpoint"], fields, inputs, deployment["timeout_seconds"], key)
    require(isinstance(payload, dict) and isinstance(payload.get("data"), list) and payload["data"],
            "h3_response_invalid", "SGLang did not return image data")
    outputs = []
    for index, row in enumerate(payload["data"]):
        raw = base64.b64decode(row["b64_json"], validate=True)
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            require(image.format == "PNG", "h3_response_invalid", "SGLang must return a PNG")
            path = output_dir / f"native_{index:03d}.png"
            atomic_write(path, raw)
            outputs.append({"path": str(path), "sha256": file_sha256(path), "width": image.width,
                            "height": image.height, "mode": image.mode, "provider_order": index})
    return {"outputs": outputs, "observation": {
        "adapter_version": "hre.h3.sglang.v1", "transport": "sglang_multipart",
        "model_identity": {"model_id": MODEL_ID, "revision": deployment["revision"],
                           "revision_verification": "operator_declared_remote_checkpoint"},
        "endpoint": deployment["endpoint"], "settings": {k: v for k, v in fields.items() if k != "prompt"},
        "input_roles": [row["role"] for row in request["inputs"]], "image_calls_attempted": 1,
        "image_calls_completed": 1, "actual_generation_count": len(outputs), "requested_image_count": 1,
        "returned_image_count": len(outputs), "elapsed_seconds": time.monotonic() - started,
        "output_normalization": "provider_png_bytes_preserved",
    }}
