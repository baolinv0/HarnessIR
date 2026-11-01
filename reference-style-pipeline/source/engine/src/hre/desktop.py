"""Manual image handoff. Never contacts a model or changes Controller state."""
from __future__ import annotations

import shutil
from pathlib import Path

from .assets import AssetRegistry, validate_asset
from .models import HREError, file_sha256, request_hash, sha256_bytes, validate_schema
from .paths import make_id, safe_path
from .prompts import build_context, render_stage
from .storage import CaseStore, atomic_write, read_json, write_json


def export_task_bundle(task: dict, destination: Path, *, case_root: Path) -> Path:
    """Export an audit package and a separate editor-only A/B/text folder."""
    case_root, destination = Path(case_root).absolute(), Path(destination).absolute()
    frozen_dir = safe_path(case_root, f'tasks/{task["task_id"]}/attempts/{task["attempt"]:03d}', must_exist=True)
    frozen = read_json(safe_path(case_root, (frozen_dir / 'request.json').relative_to(case_root).as_posix(), must_exist=True))
    if frozen != task:
        raise HREError('request_identity_mismatch', 'Export must match the frozen request file')
    context = build_context(case_root, task)
    rendered = render_stage(task['stage'], context, case_root=case_root)
    if (frozen_dir / 'dispatch.json').is_file():
        dispatch = read_json(frozen_dir / 'dispatch.json')
        if dispatch['prompt_sha256'] != sha256_bytes(rendered.encode('utf-8')):
            raise HREError('prompt_hash_mismatch', 'Rendered context differs from frozen dispatch')
    destination.mkdir(parents=True, exist_ok=True)
    bundle = destination / f"{task['task_id']}_a{task['attempt']:03d}"
    if bundle.exists():
        raise HREError('export_exists', str(bundle))
    bundle.mkdir()
    attachments = []
    for binding in context['image_bindings']:
        asset = next(a for a in task['input_assets'] if a['asset_id'] == binding['asset_id'])
        validate_asset(asset, case_root)
        relative = f"attachments/{binding['label']}.png"
        target = bundle / relative
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(safe_path(case_root, asset['path'], must_exist=True), target)
        if file_sha256(target) != asset['sha256']:
            raise HREError('artifact_hash_mismatch', relative)
        attachments.append({'label': binding['label'], 'asset_id': asset['asset_id'], 'path': relative, 'sha256': asset['sha256']})
    write_json(bundle / 'request.json', task)
    shutil.copytree(safe_path(case_root, 'prompts', must_exist=True), bundle / 'prompts')
    if (frozen_dir / 'dispatch.json').is_file():
        shutil.copyfile(frozen_dir / 'dispatch.json', bundle / 'dispatch.json')
    for name in ('config.json', 'manifest.json'):
        shutil.copyfile(safe_path(case_root, name, must_exist=True), bundle / name.replace('manifest', 'case_manifest'))
    atomic_write(bundle / 'prompt.txt', rendered.encode('utf-8'))
    if task['stage'] == 'execute':
        import json
        editor = bundle / 'editor'
        editor.mkdir()
        for attachment in attachments:
            shutil.copyfile(bundle / attachment['path'], editor / f"{attachment['label']}.png")
        atomic_write(editor / 'edit_prompt.txt', json.loads(rendered)['edit_prompt'].encode('utf-8'))
        from .reference_runtime import mask_transport
        transport=mask_transport(case_root,task)
        if transport is not None:
            target=editor/'M.png' if transport['mask_mode']=='separate_mask_image' else bundle/'transport/M.png'
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(safe_path(case_root,transport['mask_path'],must_exist=True),target)
            write_json(bundle/'mask_transport_v2.json',{**transport,'exported_mask_path':target.relative_to(bundle).as_posix()})
    manifest = {'schema_version': task['schema_version'], 'task_id': task['task_id'],
                'case_id': task['case_id'], 'case_revision': task['case_revision'],
                'stage': task['stage'], 'attempt': task['attempt'],
                'request_sha256': task['request_sha256'], 'config_sha256': task['config_sha256'],
                'prompt_sha256': file_sha256(bundle / 'prompt.txt'), 'attachments': attachments,
                'files': [{'path': path.relative_to(bundle).as_posix(), 'sha256': file_sha256(path)}
                          for path in sorted(bundle.rglob('*')) if path.is_file()],
                'handoff': 'manual; attaching files and observing results requires an operator'}
    if (bundle/'mask_transport_v2.json').exists():
        manifest['schema_version']='ref_enhance_v2'
        manifest['internal_request_schema_version']=task['schema_version']
        manifest['mask_transport']='mask_transport_v2.json'
    write_json(bundle / 'manifest.json', manifest)
    return bundle


