"""Persistent queue, cache resolution and single isolated model execution."""
import concurrent.futures
import threading
import time
from pathlib import Path
from filelock import Timeout
from .cache import EvidenceCache
from .storage import read_json, write_json, now, sha256_file
from .tool_models import EvidenceProfile, ModelRegistry, ToolJob
from .tool_registry import load_profile, load_registry, check_entry, make_contract, canonicalizer_version_from_metadata
from .tool_jobs import prepare_job, update_job
from .resource_monitor import run_worker, available_mb
from .local_evidence import validate_local_evidence

_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="hir-tool-controller")
_futures = {}
_future_lock = threading.Lock()


class ToolService:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.cache = EvidenceCache(self.root / "Data/annotations/cache")

    def _case_configuration(self, case):
        config = read_json(case.path("case_config.json"))
        return EvidenceProfile.model_validate(config["evidence_profile"]), ModelRegistry.model_validate(config["tool_registry"])

    def resolve_or_enqueue(self, case, tool_id, profile=None):
        from .service import Controller
        config = read_json(case.path("case_config.json"))
        profile, registry = self._case_configuration(case)
        entry = registry.tools[tool_id]
        state = read_json(case.path("state.json"))
        metadata = read_json(case.path("input/metadata.json"))
        version = canonicalizer_version_from_metadata(metadata)
        try:
            contract = make_contract(state["input_sha256"], tool_id, profile, entry, canonicalizer_version=version)
        except (ValueError, KeyError) as exc:
            Controller(self.root).record_tool_unavailable(case.case_id, tool_id, "model_missing", str(exc))
            return None
        existing = self.cache.lookup(contract)
        if existing:
            Controller(self.root).accept_local_evidence(case.case_id, existing, "cache_import", {"cache_hit": True, "runtime_elapsed_ms": 0.0})
            return None
        try:
            check_entry(entry)
        except (ValueError, OSError) as exc:
            Controller(self.root).record_tool_unavailable(case.case_id, tool_id, "model_missing", str(exc))
            return None
        # Resume a persisted job instead of launching a second one.
        for path in sorted((self.root / "runtime/tool_jobs").glob("*/job.json")):
            data = read_json(path)
            if data["case_id"] == case.case_id and data["tool_id"] == tool_id and data["cache_contract"] == contract and data["status"] in ("queued", "running", "resource_wait"):
                return ToolJob.model_validate(data)
        job, _ = prepare_job(self.root, case.path("input/canonical.png"), metadata["original_sha256"], case.case_id, tool_id, profile, registry, case.case_id, canonicalizer_version=version)
        return job

    def _run_job(self, job, profile, registry, require_ready=True, force_compute=False):
        directory = self.root / "runtime/tool_jobs" / job.job_id
        cached = self.cache.lookup(job.cache_contract)
        if cached and not force_compute:
            update_job(directory, job, "cache_hit")
            return cached, {"cache_hit": True, "runtime_elapsed_ms": 0.0}
        try:
            with self.cache.lock(job.tool_id, job.cache_key):
                cached = self.cache.lookup(job.cache_contract)
                if cached and not force_compute:
                    update_job(directory, job, "cache_hit")
                    return cached, {"cache_hit": True, "runtime_elapsed_ms": 0.0}
                update_job(directory, job, "running")
                result = run_worker(job, registry, directory, profile, self.root, require_ready=require_ready)
                write_json(directory / "worker_result.json", result)
                if result.status != "completed":
                    update_job(directory, job, "resource_wait" if result.status == "resource_wait" else "failed", result.error_code + ": " + (result.message or ""))
                    return None, result.model_dump()
                output = Path(result.output_dir)
                marker = read_json(output / "worker_done.json")
                if marker["evidence_sha256"] != sha256_file(output / "evidence.json"):
                    raise ValueError("Worker completion evidence hash mismatch")
                manifest = validate_local_evidence(output, job.cache_contract)
                if marker["artifact_hashes"] != [{"path": a.path, "sha256": a.sha256} for a in manifest.assets]:
                    raise ValueError("Worker done asset manifest mismatch")
                measured = manifest.model_dump()
                measured["elapsed_ms"] = result.elapsed_ms
                measured["peak_rss_mb"] = result.peak_rss_mb
                measured["quality_warnings"] = list(dict.fromkeys(measured["quality_warnings"] + ["RSS is a sampled process-tree peak, not exact peak"]))
                write_json(output / "evidence.json", measured)
                # Preserve the original worker marker; controller measurements
                # form the validated cache manifest, with its own ready marker.
                cached = self.cache.publish(job.cache_contract, output)
                update_job(directory, job, "completed")
                return cached, result.model_dump() | {"job_id": job.job_id}
        except Timeout:
            update_job(directory, job, "resource_wait", "cache_pending: another computation owns this contract")
            return None, {"status": "resource_wait", "error_code": "cache_pending"}
        except (ValueError, OSError, KeyError) as exc:
            update_job(directory, job, "failed", "validation_error: " + str(exc))
            return None, {"status": "failed", "error_code": "validation_error", "message": str(exc)}

    def run_case(self, case_id):
        from .service import Controller
        ctl = Controller(self.root)
        case = ctl.case(case_id)
        profile, registry = self._case_configuration(case)
        for tool_id in ("T2_FACE", "T1_OCR", "T3_DEPTH", "T4_SEGMENTATION"):
            state = ctl.inspect(case_id)
            unavailable = ctl.unavailable_tools(case_id)
            if state.workflow_status != "WAIT_EVIDENCE" or state.operation_status != "active":
                break
            if tool_id not in state.required_tools or tool_id in state.received_tools or tool_id in unavailable:
                continue
            job = self.resolve_or_enqueue(case, tool_id)
            if job is None:
                continue
            cached, metrics = self._run_job(job, profile, registry)
            if cached:
                ctl.accept_local_evidence(case_id, cached, "cache_import" if metrics.get("cache_hit") else "local_compute", metrics)
            elif metrics["status"] == "resource_wait":
                break
            else:
                ctl.record_tool_unavailable(case_id, tool_id, metrics.get("error_code", "worker_error"), metrics.get("message", job.last_error or "Tool failure"), metrics)
        return ctl.inspect(case_id)

    def tick(self):
        # UI tick is cheap and returns immediately; all SDK work is elsewhere.
        with _future_lock:
            for key, future in list(_futures.items()):
                if future.done():
                    try:
                        future.result()
                    except Exception as exc:
                        write_json(self.root / "runtime/tool_scheduler_errors" / (str(time.time_ns()) + ".json"), {"error": str(exc), "at": now()})
                    del _futures[key]
            if _futures:
                return
            for state_path in sorted((self.root / "cases").glob("*/state.json")):
                state = read_json(state_path)
                config = read_json(state_path.parent / "case_config.json")
                if not config.get("auto_local_tools") or state["workflow_status"] != "WAIT_EVIDENCE" or state["operation_status"] != "active":
                    continue
                profile = EvidenceProfile.model_validate(config["evidence_profile"])
                waiting = [read_json(p) for p in (self.root/"runtime/tool_jobs").glob("*/job.json") if read_json(p).get("case_id") == state["case_id"] and read_json(p).get("status") == "resource_wait"]
                if waiting and available_mb() < profile.min_available_memory_mb and not any(self.cache.lookup(j["cache_contract"]) for j in waiting):
                    continue
                key = (str(self.root), state["case_id"])
                _futures[key] = _pool.submit(self.run_case, state["case_id"])
                break
