"""Versioned task creation and immutable inputs for the four-model runtime."""
from __future__ import annotations

from copy import deepcopy
import io
import math
from pathlib import Path
import re
import shutil

from PIL import Image, ImageCms, ImageOps

from ..models import HREError, file_sha256, now, sha256_bytes
from ..storage import atomic_write, case_lock, read_json, write_json
from . import PROTOCOL_VERSION
from .common import digest, require


CATALOG = {
    "qwen21": {
        "name": "Qwen-Image-2.1", "model_id": "Qwen/Qwen-Image-2.1",
        "pipeline": "QwenImage21Pipeline", "compiler": "qwen_pe_i2i",
        "compilers": ["direct", "qwen_pe_i2i"], "grid": 32,
        "spatial_modes": ["full_frame", "crop_and_fuse"],
        "settings": {"num_inference_steps": 40, "true_cfg_scale": 1.0,
                     "negative_prompt": "", "output_resolution": 1024, "use_kv_cache": True,
                     "num_images_per_prompt": 1},
    },
    "firered11": {
        "name": "FireRed-Image-Edit-1.1", "model_id": "FireRedTeam/FireRed-Image-Edit-1.1",
        "pipeline": "QwenImageEditPlusPipeline", "compiler": "firered_recaption",
        "compilers": ["direct", "firered_recaption"], "grid": 16,
        "spatial_modes": ["full_frame", "crop_and_fuse"],
        "settings": {"num_inference_steps": 40, "true_cfg_scale": 4.0,
                     "negative_prompt": " ", "num_images_per_prompt": 1},
    },
    "flux3_klein": {
        "name": "FLUX 3 Image Klein (distilled)", "model_id": "black-forest-labs/flux-3-image-klein",
        "pipeline": "ModularPipeline", "compiler": "flux3_pup_local",
        "compilers": ["flux3_pup_local", "flux3_external_vlm_local"], "grid": 16,
        "spatial_modes": ["full_frame", "crop_and_fuse", "bbox"],
        "settings": {"num_inference_steps": 16, "num_images_per_prompt": 1,
                     "geometry_policy": "explicit_canvas"},
    },
    "fibo2_dev": {
        "name": "FIBO 2.0 Dev", "model_id": "briaai/Fibo-2.0-dev",
        "pipeline": "BriaFibo2Pipeline", "compiler": "fibo2_thales_local_openai",
        "compilers": ["fibo2_thales_local_openai"], "grid": 16,
        "spatial_modes": ["full_frame", "crop_and_fuse", "native_mask"],
        "settings": {"num_inference_steps": 50, "guidance_scale": 5.0,
                     "num_images_per_prompt": 1},
    },
}


