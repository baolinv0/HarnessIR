"""Executable dev8 -> recorded proxy selection -> disjoint test16 study gates."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re

from ..models import HREError, file_sha256, now
from ..storage import case_lock, read_json
from ..v3.common import digest, require
from ..v3.contracts import _canonical_asset
from ..v3.runner_journal import immutable_json
from .contracts import METHODS, SLOTS, finite, geometry_and_rois, normalise_config, normalise_spec, object_fields, opaque_image, opaque_pixel_sha256
from .runtime import create_case, load_case, report, run_case

VERSION = "hre_sr_study_v02"


def create_study(root: Path, manifest: dict, config: dict) -> dict:
    object_fields(manifest, {"study_id", "seed", "dev", "test"}, "study manifest")
    finite(manifest)
    sid = manifest.get("study_id")
    require(isinstance(sid, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", sid), "sr_study_invalid", "Use a simple study ID")
    seed = manifest.get("seed", 0)
    require(type(seed) is int and 0 <= seed < 2**32, "sr_study_invalid", "Freeze one valid study seed")
    for phase, count in (("dev", 8), ("test", 16)):
        require(isinstance(manifest.get(phase), list) and len(manifest[phase]) == count,
                "sr_study_size", f"The frozen {phase} manifest requires exactly {count} cases")
    config = normalise_config(config)
    root = Path(root).resolve()
    require(not root.exists() or not any(root.iterdir()), "sr_study_exists", "Create a new study directory")
    ids, pixels = set(), set()
    study = {"schema_version": VERSION, "study_id": sid, "seed": seed, "config": config,
             "execution_kind": config["mode"], "phases": {"dev": [], "test": []}, "created_at": now(),
             "oracle_labels": None, "x1_experiments": "pending_after_sr"}
    with case_lock(root):
        for phase in ("dev", "test"):
            for row in manifest[phase]:
                object_fields(row, {"case_id", "source", "rois", "ground_truth"}, "study case")
                spec = normalise_spec({key: row[key] for key in ("case_id", "source", "rois") if key in row} | {"seed": seed})
                require(spec["case_id"] not in ids, "sr_study_duplicate", "Study case IDs must be unique")
                ids.add(spec["case_id"])
                path = Path(spec["source"]["path"]).expanduser().resolve()
                source = _canonical_asset(path, root / "sources" / spec["case_id"], "source", spec["colour_policy"])
                opaque_image(Path(source["path"]))
                source.update(origin_path=str(path), origin_sha256=file_sha256(path),
                              pixel_sha256=opaque_pixel_sha256(Path(source["path"])))
                require(source["pixel_sha256"] not in pixels, "sr_study_overlap",
                        "Development and test require distinct canonical pixels, including re-encoded sources")
                pixels.add(source["pixel_sha256"])
                _, rois = geometry_and_rois(spec, source)
                spec["rois"] = [{"id": r["id"], "box": r["source_box"]} for r in rois]
                row_record = {"case_id": spec["case_id"], "spec": spec, "source": source}
                if row.get("ground_truth"):
                    gt = object_fields(row["ground_truth"], {"path"}, "offline ground_truth")
                    gt_path = Path(gt["path"]).expanduser().resolve()
                    require(gt_path.is_file(), "sr_gt_missing", "Offline GT file is missing")
                    row_record["offline_ground_truth"] = {"path": str(gt_path), "sha256": file_sha256(gt_path), "online_use": False}
                study["phases"][phase].append(row_record)
        immutable_json(root / "study.json", study)
        immutable_json(root / "study_identity.json", {"schema_version": VERSION, "study_sha256": file_sha256(root / "study.json")})
    return study_report(root)


def _load(root: Path) -> dict:
    identity, study = read_json(root / "study_identity.json"), read_json(root / "study.json")
    require(study.get("schema_version") == VERSION and identity.get("study_sha256") == file_sha256(root / "study.json"),
            "sr_study_modified", "Frozen study manifest changed")
    for rows in study["phases"].values():
        for row in rows:
            for key, checksum in (("path", "sha256"), ("original_path", "original_sha256"), ("origin_path", "origin_sha256")):
                path = Path(row["source"][key])
                require(path.is_file() and file_sha256(path) == row["source"][checksum], "sr_study_source_modified", "Frozen study source changed")
    return study


def _case_root(root: Path, phase: str, row: dict) -> Path:
    return root / "cases" / phase / row["case_id"]


def _real_development_ready(result: dict) -> bool:
    if result["execution_kind"] != "real" or result["status"] not in {"selected", "unresolved"}:
        return False
    expected = ["model_" + slot for slot in SLOTS] + ["judge_visual", "judge_evidence"]
    for key in expected:
        operation = result["operations"].get(key, {})
        if not operation.get("submitted") or operation.get("status") not in {"complete", "failed"}:
            return False
        outcome = (result.get("candidates", {}).get(key.removeprefix("model_"), {}) if key.startswith("model_")
                   else result.get("judgements", {}).get(key.removeprefix("judge_"), {}))
        observation = outcome.get("observation", {})
        attempts = observation.get("calls_attempted", observation.get("image_calls_attempted"))
        if observation.get("fixture") or type(attempts) is not int or attempts < 1:
            return False
    return True


def verified_conditions(root: Path) -> dict:
    """A conditions file is authoritative only after its independent commit marker."""
    root = Path(root).resolve()
    study = _load(root)
    path, anchor = root / "conditions.json", root / "conditions.identity.json"
    require(path.is_file() and anchor.is_file(), "sr_study_not_frozen", "No committed development freeze exists")
    identity, conditions = read_json(anchor), read_json(path)
    require(study["execution_kind"] == "real" and identity.get("conditions_sha256") == file_sha256(path)
            and identity.get("study_sha256") == file_sha256(root / "study.json")
            and conditions.get("schema_version") == "hre_sr_study_freeze_v02"
            and conditions.get("study_sha256") == identity["study_sha256"]
            and conditions.get("real_development_complete") is True, "sr_study_conditions_changed",
            "Committed study conditions changed or do not describe real development")
    expected_ids = {row["case_id"] for row in study["phases"]["dev"]}
    require(set(conditions.get("development_results", {})) == expected_ids, "sr_development_incomplete", "Freeze must bind all eight development observations")
    for row in study["phases"]["dev"]:
        result = report(_case_root(root, "dev", row))
        require(_real_development_ready(result) and digest(result) == conditions["development_results"][row["case_id"]],
                "sr_study_conditions_changed", "Development observations changed after freeze")
    return conditions


def run_study(root: Path, phase: str) -> dict:
    root = Path(root).resolve()
    require(phase in {"dev", "test"}, "sr_study_phase", "Use dev or test")
    with case_lock(root):
        study = _load(root)
        conditions_path = root / "conditions.json"
        conditions = verified_conditions(root) if conditions_path.exists() else None
        require(phase == "dev" or conditions is not None, "sr_study_not_frozen", "Finish real dev8 and freeze proxy selection before test16")
        for row in study["phases"][phase]:
            directory = _case_root(root, phase, row)
            if not (directory / "freeze.json").exists():
                spec = deepcopy(row["spec"])
                if phase == "test":
                    spec["evidence_profile"] = {"selection": "development_selected", "methods": conditions["selected_methods"],
                                                "selection_receipt": str(conditions_path)}
                create_case(directory, spec, study["config"])
            case, _ = load_case(directory)
            if phase == "test":
                require(case["protocol_sha256"] == conditions["protocol_sha256"], "sr_study_conditions_changed",
                        "Model/runtime/recipe/Judge conditions changed since development freeze")
            try:
                run_case(directory)
            except HREError as exc:
                if exc.code != "sr_submission_unknown":
                    raise
            result = report(directory)
            if result["status"] in {"selected", "unresolved"}:
                immutable_json(root / "results" / phase / (row["case_id"] + ".json"), result)
    return study_report(root)


def freeze_study(root: Path, selection: dict) -> dict:
    object_fields(selection, {"methods", "observations"}, "development proxy selection")
    methods, observations = selection.get("methods"), selection.get("observations")
    require(isinstance(methods, list) and methods and len(methods) == len(set(methods)) and all(m in METHODS for m in methods),
            "sr_study_selection", "Select a nonempty distinct set of implemented proxies")
    require(isinstance(observations, list) and observations, "sr_study_selection", "Document actual development failures before selecting proxies")
    root = Path(root).resolve()
    with case_lock(root):
        study = _load(root)
        require(study["execution_kind"] == "real", "sr_fixture_not_development", "Fixtures cannot advance a real study gate")
        results, protocol = {}, None
        for row in study["phases"]["dev"]:
            directory = _case_root(root, "dev", row)
            require((directory / "freeze.json").exists(), "sr_development_incomplete", "All eight real development cases must be run")
            result = report(directory)
            require(_real_development_ready(result), "sr_development_incomplete",
                    "Development needs eight terminal real cases with four submitted model and two submitted Judge observations; blocked/unknown/fixtures do not count")
            results[row["case_id"]] = result
            protocol = result["protocol_sha256"] if protocol is None else protocol
            require(result["protocol_sha256"] == protocol, "sr_study_conditions_changed", "Development conditions differ across cases")
        bound = []
        for observation in observations:
            object_fields(observation, {"case_id", "artifact_sha256", "failure", "why_method"}, "development observation")
            cid, checksum = observation.get("case_id"), observation.get("artifact_sha256")
            require(cid in results and checksum in results[cid]["artifacts"].values(), "sr_development_unbound",
                    "Each observed failure must bind to an actual development artifact hash")
            require(isinstance(observation.get("failure"), str) and observation["failure"].strip()
                    and isinstance(observation.get("why_method"), str) and observation["why_method"].strip(),
                    "sr_development_unbound", "Record the observed failure and why the selected proxies address it")
            bound.append(observation)
        conditions = {"schema_version": "hre_sr_study_freeze_v02", "study_id": study["study_id"],
                      "study_sha256": file_sha256(root / "study.json"), "real_development_complete": True,
                      "protocol_sha256": protocol, "selected_methods": methods, "observations": bound,
                      "development_results": {cid: digest(result) for cid, result in results.items()},
                      "held_out_pixel_sha256": [r["source"]["pixel_sha256"] for r in study["phases"]["test"]]}
        immutable_json(root / "conditions.json", conditions)
        immutable_json(root / "conditions.identity.json", {"conditions_sha256": file_sha256(root / "conditions.json"),
                                                            "study_sha256": file_sha256(root / "study.json")})
    return study_report(root)


def study_report(root: Path) -> dict:
    root = Path(root).resolve()
    with case_lock(root):
        study = _load(root)
        phases = {}
        for phase in ("dev", "test"):
            results = {}
            for row in study["phases"][phase]:
                directory = _case_root(root, phase, row)
                if (directory / "freeze.json").exists():
                    results[row["case_id"]] = report(directory)
            phases[phase] = {"planned": len(study["phases"][phase]), "terminal": sum(r["status"] in {"selected", "unresolved"} for r in results.values()),
                             "real_completed": sum(_real_development_ready(r) for r in results.values()),
                             "cases": {cid: {"status": r["status"], "selected_slot": r["selected_slot"], "accounting": r["accounting"]} for cid, r in results.items()}}
        frozen = (root / "conditions.json").exists()
        if frozen:
            verified_conditions(root)
        return {"schema_version": VERSION, "study_id": study["study_id"], "execution_kind": study["execution_kind"],
                "quality_claims": False, "phases": phases, "conditions_frozen": frozen,
                "test_gate": "open" if frozen else "pending_real_dev8_and_selection", "oracle_quality_coverage": None,
                "selection_error": None, "x1_experiments": "pending_after_sr"}
