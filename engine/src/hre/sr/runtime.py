"""One owner for frozen SR state, durable submissions, receipts and selection."""
from __future__ import annotations

from copy import deepcopy
import io
import os
from pathlib import Path
import time

import numpy as np
from PIL import Image, ImageFilter

from ..models import HREError, file_sha256, now
from ..storage import atomic_write, case_lock, read_json, write_json
from ..v3.common import digest, require
from ..v3.contracts import _canonical_asset
from ..v3.runner_journal import Journal, immutable_json
from . import adapters, evidence
from .contracts import (PROTOCOL_VERSION, SLOTS, asset, geometry_and_rois, normalise_config,
                        normalise_spec, object_fields, opaque_image, opaque_pixel_sha256, protocol_identity, recipes, verify_asset)


def _code_identity() -> dict:
    return {name: file_sha256(Path(__file__).with_name(name)) for name in
            ("contracts.py", "runtime.py", "evidence.py", "adapters.py", "_official.py")}


def preflight(config: dict) -> dict:
    config = normalise_config(config)
    if config["mode"] == "fixture":
        return {"execution_kind": "fixture", "quality_claims": False, "status": "ready",
                "models": {key: {"status": "ready", "identity": {"fixture": True}, "blockers": []}
                           for key in ("reconstruction", "seesr", "qwen")}, "judge": {"status": "ready", "blockers": []}}
    models = adapters.inspect_deployments(config["models"])
    blockers = []
    if not config["judge"].get("base_url") or not config["judge"].get("model"):
        blockers.append("Set the explicit Judge endpoint and deployed model")
    key_env = config["judge"].get("api_key_env")
    if key_env and key_env not in os.environ:
        blockers.append("Judge credential environment variable is unset: " + key_env)
    return {"execution_kind": "real", "quality_claims": False,
            "status": "ready" if not blockers and all(d["status"] == "ready" for d in models.values()) else "blocked",
            "models": models, "judge": {"status": "blocked" if blockers else "ready", "blockers": blockers}}


def _initial(case: dict, freeze_sha256: str) -> dict:
    return {"schema_version": PROTOCOL_VERSION, "case_id": case["task"]["case_id"], "freeze_sha256": freeze_sha256,
            "execution_kind": case["config"]["mode"], "quality_claims": False, "status": "created", "candidates": {},
            "operations": {}, "artifacts": {}, "evidence": {}, "judgements": {}, "decision": None,
            "selected_slot": None, "selected_output": None, "created_at": case["created_at"]}


def create_case(root: Path, spec: dict, config: dict) -> dict:
    spec, config = normalise_spec(spec), normalise_config(config)
    root = Path(root).resolve()
    source_path = Path(spec["source"]["path"]).expanduser().resolve()
    require(source_path.is_file(), "sr_source_missing", "Original LR source is missing")
    require(not root.exists() or not any(root.iterdir()), "sr_case_exists", "Use a fresh SR directory; resume an existing case")
    origin_sha = file_sha256(source_path)
    with case_lock(root):
        try:
            source = _canonical_asset(source_path, root / "inputs", "source", spec["colour_policy"])
        except (OSError, ValueError) as exc:
            raise HREError("sr_source_decode", "Original source cannot be canonicalized") from exc
        opaque_image(Path(source["path"]))
        source.update(origin_path=str(source_path), origin_sha256=origin_sha,
                      pixel_sha256=opaque_pixel_sha256(Path(source["path"])), pixel_identity_method="sr_opaque_rgb_pixels_v1")
        require(file_sha256(source_path) == origin_sha, "sr_input_modified", "Original changed during case creation")
        geometry, rois = geometry_and_rois(spec, source)
        spec["source"] = {"path": source["path"]}
        spec["rois"] = [{"id": r["id"], "box": r["source_box"]} for r in rois]
        deployment = preflight(config)
        case = {"schema_version": PROTOCOL_VERSION, "task": spec, "config": config, "source": source,
                "geometry": geometry, "rois": rois, "recipes": recipes(spec["seed"]), "deployments": deployment["models"],
                "judge_preflight": deployment["judge"], "code": _code_identity(), "created_at": now()}
        case["protocol_identity"] = protocol_identity(case)
        case["protocol_sha256"] = digest(case["protocol_identity"])
        immutable_json(root / "case.json", case)
        freeze = {"schema_version": PROTOCOL_VERSION, "case_id": spec["case_id"], "case_sha256": file_sha256(root / "case.json")}
        immutable_json(root / "freeze.json", freeze)
        state = _initial(case, file_sha256(root / "freeze.json"))
        return Journal(root, state).state


