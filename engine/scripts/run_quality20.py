"""Resumable, single-writer twenty-photo diagnostic pilot; never fake evidence.

Issue requests first, inspect each request/image in Work, archive task_reviews,
then ingest genuine JSON. Tools are a separate, sequential acceptance gate.
This batch is CPU interface validation, not a completed restoration experiment.
"""
import argparse
from collections import Counter
from pathlib import Path
import platform
import time
import uuid

import psutil

from hir_manual.protocol import validate_schema
from hir_manual.service import Controller, history
from hir_manual.storage import json_bytes, now, read_json, sha256_file, transactions, write_json, writer_lock
from hir_manual.tool_cli import doctor
from hir_manual.tool_registry import load_profile, load_registry
from hir_manual.transport import import_payload
from hir_manual.cache import EvidenceCache

ROOT = Path(__file__).resolve().parents[2]
INTENT = "保守修复实际可见的照片缺陷，保留拍摄光线、景深、构图、身份、人数、文字和几何。不补造暗部、模糊小脸或小字中无法确认的细节；清晰或无确证损伤的照片保持原状。"


def validate_batch(batch):
    manifest = read_json(batch / "manifest.json")
    rows = manifest["images"]
    if len(rows) != 20 or len({r["sample_id"] for r in rows}) != 20 or len({r["original_sha256"] for r in rows}) != 20:
        raise ValueError("Expected exactly twenty distinct real inputs")
    if manifest["selection_sha256"] != sha256_file(batch / "selection.json"):
        raise ValueError("Selection changed")
    for row in rows:
        for field, digest in (("input_path", "original_sha256"), ("canonical_path", "canonical_sha256")):
            if sha256_file(Path(row[field])) != row[digest]:
                raise ValueError("Original or viewed canonical image changed: " + row["sample_id"])
    return manifest


def freeze(batch, manifest):
    path = batch / "trial_contract.json"
    if path.exists():
        contract = read_json(path)
        if contract["manifest_sha256"] != sha256_file(batch / "manifest.json"):
            raise ValueError("Frozen twenty-photo manifest changed; create a new batch")
        return contract
    profile = load_profile("cpu_probe_v1", ROOT).model_dump()
    registry = load_registry(ROOT, "cpu_probe_v1").model_dump()
    contract = {
        "batch_id": batch.name, "frozen_at": now(), "input_count": 20,
        "manifest_sha256": sha256_file(batch / "manifest.json"),
        "selection_sha256": sha256_file(batch / "selection.json"),
        "intent": INTENT, "evidence_profile_id": "cpu_probe_v1",
        "evidence_profile": profile, "tool_registry": registry,
        "executor": "chatgpt_desktop_image", "external_model_api_calls": False,
        "harness_max_generations": 3, "direct_first_round_generations": 1,
        "formal_eligible": False, "scope": "purposeful real-photo CPU interface pilot",
        "direct_harness_comparison": "pending; same original and intent, separate sessions; first round separate from final",
        "references_read": False, "source_independence": "not established from file-list metadata",
        "diagnostic_entry": "current local Work; separately scoped from desktop session dispatch",
        "quality_gate": "No missing evidence silently waived; no SDK or restoration success inferred from schema validation.",
    }
    write_json(path, contract)
    # Runtime inputs and preprocessing snapshots belong to this isolated batch.
    # Model assets remain the absolute, immutable paths of the prepared registry.
    write_json(batch / "workflow/preprocessing/registry/cpu_probe_v1.json", registry)
    write_json(batch / "workflow/preprocessing/configs/cpu_probe.json", profile)
    return contract


def issue(batch, manifest, contract, limit):
    ctl = Controller(batch / "workflow")
    records = []
    created = 0
    for row in manifest["images"]:
        matches = []
        for config_path in (ctl.root / "cases").glob("*/case_config.json"):
            config = read_json(config_path)
            if config.get("sample_id") == row["sample_id"] and config.get("quality_batch_id") == batch.name:
                matches.append(config_path.parent.name)
        if len(matches) > 1:
            raise ValueError("Duplicate issued case; explicit recovery review required")
        if matches:
            state = ctl.inspect(matches[0])
        elif limit is None or created < limit:
            state = ctl.new(Path(row["input_path"]), contract["intent"], {
                "auto_local_tools": False, "evidence_profile_id": "cpu_probe_v1",
                "evidence_profile": contract["evidence_profile"], "tool_registry": contract["tool_registry"],
                "max_generations": 3, "branch_type": "quality20_diagnostic_CPU_interface",
                "quality_batch_id": batch.name, "sample_id": row["sample_id"],
                "formal_eligible": False,
            })
            created += 1
        else:
            break
        if state.input_sha256 != row["canonical_sha256"]:
            raise ValueError("Issued canonical differs from viewed input")
        case = ctl.case(state.case_id)
        metadata = read_json(case.path("input/metadata.json"))
        if metadata["original_sha256"] != row["original_sha256"] or metadata.get("canonicalizer_version", "hir_rgb8_exif_icc_v1") != row.get("canonicalizer_version", "hir_rgb8_exif_icc_v1"):
            raise ValueError("Issued source bytes or canonicalizer version differ from selected input")
        issued = [tx for tx in transactions(case)
                  if tx["event"]["type"] == "task_issued" and tx["event"]["details"].get("role") == "diagnose"]
        if len(issued) != 1:
            raise ValueError("Expected a single immutable diagnostic request")
        task_id = issued[0]["event"]["details"]["task_id"]
        request_path = case.path(f"tasks/{task_id}/request.json")
        record = {"sample_id": row["sample_id"], "case_id": state.case_id, "task_id": task_id,
                  "request_path": str(request_path), "request_sha256": sha256_file(request_path),
                  "work_task_path": str(case.path(f"tasks/{task_id}/work_task.txt")),
                  "canonical_path": str(case.path("input/canonical.png")), "canonical_sha256": state.input_sha256,
                  "issued_at": issued[0]["event"]["at"], "workflow_status": state.workflow_status}
        records.append(record)
        write_json(batch / "issued_tasks.json", {"records": records, "input_count": 20})
    return {"issued_or_recovered": len(records), "new_cases": created, "stage": "issue",
            "restoration_outputs": 0}


