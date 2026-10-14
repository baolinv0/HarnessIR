"""Audited local CLI. --case-root is one frozen revision; --data-root is a collection."""
from pathlib import Path
import argparse
import json
import os
import signal
import threading
import time

from hre.models import HREError, SCHEMA_VERSION


def list_cases(data_root: Path) -> list[dict]:
    from hre.storage import read_json
    result=[]
    if not data_root.exists(): return result
    for path in sorted(data_root.rglob('state.json')):
        try:
            state=read_json(path)
            result.append({'case_root':str(path.parent.resolve()),'case_id':state.get('case_id','unknown'),
                           'case_revision':state.get('case_revision'),'workflow_state':state.get('workflow_state','historical'),
                           'schema_version':state.get('schema_version','unknown'),'compatible':state.get('schema_version')==SCHEMA_VERSION})
        except (HREError,ValueError,OSError) as exc:
            result.append({'case_root':str(path.parent.resolve()),'compatible':False,'error':str(exc)})
    return result


def current_request(case_root: Path) -> dict:
    from hre.workflow import Controller
    from hre.paths import safe_path
    from hre.storage import read_json
    pending=Controller(case_root).state()['pending_task']
    if not pending: raise HREError('no_pending_task','This revision has no pending task.')
    return read_json(safe_path(case_root,pending['request_path'],must_exist=True))


def import_payload(case_root: Path, payload: dict, *, raw_text: bytes=b'', provenance: dict|None=None, error: dict|None=None):
    from hre.protocol import TaskWriter
    from hre.workflow import Controller
    request=current_request(case_root)
    done=TaskWriter(case_root).commit_submission(request,payload,raw_text=raw_text,provenance=provenance,error=error)
    return Controller(case_root).consume_done(done)


def archive_external_observation(case_root: Path, request: dict, image: Path, metadata: dict) -> Path:
    """Preserve downloaded bytes before terminal accounting; this is not a formal candidate."""
    from hre.models import canonical_json, file_sha256, sha256_bytes, now
    from hre.paths import safe_path
    from hre.storage import atomic_write, write_json, read_json
    sources=[Path(image)]+[Path(item['source']) for item in metadata.get('extras',[])]
    observations=[{'provider_order':metadata['provider_order'],'complete':True}]+metadata.get('extras',[])
    for source in sources:
        if source.is_symlink() or not source.is_file():raise HREError('unsafe_path','Raw observation source must be a real file.')
    hashes=[file_sha256(path) for path in sources]
    identity={'task_id':request['task_id'],'request_sha256':request['request_sha256'],'metadata':metadata,'raw_sha256':hashes}
    digest=sha256_bytes(canonical_json(identity))
    directory=safe_path(case_root,'external_observations/observation_'+digest)
    manifest_path=directory/'observation.json'
    if manifest_path.exists():
        manifest=read_json(manifest_path)
        for item in manifest['files']:
            if file_sha256(safe_path(case_root,item['path'],must_exist=True))!=item['sha256']:raise HREError('observation_modified','Immutable external audit bytes changed.')
        return manifest_path
    directory.mkdir(parents=True,exist_ok=False)
    records=[]
    for index,(source,digest_file) in enumerate(zip(sources,hashes)):
        target=directory/f'raw_{index:03d}.bin'
        atomic_write(target,source.read_bytes())
        if file_sha256(target)!=digest_file:raise HREError('source_changed','Downloaded output changed while archiving.')
        records.append({'path':target.relative_to(case_root).as_posix(),'sha256':digest_file,'download_index':index,'source_name':source.name,
                        'observed_provider_order':observations[index]['provider_order'],'declared_complete':observations[index]['complete']})
    write_json(manifest_path,{'schema_version':SCHEMA_VERSION,'case_id':request['case_id'],'case_revision':request['case_revision'],
                             'task_id':request['task_id'],'request_sha256':request['request_sha256'],'config_sha256':request['config_sha256'],
                             'audit_only':True,'not_ground_truth':True,'created_at':now(),'metadata':metadata,'files':records})
    return manifest_path


