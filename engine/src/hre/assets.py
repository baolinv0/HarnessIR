"""Freeze original bytes; EXIF/ICC-only conversion to explicit SDR RGB8 sRGB PNG."""
from copy import deepcopy
from importlib.resources import files
from io import BytesIO
from pathlib import Path
import json
import re
import struct
from PIL import Image, ImageCms, ImageOps
from .models import HREError, SCHEMA_VERSION, canonical_json, config_hash, file_sha256, now, sha256_bytes, validate_schema
from .paths import make_id, safe_path
from .storage import atomic_write, read_json, write_json, CaseStore, case_lock

CANONICALIZER_VERSION='hre_rgb8_v1'
_SRGB=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()

def pixel_hash(image):
    rgb=image.convert('RGB');w,h=rgb.size
    return sha256_bytes(b'HRE-RGB8-v1\0'+w.to_bytes(4,'big')+h.to_bytes(4,'big')+rgb.tobytes())


def _png_color_declarations(source):
    # Pillow ignores newer cICP/HDR chunks; examine declarations before any assumption.
    with source.open('rb') as f:
        if f.read(8)!=b'\x89PNG\r\n\x1a\n':raise HREError('invalid_image','Invalid PNG signature')
        while True:
            header=f.read(8)
            if len(header)!=8:raise HREError('invalid_image','Truncated PNG chunks')
            size,kind=struct.unpack('>I4s',header)
            if kind in {b'cICP',b'cHRM',b'gAMA',b'mDCv',b'cLLi'}:
                if size>1024:raise HREError('unsupported_color','Invalid color declaration')
                data=f.read(size)
                if kind==b'cICP' and data!=bytes([1,13,0,1]):raise HREError('unsupported_color','Unknown/HDR cICP requires traceable SDR export')
                if kind==b'cHRM' and data!=struct.pack('>8I',31270,32900,64000,33000,30000,60000,15000,6000):raise HREError('unsupported_color','Non-sRGB chromaticities require traceable SDR export')
                if kind==b'gAMA' and data!=struct.pack('>I',45455):raise HREError('unsupported_color','Unknown transfer gamma requires traceable SDR export')
                if kind in {b'mDCv',b'cLLi'}:raise HREError('unsupported_color','HDR metadata requires traceable SDR export')
            else:f.seek(size,1)
            if len(f.read(4))!=4:raise HREError('invalid_image','Truncated PNG CRC')
            if kind==b'IEND':break


def _decode(source,profile):
    if source.suffix.lower() in {'.heic','.heif','.avif','.exr','.hdr'}:
        raise HREError('unsupported_color','HDR/HEIC/AVIF requires a traceable SDR export')
    try:
        with Image.open(source) as opened:
            opened.load()
            if opened.format not in {'PNG','JPEG','TIFF','BMP','WEBP'} or getattr(opened,'n_frames',1)!=1:
                raise HREError('unsupported_color','Only single-frame known SDR formats are supported')
            # Pillow may downconvert RGB16 PNG at open, so inspect IHDR before accepting RGB8.
            if opened.format=='PNG':
                _png_color_declarations(source)
                with source.open('rb') as f:head=f.read(26)
                if len(head)>24 and head[24]!=8:raise HREError('unsupported_color','Non-RGB8 PNG requires a traceable SDR export')
            if opened.format=='TIFF':
                bits=opened.tag_v2.get(258,(8,))
                if isinstance(bits,int):bits=(bits,)
                if any(bit!=8 for bit in bits):raise HREError('unsupported_color','Non-8bit TIFF requires a traceable SDR export')
            if opened.mode not in {'RGB','RGBA','L','LA','P','CMYK'}:
                raise HREError('unsupported_color',f'Unsupported HDR/precision mode {opened.mode}')
            if any(k in opened.info for k in ('hdr','gain_map','gainmap','cicp','chromaticities')):
                raise HREError('unsupported_color','Unknown HDR/color encoding')
            oriented=ImageOps.exif_transpose(opened)
            if 'A' in oriented.getbands() or 'transparency' in oriented.info:
                rgba=oriented.convert('RGBA')
                if rgba.getchannel('A').getextrema()!=(255,255):raise HREError('unsupported_color','Transparency requires an explicit opaque SDR export')
            orientation=opened.getexif().get(274)
            if orientation is not None and orientation not in range(1,9):raise HREError('unsupported_color','Unknown EXIF orientation')
            icc=opened.info.get('icc_profile')
            if icc:
                try:
                    src_profile=ImageCms.ImageCmsProfile(BytesIO(icc))
                    description=ImageCms.getProfileDescription(src_profile).strip()
                    if any(word in description.lower() for word in ('hdr','pq','hlg','2100')):raise HREError('unsupported_color','HDR ICC requires a traceable SDR export')
                    image=ImageCms.profileToProfile(oriented,src_profile,ImageCms.ImageCmsProfile(BytesIO(_SRGB)),outputMode='RGB')
                except Exception as e:raise HREError('unsupported_color',f'ICC conversion failed: {e}') from e
            else:
                if profile.get('assume_srgb') is not True or opened.mode=='CMYK':raise HREError('missing_icc','Missing ICC requires a frozen explicit sRGB assumption; CMYK needs ICC')
                description='assumed sRGB (explicit frozen policy)';image=oriented.convert('RGB')
            return image,{'media_type':Image.MIME.get(opened.format,'application/octet-stream'),'color_description':description,'icc_sha256':sha256_bytes(icc) if icc else None,'exif_orientation':orientation,'hdr':False}, bool(orientation and orientation!=1),bool(icc)
    except HREError:raise
    except Exception as e:raise HREError('invalid_image',f'Cannot decode {source}: {e}') from e


