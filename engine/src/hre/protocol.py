"""Immutable response/done handoff, with no state or model side effects."""
from pathlib import Path
from datetime import datetime
import copy

from .models import SCHEMA_VERSION,HREError,canonical_json,file_sha256,request_hash,config_hash,sha256_bytes,now,validate_schema
from .paths import safe_path,make_id
from .storage import atomic_write,write_json,read_json
from .assets import validate_asset

IDENTITY=('schema_version','case_id','case_revision','state_revision_issued','task_id','stage','round','attempt','request_sha256','config_sha256','input_assets','prompt_version')


def _path(root:Path,path:Path)->Path:
    try:relative=path.absolute().relative_to(root.absolute()).as_posix()
    except ValueError:raise HREError('path_escape','Submission must be inside case root')
    return safe_path(root,relative,must_exist=True)


def _time(value:str)->datetime:
    d=datetime.fromisoformat(value.replace('Z','+00:00'))
    if d.tzinfo is None: raise HREError('invalid_time','Timestamp must include timezone')
    return d


def validate_request(case_root:Path,request:dict,state:dict)->None:
    validate_schema('request',request)
    if request_hash(request)!=request['request_sha256']:raise HREError('request_hash_mismatch','Request was modified')
    cfg=read_json(safe_path(case_root,'config.json',must_exist=True))
    if config_hash(cfg)!=request['config_sha256'] or state['config_sha256']!=request['config_sha256']:
        raise HREError('config_hash_mismatch','Frozen configuration was modified')
    for k in ('case_id','case_revision'):
        if request[k]!=state[k]:raise HREError('identity_mismatch',k)
    expected=state['inputs']
    if request['input_assets'][:2]!=expected:
        raise HREError('input_asset_mismatch','A/B must echo frozen assets in registered order')
    for a in request['input_assets']:validate_asset(a,case_root)
    # Audit references are immutable byte-bound artifacts, independent of latest state revision.
    p=request['payload']
    for path_key,hash_key in [('roi_manifest_path','roi_manifest_sha256'),('evidence_snapshot_path','evidence_snapshot_sha256'),('geometry_report_path','geometry_report_sha256')]:
        if p.get(path_key) is not None:
            f=safe_path(case_root,p[path_key],must_exist=True)
            if file_sha256(f)!=p[hash_key]:raise HREError('artifact_hash_mismatch',path_key)
    if request['stage']=='execute':
        source=p['prompt_source_task_id']
        if source.startswith('compiled_'):
            from .condition_handoff import compiled_condition
            compiled_condition(case_root,request)
        elif cfg.get('reference_v2',{}).get('arm_id')=='G2':
            from .prompts import _validate_prompt_source
            _validate_prompt_source(case_root,request)
        elif state['profile_id'] in ('direct_ref','direct_best_of_3'):
            expected=f"direct_prompt_{state['case_id']}_rev_{state['case_revision']}"
            record=read_json(safe_path(case_root,f'tasks/{source}/manifest.json',must_exist=True))
            if source!=expected or record.get('task_id')!=expected or record.get('edit_prompt')!=p['edit_prompt'] or record.get('prompt_sha256')!=sha256_bytes(p['edit_prompt'].encode()) or record.get('config_sha256')!=request['config_sha256'] or record.get('prompt_version')!='direct_ref_v1':
                raise HREError('prompt_source_mismatch','Frozen direct prompt artifact differs from request')
        else:
            accepted=read_json(safe_path(case_root,f'tasks/{source}/accepted/submission.json',must_exist=True))
            response_path=safe_path(case_root,accepted['response_path'],must_exist=True)
            response=read_json(response_path)
            if file_sha256(response_path)!=accepted['response_sha256'] or response['task_id']!=source or response['stage'] not in ('compose','refine') or response['status']!='ok' or response['payload']['edit_prompt']!=p['edit_prompt'] or any(response[k]!=request[k] for k in ('case_id','case_revision','config_sha256')):
                raise HREError('prompt_source_mismatch','Editing prompt must equal its accepted source result')
    if 'evidence_snapshot_path' in p:
        snap=read_json(safe_path(case_root,p['evidence_snapshot_path'],must_exist=True))
        validate_schema('evidence',snap,fragment='/$defs/snapshot')
        for k in ('case_id','case_revision','config_sha256'):
            if snap[k]!=request[k]:raise HREError('snapshot_binding_mismatch',k)
        if state['profile_id'].startswith('agent_') and snap['diagnosis_task_id'] is None:
            raise HREError('snapshot_binding_mismatch','Agent snapshot needs accepted diagnosis')
        for record in snap['evidence']:
            if file_sha256(safe_path(case_root,record['path'],must_exist=True))!=record['sha256']:
                raise HREError('snapshot_record_modified',record['path'])


