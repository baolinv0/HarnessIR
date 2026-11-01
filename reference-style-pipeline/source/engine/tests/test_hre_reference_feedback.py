"""External-review regressions. Synthetic bytes never establish real efficacy."""
from copy import deepcopy
from pathlib import Path
import numpy as np
from PIL import Image
import pytest
from hre.models import HREError,file_sha256
from hre.storage import CaseStore,read_json,write_json
from test_hre_reference_v2 import spec,pair,region,local_g1_and_g2
from test_hre_reference_review import complete_arm


def test_g2_rejects_mask_on_wrong_side_despite_correct_roi_id(tmp_path):
    from hre.masks import make_mask_contract
    from hre.reference_contracts import prepare_reference_config
    _,root=local_g1_and_g2(tmp_path);cfg=read_json(root/'config.json');inputs=CaseStore(root).load()['inputs']
    values=np.zeros((12,16),dtype=np.uint8);values[:,8:]=1
    mask=make_mask_contract(root,values,inputs[0],purpose='EDIT_MASK',roi_ids=['wall'],
                            provenance={'kind':'manual','annotator':'fixture'},relative='annotations/wrong_side.npy')
    cfg['reference_v2']['edit_mask']=mask
    cfg['reference_v2']['files'].append({k:mask[k] for k in ('path','sha256')})
    with pytest.raises(HREError,match='mask_spatial_binding'):prepare_reference_config(root,cfg,inputs)


def spatial_policy(minimum=.4):
    return dict(schema_version='mask_roi_policy_v2',roi_constraints=[dict(roi_pair_id='wall',min_edit_coverage=minimum,min_eval_coverage=.9)],
                max_edit_outside_fraction=.1,max_eval_outside_fraction=.1,rationale='Synthetic partial wall selection; frozen before outputs')


def test_spatial_policy_is_explicit_task_tolerance_and_reports_expansion(tmp_path):
    from hre.masks import make_mask_contract
    from hre.reference_contracts import mask_roi_binding
    _,root=local_g1_and_g2(tmp_path);state=CaseStore(root).load();s=read_json(root/'config.json')['reference_v2']
    values=np.zeros((12,16),dtype=np.uint8);values[:6,:8]=1
    s['edit_mask']=make_mask_contract(root,values,state['inputs'][0],purpose='EDIT_MASK',roi_ids=['wall'],
                    provenance={'kind':'manual','annotator':'fixture'},relative='annotations/partial.npy')
    s['mask_roi_policy']=spatial_policy()
    report=mask_roi_binding(root,s,state['inputs'][0])
    assert report['per_roi'][0]['edit_coverage']==.5
    assert report['masks']['EDIT_MASK']['outside_mask_fraction']==0
    assert report['masks']['EDIT_MASK']['outside_to_roi_area_ratio']==0
    s['mask_roi_policy']['roi_constraints'][0]['min_edit_coverage']=.6
    with pytest.raises(HREError,match='mask_spatial_binding'):mask_roi_binding(root,s,state['inputs'][0])
    s['mask_roi_policy']['roi_constraints'][0]['min_edit_coverage']=.4
    values[:6,8]=1
    s['edit_mask']=make_mask_contract(root,values,state['inputs'][0],purpose='EDIT_MASK',roi_ids=['wall'],
                    provenance={'kind':'manual','annotator':'fixture'},relative='annotations/expanded.npy')
    with pytest.raises(HREError,match='mask_spatial_binding'):mask_roi_binding(root,s,state['inputs'][0])
    s['mask_roi_policy']['max_edit_outside_fraction']=.12
    expanded=mask_roi_binding(root,s,state['inputs'][0])['masks']['EDIT_MASK']
    assert expanded['outside_mask_fraction']==pytest.approx(1/9)
    assert expanded['outside_to_roi_area_ratio']==pytest.approx(6/96)
    s.pop('mask_roi_policy')
    with pytest.raises(HREError,match='mask_roi_policy'):mask_roi_binding(root,s,state['inputs'][0])


