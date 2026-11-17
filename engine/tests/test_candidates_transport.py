import pytest
import base64
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import threading
from PIL import Image

from hre.models import HREError


def test_fixture_transport_explicit_and_replayed(tmp_path):
    from hre.candidates.journal import Journal
    from hre.candidates.transport import call_json
    path = tmp_path / "input.png"
    Image.new("RGB", (8, 8)).save(path)
    journal = Journal(tmp_path, {"planner": 1})
    config = {"mode": "fixture", "stages": {}}
    result = call_json(tmp_path, config, journal, "plan", "planner", "inspect", [path], fixture_response={"issues": []})
    assert result == {"issues": []}
    assert call_json(tmp_path, config, journal, "plan", "planner", "inspect", [path], fixture_response={"issues": []}) == result
    with pytest.raises(HREError, match="fixture_response"):
        call_json(tmp_path, config, journal, "plan2", "planner", "inspect", [path])


def test_fixture_input_change_is_not_replayed(tmp_path):
    from hre.candidates.journal import Journal
    from hre.candidates.transport import call_json
    path = tmp_path / "input.png"
    Image.new("RGB", (8, 8)).save(path)
    journal = Journal(tmp_path, {"planner": 1})
    call_json(tmp_path, {"mode": "fixture"}, journal, "plan", "planner", "inspect", [path], fixture_response={})
    Image.new("RGB", (8, 8), "red").save(path)
    with pytest.raises(HREError, match="request_replay_mismatch"):
        call_json(tmp_path, {"mode": "fixture"}, journal, "plan", "planner", "inspect", [path], fixture_response={})


@contextmanager
def provider(body, status=200):
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            calls.append({'path': self.path, 'body': json.loads(self.rfile.read(int(self.headers['Content-Length']))), 'authorization': self.headers.get('Authorization')})
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())
        def log_message(self, *args):
            pass
    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/v1', calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_real_transport_once_and_secret_not_saved(tmp_path, monkeypatch):
    from hre.candidates.journal import Journal
    from hre.candidates.transport import call_json
    path = tmp_path / 'input.png'
    Image.new('RGB', (8, 8), 'red').save(path)
    monkeypatch.setenv('CANDIDATE_TEST_API_KEY', 'private-test-token')
    with provider({'choices': [{'message': {'content': '{"ok":true}'}}], 'usage': {'completion_tokens': 5}}) as (url, calls):
        config = {'mode': 'real', 'stages': {'composer': {'base_url': url, 'model': 'local-vlm', 'api_key_env': 'CANDIDATE_TEST_API_KEY', 'settings': {'max_tokens': 100}}}}
        journal = Journal(tmp_path, {'compose': 2})
        assert call_json(tmp_path, config, journal, 'compose', 'compose', 'Inspect', [path]) == {'ok': True}
        assert call_json(tmp_path, config, journal, 'compose', 'compose', 'Inspect', [path]) == {'ok': True}
        assert len(calls) == 1
        assert calls[0]['path'] == '/v1/chat/completions'
        assert calls[0]['authorization'] == 'Bearer private-test-token'
        data = calls[0]['body']['messages'][0]['content'][1]['image_url']['url'].split(',', 1)[1]
        assert base64.b64decode(data) == path.read_bytes()
        for artifact in tmp_path.rglob('*.json'):
            assert 'private-test-token' not in artifact.read_text()


def test_invalid_model_json_keeps_raw_completion_and_does_not_retry(tmp_path):
    from hre.candidates.journal import Journal
    from hre.candidates.transport import call_json
    with provider({'choices': [{'message': {'content': 'invalid JSON'}}]}) as (url, calls):
        config = {'mode': 'real', 'stages': {'planner': {'base_url': url, 'model': 'local-vlm'}}}
        journal = Journal(tmp_path, {'planner': 1})
        for _ in range(2):
            with pytest.raises(HREError, match='model_json_invalid'):
                call_json(tmp_path, config, journal, 'planner', 'planner', 'Inspect', [])
        assert len(calls) == 1
        assert journal.snapshot()['operations']['planner']['state'] == 'completed'
        assert any('invalid JSON' in path.read_text() for path in tmp_path.rglob('response.json'))


def test_server_error_is_unknown_without_retry(tmp_path):
    from hre.candidates.journal import Journal
    from hre.candidates.transport import call_json
    with provider({'error': 'lost result'}, status=503) as (url, calls):
        config = {'mode': 'real', 'stages': {'planner': {'base_url': url, 'model': 'local-vlm'}}}
        journal = Journal(tmp_path, {'planner': 2})
        for _ in range(2):
            with pytest.raises(HREError, match='operation_unknown'):
                call_json(tmp_path, config, journal, 'planner', 'planner', 'Inspect', [])
        assert len(calls) == 1


@pytest.mark.parametrize('endpoint', [
    {'base_url': 'http://127.0.0.1/v1', 'model': 'SET_DEPLOYMENT_MODEL'},
    {'base_url': 'http://user:secret@127.0.0.1/v1', 'model': 'local'},
    {'base_url': 'http://127.0.0.1/v1?api_key=secret', 'model': 'local'},
    {'base_url': 'http://127.0.0.1/v1', 'model': 'local', 'settings': {'max_tokens': 0}},
    {'base_url': 'http://127.0.0.1/v1', 'model': 'local', 'settings': {'temperature': float('inf')}},
    {'base_url': 'http://127.0.0.1/v1', 'model': 'local', 'api_key': 'raw-secret'},
])
def test_bad_deployment_or_token_settings_reject_before_call(tmp_path, endpoint):
    from hre.candidates.journal import Journal
    from hre.candidates.transport import call_json
    journal = Journal(tmp_path, {'planner': 1})
    with pytest.raises(HREError):
        call_json(tmp_path, {'mode': 'real', 'stages': {'planner': endpoint}}, journal, 'plan', 'planner', 'inspect', [])
    assert not journal.snapshot()['operations']
