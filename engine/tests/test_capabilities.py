from hir_manual.capabilities import prepare_probe, complete_probe, dispatch
from hir_manual.service import Controller
from hir_manual.storage import now, write_json


def test_nonce_read_write_probe(tmp_path):
    probe = prepare_probe(tmp_path)
    from pathlib import Path
    path = Path(probe["response_path"])
    write_json(path, {"nonce": probe["nonce"], "image_description": "Synthetic probe contains a red square and a blue circle on white.", "writer": "test fixture", "completed_at": now()})
    caps = complete_probe(tmp_path, path)
    assert caps["local_read_write"] == "supported"
    assert caps["image_save"] == "untested"


def test_no_dispatch_bridge(tmp_path, photo):
    ctl = Controller(tmp_path)
    state = ctl.new(photo, "restore")
    result = dispatch(ctl, state.case_id)
    assert result.code == "unsupported"
    assert ctl.inspect(state.case_id).pending_task_id == state.pending_task_id
