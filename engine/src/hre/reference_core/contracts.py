"""Strict semantics for new versioned records; never upgrades historical data."""
from copy import deepcopy
import json

DIMENSIONS = frozenset({"neutral_balance", "chroma_by_hue", "skin_rendering",
    "shadow_midtone_highlight", "highlight_transition", "local_contrast",
    "subject_background_balance", "texture_and_noise_observation"})
COVERAGE_STATES = frozenset({"targeted", "preserve", "already_satisfied", "uncertain", "not_applicable", "excluded"})


def _check(ok, message):
    if not ok: raise ValueError(message)


def size(value, name="size"):
    _check(isinstance(value,(list,tuple)) and len(value)==2 and all(type(v) is int and v>0 for v in value),
           name+" must contain two positive integer dimensions")
    return list(value)


def validate_requirements(value):
    _check(isinstance(value,dict) and not set(value)-{"require_native_source_resolution", "minimum_native_size", "require_detail_pass"},
           "Unknown delivery requirements")
    for k in ("require_native_source_resolution","require_detail_pass"):
        _check(k not in value or type(value[k]) is bool, k+" must be boolean")
    if "minimum_native_size" in value: size(value["minimum_native_size"],"minimum_native_size")
    return deepcopy(value)


def validate_semantics(spec: dict) -> dict:
    _check(isinstance(spec,dict) and set(spec)=={"coverage","targets","delivery_requirements"}, "Expected coverage, targets and delivery_requirements")
    json.dumps(spec,allow_nan=False)
    validate_requirements(spec["delivery_requirements"])
    rows,targets=spec["coverage"],spec["targets"]
    _check(isinstance(rows,list) and isinstance(targets,list),"Coverage and targets must be arrays")
    by_id={}
    for t in targets:
        _check(isinstance(t,dict),"Target must be an object")
        for k in ("target_id","attribute","source_observation","reference_observation","acceptance_criterion"):
            _check(isinstance(t.get(k),str) and bool(t[k].strip()), "Target requires "+k)
        _check(t["target_id"] not in by_id,"Duplicate target id")
        _check(t["attribute"] in DIMENSIONS-{"texture_and_noise_observation"},"Unsupported actionable attribute")
        _check(type(t.get("mandatory")) is bool,"Target requires mandatory flag")
        _check(t.get("comparability") in {"comparable","conditional"},"Unknown/incomparable facts cannot authorize edits")
        _check(isinstance(t.get("uncertainty"),str),"Target requires explicit uncertainty")
        _check(t["comparability"]!="conditional" or bool(t["uncertainty"].strip()),"Conditional target requires limitations")
        by_id[t["target_id"]]=t
    attrs=[];mapped=[]
    for row in rows:
        _check(isinstance(row,dict),"Coverage row must be an object")
        attrs.append(row.get("attribute"))
        _check(row.get("status") in COVERAGE_STATES and isinstance(row.get("reason"),str) and bool(row["reason"].strip()),"Coverage requires status and reason")
        ids=row.get("target_ids")
        _check(isinstance(ids,list) and all(isinstance(i,str) for i in ids) and len(ids)==len(set(ids)),"Coverage target IDs must be unique")
        _check((row["status"]=="targeted")==bool(ids),"Only targeted rows may link targets")
        _check(all(i in by_id and by_id[i]["attribute"]==row.get("attribute") for i in ids),"Coverage links missing or different attribute")
        mapped.extend(ids)
    _check(len(attrs)==len(DIMENSIONS) and len(set(attrs))==len(attrs) and set(attrs)==DIMENSIONS,"Cover each of the eight dimensions exactly once")
    _check(len(mapped)==len(set(mapped)) and set(mapped)==set(by_id),"Every target must be covered exactly once")
    return deepcopy(spec)
