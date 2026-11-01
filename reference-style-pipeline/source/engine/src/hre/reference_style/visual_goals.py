"""Explicit operator-selected style excerpts, not automatic narrative execution.

Semantic review remains necessary: hash/quote binding proves source, not that a
sentence is a good edit. Private verification policy is never consulted here.
"""
from copy import deepcopy
from hre.models import sha256_bytes
from .contracts import exact,require,digest
from .s2_evidence import code

STRENGTHS=('strong','moderate','gentle','preserve','relative')
BASE_KEYS=('instruction','strength','relation')
BOUND_KEYS=(*BASE_KEYS,'instruction_hash','diagnosis_hash','selection_basis')

def validate_goal(goal,regions,diagnosis_hash):
    exact(goal,BOUND_KEYS)
    text=goal['instruction']
    require(isinstance(text,str) and 0<len(text.strip())<=2000,'bounded selected style excerpt required')
    require(goal['strength'] is None or goal['strength'] in STRENGTHS,'invalid qualitative strength')
    digest(goal['instruction_hash']);digest(goal['diagnosis_hash'])
    require(goal['instruction_hash']==sha256_bytes(text.encode('utf-8')) and goal['diagnosis_hash']==diagnosis_hash,
            'visual goal source/hash mismatch')
    require(goal['selection_basis']=='explicit_operator_selected_AB_style_excerpt','not an explicit operator style selection')
    rel=goal['relation']
    if rel is not None:
        exact(rel,('relation_id','left_region_id','right_region_id'));code(rel['relation_id'],'l')
        left,right=rel['left_region_id'],rel['right_region_id'];code(left,'r');code(right,'r')
        require(left in regions and right in regions and left!=right,'visual relation needs distinct frozen regions')
    return goal

def bind_goal(spec,regions,diagnosis,diagnosis_text):
    exact(spec,BASE_KEYS)
    require(isinstance(spec['instruction'],str) and spec['instruction'] in diagnosis_text,
            'style instruction must be an exact excerpt from the bound AB diagnosis')
    goal=dict(**deepcopy(spec),instruction_hash=sha256_bytes(spec['instruction'].encode('utf-8')),
              diagnosis_hash=diagnosis['content_hash'],selection_basis='explicit_operator_selected_AB_style_excerpt')
    return validate_goal(goal,regions,diagnosis['content_hash'])

def goal_regions(goal,subject):
    rel=goal['relation']
    return [subject] if rel is None else [rel['left_region_id'],rel['right_region_id']]


def faithful_mapping(spec, *, strength_basis):
    """Drop caller-known mapping-added labels from excerpt-backed goals only.

    This does not infer strength provenance. Separately supported structured
    diagnosis strengths are outside this conversion. Original prose is untouched.
    The normal freeze path still verifies every selected quote against diagnosis.
    """
    require(strength_basis=='mapping_added_labels','only caller-known mapping-added labels can be stripped')
    require(isinstance(spec,dict) and isinstance(spec.get('targets'),list),'target mapping required')
    result=deepcopy(spec);found=False
    for target in result['targets']:
        if 'visual_goal' not in target:continue
        goal=target['visual_goal'];exact(goal,BASE_KEYS)
        require(target.get('measurement_id') is None and target.get('judge_type')=='visual','excerpt-backed visual mapping required')
        require(isinstance(goal['instruction'],str) and bool(goal['instruction'].strip()),'selected diagnosis excerpt required')
        require(goal['strength'] is None or goal['strength'] in STRENGTHS,'unsupported strength representation')
        goal['strength']=None;found=True
    require(found,'at least one excerpt-backed goal required')
    return result