def canonicalize_image(source:Path,destination:Path,role:str,profile:dict,*,asset_id:str|None=None,candidate_binding:dict|None=None)->dict:
    source=Path(source).absolute();destination=Path(destination).absolute()
    if asset_id is not None and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',asset_id):raise HREError('unsafe_id',asset_id)
    if source==destination:raise HREError('immutable_source','Source cannot be overwritten')
    if source.is_symlink():raise HREError('unsafe_path','Symlink source must be imported from a real file')
    image,metadata,oriented,converted=_decode(source,profile)
    asset_id=asset_id or make_id('asset')
    root=Path(profile.get('case_root',destination.parent)).absolute()
    # Direct standalone use: source outside root is preserved beside canonical under a generated name.
    try:src_rel=source.relative_to(root).as_posix()
    except ValueError:
        src_rel=f'original/{asset_id}_{file_sha256(source)[:16]}{source.suffix.lower() or ".bin"}'
        raw=safe_path(root,src_rel)
        if raw.exists() and file_sha256(raw)!=file_sha256(source):raise HREError('asset_conflict','Original filename collision')
        if not raw.exists():atomic_write(raw,source.read_bytes())
        source=raw
    dest_rel=destination.relative_to(root).as_posix();safe_path(root,dest_rel)
    policy={k:v for k,v in profile.items() if k!='case_root'}
    out=BytesIO();image.save(out,format='PNG',icc_profile=_SRGB)
    if destination.exists() and destination.read_bytes()!=out.getvalue():raise HREError('asset_conflict','Immutable canonical asset already exists')
    if not destination.exists():atomic_write(destination,out.getvalue())
    source_sha=file_sha256(source)
    asset={'asset_id':asset_id,'path':dest_rel,'sha256':file_sha256(destination),'role':role,'width':image.width,'height':image.height,'color_space':'sRGB','media_type':'image/png','pixel_sha256':pixel_hash(image),'source_file':{'path':src_rel,'sha256':source_sha,**metadata},'canonicalization':{'canonicalizer_version':CANONICALIZER_VERSION,'conversion_policy_sha256':sha256_bytes(canonical_json(policy)),'source_sha256':source_sha,'orientation_applied':oriented,'icc_converted':converted,'sdr_export_record':None}}
    if candidate_binding is not None:asset['candidate_binding']=deepcopy(candidate_binding)
    validate_schema('asset',asset)
    return asset


class AssetRegistry:
    def __init__(self,case_root:Path):self.case_root=Path(case_root).absolute()
    def import_asset(self,source:Path,role:str,asset_id:str,policy:dict,candidate_binding:dict|None=None)->dict:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',asset_id):raise HREError('unsafe_id',asset_id)
        source=Path(source).absolute()
        if source.is_symlink() or not source.is_file():raise HREError('unsafe_path','Asset source must be a real file')
        folder='input' if role in ('prediction','reference') else 'assets'
        sha=file_sha256(source);suffix=source.suffix.lower() or '.bin'
        raw=safe_path(self.case_root,f'{folder}/original/{asset_id}_{sha[:16]}{suffix}')
        if not raw.exists():atomic_write(raw,source.read_bytes())
        if file_sha256(raw)!=sha:raise HREError('asset_conflict','Original copy integrity failure')
        dest=safe_path(self.case_root,f'{folder}/canonical/{asset_id}.png')
        contract=deepcopy(policy);contract['case_root']=str(self.case_root)
        asset=canonicalize_image(raw,dest,role,contract,asset_id=asset_id,candidate_binding=candidate_binding)
        validate_asset(asset,self.case_root)
        return asset