def ingest(batch, manifest, contract, limit, stop_after_publish):
    ctl = Controller(batch / "workflow")
    task_rows = {r["sample_id"]: r for r in read_json(batch / "issued_tasks.json")["records"]}
    records, accepted_new, skipped = [], 0, 0
    for row in manifest["images"]:
        sample_id = row["sample_id"]
        if sample_id not in task_rows:
            break
        task = task_rows[sample_id]
        case = ctl.case(task["case_id"])
        request_path = Path(task["request_path"])
        if sha256_file(request_path) != task["request_sha256"]:
            raise ValueError("Immutable request changed")
        payload_path = batch / "diagnoses" / (sample_id + ".json")
        review = read_json(batch / "task_reviews" / (sample_id + ".json"))
        payload = read_json(payload_path)
        validate_schema("diagnosis.schema.json", payload)
        for key, value in (("task_id", task["task_id"]), ("request_sha256", task["request_sha256"]),
                           ("canonical_sha256", row["canonical_sha256"]), ("diagnosis_sha256", sha256_file(payload_path))):
            if review.get(key) != value:
                raise ValueError("Work task review does not match immutable input/response: " + key)
        if review.get("request_read") is not True or review.get("canonical_viewed_after_request") is not True:
            raise ValueError("Requires genuine post-request inspection; preparatory observations are insufficient")
        from hir_manual.protocol import parse_time
        if parse_time(review["completed_at"]) < parse_time(task["issued_at"]):
            raise ValueError("Review predates controller request")
        expected = "WAIT_EVIDENCE" if payload["tool_plan"] else "WAIT_COMPOSITION"
        old = ctl.inspect(task["case_id"])
        official = history(case)["diagnosis"]
        if official is not None:
            if official != payload:
                raise ValueError("Official diagnosis differs; new branch required")
            skipped += 1
        elif limit is not None and accepted_new >= limit:
            break
        else:
            request = read_json(request_path)
            response = {key: request[key] for key in ("protocol_version", "task_id", "case_id", "role", "round", "expected_state_revision", "input_sha256")}
            response.update(status="ok", payload=payload, error=None, provenance={
                "model_display_name": "Current local Work (UI model identifier not exposed)",
                "model_version": None, "model_version_source": "not_exposed", "session_id": None,
                "transport_mode": "file", "writer": "local_work",
                "started_at": task["issued_at"], "completed_at": review["completed_at"],
            })
            ready = case.path(request["ready_marker"])
            if ready.exists():
                if read_json(case.path(request["response_file"])) != response:
                    raise ValueError("Different response was already published")
            else:
                result = import_payload(case, task["task_id"], json_bytes(response).decode("utf-8"), {})
                if not result.accepted:
                    raise ValueError(result.message)
            if stop_after_publish:
                return {"stage": "ingest", "stopped_after_publish": True, "sample_id": sample_id,
                        "state_before_restart": old.workflow_status, "response_published": True,
                        "controller_acceptance_not_yet_run": True}
            results = ctl.scan()
            if not results or any(not r.accepted for r in results):
                raise ValueError("Controller rejected a published response")
            accepted_new += 1
        state = ctl.inspect(task["case_id"])
        if history(case)["diagnosis"] != payload or state.workflow_status != expected:
            raise ValueError("Unexpected post-diagnosis state; stop rather than skip evidence")
        record = {"sample_id": sample_id, "case_id": state.case_id, "task_id": task["task_id"],
                  "diagnosis_sha256": sha256_file(payload_path), "request_sha256": task["request_sha256"],
                  "accepted": True, "workflow_status": state.workflow_status, "expected_state": expected,
                  "revision": state.revision, "pending_task_id": state.pending_task_id,
                  "required_tools": state.required_tools, "received_tools": state.received_tools,
                  "consumed_generations": state.budget.consumed, "reserved_generations": state.budget.reserved,
                  "workflow_completed": state.workflow_completed, "restoration_success": state.restoration_success,
                  "formal_eligible": False, "branch_deviated": state.deviated}
        records.append(record)
        write_json(batch / "diagnostic_results.json", {
            "records": records, "actual_input_count": 20, "accepted_count": len(records),
            "states": dict(Counter(r["workflow_status"] for r in records)),
            "scope": "real-photo current Work JSON/file handoff and Controller only",
            "actual_tool_inferences": 0, "actual_image_edits": 0,
            "quality_conclusion": None, "formal_eligible": False,
        })
    return {"stage": "ingest", "accepted_records": len(records), "new_acceptances": accepted_new,
            "already_accepted_skipped": skipped, "states": dict(Counter(r["workflow_status"] for r in records)),
            "restoration_outputs": 0}


