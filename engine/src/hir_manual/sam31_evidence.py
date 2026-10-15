"""Offline, source-bound SAM3.1 alternative import; never loads an ML model.

The accepted native run is independently frozen below. Imported result files do
not select their own model, source, environment, parameters or expected hashes.
This profile is intentionally separate from original SAM3 formal evaluation.
"""
from pathlib import Path
import hashlib
import importlib.util
import shutil
import tempfile
import zipfile

import numpy as np
from PIL import Image, ImageDraw

from .storage import read_json, write_json, sha256_file, sha256_bytes
from .tool_registry import canonical_json, make_contract, load_profile, load_registry
from .cache import EvidenceCache, make_cache_key

PROFILE = "gpu_sam31_v5"
RUN_ID = "sam31_169d46d8dd8243d8be922b6e19af5834"
RAW_CONTRACT = "489d609effd25eb58204fb7b614756b072c60850785d56586b70c18c5f06df23"
WEIGHT_SHA = "0567debeec80ba4ac6369540c6c248025283cb3ff2b92827509e57e2b3541cb6"
WEIGHT_REVISION = "daa63191845a41281374e725f4c9e51c7a824460"
SOURCE_REVISION = "0570b3a5be9c4e694f23d85232fb55f4a6f1f7fc"
SOURCE_SHA = "5dc53fa6360f8066d436cbc1c8cc34c2385bc0f6b87cab84a73e2cc29fce48e0"
TOKENIZER_SHA = "924691ac288e54409236115652ad4aa250f48203de50a9e4722a6ecd48d6804a"
ENV_SHA = "5125d33d53767c552330c8aa90e3d28aefe3abaa78b668f8b98af1b7da253760"
PROMPT_SHA = "1872a938dbdb663468f595281380ca3490a1e786293f40e1981efab7a78aaa91"
INPUT_ZIP_SHA = "847d740a9d1c0c473a6a71fc697860085c67dec4fd23c39f667afaa43e7c53d3"
RESULT_ZIP_SHA = "ea910b03c767274d7ee889d0a8143dcb86ba8fc6bfbd970bbdcc6ea7ef91c989"
IMPLEMENTATION = "official_sam31_tri_image_fp32_cpu_masks"


def validate_import_configuration(profile, entry):
    expected = {"checkpoint": WEIGHT_SHA, "source_tree": SOURCE_SHA, "tokenizer": TOKENIZER_SHA}
    if {c["name"]: c["sha256"] for c in entry["components"]} != expected or len(entry["components"]) != len(expected):
        raise ValueError("SAM3.1 registry components differ from independent locks")
    backend = dict(implementation=IMPLEMENTATION, source_revision=SOURCE_REVISION, framework="torch",
                   framework_version="2.10.0+cu128", device="cuda:0", precision="fp32", environment_lock_sha256=ENV_SHA)
    if entry["backend"] != backend or entry.get("execution_mode") != "cache_only" or entry["model_name"] != "SAM3.1":
        raise ValueError("SAM3.1 registry backend/model differs from independent locks")
    frozen = dict(model="SAM3.1", implementation=IMPLEMENTATION, input_size=1008, mask_threshold=.5,
        score_threshold=.5, device="cuda:0", precision="fp32", execution_mode="cache_only", raw_contract_sha256=RAW_CONTRACT,
        architecture="official_multiplex_tri_backbone_detector", mlp_backend="torch_linear_activation_fp32",
        mask_postprocess="cpu_fp32_lazy_single_instance_bilinear_align_corners_false", mask_storage="disk_stream_v1",
        compile=False, tf32=False, normalization_version="sam31_stream_lossless_png_v2")
    params = profile.tools["T4_SEGMENTATION"]
    if profile.formal_eligible or any(params.get(k) != v for k, v in frozen.items()) or sha256_bytes(canonical_json(params.get("prompt_set"))) != PROMPT_SHA:
        raise ValueError("SAM3.1 normalization profile differs from accepted native parameters")


