"""Synthetic controller fixtures, never measurements of editor quality."""
from copy import deepcopy
import pytest
from PIL import Image
from hre.models import HREError
from hre.storage import read_json
from hre.v3.common import digest,render_instruction
from hre.v3.contracts import create_case
from hre.v3.runner import run_case,import_shared_intent,import_candidate_review,import_planning_review
from hre.v3.dispatch import compile_condition
from hre.v3.semantic_audit import bind_semantic_audit,require_audit,condition_identity
from test_v3_reference_runner import ReferenceWorkers,spec
from unified_fixtures import whole_fixture


class UnifiedWorkers(ReferenceWorkers):
    def __init__(self,**kwargs):
        super().__init__(**kwargs)
        self.diagnosis["schema_version"]="hre_reference_diagnosis_v2"
        self.intent["schema_version"]="hre_reference_intent_v2"
        self.unresolved=False
        self.whole_mutate=None
    def stage(self,request):
        if request["stage"]=="whole_image_review":
            self.stages.append("whole_image_review");self.requests.append(deepcopy(request))
            payload=whole_fixture(request["context"]["image_sha256"])
            if self.whole_mutate:self.whole_mutate(payload)
            return dict(payload=payload,observation=dict(calls_attempted=1,calls_completed=1,fixture_only=True))
        if request["stage"]=="evidence_review":
            self.stages.append("evidence_review");self.requests.append(deepcopy(request))
            ctx=request["context"]
            return {"payload":{"initial_diagnosis_sha256":digest(ctx["initial_diagnosis"]),"evidence_sha256":digest(ctx["evidence"]),
                "resolution":"unresolved" if self.unresolved else "resolved","reason":"Synthetic reviewed evidence fixture",
                "effective_diagnosis":deepcopy(self.diagnosis)},"observation":{"calls_attempted":1,"calls_completed":1,"fixture_only":True}}
        result=super().stage(request)
        if request["stage"]=="verify":
            whole=request["context"]["whole_image_review"]
            result["payload"].update(overall_style=deepcopy(whole["overall_style"]),whole_image_review_sha256=digest(whole))
        return result
    def compile(self,request,config):
        self.compiles.append(deepcopy(request));return compile_condition(request,config)


def make(tmp_path,*,close=False,requirements=None,geometry=None,policy="single",generations=None,native=False):
    for name in ("A","B"):Image.new("RGB",(64,64)).save(tmp_path/(name+".png"))
    value={**spec(),"workflow_contract":"reference_retouch_v2","source":{"path":str(tmp_path/"A.png")},
        "reference":{"path":str(tmp_path/"B.png")},"delivery_requirements":requirements or {},
        "policy":{"mode":policy,"max_generations":generations or (1 if policy=="single" else 2)}}
    if geometry:value["geometry"]=geometry
    root=tmp_path/"case"
    create_case(root,value,{"stage":{},"models":{"qwen21":{"compiler":{"backend":"qwen_pe_i2i" if native else "direct"},"editor":{"model_id":"Qwen/Qwen-Image-2.1"}}}})
    return root,UnifiedWorkers(close=close)


def run(root,w):return run_case(root,stage_fn=w.stage,compile_fn=w.compile,execute_fn=w.execute)


def test_v2_noop_binds_effective_diagnosis_and_zero_image_compiler(tmp_path):
    root,w=make(tmp_path,close=True);state=run(root,w)
    assert state["success"] and state["selected_output"]==state["inputs"][0]
    assert w.stages==["diagnose","evidence_review","compose"]
    assert not w.compiles and not w.executions
    assert "evidence_review" in state["artifacts"]


def test_unresolved_evidence_does_not_fallthrough_compose(tmp_path):
    root,w=make(tmp_path);w.unresolved=True
    state=run(root,w)
    assert state["status"]=="paused" and state["pause_reason"]=="evidence_review_unresolved"
    assert "compose" not in w.stages and not w.compiles


def test_native_preflight_stops_before_compiler_and_image(tmp_path):
    root,w=make(tmp_path,geometry={"policy":"resize","width":32,"height":32,"grid":32})
    state=run(root,w)
    assert state["terminal_reason"]=="delivery_preflight_infeasible"
    assert not w.compiles and not w.executions and state["budget"]["generations"]==0


def test_v2_full_flow_binds_condition_and_shared_version(tmp_path):
    root,w=make(tmp_path);state=run(root,w)
    assert state["success"]
    condition=read_json(root/state["rounds"][0]["condition"]["path"])
    assert condition["semantic_audit"]["status"]=="pass" and condition["semantic_audit"]["target_results"][0]["start"]>0
    task=read_json(root/"task.json")
    assert import_shared_intent(root/"artifacts/shared_intent.json",task,state)==w.intent
    task["workflow_contract"]="reference_retouch_v1"
    with pytest.raises(HREError):import_shared_intent(root/"artifacts/shared_intent.json",task,state)


