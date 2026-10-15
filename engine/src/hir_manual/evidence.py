"""Offline evidence validation and immutable registration files.

Assets normally have case-relative paths. A portable external evidence bundle
may instead use paths relative to the manifest's parent (no traversal or links
outside that parent). Such assets are copied by hash into the case and paths in
the returned manifest/data are rewritten. Neither mode updates state.

Depth data: depth_kind (relative/inverse/metric), legend {near, far}, optional
depth_asset and invalid_mask asset paths. Segmentation data: labels as a list
of {id, label/name} or an ID-to-name object, background_id and ignore_id (null
when absent), optional labels_asset. Masks use true/1 for invalid pixels.
"""
import io
import math
from pathlib import Path

import numpy as np
from PIL import Image

from .models import EvidenceManifest, State
from .protocol import check_bboxes, validate_schema
from .storage import CasePaths, atomic_write, json_bytes, read_json, resolve_case_path, sha256_bytes, sha256_file
from .transport import MAX_BYTES, MAX_PIXELS, _decode


def missing_evidence(state: State) -> list[str]:
    return list(dict.fromkeys(tool for tool in state.required_tools if tool not in state.received_tools))


def _array(raw: bytes):
    try:
        # Validate the advertised shape before numpy allocates from an untrusted
        # header. allow_pickle=False alone does not prevent huge allocations.
        stream = io.BytesIO(raw)
        version = np.lib.format.read_magic(stream)
        if version == (1, 0):
            shape, _, dtype = np.lib.format.read_array_header_1_0(stream)
        elif version == (2, 0):
            shape, _, dtype = np.lib.format.read_array_header_2_0(stream)
        else:
            raise ValueError("Unsupported NPY header version")
        if dtype.hasobject:
            raise ValueError("NPY pickle/object arrays are prohibited")
        if len(shape) != 2 or any(size < 1 for size in shape) or math.prod(shape) > MAX_PIXELS:
            raise ValueError("NPY dimensions exceed pixel limit or are not an image")
        if math.prod(shape) * dtype.itemsize != len(raw) - stream.tell():
            raise ValueError("NPY data size does not match its header")
        values = np.load(io.BytesIO(raw), allow_pickle=False)
    except (ValueError, OSError, EOFError) as exc:
        raise ValueError(f"Invalid NPY: {exc}") from exc
    if not isinstance(values, np.ndarray) or values.dtype.hasobject:
        raise ValueError("Only safe NPY arrays are supported")
    return values


def _asset_bytes(case, manifest_file, asset):
    relative = asset["path"]
    local = case.path(relative)  # Validate even when this path does not exist.
    if local.exists():
        source = local
    elif not manifest_file.resolve().is_relative_to(case.case_dir):
        source = resolve_case_path(manifest_file.parent, relative)
    else:
        raise ValueError("Missing case evidence asset")
    if source.suffix.lower() in (".tmp", ".part") or not source.is_file():
        raise ValueError("Incomplete evidence asset")
    if source.stat().st_size > MAX_BYTES:
        raise ValueError("Evidence asset exceeds byte limit")
    raw = source.read_bytes()
    if sha256_bytes(raw) != asset["sha256"]:
        raise ValueError("Evidence asset hash mismatch")
    if asset["kind"] in ("photo", "map", "overlay"):
        image = _decode(raw, {})
        if image.size != (asset["width"], asset["height"]):
            raise ValueError("Declared evidence image dimensions mismatch")
    elif asset["width"] is not None or asset["height"] is not None:
        raise ValueError("Non-image dimensions must be null")
    return source, raw


def _select_array(data, entries, key, predicate):
    explicit = data.get(key)
    candidates = [entry for entry in entries if predicate(entry)]
    if explicit is not None:
        candidates = [entry for entry in candidates if entry["asset"]["path"] == explicit]
    if len(candidates) != 1:
        raise ValueError(f"Provide one unambiguous {key} raw asset")
    return candidates[0]


def _map_required(entries, manifest):
    maps = [entry for entry in entries if entry["asset"]["kind"] == "map"]
    if not maps:
        raise ValueError("Successful depth/segmentation evidence requires a visible map")
    for entry in maps:
        if (entry["asset"]["width"], entry["asset"]["height"]) != (manifest["tool_width"], manifest["tool_height"]):
            raise ValueError("Tool map dimensions must match tool coordinates")


