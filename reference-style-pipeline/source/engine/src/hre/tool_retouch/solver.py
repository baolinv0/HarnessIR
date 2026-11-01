"""Bounded deterministic coordinate descent with identity and rejected-candidate ledger."""
from dataclasses import dataclass,field
import time
import numpy as np
from .color import require,digest_bytes,resolve_domain
from .contracts import canonical
from .evidence import array_hash
from .planner import identity,coordinates,instantiate,validate_plan,CONTROLLER_PROTOCOL,NUMERIC_WARM_START_PROTOCOL
from .verifier import hard_checks,target_results,objective

class BudgetExhausted(RuntimeError):pass
@dataclass
class Budget:
    limits: dict
    used: dict=field(default_factory=lambda:dict(preview=0,native=0,replay=0,vlm=0,outer=0))
    def take(self,kind):
        if self.used[kind]>=self.limits[kind]:raise BudgetExhausted(kind+' budget exhausted')
        self.used[kind]+=1

def authorized(plan,masks,shape):
    if any(op['mask_id'] is None for op in plan['operations']):return np.ones(shape,bool)
    result=np.zeros(shape,bool)
    for op in plan['operations']:result|=masks[op['mask_id']]>0
    return result

@dataclass
class Candidate:
    values: tuple
    image: np.ndarray
    loss: float
    magnitude: float
    rows: list
    hard: dict
    key: str
    optimization_results: list=field(default_factory=list)
    acceptance_loss: float|None=None

def optimization_report(rows,contract):
    """Separate search preference; never mutate acceptance rows or frozen targets."""
    data=contract.data;targets={t['id']:t for t in data['targets']}
    v3=data['policy'].get('controller_protocol')==CONTROLLER_PROTOCOL;report=[]
    for row in rows:
        t=targets[row['id']];lo=t.get('lower');hi=t.get('upper');margin=0.;residual=row['residual']
        if v3 and t['mandatory'] and t['kind']=='interval':
            margin=data['policy']['optimization_margin_fraction']*t['scale'];lo+=margin;hi-=margin
            require(lo<=hi,'optimization interval margin invalid')
            if row['value'] is not None:residual=max(0.,lo-row['value'],row['value']-hi)/t['scale']
        report.append({'id':row['id'],'value':row['value'],'acceptance_residual':row['residual'],
                       'optimization_residual':residual,'optimization_lower':lo,'optimization_upper':hi,'optimization_margin':margin})
    return report

def optimization_loss(rows,contract,report):
    return objective([dict(row,residual=info['optimization_residual']) for row,info in zip(rows,report)],contract)

