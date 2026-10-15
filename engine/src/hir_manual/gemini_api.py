"""Explicit optional Gemini REST bridge. Never reads browser history or uses UI.

Credentials exist only in request headers in memory. Each immutable role task is
one stateless request. Unknown submissions are never automatically repeated.
"""
import base64
import io
import json
import os
import re
import time
import uuid
import urllib.error
import urllib.request
from pathlib import Path
from filelock import FileLock
from PIL import Image
from .storage import atomic_write, json_bytes, now, read_json, sha256_bytes, sha256_file, write_json
from .protocol import strict_loads, validate_payload

BASE = 'https://generativelanguage.googleapis.com/v1beta'
MAX_RESPONSE = 100 * 1024 * 1024
BRIDGE_VERSION = 'hir_gemini_rest_xyxy_v2'


class APIError(RuntimeError):
    pass


def read_key(key_file=None, key_env='GEMINI_API_KEY'):
    value = Path(key_file).read_text(encoding='utf-8-sig').strip() if key_file else os.environ.get(key_env, '').strip()
    # Accept one plain official key or one KEY= line. No credential text is ever
    # included in errors, logs, URLs, provider settings or case configuration.
    matches = re.findall(r'AIza[A-Za-z0-9_-]{30,60}', value)
    if len(matches) == 1:
        return matches[0]
    if not matches and re.fullmatch(r'[A-Za-z0-9_.-]{10,512}', value):
        return value  # Let the official service validate opaque credentials.
    raise APIError('Credential file/environment must contain exactly one plain API key')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise APIError('API redirects are prohibited')


def request_json(path, key, body=None, timeout=120):
    if not re.fullmatch(r'/models(?:\?pageSize=1000|/[A-Za-z0-9._-]+:generateContent)', path):
        raise APIError('Unsupported official API endpoint')
    req = urllib.request.Request(BASE + path, data=None if body is None else json_bytes(body),
        headers={'x-goog-api-key': key, 'Content-Type': 'application/json'})
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise APIError('API response exceeds bounded size')
        return json.loads(raw)
    except urllib.error.HTTPError as error:
        # Only a bounded, explicitly redacted error message may leave memory.
        detail = ''
        try:
            value = json.loads(error.read(8192)).get('error', {})
            detail = str(value.get('message', ''))[:600].replace(key, '[REDACTED]')
            detail = re.sub(r'https?://\S+', '[URL]', detail)
            detail = re.sub(r'AIza[A-Za-z0-9_-]+', '[REDACTED]', detail)
        except (ValueError, OSError, AttributeError):
            pass
        raise APIError('Gemini HTTP ' + str(error.code) + (': ' + detail if detail else '')) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise APIError('Gemini network failure or timeout; outcome may be unknown') from None


def list_models(key_file=None, key_env='GEMINI_API_KEY'):
    data = request_json('/models?pageSize=1000', read_key(key_file, key_env))
    return {'models': [{'name': m['name'], 'methods': m.get('supportedGenerationMethods', [])} for m in data.get('models', [])],
            'next_page_present': bool(data.get('nextPageToken'))}


def configuration(image_model, text_model, timeout_seconds=600, media_transport=None):
    for model in (image_model, text_model):
        if not isinstance(model, str) or not re.fullmatch(r'gemini-[A-Za-z0-9._-]+', model):
            raise ValueError('Explicit Gemini model IDs required; no automatic replacement')
    if timeout_seconds not in (180, 600):
        raise ValueError('Select an explicit supported transport timeout')
    result = {'executor': 'gemini_api_image', 'external_api_calls': True, 'branch_type': 'manual_variant',
            'formal_experiment_eligible': False, 'gemini_api': {'endpoint': BASE, 'image_model': image_model,
            'text_model': text_model, 'timeout_seconds': timeout_seconds, 'max_inline_bytes': 18_000_000,
            'candidate_count': 1, 'automatic_retry': False, 'stateless_roles': True}}
    if media_transport is not None:
        if media_transport != 'files_api_v1':
            raise ValueError('Unsupported explicit media transport')
        result['gemini_api']['media_transport'] = media_transport
    return result


def validate_configuration(config):
    api = config.get('gemini_api', {})
    if config.get('executor') != 'gemini_api_image' or config.get('external_api_calls') is not True:
        raise ValueError('This immutable case did not select Gemini API')
    expected = configuration(api.get('image_model'), api.get('text_model'), api.get('timeout_seconds'), api.get('media_transport'))['gemini_api']
    if api != expected or config.get('formal_experiment_eligible') is not False:
        raise ValueError('Gemini API configuration differs from explicit locked route')
    return api


