"""Decision protocol checks through the production stage entry point, with fake HTTP only."""
from copy import deepcopy
import json

import pytest

from hre.models import HREError
from hre.v3 import stages, stage_adapter
from hre.v3 import common
from hre.v3.common import digest
from test_v3_reference_contract import diagnosis_fixture, intent_fixture, request_fixture


def compact_diagnosis(full):
    value = {key: deepcopy(full[key]) for key in (
        "findings", "protected_content", "uncertainties", "tool_requests", "summary", "analysis_status")}
    for finding in value["findings"]:
        finding.pop("id")
    value["dimensions"] = {}
    for profile, coverage in zip(full["reference_profile"], full["coverage"]):
        attribute = profile["attribute"]
        value["dimensions"][attribute] = {
            "reference": {key: val for key, val in profile.items() if key != "attribute"},
            "deltas": [{key: val for key, val in delta.items() if key not in {"attribute", "id"}}
                       for delta in full["candidate_deltas"] if delta["attribute"] == attribute],
            "status": coverage["status"], "reason": coverage["reason"],
        }
    return value


def compact_intent(full):
    value = deepcopy(full)
    value.pop("protected_content")
    value["additional_protected_content"] = []
    for key in ("schema_version", "task_mode", "revision", "parent_intent_hash", "feedback_refs"):
        value.pop(key)
    for target in value["targets"]:
        for key in ("id", "priority", *stage_adapter.FACT_FIELDS, "uncertainty"):
            target.pop(key, None)
    value["coverage"] = {row["attribute"]: {"status": row["status"], "reason": row["reason"]}
                         for row in full["coverage"]}
    return value


def production(monkeypatch, stage, compact, request=None, finish="stop"):
    request = deepcopy(request or request_fixture(stage))
    request.update(stage=stage, stage_adapter=stage_adapter.VERSION, inputs=[], brief="Match B", request_id="fixture")
    request["stage_template"] = stages.stage_template(request)
    captured = {}
    def fake_chat(config, messages, response_schema):
        captured.update(schema=response_schema, messages=messages)
        return {"text": compact if isinstance(compact, str) else json.dumps(compact), "calls_attempted": 1, "calls_completed": 1,
                "finish_reason": finish, "raw_response": {"fixture": True}}
    monkeypatch.setattr(stages, "chat", fake_chat)
    return stages.run_stage(request, {}), captured, request


@pytest.mark.parametrize("version", [1, 2])
def test_diagnosis_round_trip_and_frozen_legacy(monkeypatch, version):
    full = diagnosis_fixture()
    full["schema_version"] = f"hre_reference_diagnosis_v{version}"
    request = request_fixture("diagnose")
    request["workflow_contract"] = f"reference_retouch_v{version}"
    result, captured, request = production(monkeypatch, "diagnose", compact_diagnosis(full), request)
    assert result["payload"] == full
    assert "dimensions" in captured["schema"]["anyOf"][0]["properties"]
    assert result["observation"]["decision_payload"] == compact_diagnosis(full)
    legacy = deepcopy(request)
    legacy.pop("stage_adapter")
    assert stages.stage_template(legacy)["version"] == f"hre_reference_retouch_stages_v{version}"


def test_compose_preserves_every_fact_and_criterion(monkeypatch):
    full = intent_fixture()
    result, _, _ = production(monkeypatch, "compose", compact_intent(full))
    assert result["payload"] == full


def test_compose_can_rely_on_inherited_evidence_without_reciting_it(monkeypatch):
    full = intent_fixture()
    compact = compact_intent(full)
    compact["targets"][0]["evidence_refs"] = []
    result, _, _ = production(monkeypatch, "compose", compact)
    assert result["payload"] == full


def test_target_uncertainty_remains_expressible_and_conditional_limits_are_frozen(monkeypatch):
    full = intent_fixture()
    diagnosis = diagnosis_fixture()
    full["targets"][0]["comparability"] = "comparable"
    diagnosis["candidate_deltas"][0]["comparability"] = "comparable"
    full["targets"][0]["uncertainty"] = "Check for excessive local warmth after editing."
    compact = compact_intent(full)
    compact["targets"][0]["uncertainty"] = full["targets"][0]["uncertainty"]
    result, _, _ = production(monkeypatch, "compose", compact, request_fixture("compose", diagnosis=diagnosis))
    assert result["payload"] == full
    compact = compact_intent(intent_fixture())
    compact["targets"][0]["uncertainty"] = "Conflicting correspondence claim"
    result, _, _ = production(monkeypatch, "compose", compact)
    assert result["payload"] is None