def _depth(manifest, entries):
    data = manifest["data"]
    if data.get("depth_kind") not in ("relative", "inverse", "metric"):
        raise ValueError("depth_kind must be relative, inverse, or metric")
    legend = data.get("legend")
    if not isinstance(legend, dict) or any(key not in legend or legend[key] is None or legend[key] == "" for key in ("near", "far")):
        raise ValueError("Depth requires near/far legend")
    _map_required(entries, manifest)
    mask_path = data.get("invalid_mask")
    entry = _select_array(data, entries, "depth_asset", lambda item: item["asset"]["kind"] == "raw_data" and item["source"].suffix.lower() == ".npy" and item["asset"]["path"] != mask_path)
    values = _array(entry["raw"])
    shape = (manifest["tool_height"], manifest["tool_width"])
    if values.dtype != np.dtype("float32") or values.shape != shape:
        raise ValueError("Depth must be float32 with tool image shape")
    invalid = np.zeros(shape, dtype=bool)
    if mask_path is not None:
        masks = [entry for entry in entries if entry["asset"]["path"] == mask_path]
        if len(masks) != 1:
            raise ValueError("Invalid mask must reference a declared asset")
        mask = masks[0]
        if mask["source"].suffix.lower() == ".npy":
            mask_values = _array(mask["raw"])
        else:
            image = _decode(mask["raw"], {})
            if image.format != "PNG":
                raise ValueError("Invalid mask must be lossless PNG or NPY")
            mask_values = np.asarray(image)
        if mask_values.shape != shape or mask_values.dtype.kind not in "bui" or not np.isin(mask_values, [0, 1]).all():
            raise ValueError("Invalid mask must be binary and have tool image shape")
        invalid = mask_values.astype(bool)
    if invalid.all() or not np.isfinite(values[~invalid]).all():
        raise ValueError("Depth needs finite values and at least one valid pixel")


def _label_table(data):
    labels = data.get("labels")
    table = {}
    if isinstance(labels, dict):
        for key, name in labels.items():
            if not isinstance(key, str) or not key.lstrip("-").isdigit() or not isinstance(name, str) or not name.strip():
                raise ValueError("Invalid segmentation label table")
            number = int(key)
            if number in table:
                raise ValueError("Duplicate segmentation label ID")
            table[number] = name
    elif isinstance(labels, list):
        for label in labels:
            if not isinstance(label, dict) or type(label.get("id")) is not int:
                raise ValueError("Invalid segmentation label ID")
            number = label["id"]
            name = label.get("label", label.get("name"))
            if not isinstance(name, str) or not name.strip() or number in table:
                raise ValueError("Invalid or duplicate segmentation label")
            table[number] = name
    if not table:
        raise ValueError("Segmentation requires a label table")
    if type(data.get("background_id")) is not int or data["background_id"] not in table:
        raise ValueError("Segmentation background_id must be in label table")
    if "ignore_id" not in data or (data["ignore_id"] is not None and type(data["ignore_id"]) is not int):
        raise ValueError("Segmentation requires explicit ignore_id or null")
    return table


def _segmentation(manifest, entries):
    data = manifest["data"]
    table = _label_table(data)
    _map_required(entries, manifest)
    entry = _select_array(data, entries, "labels_asset", lambda item: item["asset"]["kind"] == "raw_data")
    if entry["source"].suffix.lower() == ".npy":
        values = _array(entry["raw"])
    else:
        image = _decode(entry["raw"], {})
        if image.format != "PNG" or image.mode not in ("1", "L", "P", "I", "I;16", "I;16L", "I;16B"):
            raise ValueError("Segmentation labels require lossless integer PNG/NPY")
        values = np.asarray(image)
    if values.shape != (manifest["tool_height"], manifest["tool_width"]) or values.dtype.kind not in "ui":
        raise ValueError("Segmentation labels must have integer tool image shape")
    ids = set(int(value) for value in np.unique(values))
    ignore = data["ignore_id"]
    visible = ids - ({ignore} if ignore is not None else set())
    if visible != set(table):
        raise ValueError("Segmentation pixel IDs must match the label table")


