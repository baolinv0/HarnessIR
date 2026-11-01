"""Audit the exact final model condition; quotations alone prove provenance."""
from copy import deepcopy
from .common import digest, render_instruction, require
from ..reference_core.rendering import render_target_limits


def condition_identity(condition):
    return digest({"text":condition["text"],"native_output":condition.get("native_output")})


def structural_audit(request,condition):
    """Only the exact deterministic renderer is eligible for structural coverage."""
    require(condition["text"]==render_instruction(request) and condition.get("native_output") is None,
            "semantic_audit_required","A rewritten/native condition requires independent semantic review")
    text=condition["text"];spans=[]
    for t in request["intent"]["targets"]:
        phrase=render_target_limits(t);start=text.index(phrase)
        spans.append({"id":t["id"],"start":start,"end":start+len(phrase),"status":"covered"})
    return dict(mode="deterministic_structural",condition_sha256=condition_identity(condition),
        reference_contract_sha256=request["reference_contract_sha256"],target_results=spans,
        protections="covered",exclusions="covered",status="pass")


def bind_semantic_audit(request,condition,judgement):
    from .reference_retouch_v2 import validate_payload
    from .reference_selector import frozen_contract
    contract=frozen_contract(request["intent"])
    validate_payload("audit_condition",judgement,{"workflow_contract":"reference_retouch_v2",
        "context":{"condition_sha256":condition_identity(condition),"reference_contract":contract}})
    statuses=[r["status"] for r in judgement["target_results"]]+[judgement["protections"],judgement["exclusions"]]
    # Optional targets also cannot be silently removed from the actual instruction.
    return {**deepcopy(judgement),"mode":"independent_semantic_review",
            "status":"pass" if all(s=="covered" for s in statuses) else "pending"}


def require_audit(request,condition):
    audit=condition.get("semantic_audit",{})
    require(audit.get("condition_sha256")==condition_identity(condition) and
            audit.get("reference_contract_sha256")==request["reference_contract_sha256"] and audit.get("status")=="pass",
            "semantic_audit_pending","Final native condition has missing, contradictory or uncertain semantic coverage")
    if audit.get("mode")=="deterministic_structural":
        expected=structural_audit(request,condition)
    elif audit.get("mode")=="independent_semantic_review":
        judgement={k:v for k,v in audit.items() if k not in {"mode","status"}}
        expected=bind_semantic_audit(request,condition,judgement)
    else:
        require(False,"semantic_audit_invalid","A status/hash sidecar is not a complete validated semantic judgement")
    require(audit==expected and expected["status"]=="pass","semantic_audit_invalid","Final semantic audit is incomplete or inconsistent")
