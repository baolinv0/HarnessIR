"""Validated, planned-only offline evidence and immutable case snapshots.

No tool inference or download occurs here. T1–T4 are imported validated bundles.
"""
from pathlib import Path
import copy
import hashlib
import numpy as np


def make_cache_key(contract: dict) -> str:
    from .models import canonical_json, sha256_bytes, validate_schema
    validate_schema('evidence',contract,'/properties/cache_contract')
    return sha256_bytes(canonical_json(contract))


def _immutable(path: Path, value: dict) -> None:
    from .models import canonical_json, HREError
    from .storage import atomic_write
    data=canonical_json(value)
    if path.exists():
        if path.read_bytes()!=data: raise HREError('immutable_conflict',f'immutable artifact conflict: {path.name}')
        return
    atomic_write(path,data)


def _input_binding(asset: dict, candidate_id=None) -> dict:
    return {k:asset[k] for k in ('asset_id','role','sha256','width','height')} | {'candidate_id':candidate_id if asset['role']=='candidate' else None}


def _contract_input(asset: dict) -> dict:
    return dict(role=asset['role'],canonical_sha256=asset['sha256'],width=asset['width'],height=asset['height'])


def _remap(value, mapping: dict):
    from .models import HREError
    if isinstance(value,list):return [_remap(v,mapping) for v in value]
    if isinstance(value,dict):
        out={}
        for k,v in value.items():
            if (k=='asset_id' or k.endswith('_asset_id')) and v is not None:
                if v not in mapping:raise HREError('unmapped_asset',f'unknown asset reference: {v}')
                out[k]=mapping[v]
            elif k.endswith('_asset_ids'):
                if not isinstance(v,list) or any(x not in mapping for x in v):raise HREError('unmapped_asset','unknown asset list reference')
                out[k]=[mapping[x] for x in v]
            else:out[k]=_remap(v,mapping)
        return out
    return value


def annotation_hash(payload: dict, inputs: list[dict], assets: list[dict] | None=None, *, case_root: Path | None=None) -> str:
    """Hash the normalized payload and complete verified artifact-content graph.

    Case asset names do not enter this proof; transitive JSON contents do.
    Cyclic/unknown references are rejected instead of producing partial proofs.
    """
    from .models import canonical_json,sha256_bytes,HREError
    from .assets import validate_asset
    from .storage import read_json
    from .paths import safe_path
    source={a['asset_id']:_contract_input(a) for a in inputs}
    if len(source)!=len(inputs):raise HREError('annotation_reference','duplicate annotation source ID')
    artifacts={a['asset_id']:a for a in assets or []}
    if len(artifacts)!=len(assets or []) or set(source)&set(artifacts):raise HREError('annotation_reference','ambiguous annotation artifact ID')
    contents={}
    for aid,asset in artifacts.items():
        if case_root is None:raise HREError('annotation_root','annotation artifacts require actual case_root')
        validate_asset(asset,case_root)
        if asset['evidence_format']['kind']=='json':contents[aid]=read_json(safe_path(case_root,asset['path'],must_exist=True))
    memo={};visiting=set()

    def normalize(value):
        if isinstance(value,list):return [normalize(v) for v in value]
        if not isinstance(value,dict):return value
        result={}
        for key,item in value.items():
            if (key=='asset_id' or key.endswith('_asset_id')) and item is not None:
                result[key]=reference(item)
            elif key.endswith('_asset_ids'):
                if not isinstance(item,list):raise HREError('annotation_reference','asset reference list must be an array')
                result[key]=[reference(x) for x in item]
            else:result[key]=normalize(item)
        return result

    def reference(aid):
        if not isinstance(aid,str):raise HREError('annotation_reference','asset reference must be a string')
        if aid in source:return source[aid]
        if aid in memo:return memo[aid]
        if aid not in artifacts:raise HREError('annotation_reference','unknown annotation artifact reference')
        if aid in visiting:raise HREError('annotation_cycle','cyclic annotation artifact references are not supported')
        visiting.add(aid)
        asset=artifacts[aid];fmt=asset['evidence_format'];coord=fmt['coordinate_asset_id']
        if coord is not None and coord not in source:raise HREError('annotation_reference','annotation coordinate must identify a declared input')
        descriptor=dict(width=asset['width'],height=asset['height'],kind=fmt['kind'],dtype=fmt['dtype'],value_range=fmt['value_range'],coordinate=source.get(coord))
        if fmt['kind']=='json':descriptor['content_sha256']=sha256_bytes(canonical_json(normalize(contents[aid])))
        else:descriptor['sha256']=asset['sha256']
        visiting.remove(aid);memo[aid]=descriptor
        return descriptor

    normalized=normalize(payload)
    # Bind every declared actual artifact, including transitive and unreferenced
    # metadata; canonical-byte sorting makes input artifact order irrelevant.
    inventory=sorted((reference(aid) for aid in artifacts),key=canonical_json)
    return sha256_bytes(canonical_json(dict(payload=normalized,artifact_inventory=inventory)))


def _validate_native_geometry(record: dict, array: dict) -> None:
    from .models import HREError
    coord=array['evidence_format']['coordinate_asset_id']
    bindings=record['binding']['inputs']
    bound=[b for b in bindings if b['asset_id']==coord]
    if coord is None or len(bound)!=1:raise HREError('array_coordinate','raw array requires exactly one declared input coordinate association')
    binding=bound[0]
    frames=[f for f in record['payload']['coordinate_frames'] if f['asset_id']==coord]
    if len(frames)!=1:raise HREError('array_coordinate','raw array requires exactly one declared source-to-tool frame')
    frame=np.asarray(frames[0]['source_to_tool'],dtype=float)
    geometry=record['cache_contract']['parameters'].get('tool_geometry',{})
    declared=geometry.get(binding['role']) if isinstance(geometry,dict) else None
    if declared is None:
        width,height=binding['width'],binding['height'];expected=np.eye(3)
    else:
        if not isinstance(declared,dict) or set(declared)!={'width','height','source_to_tool'}:raise HREError('array_geometry','invalid frozen native tool geometry')
        width,height=declared['width'],declared['height']
        if type(width)!=int or type(height)!=int or width<1 or height<1:raise HREError('array_geometry','invalid frozen native dimensions')
        expected=np.asarray(declared['source_to_tool'],dtype=float)
        if expected.shape!=(3,3) or not np.isfinite(expected).all():raise HREError('array_geometry','invalid frozen native matrix')
    if (array['width'],array['height'])!=(width,height) or not np.allclose(frame,expected,rtol=0,atol=1e-12):raise HREError('array_geometry','actual array dimensions/frame differ from frozen native geometry')
    if not np.allclose(frame[2],[0,0,1],rtol=0,atol=1e-12) or abs(np.linalg.det(frame))<1e-12:raise HREError('array_geometry','native source-to-tool must be invertible affine geometry')
    corners=np.array([[0,0,1],[binding['width'],0,1],[0,binding['height'],1],[binding['width'],binding['height'],1]]) @ frame.T
    expected_corners=np.array([[0,0],[width,0],[0,height],[width,height]])
    actual=sorted(map(tuple,corners[:,:2]));wanted=sorted(map(tuple,expected_corners))
    if not np.allclose(actual,wanted,rtol=0,atol=1e-9):raise HREError('array_geometry','native frame must represent full declared input geometry')