def load_case(root: Path) -> tuple[dict, dict]:
    root = Path(root).resolve()
    require((root / "freeze.json").is_file(), "sr_case_missing", "Create an SR case first")
    freeze, case = read_json(root / "freeze.json"), read_json(root / "case.json")
    require(freeze.get("schema_version") == PROTOCOL_VERSION and case.get("schema_version") == PROTOCOL_VERSION
            and freeze.get("case_sha256") == file_sha256(root / "case.json"), "sr_case_modified", "Frozen SR contract changed")
    require(case["code"] == _code_identity(), "sr_code_modified", "SR runtime changed; retain this case for audit and create a new case")
    source = case["source"]
    for path_key, hash_key in (("path", "sha256"), ("original_path", "original_sha256"), ("origin_path", "origin_sha256")):
        path = Path(source[path_key])
        require(path.is_file() and file_sha256(path) == source[hash_key], "sr_input_modified", "Frozen original or canonical source changed")
    profile = case["task"]["evidence_profile"]
    if profile.get("selection_receipt"):
        verify_asset(profile["selection_receipt"], "sr_selection_modified")
    return case, _initial(case, file_sha256(root / "freeze.json"))


def _verify_artifacts(root: Path, state: dict) -> None:
    for relative, expected in state["artifacts"].items():
        path = root / relative
        require(path.is_file() and not path.is_symlink() and file_sha256(path) == expected,
                "sr_artifact_modified", "Frozen SR artifact is missing or changed: " + relative)
    if state.get("selected_output"):
        verify_asset(state["selected_output"])


def _track(state: dict, root: Path, paths) -> None:
    for path in paths:
        path = Path(path)
        require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root),
                "sr_artifact_path", "SR products must be real files within the case")
        state["artifacts"][path.relative_to(root).as_posix()] = file_sha256(path)


def _operation(root: Path, journal: Journal, key: str, request: dict, invoke, *, blockers=None) -> dict:
    directory = root / "operations" / key
    request_path, result_path, receipt_path = (directory / name for name in ("request.json", "result.json", "done.json"))
    existing = journal.state["operations"].get(key)
    if existing:
        require(existing["request_sha256"] == digest(request), "sr_request_changed", "A completed or pending operation cannot be reconfigured")
        if existing["status"] in {"complete", "failed", "blocked", "abandoned"}:
            return read_json(result_path) if existing["status"] != "abandoned" else {"status": "failed", "error": {"code": "sr_abandoned", "message": existing["note"]}}
        if receipt_path.exists() and existing["status"] == "submitted":
            receipt = read_json(receipt_path)
            require(receipt["request_sha256"] == existing["request_sha256"] and file_sha256(result_path) == receipt["result_sha256"],
                    "sr_receipt_modified", "Completion receipt is inconsistent")
            result = read_json(result_path)
            state = deepcopy(journal.state)
            state["operations"][key].update(status=receipt["status"], result_sha256=receipt["result_sha256"])
            _track(state, root, [p for p in directory.rglob("*") if p.is_file()])
            journal.commit(state, "operation_recovered", {"operation": key})
            if receipt["status"] != "unknown":
                return result
        raise HREError("sr_submission_unknown", f"{key} has an unknown submitted outcome; inspect its artifacts and use sr reconcile to abandon it. No automatic resubmission")
    require(not (directory / "submitted.json").exists(), "sr_submission_unknown", "An unprojected submission marker exists; operator reconciliation is required")
    immutable_json(request_path, request)
    state = deepcopy(journal.state)
    operation = {"status": "blocked" if blockers else "submitted", "request_sha256": digest(request),
                 "request_path": str(request_path), "submitted": not bool(blockers), "started_at": now()}
    if blockers:
        result = {"status": "blocked", "blockers": list(blockers), "observation": {"calls_attempted": 0, "usd": None}}
    else:
        immutable_json(directory / "submitted.json", {"operation": key, "request_sha256": digest(request), "at": operation["started_at"]})
    state["operations"][key] = operation
    state["status"] = "running"
    _track(state, root, [request_path] + ([] if blockers else [directory / "submitted.json"]))
    journal.commit(state, "operation_blocked" if blockers else "operation_submitted", {"operation": key})
    started = time.monotonic()
    if not blockers:
        try:
            result = invoke(directory)
            status = "complete"
        except HREError as exc:
            status = "unknown" if exc.code in {"chat_transport_unknown", "sr_native_timeout_unknown"} else "failed"
            result = {"status": status, "error": {"code": exc.code, "message": str(exc)},
                      "observation": getattr(exc, "observation", {})}
        except Exception as exc:
            status = "unknown"
            result = {"status": "unknown", "error": {"code": "sr_unexpected_outcome", "message": str(exc)}, "observation": {}}
    else:
        status = "blocked"
    result.setdefault("observation", {})
    result["observation"].setdefault("elapsed_seconds", time.monotonic() - started)
    result["observation"].setdefault("usd", None)
    immutable_json(result_path, result)
    receipt = {"operation": key, "request_sha256": digest(request), "result_sha256": file_sha256(result_path), "status": status}
    immutable_json(receipt_path, receipt)
    state = deepcopy(journal.state)
    state["operations"][key].update(status=status, result_sha256=receipt["result_sha256"])
    _track(state, root, [p for p in directory.rglob("*") if p.is_file()])
    journal.commit(state, "operation_finished", {"operation": key, "status": status})
    if status == "unknown":
        raise HREError("sr_submission_unknown", f"{key} outcome is unknown; reconcile explicitly. No automatic resubmission")
    return result