def verify_native(root, delivery, image_id):
    """Compare the native cache against immutable input and received ZIP locks."""
    root, delivery = Path(root), Path(delivery)
    input_zip = root / "runtime/sam3_colab/uploads/847d740a9d1c0c47/harnessir_sam3_inputs20.zip"
    output_zip = root / "runtime/alternatives/sam31/sam31_v5_selection20.zip"
    for path, expected in ((input_zip, INPUT_ZIP_SHA), (output_zip, RESULT_ZIP_SHA)):
        if sha256_file(path) != expected:
            raise ValueError("Frozen independently received archive changed")
    import json
    with zipfile.ZipFile(input_zip) as archive:
        frozen = json.loads(archive.read("inputs.json"))
        prompt = json.loads(archive.read("prompt_set.json"))
        row = next((r for r in frozen["images"] if r["image_id"] == image_id), None)
        if row is None:
            raise ValueError("Image is outside frozen original LQ input selection")
        with archive.open(row["canonical_path"]) as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != row["canonical_sha256"]:
                raise ValueError("Frozen original canonical bytes disagree")
    if read_json(delivery / "inputs.json") != frozen or read_json(delivery / "prompt_set.json") != prompt:
        raise ValueError("Native input/prompt list differs from independent source")
    if sha256_bytes(canonical_json(prompt)) != PROMPT_SHA:
        raise ValueError("Fixed prompt set changed")
    run = read_json(delivery / "run.json")
    if (run["run_id"] != RUN_ID or run["model"] != "SAM3.1" or run["formal_eligible"] is not False
            or run["contract_sha256"] != RAW_CONTRACT or sha256_bytes(canonical_json(run["contract"])) != RAW_CONTRACT
            or run["checkpoint_sha256"] != WEIGHT_SHA):
        raise ValueError("Native model/run/contract is not the accepted independent SAM3.1 v5 run")
    locks = root / "runtime/alternatives/sam31"
    official = read_json(locks / "official_weight_lock.json")
    if (official["repository"] != "facebook/sam3.1" or official["revision"] != WEIGHT_REVISION
            or official["weight"]["lfs"]["sha256"] != WEIGHT_SHA
            or official["weight"]["lfs"]["size"] != 3502755717
            or read_json(locks / "source_lock.json")["revision"] != SOURCE_REVISION
            or sha256_file(locks / "tool_environment.freeze.txt") != ENV_SHA):
        raise ValueError("Independent official source/weight/environment lock changed")
    metadata_relative = "images/" + image_id + ".json"
    # Bind byte identity to the previously received archive, not self-declared
    # hashes in metadata or raw_ready.json. No dense masks are allocated here.
    with zipfile.ZipFile(output_zip) as archive:
        for relative in ("run.json", "inputs.json", "prompt_set.json", metadata_relative, "images/" + image_id + ".npz"):
            with archive.open(relative) as stream:
                expected = hashlib.file_digest(stream, "sha256").hexdigest()
            if sha256_file(delivery / relative) != expected:
                raise ValueError("Native bytes differ from accepted received archive: " + relative)
    spec = importlib.util.spec_from_file_location("hir_sam31_native_validator", root / "engine/colab/sam3_handoff.py")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    metadata = helper.validate_result(delivery, row, RAW_CONTRACT)
    if metadata.get("checkpoint_strict_load") is not True or metadata["run_id"] != RUN_ID:
        raise ValueError("Strict detector load or run identity not proven")
    return row, metadata, prompt


def iter_masks(path, count, height, width):
    """Yield one original-size boolean mask; never load NPZ['masks']."""
    with zipfile.ZipFile(path) as archive, archive.open("masks.npy") as stream:
        version = np.lib.format.read_magic(stream)
        reader = {(1, 0): np.lib.format.read_array_header_1_0, (2, 0): np.lib.format.read_array_header_2_0}.get(version)
        if reader is None:
            raise ValueError("Unsupported mask header")
        shape, fortran, dtype = reader(stream)
        if shape != (count, height, width) or dtype != np.bool_ or fortran:
            raise ValueError("Mask shape/dtype/order mismatch")
        for _ in range(count):
            size = height * width
            raw = bytearray(size)
            offset = 0
            while offset < size:
                chunk = stream.read(min(8 * 1024**2, size - offset))
                if not chunk or (np.frombuffer(chunk, np.uint8) > 1).any():
                    raise ValueError("Truncated/nonboolean mask bytes")
                raw[offset:offset + len(chunk)] = chunk
                offset += len(chunk)
            yield np.frombuffer(raw, dtype=np.bool_).reshape(height, width)
            del raw
        if stream.read(1):
            raise ValueError("Trailing mask bytes")


