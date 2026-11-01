"""Independent, evidence-based desktop capability records; no UI automation."""
from __future__ import annotations

from pathlib import Path
from datetime import datetime

from PIL import Image

from .models import HREError, file_sha256, now, request_hash, validate_schema
from .paths import make_id, safe_path
from .storage import CaseStore, case_lock, read_json, write_json

CAPABILITY_NAMES = ('local_file_io', 'role_dispatch', 'two_image_edit', 'image_save')


def _controller_io(case_root: Path) -> dict:
    folder = case_root / 'capability_probes' / make_id('controller_io')
    folder.mkdir(parents=True)
    image_path = folder / 'local_test.png'
    # Clearly synthetic local IO test; never evidence of editor/ChatGPT access.
    Image.new('RGB', (2, 2), (13, 27, 41)).save(image_path)
    with Image.open(image_path) as im:
        im.load()
        if im.size != (2, 2) or im.getpixel((0, 0)) != (13, 27, 41):
            raise HREError('controller_probe_failed', 'Image read mismatch')
    record_path = folder / 'local_test.json'
    write_json(record_path, {'purpose': 'synthetic Controller filesystem IO test', 'image_sha256': file_sha256(image_path)})
    if read_json(record_path)['image_sha256'] != file_sha256(image_path):
        raise HREError('controller_probe_failed', 'JSON read mismatch')
    return {'status': 'passed', 'scope': 'Controller filesystem only',
            'artifacts': [{'path': p.relative_to(case_root).as_posix(), 'sha256': file_sha256(p)}
                          for p in (image_path, record_path)]}


CAPABILITY_CLAIMS = {
    'local_file_io': 'chatgpt_read_image_and_write_json',
    'role_dispatch': 'requested_role_session_dispatched',
    'two_image_edit': 'two_bound_images_edited',
    'image_save': 'generated_image_saved',
}


def _image_artifact(path: Path) -> None:
    try:
        with Image.open(path) as image:
            image.load()
    except Exception as exc:
        raise HREError('probe_evidence_invalid', 'Image evidence must contain actual decodable bytes') from exc


