from PIL import Image
import pytest
from hir_manual.service import Controller, history
from hir_manual.storage import read_json, CasePaths


def ready_to_execute(ctl, state, fixture_json):
    diagnosis = fixture_json("diagnosis")
    diagnosis["tool_plan"] = []
    assert ctl.import_json(state.case_id, ctl.current_task(state.case_id).task_id, diagnosis, "fixture").accepted
    assert ctl.import_json(state.case_id, ctl.current_task(state.case_id).task_id, fixture_json("composition"), "fixture").accepted
    return ctl.current_task(state.case_id)


def test_full_success_and_telemetry_revision(tmp_path, photo, fixture_json):
    ctl = Controller(tmp_path)
    state = ctl.new(photo, "restore")
    req = ready_to_execute(ctl, state, fixture_json)
    telemetry = ctl.operate(state.case_id, "submitted")
    assert telemetry.revision > req.expected_state_revision
    assert ctl.import_image(state.case_id, req.task_id, photo, "fixture").accepted
    assert ctl.import_json(state.case_id, ctl.current_task(state.case_id).task_id, fixture_json("verification_accepted"), "fixture").accepted
    state = ctl.inspect(state.case_id)
    assert state.workflow_completed and state.restoration_success
    assert state.selected_round == 1
    assert state.budget.consumed == 1 and state.budget.reserved == 0
    output = history(ctl.case(state.case_id))["rounds"][0]["output_asset"]["path"]
    ctl.case(state.case_id).path(output).write_bytes(b"tampered after finish")
    with pytest.raises(ValueError, match="hash mismatch"):
        ctl.inspect(state.case_id)


def test_three_generation_budget_and_original_retry(tmp_path, photo, fixture_json):
    ctl = Controller(tmp_path)
    state = ctl.new(photo, "restore")
    req = ready_to_execute(ctl, state, fixture_json)
    canonical_sha = state.input_sha256
    for number in range(1, 4):
        image = tmp_path / f"output_{number}.png"
        Image.new("RGB", (64, 48), (40 + number, 50, 60)).save(image)
        assert req.input_sha256 == canonical_sha
        assert req.allowed_assets[0].path == "input/canonical.png"
        assert ctl.import_image(state.case_id, req.task_id, image, "fixture").accepted
        verification = fixture_json("verification")
        verification["best_round"] = 0
        assert ctl.import_json(state.case_id, ctl.current_task(state.case_id).task_id, verification, "fixture").accepted
        if number < 3:
            refine = fixture_json("composition")
            refine["instruction"] += f" Address shadow noise with a more conservative regional correction, revision {number}."
            assert ctl.import_json(state.case_id, ctl.current_task(state.case_id).task_id, refine, "fixture").accepted
            req = ctl.current_task(state.case_id)
            assert req.round == number + 1
    state = ctl.inspect(state.case_id)
    assert state.terminal_reason == "budget_exhausted"
    assert state.budget.consumed == 3
    assert state.selected_round == 1
    assert state.restoration_success is False
    assert ctl.current_task(state.case_id) is None


def test_contradiction_repair_no_generation_cost(tmp_path, photo, fixture_json):
    ctl = Controller(tmp_path)
    state = ctl.new(photo, "restore")
    req = ready_to_execute(ctl, state, fixture_json)
    assert ctl.import_image(state.case_id, req.task_id, photo, "fixture").accepted
    verification_task = ctl.current_task(state.case_id)
    invalid = fixture_json("verification_accepted")
    invalid["needs_redo"] = True
    assert not ctl.import_json(state.case_id, verification_task.task_id, invalid, "fixture").accepted
    state = ctl.inspect(state.case_id)
    assert state.pending_task_id == verification_task.task_id
    assert state.budget.consumed == 1
    assert ctl.import_json(state.case_id, verification_task.task_id, fixture_json("verification_no_further_gain"), "fixture").accepted
    state = ctl.inspect(state.case_id)
    assert state.workflow_completed and state.restoration_success is False
    assert state.terminal_reason == "no_further_gain"
