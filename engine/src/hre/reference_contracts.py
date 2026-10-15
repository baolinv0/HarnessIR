"""Opt-in v2 configuration composed with the existing CaseStore/Controller."""
from copy import deepcopy
from importlib.resources import files
from pathlib import Path
import json
import math
import numpy as np
from .models import HREError, canonical_json, file_sha256, sha256_bytes
from .storage import CaseStore, atomic_write, read_json
from .paths import safe_path
from .masks import checked_file, require, validate_mask, validate_mask_probe
from .reference_evaluator import DIMENSIONS, region_mask

VERSION='ref_enhance_v2'
PROFILE_MAP={'G0':'direct_ref','G1':'agent_single','G2':'direct_ref'}
EXECUTOR_KEYS={'executor_id','model_display_name','model_exact_version','transport','pipeline_version','adapter_version','settings'}
SPEC_KEYS={'schema_version','arm_id','executor','task_scope','local_mask_eligible','roi_pairs','eval_mask','edit_mask','mask_probe','paired_g1','files','simulation_only','assume_srgb','tool_profile'}


def validate_executor(executor):
    require(isinstance(executor,dict) and set(executor)==EXECUTOR_KEYS,'invalid_executor','Explicit executor identity/settings required')
    require(all(isinstance(executor[k],str) and executor[k].strip() and executor[k]!='unknown'
                for k in EXECUTOR_KEYS-{'model_exact_version','settings'}),'invalid_executor','Record actual visible executor identity')
    require(executor['model_exact_version'] is None or isinstance(executor['model_exact_version'],str),'invalid_executor','Exact version is text or null if not observable')
    require(isinstance(executor['settings'],dict),'invalid_executor','Observed settings must be an object; unobservable values may be null')
    canonical_json(executor)


def validate_reference_spec(spec):
    from jsonschema import Draft202012Validator
    schema=json.loads((files('hre')/'resources/v2/reference_spec.schema.json').read_text())
    error=next(iter(Draft202012Validator(schema).iter_errors(spec)),None)
    if error:raise HREError('v2_schema',str(error.message))
    require(isinstance(spec,dict) and SPEC_KEYS<=set(spec) and not set(spec)-SPEC_KEYS-{'source_assets','mask_roi_policy'},'v2_schema','Unknown or missing v2 fields')
    require(spec['schema_version']==VERSION and spec['arm_id'] in PROFILE_MAP,'v2_schema','Unknown v2 arm/version')
    validate_executor(spec['executor'])
    require(spec['task_scope'] in {'local','global'} and type(spec['local_mask_eligible']) is bool
            and type(spec['simulation_only']) is bool,'v2_schema','Explicit scope/eligibility/simulation status required')
    require(isinstance(spec['roi_pairs'],list) and isinstance(spec['files'],list),'v2_schema','Region/file arrays required')
    require(type(spec['assume_srgb']) is bool and isinstance(spec['tool_profile'],dict),'v2_schema','Explicit color assumption and frozen analysis tool profile required')
    seen=set()
    for p in spec['roi_pairs']:
        keys={'roi_pair_id','prediction','reference','comparability','reasons','semantic_label','dimensions'}
        require(isinstance(p,dict) and set(p)==keys and isinstance(p['roi_pair_id'],str) and p['roi_pair_id']
                and p['roi_pair_id'] not in seen,'invalid_roi','Unique ROI identity and complete metadata required');seen.add(p['roi_pair_id'])
        require(p['comparability'] in {'comparable','partly_comparable','not_comparable','unknown','absent','unreliable'}
                and isinstance(p['reasons'],list) and p['reasons'] and all(isinstance(x,str) and x for x in p['reasons'])
                and isinstance(p['semantic_label'],str) and p['semantic_label'],'invalid_roi','Comparable-material annotation required')
        require(isinstance(p['dimensions'],list) and p['dimensions'] and set(p['dimensions'])<=DIMENSIONS
                and len(set(p['dimensions']))==len(p['dimensions']),'invalid_roi','Explicit unique target attributes required')
        for key in ('prediction','reference'):
            if p[key].get('kind')!='mask':region_mask((2,2,3),p[key],Path('.'))
    try:canonical_json(spec)
    except (ValueError,TypeError) as exc:raise HREError('v2_schema','Finite JSON values required') from exc


