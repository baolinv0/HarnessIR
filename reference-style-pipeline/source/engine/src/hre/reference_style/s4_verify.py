"""Private, versioned posthoc verification/selection. Never imported by composers."""
from copy import deepcopy
from pathlib import Path
import math
from hre.models import canonical_json,file_sha256,sha256_bytes
from hre.storage import case_lock
from .contracts import exact,require,identifier,digest,record
from .s2_evidence import code
from .s4_selected import require_selected
from . import coordinator as co,s2_store as store


def _private(root,group,key):
    identifier(key);return 'private_verification/s4/'+group+'/'+key+'.json'


def _read(root,state,group,key):
    value=co._load(root,_private(root,group,key));require(value['sample_id']==state['sample_id'],'private verification sample mismatch')
    for asset in value['payload'].get('assets',[]):require(file_sha256(co._path(root,asset['path'],True))==asset['sha256'],'private approval artifact changed')
    return value


def _write(root,state,group,key,kind,payload):
    path=_private(root,group,key);co._path(root,path).parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    require(not co._path(root,path).exists(),'private record immutable; explicit new version/identity required')
    value=record(state['sample_id'],kind,payload);co._immutable_bytes(root,path,canonical_json(value));co._path(root,path).chmod(0o600);return value


def _source(root,state,source,group,key):
    exact(source,('origin','path','sha256'));require(source['origin'] in ('user_approved','synthetic_fixture','unapproved'),'invalid calibration/policy authority')
    require(state['payload']['purpose']=='protocol_fixture' or source['origin']!='synthetic_fixture','fixture approval cannot establish real acceptance')
    if source['origin']=='unapproved':require(source['path'] is None and source['sha256'] is None,'unapproved basis has no approval claim');return [],False
    digest(source['sha256']);raw=co._read_output(source['path']);require(sha256_bytes(raw)==source['sha256'],'actual approval/calibration source hash mismatch')
    path='private_verification/s4/'+group+'/'+key+'_source.bin';co._path(root,path).parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    co._immutable_bytes(root,path,raw);co._path(root,path).chmod(0o600)
    return [{'path':path,'sha256':source['sha256']}],True


def install_policy(root,spec):
    exact(spec,('policy_id','version','allow_minor_incidental','source'));identifier(spec['policy_id']);identifier(spec['version'])
    require(type(spec['allow_minor_incidental'])is bool,'typed posthoc policy required')
    with case_lock(root):
        state=co._status(root);require(not co._path(root,_private(root,'policies',spec['policy_id'])).exists(),'policy ID frozen')
        assets,approved=_source(root,state,spec['source'],'policies',spec['policy_id'])
        return _write(root,state,'policies',spec['policy_id'],'acceptance_policy',dict(**deepcopy(spec),assets=assets,approved_basis=approved,
            overall_style_required=['tone','color','brightness'],major_action='reject',unknown_action='insufficient_evidence',approval_verification='caller_attested_artifact_not_remote_authenticated'))


def install_rule(root,spec):
    exact(spec,('rule_id','version','target_hash','policy_hash','source','global_anchors','visual_target_ids','numeric_tolerances','critical_preservation','required_confidence','review_basis'))
    identifier(spec['rule_id']);identifier(spec['version']);digest(spec['target_hash']);digest(spec['policy_hash'])
    require(isinstance(spec['global_anchors'],list) and len(set(spec['global_anchors']))==len(spec['global_anchors']) and all(x in ('tone','color','brightness') for x in spec['global_anchors']),'invalid global anchor coverage')
    require(isinstance(spec['visual_target_ids'],list) and isinstance(spec['numeric_tolerances'],list),'calibration lists required')
    for tid in spec['visual_target_ids']:code(tid,'t')
    require(len(set(spec['visual_target_ids']))==len(spec['visual_target_ids']),'duplicate visual anchors')
    ids=set()
    for t in spec['numeric_tolerances']:
        exact(t,('target_id','max_abs_residual'));code(t['target_id'],'t')
        require(t['target_id'] not in ids and type(t['max_abs_residual']) in (int,float) and math.isfinite(t['max_abs_residual']) and t['max_abs_residual']>=0,'explicit finite calibrated residual bound required');ids.add(t['target_id'])
    require(spec['critical_preservation']==['identity','ocr','naturalness'] and spec['required_confidence']=='high' and spec['review_basis']=='independent_image_first','unsupported frozen verification rule')
    with case_lock(root):
        state=co._status(root);require(not co._path(root,_private(root,'rules',spec['rule_id'])).exists(),'rule ID frozen')
        targets=[store.get(root,state,'targets',v) for v in store.registry(state)['targets']];matches=[t for t in targets if t['content_hash']==spec['target_hash']]
        require(len(matches)==1,'rule must bind a real frozen target set');target_ids={t['target_id'] for t in matches[0]['payload']['targets']}
        require(set(spec['visual_target_ids'])<=target_ids and ids<=target_ids,'calibration references unknown target')
        assets,approved=_source(root,state,spec['source'],'rules',spec['rule_id'])
        return _write(root,state,'rules',spec['rule_id'],'verification_rule',dict(**deepcopy(spec),assets=assets,approved_basis=approved,
            semantics='reference residual bounds and approved visual review basis; no synthetic real-world calibration claim'))


def install_adjudication(root,spec):
    exact(spec,('adjudication_id','evaluation_id','evaluation_hash','facts_hash','rule_hash','resolutions','source'));identifier(spec['adjudication_id']);code(spec['evaluation_id'],'j')
    for key in ('evaluation_hash','facts_hash','rule_hash'):digest(spec[key])
    require(isinstance(spec['resolutions'],list),'typed conflict resolutions required');ids=set()
    for item in spec['resolutions']:
        exact(item,('target_id','resolution'));code(item['target_id'],'t');require(item['target_id'] not in ids and item['resolution'] in ('confirm_unmet','requires_re_evaluation','unresolved'),'unsupported adjudication');ids.add(item['target_id'])
    with case_lock(root):
        state=co._status(root);assets,approved=_source(root,state,spec['source'],'adjudications',spec['adjudication_id'])
        return _write(root,state,'adjudications',spec['adjudication_id'],'conflict_adjudication',dict(**deepcopy(spec),assets=assets,approved_basis=approved))


def _decisions(root,state,evaluation_id):
    directory=co._path(root,'private_verification/s4/decisions')
    if not directory.exists():return []
    values=[_read(root,state,'decisions',p.stem) for p in directory.glob('*.json')]
    return sorted([v for v in values if v['payload']['evaluation_id']==evaluation_id],key=lambda v:v['payload']['sequence'])


def verify(root,spec):
    exact(spec,('decision_id','evaluation_id','facts_id','predecessor','adjudication_id','verification_ref'));code(spec['decision_id'],'z');code(spec['evaluation_id'],'j');code(spec['facts_id'],'f')
    ref=spec['verification_ref']
    if ref is not None:
        exact(ref,('policy_id','policy_version','policy_hash','rule_id','rule_version','rule_hash'))
        for key in ('policy_id','policy_version','rule_id','rule_version'):identifier(ref[key])
        for key in ('policy_hash','rule_hash'):digest(ref[key])
    with case_lock(root):
        state=co._status(root);evaluation=store.get(root,state,'evaluations',spec['evaluation_id']);e=evaluation['payload'];facts=store.get(root,state,'facts',spec['facts_id']);f=facts['payload']
        require(f['evaluation_id']==spec['evaluation_id'] and f['evaluation_hash']==evaluation['content_hash'],'verification facts/evaluation mismatch')
        require_selected(root,state,evaluation)
        previous=_decisions(root,state,spec['evaluation_id'])
        if previous:require(spec['predecessor']=={'decision_id':previous[-1]['payload']['decision_id'],'hash':previous[-1]['content_hash']},'new decision must explicitly link previous conclusion')
        else:require(spec['predecessor'] is None,'first decision has no predecessor')
        target=store.get(root,state,'targets',e['evaluation_target_version']);require(target['content_hash']==e['evaluation_target_hash'],'verification target mismatch')
        policy=rule=None;ready=False
        if ref is not None:
            policy=_read(root,state,'policies',ref['policy_id']);rule=_read(root,state,'rules',ref['rule_id'])
            require(policy['content_hash']==ref['policy_hash'] and policy['payload']['version']==ref['policy_version']
                and rule['content_hash']==ref['rule_hash'] and rule['payload']['version']==ref['rule_version']
                and rule['payload']['target_hash']==e['evaluation_target_hash'] and rule['payload']['policy_hash']==policy['content_hash'],'frozen verification policy/rule binding mismatch')
            ready=policy['payload']['approved_basis'] and rule['payload']['approved_basis']
        r={} if rule is None else rule['payload'];tolerances={x['target_id']:x['max_abs_residual'] for x in r.get('numeric_tolerances',[])}
        rows={m['measurement_id']:m for m in e['measurements']};visual={x['target_id']:x for x in f['targets']};statuses=[];conflicts=[]
        for t in target['payload']['targets']:
            tid=t['target_id'];ob=visual[tid];v=ob['status'] if ready and tid in r.get('visual_target_ids',[]) and ob['confidence']=='high' else 'uncalibrated'
            m=None if t['measurement_binding'] is None else rows[t['measurement_binding']['measurement_id']]
            n='uncalibrated'
            if ready and tid in tolerances and m is not None:
                n='uncertain' if m['eligibility']!='numeric_eligible' or m['candidate_absolute_residual'] is None else 'achieved' if m['candidate_absolute_residual']<=tolerances[tid] else 'unmet'
            conflict=(n=='achieved' and v in ('unmet','partial')) or (v=='achieved' and n=='unmet')
            if conflict:conflicts.append({'target_id':tid,'numeric':n,'visual':v,'resolution':'unresolved'})
            effective=v if t['judge_type']=='visual' else n if t['judge_type']=='numeric' else ('achieved' if n==v=='achieved' else 'uncalibrated' if 'uncalibrated' in (n,v) else 'uncertain' if 'uncertain' in (n,v) else 'unmet')
            if conflict:effective='conflict'
            statuses.append({'target_id':tid,'priority':t['priority'],'judge_type':t['judge_type'],'numeric':n,'visual':v,'effective':effective})
        adjudication=None
        if spec['adjudication_id'] is not None:
            adjudication=_read(root,state,'adjudications',spec['adjudication_id']);a=adjudication['payload']
            require(a['approved_basis'] and a['evaluation_id']==spec['evaluation_id'] and a['evaluation_hash']==evaluation['content_hash']
                    and a['facts_hash']==facts['content_hash'] and rule is not None and a['rule_hash']==rule['content_hash'],'adjudication must bind exact evaluation/facts/rule')
            for item in a['resolutions']:
                matches=[c for c in conflicts if c['target_id']==item['target_id']];require(len(matches)==1,'adjudication must address a real conflict')
                matches[0]['resolution']=item['resolution']
                if item['resolution']=='confirm_unmet':next(s for s in statuses if s['target_id']==item['target_id'])['effective']='unmet'
        overall={k:(ob['status'] if ready and k in r.get('global_anchors',[]) and ob['confidence']=='high' else 'uncalibrated') for k,ob in f['overall_style'].items()}
        effective=[s['effective'] for s in statuses if s['priority']=='critical']+list(overall.values())
        content=f['content_spatial'];basis=None
        if not ready or f['reviewer']['independence']!='independent' or f['review_order']!='image_first_then_evidence' or 'uncalibrated' in effective:status='needs_user_review'
        elif any(v['severity']=='major' for v in content.values()):status='rejected'
        elif 'conflict' in effective:status='needs_user_review'
        elif any(v in ('unmet','partial') for v in effective):status='revise'
        elif 'uncertain' in effective or any(v['severity']=='unknown' or v['confidence']!='high' for v in content.values()):status='insufficient_evidence'
        elif any(content[k]['severity']!='none_observed' for k in r['critical_preservation']):status='revise'
        elif any(s['severity'] in ('major','unknown') or s['confidence']!='high' for s in f['spillover']):status='needs_user_review'
        elif any(v['severity']=='minor_local_incidental' for v in content.values()):
            status='accepted' if policy['payload']['allow_minor_incidental'] else 'needs_user_review'
            if status=='accepted':basis='incidental_deviation_tolerated'
        else:status='accepted';basis='consistent'
        return _write(root,state,'decisions',spec['decision_id'],'acceptance_decision',dict(**deepcopy(spec),sequence=len(previous)+1,
            evaluation_hash=evaluation['content_hash'],facts_hash=facts['content_hash'],evaluation_version=e['version'],profile_hash=e['profile_hash'],
            raw_candidate_hash=e['raw_candidate_hash'],derived_hash=e['derived_hash'],
            status=status,acceptance_basis=basis,target_statuses=statuses,overall_style_statuses=overall,conflicts=conflicts,
            content_facts=deepcopy(content),spillover=deepcopy(f['spillover']),adjudication_hash=None if adjudication is None else adjudication['content_hash'],
            pixel_supervision_screening_status='not_certified',assets=[]))


