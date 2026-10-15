"""File/manual adapters. Only the controller may advance case state.

Adapters archive raw input, validate it against an immutable request, commit
response bytes atomically, and publish done last. Discovery never uses Downloads
or temporary files and never infers a case from file timestamps.
"""
import io
import re
import uuid
from pathlib import Path

from PIL import Image, ImageCms, UnidentifiedImageError

from .models import ImportResult, Request, Response
from .protocol import parse_time, strict_loads, validate_asset, validate_response, validate_schema
from .storage import CasePaths, atomic_write, json_bytes, now, read_json, sha256_bytes, write_json

FORMATS = {"PNG": "png", "JPEG": "jpg", "TIFF": "tiff", "WEBP": "webp", "BMP": "bmp"}
MAX_BYTES = 50 * 1024 * 1024
MAX_PIXELS = 40_000_000


def _task_request(case: CasePaths, task_id: str) -> Request:
    if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", task_id):
        raise ValueError("Invalid task identity")
    data = read_json(case.path(f"tasks/{task_id}/request.json"))
    validate_schema("request.schema.json", data, case.path("snapshot/schemas"))
    request = Request.model_validate(data)
    prefix = f"tasks/{task_id}/"
    if request.task_id != task_id or request.case_id != case.case_id:
        raise ValueError("Request identity mismatch")
    if request.response_file != prefix + "response.json" or request.ready_marker != prefix + "done.json":
        raise ValueError("Request response/done path does not belong to task")
    return request


def _archive(case, task_id, raw: bytes, extension="txt"):
    atomic_write(case.path(f"tasks/{task_id}/raw/{uuid.uuid4().hex}.{extension}"), raw)


def _ensure_unaccepted(case, task_id):
    accepted = case.path(f"tasks/{task_id}/accepted")
    if accepted.exists() and any(accepted.iterdir()):
        raise ValueError("Task already has an accepted official response")


def _envelope(request, payload, provenance):
    provenance = dict(provenance)
    if provenance.get("writer") != "supported_bridge":
        provenance.update(writer="manual_import", transport_mode="clipboard_import")
    result = {key: getattr(request, key) for key in ("protocol_version", "task_id", "case_id", "role", "round", "expected_state_revision", "input_sha256")}
    result.update(status="ok", payload=payload, error=None, provenance=provenance)
    return result


def _response_assets(request, response, case):
    assets = []
    if response.role == "execute" and response.status == "ok":
        payload = response.payload
        assets = [payload["output_asset"], *payload["extra_assets"]]
        if payload["input_image_sha256"] != request.input_sha256 or payload["instruction_sha256"] != request.context["instruction_sha256"]:
            raise ValueError("Editor input/instruction hash mismatch")
        if payload["actual_generations"] != len(assets):
            raise ValueError("Generation count must include all provider images")
        paths = [asset["path"] for asset in assets]
        if len(set(paths)) != len(paths):
            raise ValueError("Output assets must have distinct paths")
        for asset in assets:
            if not asset["path"].startswith(f"tasks/{request.task_id}/"):
                raise ValueError("Output asset belongs to another task")
            validate_asset(case, asset)
    return assets


def _publish(case, request, response, assets):
    # Remove an earlier unaccepted marker before replacing anything it attests.
    case.path(request.ready_marker).unlink(missing_ok=True)
    raw = json_bytes(response)
    atomic_write(case.path(request.response_file), raw)
    committed = now()
    if parse_time(committed) < parse_time(response.provenance["completed_at"]):
        raise ValueError("Response completion is in the future")
    marker = {"task_id": request.task_id, "response_file": request.response_file, "response_sha256": sha256_bytes(raw), "artifact_hashes": [{"path": asset["path"], "sha256": asset["sha256"]} for asset in assets], "committed_at": committed}
    validate_schema("done.schema.json", marker, case.path("snapshot/schemas"))
    write_json(case.path(request.ready_marker), marker)
    return ImportResult(accepted=True, code="ready", message="结果已保存，等待 Controller 校验提交")


def import_payload(case: CasePaths, task_id: str, raw: str, provenance: dict) -> ImportResult:
    request = _task_request(case, task_id)
    if not isinstance(raw, str):
        raise ValueError("Raw JSON must be UTF-8 text")
    _archive(case, task_id, raw.encode("utf-8"))
    _ensure_unaccepted(case, task_id)
    data = strict_loads(raw)
    # A complete envelope is validated as provided; partial envelopes cannot be
    # mistaken for payloads because the locked stage schema forbids their fields.
    response = Response.model_validate(data if "protocol_version" in data or "provenance" in data else _envelope(request, data, provenance))
    validate_response(request, response, case)
    assets = _response_assets(request, response, case)
    return _publish(case, request, response, assets)


def _decode(raw: bytes, config: dict):
    byte_limit = min(MAX_BYTES, config.get("max_output_bytes", config.get("max_input_bytes", MAX_BYTES)))
    pixel_limit = min(MAX_PIXELS, config.get("max_output_pixels", config.get("max_input_pixels", MAX_PIXELS)))
    if len(raw) > byte_limit:
        raise ValueError("Image exceeds byte limit")
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in FORMATS or getattr(image, "n_frames", 1) != 1:
                raise ValueError("Use one supported complete display-domain image")
            if image.width * image.height > pixel_limit:
                raise ValueError("Image exceeds pixel limit")
            image.verify()
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            result = image.copy()
            result.info = dict(image.info)
            result.format = image.format
            return result
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError("Image is corrupt or cannot be fully decoded") from exc


def _observations(image, canonical: Path, config: dict):
    width, height = image.size
    with Image.open(canonical) as original:
        original.load()
        input_width, input_height = original.size
    error = abs((width / height) / (input_width / input_height) - 1)
    has_alpha = "A" in image.getbands() or "transparency" in image.info
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    has_transparency = alpha.getextrema()[0] < 255
    rgb = Image.alpha_composite(Image.new("RGBA", image.size, "white"), rgba).convert("RGB")
    icc = image.info.get("icc_profile")
    if icc:
        try:
            rgb = ImageCms.profileToProfile(rgb, ImageCms.ImageCmsProfile(io.BytesIO(icc)), ImageCms.createProfile("sRGB"), outputMode="RGB")
        except (OSError, ValueError, ImageCms.PyCMSError) as exc:
            raise ValueError("Cannot interpret output ICC profile") from exc
    return {"pixel_sha256": sha256_bytes(rgb.tobytes()), "valid_geometry": error <= config.get("aspect_ratio_relative_tolerance", .02), "valid_image_constraints": image.mode == "RGB" and not has_transparency, "width": width, "height": height, "input_width": input_width, "input_height": input_height, "aspect_ratio_relative_error": error, "exact_size_match": image.size == (input_width, input_height), "format": image.format, "source_mode": image.mode, "has_alpha": has_alpha, "has_transparency": has_transparency, "alpha_evaluation_background": "white" if has_alpha else None, "embedded_icc": bool(icc), "colour_assumption": "ICC_to_sRGB" if icc else "sRGB", "exif_orientation": image.getexif().get(274, 1)}


def image_observations(output: Path, canonical: Path, config: dict) -> dict:
    output = Path(output)
    if output.suffix.lower() in (".tmp", ".part"):
        raise ValueError("Incomplete image file")
    if output.stat().st_size > min(MAX_BYTES, config.get("max_output_bytes", config.get("max_input_bytes", MAX_BYTES))):
        raise ValueError("Image exceeds byte limit")
    return _observations(_decode(output.read_bytes(), config), canonical, config)


def import_image(case: CasePaths, task_id: str, source: Path, provenance: dict, *, actual_generations=1, extras=None, provider_settings=None, save_method="manual_download", seed_control=False) -> ImportResult:
    request = _task_request(case, task_id)
    _ensure_unaccepted(case, task_id)
    if request.role != "execute":
        raise ValueError("Images may only be imported into execute tasks")
    sources = [Path(source), *(Path(path) for path in (extras or []))]
    if type(actual_generations) is not int or actual_generations != len(sources):
        raise ValueError("Generation count must equal source plus all provider extras")
    config = read_json(case.path("case_config.json"))
    prepared = []
    for index, path in enumerate(sources):
        if path.suffix.lower() in (".part", ".tmp"):
            raise ValueError("Incomplete image file")
        if path.stat().st_size > min(MAX_BYTES, config.get("max_output_bytes", config.get("max_input_bytes", MAX_BYTES))):
            raise ValueError("Image exceeds byte limit")
        raw = path.read_bytes()
        _archive(case, task_id, raw, "bin")
        image = _decode(raw, config)
        # Geometry observations do not veto a decodable algorithm output.
        _observations(image, case.path("input/canonical.png"), config)
        relative = f"tasks/{task_id}/" + ("output" if index == 0 else f"extras/output_{index:03d}") + "." + FORMATS[image.format]
        prepared.append((raw, {"path": relative, "sha256": sha256_bytes(raw), "kind": "photo", "width": image.width, "height": image.height}))
    assets = [asset for _, asset in prepared]
    payload = {"output_asset": assets[0], "input_image_sha256": request.input_sha256, "instruction_sha256": request.context["instruction_sha256"], "provider_sequence_index": 0, "actual_generations": actual_generations, "extra_assets": assets[1:], "save_method": save_method, "provider_settings": {} if provider_settings is None else provider_settings, "seed_control": seed_control}
    response = Response.model_validate(_envelope(request, payload, provenance))
    validate_response(request, response, case)
    case.path(request.ready_marker).unlink(missing_ok=True)
    for raw, asset in prepared:
        atomic_write(case.path(asset["path"]), raw)
    _response_assets(request, response, case)
    return _publish(case, request, response, assets)


def scan_ready(root: Path) -> list[Path]:
    root = Path(root).resolve()
    found = []
    for marker in sorted((root / "cases").glob("*/tasks/*/done.json")):
        if marker.is_file() and marker.resolve().is_relative_to(root / "cases"):
            found.append(marker.resolve())
    return found
