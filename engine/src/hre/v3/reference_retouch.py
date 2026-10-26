"""Opt-in reference-retouch contracts, independent of model providers.

The original v3 schemas remain immutable. This version makes reference facts,
allowed changes and success criteria distinct and freezes the latter for
verification and feedback. Schema validity is not evidence of image quality.
"""
from __future__ import annotations

from copy import deepcopy

from jsonschema import Draft202012Validator

from .common import digest, require

VERSION = "reference_retouch_v1"
TEMPLATE_VERSION = "hre_reference_retouch_stages_v1"
REFERENCE_DIMENSIONS = frozenset({
    "neutral_balance", "chroma_by_hue", "skin_rendering", "shadow_midtone_highlight",
    "highlight_transition", "local_contrast", "subject_background_balance", "texture_and_noise_observation",
})
ARTIFACT_CHECKS = frozenset({"naturalness", "reference_content_leakage", "unsupported_detail"})
ISSUE_KINDS = {"residual_degradation", "appearance_target_unmet", "overcorrection", "content_damage",
               "text_identity_damage", "execution_contract_violation", "uncertain"}
_TEXT = {"type": "string", "minLength": 1, "pattern": r"\S"}
_STRING = {"type": "string"}
_STRINGS = {"type": "array", "uniqueItems": True, "items": _TEXT}
_REFS = {**_STRINGS, "minItems": 1}
_ATTRIBUTE = {"enum": sorted(REFERENCE_DIMENSIONS)}
_COMPARABILITY = {"enum": ["comparable", "conditional", "incomparable", "unknown"]}
_COVERAGE_STATES = ["targeted", "preserve", "already_satisfied", "uncertain", "not_applicable", "excluded"]


def _object(properties, *, optional=()):
    return {"type": "object", "additionalProperties": False,
            "required": [key for key in properties if key not in optional], "properties": properties}


def _coverage(link):
    return {"type": "array", "items": _object({"attribute": _ATTRIBUTE,
            "status": {"enum": _COVERAGE_STATES}, "reason": _TEXT, link: _STRINGS})}


_DELTA = _object({"id": _TEXT, "attribute": _ATTRIBUTE, "source_region": _TEXT,
    "reference_region": _TEXT, "source_observation": _TEXT, "reference_observation": _TEXT,
    "desired_change": _TEXT, "comparability": _COMPARABILITY, "uncertainty": _STRING, "evidence_refs": _REFS})
_TARGET = _object({"id": _TEXT, "delta_id": _TEXT, "attribute": _ATTRIBUTE, "region": _TEXT,
    "instruction": _TEXT, "priority": {"type": "integer", "minimum": 1},
    "source_region": _TEXT, "reference_region": _TEXT, "source_observation": _TEXT,
    "reference_observation": _TEXT, "comparability": _COMPARABILITY, "uncertainty": _STRING,
    "mandatory": {"type": "boolean"}, "acceptance_criterion": _TEXT, "evidence_refs": _REFS}, optional=("uncertainty",))
_RELATION = _object({"subject": _TEXT, "object": _TEXT, "instruction": _TEXT, "evidence_refs": _REFS})
_FINDING = _object({"id": _TEXT, "region": _TEXT, "kind": _TEXT, "observation": _TEXT,
                   "confidence": {"type": "number", "minimum": 0, "maximum": 1}, "evidence_refs": _REFS})
DIAGNOSIS_SCHEMA = _object({"schema_version": {"const": "hre_reference_diagnosis_v1"},
    "task_mode": {"const": "reference_enhance"}, "findings": {"type": "array", "items": _FINDING},
    "protected_content": {**_STRINGS, "minItems": 1}, "uncertainties": _STRINGS,
    "tool_requests": {"type": "array", "uniqueItems": True, "items": {"enum": ["basic_statistics"]}},
    "summary": _TEXT, "analysis_status": {"enum": ["transfer_supported", "already_close", "insufficient_reference", "needs_evidence"]},
    "reference_profile": {"type": "array", "items": _object({"attribute": _ATTRIBUTE,
        "status": {"enum": ["observed", "uncertain", "not_applicable"]}, "observation": _TEXT,
        "region": _TEXT, "evidence_refs": _REFS})},
    "candidate_deltas": {"type": "array", "items": _DELTA}, "coverage": _coverage("delta_ids")})
