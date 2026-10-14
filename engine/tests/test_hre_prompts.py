import json
from pathlib import Path
import pytest
from PIL import Image


def case_and_request(tmp_path,stage='diagnose',payload=None,include_candidate=False):
    from hre.assets import create_case, AssetRegistry
    from hre.models import request_hash
    from hre.storage import read_json,write_json
    a,b=tmp_path/'a.png',tmp_path/'b.png'
    Image.new('RGB',(16,12),(30,40,50)).save(a)
    Image.new('RGB',(24,18),(130,140,150)).save(b)
    root=tmp_path/'case'
    state=create_case(a,b,{'case_id':'prompt_case'},{'profile_id':'agent_adaptive','assume_srgb':True,'reference_usable':'usable','protected_content':['A text and identity'],'reference_limitations':['unaligned; different window light']},root)
    assets=state['inputs']
    if include_candidate:
        c=tmp_path/'c.png';Image.new('RGB',(16,12),(70,80,90)).save(c)
        binding={'case_id':state['case_id'],'case_revision':state['case_revision'],'task_id':'edit_task','round':0,'generation_id':'gen_0','prediction_sha256':assets[0]['sha256'],'reference_sha256':assets[1]['sha256']}
        assets=assets+[AssetRegistry(root).import_asset(c,'candidate','cand_0',{'assume_srgb':True,'canonicalizer_version':'hre_rgb8_v1'},candidate_binding=binding)]
    req={'schema_version':'ref_enhance_v1','case_id':state['case_id'],'case_revision':state['case_revision'],'task_id':'render_task','stage':stage,'round':0,'attempt':0,'state_revision_issued':1,'config_sha256':state['config_sha256'],'input_assets':assets,'prompt_version':'ref_enhance_v1.0','payload':payload or {'comparison_policy_id':'rendering_v1','tool_profile_id':'offline','available_tools':['STATS'],'roi_manifest_path':None,'roi_manifest_sha256':None}}
    req['request_sha256']=request_hash(req)
    directory=root/'tasks'/'render_task'/'attempts'/'000';directory.mkdir(parents=True)
    write_json(directory/'request.json',req)
    write_json(directory/'adapter_context.json', {'model_observed':{'ui_model_name':'unknown','exact_model_version':None,'seed':None,'observed_at':'2026-10-13T00:00:00Z','transport':'desktop_manual','operator_steps':[]},'session_id':None})
    return root,req


def test_real_context_and_strict_json_rendering(tmp_path):
    from hre.prompts import build_context, render_stage
    from jinja2 import UndefinedError
    root,req=case_and_request(tmp_path)
    context=build_context(root,req)
    assert context['available_tools']==['STATS']
    assert context['result_schema']['$id']=='diagnosis.schema.json'
    assert context['model_observed']['ui_model_name']=='unknown'
    parsed=json.loads(render_stage('diagnose',context))
    assert [x['label'] for x in parsed['image_bindings']]==['A','B']
    assert parsed['response_identity']['request_sha256']==req['request_sha256']
    del context['available_tools']
    with pytest.raises(UndefinedError):render_stage('diagnose',context)


def test_verifier_context_uses_frozen_policy_and_never_tools(tmp_path):
    from hre.prompts import build_context,render_stage,PROTECTED_RUBRIC
    from test_hre_protocol import current_request
    from test_hre_workflow import ready_execute,execute_image
    root,_=case_and_request(tmp_path)
    ready_execute(root);execute_image(root,tmp_path);req=current_request(root)
    result=json.loads(render_stage('verify',build_context(root,req)))
    assert result['input_context']=={'protected_content':PROTECTED_RUBRIC+['A text and identity'],'reference_limitations':['unaligned; different window light']}
    assert set(result['input_context']).isdisjoint({'geometry','evidence_summary','edit_prompt','diagnosis'})
    assert [x['label'] for x in result['image_bindings']]==['A','B','C']