def build_request(case, req, config):
    api = validate_configuration(config)
    if req.role == 'execute':
        if len(req.allowed_assets) != 1 or req.allowed_assets[0].path != 'input/canonical.png':
            raise ValueError('API Executor receives only the original canonical image')
        if set(req.context) != {'instruction', 'instruction_sha256', 'request_one_image', 'new_session_required'}:
            raise ValueError('Executor context contains undeclared material')
        text = req.context['instruction']
        if sha256_bytes(text.encode('utf-8')) != req.context['instruction_sha256']:
            raise ValueError('Editing instruction changed')
    elif req.role == 'verify':
        if any(k in req.context for k in ('instruction', 'previous_instruction', 'evidence', 'diagnosis')):
            raise ValueError('Verifier must be blind to editing instructions and evidence')
        text = case.path(req.prompt_file).read_text(encoding='utf-8')
    else:
        text = case.path(req.prompt_file).read_text(encoding='utf-8')
    if req.role != 'execute':
        text += ('\n\nCOORDINATE CONTRACT: Every bbox_norm is [x_min, y_min, x_max, y_max], '
                 'four floats in [0,1] relative to ORIGINAL Picture 1. x increases from left to right; '
                 'y increases from top to bottom. This is XYXY, NOT Gemini\'s common YXYX order and NOT 0-1000 integers. '
                 'For example the left half is [0,0,0.5,1] and the top half is [0,0,1,0.5]. '
                 'Check that each defect rectangle actually covers the named visible region. '
                 'The Editor still receives only the original image and editing text.\n')
    parts = [{'text': text}]; total = len(text.encode('utf-8')); assets = []
    for asset in req.allowed_assets:
        path = case.path(asset.path)
        if sha256_file(path) != asset.sha256:
            raise ValueError('Allowed image changed')
        raw = path.read_bytes()
        with Image.open(io.BytesIO(raw)) as image:
            mime = Image.MIME.get(image.format)
        if mime not in ('image/png', 'image/jpeg', 'image/webp'):
            raise ValueError('API image MIME unsupported; no silent preprocessing')
        total += len(raw)
        if total > api['max_inline_bytes'] and api.get('media_transport') != 'files_api_v1':
            raise ValueError('Inline image budget exceeded; no silent resizing or dropped evidence')
        if api.get('media_transport') == 'files_api_v1':
            parts.append({'fileData': {'mimeType': mime, 'fileUri': 'pending:' + asset.sha256}})
        else:
            parts.append({'inlineData': {'mimeType': mime, 'data': base64.b64encode(raw).decode('ascii')}})
        assets.append({'path': asset.path, 'sha256': asset.sha256, 'bytes': len(raw)})
    settings = {'candidateCount': 1}
    if req.role == 'execute':
        settings['responseModalities'] = ['TEXT', 'IMAGE']
    else:
        settings.update(responseMimeType='application/json')
    body = {'contents': [{'role': 'user', 'parts': parts}], 'generationConfig': settings}
    if len(json_bytes(body)) > 20_000_000:
        raise ValueError('Encoded API request exceeds 20 MB; no silent resizing or dropped evidence')
    model = api['image_model'] if req.role == 'execute' else api['text_model']
    return body, model, assets


def images_and_text(response):
    images = []; text = []
    for candidate in response.get('candidates', []):
        for part in candidate.get('content', {}).get('parts', []):
            if part.get('thought'):
                continue
            inline = part.get('inlineData', part.get('inline_data'))
            if inline:
                if inline.get('mimeType', inline.get('mime_type')) not in ('image/png', 'image/jpeg', 'image/webp'):
                    raise ValueError('Unknown output image MIME')
                raw = base64.b64decode(inline['data'], validate=True)
                with Image.open(io.BytesIO(raw)) as image:
                    image.verify()
                images.append(raw)
            if 'text' in part:
                text.append(part['text'])
    return images, '\n'.join(text)


