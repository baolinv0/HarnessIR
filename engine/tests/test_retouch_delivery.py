"""Delivery gates use native pixels; synthetic images do not assess model quality."""
from copy import deepcopy
import pytest

from hre.retouch.contracts import RetouchError
from hre.retouch.workflow import Workbench, read_json, write_json
from test_retouch_workbench import analysis, contract, picture, verification


@pytest.mark.parametrize("analysis_status,pending_delta,coverage_state", [
    ("insufficient_reference", False, "already_satisfied"),
    ("transfer_supported", True, "already_satisfied"),
    ("already_close", True, "already_satisfied"),
    ("already_close", False, "uncertain")])
def test_no_change_success_cannot_override_unresolved_diagnostic_evidence(tmp_path, analysis_status, pending_delta, coverage_state):
    workbench = Workbench(tmp_path / "cases")
    case = workbench.create({"source_data": picture(), "reference_data": picture(), "brief": "Match B appearance."})
    value = analysis()
    value["analysis_status"] = analysis_status
    if not pending_delta: value["candidate_deltas"] = []
    for row in value["coverage"]: row["status"] = coverage_state
    workbench.import_stage(case["id"], "diagnose", value)
    target = contract()
    target.update(targets=[], overall_status="already_satisfied")
    for row in target["coverage"]: row.update(status="already_satisfied", target_ids=[])
    with pytest.raises(RetouchError):
        workbench.import_stage(case["id"], "compose", target)


def test_insufficient_diagnosis_cannot_enter_editing(tmp_path):
    workbench = Workbench(tmp_path / "cases")
    case = workbench.create({"source_data": picture(), "reference_data": picture(), "brief": "Match B appearance."})
    value = analysis()
    value["analysis_status"] = "insufficient_reference"
    workbench.import_stage(case["id"], "diagnose", value)
    with pytest.raises(RetouchError): workbench.import_stage(case["id"], "compose", contract())


@pytest.mark.parametrize("items", [["unrelated check"], ["naturalness"], ["naturalness", "reference_content_leakage"]])
def test_new_case_cannot_replace_required_artifact_checks_with_arbitrary_passes(tmp_path, items):
    workbench, case_id = prepared(tmp_path)
    candidate(workbench, case_id)
    value = verification()
    value["artifact_checks"] = [{"item": item, "status": "pass", "observation": "Synthetic software control.",
                                 "evidence_refs": ["A", "B", "C"]} for item in items]
    with pytest.raises(RetouchError): workbench.import_stage(case_id, "verify", value)


@pytest.mark.parametrize("change", ["missing_delta", "fake_reference", "source_only", "wrong_region"])
def test_new_composition_rejects_untraced_reference_facts_without_freezing(tmp_path, change):
    workbench = Workbench(tmp_path / "cases")
    case = workbench.create({"source_data": picture(), "reference_data": picture(), "brief": "Match B appearance."})
    workbench.import_stage(case["id"], "diagnose", analysis())
    before = (workbench._dir(case["id"]) / "state.json").read_bytes()
    value = contract()
    if change == "missing_delta": value["targets"][0]["delta_id"] = "invented"
    elif change == "fake_reference": value["targets"][0]["reference_observation"] = "Invented pink reference."
    elif change == "wrong_region": value["targets"][0]["reference_region"] = "unrelated background"
    else: value["targets"][0]["evidence_refs"] = ["A"]
    with pytest.raises(RetouchError): workbench.import_stage(case["id"], "compose", value)
    assert (workbench._dir(case["id"]) / "state.json").read_bytes() == before
    assert workbench._load(case["id"])["contract"] is None


def test_new_diagnosis_rejects_duplicate_difference_ids_without_writing(tmp_path):
    workbench = Workbench(tmp_path / "cases")
    case = workbench.create({"source_data": picture(), "reference_data": picture(), "brief": "Match B appearance."})
    value = analysis()
    value["candidate_deltas"].append(deepcopy(value["candidate_deltas"][0]))
    with pytest.raises(RetouchError): workbench.import_stage(case["id"], "diagnose", value)
    assert workbench._load(case["id"])["analysis"] is None


@pytest.mark.parametrize("section,refs", [("target_results", ["A", "C"]), ("preservation_checks", ["C"]),
    ("artifact_checks", ["C"])])
def test_new_verification_requires_role_specific_evidence_and_preserves_waiting_candidate(tmp_path, section, refs):
    workbench, case_id = prepared(tmp_path)
    candidate(workbench, case_id)
    value = verification()
    value[section][0]["evidence_refs"] = refs
    with pytest.raises(RetouchError): workbench.import_stage(case_id, "verify", value)
    saved = workbench._load(case_id)
    assert saved["phase"] == "verify" and saved["verification"] is None


