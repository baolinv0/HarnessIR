"""Recoverable two-mode, four-executor orchestration for opt-in v3 cases.

No model is invoked by imports. All image calls are preceded by a durable
submission marker; an interrupted call without a matching completion receipt is
never automatically repeated. Test callers may inject the same documented
stage/compiler/editor boundaries without a GPU or network connection.
"""
from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image

from ..models import HREError, file_sha256, now, sha256_bytes
from ..storage import case_lock, read_json, write_json
from .common import digest, require
from .runner_journal import Journal, immutable_json
from .stages import (SCHEMAS, TEMPLATE_VERSION, collect_basic_evidence, evidence_refs,
                     run_stage, stage_instruction, validate_intent, validate_payload)


class _UnknownSubmission(HREError):
    def __init__(self, operation):
        super().__init__("submission_unknown", "No confirmed response for " + operation + "; reconcile before resubmitting")


class _BudgetExhausted(HREError):
    def __init__(self, kind):
        super().__init__("budget_exhausted", kind + " budget is exhausted")


def _asset(asset: dict) -> dict:
    path = Path(asset["path"])
    require(path.is_file() and file_sha256(path) == asset["sha256"], "output_modified", "Image bytes changed: " + str(path))
    with Image.open(path) as image:
        require(image.size == (asset["width"], asset["height"]), "output_modified", "Image dimensions changed")
        if "mode" in asset:
            require(image.mode == asset["mode"], "output_modified", "Image mode changed")
    return asset


def _reference(path: Path, root: Path) -> dict:
    return {"path": path.relative_to(root).as_posix(), "sha256": file_sha256(path)}


def _read_ref(root: Path, ref: dict) -> dict:
    path = (root / ref["path"]).resolve()
    require(path.is_relative_to(root) and path.is_file() and file_sha256(path) == ref["sha256"],
            "artifact_changed", "Bound artifact changed or escaped its case")
    return read_json(path)


def _put(root: Path, relative: str, value: dict) -> dict:
    path = root / relative
    immutable_json(path, value)
    return _reference(path, root)


def _input_identity(inputs: list[dict]) -> list[dict]:
    return [{key: asset[key] for key in ("role", "sha256", "width", "height")} for asset in inputs]


def shared_intent_artifact(spec: dict, state: dict, intent: dict, provenance: dict,
                           planning: dict | None = None) -> dict:
    result = {"schema_version": "hre_shared_intent_v3", "task_mode": spec["task_mode"],
            "brief_sha256": sha256_bytes(spec["brief"].encode()), "inputs": _input_identity(state["inputs"]),
            "regions_sha256": digest(spec.get("regions", [])),
            "intent": deepcopy(intent), "intent_sha256": digest(intent), "provenance": provenance}
    if planning is not None:
        result["planning"] = deepcopy(planning)
        result["planning_sha256"] = digest(planning)
    return result


def import_shared_intent(path: Path, spec: dict, state: dict) -> dict:
    value = read_json(path)
    require(value.get("schema_version") == "hre_shared_intent_v3"
            and value.get("task_mode") == spec["task_mode"]
            and value.get("brief_sha256") == sha256_bytes(spec["brief"].encode())
            and value.get("inputs") == _input_identity(state["inputs"]),
            "shared_intent_binding", "Shared intent mode, brief or ordered source pixels differ")
    require(value.get("regions_sha256", digest([])) == digest(spec.get("regions", [])),
            "shared_intent_binding", "Frozen analysis regions differ from the shared planning artifact")
    require(value.get("intent_sha256") == digest(value.get("intent")),
            "shared_intent_modified", "Shared intent hash differs")
    if "planning" in value:
        require(value.get("planning_sha256") == digest(value["planning"]),
                "shared_intent_modified", "Frozen planning evidence hash differs")
        planning = value["planning"]
        require(isinstance(planning, dict) and not set(planning) - {"diagnosis", "evidence"},
                "shared_intent_invalid", "Frozen planning must contain only diagnosis/evidence")
        diagnosis, evidence = planning.get("diagnosis"), planning.get("evidence")
        if diagnosis is not None:
            validate_payload("diagnose", diagnosis, {"task_mode": spec["task_mode"],
                "context": {"available_evidence_refs": evidence_refs(state["inputs"])}})
        if evidence is not None:
            require(isinstance(evidence, dict) and evidence.get("schema_version") == "hre_evidence_v3"
                    and isinstance(evidence.get("records"), list), "shared_intent_invalid", "Frozen evidence has an invalid contract")
            identities = {asset["role"]: asset["sha256"] for asset in state["inputs"]}
            seen = set()
            for record in evidence["records"]:
                require(isinstance(record, dict) and isinstance(record.get("evidence_id"), str)
                        and record["evidence_id"] not in seen and record.get("role") in identities
                        and record.get("input_sha256") == identities[record["role"]],
                        "shared_intent_binding", "Frozen evidence is duplicated or belongs to other source pixels")
                seen.add(record["evidence_id"])
        allowed = set(evidence_refs(state["inputs"], diagnosis, evidence))
    else:
        # Older explicitly supplied artifacts may contain the intent alone.
        # Their original references remain provenance, not newly measured tools.
        allowed = None
    return validate_intent(value["intent"], spec["task_mode"], revision=0, check_parent=True, allowed_refs=allowed)