def run_task(root, case_id, key_file=None, key_env='GEMINI_API_KEY', retry_text_after_timeout=False):
    from .service import Controller
    from .transport import image_observations
    ctl = Controller(root); case = ctl.case(case_id)
    with FileLock(str(case.path('gemini_api.lock')), timeout=0):
        state = ctl.inspect(case_id); req = ctl.current_task(case_id)
        if state.operation_status != 'active' or not req:
            raise ValueError('Case has no active pending role task')
        config = read_json(case.path('case_config.json')); api = validate_configuration(config)
        directory = case.path(f'tasks/{req.task_id}/api'); receipt_file = directory / 'receipt.json'
        body, model, assets = build_request(case, req, config)
        if req.role == 'execute' and state.budget.consumed >= min(3, state.budget.max_generations):
            raise ValueError('API editing budget exhausted')
        response = None; prior = None
        if receipt_file.exists():
            receipt = read_json(receipt_file)
            if receipt['status'] in ('submitted', 'unknown', 'failed'):
                if (not retry_text_after_timeout or receipt['status'] != 'unknown' or req.role == 'execute'
                        or receipt.get('explicit_text_retry')):
                    raise ValueError('Prior API submission must be reviewed; automatic resubmission prohibited')
                prior = receipt
                # One explicit text-only retry; no paid image regeneration.
                # Preserve the unknown call and separately lock the longer
                # transport budget in the new attempt receipt.
                write_json(directory / 'attempts' / (receipt['stateless_call_id'] + '.json'), receipt)
            elif receipt['status'] == 'accepted':
                return receipt
            else:
                response = read_json(directory / 'provider_response.json')
        if response is None:
            key = read_key(key_file, key_env)
            if api.get('media_transport') == 'files_api_v1':
                from .gemini_files import bind_files
                body = bind_files(case, body, assets, key, api['timeout_seconds'])
            receipt = {'status': 'submitted', 'started_at': now(), 'model_requested': model,
                'bridge_version': BRIDGE_VERSION, 'bridge_source_sha256': sha256_file(Path(__file__)),
                'case_id': case_id, 'task_id': req.task_id, 'role': req.role,
                'stateless_call_id': 'gemini_' + uuid.uuid4().hex, 'request_sha256': sha256_bytes(json_bytes(body)),
                'assets': assets, 'endpoint': BASE, 'automatic_retry': False}
            timeout = 600 if prior else api['timeout_seconds']
            receipt.update(timeout_seconds=timeout, explicit_text_retry=bool(prior),
                           prior_unknown_call_id=prior['stateless_call_id'] if prior else None)
            write_json(receipt_file, receipt); started = time.perf_counter()
            try:
                response = request_json('/models/' + model + ':generateContent', key, body, timeout)
                # Nothing from headers/credential files is serialized.
                atomic_write(directory / 'provider_response.json', json_bytes(response))
                receipt.update(status='response_saved', elapsed_seconds=time.perf_counter()-started,
                               model_version=response.get('modelVersion'), response_id=response.get('responseId'),
                               usage=response.get('usageMetadata', {}), response_sha256=sha256_file(directory / 'provider_response.json'))
                write_json(receipt_file, receipt)
            except APIError as error:
                receipt.update(status='failed' if 'HTTP ' in str(error) else 'unknown', error=str(error), completed_at=now())
                write_json(receipt_file, receipt); raise
        if sha256_file(directory / 'provider_response.json') != receipt['response_sha256']:
            raise ValueError('Saved provider response changed')
        images, text = images_and_text(response)
        receipt.update(generated_images=len(images), output_text_present=bool(text),
                       candidate_finish_reasons=[c.get('finishReason') for c in response.get('candidates', [])])
        write_json(receipt_file, receipt)
        provenance = ctl.provenance('Gemini API: ' + model, 'file', 'supported_bridge', receipt['stateless_call_id'])
        provenance.update(model_version=response.get('modelVersion'), model_version_source='observed' if response.get('modelVersion') else 'not_exposed', started_at=receipt['started_at'])
        if req.role == 'execute':
            if not images:
                raise ValueError('API returned no generated image; text/refusal is not editing success')
            files = []
            original = image_observations(case.path('input/canonical.png'), case.path('input/canonical.png'), config)['pixel_sha256']
            for index, raw in enumerate(images):
                with Image.open(io.BytesIO(raw)) as image:
                    suffix = {'PNG': 'png', 'JPEG': 'jpg', 'WEBP': 'webp'}[image.format]
                file = directory / f'generated_{index:03d}.{suffix}'; atomic_write(file, raw); files.append(file)
                if image_observations(file, case.path('input/canonical.png'), config)['pixel_sha256'] == original:
                    raise ValueError('API returned an unchanged source image')
            result = ctl.import_image(case_id, req.task_id, files[0], provenance['model_display_name'], provenance,
                extras=files[1:], actual_generations=len(files), save_method='supported_bridge_save',
                provider_settings={'provider': 'Google Gemini API', 'model_requested': model,
                    'model_version': response.get('modelVersion'), 'stateless_call_id': receipt['stateless_call_id'],
                    'generation_config': body['generationConfig'], 'usage': response.get('usageMetadata', {})})
        else:
            if images:
                raise ValueError('JSON role returned undeclared generated images')
            payload = strict_loads(text); validate_payload(req.role, payload, case.path('snapshot/schemas'))
            envelope = {k: getattr(req, k) for k in ('protocol_version', 'task_id', 'case_id', 'role', 'round', 'expected_state_revision', 'input_sha256')}
            envelope.update(status='ok', payload=payload, error=None, provenance=provenance)
            result = ctl.import_json(case_id, req.task_id, json.dumps(envelope, ensure_ascii=False), provenance['model_display_name'], provenance)
        if not result.accepted:
            raise ValueError(result.message)
        receipt.update(status='accepted', completed_at=now(), generated_images=len(images), next_state=ctl.inspect(case_id).workflow_status)
        write_json(receipt_file, receipt)
        return receipt