def _prepare(root: Path, case: dict, recipe: dict) -> dict:
    source = opaque_image(Path(case["source"]["path"]))
    if recipe["slot"] == "C1":
        source = source.filter(ImageFilter.GaussianBlur(recipe["preprocess"]["radius"]))
    geometry = case["geometry"][recipe["slot"]]
    width, height = geometry["padded_lr"]
    pixels = np.pad(np.asarray(source), ((0, height - source.height), (0, width - source.width), (0, 0)), mode="edge")
    data = io.BytesIO()
    Image.fromarray(pixels).save(data, format="PNG")
    path = root / "prepared" / recipe["slot"] / "input.png"
    if path.exists():
        require(path.read_bytes() == data.getvalue(), "sr_prepared_modified", "Frozen prepared LR changed")
    else:
        atomic_write(path, data.getvalue())
    return {**asset(path), "source_sha256": case["source"]["sha256"], "preprocess": recipe["preprocess"]}


def _fixture_candidate(request: dict, config: dict, output_dir: Path) -> dict:
    behavior = config["fixture"]["candidates"][request["slot"]]
    if behavior == "crash":
        raise KeyboardInterrupt("Fixture crash after durable model submission")
    if behavior == "fail":
        raise HREError("sr_fixture_failed", "Explicit synthetic model failure")
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "native.png"
    image = opaque_image(Path(request["input"]["path"]))
    size = request["geometry"]["native_hr"]
    if behavior == "wrong_size":
        size = [size[0] - 1, size[1]]
    image = image.resize(size, Image.Resampling.NEAREST)
    if behavior == "transparent":
        image = image.convert("RGBA")
        image.putalpha(128)
    if behavior == "corrupt":
        path.write_bytes(b"explicit corrupt SR fixture")
    else:
        image.save(path)
    return {"outputs": [{"path": str(path), "sha256": file_sha256(path), "width": image.width, "height": image.height, "mode": image.mode}],
            "observation": {"fixture": True, "fixture_calls": 1, "calls_attempted": 0, "calls_completed": 0,
                            "source_sha256": request["source"]["sha256"], "quality_claims": False, "usd": None}}