def _refs(value):
    result=[]
    if isinstance(value,dict):
        if 'path' in value and 'sha256' in value:result.append({k:value[k] for k in ('path','sha256')})
        for v in value.values():result.extend(_refs(v))
    elif isinstance(value,list):
        for v in value:result.extend(_refs(v))
    return result


def validate_artifacts(root,spec):
    refs={}
    for ref in spec['files']:
        path=checked_file(root,ref)
        require(ref['path'].split('/')[0] in {'annotations','capability_probes','paired'},'v2_artifact','Use annotations/, capability_probes/ or paired/ for v2 artifacts')
        require(ref['path'] not in refs,'v2_artifact','Duplicate artifact path')
        refs[ref['path']]=ref['sha256']
    required=_refs({k:v for k,v in spec.items() if k!='files'})
    if spec['mask_probe'] is not None:
        probe=read_json(checked_file(root,spec['mask_probe']));required.extend(_refs(probe))
    for ref in required:
        require(refs.get(ref['path'])==ref['sha256'],'v2_artifact','Every referenced artifact must be frozen in files: '+ref['path'])
    return refs


def prepare_reference_config(root,config,inputs):
    if 'reference_v2' not in config:return
    spec=config['reference_v2'];validate_reference_spec(spec)
    require(config['profile_id']==PROFILE_MAP[spec['arm_id']] and config['max_generations']==1
            and config['geometry_policy']['mode']=='strict','v2_schema','v2 requires mapped single-generation strict-geometry profile')
    sources={a['role']:a['pixel_sha256'] for a in inputs}
    if 'source_assets' in spec:require(spec['source_assets']==sources,'image_binding_mismatch','v2 source pixels changed')
    spec['source_assets']=sources
    validate_artifacts(root,spec)
    a,b=inputs
    for p in spec['roi_pairs']:
        region_mask((a['height'],a['width'],3),p['prediction'],root)
        region_mask((b['height'],b['width'],3),p['reference'],root)
    roi_ids={p['roi_pair_id'] for p in spec['roi_pairs']}
    for field,purpose in [('eval_mask','EVAL_MASK'),('edit_mask','EDIT_MASK')]:
        if spec[field] is not None:
            validate_mask(root,spec[field],a)
            require(spec[field]['purpose']==purpose and set(spec[field]['target_roi_ids'])<=roi_ids,'mask_binding','Mask purpose or frozen ROI membership differs')
    mask_roi_binding(root,spec,a)
    if spec['arm_id']=='G2':
        require(spec['task_scope']=='local' and spec['local_mask_eligible'] and spec['edit_mask'] is not None
                and spec['eval_mask'] is not None and spec['mask_probe'] is not None and spec['paired_g1'] is not None,
                'skipped_capability','G2 needs local eligibility, edit/eval masks, a probe and paired G1 text')
        validate_mask_probe(root,spec['mask_probe'],spec['executor'],allow_fixture=spec['simulation_only'])
        paired=spec['paired_g1']
        require(paired.get('schema_version')=='paired_g1_prompt_v2' and paired.get('source_assets')==sources
                and paired.get('executor')==spec['executor'] and paired.get('task_scope')=='local'
                and paired.get('roi_pairs')==spec['roi_pairs'] and paired.get('eval_mask')==spec['eval_mask']
                and paired.get('mask_roi_policy')==spec.get('mask_roi_policy')
                and paired.get('simulation_only')==spec['simulation_only'], 'paired_g1_mismatch','G1 inputs, executor, ROI/eval mask and scope must be identical')
        require(paired.get('prompt_sha256')==sha256_bytes(paired['rendered_prompt'].encode())
                and paired.get('edit_prompt_sha256')==sha256_bytes(paired['edit_prompt'].encode()),'paired_g1_mismatch','Paired G1 text hashes differ')
        require(paired.get('all_targets_local') is True and set(paired.get('target_roi_ids',[]))==set(spec['edit_mask']['target_roi_ids'])
                ==set(spec['eval_mask']['target_roi_ids']),'paired_g1_mismatch','G2 masks must cover precisely the frozen G1 local target identities')
        for name in ('eval_mask','edit_mask'):
            mask=validate_mask(root,spec[name],a)
            require(not mask.all(),'mask_binding','A local mask comparison needs protected non-target pixels')
    else:
        require(spec['edit_mask'] is None and spec['paired_g1'] is None,'v2_schema','G0/G1 cannot consume an EDIT_MASK or G1 executor snapshot')


