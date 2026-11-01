"""Actual evidence import and frozen whole-region supports, never inference."""
from copy import deepcopy
from io import BytesIO
import json
import re
import numpy as np
from hre.models import sha256_bytes, canonical_json
from hre.storage import case_lock, read_json
from .contracts import exact, require, digest
from .audit import pixel_hash
from . import coordinator as co, s2_store as store

SEMANTICS=('person','face','exposed_skin','hair','clothing','sign','wall','sky','foliage','ground',
           'building','vehicle','water','food','furniture','metal','wood','glass','fabric',
           'other_whole_object','other_whole_material')
METRICS=('linear_Y','L_star','a_star','b_star','chroma')
STATS=('q05','q25','q50','q75','q95','span95_05','mean')


def code(value,prefix):
    require(isinstance(value,str) and re.fullmatch(prefix+r'[1-9][0-9]{0,5}',value), 'invalid typed S2 identifier')


def save_array(root,path,array):
    data=BytesIO();np.save(data,array,allow_pickle=False)
    co._immutable_bytes(root,path,data.getvalue())
    return {'path':path,'sha256':sha256_bytes(data.getvalue())}


def load_array(root,path):
    return np.load(co._path(root,path,True),allow_pickle=False)


def _bbox(mask):
    y,x=np.where(mask)
    return None if len(x)==0 else [int(x.min()),int(y.min()),int(x.max()-x.min()+1),int(y.max()-y.min()+1)]


