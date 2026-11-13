"""MiniMax-H3-Image adapter for an operator-hosted SGLang image-edit server.

The H3 server uses multipart POST /v1/images/edits, NOT Gemini generateContent.
Only the executor transport changes; diagnosis, tools, prompt composition,
verification, and deterministic image geometry remain in HarnessIR.
"""
from __future__ import annotations

import base64
import io
import os
import re
from urllib.parse import urlsplit

import requests
from PIL import Image


def endpoint(base_url: str) -> str:
    """Accept the SGLang host root (or its /v1 prefix), never embedded secrets."""
    parsed = urlsplit(base_url.strip())
    if (parsed.scheme not in {"http", "https"} or not parsed.netloc
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("HARNESS_H3_BASE_URL must be an HTTP(S) URL without embedded credentials")
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    return base + "/v1/images/edits"


def _canvas(image: Image.Image, requested: str) -> str:
    """H3 expects WIDTHxHEIGHT; keep the source aspect ratio for 1K/2K/4K."""
    if requested in {"1K", "2K", "4K"}:
        longest = {"1K": 1024, "2K": 2048, "4K": 4096}[requested]
        factor = longest / max(image.size)
        w, h = (max(32, round(d * factor / 32) * 32) for d in image.size)
    else:
        match = re.fullmatch(r"(\d+)x(\d+)", requested)
        if match is None:
            raise ValueError("H3 size must be 1K, 2K, 4K or WIDTHxHEIGHT")
        w, h = (int(v) for v in match.groups())
        if w < 32 or h < 32 or w % 32 or h % 32:
            raise ValueError("H3 output dimensions must be multiples of 32")
    return f"{w}x{h}"


def edit(images: list, prompt: str, *, base_url: str, image_size: str,
         timeout_sec: int | float) -> Image.Image:
    """Run exactly one reference-image edit, no silent fallback or retry."""
    if not images or len(images) > 16:
        raise ValueError("H3 accepts 1-16 reference images")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("H3 requires an edit instruction")
    if not isinstance(timeout_sec, (int, float)) or timeout_sec <= 0:
        raise ValueError("H3 timeout must be positive")

    first = Image.open(images[0]) if isinstance(images[0], (str, os.PathLike)) else images[0]
    if not isinstance(first, Image.Image):
        raise TypeError("H3 inputs must be paths or PIL images")
    size = _canvas(first, image_size)
    files = []
    for index, image in enumerate(images, 1):
        if isinstance(image, (str, os.PathLike)):
            with Image.open(image) as opened:
                buffer = io.BytesIO()
                opened.convert("RGB").save(buffer, "PNG")
        elif isinstance(image, Image.Image):
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, "PNG")
        else:
            raise TypeError("H3 inputs must be paths or PIL images")
        files.append(("image", (f"picture_{index}.png", buffer.getvalue(), "image/png")))

    # The model identifies references in upload order as <Picture 1>, ...
    instruction = (prompt if "<Picture 1>" in prompt else
                   "Edit <Picture 1> following this instruction:\n" + prompt)
    seed_text = os.environ.get("HARNESS_H3_SEED", "1234")
    try:
        seed = int(seed_text)
    except ValueError as exc:
        raise ValueError("HARNESS_H3_SEED must be a nonnegative integer") from exc
    if seed < 0 or seed >= 2**63:
        raise ValueError("HARNESS_H3_SEED must be a nonnegative 63-bit integer")
    data = {"prompt": instruction, "size": size, "seed": str(seed),
            "generator_device": "cpu", "response_format": "b64_json",
            "output_format": "png"}
    key = os.environ.get("HARNESS_H3_API_KEY", "")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    response = requests.post(endpoint(base_url), headers=headers, files=files,
                             data=data, timeout=timeout_sec)
    response.raise_for_status()
    payload = response.json()
    try:
        encoded = payload["data"][0]["b64_json"]
        raw = base64.b64decode(encoded, validate=True)
        with Image.open(io.BytesIO(raw)) as output:
            output.load()
            return output.convert("RGB")
    except (KeyError, IndexError, TypeError, ValueError, OSError) as exc:
        raise ValueError("H3 server did not return a valid base64-encoded image") from exc