def normalise_spec(spec: dict) -> dict:
    require(isinstance(spec, dict), "task_invalid", "Task must be a JSON object")
    value = deepcopy(spec)
    require(value.get("schema_version", PROTOCOL_VERSION) == PROTOCOL_VERSION,
            "task_version_invalid", "Use a new hre_task_v3 case; legacy records are not rewritten")
    value["schema_version"] = PROTOCOL_VERSION
    require(value.get("profile_id") in CATALOG, "profile_invalid", "Choose qwen21, firered11, flux3_klein or fibo2_dev")
    require(value.get("task_mode") in {"restoration", "reference_enhance"}, "task_mode_invalid",
            "task_mode is restoration or reference_enhance")
    value.setdefault("case_id", "case_" + digest(spec)[:16])
    require(isinstance(value["case_id"], str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value["case_id"]),
            "case_id_invalid", "Use a simple case ID of at most 128 characters")
    value.setdefault("strategy", "model_aware")
    require(value["strategy"] in {"native", "shared", "model_aware"}, "strategy_invalid", "Unknown condition strategy")
    require(isinstance(value.get("brief"), str) and value["brief"].strip(), "brief_required", "Supply the actual restoration/edit request")
    require(isinstance(value.get("source"), dict) and value["source"].get("path"), "source_required", "Supply one original source image")
    if value["task_mode"] == "restoration":
        require(not value.get("reference"), "reference_forbidden", "Single-source restoration does not duplicate a source as reference")
    else:
        require(isinstance(value.get("reference"), dict) and value["reference"].get("path"), "reference_required",
                "Reference enhancement requires one appearance reference")
    geometry = {"policy": "pad", "grid": 32, **value.get("geometry", {})}
    require(geometry["policy"] in {"strict", "pad", "resize"}, "geometry_invalid", "Unknown geometry policy")
    require(type(geometry["grid"]) is int and geometry["grid"] > 0
            and geometry["grid"] % CATALOG[value["profile_id"]]["grid"] == 0,
            "geometry_invalid", "Geometry grid must be a positive multiple of the model's native grid")
    if geometry["policy"] == "resize":
        for dimension in ("width", "height"):
            require(type(geometry.get(dimension)) is int and geometry[dimension] > 0 and geometry[dimension] % geometry["grid"] == 0,
                    "geometry_invalid", "Explicit resize dimensions must be positive multiples of the declared grid")
    elif any(key in geometry for key in ("width", "height")):
        raise HREError("geometry_invalid", "Set dimensions only with the explicit resize policy")
    value["geometry"] = geometry
    spatial = {"mode": "full_frame", **value.get("spatial", {})}
    require(spatial["mode"] in CATALOG[value["profile_id"]]["spatial_modes"], "spatial_unsupported",
            f"{value['profile_id']} does not implement {spatial['mode']}")
    if spatial["mode"] == "native_mask":
        require(value["task_mode"] == "restoration", "mask_reference_conflict",
                "FIBO native mask accepts one source; it cannot silently discard reference B")
        require(bool(spatial.get("mask_path")), "mask_required", "Supply a source-sized mask")
    if spatial["mode"] == "crop_and_fuse":
        require(bool(spatial.get("mask_path")), "mask_required", "Shared crop/fuse requires an explicit source-sized edit mask")
        spatial.setdefault("context_pixels", 64)
        spatial.setdefault("feather_pixels", 0)
        for key in ("context_pixels", "feather_pixels"):
            require(type(spatial[key]) is int and spatial[key] >= 0, "spatial_invalid", f"{key} must be a nonnegative integer")
        require(geometry["policy"] != "resize", "spatial_invalid", "Crop/fuse uses grid padding; global resizing is a separate run")
    if spatial["mode"] == "bbox":
        require(isinstance(spatial.get("boxes"), list) and spatial["boxes"], "bbox_required", "Supply explicit source/target boxes")
        ids = []
        for box in spatial["boxes"]:
            require(isinstance(box, dict) and isinstance(box.get("id"), str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", box["id"])
                    and isinstance(box.get("desc"), str) and box["desc"], "bbox_invalid", "Each box requires id and desc")
            ids.append(box["id"])
            box.setdefault("from", "ref_image_0")
            require(box.get("from", "ref_image_0") == "ref_image_0", "bbox_invalid", "Restoration boxes must refer to the source image")
            for key in ("src_bbox", "tgt_bbox"):
                coordinates = box.get(key)
                require(isinstance(coordinates, list) and len(coordinates) == 4
                        and all(type(x) in {int, float} and math.isfinite(x) and 0 <= x <= 1 for x in coordinates)
                        and coordinates[0] < coordinates[2] and coordinates[1] < coordinates[3],
                        "bbox_invalid", "Boxes use normalized [y_min,x_min,y_max,x_max]")
            require(box["src_bbox"] == box["tgt_bbox"], "bbox_geometry_change",
                    "This restoration runtime keeps objects in place; layout editing requires a separate task contract")
        require(len(ids) == len(set(ids)), "bbox_invalid", "Duplicate box IDs")
    value["spatial"] = spatial
    regions = value.setdefault("regions", [])
    require(isinstance(regions, list), "regions_invalid", "regions must be a list")
    region_ids = []
    for region in regions:
        require(isinstance(region, dict) and isinstance(region.get("id"), str)
                and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", region["id"])
                and isinstance(region.get("description", ""), str), "regions_invalid", "Each region needs a stable id and text description")
        region_ids.append(region["id"])
        require("source_box" in region, "regions_invalid", "Each region requires its own source box")
        require(not region.get("reference_box") or value["task_mode"] == "reference_enhance",
                "regions_invalid", "Single-source restoration has no reference coordinate system")
        for key in ("source_box", "reference_box"):
            if key not in region:
                continue
            box = region[key]
            require(isinstance(box, list) and len(box) == 4 and all(type(x) in {int, float}
                    and math.isfinite(x) and 0 <= x <= 1 for x in box) and box[0] < box[2] and box[1] < box[3],
                    "regions_invalid", "Region evidence boxes use normalized [x_min,y_min,x_max,y_max]")
    require(len(region_ids) == len(set(region_ids)), "regions_invalid", "Region IDs must be unique")
    policy = {"mode": "single", **value.get("policy", {})}
    require(policy["mode"] in {"single", "feedback", "resample"}, "policy_invalid", "Unknown generation policy")
    policy.setdefault("max_generations", 1 if policy["mode"] == "single" else 3)
    require(type(policy["max_generations"]) is int and 1 <= policy["max_generations"] <= 100,
            "budget_invalid", "Choose an explicit generation cap from 1 to 100")
    if policy["mode"] == "single":
        require(policy["max_generations"] == 1, "budget_invalid", "Single-generation policy has a budget of one")
    if policy["mode"] == "feedback":
        require(value["strategy"] != "native", "native_feedback_forbidden", "Native baseline has no derived Harness intent; use resample for its budget control")
    policy.setdefault("seed_schedule", list(range(policy["max_generations"])))
    require(isinstance(policy["seed_schedule"], list) and len(policy["seed_schedule"]) == policy["max_generations"]
            and all(type(seed) is int and 0 <= seed < 2**63 for seed in policy["seed_schedule"]),
            "seed_schedule_invalid", "Freeze one nonnegative 63-bit seed per allowed generation")
    policy.setdefault("max_stage_calls", 3 + 2 * policy["max_generations"])
    policy.setdefault("max_compiler_calls", policy["max_generations"])
    for key in ("max_stage_calls", "max_compiler_calls"):
        require(type(policy[key]) is int and policy[key] >= 0, "budget_invalid", f"{key} must be a nonnegative integer")
    value["policy"] = policy
    value.setdefault("alpha_policy", "require_opaque")
    require(value["alpha_policy"] in {"require_opaque", "composite_over_input", "drop_alpha"}, "alpha_policy_invalid", "Choose an explicit alpha normalization policy")
    value.setdefault("colour_policy", "assume_srgb")
    require(value["colour_policy"] in {"assume_srgb", "require_icc"}, "colour_policy_invalid", "Unknown input colour policy")
    value.setdefault("evaluation", {"task_goal": value["brief"], "preserve_identity_text_geometry": True,
                                    "reference_content_transfer_allowed": False})
    require(isinstance(value["evaluation"], dict), "evaluation_invalid", "Freeze an evaluation contract object")
    if value.get("shared_intent"):
        require(value["strategy"] != "native", "native_intent_forbidden", "Native baseline cannot import a shared intent")
    return value


def validate_config(config: dict, profile_id: str) -> dict:
    require(isinstance(config, dict) and isinstance(config.get("models"), dict)
            and profile_id in config["models"], "config_invalid", "Configure the selected model in config.models")
    model = config["models"][profile_id]
    require(isinstance(model, dict) and isinstance(model.get("compiler"), dict) and isinstance(model.get("editor"), dict),
            "config_invalid", "Each model needs compiler and editor configurations")
    require(model["compiler"].get("backend") in CATALOG[profile_id]["compilers"], "compiler_invalid",
            "Unsupported compiler for the selected model")
    require(model["editor"].get("model_id") == CATALOG[profile_id]["model_id"], "model_identity_mismatch",
            "The runtime checkpoint must match the four-model catalog")
    return deepcopy(config)


def _canonical_asset(source: Path, directory: Path, role: str, colour_policy: str) -> dict:
    require(source.is_file(), "input_missing", f"Missing input: {source}")
    directory.mkdir(parents=True, exist_ok=True)
    raw_path = directory / (role + ".original")
    original_hash = file_sha256(source)
    shutil.copyfile(source, raw_path)
    require(file_sha256(raw_path) == original_hash == file_sha256(source), "input_changed", "Input changed during import")
    with Image.open(raw_path) as image:
        image.load()
        require(image.mode in {"RGB", "RGBA", "L", "LA", "P", "CMYK"}, "input_mode_unsupported",
                "This runtime expects SDR eight-bit photos; prepare RAW/HDR/16-bit data explicitly")
        icc = image.info.get("icc_profile")
        require(icc or colour_policy == "assume_srgb", "input_colour_unknown", "An ICC profile is required by this task")
        require(image.mode != "CMYK" or bool(icc), "input_colour_unknown", "CMYK requires an embedded ICC profile")
        image = ImageOps.exif_transpose(image)
        has_alpha = image.mode in {"RGBA", "LA"} or "transparency" in image.info
        alpha = image.convert("RGBA").getchannel("A") if has_alpha else None
        colour_operation = "assumed_srgb"
        if icc:
            try:
                source_profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
                base = image if image.mode in {"RGB", "CMYK", "L"} else image.convert("RGB")
                image = ImageCms.profileToProfile(base, source_profile, ImageCms.createProfile("sRGB"), outputMode="RGB")
                colour_operation = "icc_to_srgb"
            except (OSError, ValueError, ImageCms.PyCMSError) as exc:
                raise HREError("input_colour_invalid", "Cannot interpret embedded ICC profile") from exc
        else:
            image = image.convert("RGB")
        if alpha is not None:
            image.putalpha(alpha)
        path = directory / (role + ".png")
        image.save(path)
        return {"role": role, "path": str(path.resolve()), "sha256": file_sha256(path),
                "pixel_sha256": sha256_bytes(image.mode.encode() + str(image.size).encode() + image.tobytes()),
                "width": image.width, "height": image.height, "mode": image.mode,
                "original_path": str(raw_path.resolve()), "original_sha256": original_hash,
                "canonicalization": {"exif_transpose": True, "colour_operation": colour_operation}}


def create_case(root: Path, spec: dict, config: dict) -> dict:
    root = Path(root).resolve()
    value = normalise_spec(spec)
    runtime = validate_config(config, value["profile_id"])
    source_path = Path(value["source"]["path"]).expanduser().resolve()
    reference_path = Path(value["reference"]["path"]).expanduser().resolve() if value.get("reference") else None
    require(source_path.is_file() and (reference_path is None or reference_path.is_file()), "input_missing", "An input image is missing")
    require(not root.exists() or not any(root.iterdir()), "case_exists", "Create a fresh case directory; use run/resume for existing cases")
    with case_lock(root):
        inputs = [_canonical_asset(source_path, root / "inputs", "source", value["colour_policy"])]
        value["source"] = {"path": inputs[0]["path"]}
        if reference_path:
            inputs.append(_canonical_asset(reference_path, root / "inputs", "appearance_reference", value["colour_policy"]))
            value["reference"] = {"path": inputs[1]["path"]}
        canvas = {"width": inputs[0]["width"], "height": inputs[0]["height"]}
        if value["spatial"].get("mask_path"):
            mask_source = Path(value["spatial"]["mask_path"]).expanduser().resolve()
            with Image.open(mask_source) as mask:
                mask = ImageOps.exif_transpose(mask).convert("L")
                require(mask.size == (canvas["width"], canvas["height"]), "mask_geometry_invalid", "Edit mask must match the canonical source canvas")
                mask = mask.point(lambda pixel: 255 if pixel >= 128 else 0)
                require(mask.getbbox() is not None, "mask_empty", "The edit mask contains no editable pixels")
                mask_path = root / "inputs" / "edit_mask.png"
                mask.save(mask_path)
            value["spatial"].update(mask_path=str(mask_path), mask_sha256=file_sha256(mask_path), mask_threshold=128)
        if value.get("shared_intent"):
            shared_path = Path(value["shared_intent"]).expanduser().resolve()
            target = root / "inputs" / "shared_intent.json"
            atomic_write(target, shared_path.read_bytes())
            value["shared_intent"] = str(target)
            value["shared_intent_sha256"] = file_sha256(target)
        state = {"schema_version": PROTOCOL_VERSION, "case_id": value["case_id"], "status": "created",
                 "round": 0, "inputs": inputs, "canvas": canvas, "created_at": now()}
        write_json(root / "task.json", value)
        write_json(root / "config.json", runtime)
        freeze = {"schema_version": PROTOCOL_VERSION, "task_sha256": file_sha256(root / "task.json"),
                  "config_sha256": file_sha256(root / "config.json"), "inputs": inputs, "canvas": canvas,
                  "created_at": state["created_at"]}
        write_json(root / "freeze.json", freeze)
        state["freeze_sha256"] = file_sha256(root / "freeze.json")
        write_json(root / "state.json", state)
    return state


def load_case(root: Path) -> tuple[dict, dict, dict]:
    root = Path(root).resolve()
    freeze = read_json(root / "freeze.json")
    spec, config, state = (read_json(root / name) for name in ("task.json", "config.json", "state.json"))
    require(freeze.get("schema_version") == PROTOCOL_VERSION and state.get("schema_version") == PROTOCOL_VERSION,
            "task_version_invalid", "Not a four-model v3 case")
    require(state.get("freeze_sha256") == file_sha256(root / "freeze.json"), "case_modified", "Frozen case identity changed")
    for name, key in (("task.json", "task_sha256"), ("config.json", "config_sha256")):
        require(file_sha256(root / name) == freeze[key], "case_modified", f"Immutable {name} changed; create a new case")
    require(state.get("inputs") == freeze["inputs"] and state.get("canvas") == freeze["canvas"], "case_modified", "State source bindings changed")
    for asset in freeze["inputs"]:
        for path_key, hash_key in (("path", "sha256"), ("original_path", "original_sha256")):
            require(file_sha256(Path(asset[path_key])) == asset[hash_key], "input_modified", "Frozen source/reference bytes changed")
    if spec["spatial"].get("mask_path"):
        require(file_sha256(Path(spec["spatial"]["mask_path"])) == spec["spatial"]["mask_sha256"], "input_modified", "Frozen mask changed")
    if spec.get("shared_intent"):
        require(file_sha256(Path(spec["shared_intent"])) == spec["shared_intent_sha256"], "input_modified", "Frozen shared intent changed")
    return spec, config, state


def validate_request(request: dict) -> None:
    require(request.get("schema_version") == "hre_model_request_v3", "request_invalid", "Expected a v3 native model request")
    require(request.get("profile_id") in CATALOG, "profile_invalid", "Unknown model profile")
    require(request.get("task_mode") in {"restoration", "reference_enhance"}, "task_mode_invalid", "Unknown task mode")
    expected_roles = ["source"] + (["appearance_reference"] if request["task_mode"] == "reference_enhance" else [])
    require([asset.get("role") for asset in request.get("inputs", [])] == expected_roles,
            "input_roles_invalid", "Input roles and order must match the task contract")
    require(request.get("strategy") in {"native", "shared", "model_aware"}, "strategy_invalid", "Unknown condition strategy")
    require((request.get("intent") is None) == (request["strategy"] == "native"), "intent_invalid", "Native has no intent; shared/model-aware require an intent")
    for key in ("width", "height"):
        require(type(request.get("canvas", {}).get(key)) is int and request["canvas"][key] > 0,
                "canvas_invalid", "Explicit positive source canvas required")
    require(type(request.get("seed")) is int and 0 <= request["seed"] < 2**63, "seed_invalid", "Invalid execution seed")
    require(isinstance(request.get("brief"), str) and request["brief"].strip(), "brief_required", "Empty instruction")
    spatial = request.get("spatial", {"mode": "full_frame"})
    supported = set(CATALOG[request["profile_id"]]["spatial_modes"]) - {"crop_and_fuse"}
    require(isinstance(spatial, dict) and spatial.get("mode") in supported,
            "spatial_unsupported", "Native requests must use a prepared, supported spatial mode")
    if spatial["mode"] == "native_mask":
        require(len(request["inputs"]) == 1 and bool(spatial.get("mask_path")), "mask_reference_conflict",
                "Native mask requires one source and an explicit mask")
    if spatial["mode"] == "bbox":
        require(isinstance(spatial.get("boxes"), list) and spatial["boxes"], "bbox_required", "Empty native bbox request")