def _validate_semantics(response:dict,request:dict,state:dict,case_root:Path)->None:
    if response['status']=='error':return
    p=response['payload'];stage=request['stage']
    if stage in ('compose','refine') and not p['edit_prompt'].strip():
        raise HREError('empty_edit_prompt','Edit prompt must contain text')
    if stage=='verify':
        kinds=[o['kind'] for o in p['preservation_observations']]
        if len(kinds)!=len(set(kinds)):raise HREError('verification_contradiction','Duplicate preservation categories')
    if stage=='refine' and p['source_round']!=request['payload']['source_round']:
        raise HREError('candidate_binding_mismatch','Refinement source round differs')
    if stage=='execute':
        asset=p['candidate_asset'];b=asset['candidate_binding'];rp=request['payload']
        expected={k:request[k] for k in ('case_id','case_revision','task_id','round')}
        expected.update(generation_id=rp['generation_id'],prediction_sha256=state['inputs'][0]['sha256'],reference_sha256=state['inputs'][1]['sha256'])
        if b!=expected or p['generation_id']!=rp['generation_id']:
            raise HREError('candidate_binding_mismatch','Candidate belongs to different source/generation')
        validate_asset(asset,case_root)
        cfg=read_json(safe_path(case_root,'config.json',must_exist=True))
        if 'reference_v2' in cfg:
            expected_executor=cfg['reference_v2']['executor'];observed=response['model_observed']
            if (observed['ui_model_name']!=expected_executor['model_display_name'] or observed['transport']!=expected_executor['transport']
                or (expected_executor['model_exact_version'] is not None and observed['exact_model_version']!=expected_executor['model_exact_version'])
                or ('seed' in expected_executor['settings'] and observed['seed']!=expected_executor['settings']['seed'])):
                raise HREError('executor_mismatch','Observed image executor differs from the frozen same-model comparison')
        policy={k:cfg[k] for k in ('assume_srgb','canonicalizer_version')}
        if asset['canonicalization']['conversion_policy_sha256']!=sha256_bytes(canonical_json(policy)) or asset['canonicalization']['canonicalizer_version']!=cfg['canonicalizer_version']:
            raise HREError('color_policy_mismatch','Candidate normalization differs from frozen input policy')
        if asset['source_file']['icc_sha256'] is None and not cfg['assume_srgb']:
            raise HREError('color_policy_mismatch','Unprofiled candidate needs frozen sRGB assumption')


ORDER_KIND='hre_output_order_v1'


def _order_record(path:Path)->dict|None:
    try:
        value=read_json(path)
    except (HREError,OSError):return None
    return value if value.get('kind')==ORDER_KIND else None


def _validate_output_order(root:Path,artifacts:dict,payload:dict,request:dict)->None:
    manifests=[value for item in artifacts.values() if item['kind']=='auxiliary' and (value:=_order_record(safe_path(root,item['path'],must_exist=True))) is not None]
    if not manifests:
        if payload['provider_order']!=0 or payload['extras'] or payload['actual_generation_count']!=1:
            raise HREError('output_order_unknown','Non-singleton output requires typed provider-order evidence')
        return
    if len(manifests)!=1:raise HREError('output_order_conflict','Exactly one typed provider-order record is allowed')
    order=manifests[0]
    required={'kind','task_id','request_sha256','generation_id','candidate_id','actual_generation_count','outputs'}
    if set(order)!=required or type(order['actual_generation_count']) is not int or not isinstance(order['outputs'],list) or not order['outputs']:
        raise HREError('output_order_schema','Invalid provider-order record shape')
    expected=dict(task_id=request['task_id'],request_sha256=request['request_sha256'],generation_id=payload['generation_id'],candidate_id=payload['candidate_asset']['asset_id'],actual_generation_count=payload['actual_generation_count'])
    if any(order[k]!=value for k,value in expected.items()):raise HREError('output_order_binding','Provider-order record belongs to different task or generation')
    rows=order['outputs'];seen=set();formal=[];complete=[]
    from PIL import Image
    for row in rows:
        if not isinstance(row,dict) or set(row)!={'provider_order','complete','path','sha256','formal'} or type(row['provider_order']) is not int or type(row['complete']) is not bool or type(row['formal']) is not bool:
            raise HREError('output_order_schema','Invalid provider-order row')
        index=row['provider_order']
        if index<0 or index>=order['actual_generation_count'] or index in seen:raise HREError('output_order_range','Provider order must be unique within charged count')
        seen.add(index)
        item=artifacts.get(row['path'])
        if item is None or item['sha256']!=row['sha256']:raise HREError('output_order_artifact','Every provider output must be hash-bound in done')
        path=safe_path(root,row['path'],must_exist=True)
        decoded=True
        try:
            with Image.open(path) as image:image.load()
        except Exception:decoded=False
        if decoded!=row['complete']:raise HREError('output_order_completeness','Provider completeness contradicts actual decoded bytes')
        if row['complete']:complete.append(row)
        if row['formal']:formal.append(row)
    if len(formal)!=1 or not formal[0]['complete'] or not complete:
        raise HREError('output_order_formal','Exactly one complete formal output is required')
    first=formal[0];raw=payload['candidate_asset']['source_file']
    if first['provider_order']!=payload['provider_order'] or first['path']!=raw['path'] or first['sha256']!=raw['sha256']:
        raise HREError('output_order_formal','Formal output differs from candidate raw source')
    if set(range(first['provider_order']+1))-seen or first['provider_order']!=min(row['provider_order'] for row in complete):
        raise HREError('output_order_selection','Formal output must be first complete with every earlier order observed')
    extras={(e['path'],e['sha256']) for e in payload['extras']}
    others={(row['path'],row['sha256']) for row in complete if not row['formal']}
    if extras!=others:raise HREError('output_order_extras','Complete nonformal outputs must match all preserved extras')


