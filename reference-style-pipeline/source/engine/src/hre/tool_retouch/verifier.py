"""Frozen ROI evaluation and independent native delivery checks, never a style oracle."""
from collections import defaultdict
import numpy as np
from .color import require, image_valid,linearize,luminance,resolve_domain
from .evidence import measure,array_hash,COMPARABILITY
from .contracts import strict,number

def target_results(image,contract,supports,domain=None):
    data=contract.data;frozen_domain=resolve_domain(data.get('source',{}).get('domain'));domain=frozen_domain if domain is None else resolve_domain(domain)
    require(domain.identity==frozen_domain.identity,'target measurement domain differs from frozen source domain')
    metrics={r:measure(image,m,domain=domain) for r,m in supports.items() if m.any()};rows=[]
    for t in data['targets']:
        row={'id':t['id'],'kind':t['kind'],'mandatory':t['mandatory'],'status':'uncertain','residual':None,'value':None}
        if t['kind'] not in ('perceptual','protection'):
            if all(r in metrics and t['metric'] in metrics[r] for r in t['regions']):
                v=[metrics[r][t['metric']] for r in t['regions']];value=v[0] if len(v)==1 else v[0]-v[1]
                residual=max(0,t['lower']-value if t['lower'] is not None else 0,value-t['upper'] if t['upper'] is not None else 0)/t['scale']
                row.update(value=value,residual=residual,status='achieved' if residual<=1e-9 else 'unmet')
        rows.append(row)
    return rows

def objective(rows,contract):
    data=contract.data;ts={t['id']:t for t in data['targets']};regions={p['id']:p for p in data['region_pairs']};groups=defaultdict(list)
    for row in rows:
        t=ts[row['id']]
        if t['kind'] in ('perceptual','protection'):continue
        if row['residual'] is None:return float('inf')
        reliability=min(COMPARABILITY[regions[r]['comparability']] for r in t['regions'])
        groups[tuple(t['regions'])].append(row['residual']*reliability*(2 if t['mandatory'] else 1))
    return float(np.mean([np.mean(v) for v in groups.values()])) if groups else 0.

def hard_checks(source,candidate,policy,authorized_mask):
    try:image_valid(candidate)
    except ValueError as e:return {'pass':False,'reasons':[str(e)]}
    if source.shape!=candidate.shape:return {'pass':False,'reasons':['native dimensions changed']}
    require(authorized_mask.shape==source.shape[:2],'authorization shape')
    reasons=[];clip_new=float(((candidate.max(-1)>=65534/65535)&(source.max(-1)<65534/65535)).mean())
    black_new=float(((candidate.min(-1)<=1/65535)&(source.min(-1)>1/65535)).mean())
    outside=~authorized_mask
    outside_error=float(np.max(abs(candidate[outside]-source[outside]))) if outside.any() else 0.
    if max(clip_new,black_new)>policy['max_new_clip']:reasons.append('new clipping exceeds frozen bound')
    if outside_error>policy['outside_tolerance']:reasons.append('unauthorized pixels changed')
    return {'pass':not reasons,'reasons':reasons,'new_white_clip':clip_new,'new_black_clip':black_new,'outside_error':outside_error}

EDGE_REVIEW_PROTOCOL='native_edge_visual_v2'

