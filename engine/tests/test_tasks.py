import pytest
from hir_manual.prompts import render_prompt
from hir_manual.service import Controller
from hir_manual.storage import CasePaths, read_json


def test_strict_template_variables():
    with pytest.raises(Exception):
        render_prompt("diagnose", {})


def test_explicit_original_upload_is_pixel_identical_and_executor_only(tmp_path,photo,fixture_json):
    ctl=Controller(tmp_path)
    state=ctl.new(photo,'synthetic desktop transport',{'desktop_original_rgb_equivalent_upload':True})
    req=ctl.current_task(state.case_id);payload=fixture_json('diagnosis');payload['tool_plan']=[]
    assert ctl.import_json(state.case_id,req.task_id,payload,'synthetic fixture').accepted
    req=ctl.current_task(state.case_id)
    assert req.allowed_assets[0].path=='input/canonical.png'  # Composer unchanged.
    assert ctl.import_json(state.case_id,req.task_id,fixture_json('composition'),'synthetic fixture').accepted
    req=ctl.current_task(state.case_id)
    assert [a.path for a in req.allowed_assets]==['input/original.png']
    transport=req.context['original_upload_transport']
    assert not transport['reencoded'] and not transport['resized']
    assert transport['canonical_sha256']==state.input_sha256
    assert ctl.import_image(state.case_id,req.task_id,photo,'synthetic fixture').accepted
    verifier=ctl.current_task(state.case_id)
    assert verifier.allowed_assets[0].path=='input/original.png'
    assert verifier.context['original_upload_transport']==transport
    assert 'instruction' not in verifier.context


def test_minimal_chain_and_role_isolation(tmp_path, photo, fixture_json):
    controller = Controller(tmp_path)
    state = controller.new(photo, "restore")
    assert state.workflow_status == "WAIT_DIAGNOSIS"
    request = controller.current_task(state.case_id)
    diagnosis = fixture_json("diagnosis")
    diagnosis["tool_plan"] = []
    result = controller.import_json(state.case_id, request.task_id, diagnosis, "test fixture")
    assert result.accepted
    state = controller.inspect(state.case_id)
    assert state.workflow_status == "WAIT_COMPOSITION"
    request = controller.current_task(state.case_id)
    composition = fixture_json("composition")
    assert controller.import_json(state.case_id, request.task_id, composition, "test fixture").accepted
    request = controller.current_task(state.case_id)
    assert request.role == "execute"
    assert [a.path for a in request.allowed_assets] == ["input/canonical.png"]
    case = CasePaths(state.case_id, tmp_path)
    assert case.path(request.prompt_file).read_text(encoding="utf-8").strip() == composition["instruction"]
    assert controller.import_image(state.case_id, request.task_id, photo, "test fixture").accepted
    request = controller.current_task(state.case_id)
    assert request.role == "verify"
    assert "instruction" not in request.context
    assert composition["instruction"] not in case.path(request.prompt_file).read_text(encoding="utf-8")


def test_duplicates_conflicts_and_old_tasks(tmp_path, photo, fixture_json):
    ctl = Controller(tmp_path)
    state = ctl.new(photo, "restore")
    req = ctl.current_task(state.case_id)
    payload = fixture_json("diagnosis")
    payload["tool_plan"] = []
    assert ctl.import_json(state.case_id, req.task_id, payload, "fixture").accepted
    revision = ctl.inspect(state.case_id).revision
    assert ctl.scan()[0].code == "already_processed"
    assert ctl.inspect(state.case_id).revision == revision
    payload["content"] = "changed"
    assert ctl.import_json(state.case_id, req.task_id, payload, "fixture").code == "conflict"
    assert ctl.inspect(state.case_id).pending_task_id != req.task_id


def test_tool_plan_dedupes_without_adding_tools(tmp_path, photo, fixture_json):
    ctl = Controller(tmp_path)
    state = ctl.new(photo, "restore")
    payload = fixture_json("diagnosis")
    payload["tool_plan"] = [{"tool": "T1_OCR", "reason": "a"}, {"tool": "T1_OCR", "reason": "b"}]
    assert ctl.import_json(state.case_id, state.pending_task_id, payload, "fixture").accepted
    state = ctl.inspect(state.case_id)
    assert state.required_tools == ["T1_OCR"]
    assert state.workflow_status == "WAIT_EVIDENCE"


def test_cli_local_bridge_preserves_file_provenance(tmp_path, photo, fixture_json, capsys):
    from hir_manual.__main__ import main
    from hir_manual.storage import write_json
    ctl = Controller(tmp_path)
    state = ctl.new(photo, "restore")
    req = ctl.current_task(state.case_id)
    source = tmp_path / "payload.json"
    write_json(source, fixture_json("diagnosis"))
    assert main(["write-response", "--root", str(tmp_path), "--case", state.case_id, "--task", req.task_id, "--file", str(source), "--model", "fixture"]) == 0
    case = ctl.case(state.case_id)
    response = read_json(case.path(req.response_file))
    assert response["provenance"]["writer"] == "local_work"
    assert response["provenance"]["transport_mode"] == "file"
    assert ctl.inspect(state.case_id).pending_task_id == req.task_id
    assert ctl.scan()[0].accepted
