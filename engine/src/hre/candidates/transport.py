import base64
import json
import math
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from PIL import Image

from hre.models import HREError, canonical_json, file_sha256, sha256_bytes
from .contracts import digest, require


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_endpoint(endpoint, default_max_tokens=8192):
    require(isinstance(endpoint, dict) and not set(endpoint) - {'base_url', 'model', 'api_key_env', 'timeout_seconds', 'settings', 'response_format'},
            'endpoint_invalid', 'Endpoint accepts deployed URL/model/settings and credential environment names only')
    base = endpoint.get('base_url', '').rstrip('/')
    parsed = urlsplit(base)
    require(parsed.scheme in {'http', 'https'} and parsed.netloc and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment,
            'endpoint_invalid', 'Configure an HTTP(S) base URL without embedded credentials or query parameters')
    require(isinstance(endpoint.get('model'), str) and endpoint['model'].strip() and
            not any(word in endpoint['model'].upper() for word in ('SET_', 'REPLACE_', 'PLACEHOLDER')),
            'deployment_missing', 'Configure the actual deployed model ID')
    timeout = endpoint.get('timeout_seconds', 600)
    require(type(timeout) in {int, float} and math.isfinite(timeout) and 0 < timeout <= 86400,
            'timeout_invalid', 'Configure a positive bounded finite timeout')
    settings = dict(endpoint.get('settings', {}))
    settings.setdefault('temperature', 0)
    settings.setdefault('max_tokens', default_max_tokens)
    require(not set(settings) - {'temperature', 'top_p', 'max_tokens', 'seed', 'frequency_penalty', 'presence_penalty'},
            'chat_settings_invalid', 'Unsupported chat setting')
    require(type(settings['max_tokens']) is int and 0 < settings['max_tokens'] <= 1000000,
            'token_budget_invalid', 'Freeze a positive bounded output token limit')
    for key, low, high, open_low in [('temperature', 0, 2, False), ('top_p', 0, 1, True), ('frequency_penalty', -2, 2, False), ('presence_penalty', -2, 2, False)]:
        if key in settings:
            value = settings[key]
            require(type(value) in {float, int} and math.isfinite(value) and (value > low if open_low else value >= low) and value <= high,
                    'chat_settings_invalid', 'Invalid finite ' + key)
    if 'seed' in settings:
        require(type(settings['seed']) is int and 0 <= settings['seed'] < 2**63, 'chat_settings_invalid', 'Invalid chat seed')
    if endpoint.get('api_key_env'):
        require(isinstance(endpoint['api_key_env'], str) and endpoint['api_key_env'].isidentifier(), 'credential_invalid', 'Credential reference must be an environment-variable name')
    return settings


def _object_pairs(items):
    value = {}
    for key, item in items:
        require(key not in value, 'model_json_invalid', 'Model JSON contains duplicate keys')
        value[key] = item
    return value


def _decode_content(body):
    try:
        content = body['choices'][0]['message']['content']
        require(isinstance(content, str), 'model_json_invalid', 'Expected JSON text in a chat completion')
        value = json.loads(content, object_pairs_hook=_object_pairs)
        require(isinstance(value, dict), 'model_json_invalid', 'Model JSON must be an object')
        canonical_json(value)
        return value
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise HREError('model_json_invalid', 'The saved completion is not a finite JSON object') from exc


