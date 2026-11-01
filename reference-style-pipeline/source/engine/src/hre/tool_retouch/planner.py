"""Finite operation grammar: VLM cannot name paths, commands, budgets or target values."""
from copy import deepcopy
from .color import require
from .contracts import strict,number
from .evidence import MATERIAL_REGION_PROTOCOL

# Development balance100-v6: extended capability range, not calibrated aesthetic claims.
# Upstream ColorBalance formula is unchanged; old runs retain their original registry/binary.
CONTROLLER_PROTOCOL='portrait_controller_v3'
MATERIAL_CONTROLLER_PROTOCOL='material_controller_v4'
NUMERIC_WARM_START_PROTOCOL='numeric_warm_start_v1'

TOOLS={
    'exposure':{'ev':(-1.,1.,0.,.015625)},
    'gamma':{'gamma':(.67,2.,1.,.01)},
    'brightness_contrast':{'brightness':(-30.,30.,0.,.5),'contrast':(-30.,30.,0.,.5)},
    'curve':{'mid':(96.,160.,128.,.5)},
    'balance':{'red':(-100.,100.,0.,.15625),'blue':(-100.,100.,0.,.15625)},
    'saturation':{'amount':(-20.,20.,0.,.3125)},
}

def validate_plan(plan,contract,masks):
    strict(plan,{'operations','reason','feedback_ids'} | ({'numeric_warm_start'} if 'numeric_warm_start' in plan else set()))
    if 'numeric_warm_start' in plan:require(type(plan['numeric_warm_start']) is bool,'numeric warm-start must be a strict boolean')
    require(isinstance(plan['reason'],str) and plan['reason'].strip(),'planning reason')
    require(isinstance(plan['feedback_ids'],list) and all(isinstance(x,str) for x in plan['feedback_ids']),'feedback IDs')
    ops=plan['operations'];require(isinstance(ops,list) and len(ops)<=6,'operation cap')
    targets={t['id'] for t in contract['targets']};target_kinds={t['id']:t.get('kind') for t in contract['targets']}
    policy=contract.get('policy',{});v3=policy.get('controller_protocol')==CONTROLLER_PROTOCOL
    material_v4=policy.get('material_controller_protocol')==MATERIAL_CONTROLLER_PROTOCOL
    if 'numeric_warm_start' in plan:require(v3,'numeric warm-start requires the explicit v3 controller')
    if 'material_controller_protocol' in policy:require(material_v4 and v3 and policy.get('material_region_protocol')==MATERIAL_REGION_PROTOCOL,'material controller requires exact material region and v3 protocols')
    seen=set();local=global_=dof=0
    for op in ops:
        strict(op,{'id','tool','target_ids','mask_id','parameters','expected_effect','protect_target_ids'})
        require(isinstance(op['id'],str) and op['id'] and op['id'] not in seen,'operation identity');seen.add(op['id'])
        require(op['tool'] in TOOLS,'unsupported tool')
        require(isinstance(op['target_ids'],list) and op['target_ids'] and set(op['target_ids'])<=targets,'unknown target IDs')
        require(isinstance(op['protect_target_ids'],list) and set(op['protect_target_ids'])<=targets,'unknown protected target')
        require(isinstance(op['expected_effect'],str) and op['expected_effect'].strip(),'expected effect required')
        if op['mask_id'] is None:global_+=1
        else:
            require(isinstance(op['mask_id'],str) and op['mask_id'] in masks,'unknown edit mask');local+=1
        strict(op['parameters'],TOOLS[op['tool']])
        for name,spec in op['parameters'].items():
            strict(spec,{'lower','upper','suggested','min_step'} | ({'mode'} if v3 and 'mode' in spec else set()))
            mode=spec.get('mode','numeric_fit')
            require(mode in ('numeric_fit','visual_proposal'),'invalid parameter mode')
            if mode=='visual_proposal':require(v3 and all(target_kinds[t] in ('perceptual','protection') for t in op['target_ids']),'visual proposal requires only perceptual/protection targets')
            lo,hi,identity,min_step=TOOLS[op['tool']][name]
            require(all(number(spec[k]) for k in ('lower','upper','suggested','min_step')),'nonfinite parameter')
            require(lo<=spec['lower']<=identity<=spec['upper']<=hi and spec['lower']<spec['upper'],'unsafe bounds / identity excluded')
            require(spec['lower']<=spec['suggested']<=spec['upper'] and min_step<=spec['min_step']<=spec['upper']-spec['lower'],'invalid step/suggestion')
            dof+=1
    require(local<=(6 if material_v4 else 4 if v3 else 3) and global_<=3 and dof<=12,'plan complexity limit')
    return deepcopy(plan)

def coordinates(plan):
    return [(i,k,spec,TOOLS[op['tool']][k][2]) for i,op in enumerate(plan['operations']) for k,spec in sorted(op['parameters'].items())]

def identity(plan):return tuple(c[3] for c in coordinates(plan))

def instantiate(plan,values):
    coords=coordinates(plan);require(len(values)==len(coords),'parameter length')
    ops=[dict(tool=x['tool'],mask_id=x['mask_id'],values={}) for x in plan['operations']]
    for (i,k,spec,_),v in zip(coords,values):
        require(number(v) and spec['lower']<=v<=spec['upper'],'parameter outside requested bounds')
        ops[i]['values'][k]=v
    return ops
