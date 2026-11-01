"""Delivery refers to native content dimensions, never a scaled display preview."""
from .contracts import size, validate_requirements


def _minimum(source_size,requirements):
    source=size(source_size,"source_size"); validate_requirements(requirements)
    minimum=list(requirements.get("minimum_native_size",[1,1]))
    if requirements.get("require_native_source_resolution",True): minimum=[max(a,b) for a,b in zip(minimum,source)]
    return minimum


def assess_delivery(source_size, native_size, requirements, *, detail="uncertain", geometry_valid=True) -> dict:
    minimum=_minimum(source_size,requirements)
    if detail not in {"pass","fail","uncertain"} or type(geometry_valid) is not bool: raise ValueError("Invalid delivery observation")
    native=size(native_size,"native_size") if native_size is not None else None
    resolution="uncertain" if native is None else "pass" if all(a>=b for a,b in zip(native,minimum)) else "fail"
    required=requirements.get("require_detail_pass",False)
    status="fail" if not geometry_valid or resolution=="fail" or required and detail=="fail" else "uncertain" if resolution=="uncertain" or required and detail!="pass" else "pass"
    return dict(status=status,minimum_native_size=minimum,native_size=native,native_resolution=resolution,
        detail_preservation=detail,detail_required=required,geometry="pass" if geometry_valid else "fail",**{"pass":status=="pass"})


def preflight(source_size, planned_size, requirements, *, capability_known=True) -> dict:
    minimum=_minimum(source_size,requirements)
    if type(capability_known) is not bool: raise ValueError("capability_known must be boolean")
    planned=size(planned_size,"planned_size") if planned_size is not None else None
    status="unknown" if not capability_known or planned is None else "feasible" if all(a>=b for a,b in zip(planned,minimum)) else "infeasible"
    return dict(status=status,minimum_native_size=minimum,planned_size=planned,**{"pass":status=="feasible"})
