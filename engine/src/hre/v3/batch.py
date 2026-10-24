"""Frozen four-model comparison matrices with one shared planning artifact."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
import shutil

from ..models import file_sha256, now
from ..storage import case_lock, read_json, write_json
from .common import digest, require
from .contracts import CATALOG, create_case, load_case, normalise_spec, validate_config
from .runner import run_case


def resolve_spec_paths(spec: dict, base: Path) -> dict:
    value = deepcopy(spec)
    for role in ("source", "reference"):
        if value.get(role):
            item = value[role]
            if isinstance(item, str):
                item = value[role] = {"path": item}
            path = Path(item["path"]).expanduser()
            item["path"] = str((base / path).resolve() if not path.is_absolute() else path.resolve())
    for container, key in ((value.get("spatial", {}), "mask_path"), (value, "shared_intent")):
        if container.get(key):
            path = Path(container[key]).expanduser()
            container[key] = str((base / path).resolve() if not path.is_absolute() else path.resolve())
    return value


def resolve_config_paths(config: dict, base: Path) -> dict:
    value = deepcopy(config)
    def walk(node):
        if isinstance(node, dict):
            for key, item in node.items():
                if key in {"local_path", "upstream_path", "system_prompt_path", "deployment_manifest", "spool_dir", "cwd"} and isinstance(item, str):
                    path = Path(item).expanduser()
                    node[key] = str((base / path).resolve() if not path.is_absolute() else path.resolve())
                elif key == "fonts" and isinstance(item, list):
                    node[key] = [str((base / Path(font)).resolve()) if not Path(font).is_absolute() else str(Path(font).resolve()) for font in item]
                else:
                    walk(item)
        elif isinstance(node, list):
            for item in node:
                walk(item)
    walk(value)
    return value


def _normalise(manifest: dict, config: dict, base: Path, *, previous_manifest: dict | None = None) -> dict:
    value = deepcopy(manifest)
    require(value.get("schema_version") == "hre_batch_v3", "batch_invalid", "Expected hre_batch_v3")
    models = value.setdefault("models", list(CATALOG))
    require(isinstance(models, list) and models and len(models) == len(set(models)) and set(models) <= set(CATALOG),
            "batch_models_invalid", "Choose unique models from the four-model catalog")
    for model in models:
        validate_config(config, model)
    seeds = value.setdefault("seeds", [42])
    require(isinstance(seeds, list) and seeds and len(seeds) == len(set(seeds))
            and all(type(seed) is int and 0 <= seed < 2**63 - 100 for seed in seeds), "batch_seeds_invalid", "Freeze unique nonnegative seed values")
    arms = value.get("arms")
    require(isinstance(arms, list) and arms, "batch_arms_invalid", "Specify the comparison arms")
    for arm in arms:
        require(isinstance(arm, dict) and isinstance(arm.get("name"), str)
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", arm["name"]), "batch_arm_invalid", "Use safe, stable arm names")
        require(arm.get("strategy") in {"native", "shared", "model_aware"}, "batch_arm_invalid", "Unknown arm strategy")
        arm.setdefault("policy", "single")
        arm.setdefault("max_generations", 1 if arm["policy"] == "single" else 3)
    require(len({arm["name"] for arm in arms}) == len(arms), "batch_arm_invalid", "Arm names must be unique")
    cases = value.get("cases")
    require(isinstance(cases, list) and cases, "batch_cases_invalid", "Supply at least one source case")
    normalized = []
    previous_cases = {case["id"]: case for case in (previous_manifest or {}).get("cases", [])}
    for case in cases:
        require(isinstance(case, dict) and isinstance(case.get("id"), str)
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", case["id"]), "batch_case_invalid", "Use stable dataset case IDs")
        item = resolve_spec_paths(case, base)
        allowed_models = item.setdefault("models", list(models))
        require(isinstance(allowed_models, list) and allowed_models and len(set(allowed_models)) == len(allowed_models)
                and set(allowed_models) <= set(models), "batch_models_invalid", "Case models must be a subset of batch models")
        item["input_files"] = []
        previous = previous_cases.get(case["id"], {})
        def input_record(role, path):
            if previous_manifest is not None:
                old = next((record for record in previous.get("input_files", []) if record["role"] == role), None)
                require(old is not None and old["path"] == str(path), "batch_modified", "A frozen dataset input path changed")
                return deepcopy(old)
            require(path.is_file(), "batch_input_missing", "Missing dataset input: " + str(path))
            return {"role": role, "path": str(path), "sha256": file_sha256(path)}
        for role in ("source", "reference"):
            if item.get(role):
                path = Path(item[role]["path"])
                item["input_files"].append(input_record(role, path))
        if item.get("spatial", {}).get("mask_path"):
            path = Path(item["spatial"]["mask_path"])
            item["input_files"].append(input_record("edit_mask", path))
        # Validate every requested model/arm before starting any remote work.
        for model in allowed_models:
            for arm in arms:
                normalise_spec(_task(item, model, arm, seeds[0]))
        normalized.append(item)
    require(len({case["id"] for case in cases}) == len(cases), "batch_case_invalid", "Dataset case IDs must be unique")
    value["cases"] = normalized
    value.setdefault("share_planning", True)
    require(type(value["share_planning"]) is bool, "batch_invalid", "share_planning must be boolean")
    return value


def _task(case: dict, model: str, arm: dict, seed: int) -> dict:
    fields = {key: deepcopy(case[key]) for key in (
        "task_mode", "source", "reference", "brief", "geometry", "spatial", "regions", "evaluation", "colour_policy", "alpha_policy"
    ) if key in case}
    return {"schema_version": "hre_task_v3", "case_id": f"{case['id']}_{model}_{arm['name']}_{seed}"[:128],
            "profile_id": model, "strategy": arm["strategy"], **fields,
            "policy": {"mode": arm["policy"], "max_generations": arm["max_generations"],
                       "seed_schedule": [seed + index for index in range(arm["max_generations"])],
                       **({"max_stage_calls": arm["max_stage_calls"]} if "max_stage_calls" in arm else {}),
                       **({"max_compiler_calls": arm["max_compiler_calls"]} if "max_compiler_calls" in arm else {})}}


def _freeze_inputs(root: Path, manifest: dict) -> dict:
    result = {}
    for case in manifest["cases"]:
        records = []
        for asset in case["input_files"]:
            original = Path(asset["path"])
            require(file_sha256(original) == asset["sha256"], "batch_input_modified", "Dataset input changed before snapshotting")
            target = root / "inputs" / case["id"] / (asset["role"] + ".original")
            target.parent.mkdir(parents=True, exist_ok=True)
            require(not target.exists(), "batch_snapshot_exists", "Use a fresh snapshot directory")
            shutil.copyfile(original, target)
            require(file_sha256(target) == asset["sha256"] == file_sha256(original),
                    "batch_input_modified", "Dataset input changed while freezing the batch")
            records.append({"role": asset["role"], "path": str(target), "sha256": asset["sha256"], "original_path": asset["path"]})
        result[case["id"]] = records
    return result


def _snapshot_case(case: dict, snapshots: dict) -> dict:
    value = deepcopy(case)
    records = snapshots.get(case["id"], [])
    require(len(records) == len(case["input_files"]), "batch_snapshot_invalid", "Incomplete frozen dataset snapshot")
    for expected in case["input_files"]:
        asset = next((record for record in records if record["role"] == expected["role"]), None)
        require(asset is not None and asset["sha256"] == expected["sha256"] and asset["original_path"] == expected["path"],
                "batch_snapshot_invalid", "Snapshot does not match the frozen manifest")
        require(file_sha256(Path(asset["path"])) == asset["sha256"], "batch_input_modified", "Frozen batch input changed")
        if asset["role"] == "edit_mask":
            value["spatial"]["mask_path"] = asset["path"]
        else:
            value[asset["role"]] = {"path": asset["path"]}
    return value


def _check_imported_case(case_root: Path, dataset_case: dict) -> None:
    _, _, state = load_case(case_root)
    by_role = {row["role"]: row["sha256"] for row in dataset_case["input_files"]}
    for asset in state["inputs"]:
        role = "reference" if asset["role"] == "appearance_reference" else "source"
        require(asset["original_sha256"] == by_role[role], "batch_input_modified", "Run imported different original input bytes from its batch snapshot")


def run_batch(manifest: dict, config: dict, root: Path, *, base: Path | None = None,
              resume: bool = False, stage_fn=None, compile_fn=None, execute_fn=None) -> dict:
    root = Path(root).resolve()
    base = Path(base or Path.cwd()).resolve()
    require(resume or not root.exists() or not any(root.iterdir()), "batch_exists", "Use --resume for an existing frozen batch")
    with case_lock(root):
        frozen_path = root / "batch.freeze.json"
        previous = read_json(frozen_path) if frozen_path.exists() else None
        value = _normalise(manifest, config, base, previous_manifest=previous["manifest"] if previous else None)
        identity = {"manifest": value, "config": config}
        if frozen_path.exists():
            frozen = read_json(frozen_path)
            require(frozen["identity_sha256"] == digest(identity), "batch_modified", "Batch/config/input bytes changed; create a new comparison run")
        else:
            require(not resume, "batch_missing", "No frozen batch exists to resume")
            frozen = {"schema_version": "hre_batch_freeze_v3", **identity,
                      "identity_sha256": digest(identity), "created_at": now(), "frozen_inputs": _freeze_inputs(root, value)}
            write_json(frozen_path, frozen)
        result = {"schema_version": "hre_batch_state_v3", "created_at": frozen["created_at"], "updated_at": now(),
                  "identity_sha256": frozen["identity_sha256"], "runs": [], "planning": [], "status": "running"}
        run_kwargs = {"stage_fn": stage_fn, "compile_fn": compile_fn, "execute_fn": execute_fn}
        for original_case in value["cases"]:
            case = _snapshot_case(original_case, frozen["frozen_inputs"])
            shared = None
            planning_problem = None
            if value["share_planning"] and any(arm["strategy"] != "native" for arm in value["arms"]):
                planning_root = root / "planning" / case["id"]
                plan_arm = {"name": "planning", "strategy": "shared", "policy": "single", "max_generations": 1}
                planning_spec = _task(case, case["models"][0], plan_arm, value["seeds"][0])
                try:
                    _snapshot_case(original_case, frozen["frozen_inputs"])
                    if not (planning_root / "state.json").exists():
                        create_case(planning_root, planning_spec, config)
                    _snapshot_case(original_case, frozen["frozen_inputs"])
                    _check_imported_case(planning_root, original_case)
                    state = run_case(planning_root, stop_after="compose", **run_kwargs)
                    result["planning"].append({"case_id": case["id"], "path": str(planning_root),
                                               "status": state["status"], "budget": state.get("budget")})
                    shared = planning_root / "artifacts" / "shared_intent.json"
                    if not shared.is_file():
                        shared = None
                        planning_problem = state.get("terminal_reason") or state.get("pause_reason") or "planning_not_ready"
                except Exception as exc:
                    planning_problem = str(exc)
                    result["planning"].append({"case_id": case["id"], "path": str(planning_root), "status": "failed", "error": str(exc)})
            for model in case["models"]:
                for arm in value["arms"]:
                    for seed in value["seeds"]:
                        case_root = root / "runs" / case["id"] / model / arm["name"] / f"seed_{seed}"
                        record = {"dataset_case_id": case["id"], "profile_id": model, "arm": arm["name"],
                                  "seed": seed, "case_root": str(case_root)}
                        if arm["strategy"] != "native" and value["share_planning"] and shared is None:
                            record.update(status="blocked_planning", error=planning_problem)
                        else:
                            try:
                                _snapshot_case(original_case, frozen["frozen_inputs"])
                                task = _task(case, model, arm, seed)
                                if shared is not None and arm["strategy"] != "native":
                                    task["shared_intent"] = str(shared)
                                if not (case_root / "state.json").exists():
                                    create_case(case_root, task, config)
                                _snapshot_case(original_case, frozen["frozen_inputs"])
                                _check_imported_case(case_root, original_case)
                                state = run_case(case_root, **run_kwargs)
                                record.update(status=state["status"], success=state.get("success", False),
                                              quality_status=state.get("quality_status"), budget=state.get("budget"),
                                              selected_kind=state.get("selected_kind"), selected_output=state.get("selected_output"))
                            except Exception as exc:
                                record.update(status="failed", error=str(exc))
                        result["runs"].append(record)
                        result["updated_at"] = now()
                        write_json(root / "batch.state.json", result)
        result["status"] = "completed" if all(row["status"] == "completed" for row in result["runs"]) else "partial"
        result["updated_at"] = now()
        write_json(root / "batch.state.json", result)
        return result