def validate_submission(case_root:Path,done_path:Path,request:dict,state:dict)->dict:
    root=Path(case_root).absolute(); done_path=_path(root,Path(done_path))
    if done_path.name!='done.json':raise HREError('incomplete_submission','Only final done.json may be consumed')
    done=read_json(done_path);validate_schema('response',done,fragment='/$defs/done_manifest')
    submission_path=done_path.parent
    prefix=f"tasks/{request['task_id']}/submissions/"
    rel=submission_path.relative_to(root).as_posix()
    if not rel.startswith(prefix) or submission_path.name!='pending' or len(submission_path.relative_to(root).parts)!=5:
        raise HREError('submission_directory_mismatch','Done is outside authorized pending directory')
    for k in ('schema_version','case_id','case_revision','task_id','request_sha256'):
        if done[k]!=request[k]:raise HREError('identity_mismatch',k)
    response_path=safe_path(root,done['response_file'],must_exist=True)
    if response_path.parent!=submission_path:raise HREError('path_escape','Response must share submission directory')
    if file_sha256(response_path)!=done['response_sha256']:raise HREError('response_hash_mismatch','Response bytes differ from done')
    response=read_json(response_path);validate_schema('response',response)
    validate_request(root,request,state)
    for k in IDENTITY:
        if response[k]!=request[k]:raise HREError('identity_mismatch',k)
    artifacts={}
    for item in done['artifacts']:
        f=safe_path(root,item['path'],must_exist=True)
        if f.parent!=submission_path:raise HREError('path_escape','Artifacts must stay in their submission directory')
        if item['path'] in artifacts:raise HREError('duplicate_artifact','Artifact path repeated')
        if f.suffix in ('.part','.tmp') or file_sha256(f)!=item['sha256']:raise HREError('artifact_hash_mismatch',item['path'])
        artifacts[item['path']]=item
    if response['status']=='ok' and request['stage']=='execute':
        p=response['payload'];a=p['candidate_asset']
        for path,sha in [(a['path'],a['sha256']),(a['source_file']['path'],a['source_file']['sha256'])]+[(e['path'],e['sha256']) for e in p['extras']]:
            if path not in artifacts or artifacts[path]['sha256']!=sha:
                raise HREError('missing_artifact','Every execution image must be explicitly committed')
        if p['actual_generation_count']<1+len(p['extras']):raise HREError('invalid_generation_count','Extras must be charged')
        _validate_output_order(root,artifacts,p,request)
        from .reference_execution import validate_committed_execution
        validate_committed_execution(root,request,response,artifacts)
    if _time(response['model_observed']['observed_at'])>_time(done['completed_at']):
        raise HREError('invalid_time','Observation occurs after done')
    if response['status']=='ok' and request['stage']=='execute' and _time(response['payload']['submitted_at'])>_time(done['completed_at']):
        raise HREError('invalid_time','Submission occurs after done')
    _validate_semantics(response,request,state,root)
    return dict(response=response,response_sha256=done['response_sha256'],done=done,submission_path=rel)


