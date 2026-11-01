"""VLM discovery, pixel-grounded bilateral correspondence and measured diagnosis.

No operator-provided labels/pairs/targets are required on the explicit auto route.
Model output never becomes a mask: masks must come from the real SAM3 runner.
"""
from copy import deepcopy
from pathlib import Path
import numpy as np
from .contracts import strict,canonical
from .color import require,ColorContext,digest_bytes
from .evidence import build_pairs,pair_manifest
from .providers import StructuredProvider
from .trace import StageTrace,provider_source
from ..storage import read_json,write_json

DIMENSIONS={'neutral_balance','chroma_by_hue','skin_rendering','shadow_midtone_highlight','highlight_transition','local_contrast','subject_background_balance','texture_and_noise_observation'}

def text_list(v):return isinstance(v,list) and all(isinstance(x,str) and x.strip() for x in v)

def validate_discovery(value):
    strict(value,{'labels','source_observations','reference_observations','protected_properties','uncertainties'})
    require(text_list(value['labels']) and 1<=len(value['labels'])<=12 and len(set(value['labels']))==len(value['labels']),'discovery needs unique bounded semantic vocabulary')
    for key in ('source_observations','reference_observations','protected_properties','uncertainties'):require(text_list(value[key]),'discovery text arrays')
    require(value['protected_properties'],'discovery must identify source protections')
    return deepcopy(value)

def validate_correspondence(value,masks):
    strict(value,{'regions','uncertainties'})
    require(text_list(value['uncertainties']) and isinstance(value['regions'],list) and 1<=len(value['regions'])<=6,'bounded correspondence')
    seen=set()
    for r in value['regions']:
        strict(r,{'id','a_mask','b_mask','semantic','comparability','reasons'})
        require(isinstance(r['id'],str) and r['id'] and r['id'] not in seen,'correspondence identity');seen.add(r['id'])
        require(r['a_mask'] in masks and masks[r['a_mask']]['side']=='A' and r['b_mask'] in masks and masks[r['b_mask']]['side']=='B','correspondence must cite actual bilateral masks')
        require(r['comparability'] in ('comparable','partially_comparable','not_comparable') and text_list(r['reasons']) and r['reasons'] and isinstance(r['semantic'],str) and r['semantic'],'explicit comparability evidence required')
    return [{**r,'provenance':'automatic'} for r in value['regions']]

def prepare_automatic(config,base,out,provider=None,segment_runner=None):
    from .segmentation import schedule_bilateral
    auto=config['automatic_diagnosis'];strict(auto,{'provider','user_goal'})
    require(isinstance(auto['user_goal'],str) and auto['user_goal'].strip(),'original user goal required')
    require(not config['masks'] and not config['regions'] and not config['segmentation']['labels'] and not config['segmentation']['regions'],'automatic route cannot be prefilled with labels, masks or correspondence')
    require(config['policy']['limits']['vlm']>=4,'automatic diagnosis requires discovery/correspondence/diagnosis/contract calls')
    out=Path(out);out.mkdir(parents=True,exist_ok=True);binding=out/'preprocess_binding.json'
    if binding.exists():require(canonical(read_json(binding))==canonical(config),'automatic preprocessing config changed')
    else:write_json(binding,config)
    provider=provider or StructuredProvider(out/'semantic_vlm',auto['provider'])
    journal=StageTrace(out);images={};colors={}
    for side,role in [('A','source'),('B','reference')]:
        p=(Path(base)/config[role]['path']).resolve()
        require(digest_bytes(p.read_bytes())==config[role]['sha256'],'automatic diagnosis source hash')
        images[side],color=ColorContext.load(p,config[role]['assume_srgb'])
        from dataclasses import asdict
        colors[side]=asdict(color)
    journal.record('input_color_audit',{'source':config['source'],'reference':config['reference']},{'color_contexts':colors,'images':images},change='按EXIF转正并按ICC转换工作域；原图保留，不是风格编辑',impact='后续分析和分割使用规范工作像素',image_changed=True)
    def ask(stage,context,views):
        return journal.call(stage,lambda:provider(stage,context,views),{'context':context,'images':views},source=provider_source(provider),change='新增实际视觉结构化输出；图像未改变',impact='必须通过阶段校验才用于下一步')
    discovered=validate_discovery(ask('discover_regions',{'user_goal':auto['user_goal'],'source_sha256':config['source']['sha256'],'reference_sha256':config['reference']['sha256']},images))
    seg=deepcopy(config['segmentation']);seg['labels']=discovered['labels']
    generated=journal.call('segmentation',lambda:schedule_bilateral(config,seg,base,out/'segmentation',runner=segment_runner,allow_unpaired=True),{'configuration':seg,'images':images},source='test_double' if segment_runner is not None else 'SAM3_cpu',change='新增双侧真实像素mask与来源回执；源图未编辑',impact='对应判断只能引用这些实际mask')
    views={k:v.copy() for k,v in images.items()};arrays={}
    for name,spec in generated['masks'].items():
        mask=np.load(spec['path'],allow_pickle=False);arrays[name]=mask
        image=images[spec['side']];require(mask.shape==image.shape[:2],'discovery mask shape')
        # Actual coverage overlay, not model-drawn boxes. Both full view and ROI crop are provided.
        views['mask '+name]=image*(.2+.8*mask[...,None])
        ys,xs=np.where(mask>=.5)
        if len(xs):views['region '+name]=image[ys.min():ys.max()+1,xs.min():xs.max()+1]
    response=ask('correspond_regions',{'user_goal':auto['user_goal'],'discovery':discovered,'catalog':generated['catalog'],
                    'restriction':'SAM3 merges instances by label. Same label does not prove same instance/illumination; mark partial or not comparable when uncertain.'},views)
    regions=validate_correspondence(response,generated['masks'])
    pairs=build_pairs(images['A'],images['B'],regions,arrays,**config['support_policy'])
    effective=deepcopy(config);effective.pop('automatic_diagnosis');effective.pop('segmentation')
    effective['masks']=generated['masks'];effective['regions']=regions
    # Editing scopes are derived from actual A masks; planner can choose them, never evaluation ROIs.
    require(not effective['edit_masks'],'automatic route derives edit scopes; operator must not prefill model region IDs')
    effective['edit_masks']={p['id']:{'source_mask':p['a_mask'],'feather_native':0.,'density':1.,'luminance_range':None} for p in regions}
    audit={'mode':'vlm_automatic','user_goal':auto['user_goal'],'discovery':discovered,'correspondence':response,'region_pairs':pair_manifest(pairs),
           'segmentation_receipts':generated['receipts'],'vlm_calls':2,'simulation':provider.simulation or generated['simulation']}
    write_json(out/'automatic_diagnosis.json',audit)
    return effective,audit

