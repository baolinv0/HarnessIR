"""Exercise the public CLI using synthetic pixels and unavailable real deployments."""
from pathlib import Path
from tempfile import TemporaryDirectory
import argparse
import json
import subprocess
import sys

from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[3]
    commands = []
    with TemporaryDirectory(prefix="hre-sr-cli-") as directory:
        temporary = Path(directory)

        def run(parts, expected=0):
            command = [sys.executable, *map(str, parts)]
            result = subprocess.run(command, cwd=repo, capture_output=True, text=True)
            commands.append({"command": [part.replace(str(temporary), "$TMP") for part in command],
                             "exit_code": result.returncode})
            assert result.returncode == expected, result.stdout + result.stderr
            return json.loads(result.stdout)

        run(["engine/examples/evidence_sr_v02/make_fixture.py", "--out", temporary / "input"])
        source = temporary / "input" / "source.png"
        with Image.open(source) as image:
            assert image.size == (256, 256)
        case = temporary / "success"
        task = temporary / "input" / "task.json"
        config = temporary / "input" / "config.json"
        run(["-m", "hre", "sr", "create", "--case-root", case, "--spec", task, "--config", config])
        state = run(["-m", "hre", "sr", "run", "--case-root", case])
        assert state["status"] == "selected" and state["selected_slot"] == "C1"
        assert {key: value["status"] for key, value in state["candidates"].items()} == {key: "valid" for key in ("C0", "C1", "C2", "C3")}
        output = state["selected_output"]
        with Image.open(output["path"]) as image:
            assert image.size == (1024, 1024)
        before = len(list((case / "journal").glob("*.json")))
        resumed = run(["-m", "hre", "sr", "resume", "--case-root", case])
        assert resumed == state
        assert len(list((case / "journal").glob("*.json"))) == before
        report = run(["-m", "hre", "sr", "report", "--case-root", case])
        assert report["execution_kind"] == "fixture" and report["quality_claims"] is False
        assert report["accounting"]["real_model_calls"] == 0 and report["accounting"]["real_judge_calls"] == 0
        assert report["accounting"]["pool_oracle_quality_coverage"] is None
        blocked_config = temporary / "blocked.json"
        blocked_config.write_text(json.dumps({"mode": "real", "models": {}, "judge": {}}))
        preflight = run(["-m", "hre", "sr", "preflight", "--config", blocked_config], 2)
        assert preflight["status"] == "blocked"
        assert all(value["status"] == "blocked" for value in preflight["models"].values())
        blocked_root = temporary / "blocked-case"
        run(["-m", "hre", "sr", "create", "--case-root", blocked_root, "--spec", task, "--config", blocked_config])
        blocked = run(["-m", "hre", "sr", "run", "--case-root", blocked_root], 2)
        assert blocked["status"] == "unresolved" and blocked["selected_output"] is None
        assert {key: value["status"] for key, value in blocked["candidates"].items()} == {key: "blocked" for key in ("C0", "C1", "C2", "C3")}
        blocked_report = run(["-m", "hre", "sr", "report", "--case-root", blocked_root])
        assert blocked_report["accounting"]["submitted_operations"] == 0
        assert blocked_report["accounting"]["real_model_calls"] == 0
        result = {
            "code_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
            "fixture": {"input_size": [256, 256], "selected_size": [output["width"], output["height"]],
                        "candidate_statuses": {k: v["status"] for k, v in state["candidates"].items()},
                        "selected_slot": state["selected_slot"], "resume_unchanged": True,
                        "real_model_calls": 0, "real_judge_calls": 0, "quality_evidence": False},
            "unconfigured_real": {"status": blocked["status"], "selected_output": None,
                                  "candidate_statuses": {k: v["status"] for k, v in blocked["candidates"].items()},
                                  "submitted_operations": 0, "real_model_calls": 0,
                                  "blockers": {k: v["blockers"] for k, v in preflight["models"].items()},
                                  "judge_blockers": preflight["judge"]["blockers"]},
            "commands": commands,
        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
