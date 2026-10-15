import pytest
from hir_manual.service import Controller, history
from hir_manual.storage import transactions
from test_integration import ready_to_execute
from PIL import Image


def test_cancelled_late_output_cost_is_counted_once(tmp_path, photo, fixture_json):
    ctl = Controller(tmp_path)
    state = ctl.new(photo, "restore")
    req = ready_to_execute(ctl, state, fixture_json)
    ctl.operate(state.case_id, "submitted")
    ctl.operate(state.case_id, "cancel")
    result = ctl.import_image(state.case_id, req.task_id, photo, "fixture")
    assert result.code == "stale_task"
    state = ctl.inspect(state.case_id)
    assert state.workflow_completed and state.terminal_reason == "cancelled"
    assert state.pending_task_id is None
    assert state.budget.consumed == 1 and state.budget.reserved == 0
    ctl.scan()
    assert ctl.inspect(state.case_id).budget.consumed == 1
    assert len(list(ctl.case(state.case_id).path("quarantine").rglob("*.png"))) == 1


def test_refine_issuance_recovers_through_pause_resume(tmp_path, photo, fixture_json, monkeypatch):
    import hir_manual.service as service
    ctl = Controller(tmp_path)
    state = ctl.new(photo, "restore")
    req = ready_to_execute(ctl, state, fixture_json)
    assert ctl.import_image(state.case_id, req.task_id, photo, "fixture").accepted
    assert ctl.import_json(state.case_id, ctl.current_task(state.case_id).task_id, fixture_json("verification"), "fixture").accepted
    new_instruction = fixture_json("composition")
    new_instruction["instruction"] += " Apply a revised conservative correction only around the left shadow boundaries."
    refine_req = ctl.current_task(state.case_id)
    original_commit = service.commit
    def crash_issue(case, state, event, *args, **kwargs):
        if event == "task_issued":
            raise RuntimeError("crash after accepted refine")
        return original_commit(case, state, event, *args, **kwargs)
    monkeypatch.setattr(service, "commit", crash_issue)
    with pytest.raises(RuntimeError):
        ctl.import_json(state.case_id, refine_req.task_id, new_instruction, "fixture")
    monkeypatch.setattr(service, "commit", original_commit)
    assert ctl.operate(state.case_id, "pause").operation_status == "paused"
    ctl.operate(state.case_id, "resume")
    req = ctl.current_task(state.case_id)
    assert req.round == 2
    assert req.context["instruction"] == new_instruction["instruction"]
    assert ctl.inspect(state.case_id).budget.reserved == 1


def test_transparent_generated_image_cannot_succeed(tmp_path, photo, fixture_json):
    ctl = Controller(tmp_path)
    state = ctl.new(photo, "restore")
    req = ready_to_execute(ctl, state, fixture_json)
    alpha = tmp_path / "transparent.png"
    Image.new("RGBA", (64, 48), (0, 0, 0, 0)).save(alpha)
    assert ctl.import_image(state.case_id, req.task_id, alpha, "fixture").accepted
    assert ctl.import_json(state.case_id, ctl.current_task(state.case_id).task_id, fixture_json("verification_accepted"), "fixture").accepted
    state = ctl.inspect(state.case_id)
    assert state.workflow_completed and state.restoration_success is False
    assert state.selected_round is None
    assert state.budget.consumed == 1


def test_extra_generation_after_accept_is_counted_and_preserves_official(tmp_path, photo, fixture_json):
    from hir_manual.storage import sha256_file
    ctl = Controller(tmp_path)
    state = ctl.new(photo, "restore")
    req = ready_to_execute(ctl, state, fixture_json)
    assert ctl.import_image(state.case_id, req.task_id, photo, "fixture").accepted
    pending = ctl.current_task(state.case_id).task_id
    official = ctl.case(state.case_id).path(history(ctl.case(state.case_id))["rounds"][0]["output_asset"]["path"])
    before = sha256_file(official)
    extra = tmp_path / "new_generation.png"
    Image.new("RGB", (64, 48), (80, 80, 80)).save(extra)
    result = ctl.import_image(state.case_id, req.task_id, extra, "fixture")
    assert result.code == "conflict"
    state = ctl.inspect(state.case_id)
    assert state.budget.consumed == 2 and state.budget.reserved == 0
    assert state.pending_task_id == pending
    assert sha256_file(official) == before
    ctl.scan()
    assert ctl.inspect(state.case_id).budget.consumed == 2
