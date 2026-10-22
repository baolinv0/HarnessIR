"""Two entry points over the same frozen handoffs: full run and stage checks.

External commands are explicit user configuration. They are invoked once; an
uncertain execution never becomes an automatic retry or an invented receipt.
"""
from copy import deepcopy
from pathlib import Path
import json
import math
import os

from .models import HREError, canonical_json, file_sha256, now, sha256_bytes, validate_schema
from .storage import read_json, write_json
from .paths import safe_path


def validate_workers(value):
    if not isinstance(value,dict) or set(value)-{'schema_version','workers','timeout_seconds'}:
        raise HREError('invalid_workers','Expected schema_version, workers and optional timeout_seconds')
    if value.get('schema_version')!='hre_workers_v1' or not isinstance(value.get('workers'),dict):
        raise HREError('invalid_workers','Expected hre_workers_v1 and a workers object')
    allowed={'stage','diagnose','compose','verify','refine','condition','execute'}
    for key,command in value['workers'].items():
        if key not in allowed or not isinstance(command,list) or not command or any(not isinstance(x,str) or not x or '\x00' in x for x in command):
            raise HREError('invalid_workers','Workers must be nonempty argument arrays for documented stages')
    timeout=value.get('timeout_seconds',900)
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or timeout<=0:
        raise HREError('invalid_workers','timeout_seconds must be a positive finite number')
    return {**deepcopy(value),'timeout_seconds':timeout}


def _runtime_config(config):
    """Freeze non-secret runtime identity for the built-in VLM worker."""
    result=deepcopy(config)
    if any('hre.model_workers' in command for command in config['workers'].values()):
        from urllib.parse import urlsplit
        endpoint=os.environ.get('HRE_VLM_BASE_URL','').strip()
        parsed=urlsplit(endpoint)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise HREError('worker_config_invalid','Use an endpoint without embedded credentials, query or fragment')
        result['builtin_vlm_runtime']={
            'base_url':endpoint,'model':os.environ.get('HRE_VLM_MODEL','').strip(),
            'timeout_seconds':os.environ.get('HRE_VLM_TIMEOUT','120'),
            'response_format':'json_object','adapter_version':'hre.model_workers.v1'}
    return result


def export_worker_request(case_root:Path,out:Path)->Path:
    """Copy current frozen inputs without advancing the Controller."""
    from .workflow import Controller
    from .cli import current_request
    from .desktop import export_task_bundle
    from .condition_handoff import export_condition_request
    root=Path(case_root).absolute();out=Path(out).absolute()
    if out.exists():raise HREError('export_exists','Choose a new worker export directory')
    state=Controller(root).state();config=read_json(root/'config.json')
    waiting=state['workflow_state']=='PAUSED' and state['pause_reason']=='condition_compilation_required'
    if not waiting and not state['pending_task']:
        raise HREError('no_pending_task','Start the case or select a case with a pending stage')
    out.mkdir(parents=True)
    if waiting:
        bundle=export_condition_request(root,out/'bundle')
        request=read_json(bundle/'condition_request.json')
        kind='condition';task_id=request['request_id']
        prompt=request.get('compiler_task','')
        if not isinstance(prompt,str):prompt=json.dumps(prompt,ensure_ascii=False)
        attachments=[{'role':role,'path':str(bundle/(role+'.png')),'sha256':file_sha256(bundle/(role+'.png'))} for role in ('A','B')]
    else:
        request=current_request(root)
        bundle=export_task_bundle(request,out/'bundle',case_root=root)
        kind='execute' if request['stage']=='execute' else 'stage';task_id=request['task_id']
        prompt=(bundle/'prompt.txt').read_text('utf-8')
        attachments=[{'role':a['label'],'path':str(bundle/a['path']),'sha256':a['sha256']} for a in read_json(bundle/'manifest.json')['attachments']]
    value=dict(schema_version='hre_worker_request_v1',kind=kind,case_root=str(root),task_id=task_id,
               request=request,prompt=prompt,attachments=attachments,output_dir=str(out/'output'),
               executor=config.get('reference_v2',{}).get('executor'),bundle_path=str(bundle))
    (out/'output').mkdir()
    path=out/'worker_request.json';write_json(path,value)
    write_json(out/'worker_request_manifest.json',{'request_sha256':file_sha256(path),
               'files':[{'path':p.relative_to(out).as_posix(),'sha256':file_sha256(p)} for p in sorted((out/'bundle').rglob('*')) if p.is_file()]})
    return path


