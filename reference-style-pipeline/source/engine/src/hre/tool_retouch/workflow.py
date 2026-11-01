"""Reference tool route: immutable contract, bounded plans, native acceptance, safe fallback."""
from dataclasses import asdict
from pathlib import Path
import time
import numpy as np
from .color import require,resize_float,preview_size,resolve_domain,digest_bytes
from .contracts import compile_contract,canonical,number,strict
from .evidence import extract,pair_manifest,array_hash,mask_valid,MATERIAL_REGION_PROTOCOL
from .planner import validate_plan,TOOLS,CONTROLLER_PROTOCOL,coordinates,MATERIAL_CONTROLLER_PROTOCOL,NUMERIC_WARM_START_PROTOCOL
from .solver import Budget,BudgetExhausted,solve,authorized
from .verifier import target_results,objective,native_checks,validate_visual,accepted,safe_visual,active_local_masks,EDGE_REVIEW_PROTOCOL
from .providers import PendingResponse
from .trace import StageTrace,provider_source,operation_diff
from .planner import instantiate,identity

DEFAULT_POLICY={
 'tolerances':{},'per_round_preview':40,'preview_side':768,
 'limits':{'preview':120,'native':3,'replay':3,'vlm':8,'outer':3},
 'identity_tolerance':2/65535,'outside_tolerance':2/65535,
 'max_new_clip':.001,'detail_ratio':[.5,2.],'max_edge_jump':.04,
 'regularization':.001,'improvement_epsilon':1e-7,
 'replay_tolerance':0.,
}

BUDGET_PROTOCOL='bounded_feedback_v2'
V2_BUDGET_CAPS={'preview':180,'native':6,'replay':6,'vlm':12,'outer':3}

def validate_policy(p):
    strict(p,set(DEFAULT_POLICY) | ({'edge_policy','budget_protocol','controller_protocol','optimization_margin_fraction','material_region_protocol','material_controller_protocol'} & set(p)));strict(p['limits'],DEFAULT_POLICY['limits'])
    if 'edge_policy' in p:require(p['edge_policy']==EDGE_REVIEW_PROTOCOL,'unknown edge policy protocol')
    if 'budget_protocol' in p:require(p['budget_protocol']==BUDGET_PROTOCOL,'unknown budget protocol')
    if 'controller_protocol' in p:require(p['controller_protocol']==CONTROLLER_PROTOCOL,'unknown controller protocol')
    if 'material_region_protocol' in p:require(p['material_region_protocol']==MATERIAL_REGION_PROTOCOL,'unknown material region protocol')
    if 'material_controller_protocol' in p:require(p['material_controller_protocol']==MATERIAL_CONTROLLER_PROTOCOL and p.get('material_region_protocol')==MATERIAL_REGION_PROTOCOL and p.get('controller_protocol')==CONTROLLER_PROTOCOL,'material controller requires exact material region and v3 protocols')
    if p.get('controller_protocol')==CONTROLLER_PROTOCOL:
        require('optimization_margin_fraction' in p and number(p['optimization_margin_fraction']) and 0<=p['optimization_margin_fraction']<=.5,'explicit optimization margin fraction in 0..0.5 required')
    else:require('optimization_margin_fraction' not in p,'optimization margin requires controller v3')
    extended=p.get('budget_protocol')==BUDGET_PROTOCOL
    caps=V2_BUDGET_CAPS if extended else DEFAULT_POLICY['limits']
    for k,cap in caps.items():require(type(p['limits'][k]) is int and 0<p['limits'][k]<=cap,'invalid budget '+k)
    require(type(p['per_round_preview']) is int and 1<=p['per_round_preview']<=(60 if extended else 40),'round budget')
    require(type(p['preview_side']) is int and 32<=p['preview_side']<=2048,'preview dimension')
    require(isinstance(p['tolerances'],dict) and all(isinstance(k,str) and number(v) and v>0 for k,v in p['tolerances'].items()),'tolerances must be calibrated and frozen')
    for k in ('identity_tolerance','outside_tolerance','max_new_clip','max_edge_jump','regularization','improvement_epsilon','replay_tolerance'):
        require(number(p[k]) and 0<=p[k]<=1,'invalid policy '+k)
    require(p['improvement_epsilon']>0,'positive improvement threshold')
    require(isinstance(p['detail_ratio'],list) and len(p['detail_ratio'])==2 and all(number(x) for x in p['detail_ratio']) and 0<=p['detail_ratio'][0]<=1<=p['detail_ratio'][1],'detail ratio')

