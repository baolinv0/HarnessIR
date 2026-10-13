"""File-only experiment preregistration, neutral review packages, and ITT analysis.

No model calls or quality claims are produced by freezing a run. The case-arm
outcome and rating contracts are documented in .work/ref_enhance/outputs_report.md.
"""
from collections import Counter, defaultdict
from copy import deepcopy
import math
from pathlib import Path
import random
import re
from importlib.resources import files as resource_files
import numpy as np
from .assets import validate_asset
from .prompts import STAGES, normalize_protected_content, validate_execution_templates
from .models import HREError, canonical_json, config_hash, file_sha256, sha256_bytes
from .paths import safe_path
from .reporting import resolve_selected_asset, cost_summary, _events
from .storage import CaseStore, atomic_write, read_json, write_json

ARMS = {"baseline": 0, "direct_ref": 1, "agent_single": 1, "agent_adaptive": 3, "direct_best_of_3": 3}
BOOTSTRAP_SEED = 20261015
BOOTSTRAP_REPLICATES = 10000


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _real_hash(value):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) and value != "0" * 64


def _file(root, record, path_key="path", hash_key="sha256"):
    _require(_real_hash(record.get(hash_key)), "missing or placeholder file hash")
    path = safe_path(root, record[path_key], must_exist=True)
    _require(path.is_file() and file_sha256(path) == record[hash_key], "file hash mismatch: " + record[path_key])
    return path


def _reject_examples(value):
    if isinstance(value, dict):
        _require(not value.get("example_only") and not value.get("simulation_only"), "example/simulation cannot be enrolled")
        for key, item in value.items():
            if key.endswith("sha256") and item is not None:
                _require(_real_hash(item), "placeholder/invalid SHA256")
            if key in {"path", "case_root", "dataset_root", "checkpoint_path", "environment_manifest_path"} and isinstance(item, str):
                _require("placeholder" not in item.lower() and "example" not in item.lower(), "placeholder/example path")
            _reject_examples(item)
    elif isinstance(value, list):
        for item in value:
            _reject_examples(item)


def _formal_case(case, root):
    _require(case.get("ready_for_enrollment") is True, "case not approved for enrollment")
    provenance = case.get("baseline_provenance", {})
    _require(provenance.get("provenance_complete") is True, "baseline provenance incomplete")
    for field in ["repository_url", "repository_commit", "predict_command_observed", "predict_working_directory", "prediction_time"]:
        _require(provenance.get(field) not in {None, "", "unknown"}, "missing baseline " + field)
    _require(re.fullmatch(r"[a-fA-F0-9]{40,64}", provenance["repository_commit"]), "invalid baseline commit")
    _require(isinstance(provenance.get("working_tree_dirty"), bool), "unknown dirty status")
    if provenance["working_tree_dirty"]:
        _require(_real_hash(provenance.get("working_tree_diff_sha256")), "missing dirty diff hash")
        _file(root, provenance, "working_tree_diff_path", "working_tree_diff_sha256")
    _file(root, provenance, "checkpoint_path", "checkpoint_sha256")
    _file(root, provenance, "environment_manifest_path", "environment_manifest_sha256")
    _require(sha256_bytes(provenance["predict_command_observed"].encode()) == provenance.get("predict_command_sha256"), "predict command hash mismatch")
    sources = case.get("source_files", {})
    for role in ["prediction_source_raw", "prediction_original", "reference_original"]:
        _file(root, sources.get(role, {}))
    _require(provenance.get("input_raw_sha256") == sources["prediction_source_raw"]["sha256"], "raw provenance mismatch")
    _require(provenance.get("prediction_output_sha256") == sources["prediction_original"]["sha256"], "prediction provenance mismatch")
    assets = {a["role"]: a for a in case["assets"]}
    for role in ["prediction", "reference"]:
        original = sources[role + "_original"]
        actual = assets[role]["source_file"]
        _require(original["sha256"] == actual["sha256"] and _file(root, original).resolve() == _file(root, actual).resolve(), role + " original differs from actual asset source")
    canonical = case.get("canonicalization", {})
    _require(canonical.get("status") in {"complete", "ok", "completed"} and canonical.get("destination_profile") == "sRGB", "unexplained canonical color conversion")
    for field in ["tool_name", "tool_version", "parameters_sha256"]:
        _require(canonical.get(field) not in {None, "", "unknown"}, "missing canonicalization " + field)
    for role in ["prediction", "reference"]:
        _require(canonical.get(role, {}).get("source_profile_explained") is True, "unexplained source color")
    reference = sources["reference_original"]
    _require(reference.get("device_verification_status") in {"verified", "observed"} and reference.get("camera_model_observed") not in {None, "", "unknown"}, "unverified reference device")
    comparability = case.get("comparability", {})
    _require(comparability.get("annotated_before_any_arm_output") is True and comparability.get("reference_usable") == "usable", "reference lacks pre-output usable annotation")
    for field in ["annotator", "annotated_at", "rules_version"]:
        _require(comparability.get(field) not in {None, "", "unknown"}, "missing comparability approval")
    _require(bool(comparability.get("comparable_rendering_dimensions")), "no comparable rendering dimension")
    _require(not comparability.get("pre_enrollment_exclusion_reason"), "pre-enrollment exclusion")
    audit = case.get("leakage_audit", {})
    _require(audit.get("status") in {"passed", "pass", "complete"} and audit.get("group_association_review_complete") is True and audit.get("descendant_split_inheritance_verified") is True, "incomplete leakage audit")
    _require(audit.get("same_raw_or_burst_across_splits") is False and audit.get("reference_or_candidates_used_for_test_tuning") is False, "test leakage")
    _file(root, audit, "audit_report_path", "audit_report_sha256")
    enrollment = case.get("enrollment", {})
    _require(enrollment.get("approved_by") and enrollment.get("approved_at") and not enrollment.get("required_missing_items"), "missing enrollment approval")
    _file(root, enrollment, "preflight_report_path", "preflight_report_sha256")


