"""Behavioral tests for opt-in v2; fixtures never establish model capability."""
from copy import deepcopy
import json
import numpy as np
from PIL import Image
import pytest
from hre.models import HREError, file_sha256
from test_hre_stats import asset


def executor():
    return dict(executor_id='desktop', model_display_name='observed editor',
                model_exact_version=None, transport='desktop_manual',
                pipeline_version='2', adapter_version='1', settings={})


def region(box):
    return dict(kind='box', box=box)


def pair():
    return dict(roi_pair_id='wall', prediction=region([0,0,.5,1]),
                reference=region([.5,0,1,1]), comparability='comparable',
                reasons=['same wall'], semantic_label='wall',
                dimensions=['brightness','color','tone','saturation'])


def spec(arm='G0'):
    return dict(schema_version='ref_enhance_v2', arm_id=arm, executor=executor(),
                task_scope='global', local_mask_eligible=False, roi_pairs=[pair()],
                eval_mask=None, edit_mask=None, mask_probe=None, paired_g1=None,
                files=[], simulation_only=True,assume_srgb=True,tool_profile={})


def bind_candidate(c,a,b):
    c['role']='candidate'
    c['candidate_binding']=dict(case_id='fixture',case_revision=0,task_id='fixture_task',round=0,generation_id='fixture_gen',prediction_sha256=a['sha256'],reference_sha256=b['sha256'])


def test_v2_opt_in_keeps_one_generation_and_v1_state(tmp_path):
    from hre.reference_contracts import create_reference_case
    from hre.workflow import Controller
    a=tmp_path/'A.png';b=tmp_path/'B.png'
    Image.new('RGB',(8,6),(40,40,40)).save(a)
    Image.new('RGB',(12,8),(80,80,80)).save(b)
    root=tmp_path/'case'
    state=create_reference_case(a,b,spec(),root,spec_root=tmp_path)
    assert state['schema_version']=='ref_enhance_v1'
    assert state['profile_id']=='direct_ref' and state['budget']['max_generations']==1
    cfg=json.loads((root/'config.json').read_text())
    assert cfg['reference_v2']['schema_version']=='ref_enhance_v2'
    assert Controller(root).start()['workflow_state']=='WAIT_EXECUTION'


def test_unprobed_g2_never_creates_or_reserves(tmp_path):
    from hre.reference_contracts import create_reference_case
    s=spec('G2');s.update(task_scope='local',local_mask_eligible=True)
    with pytest.raises(HREError,match='skipped_capability'):
        create_reference_case(tmp_path/'absentA',tmp_path/'absentB',s,tmp_path/'case',spec_root=tmp_path)
    assert not (tmp_path/'case/state.json').exists()


def test_mask_uses_explicit_binary_allow_edit_and_binds_A(tmp_path):
    from hre.masks import make_mask_contract, validate_mask, encode_edit_mask
    a=asset(tmp_path,'A',np.full((2,4,3),60,dtype=np.uint8))
    mask=np.array([[1,1,0,0],[1,1,0,0]],dtype=np.uint8)
    c=make_mask_contract(tmp_path,mask,a,purpose='EDIT_MASK',roi_ids=['wall'],
                         provenance={'kind':'manual','annotator':'fixture'},relative='annotations/edit.npy')
    assert np.array_equal(validate_mask(tmp_path,c,a),mask)
    path=encode_edit_mask(tmp_path,c,a,'white_allow',tmp_path/'encoded.png')
    assert np.asarray(Image.open(path)).tolist()==[[255,255,0,0],[255,255,0,0]]
    bad=deepcopy(c);bad['input_role']='reference'
    with pytest.raises(HREError,match='mask_binding'):validate_mask(tmp_path,bad,a)
    bad=deepcopy(c);bad['semantics']='white_means_preserve'
    with pytest.raises(HREError,match='mask_encoding'):validate_mask(tmp_path,bad,a)
    with pytest.raises(HREError,match='invalid_mask'):
        make_mask_contract(tmp_path,np.zeros((2,4,3),dtype=np.uint8),a,purpose='EDIT_MASK',roi_ids=['wall'],provenance={'kind':'manual','annotator':'fixture'},relative='annotations/overlay.npy')


