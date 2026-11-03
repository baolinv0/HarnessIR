"""A/B distributions and signed relationships from actual audited float arrays."""
from copy import deepcopy
import numpy as np
from hre.paths import make_id
from hre.storage import case_lock
from .contracts import require
from . import coordinator as co, s2_store as store
from .s2_evidence import METRICS, STATS, load_array
from .s2_public import diagnostic_view


def _analysis(root,image):
    if image['analysis_path'] is None:return None
    with np.load(co._path(root,image['analysis_path'],True),allow_pickle=False) as data:
        require(set(data.files)=={'linear_srgb','XYZ_D65','Y','Lab_D65','chroma'},'audited analysis key mismatch')
        y=data['Y'];lab=data['Lab_D65'];chroma=data['chroma']
        w,h=image['oriented_size'];require(y.shape==(h,w) and lab.shape==(h,w,3) and chroma.shape==(h,w),'analysis geometry mismatch')
        return {'linear_Y':y.copy(),'L_star':lab[...,0].copy(),'a_star':lab[...,1].copy(),
                'b_star':lab[...,2].copy(),'chroma':chroma.copy()}


def _distribution(values,mask):
    if values is None or mask is None:return {'status':'uncertain','count':0,'invalid_count':None,'values':None}
    selected=values[mask];valid=selected[np.isfinite(selected)]
    if len(valid)==0:return {'status':'uncertain','count':0,'invalid_count':int(len(selected)),'values':None}
    q=np.quantile(valid,[.05,.25,.5,.75,.95])
    values={name:float(number) for name,number in zip(STATS[:5],q)}
    values['span95_05']=float(q[4]-q[0]);values['mean']=float(valid.mean())
    return {'status':'observed','count':int(len(valid)),'invalid_count':int(len(selected)-len(valid)),'values':values}