def _resize(array,size):
    w,h=size
    return array[(np.arange(h)*array.shape[0]//h)[:,None],(np.arange(w)*array.shape[1]//w)[None,:]]


def _entries(raw,kind,size,target):
    # Use the existing strict JSON reader's semantics without accepting duplicate keys.
    def pairs(items):
        result={}
        for k,v in items:
            require(k not in result,'duplicate evidence JSON key');result[k]=v
        return result
    obj=json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,
                   parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite evidence JSON')))
    exact(obj,('entries',));require(isinstance(obj['entries'],list),'entries list required')
    parsed=[]
    for item in obj['entries']:
        exact(item,('text','bbox','confidence') if kind=='ocr' else ('bbox','confidence'))
        b=item['bbox'];require(isinstance(b,list) and len(b)==4 and all(type(x) in (int,float) and np.isfinite(x) for x in b),'invalid bbox')
        x,y,w,h=b;require(x>=0 and y>=0 and w>0 and h>0 and x+w<=size[0] and y+h<=size[1],'bbox outside evidence grid')
        confidence=item['confidence'];require(type(confidence) in (int,float) and 0<=confidence<=1,'invalid confidence')
        scaled=[int(np.floor(x*target[0]/size[0])),int(np.floor(y*target[1]/size[1])),
                int(np.ceil((x+w)*target[0]/size[0])),int(np.ceil((y+h)*target[1]/size[1]))]
        entry={'bbox':[scaled[0],scaled[1],scaled[2]-scaled[0],scaled[3]-scaled[1]],'confidence':confidence}
        if kind=='ocr':
            require(isinstance(item['text'],str) and 0<len(item['text'])<=10000,'invalid OCR text')
            entry['text_sha256']=sha256_bytes(item['text'].encode('utf-8'))
        parsed.append(entry)
    return {'entries':parsed}


def import_evidence(root,manifest,asset_path=None):
    exact(manifest,('evidence_id','role','kind','status','input_file_hash','input_pixel_hash','source',
                    'asset_sha256','coordinate_frame','asset_size','transform','value_semantics','missing_reason'))
    code(manifest['evidence_id'],'e');require(manifest['role'] in ('A','B'),'AB evidence cannot have C or unknown role')
    require(manifest['kind'] in ('segmentation','depth','ocr','face'),'unsupported evidence kind')
    require(manifest['status'] in ('available','unavailable','uncertain'),'invalid evidence status')
    exact(manifest['source'],('tool','version','origin'))
    require(isinstance(manifest['source']['tool'],str) and manifest['source']['tool'].strip(),'tool/source identity required')
    require(manifest['source']['version'] is None or isinstance(manifest['source']['version'],str),'invalid tool version')
    require(manifest['source']['origin'] in ('actual_tool','manual_annotation','synthetic_fixture'),'unknown evidence origin')
    require(manifest['coordinate_frame']=='oriented_input_grid','unsupported coordinate frame; orient explicitly first')
    size=manifest['asset_size'];require(isinstance(size,list) and len(size)==2 and all(type(x)is int and x>0 for x in size) and size[0]*size[1]<=50_000_000,'invalid asset grid')
    exact(manifest['transform'],('method','target_size'));require(manifest['transform']['method'] in ('identity','nearest_grid'),'unsupported coordinate transform')
    target_size=manifest['transform']['target_size']
    require(isinstance(target_size,list) and len(target_size)==2 and all(type(x)is int and x>0 for x in target_size),
            'transform target must be a positive integer grid')
    allowed={'segmentation':('binary_support',),'depth':('near_is_small','near_is_large'),'ocr':('ocr_entries',),'face':('face_boxes',)}
    require(manifest['value_semantics'] in allowed[manifest['kind']],'evidence value semantics mismatch')
    if manifest['status']=='available':require(asset_path is not None and manifest['missing_reason'] is None,'available requires actual asset, not a missing reason')
    else:require(manifest['missing_reason'] in ('not_installed','not_collected','coverage_insufficient','uncertain_correspondence'),'explicit missing/uncertain reason required')
    require(manifest['status']!='unavailable' or asset_path is None,'unavailable cannot attach a fabricated asset')
    with case_lock(root):
        state=co._status(root);require(state['payload']['active_attempt'] is None,'cannot change evidence during active diagnosis')
        require(manifest['evidence_id'] not in store.registry(state)['evidence'],'evidence ID already frozen')
        image=co._load(root,'input_audit.json')['payload']['images'][0 if manifest['role']=='A' else 1]
        require(manifest['input_file_hash']==image['source_file_hash'] and manifest['input_pixel_hash']==image['source_pixel_hash'],'evidence/input role hash mismatch')
        target=image['oriented_size'];require(manifest['transform']['target_size']==target,'transform target differs from audited image')
        require(manifest['transform']['method']!='identity' or size==target,'identity transform size mismatch')
        require(state['payload']['purpose']=='protocol_fixture' or manifest['source']['origin']!='synthetic_fixture','synthetic evidence cannot satisfy a real sample')
        raw=None;array=None;parsed=None
        if asset_path is None:require(manifest['asset_sha256'] is None,'missing asset cannot claim a hash')
        else:
            digest(manifest['asset_sha256']);raw=co._read_output(asset_path)
            require(sha256_bytes(raw)==manifest['asset_sha256'],'actual evidence asset hash mismatch')
            if manifest['kind'] in ('segmentation','depth'):
                require(raw.startswith(b'\x93NUMPY'),'expected one non-pickled NPY array')
                array=np.load(BytesIO(raw),allow_pickle=False)
                require(isinstance(array,np.ndarray) and array.ndim==2 and list(array.shape[::-1])==size and array.dtype.kind in 'buif','invalid evidence array')
                if manifest['kind']=='segmentation':
                    require(np.isfinite(array).all() and np.isin(array,[0,1]).all(),'segmentation support must be binary')
                    array=array.astype(bool)
                else:require(np.isfinite(array).any(),'depth has no finite observations')
                pixels=int(np.count_nonzero(array)) if manifest['kind']=='segmentation' else int(np.isfinite(array).sum())
                array=_resize(array,target)
                parsed={'pixels':pixels,'oriented_pixels':int(np.count_nonzero(array)) if manifest['kind']=='segmentation' else int(np.isfinite(array).sum()),
                        'array_pixel_hash':pixel_hash(array),'bbox':_bbox(array) if manifest['kind']=='segmentation' else None}
            else:parsed=_entries(raw,manifest['kind'],size,target)
        prefix='s2/evidence_assets/'+manifest['evidence_id'];co._path(root,prefix).mkdir(parents=True,exist_ok=False)
        assets=[];oriented_path=None
        if raw is not None:
            path=prefix+'/raw.bin';co._immutable_bytes(root,path,raw);assets.append({'path':path,'sha256':sha256_bytes(raw)})
        if array is not None:
            oriented_path=prefix+'/oriented.npy';assets.append(save_array(root,oriented_path,array))
        return store.put(root,state,'evidence',manifest['evidence_id'],'tool_evidence',
                         {'manifest':deepcopy(manifest),'parsed':parsed,'oriented_path':oriented_path,'assets':assets,
                          'provenance_verification':'caller_attested_not_remote_authenticated'})


def _support(root,role,side,evidence,size):
    if side is None:return None,{'status':'missing','pixels':0,'denominator':size[0]*size[1],'fraction':0.0,'bbox':None},False
    exact(side,('evidence_id','entry_index'));code(side['evidence_id'],'e')
    require(side['evidence_id'] in evidence,'support evidence not in frozen snapshot')
    value=evidence[side['evidence_id']]['payload'];m=value['manifest'];require(m['role']==role,'cannot copy B support into A')
    # Validate supplied references before any missing-data return. Availability is
    # evidence status, not permission to bypass the executable-context contract.
    require(m['kind'] in ('segmentation','ocr','face'),'unsupported support evidence kind')
    index=side['entry_index']
    if m['kind']=='segmentation':require(index is None,'mask has no bbox entry index')
    else:require(index is None or type(index)is int and 0<=index<1_000_000,'invalid bbox support entry index')
    if value['parsed'] is None:return None,{'status':m['status'],'pixels':0,'denominator':size[0]*size[1],'fraction':0.0,'bbox':None},False
    if m['kind']=='segmentation':
        mask=load_array(root,value['oriented_path']).astype(bool);precise=m['status']=='available'
    else:
        require(type(index)is int and index<len(value['parsed']['entries']),'invalid bbox support entry')
        box=value['parsed']['entries'][side['entry_index']]['bbox'];x,y,w,h=box
        mask=np.zeros((size[1],size[0]),bool);mask[y:y+h,x:x+w]=True;precise=False
    count=int(mask.sum());return mask,{'status':m['status'],'pixels':count,'denominator':int(mask.size),'fraction':float(mask.mean()),'bbox':_bbox(mask)},precise


def freeze_supports(root,spec):
    exact(spec,('snapshot_id','evidence_ids','global_comparability','regions','relations','trusted_ocr'))
    code(spec['snapshot_id'],'s');require(spec['global_comparability'] in ('comparable','mixed','unknown'),'invalid global comparability')
    require(all(isinstance(spec[k],list) for k in ('evidence_ids','regions','relations','trusted_ocr')),'snapshot lists required')
    for eid in spec['evidence_ids']:code(eid,'e')
    require(len(set(spec['evidence_ids']))==len(spec['evidence_ids']),'duplicate evidence refs')
    with case_lock(root):
        state=co._status(root);require(state['payload']['active_attempt'] is None,'active attempt freezes evidence')
        require(spec['snapshot_id'] not in store.registry(state)['snapshots'],'snapshot already frozen')
        evidence={eid:store.get(root,state,'evidence',eid) for eid in spec['evidence_ids']}
        images={i['role']:i for i in co._load(root,'input_audit.json')['payload']['images']}
        regions={};masks={};precisions={}
        for item in spec['regions']:
            exact(item,('region_id','semantic_class','A','B','match_status','composition','illumination','parent_id','usage'))
            rid=item['region_id'];code(rid,'r');require(rid not in regions,'duplicate region')
            require(item['semantic_class'] in SEMANTICS,'unsupported whole semantic class')
            require(item['match_status'] in ('confirmed','uncertain','unmatched') and item['composition'] in ('comparable','mixed','unknown') and item['illumination'] in ('comparable','confounded','unknown'),'invalid correspondence assessment')
            require(item['usage'] in ('independent','summary_only'),'invalid overlap usage')
            if item['parent_id'] is not None:code(item['parent_id'],'r')
            coverage={};masks[rid]={};precisions[rid]={}
            for role in ('A','B'):
                masks[rid][role],coverage[role],precisions[rid][role]=_support(root,role,item[role],evidence,images[role]['oriented_size'])
            complete=all(coverage[role]['pixels']>0 for role in ('A','B'))
            eligible='insufficient_evidence' if not complete or item['match_status']=='unmatched' else 'visual_direction_only'
            if complete and item['match_status']=='confirmed' and item['composition']==item['illumination']=='comparable' and all(precisions[rid].values()) and all(i['numeric_status']=='eligible' for i in images.values()):eligible='numeric_eligible'
            normalized={k:item[k] for k in ('region_id','semantic_class','match_status','composition','illumination','parent_id','usage')}
            normalized.update({role:None if item[role] is None else {
                'evidence_id':item[role]['evidence_id'],'entry_index':item[role]['entry_index']} for role in ('A','B')})
            regions[rid]={**normalized,'coverage':coverage,'eligibility':eligible,'support_paths':{}}
        def ancestors(rid):
            seen=set();parent=regions[rid]['parent_id']
            while parent is not None:
                require(parent in regions and parent not in seen and parent!=rid,'invalid/cyclic parent region')
                seen.add(parent);parent=regions[parent]['parent_id']
            return seen
        for rid in regions:
            for parent in ancestors(rid):
                require(regions[parent]['usage']=='summary_only','nested parent must be summary only')
                for role in ('A','B'):
                    child=masks[rid][role];outer=masks[parent][role]
                    if child is not None and outer is not None:require(not np.any(child & ~outer),'child support outside parent')
        ids=list(regions)
        for n,rid in enumerate(ids):
            for other in ids[n+1:]:
                overlap=any(masks[rid][role] is not None and masks[other][role] is not None and np.any(masks[rid][role]&masks[other][role]) for role in ('A','B'))
                require(not overlap or rid in ancestors(other) or other in ancestors(rid),'overlap requires declared hierarchy; no independent double counting')
        relids=set()
        for rel in spec['relations']:
            exact(rel,('relation_id','left','right','metric','statistic'));code(rel['relation_id'],'l')
            code(rel['left'],'r');code(rel['right'],'r')
            require(rel['relation_id'] not in relids and rel['left'] in regions and rel['right'] in regions and rel['left']!=rel['right'],'invalid relation endpoints')
            require(rel['metric'] in METRICS and rel['statistic'] in STATS,'invalid relation measure');relids.add(rel['relation_id'])
        text_protection=[]
        for ref in spec['trusted_ocr']:
            exact(ref,('evidence_id','entry_index'));code(ref['evidence_id'],'e')
            require(ref['evidence_id'] in evidence,'OCR evidence missing')
            ev=evidence[ref['evidence_id']]['payload'];m=ev['manifest'];idx=ref['entry_index']
            require(m['role']=='A' and m['kind']=='ocr' and m['status']=='available' and type(idx)is int and 0<=idx<len(ev['parsed']['entries']),'trusted OCR must reference an actual available A entry')
            text_protection.append({**ref,**ev['parsed']['entries'][idx],'role':'A','trust_basis':'explicit_snapshot_selection'})
        prefix='s2/support_assets/'+spec['snapshot_id'];co._path(root,prefix).mkdir(parents=True,exist_ok=False);assets=[]
        for rid in regions:
            for role in ('A','B'):
                if masks[rid][role] is not None:
                    path=prefix+'/'+rid+'_'+role+'.npy';assets.append(save_array(root,path,masks[rid][role]));regions[rid]['support_paths'][role]=path
        return store.put(root,state,'snapshots',spec['snapshot_id'],'region_snapshot',
            {'snapshot_id':spec['snapshot_id'],'evidence_refs':{k:v['content_hash'] for k,v in evidence.items()},
             'global_comparability':spec['global_comparability'],'regions':regions,'relations':deepcopy(spec['relations']),
             'text_protection':text_protection,'assets':assets,'aggregation_policy':'no_area_weighted_region_total; parents_summary_only'})