@pytest.mark.parametrize('values', [np.zeros((2,4),dtype=np.uint8),np.ones((2,3),dtype=np.uint8),np.full((2,4),np.nan)])
def test_invalid_masks_rejected(tmp_path,values):
    from hre.masks import make_mask_contract
    a=asset(tmp_path,'A',np.full((2,4,3),60,dtype=np.uint8))
    with pytest.raises(HREError):make_mask_contract(tmp_path,values,a,purpose='EDIT_MASK',roi_ids=['wall'],provenance={},relative='annotations/m.npy')


def test_independent_roi_brightness_and_near_zero(tmp_path):
    from hre.reference_evaluator import evaluate_reference
    a=asset(tmp_path,'A',[[[40,40,40],[0,0,0]]])
    b=asset(tmp_path,'B',[[[0,0,0],[80,80,80],[80,80,80],[80,80,80]]]);b['role']='reference'
    c=asset(tmp_path,'C',[[[70,70,70],[0,0,0]]]);bind_candidate(c,a,b)
    r=evaluate_reference(a,b,c,[pair()],case_root=tmp_path,geometry_status='pass',content_status='pass')
    attrs=r['per_roi'][0]['attributes']
    assert attrs['brightness']['delta']>0
    assert attrs['color']['relative_improvement'] is None  # neutral greys
    assert r['per_roi'][0]['areas']=={'A':1,'B':2,'C':1}
    assert attrs['tone']['delta']>0


@pytest.mark.parametrize('geometry,content', [('fail','pass'),('pass','fail'),('pass','unknown')])
def test_content_or_geometry_failure_invalidates_roi(tmp_path,geometry,content):
    from hre.reference_evaluator import evaluate_reference
    a=asset(tmp_path);b=deepcopy(a);b.update(asset_id='B',role='reference')
    c=deepcopy(a);c.update(asset_id='C');bind_candidate(c,a,b)
    r=evaluate_reference(a,b,c,[pair()],case_root=tmp_path,geometry_status=geometry,content_status=content)
    assert r['per_roi'][0]['status']=='not_assessable'
    assert r['per_roi'][0]['attributes'] is None


def test_unreliable_and_empty_roi_do_not_become_zero(tmp_path):
    from hre.reference_evaluator import evaluate_reference
    a=asset(tmp_path);b=deepcopy(a);b.update(asset_id='B',role='reference')
    c=deepcopy(a);c.update(asset_id='C');bind_candidate(c,a,b)
    p=pair();p['comparability']='not_comparable'
    r=evaluate_reference(a,b,c,[p],case_root=tmp_path,geometry_status='pass',content_status='pass')
    assert r['per_roi'][0]['attributes'] is None
    p=pair();p['prediction']=region([0,0,.01,.01])
    r=evaluate_reference(a,b,c,[p],case_root=tmp_path,geometry_status='pass',content_status='pass')
    assert r['per_roi'][0]['status']=='not_assessable'


def test_local_spill_measures_same_eval_mask_without_editor_mask(tmp_path):
    from hre.reference_evaluator import evaluate_reference
    from hre.masks import make_mask_contract
    a=asset(tmp_path,'A',np.full((2,4,3),40,dtype=np.uint8));b=asset(tmp_path,'B',np.full((2,4,3),80,dtype=np.uint8));b['role']='reference'
    c=asset(tmp_path,'C',np.full((2,4,3),70,dtype=np.uint8));bind_candidate(c,a,b)
    m=make_mask_contract(tmp_path,np.array([[1,1,0,0]]*2,dtype=np.uint8),a,purpose='EVAL_MASK',roi_ids=['wall'],provenance={'kind':'manual','annotator':'fixture'},relative='annotations/eval.npy')
    r=evaluate_reference(a,b,c,[pair()],case_root=tmp_path,geometry_status='pass',content_status='pass',task_scope='local',eval_mask=m)
    assert r['spill']['outside_L_mean_absolute_change']>0
    assert r['spill']['boundary_L_change_proxy']==pytest.approx(0)


