"""Independent-review regressions; every pixel/model observation here is synthetic."""
from copy import deepcopy
from pathlib import Path
import json
import subprocess
import sys
import shutil
import numpy as np
from PIL import Image
import pytest
from hre.models import HREError,file_sha256,sha256_bytes,now
from hre.storage import read_json,write_json,CaseStore
from test_hre_reference_v2 import spec,executor,local_g1_and_g2,delivery_fixture,observed_execution


def complete_arm(root,out,n=70):
    from hre.workflow import Controller
    from hre.cli import current_request,import_candidate_manual,import_payload
    from test_hre_protocol import diagnosis
    from test_hre_workflow import compose_payload,verification
    Controller(root).start();cfg=read_json(root/'config.json');e=cfg['reference_v2']['executor']
    if cfg['reference_v2']['arm_id']=='G1':
        assert import_payload(root,diagnosis()).accepted;assert import_payload(root,compose_payload()).accepted
    req=current_request(root);Image.new('RGB',(16,12),(n,n,n)).save(out)
    metadata=dict(actual_generation_count=1,provider_order=0,executor_observation=observed_execution(root,req,out),
                  model_observed={'ui_model_name':e['model_display_name'],'transport':e['transport'],'operator_steps':['Fixture only']})
    assert import_candidate_manual(root,req['task_id'],out,metadata,'submitted').accepted
    assert import_payload(root,verification()).accepted


def test_every_arm_rejects_actual_settings_drift(tmp_path):
    from hre.reference_contracts import create_reference_case
    from hre.workflow import Controller
    from hre.cli import current_request,import_candidate_manual
    a=tmp_path/'A.png';b=tmp_path/'B.png';out=tmp_path/'C.png'
    for p,n in [(a,40),(b,80),(out,70)]:Image.new('RGB',(16,12),(n,n,n)).save(p)
    s=spec('G0');s['executor']['settings']={'quality':'high'};root=tmp_path/'case'
    create_reference_case(a,b,s,root,spec_root=tmp_path);Controller(root).start();req=current_request(root)
    actual=deepcopy(s['executor']);actual['settings']['quality']='low'
    result=import_candidate_manual(root,req['task_id'],out,dict(actual_generation_count=1,provider_order=0,
          executor_observation=observed_execution(root,req,out,actual),model_observed={'ui_model_name':actual['model_display_name'],'transport':actual['transport']}),'submitted')
    assert not result.accepted and result.code=='executor_mismatch'


def test_raw_g2_cannot_omit_committed_transitive_delivery_graph(tmp_path):
    from hre.workflow import Controller
    from hre.cli import current_request
    from hre.reference_runtime import validate_mask_delivery
    from hre.assets import AssetRegistry
    from hre.protocol import TaskWriter
    g1,g2=local_g1_and_g2(tmp_path);Controller(g2).start();req=current_request(g2)
    out=tmp_path/'C.png';Image.new('RGB',(16,12),(70,70,70)).save(out)
    receipt=delivery_fixture(g2,req,out);validate_mask_delivery(g2,req,dict(mask_delivery=receipt,actual_generation_count=1),out)
    Controller(g2).mark_submitted(req['task_id']);binding={k:req[k] for k in ['case_id','case_revision','task_id','round']}
    binding.update(generation_id=req['payload']['generation_id'],prediction_sha256=req['input_assets'][0]['sha256'],reference_sha256=req['input_assets'][1]['sha256'])
    asset=AssetRegistry(g2).import_asset(out,'candidate','raw_fixture',{'assume_srgb':True,'canonicalizer_version':'hre_rgb8_v1'},candidate_binding=binding)
    obs=g2/'observation.json';write_json(obs,observed_execution(g2,req,out))
    payload=dict(generation_id=req['payload']['generation_id'],candidate_asset=asset,submitted_at=Controller(g2).state()['budget']['ledger'][0]['submitted_at'],
                 actual_generation_count=1,provider_order=0,selection_rule='first_complete_provider_order',extras=[],geometry_observations=[])
    done=TaskWriter(g2).commit_submission(req,payload,files=[obs],provenance={'ui_model_name':executor()['model_display_name'],'transport':executor()['transport']})
    result=Controller(g2).consume_done(done)
    assert not result.accepted


