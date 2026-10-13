from copy import deepcopy
import pytest
from hre.selection import evaluate_candidate, select_final


def verified(round=0, style="improved", confidence=.7):
    return {"candidate_id": f"c{round}", "round": round, "asset": {"asset_id": f"raw{round}"},
            "geometry": {"status": "pass", "derived_asset": None}, "duplicate_of": None,
            "verification": {"style_alignment": style, "content_preservation": "pass", "critical_defects": [],
                             "confidence": confidence, "remaining_issues": [], "retry_focus": [],
                             "style_observations": [{"dimension": "brightness", "a_to_c_change": "brighter", "c_vs_b": "closer", "comparability": "comparable", "confidence": .8}],
                             "preservation_observations": [{"kind": k, "observation": "preserved or explicitly absent", "status": "pass", "confidence": .8} for k in ["composition", "geometry", "identity", "text", "scene_content"]]}}


def test_earliest_accepted_not_confidence_sort_and_derived_mapping():
    first = verified(0, confidence=.7)
    first["geometry"]["derived_asset"] = {"asset_id": "normalized0"}
    result = select_final([verified(1, confidence=.99), first], {"asset_id": "A"})
    assert result["success"] is True
    assert result["selection"]["asset_id"] == "normalized0"
    assert result["selection"]["selected_round"] == 0


def test_usable_review_then_baseline_fallback():
    c = verified(style="unchanged")
    assert select_final([c], {"asset_id": "A"})["selection"]["review_required"] is True
    c["verification"]["confidence"] = .699
    result = select_final([c], {"asset_id": "A"})
    assert result["success"] is False
    assert result["selection"]["fallback"] is True


@pytest.mark.parametrize("change", ["missing", "duplicate", "contradiction", "defect", "no_comparable_style"])
def test_contradictory_or_missing_verification_rejected(change):
    c = deepcopy(verified())
    v = c["verification"]
    if change == "missing": v["preservation_observations"].pop()
    if change == "duplicate": v["preservation_observations"].append(v["preservation_observations"][0])
    if change == "contradiction": v["preservation_observations"][0]["status"] = "fail"
    if change == "defect": v["critical_defects"] = [{"kind": "identity_change", "observation": "face", "region_in_a": None, "confidence": .9}]
    if change == "no_comparable_style": v["style_observations"][0]["comparability"] = "unknown"
    with pytest.raises(ValueError): evaluate_candidate(c)


def test_content_fail_and_geometry_uncertain_never_usable():
    c = verified()
    c["verification"]["content_preservation"] = "fail"
    c["verification"]["preservation_observations"][0]["status"] = "fail"
    assert evaluate_candidate(c)["accepted"] is False
    c = verified()
    c["geometry"]["status"] = "uncertain"
    assert evaluate_candidate(c)["usable"] is False