def _checked_request(path):
    path=Path(path).absolute();proof=read_json(path.parent/'worker_request_manifest.json')
    if proof['request_sha256']!=file_sha256(path):
        raise HREError('worker_request_changed','Frozen worker request bytes changed')
    for item in proof['files']:
        if file_sha256(safe_path(path.parent,item['path'],must_exist=True))!=item['sha256']:
            raise HREError('worker_request_changed','Frozen handoff bytes changed')
    value=read_json(path)
    for attachment in value['attachments']:
        if file_sha256(Path(attachment['path']))!=attachment['sha256']:
            raise HREError('worker_request_changed','Attachment changed after export')
    return value


def _call(path,response,config):
    from .model_workers import run_worker
    value=_checked_request(path)
    if value['kind']=='condition' and value['request']['compiler']=='direct':
        from .model_aware import compile_direct_condition
        result=compile_direct_condition(value['request'])
        write_json(response,result)
        write_json(response.with_suffix('.invocation.json'),{'status':'succeeded','kind':'local_direct_compiler','attempts':1,'calls':0,'finished_at':now()})
        return result
    key=value['request']['stage'] if value['kind']=='stage' else value['kind']
    command=config['workers'].get(key)
    if command is None and value['kind']=='stage':command=config['workers'].get('stage')
    if command is None:raise HREError('worker_not_configured','No worker configured for '+key)
    return run_worker(command,Path(path),Path(response),timeout=config['timeout_seconds'])


def _validate_stage_result(value,result):
    if value['kind']=='condition':
        from .model_aware import validate_compiled_condition
        validate_compiled_condition(value['request'],result)
    else:
        if not isinstance(result,dict) or set(result)-{'payload','error','provenance','worker_observation'} or 'payload' not in result:
            raise HREError('invalid_worker_response','Stage worker returns {payload: object} or {payload: null, error: object}')
        if result.get('error') is not None:
            if result['payload'] is not None:raise HREError('invalid_worker_response','Error response must have null payload')
            validate_schema('response',result['error'],'#/properties/error')
        else:validate_schema({'diagnose':'diagnosis','compose':'composition','verify':'verification','refine':'refinement'}[value['request']['stage']],result['payload'])


def run_stage(request_path:Path,workers:dict,out:Path)->dict:
    """Run one analysis/compiler check without accepting it or generating an image."""
    config=validate_workers(workers);value=_checked_request(request_path);out=Path(out).absolute()
    if value['kind']=='execute':
        raise HREError('stage_generation_requires_controller','Use v2 run for accounted generation; stage checks do not call editors')
    if out.exists():raise HREError('export_exists','Choose a new stage-check output directory')
    out.mkdir(parents=True);response=out/'response.json'
    write_json(out/'started.json',{'at':now(),'request_path':str(Path(request_path).absolute()),'request_sha256':file_sha256(request_path),'workers':_runtime_config(config)})
    result=_call(request_path,response,config)
    _validate_stage_result(value,result)
    report=dict(validated=True,validation_scope='schema_and_condition_contract_only',case_advanced=False,
                response_path=str(response),response_sha256=file_sha256(response),actual_model_quality='not_established',finished_at=now())
    write_json(out/'check.json',report)
    return report


