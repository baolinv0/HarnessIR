"""Optional persistent, isolated Python workers for built-in native adapters.

Run ``python -m hre.v3.worker --serve`` inside an explicitly deployed model
environment. The JSON-lines protocol carries file paths, never image base64.
The service records a started marker before inference and never resubmits an
ambiguous old job. This is an at-most-once recovery policy, not a distributed
exactly-once guarantee.
"""
from __future__ import annotations

import argparse
import atexit
from contextlib import redirect_stdout
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading

from ..models import HREError, canonical_json, file_sha256, now
from ..storage import case_lock, read_json, write_json
from .common import digest, require, runtime_clear


def process_job(envelope: dict) -> dict:
    require(envelope.get("schema_version") == "hre_native_job_v3", "worker_request_invalid", "Wrong worker protocol")
    operation = envelope.get("operation")
    if operation == "probe":
        from .deployment import probe_runtime
        return {"ok": True, "payload": probe_runtime(envelope["profile_id"], envelope["kind"], envelope["config"])}
    require(operation in {"compile", "generate"}, "worker_operation_invalid", "Unknown native operation")
    job_root = Path(envelope["job_dir"]).resolve()
    content = {key: value for key, value in envelope.items() if key not in {"job_dir"}}
    identity = digest(content)
    with case_lock(job_root):
        marker = job_root / "job.json"
        result_path = job_root / "result.json"
        if marker.exists():
            previous = read_json(marker)
            require(previous["request_sha256"] == identity, "worker_job_conflict", "Job identity reused with changed content")
            if result_path.exists():
                result = read_json(result_path)
                if previous.get("result_sha256"):
                    require(file_sha256(result_path) == previous["result_sha256"], "worker_result_modified", "Worker result changed")
                # result.json is atomically committed after adapter completion;
                # it can reconcile a crash before the final marker was updated.
                return result
            raise HREError("worker_submission_unknown", "An earlier job was started without a durable result; reconcile before any new execution")
        write_json(marker, {"request_sha256": identity, "status": "started", "started_at": now()})
        from .dispatch import _compile_local, _generate_local
        try:
            if operation == "compile":
                payload = _compile_local(envelope["request"], envelope["config"])
            else:
                payload = _generate_local(envelope["request"], envelope["condition"], envelope["config"], Path(envelope["output_dir"]))
            result = {"ok": True, "payload": payload, "request_sha256": identity}
        except Exception as exc:
            result = {"ok": False, "error": {"code": getattr(exc, "code", type(exc).__name__), "message": str(exc),
                       "observation": getattr(exc, "observation", None), "native_output": getattr(exc, "native_output", None)},
                      "request_sha256": identity}
        write_json(result_path, result)
        write_json(marker, {"request_sha256": identity, "status": "succeeded" if result["ok"] else "failed",
                            "finished_at": now(), "result_sha256": file_sha256(result_path)})
        return result


class WorkerClient:
    def __init__(self, settings: dict):
        command = settings.get("command")
        require(isinstance(command, list) and command and all(isinstance(item, str) and item for item in command),
                "worker_command_invalid", "Worker command must be an explicit argv list")
        self.timeout = settings.get("timeout_seconds", 1800)
        require(type(self.timeout) in {int, float} and math.isfinite(self.timeout) and self.timeout > 0,
                "worker_timeout_invalid", "Positive finite worker timeout required")
        require(settings.get("cwd") is None or (isinstance(settings["cwd"], str) and Path(settings["cwd"]).is_dir()),
                "worker_cwd_invalid", "Configured worker working directory does not exist")
        environment = os.environ.copy()
        environment.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", PYTHONUNBUFFERED="1")
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=None, text=True, bufsize=1, env=environment,
                                        cwd=settings.get("cwd"))
        self.responses = queue.Queue()
        self.lock = threading.RLock()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            for line in self.process.stdout:
                self.responses.put(line)
        finally:
            self.responses.put(None)

    def call(self, envelope: dict) -> dict:
        with self.lock:
            require(self.process.poll() is None, "worker_exited", "Native worker exited; inspect its durable job record")
            try:
                self.process.stdin.write(canonical_json(envelope).decode() + "\n")
                self.process.stdin.flush()
                line = self.responses.get(timeout=self.timeout)
            except (OSError, queue.Empty) as exc:
                self.close()
                raise HREError("worker_submission_unknown", "Worker response was lost or timed out; do not blindly repeat generation") from exc
            require(line is not None, "worker_submission_unknown", "Worker exited before a response; inspect the durable job result")
            try:
                result = json.loads(line)
            except (TypeError, ValueError) as exc:
                self.close()
                raise HREError("worker_protocol_error", "Non-JSON worker stdout; results may already exist in the job directory") from exc
            return result

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)


