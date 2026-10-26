"""Integration/negative controls, not measurements of image-model quality."""
from copy import deepcopy

import pytest

from hre.models import HREError
from hre.v3.common import digest, render_instruction
from hre.v3.contracts import normalise_spec
from hre.v3.runner import _stage_request


def test_old_stage_request_hash_is_unchanged():
    request = _stage_request({"task_mode": "reference_enhance", "brief": "Match supported appearance."},
        {"inputs": [], "canvas": {"width": 32, "height": 32}}, "diagnose",
        {"available_evidence_refs": ["source", "appearance_reference"]})
    assert digest(request) == "9ac44140efa2e7363f90f1237a0cd8974f9a115f6ac42e3da10508e86c478140"


def test_legacy_intent_validator_does_not_silently_accept_a_new_workflow_schema():
    from hre.v3.stages import validate_intent
    with pytest.raises(HREError): validate_intent(intent_fixture(), "reference_enhance")


from pathlib import Path
from PIL import Image
from hre.models import file_sha256
from hre.storage import read_json, write_json
from hre.v3.contracts import create_case
from hre.v3.runner import run_case, import_shared_intent
from test_hre_v3_runner import Workers
from test_v3_reference_contract import diagnosis_fixture, intent_fixture, verification_fixture


def make_reference_case(tmp_path, *, requirements=None, policy="single", shared=None):
    Image.new("RGB", (32, 32), (40, 50, 60)).save(tmp_path / "A.png")
    Image.new("RGB", (32, 32), (70, 75, 80)).save(tmp_path / "B.png")
    value = {**spec(), "source": {"path": str(tmp_path / "A.png")},
        "reference": {"path": str(tmp_path / "B.png")}, "case_id": "ref_case",
        "policy": {"mode": policy, "max_generations": 1 if policy == "single" else 2}}
    if requirements is not None:
        value["delivery_requirements"] = requirements
    if shared:
        value["shared_intent"] = str(shared)
    config = {"stage": {}, "models": {"qwen21": {"compiler": {"backend": "direct"},
        "editor": {"model_id": "Qwen/Qwen-Image-2.1"}}}}
    root = tmp_path / "ref_case"
    create_case(root, value, config)
    return root


class ReferenceWorkers(Workers):
    def __init__(self, *, close=False, insufficient=False, mutate_verify=None, mutate_refine=None):
        super().__init__(accept_after=1)
        self.diagnosis = diagnosis_fixture(already_close=close, insufficient=insufficient)
        self.intent = intent_fixture(already_close=close, insufficient=insufficient)
        self.requests = []
        self.mutate_verify, self.mutate_refine = mutate_verify, mutate_refine

    def stage(self, request):
        self.stages.append(request["stage"])
        self.requests.append(deepcopy(request))
        stage = request["stage"]
        if stage == "diagnose": payload = deepcopy(self.diagnosis)
        elif stage == "compose": payload = deepcopy(self.intent)
        elif stage == "verify":
            payload = verification_fixture(self.intent)
            if self.mutate_verify: self.mutate_verify(payload, len(self.executions))
        else:
            previous = request["context"]["previous_intent"]
            revised = deepcopy(previous)
            revised.update(revision=previous["revision"] + 1, parent_intent_hash=digest(previous),
                           feedback_refs=request["context"]["actionable_feedback_refs"])
            revised["targets"][0]["instruction"] += " Preserve the already achieved tonal result."
            if self.mutate_refine: self.mutate_refine(revised)
            self.intent = revised
            payload = {"action": "revise", "reason": "Respond to a supported residual.", "intent": revised}
        return {"payload": payload, "observation": {"calls_attempted": 1, "calls_completed": 1,
            "fixture_only": True, "stage_request_id": request["request_id"], "stage_request_sha256": digest(request)}}


def execute_reference(root, workers):
    return run_case(root, stage_fn=workers.stage, compile_fn=workers.compile, execute_fn=workers.execute)