def _referenced_files(value, root):
    """Copy only explicit, checked provenance files, never a whole external tree."""
    found = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, str) and (key == "path" or key.endswith("_path")):
                hash_key = "sha256" if key == "path" else key[:-5] + "_sha256"
                if _real_hash(value.get(hash_key)):
                    found.add(_file(root, value, key, hash_key))
            if isinstance(item, (dict, list)):
                found.update(_referenced_files(item, root))
    elif isinstance(value, list):
        for item in value:
            found.update(_referenced_files(item, root))
    return found


def _runtime_rois(case):
    if case.get("roi_manifest"):
        return deepcopy(case["roi_manifest"])
    result = []
    for record in case.get("comparability", {}).get("ROI_pairs", []):
        boxes = {}
        for role in ["prediction", "reference"]:
            x, y, width, height = record[role + "_xywh"]
            _require(all(isinstance(v, (float, int)) and math.isfinite(v) for v in [x, y, width, height]) and 0 <= x < x + width <= 1 and 0 <= y < y + height <= 1, "invalid independent normalized ROI")
            boxes[role] = [x, y, x + width, y + height]
        flags = [record.get(k) for k in ["matched_semantics_observed", "comparable_illumination_observed", "occlusion_free_observed", "semantic_composition_comparable_observed"]]
        comparability = record.get("comparability") or ("comparable" if all(v is True for v in flags) and record.get("valid_for_auxiliary_statistics") is True else "not_comparable" if any(v is False for v in flags) else "unknown")
        result.append({"roi_pair_id": record["ROI_pair_id"], **boxes, "coordinate_system": "canonical_norm",
                       "comparability": comparability, "reason": record.get("annotation_notes") or "Frozen pre-enrollment independent A/B annotation."})
    return result