def test_spatial_binding_checks_each_roi_rather_than_only_the_union(tmp_path):
    from hre.masks import make_mask_contract
    from hre.reference_contracts import mask_roi_binding
    _,root=local_g1_and_g2(tmp_path);a=CaseStore(root).load()['inputs'][0];s=read_json(root/'config.json')['reference_v2']
    right=deepcopy(s['roi_pairs'][0]);right.update(roi_pair_id='building',prediction=region([.5,0,1,1]));s['roi_pairs'].append(right)
    for field,purpose in [('edit_mask','EDIT_MASK'),('eval_mask','EVAL_MASK')]:
        values=np.zeros((12,16),dtype=np.uint8);values[:,:8]=1
        s[field]=make_mask_contract(root,values,a,purpose=purpose,roi_ids=['wall','building'],
                    provenance={'kind':'manual','annotator':'fixture'},relative='annotations/multi_'+field+'.npy')
    s['mask_roi_policy']['roi_constraints'].append(dict(roi_pair_id='building',min_edit_coverage=.1,min_eval_coverage=.1))
    with pytest.raises(HREError,match='mask_spatial_binding'):mask_roi_binding(root,s,a)


def test_g1_does_not_require_g2_spatial_policy(tmp_path):
    from hre.reference_contracts import prepare_reference_config
    root,_=local_g1_and_g2(tmp_path);cfg=read_json(root/'config.json');cfg['reference_v2'].pop('mask_roi_policy')
    prepare_reference_config(root,cfg,CaseStore(root).load()['inputs'])


def decision_run(tmp_path,completed=1,missing_review=False):
    from hre.reference_contracts import create_reference_case
    from hre.reference_experiments import freeze_reference_run,prepare_run_arm,export_reference_blind,summarize_reference_run
    a=tmp_path/'A.png';b=tmp_path/'B.png';Image.new('RGB',(16,12),(40,40,40)).save(a);Image.new('RGB',(20,14),(80,80,80)).save(b)
    cases=[]
    for i in range(3):
        s=spec('G1');s['simulation_only']=False  # Decision-contract reproduction only; all images remain synthetic.
        create_reference_case(a,b,s,tmp_path/f'source{i}',spec_root=tmp_path,manifest={'case_id':f'c{i}'})
        cases.append(dict(case_id=f'c{i}',scene_group_id=f'scene{i}',split='dev',source_case_root=f'source{i}',g2=None))
    write_json(tmp_path/'manifest.json',dict(schema_version='reference_run_manifest_v2',stage='R1',seed=1,code_commit_sha='f'*40,excluded_rater_ids=['operator'],cases=cases))
    run=tmp_path/'run';freeze_reference_run(tmp_path/'manifest.json',run)
    for i in range(completed):
        for arm in ('G0','G1'):complete_arm(Path(prepare_run_arm(run,f'c{i}',arm)['case_root']),tmp_path/f'{i}_{arm}.png')
    blind=tmp_path/'blind';export_reference_blind(run,blind);mapping=read_json(run/'private/blind_mapping_v2.json');ratings=[]
    for item in mapping['rows']:
        if item['row']['status']!='candidate_ready' or (missing_review and item['row']['case_id']=='c2'):continue
        for rater in ('r1','r2'):
            ratings.append(dict(code=item['code'],rater_id=rater,kind='review',style='improved',content='pass',critical_defects=[],
                                attributes={d:'improved' for d in ('brightness','color','tone','saturation')},notes='Synthetic contract reproduction'))
    path=tmp_path/'ratings.json';write_json(path,dict(schema_version='reference_ratings_v2',blind_manifest_sha256=file_sha256(blind/'manifest.json'),
                    raters=[{'rater_id':r,'independent':True} for r in ('r1','r2')],ratings=ratings,comparisons=[]))
    return summarize_reference_run(run,path)