def mask_roi_binding(root,spec,prediction):
    """Measure actual A-coordinate overlap against task-specific frozen bounds."""
    masks={name:validate_mask(root,spec[field],prediction).astype(bool) for name,field in
           [('EDIT_MASK','edit_mask'),('EVAL_MASK','eval_mask')] if spec[field] is not None}
    policy=spec.get('mask_roi_policy')
    if policy is None and spec['arm_id']!='G2' and 'EDIT_MASK' not in masks:return None
    keys={'schema_version','roi_constraints','max_edit_outside_fraction','max_eval_outside_fraction','rationale'}
    require(isinstance(policy,dict) and set(policy)==keys and policy['schema_version']=='mask_roi_policy_v2'
            and isinstance(policy['rationale'],str) and policy['rationale'].strip(),'mask_roi_policy','Freeze explicit task-specific Mask/ROI tolerances before any output')
    require('EVAL_MASK' in masks,'mask_roi_policy','A local Mask cohort requires its pre-frozen EVAL_MASK')
    constraints=policy['roi_constraints'];ids=spec['eval_mask']['target_roi_ids']
    require(isinstance(constraints,list) and len(constraints)==len(ids) and all(isinstance(c,dict)
            and set(c)=={'roi_pair_id','min_edit_coverage','min_eval_coverage'} for c in constraints)
            and {c['roi_pair_id'] for c in constraints}==set(ids),'mask_roi_policy','One spatial constraint per frozen target ROI required')
    def fraction(value,*,coverage=False):
        return type(value) in (int,float) and math.isfinite(value) and (0<value<=1 if coverage else 0<=value<1)
    require(all(fraction(c[k],coverage=True) for c in constraints for k in ('min_edit_coverage','min_eval_coverage'))
            and all(fraction(policy[k]) for k in ('max_edit_outside_fraction','max_eval_outside_fraction')),
            'mask_roi_policy','Coverage must be in (0,1]; outside fraction in [0,1)')
    rois={p['roi_pair_id']:p for p in spec['roi_pairs']}
    require(set(ids)<=set(rois) and ('EDIT_MASK' not in masks or set(spec['edit_mask']['target_roi_ids'])==set(ids)),
            'mask_spatial_binding','Masks and spatial policy must name the same frozen targets')
    union=np.zeros((prediction['height'],prediction['width']),dtype=bool);rows=[]
    for constraint in constraints:
        rid=constraint['roi_pair_id'];target=region_mask((*union.shape,3),rois[rid]['prediction'],root);area=int(target.sum())
        require(area>0,'mask_spatial_binding','Target ROI has no canonical A pixels: '+rid);union|=target
        row=dict(roi_pair_id=rid,target_area=area)
        for name,prefix in [('EDIT_MASK','edit'),('EVAL_MASK','eval')]:
            if name not in masks:row[prefix+'_coverage']=None;continue
            coverage=int(np.count_nonzero(masks[name]&target))/area;row[prefix+'_coverage']=coverage
            require(coverage>=constraint['min_'+prefix+'_coverage'],'mask_spatial_binding',f'{name} undercovers ROI {rid}: {coverage:.6f}')
        rows.append(row)
    summaries={};union_area=int(union.sum())
    for name,mask in masks.items():
        area=int(mask.sum());outside=int(np.count_nonzero(mask&~union));ratio=outside/area
        prefix='edit' if name=='EDIT_MASK' else 'eval'
        require(ratio<=policy['max_'+prefix+'_outside_fraction'],'mask_spatial_binding',f'{name} exceeds frozen target-outside allowance: {ratio:.6f}')
        summaries[name]=dict(mask_area=area,target_union_area=union_area,outside_area=outside,
                             outside_mask_fraction=ratio,outside_to_roi_area_ratio=outside/union_area)
    return dict(schema_version='mask_roi_binding_v2',policy=deepcopy(policy),per_roi=rows,masks=summaries)


