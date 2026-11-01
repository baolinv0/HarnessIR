"""Actual ABC dialogue transport and closed factual projection, never policy."""
from copy import deepcopy
import math
from jsonschema import Draft202012Validator
from hre.models import canonical_json
from hre.storage import case_lock
from .contracts import exact,require,identifier,PRESERVATION
from .s2_evidence import code
from .s4_targets import target_view
from .s4_selected import require_selected
from .s2_public import _MEASUREMENT,_object,_enum,_array,_nullable,_NUM,diagnostic_view
from . import coordinator as co,s2_store as store,s3_handoff as handoff

DIMENSIONS=('identity','layout','geometry','texture','ocr','naturalness')
STATUS=('achieved','partial','unmet','uncertain')
CONFIDENCE=('high','medium','low','unknown')
SEVERITY=('none_observed','minor_local_incidental','major','unknown')
RESIDUAL=('none_observed','too_bright','too_dark','too_warm','too_cool','too_saturated','too_muted','tone_residual','relationship_residual','uncertain')
_ABC=deepcopy(_MEASUREMENT)
for schema in _ABC['oneOf']:
    extra={k:_nullable(_NUM) for k in ('C','C_minus_B','C_minus_A','baseline_absolute_residual','candidate_absolute_residual','absolute_improvement')}
    extra.update(C_operands=_nullable(_object({'left':_nullable(_NUM),'right':_nullable(_NUM)})),numeric_achievement=_enum('uncalibrated'))
    schema['properties'].update(extra);schema['required']+=list(extra)
_NUMBERS=Draft202012Validator(_array(_ABC))


def _number_view(rows):
    require(next(_NUMBERS.iter_errors(rows),None) is None,'invalid typed ABC numeric observations')
    def finite(x):
        if isinstance(x,dict):
            for v in x.values():finite(v)
        elif isinstance(x,list):
            for v in x:finite(v)
        elif type(x)is float:require(math.isfinite(x),'nonfinite ABC observations')
    finite(rows);return deepcopy(rows)


def export_abc(root,evaluation_id,view):
    code(evaluation_id,'j');require(view in ('image_first','evidence'),'unsupported ABC review view')
    with case_lock(root):
        state=co._status(root);evaluation=store.get(root,state,'evaluations',evaluation_id);e=evaluation['payload']
        require(state['payload']['active_attempt'] is None,'pending/unknown attempt must resolve')
        for attempt in state['payload']['attempts']:
            old=co._load(root,attempt['request_path'],'request')['payload']
            require(not (old.get('evaluation_id')==evaluation_id and old.get('review_view')==view),'review view already reserved; correction requires explicit reevaluation, not ask-until-pass')
        derived=require_selected(root,state,evaluation);require(derived['content_hash']==e['derived_hash'] and derived['payload']['audit'] is not None,'usable bound C display derivative required')
        c=derived['payload']['audit'];audit=co._load(root,'input_audit.json');report=store.get(root,state,'reports',e['report_id']);require(report['content_hash']==e['report_hash'],'ABC report binding mismatch')
        target=store.get(root,state,'targets',e['evaluation_target_version']);require(target['content_hash']==e['evaluation_target_hash'],'ABC target binding mismatch')
        context=dict(target_version=e['evaluation_target_version'],target_hash=e['evaluation_target_hash'],evaluation_id=evaluation_id,
            candidate_hash=e['raw_candidate_hash'],preservation_requirements=PRESERVATION,
            targets=target_view(target,report,include_numbers=view=='evidence'),candidate_measurement_basis=e['candidate_measurement_basis'],
            selected_C_artifact={k:e['selected_artifact'][k] for k in ('file_hash','pixel_hash','encoding','bit_depth','numeric_status')})
        prompt=('Inspect original A, style reference B and observed candidate C. Record whole-frame tone, color and brightness relative to B, '
                'each applicable whole-object/material goal, spillover, and content/spatial/naturalness deviations relative to A. '
                'Keep uncertainty explicit. These are factual observations, not an acceptance verdict. '+PRESERVATION)
        aids=[]
        if view=='evidence':
            public=diagnostic_view(report['payload']);context['measurements']=_number_view(e['measurements'])
            context['regions']=public['regions'];context['text_protection']=public['text_protection']
            if e['support_id'] is not None:
                support=store.get(root,state,'candidate_supports',e['support_id']);require(support['content_hash']==e['support_hash'],'ABC C support changed')
                context['C_supports']=[{k:r[k] for k in ('region_id','semantic_class','mode','coverage_pixels','coverage_denominator','coverage_fraction','bbox','eligibility','correspondence','coverage','occlusion')}
                    for r in support['payload']['regions'].values()]
                for rid,r in support['payload']['regions'].items():
                    if r['support_path'] is not None:public['regions'][rid]['support_paths']['C']=r['support_path'];public['regions'][rid]['coverage']['C']={'bbox':r['bbox']}
            aids=handoff._aids(root,evaluation,target,{'payload':{'images':audit['payload']['images']+[c]}},public,roles=('A','B','C'))
            context['localization_guides']={role:'provided' if any(a['role']==role for a in aids) else 'unavailable_no_nonempty_selected_support' for role in ('A','B','C')}
            prompt+='\nCompare the numeric evidence only where support/color are eligible; C numbers describe the exact selected C artifact, A/B retain frozen source-reference measurements. No calibrated numeric achievement is implied. Guides are localization only, not hard masks.\n'+canonical_json(context).decode('utf-8')
        else:prompt+='\nImage-first review: use these original goal identities, without measured results or private acceptance rules. Do not infer results from method names, previous verdicts or unavailable numeric evidence.\n'+canonical_json(context).decode('utf-8')
        return co._export_prepared(root,state,audit,context,'abc_diagnosis',prompt=prompt,bind_targets=False,
            prompt_version='s4_ABC_'+view+'_selected_goals_v2',attachment_aids=aids,candidate_image=c,
            extra=dict(binding_kind='abc_evaluation',evaluation_id=evaluation_id,evaluation_hash=evaluation['content_hash'],review_view=view))