_clients: dict[str, WorkerClient] = {}


def close_workers():
    for client in _clients.values():
        client.close()
    _clients.clear()


atexit.register(close_workers)


def probe_worker(settings: dict, profile_id: str, kind: str, config: dict) -> dict:
    client = WorkerClient(settings)
    local_config = {key: value for key, value in config.items() if key != "worker"}
    try:
        result = client.call({"schema_version": "hre_native_job_v3", "operation": "probe",
                              "profile_id": profile_id, "kind": kind, "config": local_config})
        require(result.get("ok"), "worker_preflight_failed", str(result.get("error", {})))
        return result["payload"]
    finally:
        client.close()


def invoke_worker(operation: str, request: dict, config: dict, *, condition: dict | None = None,
                  output_dir: Path | None = None) -> dict:
    settings = config["worker"]
    local_config = deepcopy(config)
    del local_config["worker"]
    envelope = {"schema_version": "hre_native_job_v3", "operation": operation,
                "request": request, "config": local_config}
    if operation == "generate":
        envelope.update(condition=condition, output_dir=str(Path(output_dir).resolve()))
    job_id = digest(envelope)
    parent = Path(settings.get("spool_dir", Path(request["inputs"][0]["path"]).parent / "worker_jobs"))
    envelope["job_dir"] = str((parent / job_id).resolve())
    # Separate compiler/editor processes keep optional dependencies and loaded
    # weights isolated. An explicit capacity choice controls whether both remain
    # resident on the same GPU; default releases the other process first.
    key = digest({"operation": operation, "profile": request["profile_id"], "worker": settings})
    if not settings.get("keep_other_workers", False):
        for other in list(_clients):
            if other != key:
                _clients.pop(other).close()
    client = _clients.get(key)
    if client is None or client.process.poll() is not None:
        client = _clients[key] = WorkerClient(settings)
    result = client.call(envelope)
    require(isinstance(result, dict), "worker_protocol_error", "Expected a worker response object")
    if not result.get("ok"):
        failure = result.get("error", {})
        error = HREError(failure.get("code", "worker_failed"), failure.get("message", "Native worker failed"))
        error.observation, error.native_output = failure.get("observation"), failure.get("native_output")
        error.worker_job_dir = envelope["job_dir"]
        raise error
    expected = digest({key: value for key, value in envelope.items() if key != "job_dir"})
    require(result.get("request_sha256") == expected, "worker_response_mismatch", "Worker response belongs to another request")
    payload = result["payload"]
    payload.setdefault("observation", {}).update(worker_job_dir=envelope["job_dir"], worker_command=settings["command"])
    return payload


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true", required=True)
    parser.parse_args(argv)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    try:
        for line in sys.stdin:
            try:
                envelope = json.loads(line)
                # Third-party progress prints must not corrupt the JSON protocol.
                with redirect_stdout(sys.stderr):
                    result = process_job(envelope)
            except Exception as exc:
                result = {"ok": False, "error": {"code": getattr(exc, "code", type(exc).__name__), "message": str(exc)}}
            sys.stdout.write(canonical_json(result).decode() + "\n")
            sys.stdout.flush()
    finally:
        runtime_clear()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
