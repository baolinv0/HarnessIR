"""Subprocess coverage: the CLI must persist actual controller state, not just parse."""
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
from PIL import Image


def invoke(*args, expected=0):
    result = subprocess.run([sys.executable, '-m', 'hre', *map(str,args)], capture_output=True, text=True)
    assert result.returncode == expected, result.stderr + result.stdout
    return json.loads(result.stdout)


def create(tmp_path, profile='direct_ref'):
    Image.new('RGB',(24,16),(40,60,80)).save(tmp_path/'A.png')
    Image.new('RGB',(30,20),(70,90,110)).save(tmp_path/'B.png')
    root=tmp_path/'cases'/'one'/'rev1'
    invoke('case','create','--prediction',tmp_path/'A.png','--reference',tmp_path/'B.png','--case-root',root,
           '--profile',profile,'--assume-srgb','--reference-usable','usable')
    return root


def test_cli_creates_bound_assets_and_lists_current_revision(tmp_path):
    root=create(tmp_path)
    state=invoke('case','show','--case-root',root)
    assert state['inputs'][0]['sha256'] != state['inputs'][1]['sha256']
    listing=invoke('case','list','--data-root',tmp_path/'cases')
    assert listing[0]['case_root']==str(root.resolve())
    started=invoke('case','start','--case-root',root)
    assert started['workflow_state']=='WAIT_EXECUTION' and started['budget']['reserved']==1


def test_cli_watch_is_bounded_and_never_generates(tmp_path):
    root=create(tmp_path)
    invoke('case','start','--case-root',root)
    state=invoke('watch','--case-root',root,'--max-polls','1','--interval','0')
    assert state['workflow_state']=='WAIT_EXECUTION'
    assert state['budget']['consumed']==0
    paused=invoke('case','pause','--case-root',root,'--reason','operator break')
    assert paused['workflow_state']=='PAUSED'
    assert invoke('case','resume','--case-root',root)['workflow_state']=='WAIT_EXECUTION'


def test_candidate_unknown_submission_pauses_without_counting(tmp_path):
    root=create(tmp_path);state=invoke('case','start','--case-root',root)
    result=invoke('candidate','import','--case-root',root,'--task-id',state['pending_task']['task_id'],
                  '--image',tmp_path/'B.png','--submission','unknown',expected=2)
    assert result['code']=='submission_unknown'
    state=invoke('case','show','--case-root',root)
    assert state['workflow_state']=='PAUSED' and state['budget']['consumed']==0


def test_task_bundle_contains_real_frozen_images_and_readable_prompt(tmp_path):
    root=create(tmp_path);invoke('case','start','--case-root',root)
    exported=invoke('task','export','--case-root',root,'--out',tmp_path/'exchange')
    assert Path(exported['path']).exists()
    assert list((tmp_path/'exchange').rglob('*.png'))
    assert list((tmp_path/'exchange').rglob('*.txt'))


def test_tools_commands_make_offline_handoff_actionable(tmp_path):
    from hre.cli import build_parser
    parser=build_parser()
    args=parser.parse_args(['tools','export-missing','--case-root',str(tmp_path),'--out',str(tmp_path/'jobs')])
    assert args.action=='export-missing'
    args=parser.parse_args(['tools','import-cache','--bundle',str(tmp_path/'bundle'),'--cache-root',str(tmp_path/'cache')])
    assert args.action=='import-cache'


def test_watch_consumes_writer_done_and_does_not_repeat_stage(tmp_path):
    from hre.protocol import TaskWriter
    from hre.cli import current_request
    from test_hre_protocol import diagnosis
    root=create(tmp_path,'agent_single');invoke('case','start','--case-root',root)
    done=TaskWriter(root).commit_submission(current_request(root),diagnosis())
    state=invoke('watch','--case-root',root,'--max-polls','1','--interval','0')
    assert state['workflow_state']=='WAIT_COMPOSITION'
    revision=state['revision']
    state=invoke('watch','--case-root',root,'--max-polls','1','--interval','0')
    assert state['revision']==revision and state['budget']['consumed']==0


