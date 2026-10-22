"""Single-writer, recoverable reference enhancement state machine.

All decisions are local. Task dispatch is a committed request artifact; no model APIs.
"""
from pathlib import Path
from copy import deepcopy
import json

from .models import SCHEMA_VERSION,HREError,ImportResult,canonical_json,sha256_bytes,file_sha256,request_hash,config_hash,now,validate_schema
from .paths import safe_path,make_id
from .storage import CaseStore,case_lock,read_json,write_json,atomic_write
from .assets import validate_asset
from .budget import reserve,submit,release,entry_for,validate_budget
from .protocol import validate_submission,validate_request

WAIT={'diagnose':'WAIT_DIAGNOSIS','compose':'WAIT_COMPOSITION','execute':'WAIT_EXECUTION','verify':'WAIT_VERIFICATION','refine':'WAIT_REFINEMENT'}
TERMINAL={'COMPLETED','FAILED','CANCELLED'}


def decide_after_verify(state:dict,verification:dict,geometry:dict)->dict:
    from .selection import evaluate_candidate
    c=dict(geometry=geometry,verification=verification)
    gate=evaluate_candidate(c)
    accepted=gate['accepted'];b=state['budget'];p=state['profile_id']
    if p!='direct_best_of_3' and accepted:return dict(action='complete',reason='accepted')
    if p=='direct_best_of_3':
        if b['consumed']>=b['max_generations']:return dict(action='complete',reason='fixed_k_complete')
        return dict(action='execute',reason=None)
    if p in ('direct_ref','agent_single'):return dict(action='complete',reason='single_pass_complete')
    if b['consumed']+b['reserved']>=b['max_generations']:return dict(action='complete',reason='budget_exhausted')
    comparable=any(o['comparability'] in ('comparable','partly_comparable') for o in verification['style_observations'])
    observed={o['kind'] for o in verification['preservation_observations']}
    missing_observations=verification['confidence']<.7 and observed!={'composition','geometry','identity','text','scene_content'}
    if verification['retry_focus'] and comparable and not missing_observations:return dict(action='refine',reason=None)
    return dict(action='pause',reason='verification_requires_observation')