def _validated_observation(name: str, case_root: Path, evidence: dict) -> dict:
    if evidence.get('capability') != name or evidence.get('scope') != 'chatgpt_desktop':
        raise HREError('probe_scope_mismatch', 'Evidence must name this desktop capability')
    observer, timestamp = evidence.get('observer'), evidence.get('observed_at')
    if evidence.get('status') not in {'passed', 'failed'} or not isinstance(observer, str) or not observer.strip() or not isinstance(timestamp, str):
        raise HREError('probe_evidence_invalid', 'Typed observer, observed status, and zoned time are required')
    try:
        observed = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError('Timezone is required')
    except ValueError as exc:
        raise HREError('probe_evidence_invalid', 'observed_at must be a zoned ISO timestamp') from exc
    steps, artifacts = evidence.get('steps'), evidence.get('artifacts')
    if not isinstance(steps, list) or not steps or not all(isinstance(step, str) and step.strip() for step in steps):
        raise HREError('probe_evidence_invalid', 'Describe actual observed steps')
    if not isinstance(artifacts, list) or not artifacts:
        raise HREError('probe_evidence_missing', 'Capability-specific actual artifacts are required')
    ref = evidence.get('observation')
    if not isinstance(ref, dict) or set(ref) != {'path', 'sha256'}:
        raise HREError('probe_evidence_missing', 'Provide a hash-bound hre_capability_observation_v1 record')
    path = safe_path(case_root, ref['path'], must_exist=True)
    if file_sha256(path) != ref['sha256']:
        raise HREError('probe_evidence_hash_mismatch', ref['path'])
    record = read_json(path)
    required = {'kind', 'capability', 'scope', 'claim', 'task_id', 'request_sha256', 'stage', 'status', 'observer', 'observed_at', 'steps', 'artifacts'}
    if set(record) != required or record['kind'] != 'hre_capability_observation_v1' or record['claim'] != CAPABILITY_CLAIMS[name]:
        raise HREError('probe_evidence_invalid', 'Observation kind and capability-specific claim differ')
    if any(record[key] != evidence[key] for key in ('capability', 'scope', 'status', 'observer', 'observed_at', 'steps', 'artifacts')):
        raise HREError('probe_evidence_invalid', 'Attribution or evidence differs from the immutable observation')
    directory = safe_path(case_root, f'tasks/{record["task_id"]}', must_exist=True)
    requests = []
    for source in sorted(directory.glob('attempts/*/request.json')):
        request = read_json(safe_path(case_root, source.relative_to(case_root).as_posix(), must_exist=True))
        validate_schema('request', request)
        if request_hash(request) == record['request_sha256'] == request['request_sha256']:
            requests.append(request)
    if len(requests) != 1 or requests[0]['stage'] != record['stage']:
        raise HREError('probe_task_mismatch', 'Observation must bind one actual frozen task and its stage')
    request = requests[0]
    state = CaseStore(case_root).load()
    if any(request[key] != state[key] for key in ('case_id', 'case_revision', 'config_sha256')):
        raise HREError('probe_task_mismatch', 'Observation task belongs to another case revision')
    by_purpose = {}
    for artifact in artifacts:
        if not isinstance(artifact, dict) or set(artifact) != {'path', 'sha256', 'purpose'} or not isinstance(artifact['purpose'], str):
            raise HREError('probe_evidence_invalid', 'Each artifact requires path, hash, and capability-specific purpose')
        actual = safe_path(case_root, artifact['path'], must_exist=True)
        if file_sha256(actual) != artifact['sha256']:
            raise HREError('probe_evidence_hash_mismatch', artifact['path'])
        if artifact['purpose'] in by_purpose:
            raise HREError('probe_evidence_invalid', 'Artifact purposes must be unique')
        by_purpose[artifact['purpose']] = (actual, artifact)
    if evidence['status'] == 'failed':
        if 'failure_observation' not in by_purpose:
            raise HREError('probe_evidence_missing', 'A failed probe needs its actual failure observation file')
        return record
    required_purposes = {
        'local_file_io': {'input_image', 'written_json'},
        'role_dispatch': {'dispatch_observation'},
        'two_image_edit': {'input_A', 'input_B', 'output_image', 'done_manifest'},
        'image_save': {'saved_image', 'done_manifest'},
    }[name]
    if set(by_purpose) != required_purposes:
        raise HREError('probe_evidence_missing', f'{name} requires artifact purposes {sorted(required_purposes)}')
    if name == 'role_dispatch':
        _image_artifact(by_purpose['dispatch_observation'][0])
    elif name == 'local_file_io':
        image_ref = by_purpose['input_image'][1]
        if not any(asset['sha256'] == image_ref['sha256'] for asset in request['input_assets']):
            raise HREError('probe_evidence_invalid', 'Read image is not bound to the observed task')
        _image_artifact(by_purpose['input_image'][0])
        written = read_json(by_purpose['written_json'][0]);validate_schema('response', written)
        if written['task_id'] != request['task_id'] or written['request_sha256'] != request['request_sha256'] or written['model_observed']['transport'] not in {'desktop_manual', 'desktop_bridge'}:
            raise HREError('probe_evidence_invalid', 'Written JSON is not the observed desktop task response')
    else:
        if request['stage'] != 'execute':
            raise HREError('probe_task_mismatch', 'Image editing/saving evidence requires an actual execute task')
        from .protocol import validate_submission
        result = validate_submission(case_root, by_purpose['done_manifest'][0], request, state)
        response = result['response']
        if response['status'] != 'ok' or response['model_observed']['transport'] not in {'desktop_manual', 'desktop_bridge'}:
            raise HREError('probe_evidence_invalid', 'Probe output is not an actual desktop image submission')
        saved = by_purpose['output_image' if name == 'two_image_edit' else 'saved_image']
        if saved[1]['sha256'] != response['payload']['candidate_asset']['source_file']['sha256']:
            raise HREError('probe_evidence_invalid', 'Observed saved output is not the bound generated raw image')
        _image_artifact(saved[0])
        if name == 'two_image_edit':
            for purpose, role in (('input_A', 'prediction'), ('input_B', 'reference')):
                asset = next(asset for asset in request['input_assets'] if asset['role'] == role)
                if by_purpose[purpose][1]['sha256'] != asset['sha256']:
                    raise HREError('probe_evidence_invalid', 'Observed A/B attachments differ from the actual editing task')
                _image_artifact(by_purpose[purpose][0])
    return record

def run_capability_probe(name: str, case_root: Path, *, evidence: dict | None = None) -> dict:
    """Without user-observed evidence desktop capabilities remain untested.

    Evidence includes typed attribution, real task/stage/claim, purpose-bound
    actual artifacts, and observation {path,sha256} referencing a strict
    hre_capability_observation_v1 record. See CAPABILITY_CLAIMS.
    A record is an attributed user observation, not automatic re-verification.
    """
    if name not in CAPABILITY_NAMES:
        raise HREError('unknown_capability', name)
    case_root = Path(case_root).absolute()
    case_root.mkdir(parents=True, exist_ok=True)
    imported = None
    if evidence is not None:
        _validated_observation(name, case_root, evidence)
        imported = dict(evidence)
    with case_lock(case_root):
        record_path = case_root / 'capabilities.json'
        record = read_json(record_path) if record_path.exists() else {
            'schema_version': 'ref_enhance_v1',
            'capabilities': {key: {'capability': key, 'status': 'untested', 'scope': 'chatgpt_desktop', 'evidence': None} for key in CAPABILITY_NAMES}}
        result = record['capabilities'][name]
        if imported is not None:
            result = {'capability': name, 'status': imported['status'], 'scope': 'chatgpt_desktop',
                      'evidence': imported, 'verification': 'user_observed_evidence_import'}
        else:
            result = dict(result)
        if name == 'local_file_io':
            result['controller_file_io'] = _controller_io(case_root)
        result['recorded_at'] = now()
        record['capabilities'][name] = result
        write_json(record_path, record)
        return result