@pytest.mark.parametrize('completed,missing,expected',[(1,False,'FIRST_PAIR_PASSED'),(3,False,'GO_TO_R2'),(3,True,'PROBE')])
def test_r1_first_pair_is_distinct_from_complete_reviewed_cohort(tmp_path,completed,missing,expected):
    result=decision_run(tmp_path,completed,missing)
    assert result['decision']==expected
    assert result['R1_readiness']['planned_pairs']==3
    assert result['R1_readiness']['execution_complete_pairs']==completed
    assert not result['real_effect_validated']


def test_first_pair_review_can_continue_same_cohort_then_receive_fresh_final_reviews(tmp_path):
    from hre.reference_experiments import prepare_run_arm,export_reference_blind,summarize_reference_run
    assert decision_run(tmp_path)['decision']=='FIRST_PAIR_PASSED'
    run=tmp_path/'run';old_ratings=tmp_path/'ratings.json';old=read_json(old_ratings)
    for i in (1,2):
        for arm in ('G0','G1'):complete_arm(Path(prepare_run_arm(run,f'c{i}',arm)['case_root']),tmp_path/f'next_{i}_{arm}.png')
    provisional=summarize_reference_run(run,old_ratings)
    assert provisional['decision']=='FIRST_PAIR_PASSED' and provisional['review_snapshot_kind']=='r1_progress'
    final=tmp_path/'final_blind';export_reference_blind(run,final)
    mapping=read_json(run/'private/blind_mapping_v2.json');ratings=[]
    for item in mapping['rows']:
        for rater in ('r1','r2'):
            ratings.append(dict(code=item['code'],rater_id=rater,kind='review',style='improved',content='pass',critical_defects=[],
                                attributes={d:'improved' for d in ('brightness','color','tone','saturation')},notes='Synthetic fresh final-cohort review'))
    final_ratings=tmp_path/'final_ratings.json';write_json(final_ratings,{**old,'blind_manifest_sha256':file_sha256(final/'manifest.json'),'ratings':ratings})
    result=summarize_reference_run(run,final_ratings)
    assert result['decision']=='GO_TO_R2' and result['review_snapshot_kind']=='final'
    assert summarize_reference_run(run,old_ratings)['decision']=='FIRST_PAIR_PASSED'
    with pytest.raises(HREError,match='evaluation_frozen'):export_reference_blind(run,tmp_path/'another_final')


def two_roi_run(tmp_path,granular=False):
    from hre.reference_contracts import create_reference_case
    from hre.reference_experiments import freeze_reference_run,prepare_run_arm,export_reference_blind,summarize_reference_run
    aa=np.full((12,16,3),40,dtype=np.uint8);aa[:,8:]=80
    a=tmp_path/'A.png';b=tmp_path/'B.png';Image.fromarray(aa).save(a);Image.new('RGB',(20,14),(80,80,80)).save(b)
    s=spec('G1');left=pair();left['dimensions']=['brightness'];right=deepcopy(left);right.update(roi_pair_id='building',prediction=region([.5,0,1,1]))
    s['roi_pairs']=[left,right];create_reference_case(a,b,s,tmp_path/'source',spec_root=tmp_path,manifest={'case_id':'one'})
    write_json(tmp_path/'manifest.json',dict(schema_version='reference_run_manifest_v2',stage='R0_fixture',seed=1,code_commit_sha='f'*40,
                excluded_rater_ids=['operator'],cases=[dict(case_id='one',scene_group_id='scene',split='dev',source_case_root='source',g2=None)]))
    run=tmp_path/'run';freeze_reference_run(tmp_path/'manifest.json',run)
    for arm in ('G0','G1'):complete_arm(Path(prepare_run_arm(run,'one',arm)['case_root']),tmp_path/(arm+'.png'))
    blind=tmp_path/'blind';export_reference_blind(run,blind);mapping=read_json(run/'private/blind_mapping_v2.json');ratings=[]
    for item in mapping['rows']:
        for rater in ('r1','r2'):
            rating=dict(code=item['code'],rater_id=rater,kind='review',style='improved',content='pass',critical_defects=[],attributes={'brightness':'improved'},notes='Synthetic granular review')
            if granular:rating['roi_attributes']=[dict(roi_pair_id='r001',dimension='brightness',label='improved'),dict(roi_pair_id='r002',dimension='brightness',label='worse')]
            ratings.append(rating)
    path=tmp_path/'ratings.json';write_json(path,dict(schema_version='reference_ratings_v2',blind_manifest_sha256=file_sha256(blind/'manifest.json'),
                    raters=[{'rater_id':r,'independent':True} for r in ('r1','r2')],ratings=ratings,comparisons=[]))
    return run,path,summarize_reference_run