def validate_record(case_root: Path, record: dict, inputs: list[dict] | None = None) -> None:
    """Validate strict schema, contract/binding, every reference and actual artifact."""
    from .models import validate_schema,HREError
    from .assets import validate_asset
    validate_schema('evidence',record)
    if make_cache_key(record['cache_contract'])!=record['cache_key_sha256']:raise HREError('cache_hash','cache contract hash mismatch')
    if record['tool_id']!=record['cache_contract']['tool_id']:raise HREError('tool_binding','tool differs from contract')
    bindings=record['binding']['inputs'];ids=[x['asset_id'] for x in bindings]
    if len(ids)!=len(set(ids)):raise HREError('asset_binding','duplicate input asset ID')
    if [_contract_input(x) for x in bindings]!=record['cache_contract']['inputs']:raise HREError('asset_binding','binding differs from cache contract')
    if inputs is not None:
        for binding in bindings:
            matches=[a for a in inputs if all(a.get(k)==binding[k] for k in ('asset_id','role','sha256','width','height'))]
            if len(matches)!=1:raise HREError('asset_binding','input has no unique actual asset')
            validate_asset(matches[0],case_root)
            if binding['role']=='candidate':
                candidate=matches[0].get('candidate_binding',{})
                if binding['candidate_id'] is None or candidate.get('case_id')!=record['case_id'] or candidate.get('case_revision')!=record['case_revision']:raise HREError('candidate_binding','candidate evidence must match its own case/revision and candidate ID')
            elif binding['candidate_id'] is not None:raise HREError('candidate_binding','noncandidate input cannot have candidate ID')
    mapping={i:i for i in ids};assets=record['assets']
    for asset in assets:
        if asset['asset_id'] in mapping:raise HREError('asset_binding','evidence asset ID collision')
        mapping[asset['asset_id']]=asset['asset_id']
    _remap(record['payload'],mapping)
    for asset in assets:
        _remap(asset,mapping);validate_asset(asset,case_root)
        if asset['evidence_format']['kind']=='json':
            from .storage import read_json
            from .paths import safe_path
            _remap(read_json(safe_path(case_root,asset['path'],must_exist=True)),mapping)
        coord=asset['evidence_format']['coordinate_asset_id']
        if coord is not None and coord not in ids:raise HREError('asset_binding','evidence coordinate reference must be input')
        if coord is not None and asset['evidence_format']['kind']=='array' and record['tool_id'] not in ('T3_DEPTH','T4_SEGMENTATION'):
            binding=next(b for b in bindings if b['asset_id']==coord)
            if (asset['width'],asset['height'])!=(binding['width'],binding['height']):raise HREError('array_geometry','array must match its canonical coordinate image')
    if record['status']!='ok':return
    payload=record['payload'];tool=record['tool_id']
    if tool.startswith('T'):
        contract=record['cache_contract']
        unknown={'unconfigured','unavailable','unknown',''}
        provenance=[contract['tool_version'],contract['preprocess_version'],contract['model']['name'],contract['model']['revision']]+[contract['backend'][k] for k in ('implementation','version','device','precision')]
        if any(x.lower() in unknown for x in provenance):raise HREError('unconfigured_tool','successful T1-T4 evidence requires explicit frozen tool/model/preprocess provenance')
        model=contract['model']
        if model['weights_sha256'] is None and not model['components']:
            from .models import canonical_json,sha256_bytes
            parameters=contract['parameters']
            manual=(model['name']=='manual_annotation' and contract['backend']['implementation']=='manual_annotation' and parameters.get('annotation_sha256')==annotation_hash(payload,bindings,assets,case_root=case_root) and isinstance(parameters.get('annotation_version'),str) and parameters['annotation_version'].lower() not in unknown)
            if not manual:raise HREError('model_provenance','T1-T4 evidence requires actual weights/components hashes or hash-bound manual_annotation provenance')
        frames=payload['coordinate_frames']
        if {f['asset_id'] for f in frames}!=set(ids) or len(frames)!=len(ids):raise HREError('coordinate_frame','each input needs exactly one frame')
        for frame in frames:
            m=np.asarray(frame['source_to_tool'],dtype=float)
            if not np.isfinite(m).all() or abs(np.linalg.det(m))<1e-12:raise HREError('coordinate_frame','invalid source_to_tool matrix')
        for d in payload['detections']:
            if d['source_asset_id'] not in ids:raise HREError('asset_binding','detection is not bound to an input')
            x0,y0,x1,y1=d['bbox_norm']
            if not (x0<x1 and y0<y1):raise HREError('invalid_bbox','detection bbox must be ordered')
        if tool in ('T3_DEPTH','T4_SEGMENTATION'):
            data=payload['data'];key='depth_asset_id' if tool=='T3_DEPTH' else 'mask_asset_id'
            arr=next((a for a in assets if a['asset_id']==data[key]),None)
            if not arr or arr['evidence_format']['kind']!='array':raise HREError('array_binding','raw depth/mask must reference an array asset')
            _validate_native_geometry(record,arr)
            from .paths import safe_path
            values=np.load(safe_path(case_root,arr['path'],must_exist=True),allow_pickle=False)
            if values.ndim!=2:raise HREError('array_shape','depth/segmentation must be two-dimensional')
            if tool=='T3_DEPTH' and not np.issubdtype(values.dtype,np.floating):raise HREError('array_dtype','depth must be floating point')
            if tool=='T4_SEGMENTATION':
                registry=data['class_registry'];classes=[r['class_id'] for r in registry]
                if len(set(classes))!=len(classes) or not np.issubdtype(values.dtype,np.integer) or not set(np.unique(values).tolist()).issubset(classes):raise HREError('class_registry','segmentation labels do not match registry')
            display=data['display_asset_id']
            if display is not None:
                vis=next((a for a in assets if a['asset_id']==display),None)
                if not vis or vis['evidence_format']['kind']!='visualization' or vis['evidence_format']['coordinate_asset_id']!=arr['evidence_format']['coordinate_asset_id'] or (vis['width'],vis['height'])!=(arr['width'],arr['height']):raise HREError('display_binding','display must share array coordinate image and native geometry')
    elif tool=='STATS':
        if any(r['source_asset_id'] not in ids for r in payload['regions']):raise HREError('asset_binding','stats region must refer to input')
        for r in payload['regions']:
            if r['mask_sha256'] is not None and not any(a['sha256']==r['mask_sha256'] and a['evidence_format']['kind']=='array' and a['evidence_format']['coordinate_asset_id']==r['source_asset_id'] for a in assets):raise HREError('mask_binding','stats mask hash requires matching coordinate-bound actual array')
    elif tool=='ROI_COMPARE':
        if [r['roi_pair_id'] for r in payload['roi_pairs']]!=record['binding']['roi_pair_ids']:raise HREError('roi_binding','ROI pairs differ from plan binding')
        for p in payload['roi_pairs']:
            if p['prediction_asset_id'] not in ids or p['reference_asset_id'] not in ids:raise HREError('roi_binding','ROI input not bound')
            if p['status'] in ('unknown','not_comparable') and p['metric_delta']:raise HREError('roi_comparability','noncomparable ROI must not have metric deltas')


