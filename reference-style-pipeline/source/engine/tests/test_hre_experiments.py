import json
from pathlib import Path
from PIL import Image
import pytest
from hre.assets import canonicalize_image
from hre.experiments import freeze_run, export_blind_evaluation, summarize_evaluation
from hre.storage import read_json, write_json
from hre.models import file_sha256, sha256_bytes


def run_fixture(tmp_path, cases=2, same_group=False):
    records=[]
    for i in range(cases):
        root=tmp_path / f"input{i}"; root.mkdir()
        assets=[]
        for role, color in [("prediction", "red"),("reference", "blue")]:
            source=root/(role+".source.png"); Image.new("RGB", (12, 10), color).save(source)
            assets.append(canonicalize_image(source,root/(role+".png"),role,{"assume_srgb":True},asset_id=role))
        records.append({"case_id":f"case{i}","case_revision":0,"scene_group_id":"g0" if same_group else f"g{i}","case_root":root.name,"split":"validation","assets":assets,"ready_for_enrollment":False,"comparability":{"reference_usable":"usable","reference_limitations":["Synthetic unaligned color-block fixture; no real quality evidence."]}})
    manifest={"schema_version":"ref_enhance_v1","manifest_kind":"pilot","allow_unverified":True,"reference_is_pixel_ground_truth":False,"cases":records,"run_linkage":{"selected_profile_ids":["direct_ref","agent_single"]}}
    m=tmp_path/"manifest.json";write_json(m,manifest)
    profile=tmp_path/"profile.json"
    profile.write_bytes(Path("docs/reference_enhancement/v1_20261013/config/experiment_profiles.json").read_bytes())
    freeze_run(m,profile,tmp_path/"run")
    return tmp_path/"run", m, profile


def test_freeze_real_files_profiles_and_explicit_pilot_limitations(tmp_path):
    root,_,_=run_fixture(tmp_path)
    run=read_json(root/"run.json")
    assert run["formal"] is False and run["limitations"]
    assert len(read_json(root/"planned_outcomes.json")["outcomes"])==4
    assert read_json(root/"runtime_configs/direct_ref.json")["max_generations"]==1
    assert (root/"frozen_inputs/case0/prediction.png").is_file()
    assert (root/"case_manifests/case0.json").is_file()
    assert (root/"runtime_configs/case0/direct_ref.json").is_file()
    assert read_json(root/"run.json")["prompt_files"]
    (root/"runtime_configs/direct_ref.json").write_text('{}')
    with pytest.raises(ValueError):export_blind_evaluation(root,tmp_path/"bad_blind")


@pytest.mark.parametrize("mutation",["example","group_leak","pilot_test","gt","hash"])
def test_freeze_rejects_example_leak_gt_and_corruption(tmp_path,mutation):
    _,m,p=run_fixture(tmp_path)
    manifest=read_json(m)
    if mutation=="example":manifest["example_only"]=True
    if mutation=="group_leak":manifest["cases"][1].update(scene_group_id="g0",split="dev")
    if mutation=="pilot_test":manifest["cases"][0].update(split="test",pilot_stage="R2")
    if mutation=="gt":manifest["reference_is_pixel_ground_truth"]=True
    if mutation=="hash":manifest["cases"][0]["assets"][0]["sha256"]="0"*64
    write_json(m,manifest)
    with pytest.raises(Exception):freeze_run(m,p,tmp_path/"invalid")


def completed_outcomes(root):
    plan=read_json(root/"planned_outcomes.json")
    manifest=read_json(root/"manifest.json")
    bycase={c["case_id"]:c for c in manifest["cases"]}
    for o in plan["outcomes"]:
        o.update(status="completed",selected_asset=bycase[o["case_id"]]["assets"][0],selected_asset_root=f"frozen_inputs/{o['case_id']}",workflow_success=False)
    write_json(root/"planned_outcomes.json",plan)


