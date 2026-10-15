from copy import deepcopy

import pytest

from hir_manual.models import GateResult, State
from hir_manual.workflow import decide, select_final


@pytest.fixture
def make_state(fixture_json):
    def make(status, *, consumed=0, reserved=0, tools=None, received=None, **changes):
        data = fixture_json("state")
        data.update(
            workflow_status=status,
            required_tools=tools or [],
            received_tools=received or [],
        )
        data["budget"].update(consumed=consumed, reserved=reserved)
        data.update(changes)
        return State.model_validate(data)

    return make


@pytest.fixture
def verification(fixture_json):
    return fixture_json("verification_accepted")


def round_record(number, verification=None, *, valid_geometry=True, available=True):
    record = {
        "round": number,
        "valid_geometry": valid_geometry,
        "pixel_sha256": f"{number:064x}",
        "verification": verification,
    }
    if not available:
        record["output_asset"] = None
    return record


def test_initial_state_issues_diagnosis(make_state):
    result = decide(make_state("INIT"), "start", {})
    assert (result.next_status, result.role, result.terminal_reason) == (
        "WAIT_DIAGNOSIS", "diagnose", None
    )


def test_empty_tool_plan_composes_even_when_sensitive(fixture_json, make_state):
    diagnosis = fixture_json("diagnosis")
    diagnosis["tool_plan"] = []
    result = decide(make_state("WAIT_DIAGNOSIS"), "diagnose", diagnosis)
    assert result.next_status == "WAIT_COMPOSITION"
    assert result.role == "compose"


def test_nonempty_tool_plan_waits_for_evidence(fixture_json, make_state):
    result = decide(make_state("WAIT_DIAGNOSIS"), "diagnose", fixture_json("diagnosis"))
    assert result.next_status == "WAIT_EVIDENCE"
    assert result.role is None


@pytest.mark.parametrize("plan", [
    [{"tool": "T9_UNKNOWN", "reason": "unsupported"}],
])
def test_invalid_tool_plan_is_rejected(fixture_json, make_state, plan):
    diagnosis = fixture_json("diagnosis")
    diagnosis["tool_plan"] = plan
    with pytest.raises(ValueError):
        decide(make_state("WAIT_DIAGNOSIS"), "diagnose", diagnosis)


def test_missing_face_does_not_compose(fixture_json, make_state):
    state = make_state("WAIT_EVIDENCE", tools=["T1_OCR", "T2_FACE"])
    result = decide(state, "evidence", fixture_json("evidence"))
    assert result.next_status == "WAIT_EVIDENCE"
    assert result.role is None


def test_last_required_evidence_composes(fixture_json, make_state):
    state = make_state("WAIT_EVIDENCE", tools=["T1_OCR", "T2_FACE"], received=["T1_OCR"])
    evidence = fixture_json("evidence")
    evidence["tool_id"] = "T2_FACE"
    result = decide(state, "evidence", evidence)
    assert result.next_status == "WAIT_COMPOSITION"
    assert result.role == "compose"


def test_unplanned_or_failed_evidence_is_rejected(fixture_json, make_state):
    evidence = fixture_json("evidence")
    state = make_state("WAIT_EVIDENCE", tools=["T2_FACE"])
    with pytest.raises(ValueError):
        decide(state, "evidence", evidence)
    evidence["tool_id"] = "T2_FACE"
    evidence["status"] = "error"
    with pytest.raises(ValueError):
        decide(state, "evidence", evidence)


def test_composition_sends_execute_without_mutating_state(fixture_json, make_state):
    state = make_state("WAIT_COMPOSITION")
    before = state.model_dump()
    result = decide(state, "compose", fixture_json("composition"))
    assert result.next_status == "WAIT_EXECUTION"
    assert result.role == "execute"
    assert not result.increment_round
    assert state.model_dump() == before


@pytest.mark.parametrize("consumed,reserved", [(3, 0), (2, 1), (4, 0)])
def test_no_dispatch_at_consumed_plus_reserved_budget(fixture_json, make_state, consumed, reserved):
    result = decide(make_state("WAIT_COMPOSITION", consumed=consumed, reserved=reserved),
                    "compose", fixture_json("composition"))
    assert result.next_status == "FINISHED"
    assert result.terminal_reason == "budget_exhausted"
    assert result.role is None


def test_execution_always_goes_to_verifier(fixture_json, make_state):
    result = decide(make_state("WAIT_EXECUTION", consumed=3), "execute",
                    fixture_json("execution"), GateResult(valid_geometry=False))
    assert result.next_status == "WAIT_VERIFICATION"
    assert result.role == "verify"


def test_correct_verification_accepted_without_score_threshold(verification, make_state):
    verification["overall"] = 0
    verification["scores"] = {key: 0 for key in verification["scores"]}
    result = decide(make_state("WAIT_VERIFICATION", consumed=3), "verify", verification)
    assert result.next_status == "FINISHED"
    assert result.terminal_reason == "accepted"


