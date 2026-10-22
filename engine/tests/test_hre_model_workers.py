"""Transport tests use real subprocesses/HTTP; they establish no model quality."""
import base64
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading
import time

import pytest

from hre.model_workers import run_worker, run_vlm_worker
from hre.models import HREError


def command(tmp_path, body):
    script = tmp_path / "fake_worker.py"
    script.write_text(
        "import argparse,json,pathlib,sys,time\n"
        "p=argparse.ArgumentParser();p.add_argument('--request');p.add_argument('--response');a=p.parse_args()\n"
        + body,
        encoding="utf-8",
    )
    return [sys.executable, str(script)]


def paths(tmp_path):
    request = tmp_path / "request.json"
    request.write_text("{}", encoding="utf-8")
    return request, tmp_path / "response.json"


def test_worker_passes_paths_literally_and_keeps_logs(tmp_path):
    # A shell implementation would interpret the metacharacters in this path.
    folder = tmp_path / "input ; $(touch SHELL_EXECUTED)"
    folder.mkdir()
    request, response = paths(folder)
    cmd = command(tmp_path, "print('ordinary output');print('diagnostic',file=sys.stderr)\n"
                  "pathlib.Path(a.response).write_text(json.dumps({'payload':{'input':a.request}}))\n")
    assert run_worker(cmd, request, response, timeout=3) == {"payload": {"input": str(request)}}
    assert response.with_suffix(".stdout.log").read_text().strip() == "ordinary output"
    assert response.with_suffix(".stderr.log").read_text().strip() == "diagnostic"
    receipt = json.loads(response.with_suffix(".invocation.json").read_text())
    assert receipt["status"] == "succeeded" and receipt["returncode"] == 0
    assert not (tmp_path / "SHELL_EXECUTED").exists()


@pytest.mark.parametrize("body,code", [
    ("print('failed',file=sys.stderr);sys.exit(7)\n", "worker_exit_error"),
    ("pass\n", "worker_response_missing"),
    ("pathlib.Path(a.response).write_text('not json')\n", "worker_response_invalid"),
    ("pathlib.Path(a.response).write_text('[]')\n", "worker_response_invalid"),
    ("time.sleep(5)\n", "worker_timeout"),
])
def test_failed_worker_records_one_attempt(tmp_path, body, code):
    request, response = paths(tmp_path)
    marker = tmp_path / "attempts.txt"
    prefix = f"with open({str(marker)!r},'a') as f:f.write('1')\n"
    with pytest.raises(HREError) as err:
        run_worker(command(tmp_path, prefix + body), request, response, timeout=0.2)
    assert err.value.code == code
    assert marker.read_text() == "1"
    assert json.loads(response.with_suffix(".invocation.json").read_text())["status"] == "failed"


@pytest.mark.skipif(os.name != 'posix', reason='Process-group cleanup is a POSIX guarantee')
def test_worker_timeout_kills_spawned_child_before_delayed_write(tmp_path):
    request,response=paths(tmp_path)
    started=tmp_path/'child_started';marker=tmp_path/'child_finished'
    child=("import pathlib,time;"
           f"pathlib.Path({str(started)!r}).write_text('started');"
           "time.sleep(0.5);"
           f"pathlib.Path({str(marker)!r}).write_text('orphan survived')")
    body=("import subprocess\n"
          f"subprocess.Popen([sys.executable,'-c',{child!r}])\n"
          "print('spawned child',file=sys.stderr,flush=True)\n"
          "time.sleep(5)\n")
    with pytest.raises(HREError,match='worker_timeout'):
        run_worker(command(tmp_path,body),request,response,timeout=0.25)
    assert started.exists(), 'Fixture child must start before the worker timeout'
    time.sleep(0.6)
    assert not marker.exists()
    assert 'spawned child' in response.with_suffix('.stderr.log').read_text()
    receipt=json.loads(response.with_suffix('.invocation.json').read_text())
    assert receipt['attempts']==1 and receipt['error_code']=='worker_timeout'


def test_invalid_command_and_existing_response_do_not_start_worker(tmp_path):
    request, response = paths(tmp_path)
    with pytest.raises(HREError, match="worker_command_invalid"):
        run_worker("python worker.py", request, response, timeout=1)
    with pytest.raises(HREError, match="worker_command_missing"):
        run_worker([str(tmp_path / "missing")], request, response, timeout=1)
    response.write_text('{"payload":{"old":true}}')
    with pytest.raises(HREError, match="worker_response_exists"):
        run_worker([sys.executable], request, response, timeout=1)


