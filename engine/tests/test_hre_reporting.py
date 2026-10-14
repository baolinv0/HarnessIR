from PIL import Image
import pytest
from hre.assets import create_case, canonicalize_image
from hre.geometry import check_geometry
from hre.reporting import write_report
from hre.storage import read_json, write_json
from test_hre_selection import verified
from hre.reporting import cost_summary
from hre.models import file_sha256


def test_costs_count_accepted_analysis_and_uncertain_durable_intent():
    state = {"budget": {"max_generations": 3, "consumed": 1, "reserved": 1, "ledger": [
        {"generation_id": "g0", "status": "submitted", "charged_count": 1},
        {"generation_id": "g1", "status": "reserved", "charged_count": 0, "outcome": "unknown"}]}}
    costs = cost_summary(state, [{"type": "response_accepted", "payload": {"stage": "diagnose"}}, {"type": "format_repair", "payload": {"task_id": "t"}}])
    assert costs["text_or_vision_stage_calls"] == 1
    assert costs["uncertain_submission_reservations"] == 1
    assert costs["accounted_generations"] == 2
    assert costs["format_repairs"] == 1


def test_report_rejects_state_projection_outside_transaction_history(tmp_path):
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    Image.new("RGB", (20, 10), "red").save(a)
    Image.new("RGB", (14, 18), "blue").save(b)
    root = tmp_path / "case"
    create_case(a, b, {"case_id": "case1"}, {"assume_srgb": True}, root)
    state = read_json(root / "state.json")
    state["revision"] = 999
    write_json(root / "state.json", state)
    with pytest.raises(Exception): write_report(root)


def test_report_actual_derived_asset_and_all_costs_unknown(tmp_path):
    from hre.workflow import Controller
    from hre.desktop import import_candidate
    from hre.protocol import TaskWriter
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    Image.new("RGB", (20, 10), "red").save(a)
    Image.new("RGB", (14, 18), "blue").save(b)
    root = tmp_path / "case"
    create_case(a, b, {"case_id": "case1"}, {"profile_id": "direct_ref", "assume_srgb": True, "reference_usable": "usable", "geometry_policy": {"mode": "aspect_preserving_resize", "max_aspect_ratio_error": .005}}, root)
    controller = Controller(root)
    state = controller.start()
    source = tmp_path / "c.png"
    Image.new("RGB", (40, 20), "green").save(source)
    task_id = state["pending_task"]["task_id"]
    controller.mark_submitted(task_id)
    done = import_candidate(root, task_id, source, {"actual_generation_count": 1, "provider_order": 0})
    assert controller.consume_done(done).accepted
    state = controller.state()
    request = read_json(root / state["pending_task"]["request_path"])
    derived = state["candidates"][0]["geometry"]["derived_asset"]
    assert next(a for a in request["input_assets"] if a["role"] == "candidate")["sha256"] == derived["sha256"]
    done = TaskWriter(root).commit_submission(request, verified()["verification"], provenance={"ui_model_name": "Observed UI", "exact_model_version": "v1", "seed": None})
    assert controller.consume_done(done).accepted
    report = write_report(root)
    summary = read_json(root / "final/summary.json")
    assert summary["selected_asset"]["sha256"] == derived["sha256"]
    assert summary["costs"]["observed_billed_cost"] is None
    assert summary["model_metadata"]["model_seed"] == "unknown"
    assert summary["model_metadata"]["ui_model_name"] == "Observed UI"
    assert summary["model_metadata"]["model_version"] == "v1"
    assert "engineering heuristic" in report.read_text()
    assert len(summary["candidates"]) == 1
    (root / summary["selected_asset"]["path"]).write_bytes(b"corrupt")
    with pytest.raises(Exception): write_report(root)
