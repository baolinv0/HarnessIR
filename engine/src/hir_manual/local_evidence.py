"""Strict v1.1 production evidence validation, distinct from legacy evidence."""
import json
import numpy as np
from PIL import Image
from .evidence import _array, _rewrite
from .protocol import validate_schema, check_bboxes
from .storage import read_json, resolve_case_path, sha256_file
from .tool_registry import bundle_hash, canonical_json
from .tool_models import LocalEvidenceManifest
from .storage import sha256_bytes

PAYLOADS = {"T1_OCR": "tool_payload_ocr.schema.json", "T2_FACE": "tool_payload_face.schema.json", "T3_DEPTH": "tool_payload_depth.schema.json", "T4_SEGMENTATION": "tool_payload_segmentation.schema.json"}


def _grid(root, relative):
    path = resolve_case_path(root, relative)
    if path.suffix == ".npy":
        # Original-size GPU depth can exceed 50 MiB (e.g. 22 MP float32).
        # Inspect its bounded numeric header before mapping, without making two
        # full copies in the low-memory local Controller.
        import math
        try:
            with path.open('rb') as stream:
                version = np.lib.format.read_magic(stream)
                reader = {(1, 0): np.lib.format.read_array_header_1_0,
                          (2, 0): np.lib.format.read_array_header_2_0}.get(version)
                if reader is None:
                    raise ValueError('Unsupported NPY header version')
                shape, _, dtype = reader(stream)
                if dtype.hasobject or dtype.fields or dtype.kind not in 'buif' or dtype.itemsize > 8:
                    raise ValueError('Only bounded numeric image grids are supported')
                if len(shape) != 2 or any(s < 1 for s in shape) or math.prod(shape) > 40_000_000:
                    raise ValueError('NPY dimensions exceed pixel limit')
                if math.prod(shape)*dtype.itemsize != path.stat().st_size-stream.tell():
                    raise ValueError('NPY data size does not match its header')
            return np.load(path, allow_pickle=False, mmap_mode='r')
        except (OSError, EOFError) as error:
            raise ValueError('Invalid NPY grid') from error
    with Image.open(path) as im:
        if im.width*im.height > 40_000_000:
            raise ValueError("Grid too large")
        im.load()
        if im.format != "PNG":
            raise ValueError("Masks/labels must use lossless PNG or NPY")
        return np.asarray(im)