def test_cli_payload_rejects_nonfinite_and_preserves_pending_identity(tmp_path):
    root=create(tmp_path,'agent_single');state=invoke('case','start','--case-root',root)
    payload=tmp_path/'bad.json';payload.write_text('{"confidence": NaN}')
    rejected=invoke('response','import','--case-root',root,'--payload',payload,expected=2)
    assert rejected['accepted'] is False
    after=invoke('case','show','--case-root',root)
    assert after['pending_task']==state['pending_task']


def test_collection_retains_unknown_historical_schema_without_loading_as_current(tmp_path):
    legacy=tmp_path/'cases'/'legacy';legacy.mkdir(parents=True)
    original=b'{"schema_version":"legacy_v0","case_id":"old"}'
    (legacy/'state.json').write_bytes(original)
    listing=invoke('case','list','--data-root',tmp_path/'cases')
    assert listing[0]['compatible'] is False
    assert (legacy/'state.json').read_bytes()==original


def test_response_envelope_accepts_conventional_response_and_done_flags(tmp_path):
    from hre.cli import build_parser
    args=build_parser().parse_args(['response','import','--case-root',str(tmp_path),'--response','reply.json','--done','done.json'])
    assert str(args.response)=='reply.json' and str(args.done)=='done.json'


def test_unknown_submission_cannot_resume_until_explicit_reconciliation(tmp_path):
    root=create(tmp_path);state=invoke('case','start','--case-root',root)
    task=state['pending_task']['task_id']
    invoke('candidate','import','--case-root',root,'--task-id',task,'--image',tmp_path/'A.png','--submission','unknown',expected=2)
    rejected=invoke('case','resume','--case-root',root,expected=2)
    assert rejected['code']=='submission_unconfirmed'
    state=invoke('task','submitted','--case-root',root,'--task-id',task)
    assert state['budget']['consumed']==1 and state['budget']['reserved']==0
    state=invoke('case','resume','--case-root',root)
    assert state['workflow_state']=='WAIT_EXECUTION' and state['pending_task']['task_id']==task


def test_cpu_precompute_command_writes_importable_bundle_without_state_transition(tmp_path):
    root=create(tmp_path)
    plan=tmp_path/'plan.json';plan.write_text(json.dumps({'plan':[{'plan_item_id':'stats_a','tool_id':'STATS','roles':['prediction'],'roi_pair_ids':[],
                                                                'required':True,'status':'pending','evidence_id':None}]}))
    result=invoke('tools','precompute','--case-root',root,'--plan',plan,'--out',tmp_path/'bundle')
    assert (tmp_path/'bundle'/'evidence_bundle.json').is_file()
    assert invoke('case','show','--case-root',root)['revision']==0
    imported=invoke('tools','import-cache','--bundle',tmp_path/'bundle','--cache-root',tmp_path/'cache')
    assert imported


def test_cli_manual_candidate_and_json_response_complete_actual_selection(tmp_path):
    from test_hre_selection import verified
    from hre.storage import read_json
    root=create(tmp_path);state=invoke('case','start','--case-root',root)
    Image.new('RGB',(24,16),(60,80,100)).save(tmp_path/'C.png')
    metadata=tmp_path/'candidate.json';metadata.write_text(json.dumps({'actual_generation_count':1,'provider_order':0}))
    result=invoke('candidate','import','--case-root',root,'--task-id',state['pending_task']['task_id'],
                  '--image',tmp_path/'C.png','--metadata',metadata,'--submission','submitted')
    assert result['accepted'] is True
    state=invoke('case','show','--case-root',root)
    assert state['workflow_state']=='WAIT_VERIFICATION' and state['budget']['consumed']==1
    payload=tmp_path/'verify.json';payload.write_text(json.dumps(verified()['verification']))
    assert invoke('response','import','--case-root',root,'--payload',payload)['accepted']
    state=invoke('case','show','--case-root',root)
    assert state['workflow_state']=='COMPLETED' and state['success'] is True
    result=invoke('report','--case-root',root)
    summary=read_json(root/'final'/'summary.json')
    assert summary['selected_asset']['sha256']==state['candidates'][0]['asset']['sha256']
    assert summary['selection']==state['selection']


