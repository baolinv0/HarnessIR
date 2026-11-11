"""Candidate-bound proxies and one anonymous attachment bundle for paired Judges."""
from __future__ import annotations

import base64
from copy import deepcopy
import json
import io
from pathlib import Path
import random

import numpy as np
from PIL import Image
from jsonschema import Draft202012Validator

from ..models import HREError, canonical_json, file_sha256, sha256_bytes
from ..storage import read_json
from ..v3.common import chat, digest, image_message, require
from ..v3.runner_journal import immutable_json
from .contracts import LAYOUT_VERSION, METHODS, finite, opaque_image, verify_asset

METHOD_VERSION = "sr_soft_proxies_v1"
LIMITATIONS = "Measured proxies, not verified high-frequency fidelity. Sharpness may reflect invented detail; assess source content explicitly."
SYSTEM = (
    "Evaluate super-resolution using the original low-resolution source S and common high-resolution baseline B. "
    "Assess baseline content preservation separately. For each anonymous candidate, assess identity, text, objects, "
    "geometry and color preservation against S, then perceptual improvement against the SAME B. "
    "A candidate needs content=pass AND improvement=improved to be eligible. Proxies are limited measurements, "
    "not ground truth or permission to hallucinate details. Use uncertain when content cannot be established. "
    "Return only the required JSON. Ranking must contain every candidate exactly once. best_candidate is the "
    "first eligible candidate in ranking, or null when none qualifies. Never infer baseline content from geometry."
)


def method_identity(methods: list[str]) -> dict:
    return {"version": METHOD_VERSION, "implementation_sha256": file_sha256(Path(__file__)), "methods": list(methods)}


def binding(case: dict, candidates: dict, slot: str) -> dict:
    return {"source_sha256": case["source"]["sha256"], "source_pixel_sha256": case["source"]["pixel_sha256"],
            "baseline_sha256": candidates.get("C0", {}).get("output", {}).get("sha256"),
            "candidate_sha256": candidates.get(slot, {}).get("output", {}).get("sha256"),
            "roi_sha256": digest(case["rois"]), "geometry_sha256": digest(case["geometry"][slot]),
            "method_sha256": digest(method_identity(case["task"]["evidence_profile"]["methods"]))}


def evidence_status(record: dict, case: dict, candidates: dict, slot: str) -> str:
    if record.get("binding") != binding(case, candidates, slot):
        return "stale"
    if record.get("status") != "measured":
        return record.get("status") if record.get("status") in {"missing", "failed", "stale"} else "failed"
    expected = case["task"]["evidence_profile"]["methods"]
    if record.get("method") != method_identity(expected) or set(record.get("measurements", {})) != set(expected):
        return "stale"
    try:
        finite(record["measurements"])
        for method in expected:
            measurement = record["measurements"][method]
            if measurement.get("status") != "measured" or measurement.get("version") != method:
                return "failed"
            regions = measurement["regions"]
            if len(regions) != 1 + len(case["rois"]):
                return "failed"
            for index, region in enumerate(regions):
                if region.get("region") != ("full" if index == 0 else f"R{index:02d}"):
                    return "stale"
                for key in ("candidate", "baseline", "source"):
                    if type(region.get(key)) not in {int, float}:
                        return "failed"
    except (HREError, KeyError, TypeError):
        return "failed"
    return "measured"


def _metrics(image: Image.Image, source: Image.Image) -> dict:
    rgb = np.asarray(image, dtype=np.float64) / 255
    lr = np.asarray(image.resize(source.size, Image.Resampling.BICUBIC), dtype=np.float64) / 255
    src = np.asarray(source, dtype=np.float64) / 255
    gray = rgb @ np.array([0.2126, 0.7152, 0.0722])
    dx = np.mean(np.abs(np.diff(gray, axis=1))) if gray.shape[1] > 1 else 0.0
    dy = np.mean(np.abs(np.diff(gray, axis=0))) if gray.shape[0] > 1 else 0.0
    return {"lr_consistency_v1": float(np.mean(np.abs(lr - src))),
            "clipping_v1": float(np.mean((rgb <= 1 / 255) | (rgb >= 254 / 255))),
            "edge_energy_v1": float((dx + dy) / 2)}


