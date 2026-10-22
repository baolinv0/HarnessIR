"""Real Controller integration; synthetic images do not establish editor quality."""
import json
from copy import deepcopy
from pathlib import Path
from PIL import Image
import pytest
from hre.models import HREError
from hre.reference_contracts import create_reference_case
from hre.workflow import Controller
from hre.cli import import_payload, current_request
from test_hre_reference_v2 import spec
from test_hre_protocol import diagnosis
from test_hre_workflow import compose_payload


def model_case(tmp_path, arm='G1', profile_id='qwen21', compiler='direct', compose=True, two_regions=False):
    a=tmp_path/'A.png'; b=tmp_path/'B.png'
    Image.new('RGB',(16,12),(40,40,40)).save(a)
    Image.new('RGB',(20,14),(80,80,80)).save(b)
    value=spec(arm)
    if two_regions:
        background=deepcopy(value['roi_pairs'][0]);background['roi_pair_id']='background'
        background['semantic_label']='background';value['roi_pairs'].append(background)
    value['model_aware']={'profile_id':profile_id,'strategy':'native' if arm=='G0' else 'model_aware','compiler':compiler}
    root=tmp_path/'case'
    create_reference_case(a,b,value,root,spec_root=tmp_path)
    controller=Controller(root); controller.start()
    if arm=='G1':
        assert import_payload(root,diagnosis()).accepted
        if compose:assert import_payload(root,compose_payload()).accepted
    return root,controller


@pytest.mark.parametrize('arm',['G0','G1'])
def test_compile_wait_has_no_pending_generation(tmp_path,arm):
    root,controller=model_case(tmp_path,arm)
    state=controller.state()
    assert state['workflow_state']=='PAUSED'
    assert state['pause_reason']=='condition_compilation_required'
    assert state['resume_state']=='WAIT_EXECUTION'
    assert state['pending_task'] is None
    assert state['budget']['reserved']==state['budget']['consumed']==0
    with pytest.raises(HREError):controller.resume()


def test_model_aware_g2_is_explicitly_unsupported():
    from hre.reference_contracts import validate_reference_spec
    value=spec('G2')
    value['model_aware']={'profile_id':'qwen21','strategy':'model_aware','compiler':'direct'}
    with pytest.raises(HREError,match='model_aware_g2_unsupported'):validate_reference_spec(value)


@pytest.mark.parametrize('arm,strategy',[('G0','shared'),('G0','model_aware'),('G1','native')])
def test_strategy_arm_mismatch_is_rejected_before_case_creation(tmp_path,arm,strategy):
    value=spec(arm)
    value['model_aware']={'profile_id':'qwen21','strategy':strategy,'compiler':'direct'}
    root=tmp_path/'case'
    with pytest.raises(HREError,match='model_aware_arm_strategy'):
        create_reference_case(tmp_path/'A.png',tmp_path/'B.png',value,root,spec_root=tmp_path)
    assert not root.exists()


def compiled_result(request, text='A has brighter supported midtones and unchanged scene content.'):
    return dict(schema_version='model_condition_result_v1',request_id=request['request_id'],
                profile_id=request['profile_id'],status='ok',edit_prompt=text,
                compiler_observation={'compiler_id':'direct','compiler_version':None,'settings':{},'calls':0},
                canvas=request['canvas'])


def test_import_compiled_condition_creates_one_exact_execution(tmp_path):
    from hre.condition_handoff import export_condition_request
    from hre.desktop import export_task_bundle
    root,controller=model_case(tmp_path)
    revision=controller.state()['revision']
    out=export_condition_request(root,tmp_path/'compiler')
    request=json.loads((out/'condition_request.json').read_text())
    assert controller.state()['revision']==revision
    result=compiled_result(request)
    path=tmp_path/'result.json';path.write_text(json.dumps(result))
    state=controller.accept_compiled_condition(path)
    assert state['workflow_state']=='WAIT_EXECUTION'
    assert state['budget']['reserved']==1
    bundle=export_task_bundle(current_request(root),tmp_path/'editor',case_root=root)
    assert (bundle/'editor/edit_prompt.txt').read_text()==result['edit_prompt']
    assert json.loads((bundle/'editor/condition.json').read_text())['edit_prompt']==result['edit_prompt']
    with pytest.raises(HREError):controller.accept_compiled_condition(path)
    assert controller.state()['budget']['reserved']==1