def native_checks(source,candidate,policy,authorized_mask,edit_masks,domain=None):
    domain=resolve_domain(domain)
    result=hard_checks(source,candidate,policy,authorized_mask)
    if source.shape!=candidate.shape or not np.isfinite(candidate).all():return result
    # Holdout checks not included in the optimization score: detail energy and mask boundary jumps.
    ya=luminance(source,domain);yc=luminance(candidate,domain)
    energy=lambda x:sum(float(np.mean(abs(np.diff(x,axis=i)))) if x.shape[i]>1 else 0 for i in (0,1))
    ea,ec=energy(ya),energy(yc);ratio=ec/ea if ea>1e-8 else None
    if ratio is not None and not policy['detail_ratio'][0]<=ratio<=policy['detail_ratio'][1]:result['reasons'].append('native detail energy outside frozen interval')
    edge_jump=0.;raw_edge_jump=0.;maximum=None;warnings=[]
    review_required=policy.get('edge_policy')==EDGE_REVIEW_PROTOCOL
    delta=yc-ya
    for mask_id,m in sorted(edit_masks.items()):
        mask_maximum=None
        for axis in (0,1):
            edge=abs(np.diff(m,axis=axis))>1e-5
            if edge.any():
                source_gradient=abs(np.diff(ya,axis=axis));output_gradient=abs(np.diff(yc,axis=axis))
                # Preserve the original proxy and threshold. It cannot establish causality:
                # content edges and low-confidence probability tails can trigger it.
                supported=(~edge)&(source_gradient>1e-5)
                gain=float(np.median(output_gradient[supported]/source_gradient[supported])) if supported.any() else 1.
                gain=float(np.clip(gain,.25,4.))
                excess=np.maximum(0.,output_gradient-gain*source_gradient)
                value=float(excess[edge].max());edge_jump=max(edge_jump,value)
                raw_edge_jump=max(raw_edge_jump,float(abs(np.diff(delta,axis=axis))[edge].max()))
                if review_required and (mask_maximum is None or value>mask_maximum['excess']):
                    y,x=map(int,np.unravel_index(np.argmax(np.where(edge,excess,-1.)),edge.shape))
                    yn,xn=y+(axis==0),x+(axis==1)
                    h,w=m.shape;x0=max(0,min(x-256,w-512));y0=max(0,min(y-256,h-512))
                    mask_maximum={'mask_id':mask_id,'axis':axis,'x':x,'y':y,'neighbor_xy':[xn,yn],
                                  'excess':value,'threshold':policy['max_edge_jump'],
                                  'source_gradient':float(source_gradient[y,x]),'candidate_gradient':float(output_gradient[y,x]),
                                  'nonboundary_median_gain':gain,'mask_values':[float(m[y,x]),float(m[yn,xn])],
                                  'edge_coverage_fraction':float(edge.mean()),'crop_xyxy':[x0,y0,min(w,x0+512),min(h,y0+512)]}
        if mask_maximum is not None:
            if maximum is None or mask_maximum['excess']>maximum['excess']:maximum=mask_maximum
            if mask_maximum['excess']>policy['max_edge_jump']:warnings.append(mask_maximum)
    if edge_jump>policy['max_edge_jump'] and not review_required:result['reasons'].append('native mask edge jump exceeds bound')
    result.update(detail_ratio=ratio,edge_jump=edge_jump,raw_mask_delta_jump=raw_edge_jump,checked_mask_ids=sorted(edit_masks),edge_metric='excess luminance gradient over source gradient with median nonboundary gain; heuristic, not visual proof');result['pass']=not result['reasons']
    if review_required:
        candidate_hash=array_hash(candidate)
        warnings=[dict(w,id=f'edge-{w["mask_id"]}-{w["axis"]}-{w["x"]}-{w["y"]}-{candidate_hash[:12]}',candidate_sha256=candidate_hash,
                       requirement='Inspect paired A/C native crops. Explicit pass required; missing, fail or uncertain cannot be safe.') for w in warnings]
        result.update(edge_review_protocol=EDGE_REVIEW_PROTOCOL,edge_warnings=warnings,edge_maximum=maximum,
                      edge_warning_threshold=policy['max_edge_jump'])
    if domain.id!='srgb':result['color_domain']=domain.identity
    return result

