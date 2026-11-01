"""Frozen evaluation identities, genuine C supports and full-precision ABC facts."""
from copy import deepcopy
from io import BytesIO
import numpy as np
from hre.models import sha256_bytes,file_sha256
from hre.storage import case_lock
from .contracts import exact,require,digest,identifier
from .s2_evidence import code,save_array,load_array,_bbox
from .s2_measure import _analysis,_distribution
from . import coordinator as co,s2_store as store,s4_selected as selected


def _response(root,state,rid):
    values=[co._load(root,x['record_path'],'response') for x in state['payload']['results']]
    matches=[r for r in values if r['record_id']==rid]
    require(len(matches)==1 and matches[0]['payload'].get('edit_binding') is not None,'registered generated C required, not fallback A')
    return matches[0]


def _candidate(root,state,response_id,derived_id):
    response=_response(root,state,response_id);derived=store.by_id(root,state,'candidate_derivatives',derived_id);d=derived['payload']
    require(d['response_record_id']==response_id and d['response_hash']==response['content_hash']
            and d['raw_candidate_hash']==response['payload']['candidate_hash'],'candidate/selected derivative mismatch')
    return response,derived


def freeze_version(root,spec):
    exact(spec,('version','target_version','predecessor','reason_code','coordinate_rule_version','numeric_rule_version'))
    code(spec['version'],'q');code(spec['target_version'],'v')
    require(spec['coordinate_rule_version']=='whole_semantic_C_v1' and spec['numeric_rule_version']=='ABC_signed_residual_v1','unsupported evaluation rules')
    with case_lock(root):
        state=co._status(root);versions=store.registry(state)['evaluation_versions']
        require(spec['version'] not in versions,'evaluation version immutable')
        target=store.get(root,state,'targets',spec['target_version']);t=target['payload']
        if not versions:require(spec['version']=='q1' and spec['predecessor'] is None and spec['reason_code']=='initial','initial evaluation version must be q1')
        else:
            previous=spec['predecessor'];exact(previous,('version','hash'));code(previous['version'],'q');digest(previous['hash'])
            latest=max(versions,key=lambda v:int(v[1:]));old=store.get(root,state,'evaluation_versions',latest)
            require(previous=={'version':latest,'hash':old['content_hash']} and spec['version']=='q'+str(int(latest[1:])+1),'evaluation revision must extend latest version')
            require(spec['reason_code'] in ('target_revision','corrected_evidence','diagnosis_correction'),'explicit factual evaluation revision reason required')
            if target['content_hash']!=old['payload']['target_hash']:
                require(spec['reason_code']=='target_revision' and t['revision']['predecessor_hash']==old['payload']['target_hash'],'target revision lineage mismatch')
        return store.put(root,state,'evaluation_versions',spec['version'],'evaluation_version',dict(**deepcopy(spec),
            candidate_measurement_basis=selected.BASIS,target_hash=target['content_hash'],report_id=t['report_id'],report_hash=t['report_hash'],snapshot_id=t['snapshot_id'],snapshot_hash=t['snapshot_hash'],assets=[]))


