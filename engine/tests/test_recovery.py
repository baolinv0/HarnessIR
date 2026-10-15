import pytest
from hir_manual.cases import create_case
from hir_manual.storage import CasePaths, commit, recover_case, writer_lock, read_json


@pytest.mark.parametrize("point,expected_increment", [("before_commit", 0), ("after_commit", 1), ("after_state", 1)])
def test_commit_boundaries(tmp_path, photo, point, expected_increment):
    state = create_case(tmp_path, photo, "restore", {})
    case = CasePaths(state.case_id, tmp_path)
    with writer_lock(tmp_path):
        with pytest.raises(RuntimeError):
            commit(case, state, "test_event", crash_at=point)
        recovered = recover_case(case)
        assert recovered.revision == state.revision + expected_increment
        events = case.path("events.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(events) == recovered.revision
        assert recover_case(case).revision == recovered.revision
