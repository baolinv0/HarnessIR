from pathlib import Path
import pytest
from PIL import Image


def make_case(tmp_path, profile='agent_adaptive', max_generations=3):
    from hre.assets import create_case
    a,b=tmp_path/'a.png',tmp_path/'b.png'
    Image.new('RGB',(16,12),(50,40,30)).save(a)
    Image.new('RGB',(24,18),(120,110,100)).save(b)
    root=tmp_path/'case'
    create_case(a,b,{'case_id':'test_case'},{'profile_id':profile,'max_generations':max_generations,'assume_srgb':True,'reference_usable':'usable'},root)
    return root


def diagnosis():
    return {'reference_usable':'usable','comparability':[{'scope':'global','roi_pair_id':None,'status':'comparable','reasons':['same material'],'confidence':.9}], 'global_gaps':[{'gap_id':'bright','dimension':'brightness','observation':'A dark','desired_change':'brighten','priority':1,'confidence':.9,'evidence_ids':[]}], 'local_gaps':[], 'style_targets':[{'priority':1,'target':'brighten A','support_gap_ids':['bright'],'confidence':.9}],'preservation_constraints':['preserve content'],'tool_plan':[], 'uncertainties':[]}


def current_request(root):
    from hre.workflow import Controller
    from hre.storage import read_json
    return read_json(root/Controller(root).state()['pending_task']['request_path'])


def test_real_submission_hash_identity_and_done_is_last(tmp_path):
    from hre.workflow import Controller
    from hre.protocol import TaskWriter,validate_submission
    from hre.storage import read_json,write_json
    from hre.models import HREError
    root=make_case(tmp_path)
    c=Controller(root); c.start()
    req=current_request(root)
    done=TaskWriter(root).commit_submission(req,diagnosis(),raw_text=b'actual pasted payload')
    result=validate_submission(root,done,req,c.state())
    assert result['response']['payload']==diagnosis()
    manifest=read_json(done)
    (root/manifest['response_file']).write_bytes(b'{}')
    with pytest.raises(HREError):validate_submission(root,done,req,c.state())


def test_response_echo_tamper_is_rejected_even_with_updated_done_hash(tmp_path):
    from hre.workflow import Controller
    from hre.protocol import TaskWriter,validate_submission
    from hre.storage import read_json,write_json
    from hre.models import file_sha256,HREError
    root=make_case(tmp_path); c=Controller(root);c.start();req=current_request(root)
    done=TaskWriter(root).commit_submission(req,diagnosis())
    m=read_json(done);rpath=root/m['response_file'];r=read_json(rpath);r['round']=1;write_json(rpath,r)
    m['response_sha256']=file_sha256(rpath);write_json(done,m)
    with pytest.raises(HREError):validate_submission(root,done,req,c.state())


def test_execution_with_external_auxiliary_file_has_correct_artifact_kinds(tmp_path):
    from hre.workflow import Controller
    from hre.protocol import TaskWriter,validate_submission
    from hre.assets import AssetRegistry
    from hre.storage import read_json
    from hre.models import now
    root=make_case(tmp_path,'direct_ref',1);c=Controller(root);c.start();req=current_request(root);c.mark_submitted(req['task_id'])
    image=tmp_path/'candidate.png';Image.new('RGB',(16,12),(90,80,70)).save(image)
    binding={k:req[k] for k in ('case_id','case_revision','task_id','round')}
    binding.update(generation_id=req['payload']['generation_id'],prediction_sha256=req['input_assets'][0]['sha256'],reference_sha256=req['input_assets'][1]['sha256'])
    a=AssetRegistry(root).import_asset(image,'candidate','cand_one',{'assume_srgb':True,'canonicalizer_version':'hre_rgb8_v1'},candidate_binding=binding)
    external=tmp_path/'note.txt';external.write_text('external auxiliary')
    payload=dict(generation_id=binding['generation_id'],candidate_asset=a,submitted_at=now(),actual_generation_count=1,provider_order=0,selection_rule='first_complete_provider_order',extras=[],geometry_observations=[])
    done=TaskWriter(root).commit_submission(req,payload,files=[external])
    manifest=read_json(done)
    assert manifest['artifacts'][0]['kind']=='auxiliary'
    assert {a['kind'] for a in manifest['artifacts']}=={'auxiliary','canonical_image','raw_image'}
    validate_submission(root,done,req,c.state())


@pytest.mark.parametrize('field,value',[('config_sha256','1'*64),('attempt',3),('case_revision',1),('task_id','old_task')])
def test_identity_fields_cannot_be_repaired_by_done_rehash(tmp_path,field,value):
    from hre.workflow import Controller
    from hre.protocol import TaskWriter,validate_submission
    from hre.storage import read_json,write_json
    from hre.models import file_sha256,HREError
    root=make_case(tmp_path);c=Controller(root);c.start();req=current_request(root)
    done=TaskWriter(root).commit_submission(req,diagnosis());m=read_json(done);p=root/m['response_file'];r=read_json(p);r[field]=value;write_json(p,r);m['response_sha256']=file_sha256(p);write_json(done,m)
    with pytest.raises(HREError):validate_submission(root,done,req,c.state())