def validate_asset(asset:dict,case_root:Path)->None:
    validate_schema('asset',asset)
    path=safe_path(case_root,asset['path'],True)
    if file_sha256(path)!=asset['sha256']:raise HREError('asset_hash_mismatch',asset['path'])
    fmt=asset.get('evidence_format',{})
    if asset['color_space'] is None:
        if fmt.get('kind')=='array':
            import numpy as np
            try:array=np.load(path,allow_pickle=False)
            except Exception as e:raise HREError('invalid_asset',str(e)) from e
            if not isinstance(array,np.ndarray) or str(array.dtype)!=fmt['dtype']:raise HREError('invalid_asset','Array dtype mismatch')
            if asset['width'] is not None and (array.ndim<2 or array.shape[:2]!=(asset['height'],asset['width'])):raise HREError('invalid_asset','Array dimensions mismatch')
            if not np.isfinite(array).all():raise HREError('invalid_asset','Nonfinite array values')
            if fmt['value_range'] is not None and array.size:
                lo,hi=fmt['value_range']
                if lo>hi or float(array.min())<lo or float(array.max())>hi:raise HREError('invalid_asset','Array outside declared range')
        elif fmt.get('kind')=='json':read_json(path)
        else:raise HREError('invalid_asset','Non-image evidence requires explicit evidence format')
        return
    try:
        with Image.open(path) as image:
            image.load()
            if image.mode!='RGB' or image.format!='PNG' or image.size!=(asset['width'],asset['height']):raise HREError('invalid_asset','Canonical RGB8 PNG dimensions mismatch')
            icc=image.info.get('icc_profile')
            if not icc:raise HREError('invalid_asset','Canonical image has no explicit sRGB ICC')
            cms=ImageCms.ImageCmsProfile(BytesIO(icc))
            if 'srgb' not in ImageCms.getProfileDescription(cms).lower():raise HREError('invalid_asset','Canonical ICC is not sRGB')
            if asset.get('pixel_sha256') and pixel_hash(image)!=asset['pixel_sha256']:raise HREError('asset_hash_mismatch','RGB pixel hash mismatch')
            actual_pixel_sha=pixel_hash(image)
            actual_size=image.size
            if image.getexif().get(274) not in (None,1):raise HREError('invalid_asset','Canonical EXIF orientation must already be applied')
    except HREError:raise
    except Exception as e:raise HREError('invalid_asset',str(e)) from e
    if 'source_file' in asset:
        src=asset['source_file'];raw=safe_path(case_root,src['path'],True)
        if file_sha256(raw)!=src['sha256'] or asset['canonicalization']['source_sha256']!=src['sha256']:raise HREError('asset_hash_mismatch','Original source hash mismatch')
        # Reinspect metadata without silently assuming a profile; exact recorded source remains authoritative.
        expected,actual,orientation,converted=_decode(raw,{'assume_srgb':src['icc_sha256'] is None})
        if any(src[k]!=actual[k] for k in actual):raise HREError('invalid_asset','Original color metadata mismatch')
        canonical=asset['canonicalization']
        if canonical['orientation_applied']!=orientation or canonical['icc_converted']!=converted:raise HREError('invalid_asset','Canonicalization flags contradict source metadata')
        version=canonical['canonicalizer_version']
        if version=='hre_rgb8_uniform_scale_v1':
            width,height=actual_size
            if expected.width*height!=expected.height*width:raise HREError('invalid_asset','Derived image is not an exact uniform scale')
            policy={'mode':'aspect_preserving_resize','target_width':width,'target_height':height,'interpolation':'LANCZOS','source_sha256':src['sha256'],'source_pixel_sha256':pixel_hash(expected)}
            if canonical['conversion_policy_sha256']!=sha256_bytes(canonical_json(policy)):raise HREError('invalid_asset','Derived conversion policy mismatch')
            expected=expected.resize(actual_size,Image.Resampling.LANCZOS)
        elif version!=CANONICALIZER_VERSION:raise HREError('invalid_asset','Unknown canonicalizer contract')
        if expected.size!=actual_size or pixel_hash(expected)!=actual_pixel_sha:raise HREError('invalid_asset','Canonical pixels do not derive from original under declared conversion')
    elif asset['role']!='evidence':raise HREError('invalid_asset','Image inputs require verifiable original and canonicalization provenance')