def run_case(case_root:Path,workers:dict,*,max_steps:int=16)->dict:
    """Drive existing Controller transitions; stop on any unresolved pause/error."""
    from .workflow import Controller
    from .cli import import_payload,import_candidate_manual
    from .evidence import _immutable
    root=Path(case_root).absolute();config=validate_workers(workers);controller=Controller(root)
    if type(max_steps) is not int or max_steps<1:raise HREError('invalid_steps','max_steps must be a positive integer')
    cfg_path=root/'worker_runs/config.json'
    runtime=_runtime_config(config)
    if cfg_path.exists() and read_json(cfg_path)!=runtime:
        raise HREError('worker_config_changed','Worker configuration is frozen for this case; use a new revision')
    _immutable(cfg_path,runtime)
    for _ in range(max_steps):
        state=controller.state()
        if state['workflow_state']=='CREATED':controller.start();continue
        if state['workflow_state']=='WAIT_EVIDENCE':controller.collect_evidence();continue
        if state['workflow_state'] in {'COMPLETED','FAILED','CANCELLED'}:break
        condition_wait=state['workflow_state']=='PAUSED' and state['pause_reason']=='condition_compilation_required'
        if state['workflow_state']=='PAUSED' and not condition_wait:break
        pending=state['pending_task']
        identity={'condition_revision':state['revision']} if condition_wait else {'task_id':pending['task_id'],'attempt':pending['attempt'],'sha256':pending['request_sha256']}
        run_dir=root/'worker_runs'/sha256_bytes(canonical_json(identity))
        response=run_dir/'response.json';request_path=run_dir/'export/worker_request.json'
        fresh=False
        try:run_dir.mkdir();fresh=True
        except FileExistsError:pass
        try:
            if fresh:
                request_path=export_worker_request(root,run_dir/'export')
                value=_checked_request(request_path)
                write_json(run_dir/'started.json',dict(identity=identity,at=now(),request_sha256=file_sha256(request_path)))
                # Recovery sees an uncertain external call even if this process dies.
                if value['kind']=='execute':
                    write_json(safe_path(root,f"tasks/{pending['task_id']}/submission_intent.json"),
                               dict(task_id=pending['task_id'],observed_submission=None,at=now(),source='configured_worker'))
                result=_call(request_path,response,config)
            else:
                if not response.is_file():raise HREError('worker_call_uncertain','A previous worker started without a response; reconcile it before continuing')
                receipt=response.with_suffix('.invocation.json')
                if not receipt.is_file() or read_json(receipt).get('status')!='succeeded':
                    raise HREError('worker_call_uncertain','Previous worker completion was not confirmed; its output cannot be auto-accepted')
                value=_checked_request(request_path);result=read_json(response)
            if value['kind']=='condition':
                _validate_stage_result(value,result)
                controller.accept_compiled_condition(response)
            elif value['kind']=='execute':
                if not isinstance(result,dict) or set(result)!={'image_path','metadata'}:
                    raise HREError('invalid_worker_response','Editor must return image_path and its observed metadata')
                image=Path(result['image_path'])
                if not image.is_absolute():image=response.parent/image
                from .desktop import validate_output_order
                from .cli import archive_external_observation
                validate_output_order(result['metadata'])
                current=controller.state()
                if current['workflow_state']!='WAIT_EXECUTION' or not current['pending_task'] or current['pending_task']['task_id']!=value['task_id']:
                    archive_external_observation(root,value['request'],image,result['metadata'])
                    controller.mark_submitted(value['task_id'],count=result['metadata']['actual_generation_count'])
                    raise HREError('worker_state_changed','Execution returned after case pause/termination; output retained and observed count charged without promoting it')
                imported=import_candidate_manual(root,value['task_id'],image,result['metadata'],'submitted')
                if not imported.accepted:raise HREError(imported.code,imported.message)
            else:
                _validate_stage_result(value,result)
                imported=import_payload(root,result['payload'],raw_text=response.read_bytes(),
                                        provenance=result.get('provenance',{'transport':'api'}),error=result.get('error'))
                if not imported.accepted:raise HREError(imported.code,imported.message)
            write_json(run_dir/'accepted.json',dict(at=now(),response_sha256=file_sha256(response)))
        except Exception:
            current=controller.state()
            if pending and pending['stage']=='execute' and current['workflow_state']=='WAIT_EXECUTION':
                entry=next(e for e in current['budget']['ledger'] if e['task_id']==pending['task_id'])
                if entry['status']=='reserved':controller.mark_submission_unknown(pending['task_id'],'worker_submission_unknown')
            raise
    state=controller.state()
    return dict(case_root=str(root),workflow_state=state['workflow_state'],pause_reason=state['pause_reason'],
                pending_task=state['pending_task'],budget=state['budget'],success=state['success'])