def test_probe_cannot_be_enabled_by_boolean_or_unknown_executor(tmp_path):
    from hre.masks import validate_mask_probe
    with pytest.raises(HREError):validate_mask_probe(tmp_path,{'status':'passed'},executor())
    e=executor();e['adapter_version']='changed'
    with pytest.raises(HREError):validate_mask_probe(tmp_path,{'executor':executor(),'status':'passed'},e)


def test_v2_contract_rejects_extra_fields_and_missing_region_support(tmp_path):
    from hre.reference_contracts import validate_reference_spec
    s=spec();s['native_mask_supported']=True
    with pytest.raises(HREError):validate_reference_spec(s)


def ready_g1(tmp_path,scope='global'):
    from hre.reference_contracts import create_reference_case
    from hre.workflow import Controller
    from hre.cli import import_payload
    from test_hre_workflow import compose_payload
    from test_hre_protocol import diagnosis
    a=tmp_path/'sourceA.png';b=tmp_path/'sourceB.png'
    Image.new('RGB',(16,12),(40,40,40)).save(a);Image.new('RGB',(20,14),(80,80,80)).save(b)
    s=spec('G1');s['task_scope']=scope
    root=tmp_path/'g1';create_reference_case(a,b,s,root,spec_root=tmp_path)
    Controller(root).start()
    assert import_payload(root,diagnosis()).accepted
    assert import_payload(root,compose_payload()).accepted
    return root


def test_g1_exports_short_prompt_and_captures_frozen_text(tmp_path):
    from hre.reference_contracts import capture_g1_prompt
    from hre.desktop import export_task_bundle
    from hre.cli import current_request
    root=ready_g1(tmp_path)
    paired=capture_g1_prompt(root)
    out=export_task_bundle(current_request(root),tmp_path/'exports',case_root=root)
    assert set(p.name for p in (out/'editor').iterdir())=={'A.png','B.png','edit_prompt.txt'}
    assert (out/'editor/edit_prompt.txt').read_text()==paired['rendered_prompt']
    assert len(paired['rendered_prompt'].split())<=200
    targets=list(root.glob('tasks/*/reference_targets_v2.json'))
    assert len(targets)==1


def test_g1_rejects_more_than_three_or_excessively_long_priorities(tmp_path):
    from hre.reference_contracts import create_reference_case
    from hre.workflow import Controller
    from hre.cli import import_payload
    from test_hre_workflow import compose_payload
    from test_hre_protocol import diagnosis
    a=tmp_path/'A.png';b=tmp_path/'B.png'
    Image.new('RGB',(16,12),(40,40,40)).save(a);Image.new('RGB',(16,12),(80,80,80)).save(b)
    root=tmp_path/'g1';create_reference_case(a,b,spec('G1'),root,spec_root=tmp_path)
    Controller(root).start();assert import_payload(root,diagnosis()).accepted
    p=compose_payload();p['edit_prompt']='Brighten A. '+('tone '*161)
    result=import_payload(root,p)
    assert not result.accepted


def test_v2_cli_includes_operational_entrypoints():
    from hre.cli import build_parser
    args=build_parser().parse_args(['v2','evaluate','--case-root','/tmp/case'])
    assert args.command=='v2' and args.action=='evaluate'


def test_nonfinite_v2_region_rejected():
    from hre.reference_contracts import validate_reference_spec
    s=spec('G1');s['roi_pairs'][0]['prediction']['box']=[0,0,float('nan'),1]
    with pytest.raises(HREError):validate_reference_spec(s)