def test_relative_revision_path_works_from_cli_working_directory(tmp_path):
    root=create(tmp_path)
    relative=Path(os.path.relpath(root,Path.cwd()))
    assert invoke('case','start','--case-root',relative)['workflow_state']=='WAIT_EXECUTION'


def test_oversampling_archives_actual_outputs_before_terminal_budget_accounting(tmp_path):
    from hre.models import file_sha256
    from hre.storage import read_json
    root=create(tmp_path);state=invoke('case','start','--case-root',root)
    paths=[]
    for i in range(4):
        path=tmp_path/f'raw_{i}.png';Image.new('RGB',(24,16),(60+i,80,100)).save(path);paths.append(path)
    metadata=tmp_path/'extra.json';metadata.write_text(json.dumps({'actual_generation_count':4,'provider_order':0,'extras':[{'source':str(paths[1]),'provider_order':1,'complete':True},{'source':str(paths[2]),'provider_order':2,'complete':True},{'source':str(paths[3]),'provider_order':3,'complete':True}]}))
    result=invoke('candidate','import','--case-root',root,'--task-id',state['pending_task']['task_id'],
                  '--image',paths[0],'--metadata',metadata,'--submission','submitted',expected=2)
    assert result['code']=='extra_sampling'
    state=invoke('case','show','--case-root',root)
    assert state['workflow_state']=='FAILED' and state['budget']['consumed']==4 and state['success'] is False
    assert state['candidates']==[]
    manifests=list((root/'external_observations').rglob('observation.json'))
    assert len(manifests)==1
    audit=read_json(manifests[0]);assert audit['audit_only'] is True and audit['task_id']
    assert len(audit['files'])==4
    for item,path in zip(audit['files'],paths):
        assert item['sha256']==file_sha256(path)==file_sha256(root/item['path'])
    assert [item['observed_provider_order'] for item in audit['files']]==[0,1,2,3]


def test_unknown_external_submission_without_downloaded_image_holds_budget(tmp_path):
    root=create(tmp_path);state=invoke('case','start','--case-root',root)
    task=state['pending_task']['task_id']
    state=invoke('task','unknown','--case-root',root,'--task-id',task)
    assert state['workflow_state']=='PAUSED' and state['budget']['reserved']==1
    assert state['budget']['ledger'][0]['outcome']=='unknown' and state['budget']['consumed']==0
    assert state['pending_task']['task_id']==task


def test_cli_extra_flags_preserve_explicit_provider_order_and_completion(tmp_path):
    from hre.storage import read_json
    root=create(tmp_path,'direct_best_of_3');state=invoke('case','start','--case-root',root)
    Image.new('RGB',(24,16),(60,80,100)).save(tmp_path/'C.png')
    Image.new('RGB',(24,16),(61,80,100)).save(tmp_path/'extra.png')
    metadata=tmp_path/'ordered.json';metadata.write_text(json.dumps({'actual_generation_count':2,'provider_order':0}))
    result=invoke('candidate','import','--case-root',root,'--task-id',state['pending_task']['task_id'],'--image',tmp_path/'C.png',
                  '--metadata',metadata,'--submission','submitted','--extra',tmp_path/'extra.png','--extra-order','1','--extra-complete','true')
    assert result['accepted'] is True
    after=invoke('case','show','--case-root',root)
    assert after['budget']['consumed']==2 and after['workflow_state']=='WAIT_VERIFICATION'
    response=read_json(root/'tasks'/state['pending_task']['task_id']/'accepted'/'response.json')
    assert response['payload']['actual_generation_count']==2 and len(response['payload']['extras'])==1
    submission=read_json(root/'tasks'/state['pending_task']['task_id']/'accepted'/'submission.json')
    done=read_json(root/submission['done_path'])
    audits=[read_json(root/item['path']) for item in done['artifacts'] if item['kind']=='auxiliary' and item['path'].endswith('.json')]
    audit=next(item for item in audits if item.get('kind')=='hre_output_order_v1')
    assert [(row['provider_order'],row['complete'],row['formal']) for row in audit['outputs']]==[(0,True,True),(1,True,False)]
    assert audit['actual_generation_count']==2


