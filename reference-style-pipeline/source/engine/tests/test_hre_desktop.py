import json
import pytest
from PIL import Image
from test_hre_prompts import case_and_request


def test_task_export_contains_actual_images_and_hash_manifest(tmp_path):
    from hre.desktop import export_task_bundle
    from hre.models import file_sha256
    root,req=case_and_request(tmp_path)
    exported=export_task_bundle(req,tmp_path/'exchange',case_root=root)
    manifest=json.loads((exported/'manifest.json').read_text())
    assert manifest['request_sha256']==req['request_sha256']
    assert (exported/'request.json').is_file() and (exported/'config.json').is_file()
    for attachment in manifest['attachments']:
        assert file_sha256(exported/attachment['path'])==attachment['sha256']
    assert [x['label'] for x in manifest['attachments']]==['A','B']


def test_execute_human_pack_only_images_and_plain_edit_text(tmp_path):
    from hre.desktop import export_task_bundle
    from hre.workflow import Controller
    from test_hre_protocol import make_case,current_request
    root=make_case(tmp_path,'direct_ref',1);Controller(root).start();req=current_request(root)
    folder=export_task_bundle(req,tmp_path/'exchange',case_root=root)
    human=folder/'editor'
    assert sorted(x.name for x in human.iterdir())==['A.png','B.png','edit_prompt.txt']
    prompt=(human/'edit_prompt.txt').read_text()
    assert req['payload']['edit_prompt'] in prompt
    assert 'Return one JSON' not in prompt


def test_capabilities_remain_independent_and_local_io_not_chatgpt_io(tmp_path):
    from hre.capabilities import run_capability_probe
    root,req=case_and_request(tmp_path)
    local=run_capability_probe('local_file_io',root)
    assert local['status']=='untested' and local['controller_file_io']['status']=='passed'
    for name in ['role_dispatch','two_image_edit','image_save']:
        assert run_capability_probe(name,root)['status']=='untested'
    persisted=json.loads((root/'capabilities.json').read_text())
    assert all(item['status']=='untested' for item in persisted['capabilities'].values())


def test_candidate_unknown_submission_and_wrong_task_reject_before_copy(tmp_path):
    from hre.desktop import import_candidate
    from hre.models import HREError
    from hre.workflow import Controller
    from test_hre_protocol import make_case,current_request
    root=make_case(tmp_path,'direct_ref',1);c=Controller(root);c.start();req=current_request(root)
    output=tmp_path/'output.png';Image.new('RGB',(16,12),(75,80,90)).save(output)
    with pytest.raises(HREError):import_candidate(root,'wrong_task',output,{})
    with pytest.raises(HREError):import_candidate(root,req['task_id'],output,{})
    assert not list((root/'assets').rglob('candidate_*.png'))


def test_real_candidate_raw_binding_done_and_state_writer_separation(tmp_path):
    from hre.desktop import import_candidate
    from hre.models import file_sha256
    from hre.storage import read_json
    from hre.workflow import Controller
    from hre.protocol import validate_submission
    from test_hre_protocol import make_case,current_request
    root=make_case(tmp_path,'direct_ref',1);controller=Controller(root);controller.start();req=current_request(root);controller.mark_submitted(req['task_id'])
    state_before=controller.state()
    output=tmp_path/'output.jpg';Image.new('RGB',(16,12),(75,80,90)).save(output)
    done=import_candidate(root,req['task_id'],output,{'provider_order':0,'actual_generation_count':1,'assume_srgb':True,'model_observed':{'ui_model_name':'unknown','exact_model_version':None,'seed':None,'observed_at':'2026-10-13T00:00:00Z','transport':'desktop_manual','operator_steps':['User imported an existing output.']}})
    assert controller.state()==state_before
    result=validate_submission(root,done,req,state_before)
    candidate=result['response']['payload']['candidate_asset']
    assert candidate['candidate_binding']['generation_id']==req['payload']['generation_id']
    assert candidate['candidate_binding']['prediction_sha256']==req['input_assets'][0]['sha256']
    assert file_sha256(root/candidate['source_file']['path'])==file_sha256(output)