def test_duplicate_json_check_id_cannot_hide_a_conflicting_judgment(monkeypatch):
    from test_v3_reference_contract import verification_fixture
    compact = verification_fixture()
    for name, key in (("target_results", "id"), ("preservation_checks", "item"), ("artifact_checks", "item")):
        compact[name] = {row[key]: {k: v for k, v in row.items() if k != key} for row in compact[name]}
    raw = json.dumps(compact).replace('"t1": {', '"t1": {"status": "uncertain"}, "t1": {', 1)
    result, _, _ = production(monkeypatch, "verify", raw)
    assert result["payload"] is None
    assert "Duplicate JSON key" in result["error"]["message"]
    assert result["observation"]["text"] == raw


@pytest.mark.parametrize("mutation", ["missing_dimension", "false_satisfied", "invented_evidence"])
def test_decisions_cannot_hide_missing_or_contradictory_information(monkeypatch, mutation):
    compact = compact_diagnosis(diagnosis_fixture())
    if mutation == "missing_dimension":
        compact["dimensions"].pop("skin_rendering")
    elif mutation == "false_satisfied":
        compact["dimensions"]["skin_rendering"]["status"] = "already_satisfied"
    else:
        compact["dimensions"]["skin_rendering"]["deltas"][0]["evidence_refs"] = ["invented"]
    result, _, _ = production(monkeypatch, "diagnose", compact)
    assert result["payload"] is None and result["error"]


def test_compose_five_targets_and_unknown_delta(monkeypatch):
    compact = compact_intent(intent_fixture())
    compact["targets"] *= 5
    result, _, _ = production(monkeypatch, "compose", compact)
    assert [row["priority"] for row in result["payload"]["targets"]] == [1, 2, 3, 4, 5]
    compact["targets"][0]["delta_id"] = "unknown"
    result, _, _ = production(monkeypatch, "compose", compact)
    assert result["payload"] is None


def review_decisions(full):
    compact = compact_diagnosis(full)
    return {key: ({attribute: {"confirm_unchanged": True} for attribute in value} if key == "dimensions"
                  else {"confirm_unchanged": True}) for key, value in compact.items()}


def test_review_requires_explicit_confirmation_and_binds_actual_inputs(monkeypatch):
    full = diagnosis_fixture()
    full["schema_version"] = "hre_reference_diagnosis_v2"
    request = request_fixture("evidence_review")
    request["workflow_contract"] = "reference_retouch_v2"
    request["context"].update(initial_diagnosis=full, evidence={"records": []})
    compact = {"resolution": "resolved", "reason": "Reviewed every entry.",
               "effective_diagnosis": review_decisions(full)}
    result, _, _ = production(monkeypatch, "evidence_review", compact, request)
    assert result["payload"]["effective_diagnosis"] == full
    assert result["payload"]["initial_diagnosis_sha256"] == digest(full)
    compact["effective_diagnosis"]["dimensions"].pop("skin_rendering")
    result, _, _ = production(monkeypatch, "evidence_review", compact, request)
    assert result["payload"] is None


def test_completed_truncation_is_not_a_successful_document(monkeypatch):
    result, _, _ = production(monkeypatch, "diagnose", compact_diagnosis(diagnosis_fixture()), finish="length")
    assert result["error"]["code"] == "stage_output_truncated"
    assert result["observation"]["raw_response"] == {"fixture": True}


def test_adapter_template_is_frozen(monkeypatch):
    _, _, request = production(monkeypatch, "diagnose", compact_diagnosis(diagnosis_fixture()))
    request["stage_template"]["instruction"] += "tampered"
    with pytest.raises(HREError, match="stage_template_changed"):
        stages.run_stage(request, {})