def test_cli_extra_paths_without_observed_orders_reject_before_charge(tmp_path):
    root=create(tmp_path,'direct_best_of_3');state=invoke('case','start','--case-root',root)
    metadata=tmp_path/'ordered.json';metadata.write_text(json.dumps({'actual_generation_count':2,'provider_order':0}))
    result=invoke('candidate','import','--case-root',root,'--task-id',state['pending_task']['task_id'],'--image',tmp_path/'A.png',
                  '--metadata',metadata,'--submission','submitted','--extra',tmp_path/'B.png',expected=2)
    assert result['code']=='extra_order_required'
    assert invoke('case','show','--case-root',root)['budget']['consumed']==0


def test_metadata_bare_extra_paths_do_not_establish_provider_order(tmp_path):
    root=create(tmp_path,'direct_best_of_3');state=invoke('case','start','--case-root',root)
    metadata=tmp_path/'unordered.json';metadata.write_text(json.dumps({'actual_generation_count':2,'provider_order':0,'extras':[str(tmp_path/'B.png')]}))
    result=invoke('candidate','import','--case-root',root,'--task-id',state['pending_task']['task_id'],'--image',tmp_path/'A.png',
                  '--metadata',metadata,'--submission','submitted',expected=2)
    assert result['code']=='provider_order_unknown'
    state=invoke('case','show','--case-root',root)
    assert state['budget']['consumed']==0 and state['candidates']==[]
    assert not (root/'external_observations').exists()


def test_watch_rejects_incomplete_inbox_once_and_accepts_repaired_dependency(tmp_path):
    from hre.protocol import TaskWriter
    from hre.cli import current_request
    from hre.storage import read_json
    from test_hre_protocol import diagnosis
    root=create(tmp_path,'agent_single');state=invoke('case','start','--case-root',root)
    done=TaskWriter(root).commit_submission(current_request(root),diagnosis())
    response=root/read_json(done)['response_file'];original=response.read_bytes();response.unlink()
    first=invoke('watch','--case-root',root,'--max-polls','1','--interval','0')
    for _ in range(2):
        subsequent=invoke('watch','--case-root',root,'--max-polls','1','--interval','0')
        assert subsequent['revision']==first['revision']
    assert len(list((root/'quarantine').glob('rejected_*')))==1
    assert first['pending_task']==state['pending_task'] and first['budget']['consumed']==0
    response.write_bytes(original)
    repaired=invoke('watch','--case-root',root,'--max-polls','1','--interval','0')
    assert repaired['workflow_state']=='WAIT_COMPOSITION'
    assert len(list((root/'quarantine').glob('rejected_*')))==1


def test_watch_ignores_export_and_quarantine_done_audits(tmp_path):
    from hre.cli import current_request
    from hre.protocol import TaskWriter
    from test_hre_protocol import diagnosis
    root=create(tmp_path,'agent_single');state=invoke('case','start','--case-root',root)
    done=TaskWriter(root).commit_submission(current_request(root),diagnosis())
    for folder in [root/'exports'/'copy',root/'quarantine'/'saved']:
        folder.mkdir(parents=True);(folder/'done.json').write_bytes(done.read_bytes())
    done.unlink()
    after=invoke('watch','--case-root',root,'--max-polls','3','--interval','0')
    assert after['revision']==state['revision'] and after['pending_task']==state['pending_task']
    assert not list((root/'quarantine').glob('rejected_*'))