def test_multiple_real_outputs_preserve_extras_without_selecting_them(tmp_path):
    from hre.desktop import import_candidate
    from hre.models import file_sha256,HREError
    from hre.workflow import Controller
    from hre.protocol import validate_submission
    from test_hre_protocol import make_case,current_request
    root=make_case(tmp_path,'direct_best_of_3',3);controller=Controller(root);controller.start();req=current_request(root);controller.mark_submitted(req['task_id'])
    formal=tmp_path/'formal.jpg';extra=tmp_path/'extra.png'
    Image.new('RGB',(16,12),(80,90,100)).save(formal)
    Image.new('RGB',(16,12),(20,30,40)).save(extra)
    with pytest.raises(HREError):import_candidate(root,req['task_id'],formal,{'provider_order':0,'actual_generation_count':1,'extras':[{'source':str(extra),'provider_order':1,'complete':True}]})
    done=import_candidate(root,req['task_id'],formal,{'provider_order':0,'actual_generation_count':2,'extras':[{'source':str(extra),'provider_order':1,'complete':True}]})
    p=validate_submission(root,done,req,controller.state())['response']['payload']
    assert p['candidate_asset']['source_file']['sha256']==file_sha256(formal)
    assert len(p['extras'])==1 and p['extras'][0]['sha256']==file_sha256(extra)
    assert file_sha256(root/p['extras'][0]['path'])==file_sha256(extra)


def test_capability_import_requires_actual_hash_scoped_user_evidence(tmp_path):
    from hre.capabilities import run_capability_probe
    from hre.models import file_sha256,HREError
    from hre.storage import write_json
    root,req=case_and_request(tmp_path)
    observed=root/'manual_probe_observation.json'
    screenshot=root/'synthetic_dispatch_observation.png';Image.new('RGB',(5,5),(20,30,40)).save(screenshot)
    record={'capability':'role_dispatch','status':'passed','scope':'chatgpt_desktop','observer':'synthetic test operator','observed_at':'2026-10-13T00:00:00Z','steps':['Imported record tests only; real capability remains untested outside this test.'],'artifacts':[{'path':screenshot.name,'sha256':file_sha256(screenshot),'purpose':'dispatch_observation'}]}
    write_json(observed, {**record,'kind':'hre_capability_observation_v1','task_id':req['task_id'],'request_sha256':req['request_sha256'],'stage':req['stage'],'claim':'requested_role_session_dispatched'})
    record['observation']={'path':observed.name,'sha256':file_sha256(observed)}
    with pytest.raises(HREError):run_capability_probe('image_save',root,evidence=record)
    assert run_capability_probe('role_dispatch',root,evidence=record)['status']=='passed'
    assert run_capability_probe('image_save',root)['status']=='untested'
    record['artifacts'][0]['sha256']='0'*64
    with pytest.raises(HREError):run_capability_probe('role_dispatch',root,evidence=record)


def test_task_export_rejects_frozen_request_and_prompt_context_tamper(tmp_path):
    from hre.desktop import export_task_bundle
    from hre.models import request_hash,HREError
    from hre.workflow import Controller
    from hre.storage import read_json,write_json
    from test_hre_protocol import make_case,current_request
    root=make_case(tmp_path);Controller(root).start();req=current_request(root)
    req['payload']['available_tools']=[];req['request_sha256']=request_hash(req)
    with pytest.raises(HREError):export_task_bundle(req,tmp_path/'export_bad_request',case_root=root)
    req=current_request(root);path=root/Controller(root).state()['pending_task']['request_path'];adapter=read_json(path.parent/'adapter_context.json');adapter['model_observed']['ui_model_name']='tampered';write_json(path.parent/'adapter_context.json',adapter)
    with pytest.raises(HREError):export_task_bundle(req,tmp_path/'export_bad_context',case_root=root)


@pytest.mark.parametrize('metadata',[
    {'actual_generation_count':2,'provider_order':1,'extras':[{'provider_order':0,'complete':True}]},
    {'actual_generation_count':2,'provider_order':0,'extras':[{}]},
    {'actual_generation_count':2,'provider_order':0,'extras':[{'provider_order':0,'complete':True}]},
    {'actual_generation_count':2,'provider_order':99,'extras':[{'provider_order':1,'complete':True}]},
])
def test_candidate_ordering_rejects_later_missing_duplicate_or_unknown(tmp_path,metadata):
    from hre.desktop import import_candidate
    from hre.models import HREError
    from hre.workflow import Controller
    from test_hre_protocol import make_case,current_request
    root=make_case(tmp_path,'direct_best_of_3',3);c=Controller(root);c.start();req=current_request(root);c.mark_submitted(req['task_id'])
    formal,extra=tmp_path/'formal.png',tmp_path/'extra.png'
    Image.new('RGB',(16,12),(65,76,87)).save(formal);Image.new('RGB',(16,12),(12,34,56)).save(extra)
    metadata['extras'][0]['source']=str(extra)
    with pytest.raises(HREError):import_candidate(root,req['task_id'],formal,metadata)