class Controller:
    def __init__(self,case_root:Path):
        self.root=Path(case_root).absolute();self.store=CaseStore(self.root)

    def state(self)->dict:return self.store.load()

    def _config(self,s:dict)->dict:
        config=read_json(safe_path(self.root,'config.json',must_exist=True))
        if config_hash(config)!=s['config_sha256']:raise HREError('config_hash_mismatch','Frozen configuration changed')
        return config

    def _active(self,s:dict)->None:
        if s['workflow_state'] in TERMINAL:raise HREError('terminal_state','Case is already terminal')

    def _accepted(self)->list[dict]:
        result=[]
        for path in sorted((self.root/'transactions').glob('*.json')):
            t=read_json(path);a=t.get('accepted_submission')
            if a:
                r=read_json(safe_path(self.root,a['response_path'],must_exist=True))
                if file_sha256(safe_path(self.root,a['response_path'],must_exist=True))!=a['response_sha256']:
                    raise HREError('accepted_modified','Accepted response changed')
                result.append(dict(a,response=r))
        return result

    def _latest(self,stage:str,extra:dict|None=None)->dict:
        entries=self._accepted()
        if extra:entries.append(extra)
        matches=[a for a in entries if a['response']['stage']==stage and a['response']['status']=='ok']
        if not matches:raise HREError('missing_stage_result',stage)
        return matches[-1]

    def _view(self,s:dict,extra:dict|None=None)->dict:
        v=deepcopy(s)
        if s['profile_id'].startswith('agent_'):
            d=self._latest('diagnose',extra)
            v['_diagnosis_task_id']=d['task_id'];v['diagnosis_task_id']=d['task_id'];v['_accepted_diagnosis']=d
        return v

    def _commit(self,old:dict,s:dict,event:str,payload:dict|None=None,accepted:dict|None=None,next_task:dict|None=None)->dict:
        s['updated_at']=now();validate_budget(s['budget'])
        # Storage increments revision as compare-and-swap; tasks use anticipated revision.
        return self.store.commit(s,dict(type=event,payload=payload or {},at=now()),old['revision'],accepted_submission=accepted,next_task=next_task)

    def _pause(self,s:dict,reason:str,resume_state:str|None=None)->None:
        if s['workflow_state']!='PAUSED':s['resume_state']=resume_state or s['workflow_state']
        elif resume_state is not None:s['resume_state']=resume_state
        s['workflow_state']='PAUSED';s['pause_reason']=reason

    def _finish(self,s:dict,reason:str,workflow_state:str='COMPLETED')->None:
        from .selection import select_final
        result=select_final(s['candidates'],s['inputs'][0]);selection=result['selection']
        baseline=s['profile_id']=='baseline'
        if baseline:
            selection.update(fallback=False,review_required=False)
        success=result['success'] and workflow_state=='COMPLETED' and reason not in ('budget_exhausted','baseline_only','no_prompt_change','no_supported_refinement','single_pass_complete','operator_stop')
        if not success and selection['kind']=='candidate':selection['review_required']=True
        s.update(workflow_state=workflow_state,resume_state=None,pause_reason=None,pending_task=None,success=bool(success),terminal_reason=reason,selection=selection)
        # final selection is a recoverable projection, never the transaction commit point.

    def _snapshot(self,s:dict,scope:str,candidate:dict|None=None,extra:dict|None=None)->dict:
        from .evidence import freeze_snapshot
        records=[]
        if s['evidence_snapshot']:
            ref=s['evidence_snapshot'];p=safe_path(self.root,ref['path'],must_exist=True)
            if file_sha256(p)!=ref['sha256']:raise HREError('snapshot_modified','Frozen snapshot changed')
            original=read_json(p)
            records=[read_json(safe_path(self.root,r['path'],must_exist=True)) for r in original['evidence']]
        _,ref=freeze_snapshot(self._view(s,extra),records,scope=scope,candidate_id=candidate['candidate_id'] if candidate else None,case_root=self.root)
        return ref

    def _prepare(self,s:dict,stage:str,extra:dict|None=None,task_id:str|None=None,attempt:int=0,repair:bool=False)->dict:
        config=self._config(s);task_id=task_id or make_id('task')
        inputs=deepcopy(s['inputs']);payload={};round_=s['round']
        if stage=='diagnose':
            roi=safe_path(self.root,'input/roi_manifest.json')
            tools=config.get('tool_profile',{})
            available=tools.get('available_tools',['STATS','ROI_COMPARE']) if isinstance(tools,dict) else ['STATS','ROI_COMPARE']
            payload=dict(comparison_policy_id='pre_enrolled_comparability_v1',tool_profile_id=tools.get('profile_id','offline_v1') if isinstance(tools,dict) else str(tools),available_tools=available,roi_manifest_path='input/roi_manifest.json' if roi.exists() else None,roi_manifest_sha256=file_sha256(roi) if roi.exists() else None)
        elif stage=='compose':
            a=self._latest('diagnose',extra);ref=s['evidence_snapshot']
            payload=dict(diagnosis_task_id=a['task_id'],diagnosis_response_sha256=a['response_sha256'],evidence_snapshot_path=ref['path'],evidence_snapshot_sha256=ref['sha256'])
        elif stage=='execute':
            if config.get('reference_v2',{}).get('model_aware'):
                from .condition_handoff import _frozen_request
                source,_=_frozen_request(self.root,s)
                prompt=read_json(safe_path(self.root,f'tasks/{source}/manifest.json',must_exist=True))['result']['edit_prompt']
            elif config.get('reference_v2',{}).get('arm_id')=='G2':
                from .reference_contracts import paired_prompt
                prompt=paired_prompt(self.root,config)
                source=f"paired_g1_{s['case_id']}_rev_{s['case_revision']}"
                from .evidence import _immutable
                _immutable(safe_path(self.root,f'tasks/{source}/manifest.json'),dict(schema_version='paired_g1_source_v2',
                           task_id=source,config_sha256=s['config_sha256'],paired_g1=config['reference_v2']['paired_g1']))
            elif s['profile_id'] in ('direct_ref','direct_best_of_3'):
                source=f"direct_prompt_{s['case_id']}_rev_{s['case_revision']}"
                from .prompts import render_stage,template_source
                bindings=[dict(label=label,asset_id=a['asset_id'],canonical_sha256=a['sha256']) for label,a in zip(['A','B'],inputs)]
                direct_rendered=render_stage('direct_ref',dict(image_bindings=bindings),case_root=self.root)
                prompt=json.loads(direct_rendered)['edit_prompt']
                manifest=safe_path(self.root,f'tasks/{source}/manifest.json')
                expected=dict(task_id=source,edit_prompt=prompt,prompt_version='direct_ref_v1',prompt_sha256=sha256_bytes(prompt.encode()),config_sha256=s['config_sha256'],template_source=template_source(self.root,'direct_ref'),rendered_prompt_sha256=sha256_bytes(direct_rendered.encode()))
                direct_file=manifest.with_name('prompt.txt')
                if direct_file.exists() and direct_file.read_bytes()!=direct_rendered.encode():raise HREError('direct_prompt_modified','Frozen direct rendered prompt changed')
                if not direct_file.exists():atomic_write(direct_file,direct_rendered.encode())
                if manifest.exists() and read_json(manifest)!=expected:raise HREError('direct_prompt_modified','Frozen direct prompt artifact changed')
                if not manifest.exists():write_json(manifest,expected)
            else:
                entries=self._accepted()+([extra] if extra else [])
                choices=[a for a in entries if a['response']['stage'] in ('compose','refine') and a['response']['status']=='ok']
                if not choices:raise HREError('missing_stage_result','No accepted editing prompt')
                a=choices[-1];source=a['task_id'];prompt=a['response']['payload']['edit_prompt']
                if 'reference_v2' in config:
                    from .reference_contracts import reference_targets
                    from .evidence import _immutable
                    target=reference_targets(self.root,self._latest('diagnose')['response']['payload'],a['response']['payload'],inputs)
                    _immutable(safe_path(self.root,f'tasks/{source}/reference_targets_v2.json'),target)
            gid=reserve(s['budget'],task_id,round_)
            policy=deepcopy(config.get('geometry_policy',{}))
            if isinstance(policy,str):policy=dict(mode=policy)
            policy.setdefault('mode','strict');policy.update(target_width=s['inputs'][0]['width'],target_height=s['inputs'][0]['height']);policy.setdefault('max_aspect_ratio_error',0 if policy['mode']=='strict' else .005)
            payload=dict(generation_id=gid,edit_prompt=prompt,prompt_source_task_id=source,prediction_asset_id=inputs[0]['asset_id'],reference_asset_id=inputs[1]['asset_id'],geometry_policy=policy,evidence_snapshot_sha256=s['evidence_snapshot']['sha256'])
        elif stage in ('verify','refine'):
            candidate=s['candidates'][-1];observed=candidate['geometry'].get('derived_asset') or candidate['asset'];inputs.append(deepcopy(observed))
            round_=candidate['round']+(stage=='refine')
            ref=self._snapshot(s,'verification' if stage=='verify' else 'refinement',candidate,extra)
            payload=dict(candidate_id=candidate['candidate_id'],evidence_snapshot_path=ref['path'],evidence_snapshot_sha256=ref['sha256'])
            if stage=='verify':
                g=candidate['geometry'];payload.update(generation_id=candidate['generation_id'],geometry_report_path=g['report_path'],geometry_report_sha256=g['report_sha256'],rubric_version='verification_v1')
            else:
                execute=self._latest('execute',extra)['response'];exec_request=self._task_request(execute['task_id'],execute['attempt'])
                payload.update(source_round=candidate['round'],verification_task_id=candidate['verification_task_id'],verification_response_sha256=candidate['verification_response_sha256'],previous_edit_prompt=exec_request['payload']['edit_prompt'],retry_focus=candidate['verification']['retry_focus'])
        else:raise HREError('invalid_stage',stage)
        req=dict(schema_version=SCHEMA_VERSION,case_id=s['case_id'],case_revision=s['case_revision'],task_id=task_id,stage=stage,round=round_,attempt=attempt,request_sha256='0'*64,config_sha256=s['config_sha256'],state_revision_issued=s['revision']+1,input_assets=inputs,prompt_version=f'{stage}_v1',payload=payload)
        req['request_sha256']=request_hash(req);validate_schema('request',req)
        directory=safe_path(self.root,f'tasks/{task_id}/attempts/{attempt:03d}')
        if directory.exists():raise HREError('task_exists','Request attempt is immutable')
        directory.mkdir(parents=True)
        self._adapter_context(directory,s)
        from .prompts import build_context,render_stage,dispatch_sources
        prompt=render_stage(stage,build_context(self.root,req),case_root=self.root).encode('utf-8')
        write_json(directory/'request.json',req);atomic_write(directory/'prompt.txt',prompt)
        projection=dict(request_path=(directory/'request.json').relative_to(self.root).as_posix(),request_sha256=req['request_sha256'],prompt_sha256=sha256_bytes(prompt))
        projection['template_source_proof']=dispatch_sources(self.root,stage,req)
        write_json(directory/'dispatch.json',dict(projection,stage=stage,format_repair=repair))
        projection['dispatch_sha256']=file_sha256(directory/'dispatch.json')
        s['pending_task']={k:req[k] for k in ('task_id','stage','round','attempt','request_sha256','state_revision_issued')};s['pending_task']['request_path']=projection['request_path']
        s.update(workflow_state=WAIT[stage],resume_state=None,pause_reason=None)
        return projection

    def _adapter_context(self,directory:Path,s:dict)->None:
        write_json(directory/'adapter_context.json',dict(model_observed=dict(ui_model_name='unknown',exact_model_version=None,seed=None,observed_at=now(),transport='desktop_manual',operator_steps=[]),session_id=None,evidence_plan=deepcopy(s['evidence_plan'])))

    def _task_request(self,task_id:str,attempt:int)->dict:
        return read_json(safe_path(self.root,f'tasks/{task_id}/attempts/{attempt:03d}/request.json',must_exist=True))

    def start(self)->dict:
        with case_lock(self.root):
            old=self.state();s=deepcopy(old)
            if s['workflow_state']!='CREATED':raise HREError('invalid_transition','Start requires CREATED')
            config=self._config(s)
            for asset in s['inputs']:validate_asset(asset,self.root)
            if s['profile_id']=='baseline':
                self._finish(s,'baseline_only');result=self._commit(old,s,'start');self._final_projection(result);return result
            if config.get('reference_usable')!='usable':
                self._pause(s,'pre_enrollment_reference_not_usable');return self._commit(old,s,'start_blocked')
            if s['profile_id']=='direct_best_of_3' and s['budget']['max_generations']!=3:raise HREError('invalid_profile','Best-of-3 requires exactly three slots')
            if s['profile_id'] in ('direct_ref','direct_best_of_3'):
                s['evidence_snapshot']=self._snapshot(s,'composition')
                if config.get('reference_v2',{}).get('model_aware'):
                    from .condition_handoff import prepare_condition_request
                    prepare_condition_request(self.root,s)
                    self._pause(s,'condition_compilation_required','WAIT_EXECUTION');task=None
                else:task=self._prepare(s,'execute')
            else:task=self._prepare(s,'diagnose')
            return self._commit(old,s,'start',next_task=task)

    def accept_compiled_condition(self,path:Path)->dict:
        """Accept one native compiler output and issue the ordinary execute task."""
        from .condition_handoff import freeze_compiled_condition
        with case_lock(self.root):
            old=self.state();s=deepcopy(old)
            if (old['workflow_state']!='PAUSED' or old['pause_reason']!='condition_compilation_required'
                    or old['pending_task'] is not None):
                raise HREError('condition_not_waiting','Case is not waiting for condition compilation')
            source,result=freeze_compiled_condition(self.root,s,read_json(Path(path)))
            task=self._prepare(s,'execute')
            return self._commit(old,s,'condition_compiled',dict(source_id=source,condition_kind=result['condition_kind']),next_task=task)

    def issue_task(self,stage:str)->dict:
        with case_lock(self.root):
            old=self.state();self._active(old)
            if old['pending_task'] is not None:raise HREError('pending_task_exists','Close current task before issuing another')
            if old['workflow_state']=='PAUSED':raise HREError('paused','Resume before issuing task')
            if old['workflow_state']!=WAIT.get(stage):raise HREError('invalid_transition','Stage does not match state')
            s=deepcopy(old);task=self._prepare(s,stage);self._commit(old,s,'task_issued',next_task=task)
            return self._task_request(s['pending_task']['task_id'],0)

    def _priorities(self,items:list[dict])->None:
        if [i['priority'] for i in items]!=list(range(1,len(items)+1)):
            raise HREError('invalid_priority','Targets and changes need distinct contiguous priority 1..N')

    def _supported_gaps(self,diagnosis:dict)->set[str]:
        statuses={(o['scope'],o['roi_pair_id']):o['status'] for o in diagnosis['comparability']}
        good={'comparable','partly_comparable'}
        config=read_json(safe_path(self.root,'config.json',must_exist=True))
        pairs=config.get('reference_v2',{}).get('roi_pairs',config['roi_manifest'])
        if isinstance(pairs,dict):pairs=pairs.get('roi_pairs',[])
        manual={p['roi_pair_id']:p.get('comparability',p.get('status','unknown')) for p in pairs}
        supported=set()
        if statuses.get(('global',None)) in good:supported.update(g['gap_id'] for g in diagnosis['global_gaps'])
        for g in diagnosis['local_gaps']:
            rid=g['roi_pair_id']
            if statuses.get(('roi_pair',rid)) in good and manual.get(rid) in good:supported.add(g['gap_id'])
        return supported

    def _diagnosis_semantics(self,p:dict,request:dict)->None:
        roi=read_json(safe_path(self.root,'input/roi_manifest.json',must_exist=True)) if request['payload']['roi_manifest_path'] else []
        if isinstance(roi,dict):roi=roi.get('roi_pairs',roi.get('pairs',[]))
        config=read_json(self.root/'config.json')
        if 'reference_v2' in config:roi=config['reference_v2']['roi_pairs']
        ids={r['roi_pair_id'] for r in roi}
        self._priorities(p['style_targets'])
        scopes=[(o['scope'],o['roi_pair_id']) for o in p['comparability']]
        if len(scopes)!=len(set(scopes)):raise HREError('ambiguous_comparability','Comparability scopes must be unique')
        for o in p['comparability']:
            if o['scope']=='roi_pair' and o['roi_pair_id'] not in ids:raise HREError('unknown_roi','Diagnosis references unfrozen ROI')
        gaps=p['global_gaps']+p['local_gaps']
        if any(g['evidence_ids'] for g in gaps):raise HREError('unplanned_evidence','Diagnosis context contains no prior evidence records')
        gap_ids=[g['gap_id'] for g in gaps]
        if len(gap_ids)!=len(set(gap_ids)):raise HREError('duplicate_gap','Gap IDs must be unique')
        for g in p['local_gaps']:
            if g['roi_pair_id'] not in ids:raise HREError('unknown_roi','Local gap references unfrozen ROI')
        for t in p['style_targets']:
            if not set(t['support_gap_ids'])<=set(gap_ids):raise HREError('unsupported_target','Style target references missing gap')
        for plan in p['tool_plan']:
            if plan['tool'] not in request['payload']['available_tools']:raise HREError('unavailable_tool','Diagnosis chose tool outside frozen profile')
            if not set(plan['roi_pair_ids'])<=ids:raise HREError('unknown_roi','Tool plan references unknown ROI')

    def _composition_semantics(self,p:dict,request:dict,s:dict)->None:
        relations=p.get('region_relations',[])
        if relations:
            spec=self._config(s).get('reference_v2',{})
            ids={r['roi_pair_id'] for r in spec.get('roi_pairs',[])}
            if (not spec.get('model_aware') or len(relations)>3 or any(
                    r['subject_roi_id'] not in ids or r['object_roi_id'] not in ids
                    or r['subject_roi_id']==r['object_roi_id'] for r in relations)):
                raise HREError('invalid_region_relation','Relations require model-aware planning and two distinct frozen ROI IDs')
        if 'reference_v2' in self._config(s):
            if not 1<=len(p['edit_targets'])<=3 or len(p['edit_prompt'].split())>160:
                raise HREError('v2_prompt_contract','Require 1–3 supported priorities and at most 160 English words')
            if self._config(s)['reference_v2']['task_scope']=='local' and any(t['scope']!='region' for t in p['edit_targets']):
                raise HREError('v2_prompt_contract','A local mask comparison must use only supported local priorities')
        d=self._latest('diagnose')['response']['payload'];gaps=self._supported_gaps(d)
        requested={gid for t in d['style_targets'] for gid in t['support_gap_ids']}
        self._priorities(p['edit_targets'])
        evid=set(s['evidence_snapshot']['evidence_ids'])
        refs=set(p['evidence_ids'])
        for protected in p['protected_content']:refs.update(protected['evidence_ids'])
        if not refs<=evid:raise HREError('unplanned_evidence','Composition references evidence outside frozen snapshot')
        for target in p['edit_targets']:
            if not set(target['source_gap_ids'])<=gaps & requested:raise HREError('unsupported_target','Composition target lacks comparable diagnosed support')
            local={g['gap_id'] for g in d['local_gaps']}
            if target['scope']=='region' and not set(target['source_gap_ids'])<=local:raise HREError('unsupported_target','Regional edit requires a frozen comparable local ROI gap')

    def _refinement_semantics(self,p:dict,request:dict,state:dict)->None:
        self._priorities(p['changes'])
        source=request['payload']
        matches=[candidate for candidate in state['candidates'] if candidate['candidate_id']==source['candidate_id']]
        if len(matches)!=1:raise HREError('candidate_binding_mismatch','Refinement needs its actual candidate')
        candidate=matches[0]
        if candidate['round']!=source['source_round'] or candidate['verification_task_id']!=source['verification_task_id'] or candidate['verification_response_sha256']!=source['verification_response_sha256']:
            raise HREError('candidate_binding_mismatch','Refinement feedback differs from accepted candidate verification')
        verification=candidate['verification']
        if verification is None or source['retry_focus']!=verification['retry_focus']:
            raise HREError('unsupported_refinement_issue','Refinement request must echo actual accepted retry focus')
        focus=set(verification['retry_focus'])
        if not set(p['retry_focus'])<=focus:
            raise HREError('unsupported_refinement_issue','Refinement invents retry focus absent from its accepted verifier')
        supported=focus|{issue['observation'] for issue in verification['remaining_issues']}|{defect['observation'] for defect in verification['critical_defects']}
        if any(change['based_on_issue'] not in supported for change in p['changes']):
            raise HREError('unsupported_refinement_issue','Every refinement change must reference actual accepted feedback text')

    def _apply(self,s:dict,request:dict,result:dict,accepted:dict)->dict|None:
        response=result['response'];stage=request['stage'];p=response['payload'];s['pending_task']=None
        if response['status']=='error':
            if stage=='refine' and response['error']['code']=='no_supported_refinement':self._finish(s,'no_supported_refinement');return None
            if stage=='execute':
                e=entry_for(s['budget'],request['task_id']);e['outcome']='error' if e['status']=='submitted' else 'unknown'
            self._pause(s,f"{stage}_error:{response['error']['code']}",WAIT[stage]);return None
        if stage=='diagnose':
            supported=self._supported_gaps(p)
            comparable=bool(p['style_targets']) and all(set(t['support_gap_ids'])<=supported for t in p['style_targets'])
            if p['reference_usable']!='usable' or not comparable or not p['style_targets']:
                self._pause(s,'diagnosis_reference_or_targets_unusable','WAIT_DIAGNOSIS');return None
            s['evidence_plan']=[dict(plan_item_id=f'plan_{i:03d}',tool_id=t['tool'],roles=t['roles'],roi_pair_ids=t['roi_pair_ids'],required=t['required'],status='pending',evidence_id=None) for i,t in enumerate(p['tool_plan'])]
            s['workflow_state']='WAIT_EVIDENCE'
            if not s['evidence_plan']:
                s['evidence_snapshot']=self._snapshot(s,'composition',extra=accepted);return self._prepare(s,'compose',accepted)
            return None
        if stage=='compose':
            if self._config(s).get('reference_v2',{}).get('model_aware'):
                from .condition_handoff import prepare_condition_request
                prepare_condition_request(self.root,s,accepted)
                self._pause(s,'condition_compilation_required','WAIT_EXECUTION');return None
            return self._prepare(s,'execute',accepted)
        if stage=='execute':
            e=entry_for(s['budget'],request['task_id'])
            if e['status']!='submitted':raise HREError('submission_unconfirmed','Confirm actual execution submission before import')
            submit(s['budget'],request['task_id'],p['actual_generation_count'],p['submitted_at']);e['outcome']='ok'
            if s['budget']['consumed']>s['budget']['max_generations']:
                s['deviations'].append(dict(code='extra_sampling',message='Observed generations exceed frozen budget',at=now()));self._finish(s,'extra_sampling','FAILED');return None
            a=p['candidate_asset'];prior=[s['inputs'][0]]+[c['asset'] for c in s['candidates']]
            if any(a['source_file']['sha256']==x['source_file']['sha256'] for x in prior):e['outcome']='duplicate';self._finish(s,'duplicate_output');return None
            if any(a['sha256']==x['sha256'] or (a.get('pixel_sha256') and a['pixel_sha256']==x.get('pixel_sha256')) for x in prior):e['outcome']='duplicate';self._finish(s,'canonical_duplicate_output');return None
            from .geometry import check_geometry
            g=check_geometry(s['inputs'][0],a,request['payload']['geometry_policy'],case_root=self.root)
            c=dict(candidate_id=a['asset_id'],asset=a,round=request['round'],generation_id=p['generation_id'],geometry=g,verification_task_id=None,verification_response_sha256=None,verification=None,usable=None,accepted=False,duplicate_of=None)
            s['candidates'].append(c);s['round']=request['round'];return self._prepare(s,'verify',accepted)
        if stage=='verify':
            c=s['candidates'][-1]
            if c['candidate_id']!=request['payload']['candidate_id'] or c['round']!=request['round']:raise HREError('candidate_binding_mismatch','Verification candidate mismatch')
            c.update(verification_task_id=request['task_id'],verification_response_sha256=result['response_sha256'],verification=p)
            from .selection import evaluate_candidate
            c.update(evaluate_candidate(c));decision=decide_after_verify(s,p,c['geometry'])
            if decision['action']=='complete':self._finish(s,decision['reason']);return None
            if decision['action']=='execute':s['round']=c['round']+1;return self._prepare(s,'execute',accepted)
            if decision['action']=='refine':return self._prepare(s,'refine',accepted)
            self._pause(s,decision['reason'],'WAIT_VERIFICATION');return None
        if stage=='refine':
            if p['edit_prompt'].strip()==request['payload']['previous_edit_prompt'].strip():self._finish(s,'no_prompt_change');return None
            s['round']=request['round'];return self._prepare(s,'execute',accepted)
        raise HREError('invalid_stage',stage)

    def _quarantine(self,done_path:Path,code:str,message:str)->None:
        # Copy original immutable files; never execute or trust supplied paths while preserving rejection.
        q=safe_path(self.root,f'quarantine/{make_id("rejected")}');q.mkdir(parents=True)
        try:
            p=safe_path(self.root,Path(done_path).absolute().relative_to(self.root).as_posix(),must_exist=True)
            if p.is_file() and not p.is_symlink() and p.absolute().is_relative_to(self.root.absolute()):
                for f in p.parent.iterdir():
                    if f.is_file() and not f.is_symlink():atomic_write(q/f.name,f.read_bytes())
        except (OSError,HREError,ValueError):pass
        write_json(q/'rejection.json',dict(code=code,message=message,at=now()))

    def ingest_response(self,response_path:Path,done_path:Path)->ImportResult:
        try:
            done=read_json(Path(done_path));actual=safe_path(self.root,done['response_file'],must_exist=True)
            if actual.absolute()!=Path(response_path).absolute():raise HREError('response_path_mismatch','Response argument differs from done')
        except (HREError,OSError,ValueError,KeyError) as e:return ImportResult(accepted=False,code=getattr(e,'code','protocol_rejection'),message=str(e),duplicate=False)
        return self.consume_done(done_path)

    def consume_done(self,done_path:Path)->ImportResult:
        with case_lock(self.root):
            old=self.state()
            try:
                dpath=safe_path(self.root,Path(done_path).absolute().relative_to(self.root.absolute()).as_posix(),must_exist=True)
                if dpath.name!='done.json':raise HREError('incomplete_submission','No final done marker')
                done=read_json(dpath)
                for a in self._accepted():
                    if a['task_id']==done.get('task_id'):
                        # Idempotence still verifies persisted bytes and submitted marker identity.
                        if all(done.get(k)==a.get(k) for k in ('task_id','request_sha256','response_sha256')):
                            req=self._task_request(a['task_id'],a['attempt']);validate_submission(self.root,dpath,req,old)
                            return ImportResult(accepted=True,code='already_processed',message='',duplicate=True)
                        raise HREError('conflict','Task already has a different accepted response')
                if old['workflow_state'] in TERMINAL:raise HREError('terminal_state','Late response cannot advance terminal case')
                if old['workflow_state']=='PAUSED':return ImportResult(accepted=False,code='paused',message='Pending submission waits for resume',duplicate=False)
                pending=old['pending_task']
                if pending is None:raise HREError('stale_task','No current pending task')
                request=read_json(safe_path(self.root,pending['request_path'],must_exist=True))
                result=validate_submission(self.root,dpath,request,old)
                if result['response']['status']=='ok':
                    if request['stage']=='diagnose':self._diagnosis_semantics(result['response']['payload'],request)
                    if request['stage'] in ('compose','refine'):
                        from .prompts import validate_edit_contract
                        validate_edit_contract(request['stage'],result['response']['payload'])
                        instructions=[t['operation'] for t in result['response']['payload']['edit_targets']] if request['stage']=='compose' else [t['revised_instruction'] for t in result['response']['payload']['changes']]
                        for instruction in instructions:validate_edit_contract(request['stage'],dict(edit_prompt=instruction))
                        if request['stage']=='compose':self._composition_semantics(result['response']['payload'],request,old)
                        else:self._refinement_semantics(result['response']['payload'],request,old)
                accepted=dict(task_id=request['task_id'],attempt=request['attempt'],request_sha256=request['request_sha256'],response_sha256=result['response_sha256'],response_path=done['response_file'],done_path=dpath.relative_to(self.root).as_posix())
                if 'reference_v2' in self._config(old):accepted['done_sha256']=file_sha256(dpath)
                ephemeral=dict(accepted,response=result['response'])
                s=deepcopy(old);next_task=self._apply(s,request,result,ephemeral)
                self._commit(old,s,'response_accepted',dict(task_id=request['task_id'],stage=request['stage'],response_sha256=result['response_sha256']),accepted,next_task)
                self._final_projection(s)
                return ImportResult(accepted=True,code='accepted',message='',duplicate=False)
            except (HREError,OSError,ValueError,KeyError,TypeError) as e:
                code=getattr(e,'code','protocol_rejection');self._quarantine(done_path,code,str(e))
                # Rejections are audited but retain the same pending identity and budget.
                s=deepcopy(old)
                s['deviations'].append(dict(code=code,message=str(e) or code,at=now()))
                if code=='prohibited_edit_contract' and s['workflow_state'] not in TERMINAL:self._pause(s,'prohibited_edit_contract_requires_correction')
                self._commit(old,s,'response_rejected',dict(code=code,message=str(e),task_id=old['pending_task']['task_id'] if old['pending_task'] else None))
                return ImportResult(accepted=False,code=code,message=str(e),duplicate=False)

    def _final_projection(self,s:dict)->None:
        if s['selection'] is not None:write_json(safe_path(self.root,'final/selection.json'),dict(selection=s['selection'],success=s['success'],reason=s['terminal_reason']))

    def collect_evidence(self)->dict:
        return self._resolve_and_publish_evidence()

    def _resolve_and_publish_evidence(self,expected_revision:int|None=None)->dict:
        with case_lock(self.root):
            old=self.state();self._active(old)
            if expected_revision is not None and old['revision']!=expected_revision:raise HREError('stale_state','UI revision differs from current committed state')
            if old['workflow_state']!='WAIT_EVIDENCE':raise HREError('invalid_transition','Evidence requires WAIT_EVIDENCE')
            view=self._view(old)
        from .evidence import EvidenceService
        # Local image statistics/cache materialization may be expensive. The case
        # lock protects the publication transaction, never waits on these tools.
        result=EvidenceService(self.root).resolve(view)
        with case_lock(self.root):
            current=self.state()
            if current['revision']!=old['revision']:raise HREError('stale_state','Evidence was resolved against a state that has since changed')
            s=deepcopy(old);s['evidence_plan']=result['plan'];next_task=None
            if result['snapshot_ref'] is None:self._pause(s,'required_evidence_missing','WAIT_EVIDENCE')
            else:s['evidence_snapshot']=result['snapshot_ref'];next_task=self._prepare(s,'compose')
            return self._commit(old,s,'evidence_resolved',dict(missing=result['missing']),next_task=next_task)

    def pause(self,reason:str)->dict:
        if not reason.strip():raise HREError('invalid_reason','Pause reason is required')
        with case_lock(self.root):
            old=self.state();self._active(old);s=deepcopy(old);self._pause(s,reason)
            return self._commit(old,s,'pause_requested',dict(reason=reason))

    def _blocking_terminal_reason(self,reason:str)->str:
        permitted={'unusable_reference','capability_unavailable','generation_error','verification_error','evidence_unavailable','protocol_integrity_error','extra_sampling','no_usable_candidate','no_supported_refinement','operator_stop'}
        if reason in permitted:return reason
        if reason in {'pre_enrollment_reference_not_usable','diagnosis_reference_or_targets_unusable'} or reason.startswith('diagnose_error:'):return 'unusable_reference'
        if reason=='required_evidence_missing' or reason.startswith('evidence_'):return 'evidence_unavailable'
        if 'capability_unavailable' in reason:return 'capability_unavailable'
        if reason.startswith('execute_error:') or reason=='submission_fact_unknown':return 'generation_error'
        if reason.startswith('verify_error:') or reason=='verification_requires_observation':return 'verification_error'
        if reason in {'format_repair_limit_exhausted','prohibited_edit_contract_requires_correction'} or reason.startswith(('compose_error:','refine_error:')):return 'protocol_integrity_error'
        return 'operator_stop'

    def resume(self,action:str='continue')->dict:
        with case_lock(self.root):
            old=self.state()
            if old['workflow_state']!='PAUSED':raise HREError('invalid_transition','Resume requires PAUSED')
            s=deepcopy(old);config=self._config(s)
            if action in ('stop','stop_requested'):
                blocking_reason=s['pause_reason'];terminal_reason=self._blocking_terminal_reason(blocking_reason)
                self._finish(s,terminal_reason,'FAILED');result=self._commit(old,s,'stop_requested',dict(blocking_reason=blocking_reason,terminal_reason=terminal_reason));self._final_projection(result);return result
            if config.get('reference_usable')!='usable' and s['profile_id']!='baseline':raise HREError('frozen_reference_unusable','Create new case revision with usable pre-enrollment annotation')
            if action not in ('continue','retry_analysis','retry','reconcile_submitted','release_unsubmitted','retry_generation'):raise HREError('invalid_action',action)
            target=s['resume_state'];task=None
            if target=='WAIT_EXECUTION':
                entries=[e for e in s['budget']['ledger'] if e['round']==s['round']]
                if entries and entries[-1]['status']=='reserved' and entries[-1]['outcome']=='unknown':raise HREError('submission_unconfirmed','Reconcile generation before resuming')
                if action=='retry_generation':
                    if s['pending_task'] is not None or not entries or not (entries[-1]['status']=='released_unsubmitted' or (entries[-1]['status']=='submitted' and entries[-1]['outcome']=='error')):
                        raise HREError('generation_retry_not_authorized','Retry requires confirmed failure or confirmed non-submission')
                    if s['budget']['consumed']+s['budget']['reserved']>=s['budget']['max_generations']:
                        self._finish(s,'fixed_k_complete' if s['profile_id']=='direct_best_of_3' else 'budget_exhausted')
                        result=self._commit(old,s,'generation_retry_budget_exhausted');self._final_projection(result);return result
                    s['round']=max(e['round'] for e in s['budget']['ledger'])+1
                    task=self._prepare(s,'execute')
                elif s['pending_task'] is None:raise HREError('generation_retry_requires_explicit_action','Failure cannot automatically create another execution')
            elif action=='retry_generation':raise HREError('invalid_action','New generation retry requires execution failure')
            if task is None:s.update(workflow_state=target,resume_state=None,pause_reason=None)
            if s['pending_task'] is None:
                if target=='CREATED':pass
                elif target=='WAIT_EVIDENCE':pass
                else:
                    if action not in ('retry_analysis','retry'):raise HREError('explicit_retry_required','Accepted analysis needs a new task and explicit retry action')
                    task=self._prepare(s,next(k for k,v in WAIT.items() if v==target))
            result=self._commit(old,s,'resume_requested',dict(action=action),next_task=task)
        if target=='CREATED':return self.start()
        if result['pending_task']:
            tid=result['pending_task']['task_id']
            for done in sorted((self.root/f'tasks/{tid}/submissions').glob('*/pending/done.json')):
                r=self.consume_done(done)
                if r.accepted:break
        return self.state()

    def cancel(self,reason:str)->dict:
        with case_lock(self.root):
            old=self.state();self._active(old);s=deepcopy(old)
            for e in s['budget']['ledger']:
                if e['outcome']=='pending':e['outcome']='cancelled'
            self._finish(s,'cancelled','CANCELLED');result=self._commit(old,s,'cancel_requested',dict(reason=reason));self._final_projection(result);return result

    def fail_integrity(self,reason:str)->dict:
        with case_lock(self.root):
            old=self.state();self._active(old);s=deepcopy(old)
            s['deviations'].append(dict(code='protocol_integrity_error',message=reason,at=now()))
            self._finish(s,'protocol_integrity_error','FAILED')
            result=self._commit(old,s,'fatal_integrity_error',dict(reason=reason));self._final_projection(result);return result

    def mark_submission_unknown(self,task_id:str,reason:str='submission_fact_unknown')->dict:
        with case_lock(self.root):
            old=self.state();self._active(old);s=deepcopy(old)
            p=s['pending_task']
            if p is None or p['stage']!='execute' or p['task_id']!=task_id:raise HREError('task_mismatch','Unknown submission must be current execution')
            e=entry_for(s['budget'],task_id)
            if e['status']!='reserved':raise HREError('already_submitted','Submission is already reconciled')
            write_json(safe_path(self.root,f'tasks/{task_id}/submission_intent.json'),dict(task_id=task_id,generation_id=e['generation_id'],observed_submission=None,at=now(),source='operator_observation'))
            e['outcome']='unknown';self._pause(s,reason,'WAIT_EXECUTION')
            return self._commit(old,s,'execution_intent',dict(task_id=task_id,generation_id=e['generation_id'],source='operator_observation',observed_submission=None))

    def mark_submitted(self,task_id:str,count:int=1)->dict:
        with case_lock(self.root):
            old=self.state();s=deepcopy(old);e=entry_for(s['budget'],task_id)
            if e['status']=='submitted' and count<=e['charged_count']:return old
            previous_count=e['charged_count'];terminal_accounting_only=old['workflow_state'] in TERMINAL
            gid=submit(s['budget'],task_id,count)
            if s['budget']['consumed']>s['budget']['max_generations']:
                s['deviations'].append(dict(code='extra_sampling',message='Observed submissions exceed frozen budget',at=now()))
                if not terminal_accounting_only:self._finish(s,'extra_sampling','FAILED')
            result=self._commit(old,s,'execution_submitted',dict(task_id=task_id,generation_id=gid,count=count,previous_charged_count=previous_count,charged_delta=count-previous_count,terminal_accounting_only=terminal_accounting_only,source='operator_confirmation'))
            self._final_projection(result);return result

    def release_unsubmitted(self,task_id:str)->dict:
        with case_lock(self.root):
            old=self.state();entry=entry_for(old['budget'],task_id)
            if entry['status']=='released_unsubmitted':return old
            s=deepcopy(old);release(s['budget'],task_id)
            pending=s['pending_task']
            matching_active_execution=(pending is not None and pending['stage']=='execute' and pending['task_id']==task_id)
            matching_closed_execution=(pending is None and s['round']==entry['round'] and s['workflow_state']=='PAUSED' and s['resume_state']=='WAIT_EXECUTION')
            if s['workflow_state'] not in TERMINAL and (matching_active_execution or matching_closed_execution):
                s['pending_task']=None;self._pause(s,'confirmed_unsubmitted_generation_released','WAIT_EXECUTION')
            return self._commit(old,s,'release_unsubmitted',dict(task_id=task_id,generation_id=entry['generation_id'],source='explicit_operator_confirmation',never_submitted=True))

    def retry_transport(self)->dict:
        with case_lock(self.root):
            old=self.state();self._active(old)
            if old['workflow_state']=='PAUSED':raise HREError('paused','Resume before format repair')
            p=old['pending_task']
            if p is None:raise HREError('no_pending_task','Accepted task must get new identity')
            if any(a['task_id']==p['task_id'] for a in self._accepted()):raise HREError('already_accepted','Accepted result cannot be repaired')
            limit=self._config(old).get('format_repair_limit',1)
            if p['attempt']>=limit:
                s=deepcopy(old);self._pause(s,'format_repair_limit_exhausted');return self._commit(old,s,'format_repair_exhausted')
            request=self._task_request(p['task_id'],p['attempt']);s=deepcopy(old)
            # Preserve exact observation/generation context; only envelope attempt/revision changes.
            request['attempt']+=1;request['state_revision_issued']=s['revision']+1;request['request_sha256']=request_hash(request)
            directory=safe_path(self.root,f"tasks/{p['task_id']}/attempts/{request['attempt']:03d}");directory.mkdir(parents=True,exist_ok=False)
            self._adapter_context(directory,s)
            from .prompts import build_context,render_stage,dispatch_sources
            prompt=render_stage(request['stage'],build_context(self.root,request),case_root=self.root).encode()
            write_json(directory/'request.json',request);atomic_write(directory/'prompt.txt',prompt)
            task=dict(request_path=(directory/'request.json').relative_to(self.root).as_posix(),request_sha256=request['request_sha256'],prompt_sha256=sha256_bytes(prompt))
            task['template_source_proof']=dispatch_sources(self.root,request['stage'],request)
            write_json(directory/'dispatch.json',dict(task,format_repair=True))
            task['dispatch_sha256']=file_sha256(directory/'dispatch.json')
            s['pending_task']={k:request[k] for k in ('task_id','stage','round','attempt','request_sha256','state_revision_issued')};s['pending_task']['request_path']=task['request_path']
            self._commit(old,s,'format_repair',dict(task_id=p['task_id'],attempt=request['attempt']),next_task=task)
            return request

    def recover(self)->dict:
        with case_lock(self.root):
            s=self.store.recover();self._config(s)
            for a in s['inputs']:validate_asset(a,self.root)
            # Durable uncertain intent must hold reservation, never auto-submit on restart.
            uncertain=[]
            for e in s['budget']['ledger']:
                if e['status']=='reserved' and any((self.root/f"tasks/{e['task_id']}").rglob('submission_intent.json')):uncertain.append(e['generation_id'])
            if uncertain and s['workflow_state'] not in TERMINAL and s['pause_reason']!='submission_fact_unknown':
                old=s;s=deepcopy(old)
                for e in s['budget']['ledger']:
                    if e['generation_id'] in uncertain:e['outcome']='unknown'
                self._pause(s,'submission_fact_unknown');s=self._commit(old,s,'submission_fact_unknown',dict(generation_ids=uncertain))
            self._final_projection(s)
        if s['pending_task'] and s['workflow_state'] not in TERMINAL|{'PAUSED'}:
            for d in sorted((self.root/f"tasks/{s['pending_task']['task_id']}/submissions").glob('*/pending/done.json')):
                r=self.consume_done(d)
                if r.accepted:break
        return self.state()