def create_reference_case(prediction,reference,spec,case_root,*,spec_root,manifest=None):
    from .assets import create_case
    spec=deepcopy(spec);validate_reference_spec(spec)
    if spec['arm_id']=='G2' and spec['mask_probe'] is None:
        raise HREError('skipped_capability','G2 has no observed executor mask proof; no generation was reserved')
    root=Path(case_root).absolute();source=Path(spec_root).absolute()
    require(not (root/'state.json').exists() and not (root/'config.json').exists(),'case_exists','Use a new revision')
    validate_artifacts(source,spec)
    for ref in spec['files']:
        data=checked_file(source,ref).read_bytes();target=safe_path(root,ref['path'])
        if target.exists():require(target.read_bytes()==data,'immutable_conflict','Existing case artifact differs')
        else:atomic_write(target,data)
    # v1 ROI_COMPARE accepts boxes. Rich polygon/mask regions stay in the explicit
    # v2 evaluator/Composer context and are never approximated by rectangles.
    legacy_rois=[dict(roi_pair_id=p['roi_pair_id'],prediction=p['prediction']['box'],reference=p['reference']['box'],
                     coordinate_system='canonical_norm',comparability=p['comparability'] if p['comparability'] in {'comparable','partly_comparable','not_comparable','unknown'} else 'unknown',reason='; '.join(p['reasons']))
                 for p in spec['roi_pairs'] if p['prediction']['kind']==p['reference']['kind']=='box']
    tools={'profile_id':'reference_v2','available_tools':['STATS','ROI_COMPARE'],**deepcopy(spec['tool_profile'])}
    if any(p['prediction']['kind']!='box' or p['reference']['kind']!='box' for p in spec['roi_pairs']):
        tools['available_tools']=[t for t in tools['available_tools'] if t!='ROI_COMPARE']
    cfg=dict(profile_id=PROFILE_MAP[spec['arm_id']],max_generations=1,assume_srgb=spec['assume_srgb'],reference_usable='usable',
             geometry_policy={'mode':'strict'},reference_v2=spec,roi_manifest=legacy_rois,
             reference_limitations=['Same scene within seconds; B appearance only, never pixel GT.'],
             tool_profile=tools)
    case_manifest=deepcopy(manifest or {});case_manifest['simulation_only']=spec['simulation_only']
    return create_case(prediction,reference,case_manifest,cfg,root)