def _deliver(request: dict, native: dict, directory: Path) -> dict:
    result = {"status": "contract_fail", "native": native.get("outputs", []), "observation": native.get("observation", {}),
              "hard": {"pass": False, "version": "sr_native_and_crop_contract_v1"}}
    try:
        require(isinstance(native.get("outputs"), list) and len(native["outputs"]) == 1, "sr_output_count", "Exactly one native product is required")
        item = native["outputs"][0]
        verify_asset(item)
        image = opaque_image(Path(item["path"]))
        require(list(image.size) == request["geometry"]["native_hr"], "sr_native_geometry",
                "Native output size differs from the frozen x4 padded canvas; resizing is forbidden")
        require(not native.get("observation", {}).get("native_contract_error"), "sr_native_contract", "Native model contract failed before upstream postprocessing")
        crop = request["geometry"]["crop"]
        delivered = image.crop(crop)
        require(list(delivered.size) == request["geometry"]["target_hr"], "sr_crop_geometry", "Inverse crop did not restore exact scaled content")
        output_path = directory / "delivered.png"
        delivered.save(output_path)
        result.update(status="valid", output=asset(output_path), hard={"pass": True, "version": "sr_native_and_crop_contract_v1",
                      "native_sha256": item["sha256"], "input_sha256": request["input"]["sha256"],
                      "source_sha256": request["source"]["sha256"], "geometry_sha256": digest(request["geometry"]),
                      "native_size": list(image.size), "crop": crop, "delivered_size": list(delivered.size),
                      "alpha": "opaque", "output_resize": False, "quality_claim": False})
    except (HREError, OSError, ValueError, KeyError, TypeError) as exc:
        result["hard"]["error"] = {"code": getattr(exc, "code", "sr_native_invalid"), "message": str(exc)}
    return result


def _candidate(root: Path, case: dict, recipe: dict, journal: Journal, deployments: dict) -> dict:
    slot, model_key = recipe["slot"], recipe["model_key"]
    prepared = _prepare(root, case, recipe)
    deployment = case["deployments"][model_key]
    request = {"schema_version": "hre_sr_model_request_v02", "slot": slot, "model_key": model_key,
               "source": case["source"], "input": prepared, "geometry": case["geometry"][slot], "seed": recipe["seed"],
               "preprocess": recipe["preprocess"], "deployment": deployment["identity"],
               "model_settings_sha256": digest(case["config"].get("models", {}).get(model_key, {"fixture": True}))}
    blockers = deployment["blockers"] if deployment["status"] != "ready" else []
    if case["config"]["mode"] == "fixture" and case["config"]["fixture"]["candidates"][slot] == "blocked":
        blockers = ["Explicit synthetic missing deployment"]
    state = deepcopy(journal.state)
    _track(state, root, [Path(prepared["path"])])
    if state != journal.state:
        journal.commit(state, "input_prepared", {"slot": slot})
    def invoke(directory):
        native = (_fixture_candidate(request, case["config"], directory / "native") if case["config"]["mode"] == "fixture"
                  else adapters.run_candidate(request, case["config"], directory / "native", verified_deployments=deployments))
        return _deliver(request, native, directory)
    result = _operation(root, journal, "model_" + slot, request, invoke, blockers=blockers)
    return {**result, "request": str(root / "operations" / ("model_" + slot) / "request.json"), "slot": slot}


def run_case(root: Path) -> dict:
    root = Path(root).resolve()
    case, initial = load_case(root)
    with case_lock(root):
        case, initial = load_case(root)
        journal = Journal(root, initial)
        _verify_artifacts(root, journal.state)
        if journal.state["status"] in {"selected", "unresolved"}:
            return journal.state
        deployments = case["deployments"]
        if case["config"]["mode"] == "real":
            deployments = adapters.inspect_deployments(case["config"]["models"])
            require(deployments == case["deployments"], "sr_deployment_modified", "Deployment identity/readiness changed since freeze; create a new case")
        for recipe in case["recipes"]:
            slot = recipe["slot"]
            if slot in journal.state["candidates"]:
                continue
            candidate = _candidate(root, case, recipe, journal, deployments)
            state = deepcopy(journal.state)
            state["candidates"][slot] = candidate
            journal.commit(state, "candidate_recorded", {"slot": slot, "status": candidate["status"]})
        state = deepcopy(journal.state)
        records = {}
        for slot in SLOTS:
            path = root / "evidence" / (slot + ".json")
            if path.relative_to(root).as_posix() in state["artifacts"]:
                records[slot] = read_json(path)
            else:
                records[slot] = evidence.measure(case, state["candidates"], slot)
                immutable_json(path, records[slot])
            state["evidence"][slot] = {"path": str(path), "sha256": file_sha256(path),
                                       "status": evidence.evidence_status(records[slot], case, state["candidates"], slot)}
            _track(state, root, [path])
        bundle_path = root / "judge" / "bundle.json"
        bundle = (read_json(bundle_path) if bundle_path.relative_to(root).as_posix() in state["artifacts"]
                  else evidence.build_bundle(root, case, state["candidates"]))
        if bundle:
            _track(state, root, [p for p in (root / "judge").rglob("*") if p.is_file()])
        journal.commit(state, "evidence_prepared", {"available": bundle is not None})
        if bundle:
            requests = evidence.make_requests(case, journal.state["candidates"], records, bundle)
            for arm in ("visual", "evidence"):
                blockers = case["judge_preflight"]["blockers"]
                result = _operation(root, journal, "judge_" + arm, requests[arm],
                                    lambda _, req=requests[arm]: evidence.invoke_judge(case, req, bundle), blockers=blockers)
                state = deepcopy(journal.state)
                state["judgements"][arm] = result
                journal.commit(state, "judgement_recorded", {"arm": arm, "status": result["status"]})
        else:
            state = deepcopy(journal.state)
            state["judgements"] = {arm: {"status": "unavailable", "reason": "No contract-valid common Y0"} for arm in ("visual", "evidence")}
            journal.commit(state, "judgement_unavailable", {})
        load_case(root)
        _verify_artifacts(root, journal.state)
        decision = evidence.select(case, journal.state["candidates"], records, bundle, journal.state["judgements"]["evidence"])
        immutable_json(root / "decision.json", decision)
        state = deepcopy(journal.state)
        state.update(status=decision["status"], selected_slot=decision["selected_slot"], selected_output=decision["selected_output"], decision=decision)
        _track(state, root, [root / "decision.json"])
        return journal.commit(state, "case_finished", {"selected_slot": decision["selected_slot"]})