def import_candidate_manual(case_root: Path, task_id: str, image: Path, metadata: dict, submission: str):
    from hre.workflow import Controller
    from hre.desktop import import_candidate, validate_output_order
    controller=Controller(case_root); request=current_request(case_root)
    if request['task_id']!=task_id or request['stage']!='execute':
        raise HREError('wrong_task','Candidate must bind to the current execution task.')
    if submission=='unknown':
        controller.mark_submission_unknown(task_id,'submission_fact_unknown')
        raise HREError('submission_unknown','No automatic resubmission or generation count guessed.')
    if submission=='not_submitted':
        controller.release_unsubmitted(task_id)
        raise HREError('not_submitted','Reservation released using confirmed unsubmitted status; no candidate accepted.')
    ordered=validate_output_order(metadata)
    metadata={**metadata,'extras':[{**item,'source':str(item['source'])} for item in ordered]}
    if submission not in {'submitted','already_recorded'}:
        raise HREError('invalid_submission','Explicit submitted or already_recorded status is required.')
    state=controller.state()
    entry=next((e for e in state['budget']['ledger'] if e['task_id']==task_id),None)
    if submission=='already_recorded' and (entry is None or entry['status']!='submitted'):
        raise HREError('submission_unconfirmed','already_recorded requires a confirmed submitted ledger entry.')
    count=metadata['actual_generation_count'];charged=entry['charged_count'] if entry else 0
    if state['budget']['consumed']+max(0,count-charged)>state['budget']['max_generations']:
        audit=archive_external_observation(case_root,request,image,metadata)
        controller.mark_submitted(task_id,count=count)
        raise HREError('extra_sampling',f'Observed budget exceeded; all downloaded raw outputs retained for audit at {audit}. No formal candidate promoted.')
    # Observed cumulative count is reconciled for either confirmed intake route,
    # including when the initial count was recorded before downloads completed.
    controller.mark_submitted(task_id,count=count)
    metadata={**metadata,'submitted':True}
    done=import_candidate(case_root,task_id,image,metadata)
    return controller.consume_done(done)


def _watch_fingerprint(case_root: Path, marker: Path, state: dict) -> str:
    """Observe actual dependency bytes so a completed partial transfer gets rechecked."""
    from hre.models import canonical_json, file_sha256, sha256_bytes
    from hre.paths import safe_path
    from hre.storage import read_json
    dependencies={};visited=set()
    def observe(relative: str, depth: int=0):
        if relative in visited:return
        visited.add(relative)
        # Rejection/state projection writes cannot masquerade as corrected transfers.
        if relative in {'state.json','watch_receipts.json'} or relative.split('/')[0] in {'transactions','quarantine','exports','final'}:
            dependencies[relative]='controller_owned_audit'
            return
        try:
            path=safe_path(case_root,relative,must_exist=True)
            dependencies[relative]=file_sha256(path)
            if depth<4 and path.suffix=='.json':
                try:references(read_json(path),depth+1)
                except (HREError,OSError,ValueError,TypeError):pass
        except (HREError,OSError,ValueError) as exc:
            dependencies[relative]='unavailable:'+getattr(exc,'code',type(exc).__name__)
    def references(value,depth: int=0):
        if isinstance(value,dict):
            for key,item in value.items():
                if isinstance(item,str) and (key=='path' or key=='response_file' or key.endswith('_path')):observe(item,depth)
                elif isinstance(item,(dict,list)):references(item,depth)
        elif isinstance(value,list):
            for item in value:references(item,depth)
    relative=marker.relative_to(case_root).as_posix();observe(relative)
    try:done=read_json(marker)
    except (HREError,OSError,ValueError):done={}
    task_id=done.get('task_id') if isinstance(done,dict) else None
    pending=state.get('pending_task') or {}
    current=bool(task_id and pending.get('task_id')==task_id and pending.get('request_sha256')==done.get('request_sha256'))
    if isinstance(task_id,str):
        try:
            task_root=safe_path(case_root,'tasks/'+task_id)
            for request in sorted(task_root.glob('attempts/*/request.json')):observe(request.relative_to(case_root).as_posix())
        except (HREError,OSError,ValueError):pass
    references(state['inputs'])
    entries=[entry for entry in state['budget']['ledger'] if entry['task_id']==task_id]
    context={'case_revision':state['case_revision'],'is_current_request':current,
             'submission_facts':[{key:entry[key] for key in ('status','charged_count','submitted_at')} for entry in entries]}
    return sha256_bytes(canonical_json({'marker':relative,'dependencies':dependencies,'context':context}))


