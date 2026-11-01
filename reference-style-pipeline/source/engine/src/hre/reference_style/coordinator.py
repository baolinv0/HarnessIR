"""Minimal locked, offline coordinator. No inference, automatic retries or verdicts.

S0/S1 exports are protocol scaffolding. Imports validate identities and preserve
raw bytes; they do not certify provenance, diagnosis quality, style or acceptance.
"""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import os
import json

from PIL import Image

from hre.models import canonical_json, file_sha256, sha256_bytes
from hre.paths import make_id, safe_path
from hre.storage import case_lock, read_json, write_json
from .audit import audit_image, validate_spec
from .contracts import (SCHEMA_VERSION, require, exact, identifier, digest, record, validate_record,
                        validate_roles, transition, execution_context, public_text)


def _path(root, relative, exists=False):
    return safe_path(Path(root), relative, must_exist=exists)


def _load(root, relative, kind=None):
    value = validate_record(read_json(_path(root, relative, True)))
    if kind is not None:
        require(value['kind'] == kind, 'wrong record kind')
    return value


def _immutable_bytes(root, relative, data):
    """Exclusive creation: even an incomplete prior artifact is never replaced."""
    with _path(root, relative).open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _read_output(output):
    output = Path(output).absolute()
    safe_path(output.parent, output.name, True)
    require(output.is_file(), 'output must be regular file')
    data = output.read_bytes()
    require(0 < len(data) <= 512 * 1024 * 1024, 'invalid output byte length')
    return data


def _save_state(root, sample_id, payload):
    state = record(sample_id, 'state', payload)
    # Immutable snapshots give distinguishable exported/waiting/imported/validated
    # states even though the current state pointer changes atomically.
    write_json(_path(root, 'history/' + state['record_id'] + '.json'), state)
    write_json(_path(root, 'state.json'), state)
    return state


def _verify_assets(root, audit):
    validate_roles(audit['payload']['images'])
    for image in audit['payload']['images']:
        for path_key, hash_key in [('source_path', 'source_file_hash'),
                                   ('derivative_path', 'derivative_file_hash'),
                                   ('analysis_path', 'analysis_file_hash')]:
            if image[path_key] is not None:
                require(file_sha256(_path(root, image[path_key], True)) == image[hash_key], 'audited asset modified')


def input_domain_metadata(root,state,audit=None):
    """Typed input domain and archival refs only; never execution instructions."""
    audit=_load(root,'input_audit.json','input_audit') if audit is None else audit
    images=audit['payload']['images'];validate_roles(images)
    kinds=[i.get('source_kind','base_model_output' if i['role']=='A' else 'camera_rgb') for i in images]
    require(kinds[0] in ('base_model_output','camera_rgb') and kinds[1]=='camera_rgb','invalid input-domain audit')
    for image,kind in zip(images,kinds):
        if kind=='camera_rgb':require(image['base_model_version'] is None,'camera audit cannot claim a Base model version')
        else:require(isinstance(image['base_model_version'],str) and bool(image['base_model_version'].strip()),'Base audit needs declared model version')
    domain=kinds[0];a=audit['payload'];p=state['payload']
    if 'input_domain' in a or 'input_domain' in p:
        require(a.get('input_domain')==p.get('input_domain')==domain,'input domain changed between audit and state')
    else:require(all('source_kind' not in i for i in images),'new domain declaration missing from state/audit')
    lineage=p.get('input_lineage')
    require(a.get('input_lineage')==lineage,'lineage reference changed between audit and state')
    if lineage is not None:
        exact(lineage,('path','sha256','verification'));digest(lineage['sha256'])
        require(lineage['path']=='input_lineage.json' and lineage['verification']=='archival_external_lineage_not_automatically_authenticated','invalid archival lineage reference')
        require(file_sha256(_path(root,lineage['path'],True))==lineage['sha256'],'archival input lineage changed')
    return dict(input_domain=domain,validation_scope='camera_rgb_workflow_only' if domain=='camera_rgb' else 'base_model_output_domain_only',
                input_lineage=deepcopy(lineage))