def _rewrite(value, paths):
    if isinstance(value, dict):
        return {key: _rewrite(item, paths) for key, item in value.items()}
    if isinstance(value, list):
        return [_rewrite(item, paths) for item in value]
    return paths.get(value, value) if isinstance(value, str) else value


def register_evidence(case: CasePaths, manifest_file: Path) -> EvidenceManifest:
    manifest_file = Path(manifest_file)
    manifest = read_json(manifest_file)
    validate_schema("evidence.schema.json", manifest, case.path("snapshot/schemas"))
    check_bboxes(manifest)
    state = State.model_validate(read_json(case.path("state.json")))
    if manifest["tool_id"] not in state.required_tools:
        raise ValueError("Tool is not in locked diagnosis plan")
    canonical = case.path("input/canonical.png")
    if manifest["input_sha256"] != state.input_sha256 or manifest["input_sha256"] != sha256_file(canonical):
        raise ValueError("Evidence source SHA does not match locked canonical")
    with Image.open(canonical) as image:
        image.load()
        if image.size != (manifest["source_width"], manifest["source_height"]):
            raise ValueError("Evidence source dimensions do not match canonical")
    if manifest["tool_width"] * manifest["tool_height"] > MAX_PIXELS:
        raise ValueError("Tool dimensions exceed pixel limit")
    matrix = np.asarray(manifest["source_to_tool"], dtype=np.float64)
    if not np.isfinite(matrix).all() or not np.array_equal(matrix[2], [0, 0, 1]) or np.linalg.det(matrix[:2, :2]) == 0:
        raise ValueError("source_to_tool must be a nonsingular affine transform")
    if manifest["status"] == "ok" and manifest["error"] is not None:
        raise ValueError("Successful evidence cannot contain an error")
    if manifest["status"] == "error" and (not isinstance(manifest["error"], str) or not manifest["error"].strip()):
        raise ValueError("Error evidence requires an error message")
    entries = []
    paths = [asset["path"] for asset in manifest["assets"]]
    if len(set(paths)) != len(paths):
        raise ValueError("Evidence assets must have distinct paths")
    for asset in manifest["assets"]:
        source, raw = _asset_bytes(case, manifest_file, asset)
        entries.append({"asset": asset, "source": source, "raw": raw})
    if manifest["status"] == "ok":
        if manifest["tool_id"] == "T3_DEPTH":
            _depth(manifest, entries)
        elif manifest["tool_id"] == "T4_SEGMENTATION":
            _segmentation(manifest, entries)
        elif manifest["detections"] and not any(entry["asset"]["kind"] in ("json", "raw_data") for entry in entries):
            raise ValueError("Nonempty OCR/face detections require raw output evidence")
    # Copy all evidence, including existing case assets, into immutable hash
    # locations. Later edits to a user's upload cannot change registered evidence.
    replacements = {}
    for entry in entries:
        asset = entry["asset"]
        extension = entry["source"].suffix.lower()
        if not extension or any(char not in ".abcdefghijklmnopqrstuvwxyz0123456789" for char in extension):
            extension = ".bin"
        relative = f"tools/{manifest['tool_id']}/assets/{asset['sha256']}{extension}"
        destination = case.path(relative)
        if destination.exists():
            if destination.read_bytes() != entry["raw"]:
                raise ValueError("Immutable evidence asset conflict")
        else:
            atomic_write(destination, entry["raw"])
        replacements[asset["path"]] = relative
        asset["path"] = relative
    manifest["data"] = _rewrite(manifest["data"], replacements)
    result = EvidenceManifest.model_validate(manifest)
    raw = json_bytes(result)
    digest = sha256_bytes(raw)
    version = case.path(f"tools/{result.tool_id}/versions/{digest}/evidence.json")
    if version.exists() and version.read_bytes() != raw:
        raise ValueError("Immutable evidence manifest conflict")
    if not version.exists():
        atomic_write(version, raw)
    current = case.path(f"tools/{result.tool_id}/evidence.json")
    if not current.exists():
        atomic_write(current, raw)
    return result