def validate_output_order(metadata: dict) -> list[dict]:
    """Validate explicit observed output order, without inventing file indexes."""
    count, formal = metadata.get('actual_generation_count'), metadata.get('provider_order')
    if type(count) is not int or count < 1:
        raise HREError('generation_count_unknown', 'Supply the observed actual_generation_count')
    if type(formal) is not int or formal < 0 or formal >= count:
        raise HREError('provider_order_unknown', 'Formal provider_order must be observed and within generation count')
    if metadata.get('selection_rule', 'first_complete_provider_order') != 'first_complete_provider_order':
        raise HREError('selection_rule_mismatch', 'Only first complete provider output is allowed')
    extras = metadata.get('extras', [])
    if not isinstance(extras, list):
        raise HREError('invalid_extras', 'extras must be structured output observations')
    normalized, seen = [], {formal}
    for item in extras:
        if not isinstance(item, dict) or set(item) != {'source', 'provider_order', 'complete'}:
            raise HREError('provider_order_unknown', 'Each extra requires source, observed provider_order, and complete')
        source, order, complete = item['source'], item['provider_order'], item['complete']
        if not isinstance(source, (str, Path)) or not str(source).strip():
            raise HREError('invalid_extras', 'Each downloaded output requires a real source path')
        if type(order) is not int or order < 0 or order >= count or order in seen:
            raise HREError('provider_order_unknown', 'Output orders must be unique observed integers within generation count')
        if type(complete) is not bool:
            raise HREError('provider_order_unknown', 'Output completeness must be explicitly observed')
        if complete and order < formal:
            raise HREError('not_first_complete_output', 'A complete earlier output cannot be discarded in favor of the formal candidate')
        seen.add(order)
        normalized.append({'source': str(source), 'provider_order': order, 'complete': complete})
    if count < 1 + len(normalized):
        raise HREError('invalid_generation_count', 'Every formal and observed extra output must be charged')
    if not set(range(formal)).issubset(seen):
        raise HREError('provider_order_unknown', 'Earlier outputs must be explicitly observed incomplete')
    return normalized


def _preserve_partial(case_root: Path, source: Path) -> Path:
    if source.is_symlink() or not source.is_file():
        raise HREError('unsafe_path', 'Partial output must be a real regular file')
    raw = source.read_bytes()
    path = safe_path(case_root, f'assets/partial/{make_id("partial")}{source.suffix.lower() or ".bin"}')
    atomic_write(path, raw)
    return path

