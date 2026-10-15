"""Only this controller commits state. CLI, UI and both transports share it."""
import json
import uuid
from pathlib import Path

from PIL import Image

from .cases import create_case_locked
from .models import GateResult, ImportResult, NextAction, Request, Response
from .protocol import parse_time, strict_loads, validate_asset, validate_response, validate_schema
from .storage import CasePaths, atomic_write, commit, json_bytes, now, read_json, recover_case, sha256_bytes, sha256_file, transactions, write_json, writer_lock
from .tasks import issue_task
from .workflow import decide, select_final

STATUS_MESSAGES = {
    "WAIT_DIAGNOSIS": "在独立 Diagnoser 会话中发送当前任务和原图，导入返回 JSON。",
    "WAIT_EVIDENCE": "登记诊断计划中尚缺的工具证据。",
    "WAIT_COMPOSITION": "在 Composer 会话中发送当前任务、原图及证据地图，导入 JSON。",
    "WAIT_EXECUTION": "新建 ChatGPT 图像编辑会话，只发送原图和当前指令。保存第一张完整图片并提交。",
    "WAIT_VERIFICATION": "在独立 Verifier 会话中发送原图和全部输出，导入 JSON。",
    "WAIT_REFINEMENT": "在 Composer/Refiner 会话中发送当前完整任务，导入新的指令 JSON。",
    "FINISHED": "流程已终止，可导出审计报告。",
}


def history(case):
    diagnosis = None
    evidence = {}
    rounds = {}
    for tx in transactions(case):
        details = tx["event"]["details"]
        if tx["event"]["type"] == "tool_registered":
            evidence[details["manifest"]["tool_id"]] = details["manifest"]
        response = details.get("response")
        if not response or response["status"] != "ok":
            continue
        role, payload, number = response["role"], response["payload"], response["round"]
        if role == "diagnose":
            diagnosis = payload
        elif role in ("compose", "refine"):
            target_round = number + 1 if role == "refine" else number
            rounds.setdefault(target_round, {"round": target_round})["composition"] = payload
        elif role == "execute":
            record = rounds.setdefault(number, {"round": number})
            record.update(details["round_record"])
        elif role == "verify":
            rounds.setdefault(number, {"round": number})["verification"] = payload
    return {"diagnosis": diagnosis, "evidence": list(evidence.values()), "rounds": [rounds[n] for n in sorted(rounds)]}