def _make_root(root: Path) -> Path:
    from .paths import safe_path
    root=Path(root).absolute()
    safe_path(root.parent,root.name)
    root.mkdir(parents=True,exist_ok=True)
    return root


def _copy_asset(asset: dict, origin: Path, destination: Path) -> dict:
    from .paths import safe_path
    from .models import file_sha256,HREError
    from .storage import atomic_write
    result=copy.deepcopy(asset)
    for obj in [result]+([result['source_file']] if 'source_file' in result else []):
        p=safe_path(origin,obj['path'],must_exist=True)
        if file_sha256(p)!=obj['sha256']:raise HREError('asset_hash','bundle artifact hash mismatch')
        suffix=p.suffix.lower() or '.bin'
        rel='files/'+obj['sha256']+suffix
        target=safe_path(destination,rel)
        if target.exists() and file_sha256(target)!=obj['sha256']:raise HREError('asset_collision','artifact collision')
        if not target.exists():atomic_write(target,p.read_bytes())
        obj['path']=rel
    return result


def _read_cache_entry(entry: Path) -> tuple[dict,list[dict]]:
    from .storage import read_json
    from .paths import safe_path
    from .models import file_sha256,HREError
    integrity=read_json(safe_path(entry,'entry.json',must_exist=True))
    if set(integrity)!={'record_sha256','inputs_sha256'} or file_sha256(safe_path(entry,'record.json',must_exist=True))!=integrity['record_sha256'] or file_sha256(safe_path(entry,'inputs.json',must_exist=True))!=integrity['inputs_sha256']:raise HREError('cache_integrity','cache record/inputs bytes changed')
    record=read_json(safe_path(entry,'record.json',must_exist=True));inputs=read_json(safe_path(entry,'inputs.json',must_exist=True))['inputs']
    validate_record(entry,record,inputs)
    if record['status']!='ok':raise HREError('cache_status','reusable cache entries must be successful records')
    return record,inputs


def register_cache_bundle(bundle: Path, cache_root: Path) -> dict:
    """Import directory containing evidence_bundle.json; reject unsafe paths and collisions."""
    from .storage import read_json
    from .paths import safe_path
    from .models import HREError,file_sha256,SCHEMA_VERSION
    root=Path(bundle)
    if root.is_symlink() or not root.is_dir():raise HREError('invalid_bundle','bundle must be an ordinary directory')
    manifest=read_json(safe_path(root,'evidence_bundle.json',must_exist=True))
    if set(manifest)!= {'schema_version','records','inputs'} or manifest['schema_version']!=SCHEMA_VERSION or not isinstance(manifest['records'],list) or not isinstance(manifest['inputs'],list):raise HREError('invalid_bundle','invalid evidence bundle manifest')
    inputs=manifest['inputs'];results=[];seen=set()
    from .assets import validate_asset
    for asset in inputs:validate_asset(asset,root)
    validated=[]
    for ref in manifest['records']:
        if set(ref)!= {'path','sha256'}:raise HREError('invalid_bundle','invalid record reference')
        path=safe_path(root,ref['path'],must_exist=True)
        if file_sha256(path)!=ref['sha256']:raise HREError('record_hash','bundle record hash mismatch')
        record=read_json(path);validate_record(root,record,inputs)
        key=record['cache_key_sha256']
        if record['status']=='ok':
            if key in seen:raise HREError('cache_collision','duplicate successful cache key in bundle')
            seen.add(key);validated.append(record)
    cache_root=Path(cache_root)
    if cache_root.is_symlink():raise HREError('unsafe_path','cache root cannot be a symlink')
    cache_root=_make_root(cache_root)
    import os,shutil
    from .paths import make_id
    from .storage import case_lock,_fsync_dir
    pending=safe_path(cache_root,'pending/'+make_id('bundle'));pending.mkdir(parents=True)
    staged=[]
    try:
        for record in validated:
            key=record['cache_key_sha256'];entry=safe_path(pending,key);entry.mkdir()
            copied_inputs=[_copy_asset(a,root,entry) for a in inputs if a['asset_id'] in {b['asset_id'] for b in record['binding']['inputs']}]
            stored=copy.deepcopy(record);stored['assets']=[_copy_asset(a,root,entry) for a in record['assets']]
            _immutable(safe_path(entry,'record.json'),stored);_immutable(safe_path(entry,'inputs.json'),{'inputs':copied_inputs})
            _immutable(safe_path(entry,'entry.json'),dict(record_sha256=file_sha256(safe_path(entry,'record.json')),inputs_sha256=file_sha256(safe_path(entry,'inputs.json'))))
            _read_cache_entry(entry);staged.append((key,entry))
        with case_lock(cache_root):
            # Preflight every existing conflict before publishing any new key.
            for key,entry in staged:
                final=safe_path(cache_root,key)
                if final.exists():
                    _read_cache_entry(final)
                    for name in ('record.json','inputs.json','entry.json'):
                        if safe_path(final,name).read_bytes()!=safe_path(entry,name).read_bytes():raise HREError('cache_collision','immutable existing cache key differs from imported entry')
            for key,entry in staged:
                final=safe_path(cache_root,key)
                if not final.exists():os.rename(entry,final);_fsync_dir(cache_root)
                results.append(key)
    finally:
        shutil.rmtree(pending)
    return {'registered':results,'count':len(results)}