def measure(case: dict, candidates: dict, slot: str) -> dict:
    methods = case["task"]["evidence_profile"]["methods"]
    record = {"schema_version": "hre_sr_evidence_v02", "status": "missing", "binding": binding(case, candidates, slot),
              "method": method_identity(methods), "profile_selection": case["task"]["evidence_profile"]["selection"],
              "limitations": LIMITATIONS, "measurements": {}}
    if any(candidates.get(s, {}).get("status") != "valid" for s in ("C0", slot)):
        record["reason"] = "A contract-valid candidate and common baseline are required"
        return record
    try:
        for record_asset in (case["source"], candidates["C0"]["output"], candidates[slot]["output"]):
            verify_asset(record_asset)
        source = opaque_image(Path(case["source"]["path"]))
        baseline = opaque_image(Path(candidates["C0"]["output"]["path"]))
        candidate = opaque_image(Path(candidates[slot]["output"]["path"]))
        for method in methods:
            record["measurements"][method] = {"version": method, "status": "measured", "regions": []}
        regions = [("full", source, baseline, candidate)]
        regions += [(f"R{i:02d}", source.crop(r["source_box"]), baseline.crop(r["hr_box"]), candidate.crop(r["hr_box"]))
                    for i, r in enumerate(case["rois"], 1)]
        for rid, src, base, cand in regions:
            measured = [_metrics(img, src) for img in (src, base, cand)]
            for method in methods:
                record["measurements"][method]["regions"].append({"region": rid, "source": measured[0][method],
                                                                  "baseline": measured[1][method], "candidate": measured[2][method]})
        record["status"] = "measured"
    except (HREError, OSError, ValueError) as exc:
        record.update(status="failed", reason=str(exc), measurements={})
    return record


def build_bundle(root: Path, case: dict, candidates: dict) -> dict | None:
    if candidates.get("C0", {}).get("status") != "valid":
        return None
    directory = root / "judge"
    directory.mkdir(exist_ok=True)
    available = [slot for slot in ("C1", "C2", "C3") if candidates.get(slot, {}).get("status") == "valid"]
    rng = random.Random(int(case["source"]["sha256"][:16], 16) ^ case["task"]["seed"])
    rng.shuffle(available)
    aliases = {f"A{i:02d}": slot for i, slot in enumerate(available, 1)}
    immutable_json(directory / "alias_map.local.json", {"aliases": aliases, "baseline": "C0"})
    entries = [("S", case["source"]), ("B", candidates["C0"]["output"])]
    entries += [(alias, candidates[slot]["output"]) for alias, slot in aliases.items()]
    attachments, images = [], []
    for roi_index in range(1 + len(case["rois"])):
        rid = "full" if roi_index == 0 else f"R{roi_index:02d}"
        for identity, item in entries:
            verify_asset(item)
            path = Path(item["path"])
            box = [0, 0, item["width"], item["height"]]
            if roi_index:
                region = case["rois"][roi_index - 1]
                box = region["source_box"] if identity == "S" else region["hr_box"]
                crop_path = directory / "crops" / f"{identity}_{rid}.png"
                crop_path.parent.mkdir(exist_ok=True)
                data = io.BytesIO()
                opaque_image(path).crop(box).save(data, format="PNG")
                if crop_path.exists():
                    require(crop_path.read_bytes() == data.getvalue(), "sr_artifact_modified", "Uncommitted Judge crop differs from its frozen source")
                else:
                    from ..storage import atomic_write
                    atomic_write(crop_path, data.getvalue())
                path = crop_path
            message = image_message(path)
            transport_bytes = base64.b64decode(message["image_url"]["url"].split(",", 1)[1], validate=True)
            attachments.append({"image_id": identity, "region": rid, "image_sha256": item["sha256"],
                                "crop_box": box, "width": box[2] - box[0], "height": box[3] - box[1],
                                "transport_png_sha256": sha256_bytes(transport_bytes), "transport_bytes": len(transport_bytes)})
            images.append(message)
    public = {"schema_version": "hre_sr_judge_input_v02", "layout_version": LAYOUT_VERSION,
              "source": {"id": "S", "sha256": case["source"]["sha256"], "pixel_sha256": case["source"]["pixel_sha256"],
                         "width": case["source"]["width"], "height": case["source"]["height"]},
              "baseline": {"id": "B", "sha256": candidates["C0"]["output"]["sha256"], "hard_contract": "pass"},
              "candidates": [{"id": alias, "sha256": candidates[slot]["output"]["sha256"], "hard_contract": "pass",
                              "geometry_sha256": digest(case["geometry"][slot])} for alias, slot in aliases.items()],
              "rois": [{"id": f"R{i:02d}", "source_box": r["source_box"], "hr_box": r["hr_box"]} for i, r in enumerate(case["rois"], 1)],
              "roi_sha256": digest(case["rois"]), "scale": 4, "methods": method_identity(case["task"]["evidence_profile"]["methods"]),
              "attachments": attachments, "evidence_text": None}
    bundle = {"public": public, "images": images, "aliases": aliases,
              "attachments_sha256": digest({"attachments": attachments, "images": images})}
    immutable_json(directory / "bundle.json", bundle)
    return bundle


