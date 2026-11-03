"""Preserve raw C, then separately audit/derive it. Never infer encoding from RGB."""
from io import BytesIO
from copy import deepcopy
import struct
import zlib
from PIL import Image
from hre.models import sha256_bytes, file_sha256
from hre.storage import case_lock
from .contracts import exact, require
from . import coordinator as co, s2_store as store, audit
from .s2_evidence import code


def inspect_raw(data,a_size):
    """Transport metadata only; a raw output can survive unsupported decoding."""
    geometry=dict(native_size=None,orientation=None,size_matches_A=None,spatial_correspondence='unverified',
                  numeric_support_status='uncertain',resize=None,crop=None)
    encoding=dict(status='unverified',icc_hash=None,container_bit_depth=None,raw_metadata_status='unreadable_or_unsupported')
    try:
        with Image.open(BytesIO(data)) as image:
            geometry.update(native_size=list(image.size),orientation=image.getexif().get(274,1),size_matches_A=list(image.size)==a_size)
            profile=image.info.get('icc_profile')
            encoding.update(icc_hash=sha256_bytes(profile) if isinstance(profile,bytes) else None,
                container_bit_depth=data[24] if image.format=='PNG' and len(data)>24 else 8 if image.format=='JPEG' else None,
                raw_metadata_status='header_observed_not_color_or_pixel_validated',source_format=image.format,source_mode=image.mode)
    except (OSError,ValueError,SyntaxError,zlib.error,struct.error,Image.DecompressionBombError):pass
    return geometry,encoding


def _encoding(raw,spec):
    if spec['encoding']!='auto':return spec['encoding'],'explicit_output_declaration' if spec['encoding']!='unknown' else 'unknown'
    with Image.open(BytesIO(raw)) as image:
        profile=image.info.get('icc_profile')
        if profile:
            for name,check in [('srgb',audit._is_srgb),('display_p3',audit._is_display_p3)]:
                try:check(profile);return name,'validated_embedded_ICC'
                except (ValueError,struct.error,IndexError):continue
            raise ValueError('unsupported candidate ICC; never substitute sRGB')
        # The PNG container sRGB tag is actual encoding metadata, unlike RGB mode.
        if image.format=='PNG' and 'srgb' in image.info:return 'srgb','embedded_sRGB_tag'
    return 'unknown','unknown'


def derive_candidate(root,response_id,spec):
    exact(spec,('derivation_id','encoding','encoding_basis','display_assumption'));code(spec['derivation_id'],'d')
    require(spec['encoding'] in ('auto','srgb','display_p3','unknown'),'unsupported candidate encoding declaration')
    expected={'auto':'embedded_metadata','unknown':'unknown','srgb':'explicit_output_declaration','display_p3':'explicit_output_declaration'}
    require(spec['encoding_basis']==expected[spec['encoding']],'candidate encoding basis mismatch')
    require(spec['display_assumption'] in (None,'srgb') and (spec['display_assumption'] is None or spec['encoding'] in ('unknown','auto')),
            'display assumption only applies to unknown candidates')
    with case_lock(root):
        state=co._status(root);responses=[co._load(root,e['record_path'],'response') for e in state['payload']['results']]
        responses=[r for r in responses if r['record_id']==response_id]
        require(len(responses)==1,'candidate response is not registered in this sample');response=responses[0];p=response['payload']
        require(p['stage_id']=='edit' and p.get('edit_binding') is not None and p['candidate_hash']==p['output_hash'],'requires an imported S3 raw candidate')
        key=response_id+'_'+spec['derivation_id']
        if key in store.registry(state)['candidate_derivatives']:
            prior=store.get(root,state,'candidate_derivatives',key)
            require(prior['payload']['color_spec']==spec and prior['payload']['response_hash']==response['content_hash'],'derivation identity already frozen')
            return prior
        a_size=co._load(root,'input_audit.json')['payload']['images'][0]['oriented_size']
        raw=co._path(root,p['output_path'],True).read_bytes();geometry,metadata=inspect_raw(raw,a_size)
        prefix='s3/candidate_assets/'+key;destination=co._path(root,prefix)
        require(not destination.exists(),'partial derivation exists; preserve and reconcile, never overwrite')
        destination.parent.mkdir(parents=True,exist_ok=True)
        result=None;status='failed';error=None;resolved='unknown';basis='unknown'
        try:
            resolved,basis=_encoding(raw,spec)
            if resolved=='unknown' and spec['display_assumption'] is None:
                status='blocked_unknown_encoding'
            else:
                # Color audit itself validates ICC/container consistency, opacity,
                # bit depth and orientation before deriving an explicit RGB8 view.
                internal=dict(role='C',path=str(co._path(root,p['output_path'],True)),encoding=resolved,
                              encoding_basis=basis,display_assumption='srgb' if resolved=='unknown' else None)
                result,_=audit._audit_rgb(internal,destination)
                for field in ('base_model_version','base_provenance'):result.pop(field,None)
                result['encoding_evidence']=basis
                for field in ('source_path','derivative_path','analysis_path'):
                    if result[field] is not None:result[field]=prefix+'/'+result[field]
                geometry.update(native_size=result['native_size'],orientation=result['orientation'],
                    oriented_size=result['oriented_size'],size_matches_A=result['oriented_size']==a_size,
                    exif_orientation_applied=result['orientation'])
                status='assumed_display_only' if resolved=='unknown' else 'standardized'
        except (OSError,ValueError,SyntaxError,zlib.error,struct.error,Image.DecompressionBombError):
            # Preserve raw response and any partial derivative bytes. Do not claim
            # a usable audit or convert diagnostic exception prose into prompts.
            result=None;error='unsupported_or_conflicting_color_geometry_or_decoder'
        assets=[]
        if destination.exists():
            assets=[{'path':path.relative_to(root).as_posix(),'sha256':file_sha256(path)} for path in sorted(destination.rglob('*')) if path.is_file()]
        return store.put(root,state,'candidate_derivatives',key,'candidate_derivative',dict(
            response_record_id=response_id,response_hash=response['content_hash'],raw_candidate_hash=p['candidate_hash'],raw_output_path=p['output_path'],
            color_spec=deepcopy(spec),resolved_encoding=resolved,encoding_evidence=basis,status=status,error_code=error,
            audit=result,raw_metadata=metadata,geometry=geometry,assets=assets,
            visual_style_status='not_evaluated',spatial_correspondence='unverified',numeric_region_support='requires_true_C_coordinate_evidence',
            provenance_verification='caller_attested_not_remote_authenticated'))