def create_case(prediction:Path,reference:Path,manifest:dict,config:dict,case_root:Path)->dict:
    root=Path(case_root).absolute()
    with case_lock(root):
        if safe_path(root,'state.json').exists() or safe_path(root,'config.json').exists():raise HREError('case_exists','Create a new root for changed frozen inputs/configuration')
        cfg={'profile_id':'agent_adaptive','max_generations':3,'format_repair_limit':1,'geometry_policy':{'mode':'strict'},'assume_srgb':False,'reference_usable':'unknown','roi_manifest':[],'protected_content':deepcopy(manifest.get('content_preservation_annotations',[])),'reference_limitations':[],'cache_root':None,'tool_profile':{},**deepcopy(config)}
        profiles=json.loads(files('hre').joinpath('resources/config/experiment_profiles.json').read_text('utf-8'))
        if cfg['profile_id'] not in profiles['profiles']:raise HREError('invalid_config','Unknown experiment profile')
        cap=profiles['profiles'][cfg['profile_id']]['max_generations']
        if 'max_generations' not in config:cfg['max_generations']=cap
        if cfg['profile_id']=='baseline':cfg['max_generations']=0
        if cfg['profile_id']=='direct_best_of_3' and cfg['max_generations']!=3:raise HREError('invalid_config','DirectBestOf3 requires frozen K=3')
        if type(cfg['max_generations']) is not int or cfg['max_generations']<0 or cfg['max_generations']>cap or (cfg['profile_id']!='baseline' and cfg['max_generations']==0):raise HREError('invalid_config','Generation cap exceeds frozen profile')
        if cfg['reference_usable'] not in (True,False,'usable','unusable','unknown'):raise HREError('invalid_config','Unknown reference usability annotation')
        if type(cfg['assume_srgb']) is not bool:raise HREError('invalid_config','assume_srgb must be boolean')
        from .prompts import normalize_protected_content, freeze_templates
        cfg['protected_content']=normalize_protected_content(cfg['protected_content'])
        cfg.setdefault('stats_metric',profiles['common']['stats_metric'])
        reg=AssetRegistry(root);color_policy={'assume_srgb':cfg['assume_srgb'],'canonicalizer_version':CANONICALIZER_VERSION}
        inputs=[reg.import_asset(prediction,'prediction','A',color_policy),reg.import_asset(reference,'reference','B',color_policy)]
        geometry=cfg['geometry_policy']
        if isinstance(geometry,str):geometry={'mode':geometry}
        mode=geometry.get('mode','strict')
        if mode not in ('strict','aspect_preserving_resize'):raise HREError('invalid_config','Unknown geometry mode')
        cfg['geometry_policy']={'mode':mode,'target_width':inputs[0]['width'],'target_height':inputs[0]['height'],'max_aspect_ratio_error':0 if mode=='strict' else 0.005,**geometry}
        if cfg['geometry_policy']['target_width']!=inputs[0]['width'] or cfg['geometry_policy']['target_height']!=inputs[0]['height']:raise HREError('invalid_config','Geometry target must be prediction dimensions')
        # Validate exact geometry policy using the authoritative nested schema.
        validate_schema('state',cfg['geometry_policy'],'#/properties/candidates/items/properties/geometry/properties/policy')
        cfg['schema_version']=SCHEMA_VERSION;cfg['canonicalizer_version']=CANONICALIZER_VERSION
        cfg['prompt_template_sha256']=freeze_templates(root)
        cfg['config_sha256']=config_hash(cfg)
        frozen_manifest=deepcopy(manifest)
        case_id=frozen_manifest.get('case_id',make_id('case'));case_revision=frozen_manifest.get('case_revision',0)
        frozen_manifest.setdefault('case_id',case_id);frozen_manifest.setdefault('case_revision',case_revision)
        frozen_manifest['input_hashes']={x['role']:{'source_sha256':x['source_file']['sha256'],'canonical_sha256':x['sha256']} for x in inputs}
        stamp=now()
        state={'schema_version':SCHEMA_VERSION,'case_id':case_id,'case_revision':case_revision,'revision':0,'workflow_state':'CREATED','resume_state':None,'pause_reason':None,'round':0,'config_sha256':cfg['config_sha256'],'profile_id':cfg['profile_id'],'inputs':inputs,'pending_task':None,'evidence_plan':[],'evidence_snapshot':None,'budget':{'max_generations':cfg['max_generations'],'reserved':0,'consumed':0,'ledger':[]},'candidates':[],'success':None,'terminal_reason':None,'selection':None,'deviations':[],'created_at':stamp,'updated_at':stamp}
        validate_schema('state',state)
        write_json(safe_path(root,'config.json'),cfg);write_json(safe_path(root,'manifest.json'),frozen_manifest)
        write_json(safe_path(root,'input/roi_manifest.json'),{'roi_pairs':cfg['roi_manifest']})
        CaseStore(root).initialize(state)
        return state
