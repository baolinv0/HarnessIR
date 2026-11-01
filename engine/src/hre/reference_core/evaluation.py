"""Append-only whole-image-first observations, independent of acceptance policy.

The code authenticates local files and ordering. Visual statements remain explicit
reviewer attestations; it does not invent ratings or turn local metrics into votes.
"""
from copy import deepcopy
import json
import math
from pathlib import Path
import re

from PIL import Image
from hre.models import canonical_json, file_sha256, sha256_bytes
from hre.paths import safe_path
from hre.storage import case_lock

AXES = ('tone', 'color', 'brightness', 'lighting_naturalness',
        'material_relationships', 'processing_appearance')
PROTECTIONS = ('identity', 'layout', 'geometry', 'texture', 'ocr', 'naturalness',
               'reference_content_leakage', 'unsupported_detail')
STAGES = ('whole_image', 'whole_regions', 'explanations')
_KEYS = {'schema_version', 'review_id', 'sample_id', 'stage', 'predecessor_hash',
         'images', 'display', 'reviewer', 'whole_image', 'preservation', 'regions', 'metrics', 'conflicts'}
_RESOLUTION_KEYS={'schema_version','resolution_id','sample_id','predecessor_hash','review_hashes','images','display','reviewer','resolutions'}


def _check(ok, message):
    if not ok:
        raise ValueError(message)


def _exact(value, keys):
    _check(isinstance(value, dict) and set(value) == set(keys), 'Missing or unknown observation fields')


def _text(value):
    return isinstance(value, str) and 0 < len(value.strip()) <= 10000