def test_incorrect_without_redo_is_incomplete_even_at_budget(verification, make_state):
    verification["verdict"] = "incorrect"
    verification["needs_redo"] = False
    result = decide(make_state("WAIT_VERIFICATION", consumed=3), "verify", verification)
    assert result.terminal_reason == "no_further_gain"


def test_retry_with_budget_requests_refiner(verification, make_state):
    verification.update(verdict="incorrect", needs_redo=True)
    result = decide(make_state("WAIT_VERIFICATION", consumed=1), "verify", verification)
    assert result.next_status == "WAIT_REFINEMENT"
    assert result.role == "refine"
    assert not result.increment_round


@pytest.mark.parametrize("consumed,reserved", [(3, 0), (2, 1), (4, 0)])
def test_third_failed_generation_exhausts_budget(verification, make_state, consumed, reserved):
    verification.update(verdict="incorrect", needs_redo=True)
    result = decide(make_state("WAIT_VERIFICATION", consumed=consumed, reserved=reserved),
                    "verify", verification)
    assert result.terminal_reason == "budget_exhausted"


def test_duplicate_stops_retry_before_budget(verification, make_state):
    verification.update(verdict="incorrect", needs_redo=True)
    result = decide(make_state("WAIT_VERIFICATION", consumed=3), "verify", verification,
                    GateResult(observations={"duplicate_output": True}))
    assert result.terminal_reason == "duplicate_output"


@pytest.mark.parametrize("change", ["redo", "fail", "moderate", "severe"])
def test_contradictory_correct_response_rejected(verification, make_state, change):
    if change == "redo":
        verification["needs_redo"] = True
    elif change == "fail":
        verification["checklist"]["C1"] = "fail"
    else:
        verification["defects"] = [{"item": "C1", "severity": change}]
    state = make_state("WAIT_VERIFICATION", consumed=3)
    before = state.model_dump()
    with pytest.raises(ValueError, match="[Cc]ontradict"):
        decide(state, "verify", verification,
               GateResult(observations={"duplicate_output": True}))
    assert state.model_dump() == before


def test_mild_residual_with_reasoning_can_pass(verification, make_state):
    verification["defects"] = [{"item": "C1", "severity": "mild"}]
    result = decide(make_state("WAIT_VERIFICATION"), "verify", verification)
    assert result.terminal_reason == "accepted"


def test_mild_residual_without_reasoning_is_rejected(verification, make_state):
    verification["defects"] = [{"item": "C1", "severity": "mild"}]
    verification["reasoning"] = " "
    with pytest.raises(ValueError):
        decide(make_state("WAIT_VERIFICATION"), "verify", verification)


@pytest.mark.parametrize("item", ["C1", "C2", "C5", "C6", "C7"])
def test_only_text_and_face_can_be_na(verification, make_state, item):
    verification["verdict"] = "incorrect"
    verification["checklist"][item] = "na"
    with pytest.raises(ValueError):
        decide(make_state("WAIT_VERIFICATION"), "verify", verification)


def test_text_and_face_na_are_allowed(verification, make_state):
    verification["checklist"].update(C3="na", C4="na")
    assert decide(make_state("WAIT_VERIFICATION"), "verify", verification).terminal_reason == "accepted"


def test_geometry_does_not_override_no_redo(verification, make_state):
    result = decide(make_state("WAIT_VERIFICATION", consumed=1), "verify", verification,
                    GateResult(valid_geometry=False))
    assert result.next_status == "FINISHED"
    assert result.terminal_reason == "no_further_gain"


def test_geometry_never_accepted_when_budget_exhausted(verification, make_state):
    verification.update(verdict="incorrect", needs_redo=True)
    result = decide(make_state("WAIT_VERIFICATION", consumed=3), "verify", verification,
                    GateResult(valid_geometry=False))
    assert result.terminal_reason == "budget_exhausted"


def test_bad_geometry_can_refine_after_verifier_requests_redo(verification, make_state):
    verification.update(verdict="incorrect", needs_redo=True)
    result = decide(make_state("WAIT_VERIFICATION", consumed=1), "verify", verification,
                    GateResult(valid_geometry=False))
    assert result.next_status == "WAIT_REFINEMENT"


def test_accepted_precedes_duplicate_stop(verification, make_state):
    result = decide(make_state("WAIT_VERIFICATION", consumed=3), "verify", verification,
                    GateResult(observations={"duplicate_output": True}))
    assert result.terminal_reason == "accepted"


def test_duplicate_precedes_incorrect_no_redo(verification, make_state):
    verification["verdict"] = "incorrect"
    result = decide(make_state("WAIT_VERIFICATION", consumed=3), "verify", verification,
                    GateResult(observations={"duplicate_output": True}))
    assert result.terminal_reason == "duplicate_output"


def test_refinement_advances_round_only_with_changed_instruction(fixture_json, make_state):
    result = decide(make_state("WAIT_REFINEMENT", consumed=1), "refine", fixture_json("composition"))
    assert result.next_status == "WAIT_EXECUTION"
    assert result.role == "execute"
    assert result.increment_round