def normalize_masks(npz, metadata, prompt, out):
    """Produce the established lossless segmentation protocol at bounded RAM.

    Instance masks and unions are raw assets; Composer gets the semantic image
    and actual image legend. One class union is allocated at a time.
    """
    out = Path(out)
    for directory in ("raw", "masks", "maps"):
        (out / directory).mkdir(parents=True, exist_ok=True)
    height, width = metadata["height"], metadata["width"]
    labels = prompt["labels"]
    records = metadata["instances"]
    display = np.zeros((height, width), dtype=np.uint16)
    counts = np.zeros((height, width), dtype=np.uint8)
    native = []
    assets = []
    def asset(relative, kind, size=None):
        assets.append(dict(path=relative, kind=kind, sha256=sha256_file(out / relative),
                           width=None if size is None else size[0], height=None if size is None else size[1]))
    def save(relative, array, kind="raw_data"):
        Image.fromarray(array).save(out / relative)
        asset(relative, kind, (width, height) if kind == "map" else None)
    for index, mask in enumerate(iter_masks(npz, len(records), height, width)):
        record = records[index]
        prompt_index = record["prompt_index"]
        if not 0 <= prompt_index < len(labels) or record["label"] != labels[prompt_index]:
            raise ValueError("Label/prompt association mismatch")
        bbox = np.asarray(record["bbox_xyxy"], dtype=np.float64)
        native_box = np.asarray(record["native_bbox_xyxy"], dtype=np.float64)
        if not np.isfinite(native_box).all() or not np.allclose(np.clip(native_box, 0, [width, height, width, height]), bbox, atol=1e-4, rtol=0):
            raise ValueError("Clipped/native coordinate disagreement")
        norm = (bbox / [width, height, width, height]).tolist()
        if not (0 <= norm[0] < norm[2] <= 1 and 0 <= norm[1] < norm[3] <= 1):
            raise ValueError("Invalid normalized bbox")
        path = f"masks/mask_{index:04d}.png"
        save(path, mask.astype(np.uint8) * 255)
        area = int(np.count_nonzero(mask))
        if area != record["area_pixels"]:
            raise ValueError("Native mask area disagrees")
        item = dict(id=record["id"], label=record["label"], prompt_index=prompt_index, score=record["score"],
                    bbox_norm=norm, mask_path=path, grid_shape=[height, width], view_id="full")
        # Native NPZ is already binary, not floating probabilities. Lossless
        # 0/255 PNG and threshold .5 reproduce it exactly; retain the original
        # NPZ unchanged instead of duplicating multi-GiB dense per-mask NPYs.
        native.append({**item, "native_mask_path": path, "native_bbox": native_box.tolist(), "area_pixels": area})
        # Saturate at two: protocol only needs overlap >= two, no overflow.
        np.minimum(counts + mask, 2, out=counts)
        del mask
    # Score-ordered winners; retain every overlap in raw instances and map.
    for record in sorted(native, key=lambda r: (-(r["score"] or 0), r["prompt_index"], r["id"])):
        with Image.open(out / record["native_mask_path"]) as image:
            mask = np.asarray(image) != 0
        display[mask & (display == 0)] = record["prompt_index"] + 1
        del mask
    regions = []
    union = np.zeros((height, width), dtype=bool)
    for index, label in enumerate(labels):
        union.fill(False)
        members = [r for r in native if r["prompt_index"] == index]
        for member in members:
            with Image.open(out / member["native_mask_path"]) as image:
                mask = np.asarray(image) != 0
            union |= mask
            del mask
        path = f"masks/class_{index+1:03d}_union.png"
        save(path, union.astype(np.uint8) * 255)
        regions.append(dict(class_id=index+1, label=label, prompt_index=index, union_path=path,
                            union_area_pixels=int(union.sum()), union_area_ratio=float(union.mean()), instance_ids=[r["id"] for r in members]))
    del union
    save("maps/labels.png", display)
    save("maps/overlap.png", (counts > 1).astype(np.uint8) * 255)
    palette = [dict(class_id=0, label="unassigned/unknown", rgb=[0, 0, 0])]
    for index, label in enumerate(labels):
        colour = hashlib.sha256(f"{prompt.get('palette_seed',0)}:{label}".encode()).digest()[:3]
        palette.append(dict(class_id=index+1, label=label, rgb=[64 + (v % 192) for v in colour]))
    write_json(out / "maps/palette.json", dict(unknown_id=0, classes=palette, colour_algorithm="sha256(seed:label),64+byte%192"))
    asset("maps/palette.json", "json")
    save("maps/semantic.png", np.asarray([r["rgb"] for r in palette], dtype=np.uint8)[display], "map")
    legend = Image.new("RGB", (480, 30 + 24 * len(palette)), (25, 25, 25))
    draw = ImageDraw.Draw(legend)
    draw.text((8, 5), "SAM3.1 alternative; overlap retained; not full coverage", fill="white")
    for i, item in enumerate(palette):
        y = 30 + i * 24
        draw.rectangle((8, y, 28, y+16), fill=tuple(item["rgb"]))
        draw.text((38, y), f"{item['class_id']}: {item['label']}", fill="white")
    legend.save(out / "maps/segmentation_legend.png")
    asset("maps/segmentation_legend.png", "map", legend.size)
    write_json(out / "raw/seg.json", dict(instances=native, regions=regions, mask_threshold=.5,
        overlap_pixels=int((counts > 1).sum()), overlap_path="maps/overlap.png", legend_path="maps/segmentation_legend.png", grid_shape=[height,width], view_id="full"))
    asset("raw/seg.json", "json")
    data = dict(prompt_set_id=prompt["prompt_set_id"], prompt_set_sha256=sha256_bytes(canonical_json(prompt)), label_names=labels,
        native_masks=[{k:v for k,v in item.items() if k not in ("native_mask_path", "native_bbox", "area_pixels")} for item in native],
        unknown_id=0, native_masks_may_overlap=True, display_label_path="maps/labels.png", preview_path="maps/semantic.png",
        palette_path="maps/palette.json", display_overlap_rule="score_desc_then_prompt_index_then_instance_id", unassigned_ratio=float((display == 0).mean()), native_result_path="raw/seg.json")
    return data, assets