def test_foreign_condition_cannot_advance_case(tmp_path):
    from hre.condition_handoff import export_condition_request
    root,controller=model_case(tmp_path)
    out=export_condition_request(root,tmp_path/'compiler')
    result=compiled_result(json.loads((out/'condition_request.json').read_text()))
    result['request_id']='foreign_request'
    path=tmp_path/'result.json';path.write_text(json.dumps(result))
    with pytest.raises(HREError):controller.accept_compiled_condition(path)
    assert controller.state()['pending_task'] is None
    assert controller.state()['budget']['reserved']==0


def test_native_json_reaches_existing_execute_verify_chain_unchanged(tmp_path):
    from hre.condition_handoff import export_condition_request
    from hre.desktop import export_task_bundle
    from hre.cli import import_candidate_manual
    from test_hre_reference_v2 import observed_execution,executor
    from test_hre_workflow import verification
    root,controller=model_case(tmp_path,profile_id='fibo2_dev',compiler='native')
    out=export_condition_request(root,tmp_path/'compiler')
    request=json.loads((out/'condition_request.json').read_text())
    assert request['intent']['roi_pairs'][0]['prediction']!=request['intent']['roi_pairs'][0]['reference']
    assert request['intent']['reference_statistics'][0]['status']=='measured'
    assert request['intent']['region_relations']==[]
    text='{"edit_instruction": "Adjust <image_1> using only the appearance of <image_2>", "short_description": "The same scene with softer highlights"}'
    result=compiled_result(request,text)
    result['compiler_observation'].update(compiler_id='bria-vgl',calls=1)
    path=tmp_path/'result.json';path.write_text(json.dumps(result))
    controller.accept_compiled_condition(path)
    req=current_request(root)
    bundle=export_task_bundle(req,tmp_path/'editor',case_root=root)
    assert (bundle/'editor/edit_prompt.txt').read_text()==text
    assert json.loads((bundle/'editor/condition.json').read_text())['condition_kind']=='vgl_edit'
    image=tmp_path/'C.png';Image.new('RGB',(16,12),(60,60,60)).save(image)
    meta=dict(actual_generation_count=1,provider_order=0,executor_observation=observed_execution(root,req,image),
              model_observed={'ui_model_name':executor()['model_display_name'],'transport':executor()['transport'],'operator_steps':['Fixture only; no model']})
    imported=import_candidate_manual(root,req['task_id'],image,meta,'submitted')
    assert imported.accepted,imported
    assert import_payload(root,verification()).accepted
    assert controller.state()['workflow_state']=='COMPLETED'
    assert controller.state()['budget']['consumed']==1


def relation():
    return dict(subject_roi_id='wall',object_roi_id='background',attribute='relative_brightness',
                target='Keep the wall slightly brighter than the background without flattening the scene.',source='visual_observation')


def test_supported_region_relation_is_planned_and_frozen(tmp_path):
    from hre.condition_handoff import export_condition_request
    from hre.prompts import build_context,render_stage
    root,controller=model_case(tmp_path,compose=False,two_regions=True)
    rendered=json.loads(render_stage('compose',build_context(root,current_request(root)),case_root=root))
    assert 'region_relations' in rendered['instructions']
    payload=compose_payload();payload['region_relations']=[relation()]
    assert import_payload(root,payload).accepted
    out=export_condition_request(root,tmp_path/'compiler')
    intent=json.loads((out/'condition_request.json').read_text())['intent']
    assert intent['region_relations']==payload['region_relations']
    assert intent['region_relations_status']=='annotated'


@pytest.mark.parametrize('object_id',['unknown','wall'])
def test_region_relation_requires_two_distinct_frozen_rois(tmp_path,object_id):
    root,controller=model_case(tmp_path,compose=False,two_regions=True)
    target=relation();target['object_roi_id']=object_id
    payload=compose_payload();payload['region_relations']=[target]
    result=import_payload(root,payload)
    assert not result.accepted
    assert result.code=='invalid_region_relation'
    assert controller.state()['budget']['reserved']==0