def watch(case_root: Path, max_polls: int=1, interval: float=1.0, *, stop: threading.Event|None=None) -> dict:
    """Consume genuine submission inboxes; skip unchanged receipts, never generate images."""
    from hre.workflow import Controller
    from hre.paths import safe_path
    from hre.storage import read_json, write_json, case_lock
    if max_polls<1 or interval<0:raise HREError('invalid_watch','max-polls >=1 and interval >=0 required.')
    case_root=Path(os.path.abspath(case_root));stop=stop or threading.Event();controller=Controller(case_root)
    receipt_path=safe_path(case_root,'watch_receipts.json')
    def load_receipts():
        if not receipt_path.exists():return {}
        value=read_json(receipt_path)
        return value.get('submissions',{}) if isinstance(value.get('submissions'),dict) else {}
    receipts=load_receipts()
    for index in range(max_polls):
        if stop.is_set():break
        state=controller.state()
        if state['workflow_state'] in {'COMPLETED','FAILED','CANCELLED','PAUSED'}:break
        if state['workflow_state']=='WAIT_EVIDENCE':controller.collect_evidence()
        else:
            inbox=safe_path(case_root,'tasks')
            for marker in sorted(inbox.glob('*/submissions/*/pending/done.json')):
                if stop.is_set():break
                state=controller.state()
                if state['workflow_state'] in {'COMPLETED','FAILED','CANCELLED','PAUSED'}:break
                relative=marker.relative_to(case_root).as_posix()
                fingerprint=_watch_fingerprint(case_root,marker,state)
                if receipts.get(relative,{}).get('fingerprint')==fingerprint:continue
                result=controller.consume_done(marker)
                receipt={'fingerprint':fingerprint,'accepted':result.accepted,'code':result.code}
                with case_lock(case_root):
                    receipts=load_receipts();receipts[relative]=receipt
                    write_json(receipt_path,{'kind':'hre_watch_receipts_v1','submissions':receipts})
        if index+1<max_polls:stop.wait(interval)
    return controller.state()


