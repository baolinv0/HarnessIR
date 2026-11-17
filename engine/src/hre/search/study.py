"""Freeze the study, register constrained proposals, and run the existing v3 engine."""
from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path
import re

from ..models import file_sha256, sha256_bytes
from ..storage import atomic_write, case_lock, read_json, write_json
from ..v3.batch import resolve_config_paths
from ..v3.common import digest, require
from ..v3.contracts import MODEL_CATALOG, create_case, load_case, normalise_spec, validate_config
from ..v3.runner import run_case
from ..v3.runner_journal import Journal, immutable_json
from .texture import TASK, validate_thresholds


def evaluator_identity() -> str:
    return digest({name: Path(__file__).with_name(name).read_text(encoding="utf-8")
                   for name in ("review.py", "texture.py")})

SPLITS = ("dev", "selection", "test")
BASELINE = "baseline"
DIRECT = "direct"
VERSION = "hre_texture_search_v1"
_POLICY = {"strategy": "model_aware", "instruction": "", "evidence": "all"}
_RESERVED = {"aux", "con", "nul", "prn"} | {f"{prefix}{n}" for prefix in ("com", "lpt") for n in range(1, 10)}


def check_id(value: str) -> str:
    require(isinstance(value, str) and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", value) and value not in _RESERVED,
            "search_id_invalid", "Use a lowercase name with letters, digits and hyphens")
    return value


def fields(value: dict, allowed: set[str], name: str) -> None:
    require(isinstance(value, dict) and set(value) <= allowed,
            "search_schema_invalid", f"Invalid or unexpected fields in {name}")


def _asset(root: Path, sample_id: str, kind: str, path: Path) -> dict:
    data = path.read_bytes()
    path = root / "assets" / sample_id / (kind + ".original")
    atomic_write(path, data)
    return {"path": path.relative_to(root).as_posix(), "sha256": sha256_bytes(data)}


def asset_path(root: Path, receipt: dict) -> Path:
    path = (root / receipt["path"]).resolve()
    require(path.is_relative_to(root) and path.is_file() and file_sha256(path) == receipt["sha256"],
            "study_asset_changed", "Study image or review attachment no longer matches its receipt")
    return path


def _sample(row: dict, base: Path) -> dict:
    fields(row, {"id", "scene", "split", "source", "gt", "regions", "brief", "requires_verified_content"}, "sample")
    value = deepcopy(row)
    for name in ("id", "scene"):
        check_id(value[name])
    require(value.get("split") in SPLITS, "study_split_invalid", "Each sample requires dev, selection, or test")
    target = value.get("brief", "")
    require(isinstance(target, str), "study_sample_invalid", "Image-specific texture target must be text")
    value["brief"] = TASK + ("\nImage-specific texture target: " + target.strip() if target.strip() else "")
    value.setdefault("requires_verified_content", False)
    require(type(value["requires_verified_content"]) is bool, "study_sample_invalid", "Use a boolean content requirement")
    value.setdefault("regions", [])
    require(isinstance(value["regions"], list), "study_sample_invalid", "Regions must be an array")
    for region in value["regions"]:
        fields(region, {"id", "description", "source_box", "role"}, "region")
        require(region.get("id") != "full_frame" and region.get("role") in {"target", "protected"},
                "study_region_invalid", "Use a unique region ID with a target/protected role")
        region.setdefault("description", "Texture target" if region["role"] == "target" else "Protected content")
    for kind in ("source", "gt"):
        if kind in value:
            value[kind] = (base / value[kind]).resolve()
            require(value[kind].is_file(), "study_asset_missing", f"Missing {kind} for {value['id']}")
    require("source" in value, "study_asset_missing", "Each sample requires a source image")
    require(not value["requires_verified_content"] or "gt" in value, "study_gt_required",
            "A sample that requires verified content needs an offline reference")
    return value


def _spec(study: dict, profile: str, sample: dict, policy: dict, source: Path) -> dict:
    seeds = study["seeds"]
    regions = [row for row in sample["regions"] if policy["evidence"] == "all" or row["role"] == policy["evidence"]]
    brief = sample["brief"]
    if policy["instruction"]:
        brief += "\nRestoration strategy: " + policy["instruction"]
    return normalise_spec({
        "case_id": sample["id"], "profile_id": profile, "task_mode": "restoration", "strategy": policy["strategy"],
        "brief": brief, "source": {"path": str(source)}, "regions": regions,
        "geometry": study["geometry"],
        "policy": {"mode": "resample" if len(seeds) > 1 else "single", "max_generations": len(seeds),
                   "seed_schedule": seeds},
        "evaluation": {"task_goal": sample["brief"], "preserve_identity_text_geometry": True,
                       "reference_content_transfer_allowed": False},
    })