def fixture_probe(root,e):
    """Actual fixture bytes test evidence validation, never real editor capability."""
    from hre.storage import write_json
    from hre.models import now
    refs=[];observations=[]
    def ref(p):
        r=dict(path=p.relative_to(root).as_posix(),sha256=file_sha256(p));refs.append(r);return r
    for i,kind in enumerate(['simple_region','fine_boundary','preserve_negative']):
        folder=root/'capability_probes'/kind;folder.mkdir(parents=True)
        a=np.full((12,16,3),40,dtype=np.uint8);m=np.zeros((12,16),dtype=np.uint8)
        m[:,:8]=1
        if i==1:m[::2,8:]=1
        c=a.copy()
        if i!=2:c[m==1]=80
        for name,x in [('A',a),('B',a+40),('M',m*255),('C',c)]:Image.fromarray(x).save(folder/(name+'.png'))
        ar,br,mr,cr=[ref(folder/(k+'.png')) for k in ['A','B','M','C']]
        inputs={'A':ar['sha256'],'B':br['sha256'],'M':mr['sha256']}
        write_json(folder/'request.json',dict(executor=e,input_order=['A','B','M'],input_sha256=inputs,mask_mode='separate_mask_image',mask_encoder='white_allow',mask_applies_to='A'))
        request=ref(folder/'request.json')
        write_json(folder/'delivery.json',dict(request_sha256=request['sha256'],delivered_input_sha256=inputs,delivered=True))
        write_json(folder/'response.json',dict(output_sha256=cr['sha256'],fixture_only=True))
        observations.append(dict(kind=kind,observer='test fixture',observed_at=now(),steps=['No model called'],input_A=ar,input_B=br,mask=mr,output=cr,
                                 request=request,delivery=ref(folder/'delivery.json'),response=ref(folder/'response.json'),passed=True,notes='Synthetic protocol check only'))
    proof=dict(schema_version='mask_probe_v2',executor=e,status='passed',probe_env='fixture',mask_mode='separate_mask_image',mask_encoder='white_allow',
               accepts_A_and_B=True,accepts_mask=True,mask_applies_to='A',allow_edit_semantics='0_preserve_1_allow_edit',mask_size_rule='exact_A',observations=observations)
    p=root/'capability_probes/proof.json';write_json(p,proof)
    return ref(p),refs


def local_g1_and_g2(tmp_path):
    from hre.assets import pixel_hash
    from hre.masks import make_mask_contract
    from hre.reference_contracts import create_reference_case,capture_g1_prompt
    from hre.workflow import Controller
    from hre.cli import import_payload
    from test_hre_workflow import compose_payload
    from test_hre_protocol import diagnosis
    a=tmp_path/'A.png';b=tmp_path/'B.png'
    Image.new('RGB',(16,12),(40,40,40)).save(a);Image.new('RGB',(20,14),(80,80,80)).save(b)
    desc=dict(role='prediction',width=16,height=12,pixel_sha256=pixel_hash(Image.open(a)))
    arr=np.zeros((12,16),dtype=np.uint8);arr[:,:8]=1
    evaluation=make_mask_contract(tmp_path,arr,desc,purpose='EVAL_MASK',roi_ids=['wall'],provenance={'kind':'manual','annotator':'fixture'},relative='annotations/eval.npy')
    edit=make_mask_contract(tmp_path,arr,desc,purpose='EDIT_MASK',roi_ids=['wall'],provenance={'kind':'manual','annotator':'fixture'},relative='annotations/edit.npy')
    s=spec('G1');s.update(task_scope='local',local_mask_eligible=True,eval_mask=evaluation,files=[{k:evaluation[k] for k in ['path','sha256']}])
    g1=tmp_path/'g1';create_reference_case(a,b,s,g1,spec_root=tmp_path);Controller(g1).start()
    d=diagnosis();gap=d['global_gaps'].pop();gap.update(roi_pair_id='wall',region_in_a='left wall');d['local_gaps']=[gap]
    d['comparability'].append(dict(scope='roi_pair',roi_pair_id='wall',status='comparable',reasons=['same wall'],confidence=.9))
    p=compose_payload();p['edit_prompt']='Brighten only the left wall in A toward the wall appearance in B. Preserve A geometry and text.'
    p['edit_targets'][0].update(scope='region',region_in_a='left wall')
    assert import_payload(g1,d).accepted;assert import_payload(g1,p).accepted
    s['arm_id']='G2';s['paired_g1']=capture_g1_prompt(g1);s['edit_mask']=edit
    s['files'].append({k:edit[k] for k in ['path','sha256']})
    proof,files=fixture_probe(tmp_path,s['executor']);s['mask_probe']=proof;s['files']+=files
    g2=tmp_path/'g2';create_reference_case(a,b,s,g2,spec_root=tmp_path)
    return g1,g2