def capture_g1_prompt(root):
    from .prompts import build_context,render_stage
    root=Path(root);state=CaseStore(root).load();config=read_json(root/'config.json');spec=config.get('reference_v2',{})
    require(spec.get('arm_id')=='G1','paired_g1_mismatch','Only a v2 G1 source qualifies')
    tasks=[]
    for tx_path in sorted((root/'transactions').glob('*.json')):
        tx=read_json(tx_path);issued=tx.get('next_task')
        if issued:
            request=read_json(safe_path(root,issued['request_path'],must_exist=True))
            if request['stage']=='execute':tasks.append((request,issued))
    require(len(tasks)==1,'paired_g1_mismatch','Require one committed G1 execute task, before or after generation')
    request,issued=tasks[0];rendered=json.loads(render_stage('execute',build_context(root,request),case_root=root))['edit_prompt']
    target=read_json(safe_path(root,f'tasks/{request["payload"]["prompt_source_task_id"]}/reference_targets_v2.json',must_exist=True))
    return dict(schema_version='paired_g1_prompt_v2',executor=deepcopy(spec['executor']),source_assets=deepcopy(spec['source_assets']),
                task_scope=spec['task_scope'],roi_pairs=deepcopy(spec['roi_pairs']),eval_mask=deepcopy(spec['eval_mask']),simulation_only=spec['simulation_only'],
                mask_roi_policy=deepcopy(spec.get('mask_roi_policy')),
                source_config_sha256=state['config_sha256'],source_request_sha256=request['request_sha256'],
                edit_prompt=request['payload']['edit_prompt'],edit_prompt_sha256=sha256_bytes(request['payload']['edit_prompt'].encode()),
                rendered_prompt=rendered,prompt_sha256=sha256_bytes(rendered.encode()),
                all_targets_local=all(t['scope']=='local' for t in target['targets']),
                target_roi_ids=sorted({rid for t in target['targets'] for rid in t['roi_pair_ids']}))


def paired_prompt(root,config):
    spec=config['reference_v2'];require(spec['arm_id']=='G2','paired_g1_mismatch','Not G2')
    validate_mask_probe(root,spec['mask_probe'],spec['executor'],allow_fixture=spec['simulation_only'])
    return spec['paired_g1']['edit_prompt']


def reference_targets(root,diagnosis,composition,inputs):
    gaps={g['gap_id']:g for kind in ('global_gaps','local_gaps') for g in diagnosis[kind]}
    frozen={p['roi_pair_id']:p for p in read_json(Path(root)/'config.json')['reference_v2']['roi_pairs']}
    observations={(o['scope'],o['roi_pair_id']):o for o in diagnosis['comparability']}
    require(1<=len(composition['edit_targets'])<=3,'unsupported_target','v2 requires 1 to 3 supported priorities')
    targets=[]
    for target in composition['edit_targets']:
        refs=target['source_gap_ids'];require(refs and all(g in gaps for g in refs),'unsupported_target','Missing diagnosed target support')
        gap=gaps[refs[0]];ids=sorted({gaps[g]['roi_pair_id'] for g in refs if gaps[g].get('roi_pair_id') is not None})
        scopes={('roi_pair',gaps[g]['roi_pair_id']) if gaps[g].get('roi_pair_id') is not None else ('global',None) for g in refs}
        observed=[deepcopy(observations[k]) for k in sorted(scopes) if k in observations]
        annotated=[{k:deepcopy(frozen[rid][k]) for k in ('roi_pair_id','comparability','reasons')} for rid in ids if rid in frozen]
        statuses=[observations.get(k,{}).get('status','unknown') for k in scopes]+[frozen.get(rid,{}).get('comparability','unknown') for rid in ids]
        effective=next((status for status in ('not_comparable','absent','unreliable','unknown','partly_comparable') if status in statuses),'comparable')
        targets.append(dict(target_id='t'+str(target['priority']),scope='local' if target['scope']=='region' else 'global',
                            dimension=gap['dimension'],roi_pair_id=gap.get('roi_pair_id'),roi_pair_ids=ids,direction=target['operation'],
                            confidence_kind='observational',comparability=effective,
                            comparability_sources={'diagnosis':observed,'frozen_roi':annotated},observed_support=gap['observation'],source_gap_ids=refs))
    return dict(version='reference_targets_v2',source_assets={a['role']:a['pixel_sha256'] for a in inputs},
                targets=targets,preservation_anchor='A',unsupported_targets=[])
