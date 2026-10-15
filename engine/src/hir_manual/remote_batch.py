"""Serial offline GPU evidence runner; no image editor or shutdown mutation.

Server caches remain contract addressed. Results without a real local export ID
are explicitly unbound; their index never authorizes a local import. A visual
five-photo pilot review is required before full-dataset execution.
"""
import csv
import errno
import io
import os
import re
import subprocess
import threading
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock
from PIL import Image

from .cache import EvidenceCache, make_cache_key
from .local_evidence import validate_local_evidence
from .storage import atomic_write, now, read_json, resolve_case_path, sha256_file, write_json
from .tool_jobs import prepare_job
from .tool_registry import CANONICALIZER_VERSION, LEGACY_CANONICALIZER_VERSION, GPU_PROFILE_IDS, gpu_evidence_origin_matches, check_entry, load_profile, load_registry, make_contract
from .tool_service import ToolService

ORDER = ("T2_FACE", "T1_OCR", "T3_DEPTH", "T4_SEGMENTATION")
RETURN_WINDOW_SECONDS = 15 * 60
STARTUP_CLEANUP_RESERVE_SECONDS = 60
TRANSIENT_ERRNOS = {errno.EAGAIN, errno.EINTR, errno.ESTALE, errno.ETIMEDOUT}