INTENT_SCHEMA = _object({"schema_version": {"const": "hre_reference_intent_v1"},
    "task_mode": {"const": "reference_enhance"}, "revision": {"type": "integer", "minimum": 0},
    "targets": {"type": "array", "items": _TARGET}, "region_relations": {"type": "array", "items": _RELATION},
    "protected_content": {**_STRINGS, "minItems": 1}, "uncertainties": _STRINGS, "summary": _TEXT,
    "parent_intent_hash": {"anyOf": [{"type": "null"}, {"type": "string", "pattern": "^[0-9a-f]{64}$"}]},
    "feedback_refs": _STRINGS,
    "overall_status": {"enum": ["ready_to_edit", "already_satisfied", "insufficient_evidence"]},
    "excluded_reference_traits": _STRINGS, "coverage": _coverage("target_ids")})
_ISSUE = _object({"id": _TEXT, "kind": {"enum": sorted(ISSUE_KINDS)}, "region": _TEXT,
    "observation": _TEXT, "evidence_refs": _REFS, "suggested_change": {"anyOf": [_TEXT, {"type": "null"}]}})
_CHECK = _object({"item": _TEXT, "status": {"enum": ["pass", "fail", "uncertain"]},
                  "observation": _TEXT, "evidence_refs": _REFS})
VERIFICATION_SCHEMA = _object({"verdict": {"enum": ["accept", "revise", "reject", "uncertain"]},
    "issues": {"type": "array", "items": _ISSUE}, "preservation": {"enum": ["pass", "fail", "uncertain"]},
    "task_progress": {"enum": ["improved", "unchanged", "worse", "uncertain"]},
    "confidence": {"type": "number", "minimum": 0, "maximum": 1}, "summary": _TEXT,
    "target_results": {"type": "array", "items": _object({"id": _TEXT,
        "status": {"enum": ["achieved", "partial", "unmet", "uncertain"]}, "observation": _TEXT,
        "evidence_refs": _REFS, "remaining_gap": _STRING,
        "suggested_correction": {"anyOf": [_TEXT, {"type": "null"}]}})},
    "preservation_checks": {"type": "array", "items": _CHECK}, "artifact_checks": {"type": "array", "items": _CHECK},
    "detail_preservation": {"enum": ["pass", "fail", "uncertain"]}}, optional=("detail_preservation",))
REFINEMENT_SCHEMA = _object({"action": {"enum": ["revise", "stop"]}, "reason": _TEXT,
                            "intent": {"anyOf": [INTENT_SCHEMA, {"type": "null"}]}})
SCHEMAS = {"diagnose": DIAGNOSIS_SCHEMA, "compose": INTENT_SCHEMA, "verify": VERIFICATION_SCHEMA, "refine": REFINEMENT_SCHEMA}


def enabled(spec_or_request: dict) -> bool:
    return spec_or_request.get("workflow_contract") == VERSION


