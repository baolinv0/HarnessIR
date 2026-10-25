"""Strict reference-retouch contracts; software fixtures are not model evidence."""
from copy import deepcopy

import pytest

from hre.models import HREError
from hre.v3.common import digest
from hre.v3 import reference_retouch as retouch


DIMENSIONS = sorted({"neutral_balance", "chroma_by_hue", "skin_rendering", "shadow_midtone_highlight",
                     "highlight_transition", "local_contrast", "subject_background_balance", "texture_and_noise_observation"})


def diagnosis_fixture(*, already_close=False, insufficient=False):
    deltas = [] if already_close or insufficient else [{
        "id": "d1", "attribute": "skin_rendering", "source_region": "face", "reference_region": "face",
        "source_observation": "A face has cool grey rendering.", "reference_observation": "B face is naturally warmer.",
        "desired_change": "Reduce cool grey rendering toward B.", "comparability": "conditional",
        "uncertainty": "Different pose and mixed illumination; directional comparison only.",
        "evidence_refs": ["source", "appearance_reference"]}]
    return {"schema_version": "hre_reference_diagnosis_v1", "task_mode": "reference_enhance",
            "findings": [] if not deltas else [{"id": "f1", "region": "face", "kind": "appearance_gap",
                "observation": "A face is visibly cooler than B.", "confidence": .8, "evidence_refs": ["source", "appearance_reference"]}],
            "protected_content": ["Preserve expression and readable text."], "uncertainties": [],
            "tool_requests": ["basic_statistics"], "summary": "Software-only diagnostic fixture.",
            "analysis_status": "already_close" if already_close else "insufficient_reference" if insufficient else "transfer_supported",
            "reference_profile": [{"attribute": a, "status": "observed", "observation": "Observed reference rendering.",
                "region": "whole image", "evidence_refs": ["appearance_reference"]} for a in DIMENSIONS],
            "candidate_deltas": deltas,
            "coverage": [{"attribute": a, "status": "targeted" if a == "skin_rendering" and deltas else "uncertain" if insufficient else "already_satisfied",
                "reason": "A/B observation supports this coverage state.", "delta_ids": ["d1"] if a == "skin_rendering" and deltas else []} for a in DIMENSIONS]}


def intent_fixture(*, already_close=False, insufficient=False):
    diagnosis = diagnosis_fixture(already_close=already_close, insufficient=insufficient)
    targets = []
    if diagnosis["candidate_deltas"]:
        d = diagnosis["candidate_deltas"][0]
        targets = [{"id": "t1", "delta_id": d["id"], "attribute": d["attribute"], "region": "source face",
                    "instruction": d["desired_change"], "priority": 1, "source_region": d["source_region"],
                    "reference_region": d["reference_region"], "source_observation": d["source_observation"],
                    "reference_observation": d["reference_observation"], "comparability": d["comparability"],
                    "uncertainty": d["uncertainty"], "mandatory": True,
                    "acceptance_criterion": "Natural warmer skin rendering without orange overcorrection or identity change.",
                    "evidence_refs": d["evidence_refs"]}]
    return {"schema_version": "hre_reference_intent_v1", "task_mode": "reference_enhance", "revision": 0,
            "targets": targets, "region_relations": [], "protected_content": diagnosis["protected_content"],
            "uncertainties": [], "summary": "Software-only target fixture.", "parent_intent_hash": None, "feedback_refs": [],
            "overall_status": "already_satisfied" if already_close else "insufficient_evidence" if insufficient else "ready_to_edit",
            "excluded_reference_traits": ["Do not copy B's expression or text."],
            "coverage": [{"attribute": c["attribute"], "status": c["status"], "reason": c["reason"],
                          "target_ids": ["t1"] if c["delta_ids"] else []} for c in diagnosis["coverage"]]}


def verification_fixture(intent=None):
    intent = intent or intent_fixture()
    return {"verdict": "accept", "issues": [], "preservation": "pass", "task_progress": "improved",
            "confidence": .9, "summary": "Synthetic judgment, not image-quality evidence.",
            "target_results": [{"id": t["id"], "status": "achieved", "observation": "Frozen target achieved in this fixture.",
                "evidence_refs": ["source", "appearance_reference", "candidate"], "remaining_gap": "None observed.",
                "suggested_correction": None} for t in intent["targets"]],
            "preservation_checks": [{"item": p, "status": "pass", "observation": "Source fact preserved in fixture.",
                "evidence_refs": ["source", "candidate"]} for p in intent["protected_content"]],
            "artifact_checks": [{"item": a, "status": "pass", "observation": "No observed defect in fixture.",
                "evidence_refs": ["source", "appearance_reference", "candidate"]} for a in sorted(retouch.ARTIFACT_CHECKS)]}


