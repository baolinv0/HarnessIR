"""Closed typed diagnostic projection. Narrative is never an executable field.

Validate again at each public boundary, not only at the evidence importer: an
internal producer's future optional/missing-data branch must not bypass typing.
Unknown nested fields fail closed; top-level archival report fields are omitted.
"""
from copy import deepcopy
import math
from jsonschema import Draft202012Validator
from .contracts import require
from .s2_evidence import SEMANTICS, METRICS, STATS


def _object(properties, optional=()):
    return {'type':'object','properties':properties,'required':[k for k in properties if k not in optional],
            'additionalProperties':False}


def _enum(*values):return {'enum':list(values)}
def _pattern(value):return {'type':'string','pattern':value}
def _array(item):return {'type':'array','items':item}
def _nullable(value):return {'anyOf':[{'type':'null'},value]}


_HASH=_pattern(r'^[a-f0-9]{64}$')
_NUM={'type':'number'}
_MAYBE_NUM=_nullable(_NUM)
_COUNT={'type':'integer','minimum':0}
_FRACTION={'type':'number','minimum':0,'maximum':1}
_INDEX={'type':'integer','minimum':0,'maximum':999999}
_EID=_pattern(r'^e[1-9][0-9]{0,5}$')
_RID=_pattern(r'^r[1-9][0-9]{0,5}$')
_SID=_pattern(r'^s[1-9][0-9]{0,5}$')
_STATUS=_enum('available','unavailable','uncertain')
_ELIGIBILITY=_enum('numeric_eligible','visual_direction_only','insufficient_evidence')
_BBOX={'type':'array','items':_COUNT,'minItems':4,'maxItems':4}
_REF=_nullable(_object({'evidence_id':_EID,'entry_index':_nullable(_INDEX)}))
_COVERAGE=_object({'status':_enum('available','unavailable','uncertain','missing'),
    'pixels':_COUNT,'denominator':{'type':'integer','minimum':1},'fraction':_FRACTION,'bbox':_nullable(_BBOX)},optional=('status',))
_COVERAGES=_object({'A':_COVERAGE,'B':_COVERAGE})
_GLOBAL=_object({'region_id':_enum('g0'),'semantic_class':_enum('global'),
    'usage':_enum('summary_only'),'eligibility':_ELIGIBILITY,'coverage':_COVERAGES})
_REGION=_object({'region_id':_RID,'semantic_class':_enum(*SEMANTICS),'A':_REF,'B':_REF,
    'match_status':_enum('confirmed','uncertain','unmatched'),'composition':_enum('comparable','mixed','unknown'),
    'illumination':_enum('comparable','confounded','unknown'),'parent_id':_nullable(_RID),
    'usage':_enum('independent','summary_only'),'coverage':_COVERAGES,'eligibility':_ELIGIBILITY,
    'support_paths':_object({role:_pattern(r'^s2/support_assets/s[1-9][0-9]{0,5}/r[1-9][0-9]{0,5}_'+role+r'\.npy$')
                             for role in ('A','B')},optional=('A','B'))})
_REGIONS={'type':'object','properties':{'g0':_GLOBAL},'required':['g0'],
    'patternProperties':{r'^r[1-9][0-9]{0,5}$':_REGION},'additionalProperties':False}
_ROW={'measurement_id':_pattern(r'^m[1-9][0-9]{0,5}$'),'metric':_enum(*METRICS),'statistic':_enum(*STATS),
    'A':_MAYBE_NUM,'B':_MAYBE_NUM,'delta_B_minus_A':_MAYBE_NUM,'eligibility':_ELIGIBILITY,'support_snapshot_hash':_HASH}
_OPERAND=_object({'left':_MAYBE_NUM,'right':_MAYBE_NUM})
_MEASUREMENT={'oneOf':[
    _object({**_ROW,'kind':_enum('distribution'),'subject_id':_pattern(r'^(g0|r[1-9][0-9]{0,5})$'),'operands':{'type':'null'}}),
    _object({**_ROW,'kind':_enum('relation'),'subject_id':_pattern(r'^l[1-9][0-9]{0,5}$'),
        'operands':_object({'A':_OPERAND,'B':_OPERAND}),'left_region_id':_RID,'right_region_id':_RID})]}