def visual_context(contract,source,reference,candidate,checks=None):
    result={'contract':contract.data,'contract_sha256':contract.sha256,'source_sha256':array_hash(source),'reference_sha256':array_hash(reference),'candidate_sha256':array_hash(candidate)}
    result['color_contexts']={'A':contract.data['source'],'B':contract.data['reference']}
    result['working_color_domains']={'A':resolve_domain(contract.data['source'].get('domain')).identity,'B':resolve_domain(contract.data['reference'].get('domain')).identity,'C':resolve_domain(contract.data['source'].get('domain')).identity}
    if checks is not None and checks.get('edge_review_protocol')==EDGE_REVIEW_PROTOCOL:
        result.update(edge_review_protocol=EDGE_REVIEW_PROTOCOL,edge_warnings=checks['edge_warnings'],native_checks=checks)
    return result

def views(a,b,c=None,pairs=None,edge_warnings=None):
    result={'A overview':a,'B overview':b}
    if c is not None:result['C overview']=c
    for p in pairs or []:
        for role,im in [('a',a),('b',b)]+([('c',c)] if c is not None else []):
            mask=p['supports']['b' if role=='b' else 'a'];yy,xx=np.where(mask)
            if not len(xx):continue
            # Native 512-square at region center, not a resized crop. Also include extent.
            x=int(np.median(xx));y=int(np.median(yy));x0=max(0,x-256);y0=max(0,y-256)
            result[f'{role} native {p["id"]} x{x0} y{y0}']=im[y0:y0+512,x0:x0+512]
            result[f'{role} region {p["id"]}']=im[yy.min():yy.max()+1,xx.min():xx.max()+1]
    for warning in edge_warnings or []:
        require(c is not None and warning['candidate_sha256']==array_hash(c),'edge crop candidate binding mismatch')
        x0,y0,x1,y1=warning['crop_xyxy']
        for role,im in [('A',a),('C',c)]:
            result[f'{role} edge warning {warning["id"]} native x{x0} y{y0}']=im[y0:y1,x0:x1]
    return {k:v.copy() for k,v in result.items()}

def edit_mask_catalog(edit_masks,metadata=None):
    metadata={} if metadata is None else metadata
    require(isinstance(metadata,dict),'edit mask metadata must be an object')
    return [{'id':key,'array_hash':array_hash(mask),'shape':list(mask.shape),'metadata':metadata.get(key,{})}
            for key,mask in sorted(edit_masks.items())]

