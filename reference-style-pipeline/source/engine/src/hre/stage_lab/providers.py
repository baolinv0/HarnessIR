"""Small, real transports for independently testing stage models.

No model SDK is required. OpenAI-compatible and Gemini endpoints use HTTP;
native model installations can be connected through the JSON command bridge.
"""
from __future__ import annotations

import base64
import io
import json
import mimetypes
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
import uuid

from PIL import Image, ImageEnhance


def parse_data(text: str):
    """Keep free-form output usable; decode JSON when the model supplies it."""
    value = text.strip()
    if not value:
        return None
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", value)
    if fence:
        value = fence.group(1).strip()
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for match in re.finditer(r"[\[{]", value):
            try:
                result, _ = decoder.raw_decode(value[match.start():])
                return result
            except json.JSONDecodeError:
                pass
        return None


def _image_bytes(path: str) -> tuple[bytes, str]:
    source = Path(path)
    raw = source.read_bytes()
    with Image.open(io.BytesIO(raw)) as image:
        mime = Image.MIME.get(image.format, mimetypes.guess_type(source.name)[0] or 'image/png')
    return raw, mime


def _data_url(path: str) -> str:
    raw, mime = _image_bytes(path)
    return f'data:{mime};base64,{base64.b64encode(raw).decode("ascii")}'


def _save_image(raw: bytes, output_dir: Path, index: int) -> str:
    """Validate the output, then retain its original bytes and dimensions."""
    with Image.open(io.BytesIO(raw)) as image:
        image.verify()
        extension = {'JPEG': '.jpg', 'WEBP': '.webp', 'GIF': '.gif', 'TIFF': '.tiff'}.get(image.format, '.png')
    path = output_dir / f'output_{index:03d}{extension}'
    path.write_bytes(raw)
    return str(path.resolve())


def _secret(model: dict) -> str:
    name = model.get('api_key_env')
    if name and not os.environ.get(name):
        raise ValueError(f'Set environment variable {name} before running this model.')
    return os.environ.get(name, '') if name else ''


def _redact(message: str, model: dict) -> str:
    key = os.environ.get(model.get('api_key_env', ''), '')
    return message.replace(key, '[REDACTED]') if key else message


def _url(model: dict, suffix: str, default: str) -> str:
    base = model.get('base_url') or os.environ.get(model.get('base_url_env', ''), '') or default
    if base.endswith(suffix) or base.endswith(':generateContent'):
        return base
    return base.rstrip('/') + suffix


def _post(url: str, body: bytes, headers: dict, timeout: float, model: dict) -> dict:
    try:
        with urlopen(Request(url, body, headers, method='POST'), timeout=timeout) as response:
            data = json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')[:1800]
        raise RuntimeError(_redact(f'HTTP {exc.code}: {detail}', model)) from None
    if isinstance(data, dict) and data.get('error'):
        raise RuntimeError(_redact(f'Model endpoint error: {data["error"]}', model))
    return data


def _image_from_value(value: str, output_dir: Path, index: int, timeout: float) -> str:
    if value.startswith('data:'):
        raw = base64.b64decode(value.split(',', 1)[1])
    elif value.startswith(('https://', 'http://')):
        with urlopen(value, timeout=timeout) as response:
            raw = response.read()
    else:
        raw = base64.b64decode(value)
    return _save_image(raw, output_dir, index)


