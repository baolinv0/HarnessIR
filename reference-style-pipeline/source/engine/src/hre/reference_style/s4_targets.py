"""Closed factual ABC goals. No archival revision prose or private acceptance data."""
from copy import deepcopy
from jsonschema import Draft202012Validator
from .contracts import exact,require
from .s2_evidence import SEMANTICS,METRICS,STATS
from .s2_public import _object,_enum,_array,_nullable,_pattern,_MEASUREMENT,diagnostic_view
from .visual_goals import validate_goal,STRENGTHS

_VISUAL=('tone','color','brightness','contrast','chroma','warmth')
_RID=_pattern(r'^r[1-9][0-9]{0,5}$')
_GOAL=_object({'instruction':{'type':'string','minLength':1,'maxLength':2000},'strength':_nullable(_enum(*STRENGTHS)),
    'relation':_nullable(_object({'relation_id':_pattern(r'^l[1-9][0-9]{0,5}$'),'left_region_id':_RID,'right_region_id':_RID})),
    'instruction_hash':_pattern(r'^[0-9a-f]{64}$'),'diagnosis_hash':_pattern(r'^[0-9a-f]{64}$'),
    'selection_basis':_enum('explicit_operator_selected_AB_style_excerpt')})
_SCHEMA=_object({'target_id':_pattern(r'^t[1-9][0-9]{0,5}$'),
    'subject_id':_pattern(r'^(g0|[rl][1-9][0-9]{0,5})$'),'semantic_class':_enum('global','relation',*SEMANTICS),
    'dimension':_enum(*METRICS,*_VISUAL),'direction':_enum('match_B','increase_toward_B','decrease_toward_B'),
    'judge_type':_enum('numeric','mixed','visual'),'priority':_enum('critical','secondary'),
    'measurement_id':_nullable(_pattern(r'^m[1-9][0-9]{0,5}$')),'metric':_nullable(_enum(*METRICS)),
    'statistic':_nullable(_enum(*STATS)),'left_region_id':_nullable(_RID),'right_region_id':_nullable(_RID),
    'left_semantic_class':_nullable(_enum(*SEMANTICS)),'right_semantic_class':_nullable(_enum(*SEMANTICS)),
    'reference_measurement':_nullable(_MEASUREMENT),'visual_goal':_nullable(_GOAL)})
_VALIDATOR=Draft202012Validator(_array(_SCHEMA))


def target_view(target,report,include_numbers):
    public=diagnostic_view(report['payload']);rows={m['measurement_id']:m for m in public['measurements']};regions=public['regions'];result=[]
    for t in target['payload']['targets']:
        exact(t,('target_id','subject_id','semantic_class','dimension','direction','judge_type','priority','measurement_binding',
                 'diagnosis_record_id','tolerance','support_snapshot_hash','evidence_eligibility')+(('visual_goal',) if 'visual_goal' in t else ()))
        require(t['tolerance'] is None and t['support_snapshot_hash']==public['snapshot_hash'],'style goal cannot carry private threshold or foreign support')
        p={k:deepcopy(t[k]) for k in ('target_id','subject_id','semantic_class','dimension','direction','judge_type','priority')}
        m=t['measurement_binding'];p.update(measurement_id=None,metric=None,statistic=None,left_region_id=None,right_region_id=None,
            left_semantic_class=None,right_semantic_class=None,reference_measurement=None,visual_goal=None)
        goal=t.get('visual_goal')
        if goal is not None:
            validate_goal(goal,regions,target['payload']['diagnosis_hash'])
            require(m is None and t['judge_type']=='visual','semantic instruction cannot masquerade as numeric goal')
            p['visual_goal']=deepcopy(goal)
        if m is not None:
            require(isinstance(m,dict) and m.get('measurement_id') in rows and m==rows[m['measurement_id']],'goal measurement must equal frozen typed AB row')
            direction='increase_toward_B' if m['delta_B_minus_A']>0 else 'decrease_toward_B' if m['delta_B_minus_A']<0 else 'match_B'
            require(t['subject_id']==m['subject_id'] and t['dimension']==m['metric'] and t['direction']==direction
                    and t['judge_type'] in ('numeric','mixed'),'goal meaning differs from frozen measured reference')
            p.update(measurement_id=m['measurement_id'],metric=m['metric'],statistic=m['statistic'],reference_measurement=deepcopy(m) if include_numbers else None)
            if m['kind']=='relation':
                p.update(left_region_id=m['left_region_id'],right_region_id=m['right_region_id'],
                    left_semantic_class=regions[m['left_region_id']]['semantic_class'],right_semantic_class=regions[m['right_region_id']]['semantic_class'])
        else:
            relation=None if goal is None else goal['relation']
            require(t['judge_type']=='visual' and t['dimension'] in _VISUAL and
                    (t['subject_id'] in regions if relation is None else t['subject_id']==relation['relation_id']),'invalid visual goal meaning')
            if relation is not None:
                left,right=relation['left_region_id'],relation['right_region_id']
                p.update(left_region_id=left,right_region_id=right,left_semantic_class=regions[left]['semantic_class'],right_semantic_class=regions[right]['semantic_class'])
        semantic=regions[t['subject_id']]['semantic_class'] if t['subject_id'] in regions else 'relation'
        require(t['semantic_class']==semantic,'goal semantic label must be frozen typed subject')
        result.append(p)
    require(next(_VALIDATOR.iter_errors(result),None) is None,'invalid closed ABC goal projection')
    return result