def verify_normalized_native(directory, metadata):
    """Validate source-to-normalized losslessness, including on cache reuse."""
    from .storage import resolve_case_path
    directory = Path(directory)
    manifest = read_json(directory / "evidence.json")
    if sha256_file(directory / "raw/native.npz") != metadata["npz_sha256"] or read_json(directory / "raw/native_metadata.json") != metadata:
        raise ValueError("Normalized provenance no longer matches accepted native result")
    provenance = read_json(directory / "raw/provenance.json")
    if provenance["raw_contract_sha256"] != RAW_CONTRACT or provenance["received_result_archive_sha256"] != RESULT_ZIP_SHA or provenance["frozen_input_archive_sha256"] != INPUT_ZIP_SHA:
        raise ValueError("Normalized source archive provenance mismatch")
    records = manifest["data"]["native_masks"]
    if len(records) != len(metadata["instances"]):
        raise ValueError("Normalized instance count differs from original native result")
    for i, mask in enumerate(iter_masks(directory / "raw/native.npz", len(records), metadata["height"], metadata["width"])):
        original, normalized = metadata["instances"][i], records[i]
        if (normalized["id"] != original["id"] or normalized["label"] != original["label"]
                or normalized["prompt_index"] != original["prompt_index"] or normalized["score"] != original["score"]
                or not np.allclose(normalized["bbox_norm"], np.asarray(original["bbox_xyxy"]) / [metadata["width"], metadata["height"], metadata["width"], metadata["height"]], atol=1e-12, rtol=0)):
            raise ValueError("Normalized instance association differs from original native result")
        with Image.open(resolve_case_path(directory, normalized["mask_path"])) as image:
            if not np.array_equal(np.asarray(image) != 0, mask):
                raise ValueError("Normalized mask differs from original native NPZ")
        del mask


