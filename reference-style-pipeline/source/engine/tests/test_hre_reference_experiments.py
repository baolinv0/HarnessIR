from pathlib import Path
import json
import pytest
from PIL import Image
from hre.models import HREError,file_sha256
from hre.storage import write_json,read_json
from test_hre_reference_v2 import spec,executor,observed_execution


def source_run(tmp_path):
    from hre.reference_contracts import create_reference_case
    a=tmp_path/'A.png';b=tmp_path/'B.png'
    Image.new('RGB',(16,12),(40,40,40)).save(a);Image.new('RGB',(20,14),(80,80,80)).save(b)
    source=tmp_path/'source';create_reference_case(a,b,spec('G1'),source,spec_root=tmp_path,manifest={'case_id':'one'})
    manifest=dict(schema_version='reference_run_manifest_v2',stage='R0_fixture',seed=20261015,
                  code_commit_sha='c94a4001e5250fd257e8954b56b72ca9c4725409',excluded_rater_ids=['composer'],
                  cases=[dict(case_id='one',scene_group_id='scene1',split='dev',source_case_root='source',g2=None)])
    write_json(tmp_path/'manifest.json',manifest)
    return tmp_path/'manifest.json'


def test_v2_run_freezes_planned_and_capability_skipped_denominators(tmp_path):
    from hre.reference_experiments import freeze_reference_run,reference_run_status,prepare_run_arm
    manifest=source_run(tmp_path);run=tmp_path/'run'
    freeze_reference_run(manifest,run)
    result=reference_run_status(run)
    assert len(result['rows'])==3
    by_arm={r['arm_id']:r for r in result['rows']}
    assert by_arm['G0']['status']==by_arm['G1']['status']=='planned'
    assert by_arm['G2']['status']=='skipped_not_eligible'
    assert result['max_submissions']==2
    prepared=prepare_run_arm(run,'one','G0')
    assert Path(prepared['case_root']).joinpath('state.json').exists()
    assert reference_run_status(run)['rows'][0]['case_id']=='one'
    with pytest.raises(HREError):prepare_run_arm(run,'one','G2')


def test_v2_run_rejects_postfreeze_annotations(tmp_path):
    from hre.reference_experiments import freeze_reference_run,reference_run_status
    manifest=source_run(tmp_path);run=tmp_path/'run';freeze_reference_run(manifest,run)
    path=run/'frozen/one/spec.json';value=read_json(path);value['roi_pairs']=[];write_json(path,value)
    with pytest.raises(HREError,match='artifact_hash_mismatch'):reference_run_status(run)


def test_blind_package_has_no_arm_or_prompt_and_missing_results_stay_ITT(tmp_path):
    from hre.reference_experiments import freeze_reference_run,export_reference_blind,summarize_reference_run
    manifest=source_run(tmp_path);run=tmp_path/'run';freeze_reference_run(manifest,run)
    out=tmp_path/'blind';export_reference_blind(run,out)
    payload=read_json(out/'manifest.json')
    assert len(payload['items'])==2
    text=json.dumps(payload)
    assert all(v not in text for v in ['arm_id','G0','G1','edit_prompt','executor','diagnosis'])
    ratings=dict(schema_version='reference_ratings_v2',blind_manifest_sha256=file_sha256(out/'manifest.json'),raters=[],ratings=[],comparisons=[])
    write_json(tmp_path/'ratings.json',ratings)
    summary=summarize_reference_run(run,tmp_path/'ratings.json')
    assert summary['arms']['G0']['n_itt']==1 and summary['arms']['G0']['joint_success']==0
    assert summary['arms']['G1']['n_unknown']==1
    assert summary['H1']['unknown']==1 and summary['decision']!='GO'


def test_blind_export_cannot_overwrite_a_case_or_the_run(tmp_path):
    from hre.reference_experiments import freeze_reference_run,export_reference_blind
    manifest=source_run(tmp_path);run=tmp_path/'run';freeze_reference_run(manifest,run)
    with pytest.raises(HREError):export_reference_blind(run,run/'private')