def _initialize(state: dict) -> dict:
    value = deepcopy(state)
    value.setdefault("phase", "start")
    value.setdefault("round", 0)
    value.setdefault("rounds", [])
    value.setdefault("candidates", [])
    value.setdefault("pending", None)
    value.setdefault("operation_attempts", {})
    value.setdefault("budget", {"generations": 0, "stage_calls": 0, "compiler_calls": 0})
    value.setdefault("artifacts", {})
    value.setdefault("intent", None)
    value.setdefault("observations", [])
    value.setdefault("success", False)
    return value


def _actual_charge(kind: str, result: dict) -> int:
    observation = result.get("observation", {})
    require(isinstance(observation, dict), "observation_missing", "Worker observation must be an object")
    key = "actual_generation_count" if kind == "generate" else "calls_attempted"
    value = observation.get(key)
    require(type(value) is int and value >= 0, "observation_missing", "Record the actual " + key)
    if kind == "generate":
        require(value > 0 and isinstance(result.get("outputs"), list) and len(result["outputs"]) == value,
                "generation_count_mismatch", "Returned image count differs from its observation")
        require(observation.get("image_calls_attempted") == 1 and observation.get("image_calls_completed") == 1,
                "generation_count_mismatch", "One submitted editor operation must report one pipeline invocation")
    return value


def _invoke(journal: Journal, spec: dict, kind: str, request: dict, callback, *, reserve: int = 1) -> dict:
    """One idempotent file handoff. Receipt recovery never calls callback again."""
    state, root = journal.state, journal.root
    stage_name = request.get("stage", kind)
    identity = f"{kind}-{stage_name}-r{state['round']:03d}"
    attempt = state["operation_attempts"].get(identity, 0)
    op_id = identity + f"-a{attempt:03d}"
    directory = root / "operations" / op_id
    request_path, result_path, done_path = directory / "request.json", directory / "result.json", directory / "done.json"
    key = "generations" if kind == "generate" else "compiler_calls" if kind == "compile" else "stage_calls"
    limit_key = "max_generations" if kind == "generate" else "max_compiler_calls" if kind == "compile" else "max_stage_calls"
    pending = state.get("pending")
    if pending:
        require(pending["operation_id"] == op_id, "pending_operation_mismatch", "An unresolved operation belongs to another phase")
    if done_path.is_file():
        done = read_json(done_path)
        require(done.get("request_sha256") == digest(request) and done.get("operation_id") == op_id
                and file_sha256(result_path) == done.get("result_sha256") and read_json(request_path) == request,
                "operation_receipt_modified", "Operation receipt or request/result bytes changed")
        result = read_json(result_path)
        if pending:
            value = deepcopy(state)
            charge = _actual_charge(kind, result)
            value["budget"][key] += charge - pending["reserved"]
            value["pending"] = None
            value["status"] = "running"
            value.pop("pause_reason", None)
            value["observations"].append({"operation_id": op_id, "kind": kind,
                                          "result": _reference(result_path, root), "charge": charge,
                                          "recovered": True})
            journal.commit(value, "operation_recovered", {"operation_id": op_id})
        return result
    if pending:
        raise _UnknownSubmission(op_id)
    if state["budget"][key] + reserve > spec["policy"][limit_key]:
        raise _BudgetExhausted(key)
    immutable_json(request_path, request)
    value = deepcopy(state)
    value["pending"] = {"operation_id": op_id, "identity": identity, "kind": kind,
                        "request": _reference(request_path, root), "request_sha256": digest(request),
                        "result_path": result_path.relative_to(root).as_posix(),
                        "done_path": done_path.relative_to(root).as_posix(), "budget_key": key, "reserved": reserve}
    value["budget"][key] += reserve
    value["status"] = "running"
    journal.commit(value, "operation_submitting", {"operation_id": op_id, "kind": kind})
    try:
        result = callback()
        require(isinstance(result, dict), "worker_result_invalid", "Workers must return one JSON object")
    except Exception as exc:
        # The caller cannot infer whether a remote image/VLM call ran. Even a
        # local import error may be wrapped by a transport; explicit reconcile
        # can release a proven-unsubmitted attempt, never an automatic retry.
        failure = {"code": getattr(exc, "code", type(exc).__name__), "message": str(exc), "at": now()}
        observation = getattr(exc, "observation", None)
        native_output = getattr(exc, "native_output", None)
        if observation is not None:
            failure["observation"] = observation
        if native_output is not None:
            failure["native_output"] = native_output
        if getattr(exc, "worker_job_dir", None) is not None:
            failure["worker_job_dir"] = str(exc.worker_job_dir)
        write_json(directory / "last_error.json", failure)
        completed = (kind != "generate" and isinstance(observation, dict)
                     and type(observation.get("calls_attempted")) is int
                     and observation["calls_attempted"] >= 0
                     and observation.get("calls_completed") == observation["calls_attempted"])
        if not completed:
            raise _UnknownSubmission(op_id) from exc
        # A malformed PE/VGL result can be a confirmed completed call. Preserve
        # its raw output and charge it; do not call the compiler again or label
        # a known parser failure as an unknown remote submission.
        result = {"error": {"code": failure["code"], "message": failure["message"]},
                  "observation": observation, "native_output": native_output}
    immutable_json(result_path, result)
    immutable_json(done_path, {"schema_version": "hre_operation_done_v3", "operation_id": op_id,
                              "request_sha256": digest(request), "result_sha256": file_sha256(result_path),
                              "completed_at": now()})
    charge = _actual_charge(kind, result)
    value = deepcopy(journal.state)
    value["budget"][key] += charge - value["pending"]["reserved"]
    value["pending"] = None
    value["observations"].append({"operation_id": op_id, "kind": kind,
                                  "result": _reference(result_path, root), "charge": charge, "recovered": False})
    journal.commit(value, "operation_completed", {"operation_id": op_id, "kind": kind})
    if value["budget"][key] > spec["policy"][limit_key]:
        # Keep all result files; the run may report an explicit budget violation.
        value = deepcopy(journal.state)
        value.setdefault("deviations", []).append({"code": "budget_exceeded", "kind": key,
                                                   "observed": value["budget"][key], "maximum": spec["policy"][limit_key]})
        journal.commit(value, "budget_exceeded", {"kind": key})
    return result