def test_real_chat_request_carries_schema_and_stage_budgets(monkeypatch):
    compact = compact_diagnosis(diagnosis_fixture())
    request = request_fixture("diagnose")
    request.update(stage_adapter=stage_adapter.VERSION, inputs=[], brief="Match B", request_id="http-fixture")
    request["stage_template"] = stages.stage_template(request)
    calls = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self):
            return json.dumps({"choices": [{"message": {"content": json.dumps(compact)}, "finish_reason": "stop"}]}).encode()
    def fake_urlopen(http_request, timeout):
        calls.append((json.loads(http_request.data), timeout))
        return Response()
    monkeypatch.setattr(common, "urlopen", fake_urlopen)
    endpoint = {"base_url": "http://local.invalid/v1", "model": "fixture-vlm", "response_format": "json_object",
                "settings": {"temperature": .1, "max_tokens": 9000},
                "stage_overrides": {"diagnose": {"response_format": "json_schema", "timeout_seconds": 321,
                    "settings": {"max_tokens": 12000, "thinking_token_budget": 4000,
                                 "chat_template_kwargs": {"enable_thinking": True}}}}}
    result = stages.run_stage(request, endpoint)
    assert result["payload"] == diagnosis_fixture()
    body, timeout = calls[0]
    assert len(calls) == 1 and timeout == 321
    assert body["max_tokens"] == 12000 and body["temperature"] == .1
    assert body["thinking_token_budget"] == 4000 and body["chat_template_kwargs"]["enable_thinking"] is True
    assert body["response_format"]["json_schema"]["schema"] == request["stage_template"]["response_schema"]
    assert result["observation"]["response_schema_sha256"] == digest(body["response_format"]["json_schema"]["schema"])


def test_empty_truncated_http_answer_keeps_completed_observation(monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self):
            return b'{"choices":[{"message":{"content":""},"finish_reason":"length"}]}'
    monkeypatch.setattr(common, "urlopen", lambda *args, **kwargs: Response())
    request = request_fixture("diagnose")
    request.update(stage_adapter=stage_adapter.VERSION, inputs=[], brief="Match B", request_id="truncated")
    result = stages.run_stage(request, {"base_url": "http://local.invalid/v1", "model": "fixture"})
    assert result["error"]["code"] == "stage_output_truncated"
    assert result["observation"]["calls_completed"] == result["observation"]["calls_attempted"] == 1


@pytest.mark.parametrize("message", [{"content": None, "reasoning_content": "long reasoning"},
                                     {"reasoning_content": "long reasoning"}])
def test_reasoning_only_truncation_keeps_raw_usage_and_completed_charge(monkeypatch, message):
    response = {"choices": [{"message": message, "finish_reason": "length"}], "usage": {"completion_tokens": 12000}}
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self): return json.dumps(response).encode()
    monkeypatch.setattr(common, "urlopen", lambda *args, **kwargs: Response())
    request = request_fixture("diagnose")
    request.update(stage_adapter=stage_adapter.VERSION, inputs=[], brief="Match B", request_id="reasoning-only")
    result = stages.run_stage(request, {"base_url": "http://local.invalid/v1", "model": "fixture"})
    assert result["error"]["code"] == "stage_output_truncated"
    assert result["observation"]["calls_completed"] == 1
    assert result["observation"]["raw_response"] == response
    assert result["observation"]["usage"] == response["usage"]


def test_image_not_observed_has_a_valid_constrained_schema_branch(monkeypatch):
    from jsonschema import Draft202012Validator
    error = {"error": {"code": "image_not_observed", "message": "Image was inaccessible"}}
    result, captured, request = production(monkeypatch, "diagnose", error)
    Draft202012Validator(captured["schema"]).validate(error)
    assert result["payload"] is None and result["error"] == error["error"]
    for stage in ("compose", "evidence_review", "audit_condition"):
        request = request_fixture(stage)
        request["workflow_contract"] = "reference_retouch_v2"
        request["stage_adapter"] = stage_adapter.VERSION
        template = stages.stage_template(request)
        assert "Bind initial_diagnosis_sha256" not in template["instruction"]
        assert "Use revision=0" not in template["instruction"]
        assert "binding the supplied condition_sha256" not in template["instruction"]
        Draft202012Validator(template["response_schema"]).validate(error)


@pytest.mark.parametrize("stage", [
    {"stage_overrides": {"diagnosis": {"settings": {"max_tokens": 12000}}}},
    {"stage_overrides": {"compose": {"settings": {"thinking_token_budget": -1}}}},
    {"stage_overrides": {"verify": {"timeout_seconds": 0}}},
])
def test_bad_stage_configuration_is_rejected_before_creating_case(tmp_path, stage):
    from hre.v3.contracts import create_case
    from test_v3_reference_runner import spec
    with pytest.raises(HREError):
        create_case(tmp_path / "case", spec(), {"stage": stage})
    assert not (tmp_path / "case").exists()