def initialize(root: Path, manifest: Path, config_path: Path) -> dict:
    root = root.resolve()
    manifest = manifest.resolve()
    config_path = config_path.resolve()
    value = read_json(manifest)
    fields(value, {"profiles", "samples", "thresholds", "seeds", "geometry", "maximum_proposals", "minimum_gain",
                   "calibration_note"}, "study")
    profiles = value["profiles"]
    require(isinstance(profiles, list) and profiles and all(isinstance(p, str) for p in profiles)
            and len(profiles) == len(set(profiles)), "study_profiles_invalid", "List distinct v3 profile IDs")
    runtime = resolve_config_paths(read_json(config_path), config_path.parent)
    # Keep only explicitly selected runtimes in the frozen configuration.
    model_configs = {}
    for profile in profiles:
        require(profile in MODEL_CATALOG, "study_profiles_invalid", f"Unknown profile: {profile}")
        model_configs[profile] = validate_config(runtime, profile)["models"][profile]
    runtime["models"] = model_configs
    seeds = value["seeds"]
    require(isinstance(seeds, list) and 1 <= len(seeds) <= 16
            and all(type(seed) is int and 0 <= seed < 2**63 for seed in seeds)
            and len(seeds) == len(set(seeds)), "study_seeds_invalid", "Freeze 1–16 distinct nonnegative seeds")
    geometry = value.get("geometry", {"policy": "pad", "grid": 32})
    fields(geometry, {"policy", "grid", "width", "height"}, "geometry")
    cap = value.get("maximum_proposals", 6)
    gain = value.get("minimum_gain", 0)
    note = value["calibration_note"]
    require(type(cap) is int and 1 <= cap <= 100 and type(gain) in {int, float} and math.isfinite(gain)
            and 0 <= gain <= 1 and isinstance(note, str) and bool(note.strip()),
            "study_limits_invalid", "Freeze a proposal cap, an improvement margin, and a calibration note")
    study = {"schema": VERSION, "profiles": profiles, "seeds": seeds, "geometry": geometry,
             "thresholds": validate_thresholds(value["thresholds"]), "calibration_note": note,
             "maximum_proposals": cap, "minimum_gain": gain, "runtime_sha256": digest(runtime),
             "evaluator_sha256": evaluator_identity()}
    require(isinstance(value["samples"], list) and value["samples"], "study_samples_invalid", "List study samples")
    samples = [_sample(row, manifest.parent) for row in value["samples"]]
    require(len({row["id"] for row in samples}) == len(samples), "study_duplicate", "Duplicate sample ID")
    require({row["split"] for row in samples} == set(SPLITS), "study_split_missing", "Each split must have at least one scene")
    scenes, sources, source_hashes = {}, {}, {}
    for row in samples:
        split = row["split"]
        source_hashes[row["id"]] = file_sha256(row["source"])
        require(scenes.setdefault(row["scene"], split) == split
                and sources.setdefault(source_hashes[row["id"]], split) == split,
                "study_split_leak", "A scene or original image occurs in more than one split")
        for profile in profiles:
            _spec(study, profile, row, _POLICY, row["source"])
    with case_lock(root):
        require(not (root / "study.json").exists(), "study_exists", "Freeze a new study in a new directory")
        for row in samples:
            for kind in ("source", "gt"):
                if kind in row:
                    row[kind] = _asset(root, row["id"], kind, row[kind])
                    if kind == "source":
                        require(row["source"]["sha256"] == source_hashes[row["id"]],
                                "study_asset_changed", "Source changed during study initialization")
        study["samples"] = samples
        immutable_json(root / "runtime.json", runtime)
        immutable_json(root / "study.json", {**study, "study_sha256": digest(study)})
    return {"study": str(root), "study_sha256": digest(study), "profiles": profiles,
            "sample_counts": {split: sum(s["split"] == split for s in samples) for split in SPLITS}}


def load_study(root: Path) -> dict:
    study = read_json(root / "study.json")
    require(study.get("schema") == VERSION
            and study.get("study_sha256") == digest({k: v for k, v in study.items() if k != "study_sha256"}),
            "study_modified", "Frozen study settings changed")
    require(study["evaluator_sha256"] == evaluator_identity(), "evaluator_changed",
            "Run this study with its original evaluator version")
    return study


def _version_record(study: dict, value: dict) -> dict:
    payload = {**value, "study_sha256": study["study_sha256"]}
    return {**payload, "version_sha256": digest(payload)}


def version(root: Path, study: dict, candidate: str) -> dict:
    check_id(candidate)
    if candidate in {DIRECT, BASELINE}:
        policy = {**_POLICY, **({"strategy": "native", "evidence": "none"} if candidate == DIRECT else {})}
        return _version_record(study, {"id": candidate, "parent": None, "policies": dict.fromkeys(study["profiles"], policy)})
    result = read_json(root / "versions" / (candidate + ".json"))
    require(result["id"] == candidate and result == _version_record(
        study, {k: v for k, v in result.items() if k != "version_sha256"}),
        "search_version_modified", "Frozen proposal changed")
    return result


