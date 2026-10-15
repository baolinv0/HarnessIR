"""Explicit allow_edit arrays and observed mask transports. No model inference."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import numpy as np
from PIL import Image
from .models import HREError, canonical_json, file_sha256, sha256_bytes
from .paths import safe_path
from .storage import atomic_write, read_json

MASK_VERSION = 'allow_edit_mask_v2'
ENCODERS = {'white_allow', 'black_allow', 'alpha_clear_allow'}
MODES = {'native_mask_parameter', 'separate_mask_image'}


def require(condition, code, message):
    if not condition:
        raise HREError(code, message)


def checked_file(root, ref):
    require(isinstance(ref, dict) and set(ref) == {'path','sha256'}, 'invalid_reference', 'Expected path and sha256')
    path = safe_path(Path(root), ref['path'], must_exist=True)
    require(path.is_file() and file_sha256(path) == ref['sha256'], 'artifact_hash_mismatch', ref['path'])
    return path


def _binary(values, asset):
    x = np.asarray(values)
    require(x.ndim == 2 and x.dtype == np.uint8, 'invalid_mask', 'Mask must be a 2D uint8 array, not an overlay')
    require(x.shape == (asset['height'], asset['width']), 'mask_shape', 'Mask must match canonical A exactly')
    require(set(np.unique(x).tolist()) <= {0,1} and bool(x.any()), 'invalid_mask', 'Use nonempty explicit {0,1} allow_edit values')
    return x


def _provenance(provenance,asset):
    require(isinstance(provenance,dict) and provenance.get('kind') in {'manual','T4_SEGMENTATION'},'mask_provenance','Explicit mask source required')
    if provenance['kind']=='manual':
        require(bool(isinstance(provenance.get('annotator'),str) and provenance['annotator'].strip())
                or (isinstance(provenance.get('annotation_config_sha256'),str) and len(provenance['annotation_config_sha256'])==64
                    and isinstance(provenance.get('derivation'),str) and provenance['derivation'].strip()),'mask_provenance','Manual source needs an annotator or frozen annotation/derivation')
    else:
        from .evidence import make_cache_key
        keys={'kind','cache_key_sha256','cache_contract','source_array_sha256','class_ids','erosion','dilation','feather','threshold'}
        require(set(provenance)==keys,'mask_provenance','Incomplete T4 derivation provenance')
        contract=provenance['cache_contract']
        require(make_cache_key(contract)==provenance['cache_key_sha256'] and contract['tool_id']=='T4_SEGMENTATION'
                and contract['inputs']==[{'role':'prediction','canonical_sha256':asset['sha256'],'width':asset['width'],'height':asset['height']}],
                'mask_provenance','T4 provenance/source cache identity differs')
        require(isinstance(provenance['class_ids'],list) and provenance['class_ids'] and all(type(v) is int for v in provenance['class_ids'])
                and type(provenance['erosion']) is int and 0<=provenance['erosion']<=64 and provenance['dilation']==provenance['feather']==0
                and provenance['threshold'] is None and isinstance(provenance['source_array_sha256'],str) and len(provenance['source_array_sha256'])==64,
                'mask_provenance','Invalid T4 class or derivation parameters')


def make_mask_contract(root, values, asset, *, purpose, roi_ids, provenance, relative):
    require(asset['role'] == 'prediction', 'mask_binding', 'Masks bind the prediction A')
    require(purpose in {'EDIT_MASK','EVAL_MASK'} and roi_ids and len(set(roi_ids)) == len(roi_ids), 'mask_binding', 'Declare purpose and unique target ROI IDs')
    _provenance(provenance,asset)
    values = _binary(values, asset)
    output = safe_path(Path(root), relative)
    require(output.suffix == '.npy', 'mask_encoding', 'Internal masks are uint8 NPY arrays')
    stream = BytesIO(); np.save(stream, values, allow_pickle=False)
    if output.exists():
        require(output.read_bytes() == stream.getvalue(), 'immutable_conflict', 'Use a new mask revision')
    else:
        atomic_write(output, stream.getvalue())
    return dict(schema_version=MASK_VERSION, purpose=purpose, path=relative, sha256=file_sha256(output),
                input_role='prediction', A_pixel_sha256=asset['pixel_sha256'], width=asset['width'], height=asset['height'],
                semantics='0_preserve_1_allow_edit', target_roi_ids=list(roi_ids), provenance=deepcopy(provenance))


def validate_mask(root, contract, asset):
    keys = {'schema_version','purpose','path','sha256','input_role','A_pixel_sha256','width','height','semantics','target_roi_ids','provenance'}
    require(isinstance(contract,dict) and set(contract) == keys and contract['schema_version'] == MASK_VERSION, 'mask_contract', 'Unknown or incomplete mask contract')
    require(contract['semantics'] == '0_preserve_1_allow_edit', 'mask_encoding', 'Mask direction must be explicit; no guessing or inversion')
    require(asset['role'] == contract['input_role'] == 'prediction' and contract['A_pixel_sha256'] == asset['pixel_sha256']
            and (contract['width'],contract['height']) == (asset['width'],asset['height']), 'mask_binding', 'Mask source must be frozen A')
    require(contract['purpose'] in {'EDIT_MASK','EVAL_MASK'} and contract['target_roi_ids']
            and len(set(contract['target_roi_ids'])) == len(contract['target_roi_ids']), 'mask_binding', 'Invalid purpose or target ROI IDs')
    _provenance(contract['provenance'],asset)
    path = checked_file(root, {k:contract[k] for k in ('path','sha256')})
    require(path.suffix == '.npy', 'mask_encoding', 'Colored images are not internal masks')
    return _binary(np.load(path, allow_pickle=False), asset)


def encode_edit_mask(root, contract, asset, encoder, output):
    require(encoder in ENCODERS, 'mask_encoding', 'Unsupported explicit transport encoding')
    mask = validate_mask(root, contract, asset)
    require(contract['purpose'] == 'EDIT_MASK', 'mask_binding', 'EVAL_MASK cannot silently become EDIT_MASK')
    if encoder == 'alpha_clear_allow':
        pixels = np.zeros((*mask.shape,4),dtype=np.uint8);pixels[:,:,3] = (1-mask)*255
    else:
        pixels = (mask if encoder == 'white_allow' else 1-mask)*255
    stream=BytesIO(); Image.fromarray(pixels).save(stream,format='PNG')
    output=Path(output)
    if output.exists():require(output.read_bytes()==stream.getvalue(),'immutable_conflict','Transport mask changed')
    else:atomic_write(output,stream.getvalue())
    return output


def validate_mask_probe(root, proof, executor, *, allow_fixture=False):
    """Validate three hash-bound observations; never infer desktop API support."""
    if isinstance(proof,dict) and set(proof)=={'path','sha256'}:
        proof=read_json(checked_file(root,proof))
    keys={'schema_version','executor','status','probe_env','mask_mode','mask_encoder','accepts_A_and_B','accepts_mask',
          'mask_applies_to','allow_edit_semantics','mask_size_rule','observations'}
    require(isinstance(proof,dict) and set(proof)==keys and proof['schema_version']=='mask_probe_v2', 'skipped_capability', 'Complete observed mask probe required')
    require(proof['executor']==executor, 'skipped_capability', 'Probe executor/model/transport/settings/version differ')
    require(proof['status']=='passed' and (proof['probe_env']=='real' or (allow_fixture and proof['probe_env']=='fixture')),
            'skipped_capability','Only real passed probes qualify outside a marked simulation')
    require(proof['mask_mode'] in MODES and proof['mask_encoder'] in ENCODERS and proof['accepts_A_and_B'] is True
            and proof['accepts_mask'] is True and proof['mask_applies_to']=='A'
            and proof['allow_edit_semantics']=='0_preserve_1_allow_edit' and proof['mask_size_rule']=='exact_A',
            'skipped_capability', 'Incomplete or unsupported A+B+mask transport semantics')
    observations=proof['observations']
    require(isinstance(observations,list) and len(observations)==3
            and {o.get('kind') for o in observations}=={'simple_region','fine_boundary','preserve_negative'},
            'skipped_capability','Two local probes and a preservation negative are required')
    for observation in observations:
        keys={'kind','observer','observed_at','steps','input_A','input_B','mask','output','request','delivery','response','passed','notes'}
        require(set(observation)==keys and observation['passed'] is True and observation['observer'] and observation['steps'] and observation['notes'],
                'probe_evidence_invalid','Actual attributed probe observations required')
        from datetime import datetime
        try: timestamp=datetime.fromisoformat(observation['observed_at'].replace('Z','+00:00'))
        except (ValueError,TypeError) as exc:raise HREError('probe_evidence_invalid','Zoned observed_at required') from exc
        require(timestamp.tzinfo is not None,'probe_evidence_invalid','Zoned observed_at required')
        paths={k:checked_file(root,observation[k]) for k in ('input_A','input_B','mask','output','request','delivery','response')}
        for key in ('input_A','input_B','mask','output'):
            with Image.open(paths[key]) as im:im.load()
        with Image.open(paths['input_A']) as im: size=im.size
        with Image.open(paths['output']) as im:require(im.size==size,'probe_evidence_invalid','Probe output geometry differs')
        with Image.open(paths['mask']) as im:
            require(im.size==size,'probe_evidence_invalid','Probe mask geometry differs')
            values=np.asarray(im)
            if proof['mask_encoder']=='alpha_clear_allow':
                require(im.mode=='RGBA' and set(np.unique(values[:,:,3])) <= {0,255},'mask_encoding','Invalid probe alpha mask')
            else:require(im.mode=='L' and set(np.unique(values)) <= {0,255},'mask_encoding','Invalid probe binary image')
        target=(values[:,:,3]==0) if proof['mask_encoder']=='alpha_clear_allow' else (values==255) if proof['mask_encoder']=='white_allow' else (values==0)
        require(target.any() and (~target).any(),'probe_localization','Probe must contain target and protected pixels')
        with Image.open(paths['input_A']) as im:original=np.asarray(im.convert('RGB'),dtype=float)/255
        with Image.open(paths['output']) as im:output=np.asarray(im.convert('RGB'),dtype=float)/255
        change=np.abs(output-original).mean(axis=2);inside=float(change[target].mean());outside=float(change[~target].mean())
        if observation['kind']=='preserve_negative':
            require(outside<=1/255,'probe_localization','Protected negative region drift exceeds one RGB8 level')
        else:
            require(inside>outside and inside>1/255,'probe_localization','Actual edit must be localized in the declared mask direction')
        request,delivery=read_json(paths['request']),read_json(paths['delivery'])
        response=read_json(paths['response'])
        require(response.get('output_sha256')==observation['output']['sha256'],'probe_evidence_invalid','Actual probe response output differs')
        require(request.get('executor')==executor and request.get('input_order')==['A','B','M']
                and request.get('mask_mode')==proof['mask_mode'] and request.get('mask_encoder')==proof['mask_encoder']
                and request.get('mask_applies_to')=='A','probe_evidence_invalid','Actual transport request must preserve A/B/M roles')
        expected={k:observation[v]['sha256'] for k,v in [('A','input_A'),('B','input_B'),('M','mask')]}
        require(request.get('input_sha256')==expected and delivery.get('request_sha256')==observation['request']['sha256']
                and delivery.get('delivered_input_sha256')==expected and delivery.get('delivered') is True,
                'probe_evidence_invalid','Observed delivery must bind exact A/B/mask bytes')
    return deepcopy(proof)


def derive_t4_mask(root, record, asset, *, expected_cache_contract, class_ids, purpose, roi_ids, relative, erosion=0):
    """Consume an already validated, planned A T4 record; never warp tool geometry."""
    from .evidence import validate_record
    validate_record(Path(root),record,[asset])
    from .storage import CaseStore
    from .evidence import EvidenceService
    state=CaseStore(root).load()
    planned=[p for p in state['evidence_plan'] if p['plan_item_id']==record['binding']['plan_item_id']
             and p['tool_id']=='T4_SEGMENTATION' and p['roles']==['prediction']]
    require(len(planned)==1 and state['inputs'][0]==asset,'mask_provenance','Only diagnosis-planned T4 evidence for frozen A may be consumed')
    configured=EvidenceService(root)._contract(state,planned[0],[asset])
    require(configured==expected_cache_contract,'mask_provenance','T4 does not match the case frozen model/preprocess/parameters')
    require(record['tool_id']=='T4_SEGMENTATION' and record['status']=='ok'
            and record['cache_contract']==expected_cache_contract, 'mask_provenance','T4 model/weights/preprocess/parameters must match frozen plan')
    require(set(record['binding']['roi_pair_ids'])>=set(roi_ids),'mask_binding','T4 target ROI not in planned binding')
    data=record['payload']['data'];arr=next(a for a in record['assets'] if a['asset_id']==data['mask_asset_id'])
    require(arr['evidence_format']['coordinate_asset_id']==asset['asset_id'] and (arr['width'],arr['height'])==(asset['width'],asset['height']),
            'mask_shape','Native T4 must be canonical A sized; no automatic remapping')
    require(class_ids and set(class_ids)<={r['class_id'] for r in data['class_registry']},'mask_provenance','Unknown T4 class')
    labels=np.load(safe_path(Path(root),arr['path'],must_exist=True),allow_pickle=False)
    mask=np.isin(labels,class_ids).astype(np.uint8)
    require(type(erosion) is int and 0<=erosion<=64,'mask_provenance','Erosion must be 0..64 pixels')
    for _ in range(erosion):
        p=np.pad(mask,1);mask=np.minimum.reduce([p[dy:dy+mask.shape[0],dx:dx+mask.shape[1]] for dy in range(3) for dx in range(3)])
    provenance=dict(kind='T4_SEGMENTATION', cache_key_sha256=record['cache_key_sha256'],cache_contract=deepcopy(expected_cache_contract),
                    source_array_sha256=arr['sha256'],class_ids=list(class_ids),erosion=erosion,dilation=0,feather=0,threshold=None)
    return make_mask_contract(root,mask,asset,purpose=purpose,roi_ids=roi_ids,provenance=provenance,relative=relative)