def test_refinement_cannot_advance_at_reserved_budget(fixture_json, make_state):
    result = decide(make_state("WAIT_REFINEMENT", consumed=2, reserved=1), "refine",
                    fixture_json("composition"))
    assert result.terminal_reason == "budget_exhausted"
    assert not result.increment_round


def test_unchanged_refinement_requests_repair_before_termination(fixture_json, make_state):
    state = make_state("WAIT_REFINEMENT", consumed=1)
    payload = fixture_json("composition")
    with pytest.raises(ValueError, match="instruction"):
        decide(state, "refine", payload, GateResult(observations={"prompt_unchanged": True}))
    result = decide(state, "refine", payload, GateResult(observations={
        "prompt_unchanged": True, "format_repairs_exhausted": True
    }))
    assert result.terminal_reason == "no_prompt_change"
    assert not result.increment_round


@pytest.mark.parametrize("status,role", [("WAIT_DIAGNOSIS", "verify"), ("WAIT_EXECUTION", "compose")])
def test_wrong_role_is_rejected(make_state, status, role):
    with pytest.raises(ValueError):
        decide(make_state(status), role, {})


@pytest.mark.parametrize("operation", ["paused", "blocked", "cancelled"])
def test_inactive_case_cannot_transition(make_state, operation):
    with pytest.raises(ValueError):
        decide(make_state("WAIT_DIAGNOSIS", operation_status=operation), "diagnose", {})


def test_finished_case_cannot_transition(make_state, verification):
    with pytest.raises(ValueError):
        decide(make_state("FINISHED", workflow_completed=True), "verify", verification)


def test_best_round_zero_is_first_round(verification):
    verification.update(verdict="incorrect", needs_redo=False, best_round=0)
    result = select_final([round_record(1, verification)])
    assert result.round == 1
    assert result.success is False


def test_last_verdict_cannot_mark_earlier_round_success(verification):
    earlier = deepcopy(verification)
    earlier.update(verdict="incorrect", needs_redo=True)
    latest = deepcopy(verification)
    latest.update(verdict="correct", needs_redo=False, best_round=0)
    result = select_final([round_record(1, earlier), round_record(2, latest, valid_geometry=False)])
    assert result.round == 1
    assert result.success is False


def test_accepted_latest_round_delivered_even_if_comparison_names_earlier(verification):
    earlier = deepcopy(verification)
    earlier.update(verdict="incorrect", needs_redo=True)
    result = select_final([round_record(1, earlier), round_record(2, verification)])
    assert (result.round, result.success, result.reason) == (2, True, "accepted")


def test_first_accepted_round_wins_over_later_comparison(verification):
    first = deepcopy(verification)
    latest = deepcopy(verification)
    latest.update(verdict="incorrect", best_round=1)
    result = select_final([round_record(1, first), round_record(2, latest)])
    assert (result.round, result.success, result.reason) == (1, True, "accepted")


def test_best_index_maps_attempt_order_to_explicit_round(verification):
    first = deepcopy(verification)
    first.update(verdict="incorrect", needs_redo=True)
    latest = deepcopy(first)
    latest.update(best_round=1)
    result = select_final([round_record(7, first), round_record(11, latest)])
    assert result.round == 11
    assert result.success is False


@pytest.mark.parametrize("best_round", [3, -1, True, "0"])
def test_unrepairable_best_index_falls_back_incomplete(verification, best_round):
    verification.update(verdict="incorrect", best_round=best_round)
    result = select_final([round_record(1, verification)])
    assert result.round == 1
    assert result.success is False
    assert result.reason == "invalid_best_round"


def test_best_round_excludes_bad_geometry_and_unavailable_output(verification):
    verification.update(verdict="incorrect", best_round=0)
    records = [round_record(1, verification, valid_geometry=False), round_record(2), round_record(3, available=False)]
    result = select_final(records)
    assert result.round == 2
    assert result.success is False
    assert result.reason == "invalid_best_round"


def test_no_valid_output_yields_null(verification):
    records = [round_record(1, verification, valid_geometry=False), round_record(2, available=False)]
    result = select_final(records)
    assert (result.round, result.success, result.reason) == (None, False, "no_valid_output")
    assert select_final([]).round is None


def test_no_verification_selects_earliest_valid_as_incomplete():
    result = select_final([round_record(2), round_record(4)])
    assert (result.round, result.success, result.reason) == (2, False, "unverified")


def test_selection_does_not_mutate_attempts(verification):
    records = [round_record(1, verification), round_record(2)]
    before = deepcopy(records)
    select_final(records)
    assert records == before


@pytest.mark.parametrize("change", [
    {"verdict": []}, {"needs_redo": "false"}, {"defects": {}},
    {"defects": [{"item": [], "severity": "mild"}]},
    {"defects": [{"item": "C1", "severity": []}]},
])
def test_invalid_verification_semantics_raise_value_error(verification, make_state, change):
    verification.update(change)
    with pytest.raises(ValueError):
        decide(make_state("WAIT_VERIFICATION"), "verify", verification)


def test_malformed_correct_verification_cannot_succeed(verification):
    verification["checklist"]["C2"] = "fail"
    result = select_final([round_record(1, verification)])
    assert result.success is False
