"""Independent-review blocker regressions using synthetic local files only."""
from copy import deepcopy
from pathlib import Path
import pytest
from hre.reference_core import study
from hre.v3.runner import import_candidate_review
from hre.v3.common import digest
from test_reference_study import specification,result_spec,rating_spec
from test_v3_reference_v2 import make,run


@pytest.mark.parametrize("reverse",[False,True])
@pytest.mark.parametrize("field",["relative_to_A","targets","protections","artifact_checks","overall"])
def test_all_decision_relevant_disagreements_are_unknown_until_all_rating_adjudication(tmp_path,reverse,field):
    root=tmp_path/"study";spec=specification(tmp_path);plan=study.build_study(root,spec);r=plan["payload"]["runs"][0]
    result=study.import_result(root,result_spec(plan,r,Path(spec["pairs"][0]["reference"])))
    first=rating_spec(result,r);second=rating_spec(result,r,"rating2","reviewer2")
    if field=="relative_to_A":second[field]="worse"
    elif field=="overall":first[field]["color"]="partial";second[field]["color"]="unmet"
    elif field=="targets":first[field][0]["status"]="partial";second[field][0]["status"]="unmet"
    else:first[field][0]["status"]="fail";second[field][1]["status"]="fail"
    records=[study.import_rating(root,x) for x in ([second,first] if reverse else [first,second])]
    row=study.summarize(root)["runs"][0]
    assert row["task_success"] is None and row["effective_edit_success"] is None
    assert row["rating_conflict"] and field in row["rating_conflict_fields"]
    with pytest.raises(ValueError):study.adjudicate(root,dict(adjudication_id="bad",run_id=r["run_id"],result_hash=result["content_hash"],
        rating_hashes=[records[0]["content_hash"]],selected_rating_hash=records[0]["content_hash"],reason="Incomplete adjudication"))
    study.adjudicate(root,dict(adjudication_id="a1",run_id=r["run_id"],result_hash=result["content_hash"],
        rating_hashes=[x["content_hash"] for x in records],selected_rating_hash=records[0]["content_hash"],reason="Explicit full independent adjudication fixture"))
    assert study.summarize(root)["runs"][0]["task_success"] is not None


def native_detail(source,native,result_hash,evaluation_hash,selected_sha256,status="pass",review_id="detail1"):
    return dict(schema_version="hre_native_detail_review_v1",review_id=review_id,
        source_sha256=source["sha256"],native_sha256=native["sha256"],native_size=native["native_size"],
        result_hash=result_hash,evaluation_hash=evaluation_hash,selected_sha256=selected_sha256,
        reviewer=dict(reviewer_id="detail_reviewer",independence="independent",prior_exposure="Synthetic native-file fixture only"),
        display=dict(method="native_pixels_1_to_1",note="Inspected original native file; no enlarged preview claim"),
        status=status,confidence="high",observation="Synthetic independent native-detail observation, no model-quality claim")


@pytest.mark.parametrize("status,expected",[("pass",True),("fail",False),("unknown",None)])
@pytest.mark.parametrize("role",["G","S"])
def test_required_study_detail_has_a_bound_independent_completion_path(tmp_path,status,expected,role):
    root=tmp_path/"study";spec=specification(tmp_path);spec["pairs"][0]["evaluation"]["semantics"]["delivery_requirements"]["require_detail_pass"]=True
    plan=study.build_study(root,spec);r=plan["payload"]["runs"][0];pair=plan["payload"]["pairs"][0]
    path=Path(spec["pairs"][0]["source" if role=="S" else "reference"])
    result=study.import_result(root,result_spec(plan,r,path,role));rating=rating_spec(result,r)
    rating["native_detail"]=native_detail(pair["source"],result["payload"]["candidate"],result["content_hash"],r["evaluation_hash"],result["payload"]["candidate"]["sha256"],status)
    study.import_rating(root,rating);row=study.summarize(root)["runs"][0]
    assert row["task_success"] is expected and row["delivery"]["detail_preservation"]==("uncertain" if status=="unknown" else status)
    assert row["effective_edit_success"] is (False if role=="S" else expected)