def reconcile_unknown(root: Path, operation_id: str, note: str) -> dict:
    require(isinstance(note, str) and note.strip(), "sr_reconciliation_note", "Record why this unknown result is being abandoned")
    root = Path(root).resolve()
    case, initial = load_case(root)
    with case_lock(root):
        journal = Journal(root, initial)
        _verify_artifacts(root, journal.state)
        operation = journal.state["operations"].get(operation_id)
        if operation is None:
            require(operation_id in {"model_" + s for s in SLOTS} | {"judge_visual", "judge_evidence"},
                    "sr_reconciliation_invalid", "Unknown operation slot")
            directory = root / "operations" / operation_id
            require((directory / "submitted.json").is_file() and (directory / "request.json").is_file(),
                    "sr_reconciliation_invalid", "No durable submission exists for this slot")
            submitted, request = read_json(directory / "submitted.json"), read_json(directory / "request.json")
            require(submitted.get("operation") == operation_id and submitted.get("request_sha256") == digest(request),
                    "sr_reconciliation_invalid", "Orphan submission does not match its archived request")
            operation = {"status": "submitted", "request_sha256": digest(request), "request_path": str(directory / "request.json"),
                         "submitted": True, "started_at": submitted["at"]}
        require(operation and operation["status"] in {"submitted", "unknown"}, "sr_reconciliation_invalid", "Only a submitted/unknown operation can be abandoned")
        state = deepcopy(journal.state)
        state["operations"][operation_id] = {**operation, "status": "abandoned", "note": note, "reconciled_at": now()}
        immutable_json(root / "operations" / operation_id / "abandoned.json", state["operations"][operation_id])
        _track(state, root, [p for p in (root / "operations" / operation_id).rglob("*") if p.is_file()])
        return journal.commit(state, "unknown_abandoned", {"operation": operation_id})