@pytest.fixture
def local_endpoint(monkeypatch):
    observed = []
    response = {"choices": [{"message": {"content": '{"payload":{"observed":"ok"}}'}}]}
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            observed.append((self.path, self.headers.get("Authorization"),
                             json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            self.send_response(response.get("_http_status", 200))
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("HRE_VLM_BASE_URL", f"http://127.0.0.1:{server.server_port}/v1")
    monkeypatch.setenv("HRE_VLM_MODEL", "test-model")
    monkeypatch.setenv("HRE_VLM_API_KEY", "local-test-key")
    try:
        yield observed, response
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def envelope(tmp_path):
    image = tmp_path / "A.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nimage bytes for transport test")
    return {"schema_version": "hre_worker_request_v1", "kind": "stage",
            "case_root": str(tmp_path), "task_id": "test-task", "request": {},
            "prompt": "Compare A and B. Return the requested JSON.",
            "attachments": [{"role": "content_anchor", "path": "A.png",
                             "sha256": sha256(image.read_bytes()).hexdigest()}],
            "output_dir": str(tmp_path), "executor": {}}


def test_vlm_worker_sends_image_bytes_and_extracts_payload(tmp_path, local_endpoint):
    observed, _ = local_endpoint
    result = run_vlm_worker(envelope(tmp_path))
    assert result['payload'] == {"observed": "ok"}
    assert result['provenance']['model_observed']['ui_model_name']=='test-model'
    assert result['worker_observation']['calls']==1
    assert len(observed) == 1
    path, auth, body = observed[0]
    assert path == "/v1/chat/completions" and auth == "Bearer local-test-key"
    assert body["model"] == "test-model"
    assert body["response_format"] == {"type": "json_object"}
    content = body["messages"][0]["content"]
    image_url = next(x["image_url"]["url"] for x in content if x["type"] == "image_url")
    assert image_url.startswith("data:image/png;base64,")
    assert base64.b64decode(image_url.split(",", 1)[1]) == (tmp_path / "A.png").read_bytes()
    assert any("content_anchor" in x.get("text", "") for x in content)


def test_vlm_worker_preserves_reported_stage_error(tmp_path, local_endpoint):
    observed, response = local_endpoint
    response["choices"][0]["message"]["content"] = json.dumps({
        "payload": None, "error": {"code": "evidence_unavailable", "message": "Cannot compare"}})
    result=run_vlm_worker(envelope(tmp_path))
    assert result['payload'] is None
    assert result['error']=={"code": "evidence_unavailable", "message": "Cannot compare"}
    assert len(observed) == 1


@pytest.mark.parametrize("kind", ["condition", "execute"])
def test_generic_vlm_cannot_impersonate_native_compiler_or_editor(tmp_path, local_endpoint, kind):
    observed, _ = local_endpoint
    value = envelope(tmp_path)
    value["kind"] = kind
    with pytest.raises(HREError, match="worker_kind_unsupported"):
        run_vlm_worker(value)
    assert observed == []


def test_changed_attachment_is_rejected_before_http(tmp_path, local_endpoint):
    observed, _ = local_endpoint
    value = envelope(tmp_path)
    (tmp_path / "A.png").write_bytes(b"changed")
    with pytest.raises(HREError, match="worker_attachment_changed"):
        run_vlm_worker(value)
    assert observed == []


def test_invalid_model_json_does_not_retry(tmp_path, local_endpoint):
    observed, response = local_endpoint
    response["choices"][0]["message"]["content"] = "not JSON"
    with pytest.raises(HREError, match="worker_model_response_invalid"):
        run_vlm_worker(envelope(tmp_path))
    assert len(observed) == 1


def test_http_error_has_one_attempt_and_hides_provider_response(tmp_path, local_endpoint):
    observed, response = local_endpoint
    response.update(_http_status=503, error="Do not expose provider response local-test-key")
    with pytest.raises(HREError, match="worker_http_error") as err:
        run_vlm_worker(envelope(tmp_path))
    assert len(observed) == 1
    assert "local-test-key" not in str(err.value)


def test_builtin_cli_runs_through_transport(tmp_path, local_endpoint, monkeypatch):
    observed, _ = local_endpoint
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parents[1] / "src"))
    request, response = paths(tmp_path)
    request.write_text(json.dumps(envelope(tmp_path)))
    result = run_worker([sys.executable, "-m", "hre.model_workers"], request, response, timeout=10)
    assert result['payload'] == {"observed": "ok"}
    assert result['worker_observation']['requested_model']=='test-model'
    assert len(observed) == 1
    assert response.with_suffix(".stderr.log").read_text() == ""