def validate_spec(spec: dict) -> None:
    if "workflow_contract" not in spec:
        require("delivery_requirements" not in spec, "reference_contract_required",
                "Version delivery requirements explicitly with workflow_contract")
        return
    require(enabled(spec), "workflow_contract_invalid", "Unknown reference workflow contract")
    require(spec.get("task_mode") == "reference_enhance" and spec.get("strategy", "model_aware") != "native",
            "workflow_contract_invalid", "Reference-retouch planning requires a reference task and shared/model_aware strategy")
    requirements = spec.get("delivery_requirements", {})
    require(isinstance(requirements, dict) and not set(requirements) - {
        "require_native_source_resolution", "minimum_native_size", "require_detail_pass"},
        "delivery_requirements_invalid", "Unknown or invalid delivery requirement")
    for key in ("require_native_source_resolution", "require_detail_pass"):
        require(key not in requirements or type(requirements[key]) is bool,
                "delivery_requirements_invalid", key + " must be boolean")
    if "minimum_native_size" in requirements:
        size = requirements["minimum_native_size"]
        require(isinstance(size, list) and len(size) == 2 and all(type(v) is int and v > 0 for v in size),
                "delivery_requirements_invalid", "minimum_native_size is [positive integer width, height]")


def _schema_check(schema: dict, value: dict, code="stage_payload_invalid") -> None:
    error = next(iter(Draft202012Validator(schema).iter_errors(value)), None)
    require(error is None, code, error.message if error else "Invalid payload")
    digest(value)  # canonical JSON rejects NaN and infinity from injected providers too


def _unique(rows: list[dict], key: str, code: str) -> set[str]:
    values = [item[key] for item in rows]
    require(len(values) == len(set(values)), code, "Duplicate " + key)
    return set(values)


def _role_present(refs, role):
    return any(ref == role or ref.startswith("evidence:" + role + ":") for ref in refs)


def _refs(refs, allowed, *, roles=(), code="stage_unsupported_evidence"):
    require(bool(refs) and (allowed is None or set(refs) <= allowed), code, "Evidence is missing or was not available")
    require(all(_role_present(refs, role) for role in roles), code, "Evidence must cite " + ", ".join(roles))


def _coverage_check(rows, records, link, code):
    require(_unique(rows, "attribute", code) == REFERENCE_DIMENSIONS, code, "All eight reference dimensions must be covered once")
    by_id = {item["id"]: item for item in records}
    mapped = set()
    for row in rows:
        ids = set(row[link])
        require(ids <= by_id.keys(), code, "Coverage links an unknown record")
        require((row["status"] == "targeted") == bool(ids), code, "Only targeted dimensions link actionable records")
        require(all(by_id[item]["attribute"] == row["attribute"] for item in ids), code, "Coverage attribute differs from linked record")
        mapped.update(ids)
    require(mapped == by_id.keys(), code, "Every record must be covered")


def validate_intent(intent: dict, task_mode: str, *, revision: int | None = None,
                    parent_hash: str | None = None, check_parent: bool = False,
                    allowed_refs: set[str] | None = None) -> dict:
    _schema_check(INTENT_SCHEMA, intent, "intent_invalid")
    require(intent["task_mode"] == task_mode, "intent_mode_mismatch", "Intent belongs to another task mode")
    if revision is not None:
        require(intent["revision"] == revision, "intent_revision_mismatch", "Unexpected intent revision")
    if check_parent:
        require(intent["parent_intent_hash"] == parent_hash, "intent_parent_mismatch", "Unexpected parent intent")
    targets = intent["targets"]
    _unique(targets, "id", "intent_invalid")
    require([item["priority"] for item in targets] == list(range(1, len(targets) + 1)),
            "intent_invalid", "Target priorities must be contiguous")
    _coverage_check(intent["coverage"], targets, "target_ids", "intent_coverage")
    if intent["overall_status"] == "ready_to_edit":
        require(bool(targets) and any(t["mandatory"] for t in targets), "intent_invalid", "Editing needs a supported mandatory target")
    else:
        require(not targets and not intent["region_relations"], "intent_invalid", "Non-editing outcomes cannot issue edit targets or relations")
    if intent["overall_status"] == "already_satisfied":
        require(all(row["status"] in {"already_satisfied", "preserve", "not_applicable", "excluded"}
                    for row in intent["coverage"]), "intent_invalid", "Already satisfied cannot hide an uncertain or pending dimension")
    for item in targets:
        require(item["attribute"] != "texture_and_noise_observation", "intent_invalid", "Reference texture observation is a protection boundary, not a texture-copy goal")
        require(not item["mandatory"] or item["comparability"] in {"comparable", "conditional"},
                "intent_invalid", "Mandatory targets require comparable reference attributes")
        require(item["comparability"] != "conditional" or bool(item.get("uncertainty", "").strip()),
                "intent_invalid", "Conditional correspondence needs its limitations")
        _refs(item["evidence_refs"], allowed_refs, roles=("source", "appearance_reference"), code="intent_unsupported_evidence")
    for relation in intent["region_relations"]:
        require(relation["subject"] != relation["object"], "intent_invalid", "A region relation needs distinct subjects")
        _refs(relation["evidence_refs"], allowed_refs, roles=("source", "appearance_reference"), code="intent_unsupported_evidence")
    require(allowed_refs is None or set(intent["feedback_refs"]) <= allowed_refs,
            "intent_unsupported_evidence", "Feedback references are unavailable")
    return deepcopy(intent)


