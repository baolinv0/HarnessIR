"""Synthetic contract regressions; these tests make no visual quality claims."""
from copy import deepcopy
import pytest

from hre.reference_core.contracts import DIMENSIONS, validate_semantics
from hre.reference_core.rendering import render_target_limits
from hre.reference_core.delivery import assess_delivery, preflight


def semantics():
    target = dict(target_id="tone", attribute="shadow_midtone_highlight",
        source_observation="A has dark midtones", reference_observation="B has open midtones",
        comparability="conditional", uncertainty="different illumination; preserve A light direction",
        mandatory=True, acceptance_criterion="open midtones without clipped highlights")
    return dict(targets=[target], coverage=[dict(attribute=d, status="targeted" if d==target["attribute"] else "preserve",
        reason="observed", target_ids=["tone"] if d==target["attribute"] else []) for d in sorted(DIMENSIONS)],
        delivery_requirements={})


@pytest.mark.parametrize("mutation", [
    lambda s:s["coverage"].pop(),
    lambda s:s["coverage"].append(deepcopy(s["coverage"][0])),
    lambda s:s["targets"][0].update(attribute="neutral_balance"),
    lambda s:s["targets"][0].pop("acceptance_criterion"),
    lambda s:s["targets"][0].update(comparability="unknown", mandatory=False),
    lambda s:s["targets"][0].update(comparability="incomparable", mandatory=False),
    lambda s:s["targets"][0].update(uncertainty=""),
    lambda s:s["delivery_requirements"].update(minimum_native_size=[True,32]),
])
def test_semantics_rejects_unsupported_or_lost_constraints(mutation):
    spec=semantics(); mutation(spec)
    with pytest.raises(ValueError): validate_semantics(spec)


def test_semantics_and_rendering_preserve_independent_facts_and_limits():
    spec=semantics(); assert validate_semantics(spec)==spec
    text=render_target_limits(spec["targets"][0])
    for phrase in ("A has dark midtones","B has open midtones","different illumination", "Mandatory: true",
                   "open midtones without clipped highlights"):
        assert phrase in text


def test_native_content_and_noop_require_actual_size():
    assert not assess_delivery([64,64],[32,32],{})["pass"]
    assert assess_delivery([64,64],[64,64],{},detail="pass")["pass"]
    assert not assess_delivery([64,64],[64,64],{"require_detail_pass":True})["pass"]
    assert preflight([64,64],[32,32],{})["status"]=="infeasible"
    assert preflight([64,64],None,{},capability_known=False)["status"]=="unknown"
    with pytest.raises(ValueError): preflight([64,64],[float("nan"),64],{})


def test_normalized_feedback_binds_candidate_and_pending_precedes_correction():
    from hre.reference_core.feedback import normalize_feedback
    contract={"targets":[{"target_id":"x","mandatory":True},{"target_id":"y","mandatory":True}]}
    verification={"target_results":[dict(target_id="x",status="uncertain",observation="Need actual evidence",review_action="gather_evidence",evidence_refs=["C"]),
        dict(target_id="y",status="unmet",observation="Observed gap",suggested_correction="Fix observed gap",evidence_refs=["A","B","C"])],
        "preservation_checks":[],"artifact_checks":[]}
    result=normalize_feedback(contract,verification,candidate_id="c0",round_index=0)
    assert result["action"]=="gather_evidence" and result["candidate_id"]=="c0"
    assert normalize_feedback(contract,verification,candidate_id="c0",round_index=0,delivery={"status":"fail","pass":False})["action"]=="stop"
    with pytest.raises(ValueError):normalize_feedback(contract,verification,candidate_id="c0",round_index=True)


def test_known_damage_rejects_even_when_whole_frame_calibration_unknown():
    from hre.reference_core.holistic import verdict_gate
    from unified_fixtures import whole_fixture
    value=whole_fixture({})
    value["overall_style"]["color"].update(reference_status="uncertain",relation="uncertain",magnitude="unknown",confidence="unknown")
    value["preservation"]["identity"]["status"]="fail"
    assert verdict_gate(value)=="reject"