def test_new_verify_rejects_duplicate_fixed_artifact_id(tmp_path):
    workbench, case_id = prepared(tmp_path)
    candidate(workbench, case_id)
    value = verification()
    value["artifact_checks"][2] = deepcopy(value["artifact_checks"][0])
    with pytest.raises(RetouchError): workbench.import_stage(case_id, "verify", value)


def test_new_stage_requests_describe_the_strict_lineage_and_artifact_contract(tmp_path):
    workbench, case_id = prepared(tmp_path)
    request = workbench.export(case_id, "compose")
    assert "delta_id" in request["instruction"] and "analysis_status=already_close" in request["instruction"]
    candidate(workbench, case_id)
    request = workbench.export(case_id, "verify")
    for required in ("naturalness", "reference_content_leakage", "unsupported_detail", "A/B/C"):
        assert required in request["instruction"]


def test_legacy_analysis_and_composition_can_resume_without_new_difference_fields(tmp_path):
    workbench = Workbench(tmp_path / "cases")
    case = workbench.create({"source_data": picture(), "reference_data": picture(), "brief": "Legacy task"})
    saved = workbench._load(case["id"])
    saved.pop("acceptance_version");saved.pop("delivery_requirements")
    write_json(workbench._dir(case["id"]) / "state.json", saved)
    old_analysis = analysis()
    old_analysis["candidate_deltas"] = [{"attribute": "brightness", "desired_change": "提亮脸部", "evidence_refs": ["A", "B"]}]
    for row in old_analysis["coverage"]: row["status"] = "observed"
    workbench.import_stage(case["id"], "diagnose", old_analysis)
    old_contract = contract()
    for target in old_contract["targets"]: target.pop("delta_id")
    result = workbench.import_stage(case["id"], "compose", old_contract)
    assert result["phase"] == "edit" and "acceptance_version" not in workbench._load(case["id"])


def prepared(tmp_path, requirements=None):
    workbench = Workbench(tmp_path / "cases")
    request = {"source_data": picture(), "reference_data": picture((160, 150, 120)), "brief": "Match the supported reference appearance."}
    if requirements is not None:
        request["delivery_requirements"] = requirements
    case = workbench.create(request)
    workbench.import_stage(case["id"], "diagnose", analysis())
    workbench.import_stage(case["id"], "compose", contract())
    return workbench, case["id"]


def candidate(workbench, case_id, size=(96, 128)):
    kwargs = {} if size == (96, 128) else {"external_geometry": {"policy": "full_frame_resize", "source_frame_confirmed": True}}
    return workbench.candidate(case_id, picture(size=size), "unknown", **kwargs)


def test_new_case_freezes_explicit_delivery_defaults(tmp_path):
    workbench, case_id = prepared(tmp_path)
    saved = workbench._load(case_id)
    assert saved["acceptance_version"] == "reference_retouch_delivery_v2"
    assert saved["delivery_requirements"] == {"require_native_source_resolution": True, "require_detail_pass": False}


def test_visual_pass_cannot_hide_native_resolution_failure(tmp_path):
    workbench, case_id = prepared(tmp_path)
    candidate(workbench, case_id, (48, 64))
    result = workbench.import_stage(case_id, "verify", verification())
    assert result["status"] == "delivery_not_met" and result["phase"] == "report"
    assert result["appearance_status"] == "accept"
    assert result["delivery_assessment"]["status"] == "fail"
    assert result["delivery_assessment"]["native_size"] == [48, 64]
    assert result["delivery_assessment"]["delivered_size"] == [96, 128]
    assert result["rounds"][-1]["appearance_status"] == "accept"
    assert result["rounds"][-1]["status"] == "delivery_not_met"
    assert next(s for s in result["stages"] if s["id"] == "report")["status"] == "completed"
    with pytest.raises(RetouchError):
        workbench.import_stage(case_id, "refine", {"action": "revise", "correction": "Try again", "feedback_refs": ["verification:skin_color"]})


def test_native_source_resolution_passes_the_frozen_delivery_gate(tmp_path):
    workbench, case_id = prepared(tmp_path)
    candidate(workbench, case_id)
    result = workbench.import_stage(case_id, "verify", verification())
    assert result["status"] == "accepted"
    assert result["appearance_status"] == "accept"
    assert result["delivery_assessment"]["status"] == "pass"
    assert result["delivery_assessment"]["required_native_size"] == [96, 128]