def freeze_supports(root,spec):
    exact(spec,('support_id','version','candidate_record_id','derived_record_id','candidate_hash','coordinate_image_hash','coordinate_frame','size','global_comparability','review','regions'))
    code(spec['support_id'],'k');code(spec['version'],'q');digest(spec['candidate_hash']);digest(spec['coordinate_image_hash'])
    require(spec['coordinate_frame']=='oriented_C' and isinstance(spec['size'],list) and len(spec['size'])==2 and all(type(v)is int and v>0 for v in spec['size']),'explicit C coordinate grid required')
    require(spec['global_comparability'] in ('comparable','mixed','unknown') and isinstance(spec['regions'],list),'invalid C support assessment')
    exact(spec['review'],('path','sha256','source'));exact(spec['review']['source'],('tool','version','origin'))
    source=spec['review']['source'];require(isinstance(source['tool'],str) and source['tool'].strip() and (source['version'] is None or isinstance(source['version'],str)),'review source identity required')
    require(source['origin'] in ('actual_tool','manual_review','synthetic_fixture'),'unknown C support review origin')
    digest(spec['review']['sha256']);proof=co._read_output(spec['review']['path']);require(sha256_bytes(proof)==spec['review']['sha256'],'actual support review artifact hash mismatch')
    with case_lock(root):
        state=co._status(root);require(state['payload']['active_attempt'] is None,'support freeze during active request is forbidden')
        require(state['payload']['purpose']=='protocol_fixture' or source['origin']!='synthetic_fixture','synthetic support review cannot satisfy real evidence')
        profile=store.get(root,state,'evaluation_versions',spec['version']);response,derived=_candidate(root,state,spec['candidate_record_id'],spec['derived_record_id']);d=derived['payload'];audit=d['audit']
        require(audit is not None and spec['candidate_hash']==d['raw_candidate_hash'] and spec['coordinate_image_hash']==audit['derivative_file_hash'] and spec['size']==audit['oriented_size'],'C raw/derived/grid binding mismatch')
        require(spec['support_id'] not in store.registry(state)['candidate_supports'],'support identity frozen')
        for key in store.registry(state)['candidate_supports']:
            old=store.get(root,state,'candidate_supports',key)['payload']
            require((old['candidate_record_id'],old['version'])!=(spec['candidate_record_id'],spec['version']),'one support set per candidate/evaluation version; revise explicitly')
        report=store.get(root,state,'reports',profile['payload']['report_id'])['payload'];expected=set(report['regions'])-{'g0'}
        require(all(isinstance(r,dict) and isinstance(r.get('region_id'),str) for r in spec['regions']),'typed C region refs required')
        require(len(spec['regions'])==len(expected) and {r['region_id'] for r in spec['regions']}==expected,'all frozen whole regions required; no favorable subset or new subdivisions')
        w,h=spec['size'];regions={};arrays={};raw_assets={}
        for r in spec['regions']:
            exact(r,('region_id','mode','asset_path','asset_sha256','mapping','correspondence','coverage','occlusion'));rid=r['region_id'];code(rid,'r')
            require(r['mode'] in ('actual_mask','checked_A_mapping','unavailable') and r['correspondence'] in ('confirmed','uncertain','unmatched')
                    and r['coverage'] in ('complete_comparable','mixed','unknown') and r['occlusion'] in ('none_observed','partial','unknown'),'invalid typed C support assessment')
            if r['asset_path'] is not None:require(isinstance(r['asset_path'],str),'invalid mask path')
            if r['asset_sha256'] is not None:digest(r['asset_sha256'])
            mapping=r['mapping'];outside=0;mask=None
            if mapping is not None:
                exact(mapping,('kind','offset','source_size','target_size','checked_against_C'))
                require(mapping['kind'] in ('identity','integer_translation') and mapping['checked_against_C'] is True,'mapping must be explicitly checked against C, not inferred from size')
                require(all(isinstance(mapping[k],list) and len(mapping[k])==2 and all(type(v)is int for v in mapping[k]) for k in ('offset','source_size','target_size')),'typed mapping dimensions/offset required')
                require(mapping['kind']!='identity' or mapping['offset']==[0,0],'identity cannot translate')
            if r['mode']=='actual_mask':
                require(r['asset_path'] is not None and r['asset_sha256'] is not None and mapping is None,'actual C mask needs asset and no A mapping')
                raw=co._read_output(r['asset_path']);require(sha256_bytes(raw)==r['asset_sha256'] and raw.startswith(b'\x93NUMPY'),'C mask hash/type mismatch')
                mask=np.load(BytesIO(raw),allow_pickle=False)
                require(isinstance(mask,np.ndarray) and mask.shape==(h,w) and mask.dtype.kind in 'buif' and np.isfinite(mask).all() and np.isin(mask,[0,1]).all(),'invalid binary C mask')
                mask=mask.astype(bool);raw_assets[rid]=raw
            elif r['mode']=='checked_A_mapping':
                require(r['asset_path'] is None and r['asset_sha256'] is None and mapping is not None,'checked mapping cannot hide another mask')
                a=co._load(root,'input_audit.json')['payload']['images'][0]
                require(mapping['source_size']==a['oriented_size'] and mapping['target_size']==[w,h] and 'A' in report['regions'][rid]['support_paths'],'mapping grid/A support mismatch')
                original=load_array(root,report['regions'][rid]['support_paths']['A']);ys,xs=np.where(original);dx,dy=mapping['offset'];xs=xs+dx;ys=ys+dy
                inside=(xs>=0)&(xs<w)&(ys>=0)&(ys<h);outside=int((~inside).sum());mask=np.zeros((h,w),bool);mask[ys[inside],xs[inside]]=True
            else:require(r['asset_path'] is None and r['asset_sha256'] is None and mapping is None,'unavailable support cannot carry hidden asset/mapping')
            count=0 if mask is None else int(mask.sum());fraction=count/(w*h);old=report['regions'][rid]
            eligible='numeric_eligible' if count and outside==0 and old['eligibility']=='numeric_eligible' and d['status']=='standardized' and r['correspondence']=='confirmed' and r['coverage']=='complete_comparable' and r['occlusion']=='none_observed' else 'visual_direction_only'
            if count==0 or r['correspondence']=='unmatched':eligible='insufficient_evidence'
            regions[rid]={k:r[k] for k in ('region_id','mode','correspondence','coverage','occlusion','mapping')}
            regions[rid].update(semantic_class=old['semantic_class'],coverage_pixels=count,coverage_denominator=w*h,coverage_fraction=fraction,
                A_coverage_fraction=old['coverage']['A']['fraction'],B_coverage_fraction=old['coverage']['B']['fraction'],
                mapped_outside_pixels=outside,bbox=None if mask is None else _bbox(mask),eligibility=eligible,support_path=None)
            arrays[rid]=mask
        # Preserve the frozen hierarchy rather than allow independent overlapping C regions.
        def ancestor(rid,other):
            parent=report['regions'][rid]['parent_id']
            while parent is not None:
                if parent==other:return True
                parent=report['regions'][parent]['parent_id']
            return False
        for rid,mask in arrays.items():
            if mask is None:continue
            for other,outer in arrays.items():
                if outer is None or other==rid:continue
                if ancestor(rid,other):require(not np.any(mask & ~outer),'C child outside frozen semantic parent')
                elif not ancestor(other,rid):require(not np.any(mask & outer),'independent C support overlap is not permitted')
        prefix='s4/support_assets/'+spec['support_id'];co._path(root,prefix).mkdir(parents=True,exist_ok=False);assets=[]
        co._immutable_bytes(root,prefix+'/review.bin',proof);assets.append({'path':prefix+'/review.bin','sha256':sha256_bytes(proof)})
        for rid,mask in arrays.items():
            if mask is not None:
                path=prefix+'/'+rid+'.npy';assets.append(save_array(root,path,mask));regions[rid]['support_path']=path
            if rid in raw_assets:
                path=prefix+'/'+rid+'_raw.npy';co._immutable_bytes(root,path,raw_assets[rid]);assets.append({'path':path,'sha256':sha256_bytes(raw_assets[rid])})
        return store.put(root,state,'candidate_supports',spec['support_id'],'candidate_support',dict(
            support_id=spec['support_id'],version=spec['version'],profile_hash=profile['content_hash'],candidate_record_id=response['record_id'],
            derived_record_id=derived['record_id'],derived_hash=derived['content_hash'],candidate_hash=d['raw_candidate_hash'],coordinate_image_hash=spec['coordinate_image_hash'],
            coordinate_frame='oriented_C',size=[w,h],global_comparability=spec['global_comparability'],regions=regions,
            review_source=deepcopy(source),review_sha256=sha256_bytes(proof),assets=assets,semantic_verification='caller_attested_whole_region_review_not_remote_authenticated'))