def import_image(root, delivery, image_id):
    root, delivery = Path(root).resolve(), Path(delivery).resolve()
    row, metadata, prompt = verify_native(root, delivery, image_id)
    profile, registry = load_profile(PROFILE, root), load_registry(root, PROFILE)
    entry = registry.tools["T4_SEGMENTATION"]
    validate_import_configuration(profile, entry)
    contract = make_contract(row["canonical_sha256"], "T4_SEGMENTATION", profile, entry, row["canonicalizer_version"])
    cache = EvidenceCache(root / "Data/annotations/cache")
    key = make_cache_key(contract)
    with cache.lock("T4_SEGMENTATION", key, timeout=60):
        existing = cache.lookup(contract)
        if existing:
            verify_normalized_native(existing, metadata)
            return dict(image_id=image_id, status="existing", cache_key=key, directory=str(existing))
        stage_root = root / "runtime/sam31_normalization"
        stage_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=image_id + "_", dir=stage_root) as stage:
            out = Path(stage)
            data, assets = normalize_masks(delivery / metadata["npz_path"], metadata, prompt, out)
            for source, relative, kind in ((delivery / metadata["npz_path"], "raw/native.npz", "raw_data"),
                    (delivery / "images" / (image_id + ".json"), "raw/native_metadata.json", "json")):
                shutil.copyfile(source, out / relative)
                assets.append(dict(path=relative, sha256=sha256_file(out / relative), kind=kind, width=None, height=None))
            write_json(out / "raw/provenance.json", dict(run_id=RUN_ID, raw_contract_sha256=RAW_CONTRACT,
                frozen_input_archive_sha256=INPUT_ZIP_SHA, received_result_archive_sha256=RESULT_ZIP_SHA,
                original_sha256=row["original_sha256"], canonical_sha256=row["canonical_sha256"],
                checkpoint_sha256=WEIGHT_SHA, weight_repository="facebook/sam3.1", weight_revision=WEIGHT_REVISION,
                source_revision=SOURCE_REVISION, environment_lock_sha256=ENV_SHA,
                native_npz_sha256=metadata["npz_sha256"], native_npz_path="raw/native.npz", native_metadata_path="raw/native_metadata.json",
                normalization="sam31_stream_lossless_png_v2", formal_eligible=False))
            assets.append(dict(path="raw/provenance.json", sha256=sha256_file(out / "raw/provenance.json"), kind="json", width=None, height=None))
            width, height = row["width"], row["height"]
            evidence = dict(protocol_version="1.1", tool_id="T4_SEGMENTATION", input_sha256=row["canonical_sha256"],
                status="ok", model_name="SAM3.1", checkpoint_sha256=WEIGHT_SHA, source_width=width, source_height=height,
                tool_width=width, tool_height=height, coordinates="canonical_norm", source_to_tool=[[1,0,0],[0,1,0],[0,0,1]],
                detections=[dict(bbox_norm=r["bbox_norm"], label=r["label"], text=None, confidence=r["score"], ambiguous=False) for r in data["native_masks"]],
                assets=assets, data=data, error=None, image_id=image_id, original_sha256=row["original_sha256"],
                evidence_profile_id=PROFILE, model_bundle_sha256=entry["model_bundle_sha256"],
                components=[dict(name=c["name"],sha256=c["sha256"]) for c in entry["components"]], backend=entry["backend"],
                parameters_sha256=sha256_bytes(canonical_json(contract["parameters"])), cache_key=key,
                views=[dict(id="full",kind="full_frame",grid_shape=[height,width],view_to_canonical=[[1/width,0,0],[0,1/height,0],[0,0,1]])],
                quality_warnings=["user_authorized_SAM3.1_alternative_not_original_SAM3_formal", "fixed_prompt_masks_do_not_guarantee_full_coverage", "RSS and GPU peaks sampled on remote worker; not normalization memory"],
                elapsed_ms=metadata["elapsed_seconds"]*1000, peak_rss_mb=metadata["peak_rss_mb"], formal_eligible=False)
            write_json(out / "evidence.json", evidence)
            verify_normalized_native(out, metadata)
            destination = cache.publish(contract, out)
            return dict(image_id=image_id, status="imported", cache_key=key, directory=str(destination))