def test_render_all_templates_quotes_and_binding_rejection(tmp_path):
    from hre.prompts import build_context,render_stage
    from hre.models import HREError
    root,req=case_and_request(tmp_path)
    base=build_context(root,req)
    for stage,extra in [('compose',{'diagnosis':{},'evidence_summary':[]}),('execute',{'edit_prompt':'Lift A\'s midtones.\nPreserve "exact text".'}),('direct_ref',{})]:
        result=json.loads(render_stage(stage,{**base,**extra}))
        assert len(result['image_bindings'])==2
    refined={**base,'image_bindings':base['image_bindings']+[{'label':'C','asset_id':'c','canonical_sha256':'c'*64}],'previous_edit_prompt':'Lift A.', 'verification':{}, 'source_round':0}
    assert json.loads(render_stage('refine',refined))['input_context']['source_round']==0
    with pytest.raises(HREError):render_stage('execute',{**refined,'edit_prompt':'Lift A.'})


def test_real_image_tamper_and_wrong_request_identity_rejected(tmp_path):
    from hre.prompts import build_context
    from hre.models import HREError,request_hash
    root,req=case_and_request(tmp_path)
    req['case_id']='other';req['request_sha256']=request_hash(req)
    with pytest.raises(HREError):build_context(root,req)
    req['case_id']='prompt_case';req['request_sha256']=request_hash(req)
    (root/req['input_assets'][0]['path']).write_bytes(b'not image')
    with pytest.raises(HREError):build_context(root,req)


def test_compose_uses_only_real_frozen_planned_stats_and_refine_bound_feedback(tmp_path):
    from hre.workflow import Controller
    from hre.protocol import TaskWriter
    from hre.prompts import build_context,render_stage
    from test_hre_protocol import make_case,diagnosis,current_request
    from test_hre_workflow import send,compose_payload,execute_image,verification
    root=make_case(tmp_path);controller=Controller(root);controller.start()
    diag=diagnosis();diag['tool_plan']=[{'tool':'STATS','roles':['prediction','reference'],'purpose':'Observe rendering','roi_pair_ids':[],'required':True}]
    send(root,diag)
    assert controller.state()['workflow_state']=='WAIT_EVIDENCE'
    controller.collect_evidence()
    req=current_request(root);ctx=build_context(root,req)
    assert ctx['diagnosis']==diag and ctx['evidence_summary']
    assert all(record['tool_id']=='STATS' for record in ctx['evidence_summary'])
    assert render_stage('compose',ctx)==render_stage('compose',build_context(root,req))
    comp=compose_payload();comp['evidence_ids']=[record['evidence_id'] for record in ctx['evidence_summary']]
    send(root,comp);execute_image(root,tmp_path)
    send(root,verification('unchanged',retry_focus=['brighten more']))
    refine=current_request(root);refined=json.loads(render_stage('refine',build_context(root,refine)))
    assert set(refined['input_context'])=={'previous_edit_prompt','verification','source_round'}
    assert refined['input_context']['previous_edit_prompt']==comp['edit_prompt']
    assert refined['input_context']['source_round']==0


def test_missing_real_stage_context_and_refine_wrong_candidate_reject(tmp_path):
    from hre.prompts import build_context
    from hre.models import HREError,request_hash
    root,req=case_and_request(tmp_path,'compose',{'diagnosis_task_id':'missing','diagnosis_response_sha256':'a'*64,'evidence_snapshot_path':'evidence/missing.json','evidence_snapshot_sha256':'b'*64})
    with pytest.raises(HREError):build_context(root,req)


def test_refine_rejects_feedback_for_a_different_actual_candidate(tmp_path):
    from hre.prompts import build_context
    from hre.models import HREError,request_hash
    from hre.assets import AssetRegistry
    from test_hre_protocol import make_case,current_request
    from test_hre_workflow import ready_execute,execute_image,send,verification
    root=make_case(tmp_path);ready_execute(root);execute_image(root,tmp_path);send(root,verification('unchanged',retry_focus=['brighten more']))
    req=current_request(root)
    image=tmp_path/'different.png';Image.new('RGB',(16,12),(99,44,55)).save(image)
    original=req['input_assets'][2]
    req['input_assets'][2]=AssetRegistry(root).import_asset(image,'candidate','other_actual',{'assume_srgb':True},candidate_binding=original['candidate_binding'])
    req['request_sha256']=request_hash(req)
    with pytest.raises(HREError):build_context(root,req)


def test_refine_rejects_previous_text_not_used_for_actual_candidate(tmp_path):
    from hre.prompts import build_context
    from hre.models import HREError,request_hash
    from test_hre_protocol import make_case,current_request
    from test_hre_workflow import ready_execute,execute_image,send,verification
    root=make_case(tmp_path);ready_execute(root);execute_image(root,tmp_path);send(root,verification('unchanged',retry_focus=['brighten more']))
    req=current_request(root);req['payload']['previous_edit_prompt']='Different text that was never submitted.';req['request_sha256']=request_hash(req)
    with pytest.raises(HREError):build_context(root,req)


