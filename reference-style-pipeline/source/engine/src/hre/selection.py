"""Frozen workflow selector; verification confidence is a gate, never a rank."""
from copy import deepcopy
import math

PRESERVATION_KINDS = {"composition", "geometry", "identity", "text", "scene_content"}
MINIMUM_CONFIDENCE = .7


def validate_verification(verification: dict) -> None:
    """Reject contradictory summaries and repeated observation categories."""
    observations = verification.get("preservation_observations", [])
    kinds = [item["kind"] for item in observations]
    if len(kinds) != len(set(kinds)):
        raise ValueError("duplicate preservation observation kind")
    if verification.get("content_preservation") == "pass":
        if set(kinds) != PRESERVATION_KINDS or any(o["status"] != "pass" for o in observations) or verification.get("critical_defects"):
            raise ValueError("content pass requires five passing observations and no critical defect")
    if verification.get("style_alignment") == "improved" and not any(o.get("comparability") in {"comparable", "partly_comparable"} for o in verification.get("style_observations", [])):
        raise ValueError("style improved requires a comparable observation")
    confidence = verification.get("confidence")
    if not isinstance(confidence, (float, int)) or isinstance(confidence, bool) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError("invalid verification confidence")


def evaluate_candidate(candidate: dict) -> dict:
    result = deepcopy(candidate)
    verification = candidate.get("verification")
    if verification is None:
        result.update(usable=False, accepted=False)
        return result
    validate_verification(verification)
    usable = (candidate.get("geometry", {}).get("status") == "pass"
              and verification["content_preservation"] == "pass"
              and not verification["critical_defects"]
              and verification["confidence"] >= MINIMUM_CONFIDENCE
              and not candidate.get("duplicate_of"))
    result.update(usable=usable, accepted=usable and verification["style_alignment"] == "improved")
    return result


def selected_candidate_asset(candidate: dict) -> dict:
    """The normalized asset is both verifier input and delivered output."""
    return candidate.get("geometry", {}).get("derived_asset") or candidate["asset"]


def select_final(rounds: list[dict], baseline: dict) -> dict:
    candidates = sorted((evaluate_candidate(c) for c in rounds), key=lambda c: c["round"])
    if len({c["round"] for c in candidates}) != len(candidates):
        raise ValueError("multiple formal candidates in one round")
    accepted = next((c for c in candidates if c["accepted"]), None)
    chosen = accepted or next((c for c in candidates if c["usable"]), None)
    if chosen:
        return {"selection": {"kind": "candidate", "asset_id": selected_candidate_asset(chosen)["asset_id"],
                              "candidate_id": chosen["candidate_id"], "fallback": False,
                              "review_required": accepted is None, "selected_round": chosen["round"]},
                "success": accepted is not None, "reason": "accepted" if accepted else "earliest_usable_review_required"}
    return {"selection": {"kind": "baseline", "asset_id": baseline["asset_id"], "candidate_id": None,
                          "fallback": True, "review_required": True, "selected_round": None},
            "success": False, "reason": "no_usable_candidate"}