class TaskWriter:
    def __init__(self,case_root:Path):self.root=Path(case_root).absolute()

    def commit_submission(self,request:dict,payload:dict|None,raw_text:bytes=b'',files:list[Path]|None=None,provenance:dict|None=None,error:dict|None=None)->Path:
        validate_schema('request',request)
        if request_hash(request)!=request['request_sha256']:raise HREError('request_hash_mismatch','Invalid request')
        sid=make_id('submission');directory=safe_path(self.root,f"tasks/{request['task_id']}/submissions/{sid}/pending")
        directory.mkdir(parents=True,exist_ok=False)
        payload=copy.deepcopy(payload);artifacts=[]
        mapping={}
        # Files already materialized by a bridge may be referenced in the payload.
        sources=list(files or [])
        if request['stage']=='execute' and payload is not None:
            a=payload['candidate_asset']
            sources += [safe_path(self.root,a['path'],must_exist=True),safe_path(self.root,a['source_file']['path'],must_exist=True)]
            sources += [safe_path(self.root,e['path'],must_exist=True) for e in payload['extras']]
        seen=set();order_copies=[]
        for i,source in enumerate(sources):
            source=Path(source)
            old=None
            if source.is_symlink() or not source.is_file():raise HREError('unsafe_path','Submission source must be a regular file')
            if source.resolve() in seen:continue
            seen.add(source.resolve());suffix=source.suffix.lower()
            if suffix in ('.tmp','.part') or not suffix:suffix='.bin'
            name=f'artifact_{i:03d}{suffix}'
            dest=directory/name;atomic_write(dest,source.read_bytes())
            try:old=source.relative_to(self.root).as_posix();mapping[old]=dest.relative_to(self.root).as_posix()
            except ValueError:pass
            kind='auxiliary'
            if request['stage']=='execute' and payload is not None:
                a=payload['candidate_asset']
                if old==a['path']:kind='canonical_image'
                elif old==a['source_file']['path'] or any(old==extra['path'] for extra in payload['extras']):kind='raw_image'
            artifacts.append(dict(path=dest.relative_to(self.root).as_posix(),sha256=file_sha256(dest),kind=kind))
            if kind=='auxiliary':
                order=_order_record(dest)
                if order is not None:order_copies.append((dest,order,artifacts[-1]))
        for dest,order,item in order_copies:
            for row in order.get('outputs',[]):
                old_path=row['path']
                if old_path not in mapping:raise HREError('output_order_artifact','Provider output was not copied into submission')
                row['path']=mapping[old_path]
                actual_sha=file_sha256(safe_path(self.root,row['path'],must_exist=True))
                if row['sha256']!=actual_sha:raise HREError('output_order_artifact','Provider raw hash differs before path materialization')
                row['sha256']=actual_sha
            write_json(dest,order);item['sha256']=file_sha256(dest)
        if request['stage']=='execute' and payload is not None:
            from .reference_execution import remap_submission_proofs
            remap_submission_proofs(self.root,artifacts,mapping)
        if request['stage']=='execute' and payload is not None:
            a=payload['candidate_asset'];a['path']=mapping[a['path']];a['source_file']['path']=mapping[a['source_file']['path']]
            for e in payload['extras']:e['path']=mapping[e['path']]
        if raw_text:
            raw=directory/'raw.txt';atomic_write(raw,raw_text);artifacts.append(dict(path=raw.relative_to(self.root).as_posix(),sha256=file_sha256(raw),kind='auxiliary'))
        observed=dict(ui_model_name='unknown',exact_model_version=None,seed=None,observed_at=now(),transport='desktop_manual',operator_steps=[])
        provenance=dict(provenance or {});session_id=provenance.pop('session_id',None)
        if 'model_observed' in provenance:observed.update(provenance['model_observed'])
        else:observed.update(provenance)
        response={k:copy.deepcopy(request[k]) for k in IDENTITY}
        response.update(status='error' if error is not None else 'ok',model_observed=observed,session_id=session_id,payload=payload,error=error)
        validate_schema('response',response)
        response_path=directory/'response.json';write_json(response_path,response)
        writer={'fixture':'fixture','desktop_bridge':'desktop_bridge','desktop_manual':'manual_import','api':'api_adapter'}[observed['transport']]
        done=dict(schema_version=SCHEMA_VERSION,case_id=request['case_id'],case_revision=request['case_revision'],task_id=request['task_id'],request_sha256=request['request_sha256'],response_file=response_path.relative_to(self.root).as_posix(),response_sha256=file_sha256(response_path),artifacts=artifacts,completed_at=now(),writer=writer)
        validate_schema('response',done,fragment='/$defs/done_manifest')
        path=directory/'done.json';write_json(path,done);return path