def _openai(model: dict, request: dict, output_dir: Path) -> dict:
    timeout = float(model.get('timeout', 300))
    key = _secret(model)
    headers = {'Content-Type': 'application/json'}
    if key:
        headers['Authorization'] = 'Bearer ' + key
    params = {**model.get('parameters', {}), **request.get('parameters', {})}
    is_edit = request['stage'] == 'execute' and model.get('mode', 'chat') in {'image-edit', 'images'}
    if is_edit:
        boundary = 'hre-' + uuid.uuid4().hex
        fields = {'model': model.get('model', ''), 'prompt': request['prompt'], **params}
        body = bytearray()

        def part(name, value, filename=None, mime=None):
            body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"'.encode())
            if filename:
                body.extend(f'; filename="{filename}"'.encode())
            body.extend(b'\r\n')
            if mime:
                body.extend(f'Content-Type: {mime}\r\n'.encode())
            body.extend(b'\r\n')
            body.extend(value if isinstance(value, bytes) else str(value).encode())
            body.extend(b'\r\n')

        for name, value in fields.items():
            part(name, json.dumps(value) if isinstance(value, (dict, list, bool)) else value)
        image_field = model.get('image_field', 'image[]' if len(request['images']) > 1 else 'image')
        for index, item in enumerate(request['images']):
            raw, mime = _image_bytes(item['path'])
            part(image_field, raw, f'image_{index}{Path(item["path"]).suffix}', mime)
        body.extend(f'--{boundary}--\r\n'.encode())
        headers['Content-Type'] = f'multipart/form-data; boundary={boundary}'
        url = _url(model, '/images/edits', 'https://api.openai.com/v1')
        response = _post(url, bytes(body), headers, timeout, model)
    else:
        content = []
        for item in request.get('images', []):
            content.extend([{'type': 'text', 'text': 'Image ' + item['role']},
                            {'type': 'image_url', 'image_url': {'url': _data_url(item['path'])}}])
        content.append({'type': 'text', 'text': request['prompt']})
        messages = [{'role': 'user', 'content': content}]
        if model.get('system_prompt'):
            messages.insert(0, {'role': 'system', 'content': model['system_prompt']})
        payload = {**params, 'model': model.get('model', ''), 'messages': messages}
        url = _url(model, '/chat/completions', 'https://api.openai.com/v1')
        response = _post(url, json.dumps(payload).encode(), headers, timeout, model)
    texts, images = [], []

    def collect_image(value):
        if isinstance(value, dict):
            value = value.get('url') or value.get('b64_json')
        if value:
            images.append(_image_from_value(value, output_dir, len(images), timeout))

    for item in response.get('data', []) if isinstance(response.get('data'), list) else []:
        collect_image(item)
        if item.get('revised_prompt'):
            texts.append(item['revised_prompt'])
    choices = response.get('choices') or []
    # A request is one sample by default. Retain all returned image outputs.
    for choice in choices:
        message = choice.get('message', {})
        content = message.get('content', '')
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            for part in content:
                if part.get('type') in {'text', 'output_text'}:
                    texts.append(part.get('text', ''))
                elif part.get('type') in {'image_url', 'image', 'output_image'}:
                    collect_image(part.get('image_url') or part.get('url') or part.get('b64_json'))
        for item in message.get('images', []):
            collect_image(item.get('image_url') or item)
    text = '\n'.join(t for t in texts if t)
    if not text and not images:
        raise RuntimeError('The endpoint returned no text or images. Check the endpoint mode and model capabilities.')
    return {'text': text, 'data': parse_data(text), 'images': images,
            'usage': response.get('usage', {}),
            'metadata': {'provider': 'openai', 'model': response.get('model', model.get('model')),
                         'response_id': response.get('id'), 'mode': 'image-edit' if is_edit else 'chat',
                         'finish_reasons': [c.get('finish_reason') for c in choices]}}


def _gemini(model: dict, request: dict, output_dir: Path) -> dict:
    timeout = float(model.get('timeout', 300))
    key = _secret(model)
    headers = {'Content-Type': 'application/json'}
    if key:
        if model.get('auth', 'api-key') == 'bearer':
            headers['Authorization'] = 'Bearer ' + key
        else:
            headers['x-goog-api-key'] = key
    parts = []
    for item in request.get('images', []):
        raw, mime = _image_bytes(item['path'])
        parts.extend([{'text': 'Image ' + item['role']},
                      {'inlineData': {'mimeType': mime, 'data': base64.b64encode(raw).decode()}}])
    parts.append({'text': request['prompt']})
    params = {**model.get('parameters', {}), **request.get('parameters', {})}
    if request['stage'] == 'execute':
        params.setdefault('responseModalities', ['TEXT', 'IMAGE'])
    payload = {'contents': [{'role': 'user', 'parts': parts}], 'generationConfig': params}
    if model.get('system_prompt'):
        payload['systemInstruction'] = {'parts': [{'text': model['system_prompt']}]}
    name = quote(model.get('model', ''), safe='-._')
    url = _url(model, f'/models/{name}:generateContent', 'https://generativelanguage.googleapis.com/v1beta')
    response = _post(url, json.dumps(payload).encode(), headers, timeout, model)
    texts, images = [], []
    candidates = response.get('candidates') or []
    for candidate in candidates:
        for part in candidate.get('content', {}).get('parts', []):
            if part.get('thought'):
                continue
            if 'text' in part:
                texts.append(part['text'])
            inline = part.get('inlineData') or part.get('inline_data')
            if inline and inline.get('data'):
                images.append(_save_image(base64.b64decode(inline['data']), output_dir, len(images)))
    text = '\n'.join(texts)
    if not text and not images:
        reasons = [x.get('finishReason') for x in candidates]
        raise RuntimeError(f'Gemini returned no text or images (finish reasons: {reasons}, feedback: {response.get("promptFeedback")}).')
    return {'text': text, 'data': parse_data(text), 'images': images,
            'usage': response.get('usageMetadata', {}),
            'metadata': {'provider': 'gemini', 'model': response.get('modelVersion', model.get('model')),
                         'finish_reasons': [c.get('finishReason') for c in candidates]}}