def _policy(existing: dict, proposal: dict) -> dict:
    fields(proposal, set(_POLICY), "policy")
    policy = {**existing, **proposal}
    require(policy["strategy"] in {"shared", "model_aware"}
            and isinstance(policy["instruction"], str) and len(policy["instruction"]) <= 4000
            and policy["evidence"] in {"all", "target", "protected", "none"},
            "search_policy_invalid", "Use a supported strategy, instruction, and ROI evidence policy")
    return policy


def register(root: Path, proposal: dict) -> dict:
    root = root.resolve()
    fields(proposal, {"id", "parent", "hypothesis", "policy", "model_overrides"}, "proposal")
    candidate = check_id(proposal["id"])
    parent_id = check_id(proposal["parent"])
    hypothesis = proposal["hypothesis"]
    require(candidate not in {BASELINE, DIRECT} and parent_id != DIRECT and isinstance(hypothesis, str)
            and 0 < len(hypothesis.strip()) <= 4000, "search_proposal_invalid", "Supply a new version ID, a parent and a hypothesis")
    with case_lock(root):
        study = load_study(root)
        parent = version(root, study, parent_id)
        overrides = proposal.get("model_overrides", {})
        fields(overrides, set(study["profiles"]), "model_overrides")
        policies = {p: _policy(_policy(parent["policies"][p], proposal.get("policy", {})), overrides.get(p, {}))
                    for p in study["profiles"]}
        require(policies != parent["policies"], "search_no_change", "The proposal matches its parent")
        path = root / "versions" / (candidate + ".json")
        record = _version_record(study, {"id": candidate, "parent": parent_id, "hypothesis": hypothesis, "policies": policies})
        if path.is_file():
            return immutable_json(path, record)
        require(not (root / "final.json").exists(), "search_frozen", "The final evaluation is frozen")
        require(len(list(path.parent.glob("*.json"))) < study["maximum_proposals"],
                "search_budget_exhausted", "The frozen proposal budget is exhausted")
        return immutable_json(path, record)


def gate_split(root: Path, study: dict, split: str, candidate: str, profile: str) -> None:
    require(split in SPLITS and profile in study["profiles"], "search_split_invalid", "Unknown split or profile")
    if split == "test":
        locked = read_json(root / "final.json") if (root / "final.json").is_file() else {}
        require(locked.get("study_sha256") == study["study_sha256"]
                and locked.get("versions", {}).get(profile, {}).get(candidate) == version(root, study, candidate)["version_sha256"],
                "test_locked", "Freeze the final selection before any test run")


def case_path(root: Path, split: str, profile: str, candidate: str, sample: dict) -> Path:
    return root / "runs" / split / profile / candidate / sample["id"]


def case_state(path: Path) -> tuple[dict, dict]:
    spec, _, state = load_case(path)
    return spec, Journal(path, state, read_only=True).state


def run(root: Path, split: str, profile: str, candidate: str, **workers) -> dict:
    root = root.resolve()
    with case_lock(root):
        study = load_study(root)
        entry = version(root, study, candidate)
        gate_split(root, study, split, candidate, profile)
        runtime = read_json(root / "runtime.json")
        require(digest(runtime) == study["runtime_sha256"], "study_modified", "Frozen runtime settings changed")
        results = []
        for row in study["samples"]:
            if row["split"] != split:
                continue
            path = case_path(root, split, profile, candidate, row)
            source = asset_path(root, row["source"])
            spec = _spec(study, profile, row, entry["policies"][profile], source)
            if not (path / "freeze.json").exists():
                create_case(path, spec, runtime)
            else:
                frozen_spec, frozen_config, state = load_case(path)
                expected_spec = {**spec, "source": {"path": state["inputs"][0]["path"]}}
                require(frozen_spec == expected_spec and frozen_config == runtime
                        and state["inputs"][0]["original_sha256"] == row["source"]["sha256"],
                        "search_run_mismatch", "An existing run belongs to a different frozen strategy or source")
            state = run_case(path, **workers)
            results.append({"sample": row["id"], "status": state["status"], "case_root": str(path),
                            "budget": state.get("budget", {}), "reason": state.get("pause_reason") or state.get("terminal_reason")})
        return {"split": split, "profile": profile, "candidate": candidate, "cases": results,
                "all_terminal": all(row["status"] in {"completed", "failed"} for row in results),
                "accepted": all(row["status"] == "completed" for row in results)}


def freeze_final(root: Path, reason: str) -> dict:
    root = root.resolve()
    require(isinstance(reason, str) and bool(reason.strip()), "search_reason_required", "Record the reason for freezing")
    with case_lock(root):
        study = load_study(root)
        path = root / "final.json"
        if path.is_file():
            return read_json(path)
        active = incumbents(root, study)
        versions = {p: {c: version(root, study, c)["version_sha256"] for c in {DIRECT, BASELINE, active[p]}}
                    for p in study["profiles"]}
        return immutable_json(path, {"study_sha256": study["study_sha256"], "active": active,
                                    "versions": versions, "reason": reason})


def incumbents(root: Path, study: dict) -> dict:
    path = root / "incumbents.json"
    if not path.exists():
        return dict.fromkeys(study["profiles"], BASELINE)
    return read_json(path)["active"]