def frozen_contract(intent: dict) -> dict:
    """Project immutable facts and criteria; execution instructions may be revised."""
    return {"schema_version": "hre_reference_contract_v1", "overall_status": intent["overall_status"],
            "targets": [{key: deepcopy(value) for key, value in target.items() if key != "instruction"}
                        for target in intent["targets"]],
            **{key: deepcopy(intent[key]) for key in ("region_relations", "protected_content", "excluded_reference_traits", "coverage")}}


def _diagnosis(payload, request, allowed):
    require(payload["task_mode"] == request["task_mode"], "stage_mode_mismatch", "Diagnosis mode changed")
    _unique(payload["findings"], "id", "stage_payload_invalid")
    for finding in payload["findings"]:
        _refs(finding["evidence_refs"], allowed, roles=("source",))
    require(_unique(payload["reference_profile"], "attribute", "reference_coverage") == REFERENCE_DIMENSIONS,
            "reference_coverage", "Reference profile must observe all eight dimensions once")
    for item in payload["reference_profile"]:
        _refs(item["evidence_refs"], allowed, roles=("appearance_reference",))
    _unique(payload["candidate_deltas"], "id", "stage_payload_invalid")
    for item in payload["candidate_deltas"]:
        _refs(item["evidence_refs"], allowed, roles=("source", "appearance_reference"))
        require(item["comparability"] != "conditional" or bool(item["uncertainty"].strip()),
                "reference_comparability", "Conditional reference differences need their limitations")
    _coverage_check(payload["coverage"], payload["candidate_deltas"], "delta_ids", "reference_coverage")
    if payload["analysis_status"] == "transfer_supported":
        require(bool(payload["candidate_deltas"]), "reference_diagnosis_invalid", "Supported transfer needs an observed difference")
    if payload["analysis_status"] == "already_close":
        require(not payload["candidate_deltas"] and all(row["status"] in {
            "already_satisfied", "preserve", "not_applicable", "excluded"} for row in payload["coverage"]),
            "reference_diagnosis_invalid", "Already close cannot contain unresolved differences")


