"""Transport isolation checks; fake upload responses do not constitute real-model acceptance."""
import base64
import copy
import pytest
from hir_manual import gemini_api as api
from hir_manual import gemini_files as files
from hir_manual.service import Controller
from hir_manual.storage import read_json


def test_files_transport_explicit_and_sha_checked(tmp_path, photo, monkeypatch):
    ctl = Controller(tmp_path)
    cfg = api.configuration('gemini-3-pro-image', 'gemini-3.1-pro-preview', media_transport='files_api_v1')
    state = ctl.new(photo, 'restore', cfg); case = ctl.case(state.case_id)
    body, _, assets = api.build_request(case, ctl.current_task(case.case_id), read_json(case.path('case_config.json')))
    original = copy.deepcopy(body); a = assets[0]
    record = dict(name='files/test-1', uri=files.BASE + '/v1beta/files/test-1', state='ACTIVE',
                  mimeType='image/png', sizeBytes=str(a['bytes']),
                  sha256Hash=base64.b64encode(bytes.fromhex(a['sha256'])).decode())
    calls = []
    def request(url, key, data=None, headers=None, timeout=600):
        calls.append((url, data))
        if url.endswith('/upload/v1beta/files'):
            return {}, files.BASE + '/upload/v1beta/files?upload_id=private-session'
        if 'upload_id=' in url:
            assert data == case.path(a['path']).read_bytes()
            return {'file': record}, None
        return record, None
    monkeypatch.setattr(files, '_request', request)
    bound = files.bind_files(case, body, assets, 'not-serialized-key', 600)
    assert body == original
    assert bound['contents'][0]['parts'][1]['fileData']['fileUri'] == record['uri']
    saved = case.path('gemini_files/' + a['sha256'] + '.json').read_text()
    assert 'private-session' not in saved and 'not-serialized-key' not in saved
    files.bind_files(case, body, assets, 'not-serialized-key', 600)
    assert len(calls) == 3  # Second request rechecks metadata, never uploads again.
    bad = dict(record, sha256Hash=base64.b64encode(bytes(32)).decode())
    with pytest.raises(ValueError, match='SHA256'):
        files._valid(bad, a, 'image/png')
    ascii_hex = dict(record, sha256Hash=base64.b64encode(a['sha256'].encode('ascii')).decode())
    assert files._valid(ascii_hex, a, 'image/png') == ascii_hex
    malformed = dict(record, sha256Hash=base64.b64encode(b'x' * 64).decode())
    with pytest.raises(ValueError): files._valid(malformed, a, 'image/png')


def test_files_reject_other_hosts_and_implicit_transport():
    for url in ('http://generativelanguage.googleapis.com/upload', 'https://evil.test/upload',
                'https://generativelanguage.googleapis.com@evil.test/upload'):
        with pytest.raises(ValueError): files._url(url)
    with pytest.raises(ValueError):
        api.configuration('gemini-3-pro-image', 'gemini-3.1-pro-preview', media_transport='resize')


def test_files_no_credentials_on_network_error(monkeypatch):
    import urllib.error
    class Broken:
        def open(self, *args, **kwargs):
            raise urllib.error.URLError('private-key private-url')
    monkeypatch.setattr(files.urllib.request, 'build_opener', lambda *args: Broken())
    with pytest.raises(api.APIError) as exc:
        files._request(files.BASE + '/v1beta/files/test', 'private-key')
    assert 'private-key' not in str(exc.value) and 'private-url' not in str(exc.value)
