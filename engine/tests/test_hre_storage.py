import copy
import json
import multiprocessing
import pytest
from PIL import Image
from hre.assets import create_case
from hre.models import HREError, canonical_json, config_hash, request_hash, sha256_bytes, validate_schema
from hre.storage import CaseStore, case_lock, read_json, write_json


def make_case(tmp_path):
    a=tmp_path/'a.png';b=tmp_path/'b.png';Image.new('RGB',(3,2)).save(a);Image.new('RGB',(5,4),(20,30,50)).save(b)
    root=tmp_path/'case';state=create_case(a,b,{}, {'assume_srgb':True},root)
    return root,state


def test_strict_json_and_hash_contract(tmp_path):
    assert canonical_json({'z':2,'é':1})==b'{"z":2,"\xc3\xa9":1}'
    for raw in [b'{"x":1,"x":2}',b'{"x":NaN}',b'[]']:
        (tmp_path/'j').write_bytes(raw)
        with pytest.raises(HREError):read_json(tmp_path/'j')
    with pytest.raises((ValueError,HREError)):canonical_json({'x':float('nan')})
    assert request_hash({'x':1,'request_sha256':'x'})==sha256_bytes(canonical_json({'x':1}))
    assert config_hash({'x':1,'config_sha256':'x'})==request_hash({'x':1})


def test_atomic_cas_and_reentrant_caller_lock(tmp_path):
    root,state=make_case(tmp_path);store=CaseStore(root);n=copy.deepcopy(state);n['round']=1
    with case_lock(root):res=store.commit(n,{'type':'test'},0)
    assert res['revision']==1 and store.load()==res
    with pytest.raises(HREError):store.commit(n,{'type':'stale'},0)
    assert len((root/'events.jsonl').read_text().splitlines())==1


def test_committed_transaction_replays_after_state_crash(tmp_path,monkeypatch):
    import hre.storage as storage
    root,state=make_case(tmp_path);store=CaseStore(root);original=storage.write_json
    def crash(path,data):
        if path.name=='state.json':raise OSError('crash at state projection')
        original(path,data)
    monkeypatch.setattr(storage,'write_json',crash)
    n=copy.deepcopy(state);n['round']=1
    with pytest.raises(OSError):store.commit(n,{'type':'test'},0)
    monkeypatch.setattr(storage,'write_json',original)
    recovered=store.recover();assert recovered['revision']==1 and recovered['round']==1
    assert store.recover()==recovered
    assert len((root/'events.jsonl').read_text().splitlines())==1


def test_transaction_gap_duplicate_and_previous_hash_are_integrity_errors(tmp_path):
    root,state=make_case(tmp_path);store=CaseStore(root);store.commit(copy.deepcopy(state),{'type':'test'},0)
    txfile=next((root/'transactions').glob('*.json'));tx=read_json(txfile);tx['previous_state_sha256']='0'*64;write_json(txfile,tx)
    with pytest.raises(HREError,match='protocol_integrity_error'):store.recover()


def test_frozen_config_and_manifest_are_checked(tmp_path):
    root,state=make_case(tmp_path);write_json(root/'manifest.json',{'changed':True})
    with pytest.raises(HREError):CaseStore(root).load()


def test_schema_registry_resolves_crossrefs():
    with pytest.raises(HREError):validate_schema('state',{})
    with pytest.raises(HREError):validate_schema('asset',{'path':'../evil'})


def _parallel_commit(root):
    from hre.storage import CaseStore,case_lock
    with case_lock(root):
        store=CaseStore(root);state=store.load();store.commit(state,{'type':'concurrent'},state['revision'])


def test_os_lock_serializes_processes(tmp_path):
    root,state=make_case(tmp_path)
    ctx=multiprocessing.get_context('fork' if __import__('os').name!='nt' else 'spawn')
    ps=[ctx.Process(target=_parallel_commit,args=(root,)) for _ in range(4)]
    for p in ps:p.start()
    for p in ps:p.join(10);assert p.exitcode==0
    assert CaseStore(root).load()['revision']==4


def test_duplicate_revision_and_missing_transaction_rejected(tmp_path):
    root,state=make_case(tmp_path);store=CaseStore(root)
    store.commit(state,{'type':'one'},0);state=store.load();store.commit(state,{'type':'two'},1)
    txfiles=sorted((root/'transactions').glob('*.json'));txfiles[0].unlink()
    with pytest.raises(HREError,match='protocol_integrity_error'):store.recover()


def test_state_uncommitted_change_rejected(tmp_path):
    root,state=make_case(tmp_path);state['round']=2;write_json(root/'state.json',state)
    with pytest.raises(HREError):CaseStore(root).recover()


def test_uncommitted_task_orphan_not_dispatched(tmp_path):
    root,state=make_case(tmp_path);write_json(root/'tasks/orphan/request.json',{'uncommitted':True})
    assert CaseStore(root).recover()==state
    assert not (root/'tasks/orphan/accepted').exists()


def _request_state(root,state):
    from pathlib import Path
    data=json.loads((Path(__file__).parents[2]/'docs/reference_enhancement/v1_20261013/examples/state_protocol.example.json').read_text())
    req=copy.deepcopy(data['requests'][0]);req.update(case_id=state['case_id'],case_revision=state['case_revision'],state_revision_issued=1,config_sha256=state['config_sha256'],input_assets=state['inputs'])
    req['request_sha256']=request_hash(req)
    path='tasks/diagnose_0/attempts/000/request.json';write_json(root/path,req)
    (root/path).with_name('prompt.txt').write_text('actual prompt')
    nxt=copy.deepcopy(state);nxt['workflow_state']='WAIT_DIAGNOSIS';nxt['pending_task']={k:req[k] for k in ['task_id','stage','round','attempt','request_sha256','state_revision_issued']};nxt['pending_task']['request_path']=path
    from hre.models import file_sha256
    task={'request_path':path,'request_sha256':req['request_sha256'],'prompt_sha256':file_sha256((root/path).with_name('prompt.txt'))}
    return req,nxt,task