def solve(source,plan,contract,supports,masks,backend,budget,cache=None,domain=None):
    frozen_domain=resolve_domain(contract.data.get('source',{}).get('domain'));domain=frozen_domain if domain is None else resolve_domain(domain)
    require(domain.identity==frozen_domain.identity,'solver domain differs from frozen contract')
    if hasattr(backend,'domain'):require(resolve_domain(backend.domain).identity==domain.identity,'solver backend color domain mismatch')
    elif domain.id!='srgb':raise ValueError('P3 solver requires explicit backend domain')
    cache={} if cache is None else cache;policy=contract.data['policy'];coords=coordinates(plan);start=identity(plan)
    v3=policy.get('controller_protocol')==CONTROLLER_PROTOCOL
    if v3 or 'numeric_warm_start' in plan:validate_plan(plan,contract.data,masks)
    warm_start=plan.get('numeric_warm_start',False);seed_values=None;seed_key=None
    visual_fixed={i:spec['suggested'] for i,(_,_,spec,_) in enumerate(coords) if v3 and spec.get('mode','numeric_fit')=='visual_proposal'}
    allowed=authorized(plan,masks,source.shape[:2]);ledger=[];count=0
    binding=dict(source=array_hash(source),contract=contract.sha256,plan=plan,masks={k:array_hash(v) for k,v in masks.items()},supports={k:array_hash(v) for k,v in supports.items()},backend=backend.identity,color_domain=domain.identity)
    def evaluate(values):
        nonlocal count
        instantiate(plan,values)
        key=digest_bytes(canonical({**binding,'values':values}).encode())
        if key in cache:return cache[key]
        if count>=policy['per_round_preview']:raise BudgetExhausted('round preview budget exhausted')
        budget.take('preview');count+=1;t=time.monotonic()
        try:
            output=backend.render_from_source(source.copy(),plan,values,{k:v.copy() for k,v in masks.items()})
            hard=hard_checks(source,output,policy,allowed)
            rows=target_results(output,contract,supports,domain=domain) if hard['pass'] else []
            mag=sum(((v-neutral)/(spec['upper']-spec['lower']))**2 for j,((_,_,spec,neutral),v) in enumerate(zip(coords,values)) if j not in visual_fixed)
            report=optimization_report(rows,contract) if hard['pass'] else []
            acceptance=objective(rows,contract) if hard['pass'] else float('inf')
            loss=optimization_loss(rows,contract,report)+policy['regularization']*mag if hard['pass'] else float('inf')
            c=Candidate(tuple(values),output,loss,mag,rows,hard,key,report,acceptance)
        except (ValueError,RuntimeError) as exc:
            # Invalid candidate pixels are a reject; transport/subprocess failures escape and stop execution.
            c=Candidate(tuple(values),source.copy(),float('inf'),float('inf'),[],{'pass':False,'reasons':[str(exc)]},key)
        cache[key]=c;ledger.append({'key':key,'values':list(values),'loss':c.loss if np.isfinite(c.loss) else None,'hard':c.hard,'seconds':time.monotonic()-t,**({'optimization_results':c.optimization_results,'acceptance_loss':c.acceptance_loss if c.acceptance_loss is not None and np.isfinite(c.acceptance_loss) else None,'numeric_regularization_magnitude':c.magnitude if np.isfinite(c.magnitude) else None} if v3 else {})})
        return c
    baseline_rows=target_results(source,contract,supports,domain=domain)
    baseline_report=optimization_report(baseline_rows,contract)
    baseline=Candidate(start,source.copy(),optimization_loss(baseline_rows,contract,baseline_report),0.,baseline_rows,{'pass':True,'reasons':[]},'original_A',baseline_report,objective(baseline_rows,contract))
    best=baseline;ranked=[baseline];stop='minimum_steps'
    steps=[0. if i in visual_fixed else max((c[2]['upper']-c[2]['lower'])/4,c[2]['min_step']) for i,c in enumerate(coords)]
    try:
        neutral=evaluate(start)
        require(neutral.hard['pass'] and np.max(abs(neutral.image-source))<=policy['identity_tolerance'],'backend identity mismatch')
        if visual_fixed or warm_start:
            seed=list(start)
            if warm_start:
                for index,(_,_,spec,_) in enumerate(coords):seed[index]=spec['suggested']
            for index,value in visual_fixed.items():seed[index]=value
            seed_values=tuple(seed)
            best=evaluate(seed_values);seed_key=best.key
            if best.hard['pass']:ranked.append(best)
        while any(s>=c[2]['min_step'] for s,c in zip(steps,coords)):
            changed=False
            for j,(_,_,spec,_) in enumerate(coords):
                if steps[j]<spec['min_step']:continue
                center=best.values
                for sign in (1,-1):
                    values=list(center);values[j]=min(spec['upper'],max(spec['lower'],center[j]+sign*steps[j]))
                    if values[j]==center[j]:continue
                    candidate=evaluate(tuple(values))
                    if candidate.hard['pass']:
                        ranked.append(candidate)
                        better=candidate.loss<best.loss-policy['improvement_epsilon']
                        tied=abs(candidate.loss-best.loss)<=policy['improvement_epsilon'] and candidate.magnitude<best.magnitude
                        if better or tied:best=candidate;changed=True
            if not changed:steps=[s/2 for s in steps]
    except BudgetExhausted as exc:stop=str(exc)
    ranked=sorted({c.key:c for c in ranked}.values(),key=lambda c:(c.loss,c.magnitude,c.key))
    trace={'stop':stop,'preview_renders':count,'candidates':ledger,'baseline_loss':baseline.loss,'color_domain':domain.identity}
    if v3:trace.update(controller_protocol=CONTROLLER_PROTOCOL,optimization_margin_fraction=policy['optimization_margin_fraction'],baseline_acceptance_loss=baseline.acceptance_loss,baseline_optimization_results=baseline_report,visual_proposal_coordinate_indices=sorted(visual_fixed),visual_proposal_values=[visual_fixed[i] for i in sorted(visual_fixed)],objective_note='Search loss is numerical optimization residual plus numeric-fit regularization, never a perceptual quality score. Acceptance residuals and frozen contract remain unchanged.')
    if warm_start:trace['numeric_warm_start']={'protocol':NUMERIC_WARM_START_PROTOCOL,'seed_values':list(seed_values) if seed_values is not None else None,'seed_key':seed_key,'seed_evaluated':seed_key is not None,'budget_rule':'Uses the unchanged per-round and total preview budget; cache hits are not additional renders.'}
    return best,ranked,trace
