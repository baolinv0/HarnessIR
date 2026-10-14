"""Deterministic prompts built from frozen local contracts and real image bytes."""
from __future__ import annotations

import json
import math
from copy import deepcopy
import re
from importlib.resources import files
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, meta

from .assets import validate_asset
from .models import HREError, config_hash, file_sha256, request_hash, sha256_bytes, validate_schema
from .paths import safe_path
from .storage import CaseStore, atomic_write, read_json, write_json

STAGES = {'diagnose', 'compose', 'execute', 'verify', 'refine', 'direct_ref'}
ROLE_LABEL = {'prediction': 'A', 'reference': 'B', 'candidate': 'C'}
PROTECTED_RUBRIC = [
    'Preserve A composition and camera viewpoint.',
    'Preserve A object geometry and spatial relationships.',
    'Preserve identities visible in A; explicitly note when no identity is present.',
    'Preserve exact existing text in A; explicitly note when no text is present.',
    'Preserve A scene content without adding, removing, or copying B objects or textures.',
]



def normalize_protected_content(value):
    """Validate the admitted A-coordinate contract without losing annotation fields."""
    if value is None:
        return []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                continue
            if isinstance(item, dict):
                validate_schema('composition', [item], '#/properties/protected_content')
                continue
            raise HREError('invalid_content_annotations', 'Protection lists require nonempty instructions or composition protection records')
        return deepcopy(value)
    fields = {'status', 'source_anchor', 'protected_face_regions', 'protected_text_regions', 'protected_geometry_landmarks', 'protected_object_regions', 'critical_content_rules_version', 'notes'}
    if not isinstance(value, dict) or set(value) != fields:
        raise HREError('invalid_content_annotations', 'Structured annotations require the eight documented fields')
    if value['status'] not in {'observed', 'not_observed'} or value['source_anchor'] != 'prediction':
        raise HREError('invalid_content_annotations', 'Annotation status must be explicit and its source anchor must be prediction (A)')
    if not all(isinstance(value[k], str) and value[k].strip() for k in ('critical_content_rules_version', 'notes')):
        raise HREError('invalid_content_annotations', 'Rule version and notes must be nonempty text')
    for field in ('protected_face_regions', 'protected_text_regions', 'protected_geometry_landmarks', 'protected_object_regions'):
        regions = value[field]
        if not isinstance(regions, list):
            raise HREError('invalid_content_annotations', field + ' must be a list')
        landmark = field == 'protected_geometry_landmarks'
        identity, coordinates = ('landmark_id', 'point') if landmark else ('region_id', 'bbox')
        required = {identity, 'coordinate_system', coordinates, 'instruction'}
        for region in regions:
            if not isinstance(region, dict) or not required <= set(region) or set(region) - required - {'notes', 'text', 'identity'}:
                raise HREError('invalid_content_annotations', field + ' requires documented region records')
            if region['coordinate_system'] != 'canonical_norm' or not all(isinstance(region[k], str) and region[k].strip() for k in (identity, 'instruction')) or any(not isinstance(region[k], str) for k in ('notes', 'text', 'identity') if k in region):
                raise HREError('invalid_content_annotations', 'Regions must bind normalized canonical A coordinates and text instructions')
            coords = region[coordinates]
            if not isinstance(coords, list) or len(coords) != (2 if landmark else 4) or not all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in coords) or (not landmark and not (coords[0] < coords[2] and coords[1] < coords[3])):
                raise HREError('invalid_content_annotations', 'Invalid A point or half-open [x0,y0,x1,y1] bbox')
        if len({x[identity] for x in regions}) != len(regions):
            raise HREError('invalid_content_annotations', 'Duplicate protection region identity')
    return deepcopy(value)


def freeze_templates(case_root: Path) -> dict:
    """Snapshot actual installed bytes once; their identities enter config_sha256."""
    sources = {}
    for stage in sorted(STAGES):
        data = (files('hre') / 'resources' / 'prompts' / (stage + '.j2')).read_bytes()
        relative = 'prompts/' + stage + '.j2'
        atomic_write(safe_path(case_root, relative), data)
        sources[stage] = {'stage': stage, 'path': relative, 'sha256': sha256_bytes(data)}
    write_json(safe_path(case_root, 'prompts/manifest.json'), {'schema_version': 'hre_template_sources_v1', 'templates': sources})
    return {stage: source['sha256'] for stage, source in sources.items()}