def import_candidate(case_root: Path, task_id: str, image_path: Path, metadata: dict) -> Path:
    """Register real downloaded bytes and write response/done for Controller intake.

    Call Controller.mark_submitted before importing. An image proves output bytes,
    not the time, UI, provider ordering, or number of generations.
    """
    case_root = Path(case_root).absolute()
    state = CaseStore(case_root).load()
    pending = state['pending_task']
    if not pending or pending['task_id'] != task_id or pending['stage'] != 'execute':
        raise HREError('task_mismatch', 'Choose the current pending execute task')
    if state['workflow_state'] != 'WAIT_EXECUTION':
        raise HREError('not_waiting_execution', 'Resume the current execute task before importing')
    request = read_json(safe_path(case_root, pending['request_path'], must_exist=True))
    validate_schema('request', request)
    if request_hash(request) != pending['request_sha256'] or request['request_sha256'] != pending['request_sha256']:
        raise HREError('request_hash_mismatch', task_id)
    build_context(case_root, request)
    generation = request['payload']['generation_id']
    ledger = next((entry for entry in state['budget']['ledger'] if entry['generation_id'] == generation and entry['task_id'] == task_id), None)
    if not ledger or ledger['status'] != 'submitted' or not ledger['submitted_at']:
        raise HREError('submission_unconfirmed', 'Confirm actual submission with Controller.mark_submitted before importing')
    extra_sources = validate_output_order(metadata)
    count, order = metadata['actual_generation_count'], metadata['provider_order']
    prediction = next(a for a in request['input_assets'] if a['role'] == 'prediction')
    reference = next(a for a in request['input_assets'] if a['role'] == 'reference')
    binding = {'case_id': request['case_id'], 'case_revision': request['case_revision'],
               'task_id': task_id, 'round': request['round'], 'generation_id': generation,
               'prediction_sha256': prediction['sha256'], 'reference_sha256': reference['sha256']}
    policy = read_json(safe_path(case_root, 'config.json', must_exist=True))
    # Color assumptions are frozen at admission; metadata cannot silently alter
    # the case policy when importing a candidate.
    if 'assume_srgb' in metadata and metadata['assume_srgb'] != policy['assume_srgb']:
        raise HREError('color_policy_mismatch', 'Candidate color policy differs from frozen config')
    color_policy = {'assume_srgb': policy['assume_srgb'], 'canonicalizer_version': policy['canonicalizer_version']}
    from .reference_runtime import validate_mask_delivery
    delivery_files=validate_mask_delivery(case_root,request,metadata,image_path)
    from .reference_execution import observation_files
    delivery_files+=observation_files(case_root,request,metadata)
    asset = AssetRegistry(case_root).import_asset(Path(image_path), 'candidate', make_id('candidate'), color_policy, candidate_binding=binding)
    extras, audit_files = [], list(delivery_files)
    outputs = [{'provider_order': order, 'complete': True, 'path': asset['source_file']['path'], 'sha256': asset['source_file']['sha256'], 'formal': True}]
    for item in extra_sources:
        if item['complete']:
            extra_asset = AssetRegistry(case_root).import_asset(Path(item['source']), 'candidate', make_id('extra'), color_policy, candidate_binding=binding)
            source_file = extra_asset['source_file']
            extras.append(source_file)
            raw = safe_path(case_root, source_file['path'], must_exist=True)
        else:
            raw = _preserve_partial(case_root, Path(item['source']))
        audit_files.append(raw)
        outputs.append({'provider_order': item['provider_order'], 'complete': item['complete'], 'path': raw.relative_to(case_root).as_posix(), 'sha256': file_sha256(raw), 'formal': False})
    audit = {'kind': 'hre_output_order_v1', 'task_id': task_id, 'request_sha256': request['request_sha256'], 'generation_id': generation, 'candidate_id': asset['asset_id'], 'actual_generation_count': count, 'outputs': sorted(outputs, key=lambda output: output['provider_order'])}
    audit_path = safe_path(case_root, f'assets/output_order/{make_id("order")}.json')
    write_json(audit_path, audit)
    audit_files.append(audit_path)
    payload = {'generation_id': generation, 'candidate_asset': asset,
               'submitted_at': ledger['submitted_at'], 'actual_generation_count': count,
               'provider_order': order, 'selection_rule': 'first_complete_provider_order',
               'extras': extras, 'geometry_observations': metadata.get('geometry_observations', [])}
    from .protocol import TaskWriter
    provenance = metadata.get('model_observed')
    if 'session_id' in metadata:
        provenance = {'model_observed': provenance or {}, 'session_id': metadata['session_id']}
    return TaskWriter(case_root).commit_submission(request, payload,
        raw_text=metadata.get('raw_text', '').encode('utf-8'),
        files=[safe_path(case_root, asset['path'], must_exist=True), safe_path(case_root, asset['source_file']['path'], must_exist=True)] + audit_files,
        provenance=provenance)