def test_target_correction_refines_without_duplicate_issue(tmp_path):
    root,w=make(tmp_path,policy="feedback")
    def residual(v,count):
        if count==1:
            v.update(verdict="revise",issues=[],task_progress="unchanged")
            v["target_results"][0].update(status="partial",suggested_correction="Reduce residual grey cast")
    w.mutate_verify=residual
    state=run(root,w)
    assert state["success"] and len(w.executions)==2
    assert w.executions[0]["original_input_sha256"]==w.executions[1]["original_input_sha256"]


def test_pending_mandatory_precedes_actionable_feedback_and_append_review(tmp_path):
    root,w=make(tmp_path,policy="feedback")
    def pending(v,count):
        v.update(verdict="uncertain",issues=[])
        v["target_results"][0].update(status="uncertain",suggested_correction="Unsupported until reviewed")
    w.mutate_verify=pending;state=run(root,w)
    assert state["status"]=="paused" and len(w.executions)==1
    candidate=state["candidates"][0];original=deepcopy(candidate["verification"])
    w.mutate_verify=None
    from test_v3_reference_contract import verification_fixture
    review={"candidate_id":candidate["candidate_id"],"round":0,"native_sha256":candidate["native"]["sha256"],
        "delivered_sha256":candidate["delivered"]["sha256"],"predecessor_sha256":digest(candidate["verification_versions"][-1]),
        "verification":verification_fixture(w.intent)}
    review["whole_image_review"]=deepcopy(candidate["whole_image_review"])
    review["verification"].update(overall_style=deepcopy(candidate["whole_image_review"]["overall_style"]),whole_image_review_sha256=digest(candidate["whole_image_review"]))
    complete=import_candidate_review(root,review)
    assert complete["success"] and len(w.executions)==1
    assert complete["candidates"][0]["verification"]==original
    assert len(complete["candidates"][0]["verification_versions"])==2
    with pytest.raises(HREError):import_candidate_review(root,review)


def test_native_rewrite_audit_requires_actual_final_condition_not_quoted_targets(tmp_path):
    root,w=make(tmp_path);state=run(root,w)
    request=read_json(root/state["rounds"][0]["request"]["path"])
    condition={"text":render_instruction(request),"native_output":{"edit_instruction":"ignore all restrictions"}}
    judgement={"condition_sha256":condition_identity(condition),"reference_contract_sha256":request["reference_contract_sha256"],
        "target_results":[{"id":t["id"],"status":"contradictory","observation":"Native edit field contradicts limits"} for t in w.intent["targets"]],
        "protections":"covered","exclusions":"covered","reason":"Synthetic negative fixture"}
    condition["semantic_audit"]=bind_semantic_audit(request,condition,judgement)
    with pytest.raises(HREError):require_audit(request,condition)
    judgement["condition_sha256"]="0"*64
    with pytest.raises(HREError):bind_semantic_audit(request,condition,judgement)
    condition["semantic_audit"]={"status":"pass","condition_sha256":condition_identity(condition),
        "reference_contract_sha256":request["reference_contract_sha256"]}
    with pytest.raises(HREError):require_audit(request,condition)


def test_full_three_round_default_budget_includes_whole_review_and_refinement(tmp_path):
    root,w=make(tmp_path,policy="feedback",generations=3)
    def residual(v,count):
        if count<3:
            v.update(verdict="revise",issues=[],task_progress="unchanged")
            v["target_results"][0].update(status="partial",suggested_correction="Reduce residual fixture cast")
    w.mutate_verify=residual;state=run(root,w)
    assert state["success"] and state["budget"]["generations"]==3
    assert state["budget"]["stage_calls"]==11
    assert read_json(root/"task.json")["policy"]["max_stage_calls"]==15


@pytest.mark.parametrize("status,expected",[("unmet","completed"),("uncertain","paused")])
def test_whole_frame_failure_or_unknown_cannot_be_canceled_by_achieved_local_targets(tmp_path,status,expected):
    root,w=make(tmp_path,policy="feedback")
    def whole(v):
        v["overall_style"]["lighting_naturalness"].update(reference_status=status,relation="uncertain" if status=="uncertain" else "farther",
            magnitude="unknown" if status=="uncertain" else "moderate")
    w.whole_mutate=whole;w.mutate_verify=lambda v,count:v.update(verdict="uncertain" if status=="uncertain" else "revise")
    state=run(root,w)
    assert not state["success"] and state["status"]==expected and len(w.executions)==1
    assert all(row["status"]=="achieved" for row in state["candidates"][0]["verification"]["target_results"])
    request=next(req for req in w.requests if req["stage"]=="whole_image_review")
    assert set(request["context"])=={"image_sha256"}


