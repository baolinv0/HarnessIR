"""Cross-component delivery checks; no image models or remote VLM calls."""
from copy import deepcopy
from pathlib import Path
import json
import sys

from PIL import Image
import pytest

from hre.models import HREError, file_sha256
from hre.storage import read_json, write_json
from hre.v3.batch import run_batch
from hre.v3.common import digest
from hre.v3.contracts import CATALOG
from hre.v3.report import export_report
from hre.v3.worker import WorkerClient, process_job
from test_hre_v3_runner import Workers


def configuration():
    return {"stage": {}, "models": {profile: {
        "compiler": {"backend": row["compiler"]}, "editor": {"model_id": row["model_id"]}
    } for profile, row in CATALOG.items()}}


def test_four_model_batch_freezes_one_planning_and_exports_every_run(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGB", (37, 29), (40, 50, 60)).save(source)
    manifest = {"schema_version": "hre_batch_v3", "models": list(CATALOG), "seeds": [42],
                "arms": [{"name": name, "strategy": name, "policy": "single"} for name in ("native", "shared", "model_aware")],
                "cases": [{"id": "one", "source": str(source), "task_mode": "restoration", "brief": "Reduce blur."}]}
    workers = Workers(accept_after=1)
    root = tmp_path / "comparison"
    result = run_batch(manifest, configuration(), root, stage_fn=workers.stage,
                       compile_fn=workers.compile, execute_fn=workers.execute)
    assert result["status"] == "completed" and len(result["runs"]) == 12
    assert workers.stages.count("diagnose") == workers.stages.count("compose") == 1
    assert workers.stages.count("verify") == len(workers.executions) == 12
    planned = [row["intent"] for row in workers.compiles if row["strategy"] != "native"]
    assert len(planned) == 8 and all(row == planned[0] for row in planned)
    assert all(row["intent"] is None for row in workers.compiles if row["strategy"] == "native")
    assert all(row["canvas"] == {"width": 64, "height": 32} for row in workers.executions)
    again = run_batch(manifest, configuration(), root, resume=True, stage_fn=workers.stage,
                      compile_fn=workers.compile, execute_fn=workers.execute)
    assert again["status"] == "completed" and len(workers.executions) == 12
    exported = export_report(root, tmp_path / "report")
    assert exported["runs"] == 12 and exported["unavailable"] == 0
    report = read_json(Path(exported["json"]))
    assert {row["profile_id"] for row in report["runs"]} == set(CATALOG)
    assert all((tmp_path / "report" / row["selected_image"]).is_file() for row in report["runs"])
    assert len(Path(exported["csv"]).read_text("utf-8-sig").splitlines()) == 13
    assert all(row["conditions"] and row["conditions"][0]["condition"]["text"] for row in report["runs"])
    assert any(item["kind"] == "compile" and "native_output" in item["result"]
               for item in report["runs"][0]["observations"])
    with pytest.raises(HREError, match="batch_modified"):
        run_batch({**manifest, "seeds": [43]}, configuration(), root, resume=True)


def test_batch_uses_one_snapshot_when_live_source_changes_mid_run(tmp_path):
    source = tmp_path / "live.png"
    Image.new("RGB", (32, 32), "red").save(source)
    manifest = {"schema_version": "hre_batch_v3", "models": ["qwen21", "firered11"],
                "arms": [{"name": "native", "strategy": "native"}],
                "cases": [{"id": "one", "source": str(source), "task_mode": "restoration", "brief": "Reduce blur."}]}
    workers = Workers(accept_after=1)
    def execute(*args):
        result = workers.execute(*args)
        Image.new("RGB", (32, 32), "green").save(source)
        return result
    root = tmp_path / "batch"
    result = run_batch(manifest, configuration(), root, stage_fn=workers.stage,
                       compile_fn=workers.compile, execute_fn=execute)
    assert result["status"] == "completed"
    assert len({request["original_input_sha256"]["source"] for request in workers.executions}) == 1
    # Resume relies on the captured snapshot, not on whatever now occupies the
    # original dataset path. No additional model operation occurs.
    source.unlink()
    again = run_batch(manifest, configuration(), root, resume=True, stage_fn=workers.stage,
                      compile_fn=workers.compile, execute_fn=execute)
    assert again["status"] == "completed" and len(workers.executions) == 2


def test_report_reads_validated_journal_without_rewriting_stale_projection(tmp_path):
    from test_hre_v3_runner import make_case
    from hre.v3.runner import run_case
    root = make_case(tmp_path, policy="single")
    workers = Workers(accept_after=1)
    final = run_case(root, stage_fn=workers.stage, compile_fn=workers.compile, execute_fn=workers.execute)
    old = read_json(root / "journal" / "000000.json")["state"]
    write_json(root / "state.json", old)
    before = file_sha256(root / "state.json")
    exported = export_report(root, tmp_path / "report")
    row = read_json(Path(exported["json"]))["runs"][0]
    assert row["status"] == "completed" and row["budget"] == final["budget"]
    assert file_sha256(root / "state.json") == before


def native_request(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGB", (32, 32), (50, 60, 70)).save(source)
    return {"schema_version": "hre_model_request_v3", "request_id": "worker-test",
            "task_mode": "restoration", "profile_id": "qwen21", "strategy": "native",
            "brief": "Reduce blur.", "intent": None, "seed": 42, "canvas": {"width": 32, "height": 32},
            "spatial": {"mode": "full_frame"}, "inputs": [{"role": "source", "path": str(source),
                "sha256": file_sha256(source), "width": 32, "height": 32, "mode": "RGB"}]}


def test_persistent_worker_protocol_and_durable_duplicate_result(tmp_path):
    request = native_request(tmp_path)
    envelope = {"schema_version": "hre_native_job_v3", "operation": "compile", "request": request,
                "config": {"backend": "direct"}, "job_dir": str(tmp_path / "job")}
    environment_root = Path(__file__).resolve().parents[2]
    # The caller's PYTHONPATH is inherited. Use the same CPU-only test interpreter.
    client = WorkerClient({"command": [sys.executable, "-m", "hre.v3.worker", "--serve"], "timeout_seconds": 30})
    try:
        first = client.call(envelope)
        second = client.call(envelope)
    finally:
        client.close()
    assert first == second and first["ok"]
    assert first["payload"]["observation"]["calls_attempted"] == 0
    assert read_json(tmp_path / "job" / "job.json")["status"] == "succeeded"
    broken = deepcopy(envelope)
    broken["request"]["brief"] = "A changed goal"
    with pytest.raises(HREError, match="worker_job_conflict"):
        process_job(broken)
    unknown = deepcopy(envelope)
    unknown["job_dir"] = str(tmp_path / "unknown_job")
    marker = Path(unknown["job_dir"]) / "job.json"
    write_json(marker, {"request_sha256": digest({k: v for k, v in unknown.items() if k != "job_dir"}), "status": "started"})
    with pytest.raises(HREError, match="worker_submission_unknown"):
        process_job(unknown)


def test_cli_catalog_and_dry_run_do_not_import_image_libraries(tmp_path, capsys):
    from hre.cli import main
    from test_hre_v3_runner import make_case
    assert main(["models", "catalog"]) == 0
    catalog = json.loads(capsys.readouterr().out)
    assert set(catalog["models"]) == set(CATALOG)
    root = make_case(tmp_path, policy="single")
    assert main(["models", "dry-run", "--case-root", str(root)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["model_calls"] == 0 and result["input_roles"] == ["source"]
    assert not (root / "operations").exists()