def report(root: Path, oracle: dict | None = None) -> dict:
    root = Path(root).resolve()
    case, initial = load_case(root)
    with case_lock(root):
        state = Journal(root, initial, read_only=True).state
        _verify_artifacts(root, state)
        produced = sum(bool(c.get("native")) for c in state["candidates"].values())
        valid = sum(c["status"] == "valid" for c in state["candidates"].values())
        accepted = len((state.get("decision") or {}).get("accepted_slots", []))
        operation_observations = {key: read_json(Path(op["request_path"]).with_name("result.json")).get("observation", {})
                                  for key, op in state["operations"].items() if Path(op["request_path"]).with_name("result.json").is_file()}
        observations = list(operation_observations.values())
        token_usage = [o.get("usage") for o in observations if o.get("usage") is not None]
        call_counts = {}
        for kind in ("model", "judge"):
            attempted, completed, unconfirmed = 0, 0, []
            for key, operation in state["operations"].items():
                if key.startswith(kind + "_") and operation["submitted"]:
                    observed = operation_observations.get(key, {})
                    calls = observed.get("calls_attempted", observed.get("image_calls_attempted"))
                    if type(calls) is int:
                        attempted += calls
                    else:
                        unconfirmed.append(key)
                    completed += observed.get("calls_completed", observed.get("image_calls_completed", 0))
            real = case["config"]["mode"] == "real"
            call_counts.update({"real_" + kind + "_calls": (None if unconfirmed else attempted) if real else 0,
                                kind + "_calls_attempted_observed": attempted if real else 0,
                                kind + "_calls_completed_observed": completed if real else 0,
                                kind + "_submissions_unconfirmed": unconfirmed if real else []})
        accounting = {"candidate_slots": 4, "produced_count": produced, "valid_count": valid, "accepted_count": accepted,
                      "production_coverage": produced / 4, "valid_coverage": valid / 4, "accepted_coverage": accepted / 4,
                      "pool_oracle_quality_coverage": None, "offline_oracle": None, "selection_failure": None,
                      "fallback": state.get("selected_slot") == "C0", "unresolved": state["status"] == "unresolved",
                      "candidate_failures": {s: c["status"] for s, c in state["candidates"].items() if c["status"] != "valid"},
                      "submitted_operations": sum(o["submitted"] for o in state["operations"].values()),
                      **call_counts,
                      "elapsed_seconds_observed": sum(o.get("elapsed_seconds", 0) for o in observations),
                      "token_usage_observed": token_usage or None, "token_usage_complete": len(token_usage) == 2,
                      "usd": None, "usd_status": "unknown", "quality_claims": False}
        if oracle is not None:
            accounting.update(_offline_oracle(case, state, oracle))
        return {**state, "protocol_sha256": case["protocol_sha256"], "source_identity": {
                    key: case["source"][key] for key in ("sha256", "pixel_sha256", "original_sha256")}, "accounting": accounting}


def _offline_oracle(case: dict, state: dict, oracle: dict) -> dict:
    object_fields(oracle, {"schema_version", "case_id", "source_sha256", "source_pixel_sha256", "method_version", "candidates", "best_slot"}, "offline oracle")
    require(oracle.get("schema_version") == "hre_sr_oracle_v02" and oracle.get("case_id") == case["task"]["case_id"]
            and oracle.get("source_sha256") == case["source"]["sha256"]
            and oracle.get("source_pixel_sha256") == case["source"]["pixel_sha256"], "sr_oracle_binding", "Offline labels must bind this original source and case")
    require(isinstance(oracle.get("method_version"), str) and oracle["method_version"].strip(), "sr_oracle_invalid", "Name the offline labeling method/version")
    labels = object_fields(oracle.get("candidates"), set(SLOTS), "offline candidate labels")
    valid = {s for s, c in state["candidates"].items() if c["status"] == "valid"}
    require(set(labels) == valid, "sr_oracle_incomplete", "Label every contract-valid candidate; failed products cannot qualify")
    for slot, label in labels.items():
        object_fields(label, {"sha256", "content_preserved", "improved_over_y0"}, "offline candidate label")
        require(label.get("sha256") == state["candidates"][slot]["output"]["sha256"]
                and type(label.get("content_preserved")) is bool and type(label.get("improved_over_y0")) is bool,
                "sr_oracle_binding", "Candidate labels require the exact output hash and explicit booleans")
        require(slot != "C0" or label["improved_over_y0"] is False, "sr_oracle_invalid", "Common Y0 cannot improve over itself")
    improved = [s for s, label in labels.items() if s != "C0" and label["content_preserved"] and label["improved_over_y0"]]
    baseline = labels.get("C0", {}).get("content_preserved", False)
    eligible = improved if improved else (["C0"] if baseline else [])
    best = oracle.get("best_slot")
    require(best in eligible if eligible else best is None, "sr_oracle_invalid", "Offline best_slot must match the labeled eligible pool")
    selected = state["selected_slot"]
    return {"pool_oracle_quality_coverage": bool(improved), "selection_failure": selected not in eligible if eligible else selected is not None,
            "offline_oracle": {"labels_sha256": digest(oracle), "method_version": oracle["method_version"], "best_slot": best,
                               "eligible_improved_slots": improved, "baseline_content_preserved": baseline,
                               "selected_matches_best": selected == best, "selected_slot": selected,
                               "avoidable_fallback": selected == "C0" and bool(improved),
                               "avoidable_unresolved": selected is None and bool(eligible), "online_use": False}}