@pytest.mark.parametrize('granular',[False,True])
def test_h3_uses_only_matching_roi_labels_never_broadcasts_whole_image(tmp_path,granular):
    run,path,summarize=two_roi_run(tmp_path,granular)
    result=summarize(run,path)
    assert {r['metric_direction'] for r in result['H3']}=={'improved','worse'}
    assert all(r['status']==('agree' if granular else 'unknown') for r in result['H3'])
    if granular:
        value=read_json(path)
        for r in value['ratings']:
            if r['rater_id']=='r2':r['roi_attributes'][1]['label']='improved'
        write_json(path,value);result=summarize(run,path)
        assert all(r['status']=='unknown' for r in result['H3'] if r['roi_pair_id']=='building')
        assert result['arms']['G1']['joint_success']==1


def test_h3_rejects_unknown_or_duplicated_roi_labels(tmp_path):
    run,path,summarize=two_roi_run(tmp_path,True);original=read_json(path)
    for invalid in ('unknown','duplicate'):
        value=deepcopy(original)
        if invalid=='unknown':value['ratings'][0]['roi_attributes'][0]['roi_pair_id']='not_in_this_item'
        else:value['ratings'][0]['roi_attributes'].append(deepcopy(value['ratings'][0]['roi_attributes'][0]))
        write_json(path,value)
        with pytest.raises(HREError,match='ratings_invalid'):summarize(run,path)


@pytest.mark.parametrize('annotation,diagnosed',[('partly_comparable','comparable'),('comparable','partly_comparable')])
def test_target_comparability_keeps_frozen_and_diagnosed_uncertainty(tmp_path,annotation,diagnosed):
    from hre.reference_contracts import reference_targets
    from test_hre_protocol import diagnosis
    from test_hre_workflow import compose_payload
    p=pair();p['comparability']=annotation;write_json(tmp_path/'config.json',{'reference_v2':{'roi_pairs':[p]}})
    d=diagnosis();gap=d['global_gaps'].pop();gap.update(roi_pair_id='wall',region_in_a='left wall');d['local_gaps']=[gap]
    d['comparability'].append(dict(scope='roi_pair',roi_pair_id='wall',status=diagnosed,reasons=['limited comparable material'],confidence=.7))
    c=compose_payload();c['edit_targets'][0]['scope']='region'
    target=reference_targets(tmp_path,d,c,[])['targets'][0]
    assert target['comparability']=='partly_comparable'
    assert target['comparability_sources']['diagnosis'][0]['status']==diagnosed
    assert target['comparability_sources']['frozen_roi'][0]['comparability']==annotation


def test_channel_endpoints_do_not_imply_display_luma_or_sensor_clipping():
    from hre.reference_evaluator import display_attributes
    result=display_attributes(np.array([[255,0,0],[0,0,0],[255,255,255]],dtype=np.uint8))
    assert result['channel_any_low_endpoint_fraction']==pytest.approx(2/3)
    assert result['channel_any_high_endpoint_fraction']==pytest.approx(2/3)
    assert result['display_luma_low_endpoint_fraction']==pytest.approx(1/3)
    assert result['display_luma_high_endpoint_fraction']==pytest.approx(1/3)
    assert 'shadow_clip_fraction' not in result and 'highlight_clip_fraction' not in result