def test_blind_removes_metadata_mapping_external_and_failure_itt(tmp_path):
    root,_,_=run_fixture(tmp_path);completed_outcomes(root)
    plan=read_json(root/"planned_outcomes.json");plan["outcomes"][0].update(status="failed",selected_asset=None)
    write_json(root/"planned_outcomes.json",plan)
    package=tmp_path/"blind"
    export_blind_evaluation(root,package)
    assert not (package/"mapping.json").exists()
    blind=read_json(package/"manifest.json")
    serialized=json.dumps(blind)
    assert "agent_single" not in serialized and "direct_ref" not in serialized
    assert "prompt" not in serialized and "verifier" not in serialized and "case_root" not in serialized
    mapping=read_json(root/"private/blind_mapping.json")
    ratings={"frozen":True,"raters":[{"rater_id":r,"independent":True,"participated_cases":[]} for r in ["r1","r2"]],"ratings":[]}
    for item in mapping["items"]:
        for r in ["r1","r2"]:
            ratings["ratings"].append({"code":item["code"],"rater_id":r,"style_direction":"improved","content_preservation":"pass","critical_defects":[],"comparability":"usable"})
    rp=tmp_path/"ratings.json";write_json(rp,ratings)
    summary=summarize_evaluation(root,rp)
    assert summary["arms"]["direct_ref"]["denominator"]==2
    # Delivered A is unchanged by definition, even if reviewers claim improvement.
    assert summary["arms"]["direct_ref"]["joint_success"]==0
    assert summary["arms"]["direct_ref"]["failures"]==1
    assert summary["comparisons"]["single_pass_agent_instruction_gain"]["bootstrap_replicates"]==10000
    ratings["raters"][0]["participated_cases"]=["case0"]
    write_json(rp,ratings)
    with pytest.raises(ValueError):summarize_evaluation(root,rp)


def test_group_weighting_missing_ratings_and_no_wilson_for_multicase_groups(tmp_path):
    root,_,_=run_fixture(tmp_path,same_group=True);completed_outcomes(root)
    export_blind_evaluation(root,tmp_path/"blind")
    rp=tmp_path/"ratings.json";write_json(rp,{"frozen":True,"raters":[],"ratings":[]})
    summary=summarize_evaluation(root,rp)
    assert summary["arms"]["agent_single"]["n_groups"]==1
    assert summary["arms"]["agent_single"]["wilson_interval"] is None
    assert summary["arms"]["agent_single"]["missing_ratings"]==2
    assert summary["arms"]["agent_single"]["joint_success"]==0


def formalize(m):
    data=read_json(m);data.update(manifest_kind="formal",allow_unverified=False,ready_for_enrollment=True)
    for case in data["cases"]:
        root=m.parent/case["case_root"]
        def record(name, text):
            p=root/name;p.write_text(text);return {"path":name,"sha256":file_sha256(p)}
        raw=record("capture.raw","synthetic raw fixture")
        a,b=case["assets"]
        case["source_files"]={"prediction_source_raw":raw,"prediction_original":a["source_file"],"reference_original":dict(b["source_file"],device_verification_status="observed",camera_model_observed="fixture camera")}
        checkpoint=record("checkpoint.bin","fixture checkpoint");environment=record("environment.json",'{}')
        command="fixture_predict capture.raw"
        case["baseline_provenance"]={"provenance_complete":True,"repository_url":"https://example.org/fixture","repository_commit":"a"*40,"working_tree_dirty":False,"predict_command_observed":command,"predict_command_sha256":sha256_bytes(command.encode()),"predict_working_directory":"fixture","prediction_time":"2026-10-13T00:00:00Z","checkpoint_path":checkpoint["path"],"checkpoint_sha256":checkpoint["sha256"],"environment_manifest_path":environment["path"],"environment_manifest_sha256":environment["sha256"],"input_raw_sha256":raw["sha256"],"prediction_output_sha256":a["source_file"]["sha256"]}
        case["canonicalization"]={"status":"complete","destination_profile":"sRGB","tool_name":"fixture","tool_version":"1","parameters_sha256":sha256_bytes(b"parameters"),"prediction":{"source_profile_explained":True},"reference":{"source_profile_explained":True}}
        case["comparability"]={"annotated_before_any_arm_output":True,"reference_usable":"usable","annotator":"fixture","annotated_at":"2026-10-13T00:00:00Z","rules_version":"v1","comparable_rendering_dimensions":["neutral_color_balance"]}
        case["comparability"]["ROI_pairs"]=[{"ROI_pair_id":"roi1","prediction_xywh":[.1,.2,.3,.4],"reference_xywh":[.2,.3,.4,.2],"valid_for_auxiliary_statistics":True,"matched_semantics_observed":True,"comparable_illumination_observed":True,"occlusion_free_observed":True,"semantic_composition_comparable_observed":True}]
        report=record("audit.json",'{}')
        case["leakage_audit"]={"status":"passed","group_association_review_complete":True,"descendant_split_inheritance_verified":True,"same_raw_or_burst_across_splits":False,"reference_or_candidates_used_for_test_tuning":False,"audit_report_path":report["path"],"audit_report_sha256":report["sha256"]}
        case["enrollment"]={"approved_by":"fixture","approved_at":"2026-10-13T00:00:00Z","required_missing_items":[],"preflight_report_path":report["path"],"preflight_report_sha256":report["sha256"]}
        case["ready_for_enrollment"]=True
    near=m.parent/"near_duplicates.json";near.write_text('{}')
    data["split_protocol"]={"near_duplicate_check":{"status":"passed","report_path":near.name,"report_sha256":file_sha256(near)}}
    write_json(m,data)