def test_declared_preview_delivery_can_accept_lower_native_resolution(tmp_path):
    workbench, case_id = prepared(tmp_path, {"require_native_source_resolution": False, "minimum_native_size": [48, 64]})
    candidate(workbench, case_id, (48, 64))
    result = workbench.import_stage(case_id, "verify", verification())
    assert result["status"] == "accepted"
    assert result["delivery_assessment"]["required_native_size"] == [48, 64]


@pytest.mark.parametrize("detail,expected", [(None, "uncertain"), ("uncertain", "uncertain"), ("fail", "fail"), ("pass", "pass")])
def test_required_native_detail_is_never_inferred_from_artifact_pass(tmp_path, detail, expected):
    workbench, case_id = prepared(tmp_path, {"require_detail_pass": True})
    candidate(workbench, case_id)
    value = verification()
    if detail is not None:
        value["detail_preservation"] = detail
    result = workbench.import_stage(case_id, "verify", value)
    assert result["delivery_assessment"]["detail_preservation"] == expected
    assert result["status"] == ("accepted" if detail == "pass" else "delivery_not_met")


def test_legacy_case_retains_accepted_semantics_and_get_does_not_write(tmp_path):
    workbench, case_id = prepared(tmp_path)
    candidate(workbench, case_id, (48, 64))
    saved = workbench._load(case_id)
    for key in ("acceptance_version", "delivery_requirements", "appearance_status", "delivery_assessment"):
        saved.pop(key, None)
    for row in saved["rounds"]:
        for key in ("appearance_status", "delivery_assessment"):
            row.pop(key, None)
    path = workbench._dir(case_id) / "state.json"
    write_json(path, saved)
    historical_observation = verification()
    historical_observation["artifact_checks"] = [{"item": "旧版综合自然度检查", "status": "pass", "observation": "历史观察", "evidence_refs": ["C"]}]
    result = workbench.import_stage(case_id, "verify", historical_observation)
    assert result["status"] == "accepted"
    before = path.read_bytes()
    projected = workbench.get(case_id)
    assert projected["status"] == "accepted"
    assert projected["delivery_assessment"]["status"] == "not_frozen"
    assert projected["delivery_assessment"]["native_size"] == [48, 64]
    assert path.read_bytes() == before
    assert "acceptance_version" not in read_json(path)
    assert "delivery_assessment" not in read_json(path)


def test_native_png_is_checked_instead_of_claimed_geometry(tmp_path):
    workbench, case_id = prepared(tmp_path)
    candidate(workbench, case_id, (48, 64))
    saved = workbench._load(case_id)
    saved["rounds"][-1]["candidate_geometry"]["native_size"] = [96, 128]
    write_json(workbench._dir(case_id) / "state.json", saved)
    result = workbench.import_stage(case_id, "verify", verification())
    assert result["delivery_assessment"]["native_size"] == [48, 64]
    assert result["status"] == "delivery_not_met"


def test_missing_native_file_cannot_be_certified_from_resized_candidate(tmp_path):
    workbench, case_id = prepared(tmp_path)
    imported = candidate(workbench, case_id)
    native_name = imported["rounds"][-1]["native_url"].rsplit("/", 1)[-1]
    (workbench._dir(case_id) / "assets" / native_name).unlink()
    result = workbench.import_stage(case_id, "verify", verification())
    assert result["appearance_status"] == "accept"
    assert result["status"] == "delivery_not_met"
    assert result["delivery_assessment"]["size_status"] == "uncertain"


def test_verify_receives_native_image_and_frozen_requirements(tmp_path):
    workbench, case_id = prepared(tmp_path, {"require_detail_pass": True})
    candidate(workbench, case_id)
    request = workbench.export(case_id, "verify")
    assert [row["role"] for row in request["images"]] == ["source", "appearance_reference", "candidate", "candidate_native"]
    assert request["context"]["delivery_requirements"]["require_detail_pass"] is True
    assert "candidate_native" in request["context"]["available_evidence_refs"]
    assert "detail_preservation" in request["instruction"]
    assert "prompt" not in request["context"]


@pytest.mark.parametrize("requirements", [None, [], {"require_native_source_resolution": 1}, {"require_detail_pass": "yes"},
    {"minimum_native_size": [True, 128]}, {"minimum_native_size": [96, 0]}, {"minimum_native_size": [96.0, 128]},
    {"minimum_native_size": [96]}, {"unexpected": True}])
def test_invalid_delivery_requirement_types_are_rejected_before_case_creation(tmp_path, requirements):
    workbench = Workbench(tmp_path / "cases")
    with pytest.raises(RetouchError):
        workbench.create({"source_data": picture(), "reference_data": picture(), "brief": "Match appearance", "delivery_requirements": requirements})
    assert workbench.list() == []