@pytest.mark.parametrize('observer,timestamp',[(42,'2026-10-13T00:00:00Z'),('human','not-a-time')])
def test_capability_malformed_attribution_or_unrelated_file_stays_untested(tmp_path,observer,timestamp):
    from hre.capabilities import run_capability_probe
    from hre.models import HREError,file_sha256
    root,req=case_and_request(tmp_path)
    evidence={'capability':'two_image_edit','status':'passed','scope':'chatgpt_desktop','observer':observer,'observed_at':timestamp,'steps':['x'],'artifacts':[{'path':'config.json','sha256':file_sha256(root/'config.json')}]}
    with pytest.raises(HREError):run_capability_probe('two_image_edit',root,evidence=evidence)
    assert run_capability_probe('two_image_edit',root)['status']=='untested'


def test_first_complete_after_explicit_incomplete_prior_raw_is_audited(tmp_path):
    from hre.desktop import import_candidate
    from hre.models import file_sha256
    from hre.storage import read_json
    from hre.protocol import validate_submission
    from hre.workflow import Controller
    from test_hre_protocol import make_case,current_request
    root=make_case(tmp_path,'direct_best_of_3',3);controller=Controller(root);controller.start();req=current_request(root);controller.mark_submitted(req['task_id'])
    partial=tmp_path/'partial.png';partial.write_bytes(b'actual incomplete synthetic download bytes')
    complete=tmp_path/'complete.png';Image.new('RGB',(16,12),(56,67,78)).save(complete)
    done=import_candidate(root,req['task_id'],complete,{'actual_generation_count':2,'provider_order':1,'extras':[{'source':str(partial),'provider_order':0,'complete':False}]})
    payload=validate_submission(root,done,req,controller.state())['response']['payload']
    assert not payload['extras'] and payload['provider_order']==1
    marker=read_json(done)
    records=[]
    for item in marker['artifacts']:
        if item['path'].endswith('.json'):
            record=read_json(root/item['path'])
            if record.get('kind')=='hre_output_order_v1':records.append(record)
    assert len(records)==1
    assert records[0]['outputs'][0]['complete'] is False
    assert file_sha256(root/records[0]['outputs'][0]['path'])==file_sha256(partial)


def test_legacy_bare_extra_paths_cannot_invent_order(tmp_path):
    from hre.desktop import validate_output_order
    from hre.models import HREError
    with pytest.raises(HREError):validate_output_order({'actual_generation_count':2,'provider_order':99,'extras':['some.png']})
    with pytest.raises(HREError):validate_output_order({'actual_generation_count':2,'provider_order':0,'extras':['some.png']})


def test_capability_correct_attribution_still_rejects_unrelated_config_proof(tmp_path):
    from hre.capabilities import run_capability_probe
    from hre.models import HREError,file_sha256
    from hre.storage import write_json
    root,req=case_and_request(tmp_path)
    record={'capability':'two_image_edit','status':'passed','scope':'chatgpt_desktop','observer':'test operator','observed_at':'2026-10-13T00:00:00Z','steps':['synthetic contract test only'],'artifacts':[{'path':'config.json','sha256':file_sha256(root/'config.json'),'purpose':'output_image'}]}
    path=root/'invalid_observation.json';write_json(path,{**record,'kind':'hre_capability_observation_v1','claim':'two_bound_images_edited','task_id':req['task_id'],'request_sha256':req['request_sha256'],'stage':'execute'})
    record['observation']={'path':path.name,'sha256':file_sha256(path)}
    with pytest.raises(HREError):run_capability_probe('two_image_edit',root,evidence=record)
    assert run_capability_probe('two_image_edit',root)['status']=='untested'