def _composition(payload, request, allowed):
    validate_intent(payload, request["task_mode"], revision=0, check_parent=True, allowed_refs=allowed)
    require(not payload["feedback_refs"], "intent_invalid", "Initial composition cannot cite feedback")
    diagnosis = request.get("context", {}).get("diagnosis")
    require(isinstance(diagnosis, dict), "reference_diagnosis_required", "Composition requires the actual diagnosis")
    _schema_check(DIAGNOSIS_SCHEMA, diagnosis)
    _diagnosis(diagnosis, request, allowed)
    require(set(diagnosis["protected_content"]) <= set(payload["protected_content"]),
            "source_protection_missing", "Composition dropped a diagnosed source protection")
    by_id = {item["id"]: item for item in diagnosis["candidate_deltas"]}
    for target in payload["targets"]:
        delta = by_id.get(target["delta_id"])
        require(delta is not None, "target_delta_missing", "Target does not cite an observed difference")
        require(all(target[key] == delta[key] for key in (
            "attribute", "source_region", "reference_region", "source_observation", "reference_observation", "comparability")),
            "target_delta_mismatch", "Target changed the diagnosed source/reference facts")
        require(set(delta["evidence_refs"]) <= set(target["evidence_refs"]),
                "target_delta_mismatch", "Target lost evidence supporting its difference")
        if delta["comparability"] == "conditional":
            require(target.get("uncertainty") == delta["uncertainty"], "target_delta_mismatch", "Target lost correspondence limitations")
    if payload["overall_status"] == "already_satisfied":
        require(diagnosis["analysis_status"] == "already_close" and not diagnosis["candidate_deltas"],
                "already_satisfied_unsupported", "Only an already-close diagnosis supports a successful no-edit outcome")
    elif payload["overall_status"] == "ready_to_edit":
        require(diagnosis["analysis_status"] == "transfer_supported", "reference_evidence_insufficient", "Editing requires supported reference differences")
    else:
        require(diagnosis["analysis_status"] in {"insufficient_reference", "needs_evidence"},
                "reference_diagnosis_mismatch", "Insufficient evidence must be reflected in the diagnosis")


def _verification(payload, request, allowed):
    contract = request.get("context", {}).get("reference_contract")
    require(isinstance(contract, dict) and contract.get("schema_version") == "hre_reference_contract_v1",
            "reference_contract_required", "Verify needs frozen reference criteria")
    targets = contract["targets"]
    ids = _unique(payload["target_results"], "id", "verification_coverage")
    require(ids == {item["id"] for item in targets}, "verification_coverage", "Verify every frozen target exactly once")
    _unique(payload["issues"], "id", "verification_coverage")
    for item in payload["issues"]:
        _refs(item["evidence_refs"], allowed, roles=("candidate",))
    for item in payload["target_results"]:
        _refs(item["evidence_refs"], allowed, roles=("source", "appearance_reference", "candidate"))
    require(_unique(payload["preservation_checks"], "item", "preservation_coverage") == set(contract["protected_content"]),
            "preservation_coverage", "Check every frozen source protection exactly once")
    require(_unique(payload["artifact_checks"], "item", "artifact_coverage") == ARTIFACT_CHECKS,
            "artifact_coverage", "Check every required artifact category exactly once")
    checks = payload["preservation_checks"] + payload["artifact_checks"]
    for item in checks:
        _refs(item["evidence_refs"], allowed, roles=("source", "candidate"))
        if item.get("item") == "reference_content_leakage":
            _refs(item["evidence_refs"], allowed, roles=("appearance_reference",))
    if payload["verdict"] == "accept":
        mandatory = {item["id"] for item in targets if item["mandatory"]}
        damage = {"content_damage", "text_identity_damage", "execution_contract_violation"}
        require(payload["preservation"] == "pass" and payload["task_progress"] == "improved"
                and all(row["status"] == "achieved" for row in payload["target_results"] if row["id"] in mandatory)
                and all(item["status"] == "pass" for item in checks)
                and not any(item["kind"] in damage for item in payload["issues"]),
                "verification_contradiction", "Acceptance needs every mandatory target and source/naturalness check to pass")


