"""Declared geometry and shared crop/fuse; never model-private postprocessing."""
from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from ..models import file_sha256
from ..storage import read_json, write_json
from .common import digest, load_images, require


def _record(path: Path, image: Image.Image, role: str) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return {"role": role, "path": str(path.resolve()), "sha256": file_sha256(path),
            "width": image.width, "height": image.height, "mode": image.mode}


def _pad(image: Image.Image, size: tuple[int, int], *, mask=False) -> Image.Image:
    width, height = size
    array = np.asarray(image)
    pads = [(0, height - image.height), (0, width - image.width)] + ([(0, 0)] if array.ndim == 3 else [])
    padded = np.pad(array, pads, mode="constant" if mask else "edge")
    return Image.fromarray(padded)


def prepare_request(request: dict, spec: dict, round_dir: Path) -> dict:
    """Create inspectable model inputs before compiler or editor submission."""
    value = deepcopy(request)
    images = load_images(value)
    source = images[0]
    original = deepcopy(value["inputs"][0])
    original_size = source.size
    spatial = deepcopy(spec.get("spatial", {"mode": "full_frame"}))
    mode = spatial["mode"]
    output = Path(round_dir).resolve() / "prepared"
    output.mkdir(parents=True, exist_ok=True)
    crop_box = [0, 0, source.width, source.height]
    mask = None
    if spatial.get("mask_path"):
        require(file_sha256(Path(spatial["mask_path"])) == spatial.get("mask_sha256"),
                "input_modified", "Frozen edit mask changed before preparation")
        with Image.open(spatial["mask_path"]) as opened:
            mask = opened.convert("L")
        require(mask.size == source.size, "mask_geometry_invalid", "Frozen mask and source sizes differ")
    if mode == "crop_and_fuse":
        require(mask is not None, "mask_required", "Crop/fuse requires an explicit edit mask")
        box = mask.getbbox()
        require(box is not None, "mask_empty", "No editable mask pixels")
        context = spatial.get("context_pixels", 64)
        crop_box = [max(0, box[0] - context), max(0, box[1] - context),
                    min(source.width, box[2] + context), min(source.height, box[3] + context)]
        source = source.crop(crop_box)
        value["spatial"] = {"mode": "full_frame"}
    else:
        value["spatial"] = spatial
    unpadded_size = source.size
    geometry = spec["geometry"]
    grid = geometry.get("grid", 32)
    if geometry["policy"] == "strict":
        require(source.width % grid == 0 and source.height % grid == 0, "canvas_grid_invalid",
                "Strict geometry requires source dimensions on the declared model grid; choose explicit padding")
        size = source.size
    elif geometry["policy"] == "resize":
        size = (geometry["width"], geometry["height"])
        source = source.resize(size, Image.Resampling.LANCZOS)
    else:
        size = (math.ceil(source.width / grid) * grid, math.ceil(source.height / grid) * grid)
        source = _pad(source, size)
    value["inputs"][0] = _record(output / "source.png", source, "source")
    # B deliberately retains its own view/canvas. It is not aligned to A or
    # cropped using A's coordinates; the native adapters own their documented
    # reference preprocessing.
    if len(images) > 1:
        value["inputs"][1] = _record(output / "appearance_reference.png", images[1], "appearance_reference")
    value["canvas"] = {"width": size[0], "height": size[1]}
    if mode == "native_mask":
        if geometry["policy"] == "resize":
            mask = mask.resize(size, Image.Resampling.NEAREST)
        elif geometry["policy"] == "pad":
            mask = _pad(mask, size, mask=True)
        path = output / "native_mask.png"
        mask.save(path)
        value["spatial"] = {"mode": "native_mask", "mask_path": str(path),
                            "mask_sha256": file_sha256(path), "threshold": 128,
                            "outside_pixels_hard_preserved": False}
    if mode == "bbox":
        # Resize keeps normalized coordinates, while right/bottom padding changes
        # their denominator. Source and target boxes undergo the same map.
        if geometry["policy"] == "pad":
            for box in value["spatial"]["boxes"]:
                for key in ("src_bbox", "tgt_bbox"):
                    y0, x0, y1, x1 = box[key]
                    box[key] = [y0 * original_size[1] / size[1], x0 * original_size[0] / size[0],
                                y1 * original_size[1] / size[1], x1 * original_size[0] / size[0]]
        value["spatial"]["outside_pixels_hard_preserved"] = False
    plan = {"schema_version": "hre_geometry_plan_v3", "policy": geometry["policy"], "grid": grid,
            "spatial_mode": mode, "source": original, "source_size": list(original_size),
            "crop_box_xyxy": crop_box, "unpadded_size": list(unpadded_size), "working_size": list(size),
            "padding": {"right": max(0, size[0] - unpadded_size[0]),
                        "bottom": max(0, size[1] - unpadded_size[1]), "mode": "edge"},
            "inverse": "resize_to_source" if geometry["policy"] == "resize" else "crop_declared_padding",
            "mask_path": spatial.get("mask_path"), "mask_sha256": spatial.get("mask_sha256"),
            "feather_pixels": spatial.get("feather_pixels", 0), "feather_scope": "inside_edit_mask_only",
            "outside_pixels_hard_preserved": mode == "crop_and_fuse",
            "alpha_policy": spec["alpha_policy"], "reference_geometry": "independent_native_preprocessing"}
    value["geometry_plan"] = plan
    value["original_input_sha256"] = {asset["role"]: asset["sha256"] for asset in request["inputs"]}
    value["preparation_sha256"] = digest({"inputs": value["inputs"], "canvas": value["canvas"],
                                           "spatial": value["spatial"], "plan": plan})
    plan_path = output / "geometry_plan.json"
    if plan_path.exists():
        require(read_json(plan_path) == plan, "geometry_plan_changed", "An existing round cannot change its geometry plan")
    else:
        write_json(plan_path, plan)
    return value


def _rgb(image: Image.Image, source: Image.Image, policy: str) -> tuple[Image.Image, str]:
    require(image.mode in {"RGB", "RGBA", "L", "LA"}, "output_mode_invalid", "Unsupported native output mode")
    if image.mode not in {"RGBA", "LA"}:
        return image.convert("RGB"), "rgb_conversion" if image.mode != "RGB" else "none"
    rgba = image.convert("RGBA")
    if policy == "require_opaque":
        require(rgba.getchannel("A").getextrema() == (255, 255), "output_alpha_nonopaque",
                "Native RGBA output is nonopaque; raw output is retained. Choose an explicit alpha policy in a new run")
        return rgba.convert("RGB"), "opaque_alpha_removed"
    if policy == "composite_over_input":
        background = source.convert("RGB").convert("RGBA")
        return Image.alpha_composite(background, rgba).convert("RGB"), "alpha_composite_over_working_source"
    return rgba.convert("RGB"), "alpha_discarded_explicitly"


def deliver_outputs(result: dict, request: dict, spec: dict, output_dir: Path) -> dict:
    """Preserve raw outputs and apply only the already-frozen inverse transform."""
    result = deepcopy(result)
    plan = request["geometry_plan"]
    require(request.get("preparation_sha256") == digest({"inputs": request["inputs"], "canvas": request["canvas"],
            "spatial": request["spatial"], "plan": plan}), "geometry_plan_changed", "Frozen preparation/geometry changed before delivery")
    working_images = load_images(request)
    require(file_sha256(Path(plan["source"]["path"])) == plan["source"]["sha256"],
            "input_modified", "Original source changed during native execution")
    if plan.get("mask_path"):
        require(file_sha256(Path(plan["mask_path"])) == plan.get("mask_sha256"),
                "input_modified", "Frozen edit mask changed during native execution")
    with Image.open(plan["source"]["path"]) as image:
        require(image.size == (plan["source"]["width"], plan["source"]["height"]), "input_modified", "Original source geometry changed")
        source = image.convert("RGB")
    working_source = working_images[0]
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    deliveries = []
    for index, record in enumerate(result.get("outputs", [])):
        raw = Path(record["path"])
        require(file_sha256(raw) == record["sha256"], "output_modified", "Raw output changed before delivery")
        with Image.open(raw) as image:
            image.load()
            require(image.size == (record["width"], record["height"]) and image.mode == record["mode"],
                    "output_modified", "Raw output metadata differs from its receipt")
            require(list(image.size) == plan["working_size"], "output_canvas_mismatch",
                    "Native result violates the planned working canvas; it is retained without an unplanned repair")
            delivered, alpha_action = _rgb(image, working_source, spec["alpha_policy"])
        if plan["policy"] == "resize":
            delivered = delivered.resize(tuple(plan["unpadded_size"]), Image.Resampling.LANCZOS)
        else:
            delivered = delivered.crop((0, 0, *plan["unpadded_size"]))
        if plan["spatial_mode"] == "crop_and_fuse":
            with Image.open(plan["mask_path"]) as image:
                mask = image.convert("L")
            # Blur inward only: even with feathering, pixels outside the binary
            # edit mask are copied exactly from the canonical source.
            if plan["feather_pixels"]:
                blurred = np.asarray(mask.filter(ImageFilter.GaussianBlur(plan["feather_pixels"])), dtype=np.uint16)
                binary = np.asarray(mask, dtype=np.uint16)
                mask = Image.fromarray(((blurred * binary) // 255).astype(np.uint8))
            canvas = source.copy()
            canvas.paste(delivered, tuple(plan["crop_box_xyxy"][:2]))
            delivered = Image.composite(canvas, source, mask)
        require(delivered.size == source.size, "delivery_canvas_mismatch", "Declared inverse did not produce the source canvas")
        path = output_dir / f"delivered_{index:03d}.png"
        delivered.save(path)
        deliveries.append({"path": str(path), "sha256": file_sha256(path), "width": delivered.width,
                           "height": delivered.height, "mode": "RGB", "provider_order": record.get("provider_order", index),
                           "raw_path": str(raw), "raw_sha256": record["sha256"],
                           "postprocessing": {"geometry_plan_sha256": digest(plan), "alpha_action": alpha_action,
                                              "outside_pixels_hard_preserved": plan["outside_pixels_hard_preserved"],
                                              "source_colour_alignment": False}})
    require(deliveries, "native_output_missing", "No outputs to deliver")
    result["deliveries"] = deliveries
    return result