def test_accepted_g2_keeps_proof_after_handoff_cleanup_and_detects_proof_loss(tmp_path):
    from hre.workflow import Controller
    from hre.cli import current_request,import_candidate_manual
    g1,g2=local_g1_and_g2(tmp_path);Controller(g2).start();req=current_request(g2)
    out=tmp_path/'C.png';Image.new('RGB',(16,12),(70,70,70)).save(out)
    metadata=dict(actual_generation_count=1,provider_order=0,mask_delivery=delivery_fixture(g2,req,out),executor_observation=observed_execution(g2,req,out),
                  model_observed={'ui_model_name':executor()['model_display_name'],'transport':executor()['transport']})
    assert import_candidate_manual(g2,req['task_id'],out,metadata,'submitted').accepted
    accepted=read_json(g2/f'tasks/{req["task_id"]}/accepted/submission.json');done=read_json(g2/accepted['done_path'])
    typed=[]
    for item in done['artifacts']:
        if item['path'].endswith('.json'):
            obj=read_json(g2/item['path'])
            if obj.get('kind') in {'hre_mask_delivery_audit_v2','hre_executor_observation_v2'}:typed.append((item,obj))
    assert {obj['kind'] for _,obj in typed}=={'hre_mask_delivery_audit_v2','hre_executor_observation_v2'}
    shutil.rmtree(g2/'observed_delivery')
    for name in ['mask_delivery_v2.json','executor_observation_v2.json']:
        (g2/f'tasks/{req["task_id"]}/attempts/000'/name).unlink(missing_ok=True)
    assert CaseStore(g2).load()['workflow_state']=='WAIT_VERIFICATION'
    (g2/typed[0][0]['path']).unlink()
    with pytest.raises((HREError,OSError)):CaseStore(g2).load()


def test_r1_single_unpaired_success_cannot_promote(tmp_path):
    from hre.reference_contracts import create_reference_case
    from hre.reference_experiments import freeze_reference_run,prepare_run_arm,export_reference_blind,summarize_reference_run
    a=tmp_path/'A.png';b=tmp_path/'B.png';Image.new('RGB',(16,12),(40,40,40)).save(a);Image.new('RGB',(20,14),(80,80,80)).save(b)
    cases=[]
    for i in range(3):
        s=spec('G1');s['simulation_only']=False
        create_reference_case(a,b,s,tmp_path/f'source{i}',spec_root=tmp_path,manifest={'case_id':f'c{i}'})
        cases.append(dict(case_id=f'c{i}',scene_group_id=f's{i}',split='dev',source_case_root=f'source{i}',g2=None))
    write_json(tmp_path/'m.json',dict(schema_version='reference_run_manifest_v2',stage='R1',seed=1,code_commit_sha='c'*40,excluded_rater_ids=['operator'],cases=cases))
    run=tmp_path/'run';freeze_reference_run(tmp_path/'m.json',run)
    root=Path(prepare_run_arm(run,'c0','G0')['case_root']);complete_arm(root,tmp_path/'out.png')
    blind=tmp_path/'blind';export_reference_blind(run,blind);mapping=read_json(run/'private/blind_mapping_v2.json')
    code=next(m['code'] for m in mapping['rows'] if m['row']['case_id']=='c0' and m['row']['arm_id']=='G0')
    ratings=[dict(code=code,rater_id=r,kind='review',style='improved',content='pass',critical_defects=[],attributes={d:'improved' for d in ['brightness','color','tone','saturation']},notes='Synthetic decision reproduction') for r in ['r1','r2']]
    write_json(tmp_path/'ratings.json',dict(schema_version='reference_ratings_v2',blind_manifest_sha256=file_sha256(blind/'manifest.json'),raters=[{'rater_id':r,'independent':True} for r in ['r1','r2']],ratings=ratings,comparisons=[]))
    result=summarize_reference_run(run,tmp_path/'ratings.json')
    assert result['decision']=='PROBE' and not result['real_effect_validated']


def reviewed_run(tmp_path,*,content='pass',defects=None):
    from test_hre_reference_experiments import source_run
    from hre.reference_experiments import freeze_reference_run,prepare_run_arm,export_reference_blind
    manifest=source_run(tmp_path);run=tmp_path/'run';freeze_reference_run(manifest,run)
    for arm,n in [('G0',55),('G1',70)]:complete_arm(Path(prepare_run_arm(run,'one',arm)['case_root']),tmp_path/(arm+'.png'),n)
    blind=tmp_path/'blind';export_reference_blind(run,blind);mapping=read_json(run/'private/blind_mapping_v2.json');ratings=[]
    for item in mapping['rows']:
        for rater in ['r1','r2']:
            ratings.append(dict(code=item['code'],rater_id=rater,kind='review',style='improved',content=content,critical_defects=defects or [],
                                attributes={d:'improved' for d in ['brightness','color','tone','saturation']},notes='Synthetic independent verdict'))
    file=tmp_path/'ratings.json';write_json(file,dict(schema_version='reference_ratings_v2',blind_manifest_sha256=file_sha256(blind/'manifest.json'),raters=[{'rater_id':r,'independent':True} for r in ['r1','r2']],ratings=ratings,comparisons=[]))
    return run,file


def test_independent_content_failure_invalidates_final_roi_and_h3(tmp_path):
    from hre.reference_experiments import summarize_reference_run
    run,ratings=reviewed_run(tmp_path,content='fail')
    result=summarize_reference_run(run,ratings)
    assert all(r['attributes']['n_evaluable']==0 for r in result['rows'])
    assert all(r['status']=='unknown' for r in result['H3'])
    assert all(r['workflow_attributes']['n_evaluable']>0 for r in result['rows'])