def request_fixture(stage, *, diagnosis=None, intent=None):
    diagnosis = diagnosis or diagnosis_fixture()
    intent = intent or intent_fixture()
    return {"workflow_contract": retouch.VERSION, "task_mode": "reference_enhance", "stage": stage,
            "context": {"diagnosis": diagnosis, "available_evidence_refs": ["source", "appearance_reference", "candidate", "verification:0:i1"],
                        "reference_contract": retouch.frozen_contract(intent), "previous_intent": intent,
                        "actionable_feedback_refs": ["verification:0:i1"]}}


def test_valid_diagnosis_and_composition_are_copied():
    diagnosis = diagnosis_fixture()
    assert retouch.validate_payload("diagnose", diagnosis, request_fixture("diagnose")) == diagnosis
    intent = intent_fixture()
    validated = retouch.validate_payload("compose", intent, request_fixture("compose"))
    assert validated == intent and validated is not intent


@pytest.mark.parametrize("section", ["coverage", "reference_profile"])
def test_diagnosis_requires_all_dimensions_once(section):
    payload = diagnosis_fixture()
    payload[section][-1] = deepcopy(payload[section][0])
    with pytest.raises(HREError):
        retouch.validate_payload("diagnose", payload, request_fixture("diagnose"))


@pytest.mark.parametrize("refs", [[], ["source"], ["appearance_reference"], ["source", "appearance_reference", "invented"]])
def test_delta_requires_available_source_and_reference_evidence(refs):
    payload = diagnosis_fixture()
    payload["candidate_deltas"][0]["evidence_refs"] = refs
    with pytest.raises(HREError):
        retouch.validate_payload("diagnose", payload, request_fixture("diagnose"))


@pytest.mark.parametrize("field,value", [("delta_id", "missing"), ("source_observation", "Invented A fact"),
    ("reference_observation", "Invented B fact"), ("source_region", "different object")])
def test_composition_must_trace_actual_diagnosed_difference(field, value):
    payload = intent_fixture()
    payload["targets"][0][field] = value
    with pytest.raises(HREError):
        retouch.validate_payload("compose", payload, request_fixture("compose"))


def test_composition_preserves_diagnosed_source_protection():
    payload = intent_fixture()
    payload["protected_content"] = ["Some unrelated protection."]
    with pytest.raises(HREError):
        retouch.validate_payload("compose", payload, request_fixture("compose"))


def test_more_than_three_supported_targets_are_allowed():
    payload = intent_fixture()
    for n in range(2, 6):
        target = deepcopy(payload["targets"][0])
        target.update(id=f"t{n}", priority=n)
        payload["targets"].append(target)
    next(c for c in payload["coverage"] if c["attribute"] == "skin_rendering")["target_ids"] = [t["id"] for t in payload["targets"]]
    assert len(retouch.validate_intent(payload, "reference_enhance")["targets"]) == 5


def test_already_satisfied_requires_actual_already_close_diagnosis():
    payload = intent_fixture(already_close=True)
    diagnosis = diagnosis_fixture(already_close=True)
    assert retouch.validate_payload("compose", payload, request_fixture("compose", diagnosis=diagnosis)) == payload
    with pytest.raises(HREError):
        retouch.validate_payload("compose", payload, request_fixture("compose"))
    diagnosis["analysis_status"] = "insufficient_reference"
    with pytest.raises(HREError):
        retouch.validate_payload("compose", payload, request_fixture("compose", diagnosis=diagnosis))


def test_insufficient_evidence_is_distinct_from_success():
    payload = intent_fixture(insufficient=True)
    assert retouch.validate_payload("compose", payload, request_fixture("compose", diagnosis=diagnosis_fixture(insufficient=True))) == payload
    payload["overall_status"] = "already_satisfied"
    with pytest.raises(HREError):
        retouch.validate_intent(payload, "reference_enhance")


def test_composition_rechecks_imported_already_close_evidence_consistency():
    diagnosis = diagnosis_fixture(already_close=True)
    diagnosis["coverage"][0]["status"] = "uncertain"
    payload = intent_fixture(already_close=True)
    with pytest.raises(HREError):
        retouch.validate_payload("compose", payload, request_fixture("compose", diagnosis=diagnosis))


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "unknown"])
def test_verification_target_coverage_is_exact(mutation):
    payload = verification_fixture()
    if mutation == "missing": payload["target_results"] = []
    elif mutation == "duplicate": payload["target_results"] *= 2
    else: payload["target_results"][0]["id"] = "invented"
    with pytest.raises(HREError):
        retouch.validate_payload("verify", payload, request_fixture("verify"))