class EvidenceService:
    def __init__(self, case_root: Path, cache_root: Path | None = None):
        self.case_root=Path(case_root);self.cache_root=Path(cache_root) if cache_root else None
        self._resolved_inputs=[]

    def _config(self) -> dict:
        from .storage import read_json
        from .paths import safe_path
        path=safe_path(self.case_root,'config.json')
        return read_json(path) if path.exists() else {}

    def _inputs(self,state: dict,item: dict) -> list[dict]:
        from .models import HREError
        available=list(state['inputs'])
        for c in state.get('candidates',[]):
            if c.get('candidate_id')==state.get('candidate_id') and c.get('asset'):available.append(c['asset'])
        if isinstance(state.get('candidate_asset'),dict):available.append(state['candidate_asset'])
        result=[]
        for role in item['roles']:
            matches=[a for a in available if a['role']==role]
            if len(matches)!=1:raise HREError('asset_binding',f'no unique asset for role {role}')
            result.append(matches[0])
        return result

    def _contract(self,state: dict,item: dict,inputs: list[dict]) -> dict:
        from .models import canonical_json,sha256_bytes,SCHEMA_VERSION
        config=self._config();profile=config.get('tool_profile',{}).get(item['tool_id'],{})
        builtin=item['tool_id'] in ('STATS','ROI_COMPARE')
        preprocess=profile.get('preprocess',config.get('stats_metric',{'metric_version':'display_stats_v1'}) if builtin else {'status':'unconfigured'})
        roi=config.get('reference_v2',{}).get('roi_pairs',config.get('roi_manifest'))
        contract=dict(schema_version=SCHEMA_VERSION,tool_id=item['tool_id'],tool_version=profile.get('tool_version','display_stats_v1' if builtin else 'unconfigured'),
            inputs=[_contract_input(a) for a in inputs],canonicalizer_version=inputs[0].get('canonicalization',{}).get('canonicalizer_version','hre_rgb8_v1'),
            model=profile.get('model',dict(name='none' if builtin else 'unavailable',revision='display_stats_v1' if builtin else 'unconfigured',weights_sha256=None,components=[])),
            preprocess_version=profile.get('preprocess_version','display_stats_v1' if builtin else 'unconfigured'),preprocess_sha256=sha256_bytes(canonical_json(preprocess)),
            parameters=copy.deepcopy(profile.get('parameters',{})) | ({'roi_pair_ids':item['roi_pair_ids']} if item['roi_pair_ids'] else {}),backend=profile.get('backend',dict(implementation='numpy' if builtin else 'unavailable',version=np.__version__ if builtin else 'unconfigured',device='cpu' if builtin else 'unconfigured',precision='float64' if builtin else 'unconfigured',profile_id=state['profile_id'],environment_sha256=sha256_bytes(canonical_json({'numpy':np.__version__} if builtin else {'status':'unconfigured'})))),
            roi_manifest_sha256=sha256_bytes(canonical_json(roi)) if item['roi_pair_ids'] and roi is not None else None,prompt_set_sha256=profile.get('prompt_set_sha256'))
        return contract

    def _write_record(self,record: dict,inputs: list[dict]) -> dict:
        from .paths import safe_path
        validate_record(self.case_root,record,inputs)
        _immutable(safe_path(self.case_root,'evidence/records/'+record['evidence_id']+'.json'),record)
        return record

    def _materialize(self,state: dict,item: dict,inputs: list[dict],contract: dict,entry: Path) -> dict:
        from .storage import read_json
        from .paths import safe_path
        from .models import HREError
        source,old_inputs=_read_cache_entry(entry)
        if source['cache_contract']!=contract:raise HREError('cache_contract','cache contract mismatch')
        mapping={}
        for old in source['binding']['inputs']:
            matches=[a for a in inputs if _contract_input(a)==_contract_input(old)]
            if len(matches)!=1 or old['asset_id'] in mapping:raise HREError('asset_mapping','ambiguous cross-case asset mapping')
            mapping[old['asset_id']]=matches[0]['asset_id']
        rec=copy.deepcopy(source);rec['case_id']=state['case_id'];rec['case_revision']=state['case_revision']
        rec['evidence_id']=self._record_id(state,item,contract)
        occupied=safe_path(self.case_root,'evidence/records/'+rec['evidence_id']+'.json')
        if occupied.exists() and read_json(occupied)['status']!='ok':rec['evidence_id']+='_ok'
        copied=[]
        for a in source['assets']:
            new_id=rec['evidence_id']+'_'+a['asset_id']
            mapping[a['asset_id']]=new_id
            copied.append(_copy_asset(a,entry,self.case_root))
        rec['assets']=_remap(copied,mapping);rec['payload']=_remap(rec['payload'],mapping)
        for asset in rec['assets']:
            if asset['evidence_format']['kind']=='json':
                from .models import canonical_json,sha256_bytes
                from .storage import atomic_write
                content=read_json(safe_path(self.case_root,asset['path'],must_exist=True))
                remapped=_remap(content,mapping);data=canonical_json(remapped);sha=sha256_bytes(data)
                path='files/'+sha+'.json';target=safe_path(self.case_root,path)
                if target.exists() and target.read_bytes()!=data:raise HREError('asset_collision','JSON remapping artifact collision')
                if not target.exists():atomic_write(target,data)
                asset['path']=path;asset['sha256']=sha
        rec['binding']=dict(inputs=[_input_binding(a,state.get('candidate_id')) for a in inputs],plan_item_id=item['plan_item_id'],roi_pair_ids=item['roi_pair_ids'])
        return self._write_record(rec,inputs)

    @staticmethod
    def _record_id(state,item,contract):
        from .models import canonical_json,sha256_bytes
        return 'ev_'+sha256_bytes(canonical_json([state['case_id'],state['case_revision'],item['plan_item_id'],state.get('candidate_id'),make_cache_key(contract)]))[:32]

    def resolve(self,state: dict, *, freeze: bool=True) -> dict:
        from .storage import read_json
        from .paths import safe_path
        from .models import now,SCHEMA_VERSION,HREError
        from .stats import compute_stats,METRIC_VERSION
        from .roi import compare_rois
        self._assert_frozen(state)
        if self.cache_root is None and self._config().get('cache_root'):self.cache_root=Path(self._config()['cache_root'])
        plan=copy.deepcopy(state['evidence_plan']);records=[];missing=[]
        self._resolved_inputs=list(state['inputs'])
        if state.get('candidate_asset'):self._resolved_inputs.append(state['candidate_asset'])
        for item in plan:
            inputs=self._inputs(state,item);contract=self._contract(state,item,inputs);key=make_cache_key(contract)
            rec_id=self._record_id(state,item,contract)
            existing=safe_path(self.case_root,'evidence/records/'+rec_id+'.json')
            record=None
            if existing.exists():
                local=read_json(existing);validate_record(self.case_root,local,inputs)
                if local['cache_contract']!=contract:raise HREError('cache_contract','case evidence contract mismatch')
                if local['status']=='ok':record=local
            upgraded=safe_path(self.case_root,'evidence/records/'+rec_id+'_ok.json')
            if record is None and upgraded.exists():
                record=read_json(upgraded);validate_record(self.case_root,record,inputs)
            if record is None and self.cache_root and safe_path(self.cache_root,key).exists():
                record=self._materialize(state,item,inputs,contract,safe_path(self.cache_root,key))
            if record is None and item.get('evidence_id') and not item['required']:
                observed=safe_path(self.case_root,'evidence/records/'+item['evidence_id']+'.json')
                if observed.exists():
                    prior=read_json(observed);validate_record(self.case_root,prior,inputs)
                    if prior['cache_contract']==contract and prior['binding']['plan_item_id']==item['plan_item_id'] and prior['case_id']==state['case_id'] and prior['case_revision']==state['case_revision']:record=prior
            if record is None:
                payload=None;error=None;artifacts=[]
                try:
                    if item['tool_id']=='STATS':
                        payload,artifacts=self._builtin_stats(inputs,item,rec_id)
                    elif item['tool_id']=='ROI_COMPARE':
                        roi=self._config().get('roi_manifest')
                        roi=roi.get('roi_pairs',[]) if isinstance(roi,dict) else roi
                        if not isinstance(roi,list):raise HREError('missing_roi','planned ROI manifest missing')
                        selected=[]
                        for rid in item['roi_pair_ids']:
                            matches=[p for p in roi if p['roi_pair_id']==rid]
                            if len(matches)!=1:raise HREError('missing_roi','ROI pair missing or ambiguous')
                            selected+=matches
                        byrole={a['role']:a for a in inputs}
                        payload=compare_rois(byrole['prediction'],byrole['reference'],selected,case_root=self.case_root)
                except (HREError,KeyError) as exc:
                    payload=None
                    error=dict(code=getattr(exc,'code','missing_input'),message=str(exc),retryable=True)
                if payload is not None:
                    record=dict(schema_version=SCHEMA_VERSION,evidence_id=rec_id,case_id=state['case_id'],case_revision=state['case_revision'],tool_id=item['tool_id'],status='ok',
                        binding=dict(inputs=[_input_binding(a,state.get('candidate_id')) for a in inputs],plan_item_id=item['plan_item_id'],roi_pair_ids=item['roi_pair_ids']),
                        cache_key_sha256=key,cache_contract=contract,produced_at=now(),producer='runtime',payload=payload,assets=artifacts,error=None)
                elif not item['required']:
                    from .paths import make_id
                    record=dict(schema_version=SCHEMA_VERSION,evidence_id=make_id('observation'),case_id=state['case_id'],case_revision=state['case_revision'],tool_id=item['tool_id'],status='unavailable',
                        binding=dict(inputs=[_input_binding(a,state.get('candidate_id')) for a in inputs],plan_item_id=item['plan_item_id'],roi_pair_ids=item['roi_pair_ids']),
                        cache_key_sha256=key,cache_contract=contract,produced_at=now(),producer='runtime',payload=None,assets=[],error=error or dict(code='offline_evidence_missing',message='no validated precomputed evidence available; tool was not run',retryable=True))
                if record is not None:self._write_record(record,inputs)
            if record is None:
                missing.append(item['plan_item_id']);item.update(status='pending',evidence_id=None)
            else:
                item.update(status=record['status'],evidence_id=record['evidence_id']);records.append(record)
                if item['required'] and record['status']!='ok':missing.append(item['plan_item_id'])
        snapshot=ref=None
        if freeze and not missing:
            scope=state.get('evidence_scope','composition')
            snapshot,ref=self.freeze_snapshot(state|{'evidence_plan':plan},records,scope=scope,candidate_id=state.get('candidate_id') if scope!='composition' else None)
        return dict(plan=plan,snapshot=snapshot,snapshot_ref=ref,missing=missing)

    def freeze_snapshot(self,state: dict,records: list[dict],scope: str='composition',candidate_id: str | None=None) -> tuple[dict,dict]:
        from .models import SCHEMA_VERSION,canonical_json,sha256_bytes,file_sha256,now,HREError,validate_schema
        from .paths import safe_path
        plan=state['evidence_plan'];byid={r['binding']['plan_item_id']:r for r in records}
        if len(byid)!=len(records) or set(byid)!={p['plan_item_id'] for p in plan}:raise HREError('evidence_plan','snapshot records must match planned items exactly')
        diag=_diagnosis_id(self.case_root,state)
        if scope=='composition' and candidate_id is not None:raise HREError('snapshot_scope','composition snapshot cannot bind candidate')
        if scope!='composition' and candidate_id is None:raise HREError('snapshot_scope','candidate snapshot requires candidate ID')
        refs=[];unavailable=[]
        for item in plan:
            rec=byid[item['plan_item_id']]
            inputs=self._inputs(state|({'candidate_id':candidate_id} if candidate_id else {}),item);validate_record(self.case_root,rec,inputs)
            if any(b['role']=='candidate' and b['candidate_id']!=candidate_id for b in rec['binding']['inputs']):raise HREError('candidate_binding','candidate evidence differs from snapshot candidate')
            if rec['case_id']!=state['case_id'] or rec['case_revision']!=state['case_revision'] or rec['tool_id']!=item['tool_id'] or rec['binding']['roi_pair_ids']!=item['roi_pair_ids'] or [b['role'] for b in rec['binding']['inputs']]!=item['roles']:raise HREError('evidence_binding','record not bound to this case plan')
            if item['required'] and rec['status']!='ok':raise HREError('required_evidence','required evidence is unavailable')
            path='evidence/records/'+rec['evidence_id']+'.json';self._write_record(rec,inputs)
            refs.append(dict(evidence_id=rec['evidence_id'],path=path,sha256=file_sha256(safe_path(self.case_root,path)),cache_key_sha256=rec['cache_key_sha256']))
            if rec['status']!='ok':unavailable.append(dict(plan_item_id=item['plan_item_id'],status=rec['status'],reason=rec['error']['message']))
        plan_hash=sha256_bytes(canonical_json(plan));identity=sha256_bytes(canonical_json([state['case_id'],state['case_revision'],state['config_sha256'],diag,plan_hash,scope,candidate_id,refs,unavailable]))
        path='evidence/snapshots/'+identity+'.json';target=safe_path(self.case_root,path)
        from .storage import read_json
        if target.exists():
            snapshot=read_json(target)
            expected=dict(schema_version=SCHEMA_VERSION,case_id=state['case_id'],case_revision=state['case_revision'],config_sha256=state['config_sha256'],diagnosis_task_id=diag,plan_sha256=plan_hash,scope=scope,candidate_id=candidate_id,evidence=refs,unavailable=unavailable,frozen_at=snapshot.get('frozen_at'))
            if snapshot!=expected:raise HREError('immutable_conflict','frozen snapshot altered')
        else:
            snapshot=dict(schema_version=SCHEMA_VERSION,case_id=state['case_id'],case_revision=state['case_revision'],config_sha256=state['config_sha256'],diagnosis_task_id=diag,plan_sha256=plan_hash,scope=scope,candidate_id=candidate_id,evidence=refs,unavailable=unavailable,frozen_at=now())
            validate_schema('evidence',snapshot,'/$defs/snapshot');_immutable(target,snapshot)
        return snapshot,dict(path=path,sha256=file_sha256(target),evidence_ids=[r['evidence_id'] for r in refs],frozen_at=snapshot['frozen_at'])

    def export_bundle(self,snapshot: dict,destination: Path) -> Path:
        from .storage import read_json
        from .paths import safe_path
        from .models import file_sha256,SCHEMA_VERSION,HREError
        destination=Path(destination)
        if destination.is_symlink():raise HREError('unsafe_path','bundle destination cannot be a symlink')
        destination=_make_root(destination)
        state_inputs=[];config=self._config()
        # Inputs come from the frozen state registry; this does not expand consumed evidence.
        state_path=safe_path(self.case_root,'state.json')
        if state_path.exists():
            state=read_json(state_path);state_inputs=state['inputs']
            for c in state.get('candidates',[]):
                if c.get('asset'):state_inputs.append(c['asset'])
        if not state_inputs:state_inputs=self._resolved_inputs
        if not state_inputs and snapshot['evidence']:raise HREError('missing_input','bundle export requires actual input asset registry')
        records=[];used={}
        for ref in snapshot['evidence']:
            path=safe_path(self.case_root,ref['path'],must_exist=True)
            if file_sha256(path)!=ref['sha256']:raise HREError('record_hash','frozen record changed')
            r=read_json(path);validate_record(self.case_root,r,state_inputs)
            for b in r['binding']['inputs']:
                a=next(a for a in state_inputs if a['asset_id']==b['asset_id']);used[a['asset_id']]=a
            copied=copy.deepcopy(r);copied['assets']=[_copy_asset(a,self.case_root,destination) for a in r['assets']]
            rel='records/'+r['evidence_id']+'.json';_immutable(safe_path(destination,rel),copied)
            records.append(dict(path=rel,sha256=file_sha256(safe_path(destination,rel))))
        inputs=[_copy_asset(a,self.case_root,destination) for a in used.values()]
        _immutable(safe_path(destination,'evidence_bundle.json'),dict(schema_version=SCHEMA_VERSION,records=records,inputs=inputs))
        return destination

    def _builtin_stats(self,inputs: list[dict],item: dict,record_id: str) -> tuple[dict,list]:
        from io import BytesIO
        from .stats import compute_stats,_pixels,_metrics,METRIC_VERSION
        from .roi import _box_mask
        from .models import HREError,sha256_bytes
        from .paths import safe_path
        from .storage import atomic_write
        payload=dict(metric_version=METRIC_VERSION,regions=[]);artifacts=[]
        if not item['roi_pair_ids']:
            for a in inputs:
                region=compute_stats(a,case_root=self.case_root)['regions'][0]
                region['region_id']=a['role']+'_full';payload['regions'].append(region)
            return payload,artifacts
        manifest=self._config().get('roi_manifest')
        manifest=manifest.get('roi_pairs',[]) if isinstance(manifest,dict) else manifest
        if not isinstance(manifest,list):raise HREError('missing_roi','planned ROI manifest missing')
        for rid in item['roi_pair_ids']:
            matches=[p for p in manifest if p['roi_pair_id']==rid]
            if len(matches)!=1:raise HREError('missing_roi','ROI pair missing or ambiguous')
            pair=matches[0]
            if pair.get('coordinate_system')!='canonical_norm':raise HREError('invalid_roi','ROI must be canonical_norm')
            for a in inputs:
                if a['role'] not in pair:raise HREError('missing_roi','ROI coordinates missing for input role')
                rgb=_pixels(a,self.case_root);mask=_box_mask(rgb.shape,pair[a['role']]);metrics=_metrics(rgb[mask])
                buf=BytesIO();np.save(buf,mask,allow_pickle=False);data=buf.getvalue();sha=sha256_bytes(data)
                path='files/'+sha+'.npy';target=safe_path(self.case_root,path)
                if target.exists() and target.read_bytes()!=data:raise HREError('asset_collision','mask artifact collision')
                if not target.exists():atomic_write(target,data)
                aid=record_id+'_'+a['role']+'_'+rid
                artifacts.append(dict(asset_id=aid,path=path,sha256=sha,role='evidence',width=a['width'],height=a['height'],color_space=None,
                    evidence_format=dict(kind='array',dtype='bool',value_range=[0,1],coordinate_asset_id=a['asset_id'])))
                payload['regions'].append(dict(region_id=a['role']+'_'+rid,source_asset_id=a['asset_id'],mask_sha256=sha,sample_count=int(mask.sum()),metrics=metrics))
        return payload,artifacts

    def _assert_frozen(self,state: dict) -> None:
        from .models import file_sha256,HREError
        from .storage import read_json
        from .paths import safe_path
        ref=state.get('evidence_snapshot')
        if ref:
            p=safe_path(self.case_root,ref['path'],must_exist=True)
            if file_sha256(p)!=ref['sha256']:raise HREError('snapshot_modified','frozen snapshot bytes changed')
        directory=safe_path(self.case_root,'evidence/snapshots')
        if directory.exists():
            for p in directory.glob('*.json'):
                snap=read_json(safe_path(self.case_root,p.relative_to(self.case_root).as_posix(),must_exist=True))
                for r in snap['evidence']:
                    actual=safe_path(self.case_root,r['path'],must_exist=True)
                    if file_sha256(actual)!=r['sha256']:raise HREError('record_modified','frozen evidence record bytes changed')
                    record=read_json(actual)
                    available=list(state.get('inputs',[]))
                    for candidate in state.get('candidates',[]):
                        if candidate.get('asset'):available.append(candidate['asset'])
                    if state.get('candidate_asset'):available.append(state['candidate_asset'])
                    needed=[a for a in available if a['asset_id'] in {b['asset_id'] for b in record['binding']['inputs']}]
                    validate_record(self.case_root,record,needed)

    def export_missing_jobs(self,state: dict,destination: Path) -> Path:
        """Export hash-bound offline worker requests; never execute T1–T4 inference."""
        from .models import SCHEMA_VERSION,HREError
        from .paths import safe_path
        destination=Path(destination)
        if destination.is_symlink():raise HREError('unsafe_path','job destination cannot be a symlink')
        destination=_make_root(destination)
        jobs=[];assets={}
        self._assert_frozen(state)
        for item in state['evidence_plan']:
            inputs=self._inputs(state,item);contract=self._contract(state,item,inputs)
            key=make_cache_key(contract)
            existing=safe_path(self.case_root,'evidence/records/'+self._record_id(state,item,contract)+'.json')
            if existing.exists():
                from .storage import read_json
                current=read_json(existing);validate_record(self.case_root,current,inputs)
                if current['status']=='ok' and current['cache_contract']==contract:continue
            for a in inputs:assets[a['asset_id']]=a
            profile=self._config().get('tool_profile',{}).get(item['tool_id'],{})
            jobs.append(dict(plan_item_id=item['plan_item_id'],required=item['required'],
                cache_key_sha256=key,cache_contract=contract,
                binding=dict(inputs=[_input_binding(a,state.get('candidate_id')) for a in inputs],plan_item_id=item['plan_item_id'],roi_pair_ids=item['roi_pair_ids']),
                action='builtin_precompute' if item['tool_id'] in ('STATS','ROI_COMPARE') else 'external_offline_worker',
                runnable=item['tool_id'] in ('STATS','ROI_COMPARE') or bool(profile.get('preprocess') and all(contract['backend'][k].lower() not in ('unknown','unavailable','unconfigured') for k in ('implementation','version','device','precision')) and all(contract[k].lower() not in ('unknown','unavailable','unconfigured') for k in ('tool_version','preprocess_version')) and profile.get('model') and profile['model'].get('name','unknown').lower() not in ('unknown','unavailable','unconfigured') and profile['model'].get('revision','unknown').lower() not in ('unknown','unavailable','unconfigured') and (profile['model'].get('weights_sha256') or profile['model'].get('components') or profile['model'].get('name')=='manual_annotation')),
                requirement='Exact frozen contract and validated evidence.schema.json record; no model/profile substitutions'))
        copied=[_copy_asset(a,self.case_root,destination) for a in assets.values()]
        manifest=dict(schema_version=SCHEMA_VERSION,case_id=state['case_id'],case_revision=state['case_revision'],
            config_sha256=state['config_sha256'],jobs=jobs,inputs=copied,roi_manifest=self._config().get('roi_manifest'),
            result_bundle=dict(manifest='evidence_bundle.json',required_fields=['schema_version','inputs','records'],record_ref_fields=['path','sha256']),
            instructions='External workers return actual strict evidence records and artifacts. Import validates all hashes, binding, arrays, geometry and labels. Unconfigured T1-T4 require a new frozen tool profile/case before running.')
        path=safe_path(destination,'tool_jobs.json');_immutable(path,manifest)
        return path

    def precompute(self,state: dict,plan: list[dict]) -> dict:
        """Explicit offline precomputation of chosen items, without mutating live state."""
        return self.resolve(state|{'evidence_plan':copy.deepcopy(plan)},freeze=False)

    def precompute_bundle(self,state: dict,plan: list[dict],destination: Path) -> Path:
        """Export only successful explicit offline items; missing jobs remain explicit."""
        from .models import file_sha256
        from .paths import safe_path
        result=self.precompute(state,plan)
        refs=[]
        for item in result['plan']:
            if item['status']!='ok':continue
            path='evidence/records/'+item['evidence_id']+'.json'
            from .storage import read_json
            record=read_json(safe_path(self.case_root,path,must_exist=True))
            refs.append(dict(evidence_id=item['evidence_id'],path=path,sha256=file_sha256(safe_path(self.case_root,path)),cache_key_sha256=record['cache_key_sha256']))
        return self.export_bundle({'evidence':refs},destination)

    def import_bundle(self,bundle: Path) -> dict:
        root=self.cache_root or self.case_root/'evidence'/'imported_cache'
        result=register_cache_bundle(bundle,root);self.cache_root=root
        return result