@pytest.mark.parametrize("wrong",["native_sha256","result_hash","evaluation_hash","source_sha256","selected_sha256"])
def test_detail_rejects_stale_or_wrong_native_result_evaluation_bindings(tmp_path,wrong):
    root=tmp_path/"study";spec=specification(tmp_path);plan=study.build_study(root,spec);r=plan["payload"]["runs"][0];pair=plan["payload"]["pairs"][0]
    result=study.import_result(root,result_spec(plan,r,Path(spec["pairs"][0]["reference"])));rating=rating_spec(result,r)
    rating["native_detail"]=native_detail(pair["source"],result["payload"]["candidate"],result["content_hash"],r["evaluation_hash"],result["payload"]["candidate"]["sha256"])
    rating["native_detail"][wrong]="0"*64
    with pytest.raises(ValueError):study.import_rating(root,rating)


def test_native_detail_disagreement_requires_explicit_all_rating_adjudication(tmp_path):
    root=tmp_path/"study";spec=specification(tmp_path);spec["pairs"][0]["evaluation"]["semantics"]["delivery_requirements"]["require_detail_pass"]=True
    plan=study.build_study(root,spec);r=plan["payload"]["runs"][0];pair=plan["payload"]["pairs"][0]
    result=study.import_result(root,result_spec(plan,r,Path(spec["pairs"][0]["reference"])));ratings=[]
    for n,status in enumerate(("pass","fail")):
        rating=rating_spec(result,r,"rating"+str(n),"reviewer"+str(n))
        rating["native_detail"]=native_detail(pair["source"],result["payload"]["candidate"],result["content_hash"],r["evaluation_hash"],result["payload"]["candidate"]["sha256"],status,"detail"+str(n))
        ratings.append(study.import_rating(root,rating))
    row=study.summarize(root)["runs"][0]
    assert row["task_success"] is None and row["rating_conflict_fields"]==["native_detail"]
    study.adjudicate(root,dict(adjudication_id="a1",run_id=r["run_id"],result_hash=result["content_hash"],rating_hashes=[x["content_hash"] for x in ratings],
        selected_rating_hash=ratings[1]["content_hash"],reason="Explicitly uphold independent fail after reviewing both native-detail observations"))
    assert study.summarize(root)["runs"][0]["task_success"] is False


def test_blind_rating_can_supply_native_detail_without_method_identity(tmp_path):
    root=tmp_path/"study";spec=specification(tmp_path);spec["pairs"][0]["evaluation"]["semantics"]["delivery_requirements"]["require_detail_pass"]=True
    plan=study.build_study(root,spec);r=plan["payload"]["runs"][0]
    result=study.import_result(root,result_spec(plan,r,Path(spec["pairs"][0]["reference"])));packet=study.prepare_blind(root,tmp_path/"blind")
    import json
    content=json.loads(Path(packet["packets"][0]).read_text(encoding="utf-8"));rating=rating_spec(result,r)
    binding=content["native_detail_binding"]
    rating["native_detail"]={**native_detail(dict(sha256=binding["source_sha256"]),dict(sha256=binding["native_sha256"],native_size=binding["native_size"]),
        binding["result_hash"],binding["evaluation_hash"],binding["selected_sha256"])}
    for key in ("run_id","result_hash","evaluation_hash"):del rating[key]
    study.import_blind_rating(root,tmp_path/"blind","packet_0001",rating)
    assert study.summarize(root)["runs"][0]["task_success"] is True


@pytest.mark.parametrize("mutation",[lambda d:d.update(schema_version="legacy_detail"),lambda d:d.update(native_size=[True,16]),
    lambda d:d.pop("result_hash"),lambda d:d["display"].update(method="upsampled_preview")])