def _diagnosis(root,state,response_id,evaluation,view):
    matches=[co._load(root,r['record_path'],'response') for r in state['payload']['results']]
    matches=[r for r in matches if r['record_id']==response_id];require(len(matches)==1,'actual imported ABC diagnosis required')
    result=matches[0];binding=result['payload'].get('diagnostic_binding')
    require(result['payload']['stage_id']=='abc_diagnosis' and binding is not None and binding['evaluation_id']==evaluation['payload']['evaluation_id']
            and binding['evaluation_hash']==evaluation['content_hash'] and binding['review_view']==view,'ABC diagnosis candidate/evaluation/view mismatch')
    return result


def freeze_facts(root,spec):
    exact(spec,('facts_id','evaluation_id','evidence_response_id','image_first_response_id','reviewer','overall_style','targets','content_spatial','spillover'))
    code(spec['facts_id'],'f');code(spec['evaluation_id'],'j');exact(spec['reviewer'],('reviewer_id','independence'));identifier(spec['reviewer']['reviewer_id'])
    require(spec['reviewer']['independence'] in ('independent','same_model','unknown'),'review independence must be explicit')
    exact(spec['overall_style'],('tone','color','brightness'));exact(spec['content_spatial'],DIMENSIONS)
    for value in spec['overall_style'].values():
        exact(value,('status','confidence'));require(value['status'] in STATUS and value['confidence'] in CONFIDENCE,'invalid overall factual status')
    for value in spec['content_spatial'].values():
        exact(value,('severity','confidence'));require(value['severity'] in SEVERITY and value['confidence'] in CONFIDENCE,'invalid content/spatial fact')
    require(isinstance(spec['targets'],list) and isinstance(spec['spillover'],list),'factual lists required')
    for t in spec['targets']:
        exact(t,('target_id','status','confidence','residual_code'));code(t['target_id'],'t')
        require(t['status'] in STATUS and t['confidence'] in CONFIDENCE and t['residual_code'] in RESIDUAL,'invalid typed target observation')
    for s in spec['spillover']:
        exact(s,('region_id','dimension','severity','confidence'))
        if s['region_id']!='g0':code(s['region_id'],'r')
        require(s['dimension'] in ('tone','color','brightness','contrast','chroma','warmth') and s['severity'] in SEVERITY and s['confidence'] in CONFIDENCE,'invalid typed spillover')
    with case_lock(root):
        state=co._status(root);require(state['payload']['active_attempt'] is None,'complete factual review import first')
        require(spec['facts_id'] not in store.registry(state)['facts'],'facts immutable')
        for key in store.registry(state)['facts']:require(store.get(root,state,'facts',key)['payload']['evaluation_id']!=spec['evaluation_id'],'facts already frozen; explicit reevaluation needed')
        evaluation=store.get(root,state,'evaluations',spec['evaluation_id']);e=evaluation['payload'];evidence=_diagnosis(root,state,spec['evidence_response_id'],evaluation,'evidence')
        first=None if spec['image_first_response_id'] is None else _diagnosis(root,state,spec['image_first_response_id'],evaluation,'image_first')
        if first is not None:
            order=[a['attempt_id'] for a in state['payload']['attempts']]
            require(order.index(first['payload']['attempt_id'])<order.index(evidence['payload']['attempt_id']),'independent image-first review must precede evidence view')
        target=store.get(root,state,'targets',e['evaluation_target_version']);expected=[t['target_id'] for t in target['payload']['targets']]
        require([t['target_id'] for t in spec['targets']]==expected,'all applicable target facts required in frozen order; no posthoc not-applicable escape')
        regions=store.get(root,state,'reports',e['report_id'])['payload']['regions'];require(all(s['region_id'] in regions for s in spec['spillover']),'unknown spillover region')
        return store.put(root,state,'facts',spec['facts_id'],'ABC_facts',dict(**deepcopy(spec),evaluation_hash=evaluation['content_hash'],
            evidence_response_hash=evidence['content_hash'],image_first_response_hash=None if first is None else first['content_hash'],
            review_order='image_first_then_evidence' if first is not None else 'evidence_only',assets=[],semantic_truth='caller_attested_projection_of_archived_review'))