def _id(value):
    _check(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', value), 'Invalid observation identity')


def _hash(value):
    _check(isinstance(value, str) and re.fullmatch(r'[a-f0-9]{64}', value), 'Invalid SHA256')


def _observation(value):
    _exact(value, ('reference_status', 'relation', 'direction', 'magnitude', 'confidence', 'evidence'))
    _check(value['reference_status'] in ('achieved', 'partial', 'unmet', 'uncertain'), 'Explicit reference endpoint judgement required')
    _check(value['relation'] in ('closer', 'same', 'farther', 'uncertain'), 'Unknown comparison relationship')
    _check(value['magnitude'] in ('none', 'slight', 'moderate', 'large', 'unknown'), 'Unknown comparison magnitude')
    _check(value['confidence'] in ('high', 'medium', 'low', 'unknown'), 'Unknown confidence')
    _check(_text(value['direction']) and _text(value['evidence']), 'Direction and evidence are required')
    if value['relation'] == 'uncertain':
        _check(value['magnitude'] == 'unknown', 'Uncertain observation cannot assert a known difference magnitude')
    if value['reference_status'] == 'achieved':
        _check(value['relation'] != 'uncertain' and value['confidence'] != 'unknown', 'Uncertain observation cannot certify reference achievement')


def _images(images):
    _check(isinstance(images, list) and [i.get('role') for i in images if isinstance(i, dict)] == ['A', 'B', 'C']
           and len(images) == 3, 'Exactly A/B/C display artifacts required')
    for item in images:
        _exact(item, ('role', 'path', 'sha256'))
        _hash(item['sha256'])
        _check(_text(item['path']), 'Actual image path required')
        path = Path(item['path'])
        _check(path.is_file() and file_sha256(path) == item['sha256'], 'Displayed image changed or missing')
        with Image.open(path) as image:
            image.verify()


def _validate(spec):
    _exact(spec, _KEYS)
    _check(spec['schema_version'] == 'hre_holistic_review_v1', 'Unsupported holistic review version')
    _id(spec['review_id']); _id(spec['sample_id'])
    _check(spec['stage'] in STAGES, 'Unknown review stage')
    if spec['predecessor_hash'] is not None:
        _hash(spec['predecessor_hash'])
    _images(spec['images'])
    _exact(spec['display'], ('method', 'scale', 'color_basis', 'note'))
    _check(spec['display']['method'] in ('side_by_side', 'toggle', 'sequential'), 'Explicit display method required')
    _check(all(_text(x) for x in spec['display'].values()), 'Actual display conditions required')
    _exact(spec['reviewer'], ('reviewer_id', 'independence', 'prior_exposure'))
    _id(spec['reviewer']['reviewer_id'])
    _check(spec['reviewer']['independence'] in ('independent', 'same_model', 'unknown'), 'Disclose reviewer independence')
    _check(_text(spec['reviewer']['prior_exposure']), 'Disclose prior exposure')
    _check(all(isinstance(spec[k], list) for k in ('regions', 'metrics', 'conflicts')), 'Observation arrays required')
    _check(all(_text(x) for x in spec['conflicts']), 'Explain each conflict')
    if spec['stage'] == 'whole_image':
        _exact(spec['whole_image'], AXES)
        for observation in spec['whole_image'].values():
            _observation(observation)
        _exact(spec['preservation'], PROTECTIONS)
        for item in spec['preservation'].values():
            _exact(item, ('status', 'confidence', 'evidence'))
            _check(item['status'] in ('pass', 'fail', 'uncertain') and item['confidence'] in ('high', 'medium', 'low', 'unknown')
                   and _text(item['evidence']), 'Complete independent A preservation evidence required')
        _check(not spec['regions'] and not spec['metrics'], 'Whole-image observations precede regions and metrics')
    else:
        _check(spec['whole_image'] is None and spec['preservation'] is None, 'Later views cannot rewrite whole-image facts')
    if spec['stage'] != 'whole_regions':
        _check(not spec['regions'], 'Regions belong only to the second view')
    else:
        ids = set()
        for region in spec['regions']:
            _exact(region, ('region_id', 'semantic_class', 'unit_scope', 'observations'))
            _id(region['region_id'])
            _check(region['region_id'] not in ids, 'Duplicate region review'); ids.add(region['region_id'])
            _check(region['unit_scope'] == 'whole_object_or_material' and region['semantic_class'] in (
                'person', 'face', 'exposed_skin', 'hair', 'clothing', 'sign', 'wall', 'sky', 'foliage',
                'ground', 'other_whole_material', 'other_whole_object'), 'Review complete objects/materials, not intraface editing units')
            _check(isinstance(region['observations'], dict) and region['observations'] and set(region['observations']) <= set(AXES),
                   'Use named review dimensions')
            for observation in region['observations'].values():
                _observation(observation)
    if spec['stage'] != 'explanations':
        _check(not spec['metrics'], 'Numeric explanations follow both visual views')
    for metric in spec['metrics']:
        _exact(metric, ('region_id', 'metric', 'value', 'encoding_basis', 'evidence_path', 'evidence_sha256'))
        _id(metric['region_id'])
        _check(_text(metric['metric']) and _text(metric['encoding_basis']), 'Metric identity and encoding basis required')
        value = metric['value']
        _check(value is None or type(value) in (int, float) and math.isfinite(value), 'Metric must be finite or explicitly unknown')
        _hash(metric['evidence_sha256'])
        _check(_text(metric['evidence_path']) and file_sha256(Path(metric['evidence_path'])) == metric['evidence_sha256'],
               'Actual explanatory evidence required')
    canonical_json(spec)


def read_reviews(root):
    directory = safe_path(Path(root), 'holistic')
    if not directory.exists():
        return []
    records = []
    for path in directory.glob('*.json'):
        record = json.loads(path.read_text(encoding='utf-8'))
        _exact(record, ('content_hash', 'payload'))
        _hash(record['content_hash'])
        _check(sha256_bytes(canonical_json(record['payload'])) == record['content_hash'], 'Observation record hash mismatch')
        _validate({k: record['payload'][k] for k in _KEYS})
        records.append(record)
    records.sort(key=lambda x: x['payload']['sequence'])
    _check(len(records) <= len(STAGES), 'Too many review stages')
    for number, record in enumerate(records):
        payload = record['payload']
        _check(payload['sequence'] == number + 1 and payload['stage'] == STAGES[number], 'Broken review stage chain')
        _check(payload['predecessor_hash'] == (None if number == 0 else records[number - 1]['content_hash']), 'Broken review predecessor')
        if number:
            _check(payload['images'] == records[0]['payload']['images'] and payload['sample_id'] == records[0]['payload']['sample_id'],
                   'Review images/sample changed')
        expected = None if number == 0 else records[0]['content_hash']
        _check(payload['whole_image_hash'] == expected and payload['aggregation'] == 'none', 'Whole-image identity changed')
    return records


def append_review(root, spec):
    _validate(spec)
    root = Path(root).absolute()
    root.mkdir(parents=True, exist_ok=True)
    with case_lock(root):
        prior = read_reviews(root)
        replay = [x for x in prior if x['payload']['review_id'] == spec['review_id']]
        if replay:
            _check({k: replay[0]['payload'][k] for k in _KEYS} == spec, 'Conflicting observation replay')
            return replay[0]
        number = len(prior)
        _check(number < len(STAGES) and spec['stage'] == STAGES[number], 'Whole-image, whole-regions, explanations order required')
        _check(spec['predecessor_hash'] == (None if not prior else prior[-1]['content_hash']), 'Wrong review predecessor')
        if prior:
            _check(spec['images'] == prior[0]['payload']['images'] and spec['sample_id'] == prior[0]['payload']['sample_id'],
                   'Review must use the same actual candidate')
        payload = dict(deepcopy(spec), sequence=number + 1, whole_image_hash=None if not prior else prior[0]['content_hash'],
                       truth_basis='reviewer_attested_observation_not_automatic_visual_truth', aggregation='none')
        record = {'content_hash': sha256_bytes(canonical_json(payload)), 'payload': payload}
        path = safe_path(root, 'holistic/' + spec['review_id'] + '.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as out:
            out.write(canonical_json(record))
        return record


def _conflicts(reviews):
    return [dict(review_hash=r['content_hash'],stage=r['payload']['stage'],conflict_index=n,conflict=text)
            for r in reviews for n,text in enumerate(r['payload']['conflicts'])]


def _validate_resolution(spec,reviews):
    _exact(spec,_RESOLUTION_KEYS)
    _check(spec['schema_version']=='hre_holistic_resolution_v1','Unknown holistic resolution version')
    _id(spec['resolution_id']);_id(spec['sample_id']);_hash(spec['predecessor_hash'])
    _check(len(reviews)==len(STAGES),'Complete all original whole-image/region/explanation views before resolution')
    _check(spec['review_hashes']==[r['content_hash'] for r in reviews],'Resolution must bind all exact prior review stages')
    _images(spec['images'])
    _check(spec['images']==reviews[0]['payload']['images'] and spec['sample_id']==reviews[0]['payload']['sample_id'],
           'Resolution must inspect the same actual A/B/C candidate')
    _exact(spec['display'],('method','scale','color_basis','note'))
    _check(spec['display']['method'] in ('side_by_side','toggle','sequential') and all(_text(v) for v in spec['display'].values()),'Actual resolution display conditions required')
    _exact(spec['reviewer'],('reviewer_id','independence','prior_exposure'));_id(spec['reviewer']['reviewer_id'])
    _check(spec['reviewer']['independence'] in ('independent','same_model','unknown') and _text(spec['reviewer']['prior_exposure']),'Disclose actual resolution reviewer/exposure')
    conflicts=_conflicts(reviews);expected={(r['review_hash'],r['conflict_index']):r['conflict'] for r in conflicts}
    _check(bool(expected) and isinstance(spec['resolutions'],list) and len(spec['resolutions'])==len(expected),'Explicitly address every recorded conflict')
    seen=set()
    for row in spec['resolutions']:
        _exact(row,('review_hash','conflict_index','conflict','status','confidence','evidence'));_hash(row['review_hash'])
        _check(type(row['conflict_index']) is int and row['conflict_index']>=0,'Exact conflict index required')
        key=(row['review_hash'],row['conflict_index'])
        _check(key in expected and key not in seen and row['conflict']==expected[key],'Resolution must cite an existing unique conflict without changing its text');seen.add(key)
        _check(row['status'] in ('resolved','uncertain','rejected') and row['confidence'] in ('high','medium','low','unknown') and _text(row['evidence']),
               'Actual conflict resolution evidence/confidence required')
    canonical_json(spec)


def read_resolutions(root):
    root=Path(root);reviews=read_reviews(root);directory=safe_path(root,'holistic_resolutions')
    if not directory.exists():return []
    records=[]
    for path in directory.glob('*.json'):
        record=json.loads(path.read_text(encoding='utf-8'));_exact(record,('content_hash','payload'));_hash(record['content_hash'])
        _check(record['content_hash']==sha256_bytes(canonical_json(record['payload'])),'Resolution record hash mismatch')
        _validate_resolution({k:record['payload'][k] for k in _RESOLUTION_KEYS},reviews);records.append(record)
    records.sort(key=lambda r:r['payload']['sequence'])
    predecessor=None if not reviews else reviews[-1]['content_hash']
    for n,r in enumerate(records):
        _check(r['payload']['sequence']==n+1 and r['payload']['predecessor_hash']==predecessor,'Broken resolution predecessor/sequence')
        predecessor=r['content_hash']
    return records


def append_resolution(root,spec):
    root=Path(root).absolute();root.mkdir(parents=True,exist_ok=True)
    with case_lock(root):
        reviews=read_reviews(root);_validate_resolution(spec,reviews);prior=read_resolutions(root)
        replay=[r for r in prior if r['payload']['resolution_id']==spec['resolution_id']]
        if replay:
            _check({k:replay[0]['payload'][k] for k in _RESOLUTION_KEYS}==spec,'Conflicting resolution replay');return replay[0]
        _check(spec['predecessor_hash']==(prior[-1]['content_hash'] if prior else reviews[-1]['content_hash']),'Resolution must append to the exact current predecessor')
        payload=dict(deepcopy(spec),sequence=len(prior)+1,truth_basis='actual_file_bound_reviewer_attestation_not_automatic_visual_truth')
        record=dict(content_hash=sha256_bytes(canonical_json(payload)),payload=payload)
        path=safe_path(root,'holistic_resolutions/'+spec['resolution_id']+'.json');path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as out:out.write(canonical_json(record))
        return record


def conflict_state(root):
    reviews=read_reviews(root);conflicts=_conflicts(reviews);resolutions=read_resolutions(root)
    rows=[]
    latest=None if not resolutions else resolutions[-1]
    for conflict in conflicts:
        row=None if latest is None else next(r for r in latest['payload']['resolutions'] if
            (r['review_hash'],r['conflict_index'])==(conflict['review_hash'],conflict['conflict_index']))
        resolved=bool(row is not None and row['status']=='resolved' and row['confidence']=='high' and latest['payload']['reviewer']['independence']=='independent')
        rows.append(dict(**conflict,resolved=resolved,resolution_hash=None if latest is None else latest['content_hash'],resolution=deepcopy(row)))
    return dict(conflicts=rows,unresolved_conflicts=[r for r in rows if not r['resolved']],resolution_hashes=[r['content_hash'] for r in resolutions])


def render_report(root):
    records = read_reviews(root)
    _check(bool(records), 'No actual review observations imported')
    lines = ['# Whole-image-first review', '', 'No aggregate score; uncertainty and conflicts remain separate.']
    for record in records:
        p = record['payload']
        title = {'whole_image': 'Whole-image', 'whole_regions': 'Whole-region', 'explanations': 'Explanatory'}[p['stage']]
        fields = {'whole_image': ('whole_image', 'preservation'), 'whole_regions': ('regions',), 'explanations': ('metrics',)}[p['stage']]
        lines += ['', '## ' + title, 'Record: ' + record['content_hash'], '```json',
                  json.dumps({k: p[k] for k in (*fields, 'conflicts', 'display', 'reviewer')}, ensure_ascii=False, indent=2), '```']
    lines+=['','## Bound conflict resolutions','```json',json.dumps(dict(state=conflict_state(root),records=read_resolutions(root)),ensure_ascii=False,indent=2),'```']
    return '\n'.join(lines) + '\n'