class ToolWorkflow:
    def __init__(self,backend,planner,reviewer,policy,automatic_diagnosis=None,numeric_warm_start_min_round=None):
        validate_policy(policy)
        require(numeric_warm_start_min_round is None or (type(numeric_warm_start_min_round) is int and numeric_warm_start_min_round>=1),'numeric warm-start minimum round must be an integer >=1 or None')
        if numeric_warm_start_min_round is not None:require(policy.get('controller_protocol')==CONTROLLER_PROTOCOL,'numeric warm-start requires the explicit v3 controller')
        self.numeric_warm_start_min_round=numeric_warm_start_min_round
        self.backend=backend;self.planner=planner;self.reviewer=reviewer;self.policy=policy;self.automatic_diagnosis=automatic_diagnosis
    def run(self,a,b,context_a,context_b,pairs,edit_masks,out):
        out=Path(out);out.mkdir(parents=True,exist_ok=True);t0=time.monotonic();budget=Budget(self.policy['limits']);events=[]
        timings=dict(measurement=0.,planning=0.,review=0.,search=0.,native=0.,export=0.,replay=0.)
        result={'timings_seconds':timings,'route':'reference_tool_retouch_v1','status':'execution_failed','success':False,'output':'original_A','budget':budget.used,'events':events,
                'simulation':bool(self.backend.simulation or getattr(self.planner,'simulation',False) or getattr(self.reviewer,'simulation',False) or (self.automatic_diagnosis or {}).get('simulation',False)),
                'real_effect_validated':False,'contract_sha256':None}
        journal=StageTrace(out)
        controller_v3=self.policy.get('controller_protocol')==CONTROLLER_PROTOCOL
        if controller_v3:result['controller_protocol']=CONTROLLER_PROTOCOL
        edge_v2=self.policy.get('edge_policy')==EDGE_REVIEW_PROTOCOL
        if edge_v2:result['edge_review_protocol']=EDGE_REVIEW_PROTOCOL
        if self.policy.get('budget_protocol')==BUDGET_PROTOCOL:result['budget_protocol']=BUDGET_PROTOCOL
        prior_edit=None
        def timed(kind,fn,*args,**kwargs):
            started=time.monotonic()
            try:return fn(*args,**kwargs)
            finally:timings[kind]+=time.monotonic()-started
        def call(provider,stage,context,images):
            budget.take('vlm')
            return journal.call(stage,lambda:timed('review' if stage=='verify' else 'planning',provider,stage,context,images),{'context':context,'images':images},source=provider_source(provider),change='新增该阶段的实际结构化判断；图像未改变',impact='输出仍须通过对应阶段校验')
        contract=None
        try:
            domain_a=resolve_domain(context_a.domain);domain_b=resolve_domain(context_b.domain)
            require(domain_a.id==domain_b.id,'source/reference working-space mismatch')
            if hasattr(self.backend,'domain'):require(resolve_domain(self.backend.domain).identity==domain_a.identity,'backend/source color domain mismatch')
            else:require(domain_a.id=='srgb','P3 workflow requires explicit backend domain')
            result['color_domains']={'A':domain_a.identity,'B':domain_b.identity}
            if self.automatic_diagnosis is not None:budget.used['vlm']=self.automatic_diagnosis['vlm_calls']
            require(all(p['comparability']=='not_comparable' or min(p['counts'].values())>0 for p in pairs),'invalid pair support')
            if not any(p['comparability']!='not_comparable' for p in pairs):
                result.update(status='reference_insufficient',reason='no comparable support');return result
            for mask in edit_masks.values():mask_valid(mask,a.shape[:2])
            obs=journal.call('statistics',lambda:timed('measurement',extract,a,b,pairs,domain_a=domain_a,domain_b=domain_b),{'A':a,'B':b,'regions':pair_manifest(pairs),'color_domains':{'A':domain_a.identity,'B':domain_b.identity}},change='新增双侧冻结ROI统计；图像未改变',impact='诊断和目标只能引用这些实际统计')
            diagnosis=None
            context={'observations':obs,'regions':pair_manifest(pairs),'policy':self.policy,'color_contexts':{'A':asdict(context_a),'B':asdict(context_b)},'working_color_domains':{'A':domain_a.identity,'B':domain_b.identity}}
            if 'inherited_semantic_intent' in (self.automatic_diagnosis or {}):context['inherited_semantic_intent']=self.automatic_diagnosis['inherited_semantic_intent']
            if self.automatic_diagnosis is not None:
                from .diagnosis import validate_measured_diagnosis,DIMENSIONS
                context.update(user_goal=self.automatic_diagnosis['user_goal'],discovery=self.automatic_diagnosis['discovery'],dimensions=sorted(DIMENSIONS))
                diagnosis=validate_measured_diagnosis(call(self.planner,'diagnose',context,views(a,b,pairs=pairs)),obs,pairs,self.automatic_diagnosis['discovery']['protected_properties'])
                context['measured_diagnosis']=diagnosis
                result['measured_diagnosis']=diagnosis
            proposal=call(self.planner,'contract',context,views(a,b,pairs=pairs))
            contract=compile_contract(proposal,obs,pairs,asdict(context_a),asdict(context_b),self.policy,diagnosis)
            journal.record('contract_frozen',{'proposal':proposal},contract,change='校验并冻结目标、保护项、ROI和数值区间；图像未改变',impact='后续优化与复核不可修改合同')
            result['contract_sha256']=contract.sha256
            path=out/'contract.json'
            if path.exists():require(path.read_text()==canonical({'sha256':contract.sha256,'contract':contract.data}),'cannot replace frozen contract')
            else:contract.save(path)
            supports={p['id']:p['supports']['a'] for p in pairs if p['comparability']!='not_comparable'}
            baseline=target_results(a,contract,supports,domain=domain_a);base_loss=objective(baseline,contract)
            perceptual_ids={t['id'] for t in contract.data['targets'] if t['kind'] in ('perceptual','protection')}
            visual_anchor=None;baseline_visual=None;feedback=[]  # Latest feedback is not the promotion baseline.
            def pending_visual(review):
                return {t['id'] for t in (review or {}).get('target_results',[]) if t['id'] in perceptual_ids and t['status'] in ('partial','unmet')}
            def numeric_preserved(rows,reference_rows=None):
                current={r['id']:r for r in rows}
                reference_rows=baseline if reference_rows is None else reference_rows
                return all(r['kind'] in ('perceptual','protection') or not r['mandatory'] or r['status']!='achieved' or current.get(r['id'],{}).get('status')=='achieved' for r in reference_rows)
            def visual_progress(review,previous):
                if not previous:return False
                scores={'unmet':1,'partial':2,'achieved':3}
                old={r['id']:r for r in previous['target_results']};now={r['id']:r for r in review['target_results']}
                if any(old[k]['status']=='uncertain' or now[k]['status']=='uncertain' for k in perceptual_ids):return False
                return bool(perceptual_ids) and all(scores[now[k]['status']]>=scores[old[k]['status']] for k in perceptual_ids) and any(scores[now[k]['status']]>scores[old[k]['status']] for k in perceptual_ids)

            if all(r['residual'] in (None,0.) for r in baseline):
                baseline_checks={'edge_review_protocol':EDGE_REVIEW_PROTOCOL,'edge_warnings':[]} if edge_v2 else None
                v=call(self.reviewer,'verify',visual_context(contract,a,b,a,baseline_checks),views(a,b,a,pairs))
                validate_visual(v,contract,a,b,a,[] if edge_v2 else None)
                visual_anchor=v;baseline_visual=v
                feedback=[{'id':'baseline-visual','targets':v['target_results'],'notes':v['notes'],'preservation_checks':v['preservation_checks'],'content':v['content'],'naturalness':v['naturalness'],'native_inspected':v['native_inspected']}]
                journal.record('baseline_visual_feedback',{'source':'original_A'},feedback,source=provider_source(self.reviewer),change='保留原图视觉未满足项；图像未改变',impact='作为预算内感知候选的真实依据')
                if accepted(baseline,v,[] if edge_v2 else None):
                    result.update(status='already_satisfied',success=True,target_results=baseline,visual=v);return result
            size=preview_size(a,self.policy['preview_side']);small=resize_float(a,size)
            small_masks={k:resize_float(v,size,True) for k,v in edit_masks.items()}
            small_support={k:resize_float(v.astype(float),size,True)>=.999 for k,v in supports.items()}
            require(all(x.any() for x in small_support.values()),'preview loses a frozen ROI; raise preview size in a new protocol')
            preview_preservation_baseline=target_results(small,contract,small_support,domain=domain_a) if controller_v3 else baseline
            if controller_v3:journal.record('preview_preservation_baseline',{'source_preview':small,'preview_supports':small_support},{'preview_baseline_targets':preview_preservation_baseline,'native_baseline_targets':baseline},change='预览候选仅与相同预览分辨率和支持的原始A比较数值保护；图像不变',impact='避免缩放偏差被误判为候选回退；原生及导出保护仍使用原生A基线')
            best_safe=None;best_loss=base_loss;last_preview=float('inf');cache={}
            while budget.used['outer']<budget.limits['outer']:
                budget.take('outer');round_id=budget.used['outer']
                plan_context={'contract':contract.data,'tools':TOOLS,'edit_mask_ids':list(edit_masks),'feedback':feedback,'color_contexts':{'A':asdict(context_a),'B':asdict(context_b)},'working_color_domains':{'A':domain_a.identity,'B':domain_b.identity}}
                plan_images=views(a,b,pairs=pairs)
                if controller_v3:
                    plan_context.update(controller_protocol=CONTROLLER_PROTOCOL,parameter_modes=['numeric_fit','visual_proposal'],local_operation_cap=6 if self.policy.get('material_controller_protocol')==MATERIAL_CONTROLLER_PROTOCOL else 4,operation_cap=6,total_parameter_cap=12,optimization_interval_margin_scale=self.policy['optimization_margin_fraction'],visual_proposal_rule='Only all-perceptual/protection target operations; suggested values are validated, actually rendered, then held fixed while fitting numeric coordinates. No invented perceptual loss.',edit_mask_catalog=edit_mask_catalog(edit_masks,(self.automatic_diagnosis or {}).get('edit_mask_metadata')))
                    overlay_ids=['skin','dark']
                    if self.policy.get('material_controller_protocol')==MATERIAL_CONTROLLER_PROTOCOL:
                        material_ids=sorted(key for key in edit_masks if key.startswith('material-'))
                        require(len(material_ids)<=3,'material edit overlay cap is 3')
                        overlay_ids.extend(material_ids)
                    for key in overlay_ids:
                        if key in edit_masks:plan_images['A actual edit soft-mask overlay '+key]=resize_float(a*(.2+.8*edit_masks[key][...,None]),preview_size(a,1024))
                    plan_context['edit_mask_overlay_note']='Display-only A*(0.2+0.8*soft_mask); image A is unchanged. Catalog hashes bind the exact loaded native mask arrays used for rendering; shape is [height,width].'
                if self.policy.get('material_controller_protocol')==MATERIAL_CONTROLLER_PROTOCOL:
                    plan_context.update(material_controller_protocol=MATERIAL_CONTROLLER_PROTOCOL,material_region_protocol=MATERIAL_REGION_PROTOCOL)
                warm_start_available=self.numeric_warm_start_min_round is not None and round_id>=self.numeric_warm_start_min_round
                if warm_start_available:
                    plan_context['numeric_warm_start_capability']={'protocol':NUMERIC_WARM_START_PROTOCOL,'plan_field':'numeric_warm_start','type':'boolean','default':False,'identity_first':True,'preview_budget_unchanged':True,'rule':'Explicit true renders a seed combining validated numeric_fit suggested values and fixed visual_proposal suggested values, then continues numeric optimization. Every render starts from original A.'}
                plan=call(self.planner,'plan',plan_context,plan_images)
                validate_plan(plan,contract.data,edit_masks)
                require(not plan.get('numeric_warm_start',False) or warm_start_available,'numeric warm-start was not advertised for this round')
                require(set(plan['feedback_ids'])<={f['id'] for f in feedback} and (round_id==1 or bool(plan['feedback_ids'])),'revision must cite actual current feedback')
                wanted=pending_visual(visual_anchor)
                claimed={target for op in plan['operations'] for target in op['target_ids']}
                unsupported=set(wanted)-claimed
                diagnosed={d['id']:d for d in (contract.data.get('measured_diagnosis') or {}).get('deltas',[])}
                unsupported|={t['id'] for t in contract.data['targets'] if t['id'] in wanted and diagnosed.get(t.get('delta_id'),{}).get('dimension')=='texture_and_noise_observation'}
                visual_candidates_for=wanted-unsupported
                result.pop('unsupported_targets',None)
                if unsupported:
                    result['unsupported_targets']=[{'id':k,'reason':'no supported operation assigned, or texture/noise operator unavailable'} for k in sorted(unsupported)]
                    journal.record('unsupported_targets',{'plan':plan},result['unsupported_targets'],status='unsupported',change='显式记录无法执行的感知目标；图像未改变',impact='不将无能力目标隐藏成数值无改善')
                before=contract.sha256
                best,ranked,trace=journal.call('search_execution',lambda:timed('search',solve,small,plan,contract,small_support,small_masks,self.backend,budget,cache,domain=domain_a),{'round':round_id,'plan':plan,'source':small},source='test_double' if self.backend.simulation else 'PhotoCraft_cpu',change='实际预览搜索执行',impact='搜索失败则停止；成功结果进入候选排序',image_changed=True)
                contract.verify();require(contract.sha256==before,'contract changed during search')
                journal.record('parameter_search',{'round':round_id,'plan':plan,'source':small,'mask_versions':small_masks}, {'trace':trace,'selected_values':best.values,'selected_targets':best.rows},seconds=sum(x['seconds'] for x in trace['candidates']),source='test_double' if self.backend.simulation else 'PhotoCraft_cpu',change='从原始A预览执行有界参数搜索；未把分析阶段当作图像编辑',impact='仅安全改善候选进入原生渲染',image_changed=True)
                events.append({'round':round_id,'plan':plan,'search':trace});feedback=[]
                improved=[c for c in ranked if c.key!='original_A' and c.loss<trace['baseline_loss']-self.policy['improvement_epsilon']]
                proposal_coordinates={i:spec['suggested'] for i,(_,_,spec,_) in enumerate(coordinates(plan)) if controller_v3 and spec.get('mode','numeric_fit')=='visual_proposal'}
                if proposal_coordinates:
                    proposed=[c for c in ranked if c.key!='original_A' and c.values!=identity(plan) and c.hard['pass'] and numeric_preserved(c.rows,preview_preservation_baseline) and all(c.values[i]==v for i,v in proposal_coordinates.items())]
                    seen={c.key for c in improved};improved.extend(c for c in proposed if c.key not in seen)
                    journal.record('explicit_visual_proposal_candidates',{'plan':plan,'fixed_coordinates':proposal_coordinates},{'candidate_keys':[c.key for c in proposed],'numeric_protection':'mandatory numeric targets achieved by same-preview baseline retained; native baseline independently enforced at export' if controller_v3 else 'already-satisfied mandatory numeric targets retained','no_perceptual_loss':True},change='真实渲染当前规划的感知参数建议并固定；数值拟合不抹掉视觉意图',impact='所有候选仍须原生硬检查、导出、重放和真实视觉验收')
                if visual_candidates_for:
                    # Visual failures, not invented numerical scores, permit bounded candidates.
                    visual_candidates=[c for c in ranked if c.key!='original_A' and c.values!=identity(plan) and c.hard['pass'] and numeric_preserved(c.rows,preview_preservation_baseline)]
                    seen={c.key for c in improved}
                    improved.extend(c for c in visual_candidates if c.key not in seen)
                    journal.record('perceptual_candidates',{'feedback':visual_anchor,'target_ids':sorted(visual_candidates_for)}, {'candidate_keys':[c.key for c in improved],'numeric_protection':'mandatory numeric targets achieved by same-preview baseline retained; native baseline independently enforced at export' if controller_v3 else 'already-satisfied mandatory numeric targets retained','native_budget_remaining':budget.limits['native']-budget.used['native']},change='依据实际视觉未满足反馈允许非identity候选，不伪造感知数值loss',impact='候选仍须逐一通过原生安全与视觉复核')
                if not improved:
                    result['reason']='unsupported perceptual targets' if unsupported else ('no safe bounded perceptual candidate' if wanted else 'no safe preview improvement')
                    break
                for candidate in improved:
                    # Native candidate exports and replay checks have separate bounded counters.
                    if budget.used['native']>=budget.limits['native'] or budget.used['replay']>=budget.limits['replay']:break
                    budget.take('native');native=journal.call('native_render',lambda:timed('native',self.backend.render_from_source,a.copy(),plan,candidate.values,{k:v.copy() for k,v in edit_masks.items()}),{'round':round_id,'source_A':a,'plan':plan,'values':candidate.values,'masks':edit_masks},source='test_double' if self.backend.simulation else 'PhotoCraft_cpu',change='从原始A生成原生C；不是在上一轮C上累积编辑',impact='须通过原生硬检查、导出与独立复核',image_changed=True)
                    used_masks=active_local_masks(plan,candidate.values,edit_masks)
                    checks=native_checks(a,native,self.policy,authorized(plan,edit_masks,a.shape[:2]),used_masks,domain=domain_a)
                    rows=target_results(native,contract,supports,domain=domain_a) if checks['pass'] else []
                    from .color import encode_png16
                    native_file=f'native-attempt-{round_id}-{budget.used["native"]}.png'
                    if not (out/native_file).exists():encode_png16(out/native_file,native,domain=domain_a)
                    current_edit={'operations':[{**op,'id':spec['id']} for op,spec in zip(instantiate(plan,candidate.values),plan['operations'])],'mask_versions':{k:array_hash(v) for k,v in edit_masks.items()},'targets':rows,'protection':checks,'file':native_file,'execution':getattr(self.backend,'last_execution',{'kind':'test_double' if self.backend.simulation else 'actual_backend_call'})}
                    delta={'operations':operation_diff(prior_edit,current_edit),'previous':prior_edit,'current':current_edit,'source_baseline_targets':baseline,'reference_observations':{k:v for k,v in obs.items() if k.startswith('b:')},'all_renders_from_original_A':True}
                    journal.record('round_comparison',{'round':round_id,'A':a,'B':b},delta,change='新增相对上一实际候选的操作/参数/mask/统计比较；比较本身不编辑图像',impact='记录原生失败或进入复核的依据')
                    prior_edit=current_edit
                    feedback.append({'id':f'native-{round_id}-{budget.used["native"]}','checks':checks,'targets':rows})
                    journal.record('native_acceptance',{'candidate':native_file},{'checks':checks,'targets':rows,'feedback':feedback},change='新增原生保护检查和逐目标残差；图像未改变',impact='失败候选不进入视觉验收')
                    if not checks['pass']:continue
                    filename=f'candidate-{round_id}-{budget.used["native"]}.png';path=out/filename
                    # Preserve evidence for export, exported-pixel acceptance and replay independently.
                    def export_or_restore():
                        if path.exists():
                            from .color import read_png16
                            restored,metadata=read_png16(path)
                            require(metadata['profile']==domain_a.profile and not metadata['srgb_chunk'],'resume export ICC/domain mismatch')
                            metadata.pop('profile',None)
                            require(restored.shape==native.shape and np.max(abs(restored-native))<=.5/65535+1e-8,'resume candidate differs')
                            return restored,metadata
                        return timed('export',self.backend.export_native,path,native)
                    exported,meta=journal.call('export',export_or_restore,{'native_file':native_file,'native':native,'destination':filename},source='native_RGB16_export',change='生成或核对实际RGB16文件与ICC，不假设往返正确',impact='对导出后实际像素重新验收',image_changed=True)
                    require(meta.get('icc_sha256')==digest_bytes(domain_a.profile) and meta.get('srgb_chunk') is False,'export ICC/domain mismatch')
                    export_started=time.monotonic()
                    checks=native_checks(a,exported,self.policy,authorized(plan,edit_masks,a.shape[:2]),used_masks,domain=domain_a)
                    rows=target_results(exported,contract,supports,domain=domain_a)
                    if not numeric_preserved(rows):checks['reasons'].append('previously satisfied mandatory numeric target regressed');checks['pass']=False
                    journal.record('exported_native_acceptance',{'file':filename,'pixels':exported},{'checks':checks,'targets':rows},status='completed' if checks['pass'] else 'failed',seconds=time.monotonic()-export_started,change='新增导出后实际检查和残差；图像未改变',impact='失败则拒绝该候选，保留失败原因')
                    if not checks['pass']:
                        feedback.append({'id':f'export-{round_id}-{budget.used["native"]}','checks':checks,'targets':rows})
                        continue
                    budget.take('replay');replay_started=time.monotonic()
                    try:replay=timed('replay',self.backend.replay,a.copy(),plan,candidate.values,edit_masks,native,self.policy['replay_tolerance'])
                    except Exception as exc:
                        journal.record('replay',{'file':filename},{'error':type(exc).__name__,'reason':str(exc)},status='failed',seconds=time.monotonic()-replay_started,source='test_double' if self.backend.simulation else 'PhotoCraft_cpu',change='重放失败；不丢弃错误证据',impact='停止执行并回退已验证安全结果')
                        raise
                    journal.record('replay',{'file':filename,'expected_native':native},replay,status='completed' if replay['pass'] else 'failed',seconds=time.monotonic()-replay_started,source='test_double' if self.backend.simulation else 'PhotoCraft_cpu',change='保存实际重放误差、阈值及输出哈希',impact='不一致时停止，不晋升为交付')
                    require(replay['pass'],'replay mismatch')
                    edge_warnings=checks.get('edge_warnings') if edge_v2 else None
                    visual=call(self.reviewer,'verify',visual_context(contract,a,b,exported,checks),views(a,b,exported,pairs,edge_warnings))
                    validate_visual(visual,contract,a,b,exported,edge_warnings)
                    delivery={'file':filename,'target_results':rows,'native_checks':checks,'visual':visual,'export':meta,'replay':replay,'values':list(candidate.values),'plan':plan,'pixel_sha256':array_hash(exported)}
                    journal.record('delivery_verification',{'candidate':filename,'contract_sha256':contract.sha256},delivery,source=provider_source(self.reviewer),change='新增逐目标/保护视觉判断、导出和重放结果；图像未改变',impact='决定接受、回退或有限反馈修订')
                    events.append({'native_candidate':delivery})
                    feedback.append({'id':f'visual-{round_id}-{budget.used["native"]}','targets':visual['target_results'],'notes':visual['notes'],'preservation_checks':visual['preservation_checks'],**({'edge_reviews':visual['edge_reviews']} if edge_v2 else {})})
                    journal.record('feedback',{'round':round_id},feedback,change='保存实际逐目标/保护反馈与剩余问题；图像未改变',impact='决定终止或触发下一轮有界修订')
                    promotion_reference=best_safe['visual'] if best_safe else baseline_visual
                    progress=visual_progress(visual,promotion_reference)
                    previous_judgments={r['id']:r['status'] for r in (promotion_reference or {}).get('target_results',[])}
                    current_judgments={r['id']:r['status'] for r in visual['target_results']}
                    transitions=[{'id':k,'from':previous_judgments[k],'to':current_judgments[k]} for k in sorted(perceptual_ids&previous_judgments.keys()) if previous_judgments[k]!=current_judgments[k]]
                    journal.record('perceptual_comparison',{'reference':best_safe['file'] if best_safe else 'original_A','candidate':filename}, {'quality_improved':progress,'unknown_resolutions':[t for t in transitions if t['from']=='uncertain' and t['to']!='uncertain'],'known_quality_changes':[t for t in transitions if 'uncertain' not in (t['from'],t['to'])]},change='单列未知状态消解与已知质量变化；未知不是更低效果等级',impact='只有相对固定原图/最佳安全基准的进步可用于感知晋升')
                    visual_anchor=visual
                    if not safe_visual(visual,edge_warnings):
                        result['unconfirmed_safety']=True
                        continue
                    loss=objective(rows,contract)
                    if loss<best_loss-self.policy['improvement_epsilon'] or (progress and numeric_preserved(rows) and loss<=best_loss+self.policy['improvement_epsilon']):best_safe=delivery;best_loss=loss
                    if accepted(rows,visual,edge_warnings):
                        result.update(status='accepted',success=True,output=filename,delivery=delivery);return result
                    break
                if budget.used['native']>=budget.limits['native']:result['reason']='native/replay budget exhausted';break
                if not pending_visual(visual_anchor) and best.loss>=last_preview-self.policy['improvement_epsilon']:result['reason']='outer revision made no improvement';break
                journal.record('feedback_revision',{'round':round_id},feedback,change='保留当前失败/未满足项供下一轮引用；合同和图像不改变',impact='下一轮计划须引用实际反馈')
                last_preview=best.loss
            if best_safe:
                result.update(status='improved_incomplete',output=best_safe['file'],delivery=best_safe)
            else:result.update(status='no_safe_improvement')
        except PendingResponse as exc:
            result.update(status='waiting_for_response',reason=str(exc))
        except BudgetExhausted as exc:
            result.update(status='no_safe_improvement',reason=str(exc))
        except Exception as exc:
            result.update(status='execution_failed',reason=type(exc).__name__+': '+str(exc))
        finally:
            result['seconds']=time.monotonic()-t0
            # Persist factual status on every exit, including pauses and failures.
            from ..storage import write_json
            write_json(out/'result.json',result)
            from .experiment import write_case_report
            write_case_report(out,result)
        return result