def _status(root):
    state = _load(root, 'state.json', 'state')
    audit = _load(root, 'input_audit.json', 'input_audit')
    require(audit['sample_id'] == state['sample_id'] and
            audit['content_hash'] == state['payload']['input_audit_hash'], 'audit/state mismatch')
    _verify_assets(root, audit)
    input_domain_metadata(root,state,audit)
    attempts_root = _path(root, 'attempts')
    if attempts_root.exists():
        require({p.name for p in attempts_root.iterdir()} == {a['attempt_id'] for a in state['payload']['attempts']},
                'orphan or missing attempt: reconcile existing files before another export')
    for attempt in state['payload']['attempts']:
        request = _load(root, attempt['request_path'], 'request')
        p = request['payload']
        require(request['sample_id'] == state['sample_id'] and p['attempt_id'] == attempt['attempt_id']
                and request['content_hash'] == attempt['request_hash'], 'attempt/request mismatch')
        for item in p['images']:
            require(file_sha256(_path(root, item['path'], True)) == item['derivative_file_hash'], 'exported derivative modified')
        for item in p.get('planned_attachments',[]):
            require(file_sha256(_path(root,item['path'],True))==item['sha256'],'planned attachment modified')
    for result in state['payload']['results']:
        response = _load(root, result['record_path'], 'response')
        require(response['sample_id'] == state['sample_id'] and response['content_hash'] == result['record_hash'], 'result/state mismatch')
        rp = response['payload']
        require(file_sha256(_path(root, rp['output_path'], True)) == rp['output_hash'], 'raw output modified')
        receipt = _path(root, 'attempts/' + rp['attempt_id'] + '/receipt.json', True)
        require(file_sha256(receipt) == rp['receipt_hash'], 'receipt modified')
        matches = [a for a in state['payload']['attempts'] if a['attempt_id'] == rp['attempt_id']]
        require(len(matches) == 1 and matches[0]['status'] == 'validated'
                and matches[0]['request_hash'] == rp['request_hash'], 'response not bound to validated attempt')
    if 's2' in state['payload']:
        from .s2_store import verify
        verify(root,state)
    return state


def status(root):
    _path(root, 'state.json', True)  # Never create an empty root through case_lock.
    with case_lock(Path(root)):
        return _status(root)


def create_sample(config, out):
    require(isinstance(config,dict),'sample configuration must be an object')
    exact(config, ('sample_id', 'provider', 'purpose', 'inputs')+(('input_lineage',) if 'input_lineage' in config else ()))
    identifier(config['sample_id'])
    require(config['provider'] == 'current_chat_offline', 'only current_chat_offline is implemented')
    require(config['purpose'] in ('reference_style', 'protocol_fixture'), 'explicit purpose required')
    validate_roles(config['inputs'])
    for spec in config['inputs']:
        validate_spec(spec)
    lineage=None;lineage_bytes=None
    if 'input_lineage' in config:
        ref=config['input_lineage'];exact(ref,('path','sha256'));digest(ref['sha256'])
        lineage_bytes=_read_output(ref['path']);require(sha256_bytes(lineage_bytes)==ref['sha256'],'input lineage hash mismatch')
        decoded=json.loads(lineage_bytes.decode('utf-8'),parse_constant=lambda value:(_ for _ in ()).throw(ValueError('nonfinite lineage JSON')))
        require(isinstance(decoded,dict),'input lineage must be a JSON object')
        lineage=dict(path='input_lineage.json',sha256=ref['sha256'],verification='archival_external_lineage_not_automatically_authenticated')
    out = Path(out).absolute()
    _path(out.parent, out.name)
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    images = []
    for spec in config['inputs']:
        prefix = 'assets/' + spec['role']
        audited, _ = audit_image(spec, _path(out, prefix))
        for key in ('source_path', 'derivative_path', 'analysis_path'):
            if audited[key] is not None:
                audited[key] = prefix + '/' + audited[key]
        images.append(audited)
    if lineage is not None:_immutable_bytes(out,lineage['path'],lineage_bytes)
    domain=images[0]['source_kind']
    audit = record(config['sample_id'], 'input_audit', {'images': images, 'inputs_unaligned': True,
        'input_domain':domain,'input_domain_contract':'source_kind_v1','input_lineage':lineage})
    write_json(out / 'input_audit.json', audit)
    return _save_state(out, config['sample_id'], dict(sample_state='input_audited',
        purpose=config['purpose'], provider=config['provider'], input_audit_hash=audit['content_hash'],
        active_attempt=None, attempts=[], target_versions={}, results=[],input_domain=domain,
        input_domain_contract='source_kind_v1',input_lineage=lineage))