class Controller:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def case(self, case_id):
        return CasePaths(case_id, self.root)

    def list_cases(self):
        result = []
        for path in sorted((self.root / "cases").glob("*/state.json")):
            try:
                result.append(self.inspect(path.parent.name).model_dump())
            except (ValueError, OSError) as exc:
                result.append({"case_id": path.parent.name, "workflow_status": "UNKNOWN", "operation_status": "blocked", "block_reason": str(exc)})
        return result

    def inspect(self, case_id):
        with writer_lock(self.root):
            case = self.case(case_id)
            return self._reconcile(case, recover_case(case))

    def current_task(self, case_id):
        state = self.inspect(case_id)
        if not state.pending_task_id:
            return None
        return Request.model_validate(read_json(self.case(case_id).path(f"tasks/{state.pending_task_id}/request.json")))

    def new(self, source: Path, intent: str, config=None):
        with writer_lock(self.root):
            state = create_case_locked(self.root, source, intent, config or {})
            case = self.case(state.case_id)
            state.workflow_status = "WAIT_DIAGNOSIS"
            request = self._issue(case, state, "diagnose")
            return commit(case, state, "task_issued", {"task_id": request.task_id, "role": "diagnose"}, next_task=request)

    def _action(self, state, role=None):
        state.next_action = NextAction(code=state.workflow_status.lower(), message=STATUS_MESSAGES[state.workflow_status], required_artifacts=[t for t in state.required_tools if t not in state.received_tools] if state.workflow_status == "WAIT_EVIDENCE" else [], target_role=role)

    def _issue(self, case, state, role):
        hist = history(case)
        config = read_json(case.path("case_config.json"))
        context = {"statistics": {"mean_brightness": None, "input_width": read_json(case.path("input/metadata.json"))["width"], "input_height": read_json(case.path("input/metadata.json"))["height"]}, "diagnosis": hist["diagnosis"], "evidence": [e for e in hist["evidence"] if e["status"] == "ok" and e["tool_id"] in state.received_tools]}
        if role in ("compose", "refine"):
            self._freeze_evidence(case, state)
            context["unavailable_tools"] = self.unavailable_tools(state.case_id)
            context["excluded_tools"] = self.excluded_tools(state.case_id)
        valid_outputs = [r for r in hist["rounds"] if r.get("output_asset")]
        context["attempts"] = [{"index": r["round"] - 1, "round": r["round"], "task_id": r["task_id"], "image_sha256": r["output_asset"]["sha256"], "output_asset": r["output_asset"]} for r in valid_outputs]
        if role == "execute":
            if state.budget.consumed + state.budget.reserved >= state.budget.max_generations:
                raise ValueError("Generation budget exhausted")
            record = next(r for r in hist["rounds"] if r["round"] == state.round)
            context["instruction"] = record["composition"]["instruction"]
            context["instruction_sha256"] = sha256_bytes(context["instruction"].encode("utf-8"))
            state.budget.reserved += 1
        if role == "refine":
            last = valid_outputs[-1]
            context.update(previous_instruction=last["composition"]["instruction"], verification=last["verification"])
        if role == "verify":
            context["task_types"] = list(dict.fromkeys(r["composition"]["task_type"] for r in valid_outputs))
            context["measurements"] = {"geometry": [{"round": r["round"], "valid": r["valid_geometry"], "observations": r["geometry"]} for r in valid_outputs]}
        request = issue_task(case, state, role, context)
        state.pending_task_id = request.task_id
        self._action(state, role)
        return request

    def _accepted(self, case, task_id):
        for tx in transactions(case):
            if tx.get("accepted_response_sha256") and tx["event"]["details"].get("response", {}).get("task_id") == task_id:
                return tx["accepted_response_sha256"]
        return None

    def _repair_count(self, case, task_id):
        return sum(tx["event"]["type"] == "response_rejected" and tx["event"]["details"].get("task_id") == task_id and tx["event"]["details"].get("repairable", False) for tx in transactions(case))

    def _reject(self, case, state, task_id, raw: bytes, code, message, repairable=False):
        digest = sha256_bytes(raw)
        existing = [tx for tx in transactions(case) if tx["event"]["type"] == "response_rejected" and tx["event"]["details"].get("raw_sha256") == digest and tx["event"]["details"].get("task_id") == task_id]
        if existing:
            return ImportResult(accepted=False, code=code, message=message)
        prefix = f"quarantine/{task_id}_{digest}"
        atomic_write(case.path(prefix + ".raw"), raw)
        write_json(case.path(prefix + ".json"), {"code": code, "message": message, "at": now()})
        details = {"task_id": task_id, "raw_sha256": digest, "code": code, "message": message, "repairable": repairable}
        max_repairs = read_json(case.path("case_config.json"))["max_format_repairs"]
        if repairable and state.pending_task_id == task_id:
            request = Request.model_validate(read_json(case.path(f"tasks/{task_id}/request.json")))
            from .prompts import encoded, render_prompt
            rendered = render_prompt("format_repair", {"role": request.role, "validation_errors_json": encoded([message]), "raw_response": raw.decode("utf-8", errors="replace"), "payload_schema_json": encoded(read_json(case.path(f"snapshot/schemas/{request.payload_schema}")))}, case.path("snapshot"))
            atomic_write(case.path(f"tasks/{task_id}/format_repair.txt"), rendered.encode("utf-8"))
            if self._repair_count(case, task_id) > max_repairs - 1:
                state.operation_status = "blocked"
                state.block_reason = "format_repairs_exhausted: " + message
            state.next_action = NextAction(code="format_repair", message="同一任务 JSON 校验失败：" + message, required_artifacts=[], target_role=request.role)
        commit(case, state, "response_rejected", details)
        return ImportResult(accepted=False, code=code, message=message)

    def _finish(self, case, state, reason):
        hist = history(case)
        selection = select_final([r for r in hist["rounds"] if r.get("output_asset")])
        state.workflow_status = "FINISHED"
        state.pending_task_id = None
        state.workflow_completed = True
        state.terminal_reason = reason
        state.selected_round = selection.round
        state.restoration_success = selection.success if reason == "accepted" else False
        self._action(state)

    def _account_late_generation(self, case, state, request, response_raw, marker):
        """Validate a late execute result and account cost without advancing it."""
        if request.role != "execute":
            return state
        digest = sha256_bytes(response_raw)
        if any(tx["event"]["type"] == "late_generation_received" and tx["event"]["details"].get("response_sha256") == digest and tx["event"]["details"].get("task_id") == request.task_id for tx in transactions(case)):
            return state
        response = Response.model_validate(strict_loads(response_raw.decode("utf-8")))
        validate_response(request, response, case)
        if response.status != "ok":
            return state
        payload = response.payload
        assets = [payload["output_asset"], *payload["extra_assets"]]
        if payload["input_image_sha256"] != state.input_sha256 or payload["instruction_sha256"] != request.context["instruction_sha256"]:
            raise ValueError("Late editor input/instruction mismatch")
        if payload["actual_generations"] != len(assets):
            raise ValueError("Late generation count must include every provider output")
        listed = {a["path"]: a["sha256"] for a in marker["artifact_hashes"]}
        if len(listed) != len(assets) or listed != {a["path"]: a["sha256"] for a in assets}:
            raise ValueError("Late done assets mismatch")
        archived = []
        for asset in assets:
            if not asset["path"].startswith(f"tasks/{request.task_id}/"):
                raise ValueError("Late asset belongs to another task")
            validate_asset(case, asset)
            from .transport import image_observations
            image_observations(case.path(asset["path"]), case.path("input/canonical.png"), read_json(case.path("case_config.json")))
            target = f"quarantine/late_{request.task_id}/{digest}/{asset['sha256']}" + case.path(asset["path"]).suffix
            atomic_write(case.path(target), case.path(asset["path"]).read_bytes())
            archived.append(target)
        # An unaccepted issued task still owns its reservation. A conflict with
        # an already accepted task is additional sampling and owns no new slot.
        if not self._accepted(case, request.task_id):
            state.budget.reserved = max(0, state.budget.reserved - 1)
        state.budget.consumed += payload["actual_generations"]
        state.deviated = True
        return commit(case, state, "late_generation_received", {"task_id": request.task_id, "response_sha256": digest, "actual_generations": payload["actual_generations"], "archived_assets": archived, "extra_sampling": bool(self._accepted(case, request.task_id)) or state.budget.consumed > state.budget.max_generations})

    def _accept(self, case, done_path):
        state = recover_case(case)
        raw = done_path.read_bytes()
        task_id = done_path.parent.name
        try:
            marker = strict_loads(raw.decode("utf-8"))
            validate_schema("done.schema.json", marker, case.path("snapshot/schemas"))
            request = Request.model_validate(read_json(case.path(f"tasks/{task_id}/request.json")))
            if marker["task_id"] != task_id or marker["response_file"] != request.response_file or case.path(request.ready_marker) != done_path.resolve():
                raise ValueError("Completion marker identity mismatch")
            response_raw = case.path(marker["response_file"]).read_bytes()
            digest = sha256_bytes(response_raw)
            if digest != marker["response_sha256"]:
                raise ValueError("Completion response hash mismatch")
            accepted = self._accepted(case, task_id)
            if accepted == digest:
                return ImportResult(accepted=True, code="already_processed", message="响应已处理，不重复推进")
            if accepted:
                state = self._account_late_generation(case, state, request, response_raw, marker)
                return self._reject(case, state, task_id, response_raw, "conflict", "已接受任务的不同结果不能覆盖正式值")
            if state.pending_task_id != task_id:
                state = self._account_late_generation(case, state, request, response_raw, marker)
                return self._reject(case, state, task_id, response_raw, "stale_task", "旧任务不能改变当前状态")
            if state.operation_status != "active":
                return ImportResult(accepted=False, code="not_active", message="Case 已暂停或阻塞；保留结果等待继续")
            response = Response.model_validate(strict_loads(response_raw.decode("utf-8")))
            validate_response(request, response, case)
            if parse_time(marker["committed_at"]) < parse_time(response.provenance["completed_at"]):
                raise ValueError("done precedes response completion")
            assets = []
            if response.role == "execute" and response.status == "ok":
                assets = [response.payload["output_asset"], *response.payload["extra_assets"]]
            declared = {a["path"]: a["sha256"] for a in assets}
            listed = {a["path"]: a["sha256"] for a in marker["artifact_hashes"]}
            if len(listed) != len(marker["artifact_hashes"]) or declared != listed:
                raise ValueError("done assets must match payload exactly")
            for asset in assets:
                if not asset["path"].startswith(f"tasks/{task_id}/"):
                    raise ValueError("Output asset belongs to another task")
                validate_asset(case, asset)
            if response.status == "error":
                state.operation_status = "blocked"
                state.block_reason = response.error["message"]
                commit(case, state, "response_error", {"response": response.model_dump(), "raw_sha256": digest})
                return ImportResult(accepted=True, code="blocked", message=state.block_reason)
            hist = history(case)
            gates = GateResult()
            round_record = None
            payload = response.payload
            if response.role == "execute":
                if payload["input_image_sha256"] != state.input_sha256 or payload["instruction_sha256"] != request.context["instruction_sha256"]:
                    raise ValueError("Editor input/instruction hash mismatch")
                if payload["actual_generations"] != len(assets):
                    raise ValueError("Generation count must include all provider images")
                from .transport import image_observations
                observations = image_observations(case.path(payload["output_asset"]["path"]), case.path("input/canonical.png"), read_json(case.path("case_config.json")))
                round_record = {"round": state.round, "task_id": task_id, "output_asset": payload["output_asset"], "extra_assets": payload["extra_assets"], "pixel_sha256": observations["pixel_sha256"], "valid_geometry": observations["valid_geometry"], "valid_image_constraints": observations["valid_image_constraints"], "geometry": observations}
            elif response.role == "verify":
                from .workflow import _verification_semantics
                _verification_semantics(payload)
                outputs = [r for r in hist["rounds"] if r.get("output_asset")]
                best = payload["best_round"]
                valid_best = next((r for r in outputs if r["round"] == best + 1 and r["valid_geometry"]), None)
                if valid_best is None:
                    if self._repair_count(case, task_id) < read_json(case.path("case_config.json"))["max_format_repairs"]:
                        raise ValueError("best_round must refer to a displayed geometrically valid output")
                    payload = dict(payload)
                    payload["best_round"] = next((r["round"] - 1 for r in outputs if r["valid_geometry"]), -1)
                    # Preserve the raw invalid index; fallback is explicitly only an unpassed candidate.
                    if payload["best_round"] == -1:
                        payload["best_round"] = 0
                    payload["verdict"] = "incorrect"
                    payload["needs_redo"] = False
                latest = outputs[-1]
                gates = GateResult(valid_geometry=latest["valid_geometry"], observations={"valid_image_constraints": latest.get("valid_image_constraints", True), "duplicate_output": any(r["pixel_sha256"] == latest["pixel_sha256"] for r in outputs[:-1])})
            elif response.role == "refine":
                previous = hist["rounds"][-1]["composition"]["instruction"]
                gates.observations = {"prompt_unchanged": " ".join(payload["instruction"].split()) == " ".join(previous.split()), "format_repairs_exhausted": self._repair_count(case, task_id) >= read_json(case.path("case_config.json"))["max_format_repairs"]}
            transition = decide(state, response.role, payload, gates)
        except (ValueError, KeyError, OSError, TypeError) as exc:
            return self._reject(case, state, task_id, locals().get("response_raw", raw), "validation_error", str(exc), repairable=state.pending_task_id == task_id)
        # Everything below runs only after full validation; record result before next context is built.
        atomic_write(case.path(f"tasks/{task_id}/accepted/{digest}.json"), response_raw)
        details = {"response": response.model_dump(), "transport_mode": response.provenance["transport_mode"], "round_record": round_record, "accepted_path": f"tasks/{task_id}/accepted/{digest}.json", "transition": transition.model_dump()}
        if response.role == "diagnose":
            state.required_tools = list(dict.fromkeys(t["tool"] for t in payload["tool_plan"]))
        if response.role == "execute":
            state.budget.reserved -= 1
            state.budget.consumed += payload["actual_generations"]
            if state.budget.consumed > state.budget.max_generations:
                state.deviated = True
                details["extra_sampling"] = True
        state.pending_task_id = None
        state.workflow_status = transition.next_status
        self._action(state, transition.role)
        # Accept is one committed transaction, then next-task issuance a recoverable second transaction.
        state = commit(case, state, "response_accepted", details, accepted_response_sha256=digest)
        if transition.terminal_reason:
            self._finish(case, state, transition.terminal_reason)
            state = commit(case, state, "case_finished", {"terminal_reason": transition.terminal_reason})
        elif transition.role:
            if transition.increment_round:
                state.round += 1
            next_request = self._issue(case, state, transition.role)
            state = commit(case, state, "task_issued", {"task_id": next_request.task_id, "role": transition.role}, next_task=next_request)
        return ImportResult(accepted=True, code="accepted", message=state.next_action.message)

    def _reconcile(self, case, state):
        """Recover interrupted acceptance -> next-task issuance without re-consuming response."""
        if state.pending_task_id or state.workflow_completed or state.operation_status != "active":
            return state
        if state.workflow_status == "INIT":
            state.workflow_status = "WAIT_DIAGNOSIS"
        if state.workflow_status == "WAIT_EVIDENCE":
            config = read_json(case.path("case_config.json"))
            unavailable = self.unavailable_tools(state.case_id) if config.get("evidence_profile", {}).get("evidence_failure_policy") == "continue_with_unavailable" else {}
            if set(state.required_tools) <= set(state.received_tools) | set(unavailable):
                state.workflow_status = "WAIT_COMPOSITION"
        mapping = {"WAIT_DIAGNOSIS": "diagnose", "WAIT_COMPOSITION": "compose", "WAIT_EXECUTION": "execute", "WAIT_VERIFICATION": "verify", "WAIT_REFINEMENT": "refine"}
        if state.workflow_status == "FINISHED":
            last = next(tx for tx in reversed(transactions(case)) if tx["event"]["type"] == "response_accepted")
            reason = last["event"]["details"]["transition"]["terminal_reason"]
            self._finish(case, state, reason)
            return commit(case, state, "case_finished", {"recovered": True, "terminal_reason": reason})
        if state.workflow_status == "WAIT_EXECUTION":
            # Last accepted refiner belongs to the previous round until next issuance commits.
            last = next((tx["event"]["details"].get("response", {}) for tx in reversed(transactions(case)) if tx["event"]["type"] == "response_accepted"), {})
            if last.get("role") == "refine" and state.round == last["round"]:
                state.round += 1
        role = mapping.get(state.workflow_status)
        if role:
            req = self._issue(case, state, role)
            return commit(case, state, "task_issued", {"task_id": req.task_id, "role": role, "recovered": True}, next_task=req)
        return state

    def scan(self):
        with writer_lock(self.root):
            results = self.scan_locked()
        from .tool_service import ToolService
        ToolService(self.root).tick()
        return results

    def scan_locked(self):
        from .transport import scan_ready
        results = []
        for path in scan_ready(self.root):
            case = self.case(path.parents[2].name)
            results.append(self._accept(case, path))
        for state_file in sorted((self.root / "cases").glob("*/state.json")):
            case = self.case(state_file.parent.name)
            self._reconcile(case, recover_case(case))
        return results

    def import_json(self, case_id, task_id, payload, model_display_name, provenance=None):
        with writer_lock(self.root):
            from .transport import import_payload
            case = self.case(case_id)
            state = recover_case(case)
            request = Request.model_validate(read_json(case.path(f"tasks/{task_id}/request.json")))
            if self._accepted(case, task_id):
                return self._reject(case, state, task_id, json_bytes(payload) if isinstance(payload, dict) else payload.encode("utf-8"), "conflict", "该任务已有正式结果")
            if task_id != state.pending_task_id:
                return self._reject(case, state, task_id, json_bytes(payload) if isinstance(payload, dict) else payload.encode("utf-8"), "stale_task", "该任务已不是当前任务")
            raw = json.dumps(payload, ensure_ascii=False, allow_nan=False) if isinstance(payload, dict) else payload
            try:
                import_payload(case, task_id, raw, provenance or self.provenance(model_display_name))
            except (ValueError, OSError) as exc:
                return self._reject(case, state, task_id, raw.encode("utf-8"), "validation_error", str(exc), repairable=True)
            return self._accept(case, case.path(request.ready_marker))

    @staticmethod
    def provenance(model_display_name, transport_mode="clipboard_import", writer="manual_import", session_id=None):
        if not model_display_name.strip():
            raise ValueError("Enter the actual model display name")
        stamp = now()
        return {"model_display_name": model_display_name, "model_version": None, "model_version_source": "not_exposed", "session_id": session_id, "transport_mode": transport_mode, "writer": writer, "started_at": stamp, "completed_at": stamp}

    def import_image(self, case_id, task_id, source, model_display_name, provenance=None, **options):
        with writer_lock(self.root):
            from .transport import import_image
            case = self.case(case_id)
            state = recover_case(case)
            request = Request.model_validate(read_json(case.path(f"tasks/{task_id}/request.json")))
            if request.role != "execute":
                return self._reject(case, state, task_id, Path(source).read_bytes(), "stale_task", "图片必须绑定 execute 任务")
            if self._accepted(case, task_id):
                # Additional externally generated images are retained and
                # counted, but must never replace this task's official files.
                try:
                    from .transport import image_observations, FORMATS
                    sources = [Path(source), *[Path(p) for p in options.get("extras", [])]]
                    count = options.get("actual_generations", len(sources))
                    if type(count) is not int or count != len(sources):
                        raise ValueError("Generation count must include every provider image")
                    prefix = f"tasks/{task_id}/late/{uuid.uuid4().hex}"
                    assets = []
                    for index, path in enumerate(sources):
                        observations = image_observations(path, case.path("input/canonical.png"), read_json(case.path("case_config.json")))
                        raw = path.read_bytes()
                        relative = f"{prefix}/output_{index:03d}." + FORMATS[observations["format"]]
                        atomic_write(case.path(relative), raw)
                        assets.append({"path": relative, "sha256": sha256_bytes(raw), "kind": "photo", "width": observations["width"], "height": observations["height"]})
                    payload = {"output_asset": assets[0], "input_image_sha256": request.input_sha256, "instruction_sha256": request.context["instruction_sha256"], "provider_sequence_index": 0, "actual_generations": count, "extra_assets": assets[1:], "save_method": options.get("save_method", "manual_download"), "provider_settings": options.get("provider_settings") or {}, "seed_control": options.get("seed_control", False)}
                    envelope = {k: getattr(request, k) for k in ("protocol_version", "task_id", "case_id", "role", "round", "expected_state_revision", "input_sha256")}
                    envelope.update(status="ok", payload=payload, error=None, provenance=provenance or self.provenance(model_display_name))
                    raw_response = json_bytes(envelope)
                    marker = {"task_id": task_id, "response_file": f"{prefix}/response.json", "response_sha256": sha256_bytes(raw_response), "artifact_hashes": [{"path": a["path"], "sha256": a["sha256"]} for a in assets], "committed_at": now()}
                    validate_schema("done.schema.json", marker, case.path("snapshot/schemas"))
                    atomic_write(case.path(f"{prefix}/response.json"), raw_response)
                    write_json(case.path(f"{prefix}/done.json"), marker)
                    state = self._account_late_generation(case, state, request, raw_response, marker)
                    return self._reject(case, state, task_id, raw_response, "conflict", "额外生成已归档并计入成本，不替换正式输出。")
                except (ValueError, OSError) as exc:
                    return self._reject(case, state, task_id, Path(source).read_bytes(), "validation_error", str(exc))
            try:
                import_image(case, task_id, Path(source), provenance or self.provenance(model_display_name), **options)
            except (ValueError, OSError) as exc:
                return self._reject(case, state, task_id, Path(source).read_bytes(), "validation_error", str(exc))
            return self._accept(case, case.path(request.ready_marker))

    def register_evidence(self, case_id, manifest_file):
        manifest_file = Path(manifest_file)
        if read_json(manifest_file).get("protocol_version") == "1.1":
            if manifest_file.name != "evidence.json":
                raise ValueError("Local evidence bundle must use evidence.json")
            from .tool_registry import make_contract, canonicalizer_version_from_metadata
            from .tool_models import EvidenceProfile
            from .cache import EvidenceCache, make_cache_key
            from .local_evidence import validate_local_evidence
            case = self.case(case_id)
            with writer_lock(self.root):
                state = recover_case(case)
                if state.workflow_status != "WAIT_EVIDENCE" or state.operation_status != "active":
                    raise ValueError("Not waiting for evidence")
                data = read_json(manifest_file)
                tool = data["tool_id"]
                if tool not in state.required_tools:
                    raise ValueError("Tool is not in locked diagnosis plan")
                config = read_json(case.path("case_config.json"))
                version = canonicalizer_version_from_metadata(read_json(case.path("input/metadata.json")))
                contract = make_contract(state.input_sha256, tool, EvidenceProfile.model_validate(config["evidence_profile"]), config["tool_registry"]["tools"][tool], canonicalizer_version=version)
                validate_local_evidence(manifest_file.parent, contract)
            cache = EvidenceCache(self.root / "Data/annotations/cache")
            with cache.lock(tool, make_cache_key(contract), timeout=30):
                published = cache.publish(contract, manifest_file.parent)
            return self.accept_local_evidence(case_id, published, source="manual_import")
        with writer_lock(self.root):
            from .evidence import register_evidence
            case = self.case(case_id)
            state = recover_case(case)
            if state.workflow_status != "WAIT_EVIDENCE" or state.operation_status != "active":
                raise ValueError("Not waiting for evidence")
            manifest = register_evidence(case, Path(manifest_file))
            if manifest.tool_id not in state.required_tools:
                raise ValueError("Tool is not in locked diagnosis plan")
            if manifest.tool_id in state.received_tools:
                existing = next(e for e in history(case)["evidence"] if e["tool_id"] == manifest.tool_id)
                if existing != manifest.model_dump():
                    raise ValueError("Evidence conflict")
                return state
            if manifest.status == "error":
                state.operation_status = "blocked"
                state.block_reason = manifest.error
            else:
                state.received_tools.append(manifest.tool_id)
            self._action(state)
            state = commit(case, state, "tool_registered", {"manifest": manifest.model_dump()})
            if state.operation_status == "active" and set(state.required_tools) <= set(state.received_tools):
                state.workflow_status = "WAIT_COMPOSITION"
                req = self._issue(case, state, "compose")
                state = commit(case, state, "task_issued", {"task_id": req.task_id, "role": "compose"}, next_task=req)
            return state

    def operate(self, case_id, action, reason=None):
        with writer_lock(self.root):
            case = self.case(case_id)
            state = recover_case(case)
            if state.workflow_completed:
                raise ValueError("Case already finished")
            if action == "pause":
                state.operation_status = "paused"
            elif action == "resume":
                if state.block_reason and state.block_reason.startswith("format_repairs_exhausted"):
                    raise ValueError("Format repair budget exhausted; cancel or create a manual variant")
                state.operation_status = "active"
                state.block_reason = None
            elif action == "cancel":
                state.operation_status = "cancelled"
                self._finish(case, state, "cancelled")
            elif action == "submitted":
                req = read_json(case.path(f"tasks/{state.pending_task_id}/request.json"))
                if req["role"] != "execute":
                    raise ValueError("Only execute has submission telemetry")
            elif action == "skip_tool":
                if not reason or state.workflow_status != "WAIT_EVIDENCE":
                    raise ValueError("Provide tool_id:reason while waiting for evidence")
                tool_id, _, explanation = reason.partition(":")
                if tool_id not in state.required_tools or not explanation.strip():
                    raise ValueError("Invalid skipped tool/reason")
                state.required_tools.remove(tool_id)
                state.deviated = True
                state.operation_status = "active"
                state.block_reason = None
            else:
                raise ValueError("Unknown operation")
            state = commit(case, state, "execution_submitted" if action == "submitted" else "manual_intervention", {"action": action, "reason": reason, "task_id": state.pending_task_id})
            if state.workflow_status == "WAIT_EVIDENCE" and set(state.required_tools) <= set(state.received_tools) and state.operation_status == "active":
                state.workflow_status = "WAIT_COMPOSITION"
            return self._reconcile(case, state)

    def manual_variant(self, case_id, intent=None):
        state = self.inspect(case_id)
        case = self.case(case_id)
        config = read_json(case.path("case_config.json"))
        source = case.path(read_json(case.path("input/metadata.json"))["original_path"])
        return self.new(source, intent or config["intent"], {"parent_case_id": case_id, "branch_type": "manual_variant", "max_generations": state.budget.max_generations})

    def export(self, case_id, destination):
        with writer_lock(self.root):
            from .reports import export_case
            recover_case(self.case(case_id))
            return export_case(self.case(case_id), Path(destination))

    def unavailable_tools(self, case_id):
        return {tx["event"]["details"]["tool_id"]: tx["event"]["details"] for tx in transactions(self.case(case_id)) if tx["event"]["type"] == "tool_unavailable"}

    def excluded_tools(self, case_id):
        """User/operator exclusions are neither model failures nor empty results."""
        result = {}
        for tx in transactions(self.case(case_id)):
            if tx["event"]["type"] != "manual_intervention":
                continue
            details = tx["event"]["details"]
            if details.get("action") == "skip_tool":
                tool, _, reason = details["reason"].partition(":")
                result[tool] = {"tool_id": tool, "reason": reason, "status": "excluded", "source": "manual_intervention"}
        return result

    def _freeze_evidence(self, case, state):
        path = case.path("tools/evidence_snapshot.json")
        if path.exists():
            return
        hist = history(case)
        consumed = [e for e in hist["evidence"] if e["tool_id"] in state.required_tools and e["status"] == "ok"]
        bindings = [tx["event"]["details"].get("binding") for tx in transactions(case) if tx["event"]["type"] == "tool_registered" and tx["event"]["details"].get("binding")]
        excluded = self.excluded_tools(state.case_id)
        write_json(path, {"required_tools": state.required_tools, "consumed": consumed, "bindings": bindings,
                          "unavailable": self.unavailable_tools(state.case_id), "excluded": excluded,
                          "partial_evidence": bool(self.unavailable_tools(state.case_id) or excluded)})

    def _finish_tools_if_ready(self, case, state):
        unavailable = self.unavailable_tools(state.case_id)
        config = read_json(case.path("case_config.json"))
        policy = config.get("evidence_profile", {}).get("evidence_failure_policy", "all_planned_tools_required")
        covered = set(state.received_tools) | (set(unavailable) if policy == "continue_with_unavailable" else set())
        if set(state.required_tools) <= covered and state.operation_status == "active":
            state.workflow_status = "WAIT_COMPOSITION"
            req = self._issue(case, state, "compose")
            return commit(case, state, "task_issued", {"task_id": req.task_id, "role": "compose", "partial_evidence": bool(unavailable)}, next_task=req)
        return state

    def accept_local_evidence(self, case_id, cache_dir, source="local_compute", metrics=None):
        from .evidence_pack import bind_evidence
        with writer_lock(self.root):
            case = self.case(case_id)
            state = recover_case(case)
            if state.workflow_status != "WAIT_EVIDENCE" or state.operation_status != "active":
                return state  # Cache remains reusable; paused/cancelled cases do not advance.
            cached = read_json(Path(cache_dir) / "evidence.json")
            tool_id = cached["tool_id"]
            if tool_id not in state.required_tools:
                raise ValueError("Unplanned cached tool cannot be consumed")
            if tool_id in state.received_tools:
                return state
            config = read_json(case.path("case_config.json"))
            from .tool_registry import make_contract, canonicalizer_version_from_metadata
            from .tool_models import EvidenceProfile
            entry = config["tool_registry"]["tools"][tool_id]
            profile = EvidenceProfile.model_validate(config["evidence_profile"])
            from .cache import make_cache_key
            version = canonicalizer_version_from_metadata(read_json(case.path("input/metadata.json")))
            expected = make_contract(state.input_sha256, tool_id, profile, entry, canonicalizer_version=version)
            if make_cache_key(expected) != cached["cache_key"]:
                raise ValueError("Cache differs from the frozen case model/config")
            binding, manifest = bind_evidence(case, Path(cache_dir), source)
            state.received_tools.append(tool_id)
            self._action(state)
            state = commit(case, state, "tool_registered", {"manifest": manifest, "binding": binding.model_dump(), "worker_cost": metrics or {}, "source": source})
            return self._finish_tools_if_ready(case, state)

    def record_tool_unavailable(self, case_id, tool_id, code, message, metrics=None):
        with writer_lock(self.root):
            case = self.case(case_id)
            state = recover_case(case)
            if state.workflow_status != "WAIT_EVIDENCE" or state.operation_status != "active":
                return state
            if tool_id not in state.required_tools:
                raise ValueError("Unplanned tool failure")
            if tool_id in self.unavailable_tools(case_id):
                return state
            config = read_json(case.path("case_config.json"))
            partial = config.get("evidence_profile", {}).get("evidence_failure_policy") == "continue_with_unavailable"
            if partial:
                state.deviated = True
            else:
                state.operation_status = "blocked"
                state.block_reason = f"{tool_id}: {code}: {message}"
            state = commit(case, state, "tool_unavailable", {"tool_id": tool_id, "code": code, "message": message, "metrics": metrics or {}, "partial_evidence": partial})
            return self._finish_tools_if_ready(case, state)