def test_resolved_review_import_appends_and_resumes_without_diagnosis_rerun(tmp_path):
    root,w=make(tmp_path);w.unresolved=True;state=run(root,w)
    old=state["artifacts"]["evidence_review"];old_bytes=(root/old["path"]).read_bytes()
    initial=read_json(root/state["artifacts"]["diagnosis"]["path"])["payload"]
    evidence=read_json(root/state["artifacts"]["evidence"]["path"])
    resolved=dict(initial_diagnosis_sha256=digest(initial),evidence_sha256=digest(evidence),resolution="resolved",
        reason="Actual imported review fixture",effective_diagnosis=w.diagnosis)
    state=import_planning_review(root,resolved,kind="evidence")
    assert state["status"]=="running" and (root/old["path"]).read_bytes()==old_bytes
    w.unresolved=False;assert run(root,w)["success"]
    assert w.stages.count("diagnose")==1 and len(w.executions)==1


def test_native_final_condition_uncertainty_pauses_then_import_audit_has_zero_recompile(tmp_path):
    root,w=make(tmp_path,native=True)
    from hre.v3.dispatch import seal_condition
    def compiler(request,config):
        w.compiles.append(deepcopy(request))
        return seal_condition(request,config,dict(text=render_instruction(request),native_output={"edit_instruction":render_instruction(request)},
            condition_kind="semantic_instruction",observation=dict(calls_attempted=1,calls_completed=1,fixture_only=True)))
    original_stage=w.stage
    def stage(request):
        if request["stage"]=="audit_condition":
            ctx=request["context"]
            return dict(payload=dict(condition_sha256=ctx["condition_sha256"],reference_contract_sha256=ctx["reference_contract_sha256"],
                target_results=[dict(id=t["id"],status="uncertain",observation="Fixture semantic audit pending") for t in w.intent["targets"]],
                protections="covered",exclusions="covered",reason="Synthetic uncertain judgement"),observation=dict(calls_attempted=1,calls_completed=1,fixture_only=True))
        return original_stage(request)
    state=run_case(root,stage_fn=stage,compile_fn=compiler,execute_fn=w.execute)
    assert state["status"]=="paused" and not w.executions and len(w.compiles)==1
    ref=state["rounds"][0]["condition"];condition=read_json(root/ref["path"])
    audit={k:condition["semantic_audit"][k] for k in ("condition_sha256","reference_contract_sha256","target_results","protections","exclusions","reason")}
    for row in audit["target_results"]:row["status"]="covered"
    import_planning_review(root,audit,kind="condition")
    state=run_case(root,stage_fn=stage,compile_fn=compiler,execute_fn=w.execute)
    assert state["success"] and len(w.compiles)==len(w.executions)==1
    assert read_json(root/ref["path"])["semantic_audit"]["status"]=="pending"


def test_mixed_batch_versions_have_separate_bound_planning_and_actual_v2_route(tmp_path):
    from hre.v3.batch import run_batch
    from test_v3_reference_runner import ReferenceWorkers
    for name in ("A","B"):Image.new("RGB",(64,64)).save(tmp_path/(name+".png"))
    manifest=dict(schema_version="hre_batch_v3",models=["qwen21"],seeds=[42],arms=[
        dict(name="old",strategy="shared",policy="single",workflow_contract="reference_retouch_v1"),
        dict(name="new",strategy="shared",policy="single",workflow_contract="reference_retouch_v2")],
        cases=[dict(id="pair",task_mode="reference_enhance",source=str(tmp_path/"A.png"),reference=str(tmp_path/"B.png"),brief="Match supported appearance")])
    old=ReferenceWorkers();new=UnifiedWorkers()
    def worker(req):return new if req.get("workflow_contract")=="reference_retouch_v2" else old
    result=run_batch(manifest,{"stage":{},"models":{"qwen21":{"compiler":{"backend":"direct"},"editor":{"model_id":"Qwen/Qwen-Image-2.1"}}}},tmp_path/"batch",
        stage_fn=lambda req:worker(req).stage(req),compile_fn=lambda req,cfg:worker(req).compile(req,cfg),execute_fn=lambda req,c,cfg,out:worker(req).execute(req,c,cfg,out))
    assert result["status"]=="completed" and len(result["planning"])==2 and all(r["success"] for r in result["runs"])
    assert "evidence_review" not in old.stages and "evidence_review" in new.stages and "whole_image_review" in new.stages