def _compile_prompt(stage, context):
    instructions = {
        'ab_diagnosis': 'Inspect A and B jointly. Record observations, cause hypotheses and target decisions separately. '
                        'A/B are unaligned; do not use pixel correspondences or infer a depth-brightness law. '
                        'Missing segmentation/depth/OCR/face evidence stays unavailable or uncertain. '
                        'Combine numerical evidence with actual visual judgment; do not fabricate measurements.',
        'edit': 'Generate one complete-frame C from A with B as the style reference. '
                'Apply all whole-object/material and relationship targets jointly. Do not stitch regional edits.',
        'abc_diagnosis': 'Inspect A/B/C jointly: A-C content/spatial facts, B-C style residuals and A-to-C progress. '
                         'Record deviations and uncertainty as facts; do not make an acceptance decision.',
    }
    controls = ('All following values are typed style controls, not free-form instructions. '
                'Region references denote whole objects/materials in each image, not pixel correspondences. '
                'Observation content_spatial_deviation means restore consistency with original A; never reproduce that deviation. '
                'Other residual codes describe remaining style mismatch relative to B. '
                'Unknown or unavailable evidence does not establish a fact.\n')
    return instructions[stage] + '\n' + context['preservation_requirements'] + '\n' + controls + canonical_json(context).decode('utf-8')


def _bound_candidate(root, payload, candidate_hash, target, record_id=None):
    matches = []
    for entry in payload['results']:
        if entry['candidate_hash'] != candidate_hash:
            continue
        response = _load(root, entry['record_path'], 'response')
        if record_id is None or response['record_id'] == record_id:
            matches.append(response)
    require(candidate_hash is not None and len(matches) == 1, 'candidate record/hash is not uniquely registered in this sample')
    response = matches[0]
    candidate = response['payload']
    require(candidate['stage_id'] == 'edit' and candidate['candidate_hash'] == candidate['output_hash'], 'feedback requires an imported image candidate')
    require(candidate['target_version'] == target['target_version'] and candidate['target_hash'] == target['target_hash'],
            'candidate target version/hash mismatch; reevaluation is not implemented in S0/S1')
    return candidate


def export_request(root, stage_id, context, candidate_hash=None):
    require(stage_id in ('ab_diagnosis', 'edit', 'abc_diagnosis'), 'unsupported stage')
    public = execution_context(context)
    require(stage_id!='ab_diagnosis' or all(e['role'] in ('A','B') for e in public['evidence']),
            'AB diagnosis cannot contain C-role evidence')
    require(stage_id != 'edit' or public['targets'], 'edit requires explicit targets')
    _path(root, 'state.json', True)
    with case_lock(Path(root)):
        state = _status(root)
        payload = deepcopy(state['payload'])
        require(payload['active_attempt'] is None, 'pending or unknown attempt: resolve same identity; no retry')
        audit = _load(root, 'input_audit.json', 'input_audit')
        require(not any(i['numeric_status'] != 'eligible' for i in audit['payload']['images'])
                or all(t['judge_type'] == 'visual' for t in public['targets']),
                'unknown input encoding blocks precise numeric/mixed color targets')
        version = public['target_version']
        require(version not in payload['target_versions'] or payload['target_versions'][version] == public['target_hash'],
                'target version already bound to different content')
        for feedback in public['feedback']:
            _bound_candidate(root, payload, feedback['candidate_hash'], public, feedback['candidate_record_id'])
        candidate = None
        if stage_id == 'abc_diagnosis':
            candidate = _bound_candidate(root, payload, candidate_hash, public)
        else:
            require(candidate_hash is None, 'candidate only belongs to ABC diagnosis')
        return _export_prepared(root, state, audit, public, stage_id, candidate)