def probe(batch, manifest, contract):
    # Only the first T2 probe is attempted until M1's 3-photo T2/T1 gate passes.
    # Do not create 20 identical RAM failures or count unstarted jobs as inference.
    source = next(r for r in manifest["images"] if r["sample_id"] == "HC_RAIM_Phase1_011")
    if load_profile("cpu_probe_v1", ROOT).model_dump() != contract["evidence_profile"] or load_registry(ROOT, "cpu_probe_v1").model_dump() != contract["tool_registry"]:
        raise ValueError("Deployment changed after batch freeze; create a new trial configuration")
    result = doctor(ROOT, "cpu_probe_v1", "T2_FACE", Path(source["input_path"]))
    detection_count = None
    cache_reuse = None
    if result["ready"]:
        cached = Path(result["cache_path"])
        evidence = read_json(cached / "evidence.json")
        detection_count = len(evidence["detections"])
        cache_reuse = EvidenceCache(ROOT / "Data/annotations/cache").lookup(read_json(cached / "contract.json")) == cached
    report = {"stage": "M1_first_T2_probe", "created_at": now(), "sample_id": source["sample_id"],
              "formal_eligible": False, "result": result,
              "remaining_stage_jobs": "not attempted until first T2 probe passes; then T2 three photos, T1 three photos, then M2",
              "outcome": ("empty_detection" if detection_count == 0 else "evidence_returned") if result["ready"] else result["worker"].get("status", "model_run_failed"),
              "validated_inferences": int(result["ready"]), "detection_count": detection_count,
              "cache_reuse_validated": cache_reuse,
              "restoration_outputs": 0}
    write_json(batch / "tool_probe.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", required=True, type=Path)
    parser.add_argument("--stage", required=True, choices=["issue", "ingest", "probe"])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--stop-after-publish", action="store_true",
                        help="Stop before Controller scan to exercise real restart recovery")
    args = parser.parse_args()
    batch = args.batch.resolve()
    if not batch.is_relative_to(ROOT / "runtime/quality20") or (args.limit is not None and args.limit < 1):
        raise ValueError("Use a quality20 batch within this workspace and a positive limit")
    process = psutil.Process()
    started_at, start, rss_start = now(), time.monotonic(), process.memory_info().rss / 1024**2
    available_start = psutil.virtual_memory().available / 1024**2
    with writer_lock(batch):
        try:
            manifest = validate_batch(batch)
            contract = freeze(batch, manifest)
            if args.stage == "issue":
                result = issue(batch, manifest, contract, args.limit)
            elif args.stage == "ingest":
                result = ingest(batch, manifest, contract, args.limit, args.stop_after_publish)
            else:
                result = probe(batch, manifest, contract)
        except (ValueError, OSError, KeyError) as exc:
            write_json(batch / "runs" / (uuid.uuid4().hex + ".json"), {
                "stage": args.stage, "started_at": started_at, "completed_at": now(),
                "status": "stopped", "error": str(exc),
                "elapsed_ms": (time.monotonic() - start) * 1000,
                "restoration_outputs": 0, "no_missing_evidence_waived": True,
            })
            raise
        receipt = {"run_id": uuid.uuid4().hex, "started_at": started_at, "completed_at": now(),
                   "controller_python": platform.python_version(), "controller_psutil": psutil.__version__,
                   "elapsed_ms": (time.monotonic() - start) * 1000,
                   "controller_rss_start_mib": rss_start, "controller_rss_end_mib": process.memory_info().rss / 1024**2,
                   "controller_rss_note": "Endpoint observations only, not peak model memory or Work visual reasoning time",
                   "available_memory_start_mib": available_start,
                   "available_memory_end_mib": psutil.virtual_memory().available / 1024**2,
                   "result": result}
        write_json(batch / "runs" / (receipt["run_id"] + ".json"), receipt)
        print(receipt)
        return 3 if args.stage == "probe" and not result["result"]["ready"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