def test_formal_provenance_is_checked_and_near_duplicate_report_copied(tmp_path):
    _,m,p=run_fixture(tmp_path);formalize(m)
    destination=tmp_path/"formal"
    freeze_run(m,p,destination)
    assert read_json(destination/"run.json")["formal"] is True
    assert (destination/"provenance/near_duplicates.json").is_file()
    roi=read_json(destination/"runtime_configs/case0/agent_single.json")["roi_manifest"][0]
    assert roi["prediction"]==pytest.approx([.1,.2,.4,.6])
    assert roi["reference"]==pytest.approx([.2,.3,.6,.5])
    assert roi["comparability"]=="comparable"
    data=read_json(m);data["cases"][0]["baseline_provenance"]["predict_command_observed"]="changed"
    write_json(m,data)
    with pytest.raises(ValueError,match="command hash"):freeze_run(m,p,tmp_path/"bad")


def test_case_id_path_traversal_and_changed_mapping_rejected(tmp_path):
    root,m,p=run_fixture(tmp_path)
    data=read_json(m);data["cases"][0]["case_id"]="../escape"
    write_json(m,data)
    with pytest.raises(Exception):freeze_run(m,p,tmp_path/"bad")
    completed_outcomes(root);export_blind_evaluation(root,tmp_path/"blind")
    path=root/"private/blind_mapping.json";mapping=read_json(path)
    mapping["items"][0]["arm_id"]="evil"
    write_json(path,mapping)
    rp=tmp_path/"ratings.json";write_json(rp,{"frozen":True,"raters":[],"ratings":[]})
    with pytest.raises(ValueError):summarize_evaluation(root,rp)


def test_manual_outcome_rejects_candidate_bound_to_wrong_inputs(tmp_path):
    root,_,_=run_fixture(tmp_path,cases=1)
    plan=read_json(root/"planned_outcomes.json")
    outcome=plan["outcomes"][0]
    asset_root=root/outcome["input_case_root"]
    source=asset_root/"generated_source.png";Image.new("RGB",(12,10),"green").save(source)
    binding={"case_id":"case0","case_revision":0,"task_id":"t","round":0,"generation_id":"g","prediction_sha256":"a"*64,"reference_sha256":"b"*64}
    generated=canonicalize_image(source,asset_root/"generated.png","candidate",{"assume_srgb":True},asset_id="generated",candidate_binding=binding)
    outcome.update(status="completed",selected_asset=generated,selected_asset_root=outcome["input_case_root"])
    write_json(root/"planned_outcomes.json",plan)
    with pytest.raises(ValueError,match="input binding"):export_blind_evaluation(root,tmp_path/"blind")