def test_g2_same_text_soft_mask_and_delivery_is_mandatory(tmp_path):
    from hre.cli import current_request
    from hre.desktop import export_task_bundle,import_candidate
    from hre.reference_contracts import capture_g1_prompt
    from hre.workflow import Controller
    from hre.reference_runtime import mask_transport
    g1,g2=local_g1_and_g2(tmp_path);Controller(g2).start();req=current_request(g2)
    exported=export_task_bundle(req,tmp_path/'exports',case_root=g2)
    assert set(p.name for p in (exported/'editor').iterdir())=={'A.png','B.png','M.png','edit_prompt.txt'}
    assert (exported/'editor/edit_prompt.txt').read_text()==capture_g1_prompt(g1)['rendered_prompt']
    transport=mask_transport(g2,req);assert transport['mask_mode']=='separate_mask_image'
    c=tmp_path/'output.png';Image.new('RGB',(16,12),(70,70,70)).save(c)
    Controller(g2).mark_submitted(req['task_id'])
    with pytest.raises(HREError,match='mask_delivery_missing'):
        import_candidate(g2,req['task_id'],c,dict(actual_generation_count=1,provider_order=0))


def test_probe_fixtures_cannot_qualify_real_mode(tmp_path):
    from hre.masks import validate_mask_probe
    p,_=fixture_probe(tmp_path,executor())
    assert validate_mask_probe(tmp_path,p,executor(),allow_fixture=True)['probe_env']=='fixture'
    with pytest.raises(HREError,match='skipped_capability'):validate_mask_probe(tmp_path,p,executor())


def test_g2_rejects_changed_executor_or_prompt(tmp_path):
    from hre.reference_contracts import prepare_reference_config
    from hre.storage import read_json,CaseStore
    g1,g2=local_g1_and_g2(tmp_path);cfg=read_json(g2/'config.json');inputs=CaseStore(g2).load()['inputs']
    cfg['reference_v2']['paired_g1']['rendered_prompt']+=' changed'
    with pytest.raises(HREError,match='paired_g1_mismatch'):prepare_reference_config(g2,cfg,inputs)


def delivery_fixture(root,request,image):
    from hre.reference_runtime import mask_transport
    from hre.storage import write_json
    from hre.models import now
    contract=mask_transport(root,request);folder=root/'observed_delivery';folder.mkdir(exist_ok=True)
    write_json(folder/'request.json',contract)
    write_json(folder/'response.json',dict(transport_request_sha256=file_sha256(folder/'request.json'),actual_generation_count=1,output_sha256=file_sha256(image)))
    def ref(p):return dict(path=p.relative_to(root).as_posix(),sha256=file_sha256(p))
    receipt={k:contract[k] for k in ['request_sha256','executor','mask_mode','mask_encoder','input_order','prompt_sha256']}
    receipt.update(schema_version='mask_delivery_v2',delivered_input_sha256=contract['input_sha256'],delivered=True,
                   observer='fixture, no model',observed_at=now(),transport_request=ref(folder/'request.json'),transport_response=ref(folder/'response.json'))
    write_json(folder/'receipt.json',receipt)
    return ref(folder/'receipt.json')