@pytest.mark.parametrize('malformed',[False,True])
def test_already_recorded_oversampling_preserves_all_raw_before_decoding_or_cost_failure(tmp_path,malformed):
    from hre.models import file_sha256
    from hre.storage import read_json
    root=create(tmp_path);state=invoke('case','start','--case-root',root);task=state['pending_task']['task_id']
    invoke('task','submitted','--case-root',root,'--task-id',task,'--count','1')
    files=[]
    for index in range(4):
        path=tmp_path/f'ordered_{index}.png';Image.new('RGB',(24,16),(65+index,80,100)).save(path);files.append(path)
    if malformed:
        files[0].write_bytes(b'actual undecodable formal download');files[1].write_bytes(b'actual partial extra download')
    metadata=tmp_path/'observed.json';metadata.write_text(json.dumps({'actual_generation_count':4,'provider_order':0,'extras':[
        {'source':str(files[1]),'provider_order':1,'complete':not malformed},
        {'source':str(files[2]),'provider_order':2,'complete':True},
        {'source':str(files[3]),'provider_order':3,'complete':True}]}))
    assets_before={str(path.relative_to(root)):file_sha256(path) for path in (root/'assets').rglob('*') if path.is_file()}
    result=invoke('candidate','import','--case-root',root,'--task-id',task,'--image',files[0],'--metadata',metadata,'--submission','already_recorded',expected=2)
    assert result['code']=='extra_sampling'
    after=invoke('case','show','--case-root',root)
    assert after['workflow_state']=='FAILED' and after['budget']['consumed']==4 and after['candidates']==[]
    assert {str(path.relative_to(root)):file_sha256(path) for path in (root/'assets').rglob('*') if path.is_file()}==assets_before
    audit=read_json(next((root/'external_observations').rglob('observation.json')))
    assert [row['observed_provider_order'] for row in audit['files']]==[0,1,2,3]
    assert all(row['sha256']==file_sha256(original)==file_sha256(root/row['path']) for row,original in zip(audit['files'],files))


@pytest.mark.parametrize('conflict',[False,True])
def test_watch_deduplicates_unchanged_stale_or_conflicting_submission(tmp_path,conflict):
    from hre.cli import current_request
    from hre.models import request_hash
    from hre.protocol import TaskWriter
    from hre.workflow import Controller
    from test_hre_protocol import diagnosis
    root=create(tmp_path,'agent_single');invoke('case','start','--case-root',root);request=current_request(root)
    if conflict:
        original=TaskWriter(root).commit_submission(request,diagnosis());assert Controller(root).consume_done(original).accepted
        changed=diagnosis();changed['global_gaps'][0]['observation']='Distinct synthetic conflicting diagnosis'
        TaskWriter(root).commit_submission(request,changed)
    else:
        stale={**request,'case_revision':request['case_revision']+1};stale['request_sha256']=request_hash(stale)
        TaskWriter(root).commit_submission(stale,diagnosis())
    first=invoke('watch','--case-root',root,'--max-polls','1','--interval','0')
    assert len(list((root/'quarantine').glob('rejected_*')))==1
    for _ in range(2):
        repeated=invoke('watch','--case-root',root,'--max-polls','1','--interval','0')
        assert repeated['revision']==first['revision'] and repeated['pending_task']==first['pending_task']
    if not conflict:
        TaskWriter(root).commit_submission(request,diagnosis())
        assert invoke('watch','--case-root',root,'--max-polls','1','--interval','0')['workflow_state']=='WAIT_COMPOSITION'
        invoke('watch','--case-root',root,'--max-polls','1','--interval','0')
    assert len(list((root/'quarantine').glob('rejected_*')))==1


def test_watch_receipt_does_not_retry_rejection_due_to_controller_audit_changes(tmp_path):
    from hre.cli import current_request
    from hre.models import file_sha256
    from hre.protocol import TaskWriter
    from hre.storage import read_json, write_json
    from test_hre_protocol import diagnosis
    root=create(tmp_path,'agent_single');invoke('case','start','--case-root',root)
    done=TaskWriter(root).commit_submission(current_request(root),diagnosis())
    marker=read_json(done);marker['response_file']='state.json';marker['response_sha256']=file_sha256(root/'state.json');write_json(done,marker)
    first=invoke('watch','--case-root',root,'--max-polls','1','--interval','0')
    after=invoke('watch','--case-root',root,'--max-polls','2','--interval','0')
    assert after['revision']==first['revision'] and len(list((root/'quarantine').glob('rejected_*')))==1
