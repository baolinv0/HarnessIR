#!/usr/bin/env python3
"""Offline static validation of the design package; no model or workflow runs."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, UndefinedError
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
CHECKS: list[str] = []


def check(condition: bool, name: str) -> None:
    if not condition:
        raise AssertionError(name)
    CHECKS.append(name)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


SCHEMAS = {p.name: read_json(p) for p in sorted((ROOT / "schemas").glob("*.json"))}
RESOURCES = {}
for filename, original in SCHEMAS.items():
    schema = copy.deepcopy(original)
    uri = (ROOT / "schemas" / filename).as_uri()
    schema["$id"] = uri
    Draft202012Validator.check_schema(schema)
    RESOURCES[uri] = Resource.from_contents(schema)
    CHECKS.append("schema: " + filename)
REGISTRY = Registry().with_resources(RESOURCES.items())


def validator(filename: str, fragment: str = "") -> Draft202012Validator:
    uri = (ROOT / "schemas" / filename).as_uri()
    return Draft202012Validator(
        {"$ref": uri + fragment}, registry=REGISTRY, format_checker=FormatChecker()
    )


def valid(filename: str, value, name: str, fragment: str = "") -> None:
    errors = list(validator(filename, fragment).iter_errors(value))
    check(not errors, name + (": " + str(errors[0]) if errors else ""))


def invalid(filename: str, value, name: str, fragment: str = "") -> None:
    check(bool(list(validator(filename, fragment).iter_errors(value))), name)


def canonical_sha(value) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    for path in sorted(ROOT.rglob("*.json")):
        read_json(path)
        CHECKS.append("json: " + str(path.relative_to(ROOT)))
    fixture = read_json(ROOT / "examples/stage_payloads.example.json")
    check(fixture["simulation_only"] is True, "stage fixtures explicitly synthetic")
    stages = {"diagnose": "diagnosis", "compose": "composition",
              "verify": "verification", "refine": "refinement"}
    for stage, payload_name in stages.items():
        schema = payload_name + ".schema.json"
        payload = fixture["payloads"][payload_name]
        valid(schema, payload, "stage payload: " + payload_name)
        bad = copy.deepcopy(payload)
        bad["unexpected_field"] = True
        invalid(schema, bad, "extra key rejected: " + payload_name)
        bad = copy.deepcopy(payload)
        bad.pop(SCHEMAS[schema]["required"][0])
        invalid(schema, bad, "missing key rejected: " + payload_name)
        check(fixture["sample_context"][stage]["result_schema"] == SCHEMAS[schema],
              "inline schema matches file: " + payload_name)
    valid("diagnosis.schema.json", fixture["unseen_images_diagnosis"],
          "unknown diagnosis is a legal parser fixture")
    for confidence in [True, "0.8", -0.01, 1.01]:
        bad = copy.deepcopy(fixture["payloads"]["verification"])
        bad["confidence"] = confidence
        invalid("verification.schema.json", bad, "bad confidence: " + repr(confidence))
    for property_name, value in [("style_alignment", "true"),
                                 ("content_preservation", True)]:
        bad = copy.deepcopy(fixture["payloads"]["verification"])
        bad[property_name] = value
        invalid("verification.schema.json", bad, "three-state typing: " + property_name)
    evidence_ref = copy.deepcopy(fixture["payloads"]["composition"])
    evidence_ref["evidence_ids"] = ["E.STATS-001"]
    valid("composition.schema.json", evidence_ref, "cross-schema public evidence ID")
    for kind in ["composition", "geometry", "identity", "text", "scene_content"]:
        bad = copy.deepcopy(fixture["payloads"]["verification"])
        bad["preservation_observations"] = [o for o in bad["preservation_observations"] if o["kind"] != kind]
        invalid("verification.schema.json", bad, "pass requires observation: " + kind)
    bad = copy.deepcopy(fixture["payloads"]["verification"])
    bad["preservation_observations"][0]["status"] = "fail"
    invalid("verification.schema.json", bad, "summary pass cannot override detailed fail")
    bad = copy.deepcopy(fixture["payloads"]["verification"])
    bad.update(style_alignment="improved", style_observations=[])
    invalid("verification.schema.json", bad, "improvement requires comparable observation")
    refine = fixture["sample_context"]["refine"]
    check(refine["response_identity"]["round"] == refine["source_round"] + 1,
          "refine envelope targets next generation round")

    env = Environment(loader=FileSystemLoader(str(ROOT / "prompts")),
                      undefined=StrictUndefined, autoescape=False)
    for stage, context in fixture["sample_context"].items():
        template = env.get_template(stage + ".j2")
        rendered = json.loads(template.render(**context))
        CHECKS.append("template JSON rendered: " + stage)
        expected_labels = ["A", "B", "C"] if stage in ["verify", "refine"] else ["A", "B"]
        check([a["label"] for a in rendered["image_bindings"]] == expected_labels,
              "template image labels: " + stage)
        if stage in stages:
            valid("asset.schema.json", context["response_identity"]["input_assets"][0],
                  "template primary asset: " + stage)
            response = copy.deepcopy(context["response_identity"])
            response.update(status="ok", model_observed=context["model_observed"],
                            session_id=context["session_id"], error=None,
                            payload=fixture["payloads"][stages[stage]])
            valid("response.schema.json", response, "template response envelope: " + stage)
            response.update(status="error", payload=None,
                            error={"code": "image_not_observed",
                                   "message": "Synthetic error fixture", "retryable": True})
            valid("response.schema.json", response, "error envelope: " + stage)
        for key in context:
            incomplete = dict(context)
            incomplete.pop(key)
            try:
                template.render(**incomplete)
            except (UndefinedError, TypeError) as exc:
                if isinstance(exc, TypeError) and "StrictUndefined" not in str(exc):
                    raise
                CHECKS.append("missing template context rejected: " + stage + "/" + key)
            else:
                raise AssertionError("StrictUndefined did not reject " + stage + "/" + key)
    context = copy.deepcopy(fixture["sample_context"]["execute"])
    context["edit_prompt"] = 'Quotes " and newline\n中文; $() remains data.'
    rendered = json.loads(env.get_template("execute.j2").render(**context))
    check(context["edit_prompt"] in rendered["edit_prompt"], "JSON escaping round trip")

    protocol = read_json(ROOT / "examples/state_protocol.example.json")
    check(protocol["simulation_only"] is True, "protocol fixtures explicitly synthetic")
    groups = {"assets": ("asset.schema.json", ""),
              "requests": ("request.schema.json", ""),
              "responses": ("response.schema.json", ""),
              "states": ("state.schema.json", ""),
              "evidence_records": ("evidence.schema.json", ""),
              "snapshots": ("evidence.schema.json", "#/$defs/snapshot"),
              "done_manifests": ("response.schema.json", "#/$defs/done_manifest")}
    for group, (filename, fragment) in groups.items():
        check(len(protocol[group]) > 0, "fixture group exists: " + group)
        for i, value in enumerate(protocol[group]):
            valid(filename, value, "protocol fixture: " + group + "/" + str(i), fragment)
    for request in protocol["requests"]:
        unsigned = {k: v for k, v in request.items() if k != "request_sha256"}
        check(canonical_sha(unsigned) == request["request_sha256"],
              "computed request hash: " + request["task_id"])
    for path in ["/outside.png", "../outside.png", "input/../outside.png",
                 "C:\\outside.png", "input//outside.png"]:
        bad = copy.deepcopy(protocol["assets"][0])
        bad["path"] = path
        invalid("asset.schema.json", bad, "unsafe path rejected: " + path)
    bad = copy.deepcopy(protocol["requests"][0])
    bad["input_assets"] = [a for a in bad["input_assets"] if a["role"] != "reference"]
    invalid("request.schema.json", bad, "request without reference rejected")
    bad = copy.deepcopy(protocol["responses"][0])
    bad.update(status="ok", payload=None)
    invalid("response.schema.json", bad, "ok response cannot have null payload")

    config = read_json(ROOT / "config/experiment_profiles.json")
    profiles = config["profiles"]
    check(profiles["baseline"]["max_generations"] == 0, "baseline zero budget")
    check(profiles["direct_ref"]["max_generations"] == profiles["agent_single"]["max_generations"] == 1,
          "single generation comparison")
    check(profiles["direct_best_of_3"]["max_generations"] == profiles["agent_adaptive"]["max_generations"] == 3,
          "three generation cap comparison")
    check(profiles["agent_adaptive"]["evidence_policy"] == "diagnosis_planned_only",
          "refine does not add a tool plan")
    check(profiles["direct_best_of_3"]["stop_on_accept"] is False,
          "fixed K has no accept early stop")
    check(profiles["direct_best_of_3"]["no_accepted_budget_completion_terminal_reason"] == "fixed_k_complete",
          "fixed K completion separate from adaptive exhaustion")
    selector = config["common"]["selector"]
    for requirements in ["accept_requirements", "usable_requirements"]:
        check(selector[requirements]["critical_defects_empty"] is True,
              "critical defect gate: " + requirements)
        check(selector[requirements]["minimum_confidence"] == 0.7,
              "frozen confidence heuristic: " + requirements)
    check(selector["rank_by_confidence"] is False and selector["rank_by_no_reference_score"] is False,
          "selector cannot rank by confidence or NR")
    resize = config["common"]["output_normalization"]["optional_aspect_preserving_resize"]
    check(resize["require_exact_aspect_cross_product"] is True,
          "optional resize cannot introduce anisotropic warp")
    check(config["reference_is_pixel_ground_truth"] is False, "reference is not pixel GT")
    manifest = read_json(ROOT / "examples/dataset_manifest.example.json")
    check(manifest.get("simulation_only") is True, "dataset manifest explicitly synthetic")

    for path in sorted(ROOT.rglob("*.md")):
        content = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.S)
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", content):
            if "://" in target or target.startswith("#") or target.startswith("mailto:"):
                continue
            local = (path.parent / target.split("#")[0]).resolve()
            check(local.exists(), "relative link exists: " + str(path.relative_to(ROOT)) + " -> " + target)
    print(json.dumps({"status": "PASS", "checks": len(CHECKS),
                      "schemas": len(SCHEMAS), "templates": len(fixture["sample_context"]),
                      "scope": "static design package only; no image/model/controller execution"},
                     ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "completed_checks": len(CHECKS),
                          "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise
