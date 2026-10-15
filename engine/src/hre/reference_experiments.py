"""One-shot v2 experiment plans and independent review, never a workflow state store."""
from collections import Counter,defaultdict
from copy import deepcopy
from importlib.resources import files
from pathlib import Path
import random
import re
import secrets
from .models import HREError,canonical_json,file_sha256,sha256_bytes
from .storage import CaseStore,atomic_write,read_json,write_json
from .paths import safe_path
from .masks import require,checked_file,validate_mask,validate_mask_probe
from .reference_contracts import create_reference_case,capture_g1_prompt,validate_reference_spec,_refs

ARMS=('G0','G1','G2')
DEFECT_CATEGORIES={'identity','text','geometry','scene_content','content_transfer','seam','color_artifact','clipping','other'}


def _runtime_digest():
    root=files('hre');inventory={}
    for path in sorted(Path(str(root)).rglob('*')):
        if path.is_file() and path.suffix in {'.py','.j2','.json'}:
            inventory[path.relative_to(Path(str(root))).as_posix()]=file_sha256(path)
    return sha256_bytes(canonical_json(inventory))


def _copy(root,dest,ref):
    data=checked_file(root,ref).read_bytes();target=safe_path(dest,ref['path'])
    if target.exists():require(target.read_bytes()==data,'immutable_conflict',ref['path'])
    else:atomic_write(target,data)


def freeze_reference_run(manifest,destination):
    manifest=Path(manifest);destination=Path(destination).absolute();data=read_json(manifest)
    keys={'schema_version','stage','seed','code_commit_sha','excluded_rater_ids','cases'}
    require(set(data)==keys and data['schema_version']=='reference_run_manifest_v2','run_schema','Complete explicit v2 manifest required')
    require(data['stage'] in {'R0_fixture','R1','R2','R3'} and type(data['seed']) is int
            and re.fullmatch('[a-f0-9]{40}',data['code_commit_sha']),'run_schema','Stage, frozen randomization seed and code commit required')
    require(isinstance(data['excluded_rater_ids'],list) and all(isinstance(v,str) and v for v in data['excluded_rater_ids']), 'run_schema','Declare generator/composer/operator rater exclusions')
    cases=data['cases'];require(isinstance(cases,list) and cases,'run_schema','At least one enrolled scene required')
    require(len({c['case_id'] for c in cases})==len(cases),'run_schema','Duplicate case identity')
    if data['stage']=='R1':require(3<=len(cases)<=5,'stage_count','R1 requires 3–5 pairs')
    if data['stage']=='R2':require(len(cases)==12,'stage_count','R2 requires 12 frozen pairs')
    require(not destination.exists() or not any(destination.iterdir()),'run_exists','Use a fresh run revision')
    prepared=[];identities={};groups=defaultdict(set);rng=random.Random(data['seed'])
    # Validate every source before writing the new run.
    for case in cases:
        require(set(case)=={'case_id','scene_group_id','split','source_case_root','g2'} and re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]*',case['case_id'])
                and case['scene_group_id'] and case['split'] in {'dev','pilot','test'},'run_schema','Explicit safe case, scene group and split required')
        require((data['stage']=='R3')==(case['split']=='test'),'split_leakage','Only R3 may use test, and R3 requires test')
        source=safe_path(manifest.parent,case['source_case_root'],must_exist=True);state=CaseStore(source).load();cfg=read_json(source/'config.json')
        spec=deepcopy(cfg.get('reference_v2'));validate_reference_spec(spec)
        require(spec['arm_id']=='G1' and state['case_id']==case['case_id'],'run_schema','Enroll a frozen v2 G1 input case with matching ID')
        require(not state['candidates'] and state['budget']['consumed']==0,'post_output_enrollment','Freeze ROI/eligibility before observing any output')
        require(data['stage']=='R0_fixture' or not spec['simulation_only'],'fixture_not_real','Synthetic fixtures cannot enter R1/R2/R3')
        require(data['stage']!='R0_fixture' or spec['simulation_only'],'fixture_not_real','R0_fixture is for marked simulations only')
        groups[case['scene_group_id']].add(case['split'])
        for a in state['inputs']:
            key=a['pixel_sha256'];prior=identities.get(key)
            require(prior is None or prior==case['split'],'split_leakage','A/B source reused across splits');identities[key]=case['split']
        g2=case['g2'];status='skipped_not_eligible';reason='Not pre-enrolled as local mask eligible';g2spec=None
        if spec['local_mask_eligible'] and spec['task_scope']=='local':
            status='skipped_capability';reason='No passed executor A+B+mask proof and edit mask'
            if g2 is not None:
                require(set(g2)=={'edit_mask','mask_probe','files'},'run_schema','G2 metadata requires edit mask, probe and files')
                for ref in g2['files']:checked_file(source,ref)
                listed={r['path']:r['sha256'] for r in g2['files']}
                required=_refs(g2['edit_mask'])+_refs(g2['mask_probe'])
                if g2['mask_probe'] is not None:required+=_refs(read_json(checked_file(source,g2['mask_probe'])))
                require(all(listed.get(r['path'])==r['sha256'] for r in required),'run_schema','Freeze all G2 probe/mask source artifacts')
                try:
                    require(g2['edit_mask'] is not None and g2['mask_probe'] is not None,'skipped_capability','Missing G2 mask/probe')
                    validate_mask(source,g2['edit_mask'],state['inputs'][0]);require(g2['edit_mask']['purpose']=='EDIT_MASK','mask_binding','G2 needs EDIT_MASK')
                    validate_mask_probe(source,g2['mask_probe'],spec['executor'],allow_fixture=spec['simulation_only'])
                    require(spec['eval_mask'] is not None,'mask_binding','G1/G2 require same pre-frozen EVAL_MASK')
                    status='planned';reason=None;g2spec=deepcopy(g2)
                except HREError as exc:
                    if exc.code!='skipped_capability':raise
                    reason=str(exc)
        prepared.append((case,source,state,spec,g2spec,status,reason))
    require(all(len(v)==1 for v in groups.values()),'split_leakage','A scene group cannot cross splits')
    destination.mkdir(parents=True,exist_ok=True);plan=[];frozen_files={}
    def remember(path):frozen_files[path.relative_to(destination).as_posix()]=file_sha256(path)
    for case,source,state,spec,g2,status,reason in prepared:
        target=destination/'frozen'/case['case_id']
        refs=[*spec['files']]
        for a in state['inputs']:
            refs.extend([{k:a[k] for k in ('path','sha256')},{k:a['source_file'][k] for k in ('path','sha256')}])
        if g2:refs.extend(g2['files'])
        for ref in refs:_copy(source,target,ref);remember(target/ref['path'])
        for name,value in [('spec.json',spec),('inputs.json',{'assets':state['inputs']}),('source_manifest.json',read_json(source/'manifest.json')),('g2.json',{'definition':g2})]:
            write_json(target/name,value);remember(target/name)
        order=list(ARMS);rng.shuffle(order)
        for arm in ARMS:
            plan.append(dict(case_id=case['case_id'],scene_group_id=case['scene_group_id'],split=case['split'],arm_id=arm,
                             execution_order=order.index(arm),status=status if arm=='G2' else 'planned',reason=reason if arm=='G2' else None,
                             case_root=f'cases/{case["case_id"]}/{arm}',local_mask_eligible=spec['local_mask_eligible'],executor_sha256=sha256_bytes(canonical_json(spec['executor']))))
    write_json(destination/'manifest.json',data);remember(destination/'manifest.json')
    write_json(destination/'plan.json',{'schema_version':'reference_plan_v2','rows':plan});remember(destination/'plan.json')
    run=dict(schema_version='reference_run_v2',stage=data['stage'],seed=data['seed'],code_commit_sha=data['code_commit_sha'],
             runtime_source_sha256=_runtime_digest(),files=frozen_files,simulation_only=data['stage']=='R0_fixture',
             excluded_rater_ids=data['excluded_rater_ids'],real_effect_validated=False)
    write_json(destination/'run.json',run)
    return destination/'run.json'


def _load(root):
    root=Path(root);run=read_json(root/'run.json')
    require(run.get('schema_version')=='reference_run_v2','run_schema','Not a v2 run')
    require(_runtime_digest()==run['runtime_source_sha256'],'runtime_changed','Installed evaluator/templates/code differ from this frozen run')
    for path,digest in run['files'].items():checked_file(root,dict(path=path,sha256=digest))
    return run,read_json(root/'plan.json')['rows']


def prepare_run_arm(root,case_id,arm):
    root=Path(root);run,plan=_load(root);matches=[r for r in plan if r['case_id']==case_id and r['arm_id']==arm]
    require(len(matches)==1,'unknown_arm','Case/arm not enrolled');row=matches[0]
    require(row['status']=='planned','skipped_capability',row['reason'] or 'Not eligible')
    target=safe_path(root,row['case_root']);frozen=root/'frozen'/case_id
    require(_runtime_digest()==run['runtime_source_sha256'],'runtime_changed','Installed code/templates changed; use the frozen version or a new run')
    if (target/'state.json').exists():return {'case_root':str(target.absolute()),'state':CaseStore(target).load()}
    spec=read_json(frozen/'spec.json');spec['arm_id']=arm
    if arm=='G2':
        g2=read_json(frozen/'g2.json')['definition'];spec.update(edit_mask=g2['edit_mask'],mask_probe=g2['mask_probe'])
        combined={ref['path']:ref for ref in spec['files']+g2['files']};spec['files']=list(combined.values())
        spec['paired_g1']=capture_g1_prompt(root/'cases'/case_id/'G1')
    inputs=read_json(frozen/'inputs.json')['assets']
    source_manifest=read_json(frozen/'source_manifest.json');source_manifest.update(case_id=case_id,scene_group_id=row['scene_group_id'],split=row['split'])
    state=create_reference_case(*[safe_path(frozen,a['source_file']['path'],must_exist=True) for a in inputs],spec,target,spec_root=frozen,manifest=source_manifest)
    return {'case_root':str(target.absolute()),'state':state}


def reference_run_status(root):
    from .reporting import cost_summary,_events
    from .reference_runtime import evaluate_reference_case
    root=Path(root);run,plan=_load(root);rows=[]
    for planned in plan:
        row=deepcopy(planned);row.update(candidate=None,geometry_status='unknown',content_status='unknown',costs=None,attributes=None,state_revision=None)
        frozen=root/'frozen'/row['case_id'];original=read_json(frozen/'spec.json');inputs=read_json(frozen/'inputs.json')['assets']
        row.update(executor=original['executor'],source_assets=original['source_assets'],input_assets=inputs,
                   roi_manifest_sha256=sha256_bytes(canonical_json(original['roi_pairs'])),eval_mask_sha256=original['eval_mask']['sha256'] if original['eval_mask'] else None,
                   config_sha256=None,prompt_sha256=None,executor_observation=None,mask_mode=None,edit_mask_sha256=None,
                   intended_submissions=1 if planned['status']=='planned' else 0,editor_mask_consumed=False)
        if row['arm_id']=='G2':
            g2=read_json(frozen/'g2.json')['definition']
            if g2:
                row['edit_mask_sha256']=g2['edit_mask']['sha256'];row['mask_mode']=read_json(checked_file(frozen,g2['mask_probe']))['mask_mode']
        case=safe_path(root,row['case_root'])
        if planned['status']!='planned' or not (case/'state.json').exists():rows.append(row);continue
        state=CaseStore(case).load();cfg=read_json(case/'config.json');spec=cfg['reference_v2'];row['config_sha256']=state['config_sha256']
        require(spec['arm_id']==row['arm_id'] and spec['source_assets']==original['source_assets'] and spec['executor']==original['executor']
                and spec['roi_pairs']==original['roi_pairs'] and spec['eval_mask']==original['eval_mask'],'run_identity_mismatch','Case no longer matches frozen inputs/ROI/executor')
        require(state['budget']['max_generations']==1,'run_identity_mismatch','Single-shot budget changed')
        if row['arm_id']=='G2':
            require(spec['paired_g1']==capture_g1_prompt(root/'cases'/row['case_id']/'G1'),'paired_g1_mismatch','G2 is not paired with this run actual G1 prompt')
            original_g2=read_json(root/'frozen'/row['case_id']/'g2.json')['definition']
            require(spec['edit_mask']==original_g2['edit_mask'] and spec['mask_probe']==original_g2['mask_probe'],
                    'run_identity_mismatch','G2 edit mask/probe differs from pre-enrollment')
        c=state['candidates'][0] if state['candidates'] else None
        for transaction in sorted((case/'transactions').glob('*.json')):
            accepted=read_json(transaction)['accepted_submission']
            if not accepted:continue
            response=read_json(case/accepted['response_path'])
            if response['stage']!='execute' or response['status']!='ok':continue
            for item in read_json(case/accepted['done_path'])['artifacts']:
                if item['kind']=='auxiliary' and item['path'].endswith('.json'):
                    try:observed=read_json(case/item['path'])
                    except HREError:continue
                    if observed.get('kind')=='hre_executor_observation_v2':
                        row['executor_observation']={'receipt':observed,'artifact':{k:item[k] for k in ('path','sha256')}}
                        row['prompt_sha256']=observed['prompt_sha256'];row['editor_mask_consumed']=spec['arm_id']=='G2'
        valid=c is not None and c['geometry']['status']=='pass' and state['budget']['consumed']==1 and not state['deviations']
        status='candidate_ready' if valid and state['workflow_state']=='COMPLETED' else 'failed' if state['workflow_state'] in {'FAILED','CANCELLED','COMPLETED'} else 'unknown' if state['workflow_state']=='PAUSED' else 'running'
        row.update(status=status,reason=state['terminal_reason'] or state['pause_reason'],state_revision=state['revision'],
                   candidate=c['asset'] if c else None,geometry_status=c['geometry']['status'] if c else 'unknown',
                   content_status=c['verification']['content_preservation'] if c and c['verification'] else 'unknown',
                   costs=cost_summary(state,_events(case)),attributes=evaluate_reference_case(case),
                   observed_submissions=state['budget']['consumed'],operator_active_time=None,observed_billed_cost=None)
        rows.append(row)
    return dict(schema_version='reference_run_status_v2',rows=rows,max_submissions=sum(r['status']=='planned' for r in plan),
                n_pairs=len({r['case_id'] for r in plan}),n_groups=len({r['scene_group_id'] for r in plan}),
                n_mask_eligible=sum(r['arm_id']=='G2' and r['local_mask_eligible'] for r in plan),n_mask_capable=sum(r['arm_id']=='G2' and r['status']=='planned' for r in plan),simulation_only=run['simulation_only'])


def export_reference_blind(root,destination):
    root=Path(root).absolute();destination=Path(destination).absolute();run,plan=_load(root)
    require(not destination.is_relative_to(root) and not root.is_relative_to(destination),'blind_path','Reviewer package must be outside the run and its private mapping')
    require(not destination.exists() or not any(destination.iterdir()),'export_exists','Use a fresh reviewer package')
    require(not (root/'private/blind_mapping_v2.json').exists(),'evaluation_frozen','An evaluation snapshot is already frozen')
    status=reference_run_status(root);rows=[r for r in status['rows'] if not r['status'].startswith('skipped_')]
    rng=random.Random(run['seed']);rng.shuffle(rows);items=[];mapping=[];lookup={};destination.mkdir(parents=True,exist_ok=True)
    for row in rows:
        code=secrets.token_hex(12);frozen=root/'frozen'/row['case_id'];inputs=read_json(frozen/'inputs.json')['assets'];spec=read_json(frozen/'spec.json')
        image_paths={};candidate=row['candidate'];candidate_root=root/row['case_root']
        for role,a,source in [('A',inputs[0],frozen),('B',inputs[1],frozen),('C',candidate or inputs[0],candidate_root if candidate else frozen)]:
            path='images/'+code+'_'+role+'.png'
            atomic_write(destination/path,checked_file(source,{k:a[k] for k in ('path','sha256')}).read_bytes());image_paths[role]=path
        dimensions=sorted({d for p in spec['roi_pairs'] for d in p['dimensions']})
        review_regions=[]
        for index,pair in enumerate(spec['roi_pairs']):
            entry={'dimensions':pair['dimensions'],'comparability':pair['comparability']}
            for role,label in [('prediction','A'),('reference','B')]:
                region=deepcopy(pair[role])
                if region['kind']=='mask':
                    import numpy as np
                    from PIL import Image
                    from io import BytesIO
                    values=np.load(checked_file(frozen,{k:region[k] for k in ('path','sha256')}),allow_pickle=False)
                    image=BytesIO();Image.fromarray(values*255).save(image,format='PNG')
                    path=f'regions/{code}_{index}_{label}.png';atomic_write(destination/path,image.getvalue())
                    region={'kind':'mask','path':path,'sha256':file_sha256(destination/path),'semantics':'white_target','coordinate_image':label}
                entry[role]=region
            review_regions.append(entry)
        items.append(dict(code=code,images=image_paths,target_dimensions=dimensions,
                          roi_regions=review_regions))
        mapping.append(dict(code=code,row=row));lookup[(row['case_id'],row['arm_id'])]=code
    comparisons=[];private_comparisons=[]
    for cid in sorted({r['case_id'] for r in rows}):
        for left_arm,right_arm,hyp in [('G1','G0','H1'),('G2','G1','H2')]:
            if (cid,left_arm) not in lookup or (cid,right_arm) not in lookup:continue
            sides=[left_arm,right_arm];rng.shuffle(sides);code=secrets.token_hex(12)
            comparisons.append(dict(code=code,left=lookup[(cid,sides[0])],right=lookup[(cid,sides[1])]))
            private_comparisons.append(dict(code=code,case_id=cid,hypothesis=hyp,left_arm=sides[0],right_arm=sides[1],preferred_arm=left_arm))
    neutral=dict(schema_version='reference_blind_v2',items=items,comparisons=comparisons,
                 rubric=dict(style_anchor='B appearance; judge improvement relative to A',content_anchor='A',
                             joint_success='Improved style, preserved content, no critical defects; review each requested attribute',
                             critical_defect_contract={'categories':sorted(DEFECT_CATEGORIES),'severity':'critical','observation':'Nonempty description; categories must not be free-form text'}))
    write_json(destination/'manifest.json',neutral)
    private=dict(schema_version='reference_blind_mapping_v2',blind_manifest_sha256=file_sha256(destination/'manifest.json'),
                 rows=mapping,comparisons=private_comparisons,status_sha256=sha256_bytes(canonical_json(status)),
                 reviewer_files={p.relative_to(destination).as_posix():file_sha256(p) for p in destination.rglob('*') if p.is_file()})
    write_json(root/'private/blind_mapping_v2.json',private)
    write_json(root/'private/evaluation_freeze_v2.json',{'mapping_sha256':file_sha256(root/'private/blind_mapping_v2.json')})
    return destination/'manifest.json'


def _resolved(entries,key,raters,excluded,validate,signature):
    rows=[e for e in entries if e.get('code')==key]
    require(len({(r.get('rater_id'),r.get('kind')) for r in rows})==len(rows),'ratings_invalid','Duplicate review/adjudication')
    for r in rows:
        require(r.get('rater_id') in raters and r['rater_id'] not in excluded and raters[r['rater_id']] is True,
                'ratings_not_independent','Unknown, excluded or non-independent reviewer')
        validate(r)
    reviews=[r for r in rows if r.get('kind')=='review'];judges=[r for r in rows if r.get('kind')=='adjudication']
    if len(reviews)!=2:return None
    if signature(reviews[0])==signature(reviews[1]):return reviews[0]
    if len(judges)==1 and judges[0]['rater_id'] not in {r['rater_id'] for r in reviews}:return judges[0]
    return None


def _independent_attributes(root,row,verdict):
    """Workflow measurements remain audit data; final validity follows independent content review."""
    measured=deepcopy(row.get('attributes'))
    if measured is None:
        spec=read_json(Path(root)/'frozen'/row['case_id']/'spec.json')
        measured=dict(per_roi=[dict(roi_pair_id=p['roi_pair_id'],status='not_assessable',attributes=None,stats=None,reasons=['No candidate']) for p in spec['roi_pairs']],
                      n_evaluable=0,spill=None)
    content=verdict['content'] if verdict and not verdict['critical_defects'] else 'fail' if verdict else 'unknown'
    if content!='pass':
        for roi in measured['per_roi']:
            roi.update(status='not_assessable',attributes=None,stats=None)
            roi.setdefault('reasons',[]).append('Independent content preservation failed or is unresolved')
        measured.update(n_evaluable=0,spill=None,content_status=content,validity_source='independent_review')
        return measured
    if row['candidate'] and row['geometry_status']=='pass' and measured.get('content_status')!='pass':
        from .reference_evaluator import evaluate_reference
        case=Path(root)/row['case_root'];state=CaseStore(case).load();spec=read_json(case/'config.json')['reference_v2']
        measured=evaluate_reference(*state['inputs'],row['candidate'],spec['roi_pairs'],case_root=case,
                                    geometry_status='pass',content_status='pass',eval_mask=spec['eval_mask'],task_scope=spec['task_scope'])
    measured['validity_source']='independent_review'
    return measured


def _h2_decision(rows,preferences,*,n_eligible,n_capable):
    by={(r['case_id'],r['arm_id']):r for r in rows};qualified=[];benefits=[];critical_G1=critical_G2=0
    for case in sorted({r['case_id'] for r in rows if r['arm_id']=='G2'}):
        g1,g2=by.get((case,'G1')),by.get((case,'G2'))
        if not g1 or not g2:continue
        critical_G1+=int(bool(g1.get('review') and g1['review']['critical_defects']))
        critical_G2+=int(bool(g2.get('review') and g2['review']['critical_defects']))
        if g1['status']!=g2['status'] or g1['status']!='candidate_ready' or g1['review_unknown'] or g2['review_unknown']:continue
        qualified.append(case)
        preference=next((p['result'] for p in preferences if p['case_id']==case),'unknown')
        if preference!='win' or not g2['joint_success'] or g1['review']['content']!='pass' or g1['review']['critical_defects']:continue
        a={r['roi_pair_id']:r for r in g1['attributes']['per_roi']};b={r['roi_pair_id']:r for r in g2['attributes']['per_roi']}
        attribute=any((a[k].get('attributes') and b[k].get('attributes') and any(
                      b[k]['attributes'][d]['after']+1e-4<a[k]['attributes'][d]['after'] for d in a[k]['attributes'] if d in b[k]['attributes'])) for k in a.keys()&b.keys())
        s1,s2=g1['attributes'].get('spill'),g2['attributes'].get('spill');spill=False
        if s1 and s2 and s1.get('status')==s2.get('status')=='measured' and s1['outside_area']==s2['outside_area']:
            L1,L2=s1['outside_L_mean_absolute_change'],s2['outside_L_mean_absolute_change'];ab1,ab2=s1['outside_ab_mean_distance'],s2['outside_ab_mean_distance']
            spill=(L2+.1<L1 and ab2<=ab1+.1) or (ab2+.1<ab1 and L2<=L1+.1)
        if attribute or spill:benefits.append(dict(case_id=case,reference_attribute_better=bool(attribute),spill_reduced=bool(spill)))
    wins=sum(p['result']=='win' for p in preferences);losses=sum(p['result']=='loss' for p in preferences);unknown=sum(p['result']=='unknown' for p in preferences)
    decision='PROBE';reason='Need six completed qualified pairs, two reviewed local benefits, and no new serious defects'
    if n_capable==0:decision='SKIPPED';reason='No capability-qualified local cohort; G0/G1 can continue independently'
    elif critical_G2:decision='STOP';reason='Serious G2 defects; withhold Mask route'
    elif len(qualified)>=6 and unknown==0 and len(benefits)>=2 and wins>=2:decision='GO';reason='Conditional local Mask engineering gate met'
    elif len(qualified)>=6 and unknown==0 and (losses>wins or len(benefits)<2):decision='STOP';reason='No demonstrated Mask net benefit at the planned local gate'
    return dict(decision=decision,reason=reason,eligible_pairs=n_eligible,capable_pairs=n_capable,qualified_pairs=len(qualified),
                local_benefit_cases=benefits,n_local_benefit=len(benefits),critical_G1=critical_G1,critical_G2=critical_G2,
                spill_minimum_absolute_change=.1,minimum_qualified_pairs=6,minimum_local_benefit_pairs=2)


def summarize_reference_run(root,ratings):
    root=Path(root);run,plan=_load(root);mapping=read_json(root/'private/blind_mapping_v2.json');freeze=read_json(root/'private/evaluation_freeze_v2.json')
    require(file_sha256(root/'private/blind_mapping_v2.json')==freeze['mapping_sha256'],'artifact_hash_mismatch','Blind mapping changed')
    current=reference_run_status(root)
    require(sha256_bytes(canonical_json(current))==mapping['status_sha256'],'evaluation_changed','Case outputs changed after blind export; create a new run revision')
    data=read_json(ratings)
    require(set(data)=={'schema_version','blind_manifest_sha256','raters','ratings','comparisons'}
            and data['schema_version']=='reference_ratings_v2' and data['blind_manifest_sha256']==mapping['blind_manifest_sha256'],
            'ratings_invalid','Ratings must bind this frozen neutral manifest')
    require(len({r['rater_id'] for r in data['raters']})==len(data['raters']),'ratings_invalid','Duplicate rater')
    raters={r['rater_id']:r['independent'] for r in data['raters']};excluded=set(run['excluded_rater_ids'])
    allowed_codes={m['code'] for m in mapping['rows']};comparison_codes={c['code'] for c in mapping['comparisons']}
    require(all(r.get('code') in allowed_codes for r in data['ratings']) and all(r.get('code') in comparison_codes for r in data['comparisons']),
            'ratings_invalid','Unknown blinded item or comparison')
    styles={'improved','unchanged','worse','uncertain'};content={'pass','fail','uncertain'}
    def valid_review(r):
        require(set(r)=={'code','rater_id','kind','style','content','critical_defects','attributes','notes'}
                and r['kind'] in {'review','adjudication'} and r['style'] in styles and r['content'] in content
                and isinstance(r['critical_defects'],list) and all(isinstance(x,dict) and set(x)=={'category','severity','observation'}
                    and x['category'] in DEFECT_CATEGORIES and x['severity']=='critical' and isinstance(x['observation'],str) and x['observation'].strip() for x in r['critical_defects'])
                and isinstance(r['attributes'],dict) and all(v in styles for v in r['attributes'].values()) and r['notes'],
                'ratings_invalid','Incomplete independent attribute/content review')
        require(not (r['content']=='pass' and r['critical_defects']),'ratings_invalid','Content pass contradicts critical defects')
    arms={a:dict(n_itt=sum(r['arm_id']==a and r['status']=='planned' for r in plan),joint_success=0,n_unknown=0,n_failed=0,n_critical=0,n_content_failed=0) for a in ARMS}
    output=[];h3=[]
    for item in mapping['rows']:
        row=deepcopy(item['row']);verdict=_resolved(data['ratings'],item['code'],raters,excluded,valid_review,
                              lambda r:(r['style'],r['content'],canonical_json(sorted(r['critical_defects'],key=lambda x:(x['category'],x['observation']))),canonical_json(r['attributes'])))
        if verdict:
            spec=read_json(root/'frozen'/row['case_id']/'spec.json');dims={d for p in spec['roi_pairs'] for d in p['dimensions']}
            require(set(verdict['attributes'])==dims,'ratings_invalid','Review all frozen target attributes')
        row['workflow_attributes']=deepcopy(row.get('attributes'));row['attributes']=_independent_attributes(root,row,verdict)
        success=bool(verdict and row['status']=='candidate_ready' and verdict['style']=='improved' and verdict['content']=='pass'
                     and not verdict['critical_defects'] and row['attributes']['n_evaluable']>0)
        unknown=(verdict is None or verdict['style']=='uncertain' or verdict['content']=='uncertain' or row['status'] not in {'candidate_ready','failed'}
                 or (verdict['content']=='pass' and row['attributes']['n_evaluable']==0))
        summary=arms[row['arm_id']];summary['joint_success']+=int(success);summary['n_unknown']+=int(unknown)
        summary['n_failed']+=int(row['status']=='failed');summary['n_critical']+=int(bool(verdict and verdict['critical_defects']))
        summary['n_content_failed']+=int(bool(verdict and verdict['content']=='fail'))
        row.update(blind_code=item['code'],joint_success=success,review_unknown=unknown,review=verdict);output.append(row)
        frozen_spec=read_json(root/'frozen'/row['case_id']/'spec.json');evaluated={r['roi_pair_id']:r for r in row['attributes']['per_roi']}
        for roi in frozen_spec['roi_pairs']:
            for dim in roi['dimensions']:
                metric=(evaluated.get(roi['roi_pair_id'],{}).get('attributes') or {}).get(dim)
                label=verdict['attributes'].get(dim) if verdict else None
                direction=('improved' if metric['delta']>1e-4 else 'worse' if metric['delta']< -1e-4 else 'unchanged') if metric else None
                h3.append(dict(case_id=row['case_id'],arm_id=row['arm_id'],roi_pair_id=roi['roi_pair_id'],attribute=dim,metric_direction=direction,
                               review_direction=label,status='unknown' if direction is None or label in {None,'uncertain'} else 'agree' if direction==label else 'conflict',
                               reason='Independent content/ROI validity unresolved or failed' if direction is None else None))
    outcomes={(r['case_id'],r['arm_id']):r for r in output};comparisons={h:dict(wins=0,ties=0,losses=0,unknown=0) for h in ('H1','H2')}
    def valid_pair(r):require(set(r)=={'code','rater_id','kind','preference','notes'} and r['kind'] in {'review','adjudication'} and r['preference'] in {'left','right','tie','uncertain'} and r['notes'], 'ratings_invalid','Invalid paired preference')
    h2_preferences=[]
    for comp in mapping['comparisons']:
        label=_resolved(data['comparisons'],comp['code'],raters,excluded,valid_pair,lambda r:r['preference'])
        left=outcomes[(comp['case_id'],comp['left_arm'])];right=outcomes[(comp['case_id'],comp['right_arm'])]
        key='unknown'
        if label and label['preference']!='uncertain' and left['status']==right['status']=='candidate_ready':
            if label['preference']=='tie':key='ties'
            else:key='wins' if comp[label['preference']+'_arm']==comp['preferred_arm'] else 'losses'
        comparisons[comp['hypothesis']][key]+=1
        if comp['hypothesis']=='H2':h2_preferences.append(dict(case_id=comp['case_id'],result={'wins':'win','losses':'loss','ties':'tie','unknown':'unknown'}[key]))
    serious=any(r['arm_id'] in {'G0','G1'} and r['review'] and r['review']['critical_defects'] for r in output)
    h1=comparisons['H1'];delta=arms['G1']['joint_success']-arms['G0']['joint_success']
    decision='PROBE';reason='Insufficient independent evidence or net benefit; do not scale automatically'
    if serious:decision='STOP';reason='Serious identity/text/content transfer defect in independent review'
    elif run['simulation_only']:reason='Fixture-only engineering validation; real R1/R2 have not run'
    elif run['stage']=='R1' and any(all((cid,arm) in outcomes and outcomes[(cid,arm)]['status']=='candidate_ready'
            and not outcomes[(cid,arm)]['review_unknown'] and outcomes[(cid,arm)]['review']['content']=='pass'
            and outcomes[(cid,arm)]['attributes']['n_evaluable']>0 for arm in ('G0','G1'))
            and any(outcomes[(cid,arm)]['joint_success'] for arm in ('G0','G1')) for cid in {r['case_id'] for r in output}) and not any(r['status']=='failed' for r in output if r['arm_id'] in {'G0','G1'}):
        decision='GO_TO_R2';reason='Real small-sample chain has an independently reviewed successful result; no population claim'
    elif run['stage'] in {'R2','R3'} and current['n_groups']>=12 and h1['unknown']==0 and arms['G0']['n_unknown']==arms['G1']['n_unknown']==0 and h1['wins']-h1['losses']>=3 and delta>0 and arms['G1']['n_critical']<=arms['G0']['n_critical']:
        decision='GO';reason='Predeclared engineering net-benefit gate met; not statistical significance'
    h2_decision=_h2_decision(output,h2_preferences,n_eligible=current['n_mask_eligible'],n_capable=current['n_mask_capable'])
    result=dict(schema_version='reference_summary_v2',arms=arms,H1=h1,H2=comparisons['H2'],H3=h3,
                n_pairs=current['n_pairs'],n_groups=current['n_groups'],n_mask_eligible=current['n_mask_eligible'],n_mask_capable=current['n_mask_capable'],
                n_mask_skipped=sum(r['arm_id']=='G2' and r['status'].startswith('skipped_') for r in plan),planned_rows=plan,rows=output,
                n_evaluable=sum(r['attributes']['n_evaluable']>0 for r in output),n_failed=sum(r['status']=='failed' or bool(r['review'] and r['review']['content']=='fail') for r in output),
                n_unknown=sum(r['review_unknown'] for r in output),
                joint_success_difference_G1_minus_G0=delta,decision=decision,decision_reason=reason,
                H1_decision={'decision':decision,'reason':reason},H2_decision=h2_decision,decision_scope='G1_vs_G0',
                simulation_only=run['simulation_only'],real_effect_validated=not run['simulation_only'] and run['stage'] in {'R2','R3'} and decision=='GO',
                limitations=['Unknown/missing/failed items remain in eligible ITT denominators. No NR-IQA or cross-attribute quality aggregate.',
                             'Mask comparisons require frozen same executor, inputs, prompt and eligible local cohort. Costs may be unknown.'])
    output_path=root/'analysis'/('summary_'+file_sha256(Path(ratings))[:16]+'.json')
    from .evidence import _immutable
    _immutable(output_path,result)
    return result