def call_json(root, config, journal, operation_id, kind, prompt, images, *, system='', group=None, fixture_response=None):
    require(config.get('mode') in {'fixture', 'real'}, 'runtime_mode_invalid', 'Declare fixture or real mode')
    require(isinstance(prompt, str) and isinstance(system, str), 'prompt_invalid', 'Prompt and system must be strings')
    endpoint_key = 'judge' if kind.startswith('judge_') else {'diagnosis': 'diagnoser', 'compose': 'composer'}.get(kind, kind)
    endpoint = config.get('stages', {}).get(endpoint_key, {})
    bindings, image_content = [], []
    for entry in images:
        path = Path(entry).resolve()
        require(not path.is_relative_to((Path(root).resolve() / 'offline').resolve()), 'offline_input_forbidden', 'Offline artifacts cannot enter online requests')
        require(path.is_file(), 'image_missing', 'Model input image is missing')
        image_bytes = path.read_bytes()
        with Image.open(path) as image:
            image.load()
            require(image.format in {'PNG', 'JPEG'}, 'image_format_invalid', 'Use PNG or JPEG model inputs')
            mime = 'image/png' if image.format == 'PNG' else 'image/jpeg'
        bindings.append({'path': str(path), 'sha256': sha256_bytes(image_bytes), 'mime': mime})
        image_content.append({'type': 'image_url', 'image_url': {'url': 'data:' + mime + ';base64,' + base64.b64encode(image_bytes).decode('ascii')}})
    messages = []
    if system:
        messages.append({'role': 'system', 'content': system})
    messages.append({'role': 'user', 'content': [{'type': 'text', 'text': prompt}] + image_content})
    settings = dict(endpoint.get('settings', {}))
    settings.setdefault('temperature', 0)
    settings.setdefault('max_tokens', config.get('review', {}).get('max_output_tokens', 8192))
    require(type(settings.get('max_tokens')) is int and settings['max_tokens'] > 0, 'token_budget_invalid', 'Freeze a positive output token limit')
    allowed = {'temperature', 'top_p', 'max_tokens', 'seed', 'frequency_penalty', 'presence_penalty'}
    require(not set(settings) - allowed, 'chat_settings_invalid', 'Unsupported chat setting')
    payload = {'model': endpoint.get('model', 'fixture'), 'messages': messages, 'response_format': {'type': 'json_object'}, **settings}
    request = {'mode': config['mode'], 'endpoint': endpoint.get('base_url'), 'model': payload['model'],
               'settings': settings, 'system': system, 'prompt': prompt, 'images': bindings,
               'fixture_response_sha256': digest(fixture_response) if fixture_response is not None else None}
    if config['mode'] == 'fixture':
        require(isinstance(fixture_response, dict), 'fixture_response_missing', 'Fixture calls require an explicit scripted response')
        callback = lambda: {'choices': [{'message': {'content': canonical_json(fixture_response).decode('utf-8')}}], 'fixture_only': True}
    else:
        validate_endpoint(endpoint, config.get('review', {}).get('max_output_tokens', 8192))
        base = endpoint.get('base_url', '').rstrip('/')
        parsed = urlsplit(base)
        require(parsed.scheme in {'http', 'https'} and parsed.netloc and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment,
                'endpoint_invalid', 'Configure a plain HTTP(S) local deployment base URL without credentials')
        require(isinstance(endpoint.get('model'), str) and endpoint['model'] and 'SET_' not in endpoint['model'] and 'REPLACE_' not in endpoint['model'],
                'deployment_missing', 'Configure the deployed model ID')
        url = base if base.endswith('/chat/completions') else base + '/chat/completions'
        timeout = endpoint.get('timeout_seconds', 600)
        require(type(timeout) in {int, float} and 0 < timeout <= 86400, 'timeout_invalid', 'Configure a positive bounded timeout')
        headers = {'Content-Type': 'application/json'}
        key_env = endpoint.get('api_key_env')
        if key_env:
            require(isinstance(key_env, str) and key_env in os.environ, 'credential_missing', 'Configured credential environment variable is missing')
            headers['Authorization'] = 'Bearer ' + os.environ[key_env]
        def callback():
            for item in bindings:
                require(file_sha256(Path(item['path'])) == item['sha256'], 'input_modified', 'Input changed before HTTP submission')
            http_request = Request(url, data=canonical_json(payload), headers=headers, method='POST')
            try:
                with build_opener(_NoRedirect()).open(http_request, timeout=timeout) as response:
                    raw = response.read()
            except HTTPError as exc:
                if exc.code >= 500:
                    raise ConnectionError('Provider returned an uncertain server error') from exc
                raise HREError('http_call_failed', 'Provider rejected the request with HTTP ' + str(exc.code)) from exc
            try:
                result = json.loads(raw.decode('utf-8'), object_pairs_hook=_object_pairs)
                require(isinstance(result, dict), 'provider_response_invalid', 'Provider response must be an object')
                canonical_json(result)
            except (ValueError, UnicodeError) as exc:
                raise ConnectionError('Provider returned a response without a recoverable completion receipt') from exc
            return result
    body = journal.invoke(operation_id, kind, request, callback, group=group)
    return _decode_content(body)