def test_g2_fixture_full_import_verification_and_roi_report(tmp_path):
    from hre.cli import current_request,import_candidate_manual,import_payload
    from hre.workflow import Controller
    from hre.reference_runtime import evaluate_reference_case
    from test_hre_workflow import verification
    g1,g2=local_g1_and_g2(tmp_path);Controller(g2).start();req=current_request(g2)
    out=tmp_path/'C.png';Image.new('RGB',(16,12),(70,70,70)).save(out)
    metadata=dict(actual_generation_count=1,provider_order=0,mask_delivery=delivery_fixture(g2,req,out),
                  model_observed={'ui_model_name':executor()['model_display_name'],'transport':executor()['transport'],'operator_steps':['Fixture only; no model']},executor_observation=observed_execution(g2,req,out))
    assert import_candidate_manual(g2,req['task_id'],out,metadata,'submitted').accepted
    assert import_payload(g2,verification()).accepted
    assert Controller(g2).state()['budget']['consumed']==1
    result=evaluate_reference_case(g2)
    assert result['simulation_only'] and not result['real_effect_validated']
    assert result['per_roi'][0]['attributes']['brightness']['delta']>0
    assert result['spill']['outside_L_mean_absolute_change']>0


def test_g2_forged_changed_prompt_in_delivery_rejected(tmp_path):
    from hre.cli import current_request
    from hre.reference_runtime import validate_mask_delivery
    from hre.storage import read_json,write_json
    from hre.workflow import Controller
    g1,g2=local_g1_and_g2(tmp_path);Controller(g2).start();req=current_request(g2)
    out=tmp_path/'C.png';Image.new('RGB',(16,12),(70,70,70)).save(out)
    ref=delivery_fixture(g2,req,out);p=g2/ref['path'];record=read_json(p);record['prompt_sha256']='0'*64;write_json(p,record)
    ref['sha256']=file_sha256(p)
    with pytest.raises(HREError,match='mask_delivery_invalid'):
        validate_mask_delivery(g2,req,dict(actual_generation_count=1,mask_delivery=ref),out)


def test_probe_requires_observed_local_change_not_just_passed_flags(tmp_path):
    from hre.masks import validate_mask_probe
    from hre.storage import read_json
    ref,_=fixture_probe(tmp_path,executor());p=read_json(tmp_path/ref['path'])
    first=p['observations'][0];first['output']=deepcopy(first['input_A'])
    with pytest.raises(HREError,match='probe_localization'):
        validate_mask_probe(tmp_path,p,executor(),allow_fixture=True)


def test_polygon_roi_matches_half_open_box(tmp_path):
    from hre.reference_evaluator import region_mask
    box=region_mask((6,8,3),region([0,0,.5,1]),tmp_path)
    poly=region_mask((6,8,3),dict(kind='polygon',points=[[0,0],[.5,0],[.5,1],[0,1]]),tmp_path)
    assert np.array_equal(box,poly)


def test_v2_execute_model_cannot_drift_from_frozen_executor(tmp_path):
    from hre.reference_contracts import create_reference_case
    from hre.cli import current_request,import_candidate_manual
    from hre.workflow import Controller
    from hre.models import now
    a=tmp_path/'A.png';b=tmp_path/'B.png';out=tmp_path/'C.png'
    for p,n in [(a,40),(b,80),(out,70)]:Image.new('RGB',(16,12),(n,n,n)).save(p)
    root=tmp_path/'g0';create_reference_case(a,b,spec('G0'),root,spec_root=tmp_path);Controller(root).start();request=current_request(root)
    observed=dict(ui_model_name='different model',exact_model_version=None,seed=None,observed_at=now(),transport='desktop_manual',operator_steps=['fixture'])
    result=import_candidate_manual(root,request['task_id'],out,dict(actual_generation_count=1,provider_order=0,model_observed=observed,executor_observation=observed_execution(root,request,out)),'submitted')
    assert not result.accepted and result.code=='executor_mismatch'


