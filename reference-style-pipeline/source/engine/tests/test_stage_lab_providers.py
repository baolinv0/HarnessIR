import base64
import io
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from PIL import Image

from hre.stage_lab.providers import call_provider


@pytest.fixture
def picture(tmp_path):
    path = tmp_path / 'A.png'
    Image.new('RGB', (12, 8), (30, 60, 90)).save(path)
    return path


@pytest.fixture
def api():
    state = {'requests': [], 'reply': {}}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers['Content-Length']))
            state['requests'].append((self.path, dict(self.headers), body))
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(state['reply']).encode())

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state['url'] = f'http://127.0.0.1:{server.server_port}/v1'
    yield state
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def request(picture, stage='diagnose'):
    return {'stage': stage, 'prompt': 'Compare image A with image B.',
            'images': [{'role': 'A', 'path': str(picture)}, {'role': 'B', 'path': str(picture)}],
            'context': {}, 'parameters': {}, 'profile': {}}


def test_openai_chat_preserves_image_order_and_parses_fenced_json(api, picture, tmp_path, monkeypatch):
    monkeypatch.setenv('LAB_TEST_KEY', 'test-key')
    api['reply'] = {'choices': [{'message': {'content': '```json\n{"differences": []}\n```'}}],
                    'usage': {'prompt_tokens': 12}}
    result = call_provider({'provider': 'openai', 'model': 'vision-a', 'base_url': api['url'],
                            'api_key_env': 'LAB_TEST_KEY', 'parameters': {'temperature': 0}},
                           request(picture), tmp_path / 'run')
    path, headers, body = api['requests'][0]
    payload = json.loads(body)
    assert path == '/v1/chat/completions'
    assert headers['Authorization'] == 'Bearer test-key'
    assert payload['model'] == 'vision-a'
    content = payload['messages'][-1]['content']
    assert [x['text'] for x in content if x['type'] == 'text'][:2] == ['Image A', 'Image B']
    assert len([x for x in content if x['type'] == 'image_url']) == 2
    assert result['data'] == {'differences': []}
    assert result['usage']['prompt_tokens'] == 12


def test_openai_image_edit_posts_both_images_and_keeps_output_bytes(api, picture, tmp_path):
    original = picture.read_bytes()
    api['reply'] = {'data': [{'b64_json': base64.b64encode(original).decode()}]}
    result = call_provider({'provider': 'openai', 'model': 'editor', 'base_url': api['url'],
                            'mode': 'image-edit'}, request(picture, 'execute'), tmp_path / 'run')
    path, headers, body = api['requests'][0]
    assert path == '/v1/images/edits'
    assert 'multipart/form-data' in headers['Content-Type']
    assert body.count(b'name="image[]"') == 2
    assert Path(result['images'][0]).read_bytes() == original


def test_gemini_reads_images_and_skips_thought_text(api, picture, tmp_path):
    encoded = base64.b64encode(picture.read_bytes()).decode()
    api['reply'] = {'candidates': [{'content': {'parts': [
        {'text': 'private reasoning', 'thought': True}, {'text': '{"ok":true}'},
        {'inlineData': {'mimeType': 'image/png', 'data': encoded}}]}}],
        'usageMetadata': {'totalTokenCount': 13}}
    result = call_provider({'provider': 'gemini', 'model': 'image-model',
                            'base_url': api['url']}, request(picture, 'execute'), tmp_path / 'run')
    path, _, body = api['requests'][0]
    payload = json.loads(body)
    assert path == '/v1/models/image-model:generateContent'
    assert len([p for p in payload['contents'][0]['parts'] if 'inlineData' in p]) == 2
    assert result['text'] == '{"ok":true}'
    assert result['data'] == {'ok': True}
    assert Image.open(result['images'][0]).size == (12, 8)


def test_command_receives_request_and_resolves_relative_image(picture, tmp_path):
    worker = tmp_path / 'worker.py'
    worker.write_text('''import json, shutil, sys\nfrom pathlib import Path\nr=json.loads(Path(sys.argv[1]).read_text())\nout=Path(sys.argv[2])\nshutil.copyfile(r["images"][0]["path"],out.parent/"candidate.png")\nout.write_text(json.dumps({"text":"done", "data":{"stage":r["stage"]}, "images":["candidate.png"]}))\n''')
    model = {'provider': 'command', 'command': [sys.executable, str(worker), '{request}', '{output}']}
    result = call_provider(model, request(picture, 'execute'), tmp_path / 'run')
    assert result['data'] == {'stage': 'execute'}
    assert Path(result['images'][0]).is_absolute()
    assert Image.open(result['images'][0]).size == (12, 8)


def test_command_failure_is_visible(picture, tmp_path):
    with pytest.raises(RuntimeError, match='exit 3.*worker failed'):
        call_provider({'provider': 'command', 'command': [sys.executable, '-c',
                       'import sys; print("worker failed",file=sys.stderr); sys.exit(3)']},
                      request(picture), tmp_path / 'run')


def test_demo_labels_synthetic_outputs_and_changes_pixels(picture, tmp_path):
    result = call_provider({'provider': 'demo', 'model': 'demo-a'},
                           request(picture, 'execute'), tmp_path / 'run')
    assert result['metadata']['synthetic'] is True
    assert result['data']['synthetic'] is True
    with Image.open(result['images'][0]) as image:
        assert image.size == (12, 8)
        assert image.getpixel((0, 0)) != (30, 60, 90)


def test_manual_provider_has_actionable_handoff_error(picture, tmp_path):
    with pytest.raises(ValueError, match='export.*import'):
        call_provider({'provider': 'manual'}, request(picture), tmp_path / 'run')