@pytest.mark.parametrize("close,insufficient", [(True, False), (False, True)])
def test_no_edit_and_insufficient_evidence_remain_distinct(monkeypatch, close, insufficient):
    diagnosis = diagnosis_fixture(already_close=close, insufficient=insufficient)
    intent = intent_fixture(already_close=close, insufficient=insufficient)
    result, _, _ = production(monkeypatch, "compose", compact_intent(intent), request_fixture("compose", diagnosis=diagnosis))
    assert result["payload"] == intent


def test_verify_uses_fixed_identity_checks_without_assigning_visual_success(monkeypatch):
    from test_v3_reference_contract import verification_fixture
    full = verification_fixture()
    compact = deepcopy(full)
    for name, key in (("target_results", "id"), ("preservation_checks", "item"), ("artifact_checks", "item")):
        compact[name] = {row[key]: {k: v for k, v in row.items() if k != key} for row in full[name]}
    result, _, _ = production(monkeypatch, "verify", compact)
    assert result["payload"] == full
    compact["target_results"]["t1"]["status"] = "uncertain"
    result, _, _ = production(monkeypatch, "verify", compact)
    assert result["payload"] is None
    compact["target_results"] = {}
    result, _, _ = production(monkeypatch, "verify", compact)
    assert result["payload"] is None


def test_review_replacement_cannot_drop_a_source_protection(monkeypatch):
    full = diagnosis_fixture()
    full["schema_version"] = "hre_reference_diagnosis_v2"
    request = request_fixture("evidence_review")
    request["workflow_contract"] = "reference_retouch_v2"
    request["context"].update(initial_diagnosis=full, evidence={"records": []})
    review = review_decisions(full)
    review["protected_content"] = {"replace": ["Different protection"]}
    result, _, _ = production(monkeypatch, "evidence_review", {
        "resolution": "resolved", "reason": "Reviewed", "effective_diagnosis": review}, request)
    assert result["payload"] is None


@pytest.mark.parametrize("version,close", [(1, True), (2, True), (1, False), (2, False)])
def test_controller_calls_real_stage_path_and_accounts_once(tmp_path, monkeypatch, version, close):
    from PIL import Image
    from hre.v3 import runner
    from hre.v3.contracts import create_case
    from hre.storage import read_json
    from test_v3_reference_runner import spec, ReferenceWorkers
    from test_v3_reference_v2 import UnifiedWorkers
    for name in ("A", "B"):
        Image.new("RGB", (32, 32)).save(tmp_path / (name + ".png"))
    task = {**spec(), "workflow_contract": f"reference_retouch_v{version}",
            "stage_adapter": stage_adapter.VERSION, "source": {"path": str(tmp_path / "A.png")},
            "reference": {"path": str(tmp_path / "B.png")}}
    config = {"stage": {"base_url": "http://local.invalid/v1", "model": "fixture"},
              "models": {"qwen21": {"compiler": {"backend": "direct"}, "editor": {"model_id": "Qwen/Qwen-Image-2.1"}}}}
    root = tmp_path / "case"
    create_case(root, task, config)
    workers = (UnifiedWorkers if version == 2 else ReferenceWorkers)(close=close)
    workers.diagnosis["schema_version"] = f"hre_reference_diagnosis_v{version}"
    workers.intent["schema_version"] = f"hre_reference_intent_v{version}"
    actual_run = stages.run_stage
    calls = []
    def run_with_fake_http(request, endpoint):
        payload = workers.stage(request)["payload"]
        stage = request["stage"]
        if stage == "diagnose": decisions = compact_diagnosis(payload)
        elif stage == "compose": decisions = compact_intent(payload)
        elif stage == "evidence_review":
            decisions = {"resolution": "resolved", "reason": payload["reason"],
                         "effective_diagnosis": review_decisions(payload["effective_diagnosis"])}
        elif stage == "verify":
            decisions = deepcopy(payload)
            decisions.pop("overall_style", None)
            decisions.pop("whole_image_review_sha256", None)
            for name, key in (("target_results", "id"), ("preservation_checks", "item"), ("artifact_checks", "item")):
                decisions[name] = {row[key]: {k: v for k, v in row.items() if k != key} for row in payload[name]}
        else:
            decisions = payload
        def fake_chat(*args, **kwargs):
            calls.append(stage)
            return {"text": json.dumps(decisions), "calls_attempted": 1, "calls_completed": 1}
        monkeypatch.setattr(stages, "chat", fake_chat)
        return actual_run(request, endpoint)
    monkeypatch.setattr(runner, "run_stage", run_with_fake_http)
    state = runner.run_case(root, compile_fn=workers.compile, execute_fn=workers.execute)
    assert state["success"] and len(workers.executions) == (0 if close else 1)
    expected = ["diagnose", "compose"] if version == 1 else ["diagnose", "evidence_review", "compose"]
    if not close:
        expected += (["whole_image_review"] if version == 2 else []) + ["verify"]
    assert calls == expected
    assert state["budget"]["stage_calls"] == len(calls)
    assert runner.run_case(root)["budget"]["stage_calls"] == len(calls)
    for name in calls:
        archived = read_json(root / "operations" / f"stage-{name}-r000-a000" / "request.json")
        if name in stage_adapter.STAGES:
            assert archived["stage_template"]["version"].endswith(stage_adapter.VERSION)


