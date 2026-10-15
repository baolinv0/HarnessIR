"""Pure decisions for the fixed adapted HarnessIR workflow.

The service validates schemas and assets before calling these functions. This
module checks the additional semantic constraints without opening any files or
changing the state, payloads, generation ledger, or round records.
"""

from .models import GateResult, Selection, State, Transition


TOOLS = frozenset({"T1_OCR", "T2_FACE", "T3_DEPTH", "T4_SEGMENTATION"})
CHECKLIST_ITEMS = frozenset({"C1", "C2", "C3", "C4", "C5", "C6", "C7"})
NA_ALLOWED = frozenset({"C3", "C4"})
ROLE_STATES = {
    "diagnose": "WAIT_DIAGNOSIS",
    "evidence": "WAIT_EVIDENCE",
    "compose": "WAIT_COMPOSITION",
    "execute": "WAIT_EXECUTION",
    "verify": "WAIT_VERIFICATION",
    "refine": "WAIT_REFINEMENT",
}


def _finish(reason: str) -> Transition:
    return Transition(next_status="FINISHED", terminal_reason=reason)


def _has_budget(state: State) -> bool:
    return state.budget.consumed + state.budget.reserved < state.budget.max_generations


def _flag(gates: GateResult, key: str) -> bool:
    value = gates.observations.get(key, False)
    if type(value) is not bool:
        raise ValueError(f"Gate observation {key} must be a boolean")
    return value


def _verification_semantics(payload: dict) -> None:
    """Reject contradictions before any terminal or budget decision.

    A mild residual is compatible with success only with nonempty reasoning
    and a checklist that does not fail. Numerical scores do not decide success.
    """
    verdict = payload.get("verdict")
    redo = payload.get("needs_redo")
    if not isinstance(verdict, str) or verdict not in {"correct", "incorrect"} or type(redo) is not bool:
        raise ValueError("Verification requires a verdict and boolean needs_redo")
    checklist = payload.get("checklist")
    if not isinstance(checklist, dict) or set(checklist) != CHECKLIST_ITEMS:
        raise ValueError("Verification requires the complete C1-C7 checklist")
    for item, value in checklist.items():
        if not isinstance(value, str) or value not in {"pass", "fail", "na"}:
            raise ValueError(f"Invalid checklist value for {item}")
        if value == "na" and item not in NA_ALLOWED:
            raise ValueError(f"Checklist {item} cannot be na")
    defects = payload.get("defects")
    if not isinstance(defects, list):
        raise ValueError("Verification defects must be a list")
    for defect in defects:
        if (not isinstance(defect, dict) or not isinstance(defect.get("item"), str)
                or defect["item"] not in CHECKLIST_ITEMS):
            raise ValueError("Defect requires a checklist item")
        severity = defect.get("severity")
        if not isinstance(severity, str) or severity not in {"mild", "moderate", "severe"}:
            raise ValueError("Defect requires a valid severity")
    if verdict == "correct":
        if redo:
            raise ValueError("Contradictory verification: correct with needs_redo=true")
        if "fail" in checklist.values():
            raise ValueError("Contradictory verification: correct with failed checklist")
        if any(defect["severity"] != "mild" for defect in defects):
            raise ValueError("Contradictory verification: correct with moderate/severe defect")
        reasoning = payload.get("reasoning")
        if defects and (not isinstance(reasoning, str) or not reasoning.strip()):
            raise ValueError("Mild residual defects require reasoning")