def validate_visual(receipt,contract,source,reference,candidate,edge_warnings=None):
    strict(receipt,{'contract_sha256','source_sha256','reference_sha256','candidate_sha256','observer','target_results','content','naturalness','reference_match','native_inspected','notes','preservation_checks'} | ({'edge_reviews'} if edge_warnings is not None else set()))
    require(receipt['contract_sha256']==contract.sha256 and receipt['source_sha256']==array_hash(source) and receipt['reference_sha256']==array_hash(reference) and receipt['candidate_sha256']==array_hash(candidate),'visual receipt binding mismatch')
    require(isinstance(receipt['observer'],str) and receipt['observer'].strip(),'attributed visual review required')
    require(type(receipt['native_inspected']) is bool and isinstance(receipt['notes'],str),'review fields')
    for key in ('content','naturalness','reference_match'):require(receipt[key] in ('pass','fail','uncertain'),'invalid visual outcome')
    targets={t['id'] for t in contract.data['targets']};rows=receipt['target_results']
    require(isinstance(rows,list) and len(rows)==len(targets) and {r['id'] for r in rows}==targets,'every frozen target needs visual result')
    for r in rows:
        strict(r,{'id','status','observation'});require(r['status'] in ('achieved','partial','unmet','uncertain') and isinstance(r['observation'],str) and r['observation'].strip(),'target review')
    checks=receipt['preservation_checks'];protected=set(contract.data['protected_properties'])
    require(isinstance(checks,list) and len(checks)==len(protected) and {r['item'] for r in checks}==protected,'every protected property needs an independent check')
    for row in checks:
        strict(row,{'item','status','observation'});require(row['status'] in ('pass','fail','uncertain') and isinstance(row['observation'],str) and row['observation'].strip(),'invalid protection check')
    if edge_warnings is not None:
        expected={w['id'] for w in edge_warnings};reviews=receipt['edge_reviews']
        require(all(w['candidate_sha256']==receipt['candidate_sha256'] for w in edge_warnings),'edge warning candidate binding mismatch')
        require(isinstance(reviews,list) and len(reviews)==len(expected) and all(isinstance(r,dict) for r in reviews)
                and {r.get('warning_id') for r in reviews}==expected,'every edge warning needs exactly one explicit review')
        for row in reviews:
            strict(row,{'warning_id','status','observation'})
            require(row['status'] in ('pass','fail','uncertain') and isinstance(row['observation'],str) and row['observation'].strip(),'invalid edge warning review')
    return receipt

def safe_visual(visual,edge_warnings=None):
    """Safety is affirmative evidence, independently of target completion."""
    if edge_warnings is not None:
        expected={w['id'] for w in edge_warnings};reviews=(visual or {}).get('edge_reviews')
        if not (isinstance(reviews,list) and len(reviews)==len(expected)
                and all(isinstance(r,dict) and r.get('status')=='pass' and isinstance(r.get('observation'),str) and r['observation'].strip() for r in reviews)
                and {r.get('warning_id') for r in reviews}==expected):return False
    elif visual and 'edge_reviews' in visual and any(r.get('status')!='pass' for r in visual['edge_reviews']):return False
    return bool(visual and visual.get('native_inspected') is True
                and visual.get('content')=='pass' and visual.get('naturalness')=='pass'
                and bool(visual.get('preservation_checks'))
                and all(r['status']=='pass' for r in visual['preservation_checks']))

def active_local_masks(plan,values,masks):
    from .planner import coordinates,instantiate
    operations=instantiate(plan,values);active=set()
    for (index,key,spec,neutral),value in zip(coordinates(plan),values):
        if value!=neutral and operations[index]['mask_id'] is not None:active.add(operations[index]['mask_id'])
    return {key:masks[key] for key in sorted(active)}

def accepted(rows,visual,edge_warnings=None):
    if not safe_visual(visual,edge_warnings):return False
    if any(visual[k]!='pass' for k in ('content','naturalness','reference_match')):return False
    if any(r['status']!='pass' for r in visual['preservation_checks']):return False
    judged={r['id']:r['status'] for r in visual['target_results']}
    return all(not r['mandatory'] or ((r['kind'] in ('perceptual','protection') or r['status']=='achieved') and judged.get(r['id'])=='achieved') for r in rows)