def _export_prepared(root, state, audit, public, stage_id, candidate=None, *, extra=None, prompt=None, bind_targets=True,
                     prompt_version='typed_style_preservation_v2',attachment_aids=None,candidate_image=None):
    """Internal typed producer boundary; callers hold the sample lock."""
    require(state['payload']['active_attempt'] is None, 'pending attempt must resolve before export')
    attempt_id = make_id('attempt')
    from .s4_budget import reserve
    state=reserve(root,state,'edit_attempts' if stage_id=='edit' else 'diagnostics',attempt_id)
    payload = deepcopy(state['payload'])
    prefix = 'attempts/' + attempt_id
    directory = _path(root, prefix)
    directory.mkdir(parents=True, exist_ok=False)
    images = []
    for audited in audit['payload']['images']+([] if candidate_image is None else [candidate_image]):
        relative = prefix + '/' + audited['role'] + '.png'
        data = _path(root, audited['derivative_path'], True).read_bytes()
        _path(root, relative).write_bytes(data)
        images.append({key: deepcopy(audited[key]) for key in (
            'role', 'source_file_hash', 'source_pixel_hash', 'derivative_file_hash',
            'derivative_pixel_hash', 'source_encoding', 'source_bit_depth',
            'source_icc_hash', 'source_png_color_metadata', 'orientation', 'native_size', 'oriented_size',
            'derivative_encoding', 'derivative_bit_depth', 'conversion_chain',
            'geometry', 'gamut_clipped_pixel_fraction', 'quantization', 'numeric_status', 'display_assumption')})
        images[-1]['path'] = relative
    bindings = [{key: item[key] for key in ('role', 'source_file_hash', 'source_pixel_hash',
                                           'derivative_file_hash', 'derivative_pixel_hash')} for item in images]
    prompt = _compile_prompt(stage_id, public) if prompt is None else prompt
    attachments={}
    if attachment_aids is not None:
        from .contracts import content_hash
        planned=[dict(role=i['role'],purpose={'A':'content_image','B':'style_reference','C':'candidate_observation'}[i['role']],
                      path=i['path'],sha256=i['derivative_file_hash'],mime_type='image/png') for i in images]
        planned.extend(deepcopy(attachment_aids))
        planned=[dict(attachment_id='a'+str(n),ordinal=n,**item) for n,item in enumerate(planned,1)]
        attachments=dict(planned_attachments=planned,planned_attachment_manifest_hash=content_hash(planned))
    request = record(state['sample_id'], 'request', dict(attempt_id=attempt_id, stage_id=stage_id,
        provider='current_chat_offline', purpose=payload['purpose'], input_audit_hash=audit['content_hash'],
        images=images, role_bindings=bindings, context=public, prompt=prompt,
        prompt_version=prompt_version, prompt_hash=sha256_bytes(prompt.encode('utf-8')),
        expected_response_type='image' if stage_id == 'edit' else 'text',
        candidate=None if candidate is None else {k: candidate[k] for k in ('candidate_hash', 'output_path', 'geometry')},
        tool_internal_input_transforms='unknown', effect_validation='not_performed', **attachments, **(extra or {})))
    request_path = prefix + '/request.json'
    write_json(_path(root, request_path), request)
    item = dict(attempt_id=attempt_id, stage_id=stage_id, request_path=request_path,
                request_hash=request['content_hash'], status='exported')
    payload['attempts'].append(item)
    payload['active_attempt'] = deepcopy(item)
    if bind_targets:
        payload['target_versions'][public['target_version']] = public['target_hash']
    _save_state(root, state['sample_id'], payload)
    item['status'] = transition('exported', 'waiting_for_response')
    payload['active_attempt'] = deepcopy(item)
    _save_state(root, state['sample_id'], payload)
    return request