def select(root,spec):
    exact(spec,('selection_id','version','decision_ids','rule_version'));code(spec['selection_id'],'sel');code(spec['version'],'q')
    require(spec['rule_version']=='first_accepted_generation_order_v1' and isinstance(spec['decision_ids'],list),'frozen transparent selection rule required')
    for key in spec['decision_ids']:code(key,'z')
    require(len(set(spec['decision_ids']))==len(spec['decision_ids']),'duplicate selection decision')
    with case_lock(root):
        state=co._status(root);require(spec['selection_id'] not in store.registry(state)['selections'],'selection manifest immutable')
        profile=store.get(root,state,'evaluation_versions',spec['version'])
        evaluations=[store.get(root,state,'evaluations',key) for key in store.registry(state)['evaluations']]
        evaluations=[e for e in evaluations if e['payload']['version']==spec['version']];require(evaluations,'no evaluated C candidate; never fallback A')
        for evaluation in evaluations:require_selected(root,state,evaluation)
        # The pool includes all generated candidates under this target lineage, not
        # just those the caller chose to evaluate after seeing favorable results.
        lineage=set();version=profile['payload']['target_version']
        while version is not None:
            target=store.get(root,state,'targets',version);lineage.add(target['content_hash']);version=target['payload']['revision']['predecessor_version']
        generated=[co._load(root,x['record_path'],'response') for x in state['payload']['results']]
        generated=[r for r in generated if r['payload'].get('edit_binding') is not None and r['payload']['target_hash'] in lineage]
        evaluated_ids={e['payload']['candidate_record_id'] for e in evaluations}
        unevaluated=[r['record_id'] for r in generated if r['record_id'] not in evaluated_ids]
        decisions={}
        for key in spec['decision_ids']:
            decision=_read(root,state,'decisions',key);d=decision['payload']
            require(d['evaluation_version']==spec['version'] and d['profile_hash']==profile['content_hash'],'different evaluation versions cannot be compared')
            require(d['evaluation_id'] not in decisions,'multiple conclusions for one candidate')
            latest=_decisions(root,state,d['evaluation_id'])[-1];require(latest['content_hash']==decision['content_hash'],'selection cannot use a superseded conclusion')
            decisions[d['evaluation_id']]=decision
        references=[d['payload']['verification_ref'] for d in decisions.values()]
        require(not references or all(r==references[0] for r in references),'selection requires compatible frozen policy/calibration versions')
        require(set(decisions)<={e['payload']['evaluation_id'] for e in evaluations},'decision not in frozen evaluated set')
        order=[co._load(root,x['record_path'],'response')['record_id'] for x in state['payload']['results']]
        evaluations.sort(key=lambda e:order.index(e['payload']['candidate_record_id']))
        pending=bool(unevaluated) or any(e['payload']['evaluation_id'] not in decisions or decisions[e['payload']['evaluation_id']]['payload']['status'] in ('needs_user_review','insufficient_evidence') for e in evaluations)
        accepted=[e for e in evaluations if e['payload']['evaluation_id'] in decisions and decisions[e['payload']['evaluation_id']]['payload']['status']=='accepted']
        selected=None if pending or not accepted else accepted[0];label=None
        if selected is not None:
            e=selected['payload'];d=decisions[e['evaluation_id']]['payload'];derived=store.by_id(root,state,'candidate_derivatives',e['derived_record_id']);c=derived['payload'];a=c['audit']
            label=dict(sample_id=state['sample_id'],evaluation_id=e['evaluation_id'],evaluation_hash=selected['content_hash'],evaluation_version=e['version'],
                evaluation_profile_hash=e['profile_hash'],generation_target_hash=e['generation_target_hash'],evaluation_target_hash=e['evaluation_target_hash'],
                raw_candidate_hash=e['raw_candidate_hash'],raw_output_path=c['raw_output_path'],derived_record_id=derived['record_id'],derived_record_hash=derived['content_hash'],
                derived_file_hash=None if a is None else a['derivative_file_hash'],derived_path=None if a is None else a['derivative_path'],
                source_pixel_hash=None if a is None else a['source_pixel_hash'],color_status=c['status'],geometry=c['geometry'],
                conversion_chain=None if a is None else a['conversion_chain'],visual_style_status='accepted',acceptance_basis=d['acceptance_basis'],
                pixel_supervision_screening_status='not_certified_local_drift_flagged' if d['acceptance_basis']=='incidental_deviation_tolerated' else 'not_certified_requires_alignment_screening',
                support_hash=e['support_hash'],content_facts=d['content_facts'],evaluated_artifact=deepcopy(e['selected_artifact']),candidate_measurement_basis=e['candidate_measurement_basis'])
            label.update(co.input_domain_metadata(root,state))
        summaries=[dict(evaluation_id=e['payload']['evaluation_id'],candidate_hash=e['payload']['raw_candidate_hash'],
            decision=None if e['payload']['evaluation_id'] not in decisions else {k:decisions[e['payload']['evaluation_id']]['payload'][k] for k in ('decision_id','status','target_statuses','overall_style_statuses','conflicts','acceptance_basis')}) for e in evaluations]
        return store.put(root,state,'selections',spec['selection_id'],'label_selection',dict(**deepcopy(spec),profile_hash=profile['content_hash'],
            status='pending_review' if pending else 'selected' if selected is not None else 'no_accepted_candidate',candidates=summaries,
            verification_ref=None if not references else deepcopy(references[0]),unevaluated_candidate_ids=unevaluated,label_manifest=label,assets=[]))