def _diagnosis_id(case_root: Path,state: dict):
    from .models import HREError,file_sha256
    from .storage import read_json
    from .paths import safe_path
    if not state['profile_id'].startswith('agent_'):return None
    explicit=state.get('diagnosis_task_id') or state.get('_diagnosis_task_id')
    found=[]
    directory=safe_path(case_root,'transactions')
    if directory.exists():
        for p in sorted(directory.glob('*.json')):
            tx=read_json(safe_path(case_root,p.relative_to(case_root).as_posix(),must_exist=True))
            a=tx.get('accepted_submission')
            if not a:continue
            path=safe_path(case_root,a['response_path'],must_exist=True)
            if file_sha256(path)!=a['response_sha256']:raise HREError('accepted_modified','accepted response changed')
            response=read_json(path)
            if response.get('case_id')==state['case_id'] and response.get('case_revision')==state['case_revision'] and response.get('stage')=='diagnose' and response.get('status')=='ok':found.append(response['task_id'])
    actual=found[-1] if found else None
    transient=state.get('_accepted_diagnosis')
    if transient:
        from .models import validate_schema
        path=safe_path(case_root,transient['response_path'],must_exist=True)
        if file_sha256(path)!=transient['response_sha256']:raise HREError('accepted_modified','diagnosis response bytes changed')
        response=read_json(path);validate_schema('response',response)
        if response['case_id']!=state['case_id'] or response['case_revision']!=state['case_revision'] or response['stage']!='diagnose' or response['status']!='ok' or response['task_id']!=transient['task_id']:raise HREError('diagnosis_binding','invalid accepted diagnosis artifact')
        actual=response['task_id']
    if explicit and actual and explicit!=actual:raise HREError('diagnosis_binding','snapshot diagnosis task differs from accepted diagnosis')
    if not actual:raise HREError('missing_diagnosis','Agent snapshot requires accepted diagnosis task ID')
    return actual


