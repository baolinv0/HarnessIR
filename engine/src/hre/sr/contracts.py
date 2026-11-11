"""Frozen SR domain boundaries, source identity and exact LR-to-HR geometry."""
from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path
import re
from urllib.parse import urlsplit

from PIL import Image

from ..models import HREError, file_sha256, sha256_bytes
from ..storage import read_json
from ..v3.common import digest, require, validate_chat_settings

PROTOCOL_VERSION = "hre_sr_v02"
FIXTURE_MARKER = "SR_TEST_FIXTURE_NOT_MODEL_QUALITY"
SLOTS = ("C0", "C1", "C2", "C3")
METHODS = ("lr_consistency_v1", "clipping_v1", "edge_energy_v1")
LAYOUT_VERSION = "sr_anonymous_full_and_roi_v1"
PREFILTER = {"method": "Pillow.GaussianBlur", "radius": 0.35, "version": "sr_mild_prefilter_v1"}


def object_fields(value, allowed: set[str], name: str) -> dict:
    require(isinstance(value, dict) and not set(value) - allowed, "sr_schema_invalid",
            f"{name} must be an object with only: {', '.join(sorted(allowed))}")
    return value


def finite(value) -> None:
    if isinstance(value, dict):
        for item in value.values():
            finite(item)
    elif isinstance(value, list):
        for item in value:
            finite(item)
    elif isinstance(value, float):
        require(math.isfinite(value), "sr_nonfinite", "Nonfinite numbers are forbidden")


def opaque_image(path: Path) -> Image.Image:
    try:
        with Image.open(path) as opened:
            opened.load()
            require(opened.mode in {"RGB", "RGBA", "L", "LA", "P"}, "sr_image_mode",
                    "SR accepts canonical eight-bit SDR images")
            rgba = opened.convert("RGBA")
            require(rgba.getchannel("A").getextrema() == (255, 255), "sr_alpha_unsupported",
                    "SR v0.2 requires opaque source and outputs; transparency cannot be flattened")
            return opened.convert("RGB")
    except (OSError, ValueError) as exc:
        raise HREError("sr_image_decode", f"Cannot decode image: {path}") from exc


def asset(path: Path) -> dict:
    image = opaque_image(path)
    return {"path": str(path.resolve()), "sha256": file_sha256(path),
            "width": image.width, "height": image.height, "mode": "RGB"}


def opaque_pixel_sha256(path: Path) -> str:
    image = opaque_image(path)
    return sha256_bytes(image.mode.encode() + str(image.size).encode() + image.tobytes())


def verify_asset(record: dict, code="sr_artifact_modified") -> None:
    path = Path(record["path"])
    require(path.is_file() and file_sha256(path) == record["sha256"], code,
            "Frozen artifact is missing or changed: " + str(path))


def normalise_spec(spec: dict) -> dict:
    object_fields(spec, {"schema_version", "case_id", "source", "scale", "seed", "rois",
                         "alpha_policy", "colour_policy", "evidence_profile"}, "SR task")
    finite(spec)
    value = deepcopy(spec)
    require(value.get("schema_version", PROTOCOL_VERSION) == PROTOCOL_VERSION,
            "sr_version_invalid", "Create a new hre_sr_v02 case")
    value["schema_version"] = PROTOCOL_VERSION
    value.setdefault("case_id", "sr_" + digest(spec)[:16])
    require(isinstance(value["case_id"], str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value["case_id"]),
            "sr_case_id_invalid", "Use a simple case ID of at most 128 characters")
    source = object_fields(value.get("source"), {"path"}, "source")
    require(isinstance(source.get("path"), str) and source["path"].strip(), "sr_source_required", "Supply the original LR source")
    value.setdefault("scale", 4)
    require(type(value["scale"]) is int and value["scale"] == 4, "sr_scale_unsupported",
            "This real-model profile supports integer x4 only")
    value.setdefault("seed", 0)
    require(type(value["seed"]) is int and 0 <= value["seed"] < 2**32, "sr_seed_invalid",
            "Freeze an integer seed in [0, 2**32)")
    value.setdefault("alpha_policy", "require_opaque")
    require(value["alpha_policy"] == "require_opaque", "sr_alpha_policy", "Only require_opaque is supported")
    value.setdefault("colour_policy", "assume_srgb")
    require(value["colour_policy"] in {"assume_srgb", "require_icc"}, "sr_colour_policy", "Unknown colour policy")
    require(isinstance(value.get("rois", []), list), "sr_roi_invalid", "rois must be a list")
    profile = object_fields(value.get("evidence_profile", {}), {"methods", "selection", "selection_receipt"}, "evidence_profile")
    profile = {"methods": list(METHODS), "selection": "provisional", **profile}
    require(isinstance(profile["methods"], list) and profile["methods"] and all(isinstance(method, str) and method in METHODS for method in profile["methods"])
            and len(set(profile["methods"])) == len(profile["methods"]), "sr_evidence_profile", "Choose known, distinct proxy methods")
    require(profile["selection"] in {"provisional", "development_selected"}, "sr_evidence_profile", "Unknown selection status")
    if profile["selection"] == "development_selected":
        require(isinstance(profile.get("selection_receipt"), str), "sr_selection_receipt", "Selected proxies require a development freeze receipt")
        path = Path(profile["selection_receipt"]).expanduser().resolve()
        from .study import verified_conditions
        require(path.name == "conditions.json", "sr_selection_receipt", "Use the committed study conditions.json receipt")
        receipt = verified_conditions(path.parent)
        require(receipt.get("schema_version") == "hre_sr_study_freeze_v02" and receipt.get("real_development_complete") is True
                and receipt.get("selected_methods") == profile["methods"], "sr_selection_receipt", "Development selection receipt does not match")
        profile["selection_receipt"] = {"path": str(path), "sha256": file_sha256(path)}
    else:
        require("selection_receipt" not in profile, "sr_selection_receipt", "A provisional profile has no development receipt")
    value["evidence_profile"] = profile
    return value