def _stage_request(spec: dict, state: dict, stage: str, context: dict,
                   candidate: dict | None = None) -> dict:
    inputs = deepcopy(state["inputs"])
    if candidate:
        inputs.append({**deepcopy(candidate["delivered"]), "role": "candidate"})
    request = {"schema_version": "hre_stage_request_v3", "stage": stage,
               "task_mode": spec["task_mode"], "brief": spec["brief"],
               "inputs": inputs, "canvas": state["canvas"], "context": context}
    request["stage_template"] = {"version": TEMPLATE_VERSION, "instruction": stage_instruction(request),
                                 "response_schema": deepcopy(SCHEMAS[stage])}
    request["request_id"] = digest(request)
    return request


def _stage(journal: Journal, spec: dict, config: dict, request: dict, stage_fn) -> dict:
    if stage_fn is None:
        require(isinstance(config.get("stage"), dict), "stage_endpoint_required", "Configure the actual stage VLM endpoint")
        endpoint = config["stage"]
        require(isinstance(endpoint.get("base_url"), str) and isinstance(endpoint.get("model"), str)
                and endpoint["model"].strip(), "stage_endpoint_required", "Configure stage.base_url and stage.model")
        parsed = urlsplit(endpoint["base_url"])
        require(parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username
                and not parsed.password and not parsed.query and not parsed.fragment,
                "stage_endpoint_required", "Stage endpoint must be HTTP(S) without embedded credentials/query")
    result = _invoke(journal, spec, "stage", request,
                     lambda: stage_fn(request) if stage_fn else run_stage(request, config["stage"]))
    require(journal.state["budget"]["stage_calls"] <= spec["policy"]["max_stage_calls"],
            "stage_budget_exceeded", "The stage worker exceeded its frozen call budget")
    if result.get("error"):
        error = result["error"]
        raise HREError("stage_error", str(error.get("code", "unknown")) + ": " + str(error.get("message", "")))
    require(isinstance(result.get("payload"), dict), "stage_payload_invalid", "A stage result must contain a payload")
    validate_payload(request["stage"], result["payload"], request)
    return result


def _get_round(state: dict) -> dict:
    matches = [record for record in state["rounds"] if record["round"] == state["round"]]
    require(len(matches) == 1, "round_missing", "Current round record is missing")
    return matches[0]


def _accepted(candidate: dict, spec: dict) -> bool:
    verification = candidate.get("verification")
    return bool(verification and candidate.get("geometry_valid", False)
                and verification["verdict"] == "accept" and verification["preservation"] == "pass"
                and verification["task_progress"] == "improved"
                and verification["confidence"] >= spec.get("evaluation", {}).get("minimum_confidence", 0.7))


def _finish(journal: Journal, spec: dict, reason: str, *, failed: bool = False) -> dict:
    value = deepcopy(journal.state)
    candidates = value["candidates"]
    for candidate in candidates:
        _asset(candidate["native"])
        _asset(candidate["delivered"])
    deliverable = [candidate for candidate in candidates if candidate.get("geometry_valid", False)
                   and candidate.get("delivery_status") != "invalid"]
    accepted = [candidate for candidate in deliverable if _accepted(candidate, spec)]
    if accepted:
        selected, kind = accepted[0], "candidate_accepted"
    elif deliverable:
        def rank(candidate):
            verification = candidate.get("verification") or {}
            return (int(candidate.get("geometry_valid", False)),
                    {"pass": 2, "uncertain": 1, "fail": 0}.get(verification.get("preservation"), -1),
                    {"improved": 3, "unchanged": 2, "uncertain": 1, "worse": 0}.get(verification.get("task_progress"), -1),
                    verification.get("confidence", -1), -candidate["round"], -candidate["provider_order"])
        selected, kind = max(deliverable, key=rank), "candidate_unaccepted"
    else:
        selected, kind = None, "source_baseline"
    asset = selected["delivered"] if selected else value["inputs"][0]
    _asset(asset)
    value.update(status="failed" if failed else "completed", phase="finished", pending=None,
                 terminal_reason=reason, success=bool(accepted) and not failed,
                 selected_kind=kind, selected_candidate_id=selected["candidate_id"] if selected else None,
                 selected_output=deepcopy(asset), quality_status="accepted" if accepted and not failed else "quality_not_met")
    value.pop("pause_reason", None)
    value.pop("ready_after", None)
    return journal.commit(value, "finished", {"reason": reason, "selected_kind": kind})


def _initial_context(state: dict, root: Path, regions: list[dict] | None = None) -> dict:
    diagnosis = _read_ref(root, state["artifacts"]["diagnosis"])["payload"] if "diagnosis" in state["artifacts"] else None
    evidence = _read_ref(root, state["artifacts"]["evidence"]) if "evidence" in state["artifacts"] else None
    return {"diagnosis": diagnosis, "evidence": evidence, "regions": deepcopy(regions or []),
            "available_evidence_refs": evidence_refs(state["inputs"], diagnosis, evidence)}


