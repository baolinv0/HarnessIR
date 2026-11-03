"""One bound feedback record is the controller's source of actionability."""
from copy import deepcopy
import hashlib
import json


def _hash(value): return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def normalize_feedback(contract, verification, *, candidate_id, round_index, verification_sha256=None, delivery=None):
    if not isinstance(candidate_id,str) or not candidate_id.strip() or type(round_index) is not int or round_index<0: raise ValueError("Exact candidate/round binding required")
    expected=verification_sha256 or _hash(verification)
    if expected!=_hash(verification): raise ValueError("Verification binding differs")
    targets=contract.get("targets",[])
    mandatory={t.get("target_id",t.get("id")) for t in targets if t["mandatory"]}
    rows=[]
    def add(scope,key,status,observation,correction,refs,mandatory=True,review_action=None):
        action="manual_review" if status in {"uncertain","unknown","pending"} else "revise_prompt" if status in {"partial","unmet","fail"} and correction else "stop"
        if review_action is not None:
            if review_action not in {"gather_evidence","manual_review","stop","revise_prompt"}:raise ValueError("Unsupported feedback action")
            if review_action=="revise_prompt" and (not correction or status in {"uncertain","unknown","pending"}):raise ValueError("Uncertain feedback cannot authorize refinement")
            action=review_action
        rows.append(dict(feedback_id=f"verification:{scope}:{key}",scope=scope,item_id=key,status=status,observation=observation,
            correction=correction,evidence_refs=deepcopy(refs),mandatory=mandatory,action=action))
    for row in verification.get("target_results",[]):
        key=row.get("target_id",row.get("id"))
        if row["status"]!="achieved":add("target",key,row["status"],row["observation"],row.get("suggested_correction"),row.get("evidence_refs",[]),key in mandatory,row.get("review_action"))
    for scope in ("preservation","artifact"):
        for row in verification.get(scope+"_checks",[]):
            if row["status"]!="pass":add(scope,row["item"],row["status"],row["observation"],row.get("suggested_correction"),row.get("evidence_refs",[]),review_action=row.get("review_action"))
    for key,row in verification.get("overall_style",{}).items():
        if row["reference_status"]!="achieved":add("whole_image",key,row["reference_status"],row["evidence"],None,["source","appearance_reference","candidate"])
    whole=verification.get("whole_image_review",{})
    for key,row in whole.get("preservation",{}).items():
        if row["status"]!="pass":add("whole_image_preservation",key,row["status"],row["evidence"],None,["source","candidate"])
    if whole.get("conflicts"):add("whole_image","unresolved_conflicts","uncertain","; ".join(whole["conflicts"]),None,[])
    if delivery and not delivery.get("pass",delivery.get("status")=="pass"):
        add("delivery","native_delivery",delivery.get("status","uncertain"),"Frozen native delivery requirements",None,[])
    # A known physical infeasibility stops before asking an editor for a prompt fix.
    known_damage=any(row["status"]=="fail" for row in whole.get("preservation",{}).values())
    if known_damage or delivery and delivery.get("status") in {"fail","infeasible"}: action="stop"
    elif any(r["mandatory"] and r["action"]=="gather_evidence" for r in rows): action="gather_evidence"
    elif any(r["mandatory"] and r["action"]=="manual_review" for r in rows): action="manual_review"
    elif any(r["action"]=="revise_prompt" for r in rows): action="revise_prompt"
    else: action="stop"
    return dict(schema_version="hre_feedback_v1",candidate_id=candidate_id,round=round_index,
        verification_sha256=expected,action=action,items=rows,known_major_damage=known_damage,
        actionable_feedback_refs=[r["feedback_id"] for r in rows if r["action"]=="revise_prompt"])