def test_serious_defects_have_explicit_validated_categories(tmp_path):
    from hre.reference_experiments import summarize_reference_run
    run,ratings=reviewed_run(tmp_path,content='fail',defects=['face identity changed'])
    with pytest.raises(HREError,match='ratings_invalid'):summarize_reference_run(run,ratings)
    value=read_json(ratings)
    for r in value['ratings']:r['critical_defects']=[dict(category='identity',severity='critical',observation='face identity changed')]
    write_json(ratings,value)
    assert summarize_reference_run(run,ratings)['decision']=='STOP'


def test_h2_has_separate_qualified_decision(tmp_path):
    from hre.reference_experiments import summarize_reference_run
    run,ratings=reviewed_run(tmp_path)
    result=summarize_reference_run(run,ratings)
    assert result['H2_decision']['decision']=='SKIPPED'
    assert result['H2_decision']['qualified_pairs']==0
    assert result['n_mask_capable']==0 and result['n_mask_skipped']==1


@pytest.mark.parametrize('count,preference,expected',[(5,'win','PROBE'),(6,'loss','STOP'),(6,'win','GO')])
def test_h2_decision_requires_six_pairs_and_two_observed_local_benefits(count,preference,expected):
    from hre.reference_experiments import _h2_decision
    rows=[];preferences=[]
    for i in range(count):
        for arm in ['G1','G2']:
            rows.append(dict(case_id=str(i),arm_id=arm,status='candidate_ready',review_unknown=False,joint_success=True,
                             review={'content':'pass','critical_defects':[]},
                             attributes={'per_roi':[{'roi_pair_id':'wall','attributes':{'brightness':{'after':1 if arm=='G2' else 2}}}],'spill':None}))
        preferences.append({'case_id':str(i),'result':preference})
    result=_h2_decision(rows,preferences,n_eligible=count,n_capable=count)
    assert result['decision']==expected and result['qualified_pairs']==count


@pytest.mark.skipif(sys.platform!='linux',reason='Linux peak-RSS contract is measured in KiB')
def test_three_megapixel_attribute_and_spill_memory_is_bounded():
    script='''import json,resource,numpy as np
from hre.reference_evaluator import display_attributes,_spill
a=np.full((1500,2000,3),40,dtype=np.uint8);b=np.full_like(a,80);c=np.full_like(a,70)
m=np.zeros((1500,2000),dtype=bool);m[:,:1000]=True
s=display_attributes(a[m]);v=_spill(a,c,m)
print(json.dumps({'rss':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'L':s['L_mean'],'spill':v['outside_L_mean_absolute_change']}))
'''
    process=subprocess.run([sys.executable,'-c',script],capture_output=True,text=True,check=True)
    result=json.loads(process.stdout)
    assert result['rss']<300*1024
    assert 10<result['L']<25 and result['spill']>0


def test_imported_mask_contract_requires_provenance(tmp_path):
    from hre.masks import make_mask_contract,validate_mask
    from test_hre_stats import asset
    a=asset(tmp_path);mask=make_mask_contract(tmp_path,np.ones((2,2),dtype=np.uint8),a,purpose='EVAL_MASK',roi_ids=['wall'],
                                            provenance={'kind':'manual','annotator':'fixture'},relative='annotations/eval.npy')
    mask['provenance']={}
    with pytest.raises(HREError,match='mask_provenance'):validate_mask(tmp_path,mask,a)


def test_v2_execute_template_requires_versioned_context(tmp_path):
    from hre.reference_contracts import create_reference_case
    from hre.workflow import Controller
    from hre.cli import current_request
    from hre.prompts import build_context,render_stage
    from jinja2 import UndefinedError
    a=tmp_path/'A.png';b=tmp_path/'B.png'
    for p in [a,b]:Image.new('RGB',(16,12),(40,40,40)).save(p)
    root=tmp_path/'case';create_reference_case(a,b,spec('G0'),root,spec_root=tmp_path)
    Controller(root).start();context=build_context(root,current_request(root))
    assert json.loads(render_stage('execute',context,case_root=root))['reference_v2_contract']=={
        'schema_version':'ref_enhance_v2','minimum_engine_version':'0.2.0'}
    context.pop('reference_v2_contract')
    with pytest.raises(UndefinedError):render_stage('execute',context,case_root=root)


def test_v2_journal_requires_accepted_done_digest(tmp_path):
    from hre.reference_contracts import create_reference_case
    a=tmp_path/'A.png';b=tmp_path/'B.png'
    for p in [a,b]:Image.new('RGB',(16,12),(40,40,40)).save(p)
    root=tmp_path/'case';create_reference_case(a,b,spec('G0'),root,spec_root=tmp_path)
    complete_arm(root,tmp_path/'C.png')
    for path in sorted((root/'transactions').glob('*.json')):
        tx=read_json(path)
        if tx['accepted_submission']:
            tx['accepted_submission'].pop('done_sha256');write_json(path,tx);break
    with pytest.raises(HREError,match='protocol_integrity_error'):CaseStore(root).load()