def build_parser() -> argparse.ArgumentParser:
    parser=argparse.ArgumentParser(prog='hre',description=__doc__)
    groups=parser.add_subparsers(dest='command',required=True)
    def root(p):p.add_argument('--case-root',type=Path,required=True,help='Exact case revision directory containing state.json; never the collection.')
    case=groups.add_parser('case').add_subparsers(dest='action',required=True)
    p=case.add_parser('create');root(p)
    p.add_argument('--prediction',type=Path,required=True);p.add_argument('--reference',type=Path,required=True)
    p.add_argument('--manifest',type=Path);p.add_argument('--config',type=Path)
    p.add_argument('--profile',choices=['baseline','direct_ref','agent_single','agent_adaptive','direct_best_of_3'])
    p.add_argument('--assume-srgb',action='store_true',default=None)
    p.add_argument('--reference-usable',choices=['usable','unknown','unusable'])
    p=case.add_parser('list');p.add_argument('--data-root',type=Path,required=True,help='Collection searched read-only for current and historical states.')
    for name in ['show','start','pause','resume','cancel','recover','retry-transport']:
        p=case.add_parser(name);root(p)
        if name in {'pause','cancel'}:p.add_argument('--reason',default='operator request')
        if name=='resume':p.add_argument('--action',dest='resume_action',default='continue')
    task=groups.add_parser('task').add_subparsers(dest='action',required=True)
    p=task.add_parser('export');root(p);p.add_argument('--out',type=Path,required=True)
    for name in ['submitted','unknown','release-unsubmitted']:
        p=task.add_parser(name);root(p);p.add_argument('--task-id',required=True)
        if name=='submitted':p.add_argument('--count',type=int,default=1)
    response=groups.add_parser('response').add_subparsers(dest='action',required=True)
    p=response.add_parser('import');root(p)
    inp=p.add_mutually_exclusive_group();inp.add_argument('--payload',type=Path);inp.add_argument('--response',type=Path);p.add_argument('--done',type=Path)
    p.add_argument('--response-done',type=Path,help='Use with --response for an existing protocol envelope/done pair.')
    p.add_argument('--metadata',type=Path)
    candidate=groups.add_parser('candidate').add_subparsers(dest='action',required=True)
    p=candidate.add_parser('import');root(p);p.add_argument('--task-id',required=True);p.add_argument('--image',type=Path,required=True);p.add_argument('--metadata',type=Path)
    p.add_argument('--extra',type=Path,action='append',default=[],help='Extra raw source; each requires a corresponding explicit --extra-order and --extra-complete.')
    p.add_argument('--extra-order',type=int,action='append',default=[])
    p.add_argument('--extra-complete',choices=['true','false'],action='append',default=[])
    p.add_argument('--submission',choices=['submitted','already_recorded','unknown','not_submitted'],required=True)
    cap=groups.add_parser('capabilities').add_subparsers(dest='action',required=True)
    p=cap.add_parser('probe');root(p);p.add_argument('--name',choices=['local_file_io','role_dispatch','two_image_edit','image_save','all'],default='all');p.add_argument('--evidence',type=Path)
    evidence=groups.add_parser('evidence').add_subparsers(dest='action',required=True)
    p=evidence.add_parser('collect');root(p)
    p=evidence.add_parser('import');p.add_argument('--bundle',type=Path,required=True);p.add_argument('--cache-root',type=Path,required=True)
    tools=groups.add_parser('tools').add_subparsers(dest='action',required=True)
    p=tools.add_parser('import-cache');p.add_argument('--bundle',type=Path,required=True);p.add_argument('--cache-root',type=Path,required=True)
    p=tools.add_parser('export-missing');root(p);p.add_argument('--out',type=Path,required=True)
    p=tools.add_parser('precompute');root(p);p.add_argument('--plan',type=Path);p.add_argument('--out',type=Path,required=True)
    p=groups.add_parser('watch');root(p);p.add_argument('--max-polls',type=int,default=1);p.add_argument('--interval',type=float,default=1.0)
    p=groups.add_parser('report');root(p)
    run=groups.add_parser('run').add_subparsers(dest='action',required=True)
    p=run.add_parser('freeze');p.add_argument('--manifest',type=Path,required=True);p.add_argument('--profile',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    ev=groups.add_parser('evaluation').add_subparsers(dest='action',required=True)
    for name in ['export','analyze']:
        p=ev.add_parser(name);p.add_argument('--run',type=Path,required=True)
        if name=='export':p.add_argument('--out',type=Path,required=True)
        else:p.add_argument('--ratings',type=Path,required=True)
    return parser


def dispatch(args):
    from hre.storage import read_json
    if hasattr(args,'case_root'):args.case_root=Path(os.path.abspath(args.case_root))
    if args.command=='case' and args.action=='list':return list_cases(args.data_root)
    if args.command=='case' and args.action=='create':
        from hre.assets import create_case
        config=read_json(args.config) if args.config else {}
        for key,value in [('profile_id',args.profile),('assume_srgb',args.assume_srgb),('reference_usable',args.reference_usable)]:
            if value is not None:config[key]=value
        return create_case(args.prediction,args.reference,read_json(args.manifest) if args.manifest else {},config,args.case_root)
    if args.command in {'run','evaluation'}:
        from hre.experiments import freeze_run, export_blind_evaluation, summarize_evaluation
        if args.command=='run':return {'path':str(freeze_run(args.manifest,args.profile,args.out))}
        if args.action=='export':return {'path':str(export_blind_evaluation(args.run,args.out))}
        return summarize_evaluation(args.run,args.ratings)
    if (args.command=='evidence' and args.action=='import') or (args.command=='tools' and args.action=='import-cache'):
        from hre.evidence import register_cache_bundle
        return register_cache_bundle(args.bundle,args.cache_root)
    from hre.workflow import Controller
    controller=Controller(args.case_root)
    if args.command=='case':
        if args.action=='show':return controller.state()
        if args.action in {'pause','cancel'}:return getattr(controller,args.action)(args.reason)
        if args.action=='resume':return controller.resume(args.resume_action)
        return getattr(controller,args.action.replace('-','_'))()
    if args.command=='task':
        if args.action=='submitted':return controller.mark_submitted(args.task_id,args.count)
        if args.action=='release-unsubmitted':return controller.release_unsubmitted(args.task_id)
        if args.action=='unknown':return controller.mark_submission_unknown(args.task_id)
        from hre.desktop import export_task_bundle
        return {'path':str(export_task_bundle(current_request(args.case_root),args.out,case_root=args.case_root))}
    if args.command=='response':
        if args.payload and args.done:raise HREError('ambiguous_import','Choose payload wrapping or existing done ingestion.')
        if not(args.payload or args.response or args.done):raise HREError('missing_input','Supply --payload, --done or --response with --done.')
        if args.payload:return import_payload(args.case_root,read_json(args.payload),raw_text=args.payload.read_bytes(),provenance=read_json(args.metadata) if args.metadata else None)
        if args.response:
            marker=args.done or args.response_done
            if not marker:raise HREError('missing_done','--response requires --done; --payload wraps stage JSON in the current identity.')
            return controller.ingest_response(args.response,marker)
        return controller.consume_done(args.done)
    if args.command=='candidate':
        metadata=read_json(args.metadata) if args.metadata else {}
        if not(len(args.extra)==len(args.extra_order)==len(args.extra_complete)):
            raise HREError('extra_order_required','Each --extra needs an explicit --extra-order and --extra-complete; order is never inferred from filenames or selection.')
        declared=[{'source':str(path),'provider_order':order,'complete':complete=='true'} for path,order,complete in zip(args.extra,args.extra_order,args.extra_complete)]
        if declared:metadata={**metadata,'extras':metadata.get('extras',[])+declared}
        return import_candidate_manual(args.case_root,args.task_id,args.image,metadata,args.submission)
    if args.command=='capabilities':
        from hre.capabilities import run_capability_probe
        names=['local_file_io','role_dispatch','two_image_edit','image_save'] if args.name=='all' else [args.name]
        evidence=read_json(args.evidence) if args.evidence else None
        return {name:run_capability_probe(name,args.case_root,evidence=evidence) for name in names}
    if args.command=='tools':
        from hre.evidence import EvidenceService
        state=controller.state();service=EvidenceService(args.case_root)
        if args.action=='precompute':
            plan=read_json(args.plan)['plan'] if args.plan else state['evidence_plan']
            return {'path':str(service.precompute_bundle(state,plan,args.out))}
        return {'path':str(service.export_missing_jobs(state,args.out))}
    if args.command=='evidence':return controller.collect_evidence()
    if args.command=='report':
        from hre.reporting import write_report
        return {'path':str(write_report(args.case_root))}
    if args.command=='watch':
        stop=threading.Event()
        old=signal.signal(signal.SIGINT,lambda *_:stop.set())
        try:return watch(args.case_root,args.max_polls,args.interval,stop=stop)
        finally:signal.signal(signal.SIGINT,old)
    raise HREError('unknown_command',args.command)


def main(argv=None) -> int:
    args=build_parser().parse_args(argv)
    try:
        value=dispatch(args)
        if hasattr(value,'model_dump'):value=value.model_dump()
        print(json.dumps(value,ensure_ascii=False,allow_nan=False,default=str))
        return 2 if isinstance(value,dict) and value.get('accepted') is False else 0
    except (HREError,OSError,ValueError,KeyError) as exc:
        print(json.dumps({'accepted':False,'code':getattr(exc,'code','input_error'),'message':str(exc)}))
        return 2


if __name__=='__main__':raise SystemExit(main())
