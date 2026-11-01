"""S4 numeric identity: exact selected C pixels, never native-only diagnostics."""
from hre.models import file_sha256
from .contracts import require
from . import coordinator as co,s2_store as store,audit
from .s2_measure import _analysis

BASIS='selected_C_artifact_v1'


def analyze_selected(root,derived,evaluation_id):
    """Re-audit immutable selected bytes; retain S3 native audit unchanged.

    A tagged display derivative of unknown source color remains nonnumeric. The
    float64 output describes RGB8's actual values, not restored native precision.
    """
    d=derived['payload'];a=d['audit']
    if a is None:return None,None,[]
    binding=dict(path=a['derivative_path'],file_hash=a['derivative_file_hash'],pixel_hash=a['derivative_pixel_hash'],
        encoding=a['derivative_encoding'],bit_depth=a['derivative_bit_depth'],numeric_status=a['numeric_status'],
        analysis_path=None,analysis_file_hash=None,analysis_source_file_hash=None,
        precision='exact_selected_RGB8_values_in_float64_not_restored_native_precision')
    require(file_sha256(co._path(root,binding['path'],True))==binding['file_hash'],'selected C file changed')
    if d['status']!='standardized':
        require(a['numeric_status']=='blocked_unknown_encoding','unusable C must not claim selected numeric eligibility')
        return binding,None,[]
    require(binding['encoding']=='srgb' and binding['bit_depth']==8 and a['numeric_status']=='eligible','unsupported selected C representation')
    prefix='s4/selected_analysis/'+evaluation_id;destination=co._path(root,prefix)
    destination.parent.mkdir(parents=True,exist_ok=True)
    selected,_=audit._audit_rgb(dict(role='C',path=str(co._path(root,binding['path'],True)),encoding='srgb',
        encoding_basis='bound_selected_derivative_encoding',display_assumption=None),destination)
    require(selected['source_file_hash']==binding['file_hash'] and selected['source_pixel_hash']==binding['pixel_hash']
        and selected['source_bit_depth']==8 and selected['orientation']==1 and selected['oriented_size']==a['oriented_size'],
        'analysis must decode exact selected C without new geometry or representation')
    selected['analysis_path']=prefix+'/'+selected['analysis_path']
    binding.update(analysis_path=selected['analysis_path'],analysis_file_hash=selected['analysis_file_hash'],
        analysis_source_file_hash=selected['source_file_hash'])
    assets=[dict(path=p.relative_to(root).as_posix(),sha256=file_sha256(p)) for p in sorted(destination.iterdir()) if p.is_file()]
    return binding,_analysis(root,selected),assets


def require_selected(root,state,evaluation):
    """No implicit upgrade of old raw-C evaluations or conclusions to new output."""
    e=evaluation['payload'];require(e.get('candidate_measurement_basis')==BASIS,
        'legacy native-C evaluation requires explicit versioned reevaluation of selected artifact')
    derived=store.by_id(root,state,'candidate_derivatives',e['derived_record_id']);d=derived['payload'];a=d['audit']
    require(derived['content_hash']==e['derived_hash'] and d['raw_candidate_hash']==e['raw_candidate_hash'],'evaluated C/derivative identity changed')
    b=e['selected_artifact']
    if a is None:require(b is None,'unavailable selected C cannot have numeric binding');return derived
    require(b is not None and all(b[k]==a[v] for k,v in (('path','derivative_path'),('file_hash','derivative_file_hash'),
        ('pixel_hash','derivative_pixel_hash'),('encoding','derivative_encoding'),('bit_depth','derivative_bit_depth'),('numeric_status','numeric_status'))),
        'selected C does not match frozen evaluated representation')
    require(file_sha256(co._path(root,b['path'],True))==b['file_hash'],'selected C bytes changed')
    if d['status']=='standardized':
        require(b['analysis_source_file_hash']==b['file_hash'] and b['analysis_path'] is not None
            and file_sha256(co._path(root,b['analysis_path'],True))==b['analysis_file_hash'],'selected analysis/file binding mismatch')
    else:require(b['numeric_status']=='blocked_unknown_encoding' and b['analysis_path'] is None,'unknown C cannot inherit known display encoding')
    return derived
