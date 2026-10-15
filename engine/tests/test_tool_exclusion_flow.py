"""Synthetic state-machine checks; no desktop editing/real tool inference."""
import json

from hir_manual.service import Controller
from hir_manual.storage import read_json


def test_exclusion_reaches_composer_and_is_not_empty_evidence(tmp_path, photo, fixture_json):
    ctl=Controller(tmp_path)
    state=ctl.new(photo,"Conservative restoration",{"auto_local_tools":False})
    req=ctl.current_task(state.case_id)
    payload=fixture_json("diagnosis")
    payload["tool_plan"]=[{"tool":"T4_SEGMENTATION","reason":"Synthetic boundary-sensitive fixture"}]
    result=ctl.import_json(state.case_id,req.task_id,json.dumps(payload),"synthetic fixture only")
    assert result.accepted and ctl.inspect(state.case_id).workflow_status=="WAIT_EVIDENCE"
    state=ctl.operate(state.case_id,"skip_tool","T4_SEGMENTATION:Human-authorized no-T4 flow test")
    assert state.workflow_status=="WAIT_COMPOSITION" and state.deviated
    req=ctl.current_task(state.case_id)
    assert req.context["evidence"]==[] and req.context["unavailable_tools"]=={}
    assert req.context["excluded_tools"]["T4_SEGMENTATION"]["status"]=="excluded"
    assert "Human-authorized no-T4" in req.context["excluded_tools"]["T4_SEGMENTATION"]["reason"]
    frozen=read_json(ctl.case(state.case_id).path("tools/evidence_snapshot.json"))
    assert frozen["partial_evidence"] and frozen["consumed"]==[] and frozen["unavailable"]=={}
    assert frozen["excluded"]==req.context["excluded_tools"]
    prompt=ctl.case(state.case_id).path(req.prompt_file).read_text(encoding="utf-8")
    assert '"excluded"' in prompt and '"partial_evidence": true' in prompt
    assert len(req.allowed_assets)==1
    # A fresh process recovers the same immutable pending task and exclusion.
    resumed=Controller(tmp_path).current_task(state.case_id)
    assert resumed.task_id==req.task_id and resumed.context["excluded_tools"]==req.context["excluded_tools"]


def test_no_exclusion_keeps_complete_evidence_flag(tmp_path,photo,fixture_json):
    ctl=Controller(tmp_path);state=ctl.new(photo,"Conservative restoration",{"auto_local_tools":False})
    req=ctl.current_task(state.case_id);payload=fixture_json("diagnosis");payload["tool_plan"]=[]
    assert ctl.import_json(state.case_id,req.task_id,json.dumps(payload),"synthetic fixture only").accepted
    req=ctl.current_task(state.case_id)
    assert req.context["excluded_tools"]=={}
    assert not read_json(ctl.case(state.case_id).path("tools/evidence_snapshot.json"))["partial_evidence"]
