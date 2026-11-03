"""Deterministic factual limits. No reviewer preferences are accepted."""
import json


def render_target_limits(target: dict) -> str:
    if not isinstance(target,dict): raise ValueError("Target must be an object")
    json.dumps(target,allow_nan=False)
    identifier=target.get("target_id",target.get("id"))
    if not isinstance(identifier,str) or not identifier.strip(): raise ValueError("Target ID required")
    keys=("attribute","source_region","reference_region","source_observation","reference_observation",
          "comparability","uncertainty","mandatory","acceptance_criterion")
    labels={"mandatory":"Mandatory", "uncertainty":"Limitations", "acceptance_criterion":"Acceptance criterion"}
    rows=["Target ["+identifier+"] limits:"]
    for k in keys:
        if k in target:
            v=target[k]
            if isinstance(v,(dict,list,bool)): v=json.dumps(v,ensure_ascii=False,allow_nan=False,sort_keys=True)
            rows.append(labels.get(k,k.replace("_"," ").capitalize())+": "+str(v))
    return "\n".join(rows)