def _paths(value):
    found = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key.endswith("_path") and isinstance(item, str):
                found.add(item)
            found.update(_paths(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_paths(item))
    return found


def validate_local_evidence(directory, contract=None):
    try:
        return _validate_local_evidence(directory,contract)
    except (TypeError,KeyError,IndexError,OverflowError) as exc:
        raise ValueError("Malformed native evidence: " + str(exc)) from exc


def _validate_local_evidence(directory, contract=None):
    directory = __import__("pathlib").Path(directory)
    manifest = read_json(directory / "evidence.json")
    validate_schema("evidence_local.schema.json", manifest)
    if manifest["status"] != "ok" or manifest["error"] is not None:
        raise ValueError("Only successful evidence may enter a cache")
    if bundle_hash(manifest["components"]) != manifest["model_bundle_sha256"]:
        raise ValueError("Evidence model bundle mismatch")
    validate_schema(PAYLOADS[manifest["tool_id"]], manifest["data"])
    check_bboxes(manifest)
    if contract is not None:
        from .cache import make_cache_key
        if make_cache_key(contract) != manifest["cache_key"]:
            raise ValueError("Evidence cache contract mismatch")
        for field, key in (("input_sha256", "canonical_sha256"), ("tool_id", "tool_id"), ("model_bundle_sha256", "model_bundle_sha256"), ("backend", "backend")):
            if manifest[field] != contract[key]:
                raise ValueError(f"Evidence contract disagrees: {field}")
        if manifest["parameters_sha256"] != sha256_bytes(canonical_json(contract["parameters"])):
            raise ValueError("Evidence parameters mismatch")
        aliases = {"PP-OCRv6_medium_det+PP-OCRv6_medium_rec":"PP-OCRv6_medium_det+rec","SCRFD_det_10g.onnx":"SCRFD_det_10g"}
        planned_model=contract["parameters"]["model"]
        if manifest["model_name"] != aliases.get(planned_model,planned_model):
            raise ValueError("Evidence model name differs from frozen contract")
    if manifest["formal_eligible"] and (manifest["evidence_profile_id"]!="gpu_full_v1" or not manifest["backend"]["device"].startswith("cuda")):
        raise ValueError("CPU or unknown-profile evidence cannot be marked formal")
    views = {}
    for view in manifest["views"]:
        if view["id"] in views:
            raise ValueError("Duplicate view ID")
        matrix = np.asarray(view["view_to_canonical"], dtype=np.float64)
        h, w = view["grid_shape"]
        if h*w > 40_000_000 or not np.isfinite(matrix).all() or not np.array_equal(matrix[2], [0,0,1]) or abs(np.linalg.det(matrix)) < 1e-15:
            raise ValueError("Invalid view geometry")
        corners = (matrix @ np.asarray([[0,0,1],[w,0,1],[0,h,1],[w,h,1]]).T).T[:, :2]
        if view["kind"] == "full_frame":
            source_corners = np.asarray([[0,0,1],[1,0,1],[0,1,1],[1,1,1]])
            inside = (np.linalg.inv(matrix) @ source_corners.T).T[:, :2]
            if (inside < -1e-5).any() or (inside > np.asarray([w,h])+1e-5).any():
                raise ValueError("Full-frame view does not cover the canonical image")
        elif (corners < -1e-6).any() or (corners > 1+1e-6).any():
            raise ValueError("ROI/tile view escapes canonical geometry")
        views[view["id"]] = view
    assets = {}
    for asset in manifest["assets"]:
        validate_schema("asset.schema.json", asset)
        if asset["path"] in assets:
            raise ValueError("Duplicate evidence asset")
        path = resolve_case_path(directory, asset["path"])
        if path.suffix in (".part", ".tmp") or sha256_file(path) != asset["sha256"]:
            raise ValueError("Evidence asset mismatch/incomplete")
        if asset["kind"] in ("photo", "map", "overlay"):
            with Image.open(path) as im:
                im.load()
                if im.size != (asset["width"], asset["height"]):
                    raise ValueError("Evidence asset dimensions mismatch")
        elif asset["width"] is not None or asset["height"] is not None:
            raise ValueError("Raw/text/JSON dimensions must be null")
        assets[asset["path"]] = asset
    if not _paths(manifest["data"]) <= set(assets):
        raise ValueError("Every data path must be declared and hashed")
    data = manifest["data"]
    records = data.get("items", data.get("faces", data.get("native_masks", [])))
    ids = set()
    for record in records:
        if record["id"] in ids or record["view_id"] not in views:
            raise ValueError("Duplicate record or unknown view")
        ids.add(record["id"])
        x0,y0,x1,y1 = record["bbox_norm"]
        if not (x0 < x1 and y0 < y1):
            raise ValueError("Reversed box")
        if "polygon_norm" in record:
            polygon = np.asarray(record["polygon_norm"])
            if not np.allclose([*polygon.min(axis=0), *polygon.max(axis=0)], record["bbox_norm"], atol=1e-6):
                raise ValueError("OCR polygon/bbox association mismatch")
    if manifest["tool_id"] == "T3_DEPTH":
        if data["view_id"] not in views:
            raise ValueError("Unknown depth view")
        values = _grid(directory, data["depth_path"])
        mask = _grid(directory, data["valid_mask_path"])
        shape = tuple(data["grid_shape"])
        if shape != tuple(views[data["view_id"]]["grid_shape"]):
            raise ValueError("Depth array/view grid disagreement")
        if values.dtype != np.float32 or values.shape != shape or mask.shape != shape or not np.isin(mask, [0,1,255]).all():
            raise ValueError("Depth/valid mask shape or dtype mismatch")
        valid = mask != 0
        if not valid.any() or not np.isfinite(values[valid]).all():
            raise ValueError("Depth has no finite valid values")
        if not np.allclose([values[valid].min(), values[valid].max()], data["finite_value_range"], atol=1e-5):
            raise ValueError("Depth range is untrue")
        if contract and data["larger_is"] != contract["parameters"]["larger_is"]:
            raise ValueError("Depth direction mismatch")
        if _grid(directory,data["preview_path"]).shape != shape:
            raise ValueError("Depth preview grid mismatch")
    if manifest["tool_id"] == "T4_SEGMENTATION":
        labels = data["label_names"]
        # Bounded row blocks limit temporary threshold/finite/colour arrays to
        # at most one Mi-pixel. PNG decoding remains one asset at a time; NPY
        # inputs use _grid's read-only memory mapping.
        def blocks(height, width):
            columns = min(width, 1_048_576)
            rows = max(1, 1_048_576 // columns)
            for start in range(0, height, rows):
                for left in range(0, width, columns):
                    yield (slice(start, min(start + rows, height)), slice(left, min(left + columns, width)))
        if len(labels) > np.iinfo(np.uint16).max:
            raise ValueError("Too many display classes for uint16 labels")
        if contract and (labels != contract["parameters"]["prompt_set"]["labels"] or data["prompt_set_sha256"] != contract["prompt_set_sha256"]):
            raise ValueError("Segmentation fixed prompt-set mismatch")
        for record in records:
            index = record["prompt_index"]
            if not 0 <= index < len(labels) or record["label"] != labels[index]:
                raise ValueError("Mask/label association mismatch")
            mask = _grid(directory, record["mask_path"])
            if tuple(record["grid_shape"]) != tuple(views[record["view_id"]]["grid_shape"]):
                raise ValueError("Mask/view grid disagreement")
            if mask.shape != tuple(record["grid_shape"]) or any(not np.isin(mask[part], [0,1,255]).all() for part in blocks(*mask.shape)):
                raise ValueError("Invalid instance mask")
        if records:
            del mask
        if data["display_label_path"]:
            display = _grid(directory, data["display_label_path"])
            if display.dtype.kind not in "uib" or display.min() < 0 or display.max() > len(labels):
                raise ValueError("Unknown display label ID")
        native = read_json(resolve_case_path(directory, data["native_result_path"]))
        if not _paths(native) <= set(assets):
            raise ValueError("Native unions/masks must all be hashed assets")
        native_records = native.get("instances", [])
        if not isinstance(native_records,list) or not all(isinstance(r,dict) and isinstance(r.get("id"),str) for r in native_records):
            raise ValueError("Malformed native instance list")
        native_ids = [r["id"] for r in native_records]
        if len(native_ids) != len(set(native_ids)) or set(native_ids) != ids:
            raise ValueError("Native and normalized instance IDs disagree")
        by_id = {r["id"]: r for r in native_records}
        shape = tuple(native["grid_shape"])
        if native["view_id"] not in views or shape != tuple(views[native["view_id"]]["grid_shape"]):
            raise ValueError("Native segmentation/view grid disagreement")
        expected_display = np.zeros(shape,dtype=np.uint16)
        # Only >1 is part of the overlap protocol. Saturate at two, so this
        # single uint8 grid cannot overflow regardless of instance count.
        overlap_count = np.zeros(shape,dtype=np.uint8)
        threshold = native["mask_threshold"]
        if contract and threshold != contract["parameters"]["mask_threshold"]:
            raise ValueError("Native mask threshold differs from contract")
        for record in sorted(records,key=lambda r: (-(r["score"] or 0),r["prompt_index"],r["id"])):
            original = by_id[record["id"]]
            if any(original.get(k) != v for k,v in record.items()):
                raise ValueError("Native mask/label instance association mismatch")
            values = _grid(directory,original["native_mask_path"])
            normalized = _grid(directory,record["mask_path"])
            if values.dtype.kind not in "buif" or values.shape != shape or normalized.shape != shape:
                raise ValueError("Native mask threshold does not reproduce normalized mask")
            for part in blocks(*shape):
                binary = normalized[part] != 0
                if not np.isfinite(values[part]).all() or not np.array_equal(values[part] >= threshold, binary):
                    raise ValueError("Native mask threshold does not reproduce normalized mask")
                counts = overlap_count[part]
                np.minimum(counts + binary, 2, out=counts)
                display_part = expected_display[part]
                display_part[binary & (display_part == 0)] = record["prompt_index"] + 1
            del values, normalized, binary, counts, display_part
        regions = native.get("regions",[])
        if not isinstance(regions,list) or not all(isinstance(r,dict) for r in regions) or len(regions)!=len(labels):
            raise ValueError("Native class union list incomplete")
        # Reuse one union for every class, rather than allocating one full
        # image per label. Native instances remain individually validated above.
        union = np.zeros(shape, dtype=bool)
        for index,region in enumerate(regions):
            expected_ids = [r["id"] for r in native_records if r["prompt_index"]==index]
            if region["prompt_index"]!=index or region["class_id"]!=index+1 or region["label"]!=labels[index] or region["instance_ids"]!=expected_ids:
                raise ValueError("Class union/instance association mismatch")
            union.fill(False)
            for instance_id in expected_ids:
                instance_mask = _grid(directory, by_id[instance_id]["mask_path"])
                for part in blocks(*shape):
                    union[part] |= instance_mask[part] != 0
                del instance_mask
            native_union = _grid(directory, region["union_path"])
            if native_union.shape != shape or any(not np.array_equal(native_union[part] != 0, union[part]) for part in blocks(*shape)):
                raise ValueError("Class union/instance association mismatch")
            del native_union
        del union
        native_overlap = _grid(directory,native["overlap_path"])
        if native_overlap.shape != shape or any(not np.array_equal(native_overlap[part] != 0, overlap_count[part] > 1) for part in blocks(*shape)):
            raise ValueError("Native overlap map mismatch")
        del native_overlap, overlap_count
        if data["display_label_path"] and (display.shape != shape or any(not np.array_equal(display[part], expected_display[part]) for part in blocks(*shape))):
            raise ValueError("Display labels do not follow the declared overlap rule")
        if data["display_label_path"]:
            del display
        unassigned = sum(np.count_nonzero(expected_display[part] == 0) for part in blocks(*shape)) / (shape[0] * shape[1])
        if not np.isclose(data["unassigned_ratio"], unassigned):
            raise ValueError("Unassigned display area is untrue")
        palette = read_json(resolve_case_path(directory,data["palette_path"]))
        colours = palette.get("classes",[])
        if len(colours)!=len(labels)+1 or palette.get("unknown_id")!=0 or colours[0]!= {"class_id":0,"label":"unassigned/unknown","rgb":[0,0,0]}:
            raise ValueError("Palette unknown/class mapping mismatch")
        import hashlib
        seed = contract["parameters"]["prompt_set"].get("palette_seed",0) if contract else None
        for index,label in enumerate(labels):
            colour=colours[index+1]
            if colour["class_id"]!=index+1 or colour["label"]!=label:
                raise ValueError("Palette class association mismatch")
            if seed is not None and colour["rgb"] != [64+(v%192) for v in hashlib.sha256(f"{seed}:{label}".encode()).digest()[:3]]:
                raise ValueError("Palette differs from frozen class colours")
        preview = _grid(directory,data["preview_path"])
        palette_values = np.asarray([c["rgb"] for c in colours],dtype=np.uint8)
        if preview.shape != (*shape, 3) or any(not np.array_equal(preview[part], palette_values[expected_display[part]]) for part in blocks(*shape)):
            raise ValueError("Preview colours/labels do not match palette")
    return LocalEvidenceManifest.model_validate(manifest)