def test_partial_response_and_symlink_done_do_not_advance(tmp_path):
    from hre.workflow import Controller
    from hre.protocol import TaskWriter
    root=make_case(tmp_path);c=Controller(root);c.start();req=current_request(root)
    done=TaskWriter(root).commit_submission(req,diagnosis());part=done.with_name('done.json.part');done.rename(part)
    assert not c.consume_done(part).accepted
    assert c.state()['pending_task']['task_id']==req['task_id']
    done.symlink_to(part)
    assert not c.consume_done(done).accepted
    assert c.state()['workflow_state']=='WAIT_DIAGNOSIS'


def test_taskwriter_rejects_ok_empty_payload_and_error_payload(tmp_path):
    from hre.workflow import Controller
    from hre.protocol import TaskWriter
    root=make_case(tmp_path);Controller(root).start();req=current_request(root)
    with pytest.raises(Exception):TaskWriter(root).commit_submission(req,{})
    with pytest.raises(Exception):TaskWriter(root).commit_submission(req,diagnosis(),error=dict(code='failed',message='failed',retryable=True))


def test_quarantine_does_not_follow_rejected_submission_parent_symlink(tmp_path):
    from hre.workflow import Controller
    root=make_case(tmp_path);c=Controller(root);c.start()
    external=tmp_path/'external';external.mkdir();(external/'done.json').write_text('{}');(external/'private.txt').write_text('must not follow rejected directory')
    link=root/'linked';link.symlink_to(external,target_is_directory=True)
    assert not c.consume_done(link/'done.json').accepted
    assert not list((root/'quarantine').rglob('private.txt'))


def test_candidate_color_policy_is_bound_to_frozen_configuration(tmp_path):
    from hre.workflow import Controller
    from hre.desktop import import_candidate
    from hre.storage import read_json,write_json
    from hre.models import file_sha256,HREError
    from hre.protocol import validate_submission
    root=make_case(tmp_path,'direct_ref',1);c=Controller(root);c.start();req=current_request(root);c.mark_submitted(req['task_id'])
    image=tmp_path/'c.png';Image.new('RGB',(16,12),(90,80,70)).save(image)
    done=import_candidate(root,req['task_id'],image,dict(actual_generation_count=1,provider_order=0))
    manifest=read_json(done);response_path=root/manifest['response_file'];r=read_json(response_path)
    r['payload']['candidate_asset']['canonicalization']['conversion_policy_sha256']='0'*64
    write_json(response_path,r);manifest['response_sha256']=file_sha256(response_path);write_json(done,manifest)
    with pytest.raises(HREError):validate_submission(root,done,req,c.state())


def test_order_manifest_remaps_real_files_and_rejects_skipped_complete_output(tmp_path):
    from hre.workflow import Controller
    from hre.desktop import import_candidate
    from hre.protocol import TaskWriter,validate_submission
    from hre.storage import read_json,write_json
    from hre.models import file_sha256,HREError
    root=make_case(tmp_path,'direct_best_of_3',3);c=Controller(root);c.start();req=current_request(root);c.mark_submitted(req['task_id'])
    image=tmp_path/'candidate_order.png';Image.new('RGB',(16,12),(100,90,80)).save(image)
    done=import_candidate(root,req['task_id'],image,dict(actual_generation_count=1,provider_order=0));m=read_json(done);p=read_json(root/m['response_file'])['payload']
    formal=p['candidate_asset']['source_file'];audit=root/'order.json'
    order=dict(kind='hre_output_order_v1',task_id=req['task_id'],request_sha256=req['request_sha256'],generation_id=p['generation_id'],candidate_id=p['candidate_asset']['asset_id'],actual_generation_count=1,outputs=[dict(provider_order=0,complete=True,path=formal['path'],sha256=formal['sha256'],formal=True)])
    write_json(audit,order)
    second=TaskWriter(root).commit_submission(req,p,files=[root/formal['path'],audit])
    manifest=read_json(second)
    copied=[]
    for art in manifest['artifacts']:
        if art['path'].endswith('.json'):
            value=read_json(root/art['path'])
            if value.get('kind')=='hre_output_order_v1':copied.append((art,value))
    assert len(copied)==1
    artifact,value=copied[0]
    assert value['outputs'][0]['path'].startswith(second.parent.relative_to(root).as_posix())
    validate_submission(root,second,req,c.state())
    # A skipped earlier complete image must fail even when done and manifest hashes are recomputed.
    response_path=root/manifest['response_file'];response=read_json(response_path)
    response['payload']['actual_generation_count']=2;response['payload']['provider_order']=1;write_json(response_path,response)
    value['actual_generation_count']=2;value['outputs'][0]['provider_order']=1
    value['outputs'].append(dict(value['outputs'][0],provider_order=0,formal=False))
    write_json(root/artifact['path'],value)
    artifact['sha256']=file_sha256(root/artifact['path']);manifest['response_sha256']=file_sha256(response_path);write_json(second,manifest)
    with pytest.raises(HREError):validate_submission(root,second,req,c.state())


def test_fixed_direct_prompt_source_is_immutable_at_response_intake(tmp_path):
    from hre.workflow import Controller
    from hre.protocol import TaskWriter,validate_submission
    from hre.storage import read_json,write_json
    from hre.models import HREError
    root=make_case(tmp_path,'direct_ref',1);c=Controller(root);c.start();req=current_request(root)
    done=TaskWriter(root).commit_submission(req,None,error=dict(code='editor_failed',message='editor failed',retryable=True))
    source=root/f"tasks/{req['payload']['prompt_source_task_id']}/manifest.json";value=read_json(source);value['edit_prompt']='tampered direct prompt';write_json(source,value)
    with pytest.raises(HREError):validate_submission(root,done,req,c.state())