def response_schema(aliases: list[str]) -> dict:
    enum = aliases or ["__no_candidates__"]
    return {"type": "object", "additionalProperties": False,
            "required": ["baseline_content", "candidates", "ranking", "best_candidate", "reason"],
            "properties": {"baseline_content": {"enum": ["pass", "fail", "uncertain"]},
                "candidates": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                    "required": ["id", "content", "improvement", "confidence"], "properties": {
                        "id": {"enum": enum}, "content": {"enum": ["pass", "fail", "uncertain"]},
                        "improvement": {"enum": ["improved", "no_improvement", "uncertain"]},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1}}}},
                "ranking": {"type": "array", "items": {"enum": enum}, "uniqueItems": True},
                "best_candidate": {"anyOf": [{"enum": enum}, {"type": "null"}]},
                "reason": {"type": "string", "minLength": 1, "maxLength": 4000}}}


def _project_evidence(case: dict, candidates: dict, records: dict, aliases: dict) -> str:
    projected = []
    for alias, slot in [("B", "C0"), *aliases.items()]:
        record = records.get(slot, {})
        status = evidence_status(record, case, candidates, slot)
        item = {"image_id": alias, "status": status, "binding": binding(case, candidates, slot),
                "method": method_identity(case["task"]["evidence_profile"]["methods"]), "measurements": {}}
        if status == "measured":
            for method in case["task"]["evidence_profile"]["methods"]:
                result = record["measurements"][method]
                item["measurements"][method] = {"status": "measured", "version": method,
                    "regions": [{key: r[key] for key in ("region", "candidate", "baseline", "source")} for r in result["regions"]]}
        projected.append(item)
    return canonical_json({"profile_selection": case["task"]["evidence_profile"]["selection"],
                           "limitations": LIMITATIONS, "measurements": projected}).decode()


def make_requests(case: dict, candidates: dict, records: dict, bundle: dict) -> dict:
    schema = response_schema(list(bundle["aliases"]))
    requests = {}
    config = case["config"]["judge"]
    for arm in ("visual", "evidence"):
        public = deepcopy(bundle["public"])
        if arm == "evidence":
            public["evidence_text"] = _project_evidence(case, candidates, records, bundle["aliases"])
        messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": [
            {"type": "text", "text": canonical_json(public).decode()}, *deepcopy(bundle["images"])]}]
        body = {"model": config.get("model", "fixture-judge"), "messages": messages, **config["settings"], "stream": False}
        mode = config["response_format"]
        if mode == "json_object":
            body["response_format"] = {"type": "json_object"}
        elif mode == "json_schema":
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "hre_response", "strict": True, "schema": schema}}
        requests[arm] = {"schema_version": "hre_sr_judge_request_v02", "arm": arm, "body": body,
                         "body_sha256": digest(body), "response_schema": schema, "endpoint": config.get("base_url"),
                         "attachments_sha256": bundle["attachments_sha256"]}
    return requests


def _strict_json(text: str) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "sr_judge_invalid", "Duplicate response keys")
            result[key] = value
        return result
    def constant(_):
        raise HREError("sr_judge_invalid", "Nonfinite Judge confidence or value")
    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, TypeError) as exc:
        raise HREError("sr_judge_invalid", "Judge did not return one complete JSON object") from exc


def validate_judgement(value: dict, aliases: list[str]) -> dict:
    finite(value)
    errors = list(Draft202012Validator(response_schema(aliases)).iter_errors(value))
    require(not errors, "sr_judge_invalid", "Judge response violates the frozen schema")
    ids = [c["id"] for c in value["candidates"]]
    require(len(ids) == len(set(ids)) and set(ids) == set(aliases) and set(value["ranking"]) == set(aliases),
            "sr_judge_invalid", "Judge must assess and rank every known anonymous candidate exactly once")
    eligible = {c["id"] for c in value["candidates"] if c["content"] == "pass" and c["improvement"] == "improved"}
    first = next((cid for cid in value["ranking"] if cid in eligible), None)
    require(value["best_candidate"] == first, "sr_judge_invalid", "best_candidate is inconsistent with content, improvement or ranking")
    return value