def run_case(root: Path, *, stage_fn=None, compile_fn=None, execute_fn=None,
             max_steps: int | None = None, stop_after: str | None = None) -> dict:
    """Run or resume a case. Unknown submissions remain paused until reconciled."""
    from .contracts import load_case
    from . import dispatch
    root = Path(root).resolve()
    require(max_steps is None or (type(max_steps) is int and max_steps > 0), "invalid_steps", "max_steps must be positive")
    require(stop_after in {None, "compose", "condition"}, "invalid_stop_stage", "Use compose, condition or no stage cutoff")
    with case_lock(root):
        spec, config, loaded = load_case(root)
        threshold = spec.get("evaluation", {}).get("minimum_confidence", 0.7)
        require(type(threshold) in {int, float} and math.isfinite(threshold) and 0 <= threshold <= 1,
                "evaluation_invalid", "minimum_confidence must be a finite number in [0,1]")
        if max_steps is None:
            max_steps = 16 + 10 * spec["policy"]["max_generations"]
        journal = Journal(root, loaded)
        if journal.state.get("status") in {"completed", "failed", "cancelled"}:
            for candidate in journal.state.get("candidates", []):
                _asset(candidate["native"]); _asset(candidate["delivered"])
            return journal.state
        initialized = _initialize(journal.state)
        if initialized != journal.state:
            journal.commit(initialized, "runner_initialized", {})
        model = config["models"][spec["profile_id"]]
        compiler_config, editor_config = model["compiler"], model["editor"]
        compile_fn = compile_fn or dispatch.compile_condition
        execute_fn = execute_fn or dispatch.generate
        for _ in range(max_steps):
            state = journal.state
            if state.get("status") in {"completed", "failed", "cancelled"}:
                break
            if state.get("status") == "paused" and not state.get("pending"):
                break
            phase = state["phase"]
            if ((stop_after == "compose" and phase == "condition")
                    or (stop_after == "condition" and phase == "execute")):
                if state.get("status") != "ready" or state.get("ready_after") != stop_after:
                    value = deepcopy(state)
                    value.update(status="ready", ready_after=stop_after)
                    journal.commit(value, "prepared_without_generation", {"stop_after": stop_after})
                break
            try:
                if phase == "start":
                    value = deepcopy(state)
                    value["status"] = "running"
                    if spec["strategy"] == "native":
                        value["phase"] = "condition"
                    elif spec.get("shared_intent"):
                        source = Path(spec["shared_intent"])
                        intent = import_shared_intent(source, spec, state)
                        imported = read_json(source)
                        value["intent"] = intent
                        value["artifacts"]["shared_intent"] = _put(root, "artifacts/shared_intent.json", imported)
                        planning = imported.get("planning", {})
                        if planning.get("diagnosis") is not None:
                            value["artifacts"]["diagnosis"] = _put(root, "artifacts/diagnosis.json", {
                                "payload": planning["diagnosis"], "observation": {"calls_attempted": 0, "calls_completed": 0,
                                    "kind": "frozen_planning_import", "origin": imported.get("provenance")}})
                        if planning.get("evidence") is not None:
                            value["artifacts"]["evidence"] = _put(root, "artifacts/evidence.json", planning["evidence"])
                        value["phase"] = "condition"
                        value["planning_origin"] = {"kind": "imported", "path": str(source), "sha256": file_sha256(source)}
                    else:
                        value["phase"] = "diagnose"
                    journal.commit(value, "started", {})
                elif phase == "diagnose":
                    context = {"available_tools": ["basic_statistics"], "regions": deepcopy(spec.get("regions", [])),
                               "available_evidence_refs": evidence_refs(state["inputs"])}
                    request = _stage_request(spec, state, "diagnose", context)
                    result = _stage(journal, spec, config, request, stage_fn)
                    value = deepcopy(journal.state)
                    value["artifacts"]["diagnosis"] = _put(root, "artifacts/diagnosis.json", result)
                    value["phase"] = "evidence"
                    journal.commit(value, "diagnosed", {})
                    if not result["payload"]["findings"]:
                        _finish(journal, spec, "no_supported_target")
                elif phase == "evidence":
                    diagnosis = _read_ref(root, state["artifacts"]["diagnosis"])["payload"]
                    result = collect_basic_evidence(state["inputs"], requested="basic_statistics" in diagnosis["tool_requests"],
                                                    regions=spec.get("regions", []))
                    value = deepcopy(state)
                    value["artifacts"]["evidence"] = _put(root, "artifacts/evidence.json", result)
                    value["phase"] = "compose"
                    journal.commit(value, "evidence_collected", {})
                elif phase == "compose":
                    request = _stage_request(spec, state, "compose", _initial_context(state, root, spec.get("regions", [])))
                    result = _stage(journal, spec, config, request, stage_fn)
                    value = deepcopy(journal.state)
                    value["artifacts"]["composition"] = _put(root, "artifacts/composition.json", result)
                    value["intent"] = result["payload"]
                    artifact = shared_intent_artifact(spec, value, value["intent"],
                                                     {"case_id": spec["case_id"], "composition": value["artifacts"]["composition"]},
                                                     {key: _initial_context(value, root)[key] for key in ("diagnosis", "evidence")})
                    value["artifacts"]["shared_intent"] = _put(root, "artifacts/shared_intent.json", artifact)
                    value["phase"] = "condition"
                    journal.commit(value, "intent_accepted", {"intent_sha256": digest(value["intent"])})
                elif phase == "condition":
                    if not any(record["round"] == state["round"] for record in state["rounds"]):
                        value = deepcopy(state)
                        value["rounds"].append({"round": state["round"], "seed": spec["policy"]["seed_schedule"][state["round"]],
                                                "intent_sha256": digest(state["intent"]) if state["intent"] else None})
                        journal.commit(value, "round_started", {"round": state["round"]})
                        state = journal.state
                    round_dir = root / "rounds" / f"{state['round']:03d}"
                    prepared_path = round_dir / "prepared_request.json"
                    if _get_round(state).get("request"):
                        request = _read_ref(root, _get_round(state)["request"])
                    else:
                        original = {"schema_version": "hre_model_request_v3", "profile_id": spec["profile_id"],
                                    "task_mode": spec["task_mode"], "strategy": spec["strategy"], "brief": spec["brief"],
                                    "intent": deepcopy(state["intent"]), "inputs": deepcopy(state["inputs"]),
                                    "canvas": deepcopy(state["canvas"]), "spatial": deepcopy(spec["spatial"]),
                                    "seed": spec["policy"]["seed_schedule"][state["round"]]}
                        original["request_id"] = digest(original)
                        immutable_json(round_dir / "original_request.json", original)
                        request = dispatch.prepare_request(original, spec, round_dir)
                        immutable_json(prepared_path, request)
                        value = deepcopy(journal.state)
                        _get_round(value)["request"] = _reference(prepared_path, root)
                        _get_round(value)["original_request"] = _reference(round_dir / "original_request.json", root)
                        journal.commit(value, "request_prepared", {"round": state["round"]})
                        state = journal.state
                    require(all(request.get(key) == spec[key] for key in ("profile_id", "task_mode", "strategy", "brief"))
                            and request.get("intent") == state["intent"]
                            and request.get("seed") == spec["policy"]["seed_schedule"][state["round"]]
                            and request.get("original_input_sha256") == {asset["role"]: asset["sha256"] for asset in state["inputs"]},
                            "prepared_request_mismatch", "Prepared request differs from this round's frozen source, intent or policy")
                    for asset in request["inputs"]:
                        _asset(asset)
                    if state["round"] > 0 and spec["policy"]["mode"] == "resample":
                        previous = state["rounds"][0]
                        result = deepcopy(_read_ref(root, previous["condition"]))
                        result["cache_origin"] = {"case_id": state["case_id"], "round": 0,
                                                  "condition": deepcopy(previous["condition"]), "policy": "fixed_prompt_resample"}
                        result["observation"] = {"compiler_id": "accepted_condition_cache", "calls_attempted": 0,
                                                 "calls_completed": 0, "origin_observation": deepcopy(result["observation"])}
                    else:
                        compiler_request = deepcopy(request)
                        compiler_request["execution_attempt"] = state["operation_attempts"].get(f"compile-compile-r{state['round']:03d}", 0)
                        result = _invoke(journal, spec, "compile", compiler_request,
                                         lambda: compile_fn(compiler_request, compiler_config),
                                         reserve=0 if compiler_config.get("backend") == "direct" else 1)
                    if result.get("error"):
                        raise HREError("compiler_error", str(result["error"].get("code", "unknown"))
                                       + ": " + str(result["error"].get("message", "")))
                    require(isinstance(result.get("text"), str) and bool(result["text"].strip())
                            and isinstance(result.get("condition_kind"), str), "condition_invalid", "Compiler returned no executable native condition")
                    value = deepcopy(journal.state)
                    record = _get_round(value)
                    record["request"] = _reference(prepared_path, root)
                    record["condition"] = _put(root, f"rounds/{state['round']:03d}/condition.json", result)
                    value["phase"] = "execute"
                    journal.commit(value, "condition_accepted", {"round": state["round"], "cached": "cache_origin" in result})
                    if value["budget"]["compiler_calls"] > spec["policy"]["max_compiler_calls"]:
                        _finish(journal, spec, "compiler_budget_exceeded", failed=True)
                elif phase == "execute":
                    record = _get_round(state)
                    request, condition = _read_ref(root, record["request"]), _read_ref(root, record["condition"])
                    round_dir = root / "rounds" / f"{state['round']:03d}"
                    generation_attempt = state["operation_attempts"].get(f"generate-generate-r{state['round']:03d}", 0)
                    output_dir = round_dir / "native" / f"attempt_{generation_attempt:03d}"
                    execution_request = {"request": request, "condition_sha256": digest(condition),
                                         "editor_config_sha256": digest(editor_config), "output_dir": str(output_dir)}
                    result = _invoke(journal, spec, "generate", execution_request,
                                     lambda: execute_fn(request, condition, editor_config, output_dir))
                    for asset in result["outputs"]:
                        _asset(asset)
                    generated_ref = _put(root, f"rounds/{state['round']:03d}/generation.json", result)
                    value = deepcopy(journal.state)
                    _get_round(value)["generation"] = generated_ref
                    _get_round(value)["native_outputs"] = deepcopy(result["outputs"])
                    journal.commit(value, "native_outputs_preserved", {"round": state["round"]})
                    delivered_path = round_dir / "delivery.json"
                    if delivered_path.exists():
                        delivered = read_json(delivered_path)
                    else:
                        try:
                            delivered = dispatch.deliver_outputs(result, request, spec, round_dir / "delivered")
                        except HREError as exc:
                            # Show the actual model products even when their
                            # geometry/alpha contract prevents a deliverable.
                            value = deepcopy(journal.state)
                            ids = []
                            for order, native in enumerate(result["outputs"]):
                                identity = f"r{state['round']:03d}-p{order:03d}"
                                ids.append(identity)
                                value["candidates"].append({"candidate_id": identity, "round": state["round"],
                                    "provider_order": order, "native": deepcopy(native), "delivered": deepcopy(native),
                                    "geometry_valid": False, "verification": None, "accepted": False,
                                    "delivery_status": "invalid", "delivery_error": {"code": exc.code, "message": str(exc)}})
                            _get_round(value)["candidate_ids"] = ids
                            journal.commit(value, "native_outputs_not_deliverable", {"code": exc.code})
                            raise
                        immutable_json(delivered_path, delivered)
                    assets = delivered.get("deliveries", result["outputs"])
                    require(len(assets) == len(result["outputs"]), "delivery_count_mismatch", "All native outputs must be retained")
                    value = deepcopy(journal.state)
                    record = _get_round(value)
                    record["generation"] = generated_ref
                    record["delivery"] = _reference(delivered_path, root)
                    ids = []
                    for order, (native, output) in enumerate(zip(result["outputs"], assets)):
                        _asset(output)
                        identity = f"r{state['round']:03d}-p{order:03d}"
                        ids.append(identity)
                        require(not any(c["candidate_id"] == identity for c in value["candidates"]), "candidate_duplicate", "Candidate was already imported")
                        value["candidates"].append({"candidate_id": identity, "round": state["round"], "provider_order": order,
                                                     "native": deepcopy(native), "delivered": deepcopy(output),
                                                     "geometry_valid": (output["width"], output["height"]) == (state["canvas"]["width"], state["canvas"]["height"]),
                                                     "verification": None, "accepted": False})
                    record["candidate_ids"] = ids
                    value["phase"] = "verify"
                    journal.commit(value, "images_imported", {"candidate_ids": ids})
                    if len(assets) != 1 or value["budget"]["generations"] > spec["policy"]["max_generations"]:
                        _finish(journal, spec, "unexpected_generation_count", failed=True)
                elif phase == "verify":
                    candidate = next(c for c in state["candidates"] if c["candidate_id"] == _get_round(state)["candidate_ids"][0])
                    context = {"evaluation": deepcopy(spec.get("evaluation", {})), "regions": deepcopy(spec.get("regions", [])),
                               "geometry_valid": candidate["geometry_valid"],
                               "available_evidence_refs": evidence_refs(state["inputs"]) + ["candidate"]}
                    request = _stage_request(spec, state, "verify", context, candidate)
                    result = _stage(journal, spec, config, request, stage_fn)
                    value = deepcopy(journal.state)
                    current = next(c for c in value["candidates"] if c["candidate_id"] == candidate["candidate_id"])
                    current["verification"] = result["payload"]
                    current["accepted"] = _accepted(current, spec)
                    _get_round(value)["verification"] = _put(root, f"rounds/{state['round']:03d}/verification.json", result)
                    journal.commit(value, "verified", {"candidate_id": candidate["candidate_id"], "accepted": current["accepted"]})
                    policy = spec["policy"]["mode"]
                    exhausted = value["budget"]["generations"] >= spec["policy"]["max_generations"]
                    if policy == "single" or exhausted or (policy == "feedback" and current["accepted"]):
                        _finish(journal, spec, "accepted" if current["accepted"] else "generation_budget_complete")
                    elif policy == "resample":
                        value = deepcopy(journal.state)
                        value["round"] += 1; value["phase"] = "condition"
                        journal.commit(value, "resample_requested", {})
                    else:
                        verification = result["payload"]
                        actionable = [issue for issue in verification["issues"] if issue["suggested_change"]
                                      and issue["kind"] not in {"uncertain", "execution_contract_violation"}]
                        if verification["verdict"] == "uncertain" or not actionable:
                            _finish(journal, spec, "no_supported_refinement")
                        else:
                            value = deepcopy(journal.state); value["phase"] = "refine"
                            journal.commit(value, "refinement_requested", {})
                elif phase == "refine":
                    candidate = next(c for c in state["candidates"] if c["candidate_id"] == _get_round(state)["candidate_ids"][0])
                    context = _initial_context(state, root, spec.get("regions", []))
                    verification = candidate["verification"]
                    refs = evidence_refs(state["inputs"], context["diagnosis"], context["evidence"],
                                         round_index=state["round"], verification=verification)
                    refs += ["candidate"] + state["intent"].get("feedback_refs", [])
                    for target in state["intent"]["targets"] + state["intent"]["region_relations"]:
                        refs += target["evidence_refs"]
                    context.update(previous_intent=state["intent"], previous_intent_hash=digest(state["intent"]),
                                   verification=verification, available_evidence_refs=sorted(set(refs)),
                                   actionable_feedback_refs=[f"verification:{state['round']}:{issue['id']}" for issue in verification["issues"]
                                                             if issue["suggested_change"] and issue["kind"] not in {"uncertain", "execution_contract_violation"}])
                    request = _stage_request(spec, state, "refine", context, candidate)
                    result = _stage(journal, spec, config, request, stage_fn)
                    value = deepcopy(journal.state)
                    _get_round(value)["refinement"] = _put(root, f"rounds/{state['round']:03d}/refinement.json", result)
                    journal.commit(value, "refinement_observed", {})
                    payload = result["payload"]
                    if payload["action"] == "stop":
                        _finish(journal, spec, "refinement_stopped")
                    else:
                        changed = any(payload["intent"][key] != state["intent"][key]
                                      for key in ("targets", "region_relations", "protected_content", "uncertainties"))
                        if not changed:
                            _finish(journal, spec, "no_supported_prompt_change")
                        else:
                            value = deepcopy(journal.state)
                            value["intent"] = payload["intent"]
                            value["round"] += 1; value["phase"] = "condition"
                            journal.commit(value, "refined_intent_accepted", {"intent_sha256": digest(value["intent"])})
                else:
                    raise HREError("phase_unknown", str(phase))
            except _UnknownSubmission as exc:
                value = deepcopy(journal.state)
                value.update(status="paused", pause_reason="submission_unknown", last_error={"code": exc.code, "message": str(exc)})
                if value.get("pending"):
                    error_path = root / "operations" / value["pending"]["operation_id"] / "last_error.json"
                    if error_path.exists():
                        value["last_error"]["worker_error"] = _reference(error_path, root)
                journal.commit(value, "submission_unknown", {})
                break
            except _BudgetExhausted:
                _finish(journal, spec, "call_budget_exhausted")
                break
            except HREError as exc:
                value = deepcopy(journal.state)
                value["last_error"] = {"code": exc.code, "message": str(exc)}
                if value.get("pending"):
                    value.update(status="paused", pause_reason="operation_response_requires_review")
                    journal.commit(value, "operation_response_requires_review", {})
                else:
                    journal.commit(value, "run_error", {})
                    _finish(journal, spec, exc.code, failed=True)
                break
        return journal.state