def export_report(root,path):
    """Human handoff only, never an execution context. No raw policy prose copied."""
    with case_lock(root):
        state=co._status(root);p=state['payload'];registry=store.registry(state);audit=co._load(root,'input_audit.json')
        domain=co.input_domain_metadata(root,state,audit)
        lines=['# Reference-style run report','', '**Human audit report: do not feed acceptance history back into edit prompts.**','',
            f'Sample: `{state["sample_id"]}`; purpose: `{p["purpose"]}`; schema: `{state["schema_version"]}`.',
            'Runtime: current_chat_offline file bridge. Code performs zero model/API calls; external dialogue is caller-attested, not remotely authenticated.','',
            '## Inputs / provenance',
            ('A is caller-declared camera RGB, not Base output. Scope: camera_rgb_workflow_only; this is not Base-model validation.'
             if domain['input_domain']=='camera_rgb' else 'A is caller-declared Base output; this code does not independently authenticate Base provenance.'),
            'Source hashes below identify supplied input bytes, not necessarily upstream camera-original bytes.']
        if domain['input_lineage'] is not None:
            ref=domain['input_lineage'];lines.append(f'Upstream original-to-supplied lineage artifact: `{ref["path"]}`, SHA256 `{ref["sha256"]}`. Hash-bound external attestation; conversion and upstream provenance are not automatically authenticated.')
        else:lines.append('Upstream original-to-supplied lineage artifact: not provided.')
        if p['purpose']=='protocol_fixture':lines.insert(2,'**SYNTHETIC PROTOCOL FIXTURE: no real model/style evidence or user calibration.**')
        for image in audit['payload']['images']:
            lines.append(f'- {image["role"]}: source `{image["source_file_hash"]}`, derivative `{image["derivative_file_hash"]}`, {image["source_encoding"]}, {image["source_bit_depth"]}-bit, native {image["native_size"]}, oriented {image["oriented_size"]}.')
        lines+=['','## Budget / attempts','```json',canonical_json(p.get('budget')).decode(),'```']
        for attempt in p['attempts']:
            request=co._load(root,attempt['request_path'],'request');r=request['payload']
            lines.append(f'- `{attempt["attempt_id"]}` / {attempt["stage_id"]}: **{attempt["status"]}**, request `{request["content_hash"]}`, prompt `{r["prompt_hash"]}`; planned attachments {len(r.get("planned_attachments",r["images"]))}.')
        lines+=['','## Actual stage records']
        for group in ('evidence','snapshots','reports','targets','compiled','submissions','candidate_derivatives','evaluation_versions','candidate_supports','evaluations','facts','feedback','selections','failures'):
            lines.append(f'- {group}: {len(registry[group])} record(s)' if registry[group] else f'- {group}: **NOT RUN / unavailable**')
            for key in registry[group]:
                v=store.get(root,state,group,key);vp=v['payload'];status=vp.get('status',vp.get('package_status',vp.get('stage_evidence_status','recorded')))
                if group=='evidence':status=vp['manifest']['status']
                lines.append(f'  - `{key}` / `{v["record_id"]}` / `{v["content_hash"]}`: {status}')
                if group=='submissions':lines+=['```json',canonical_json({k:vp[k] for k in ('submitted_prompt_hash','submitted_attachments','package_status','provenance_verification','remote_input_visibility')}).decode(),'```']
                if group=='candidate_derivatives':
                    summary={k:vp[k] for k in ('raw_candidate_hash','raw_output_path','status','geometry','spatial_correspondence','visual_style_status')}
                    summary['selected_derivative_audit']=None if vp['audit'] is None else {k:vp['audit'][k] for k in ('derivative_file_hash','derivative_pixel_hash','derivative_path','source_encoding','native_size','oriented_size','numeric_status','conversion_chain')}
                    lines+=['```json',canonical_json(summary).decode(),'```']
                if group=='selections':lines+=['```json',canonical_json({'label_manifest':vp['label_manifest'],'unevaluated_candidate_ids':vp['unevaluated_candidate_ids']}).decode(),'```']
                if group=='facts':lines+=['```json',canonical_json({k:vp[k] for k in ('overall_style','targets','content_spatial','spillover','reviewer','review_order')}).decode(),'```']
        lines+=['','## Candidate ABC numeric / visual findings']
        for key in registry['evaluations']:
            evaluation=store.get(root,state,'evaluations',key);e=evaluation['payload'];target=store.get(root,state,'targets',e['evaluation_target_version'])
            lines+=['```json',canonical_json(dict(candidate_measurement_basis=e.get('candidate_measurement_basis','legacy_native_C_requires_reevaluation'),
                selected_artifact=e.get('selected_artifact'),native_diagnostics_use='separate_raw_only_not_final_artifact_acceptance')).decode(),'```']
            selected={t['measurement_binding']['measurement_id'] for t in target['payload']['targets'] if t['measurement_binding'] is not None}
            lines += [f'### {key} / {e["version"]}',f'Raw C `{e["raw_candidate_hash"]}`; selected derivative record `{e["derived_hash"]}`.',
                f'Generation target `{e["generation_target_hash"]}`; evaluation target `{e["evaluation_target_hash"]}`.',
                '| Measure | A | B | C | C_minus_B | C_minus_A | baseline_absolute_residual | candidate_absolute_residual | Absolute improvement | Eligibility |','|---|---:|---:|---:|---:|---:|---:|---:|---:|---|']
            for m in e['measurements']:
                if m['measurement_id'] in selected or m['subject_id']=='g0' and m['statistic'] in ('q50','span95_05'):
                    lines.append('| '+f'{m["subject_id"]}/{m["metric"]}/{m["statistic"]}'+' | '+' | '.join(str(m[k]) for k in ('A','B','C','C_minus_B','C_minus_A','baseline_absolute_residual','candidate_absolute_residual','absolute_improvement','eligibility'))+' |')
            decisions=_decisions(root,state,key)
            if not decisions:lines.append('Verification: **NOT RUN**; no acceptance or pixel-label claim.')
            for decision in decisions:
                lines+=['```json',canonical_json({k:decision['payload'][k] for k in ('decision_id','status','acceptance_basis','overall_style_statuses','target_statuses','conflicts','verification_ref','pixel_supervision_screening_status')}).decode(),'```']
        lines+=['','## Unverified / NOT RUN items',
            '- Same-goal deterministic comparison and batch stability: **NOT RUN / UNVERIFIED**.',
            '- Training utility, pixel-label certification and downstream X pairing: **NOT RUN**.',
            '- Qwen server execution: **NOT INTEGRATED / NOT RUN**. Existing native bridge needs an explicit provider adapter and new provenance/receipt mapping; never label Qwen output as a ChatGPT receipt.',
            '- Real calibration/approval is only the supplied versioned artifact attestation; synthetic_fixture data never establishes real style performance.',
            '- Unknown/failed requests retain reservations. No fallback A is a successful C.']
        output=Path(path).absolute();co._immutable_bytes(output.parent,output.name,('\n'.join(lines)+'\n').encode('utf-8'))
        return {'path':str(output),'sha256':file_sha256(output),'purpose':'human_run_report_not_execution_context'}