def test_already_satisfied_is_successful_pixel_identical_and_zero_generation(tmp_path):
    root = make_reference_case(tmp_path)
    workers = ReferenceWorkers(close=True)
    state = execute_reference(root, workers)
    assert state["success"] and state["terminal_reason"] == "already_satisfied"
    assert state["selected_kind"] == "source_already_satisfied"
    assert state["selected_output"] == state["inputs"][0]
    assert state["budget"]["generations"] == state["budget"]["compiler_calls"] == 0
    assert not workers.compiles and not workers.executions
    assert workers.stages == ["diagnose", "compose"]
    assert execute_reference(root, workers) == state


def test_insufficient_reference_is_zero_generation_but_not_success(tmp_path):
    root = make_reference_case(tmp_path)
    workers = ReferenceWorkers(insufficient=True)
    state = execute_reference(root, workers)
    assert not state["success"] and state["terminal_reason"] == "insufficient_evidence"
    assert state["budget"]["generations"] == 0 and not workers.compiles


def test_already_satisfied_still_checks_frozen_native_delivery_requirements(tmp_path):
    root = make_reference_case(tmp_path, requirements={"minimum_native_size": [64, 64]})
    workers = ReferenceWorkers(close=True)
    state = execute_reference(root, workers)
    assert not state["success"] and state["quality_status"] == "delivery_not_met"
    assert not state["delivery_assessment"]["pass"]
    assert not workers.executions and state["selected_output"] == state["inputs"][0]


def test_no_degradation_findings_does_not_skip_supported_appearance_targets(tmp_path):
    root = make_reference_case(tmp_path)
    workers = ReferenceWorkers()
    workers.diagnosis["findings"] = []
    state = execute_reference(root, workers)
    assert state["success"] and len(workers.executions) == 1
    verify = next(r for r in workers.requests if r["stage"] == "verify")
    assert "reference_contract" in verify["context"]
    assert "intent" not in verify["context"] and "profile_id" not in verify
    assert [a["role"] for a in verify["inputs"]] == ["source", "appearance_reference", "candidate", "candidate_native"]


@pytest.mark.parametrize("requirements", [{"minimum_native_size": [64, 64]}, {"require_detail_pass": True}])
def test_appearance_pass_cannot_hide_failed_native_or_detail_delivery(tmp_path, requirements):
    root = make_reference_case(tmp_path, requirements=requirements)
    workers = ReferenceWorkers()
    state = execute_reference(root, workers)
    candidate = state["candidates"][0]
    assert candidate["appearance_status"] == "accept"
    assert not candidate["delivery_assessment"]["pass"]
    assert not candidate["accepted"] and not state["success"]


def test_optional_partial_remains_visible_without_blocking_required_success(tmp_path):
    root = make_reference_case(tmp_path)
    def partial(payload, count): payload["target_results"][1]["status"] = "partial"
    workers = ReferenceWorkers(mutate_verify=partial)
    target = deepcopy(workers.intent["targets"][0])
    target.update(id="optional_skin", priority=2, mandatory=False)
    workers.intent["targets"].append(target)
    next(c for c in workers.intent["coverage"] if c["attribute"] == "skin_rendering")["target_ids"].append("optional_skin")
    state = execute_reference(root, workers)
    assert state["success"]
    assert state["candidates"][0]["verification"]["target_results"][1]["status"] == "partial"


def residual(payload, count):
    if count > 1: return
    payload.update(verdict="revise", task_progress="unchanged", issues=[{"id": "i1", "kind": "appearance_target_unmet",
        "region": "face", "observation": "Supported grey cast remains.", "evidence_refs": ["source", "appearance_reference", "candidate"],
        "suggested_change": "Reduce remaining grey cast while retaining brightness."}])
    payload["target_results"][0].update(status="partial", remaining_gap="Grey cast remains.", suggested_correction="Reduce the residual grey cast.")


def test_feedback_keeps_frozen_goals_and_original_AB(tmp_path):
    root = make_reference_case(tmp_path, policy="feedback")
    workers = ReferenceWorkers(mutate_verify=residual)
    state = execute_reference(root, workers)
    assert state["success"] and len(workers.executions) == 2
    assert workers.executions[0]["original_input_sha256"] == workers.executions[1]["original_input_sha256"]
    assert workers.executions[0]["reference_contract_sha256"] == workers.executions[1]["reference_contract_sha256"]
    assert workers.executions[0]["intent"]["targets"][0]["instruction"] != workers.executions[1]["intent"]["targets"][0]["instruction"]