def test_actual_generated_success_group_weighted_and_failed_attempt_retained(tmp_path):
    root,_,_=run_fixture(tmp_path,cases=3)
    # Two correlated pairs in g0 and one independent pair in g2.
    manifest=read_json(root/"manifest.json")
    manifest["cases"][1]["scene_group_id"]="g0"
    # Re-freeze from source manifest to keep registered identities coherent.
    source=read_json(tmp_path/"manifest.json");source["cases"][1]["scene_group_id"]="g0"
    write_json(tmp_path/"manifest.json",source)
    root=tmp_path/"weighted"
    freeze_run(tmp_path/"manifest.json",tmp_path/"profile.json",root)
    plan=read_json(root/"planned_outcomes.json")
    for o in plan["outcomes"]:
        asset_root=root/o["input_case_root"]
        image=asset_root/"generation_source.png";Image.new("RGB",(12,10),"green").save(image)
        inputs=next(c for c in source["cases"] if c["case_id"]==o["case_id"])["assets"]
        binding={"case_id":o["case_id"],"case_revision":0,"task_id":"t","round":0,"generation_id":"g","prediction_sha256":inputs[0]["sha256"],"reference_sha256":inputs[1]["sha256"]}
        generated=canonicalize_image(image,asset_root/(o["arm_id"]+".png"),"candidate",{"assume_srgb":True},asset_id="generated",candidate_binding=binding)
        o.update(status="completed",selected_asset=generated,selected_asset_root=o["input_case_root"])
        register_external_contract(root,o)
    write_json(root/"planned_outcomes.json",plan)
    export_blind_evaluation(root,tmp_path/"blind")
    mapping=read_json(root/"private/blind_mapping.json")
    ratings={"frozen":True,"raters":[{"rater_id":r,"independent":True,"participated_cases":[]} for r in ["r1","r2"]],"ratings":[]}
    for item in mapping["items"]:
        success=item["arm_id"]=="agent_single" and item["case_id"]!="case2"
        for r in ["r1","r2"]:
            ratings["ratings"].append({"code":item["code"],"rater_id":r,"style_direction":"improved" if success else "unchanged","content_preservation":"pass","critical_defects":[],"comparability":"usable"})
    rp=tmp_path/"ratings.json";write_json(rp,ratings)
    summary=summarize_evaluation(root,rp)
    arm=summary["arms"]["agent_single"]
    assert arm["joint_success"]==2
    assert arm["scene_equal_weight_rate"]==.5 and arm["case_weight_rate"]==pytest.approx(2/3)
    assert arm["wilson_interval"] is None
    comparison=summary["comparisons"]["single_pass_agent_instruction_gain"]
    assert comparison["estimate"]==.5 and comparison["ci95"]==[0.,1.]
    assert arm["cost_unknown_fraction"]==1.
    ratings["ratings"][0]["style_direction"]="worse";write_json(rp,ratings)
    with pytest.raises(ValueError,match="ratings changed"):summarize_evaluation(root,rp)


@pytest.mark.parametrize("role", ["reference", "unrelated_prediction"])
def test_review_rejects_wrong_delivered_role_or_prediction_identity(tmp_path, role):
    root,_,_=run_fixture(tmp_path,cases=1)
    plan=read_json(root/"planned_outcomes.json");o=plan["outcomes"][0]
    if role=="reference": selected=read_json(root/"manifest.json")["cases"][0]["assets"][1]
    else:
        src=root/o["input_case_root"]/"other.source.png";Image.new("RGB",(12,10),"green").save(src)
        selected=canonicalize_image(src,src.with_name("other.png"),"prediction",{"assume_srgb":True},asset_id="other")
    o.update(status="completed",selected_asset=selected,selected_asset_root=o["input_case_root"])
    write_json(root/"planned_outcomes.json",plan)
    with pytest.raises(ValueError):export_blind_evaluation(root,tmp_path/"blind")


def test_review_anchor_root_cannot_substitute_mutable_input_hint(tmp_path):
    root,_,_=run_fixture(tmp_path,cases=1);completed_outcomes(root)
    alternative=root/"alternative";alternative.mkdir()
    Image.new("RGB",(12,10),"yellow").save(alternative/"prediction.png")
    Image.new("RGB",(12,10),"cyan").save(alternative/"reference.png")
    plan=read_json(root/"planned_outcomes.json")
    for o in plan["outcomes"]:o["input_case_root"]="alternative"
    write_json(root/"planned_outcomes.json",plan)
    export_blind_evaluation(root,tmp_path/"blind")
    blind=read_json(tmp_path/"blind/manifest.json");expected=read_json(root/"manifest.json")["cases"][0]["assets"][0]["sha256"]
    assert all(file_sha256(tmp_path/"blind"/i["images"]["A"])==expected for i in blind["items"])


@pytest.mark.parametrize("role",["prediction", "reference"])
def test_review_formal_declared_original_matches_actual_asset_source(tmp_path,role):
    _,m,p=run_fixture(tmp_path,cases=1);formalize(m);data=read_json(m)
    c=data["cases"][0]
    if role=="prediction":
        c["source_files"]["prediction_original"]=c["source_files"]["reference_original"]
        c["baseline_provenance"]["prediction_output_sha256"]=c["source_files"]["reference_original"]["sha256"]
    else:
        c["source_files"]["reference_original"].update(path=c["source_files"]["prediction_original"]["path"],sha256=c["source_files"]["prediction_original"]["sha256"])
    write_json(m,data)
    with pytest.raises(ValueError,match="original.*asset source"):freeze_run(m,p,tmp_path/"bad")


