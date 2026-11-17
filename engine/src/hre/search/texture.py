"""Frozen, same-size texture restoration measurements in 8-bit sRGB."""
from __future__ import annotations

import io
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms, ImageFilter, ImageOps

from ..models import HREError
from ..v3.common import require

TASK = ("Improve existing texture and supported fine detail only. Preserve low-frequency luminance, "
        "color, shadow detail, geometry, legible text and identity. Leave unsupported details ambiguous.")
LIMITS = {"luma_p95": 255, "chroma_p95": 255, "new_clipping_fraction": 1}


def validate_thresholds(thresholds: dict) -> dict:
    require(isinstance(thresholds, dict) and set(thresholds) == set(LIMITS), "thresholds_invalid",
            "Freeze all three texture thresholds using a separate calibration set")
    for name, maximum in LIMITS.items():
        value = thresholds[name]
        require(type(value) in {int, float} and math.isfinite(value) and 0 <= value < maximum,
                "thresholds_invalid", f"Expected a finite {name} in [0, {maximum})")
    return thresholds


def pixel_box(box: list[float], size: tuple[int, int]) -> tuple[int, int, int, int]:
    width, height = size
    require(isinstance(box, list) and len(box) == 4
            and all(type(value) in {int, float} and math.isfinite(value) and 0 <= value <= 1 for value in box)
            and box[0] < box[2] and box[1] < box[3], "texture_region_invalid",
            "Use a nonempty [x0,y0,x1,y1] box normalized to the source canvas")
    x0, y0, x1, y1 = box
    return (math.floor(x0 * width), math.floor(y0 * height),
            math.ceil(x1 * width), math.ceil(y1 * height))


def _load_srgb(path: Path) -> Image.Image:
    with Image.open(path) as raw:
        image = ImageOps.exif_transpose(raw)
        profile = image.info.get("icc_profile")
        if profile is None:
            return image.convert("RGB")
        try:
            src = ImageCms.ImageCmsProfile(io.BytesIO(profile))
            base = image if image.mode in {"L", "RGB", "CMYK"} else image.convert("RGB")
            return ImageCms.profileToProfile(base, src, ImageCms.createProfile("sRGB"), outputMode="RGB")
        except (OSError, ValueError, ImageCms.PyCMSError) as exc:
            raise HREError("texture_color_profile", "Cannot interpret the embedded color profile") from exc


def measure(source: Path, output: Path, regions: list[dict], thresholds: dict | None = None) -> dict:
    source_rgb = _load_srgb(source)
    try:
        output_rgb = _load_srgb(output)
    except HREError as exc:
        return {"violations": [{"region": "full_frame", "check": exc.code}], "regions": {}, "unchanged": False}
    if output_rgb.size != source_rgb.size:
        return {"violations": [{"region": "full_frame", "check": "canvas"}], "regions": {}, "unchanged": False}

    source_ycc = source_rgb.convert("YCbCr")
    output_ycc = output_rgb.convert("YCbCr")
    # Blur the full canvas first; cropping before filtering changes boundary statistics.
    source_y = source_ycc.getchannel("Y")
    output_y = output_ycc.getchannel("Y")
    radii = (2, 8)
    luma = [np.abs(np.asarray(source_y.filter(ImageFilter.GaussianBlur(radius)), dtype=np.int16)
                   - np.asarray(output_y.filter(ImageFilter.GaussianBlur(radius)), dtype=np.int16))
            for radius in radii]
    chroma = np.abs(np.asarray(source_ycc, dtype=np.int16)[..., 1:]
                    - np.asarray(output_ycc, dtype=np.int16)[..., 1:])
    src, out = np.asarray(source_y), np.asarray(output_y)
    new_clipping = ((out <= 2) & (src > 2)) | ((out >= 253) & (src < 253))
    metrics = {}
    violations = []
    boxes = {"full_frame": [0, 0, 1, 1], **{row["id"]: row["source_box"] for row in regions}}
    require(len(boxes) == len(regions) + 1, "texture_region_invalid", "Region names must be unique")
    for name, box in boxes.items():
        x0, y0, x1, y1 = pixel_box(box, source_rgb.size)
        roi = np.s_[y0:y1, x0:x1]
        luma_by_radius = {str(radius): float(np.percentile(diff[roi], 95)) for radius, diff in zip(radii, luma)}
        chroma_by_channel = np.percentile(chroma[roi].reshape(-1, 2), 95, axis=0)
        values = {"luma_p95": max(luma_by_radius.values()),
                  "chroma_p95": float(max(chroma_by_channel)),
                  "new_clipping_fraction": float(new_clipping[roi].mean())}
        metrics[name] = {**values, "luma_p95_by_radius": luma_by_radius}
        if thresholds is not None:
            violations.extend({"region": name, "check": key, "value": val, "limit": thresholds[key]}
                              for key, val in values.items() if val > thresholds[key])
    return {"violations": violations, "regions": metrics,
            "unchanged": np.array_equal(np.asarray(source_rgb), np.asarray(output_rgb))}


def assess(measurements: dict, grade: dict, requires_verified_content: bool) -> dict:
    preservation = grade["preservation"]
    progress = grade["texture"]
    # An uncertain texture or uncertain key-content judgment carries no promotion credit.
    severe = bool(measurements["violations"]) or (
        not measurements["unchanged"] and (preservation == "conflict" or grade["artifact"] == "major"))
    improved = (not severe and not measurements["unchanged"] and progress == "improved"
                and preservation in {"verified", "no_visible_conflict"}
                and (not requires_verified_content or preservation == "verified")
                and grade["artifact"] in {"none", "minor"})
    return {"eligible": improved, "severe": severe, "preservation": preservation,
            "texture": progress, "artifact": grade["artifact"], "evidence": grade["evidence"]}