def test_local_contract_rejects_global_composition(tmp_path):
    from hre.reference_contracts import create_reference_case
    from hre.cli import import_payload
    from hre.workflow import Controller
    from test_hre_protocol import diagnosis
    from test_hre_workflow import compose_payload
    a=tmp_path/'A.png';b=tmp_path/'B.png'
    Image.new('RGB',(16,12),(40,40,40)).save(a);Image.new('RGB',(16,12),(80,80,80)).save(b)
    s=spec('G1');s['task_scope']='local'
    root=tmp_path/'g1';create_reference_case(a,b,s,root,spec_root=tmp_path);Controller(root).start()
    assert import_payload(root,diagnosis()).accepted
    result=import_payload(root,compose_payload())
    assert not result.accepted and result.code=='v2_prompt_contract'


def test_planned_t4_derivation_rejects_changed_model_with_same_array(tmp_path):
    from test_hre_evidence import offline_bundle
    from test_hre_protocol import diagnosis
    from hre.reference_contracts import create_reference_case
    from hre.cli import import_payload
    from hre.workflow import Controller
    from hre.storage import read_json,atomic_write
    from hre.evidence import EvidenceService,make_cache_key,validate_record
    from hre.masks import derive_t4_mask
    source=tmp_path/'offline'
    state,item,record=offline_bundle(source,'T4_SEGMENTATION',array=np.array([[0,1],[1,0]],dtype=np.uint8))
    s=spec('G1');s['tool_profile']=read_json(source/'config.json')['tool_profile']
    s['tool_profile']['available_tools']=['STATS','T4_SEGMENTATION']
    root=tmp_path/'case';create_reference_case(source/'A_original.png',source/'B_original.png',s,root,spec_root=tmp_path)
    Controller(root).start();d=diagnosis();d['tool_plan']=[dict(tool='T4_SEGMENTATION',roles=['prediction'],roi_pair_ids=['wall'],required=True,purpose='fixture planned segmentation')]
    assert import_payload(root,d).accepted
    actual=Controller(root).state();a=actual['inputs'][0];plan=actual['evidence_plan'][0]
    contract=EvidenceService(root)._contract(actual,plan,[a])
    record.update(case_id=actual['case_id'],case_revision=actual['case_revision'],cache_contract=contract,cache_key_sha256=make_cache_key(contract))
    record['binding'].update(inputs=[{k:a[k] for k in ['asset_id','role','sha256','width','height']}|{'candidate_id':None}],plan_item_id=plan['plan_item_id'],roi_pair_ids=['wall'])
    atomic_write(root/'annotations/t4.npy',(source/'raw.npy').read_bytes());record['assets'][0]['path']='annotations/t4.npy'
    validate_record(root,record,[a])
    out=derive_t4_mask(root,record,a,expected_cache_contract=contract,class_ids=[1],purpose='EDIT_MASK',roi_ids=['wall'],relative='annotations/edit.npy')
    assert out['provenance']['cache_contract']['model']==contract['model']
    changed=deepcopy(contract);changed['model']['revision']='changed'
    with pytest.raises(HREError,match='mask_provenance'):
        derive_t4_mask(root,record,a,expected_cache_contract=changed,class_ids=[1],purpose='EDIT_MASK',roi_ids=['wall'],relative='annotations/changed.npy')

def observed_execution(root,request,output,actual_executor=None):
    from hre.storage import read_json
    from hre.models import sha256_bytes,now
    from hre.prompts import build_context,render_stage
    from hre.reference_runtime import mask_transport
    actual_executor=deepcopy(actual_executor or read_json(root/'config.json')['reference_v2']['executor'])
    rendered=json.loads(render_stage('execute',build_context(root,request),case_root=root))['edit_prompt']
    inputs={k:a['sha256'] for k,a in zip(['A','B'],request['input_assets'])}
    transport=mask_transport(root,request)
    if transport:inputs=transport['input_sha256']
    return dict(kind='hre_executor_observation_v2',schema_version='ref_enhance_v2',executor=actual_executor,
                request_sha256=request['request_sha256'],prompt_sha256=sha256_bytes(rendered.encode()),input_sha256=inputs,
                output_sha256=file_sha256(output),actual_generation_count=1,observer='test fixture',observed_at=now(),steps=['No model called; test observation'])
