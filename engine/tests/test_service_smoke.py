from hir_manual.service import Controller


def test_restart_same_pending_task(tmp_path, photo):
    ctl = Controller(tmp_path)
    state = ctl.new(photo, "restore")
    assert Controller(tmp_path).inspect(state.case_id).pending_task_id == state.pending_task_id
    assert Controller(tmp_path).current_task(state.case_id).role == "diagnose"


def test_pause_resume(tmp_path, photo):
    ctl = Controller(tmp_path)
    state = ctl.new(photo, "restore")
    assert ctl.operate(state.case_id, "pause").operation_status == "paused"
    resumed = ctl.operate(state.case_id, "resume")
    assert resumed.pending_task_id == state.pending_task_id
    assert resumed.operation_status == "active"