def mark_unknown(root, attempt_id, reason):
    public_text(reason)
    _path(root, 'state.json', True)
    with case_lock(Path(root)):
        state = _status(root)
        p = deepcopy(state['payload'])
        active = p['active_attempt']
        require(active is not None and active['attempt_id'] == attempt_id, 'not the active attempt')
        for item in p['attempts']:
            if item['attempt_id'] == attempt_id:
                item['status'] = transition(item['status'], 'response_unknown')
                item['unknown_reason'] = reason
                p['active_attempt'] = deepcopy(item)
        return _save_state(root, state['sample_id'], p)


def import_response(root, receipt, output):
    base_keys=('schema_version', 'sample_id', 'attempt_id', 'stage_id', 'request_hash',
                    'target_version', 'target_hash', 'prompt_hash', 'role_bindings',
                    'response_type', 'output_sha256', 'provenance')
    require(isinstance(receipt,dict) and set(base_keys)<=set(receipt)
            and set(receipt)<=set(base_keys)|{'submission_record_id','submission_hash'},'invalid receipt fields')
    require(receipt['schema_version'] == SCHEMA_VERSION, 'receipt schema mismatch')
    _path(root, 'state.json', True)
    with case_lock(Path(root)):
        state = _status(root)
        p = deepcopy(state['payload'])
        # A committed receipt can be replayed after lost acknowledgment, including
        # while a newer attempt is pending. Exact replay is a read-only result.
        for entry in p['results']:
            prior = _load(root, entry['record_path'], 'response')
            if prior['payload']['attempt_id'] != receipt['attempt_id']:
                continue
            prior_receipt = read_json(_path(root, 'attempts/' + receipt['attempt_id'] + '/receipt.json', True))
            require(receipt == prior_receipt, 'conflicting replay of immutable receipt')
            require(sha256_bytes(_read_output(output)) == prior['payload']['output_hash'], 'conflicting replay output')
            return prior
        active = p['active_attempt']
        require(active is not None and active['status'] in ('waiting_for_response', 'response_unknown'), 'no importable active attempt')
        request = _load(root, active['request_path'], 'request')
        req = request['payload']
        is_s3=req.get('binding_kind') in ('compiled_edit','abc_evaluation')
        exact(receipt,base_keys+(('submission_record_id','submission_hash') if is_s3 else ()))
        submission=None
        expected = dict(sample_id=state['sample_id'], attempt_id=req['attempt_id'], stage_id=req['stage_id'],
                        request_hash=request['content_hash'], target_version=req['context']['target_version'],
                        target_hash=req['context']['target_hash'], prompt_hash=req['prompt_hash'],
                        role_bindings=req['role_bindings'], response_type=req['expected_response_type'])
        require(all(receipt[k] == v for k, v in expected.items()), 'receipt/request identity, role or target mismatch')
        provenance = receipt['provenance']
        exact(provenance, ('origin', 'provider', 'conversation_ref', 'tool_call_ref', 'model_version',
                           'transcription_note', 'input_visibility'))
        require(provenance['origin'] == ('synthetic_fixture' if p['purpose'] == 'protocol_fixture' else 'actual_current_chat'), 'receipt provenance/purpose mismatch')
        require(provenance['provider'] == 'chatgpt', 'not an actual ChatGPT bridge provider')
        require(provenance['input_visibility'] == 'audited_files_attached_internal_transforms_unknown', 'unsupported input visibility claim')
        for key in ('conversation_ref', 'tool_call_ref', 'transcription_note'):
            require(isinstance(provenance[key], str) and bool(provenance[key].strip()), 'receipt provenance missing')
        require(provenance['model_version'] is None or isinstance(provenance['model_version'], str), 'invalid model version')
        if is_s3:
            from .s3_handoff import bound_submission
            submission=bound_submission(root,state,request,receipt)
        data = _read_output(output)
        require(sha256_bytes(data) == receipt['output_sha256'], 'candidate/output hash mismatch')
        geometry = None
        encoding = None
        if is_s3 and receipt['response_type']=='image':
            from .s3_candidate import inspect_raw
            geometry,encoding=inspect_raw(data,req['images'][0]['oriented_size'])
        elif receipt['response_type'] == 'image':
            with Image.open(BytesIO(data)) as image:
                require(image.format in ('PNG', 'JPEG') and image.mode == 'RGB', 'unsupported raw candidate format')
                require(getattr(image, 'n_frames', 1) == 1 and 0 < image.width * image.height <= 50_000_000, 'candidate frame/pixel limit')
                image.load()
                geometry = dict(native_size=list(image.size), orientation=image.getexif().get(274, 1),
                                size_matches_A=list(image.size) == req['images'][0]['oriented_size'],
                                spatial_correspondence='unverified', numeric_support_status='uncertain', resize=None, crop=None)
                # Do not infer sRGB from Pillow RGB mode or manufacture an ICC.
                encoding = dict(status='unverified', icc_hash=sha256_bytes(image.info['icc_profile']) if image.info.get('icc_profile') else None,
                                container_bit_depth=(data[24] if image.format == 'PNG' else 8))
        else:
            require(bool(data.decode('utf-8').strip()), 'empty text response')
        prefix = 'attempts/' + req['attempt_id']
        output_path = prefix + '/raw_response.bin'
        require(not any(_path(root, prefix + '/' + name).exists() for name in
                        ('raw_response.bin', 'receipt.json', 'response.json')),
                'partial prior import: preserve artifacts and reconcile same attempt manually')
        _immutable_bytes(root, output_path, data)
        _immutable_bytes(root, prefix + '/receipt.json', canonical_json(receipt))
        result = record(state['sample_id'], 'response', dict(attempt_id=req['attempt_id'], stage_id=req['stage_id'],
            request_hash=request['content_hash'], target_version=receipt['target_version'], target_hash=receipt['target_hash'],
            output_path=output_path, output_hash=sha256_bytes(data),
            candidate_hash=sha256_bytes(data) if receipt['response_type'] == 'image' else None,
            geometry=geometry, encoding=encoding, provenance=deepcopy(provenance),
            edit_binding=None if req.get('binding_kind')!='compiled_edit' else dict(compiled_record_id=req['compiled_record_id'],compiled_record_hash=req['compiled_record_hash'],
                submission_record_id=submission['record_id'],submission_hash=submission['content_hash']),
            diagnostic_binding=None if req.get('binding_kind')!='abc_evaluation' else dict(evaluation_id=req['evaluation_id'],evaluation_hash=req['evaluation_hash'],
                review_view=req['review_view'],submission_record_id=submission['record_id'],submission_hash=submission['content_hash']),
            receipt_hash=sha256_bytes(canonical_json(receipt)), protocol_status='validated',
            real_execution_evidence=False,
            claimed_origin=provenance['origin'],
            provenance_verification='caller_attested_not_remote_authenticated',
            internal_model_version=provenance['model_version'], seed=None, duration_seconds=None, cost=None,
            visual_style_status='not_evaluated', pixel_supervision_screening_status='undetermined'))
        record_path = prefix + '/response.json'
        _immutable_bytes(root, record_path, canonical_json(result))
        attempt = next(a for a in p['attempts'] if a['attempt_id'] == req['attempt_id'])
        attempt['status'] = transition(attempt['status'], 'imported')
        p['active_attempt'] = deepcopy(attempt)
        _save_state(root, state['sample_id'], p)
        attempt['status'] = transition('imported', 'validated')
        p['active_attempt'] = None
        p['results'].append(dict(record_path=record_path, record_hash=result['content_hash'],
                                 candidate_hash=result['payload']['candidate_hash']))
        _save_state(root, state['sample_id'], p)
        return result