@pytest.mark.parametrize('text',[
    'Edit Image C. Keep original exposure and color. Save output to /tmp/edit.png and return JSON.',
    'Copy the person from Image B into A. Edit Image C. Keep original exposure and color. Return JSON.',
    'Preserve the original brightness and colors of A.',
    'Use Image C as the editing source.',
])
def test_edit_contract_known_forbidden_instructions(text):
    from hre.prompts import validate_edit_contract
    from hre.models import HREError
    with pytest.raises(HREError):validate_edit_contract('compose',{'edit_prompt':text})


@pytest.mark.parametrize('text',[
    "Edit Image A. Do not edit Image C. Do not copy B's objects or textures. Brighten comparable midtones.",
    'Start from original A. Reduce excessive saturation and highlight clipping while preserving geometry.',
    'Brighten image A while preserving its content.',
])
def test_edit_contract_correct_negations_and_supported_reduction(text):
    from hre.prompts import validate_edit_contract
    validate_edit_contract('refine',{'edit_prompt':text})


def test_verify_rejects_candidate_payload_id_and_source_task_mismatch(tmp_path):
    from hre.prompts import build_context
    from hre.models import HREError,request_hash
    from test_hre_protocol import make_case,current_request
    from test_hre_workflow import ready_execute,execute_image
    root=make_case(tmp_path);ready_execute(root);execute_image(root,tmp_path);req=current_request(root)
    req['payload']['candidate_id']='another_master';req['request_sha256']=request_hash(req)
    with pytest.raises(HREError):build_context(root,req)
    req=current_request(root);req['input_assets'][2]['candidate_binding']['task_id']='nonexistent_source';req['request_sha256']=request_hash(req)
    with pytest.raises(HREError):build_context(root,req)


def test_derived_candidate_keeps_master_identity_through_verify_and_refine(tmp_path):
    from hre.assets import create_case
    from hre.workflow import Controller
    from hre.desktop import import_candidate
    from hre.prompts import build_context
    from test_hre_protocol import current_request
    from test_hre_workflow import ready_execute,send,verification
    a,b=tmp_path/'scaled_a.png',tmp_path/'scaled_b.png'
    Image.new('RGB',(16,12),(30,40,50)).save(a);Image.new('RGB',(24,18),(110,120,130)).save(b)
    root=tmp_path/'scaled_case';create_case(a,b,{'case_id':'scaled_case'},{'assume_srgb':True,'reference_usable':'usable','geometry_policy':{'mode':'aspect_preserving_resize'}},root)
    ready_execute(root);controller=Controller(root);execute=current_request(root);controller.mark_submitted(execute['task_id'])
    raw=tmp_path/'scaled_output.png';Image.new('RGB',(32,24),(70,80,90)).save(raw)
    done=import_candidate(root,execute['task_id'],raw,{'actual_generation_count':1,'provider_order':0})
    assert controller.consume_done(done).accepted
    verify=current_request(root)
    assert verify['input_assets'][2]['asset_id']!=verify['payload']['candidate_id']
    assert build_context(root,verify)['image_bindings'][2]['asset_id']==verify['input_assets'][2]['asset_id']
    send(root,verification('unchanged',retry_focus=['brighten more']))
    refine=current_request(root)
    assert build_context(root,refine)['source_round']==0


def test_approved_direct_and_execute_prefixes_pass_edit_contract(tmp_path):
    from hre.prompts import build_context,render_stage,validate_edit_contract
    root,req=case_and_request(tmp_path)
    context=build_context(root,req)
    direct=json.loads(render_stage('direct_ref',context))
    validate_edit_contract('direct_ref',direct)
    execute=json.loads(render_stage('execute',{**context,'edit_prompt':'Brighten comparable midtones in A. Do not copy any B objects.'}))
    validate_edit_contract('execute',execute)


def test_negated_color_change_is_still_a_positive_original_rendering_freeze():
    from hre.prompts import validate_edit_contract
    from hre.models import HREError
    with pytest.raises(HREError):validate_edit_contract('compose',{'edit_prompt':'Brighten A, but do not change its original colors or exposure.'})
