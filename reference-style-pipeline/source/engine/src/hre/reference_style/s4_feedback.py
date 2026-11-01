"""Closed factual residual feedback. No verifier/policy/accepted-history imports."""
from copy import deepcopy
from hre.models import canonical_json,sha256_bytes
from hre.storage import case_lock
from .contracts import exact,require,PRESERVATION
from .s2_evidence import code
from .s4_selected import require_selected
from . import coordinator as co,s2_store as store,s4_budget as budget


def freeze_feedback(root,spec):
    exact(spec,('feedback_id','evaluation_id','facts_id','current_target_version','target_ids','include_global_residuals'))
    code(spec['feedback_id'],'fb');code(spec['evaluation_id'],'j');code(spec['facts_id'],'f');code(spec['current_target_version'],'v')
    require(isinstance(spec['target_ids'],list) and type(spec['include_global_residuals'])is bool,'typed feedback selection required')
    for tid in spec['target_ids']:code(tid,'t')
    require(len(set(spec['target_ids']))==len(spec['target_ids']),'duplicate feedback target')
    with case_lock(root):
        state=co._status(root);require(state['payload']['active_attempt'] is None,'resolve pending attempt before feedback')
        require(spec['feedback_id'] not in store.registry(state)['feedback'],'feedback identity frozen')
        evaluation=store.get(root,state,'evaluations',spec['evaluation_id']);e=evaluation['payload'];facts=store.get(root,state,'facts',spec['facts_id']);f=facts['payload']
        require_selected(root,state,evaluation)
        require(f['evaluation_id']==spec['evaluation_id'] and f['evaluation_hash']==evaluation['content_hash'],'feedback facts/evaluation mismatch')
        latest=max(store.registry(state)['targets'],key=lambda v:int(v[1:]))
        require(spec['current_target_version']==latest==e['evaluation_target_version'],'old candidate must be explicitly reevaluated against current targets before feedback')
        target=store.get(root,state,'targets',latest);require(target['content_hash']==e['evaluation_target_hash'],'feedback target binding mismatch')
        targets={t['target_id']:t for t in target['payload']['targets']};rows={m['measurement_id']:m for m in e['measurements']};observations={o['target_id']:o for o in f['targets']}
        require(set(spec['target_ids'])<=set(targets),'unknown feedback target');residuals=[]
        for tid in spec['target_ids']:
            t=targets[tid];m=None if t['measurement_binding'] is None else rows[t['measurement_binding']['measurement_id']]
            direction='review_required';measurement=None
            if m is not None and m['eligibility']=='numeric_eligible' and m['C_minus_B'] is not None:
                direction='decrease_toward_B' if m['C_minus_B']>0 else 'increase_toward_B' if m['C_minus_B']<0 else 'match_B'
                measurement={k:m[k] for k in ('measurement_id','subject_id','kind','metric','statistic','A','B','C','C_minus_B','C_minus_A','absolute_improvement')}
                if m['kind']=='relation':measurement.update(left_region_id=m['left_region_id'],right_region_id=m['right_region_id'],C_operands=m['C_operands'])
            residuals.append(dict(target_id=tid,subject_id=t['subject_id'],dimension=t['dimension'],direction=direction,
                measured_residual=measurement,visual_residual_code=observations[tid]['residual_code'],visual_confidence=observations[tid]['confidence']))
        content=[dict(dimension=k,observation_code='restore_original_A_consistency' if v['severity']!='unknown' else 'consistency_uncertain_recheck_original_A',confidence=v['confidence'])
                 for k,v in f['content_spatial'].items() if v['severity']!='none_observed']
        global_residuals=[dict(dimension=k,observation_code='match_B_'+k,status=v['status'],confidence=v['confidence'])
                          for k,v in f['overall_style'].items() if spec['include_global_residuals'] and v['status']!='achieved']
        state=budget.reserve(root,state,'feedback_rounds',spec['feedback_id'])
        return store.put(root,state,'feedback',spec['feedback_id'],'execution_feedback',dict(
            feedback_id=spec['feedback_id'],evaluation_id=spec['evaluation_id'],evaluation_hash=evaluation['content_hash'],facts_id=spec['facts_id'],facts_hash=facts['content_hash'],
            candidate_record_id=e['candidate_record_id'],candidate_hash=e['raw_candidate_hash'],generation_target_hash=e['generation_target_hash'],
            current_target_version=latest,current_target_hash=target['content_hash'],residuals=residuals,global_residuals=global_residuals,content_restoration=content,
            spillover=deepcopy(f['spillover']),preservation_requirements=PRESERVATION,assets=[]))


def validate_binding(root,state,compiled):
    p=compiled['payload'];feedback=store.get(root,state,'feedback',p['feedback_id']);f=feedback['payload']
    require(feedback['content_hash']==p['feedback_hash'] and f['current_target_hash']==p['target_hash'] and f['current_target_version']==p['target_version'],'compiled feedback/current target mismatch')
    evaluation=store.get(root,state,'evaluations',f['evaluation_id']);facts=store.get(root,state,'facts',f['facts_id'])
    require_selected(root,state,evaluation)
    require(evaluation['content_hash']==f['evaluation_hash'] and facts['content_hash']==f['facts_hash'],'feedback source facts changed')
    return feedback


def compile_feedback(root,compiled_id,feedback_id):
    code(feedback_id,'fb')
    with case_lock(root):
        state=co._status(root);base=store.get(root,state,'compiled',compiled_id);p=deepcopy(base['payload']);feedback=store.get(root,state,'feedback',feedback_id);f=feedback['payload']
        require_selected(root,state,store.get(root,state,'evaluations',f['evaluation_id']))
        require(p['prompt_version'] in ('measured_whole_region_v1','diagnosis_backed_visual_goals_v1','faithful_diagnosis_goals_v1'),'feedback starts from the original target draft, not accumulated candidate/history prompts')
        require(p['target_version']==f['current_target_version'] and p['target_hash']==f['current_target_hash'],'feedback requires the same current evaluation target')
        public={k:deepcopy(f[k]) for k in ('residuals','global_residuals','content_restoration','spillover','preservation_requirements')}
        prompt=p['prompt']+'\nFactual feedback from previous C only. Start again from original A and B, never keep previous C geometry or use C as the structure standard. Residual directions describe C versus B, not an additive pixel operation on A.\n'+canonical_json(public).decode('utf-8')
        p.update(prompt=prompt,prompt_hash=sha256_bytes(prompt.encode('utf-8')),prompt_version={'faithful_diagnosis_goals_v1':'faithful_diagnosis_goals_feedback_v1','diagnosis_backed_visual_goals_v1':'diagnosis_backed_visual_goals_feedback_v1','measured_whole_region_v1':'measured_whole_region_feedback_v1'}[p['prompt_version']],
            base_compiled_record_id=base['record_id'],base_compiled_hash=base['content_hash'],feedback_id=feedback_id,feedback_hash=feedback['content_hash'])
        return store.put(root,state,'compiled',None,'compiled_request',p)