def test_review_same_raw_different_predictions_cannot_cross_splits(tmp_path):
    _,m,p=run_fixture(tmp_path);formalize(m);data=read_json(m)
    for index,c in enumerate(data["cases"]):
        c["split"]="dev" if index==0 else "test"
        r=m.parent/c["case_root"]
        for asset in c["assets"]:
            src=r/(asset["role"]+"_distinct.source.png");Image.new("RGB",(12,10),(20+index*100,80,100) if asset["role"]=="prediction" else (100,40+index*100,60)).save(src)
            new=canonicalize_image(src,r/(asset["role"]+"_distinct.png"),asset["role"],{"assume_srgb":True},asset_id=asset["asset_id"])
            asset.update(new)
            key=asset["role"]+"_original"
            c["source_files"][key].update(path=asset["source_file"]["path"],sha256=asset["source_file"]["sha256"])
            if asset["role"]=="prediction":c["baseline_provenance"]["prediction_output_sha256"]=asset["source_file"]["sha256"]
    write_json(m,data)
    with pytest.raises(ValueError,match="cross-split"):freeze_run(m,p,tmp_path/"bad")


@pytest.mark.parametrize("reverse",[False,True])
@pytest.mark.parametrize("resolution",[None,"usable","unusable","uncertain","missing"])
def test_review_comparability_conflict_is_order_independent_uncertainty(tmp_path,reverse,resolution):
    root,_,_=run_fixture(tmp_path,cases=1)
    plan=read_json(root/"planned_outcomes.json")
    for o in plan["outcomes"]:
        ar=root/o["input_case_root"];src=ar/"green.source.png";Image.new("RGB",(12,10),"green").save(src)
        inputs=read_json(root/"manifest.json")["cases"][0]["assets"]
        binding={"case_id":"case0","case_revision":0,"task_id":"t","round":0,"generation_id":"g","prediction_sha256":inputs[0]["sha256"],"reference_sha256":inputs[1]["sha256"]}
        c=canonicalize_image(src,ar/(o["arm_id"]+".png"),"candidate",{"assume_srgb":True},asset_id="generated",candidate_binding=binding)
        o.update(status="completed",selected_asset=c,selected_asset_root=o["input_case_root"])
        register_external_contract(root,o)
    write_json(root/"planned_outcomes.json",plan);export_blind_evaluation(root,tmp_path/"blind")
    rating={"frozen":True,"raters":[{"rater_id":r,"independent":True,"participated_cases":[]} for r in ["r1","r2"]],"ratings":[]}
    for item in read_json(root/"private/blind_mapping.json")["items"]:
        for r,comp in [("r1","usable"),("r2","unusable")]:rating["ratings"].append({"code":item["code"],"rater_id":r,"style_direction":"improved","content_preservation":"pass","critical_defects":[],"comparability":comp})
    if resolution is not None:
        rating["raters"].append({"rater_id":"r3","independent":True,"participated_cases":[]})
        rating["adjudications"]=[{"code":item["code"],"rater_id":"r3","style_direction":"improved","content_preservation":"pass","critical_defects":[],**({"comparability":resolution} if resolution!="missing" else {})} for item in read_json(root/"private/blind_mapping.json")["items"]]
    if reverse:rating["ratings"].reverse()
    rp=tmp_path/"ratings.json";write_json(rp,rating)
    if resolution=="missing":
        with pytest.raises(ValueError,match="comparability"):summarize_evaluation(root,rp)
    else:
        result=summarize_evaluation(root,rp)
        assert all(o["rating_status"]==("unresolved_disagreement" if resolution is None else "third_rater_adjudication") and o["joint_success"]==(1 if resolution=="usable" else 0) for o in result["outcomes"])