_DEPTH=_object({'relation_id':_pattern(r'^l[1-9][0-9]{0,5}$'),'evidence_id':_EID,'role':_enum('A','B'),
    'left_median':_MAYBE_NUM,'right_median':_MAYBE_NUM,
    'ordering':_enum('uncertain','left_nearer','right_nearer','equal_relative_depth'),
    'cross_image_scale_comparison':_enum('not_performed'),'brightness_rule':_enum('none')})
_FACE_ENTRY=_object({'bbox':_BBOX,'confidence':_FRACTION})
_OCR_ENTRY=_object({'bbox':_BBOX,'confidence':_FRACTION,'text_sha256':_HASH})
_PROTECTION=_object({'evidence_id':_EID,'entry_index':_INDEX,'bbox':_BBOX,'confidence':_FRACTION,
    'text_sha256':_HASH,'role':_enum('A'),'trust_basis':_enum('explicit_snapshot_selection')})
_EVIDENCE_COMMON={'evidence_id':_EID,'role':_enum('A','B'),'status':_STATUS,'record_hash':_HASH,
    'missing_reason':_enum(None,'not_installed','not_collected','coverage_insufficient','uncertain_correspondence')}
_ARRAY_OBSERVATION=_object({'pixels':_COUNT,'oriented_pixels':_COUNT,'array_pixel_hash':_HASH,'bbox':_nullable(_BBOX)})
_EVIDENCE={'oneOf':[
    _object({**_EVIDENCE_COMMON,'kind':_enum('segmentation'),'value_semantics':_enum('binary_support'),
        'observations':_nullable(_ARRAY_OBSERVATION)}),
    _object({**_EVIDENCE_COMMON,'kind':_enum('depth'),'value_semantics':_enum('near_is_small','near_is_large'),
        'observations':_nullable(_ARRAY_OBSERVATION),
        'relative_depth_quantiles':_nullable({'type':'array','items':_NUM,'minItems':3,'maxItems':3}),
        'derived_status':_enum('insufficient_finite_support','observed_within_image_only'),
        'cross_image_scale_comparison':_enum('not_performed')},
        optional=('relative_depth_quantiles','derived_status','cross_image_scale_comparison')),
    *[_object({**_EVIDENCE_COMMON,'kind':_enum(kind),'value_semantics':_enum(semantics),
        'observations':_nullable(_object({'entries':_array(entry)}))})
      for kind,semantics,entry in [('ocr','ocr_entries',_OCR_ENTRY),('face','face_boxes',_FACE_ENTRY)]]]}
_COLOR=_object({'numeric_status':_enum('eligible','blocked_unknown_encoding'),
    'source_endpoint_pixel_fraction':_FRACTION,'gamut_clipped_pixel_fraction':_nullable(_FRACTION)})
_FIELDS={'snapshot_id':_SID,'snapshot_hash':_HASH,'measurements':_array(_MEASUREMENT),'regions':_REGIONS,
    'depth_orders':_array(_DEPTH),'text_protection':_array(_PROTECTION),'evidence':_array(_EVIDENCE),
    'source_color_audit':_object({'A':_COLOR,'B':_COLOR})}
_VALIDATOR=Draft202012Validator(_object(_FIELDS))
_ASSETS=Draft202012Validator(_array(_object({'path':_pattern(
    r'^s2/(support_assets/s[1-9][0-9]{0,5}/r[1-9][0-9]{0,5}_[AB]\.npy|'
    r'evidence_assets/e[1-9][0-9]{0,5}/(raw\.bin|oriented\.npy))$'),'sha256':_HASH})))


def diagnostic_view(payload):
    """Return only closed, finite typed observations; reject malformed producers."""
    require(isinstance(payload,dict) and all(k in payload for k in _FIELDS),'diagnostic fields missing')
    require('assets' in payload and next(_ASSETS.iter_errors(payload['assets']),None) is None,
            'invalid typed diagnostic attachment refs')
    result={k:deepcopy(payload[k]) for k in _FIELDS}
    def finite(value):
        if isinstance(value,dict):
            for item in value.values():finite(item)
        elif isinstance(value,list):
            for item in value:finite(item)
        elif type(value)is float:require(math.isfinite(value),'nonfinite diagnostic value')
    finite(result)
    error=next(_VALIDATOR.iter_errors(result),None)
    require(error is None,'invalid typed diagnostic projection')
    return result