def template_source(case_root: Path, stage: str) -> dict:
    config = read_json(safe_path(case_root, 'config.json', must_exist=True))
    sources = read_json(safe_path(case_root, 'prompts/manifest.json', must_exist=True))
    source = sources['templates'][stage]
    if source != {'stage': stage, 'path': 'prompts/' + stage + '.j2', 'sha256': config.get('prompt_template_sha256', {}).get(stage)} or file_sha256(safe_path(case_root, source['path'], must_exist=True)) != source['sha256']:
        raise HREError('template_source_mismatch', 'Frozen template source differs from hashed case configuration')
    return deepcopy(source)


def dispatch_sources(case_root: Path, stage: str, request: dict) -> dict:
    sources = [template_source(case_root, stage)]
    proof = {'templates': sources}
    if stage == 'execute' and request['payload']['prompt_source_task_id'].startswith('direct_prompt_'):
        source = request['payload']['prompt_source_task_id']
        sources.append(template_source(case_root, 'direct_ref'))
        proof['direct_prompt_files'] = [{'path': f'tasks/{source}/{name}', 'sha256': file_sha256(safe_path(case_root, f'tasks/{source}/{name}', must_exist=True))} for name in ('manifest.json', 'prompt.txt')]
    return proof


def validate_execution_templates(case_root: Path) -> dict:
    """Require execution-time source proof; never synthesize it for old journals."""
    config = read_json(safe_path(case_root, 'config.json', must_exist=True))
    identities = config.get('prompt_template_sha256')
    if not isinstance(identities, dict) or set(identities) != STAGES:
        raise HREError('unverified_prompt_execution', 'No complete execution-time template identity contract')
    freeze = read_json(safe_path(case_root, 'freeze.json', must_exist=True))['files']
    for stage in STAGES:
        source = template_source(case_root, stage)
        if freeze.get(source['path']) != source['sha256']:
            raise HREError('unverified_prompt_execution', 'Template source was not frozen at initialization')
    for path in sorted((case_root / 'transactions').glob('*.json')):
        tx = read_json(path)
        task = tx['next_task']
        if not task:
            continue
        request = read_json(safe_path(case_root, task['request_path'], must_exist=True))
        expected = dispatch_sources(case_root, request['stage'], request)
        if task.get('template_source_proof') != expected:
            raise HREError('unverified_prompt_execution', 'Issued task has no matching source proof')
        directory = Path(task['request_path']).parent
        dispatch = read_json(safe_path(case_root, (directory / 'dispatch.json').as_posix(), must_exist=True))
        if dispatch.get('template_source_proof') != expected or file_sha256(safe_path(case_root, (directory / 'dispatch.json').as_posix(), must_exist=True)) != task.get('dispatch_sha256'):
            raise HREError('unverified_prompt_execution', 'Dispatch source proof differs from committed journal')
    return identities