def evaluate(root,spec):
    exact(spec,('evaluation_id','version','candidate_record_id','derived_record_id','support_id','reevaluation'));code(spec['evaluation_id'],'j');code(spec['version'],'q')
    if spec['support_id'] is not None:code(spec['support_id'],'k')
    with case_lock(root):
        state=co._status(root);require(state['payload']['active_attempt'] is None,'resolve active attempt before evaluation')
        require(spec['evaluation_id'] not in store.registry(state)['evaluations'],'evaluation immutable')
        profile=store.get(root,state,'evaluation_versions',spec['version']);q=profile['payload']
        require(q.get('candidate_measurement_basis')==selected.BASIS,'legacy evaluation profile requires explicit new factual version')
        response,derived=_candidate(root,state,spec['candidate_record_id'],spec['derived_record_id']);d=derived['payload']
        history=[store.get(root,state,'evaluations',key) for key in store.registry(state)['evaluations']]
        previous=[v for v in history if v['payload']['candidate_record_id']==response['record_id']]
        require(not any(v['payload']['version']==spec['version'] for v in previous),'candidate already evaluated under this version')
        if previous or response['payload']['target_hash']!=q['target_hash']:
            ref=spec['reevaluation'];exact(ref,('previous_evaluation_id','previous_hash','reason_code'))
            old=store.get(root,state,'evaluations',ref['previous_evaluation_id'])
            require(old['payload']['candidate_record_id']==response['record_id'] and old['content_hash']==ref['previous_hash']
                    and q['predecessor'] is not None and old['payload']['version']==q['predecessor']['version'],'reevaluation predecessor mismatch')
            require(ref['reason_code']==q['reason_code'],'reevaluation reason must match version lineage')
        else:require(spec['reevaluation'] is None,'unexpected reevaluation reference')
        report=store.get(root,state,'reports',q['report_id']);require(report['content_hash']==q['report_hash'],'evaluation AB report changed')
        support=None if spec['support_id'] is None else store.get(root,state,'candidate_supports',spec['support_id'])
        if support is not None:require(support['payload']['candidate_record_id']==response['record_id'] and support['payload']['derived_hash']==derived['content_hash'] and support['payload']['profile_hash']==profile['content_hash'],'candidate support binding mismatch')
        audit=d['audit'];native_arrays=None if audit is None else _analysis(root,audit)
        artifact,arrays,selected_assets=selected.analyze_selected(root,derived,spec['evaluation_id'])
        sp=None if support is None else support['payload'];distributions={};native_distributions={};eligibility={}
        for rid,region in report['payload']['regions'].items():
            mask=None
            if rid=='g0' and audit is not None:mask=np.ones(tuple(audit['oriented_size'][::-1]),bool)
            elif sp is not None and sp['regions'][rid]['support_path'] is not None:mask=load_array(root,sp['regions'][rid]['support_path'])
            eligibility[rid]=('numeric_eligible' if sp is not None and sp['global_comparability']=='comparable' and d['status']=='standardized' and region['eligibility']=='numeric_eligible' else 'visual_direction_only') if rid=='g0' else ('insufficient_evidence' if sp is None else sp['regions'][rid]['eligibility'])
            distributions[rid]={metric:_distribution(None if arrays is None else arrays[metric],mask) for metric in ('linear_Y','L_star','a_star','b_star','chroma')}
            native_distributions[rid]={metric:_distribution(None if native_arrays is None else native_arrays[metric],mask) for metric in ('linear_Y','L_star','a_star','b_star','chroma')}
        rows=[]
        for original in report['payload']['measurements']:
            m=deepcopy(original);rid=m['subject_id'];metric=m['metric'];stat=m['statistic'];operands=None
            if m['kind']=='relation':
                left,right=m['left_region_id'],m['right_region_id'];lv=(distributions[left][metric]['values'] or {}).get(stat);rv=(distributions[right][metric]['values'] or {}).get(stat)
                C=None if lv is None or rv is None else lv-rv;operands={'left':lv,'right':rv};ok=all(eligibility[x]=='numeric_eligible' for x in (left,right))
            else:C=(distributions[rid][metric]['values'] or {}).get(stat);ok=eligibility[rid]=='numeric_eligible'
            m.update(C=C,C_operands=operands,C_minus_B=None if C is None or m['B'] is None else C-m['B'],C_minus_A=None if C is None or m['A'] is None else C-m['A'],
                baseline_absolute_residual=None if m['A'] is None or m['B'] is None else abs(m['A']-m['B']),candidate_absolute_residual=None if C is None or m['B'] is None else abs(C-m['B']),
                eligibility='numeric_eligible' if ok and C is not None and m['eligibility']=='numeric_eligible' else 'visual_direction_only',numeric_achievement='uncalibrated')
            m['absolute_improvement']=None if m['baseline_absolute_residual'] is None or m['candidate_absolute_residual'] is None else m['baseline_absolute_residual']-m['candidate_absolute_residual'];rows.append(m)
        return store.put(root,state,'evaluations',spec['evaluation_id'],'candidate_evaluation',dict(
            evaluation_id=spec['evaluation_id'],version=spec['version'],profile_hash=profile['content_hash'],candidate_record_id=response['record_id'],response_hash=response['content_hash'],
            raw_candidate_hash=d['raw_candidate_hash'],derived_record_id=derived['record_id'],derived_hash=derived['content_hash'],
            generation_target_version=response['payload']['target_version'],generation_target_hash=response['payload']['target_hash'],
            evaluation_target_version=q['target_version'],evaluation_target_hash=q['target_hash'],report_id=q['report_id'],report_hash=q['report_hash'],snapshot_hash=q['snapshot_hash'],
            support_id=spec['support_id'],support_hash=None if support is None else support['content_hash'],reevaluation=deepcopy(spec['reevaluation']),
            measurements=rows,C_distributions=distributions,assets=selected_assets,selected_artifact=artifact,candidate_measurement_basis=selected.BASIS,
            native_C_diagnostics=dict(basis='raw_decoded_before_output_clipping_quantization_not_acceptance',raw_candidate_hash=d['raw_candidate_hash'],
                analysis_path=None if audit is None else audit['analysis_path'],analysis_file_hash=None if audit is None else audit['analysis_file_hash'],distributions=native_distributions),
            numeric_rule_version=q['numeric_rule_version'],coordinate_rule_version=q['coordinate_rule_version'],style_status='not_evaluated',spatial_correspondence='not_inferred_from_size'))