@pytest.mark.parametrize("drift",["geometry","tools","roi","reference_limits","repair","none"])
def test_review_live_config_drift_stays_itt_with_observed_cost(tmp_path,drift):
    from hre.assets import create_case
    from hre.workflow import Controller
    from hre.desktop import import_candidate
    from hre.protocol import TaskWriter
    from test_hre_selection import verified
    _,m,p=run_fixture(tmp_path,cases=1);formalize(m)
    data=read_json(m);data["cases"][0]["content_preservation_annotations"]=[];write_json(m,data)
    root=tmp_path/"formal";freeze_run(m,p,root)
    plan=read_json(root/"planned_outcomes.json");o=next(x for x in plan["outcomes"] if x["arm_id"]=="direct_ref")
    case=data["cases"][0];config=read_json(root/"runtime_configs/case0/direct_ref.json")
    if drift=="geometry":config["geometry_policy"]={"mode":"aspect_preserving_resize","max_aspect_ratio_error":.005}
    if drift=="tools":config["tool_profile"]={"unexpected_tool_version":"2"}
    if drift=="roi":config["roi_manifest"]=[]
    if drift=="reference_limits":config["reference_limitations"]=["unexpected post-enrollment change"]
    if drift=="repair":config["format_repair_limit"]=0
    cr=root/o["case_root"];ir=root/"frozen_inputs/case0"
    create_case(ir/case["assets"][0]["path"],ir/case["assets"][1]["path"],case,config,cr)
    controller=Controller(cr);state=controller.start();tid=state["pending_task"]["task_id"];controller.mark_submitted(tid)
    source=tmp_path/"large.png"
    # Real embedded sRGB candidate; no per-candidate assumption override.
    from PIL import ImageCms
    Image.new("RGB",(24,20) if drift=="geometry" else (12,10),"green").save(source,icc_profile=ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes())
    assert controller.consume_done(import_candidate(cr,tid,source,{"actual_generation_count":1,"provider_order":0})).accepted
    req=read_json(cr/controller.state()["pending_task"]["request_path"])
    assert controller.consume_done(TaskWriter(cr).commit_submission(req,verified()["verification"])).accepted
    export_blind_evaluation(root,tmp_path/"blind")
    mapping=read_json(root/"private/blind_mapping.json");record=next(x for x in mapping["items"] if x["arm_id"]=="direct_ref")
    assert bool(record["protocol_violations"])==(drift!="none")
    assert record["status"]==("protocol_violation" if drift!="none" else "completed")
    assert record["costs"]["accounted_generations"]==1
    rp=tmp_path/"ratings.json";write_json(rp,{"frozen":True,"raters":[{"rater_id":r,"independent":True,"participated_cases":[]} for r in ["r1","r2"]],"ratings":[{"code":x["code"],"rater_id":r,"style_direction":"improved","content_preservation":"pass","critical_defects":[],"comparability":"usable"} for x in mapping["items"] for r in ["r1","r2"]]})
    result=summarize_evaluation(root,rp)
    assert result["arms"]["direct_ref"]["denominator"]==1 and result["arms"]["direct_ref"]["joint_success"]==(1 if drift=="none" else 0)


def register_external_contract(root,outcome):
    """Produce the imported execution contract through the real case initializer."""
    from hre.assets import create_case
    config=read_json(root/"runtime_configs"/outcome["case_id"]/(outcome["arm_id"]+".json"))
    case=next(c for c in read_json(root/"manifest.json")["cases"] if c["case_id"]==outcome["case_id"])
    inputs={a["role"]:a for a in case["assets"]};ir=root/"frozen_inputs"/case["case_id"]
    record=root/"external_records"/case["case_id"]/outcome["arm_id"]
    create_case(ir/inputs["prediction"]["path"],ir/inputs["reference"]["path"],case,config,record)
    # Synthetic external positives must retain actual issued prompts/journal,
    # not assert matching template hashes after a candidate already exists.
    from hre.workflow import Controller
    from hre.protocol import TaskWriter
    from hre.desktop import import_candidate
    from test_hre_protocol import diagnosis, current_request
    from test_hre_workflow import compose_payload, verification
    from PIL import ImageCms
    controller=Controller(record);controller.start()
    if outcome['arm_id'] == 'agent_single':
        assert controller.consume_done(TaskWriter(record).commit_submission(current_request(record),diagnosis())).accepted
        assert controller.consume_done(TaskWriter(record).commit_submission(current_request(record),compose_payload())).accepted
    request=current_request(record);controller.mark_submitted(request['task_id'])
    raw=root/outcome['selected_asset_root']/outcome['selected_asset']['source_file']['path']
    source=record/'synthetic_generated.png'
    with Image.open(raw) as image:
        image.save(source,icc_profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes())
    assert controller.consume_done(import_candidate(record,request['task_id'],source,{'actual_generation_count':1,'provider_order':0})).accepted
    assert controller.consume_done(TaskWriter(record).commit_submission(current_request(record),verification())).accepted
    from hre.reporting import resolve_selected_asset
    outcome['selected_asset']=resolve_selected_asset(controller.state())
    outcome['selected_asset_root']=record.relative_to(root).as_posix()
    outcome["execution_contract"]={"path":(record/"config.json").relative_to(root).as_posix(),"sha256":file_sha256(record/"config.json"),
                                   "selected_asset_id":outcome["selected_asset"]["asset_id"],"selected_asset_sha256":outcome["selected_asset"]["sha256"],
                                   "execution_record_root":record.relative_to(root).as_posix()}