def _reconciled_bindings(result: dict, kind: str, request: dict, selected_config: dict | None,
                         condition: dict | None, output_dir: Path | None) -> None:
    """Require existing production bindings; an unbound response cannot be imported.

    Semantic request bindings deliberately permit seed-only resampling. Recovery
    additionally binds the complete submitted request and actual output directory,
    so an earlier seed, source, condition or explicit retry cannot stand in for
    the pending operation.
    """
    from . import dispatch
    if kind == "stage":
        expected = {"stage_request_id": request["request_id"], "stage_request_sha256": digest(request)}
        bindings = result.get("observation")
    elif kind == "compile":
        require(isinstance(result.get("text"), str) and result["text"].strip(),
                "reconciliation_binding", "A recovered compiler result must contain its accepted native text")
        expected = {"schema_version": "hre_condition_v3", "profile_id": request["profile_id"],
                    "request_binding_sha256": dispatch.request_binding(request),
                    "compilation_request_sha256": digest(request), "compiler_config_sha256": digest(selected_config),
                    "text_sha256": sha256_bytes(result["text"].encode())}
        bindings = result
    else:
        expected = {"request_binding_sha256": dispatch.request_binding(request),
                    "execution_request_sha256": digest(request), "editor_config_sha256": digest(selected_config),
                    "condition_sha256": digest(condition), "condition_text_sha256": condition["text_sha256"],
                    "output_directory": str(output_dir)}
        bindings = result.get("observation")
    require(isinstance(bindings, dict), "reconciliation_binding", "The actual response has no bound receipt")
    for key, value in expected.items():
        require(key in bindings and bindings[key] == value, "reconciliation_binding",
                "Recovered " + kind + " response does not match the pending " + key)
    for asset in request["inputs"]:
        _asset(asset)
    if kind == "stage":
        if result.get("error") is not None:
            error = result["error"]
            require(isinstance(error, dict) and isinstance(error.get("code"), str)
                    and isinstance(error.get("message"), str), "reconciliation_result_invalid", "Invalid stage error receipt")
        else:
            validate_payload(request["stage"], result.get("payload"), request)
    if kind == "generate":
        require(isinstance(result.get("outputs"), list) and result["outputs"],
                "reconciliation_result_invalid", "Recovered generation has no native outputs")
        for asset in result["outputs"]:
            require(isinstance(asset, dict) and isinstance(asset.get("path"), str)
                    and isinstance(asset.get("sha256"), str) and type(asset.get("width")) is int
                    and type(asset.get("height")) is int, "reconciliation_result_invalid", "Invalid native output record")
            path = Path(asset["path"])
            require(path.is_absolute() and path.resolve().is_relative_to(output_dir),
                    "reconciliation_binding", "Recovered native output is outside the pending execution directory")
            _asset(asset)