def _utc(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Shutdown deadline must include UTC timezone")
    return parsed.astimezone(timezone.utc)


def verify_shutdown_record(record_path, deadline=None):
    """Verify the operator's saved observation, never schedule/extend shutdown."""
    record = read_json(Path(record_path))
    compute_only = record.get("verified") is False and record.get("status") == "unsupported" and record.get("compute_deadline_utc") and record.get("verification")
    if not compute_only and (record.get("verified") is not True or not record.get("method") or not record.get("verification")):
        raise ValueError("A previously verified shutdown observation is required")
    actual = _utc(record["compute_deadline_utc"] if compute_only else record["deadline_utc"])
    if deadline is not None and actual != _utc(deadline):
        raise ValueError("Requested deadline differs from verified shutdown record")
    if actual <= datetime.now(timezone.utc):
        raise ValueError("Verified shutdown deadline has elapsed")
    return actual, record


def validate_dataset(dataset):
    dataset = Path(dataset).resolve()
    manifest = read_json(dataset / "manifest.json")
    rows = manifest.get("images")
    pilots = manifest.get("pilot_ids")
    if not isinstance(rows, list) or not rows or not isinstance(pilots, list) or len(pilots) != 5 or len(set(pilots)) != 5:
        raise ValueError("Prepared manifest needs images and exactly five distinct pilot IDs")
    ids, hashes = set(), set()
    for row in rows:
        image_id = row.get("image_id")
        if not isinstance(image_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", image_id) or image_id in ids:
            raise ValueError("Invalid or duplicate dataset image ID")
        ids.add(image_id)
        for name in ("canonical_sha256", "original_sha256"):
            if not isinstance(row.get(name), str) or not re.fullmatch(r"[a-f0-9]{64}", row[name]):
                raise ValueError("Invalid source SHA256")
        if row["canonical_sha256"] in hashes:
            raise ValueError("Duplicate canonical image cannot count as an independent dataset item")
        hashes.add(row["canonical_sha256"])
        if row.get("canonicalizer_version") not in (CANONICALIZER_VERSION, LEGACY_CANONICALIZER_VERSION):
            raise ValueError("Unsupported canonicalizer identity; no silent migration")
        canonical = resolve_case_path(dataset, row["canonical_path"])
        original = resolve_case_path(dataset, row["original_path"])
        if sha256_file(canonical) != row["canonical_sha256"] or sha256_file(original) != row["original_sha256"]:
            raise ValueError("Prepared dataset original/canonical SHA256 mismatch")
        with Image.open(canonical) as image:
            image.load()
            if image.format != "PNG" or image.mode != "RGB" or image.size != (row["width"], row["height"]) or image.width * image.height > 40_000_000:
                raise ValueError("Prepared canonical must be original-size RGB PNG")
    if not set(pilots) <= ids:
        raise ValueError("Pilot image ID absent from prepared manifest")
    return manifest


def _gpu_sample():
    sample = {"at": now(), "scope": "sampled_device_wide; other GPU users may contribute", "devices": [], "processes": [], "available": False}
    try:
        query = subprocess.run(["nvidia-smi", "--query-gpu=index,uuid,memory.used,memory.total", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5, check=True)
        for line in query.stdout.splitlines():
            fields = [part.strip() for part in line.split(",")]
            if len(fields) != 4:
                raise ValueError("Unexpected nvidia-smi device response")
            sample["devices"].append({"index": int(fields[0]), "uuid": fields[1], "memory_used_mib": float(fields[2]), "memory_total_mib": float(fields[3])})
        if not sample["devices"]:
            raise ValueError("nvidia-smi returned no visible GPU device")
        processes = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,process_name,used_gpu_memory", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5, check=True)
        for line in processes.stdout.splitlines():
            fields = [part.strip() for part in line.split(",")]
            if len(fields) == 3:
                sample["processes"].append({"pid": int(fields[0]), "process_name": fields[1], "memory_used_mib": None if fields[2] in ("[N/A]", "N/A") else float(fields[2])})
        sample["available"] = True
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        sample["error"] = str(exc)
    return sample


class GpuSampler:
    def __init__(self, interval_seconds=1):
        self.interval = interval_seconds
        self.samples = []
        self.stop = threading.Event()
        self.thread = None

    def __enter__(self):
        self.samples.append(_gpu_sample())
        def sample():
            while not self.stop.wait(self.interval):
                self.samples.append(_gpu_sample())
        self.thread = threading.Thread(target=sample, name="hir-gpu-samples", daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join(timeout=12)
        self.samples.append(_gpu_sample())

    def report(self, worker_pid):
        device_peak = max((sum(d["memory_used_mib"] for d in s["devices"]) for s in self.samples if s["available"]), default=None)
        pid_values = [p["memory_used_mib"] for s in self.samples for p in s["processes"] if p["pid"] == worker_pid and p["memory_used_mib"] is not None]
        last = self.samples[-1]
        return {"sample_interval_seconds": self.interval, "peak_is_sampled": True, "device_scope": "device-wide sum; includes other processes, not allocated tensor peak", "peak_device_used_mib": device_peak, "worker_pid": worker_pid, "peak_worker_pid_used_mib": max(pid_values, default=None), "worker_pid_present_after_exit": any(p["pid"] == worker_pid for p in last["processes"]) if worker_pid and last["available"] else None, "before": self.samples[0], "after": last, "samples": self.samples}


def _empty(evidence):
    data = evidence.data
    return evidence.tool_id != "T3_DEPTH" and not data.get("items", data.get("faces", data.get("native_masks", [])))


def _valid_result(row, record, contract, cache, profile_id="gpu_full_v1"):
    directory = cache.lookup(contract)
    if directory is None:
        raise ValueError("Pilot evidence is no longer a valid same-contract cache")
    evidence = validate_local_evidence(directory, contract)
    if not gpu_evidence_origin_matches(profile_id, contract["tool_id"], evidence.evidence_profile_id, evidence.formal_eligible):
        raise ValueError("Pilot evidence profile provenance differs from selected protocol")
    if evidence.original_sha256 != row["original_sha256"] or (evidence.source_width, evidence.source_height) != (row["width"], row["height"]):
        raise ValueError("Evidence source identity/geometry differs from prepared manifest")
    if record.get("status") not in ("ok", "empty") or record.get("actual_inference_confirmed") is not True or record.get("process_released") is not True:
        raise ValueError("Pilot requires actual successful inference and confirmed process release")
    if record.get("cache_key") != evidence.cache_key or record.get("evidence_sha256") != sha256_file(directory / "evidence.json"):
        raise ValueError("Pilot record no longer binds the validated cache manifest")
    actual_dir = Path(record.get("actual_run_evidence_dir", "")).resolve()
    tool_jobs = cache.root.parents[2] / "runtime/tool_jobs"
    if not actual_dir.is_relative_to(tool_jobs.resolve()):
        raise ValueError("Pilot actual output must belong to an isolated tool job")
    if sha256_file(actual_dir / "evidence.json") != record.get("actual_run_evidence_sha256"):
        raise ValueError("Actual pilot-run evidence changed")
    actual = validate_local_evidence(actual_dir, contract)
    if actual.original_sha256 != row["original_sha256"] or (actual.source_width, actual.source_height) != (row["width"], row["height"]):
        raise ValueError("Actual pilot-run image identity differs")
    worker_path = actual_dir.parent / "worker_result.json"
    if sha256_file(worker_path) != record.get("worker_result_sha256"):
        raise ValueError("Actual pilot worker measurement changed")
    worker = read_json(worker_path)
    if worker.get("status") != "completed" or worker.get("process_released") is not True or not worker.get("pid"):
        raise ValueError("Pilot has no successful released measured worker process")
    return directory, evidence


def verify_pilot_review(root, manifest, profile, registry, pilot_summary_path, review_path, expected_dataset_sha256=None):
    review = read_json(Path(review_path))
    if review.get("accepted") is not True or not review.get("reviewed_by") or review.get("pilot_summary_sha256") != sha256_file(Path(pilot_summary_path)):
        raise ValueError("Full dataset requires explicit visual review bound to pilot summary SHA256")
    summary = read_json(Path(pilot_summary_path))
    if summary.get("stage") != "pilot" or summary.get("complete") is not True or summary.get("dataset_manifest_sha256") != sha256_file(Path(summary["dataset_manifest_path"])):
        raise ValueError("Pilot has not completed its actual inference gate")
    if expected_dataset_sha256 and summary["dataset_manifest_sha256"] != expected_dataset_sha256:
        raise ValueError("Pilot review belongs to a different prepared dataset")
    if summary.get("profile") != profile.model_dump():
        raise ValueError("Pilot review belongs to a different frozen evidence profile")
    if summary.get("pilot_ids") != manifest["pilot_ids"] or len(summary.get("results", [])) != 20:
        raise ValueError("Pilot must contain exactly five photos times all four tools")
    expected = {(image_id, tool) for image_id in manifest["pilot_ids"] for tool in ORDER}
    records = {(r["image_id"], r["tool_id"]): r for r in summary["results"]}
    if len(records) != 20 or set(records) != expected:
        raise ValueError("Pilot identities are incomplete or duplicated")
    cache, by_id = EvidenceCache(Path(root) / "Data/annotations/cache"), {r["image_id"]: r for r in manifest["images"]}
    for image_id, tool in sorted(expected):
        row = by_id[image_id]
        contract = make_contract(row["canonical_sha256"], tool, profile, registry.tools[tool], canonicalizer_version=row["canonicalizer_version"])
        _valid_result(row, records[(image_id, tool)], contract, cache, profile.evidence_profile_id)
    return review


def _status(directory, summary):
    write_json(directory / "summary.json", summary)
    stream = io.StringIO(newline="")
    fields = ["image_id", "tool_id", "status", "cache_hit", "actual_inference_confirmed", "job_id", "cache_key", "elapsed_ms", "peak_rss_mb", "peak_device_used_mib", "process_released", "error_code", "message"]
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(summary["results"])
    atomic_write(directory / "processing_status.csv", stream.getvalue().encode("utf-8"))


def _prior_actual(prior, image_id, tool, key, evidence_sha):
    return next((record for record in reversed(prior) if record.get("image_id") == image_id and record.get("tool_id") == tool and record.get("cache_key") == key and record.get("evidence_sha256") == evidence_sha and record.get("actual_inference_confirmed") is True and record.get("process_released") is True and record.get("status") in ("ok", "empty")), None)


def _run_one(root, dataset, row, tool, profile, registry, stage, previous):
    service = ToolService(root)
    contract = make_contract(row["canonical_sha256"], tool, profile, registry.tools[tool], canonicalizer_version=row["canonicalizer_version"])
    cached = service.cache.lookup(contract)
    key = make_cache_key(contract)
    fatal = next((r for r in reversed(previous) if r.get("image_id") == row["image_id"] and r.get("tool_id") == tool and r.get("cache_key") == key and r.get("error_code") in ("oom", "timeout")), None)
    if fatal:
        blocked = dict(fatal)
        blocked.update(retry_blocked=True, runtime_elapsed_ms=0.0, message="Previous OOM/timeout for this exact contract; parameter/model changes require a new frozen configuration")
        return blocked
    previous_actual = _prior_actual(previous, row["image_id"], tool, key, sha256_file(cached / "evidence.json")) if cached else None
    # Warm-up cannot be inferred from a downloaded/imported cache. On resume a
    # proven real pilot run may be reused, preserving its original cost record.
    compute = cached is None or (stage == "pilot" and previous_actual is None)
    if not compute:
        if previous_actual is not None:
            _valid_result(row, previous_actual, contract, service.cache, profile.evidence_profile_id)
        evidence = validate_local_evidence(cached, contract)
        if not gpu_evidence_origin_matches(profile.evidence_profile_id, tool, evidence.evidence_profile_id, evidence.formal_eligible):
            raise ValueError("Cached evidence protocol provenance mismatch")
        record = dict(previous_actual or {})
        record.update(image_id=row["image_id"], tool_id=tool, status="empty" if _empty(evidence) else "ok", cache_hit=True, runtime_elapsed_ms=0.0, cache_key=key, cache_dir=str(cached), evidence_sha256=sha256_file(cached / "evidence.json"), contract=contract, evidence_origin_profile=evidence.evidence_profile_id)
        record["metrics_origin"] = "prior_real_run_preserved; no worker launched for this cache hit"
        if stage == "all" and previous_actual is None:
            record.update(actual_inference_confirmed=False, process_released=None, inference_origin="fully_matching_existing_cache; no process launched")
        return record
    check_entry(registry.tools[tool], require_ready=stage == "all")
    job, directory = prepare_job(root, resolve_case_path(dataset, row["canonical_path"]), row["original_sha256"], row["image_id"], tool, profile, registry, canonicalizer_version=row["canonicalizer_version"])
    with GpuSampler() as gpu:
        cached, metrics = service._run_job(job, profile, registry, require_ready=stage == "all", force_compute=True)
    gpu_record = gpu.report(metrics.get("pid"))
    write_json(directory / "logs/gpu_samples.json", gpu_record)
    record = {"image_id": row["image_id"], "tool_id": tool, "status": "failed", "cache_hit": False, "actual_inference_confirmed": False, "job_id": job.job_id, "cache_key": key, "contract": contract, "elapsed_ms": metrics.get("elapsed_ms", 0), "peak_rss_mb": metrics.get("peak_rss_mb"), "process_released": metrics.get("process_released", False), "error_code": metrics.get("error_code"), "message": metrics.get("message"), "worker": metrics, "gpu": gpu_record, "peak_device_used_mib": gpu_record["peak_device_used_mib"], "log_dir": str(directory / "logs")}
    if not cached or metrics.get("status") != "completed" or metrics.get("process_released") is not True or gpu_record["worker_pid_present_after_exit"] is True:
        if metrics.get("status") == "resource_wait":
            record["status"] = "resource_wait"
        if cached and record["error_code"] is None:
            record.update(error_code="process_release_unconfirmed", message="Worker release could not be confirmed; not eligible for pilot gate")
        return record
    evidence = validate_local_evidence(cached, contract)
    if not gpu_evidence_origin_matches(profile.evidence_profile_id, tool, evidence.evidence_profile_id, evidence.formal_eligible):
        raise ValueError("Computed evidence protocol provenance mismatch")
    if evidence.original_sha256 != row["original_sha256"] or (evidence.source_width, evidence.source_height) != (row["width"], row["height"]):
        raise ValueError("Computed evidence source hash/size mismatch")
    actual_dir = Path(metrics["output_dir"])
    validate_local_evidence(actual_dir, contract)
    record.update(status="empty" if _empty(evidence) else "ok", actual_inference_confirmed=True, cache_dir=str(cached), evidence_sha256=sha256_file(cached / "evidence.json"), actual_run_evidence_dir=str(actual_dir), actual_run_evidence_sha256=sha256_file(actual_dir / "evidence.json"), worker_result_sha256=sha256_file(directory / "worker_result.json"), error_code=None)
    entry = registry.tools[tool]
    entry["ready"] = True
    entry["warmup_evidence"] = {"job_id": job.job_id, "cache_key": key, "manifest_sha256": record["evidence_sha256"], "validated_at": now(), "result": metrics}
    registry_path=Path(root)/"preprocessing/registry"/(profile.evidence_profile_id+".json")
    with FileLock(str(registry_path)+'.lock'):
        actual=read_json(registry_path) if registry_path.exists() else registry.model_dump()
        actual['tools'][tool]=entry
        actual['registry_status']="ready" if all(actual['tools'].get(t,{}).get('ready') for t in ORDER) else "partially_ready"
        write_json(registry_path,actual)
    return record


def package_results(root, dataset, manifest, summary, directory):
    """Only validated caches are returned; failed jobs are index/log records."""
    root, dataset, directory = Path(root), Path(dataset), Path(directory)
    cache = EvidenceCache(root / "Data/annotations/cache")
    export_id = manifest.get("actual_export_bundle_id")
    if export_id is not None and not re.fullmatch(r"export_[a-f0-9]{32}", export_id):
        raise ValueError("Invalid actual local export binding")
    index = {"protocol_version": "1.1", "bundle_kind": "cache_results" if export_id else "unbound_cache_results", "bundle_id": export_id, "local_import_authorized": False, "requires_local_expected_ledger": True, "entries": []}
    rows = {r["image_id"]: r for r in manifest["images"]}
    archive_path = directory / "validated_results.zip"
    temporary = archive_path.with_name(archive_path.name + "." + uuid.uuid4().hex + ".tmp")
    written = set()
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for record in summary["results"]:
                if record.get("status") not in ("ok", "empty"):
                    continue
                contract = record["contract"]
                cached = cache.lookup(contract)
                if cached is None:
                    continue
                evidence = validate_local_evidence(cached, contract)
                row = rows[record["image_id"]]
                if evidence.original_sha256 != row["original_sha256"]:
                    raise ValueError("Packaging original image identity mismatch")
                prefix = "results/" + record["tool_id"] + "/" + record["cache_key"]
                input_path = "inputs/" + row["canonical_sha256"] + ".png"
                for filename in ("evidence.json", "contract.json", "ready.json", *[a.path for a in evidence.assets]):
                    name = prefix + "/" + filename
                    if name not in written:
                        archive.write(resolve_case_path(cached, filename), name)
                        written.add(name)
                if input_path not in written:
                    archive.write(resolve_case_path(dataset, row["canonical_path"]), input_path)
                    written.add(input_path)
                index["entries"].append({"image_id": record["image_id"], "tool_id": record["tool_id"], "cache_key": record["cache_key"], "contract": contract, "input_path": input_path, "evidence_dir": prefix})
            archive.writestr("bundle.json", __import__("json").dumps(index, ensure_ascii=False, allow_nan=False, indent=2))
        os.replace(temporary, archive_path)
    finally:
        temporary.unlink(missing_ok=True)
    write_json(directory / "results_manifest.json", index)
    return archive_path


def run_batch(root: Path, dataset: Path, stage: str, shutdown_deadline=None, pilot_review: Path | None = None, shutdown_record: Path | None = None, profile_id="gpu_full_v1", image_ids=None, tool_ids=None):
    root, dataset = Path(root).resolve(), Path(dataset).resolve()
    if stage not in ("pilot", "all"):
        raise ValueError("Stage must be pilot or all")
    if profile_id not in GPU_PROFILE_IDS:
        raise ValueError("Explicit supported GPU evidence profile required")
    deadline, receipt = verify_shutdown_record(shutdown_record or root / "runtime/remote/shutdown_record.json", shutdown_deadline)
    manifest = validate_dataset(dataset)
    if tool_ids is not None and (stage != "all" or not isinstance(tool_ids, list) or not tool_ids or any(type(t) is not str for t in tool_ids) or len(set(tool_ids)) != len(tool_ids) or not set(tool_ids) <= set(ORDER)):
        raise ValueError("Tool selection requires reviewed all stage and distinct supported tool IDs")
    requested_tools = tuple(t for t in ORDER if tool_ids is None or t in tool_ids)
    selection = None
    if image_ids is not None:
        if stage != "all" or not isinstance(image_ids, list) or not image_ids or any(type(i) is not str for i in image_ids) or len(image_ids) != len(set(image_ids)) or not set(image_ids) <= {r["image_id"] for r in manifest["images"]}:
            raise ValueError("Selection requires reviewed all stage and distinct IDs from the frozen dataset")
        selection = sorted(image_ids)
    profile, registry = load_profile(profile_id, root), load_registry(root, profile_id)
    if profile.configuration_status in ("design_example_not_deployed", "example"):
        raise ValueError("GPU configuration must be explicitly deployed and frozen before runtime")
    if profile.keep_worker_alive:
        # Existing worker_main is one job per process. We do not alter the frozen
        # profile/contract: serial runner deliberately releases after each image.
        lifetime_note = "existing single-job worker; no cross-image process retained"
    else:
        lifetime_note = "single-job worker"
    if stage == "all":
        for tool in requested_tools:
            check_entry(registry.tools[tool], require_ready=True)
            make_contract(manifest["images"][0]["canonical_sha256"], tool, profile, registry.tools[tool], canonicalizer_version=manifest["images"][0]["canonicalizer_version"])
    dataset_directory = root / "runtime/remote_batches" / (sha256_file(dataset / "manifest.json")[:16])
    scope_name = stage if selection is None else "selection_" + __import__("hashlib").sha256(__import__("json").dumps(selection, separators=(",", ":")).encode()).hexdigest()[:16]
    if requested_tools != ORDER:
        scope_name += "_tools_" + __import__("hashlib").sha256(__import__("json").dumps(requested_tools).encode()).hexdigest()[:8]
    directory = (dataset_directory if profile_id == "gpu_full_v1" else dataset_directory / profile_id) / scope_name
    directory.mkdir(parents=True, exist_ok=True)
    pilot_path = directory.parent / "pilot/summary.json"
    if stage == "all":
        if pilot_review is None:
            raise ValueError("Full dataset requires a pilot-review JSON; review cannot be inferred")
        verify_pilot_review(root, manifest, profile, registry, pilot_path, pilot_review, sha256_file(dataset / "manifest.json"))
    with FileLock(str(root / ".hir-remote-batch.lock"), timeout=0):
        previous = read_json(directory / "summary.json").get("results", []) if (directory / "summary.json").exists() else []
        previous.extend(read_json(path) for path in sorted((directory / "completed_records").glob("*.json")))
        if profile_id == "gpu_yoloe26l_v1":
            original_pilot = dataset_directory / "pilot/summary.json"
            if original_pilot.is_file():
                source_proof = read_json(original_pilot)
                if source_proof.get("dataset_manifest_sha256") == sha256_file(dataset / "manifest.json"):
                    # _prior_actual and _valid_result require full contract,
                    # cache/output digests and genuine released worker proof.
                    previous.extend(r for r in source_proof.get("results", []) if r.get("tool_id") != "T4_SEGMENTATION")
        if stage == "all":
            previous += read_json(pilot_path)["results"]
        summary = {"stage": stage, "started_at": now(), "dataset_manifest_path": str(dataset / "manifest.json"), "dataset_manifest_sha256": sha256_file(dataset / "manifest.json"), "pilot_ids": manifest["pilot_ids"], "profile": profile.model_dump(), "shutdown_deadline_utc": deadline.isoformat() if receipt.get("verified") is True else None, "compute_deadline_utc": deadline.isoformat(), "shutdown_verified": receipt.get("verified") is True, "shutdown_record": receipt, "return_window_seconds": RETURN_WINDOW_SECONDS, "worker_lifetime": lifetime_note, "complete": False, "results": [], "errors": [], "actual_inference_confirmed_count": 0, "model_executions_this_run": 0, "cache_hits_this_run": 0, "visual_review_required": stage == "pilot"}
        selected = [r for r in manifest["images"] if (r["image_id"] in selection if selection is not None else stage == "all" or r["image_id"] in manifest["pilot_ids"])]
        summary.update(dataset_image_count=len(manifest["images"]),selected_image_count=len(selected),selected_image_ids=[r["image_id"] for r in selected],requested_tool_ids=list(requested_tools),scope="reviewed_tool_subset" if requested_tools != ORDER else "reviewed_subset" if selection is not None else "five_photo_pilot" if stage == "pilot" else "full_dataset",full_dataset_complete=False)
        stopped = False
        for tool in requested_tools:
            for row in selected:
                # Reserve the full frozen job budget before starting, plus the
                # untouched 15-minute transfer window. Never extend shutdown.
                remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
                if remaining < RETURN_WINDOW_SECONDS + STARTUP_CLEANUP_RESERVE_SECONDS + profile.tools[tool]["timeout_seconds"]:
                    summary.update(stopped_reason="shutdown_return_window", remaining_seconds=remaining)
                    stopped = True
                    break
                result = None
                for attempt in range(2):
                    try:
                        result = _run_one(root, dataset, row, tool, profile, registry, stage, previous)
                        result["io_attempts"] = attempt + 1
                        break
                    except OSError as exc:
                        if attempt == 0 and exc.errno in TRANSIENT_ERRNOS:
                            time.sleep(.25)
                            continue
                        result = {"image_id": row["image_id"], "tool_id": tool, "status": "failed", "actual_inference_confirmed": False, "error_code": "io_error", "message": str(exc), "io_attempts": attempt + 1}
                        break
                    except (ValueError, KeyError, TypeError) as exc:
                        message = str(exc)
                        code = "model_missing" if "model_missing:" in message else "unavailable" if "unavailable:" in message else "validation_error"
                        result = {"image_id": row["image_id"], "tool_id": tool, "status": "failed", "actual_inference_confirmed": False, "error_code": code, "message": message, "io_attempts": attempt + 1}
                        break
                    except KeyboardInterrupt:
                        result = {"image_id": row["image_id"], "tool_id": tool, "status": "interrupted", "actual_inference_confirmed": False, "error_code": "interrupted", "message": "Interrupt received; isolated monitor cleans up its worker and validated prior caches are retained", "io_attempts": attempt + 1}
                        break
                summary["results"].append(result)
                if result["status"] in ("ok", "empty"):
                    write_json(directory / "completed_records" / (row["image_id"] + "_" + tool + ".json"), result)
                summary["actual_inference_confirmed_count"] += int(result.get("actual_inference_confirmed") is True)
                summary["model_executions_this_run"] += int(result.get("actual_inference_confirmed") is True and not result.get("cache_hit"))
                summary["cache_hits_this_run"] += int(result.get("cache_hit") is True)
                _status(directory, summary)
                if result["status"] not in ("ok", "empty"):
                    summary["stopped_reason"] = result.get("error_code", result["status"])
                    stopped = True
                    break
            if stopped:
                break
        summary["complete"] = not stopped and len(summary["results"]) == len(selected) * len(requested_tools) and all(r["status"] in ("ok", "empty") for r in summary["results"])
        if stage == "pilot":
            summary["complete"] = summary["complete"] and summary["actual_inference_confirmed_count"] == 20
        summary["finished_at"] = now()
        summary["full_dataset_complete"] = summary["complete"] and stage == "all" and selection is None and requested_tools == ORDER
        _status(directory, summary)
        archive = package_results(root, dataset, manifest, summary, directory)
        summary["validated_results_zip"] = str(archive)
        summary["validated_results_zip_sha256"] = sha256_file(archive)
        _status(directory, summary)
        return summary
