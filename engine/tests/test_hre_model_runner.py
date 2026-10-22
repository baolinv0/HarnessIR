"""Runner orchestration tests; no learned model is called."""
import json
import sys
from pathlib import Path
import pytest
from hre.models import HREError, file_sha256
from hre.storage import read_json, write_json
from hre.workflow import Controller
from test_hre_condition_handoff import model_case


def workers():
    return {'schema_version':'hre_workers_v1','workers':{'stage':[sys.executable,'-m','hre.model_workers'],
            'execute':['external-editor']},'timeout_seconds':60}


def test_export_and_direct_stage_check_do_not_advance_controller(tmp_path):
    from hre.model_runner import export_worker_request, run_stage
    root,controller=model_case(tmp_path)
    before=file_sha256(root/'state.json')
    request=export_worker_request(root,tmp_path/'export')
    result=run_stage(request,workers(),tmp_path/'check')
    assert result['validated'] and result['case_advanced'] is False
    assert read_json(Path(result['response_path']))['profile_id']=='qwen21'
    assert file_sha256(root/'state.json')==before


def test_full_runner_compiles_without_external_call_then_uses_editor_once(tmp_path,monkeypatch):
    from hre.model_runner import run_case
    import hre.model_workers
    root,controller=model_case(tmp_path)
    calls=[]
    def fail_editor(command,request_path,response_path,*,timeout):
        calls.append(read_json(request_path)['kind'])
        raise HREError('worker_failed','Simulated process failure')
    monkeypatch.setattr(hre.model_workers,'run_worker',fail_editor)
    with pytest.raises(HREError,match='worker_failed'):run_case(root,workers())
    assert calls==['execute']
    state=controller.state()
    assert state['workflow_state']=='PAUSED' and state['pause_reason']=='worker_submission_unknown'
    assert state['budget']['reserved']==1 and state['budget']['consumed']==0
    run_case(root,workers())
    assert calls==['execute']


def test_runner_configuration_cannot_change_between_invocations(tmp_path):
    from hre.model_runner import run_case
    root,controller=model_case(tmp_path)
    run_case(root,workers(),max_steps=1)
    changed=workers();changed['workers']['execute']=['another-editor']
    with pytest.raises(HREError,match='worker_config_changed'):run_case(root,changed)


def test_stage_debug_refuses_unaccounted_generation(tmp_path):
    from hre.model_runner import export_worker_request,run_case,run_stage
    root,controller=model_case(tmp_path)
    run_case(root,workers(),max_steps=1)
    request=export_worker_request(root,tmp_path/'export')
    with pytest.raises(HREError,match='stage_generation_requires_controller'):
        run_stage(request,workers(),tmp_path/'debug')
    assert controller.state()['budget']['consumed']==0


def test_modified_stage_export_rejected(tmp_path):
    from hre.model_runner import export_worker_request,run_stage
    root,_=model_case(tmp_path)
    path=export_worker_request(root,tmp_path/'export')
    value=read_json(path);value['request']['brief']='changed'
    write_json(path,value)
    with pytest.raises(HREError,match='worker_request_changed'):
        run_stage(path,workers(),tmp_path/'debug')


def test_real_subprocess_full_flow_and_independent_stage_check(tmp_path):
    import importlib.util
    path=Path(__file__).resolve().parents[1]/'examples/model_aware_demo.py'
    spec=importlib.util.spec_from_file_location('model_aware_fixture',path)
    demo=importlib.util.module_from_spec(spec);spec.loader.exec_module(demo)
    report=demo.run_demo(tmp_path/'demo')
    assert report['actual_model_called'] is False
    assert report['stage_check']['case_advanced'] is False
    assert report['full_run']['workflow_state']=='COMPLETED'
    assert report['full_run']['success']
    assert report['full_run']['budget']['consumed']==1
    from hre.stage_comparison import compare_stages
    html=compare_stages([tmp_path/'demo/diagnose_check'],tmp_path/'comparison.html').read_text()
    assert 'data:image/png;base64,' in html
    assert 'A/B image bytes match' in html
    assert 'SYNTHETIC' in html


def test_failed_worker_response_cannot_be_accepted_on_restart(tmp_path,monkeypatch):
    from hre.model_runner import run_case
    from hre.reference_contracts import create_reference_case
    from test_hre_reference_v2 import spec
    from test_hre_protocol import diagnosis
    from PIL import Image
    import hre.model_workers
    for name in ('A','B'):Image.new('RGB',(16,12),(30,40,50)).save(tmp_path/(name+'.png'))
    root=tmp_path/'case';create_reference_case(tmp_path/'A.png',tmp_path/'B.png',spec('G1'),root,spec_root=tmp_path)
    calls=[]
    def failed(command,request_path,response_path,*,timeout):
        calls.append(1);write_json(response_path,{'payload':diagnosis()})
        write_json(response_path.with_suffix('.invocation.json'),{'status':'failed'})
        raise HREError('worker_exit_error','Failed after writing response')
    monkeypatch.setattr(hre.model_workers,'run_worker',failed)
    with pytest.raises(HREError,match='worker_exit_error'):run_case(root,workers())
    with pytest.raises(HREError,match='worker_call_uncertain'):run_case(root,workers())
    assert len(calls)==1
    assert Controller(root).state()['workflow_state']=='WAIT_DIAGNOSIS'


def test_vlm_runtime_model_is_frozen_without_credentials(tmp_path,monkeypatch):
    from hre.model_runner import run_case
    root,_=model_case(tmp_path)
    monkeypatch.setenv('HRE_VLM_MODEL','vlm-one')
    monkeypatch.setenv('HRE_VLM_API_KEY','do-not-store-me')
    run_case(root,workers(),max_steps=1)
    frozen=(root/'worker_runs/config.json').read_text()
    assert 'vlm-one' in frozen and 'do-not-store-me' not in frozen
    monkeypatch.setenv('HRE_VLM_MODEL','vlm-two')
    with pytest.raises(HREError,match='worker_config_changed'):run_case(root,workers())


def test_late_editor_result_after_cancel_is_accounted_and_preserved(tmp_path,monkeypatch):
    from hre.model_runner import run_case
    from test_hre_reference_v2 import observed_execution,executor
    from PIL import Image
    import hre.model_workers
    root,controller=model_case(tmp_path)
    def delayed(command,request_path,response_path,*,timeout):
        envelope=read_json(request_path);image=response_path.parent/'C.png'
        Image.new('RGB',(16,12),(60,60,60)).save(image)
        meta=dict(actual_generation_count=1,provider_order=0,
            executor_observation=observed_execution(root,envelope['request'],image),
            model_observed={'ui_model_name':executor()['model_display_name'],'transport':executor()['transport']})
        result=dict(image_path=str(image),metadata=meta);write_json(response_path,result)
        controller.cancel('User cancelled while worker was running')
        return result
    monkeypatch.setattr(hre.model_workers,'run_worker',delayed)
    with pytest.raises(HREError,match='worker_state_changed'):run_case(root,workers())
    state=controller.state()
    assert state['workflow_state']=='CANCELLED'
    assert state['budget']['consumed']==1 and state['budget']['reserved']==0
    assert list((root/'external_observations').glob('*/observation.json'))