def validate_measured_diagnosis(value,observations,pairs,prior_protections=()):
    strict(value,{'deltas','coverage','protected_properties','uncertainties','summary'})
    require(text_list(value['protected_properties']) and value['protected_properties'] and set(prior_protections)<=set(value['protected_properties']),'diagnosis dropped discovered source protection')
    require(text_list(value['uncertainties']) and isinstance(value['summary'],str) and value['summary'],'diagnosis explanation')
    require(isinstance(value['deltas'],list) and len(value['deltas'])<=32,'diagnosis delta cap')
    ids=set();regions={p['id']:p for p in pairs}
    for d in value['deltas']:
        strict(d,{'id','dimension','regions','evidence_ids','interpretation','transfer','uncertainty'})
        require(isinstance(d['id'],str) and d['id'] and d['id'] not in ids,'delta identity');ids.add(d['id'])
        require(d['dimension'] in DIMENSIONS and isinstance(d['regions'],list) and d['regions'] and set(d['regions'])<=regions.keys(),'delta dimension/region')
        require(isinstance(d['evidence_ids'],list) and d['evidence_ids'] and set(d['evidence_ids'])<=observations.keys(),'delta actual measurement evidence')
        require(all(observations[e]['region'] in d['regions'] for e in d['evidence_ids']) and {'a','b'}<={observations[e]['role'] for e in d['evidence_ids']},'delta needs relevant bilateral evidence')
        require(d['transfer'] in ('target','preserve','exclude','uncertain') and isinstance(d['interpretation'],str) and d['interpretation'] and isinstance(d['uncertainty'],str),'delta interpretation')
        if any(regions[r]['comparability']!='comparable' for r in d['regions']):require(d['uncertainty'].strip(),'weak correspondence uncertainty cannot disappear')
    coverage=value['coverage'];require(isinstance(coverage,list) and len(coverage)==len(DIMENSIONS) and {r['dimension'] for r in coverage}==DIMENSIONS,'diagnosis must account for all eight appearance dimensions')
    linked=set()
    for r in coverage:
        strict(r,{'dimension','status','delta_ids','reason'})
        require(r['status'] in ('targeted','preserve','excluded','uncertain','not_applicable') and isinstance(r['reason'],str) and r['reason'],'coverage reason')
        require(isinstance(r['delta_ids'],list) and set(r['delta_ids'])<=ids and (r['status']!='targeted' or r['delta_ids']),'coverage refs')
        require(all(d['dimension']==r['dimension'] for d in value['deltas'] if d['id'] in r['delta_ids']),'coverage dimension mismatch')
        linked.update(r['delta_ids'])
    require(linked==ids,'diagnosed difference omitted from coverage')
    return deepcopy(value)