def _worker_response(root: Path, spec: dict, config: dict, state: dict, response_path: Path,
                      result: dict) -> tuple[dict, dict | None]:
    """Verify a sealed adapter result or a matching native worker job envelope."""
    from . import dispatch
    require(isinstance(result, dict), "reconciliation_result_invalid", "Provide one actual response object")
    pending = state["pending"]
    kind = pending["kind"]
    require(kind in {"stage", "compile", "generate"}, "reconciliation_worker_kind", "Unknown pending operation kind")
    operation_request = _read_ref(root, pending["request"])
    require(digest(operation_request) == pending["request_sha256"], "reconciliation_binding", "Pending operation request hash differs")
    model = config["models"][spec["profile_id"]]
    condition, output_dir = None, None
    if kind == "stage":
        request, selected_config = operation_request, config.get("stage")
    elif kind == "compile":
        request, selected_config = operation_request, model["compiler"]
    else:
        request, selected_config = operation_request["request"], model["editor"]
        condition = _read_ref(root, _get_round(state)["condition"])
        require(digest(condition) == operation_request["condition_sha256"]
                and digest(selected_config) == operation_request["editor_config_sha256"],
                "reconciliation_binding", "The editor condition/config differs from the pending operation")
        require(isinstance(operation_request.get("output_dir"), str), "reconciliation_binding",
                "The pending operation has no frozen output directory")
        output_dir = Path(operation_request["output_dir"])
        require(output_dir.is_absolute() and output_dir.resolve().is_relative_to(root),
                "reconciliation_binding", "The pending output directory escapes its case")
        output_dir = output_dir.resolve()
    provenance = {"response_path": str(response_path), "response_sha256": file_sha256(response_path)}
    if "ok" not in result and "request_sha256" not in result:
        _reconciled_bindings(result, kind, request, selected_config, condition, output_dir)
        provenance["format"] = "verified_sealed_adapter_result"
        return result, provenance
    require(kind in {"compile", "generate"}, "reconciliation_worker_kind", "Stage recovery requires its bound stage response")
    local_config = {key: value for key, value in selected_config.items() if key != "worker"}
    expected = {"schema_version": "hre_native_job_v3", "operation": kind,
                "request": request, "config": local_config}
    if kind == "generate":
        expected.update(condition=condition, output_dir=operation_request["output_dir"])
    expected_hash = digest(expected)
    require(type(result.get("ok")) is bool and result["request_sha256"] == expected_hash,
            "reconciliation_worker_binding", "Worker result belongs to another frozen native job")
    marker_path = response_path.parent / "job.json"
    if marker_path.is_file():
        marker = read_json(marker_path)
        require(marker.get("request_sha256") == expected_hash
                and (not marker.get("result_sha256") or marker["result_sha256"] == file_sha256(response_path)),
                "reconciliation_worker_binding", "Worker journal/result hash differs")
    provenance.update(format="verified_native_worker_envelope", worker_request_sha256=expected_hash)
    if not result["ok"]:
        error = result.get("error", {})
        require(isinstance(error, dict), "reconciliation_worker_error", "Invalid worker error envelope")
        return {"error": {"code": error.get("code", "worker_error"), "message": error.get("message", "Worker failed")},
                "observation": error.get("observation"), "native_output": error.get("native_output")}, provenance
    payload = result.get("payload")
    require(isinstance(payload, dict), "reconciliation_worker_payload", "Worker returned no adapter payload")
    if kind == "compile":
        payload = dispatch.seal_condition(request, selected_config, payload)
    else:
        payload = dispatch.seal_generation(request, condition, selected_config, payload, output_dir=output_dir)
    _reconciled_bindings(payload, kind, request, selected_config, condition, output_dir)
    return payload, provenance