def test_detail_schema_does_not_accept_unbound_old_or_preview_booleans(tmp_path,mutation):
    root=tmp_path/"study";spec=specification(tmp_path);plan=study.build_study(root,spec);r=plan["payload"]["runs"][0];pair=plan["payload"]["pairs"][0]
    result=study.import_result(root,result_spec(plan,r,Path(spec["pairs"][0]["reference"])));rating=rating_spec(result,r)
    rating["native_detail"]=native_detail(pair["source"],result["payload"]["candidate"],result["content_hash"],r["evaluation_hash"],result["payload"]["candidate"]["sha256"])
    mutation(rating["native_detail"])
    with pytest.raises(ValueError):study.import_rating(root,rating)


@pytest.mark.parametrize("conclusion",["accept","revise","uncertain","reject"])
def test_historical_review_never_changes_current_terminal_scheduler(tmp_path,conclusion):
    root,w=make(tmp_path,policy="feedback",generations=3)
    def residual(v,count):
        if count==1:
            v.update(verdict="revise",issues=[],task_progress="unchanged")
            v["target_results"][0].update(status="partial",suggested_correction="Reduce fixture residual")
    w.mutate_verify=residual;before=run(root,w);candidate=before["candidates"][0]
    v=deepcopy(before["candidates"][1]["verification"] if conclusion=="accept" else candidate["verification"])
    v.pop("whole_image_review",None);v["verdict"]=conclusion
    v.update(whole_image_review_sha256=digest(candidate["whole_image_review"]),overall_style=deepcopy(candidate["whole_image_review"]["overall_style"]))
    if conclusion=="uncertain":v["target_results"][0]["status"]="uncertain"
    review=dict(candidate_id=candidate["candidate_id"],round=0,native_sha256=candidate["native"]["sha256"],delivered_sha256=candidate["delivered"]["sha256"],
        predecessor_sha256=digest(candidate["verification_versions"][-1]),whole_image_review=deepcopy(candidate["whole_image_review"]),verification=v)
    keys=("status","success","selected_candidate_id","round","phase","terminal_reason","budget")
    changed=import_candidate_review(root,review)
    assert {k:changed.get(k) for k in keys}=={k:before.get(k) for k in keys}
    assert changed["candidates"][0]["verification_versions"][0]==candidate["verification_versions"][0]
    assert len(changed["candidates"][0]["verification_versions"])==2
    resumed=run(root,w)
    assert resumed["success"] and resumed["selected_candidate_id"]==before["selected_candidate_id"] and len(w.executions)==2


@pytest.mark.parametrize("conclusion",["revise","uncertain","reject"])
def test_current_review_schedules_only_its_exact_candidate_and_preserves_budgets(tmp_path,conclusion):
    root,w=make(tmp_path,policy="feedback",generations=3);before=run(root,w);candidate=before["candidates"][0]
    v=deepcopy(candidate["verification"]);v.pop("whole_image_review",None);v["verdict"]=conclusion
    if conclusion in {"revise","uncertain"}:
        v["target_results"][0].update(status="partial" if conclusion=="revise" else "uncertain",suggested_correction="Correct actual reviewed residual")
    review=dict(candidate_id=candidate["candidate_id"],round=0,native_sha256=candidate["native"]["sha256"],delivered_sha256=candidate["delivered"]["sha256"],
        predecessor_sha256=digest(candidate["verification_versions"][-1]),whole_image_review=deepcopy(candidate["whole_image_review"]),verification=v)
    changed=import_candidate_review(root,review)
    assert changed["budget"]==before["budget"] and len(w.executions)==1
    assert not changed["success"]
    if conclusion=="revise":
        assert changed["phase"]=="refine" and changed["status"]=="running"
        resumed=run(root,w)
        assert resumed["success"] and len(w.executions)==2
        assert resumed["candidates"][0]["feedback"]["candidate_id"]==candidate["candidate_id"]
    elif conclusion=="uncertain":assert changed["status"]=="paused" and run(root,w)==changed
    else:assert changed["status"]=="completed" and len(w.executions)==1