def test_next_task_must_match_pending_identity(tmp_path):
    root,state=make_case(tmp_path);req,nxt,task=_request_state(root,state)
    nxt['pending_task']['task_id']='different_task'
    with pytest.raises(HREError):CaseStore(root).commit(nxt,{'type':'issue'},0,next_task=task)


def test_pending_request_detects_content_tamper(tmp_path):
    root,state=make_case(tmp_path);req,nxt,task=_request_state(root,state)
    CaseStore(root).commit(nxt,{'type':'issue'},0,next_task=task)
    req['payload']['comparison_policy_id']='tampered';write_json(root/task['request_path'],req)
    with pytest.raises(HREError):CaseStore(root).load()


def test_accepted_response_must_match_record_identity(tmp_path):
    from hre.models import file_sha256,now
    root,state=make_case(tmp_path);req,nxt,task=_request_state(root,state)
    current=CaseStore(root).commit(nxt,{'type':'issue'},0,next_task=task)
    data=json.loads((__import__('pathlib').Path(__file__).parents[2]/'docs/reference_enhancement/v1_20261013/examples/state_protocol.example.json').read_text())
    response=copy.deepcopy(data['responses'][0]);response.update({k:v for k,v in req.items() if k!='payload'})
    response['task_id']='wrong_task'
    folder='tasks/diagnose_0/submissions/s1/pending'
    response_path=folder+'/response.json';write_json(root/response_path,response);sha=file_sha256(root/response_path)
    done={'schema_version':'ref_enhance_v1','case_id':state['case_id'],'case_revision':0,'task_id':req['task_id'],'request_sha256':req['request_sha256'],'response_file':response_path,'response_sha256':sha,'artifacts':[],'completed_at':now(),'writer':'fixture'}
    done_path=folder+'/done.json';write_json(root/done_path,done)
    accepted={'task_id':req['task_id'],'attempt':0,'request_sha256':req['request_sha256'],'response_sha256':sha,'response_path':response_path,'done_path':done_path}
    with pytest.raises(HREError):CaseStore(root).commit(current,{'type':'accept'},1,accepted_submission=accepted)


def _charged_case(tmp_path):
    from hre.models import now
    root,s=make_case(tmp_path);store=CaseStore(root)
    s['budget'].update(reserved=1,ledger=[{'generation_id':'g1','task_id':'t1','round':0,'status':'reserved','charged_count':0,'submitted_at':None,'outcome':'pending'}]);s=store.commit(s,{'type':'reserve'},0)
    s['budget']['ledger'][0].update(status='submitted',charged_count=1,submitted_at=now(),outcome='ok');s['budget'].update(reserved=0,consumed=1);s=store.commit(s,{'type':'submit'},1)
    return root,s,store


def test_charged_budget_cannot_be_erased(tmp_path):
    root,s,store=_charged_case(tmp_path);s['budget'].update(consumed=0,ledger=[])
    with pytest.raises(HREError):store.commit(s,{'type':'erase'},2)


@pytest.mark.parametrize('field,value',[('task_id','other'),('round',1),('status','released_unsubmitted'),('charged_count',0),('submitted_at','2026-10-14T00:00:00Z')])
def test_submitted_ledger_identity_cost_timestamp_immutable(tmp_path,field,value):
    root,s,store=_charged_case(tmp_path);entry=s['budget']['ledger'][0];entry[field]=value
    if field=='status':entry.update(charged_count=0,submitted_at=None);s['budget']['consumed']=0
    if field=='charged_count':s['budget']['consumed']=0
    with pytest.raises(HREError):store.commit(s,{'type':'mutation'},2)


def test_late_extra_cost_can_exceed_budget_without_erasing_accounting(tmp_path):
    root,s,store=_charged_case(tmp_path);s['budget']['ledger'][0]['charged_count']=4;s['budget']['consumed']=4
    committed=store.commit(s,{'type':'extra_cost'},2)
    assert committed['budget']['consumed']==4 and store.recover()['budget']['consumed']==4


def test_released_generation_cannot_be_reused(tmp_path):
    root,s=make_case(tmp_path);store=CaseStore(root)
    entry={'generation_id':'g1','task_id':'t1','round':0,'status':'reserved','charged_count':0,'submitted_at':None,'outcome':'pending'}
    s['budget'].update(reserved=1,ledger=[entry]);s=store.commit(s,{'type':'reserve'},0)
    s['budget']['ledger'][0].update(status='released_unsubmitted',outcome=None);s['budget']['reserved']=0;s=store.commit(s,{'type':'release'},1)
    s['budget']['ledger'][0]['status']='reserved';s['budget']['reserved']=1
    with pytest.raises(HREError):store.commit(s,{'type':'reuse'},2)


def test_json_bom_is_rejected(tmp_path):
    path=tmp_path/'j';path.write_bytes(b'\xef\xbb\xbf{"x":1}')
    with pytest.raises(HREError):read_json(path)


def test_recovery_rejects_predecessor_cost_erasure_even_self_consistent_snapshot(tmp_path):
    root,s,store=_charged_case(tmp_path);s=store.commit(s,{'type':'no_op'},2)
    last=sorted((root/'transactions').glob('*.json'))[-1];tx=read_json(last)
    tx['next_state']['budget'].update(consumed=0,ledger=[])
    write_json(last,tx);write_json(root/'state.json',tx['next_state'])
    with pytest.raises(HREError,match='protocol_integrity_error'):store.recover()