def normalise_config(config: dict) -> dict:
    object_fields(config, {"mode", "models", "judge", "fixture", "fixture_marker"}, "SR config")
    finite(config)
    value = deepcopy(config)
    value.setdefault("mode", "real")
    require(value["mode"] in {"real", "fixture"}, "sr_mode_invalid", "mode is real or explicit fixture")
    if value["mode"] == "fixture":
        require(value.get("fixture_marker") == FIXTURE_MARKER, "sr_fixture_marker", "Test fixtures require their explicit marker")
        require("models" not in value, "sr_fixture_config", "Fixtures cannot impersonate deployed models")
        fixture = object_fields(value.get("fixture", {}), {"candidates", "judge"}, "fixture")
        candidates = object_fields(fixture.get("candidates", {}), set(SLOTS), "fixture.candidates")
        require(all(x in {"ok", "fail", "blocked", "wrong_size", "transparent", "corrupt", "crash"} for x in candidates.values()),
                "sr_fixture_config", "Unknown fixture candidate behavior")
        judgement = object_fields(fixture.get("judge", {}), {"content", "improved", "ranking", "behavior"}, "fixture.judge")
        content = object_fields(judgement.get("content", {}), set(SLOTS), "fixture.judge.content")
        require(all(x in {"pass", "fail", "uncertain"} for x in content.values()), "sr_fixture_config", "Invalid fixture content status")
        for key in ("improved", "ranking"):
            items = judgement.get(key, [])
            require(isinstance(items, list) and len(items) == len(set(items)) and all(x in SLOTS[1:] for x in items),
                    "sr_fixture_config", "Fixture candidate lists need distinct non-baseline slots")
        require(judgement.get("behavior", "ok") in {"ok", "invalid", "truncated", "unavailable", "crash"},
                "sr_fixture_config", "Unknown fixture Judge behavior")
        value["fixture"] = {"candidates": {slot: "ok" for slot in SLOTS} | candidates,
                            "judge": {"content": {slot: "pass" for slot in SLOTS} | content,
                                      "improved": judgement.get("improved", []),
                                      "ranking": judgement.get("ranking", list(SLOTS[1:])),
                                      "behavior": judgement.get("behavior", "ok")}}
    else:
        require("fixture" not in value and "fixture_marker" not in value, "sr_fixture_config", "Fixture settings require fixture mode")
        from .adapters import normalise_models
        value["models"] = normalise_models(value.get("models", {}))
    judge = object_fields(value.get("judge", {}), {"base_url", "model", "settings", "timeout_seconds", "api_key_env", "response_format"}, "judge")
    judge = {"settings": {"temperature": 0, "max_tokens": 4096, "seed": 0}, "timeout_seconds": 600,
             "response_format": "json_object", **judge}
    validate_chat_settings(judge["settings"])
    for key, item in judge["settings"].items():
        if key in {"max_tokens", "max_completion_tokens", "seed", "thinking_token_budget"}:
            require(type(item) is int and item >= 0 and (key not in {"max_tokens", "max_completion_tokens"} or item > 0),
                    "sr_judge_settings", f"{key} requires a nonnegative integer (positive token limit)")
        if key in {"temperature", "top_p", "presence_penalty", "frequency_penalty"}:
            require(type(item) in {int, float} and math.isfinite(item), "sr_judge_settings", f"{key} must be finite numeric")
    require(type(judge["timeout_seconds"]) in {int, float} and math.isfinite(judge["timeout_seconds"]) and judge["timeout_seconds"] > 0,
            "sr_judge_settings", "Positive finite Judge timeout required")
    require(judge["response_format"] in {"json_object", "json_schema", "none"}, "sr_judge_settings", "Unknown response format")
    if judge.get("base_url"):
        parsed = urlsplit(judge["base_url"])
        require(parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password
                and not parsed.query and not parsed.fragment, "sr_judge_endpoint", "Use an explicit credential-free HTTP(S) endpoint")
    if "model" in judge:
        require(isinstance(judge["model"], str) and judge["model"].strip(), "sr_judge_endpoint", "Set the deployed Judge model")
    if "api_key_env" in judge:
        require(isinstance(judge["api_key_env"], str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", judge["api_key_env"]),
                "sr_judge_endpoint", "Use an environment-variable name for credentials")
    value["judge"] = judge
    return value


def geometry_and_rois(spec: dict, source: dict) -> tuple[dict, list[dict]]:
    width, height = source["width"], source["height"]
    scale = spec["scale"]
    geometries = {}
    for slot, grid, minimum in (("C0", 1, 1), ("C1", 1, 1), ("C2", 2, 128), ("C3", 8, 8)):
        pw, ph = (((max(d, minimum) + grid - 1) // grid) * grid for d in (width, height))
        geometries[slot] = {"lr": [width, height], "padded_lr": [pw, ph], "native_hr": [pw * scale, ph * scale],
                            "target_hr": [width * scale, height * scale], "crop": [0, 0, width * scale, height * scale],
                            "pad_lrtb": [0, pw - width, 0, ph - height], "padding": "edge_right_bottom", "scale": scale}
    rois = spec.get("rois")
    if rois is None:
        rois = [{"id": "center", "box": [width // 4, height // 4, max(width // 4 + 1, 3 * width // 4), max(height // 4 + 1, 3 * height // 4)]}]
    require(1 <= len(rois) <= 16, "sr_roi_invalid", "Freeze one to sixteen original-source ROIs")
    result, ids = [], set()
    for region in rois:
        object_fields(region, {"id", "box"}, "ROI")
        rid, box = region.get("id"), region.get("box")
        require(isinstance(rid, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", rid) and rid not in ids,
                "sr_roi_invalid", "Use distinct simple ROI IDs")
        require(isinstance(box, list) and len(box) == 4 and all(type(n) is int for n in box)
                and 0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height,
                "sr_roi_invalid", "ROI boxes are integer original-LR pixel coordinates [x0,y0,x1,y1]")
        ids.add(rid)
        result.append({"id": rid, "source_box": box, "hr_box": [n * scale for n in box]})
    return geometries, result


def recipes(seed: int) -> list[dict]:
    return [{"slot": slot, "model_key": key, "source": "original_lr", "seed": seed,
             "preprocess": PREFILTER if slot == "C1" else {"method": "identity", "version": "sr_identity_v1"}}
            for slot, key in (("C0", "reconstruction"), ("C1", "reconstruction"), ("C2", "seesr"), ("C3", "qwen"))]


def protocol_identity(case: dict) -> dict:
    """Across cases, source pixels and ROI positions are intentionally not conditions."""
    return {"schema_version": PROTOCOL_VERSION, "scale": case["task"]["scale"], "recipes": case["recipes"],
            "models": case["config"].get("models"), "deployments": case["deployments"],
            "judge": case["config"]["judge"], "alpha_policy": case["task"]["alpha_policy"],
            "colour_policy": case["task"]["colour_policy"], "layout_version": LAYOUT_VERSION,
            "roi_policy": "frozen_original_pixel_boxes_scaled_exactly_v1",
            "geometry_policy": "right_bottom_edge_pad_exact_x4_crop_v1", "code": case["code"]}