def test_feedback_cannot_weaken_a_frozen_acceptance_criterion(tmp_path):
    root = make_reference_case(tmp_path, policy="feedback")
    workers = ReferenceWorkers(mutate_verify=residual,
        mutate_refine=lambda value: value["targets"][0].update(acceptance_criterion="Anything is acceptable."))
    state = execute_reference(root, workers)
    assert not state["success"] and len(workers.executions) == 1
    assert state["status"] == "failed"


def test_shared_reference_planning_rejects_a_different_workflow_version(tmp_path):
    root = make_reference_case(tmp_path)
    workers = ReferenceWorkers()
    state = execute_reference(root, workers)
    spec_value = read_json(root / "task.json")
    artifact = root / "artifacts/shared_intent.json"
    assert import_shared_intent(artifact, spec_value, state) == workers.intent
    spec_value.pop("workflow_contract")
    with pytest.raises(HREError, match="shared_contract_version"):
        import_shared_intent(artifact, spec_value, state)


def test_report_exposes_reference_chain_and_delivery_failure_without_rewriting_case(tmp_path):
    from hre.v3.report import export_report
    root = make_reference_case(tmp_path, requirements={"minimum_native_size": [64, 64]})
    workers = ReferenceWorkers()
    execute_reference(root, workers)
    before = file_sha256(root / "state.json")
    output = tmp_path / "report"
    export_report(root, output)
    row = read_json(output / "report.json")["runs"][0]
    assert row["reference_workflow"]["reference_contract"]["targets"][0]["acceptance_criterion"]
    assert row["reference_workflow"]["diagnosis"]["payload"]["reference_profile"]
    assert row["reference_workflow"]["compiled_conditions"]
    assert row["candidates"][0]["appearance_status"] == "accept"
    assert not row["candidates"][0]["delivery_assessment"]["pass"]
    assert file_sha256(root / "state.json") == before


def spec():
    return {"profile_id": "qwen21", "task_mode": "reference_enhance", "strategy": "shared",
            "brief": "Match supported appearance.", "source": {"path": "A.png"},
            "reference": {"path": "B.png"}, "workflow_contract": "reference_retouch_v1"}


def test_unknown_workflow_contract_is_rejected():
    value = spec()
    value["workflow_contract"] = "invented"
    with pytest.raises(HREError):
        normalise_spec(value)


@pytest.mark.parametrize("change", [{"task_mode": "restoration", "reference": None}, {"strategy": "native"}])
def test_reference_contract_cannot_be_used_for_another_task_or_native_baseline(change):
    value = spec()
    value.update(change)
    with pytest.raises(HREError):
        normalise_spec(value)


def test_reference_requests_select_new_frozen_template():
    request = _stage_request(spec(), {"inputs": [], "canvas": {"width": 32, "height": 32}},
                             "diagnose", {"available_evidence_refs": ["source", "appearance_reference"]})
    assert request.get("workflow_contract") == "reference_retouch_v1"
    assert request["stage_template"]["version"] == "hre_reference_retouch_stages_v1"


def test_all_reference_facts_and_success_criteria_enter_compiler_input():
    value = {**spec(), "intent": {"targets": [{"id": "skin", "region": "face", "priority": 1,
        "instruction": "Reduce grey cast.", "attribute": "skin_rendering", "mandatory": True,
        "source_observation": "A has a cool grey face.", "reference_observation": "B has restrained warm cheeks.",
        "source_region": "face", "reference_region": "cheeks", "acceptance_criterion": "Warm without orange clipping."}],
        "region_relations": [], "protected_content": ["Expression"], "uncertainties": [],
        "excluded_reference_traits": ["B pose"]}}
    rendered = render_instruction(value)
    for text in ("A has a cool grey face.", "B has restrained warm cheeks.", "Warm without orange clipping.", "B pose"):
        assert text in rendered
