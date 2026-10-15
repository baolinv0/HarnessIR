"""Standalone SAM3 Colab raw-handoff runner; no Controller/model API coupling.

Preparation is explicit and network-enabled. Workers have network disabled,
one image/process, exact input/contract checks, and never install dependencies.
Raw results require independent local import before becoming production cache.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import time
import traceback
import uuid
import zipfile

REVISION = "0570b3a5be9c4e694f23d85232fb55f4a6f1f7fc"
WEIGHT_REVISION = "3c879f39826c281e95690f02c7821c4de09afae7"
CHECKPOINT_SHA256 = "9999e2341ceef5e136daa386eecb55cb414446a00ac2b55eb2dfd2f7c3cf8c9e"
CHECKPOINT_BYTES = 3450062241
CHECKPOINT_FILENAME = "sam3.pt"
WEIGHT_REPOSITORY = "facebook/sam3"
RUN_PREFIX = "sam3_"
PROFILE = "colab_sam3_1008_v1"
PARAMETERS = dict(model="SAM3", checkpoint_generation="SAM3-not-SAM3.1", device="cuda:0",
                  precision="fp32", input_size=1008, source_view_long_edge=None,
                  mask_threshold=0.5, score_threshold=0.15, timeout_seconds=900,
                  cpu_threads=2, compile=False, tf32=False, roi_policy_id="full_frame_v1")


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def write_disk_masks_npz(destination, paths, height, width, arrays):
    """Pack temporary masks; final NPZ remains ordinary full-resolution bool.

    Stream the NPY payload directly into ZIP instead of making a second dense
    multi-instance disk copy. This changes storage only, never mask values.
    """
    import numpy as np
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        with archive.open("masks.npy", "w", force_zip64=True) as stream:
            np.lib.format.write_array_header_1_0(stream, dict(descr=np.lib.format.dtype_to_descr(np.dtype(bool)),
                 fortran_order=False, shape=(len(paths), height, width)))
            for path in paths:
                packed = np.load(path, mmap_mode="r", allow_pickle=False)
                if packed.dtype != np.uint8 or packed.shape != ((height*width+7)//8,):
                    raise ValueError("Invalid packed staging mask")
                remaining = height*width
                for offset in range(0, len(packed), 1024**2):
                    chunk = np.unpackbits(packed[offset:offset+1024**2], bitorder="big")[:remaining]
                    stream.write(chunk.tobytes()); remaining -= len(chunk)
                if remaining:
                    raise ValueError("Incomplete staging mask")
        for name, array in arrays.items():
            buffer = io.BytesIO(); np.save(buffer, array, allow_pickle=False)
            archive.writestr(name + ".npy", buffer.getvalue())


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temp.replace(path)


def under(root, relative):
    if "\\" in str(relative) or Path(relative).is_absolute():
        raise ValueError("Only relative POSIX asset paths are allowed")
    path = (Path(root) / relative).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        raise ValueError("Asset path escapes its delivery directory")
    return path


def extract_bundle(archive, destination, expected_sha):
    if sha(archive) != expected_sha:
        raise ValueError("Input package SHA256 mismatch")
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as source:
        names = source.namelist()
        if len(names) != len(set(n.casefold() for n in names)):
            raise ValueError("Duplicate ZIP names")
        if sum(i.file_size for i in source.infolist()) > 4 * 1024**3:
            raise ValueError("Input ZIP exceeds 4 GiB budget")
        for info in source.infolist():
            path = under(destination, info.filename)
            if info.is_dir() or ((info.external_attr >> 16) & 0o170000) == 0o120000:
                raise ValueError("Directory/symlink members not expected")
            path.parent.mkdir(parents=True, exist_ok=True)
            with source.open(info) as incoming, path.open("wb") as outgoing:
                import shutil
                shutil.copyfileobj(incoming, outgoing)
    return verify_inputs(destination)


def verify_inputs(bundle):
    from PIL import Image
    manifest = read(Path(bundle) / "inputs.json")
    ids = set()
    for row in manifest["images"]:
        if row["image_id"] in ids or not re.fullmatch(r"[A-Za-z0-9_-]+", row["image_id"]):
            raise ValueError("Invalid/duplicate image ID")
        ids.add(row["image_id"])
        path = under(bundle, row["canonical_path"])
        if sha(path) != row["canonical_sha256"]:
            raise ValueError("Canonical input hash changed")
        with Image.open(path) as image:
            if image.format != "PNG" or image.mode != "RGB" or image.size != (row["width"], row["height"]):
                raise ValueError("Canonical image format/shape differs")
    prompts = read(Path(bundle) / "prompt_set.json")
    if len(prompts["labels"]) != 31 or len(set(prompts["labels"])) != 31 or prompts["unknown_id"] != 0:
        raise ValueError("Expected exact 31-class prompt set")
    for name in ("pilot5.json", "selection20.json"):
        selected = read(Path(bundle) / name)["image_ids"]
        if len(selected) != len(set(selected)) or not set(selected) <= ids:
            raise ValueError("Selection differs from frozen inputs")
    return manifest


def validate_result(output, row, contract_sha):
    import numpy as np
    output = Path(output)
    metadata = read(output / "images" / (row["image_id"] + ".json"))
    if metadata["status"] not in ("ok", "empty"):
        raise ValueError("Failed/pending results cannot be reused")
    for key in ("image_id", "canonical_sha256", "original_sha256", "canonicalizer_version", "width", "height"):
        if metadata[key] != row[key]:
            raise ValueError("Result/source binding differs: " + key)
    if metadata["contract_sha256"] != contract_sha or metadata["coordinate_space"] != "canonical_pixels":
        raise ValueError("Result configuration/coordinates differ")
    if metadata.get("process_released") is not True:
        raise ValueError("Worker release has not been verified")
    path = under(output, metadata["npz_path"])
    if sha(path) != metadata["npz_sha256"]:
        raise ValueError("NPZ asset hash changed")
    # Validate the complete mask payload without materializing every full-size
    # instance at once on the low-memory Windows Controller.
    with zipfile.ZipFile(path) as archive, archive.open("masks.npy") as stream:
        version = np.lib.format.read_magic(stream)
        if version == (1, 0):
            mask_shape, fortran, mask_dtype = np.lib.format.read_array_header_1_0(stream)
        elif version == (2, 0):
            mask_shape, fortran, mask_dtype = np.lib.format.read_array_header_2_0(stream)
        else:
            raise ValueError("Unsupported mask NPY header")
        if fortran or mask_dtype != np.bool_:
            raise ValueError("Instance mask dtype/order mismatch")
        count = len(metadata["instances"])
        if mask_shape != (count, row["height"], row["width"]):
            raise ValueError("Instance mask shape/dtype mismatch")
        remaining = int(np.prod(mask_shape, dtype=np.int64))
        while remaining:
            data = stream.read(min(8*1024**2, remaining))
            if not data or (np.frombuffer(data, dtype=np.uint8) > 1).any():
                raise ValueError("Invalid/truncated binary mask payload")
            remaining -= len(data)
        if stream.read(1):
            raise ValueError("Unexpected mask payload bytes")
    with np.load(path, allow_pickle=False) as arrays:
        boxes, scores, indices, labels = (arrays[k] for k in
            ("boxes_xyxy", "scores", "prompt_indices", "labels"))
        count = len(metadata["instances"])
        if mask_shape != (count, row["height"], row["width"]):
            raise ValueError("Instance mask shape/dtype mismatch")
        if boxes.shape != (count, 4) or boxes.dtype != np.float32 or scores.shape != (count,) or scores.dtype != np.float32:
            raise ValueError("Boxes/scores shape/dtype mismatch")
        if indices.shape != (count,) or indices.dtype != np.int32 or labels.shape != (count,) or labels.dtype.kind != "U":
            raise ValueError("Prompt association shape/dtype mismatch")
        if not np.isfinite(boxes).all() or not np.isfinite(scores).all() or ((scores < 0) | (scores > 1)).any():
            raise ValueError("Invalid finite scores/boxes")
        if count and ((boxes[:, 0] < 0).any() or (boxes[:, 1] < 0).any() or
                      (boxes[:, 2] > row["width"]).any() or (boxes[:, 3] > row["height"]).any() or
                      (boxes[:, 2:] <= boxes[:, :2]).any()):
            raise ValueError("Boxes outside canonical pixels or degenerate")
        prompt_names = read(output / "prompt_set.json")["labels"]
        seen = set()
        for i, instance in enumerate(metadata["instances"]):
            if not 0 <= int(indices[i]) < len(prompt_names):
                raise ValueError("Invalid prompt index")
            if str(labels[i]) != prompt_names[int(indices[i])] or instance["label"] != str(labels[i]) or instance["prompt_index"] != int(indices[i]):
                raise ValueError("Mask/class/prompt mismatch")
            if instance["id"] in seen or instance["array_index"] != i:
                raise ValueError("Duplicate/reordered instance")
            seen.add(instance["id"])
            if not np.allclose(instance["bbox_xyxy"], boxes[i], rtol=0, atol=1e-4) or abs(instance["score"] - float(scores[i])) > 1e-6:
                raise ValueError("JSON/NPZ instance values differ")
        if (count == 0) != (metadata["status"] == "empty"):
            raise ValueError("Empty detection status mismatch")
    return metadata


def prepare(base, platform_check=None):
    """Explicit deployment only. Never invoked by inference or resume."""
    import urllib.request
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("This pinned Notebook requires Python 3.12; no automatic runtime replacement")
    base = Path(base).resolve()
    base.mkdir(parents=True, exist_ok=True)
    source = base / ("sam3-" + REVISION)
    archive = base / "sam3_source.zip"
    if not source.exists():
        urllib.request.urlretrieve("https://codeload.github.com/facebookresearch/sam3/zip/" + REVISION, archive)
        with zipfile.ZipFile(archive) as z:
            for member in z.infolist():
                path = under(base, member.filename)
                if not path.is_relative_to(source):
                    raise ValueError("Unexpected source ZIP root")
                if ((member.external_attr >> 16) & 0o170000) == 0o120000:
                    raise ValueError("Source ZIP symlink")
                if member.is_dir():
                    path.mkdir(parents=True, exist_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(z.read(member))
    python = base / "tool_env/bin/python"
    if not python.exists():
        subprocess.run([sys.executable, "-m", "venv", str(base / "tool_env")], check=True)
    log = base / "deployment.log"
    with log.open("a") as stream:
        for arguments in (
            ["setuptools==78.1.0", "wheel==0.45.1"],
            ["--index-url", "https://download.pytorch.org/whl/cu128", "torch==2.10.0", "torchvision==0.25.0"],
            ["numpy==1.26.4", "Pillow==12.1.0", "timm==1.0.22", "einops==0.8.1", "iopath==0.1.10",
             "ftfy==6.1.1", "regex", "tqdm", "huggingface_hub", "psutil==7.2.2", "pycocotools==2.0.11", "scipy==1.15.3",
             "opencv-python-headless==4.11.0.86", "hydra-core==1.3.2", "decord==0.6.0"],
            ["--no-deps", "--no-build-isolation", str(source)],
        ):
            subprocess.run([str(python), "-m", "pip", "install", *arguments], check=True, stdout=stream, stderr=stream)
        if platform_check is None:
            subprocess.run([str(python), "-m", "pip", "check"], check=True, stdout=stream, stderr=stream)
        else:
            platform_check(python, base, stream)
    freeze = subprocess.check_output([str(python), "-m", "pip", "freeze", "--all"])
    (base / "environment.freeze.txt").write_bytes(freeze)
    witness_code = "import torch,json; torch.set_num_threads(2); torch.manual_seed(20261013); assert torch.cuda.is_available(); x=torch.arange(64,dtype=torch.float32,device='cuda').reshape(8,8); y=x@x; torch.cuda.synchronize(); c=torch.arange(64,dtype=torch.float32).reshape(8,8); assert torch.equal(y.cpu(),c@c); print(json.dumps(dict(passed=True,torch=torch.__version__,cuda=torch.version.cuda,gpu=torch.cuda.get_device_name(0))))"
    witness = json.loads(subprocess.check_output([str(python), "-c", witness_code], text=True).strip().splitlines()[-1])
    components = [{"path": p.relative_to(source).as_posix(), "sha256": sha(p)} for p in sorted(source.rglob("*")) if p.is_file() and "__pycache__" not in p.parts and ".egg-info" not in str(p)]
    receipt = dict(source_revision=REVISION, source_components=components, source_tree_sha256=digest(components),
                   environment_lock_sha256=sha(base / "environment.freeze.txt"), python_executable=str(python),
                   tokenizer_path=str(source / "sam3/assets/bpe_simple_vocab_16e6.txt.gz"),
                   gpu_witness=witness, image_inference_completed=False, ready=False)
    receipt["tokenizer_sha256"] = sha(receipt["tokenizer_path"])
    receipt["python_version"] = sys.version
    write(base / "deployment.json", receipt)
    return receipt


def initialize(bundle, deployment, checkpoint, output, expected_checkpoint_sha, provenance_url):
    import shutil
    bundle, deployment, checkpoint, output = map(lambda p: Path(p).resolve(), (bundle, deployment, checkpoint, output))
    verify_inputs(bundle)
    if not checkpoint.is_file() or checkpoint.suffix != ".pt" or checkpoint.stat().st_size != CHECKPOINT_BYTES:
        raise ValueError("Official native SAM3 .pt weights required; configs/safetensors/SAM3.1 are not interchangeable")
    if expected_checkpoint_sha != CHECKPOINT_SHA256 or sha(checkpoint) != expected_checkpoint_sha:
        raise ValueError("Checkpoint differs from independently recorded local hash")
    # A Drive checkpoint is staged once to local Colab disk. Single-image workers
    # can then hash/load it without repeatedly streaming 3.45 GB from Drive.
    staged = deployment / "checkpoints" / CHECKPOINT_FILENAME
    staged.parent.mkdir(parents=True, exist_ok=True)
    if checkpoint != staged:
        if not staged.is_file() or sha(staged) != expected_checkpoint_sha:
            temp = staged.with_suffix(".pt.tmp")
            shutil.copyfile(checkpoint, temp)
            if sha(temp) != expected_checkpoint_sha:
                raise ValueError("Checkpoint changed while staging to local disk")
            temp.replace(staged)
        checkpoint = staged
    receipt = read(deployment / "deployment.json")
    if not receipt["gpu_witness"]["passed"] or receipt["source_revision"] != REVISION:
        raise ValueError("Prepared environment/GPU witness differs")
    if sha(deployment / "environment.freeze.txt") != receipt["environment_lock_sha256"] or sha(receipt["tokenizer_path"]) != receipt["tokenizer_sha256"]:
        raise ValueError("Prepared assets changed")
    source = deployment / ("sam3-" + REVISION)
    for component in receipt["source_components"]:
        if sha(under(source, component["path"])) != component["sha256"]:
            raise ValueError("Prepared official source changed")
    current_freeze = subprocess.check_output([receipt["python_executable"], "-m", "pip", "freeze", "--all"])
    if hashlib.sha256(current_freeze).hexdigest() != receipt["environment_lock_sha256"]:
        raise ValueError("Tool environment changed since preparation")
    contract = dict(profile_id=PROFILE, parameters=PARAMETERS, checkpoint_sha256=expected_checkpoint_sha,
                    weight_repository=WEIGHT_REPOSITORY, weight_revision=WEIGHT_REVISION,
                    source_revision=REVISION, source_tree_sha256=receipt["source_tree_sha256"],
                    tokenizer_sha256=receipt["tokenizer_sha256"], environment_lock_sha256=receipt["environment_lock_sha256"],
                    backend=receipt["gpu_witness"], prompt_set_sha256=digest(read(bundle / "prompt_set.json")))
    if (output / "run.json").exists():
        run = read(output / "run.json")
        if run["contract"] != contract or run["inputs_sha256"] != sha(bundle / "inputs.json"):
            raise ValueError("Existing output run has another contract/input list; use a new directory")
        # Relocating identical assets after a Colab reset does not change contract.
        run.update(checkpoint_path=str(checkpoint), bundle=str(bundle), deployment=str(deployment))
        write(output / "run.json", run)
        shutil.copyfile(deployment / "deployment.json", output / "deployment.json")
        return run
    output.mkdir(parents=True, exist_ok=True)
    run = dict(handoff_version="sam3_raw_v1", run_id=RUN_PREFIX + uuid.uuid4().hex,
               model=PARAMETERS["model"], checkpoint_generation=PARAMETERS["checkpoint_generation"], checkpoint_path=str(checkpoint),
               checkpoint_sha256=expected_checkpoint_sha, checkpoint_provenance_url=provenance_url,
               checkpoint_identity="official_native_SHA256_verified_pending_strict_load", formal_eligible=False,
               official_checkpoint_repository=WEIGHT_REPOSITORY, official_checkpoint_revision=WEIGHT_REVISION,
               deviations=["Official SAM3 image input 1008 instead of prior profile 1024", "Colab backend/env locked independently"],
               contract=contract, contract_sha256=digest(contract), inputs_sha256=sha(bundle / "inputs.json"),
               bundle=str(bundle), deployment=str(deployment), image_inference_completed=False,
               deployment_receipt_sha256=sha(deployment / "deployment.json"),
               gpu_driver=subprocess.check_output(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"], text=True).strip())
    for name in ("inputs.json", "prompt_set.json", "pilot5.json", "selection20.json"):
        shutil.copyfile(bundle / name, output / name)
    shutil.copyfile(deployment / "environment.freeze.txt", output / "environment.freeze.txt")
    shutil.copyfile(deployment / "deployment.json", output / "deployment.json")
    shutil.copyfile(deployment / "deployment.log", output / "deployment.log")
    write(output / "run.json", run)
    return run


def offline():
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", OMP_NUM_THREADS="2", MKL_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2")
    def audit(event, arguments):
        if event in ("socket.connect", "socket.getaddrinfo", "socket.sendto", "socket.sendmsg"):
            raise RuntimeError("Inference network is forbidden")
        if event in ("subprocess.Popen", "os.system", "os.posix_spawn"):
            import shlex
            command = arguments[1] if event == "subprocess.Popen" else arguments[0]
            tokens = [str(t).lower() for t in command] if isinstance(command, (list, tuple)) else shlex.split(str(command).lower())
            if any(Path(t).stem in ("pip", "pip3", "uv", "conda", "curl", "wget", "git", "powershell", "pwsh") for t in tokens) or "-m pip" in " ".join(tokens):
                raise RuntimeError("Inference package installation/download is forbidden")
    sys.addaudithook(audit)


def worker(output, image_id):
    offline()
    import numpy as np
    import torch
    from PIL import Image
    output = Path(output)
    run = read(output / "run.json")
    row = next(r for r in read(output / "inputs.json")["images"] if r["image_id"] == image_id)
    source = under(run["bundle"], row["canonical_path"])
    if sha(source) != row["canonical_sha256"] or sha(run["checkpoint_path"]) != run["checkpoint_sha256"]:
        raise ValueError("Source/checkpoint changed before worker startup")
    from sam3 import model_builder
    from sam3.model.sam3_image_processor import Sam3Processor
    # Official builder otherwise warns about missing weights and continues.
    # Reject partial/incompatible checkpoint loading rather than emitting evidence.
    def strict_load(model, checkpoint_path):
        weights = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
        if isinstance(weights, dict) and isinstance(weights.get("model"), dict):
            weights = weights["model"]
        weights = {k.removeprefix("detector."): v for k, v in weights.items() if k.startswith("detector.")}
        if not weights:
            raise ValueError("No official SAM3 detector weights; incompatible format")
        model.load_state_dict(weights, strict=True)
    model_builder._load_checkpoint = strict_load
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.cuda.reset_peak_memory_stats()
    receipt = read(output / "deployment.json")
    model = model_builder.build_sam3_image_model(checkpoint_path=run["checkpoint_path"],
        bpe_path=receipt["tokenizer_path"], load_from_HF=False, device="cuda", eval_mode=True,
        enable_inst_interactivity=False, compile=False)
    # The official module sets TF32 at import, so set it again after imports.
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    processor = Sam3Processor(model, resolution=PARAMETERS["input_size"], device="cuda", confidence_threshold=PARAMETERS["score_threshold"])
    labels = read(output / "prompt_set.json")["labels"]
    all_masks, all_boxes, all_scores, all_indices, names, instances = [], [], [], [], [], []
    with Image.open(source) as image, torch.inference_mode():
        state = processor.set_image(image)
        for index, label in enumerate(labels):
            processor.reset_all_prompts(state)
            result = processor.set_text_prompt(state=state, prompt=label)
            masks, boxes, scores = result["masks_logits"], result["boxes"], result["scores"]
            if not len(masks) == len(boxes) == len(scores):
                raise ValueError("SAM3 mask/box/score count mismatch")
            for i in range(len(scores)):
                probabilities = masks[i].squeeze(0).detach().cpu().numpy()
                if probabilities.shape != (row["height"], row["width"]) or not np.isfinite(probabilities).all() or probabilities.min() < 0 or probabilities.max() > 1:
                    raise ValueError("Official masks_logits must contain full-resolution sigmoid probabilities")
                native = boxes[i].detach().cpu().numpy().astype(np.float32)
                box = np.clip(native, 0, [row["width"], row["height"], row["width"], row["height"]]).astype(np.float32)
                score = float(scores[i].item())
                masks_array = probabilities >= PARAMETERS["mask_threshold"]
                if PARAMETERS.get("mask_storage") == "disk_stream_v1":
                    staging = output / "mask_staging" / image_id
                    staging.mkdir(parents=True, exist_ok=True)
                    mask_file = staging / f"{len(all_masks):06d}.npy"
                    np.save(mask_file, np.packbits(masks_array.reshape(-1), bitorder="big"), allow_pickle=False)
                    all_masks.append(mask_file)
                else:
                    all_masks.append(masks_array)
                all_boxes.append(box); all_scores.append(score)
                all_indices.append(index); names.append(label)
                instances.append(dict(id=f"prompt_{index:03d}_mask_{i:04d}", array_index=len(instances), label=label,
                                      prompt_index=index, score=score, bbox_xyxy=box.tolist(), native_bbox_xyxy=native.tolist(),
                                      area_pixels=int(masks_array.sum())))
            del result, masks, boxes, scores
    images = output / "images"
    images.mkdir(exist_ok=True)
    npz = images / (image_id + ".npz")
    temporary = npz.with_suffix(".npz.tmp")
    arrays = dict(boxes_xyxy=np.asarray(all_boxes, dtype=np.float32).reshape(-1, 4), scores=np.asarray(all_scores, dtype=np.float32),
                  prompt_indices=np.asarray(all_indices, dtype=np.int32), labels=np.asarray(names, dtype="U64"))
    if PARAMETERS.get("mask_storage") == "disk_stream_v1":
        write_disk_masks_npz(temporary, all_masks, row["height"], row["width"], arrays)
    else:
        with temporary.open("wb") as stream:
            np.savez_compressed(stream, masks=np.stack(all_masks) if all_masks else np.zeros((0, row["height"], row["width"]), dtype=bool), **arrays)
    temporary.replace(npz)
    if PARAMETERS.get("mask_storage") == "disk_stream_v1" and all_masks:
        import shutil
        shutil.rmtree(staging)
    torch.cuda.synchronize()
    metadata = {k: row[k] for k in ("image_id", "canonical_sha256", "original_sha256", "canonicalizer_version", "width", "height")}
    metadata.update(handoff_version="sam3_raw_v1", status="ok" if instances else "empty", coordinate_space="canonical_pixels",
                    run_id=run["run_id"], contract_sha256=run["contract_sha256"], npz_path="images/" + npz.name,
                    npz_sha256=sha(npz), instances=instances, checkpoint_strict_load=True,
                    mask_values="binary_probability_ge_0.5", native_masks_may_overlap=True,
                    peak_torch_allocated_mb=torch.cuda.max_memory_allocated()/1024**2,
                    peak_torch_reserved_mb=torch.cuda.max_memory_reserved()/1024**2, process_released=False)
    write(images / (image_id + ".json"), metadata)


def summary(output, planned):
    output = Path(output)
    rows = []
    for image_id in planned:
        path = output / "images" / (image_id + ".json")
        value = read(path) if path.exists() else dict(image_id=image_id, status="pending")
        rows.append({k: value.get(k) for k in ("image_id", "status", "error_code", "elapsed_seconds", "npz_path", "log_path", "peak_rss_mb", "peak_gpu_memory_mb", "process_released")})
    with (output / "processing_status.csv.tmp").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else ["image_id", "status"])
        writer.writeheader(); writer.writerows(rows)
    (output / "processing_status.csv.tmp").replace(output / "processing_status.csv")
    result = {status: sum(r["status"] == status for r in rows) for status in ("ok", "empty", "failed", "pending")}
    result.update(planned=len(planned), complete=result["pending"] == result["failed"] == 0, formal_eligible=False)
    write(output / "summary.json", result)
    return result


def pilot_digest(output):
    output = Path(output)
    run = read(output / "run.json")
    rows = {r["image_id"]: r for r in read(output / "inputs.json")["images"]}
    ids = read(output / "pilot5.json")["image_ids"]
    values = []
    for image_id in ids:
        metadata = validate_result(output, rows[image_id], run["contract_sha256"])
        values.append(dict(image_id=image_id, metadata_sha256=sha(output / "images" / (image_id + ".json")), npz_sha256=metadata["npz_sha256"]))
    return digest(dict(run_id=run["run_id"], contract_sha256=run["contract_sha256"], results=values))


def accept_pilot(output, reviewer):
    if not str(reviewer).strip():
        raise ValueError("Reviewer must be named after inspecting masks/legend")
    write(Path(output) / "pilot_review.json", dict(accepted=True, reviewed_by=reviewer,
          pilot_digest=pilot_digest(output), review_scope="T4_only_not_all_four_tools_gate"))


def batch(output, stage, wall_seconds=7200, retry_failed=False):
    # Linux advisory lock is held for the entire dispatch, released on interrupt.
    import fcntl
    output = Path(output)
    with (output / "dispatch.lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _batch(output, stage, wall_seconds, retry_failed)


def _batch(output, stage, wall_seconds=7200, retry_failed=False):
    import psutil
    output = Path(output).resolve()
    run = read(output / "run.json")
    if stage not in ("pilot", "selection20"):
        raise ValueError("Unknown batch stage")
    verify_inputs(run["bundle"])
    rows = {r["image_id"]: r for r in read(output / "inputs.json")["images"]}
    lease_path = output / "worker_lease.json"
    if lease_path.exists():
        lease = read(lease_path)
        if psutil.pid_exists(lease["pid"]):
            try:
                command = psutil.Process(lease["pid"]).cmdline()
                if "worker" in command and str(output) in command:
                    raise RuntimeError("Previous worker still running after interruption; wait or terminate it explicitly")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    ids = read(output / ("pilot5.json" if stage == "pilot" else "selection20.json"))["image_ids"]
    if stage != "pilot":
        review = read(output / "pilot_review.json")
        if review.get("accepted") is not True or review["pilot_digest"] != pilot_digest(output):
            raise ValueError("Current real five-image T4 pilot must be reviewed first")
    python = read(output / "deployment.json")["python_executable"]
    actual_freeze = subprocess.check_output([python, "-m", "pip", "freeze", "--all"])
    if hashlib.sha256(actual_freeze).hexdigest() != run["contract"]["environment_lock_sha256"]:
        raise ValueError("Tool environment differs; do not reuse/start jobs")
    deadline = time.monotonic() + wall_seconds
    planned = read(output / "selection20.json")["image_ids"]
    (output / "logs").mkdir(exist_ok=True)
    (output / "images").mkdir(exist_ok=True)
    for image_id in ids:
        path = output / "images" / (image_id + ".json")
        if path.exists():
            value = read(path)
            if value["status"] in ("ok", "empty"):
                if value.get("process_released") is True:
                    validate_result(output, rows[image_id], run["contract_sha256"])
                    print(image_id, "validated cache hit", flush=True)
                    continue
                value.update(status="failed", error_code="interrupted_unverified_release", error_message="Worker result was never finalized by Controller; explicit retry required")
                write(path, value)
            if not retry_failed:
                print(image_id, "previous failure retained; explicit retry required", flush=True)
                continue
            attempts = value.get("attempt", 1)
            if attempts >= 2:
                print(image_id, "limited retry exhausted", flush=True)
                continue
            backup = path.with_name(path.stem + f".attempt{attempts}.json")
            if not backup.exists():
                path.replace(backup)
        else:
            attempts = 0
        if deadline - time.monotonic() < PARAMETERS["timeout_seconds"] + 120:
            print("Wall budget insufficient for another job and save reserve", flush=True)
            break
        active = subprocess.check_output(["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"], text=True).strip()
        if active:
            raise RuntimeError("GPU already has an active compute process; single-worker policy refuses concurrent startup")
        started = time.monotonic(); peak = 0.; samples = []
        gpu_peak, gpu_last, gpu_value = None, -1., None
        logfile = output / "logs" / f"{image_id}.attempt{attempts+1}.log"
        error = None
        interruption = None
        with logfile.open("w") as log:
            process = subprocess.Popen([python, str(Path(__file__).resolve()), "worker", "--output", str(output), "--image-id", image_id],
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            write(lease_path, dict(pid=process.pid, image_id=image_id, run_id=run["run_id"]))
            try:
                while process.poll() is None:
                    try:
                        parent = psutil.Process(process.pid)
                        rss = sum(p.memory_info().rss for p in [parent, *parent.children(recursive=True)] if p.is_running()) / 1024**2
                        peak = max(peak, rss)
                        if time.monotonic()-gpu_last >= 1:
                            try:
                                queried = subprocess.check_output(["nvidia-smi", "--query-compute-apps=pid,used_gpu_memory", "--format=csv,noheader,nounits"], text=True, timeout=3)
                                pidset = {p.pid for p in [parent, *parent.children(recursive=True)]}
                                values = [float(line.split(",")[1].strip()) for line in queried.splitlines()
                                          if int(line.split(",")[0].strip()) in pidset and line.split(",")[1].strip().replace(".", "", 1).isdigit()]
                                gpu_value = sum(values) if values else None
                                if gpu_value is not None: gpu_peak = max(gpu_peak or 0., gpu_value)
                            except (subprocess.SubprocessError, ValueError, OSError):
                                gpu_value = None
                            gpu_last = time.monotonic()
                        samples.append(dict(seconds=time.monotonic()-started, rss_mb=rss, gpu_process_memory_mb=gpu_value))
                        if rss > 24576 or psutil.virtual_memory().available < 1024**3:
                            error = "memory_budget"
                    except psutil.Error:
                        pass
                    if time.monotonic()-started > PARAMETERS["timeout_seconds"]:
                        error = "timeout"
                    if error:
                        break
                    time.sleep(0.2)
            except BaseException as exc:
                interruption = exc
                error = "interrupted"
            finally:
                if process.poll() is None:
                    import signal
                    try: os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError: pass
                    try: process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL); process.wait()
            process.wait()
        write(output / "logs" / f"{image_id}.attempt{attempts+1}.resources.json", samples)
        elapsed = time.monotonic()-started
        released = not psutil.pid_exists(process.pid)
        if process.returncode != 0 or error:
            text = logfile.read_text(errors="replace")
            code = error or ("oom" if "out of memory" in text.lower() else
                             "import_error" if "ModuleNotFoundError" in text or "ImportError" in text else
                             "model_missing" if "FileNotFoundError" in text else
                             "checkpoint_incompatible" if "load_state_dict" in text or "incompatible format" in text else "runtime_error")
            metadata = {k: rows[image_id][k] for k in ("image_id", "canonical_sha256", "original_sha256", "canonicalizer_version", "width", "height")}
            metadata.update(status="failed", error_code=code, error_message=text[-3000:], run_id=run["run_id"],
                            contract_sha256=run["contract_sha256"], instances=[], attempt=attempts+1)
        else:
            metadata = read(path)
            metadata["attempt"] = attempts+1
        metadata.update(elapsed_seconds=elapsed, peak_rss_mb=peak if samples else None, peak_gpu_memory_mb=gpu_peak,
                        gpu_memory_measurement="nvidia-smi process sample every 1s; torch allocator peak additionally in success metadata",
                        process_released=released, log_path=logfile.relative_to(output).as_posix(), returncode=process.returncode)
        write(path, metadata)
        if metadata["status"] in ("ok", "empty"):
            try:
                validate_result(output, rows[image_id], run["contract_sha256"])
            except Exception as exc:
                metadata.update(status="failed", error_code="output_validation", error_message=str(exc))
                write(path, metadata)
        summary(output, planned)
        print(image_id, metadata["status"], round(elapsed, 2), "seconds", flush=True)
        if PARAMETERS.get("stop_on_systemic_failure") and metadata.get("error_code") in ("checkpoint_incompatible", "import_error", "model_missing"):
            print("Systemic model failure: stop remaining images until a new configuration is reviewed", flush=True)
            break
        if interruption:
            raise interruption
    total = summary(output, planned)
    real_validated = [read(output / "images" / (i + ".json")) for i in planned if (output / "images" / (i + ".json")).exists()]
    run["image_inference_completed"] = any(v.get("status") in ("ok","empty") and v.get("checkpoint_strict_load") is True and v.get("process_released") is True for v in real_validated)
    run["validated_image_count"] = total["ok"] + total["empty"]
    if run["image_inference_completed"]:
        run["checkpoint_identity"] = "official_native_SHA256_verified_strict_detector_load_passed"
    write(output / "run.json", run)
    states = [read(output / "images" / (i + ".json"))["status"] if (output / "images" / (i + ".json")).exists() else "pending" for i in ids]
    result = {status: states.count(status) for status in ("ok", "empty", "failed", "pending")}
    result.update(stage=stage, planned=len(ids), complete=result["failed"] == result["pending"] == 0, selection20=total, formal_eligible=False)
    write(output / ("pilot_status.json" if stage == "pilot" else "selection20_status.json"), result)
    return result


def gallery(output):
    import base64
    import numpy as np
    from PIL import Image, ImageDraw
    output = Path(output)
    run = read(output / "run.json")
    labels = read(output / "prompt_set.json")["labels"]
    colors = [tuple(64 + b % 192 for b in hashlib.sha256(f"0:{name}".encode()).digest()[:3]) for name in labels]
    rows = {r["image_id"]: r for r in read(output / "inputs.json")["images"]}
    def encoded(image):
        image.thumbnail((900, 900))
        stream = io.BytesIO(); image.save(stream, format="PNG")
        return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode()
    cards = []
    for image_id in read(output / "selection20.json")["image_ids"]:
        row = rows[image_id]
        image = Image.open(under(run["bundle"], row["canonical_path"])).convert("RGB")
        image.thumbnail((900, 900))
        path = output / "images" / (image_id + ".json")
        status = read(path)["status"] if path.exists() else "pending"
        overlay = image.copy(); found = []
        if status in ("ok", "empty"):
            metadata = validate_result(output, row, run["contract_sha256"])
            mask_path = under(output, metadata["npz_path"])
            with np.load(mask_path, allow_pickle=False) as z, zipfile.ZipFile(mask_path) as archive, archive.open("masks.npy") as mask_stream:
                version = np.lib.format.read_magic(mask_stream)
                header_reader = np.lib.format.read_array_header_1_0 if version == (1,0) else np.lib.format.read_array_header_2_0
                shape, _, _ = header_reader(mask_stream)
                pixels = np.asarray(overlay).astype(np.float32)
                for index, box, score in zip(z["prompt_indices"], z["boxes_xyxy"], z["scores"]):
                    payload = mask_stream.read(shape[1]*shape[2])
                    native_mask = np.frombuffer(payload, dtype=bool).reshape(shape[1:])
                    mask = np.asarray(Image.fromarray(native_mask).resize(image.size, Image.Resampling.NEAREST), dtype=bool)
                    pixels[mask] = pixels[mask]*0.55 + np.asarray(colors[int(index)])*0.45
                    found.append(f"{labels[int(index)]}: {float(score):.3f}")
                overlay = Image.fromarray(pixels.clip(0,255).astype(np.uint8))
                draw = ImageDraw.Draw(overlay)
                for box, index in zip(z["boxes_xyxy"], z["prompt_indices"]):
                    scaled_box = box * np.asarray([image.width/row["width"],image.height/row["height"],image.width/row["width"],image.height/row["height"]])
                    draw.rectangle(scaled_box.tolist(), outline=colors[int(index)], width=3)
        evidence = f"<img src='{encoded(overlay)}'>" if status in ("ok", "empty") else "<p>T4未运行或失败：没有有效分割证据。</p>"
        cards.append(f"<section><h2>{html.escape(image_id)} — {html.escape(status)}</h2><img src='{encoded(image)}'>{evidence}<p>{html.escape(', '.join(found))}</p></section>")
    legend = " ".join(f"<span style='background:rgb{color};padding:4px;color:black'>{html.escape(label)}</span>" for color,label in zip(colors,labels))
    page = "<!doctype html><meta charset='utf-8'><title>HarnessIR SAM3 evidence</title><style>body{font:16px sans-serif;background:#eee;padding:20px}section{background:white;padding:15px;margin:20px 0}img{max-width:48%;vertical-align:top}span{display:inline-block;margin:3px}</style><h1>SAM3证据：原图 / Mask叠加</h1><p>工具证据，非恢复结果；重叠实例仍保留在NPZ。Formal eligible: false.</p>" + legend + "".join(cards)
    (output / "evidence_gallery.html").write_text(page, encoding="utf-8")
    return output / "evidence_gallery.html"


def export_results(output, destination):
    output = Path(output).resolve(); destination = Path(destination).resolve()
    if destination.is_relative_to(output):
        raise ValueError("Result ZIP must be outside output directory")
    run = read(output / "run.json")
    for row in read(output / "inputs.json")["images"]:
        path = output / "images" / (row["image_id"] + ".json")
        if path.exists() and read(path)["status"] in ("ok", "empty"):
            validate_result(output, row, run["contract_sha256"])
    gallery(output)
    files = [p for p in sorted(output.rglob("*")) if p.is_file() and not p.name.endswith(".tmp") and p.name != "delivery_manifest.json" and "mask_staging" not in p.relative_to(output).parts]
    index = [{"path":p.relative_to(output).as_posix(), "sha256":sha(p), "bytes":p.stat().st_size} for p in files]
    write(output / "delivery_manifest.json", dict(kind="sam3_raw_handoff_not_production_cache", files=index, formal_eligible=False))
    with zipfile.ZipFile(destination.with_suffix(".zip.tmp"), "w", zipfile.ZIP_DEFLATED) as z:
        for p in [*files, output / "delivery_manifest.json"]:
            z.write(p, p.relative_to(output).as_posix())
    destination.with_suffix(".zip.tmp").replace(destination)
    return dict(path=str(destination), sha256=sha(destination), bytes=destination.stat().st_size)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "worker", "batch"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image-id")
    parser.add_argument("--stage", choices=("pilot", "selection20"), default="pilot")
    args = parser.parse_args()
    try:
        if args.action == "prepare": print(json.dumps(prepare(args.output)))
        elif args.action == "worker": worker(args.output, args.image_id)
        else: print(json.dumps(batch(args.output, args.stage)))
    except Exception:
        traceback.print_exc(); return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