def test_review_unverified_external_candidate_cannot_be_protocol_success(tmp_path):
    root,_,_=run_fixture(tmp_path,cases=1);plan=read_json(root/"planned_outcomes.json")
    for o in plan["outcomes"]:
        ar=root/o["input_case_root"];source=ar/"generated.source.png";Image.new("RGB",(12,10),"green").save(source)
        inputs=read_json(root/"manifest.json")["cases"][0]["assets"]
        binding={"case_id":"case0","case_revision":0,"task_id":"t","round":0,"generation_id":"g","prediction_sha256":inputs[0]["sha256"],"reference_sha256":inputs[1]["sha256"]}
        candidate=canonicalize_image(source,ar/(o["arm_id"]+".png"),"candidate",{"assume_srgb":True},asset_id="generated",candidate_binding=binding)
        o.update(status="completed",selected_asset=candidate,selected_asset_root=o["input_case_root"])
    write_json(root/"planned_outcomes.json",plan);export_blind_evaluation(root,tmp_path/"blind")
    assert all(m["status"]=="protocol_violation" for m in read_json(root/"private/blind_mapping.json")["items"])


@pytest.mark.parametrize("damage", ["bad_sha", "missing_file"])
def test_invalid_external_contract_preserves_other_outcome_export_and_itt(tmp_path,damage):
    root,_,_=run_fixture(tmp_path,cases=1)
    plan=read_json(root/"planned_outcomes.json")
    for o in plan["outcomes"]:
        ar=root/"frozen_inputs/case0";source=ar/"generated.source.png";Image.new("RGB",(12,10),"green").save(source)
        inputs=read_json(root/"manifest.json")["cases"][0]["assets"]
        binding={"case_id":"case0","case_revision":0,"task_id":"t","round":0,"generation_id":"g","prediction_sha256":inputs[0]["sha256"],"reference_sha256":inputs[1]["sha256"]}
        candidate=canonicalize_image(source,ar/(o["arm_id"]+".png"),"candidate",{"assume_srgb":True},asset_id="generated",candidate_binding=binding)
        o.update(status="completed",selected_asset=candidate,selected_asset_root="frozen_inputs/case0")
        register_external_contract(root,o)
    broken=plan["outcomes"][0];other=plan["outcomes"][1]
    if damage=="bad_sha":broken["execution_contract"]["sha256"]="a"*64
    else:broken["execution_contract"]["path"]="external_records/missing.json"
    write_json(root/"planned_outcomes.json",plan)
    export_blind_evaluation(root,tmp_path/"blind")
    mapping=read_json(root/"private/blind_mapping.json")["items"]
    assert len(mapping)==2 and len(read_json(tmp_path/"blind/manifest.json")["items"])==2
    bad=next(x for x in mapping if x["arm_id"]==broken["arm_id"])
    good=next(x for x in mapping if x["arm_id"]==other["arm_id"])
    assert bad["status"]=="protocol_violation" and bad["protocol_violations"]
    assert bad["costs"] is None and good["status"]=="completed"
    rp=tmp_path/"ratings.json";write_json(rp,{"frozen":True,"raters":[{"rater_id":r,"independent":True,"participated_cases":[]} for r in ["r1","r2"]],"ratings":[{"code":x["code"],"rater_id":r,"style_direction":"improved","content_preservation":"pass","critical_defects":[],"comparability":"usable"} for x in mapping for r in ["r1","r2"]]})
    summary=summarize_evaluation(root,rp)
    assert summary["denominator"]==2
    assert summary["arms"][broken["arm_id"]]["joint_success"]==0
    assert summary["arms"][other["arm_id"]]["joint_success"]==1