def measure_ab(root,snapshot_id):
    with case_lock(root):
        state=co._status(root);snapshot=store.get(root,state,'snapshots',snapshot_id)
        images={i['role']:i for i in co._load(root,'input_audit.json')['payload']['images']}
        arrays={role:_analysis(root,image) for role,image in images.items()}
        regions=deepcopy(snapshot['payload']['regions'])
        global_eligible='numeric_eligible' if snapshot['payload']['global_comparability']=='comparable' and all(v is not None for v in arrays.values()) else 'visual_direction_only'
        regions={'g0':{'region_id':'g0','semantic_class':'global','usage':'summary_only','eligibility':global_eligible,
                 'coverage':{r:{'pixels':i['oriented_size'][0]*i['oriented_size'][1],'denominator':i['oriented_size'][0]*i['oriented_size'][1],'fraction':1.0,'bbox':[0,0,*i['oriented_size']]} for r,i in images.items()}},**regions}
        supports={};distributions={};measurements=[]
        for rid,region in regions.items():
            supports[rid]={};distributions[rid]={}
            for role,image in images.items():
                if rid=='g0':mask=np.ones((image['oriented_size'][1],image['oriented_size'][0]),bool)
                else:mask=load_array(root,region['support_paths'][role]).astype(bool) if role in region['support_paths'] else None
                supports[rid][role]=mask
                distributions[rid][role]={metric:_distribution(None if arrays[role] is None else arrays[role][metric],mask) for metric in METRICS}
            for metric in METRICS:
                for statistic in STATS:
                    values={role:(distributions[rid][role][metric]['values'] or {}).get(statistic) for role in ('A','B')}
                    eligible=region['eligibility']
                    if any(v is None for v in values.values()):eligible='insufficient_evidence' if any(region['coverage'][r]['pixels']==0 for r in ('A','B')) else 'visual_direction_only'
                    measurements.append({'measurement_id':'m'+str(len(measurements)+1),'subject_id':rid,'kind':'distribution',
                        'metric':metric,'statistic':statistic,**values,'delta_B_minus_A':None if any(v is None for v in values.values()) else values['B']-values['A'],
                        'eligibility':eligible,'support_snapshot_hash':snapshot['content_hash'],'operands':None})
        depth_orders=[]
        for relation in snapshot['payload']['relations']:
            left,right=relation['left'],relation['right'];metric,statistic=relation['metric'],relation['statistic']
            operands={};values={}
            for role in ('A','B'):
                l=(distributions[left][role][metric]['values'] or {}).get(statistic)
                r=(distributions[right][role][metric]['values'] or {}).get(statistic)
                operands[role]={'left':l,'right':r};values[role]=None if l is None or r is None else l-r
            eligible='numeric_eligible' if all(regions[r]['eligibility']=='numeric_eligible' for r in (left,right)) and all(v is not None for v in values.values()) else 'visual_direction_only'
            if any(regions[r]['eligibility']=='insufficient_evidence' for r in (left,right)):eligible='insufficient_evidence'
            measurements.append({'measurement_id':'m'+str(len(measurements)+1),'subject_id':relation['relation_id'],'kind':'relation',
                'metric':metric,'statistic':statistic,**values,'delta_B_minus_A':None if any(v is None for v in values.values()) else values['B']-values['A'],
                'eligibility':eligible,'support_snapshot_hash':snapshot['content_hash'],'operands':operands,'left_region_id':left,'right_region_id':right})
            for eid in snapshot['payload']['evidence_refs']:
                ev=store.get(root,state,'evidence',eid)['payload'];m=ev['manifest'];role=m['role']
                if m['kind']!='depth' or m['status']!='available' or ev['oriented_path'] is None:continue
                depth=load_array(root,ev['oriented_path']);numbers=[]
                for rid in (left,right):
                    mask=supports[rid][role];v=np.array([]) if mask is None else depth[mask & np.isfinite(depth)]
                    numbers.append(None if len(v)==0 else float(np.median(v)))
                ordering='uncertain'
                if all(v is not None for v in numbers):
                    sign=(numbers[0]-numbers[1])*(1 if m['value_semantics']=='near_is_small' else -1)
                    ordering='left_nearer' if sign<0 else ('right_nearer' if sign>0 else 'equal_relative_depth')
                depth_orders.append({'relation_id':relation['relation_id'],'evidence_id':eid,'role':role,
                    'left_median':numbers[0],'right_median':numbers[1],'ordering':ordering,
                    'cross_image_scale_comparison':'not_performed','brightness_rule':'none'})
        evidence=[];assets=deepcopy(snapshot['payload']['assets'])
        for eid,hash_ in snapshot['payload']['evidence_refs'].items():
            ev=store.get(root,state,'evidence',eid);require(ev['content_hash']==hash_,'snapshot evidence stale')
            m=ev['payload']['manifest']
            evidence.append({k:m[k] for k in ('evidence_id','role','kind','status','missing_reason','value_semantics')})
            evidence[-1]['record_hash']=ev['content_hash']
            evidence[-1]['observations']=deepcopy(ev['payload']['parsed'])
            if m['kind']=='depth' and ev['payload']['oriented_path'] is not None:
                depth=load_array(root,ev['payload']['oriented_path']);finite=depth[np.isfinite(depth)]
                evidence[-1]['relative_depth_quantiles']=None if len(finite)==0 else [float(x) for x in np.quantile(finite,[.25,.5,.75])]
                evidence[-1]['derived_status']='insufficient_finite_support' if len(finite)==0 else 'observed_within_image_only'
                evidence[-1]['cross_image_scale_comparison']='not_performed'
            # Source text/version/metadata are archival, never copied into prompts.
            assets.extend(ev['payload']['assets'])
        payload={'snapshot_id':snapshot_id,'snapshot_hash':snapshot['content_hash'],'input_audit_hash':state['payload']['input_audit_hash'],
                 'regions':regions,'distributions':distributions,'measurements':measurements,'depth_orders':depth_orders,
                 'text_protection':deepcopy(snapshot['payload']['text_protection']),'evidence':evidence,'assets':assets,
                 'numeric_policy':'all finite supported pixels; endpoints retained; no A/B pixelwise error',
                 'source_color_audit':{r:{k:i[k] for k in ('numeric_status','source_endpoint_pixel_fraction','gamut_clipped_pixel_fraction')} for r,i in images.items()},
                 'stage_evidence_status':'numeric_observed_visual_diagnosis_pending'}
        payload.update(diagnostic_view(payload))
        return store.put(root,state,'reports',None,'ab_report',payload)