def dispatch_event(case_root:Path,event:str,payload:dict)->dict:
    if event=='evidence_ready':return Controller(case_root)._resolve_and_publish_evidence(payload.get('expected_revision'))
    with case_lock(case_root):
        c=Controller(case_root)
        if 'expected_revision' in payload and c.state()['revision']!=payload['expected_revision']:
            raise HREError('stale_state','UI revision differs from current committed state')
        actions={
            'start':lambda:c.start(),
            'pause_requested':lambda:c.pause(payload['reason']),
            'resume_requested':lambda:c.resume(payload.get('action','continue')),
            'cancel_requested':lambda:c.cancel(payload['reason']),
            'execution_submitted':lambda:c.mark_submitted(payload['task_id'],payload.get('count',1)),
            'execution_intent':lambda:c.mark_submission_unknown(payload['task_id'],payload.get('reason','submission_fact_unknown')),
            'evidence_ready':lambda:c.collect_evidence(),
            'evidence_failed':lambda:c.pause(payload.get('reason','required_evidence_missing')),
            'release_unsubmitted':lambda:c.release_unsubmitted(payload['task_id']),
            'retry_transport':lambda:c.retry_transport(),
            'fatal_integrity_error':lambda:c.fail_integrity(payload['reason']),
            'stop_requested':lambda:c.resume('stop'),
        }
        if event=='response_ready':
            c.consume_done(Path(payload['done_path']))
            return c.state()
        if event not in actions:raise HREError('unknown_event',event)
        return actions[event]()


def reserve_generation(case_root:Path,task_id:str)->str:
    with case_lock(case_root):
        c=Controller(case_root);old=c.state();c._active(old);s=deepcopy(old)
        if s['pending_task'] is None or s['pending_task']['task_id']!=task_id or s['pending_task']['stage']!='execute':raise HREError('invalid_generation_task','Only the current execution can reserve')
        gid=reserve(s['budget'],task_id,s['round'])
        if s!=old:c._commit(old,s,'generation_reserved',dict(task_id=task_id,generation_id=gid))
        return gid