def test_audit_binds_condition_and_requires_each_target(monkeypatch):
    request = request_fixture("audit_condition")
    request["workflow_contract"] = "reference_retouch_v2"
    request["context"]["condition_sha256"] = "actual-condition"
    payload = {"target_results": {"t1": {"status": "covered", "observation": "Inspected all target constraints"}},
               "protections": "covered", "exclusions": "covered", "reason": "Inspected the actual native edit fields"}
    result, _, _ = production(monkeypatch, "audit_condition", payload, request)
    assert result["payload"]["condition_sha256"] == "actual-condition"
    payload["target_results"] = {}
    result, _, _ = production(monkeypatch, "audit_condition", payload, request)
    assert result["payload"] is None


def test_review_can_add_a_dimension_delta_without_losing_other_facts(monkeypatch):
    full = diagnosis_fixture()
    full["schema_version"] = "hre_reference_diagnosis_v2"
    request = request_fixture("evidence_review")
    request["workflow_contract"] = "reference_retouch_v2"
    request["context"].update(initial_diagnosis=full, evidence={"records": []})
    review = review_decisions(full)
    dimension = compact_diagnosis(full)["dimensions"]["neutral_balance"]
    dimension["status"] = "targeted"
    dimension["reason"] = "Fresh evidence supports a separate background cast."
    delta = deepcopy(compact_diagnosis(full)["dimensions"]["skin_rendering"]["deltas"][0])
    delta.update(source_region="background", reference_region="background", desired_change="Reduce background yellow cast.")
    dimension["deltas"] = [delta]
    review["dimensions"]["neutral_balance"] = {"replace": dimension}
    result, _, _ = production(monkeypatch, "evidence_review", {
        "resolution": "resolved", "reason": "New background evidence", "effective_diagnosis": review}, request)
    effective = result["payload"]["effective_diagnosis"]
    assert effective["candidate_deltas"][0] == {"id": "d1", "attribute": "neutral_balance", **delta}
    original_skin = full["candidate_deltas"][0]
    assert effective["candidate_deltas"][1] == {**original_skin, "id": "d2"}
    assert next(row for row in effective["coverage"] if row["attribute"] == "skin_rendering")["delta_ids"] == ["d2"]
    assert request["context"]["initial_diagnosis"] == full


def test_task_option_is_validated_and_bound_into_request():
    from hre.v3.contracts import normalise_spec
    from hre.v3.runner import _stage_request
    from test_v3_reference_runner import spec
    task = normalise_spec({**spec(), "stage_adapter": stage_adapter.VERSION})
    request = _stage_request(task, {"inputs": [], "canvas": {}}, "diagnose", {
        "available_evidence_refs": ["source", "appearance_reference"]})
    assert request["stage_adapter"] == stage_adapter.VERSION
    assert request["stage_template"]["version"].endswith(stage_adapter.VERSION)
    with pytest.raises(HREError, match="stage_adapter_invalid"):
        normalise_spec({**spec(), "stage_adapter": "unknown"})


@pytest.mark.parametrize("kwargs", [{"thinking_token_budget": -1}, {"thinking_token_budget": True}, {"chat_template_kwargs": []}])
def test_invalid_reasoning_settings_rejected_before_http(monkeypatch, kwargs):
    def forbidden(*args, **kw): raise AssertionError("Should reject before HTTP")
    monkeypatch.setattr(common, "urlopen", forbidden)
    with pytest.raises(HREError, match="unsupported_chat_setting"):
        common.chat({"base_url": "http://local.invalid/v1", "model": "fixture", "settings": kwargs}, [])