def _command(model: dict, request: dict, output_dir: Path) -> dict:
    command = model.get('command')
    if not isinstance(command, list) or not command or not all(isinstance(v, str) for v in command):
        raise ValueError('A command model needs an argv list, for example ["python", "worker.py", "--request", "{request}", "--output", "{output}"].')
    request_path, response_path = output_dir / 'request.json', output_dir / 'response.json'
    request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding='utf-8')
    replacements = {'{request}': str(request_path), '{output}': str(response_path), '{output_dir}': str(output_dir)}
    argv = []
    for token in command:
        for key, value in replacements.items():
            token = token.replace(key, value)
        argv.append(token)
    try:
        completed = subprocess.run(argv, cwd=model.get('cwd'), capture_output=True, text=True,
                                   timeout=float(model.get('timeout', 1800)), check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f'Command exceeded timeout of {model.get("timeout", 1800)} seconds.') from exc
    (output_dir / 'worker_stdout.log').write_text(_redact(completed.stdout, model), encoding='utf-8')
    (output_dir / 'worker_stderr.log').write_text(_redact(completed.stderr, model), encoding='utf-8')
    if completed.returncode:
        detail = (completed.stderr or completed.stdout)[-1800:].strip()
        raise RuntimeError(_redact(f'Command exit {completed.returncode}: {detail}', model))
    if response_path.exists():
        result = json.loads(response_path.read_text(encoding='utf-8'))
    else:
        result = parse_data(completed.stdout)
        if result is None:
            raise RuntimeError('Command succeeded but produced neither response.json nor a JSON object on stdout.')
    if not isinstance(result, dict):
        raise ValueError('Command response must be a JSON object.')
    if result.get('error'):
        raise RuntimeError(str(result['error']))
    image_paths = []
    for item in result.get('images', []):
        path = Path(item['path'] if isinstance(item, dict) else item)
        if not path.is_absolute():
            path = output_dir / path
        if not path.is_file():
            raise FileNotFoundError(f'Worker output image does not exist: {path}')
        with Image.open(path) as image:
            image.verify()
        image_paths.append(str(path.resolve()))
    text = result.get('text', '')
    data = result.get('data', parse_data(text))
    if not text and data is not None:
        text = json.dumps(data, ensure_ascii=False, indent=2)
    return {'text': text, 'data': data, 'images': image_paths,
            'usage': result.get('usage', {}),
            'metadata': {'provider': 'command', **result.get('metadata', {})}}


def _demo(model: dict, request: dict, output_dir: Path) -> dict:
    """Deterministic UI fixture, explicitly not a real model evaluation."""
    stage = request['stage']
    profile = request.get('profile', {})
    gain = float(model.get('parameters', {}).get('gain', 1.18))
    images = []
    data = {'synthetic': True, 'stage': stage, 'model': model.get('model', 'demo'),
            'notice': 'Synthetic demonstration only; not a model performance result.'}
    if stage == 'diagnose':
        data.update(differences=[{'id': 'demo-observation-1', 'region': 'foreground',
                                 'attribute': 'shadow_visibility', 'direction': 'A darker than B',
                                 'confidence': 'synthetic', 'evidence': 'Demonstration fixture, not visual inference.'}],
                    region_relations=[{'regions': ['foreground', 'background'], 'observation': 'Synthetic relationship example.'}])
    elif stage == 'plan':
        data.update(actions=[{'id': 'demo-action-1', 'region': 'foreground', 'attribute': 'brightness',
                              'direction': 'increase', 'preserve': ['geometry', 'text'],
                              'instruction': 'Lift supported shadows while retaining foreground-background separation.'}])
    elif stage == 'compile':
        prompt = 'Edit image A using B only as an appearance reference. Lift visible shadows while preserving scene content.'
        data.update(edit_prompt=prompt, rewritten_prompt=prompt, profile=profile.get('id', 'generic'),
                    action_delta={'preserved': ['shadow visibility'], 'omitted': [], 'modified': [], 'added': []})
    elif stage == 'execute':
        source = next((x['path'] for x in request['images'] if x['role'] == 'A'), None)
        if source is None:
            raise ValueError('Demo execution requires image A.')
        with Image.open(source) as image:
            edited = ImageEnhance.Brightness(image.convert('RGB')).enhance(gain)
            target = output_dir / 'demo_output.png'
            edited.save(target)
        images = [str(target.resolve())]
        data.update(operation='deterministic_brightness', gain=gain)
    elif stage == 'judge':
        data.update(reference_alignment='uncertain', content_preservation='uncertain',
                    coordination='uncertain', overall='uncertain',
                    observations=['Synthetic judge; no actual model verdict is available.'])
    return {'text': json.dumps(data, ensure_ascii=False, indent=2), 'data': data, 'images': images,
            'usage': {}, 'metadata': {'provider': 'demo', 'synthetic': True}}


def call_provider(model: dict, request: dict, output_dir: Path) -> dict:
    """Run one configured stage model and return text, data, images and usage."""
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    provider = model.get('provider', 'openai')
    if provider == 'manual':
        raise ValueError('Manual models use export followed by import of the observed response.')
    handlers = {'openai': _openai, 'openai-compatible': _openai, 'gemini': _gemini,
                'command': _command, 'demo': _demo}
    if provider not in handlers:
        raise ValueError(f'Unknown provider {provider!r}; choose openai, gemini, command, manual or demo.')
    started = time.perf_counter()
    result = handlers[provider](model, request, output_dir)
    result.setdefault('metadata', {})['transport_duration_s'] = round(time.perf_counter() - started, 4)
    return result
