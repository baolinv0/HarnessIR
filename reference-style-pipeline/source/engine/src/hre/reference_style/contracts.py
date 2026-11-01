"""Versioned file-bridge contracts, deliberately independent of old workflows.

Hashes are integrity bindings, not signatures or proof that a model was called.
Public context is rebuilt from a narrow schema; private policy is never an input.
"""
from copy import deepcopy
from datetime import datetime
import re

from hre.models import canonical_json, sha256_bytes, now
from hre.paths import make_id

SCHEMA_VERSION = 'reference_style_s4_v6'
HASH_VERSION = 'sorted_utf8_json_v1'
PRESERVATION = (
    'Use A as the content and spatial-structure reference. Maximize consistency '
    'of scene, people and object identity, layout, geometry and relative positions. '
    'Transfer only B tone, color, brightness and whole-object/material relationships. '
    'Edit the complete frame jointly; do not subdivide faces, replace text, '
    'or use previous C as a new structural reference.'
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def exact(value, keys):
    require(isinstance(value, dict) and set(value) == set(keys),
            'missing or unknown fields: expected ' + ', '.join(sorted(keys)))


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', value),
            'invalid identifier')
    return value


def digest(value):
    require(isinstance(value, str) and re.fullmatch(r'[a-f0-9]{64}', value), 'invalid SHA256')
    return value


def content_hash(value):
    return sha256_bytes(canonical_json(value))


def record(sample_id, kind, payload):
    identifier(sample_id)
    identifier(kind)
    require(isinstance(payload, dict), 'record payload must be object')
    value = dict(schema_version=SCHEMA_VERSION, hash_version=HASH_VERSION,
                 sample_id=sample_id, record_id=make_id(kind), kind=kind,
                 created_at=now(), payload=deepcopy(payload))
    value['content_hash'] = content_hash(value)
    return value


def validate_record(value):
    exact(value, ('schema_version', 'hash_version', 'sample_id', 'record_id',
                  'kind', 'created_at', 'payload', 'content_hash'))
    require(value['schema_version'] == SCHEMA_VERSION and value['hash_version'] == HASH_VERSION,
            'unsupported schema/hash version')
    for key in ('sample_id', 'record_id', 'kind'):
        identifier(value[key])
    require(isinstance(value['payload'], dict), 'record payload must be object')
    stamp = datetime.fromisoformat(value['created_at'].replace('Z', '+00:00'))
    require(stamp.tzinfo is not None, 'timestamp must have timezone')
    digest(value['content_hash'])
    require(value['content_hash'] == content_hash({k: v for k, v in value.items() if k != 'content_hash'}),
            'record hash mismatch')
    return value


def validate_roles(images):
    require(isinstance(images, list) and all(isinstance(i, dict) for i in images)
            and [i.get('role') for i in images] == ['A', 'B'],
            'exactly one A then one B required; no X or fallback')


_TRANSITIONS = {
    'exported': {'waiting_for_response', 'response_unknown', 'failed'},
    'waiting_for_response': {'imported', 'response_unknown', 'failed'},
    'response_unknown': {'imported', 'failed'},
    'imported': {'validated', 'failed'},
    'validated': set(), 'failed': set(),
}


def transition(old, new):
    require(new in _TRANSITIONS.get(old, set()), f'illegal attempt transition {old} -> {new}')
    return new


def public_text(value):
    require(isinstance(value, str) and bool(value.strip()) and len(value) <= 10000, 'invalid public text')
    # Defense in depth, not a general semantic/DLP classifier. The primary boundary
    # is typed projection and never opening the private verifier store here.
    forbidden = r'acceptance[_ ]?policy|allowed[_ ]?content|accepted|tolerat|permitted|changes? (?:are )?allowed|可容忍|可接受|允许.*(?:结构|五官|纹理|几何)'
    require(not re.search(forbidden, value, re.I), 'posthoc policy/decision is forbidden in execution text')
    return value