@pytest.mark.parametrize('disagree',[False,True])
def test_independent_reviews_control_success_and_disagreement_is_unknown(tmp_path,disagree):
    from hre.reference_experiments import freeze_reference_run,prepare_run_arm,export_reference_blind,summarize_reference_run
    from hre.workflow import Controller
    from hre.cli import current_request,import_payload,import_candidate_manual
    from test_hre_protocol import diagnosis
    from test_hre_workflow import compose_payload,verification
    manifest=source_run(tmp_path);run=tmp_path/'run';freeze_reference_run(manifest,run)
    for arm,n in [('G0',55),('G1',70)]:
        root=Path(prepare_run_arm(run,'one',arm)['case_root']);Controller(root).start()
        if arm=='G1':assert import_payload(root,diagnosis()).accepted;assert import_payload(root,compose_payload()).accepted
        req=current_request(root);out=tmp_path/(arm+'.png');Image.new('RGB',(16,12),(n,n,n)).save(out)
        metadata=dict(actual_generation_count=1,provider_order=0,executor_observation=observed_execution(root,req,out),model_observed={'ui_model_name':executor()['model_display_name'],'transport':executor()['transport'],'operator_steps':['Fixture only']})
        assert import_candidate_manual(root,req['task_id'],out,metadata,'submitted').accepted
        assert import_payload(root,verification()).accepted
    blind=tmp_path/'blind';export_reference_blind(run,blind);private=read_json(run/'private/blind_mapping_v2.json');reviews=[];comparisons=[]
    for item in private['rows']:
        arm=item['row']['arm_id']
        for i,rater in enumerate(['r1','r2']):
            style='improved' if arm=='G1' else 'worse'
            if disagree and arm=='G1' and i==1:style='worse'
            reviews.append(dict(code=item['code'],rater_id=rater,kind='review',style=style,content='pass',critical_defects=[],
                                attributes={d:style for d in ['brightness','color','tone','saturation']},notes='Synthetic independent-review contract input'))
    for comp in private['comparisons']:
        for rater in ['r1','r2']:
            comparisons.append(dict(code=comp['code'],rater_id=rater,kind='review',preference='left' if comp['left_arm']=='G1' else 'right',notes='Fixture paired preference'))
    ratings=dict(schema_version='reference_ratings_v2',blind_manifest_sha256=file_sha256(blind/'manifest.json'),raters=[{'rater_id':r,'independent':True} for r in ['r1','r2']],ratings=reviews,comparisons=comparisons)
    write_json(tmp_path/'ratings.json',ratings)
    result=summarize_reference_run(run,tmp_path/'ratings.json')
    assert result['arms']['G0']['joint_success']==0
    assert result['arms']['G1']['joint_success']==(0 if disagree else 1)
    assert result['arms']['G1']['n_unknown']==int(disagree)
    assert result['H1']['wins']==1 and result['decision']=='PROBE'


def test_binary_roi_regions_reach_blind_review_with_neutral_names(tmp_path):
    import numpy as np
    from hre.reference_contracts import create_reference_case
    from hre.reference_experiments import freeze_reference_run,export_reference_blind
    (tmp_path/'annotations').mkdir()
    aa=np.zeros((12,16),dtype=np.uint8);aa[:,:8]=1;bb=np.zeros((14,20),dtype=np.uint8);bb[:,10:]=1
    s=spec('G1');s['files']=[]
    for key,values in [('prediction',aa),('reference',bb)]:
        p=tmp_path/'annotations'/(key+'.npy');np.save(p,values,allow_pickle=False)
        ref=dict(path=p.relative_to(tmp_path).as_posix(),sha256=file_sha256(p));s['files'].append(ref)
        s['roi_pairs'][0][key]={'kind':'mask',**ref}
    a=tmp_path/'A.png';b=tmp_path/'B.png'
    Image.new('RGB',(16,12),(40,40,40)).save(a);Image.new('RGB',(20,14),(80,80,80)).save(b)
    create_reference_case(a,b,s,tmp_path/'source',spec_root=tmp_path,manifest={'case_id':'one'})
    write_json(tmp_path/'m.json',dict(schema_version='reference_run_manifest_v2',stage='R0_fixture',seed=1,code_commit_sha='c'*40,excluded_rater_ids=['operator'],
                                   cases=[dict(case_id='one',scene_group_id='scene1',split='dev',source_case_root='source',g2=None)]))
    run=tmp_path/'run';freeze_reference_run(tmp_path/'m.json',run);blind=tmp_path/'blind';export_reference_blind(run,blind)
    package=read_json(blind/'manifest.json')
    for item in package['items']:
        assert len(item['roi_regions'])==1
        for key,size in [('prediction',(16,12)),('reference',(20,14))]:
            region=item['roi_regions'][0][key]
            assert region['kind']=='mask' and Image.open(blind/region['path']).size==size
            assert 'EDIT_MASK' not in region['path']