def export_missing_jobs(state: dict,destination: Path,*,case_root: Path) -> Path:
    return EvidenceService(case_root).export_missing_jobs(state,destination)


def freeze_snapshot(state: dict,records: list[dict],scope: str='composition',candidate_id: str | None=None,*,case_root: Path | None=None):
    from .models import HREError
    root=case_root or state.get('case_root')
    if root is None:raise HREError('case_root_required','freeze_snapshot requires case_root; use EvidenceService.freeze_snapshot')
    return EvidenceService(Path(root)).freeze_snapshot(state,records,scope,candidate_id)


def validate_snapshot(case_root: Path,snapshot: dict,state: dict) -> None:
    from .models import validate_schema,file_sha256,HREError,canonical_json,sha256_bytes
    from .storage import read_json
    from .paths import safe_path
    validate_schema('evidence',snapshot,'/$defs/snapshot')
    if any(snapshot[k]!=state[k] for k in ('case_id','case_revision','config_sha256')):raise HREError('snapshot_binding','snapshot identity differs from case')
    if snapshot['plan_sha256']!=sha256_bytes(canonical_json(state['evidence_plan'])):raise HREError('snapshot_plan','snapshot plan hash mismatch')
    svc=EvidenceService(case_root);byid={p['plan_item_id']:p for p in state['evidence_plan']};seen=set();unavailable=[]
    for ref in snapshot['evidence']:
        path=safe_path(case_root,ref['path'],must_exist=True)
        if file_sha256(path)!=ref['sha256']:raise HREError('record_hash','snapshot record changed')
        rec=read_json(path);pid=rec['binding']['plan_item_id']
        if pid not in byid or pid in seen:raise HREError('snapshot_plan','unplanned or duplicate evidence')
        seen.add(pid);item=byid[pid];validate_record(case_root,rec,svc._inputs(state|({'candidate_id':snapshot['candidate_id']} if snapshot['candidate_id'] else {}),item))
        if any(b['role']=='candidate' and b['candidate_id']!=snapshot['candidate_id'] for b in rec['binding']['inputs']):raise HREError('candidate_binding','candidate evidence differs from snapshot candidate')
        if rec['case_id']!=state['case_id'] or rec['case_revision']!=state['case_revision'] or rec['tool_id']!=item['tool_id'] or rec['evidence_id']!=ref['evidence_id'] or rec['cache_key_sha256']!=ref['cache_key_sha256']:raise HREError('snapshot_binding','snapshot record binding mismatch')
        if [b['role'] for b in rec['binding']['inputs']]!=item['roles'] or rec['binding']['roi_pair_ids']!=item['roi_pair_ids'] or item['status']!=rec['status'] or item['evidence_id']!=rec['evidence_id']:raise HREError('snapshot_plan','record differs from frozen resolved plan')
        if item['required'] and rec['status']!='ok':raise HREError('required_evidence','required evidence unavailable')
        if rec['status']!='ok':unavailable.append(dict(plan_item_id=pid,status=rec['status'],reason=rec['error']['message']))
    if snapshot['unavailable']!=unavailable:raise HREError('snapshot_plan','unavailable items differ from evidence records')
    if seen!=set(byid):raise HREError('snapshot_plan','snapshot missing plan item')
    if snapshot['diagnosis_task_id']!=_diagnosis_id(case_root,state):raise HREError('diagnosis_binding','snapshot diagnosis task mismatch')
