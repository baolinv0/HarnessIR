"""Explicit original-byte Gemini Files transport; credentials/opaque upload URLs stay in memory."""
import base64
import copy
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from .storage import read_json, write_json, sha256_file, now, json_bytes

HOST = 'generativelanguage.googleapis.com'
BASE = 'https://' + HOST
MAX_FILE = 100 * 1024 * 1024


def _url(url):
    value = urllib.parse.urlsplit(url)
    if value.scheme != 'https' or value.netloc != HOST or value.username or value.fragment:
        raise ValueError('Files transport endpoint outside official API')
    return url


def _request(url, key, data=None, headers=None, timeout=600):
    from .gemini_api import NoRedirect, APIError
    headers = dict(headers or {})
    headers['x-goog-api-key'] = key
    req = urllib.request.Request(_url(url), data=data, headers=headers)
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=timeout) as response:
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise APIError('Files metadata exceeds bound')
            return (json.loads(raw) if raw else {}), response.headers.get('X-Goog-Upload-URL')
    except urllib.error.HTTPError as error:
        raise APIError('Files HTTP ' + str(error.code) + '; no credential or upload URL logged') from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise APIError('Files network failure; upload availability unknown, no generation submitted') from None


def _valid(file, asset, mime):
    name = file.get('name', '')
    if not re.fullmatch(r'files/[a-z0-9-]{1,40}', name):
        raise ValueError('Invalid official file resource name')
    if file.get('uri') != BASE + '/v1beta/' + name:
        raise ValueError('Unexpected official file URI')
    if file.get('state') != 'ACTIVE' or file.get('mimeType') != mime:
        raise ValueError('Uploaded file not active or MIME differs')
    if int(file.get('sizeBytes', -1)) != asset['bytes']:
        raise ValueError('Uploaded file byte count differs')
    try:
        decoded = base64.b64decode(file['sha256Hash'], validate=True)
        # Official REST currently returns base64 of the ASCII hex digest;
        # other official representations use 32 raw digest bytes. Both must
        # resolve to the exact local SHA256, never a truncated/permissive match.
        if len(decoded) == 32:
            digest = decoded.hex()
        elif len(decoded) == 64 and re.fullmatch(b'[a-f0-9]{64}', decoded):
            digest = decoded.decode('ascii')
        else:
            raise ValueError('Unsupported official SHA256 representation')
    except (KeyError, ValueError):
        raise ValueError('Official uploaded SHA256 missing') from None
    if digest != asset['sha256']:
        raise ValueError('Uploaded original-byte SHA256 differs')
    return file


def bind_files(case, body, assets, key, timeout):
    """No inference until every required allowed asset is uploaded and independently hash-checked."""
    result = copy.deepcopy(body)
    parts = result['contents'][0]['parts']
    for part, asset in zip(parts[1:], assets, strict=True):
        path = case.path(asset['path'])
        if path.stat().st_size != asset['bytes'] or sha256_file(path) != asset['sha256']:
            raise ValueError('Allowed source changed before upload')
        if asset['bytes'] > MAX_FILE:
            raise ValueError('Original file exceeds explicit 100 MiB transport limit')
        mime = part['fileData']['mimeType']
        receipt_path = case.path('gemini_files/' + asset['sha256'] + '.json')
        file = None
        if receipt_path.exists():
            saved = read_json(receipt_path)
            if saved.get('status') == 'active':
                name = saved['file']['name']
                if not re.fullmatch(r'files/[a-z0-9-]{1,40}', name):
                    raise ValueError('Invalid saved file name')
                # Recheck remote lifetime, state and byte identity; no automatic expired-file substitution.
                file, _ = _request(BASE + '/v1beta/' + name, key, timeout=timeout)
                _valid(file, asset, mime)
            else:
                raise ValueError('Previous file upload incomplete; review before resubmission')
        if file is None:
            receipt = dict(status='upload_started', started_at=now(), asset=asset, mime=mime,
                           transport='files_api_v1', no_resize=True)
            write_json(receipt_path, receipt)
            started = time.perf_counter()
            try:
                _, upload_url = _request(BASE + '/upload/v1beta/files', key,
                    json_bytes({'file': {'display_name': 'hir_' + asset['sha256'][:24]}}),
                    {'Content-Type': 'application/json', 'X-Goog-Upload-Protocol': 'resumable',
                     'X-Goog-Upload-Command': 'start', 'X-Goog-Upload-Header-Content-Length': str(asset['bytes']),
                     'X-Goog-Upload-Header-Content-Type': mime}, timeout)
                if not upload_url:
                    raise ValueError('Official resumable upload URL missing')
                value, _ = _request(upload_url, key, path.read_bytes(),
                    {'Content-Type': mime, 'Content-Length': str(asset['bytes']),
                     'X-Goog-Upload-Offset': '0', 'X-Goog-Upload-Command': 'upload, finalize'}, timeout)
                file = value.get('file', {})
                _valid(file, asset, mime)
                receipt.update(status='active', file=file, completed_at=now(), elapsed_seconds=time.perf_counter()-started)
                write_json(receipt_path, receipt)
            except Exception:
                receipt.update(status='incomplete', completed_at=now())
                write_json(receipt_path, receipt)
                raise
        part['fileData']['fileUri'] = file['uri']
    return result