def freeze_run(manifest: Path, profile: Path, destination: Path) -> Path:
    manifest, profile, destination = Path(manifest), Path(profile), Path(destination)
    data, profiles = read_json(manifest), read_json(profile)
    _reject_examples(data)
    _require(data.get("manifest_kind") != "example_only", "example manifest")
    _require(data.get("schema_version") == "ref_enhance_v1", "wrong manifest version")
    _require(data.get("reference_is_pixel_ground_truth", False) is False and data.get("future_pseudo_target_policy", {}).get("reference_is_pixel_ground_truth", False) is False, "reference cannot be pixel ground truth")
    pilot = data.get("allow_unverified") is True
    if pilot:
        _require(data.get("manifest_kind") == "pilot", "allow_unverified requires explicitly pilot manifest")
    else:
        _require(data.get("ready_for_enrollment") is True, "manifest not ready for enrollment")
    _require(profiles.get("schema_version") == "ref_enhance_v1" and profiles.get("reference_is_pixel_ground_truth") is False, "invalid experiment profiles")
    common = profiles["common"]
    _require(common["output_normalization"].get("preserve_raw_generated_file") is True
             and all(common["output_normalization"].get(k) is False for k in ["warp_allowed", "crop_allowed", "post_generation_color_adjustment_allowed"]), "normalization permits forbidden edits")
    _require(common["selector"]["selector_version"] == "earliest_accepted_then_earliest_usable_v1" and common["selector"]["accept_requirements"]["minimum_confidence"] == .7, "selector differs from frozen V1")
    _require(common["selector"].get("rank_by_confidence") is False and common["selector"].get("rank_by_no_reference_score") is False, "quality ranking prohibited")
    selected = data.get("run_linkage", {}).get("selected_profile_ids") or list(ARMS)
    _require(len(set(selected)) == len(selected) and all(a in ARMS for a in selected), "unsupported or duplicate arm")
    for arm in selected:
        _require(profiles["profiles"][arm].get("enabled") is True and profiles["profiles"][arm]["max_generations"] == ARMS[arm], "incorrect arm generation cap")
    normalization = common["output_normalization"]
    mode = normalization.get("mode", "strict")
    _require(mode in {"strict", "aspect_preserving_resize"}, "unknown geometry mode")
    if mode != "strict":
        _require(normalization.get("optional_aspect_preserving_resize", {}).get("enabled") is True and profiles["config_version"] != "experiment_profiles_v1_20261013", "scale requires new frozen configuration version")
    cases = data.get("cases", [])
    _require(bool(cases), "empty experiment")
    _require(len({(c["case_id"], c["case_revision"]) for c in cases}) == len(cases), "duplicate case revision")
    _require(len({c["case_id"] for c in cases}) == len(cases), "one case revision per frozen run")
    for case in cases:
        normalize_protected_content(case.get('content_preservation_annotations'))
    associations = defaultdict(set)
    hashes = defaultdict(set)
    resolved = []
    for case in cases:
        _require(isinstance(case.get("case_id"), str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", case["case_id"]), "unsafe case identity")
        _require(type(case.get("case_revision")) is int and case["case_revision"] >= 0, "invalid case revision")
        _require(case.get("split") in {"dev", "validation", "test"} and case.get("scene_group_id"), "missing scene group/split")
        _require(not (case["split"] == "test" and (pilot or case.get("pilot_stage") or case.get("used_for_tuning") is True)), "pilot/tuning case cannot be test")
        audit = case.get("leakage_audit", {})
        _require(audit.get("reference_or_candidates_used_for_test_tuning") is not True and audit.get("same_raw_or_burst_across_splits") is not True, "observed split leakage")
        for key in ["scene_group_id", "capture_event_id", "source_DNG_family_id"]:
            if case.get(key): associations[(key, case[key])].add(case["split"])
        for key in ["physical_scene_family"]:
            if case.get("scene", {}).get(key): associations[(key, case["scene"][key])].add(case["split"])
        root = safe_path(manifest.parent, case["case_root"], must_exist=True)
        _runtime_rois(case)
        roles = Counter(asset["role"] for asset in case["assets"])
        _require(roles == {"prediction": 1, "reference": 1}, "exactly prediction and reference required")
        for asset in case["assets"]:
            _require(_real_hash(asset["sha256"]), "placeholder asset")
            validate_asset(asset, root)
            _require(asset.get("source_file") and asset.get("canonicalization") and asset.get("pixel_sha256"), "missing real original/canonical provenance")
            hashes[asset["sha256"]].add(case["split"])
            hashes[asset["source_file"]["sha256"]].add(case["split"])
        for source in case.get("source_files", {}).values():
            if isinstance(source, dict) and source.get("path"):
                _file(root, source)
                hashes[source["sha256"]].add(case["split"])
        raw_hash = case.get("baseline_provenance", {}).get("input_raw_sha256")
        if raw_hash: hashes[raw_hash].add(case["split"])
        if not pilot: _formal_case(case, root)
        resolved.append((case, root, _referenced_files(case, root)))
    _require(all(len(splits) == 1 for splits in associations.values()) and all(len(splits) == 1 for splits in hashes.values()), "cross-split group/source/asset leakage")
    near_path = None
    if not pilot:
        near = data.get("split_protocol", {}).get("near_duplicate_check", {})
        _require(near.get("status") in {"passed", "pass", "complete"}, "near duplicate audit missing")
        near_path = _file(manifest.parent, near, "report_path", "report_sha256")
    _require(not destination.exists() or not any(destination.iterdir()), "run destination is not empty")
    destination.mkdir(parents=True, exist_ok=True)
    frozen = deepcopy(data)
    rng = random.Random(20261013)
    outcomes = []
    for case, root, files in resolved:
        destroot = safe_path(destination, "frozen_inputs/" + case["case_id"])
        for path in files:
            output = safe_path(destroot, path.relative_to(root).as_posix())
            output.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(output, path.read_bytes())
        arm_order = list(selected); rng.shuffle(arm_order)
        for order, arm in enumerate(arm_order):
            outcomes.append({"case_id": case["case_id"], "case_revision": case["case_revision"], "scene_group_id": case["scene_group_id"],
                             "split": case["split"], "arm_id": arm, "execution_order": order, "status": "planned",
                             "case_root": "records/" + case["case_id"] + "/" + arm, "input_case_root": "frozen_inputs/" + case["case_id"],
                             "selected_asset": None, "selected_asset_root": None, "workflow_success": False})
        write_json(destination / "case_manifests" / (case["case_id"] + ".json"), case)
    write_json(destination / "manifest.json", frozen)
    write_json(destination / "profile.json", profiles)
    provenance_files = {}
    if near_path:
        copied_near = destination / "provenance/near_duplicates.json"
        atomic_write(copied_near, near_path.read_bytes())
        provenance_files["provenance/near_duplicates.json"] = file_sha256(copied_near)
    runtime_files = {"case_manifests/" + c["case_id"] + ".json": file_sha256(destination / "case_manifests" / (c["case_id"] + ".json")) for c in cases}
    prompt_files = {}
    for template in resource_files("hre").joinpath("resources/prompts").iterdir():
        if template.name.endswith(".j2"):
            path = destination / "prompts" / template.name
            atomic_write(path, template.read_bytes())
            prompt_files[path.relative_to(destination).as_posix()] = file_sha256(path)
    _require(set(path.rsplit("/", 1)[-1] for path in prompt_files) == {"diagnose.j2", "compose.j2", "execute.j2", "verify.j2", "refine.j2", "direct_ref.j2"}, "missing frozen prompt template")
    template_identities = {Path(path).stem: digest for path, digest in prompt_files.items()}
    for arm in selected:
        runtime = {"profile_id": arm, "max_generations": ARMS[arm], "format_repair_limit": common["format_repair_limit"],
                   "geometry_policy": {"mode": mode, "max_aspect_ratio_error": 0 if mode == "strict" else .005},
                   "assume_srgb": False, "reference_usable": "unknown", "roi_manifest": [], "protected_content": [],
                   "reference_limitations": [], "cache_root": None, "tool_profile": {}, "prompt_template_sha256": template_identities}
        write_json(destination / "runtime_configs" / (arm + ".json"), runtime)
        runtime_files["runtime_configs/" + arm + ".json"] = file_sha256(destination / "runtime_configs" / (arm + ".json"))
        for case in cases:
            specific = deepcopy(runtime)
            annotation = case.get("comparability", {})
            specific["reference_usable"] = annotation.get("reference_usable", "unknown") or "unknown"
            specific["reference_limitations"] = annotation.get("reference_limitations", [])
            specific["protected_content"] = normalize_protected_content(case.get("content_preservation_annotations"))
            specific["roi_manifest"] = _runtime_rois(case)
            path = destination / "runtime_configs" / case["case_id"] / (arm + ".json")
            write_json(path, specific)
            runtime_files[path.relative_to(destination).as_posix()] = file_sha256(path)
    write_json(destination / "planned_outcomes.json", {"schema_version": "hre_outcomes_v1", "outcomes": outcomes})
    run = {"schema_version": "hre_run_v1", "formal": not pilot, "allow_unverified": pilot,
           "manifest_sha256": file_sha256(destination / "manifest.json"), "profile_sha256": file_sha256(destination / "profile.json"),
           "planned_identities": [{k: o[k] for k in ["case_id", "case_revision", "scene_group_id", "split", "arm_id"]} for o in outcomes],
           "limitations": ["Explicit unverified pilot; provenance/approval gaps prohibit formal claims."] if pilot else [],
           "status": "frozen_not_run", "provenance_files": provenance_files, "runtime_files": runtime_files, "prompt_files": prompt_files,
           "bootstrap_seed": BOOTSTRAP_SEED, "bootstrap_replicates": BOOTSTRAP_REPLICATES,
           "model_version": "unknown", "model_seed": "unknown", "observed_billed_cost": None}
    write_json(destination / "run.json", run)
    return destination / "run.json"


def _load_run(root):
    run = read_json(root / "run.json")
    _require(file_sha256(root / "manifest.json") == run["manifest_sha256"] and file_sha256(root / "profile.json") == run["profile_sha256"], "frozen run input changed")
    for path, digest in {**run.get("provenance_files", {}), **run.get("runtime_files", {}), **run.get("prompt_files", {})}.items():
        _require(file_sha256(safe_path(root, path, must_exist=True)) == digest, "frozen provenance changed")
    manifest = read_json(root / "manifest.json")
    outcomes = read_json(root / "planned_outcomes.json")["outcomes"]
    identities = [{k: o[k] for k in ["case_id", "case_revision", "scene_group_id", "split", "arm_id"]} for o in outcomes]
    _require(sorted(identities, key=canonical_json) == sorted(run["planned_identities"], key=canonical_json), "planned ITT identities changed")
    for case in manifest["cases"]:
        input_root = safe_path(root, "frozen_inputs/" + case["case_id"], must_exist=True)
        _referenced_files(case, input_root)
        for asset in case["assets"]:
            validate_asset(asset, input_root)
    return run, manifest, outcomes


def _outcome_asset(root, outcome):
    state_path = safe_path(root, "records/" + outcome["case_id"] + "/" + outcome["arm_id"]) / "state.json"
    if state_path.exists():
        state = CaseStore(state_path.parent).load()
        _require(state["case_id"] == outcome["case_id"] and state["case_revision"] == outcome["case_revision"], "outcome state case identity mismatch")
        selected = resolve_selected_asset(state)
        selected_root = state_path.parent
        status = "completed" if state["workflow_state"] == "COMPLETED" else "failed" if state["workflow_state"] == "FAILED" else "cancelled" if state["workflow_state"] == "CANCELLED" else "planned"
        _require(sum(e["charged_count"] for e in state["budget"]["ledger"]) == state["budget"]["consumed"], "outcome generation ledger mismatch")
        if state["budget"]["consumed"] > ARMS[outcome["arm_id"]]: status = "failed"
        return selected, selected_root, status, state
    selected = outcome.get("selected_asset")
    selected_root = safe_path(root, outcome["selected_asset_root"], must_exist=True) if selected else None
    _require(outcome["status"] in {"planned", "completed", "failed", "cancelled"}, "invalid outcome status")
    if selected and selected["role"] == "candidate":
        binding = selected.get("candidate_binding", {})
        _require(binding.get("case_id") == outcome["case_id"] and binding.get("case_revision") == outcome["case_revision"], "selected candidate belongs to another case")
    return selected, selected_root, outcome["status"], None


def _expected_config(root, case, arm):
    config = read_json(root / "runtime_configs" / case["case_id"] / (arm + ".json"))
    profile = read_json(root / "profile.json")
    prediction = next(a for a in case["assets"] if a["role"] == "prediction")
    policy = config["geometry_policy"]
    config["geometry_policy"] = {"mode": policy.get("mode", "strict"), "target_width": prediction["width"],
                                 "target_height": prediction["height"], "max_aspect_ratio_error": 0 if policy.get("mode", "strict") == "strict" else .005, **policy}
    config.setdefault("stats_metric", profile["common"]["stats_metric"])
    config.update(schema_version="ref_enhance_v1", canonicalizer_version="hre_rgb8_v1")
    config["config_sha256"] = config_hash(config)
    return config



def _external_execution(root, outcome):
    contract = outcome['execution_contract']
    record_root = safe_path(root, contract['execution_record_root'], must_exist=True)
    state = CaseStore(record_root).load()
    _require({'COMPLETED':'completed', 'FAILED':'failed', 'CANCELLED':'cancelled'}.get(state['workflow_state']) == outcome['status'] and all(state[k] == outcome[k] for k in ('case_id', 'case_revision')), 'external journal case/status mismatch')
    selected = resolve_selected_asset(state)
    _require(selected == outcome['selected_asset'], 'external journal selected asset mismatch')
    config = _file(root, contract)
    _require(config.resolve() == (record_root / 'config.json').resolve(), 'external config is not journal config')
    return record_root, state


def _protocol_violations(root, outcome, case, state, selected_root):
    expected = _expected_config(root, case, outcome["arm_id"])
    if state is None:
        if (outcome.get("selected_asset") or {}).get("role") == "candidate":
            contract = outcome.get("execution_contract")
            if not contract:
                return ["unverified_external_execution_contract"]
            try:
                _require(isinstance(contract, dict), "invalid external contract shape")
                config_path = _file(root, contract)
                executed_config = read_json(config_path)
            except (HREError, OSError, ValueError, KeyError, TypeError) as error:
                code = getattr(error, "code", "invalid_file_or_hash")
                return ["external_execution_contract_unverifiable:" + code]
            actual = outcome["selected_asset"]
            if executed_config != expected or contract.get("selected_asset_id") != actual["asset_id"] or contract.get("selected_asset_sha256") != actual["sha256"]:
                return ["external_execution_contract_differs_from_frozen_arm_or_selection"]
            try:
                record_root, external_state = _external_execution(root, outcome)
                return _protocol_violations(root, outcome, case, external_state, record_root)
            except (HREError, OSError, ValueError, KeyError, TypeError) as error:
                return ['unverified_external_prompt_execution:' + getattr(error, 'code', 'invalid_record')]
        return []
    reasons = []
    try:
        actual_templates = validate_execution_templates(selected_root)
        frozen_templates = {Path(path).stem: digest for path, digest in read_json(root / "run.json")["prompt_files"].items()}
        if actual_templates != frozen_templates:
            reasons.append("executed_prompt_templates_differ_from_frozen_run")
    except (HREError, OSError, ValueError, KeyError, TypeError):
        reasons.append("unverified_prompt_execution")
    executed = read_json(selected_root / "config.json")
    if executed != expected:
        reasons.append("executed_configuration_differs_from_frozen_arm")
    manifest = read_json(selected_root / "manifest.json")
    if any(manifest.get(key) != value for key, value in case.items()):
        reasons.append("executed_manifest_annotations_differ_from_frozen_case")
    if state["profile_id"] != outcome["arm_id"] or state["budget"]["max_generations"] != ARMS[outcome["arm_id"]] or state["budget"]["consumed"] > ARMS[outcome["arm_id"]]:
        reasons.append("executed_profile_or_budget_differs_from_frozen_arm")
    expected_inputs = {a["role"]: a["sha256"] for a in case["assets"]}
    if {a["role"]: a["sha256"] for a in state["inputs"]} != expected_inputs:
        reasons.append("executed_input_images_differ_from_frozen_case")
    for candidate in state["candidates"]:
        if candidate["geometry"]["policy"] != expected["geometry_policy"]:
            reasons.append("candidate_geometry_policy_differs_from_frozen_arm")
    return sorted(set(reasons))


def export_blind_evaluation(run_root: Path, destination: Path) -> Path:
    root, destination = Path(run_root), Path(destination)
    _require(not destination.resolve().is_relative_to((root / "private").resolve()) and not (root / "private").resolve().is_relative_to(destination.resolve()), "mapping must be outside reviewer package")
    _require(not destination.exists() or not any(destination.iterdir()), "review package destination is not empty")
    _require(not (root / "private/blind_mapping.json").exists(), "existing blind mapping is frozen; use a new run revision")
    run, manifest, outcomes = _load_run(root)
    cases = {c["case_id"]: c for c in manifest["cases"]}
    rng = random.Random(20261014)
    order = list(outcomes); rng.shuffle(order)
    items, mapping = [], []
    destination.mkdir(parents=True, exist_ok=True)
    for outcome in order:
        code = "item_" + format(rng.getrandbits(96), "024x")
        case = cases[outcome["case_id"]]
        input_root = safe_path(root, "frozen_inputs/" + outcome["case_id"], must_exist=True)
        inputs = {a["role"]: a for a in case["assets"]}
        for input_asset in inputs.values(): validate_asset(input_asset, input_root)
        selected, selected_root, status, state = _outcome_asset(root, outcome)
        violations = _protocol_violations(root, outcome, case, state, selected_root)
        if selected:
            validate_asset(selected, selected_root)
            _require(selected["role"] in {"prediction", "candidate"}, "delivered asset role must be candidate or exact frozen prediction")
            if selected["role"] == "prediction":
                _require(selected["sha256"] == inputs["prediction"]["sha256"] and selected["pixel_sha256"] == inputs["prediction"]["pixel_sha256"], "delivered prediction is not frozen A")
                if state is None:
                    _require(selected == inputs["prediction"], "imported prediction is not registered frozen A")
            if outcome["arm_id"] == "baseline":
                _require(selected["role"] == "prediction", "baseline must deliver frozen A")
            if selected["role"] == "candidate":
                binding = selected["candidate_binding"]
                input_binding = binding["prediction_sha256"] == inputs["prediction"]["sha256"] and binding["reference_sha256"] == inputs["reference"]["sha256"]
                if state is None: _require(input_binding, "selected candidate input binding mismatch")
                elif not input_binding: violations.append("selected_candidate_input_binding_differs_from_frozen_case")
                _require(selected["pixel_sha256"] != inputs["reference"]["pixel_sha256"] and selected["source_file"]["sha256"] not in {inputs["reference"]["sha256"], inputs["reference"]["source_file"]["sha256"]}, "reference B cannot be a generated candidate")
            dimensions_match = (selected["width"], selected["height"]) == (inputs["prediction"]["width"], inputs["prediction"]["height"])
            if state is None: _require(dimensions_match, "delivered asset pixel dimensions differ from prediction")
            elif not dimensions_match: violations.append("delivered_geometry_differs_from_frozen_prediction")
        observed_state, observed_root = state, selected_root
        if state is None and outcome.get('execution_contract'):
            try:
                observed_root, observed_state = _external_execution(root, outcome)
            except (HREError, OSError, ValueError, KeyError, TypeError):
                pass
        if violations: status = "protocol_violation"
        # Missing/failed deliveries are represented by A; their failure stays in private ITT data.
        delivered = selected or inputs["prediction"]
        delivered_root = selected_root if selected else input_root
        paths = {}
        for role, asset, source_root in [("A", inputs["prediction"], input_root), ("B", inputs["reference"], input_root), ("C", delivered, delivered_root)]:
            filename = "images/" + code + "_" + role + ".png"
            output = safe_path(destination, filename)
            output.parent.mkdir(parents=True, exist_ok=True)
            data = safe_path(source_root, asset["path"], must_exist=True).read_bytes()
            _require(sha256_bytes(data) == asset["sha256"], "actual exported asset bytes changed")
            atomic_write(output, data)
            paths[role] = filename
        panel_order = ["A", "B"]; rng.shuffle(panel_order)
        comparative = case.get("comparability", {})
        item = {"code": code, "images": paths, "anchor_panel_order": panel_order,
                "comparable_rendering_dimensions": comparative.get("comparable_rendering_dimensions", []),
                "reference_limitations": comparative.get("reference_limitations", []),
                "roi_pairs": [{k: r[k] for k in ["prediction_xywh", "reference_xywh", "comparable_dimensions"] if k in r} for r in comparative.get("ROI_pairs", [])]}
        items.append(item)
        mapping.append({"code": code, "case_id": outcome["case_id"], "case_revision": outcome["case_revision"], "scene_group_id": outcome["scene_group_id"],
                        "arm_id": outcome["arm_id"], "status": status, "protocol_violations": sorted(set(violations)), "selected_asset": selected,
                        "delivered_sha256": delivered["sha256"], "prediction_sha256": inputs["prediction"]["sha256"],
                        "workflow_success": observed_state.get("success", False) if observed_state else outcome.get("workflow_success", False),
                        "fallback": observed_state.get("selection", {}).get("fallback", False) if observed_state and observed_state.get("selection") else selected is None,
                        "costs": cost_summary(observed_state, _events(observed_root)) if observed_state else None})
    neutral = {"schema_version": "hre_blind_v1", "rubric_version": "independent_final_rubric_v1_20261013",
               "items": items, "limitations": ["A-equivalent candidates may reveal the baseline arm."],
               "rubric": {"style_anchor": "B comparable attributes; improvement relative to A", "content_anchor": "A",
                          "joint_success": "style improved AND content pass AND no critical defects"}}
    write_json(destination / "manifest.json", neutral)
    mapping_path = root / "private/blind_mapping.json"
    write_json(mapping_path, {"schema_version": "hre_blind_mapping_v1", "blind_manifest_sha256": file_sha256(destination / "manifest.json"),
                              "items": mapping, "planned_identities_sha256": sha256_bytes(canonical_json(run["planned_identities"]))})
    write_json(root / "evaluation_freeze.json", {"mapping_sha256": file_sha256(mapping_path),
                                                "planned_outcomes_sha256": file_sha256(root / "planned_outcomes.json")})
    return destination / "manifest.json"


def _wilson(values):
    n = len(values)
    if not n: return None
    z, p = 1.959963984540054, sum(values) / n
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return [center - spread, center + spread]


def summarize_evaluation(run_root: Path, ratings: Path) -> dict:
    root, ratings = Path(run_root), Path(ratings)
    run, manifest, outcomes = _load_run(root)
    freeze = read_json(root / "evaluation_freeze.json")
    _require(file_sha256(root / "private/blind_mapping.json") == freeze["mapping_sha256"], "blind mapping changed")
    _require(file_sha256(root / "planned_outcomes.json") == freeze["planned_outcomes_sha256"], "outcomes changed after blind lock")
    mapping = read_json(root / "private/blind_mapping.json")
    _require(mapping["planned_identities_sha256"] == sha256_bytes(canonical_json(run["planned_identities"])), "blind mapping plan changed")
    data = read_json(ratings)
    _require(data.get("frozen") is True, "ratings must be frozen before unblinding")
    ratings_digest = file_sha256(ratings)
    ratings_lock = root / "private/ratings_freeze.json"
    if ratings_lock.exists():
        _require(read_json(ratings_lock)["ratings_sha256"] == ratings_digest, "ratings changed after unblinding; use a new run revision")
    if "blind_manifest_sha256" in data:
        _require(data["blind_manifest_sha256"] == mapping["blind_manifest_sha256"], "ratings belong to another blind export")
    bycode = {m["code"]: m for m in mapping["items"]}
    identities = [{k: m[k] for k in ["case_id", "case_revision", "scene_group_id", "arm_id"]} for m in mapping["items"]]
    expected = [{k: o[k] for k in ["case_id", "case_revision", "scene_group_id", "arm_id"]} for o in outcomes]
    _require(len(bycode) == len(outcomes) and sorted(identities, key=canonical_json) == sorted(expected, key=canonical_json), "incomplete blind mapping/ITT coverage")
    raters = {r["rater_id"]: r for r in data.get("raters", [])}
    _require(len(raters) == len(data.get("raters", [])), "duplicate evaluator identity")
    labels = defaultdict(list)
    seen = set()
    for rating in data.get("ratings", []):
        code, rater = rating["code"], rating["rater_id"]
        _require(code in bycode and rater in raters and (code, rater) not in seen, "unknown/duplicate rating")
        seen.add((code, rater))
        record = bycode[code]
        _require(raters[rater].get("independent") is True and record["case_id"] not in raters[rater].get("participated_cases", []), "evaluator participated in prompt or selection")
        _require(rating.get("style_direction") in {"improved", "unchanged", "worse", "uncertain", "abstain", "error"} and rating.get("content_preservation") in {"pass", "fail", "uncertain", "abstain", "error"}, "invalid evaluation label")
        _require(isinstance(rating.get("critical_defects"), list), "critical defects list required")
        _require(rating.get("comparability") in {"usable", "partial", "unusable", "uncertain"}, "explicit comparability label required")
        labels[code].append(rating)
    adjudications = {a["code"]: a for a in data.get("adjudications", [])}
    _require(len(adjudications) == len(data.get("adjudications", [])), "duplicate adjudication")
    rows = []
    for code, record in bycode.items():
        available = labels[code]
        final, reason = None, "missing_ratings"
        if len(available) >= 2:
            signatures = {(r["comparability"], r["style_direction"], r["content_preservation"], bool(r["critical_defects"])) for r in available}
            if len(signatures) == 1:
                final, reason = available[0], "agreement"
            else:
                reason = "unresolved_disagreement"
                adjudication = adjudications.get(code)
                if adjudication:
                    rater = adjudication["rater_id"]
                    _require(rater in raters and raters[rater].get("independent") is True and record["case_id"] not in raters[rater].get("participated_cases", []) and rater not in {r["rater_id"] for r in available}, "adjudicator must be third independent evaluator")
                    _require(adjudication.get("style_direction") in {"improved", "unchanged", "worse", "uncertain"} and adjudication.get("content_preservation") in {"pass", "fail", "uncertain"} and isinstance(adjudication.get("critical_defects"), list), "invalid adjudication")
                    _require(adjudication.get("comparability") in {"usable", "partial", "unusable", "uncertain"}, "adjudication comparability required")
                    final, reason = adjudication, "third_rater_adjudication"
        valid = final is not None and final["comparability"] in {"usable", "partial"} and final["style_direction"] not in {"uncertain", "abstain", "error"} and final["content_preservation"] not in {"uncertain", "abstain", "error"}
        success = int(valid and record["status"] == "completed" and not record["protocol_violations"] and record["arm_id"] != "baseline" and record["delivered_sha256"] != record["prediction_sha256"] and final["style_direction"] == "improved" and final["content_preservation"] == "pass" and not final["critical_defects"])
        rows.append({**record, "joint_success": success, "rating_status": reason, "n_ratings": len(available), "n_valid": int(valid),
                     "style_direction": final["style_direction"] if final else None, "content_preservation": final["content_preservation"] if final else None,
                     "critical_defect": bool(final["critical_defects"]) if final else None})
    arms = {}
    grouped = {}
    for arm in sorted({o["arm_id"] for o in outcomes}):
        records = [r for r in rows if r["arm_id"] == arm]
        groups = defaultdict(list)
        for record in records: groups[record["scene_group_id"]].append(record["joint_success"])
        grouped[arm] = {g: float(np.mean(v)) for g, v in groups.items()}
        independent = all(len(v) == 1 for v in groups.values())
        costs = [r["costs"] for r in records]
        known_generations = [c["accounted_generations"] for c in costs if c is not None]
        known_bills = [c["observed_billed_cost"] for c in costs if c is not None and c["observed_billed_cost"] is not None]
        currencies = {c["currency"] for c in costs if c is not None and c["observed_billed_cost"] is not None}
        arms[arm] = {"n_pairs": len(records), "n_groups": len(groups), "n_raters": len({r["rater_id"] for item in records for r in labels[item["code"]]}),
                     "n_valid": sum(r["n_valid"] for r in records), "denominator": len(records),
                     "joint_success": sum(r["joint_success"] for r in records), "scene_equal_weight_rate": float(np.mean(list(grouped[arm].values()))),
                     "case_weight_rate": sum(r["joint_success"] for r in records) / len(records),
                     "missing_ratings": sum(r["rating_status"] == "missing_ratings" for r in records),
                     "failures": sum(r["status"] != "completed" for r in records), "fallbacks": sum(bool(r["fallback"]) for r in records),
                     "style_labels": dict(Counter(r["style_direction"] or "missing" for r in records)),
                     "content_labels": dict(Counter(r["content_preservation"] or "missing" for r in records)),
                     "critical_defects": sum(r["critical_defect"] is True for r in records),
                     "generation_cap": ARMS[arm],
                     "actual_generations": {"mean": float(np.mean(known_generations)) if known_generations else None,
                                            "median": float(np.median(known_generations)) if known_generations else None,
                                            "p90": float(np.quantile(known_generations, .9)) if known_generations else None,
                                            "n_observed": len(known_generations), "n_unknown": len(records) - len(known_generations)},
                     "observed_billed_cost_total": sum(known_bills) if len(known_bills) == len(records) and len(currencies) == 1 else None,
                     "observed_billed_cost_partial": sum(known_bills) if known_bills and len(currencies) == 1 else None,
                     "currency": next(iter(currencies)) if len(currencies) == 1 else None,
                     "cost_unknown_fraction": (len(records) - len(known_bills)) / len(records),
                     "wilson_interval": _wilson([r["joint_success"] for r in records]) if independent and all(r["n_valid"] for r in records) else None,
                     "wilson_unit": "one adjudicated pair per independent scene group" if independent and all(r["n_valid"] for r in records) else None}
    comparisons = {}
    for name, treatment, control in [("single_pass_agent_instruction_gain", "agent_single", "direct_ref"), ("adaptive_vs_fixed_prompt_sampling", "agent_adaptive", "direct_best_of_3")]:
        if treatment not in grouped or control not in grouped: continue
        groups = sorted(grouped[treatment])
        _require(set(groups) == set(grouped[control]), "paired comparison group coverage mismatch")
        differences = np.array([grouped[treatment][g] - grouped[control][g] for g in groups])
        generator = np.random.default_rng(BOOTSTRAP_SEED)
        estimates = differences[generator.integers(0, len(groups), size=(BOOTSTRAP_REPLICATES, len(groups)))].mean(axis=1)
        comparisons[name] = {"treatment": treatment, "control": control, "estimate": float(differences.mean()),
                             "ci95": np.quantile(estimates, [.025, .975]).tolist(), "n_groups": len(groups),
                             "bootstrap_seed": BOOTSTRAP_SEED, "bootstrap_replicates": BOOTSTRAP_REPLICATES,
                             "bootstrap_unit": "paired scene group, all arms and cases together", "wilson_interval": None}
    summary = {"schema_version": "hre_evaluation_v1", "formal": run["formal"], "ratings_sha256": file_sha256(ratings),
               "n_raters": len(raters), "n_pairs": len(manifest["cases"]), "n_groups": len({c["scene_group_id"] for c in manifest["cases"]}),
               "denominator": len(outcomes), "arms": arms, "comparisons": comparisons, "outcomes": rows,
               "limitations": run["limitations"] + (["Fewer than two independent raters for some outcomes; unconfirmed successes counted zero."] if any(r["n_ratings"] < 2 for r in rows) else []) + (["Fewer than 60 scene groups; intervals are descriptive and do not establish statistical power."] if len({c["scene_group_id"] for c in manifest["cases"]}) < 60 else [])}
    if not ratings_lock.exists():
        atomic_write(root / "private/frozen_ratings.json", ratings.read_bytes())
        write_json(ratings_lock, {"ratings_sha256": ratings_digest, "mapping_sha256": freeze["mapping_sha256"]})
    write_json(root / "analysis/summary.json", summary)
    return summary