def validate_edit_contract(stage: str, payload: dict) -> None:
    """Reject known conflicting editor instructions without claiming general NLP.

    The fixed execution prefix supplies A when dynamic text leaves it implicit.
    Explicit wrong sources, positive content copying, global rendering freezes,
    and file/JSON workflow commands are never repaired into different wording.
    Negation is scoped to individual clauses and the matched command.
    Structured source/gap/feedback support is checked by Controller separately.
    """
    if stage not in {'compose', 'refine', 'execute', 'direct_ref'}:
        raise HREError('invalid_stage', stage)
    text = payload.get('edit_prompt')
    if not isinstance(text, str) or not text.strip():
        raise HREError('prohibited_edit_contract', 'A nonempty editing instruction is required')
    clauses = re.split(r'[.;\n]+|\b(?:but|however|while|then)\b', text.lower())
    rules = [
        ('wrong editing source', r'\b(?:edit|enhance|modify|retouch|adjust|work\s+(?:from|on)|start\s+from|use)\s+(?:(?:the|attached|previous|original|image|photo|candidate|output)\s+)*(?:[bc]\b|candidate\b)'),
        ('copying B content', r'\b(?:copy|transfer|paste|replace|import|borrow|replicate|reproduce|take)\b[^;.!?]{0,140}(?:\b(?:image|photo|reference)\s+b\b|\bb[\'’]s\b|\bfrom\s+b\b|\bb\s+(?:into|onto)\s+a\b)'),
        ('freezing original rendering', r'\b(?:do\s+not|don[\'’]t|never)\s+(?:change|alter|adjust|modify)\b[^;.!?]{0,30}\boriginal\b[^;.!?]{0,25}\b(?:brightness|exposure|colou?rs?|saturation|contrast|white\s+balance)\b'),
        ('freezing original rendering', r'\b(?:keep|preserve|retain|maintain|freeze|leave)\b[^;.!?]{0,40}\b(?:original|unchanged|unaltered)\b[^;.!?]{0,45}\b(?:brightness|exposure|colou?rs?|saturation|contrast|white\s+balance|tonal\s+rendering)\b'),
        ('freezing original rendering', r'\b(?:keep|preserve|retain|maintain|freeze|leave)\b[^;.!?]{0,35}\b(?:brightness|exposure|colou?rs?|saturation|contrast|white\s+balance)\b[^;.!?]{0,30}\b(?:unchanged|unaltered|the\s+same)\b'),
        ('workflow output command', r'\b(?:return|output|respond|emit|produce)\b[^;.!?]{0,30}\bjson\b'),
        ('workflow file command', r'\b(?:save|write|export|download)\b[^;.!?]{0,80}\b(?:file|path|directory|folder|disk|output)\b'),
        ('workflow path command', r'(?:/[^\s/]+/|[a-z]:\\|https?://|file://)'),
        ('tool or metric narration', r'\b(?:t[1-4]_(?:ocr|face|depth|segmentation)|roi_compare|stats|ssim|psnr|evidence_id)\b'),
    ]
    for clause in clauses:
        for description, pattern in rules:
            for match in re.finditer(pattern, clause):
                # A short preceding negation applies only to this verb/match;
                # "Do not copy B; edit C" is split and the second clause rejects.
                prefix = clause[:match.start()]
                if re.search(r'\b(?:do\s+not|don[\'’]t|never|avoid|must\s+not)\s+(?:\w+\s+){0,2}$', prefix):
                    continue
                # Rendering descriptions may cite B as a goal; the prohibited
                # copying rule targets scene content or an entire image only.
                if description == 'copying B content' and re.search(r'\b(?:brightness|colou?rs?|contrast|rendering|saturation|tonal)\b', clause[match.start():]) and not re.search(r'\b(?:person|people|face|identity|identities|text|objects?|textures?|scene|content|viewpoint|camera|lighting|details?)\b', clause[match.start():]):
                    continue
                if description == 'wrong editing source' and re.match(r'use\b', match.group()) and re.search(r'\bb\b', match.group()) and re.search(r'\b(?:rendering|appearance)\s+reference\b', clause[match.end():]) and not re.search(r'\b(?:edit(?:ing)?\s+source|content\s+source|main\s+image)\b', clause[match.end():]):
                    continue
                raise HREError('prohibited_edit_contract', description)

def _binding_check(stage: str, bindings: list[dict]) -> None:
    expected = ['A', 'B', 'C'] if stage in {'verify', 'refine'} else ['A', 'B']
    if not isinstance(bindings, list) or not all(isinstance(b, dict) for b in bindings) or [b.get('label') for b in bindings] != expected:
        raise HREError('image_binding_mismatch', f'{stage} requires exactly {expected}')
    if len({b.get('asset_id') for b in bindings}) != len(expected):
        raise HREError('image_binding_mismatch', 'Asset IDs must be distinct')
    for binding in bindings:
        sha = binding.get('canonical_sha256', '')
        if not isinstance(sha, str) or len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
            raise HREError('image_binding_mismatch', 'A real canonical SHA256 is required')