def invoke_judge(case: dict, request: dict, bundle: dict) -> dict:
    if case["config"]["mode"] == "fixture":
        settings = case["config"]["fixture"]["judge"]
        behavior = settings["behavior"]
        if behavior == "crash":
            raise KeyboardInterrupt("Fixture crash after durable Judge submission")
        if behavior == "unavailable":
            raise HREError("sr_fixture_judge_unavailable", "Explicit fixture Judge failure")
        outcomes = [{"id": alias, "content": settings["content"][slot],
                     "improvement": "improved" if slot in settings["improved"] else "no_improvement", "confidence": 0.8}
                    for alias, slot in bundle["aliases"].items()]
        reverse = {slot: alias for alias, slot in bundle["aliases"].items()}
        ranking = [reverse[s] for s in settings["ranking"] if s in reverse]
        ranking += [a for a in bundle["aliases"] if a not in ranking]
        eligible = {c["id"] for c in outcomes if c["content"] == "pass" and c["improvement"] == "improved"}
        value = {"baseline_content": settings["content"]["C0"], "candidates": outcomes, "ranking": ranking,
                 "best_candidate": next((a for a in ranking if a in eligible), None), "reason": "Explicit synthetic fixture, no quality finding"}
        observation = {"text": "invalid" if behavior == "invalid" else canonical_json(value).decode(),
                       "finish_reason": "length" if behavior == "truncated" else "stop", "usage": None,
                       "request_sha256": request["body_sha256"], "calls_attempted": 0, "calls_completed": 0,
                       "fixture_calls": 1, "elapsed_seconds": 0.0, "usd": None, "fixture": True}
    else:
        try:
            observation = chat(case["config"]["judge"], request["body"]["messages"], request["response_schema"])
        except HREError as exc:
            exc.observation = {"request_sha256": request["body_sha256"], "endpoint": request["endpoint"],
                               "calls_attempted": int(exc.code in {"chat_http_error", "chat_transport_unknown", "chat_output_invalid"}),
                               "calls_completed": int(exc.code == "chat_output_invalid"), "usage": None, "usd": None,
                               "error_code": exc.code}
            raise
    try:
        require(observation.get("request_sha256") == request["body_sha256"], "sr_judge_request_mismatch",
                "Actual chat request differed from the archived frozen request")
        require(observation.get("finish_reason") == "stop", "sr_judge_incomplete", "Truncated or incomplete Judge response is unavailable")
        value = validate_judgement(_strict_json(observation["text"]), list(bundle["aliases"]))
        return {"status": "available", "assessment": value, "observation": observation,
                "request_sha256": request["body_sha256"], "attachments_sha256": bundle["attachments_sha256"]}
    except HREError as exc:
        return {"status": "unavailable", "error": {"code": exc.code, "message": str(exc)}, "observation": observation}


def select(case: dict, candidates: dict, records: dict, bundle: dict | None, judgement: dict) -> dict:
    decision = {"status": "unresolved", "selected_slot": None, "selected_output": None, "accepted_slots": [],
                "reason": "Common Y0 and the frozen evidence-arm judgement are required", "official_arm": "evidence"}
    if bundle is None or judgement.get("status") != "available":
        return decision
    assessment = validate_judgement(judgement["assessment"], list(bundle["aliases"]))
    base_qualified = (candidates.get("C0", {}).get("status") == "valid" and assessment["baseline_content"] == "pass"
                      and evidence_status(records.get("C0", {}), case, candidates, "C0") == "measured")
    outcomes = {c["id"]: c for c in assessment["candidates"]}
    for alias in assessment["ranking"]:
        slot = bundle["aliases"][alias]
        outcome = outcomes[alias]
        if (candidates[slot]["status"] == "valid" and outcome["content"] == "pass" and outcome["improvement"] == "improved"
                and evidence_status(records.get(slot, {}), case, candidates, slot) == "measured"
                and evidence_status(records.get("C0", {}), case, candidates, "C0") == "measured"):
            decision["accepted_slots"].append(slot)
    selected = decision["accepted_slots"][0] if decision["accepted_slots"] else ("C0" if base_qualified else None)
    if selected:
        decision.update(status="selected", selected_slot=selected, selected_output=deepcopy(candidates[selected]["output"]),
                        reason="Explicit content preservation and improvement" if selected != "C0" else "Content-qualified common Y0 fallback")
    else:
        decision["reason"] = "No evidence-qualified improved candidate and no content-qualified Y0"
    return decision