def decide(state: State, role: str, payload: dict, gates: GateResult | None = None) -> Transition:
    """Return the next workflow step without mutating any input.

    Verification precedence is: reject semantic contradictions; accept a correct
    result with valid geometry; stop duplicates; honor needs_redo=false as
    incomplete; stop at the consumed-plus-reserved budget; otherwise refine.
    Geometry failures cannot succeed, and do not override a verifier's no-redo.

    Evidence payloads are a single validated manifest. Its tool is combined with
    state.received_tools for this decision, but only the service persists it.
    The service reserves a generation before executing and consumes it upon
    confirmed output; this function does neither.
    """
    if state.operation_status != "active" or state.workflow_completed:
        raise ValueError("Only an active incomplete case can transition")
    if not isinstance(payload, dict):
        raise ValueError("Workflow payload must be an object")
    gates = gates if gates is not None else GateResult()
    if not isinstance(role, str):
        raise ValueError("Workflow role must be a string")
    if state.workflow_status == "INIT" and role in {"start", "init"}:
        return Transition(next_status="WAIT_DIAGNOSIS", role="diagnose")
    if role not in ROLE_STATES or state.workflow_status != ROLE_STATES[role]:
        raise ValueError(f"Role {role} cannot respond in {state.workflow_status}")

    if role == "diagnose":
        plan = payload.get("tool_plan")
        if not isinstance(plan, list):
            raise ValueError("Diagnosis requires a tool_plan list")
        tools = []
        for entry in plan:
            if (not isinstance(entry, dict) or not isinstance(entry.get("tool"), str)
                    or entry["tool"] not in TOOLS):
                raise ValueError("Diagnosis contains an unknown tool")
            tools.append(entry["tool"])
        tools = list(dict.fromkeys(tools))
        if tools:
            return Transition(next_status="WAIT_EVIDENCE")
        return Transition(next_status="WAIT_COMPOSITION", role="compose")

    if role == "evidence":
        tool = payload.get("tool_id")
        if not isinstance(tool, str) or tool not in TOOLS or tool not in state.required_tools:
            raise ValueError("Evidence tool was not requested")
        if payload.get("status") != "ok":
            raise ValueError("Failed tool evidence cannot advance the workflow")
        received = set(state.received_tools) | {tool}
        if set(state.required_tools) <= received:
            return Transition(next_status="WAIT_COMPOSITION", role="compose")
        return Transition(next_status="WAIT_EVIDENCE")

    if role in {"compose", "refine"}:
        instruction = payload.get("instruction")
        if not isinstance(instruction, str) or not instruction.strip():
            raise ValueError("Composition requires a nonempty instruction")
        if role == "refine" and _flag(gates, "prompt_unchanged"):
            if _flag(gates, "format_repairs_exhausted"):
                return _finish("no_prompt_change")
            raise ValueError("Refinement instruction is unchanged; repair the same task")
        if not _has_budget(state):
            return _finish("budget_exhausted")
        return Transition(next_status="WAIT_EXECUTION", role="execute", increment_round=role == "refine")

    if role == "execute":
        # Decode and provenance checks are service responsibilities. Every valid
        # received image gets verification, including geometry failures and
        # unexpected generations that have already consumed the budget.
        return Transition(next_status="WAIT_VERIFICATION", role="verify")

    _verification_semantics(payload)
    image_constraints = gates.observations.get("valid_image_constraints", True)
    if type(image_constraints) is not bool:
        raise ValueError("valid_image_constraints must be a boolean")
    if payload["verdict"] == "correct" and gates.valid_geometry and image_constraints:
        return _finish("accepted")
    if _flag(gates, "duplicate_output"):
        return _finish("duplicate_output")
    if not payload["needs_redo"]:
        return _finish("no_further_gain")
    if not _has_budget(state):
        return _finish("budget_exhausted")
    return Transition(next_status="WAIT_REFINEMENT", role="refine")


def _valid_output(record: dict) -> bool:
    number = record.get("round")
    pixels = record.get("pixel_sha256")
    return (
        type(number) is int
        and number >= 1
        and record.get("valid_geometry") is True
        and record.get("valid_image_constraints", True) is True
        and isinstance(pixels, str)
        and len(pixels) == 64
        and all(character in "0123456789abcdef" for character in pixels)
        and ("output_asset" not in record or record["output_asset"] is not None)
    )


def _accepted(record: dict) -> bool:
    verification = record.get("verification")
    if not _valid_output(record) or not isinstance(verification, dict):
        return False
    try:
        _verification_semantics(verification)
    except (ValueError, TypeError):
        return False
    return verification["verdict"] == "correct"


def select_final(rounds: list[dict]) -> Selection:
    """Select a candidate from attempt records in the supplied attempt order.

    The first accepted output stops the normal workflow. Otherwise the last
    verifier's zero-based best_round indexes this list, and the record's explicit
    round value is returned. Unavailable/geometry-invalid outputs are excluded.
    An invalid best index falls back to the earliest valid round, always as an
    incomplete candidate. Without any valid output, final_output is null.

    Presence of output_asset=None marks unavailable output; omitting this
    optional field is permitted when the caller already validated assets.
    """
    accepted = next((record for record in rounds if _accepted(record)), None)
    if accepted is not None:
        return Selection(round=accepted["round"], success=True, reason="accepted")

    valid = [record for record in rounds if _valid_output(record)]
    if not valid:
        return Selection(round=None, success=False, reason="no_valid_output")
    earliest = min(valid, key=lambda record: record["round"])
    latest = next((record["verification"] for record in reversed(rounds)
                   if isinstance(record.get("verification"), dict)), None)
    if latest is None:
        return Selection(round=earliest["round"], success=False, reason="unverified")
    index = latest.get("best_round")
    if type(index) is not int or not 0 <= index < len(rounds) or not _valid_output(rounds[index]):
        return Selection(round=earliest["round"], success=False, reason="invalid_best_round")
    selected = rounds[index]
    return Selection(round=selected["round"], success=_accepted(selected), reason="best_round")