def render_stage(stage: str, context: dict, *, case_root: Path | None = None) -> str:
    if stage not in STAGES:
        raise HREError('invalid_stage', stage)
    # Let StrictUndefined produce the useful missing-field error before validation.
    if case_root is not None:
        template_source(Path(case_root), stage)
    template_root = Path(case_root) / 'prompts' if case_root is not None else files('hre') / 'resources' / 'prompts'
    env = Environment(loader=FileSystemLoader(str(template_root)),
                      undefined=StrictUndefined, autoescape=False)
    source = env.loader.get_source(env, f'{stage}.j2')[0]
    for field in sorted(meta.find_undeclared_variables(env.parse(source))):
        if field not in context:
            str(env.undefined(name=field))
    rendered = env.get_template(f'{stage}.j2').render(**context)
    try:
        bundle = json.loads(rendered, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (ValueError, TypeError) as exc:
        raise HREError('invalid_prompt_json', str(exc)) from exc
    _binding_check(stage, bundle['image_bindings'])
    return rendered


def verified_json(case_root: Path, relative: str, expected_sha: str) -> dict:
    path = safe_path(case_root, relative, must_exist=True)
    if file_sha256(path) != expected_sha:
        raise HREError('artifact_hash_mismatch', relative)
    return read_json(path)


def _response_payload(case_root: Path, task_id: str, sha: str, stage: str, request: dict) -> tuple[dict, Path]:
    task_dir = safe_path(case_root, f'tasks/{task_id}', must_exist=True)
    # During a Controller transaction the verified submission precedes its
    # accepted projection. Find only exact bytes; never choose a recent response.
    candidates = [task_dir / 'accepted' / 'response.json']
    candidates += sorted(task_dir.glob('**/response.json'))
    matched = []
    for path in candidates:
        if path.is_file():
            safe_path(case_root, path.relative_to(case_root).as_posix(), must_exist=True)
            if file_sha256(path) == sha:
                matched.append(path)
    if not matched:
        raise HREError('missing_stage_context', f'No hash-matched {stage} response for {task_id}')
    response = read_json(matched[0])
    validate_schema('response', response)
    if any(response[key] != request[key] for key in ('case_id', 'case_revision', 'config_sha256')):
        raise HREError('context_identity_mismatch', task_id)
    if response['task_id'] != task_id or response['stage'] != stage or response['status'] != 'ok':
        raise HREError('context_identity_mismatch', task_id)
    for asset in response['input_assets']:
        validate_asset(asset, case_root)
    return response, matched[0]


def _evidence_summary(case_root: Path, request: dict, state: dict, diagnosis: dict, adapter: dict, diagnosis_path: Path) -> list[dict]:
    from .evidence import validate_snapshot
    payload = request['payload']
    snapshot = verified_json(case_root, payload['evidence_snapshot_path'], payload['evidence_snapshot_sha256'])
    plan = adapter.get('evidence_plan', state['evidence_plan'])
    stable = [{k: item[k] for k in ('tool_id', 'roles', 'roi_pair_ids', 'required')} for item in plan]
    expected = [{'tool_id': item['tool'], **{k: item[k] for k in ('roles', 'roi_pair_ids', 'required')}} for item in diagnosis['tool_plan']]
    if stable != expected:
        raise HREError('evidence_plan_mismatch', 'Dispatched plan differs from diagnosis tool plan')
    validate_snapshot(case_root, snapshot, {**state, 'evidence_plan': plan, 'diagnosis_task_id': payload['diagnosis_task_id'], '_accepted_diagnosis': {'task_id': payload['diagnosis_task_id'], 'response_path': diagnosis_path.relative_to(case_root).as_posix(), 'response_sha256': payload['diagnosis_response_sha256']}})
    if snapshot['scope'] != 'composition' or snapshot['diagnosis_task_id'] != payload['diagnosis_task_id']:
        raise HREError('evidence_binding_mismatch', 'Composition snapshot diagnosis/scope differs')
    records = []
    for item in snapshot['evidence']:
        record = verified_json(case_root, item['path'], item['sha256'])
        records.append(record)
    return records


def _source_execution(case_root: Path, candidate: dict, request: dict) -> dict:
    binding = candidate['candidate_binding']
    directory = safe_path(case_root, f'tasks/{binding["task_id"]}', must_exist=True)
    matches = []
    for path in sorted(directory.glob('attempts/*/request.json')):
        source = read_json(safe_path(case_root, path.relative_to(case_root).as_posix(), must_exist=True))
        validate_schema('request', source)
        if request_hash(source) != source['request_sha256']:
            raise HREError('request_hash_mismatch', binding['task_id'])
        if source['stage'] == 'execute' and source['payload']['generation_id'] == binding['generation_id']:
            if any(source[k] != request[k] for k in ('case_id', 'case_revision', 'config_sha256')) or source['round'] != binding['round'] or source['task_id'] != binding['task_id']:
                raise HREError('candidate_binding_mismatch', 'Source execution identity differs')
            if source['input_assets'] != [a for a in request['input_assets'] if a['role'] != 'candidate']:
                raise HREError('candidate_binding_mismatch', 'Source execution uses another A/B pair')
            matches.append(source)
    if not matches:
        raise HREError('candidate_binding_mismatch', 'No real hash-verified source execution request')
    return matches[0]


def _candidate_geometry_binding(case_root: Path, candidate: dict, request: dict, verify_payload: dict) -> None:
    report = verified_json(case_root, verify_payload['geometry_report_path'], verify_payload['geometry_report_sha256'])
    master = verify_payload['candidate_id']
    if request['payload']['candidate_id'] != master or report.get('raw_asset_id') != master:
        raise HREError('candidate_binding_mismatch', 'Candidate master identity differs from real geometry audit')
    if candidate['asset_id'] == master:
        if report.get('raw_sha256') != candidate['sha256']:
            raise HREError('candidate_binding_mismatch', 'Candidate master bytes differ')
    elif report.get('derived_asset') != candidate:
        raise HREError('candidate_binding_mismatch', 'Observed C is not the audited derivation of this master')
    source = _source_execution(case_root, candidate, request)
    if report.get('policy') != source['payload']['geometry_policy'] or report.get('source_file') != candidate.get('source_file'):
        raise HREError('candidate_binding_mismatch', 'Geometry audit differs from the frozen source policy or raw bytes')
    from .protocol import validate_submission
    state = CaseStore(case_root).load()
    directory = safe_path(case_root, f'tasks/{candidate["candidate_binding"]["task_id"]}', must_exist=True)
    for marker in sorted(directory.glob('**/done.json')):
        try:
            done = read_json(safe_path(case_root, marker.relative_to(case_root).as_posix(), must_exist=True))
            response = verified_json(case_root, done['response_file'], done['response_sha256'])
            source_request = read_json(safe_path(case_root, f'tasks/{response["task_id"]}/attempts/{response["attempt"]:03d}/request.json', must_exist=True))
            result = validate_submission(case_root, marker, source_request, state)['response']
            if result['status'] == 'ok' and result['stage'] == 'execute':
                master_asset = result['payload']['candidate_asset']
                if master_asset['asset_id'] == master and master_asset['sha256'] == report['raw_sha256'] and master_asset['candidate_binding'] == candidate['candidate_binding'] and master_asset['source_file']['sha256'] == candidate['source_file']['sha256']:
                    return
        except (HREError, KeyError):
            continue
    raise HREError('candidate_binding_mismatch', 'Observed C has no actual matching source execution submission')


def _validate_prompt_source(case_root: Path, request: dict) -> None:
    payload = request['payload']
    source_id = payload['prompt_source_task_id']
    directory = safe_path(case_root, f'tasks/{source_id}', must_exist=True)
    artifact = directory / 'manifest.json'
    if source_id.startswith('direct_prompt_'):
        state = CaseStore(case_root).load()
        expected = f'direct_prompt_{request["case_id"]}_rev_{request["case_revision"]}'
        if state['profile_id'] not in {'direct_ref', 'direct_best_of_3'} or source_id != expected:
            raise HREError('prompt_source_mismatch', 'Direct artifact is not the frozen source for this case profile')
        source = read_json(artifact)
        if source.get('task_id') != source_id or source.get('config_sha256') != request['config_sha256'] or source.get('prompt_version') != 'direct_ref_v1' or source.get('edit_prompt') != payload['edit_prompt'] or source.get('prompt_sha256') != sha256_bytes(payload['edit_prompt'].encode()):
            raise HREError('prompt_source_mismatch', 'Direct prompt artifact differs')
        validate_edit_contract('direct_ref', source)
        return
    matches = []
    accepted = directory / 'accepted' / 'response.json'
    paths = [accepted] if accepted.is_file() else sorted(directory.glob('**/response.json'))
    for path in paths:
        source = read_json(safe_path(case_root, path.relative_to(case_root).as_posix(), must_exist=True))
        if source.get('status') != 'ok' or source.get('stage') not in {'compose', 'refine'} or source.get('task_id') != source_id:
            continue
        if source.get('payload', {}).get('edit_prompt') != payload['edit_prompt']:
            continue
        validate_schema('response', source)
        source_request = read_json(safe_path(case_root, f'tasks/{source_id}/attempts/{source["attempt"]:03d}/request.json', must_exist=True))
        validate_schema('request', source_request)
        if request_hash(source_request) != source['request_sha256'] or any(source_request[key] != source[key] for key in source_request if key != 'payload'):
            raise HREError('prompt_source_mismatch', 'Editing source does not echo its real frozen request')
        if any(source[k] != request[k] for k in ('case_id', 'case_revision', 'config_sha256')):
            raise HREError('prompt_source_mismatch', 'Editing prompt source belongs to another case')
        validate_edit_contract(source['stage'], source['payload'])
        matches.append(source)
    if not matches:
        raise HREError('prompt_source_mismatch', 'No bound Compose/Refine editing payload')

def build_context(case_root: Path, request: dict) -> dict:
    case_root = Path(case_root).absolute()
    validate_schema('request', request)
    if request_hash(request) != request['request_sha256']:
        raise HREError('request_hash_mismatch', 'Request bytes contract differs')
    state = CaseStore(case_root).load()
    config = read_json(safe_path(case_root, 'config.json', must_exist=True))
    if config_hash(config) != request['config_sha256'] or state['config_sha256'] != request['config_sha256']:
        raise HREError('config_hash_mismatch', 'Frozen configuration differs')
    if any(state[key] != request[key] for key in ('case_id', 'case_revision')):
        raise HREError('request_identity_mismatch', 'Request belongs to another case revision')
    expected_roles = {'prediction', 'reference', 'candidate'} if request['stage'] in {'verify', 'refine'} else {'prediction', 'reference'}
    if {asset['role'] for asset in request['input_assets']} != expected_roles or len(request['input_assets']) != len(expected_roles):
        raise HREError('image_binding_mismatch', 'Stage image role set differs')
    by_role = {asset['role']: asset for asset in request['input_assets']}
    for frozen in state['inputs']:
        if by_role.get(frozen['role']) != frozen:
            raise HREError('image_binding_mismatch', 'Frozen A/B binding differs')
    for asset in request['input_assets']:
        validate_asset(asset, case_root)
    stage, payload = request['stage'], request['payload']
    bindings = [{'label': ROLE_LABEL[a['role']], 'asset_id': a['asset_id'], 'canonical_sha256': a['sha256']}
                for a in sorted(request['input_assets'], key=lambda a: ROLE_LABEL[a['role']])]
    _binding_check(stage, bindings)
    result = {'image_bindings': bindings}
    if stage in {'verify', 'refine'}:
        binding = by_role['candidate'].get('candidate_binding', {})
        if any(binding.get(key) != request[key] for key in ('case_id', 'case_revision')):
            raise HREError('candidate_binding_mismatch', 'Candidate belongs to another case revision')
        source_round = request['round'] if stage == 'verify' else payload['source_round']
        if binding.get('round') != source_round:
            raise HREError('candidate_binding_mismatch', 'Candidate belongs to another source round')
        if binding.get('prediction_sha256') != by_role['prediction']['sha256'] or binding.get('reference_sha256') != by_role['reference']['sha256']:
            raise HREError('candidate_binding_mismatch', 'Candidate belongs to another A/B pair')
    if stage == 'execute':
        if payload['prediction_asset_id'] != by_role['prediction']['asset_id'] or payload['reference_asset_id'] != by_role['reference']['asset_id']:
            raise HREError('image_binding_mismatch', 'Execute source ID differs')
        validate_edit_contract('execute', payload)
        _validate_prompt_source(case_root, request)
        result['edit_prompt'] = payload['edit_prompt']
        return result
    adapter = read_json(safe_path(case_root, f'tasks/{request["task_id"]}/attempts/{request["attempt"]:03d}/adapter_context.json', must_exist=True))
    validate_schema('response', adapter['model_observed'], '/properties/model_observed')
    if adapter.get('session_id') is not None and not isinstance(adapter['session_id'], str):
        raise HREError('invalid_adapter_context', 'session_id must be null or text')
    result.update({
        'response_identity': {k: v for k, v in request.items() if k != 'payload'},
        'model_observed': adapter['model_observed'],
        'session_id': adapter['session_id'],
        'result_schema': read_json(Path(str(files('hre') / 'resources' / 'schemas' / f'{ {"diagnose":"diagnosis","compose":"composition","verify":"verification","refine":"refinement"}[stage]}.schema.json'))),
    })
    if stage == 'diagnose':
        if payload['roi_manifest_path'] is None:
            if payload['roi_manifest_sha256'] is not None:
                raise HREError('roi_binding_mismatch', 'ROI path and SHA must both be absent')
            pairs = config['roi_manifest']
        else:
            roi = verified_json(case_root, payload['roi_manifest_path'], payload['roi_manifest_sha256'])
            pairs = roi.get('roi_pairs', roi.get('pairs')) if isinstance(roi, dict) else roi
            if pairs is None:
                raise HREError('missing_stage_context', 'ROI manifest lacks pairs')
            if pairs != config['roi_manifest']:
                raise HREError('roi_binding_mismatch', 'ROI pairs differ from frozen config')
        result.update(manual_roi_pairs=pairs, available_tools=payload['available_tools'], evidence_summary=[])
    elif stage == 'compose':
        response, source_path = _response_payload(case_root, payload['diagnosis_task_id'], payload['diagnosis_response_sha256'], 'diagnose', request)
        result.update(diagnosis=response['payload'], evidence_summary=_evidence_summary(case_root, request, state, response['payload'], adapter, source_path))
    elif stage == 'verify':
        candidate = by_role['candidate']
        if candidate.get('candidate_binding', {}).get('generation_id') != payload['generation_id']:
            raise HREError('candidate_binding_mismatch', 'Verifier generation differs')
        _candidate_geometry_binding(case_root, candidate, request, payload)
        annotations = normalize_protected_content(config['protected_content'])
        protected = {'rubric': PROTECTED_RUBRIC, 'annotations': annotations} if isinstance(annotations, dict) else PROTECTED_RUBRIC + annotations
        result.update(protected_content=protected, reference_limitations=config['reference_limitations'])
    elif stage == 'refine':
        response, _ = _response_payload(case_root, payload['verification_task_id'], payload['verification_response_sha256'], 'verify', request)
        source = next((a for a in response['input_assets'] if a['role'] == 'candidate'), None)
        if source != by_role['candidate'] or response['round'] != payload['source_round']:
            raise HREError('candidate_binding_mismatch', 'Refinement verification source differs')
        verify_request = read_json(safe_path(case_root, f'tasks/{response["task_id"]}/attempts/{response["attempt"]:03d}/request.json', must_exist=True))
        if request_hash(verify_request) != response['request_sha256']:
            raise HREError('request_hash_mismatch', 'Source verification request changed')
        _candidate_geometry_binding(case_root, source, request, verify_request['payload'])
        binding = source['candidate_binding']
        source_task = safe_path(case_root, f'tasks/{binding["task_id"]}', must_exist=True)
        source_requests = []
        for path in sorted(source_task.glob('attempts/*/request.json')):
            actual = read_json(safe_path(case_root, path.relative_to(case_root).as_posix(), must_exist=True))
            validate_schema('request', actual)
            if request_hash(actual) != actual['request_sha256']:
                raise HREError('request_hash_mismatch', binding['task_id'])
            if actual['stage'] == 'execute' and actual['payload']['generation_id'] == binding['generation_id']:
                source_requests.append(actual)
        if not source_requests or any(actual['payload']['edit_prompt'] != payload['previous_edit_prompt'] or actual['round'] != payload['source_round'] for actual in source_requests):
            raise HREError('context_identity_mismatch', 'Previous editing text differs from the bound source execution')
        result.update(previous_edit_prompt=payload['previous_edit_prompt'], verification=response['payload'], source_round=payload['source_round'])
    return result