def execution_context(value):
    """Controlled executable projection; no caller prose is an instruction field.

    Raw VLM observations remain in imported response artifacts. Converting their
    meaning into these finite typed controls is an explicit caller operation,
    never an automatic copy of narrative/diagnostic/acceptance text.
    """
    exact(value, ('target_version', 'targets', 'evidence', 'feedback'))
    require(isinstance(value['target_version'], str) and re.fullmatch(r'v[1-9][0-9]{0,5}', value['target_version']),
            'target version must be v plus a positive integer')
    require(all(isinstance(value[k], list) for k in ('targets', 'evidence', 'feedback')), 'context lists required')
    evidence_ids = set()
    for item in value['evidence']:
        exact(item, ('evidence_id', 'role', 'kind', 'status', 'reason_code'))
        require(isinstance(item['evidence_id'], str) and re.fullmatch(r'e[1-9][0-9]{0,5}', item['evidence_id']),
                'evidence ID must be e plus a positive integer')
        require(item['evidence_id'] not in evidence_ids, 'duplicate evidence ID')
        evidence_ids.add(item['evidence_id'])
        require(item['role'] in ('A', 'B', 'C'), 'invalid evidence role')
        require(item['kind'] in ('segmentation', 'depth', 'ocr', 'face', 'numeric', 'visual'), 'invalid evidence kind')
        require(item['status'] in ('available', 'unavailable', 'uncertain'), 'invalid evidence status')
        require(item['reason_code'] in ('observed', 'not_installed', 'not_collected',
                'coverage_insufficient', 'correspondence_uncertain', 'encoding_unknown'), 'unsupported evidence reason code')
    target_ids = set()
    for item in value['targets']:
        exact(item, ('target_id', 'unit', 'region_refs', 'effect', 'numeric_range',
                     'judge_type', 'priority', 'evidence_ids'))
        require(isinstance(item['target_id'], str) and re.fullmatch(r't[1-9][0-9]{0,5}', item['target_id']),
                'target ID must be t plus a positive integer')
        require(item['target_id'] not in target_ids, 'duplicate target ID')
        target_ids.add(item['target_id'])
        require(item['unit'] in ('global', 'whole_semantic_object', 'whole_material', 'relation'), 'only whole semantic units allowed')
        require(item['judge_type'] in ('numeric', 'visual', 'mixed'), 'invalid judge_type')
        require(item['priority'] in ('critical', 'secondary'), 'invalid priority')
        require(isinstance(item['region_refs'], list), 'typed region references required')
        expected_roles = {'global': [], 'whole_semantic_object': ['A', 'B'],
                          'whole_material': ['A', 'B'], 'relation': ['A', 'A', 'B', 'B']}[item['unit']]
        require([r.get('role') for r in item['region_refs'] if isinstance(r, dict)] == expected_roles
                and len(item['region_refs']) == len(expected_roles), 'region roles/arity mismatch')
        for region in item['region_refs']:
            exact(region, ('role', 'semantic_class', 'instance_index'))
            require(region['semantic_class'] in ('person', 'face', 'exposed_skin', 'hair', 'clothing', 'sign', 'wall', 'sky',
                    'foliage', 'ground', 'building', 'vehicle', 'water', 'food', 'furniture',
                    'metal', 'wood', 'glass', 'fabric', 'other_whole_object', 'other_whole_material'),
                    'unsupported semantic class; no custom labels or face subdivisions')
            require(type(region['instance_index']) is int and 1 <= region['instance_index'] <= 10000,
                    'invalid semantic instance index')
        exact(item['effect'], ('dimension', 'direction'))
        dimensions = ('relative_brightness', 'relative_warmth', 'relative_chroma') if item['unit'] == 'relation' else (
            'tone', 'color', 'brightness', 'contrast', 'chroma', 'warmth')
        require(item['effect']['dimension'] in dimensions, 'unsupported style effect')
        require(item['effect']['direction'] in ('match_B', 'increase_toward_B', 'decrease_toward_B'), 'unsupported style direction')
        if item['numeric_range'] is not None:
            bounds = item['numeric_range']
            exact(bounds, ('metric', 'lower', 'upper'))
            limits = {'linear_Y': (0, 1), 'L_star': (0, 100), 'a_star': (-200, 200),
                      'b_star': (-200, 200), 'chroma': (0, 300)}
            require(bounds['metric'] in limits, 'unsupported numeric metric')
            require(all(type(bounds[k]) in (int, float) for k in ('lower', 'upper')), 'numeric bounds required')
            low, high = limits[bounds['metric']]
            require(low <= bounds['lower'] <= bounds['upper'] <= high, 'invalid numeric style range')
            require(item['judge_type'] in ('numeric', 'mixed'), 'numeric range requires numeric or mixed judge')
        require(isinstance(item['evidence_ids'], list) and all(e in evidence_ids for e in item['evidence_ids']), 'unknown evidence reference')
    for item in value['feedback']:
        exact(item, ('target_id', 'candidate_record_id', 'candidate_hash', 'observation_code'))
        require(item['target_id'] in target_ids, 'unknown feedback target')
        require(isinstance(item['candidate_record_id'], str) and re.fullmatch(r'response_[a-f0-9]{32}', item['candidate_record_id']),
                'candidate record must be an opaque response UUID')
        digest(item['candidate_hash'])
        require(item['observation_code'] in ('too_bright', 'too_dark', 'too_warm', 'too_cool',
                'too_saturated', 'too_muted', 'tone_residual', 'relationship_residual',
                'content_spatial_deviation', 'spillover', 'uncertain'), 'unsupported factual observation code')
    result = deepcopy(value)
    result['preservation_requirements'] = PRESERVATION
    # Feedback changes the request identity, not the frozen target definition.
    result['target_hash'] = content_hash({k: v for k, v in result.items() if k != 'feedback'})
    return result