@pytest.mark.parametrize("status", ["partial", "unmet", "uncertain"])
def test_accept_cannot_hide_a_required_target_failure(status):
    payload = verification_fixture()
    payload["target_results"][0]["status"] = status
    with pytest.raises(HREError):
        retouch.validate_payload("verify", payload, request_fixture("verify"))


def test_optional_target_failure_remains_visible_without_blocking_accept():
    intent = intent_fixture()
    optional = deepcopy(intent["targets"][0])
    optional.update(id="t2", priority=2, mandatory=False)
    intent["targets"].append(optional)
    next(c for c in intent["coverage"] if c["attribute"] == "skin_rendering")["target_ids"].append("t2")
    payload = verification_fixture(intent)
    payload["target_results"][1]["status"] = "partial"
    assert retouch.validate_payload("verify", payload, request_fixture("verify", intent=intent))["verdict"] == "accept"


@pytest.mark.parametrize("section", ["preservation_checks", "artifact_checks"])
def test_verification_requires_every_frozen_check(section):
    payload = verification_fixture()
    payload[section].pop()
    with pytest.raises(HREError):
        retouch.validate_payload("verify", payload, request_fixture("verify"))


@pytest.mark.parametrize("section,status", [("preservation_checks", "fail"), ("preservation_checks", "uncertain"),
                                        ("artifact_checks", "fail"), ("artifact_checks", "uncertain")])
def test_accept_cannot_override_content_or_artifact_failure(section, status):
    payload = verification_fixture()
    payload[section][0]["status"] = status
    with pytest.raises(HREError):
        retouch.validate_payload("verify", payload, request_fixture("verify"))


def test_feedback_can_change_execution_expression_but_not_frozen_goal():
    previous = intent_fixture()
    revised = deepcopy(previous)
    revised.update(revision=1, parent_intent_hash=digest(previous), feedback_refs=["verification:0:i1"])
    revised["targets"][0]["instruction"] += " Avoid pink overcorrection."
    payload = {"action": "revise", "reason": "Respond to observed residual.", "intent": revised}
    assert retouch.validate_payload("refine", payload, request_fixture("refine"))["intent"] == revised
    revised["targets"][0]["mandatory"] = False
    with pytest.raises(HREError):
        retouch.validate_payload("refine", payload, request_fixture("refine"))


@pytest.mark.parametrize("change", ["acceptance", "coverage", "protection", "reference_fact"])
def test_feedback_cannot_lower_acceptance_or_change_reference_facts(change):
    previous = intent_fixture()
    revised = deepcopy(previous)
    revised.update(revision=1, parent_intent_hash=digest(previous), feedback_refs=["verification:0:i1"])
    if change == "acceptance": revised["targets"][0]["acceptance_criterion"] = "Any warmer output is good."
    elif change == "coverage": revised["coverage"][0]["reason"] = "Ignore this after seeing output."
    elif change == "protection": revised["protected_content"].append("New benchmark requirement.")
    else: revised["targets"][0]["reference_observation"] = "Reference is pink."
    with pytest.raises(HREError):
        retouch.validate_payload("refine", {"action": "revise", "reason": "Synthetic", "intent": revised}, request_fixture("refine"))


def test_spec_is_opt_in_and_rejects_cross_task_or_unversioned_options():
    assert not retouch.enabled({})
    retouch.validate_spec({"task_mode": "restoration"})
    spec = {"workflow_contract": retouch.VERSION, "task_mode": "reference_enhance", "strategy": "shared"}
    retouch.validate_spec(spec)
    for mutation in [{"workflow_contract": "future"}, {"task_mode": "restoration"}, {"strategy": "native"},
                     {"delivery_requirements": {"minimum_native_size": [True, 200]}},
                     {"delivery_requirements": {"unrecognised": True}}]:
        with pytest.raises(HREError): retouch.validate_spec({**spec, **mutation})


def test_stage_instructions_distinguish_roles_and_no_change_path():
    text = retouch.stage_instruction(request_fixture("diagnose"))
    assert "already_close" in text and "appearance_reference" in text
    text = retouch.stage_instruction(request_fixture("verify"))
    assert "reference_contract" in text and "optional" in text


def test_detail_authenticity_is_an_independent_optional_observation():
    payload = verification_fixture()
    payload["detail_preservation"] = "uncertain"
    assert retouch.validate_payload("verify", payload, request_fixture("verify"))["verdict"] == "accept"
    payload["detail_preservation"] = "assumed_pass"
    with pytest.raises(HREError):
        retouch.validate_payload("verify", payload, request_fixture("verify"))