def reconcile(root: Path, decision: str, *, result_path: Path | None = None,
              evidence: str, operation_id: str | None = None) -> dict:
    """Explicitly reconcile an uncertain call; never silently retry a generation.

    confirmed_result imports a real worker response, not an invented success.
    not_submitted releases the reserved attempt only with an operator's recorded
    evidence. consumed_failed keeps its budget charged and permits a new attempt.
    stop preserves the unresolved reservation and all native files for audit.
    """
    from .contracts import load_case
    root = Path(root).resolve()
    require(isinstance(evidence, str) and bool(evidence.strip()), "reconciliation_evidence_required", "Explain the observed submission outcome")
    require(decision in {"confirmed_result", "not_submitted", "consumed_failed", "stop"}, "reconciliation_invalid", str(decision))
    with case_lock(root):
        spec, config, loaded = load_case(root)
        journal = Journal(root, loaded)
        state = deepcopy(journal.state)
        pending = state.get("pending")
        require(pending is not None and state.get("status") == "paused", "reconciliation_not_waiting", "Case has no unresolved submission")
        require(operation_id is None or operation_id == pending["operation_id"], "reconciliation_binding", "Another operation is pending")
        record = {"operation_id": pending["operation_id"], "decision": decision, "evidence": evidence, "at": now()}
        if decision == "confirmed_result":
            require(result_path is not None, "reconciliation_result_missing", "Provide the actual worker response JSON")
            response_path = Path(result_path).resolve()
            result, worker_provenance = _worker_response(root, spec, config, state, response_path, read_json(response_path))
            if worker_provenance:
                record["worker_response"] = worker_provenance
            _actual_charge(pending["kind"], result)
            destination, done = root / pending["result_path"], root / pending["done_path"]
            if destination.exists():
                require(read_json(destination) == result, "reconciliation_result_conflict", "Preserved result differs; do not overwrite evidence")
            immutable_json(destination, result)
            immutable_json(done, {"schema_version": "hre_operation_done_v3", "operation_id": pending["operation_id"],
                                  "request_sha256": pending["request_sha256"], "result_sha256": file_sha256(destination),
                                  "completed_at": now(), "reconciled": True})
            record["result_sha256"] = file_sha256(destination)
            state["status"] = "running"
            state.pop("pause_reason", None)
        elif decision == "stop":
            state.update(status="cancelled", terminal_reason="operator_stop_unknown_submission", success=False)
        else:
            if decision == "not_submitted":
                state["budget"][pending["budget_key"]] -= pending["reserved"]
            state["operation_attempts"][pending["identity"]] = state["operation_attempts"].get(pending["identity"], 0) + 1
            state["pending"] = None
            state["status"] = "running"
            state.pop("pause_reason", None)
        state.setdefault("reconciliations", []).append(record)
        return journal.commit(state, "reconciled", record)