def validate_payload(stage: str, payload: dict, request: dict) -> dict:
    require(stage in SCHEMAS, "stage_unknown", str(stage))
    _schema_check(SCHEMAS[stage], payload)
    context = request.get("context", {})
    # An explicitly empty list means no evidence, not an invitation to invent it.
    allowed = set(context.get("available_evidence_refs", []))
    if stage == "diagnose":
        _diagnosis(payload, request, allowed)
    elif stage == "compose":
        _composition(payload, request, allowed)
    elif stage == "verify":
        _verification(payload, request, allowed)
    elif payload["action"] == "stop":
        require(payload["intent"] is None, "refinement_invalid", "A stop decision cannot issue a revised intent")
    else:
        previous = context["previous_intent"]
        validate_intent(payload["intent"], request["task_mode"], revision=previous["revision"] + 1,
                        parent_hash=digest(previous), check_parent=True, allowed_refs=allowed)
        require(frozen_contract(payload["intent"]) == frozen_contract(previous), "reference_contract_changed",
                "Feedback may revise execution instructions, never frozen reference goals or acceptance criteria")
        require(bool(set(payload["intent"]["feedback_refs"]) & set(context.get("actionable_feedback_refs", []))),
                "refinement_unsupported", "Refinement must cite an actionable observed issue")
    return deepcopy(payload)


def stage_instruction(request: dict) -> str:
    common = (
        "Analyze the actual source A and appearance_reference B. A defines identity, expression, objects, readable text, "
        "viewpoint, framing, geometry and authentic visible detail. B defines only supported photographic appearance. "
        "Use their independent regions and attribute-specific comparability; B is not aligned ground truth. "
        "Never copy B's contents or textures, invent measurements, or treat material/illumination differences as proven processing. "
        "Return one JSON object matching the supplied schema. Use only available_evidence_refs; if images were not observed, "
        'return {"error":{"code":"image_not_observed","message":"reason"}}. '
    )
    instructions = {
        "diagnose": "Cover all eight reference dimensions with separate B observations, A/B candidate_deltas and coverage. "
            "Reference observations state what B shows, not a desired edit copied into the observation. Record source protection. "
            "Use transfer_supported for supported differences, already_close only when every requested attribute is already satisfied "
            "and no unresolved difference remains, insufficient_reference or needs_evidence for missing support. No degradation "
            "does not imply no reference-retouch target. Only basic_statistics is deployed; request it when useful.",
        "compose": "Convert the actual diagnosis and evidence into an attribute-complete shared intent. Every target cites its "
            "delta_id and preserves its source/reference observations, regions, comparability and evidence. Distinguish the "
            "instruction from the acceptance_criterion; declare mandatory versus optional and explain every coverage dimension. "
            "There is no three-target cap. Preserve diagnosed source protection and exclude B's content traits. Use revision=0, "
            "parent_intent_hash=null and feedback_refs=[]. already_satisfied requires already_close evidence and zero targets; "
            "insufficient_evidence is a separate unsuccessful no-edit outcome.",
        "verify": "Compare A/B/candidate using only the frozen reference_contract, trusted evidence and geometry. You do not "
            "receive the generation prompt or editor model identity. Return each frozen target id exactly once and each "
            "protected_content item exactly once; check naturalness, reference_content_leakage and unsupported_detail. "
            "mandatory targets must all be achieved; optional residuals remain visible without hiding the mandatory result. "
            "Any uncertain mandatory/protection check prevents accept. Mean color proximity and an attractive result do not "
            "prove texture authenticity. Inspect candidate_native at its native resolution when provided; record "
            "detail_preservation=uncertain when source high-frequency detail cannot be certified. Artifact pass does not "
            "certify original-detail authenticity. Native dimensions and the required detail gate are separately checked by the controller.",
        "refine": "Respond only to actionable observed verification issues. Keep the frozen reference target set, A/B facts, "
            "comparability, mandatory flags, acceptance criteria, evidence, protections, exclusions and coverage unchanged. "
            "Only revise execution instruction text and supported plan notes; retain all previously achieved goals. Use "
            "revision=previous+1 and parent_intent_hash=digest(previous_intent), citing actionable_feedback_refs. The next edit "
            "uses original A+B. If no supported correction exists, return action=stop and intent=null.",
    }
    require(request.get("stage") in instructions, "stage_unknown", str(request.get("stage")))
    return common + instructions[request["stage"]]
