"""Single-attempt worker transport and an optional OpenAI-compatible VLM worker.

External workers accept ``--request PATH --response PATH``. The built-in worker
only handles text/vision stages; native condition compilers and image editors
must supply their own worker. No model result or execution receipt is invented.
"""
from __future__ import annotations

import argparse
import base64
from hashlib import sha256
import json
import math
import mimetypes
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .models import HREError, now


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _read_object(path: Path, code: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise HREError(code, "Expected a readable JSON object") from exc
    if not isinstance(value, dict):
        raise HREError(code, "Expected a JSON object")
    return value


def run_worker(command: list[str], request_path: Path, response_path: Path, *, timeout: float) -> dict:
    """Run one worker without a shell or retries, retaining logs and invocation status.

    The returned dict is exactly the worker response. Sidecars use the response
    stem: ``.stdout.log``, ``.stderr.log``, and ``.invocation.json``. A response
    that already exists is rejected so an old result cannot satisfy a new call.
    The caller is responsible for unique task directories and resume policy.
    """
    if (not isinstance(command, list) or not command or
            any(not isinstance(item, str) or not item or "\0" in item for item in command)):
        raise HREError("worker_command_invalid", "Use a non-empty argument list, not a shell command string")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
        raise HREError("worker_timeout_invalid", "Worker timeout must be a positive finite number")
    if shutil.which(command[0]) is None:
        raise HREError("worker_command_missing", "Worker executable was not found or is not executable")
    request_path, response_path = Path(request_path).resolve(), Path(response_path).resolve()
    if not request_path.is_file():
        raise HREError("worker_request_missing", "Worker request file does not exist")
    if response_path.exists():
        raise HREError("worker_response_exists", "Use a new response path for each invocation")
    response_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path = response_path.with_suffix(".invocation.json")
    receipt = {"schema_version": "hre_worker_invocation_v1", "started_at": now(),
               "finished_at": None, "status": "running", "returncode": None,
               "timeout_seconds": timeout, "attempts": 1}
    _write_json(receipt_path, receipt)
    started = time.monotonic()
    try:
        with response_path.with_suffix(".stdout.log").open("wb") as stdout, \
                response_path.with_suffix(".stderr.log").open("wb") as stderr:
            try:
                process = subprocess.Popen(
                    command + ["--request", str(request_path), "--response", str(response_path)],
                    stdout=stdout, stderr=stderr, stdin=subprocess.DEVNULL,
                    shell=False, start_new_session=(os.name=='posix'),
                )
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    if os.name=='posix':
                        try:os.killpg(process.pid,signal.SIGKILL)
                        except ProcessLookupError:pass
                    else:process.kill()
                    process.wait()
                    raise
            except subprocess.TimeoutExpired as exc:
                raise HREError("worker_timeout", "Worker exceeded its timeout; no retry was made") from exc
            except OSError as exc:
                raise HREError("worker_start_failed", "Worker could not be started") from exc
        receipt["returncode"] = process.returncode
        if process.returncode != 0:
            raise HREError("worker_exit_error", f"Worker exited with status {process.returncode}; see stderr log")
        if not response_path.is_file():
            raise HREError("worker_response_missing", "Worker exited without creating its response")
        payload = _read_object(response_path, "worker_response_invalid")
        receipt["status"] = "succeeded"
        return payload
    except HREError as exc:
        receipt.update(status="failed", error_code=exc.code)
        raise
    finally:
        receipt.update(finished_at=now(), elapsed_seconds=round(time.monotonic() - started, 6))
        _write_json(receipt_path, receipt)


def run_vlm_worker(envelope: dict) -> dict:
    """Make one real chat-completions request and return only the stage payload.

    Configure ``HRE_VLM_BASE_URL`` (usually ending in /v1), ``HRE_VLM_MODEL``,
    optional ``HRE_VLM_API_KEY`` and optional ``HRE_VLM_TIMEOUT`` (seconds).
    Credentials are never included in response files or exception messages.
    """
    if envelope.get("schema_version") != "hre_worker_request_v1":
        raise HREError("worker_request_invalid", "Unsupported worker request schema")
    if envelope.get("kind") != "stage":
        raise HREError("worker_kind_unsupported", "The generic VLM worker only supports stage requests")
    prompt = envelope.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise HREError("worker_request_invalid", "A stage prompt is required")
    base_url, model = os.environ.get("HRE_VLM_BASE_URL", "").strip(), os.environ.get("HRE_VLM_MODEL", "").strip()
    parsed = urlsplit(base_url)
    if not base_url or parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HREError("worker_config_invalid", "HRE_VLM_BASE_URL must be an HTTP(S) endpoint without embedded credentials")
    if not model:
        raise HREError("worker_config_invalid", "HRE_VLM_MODEL is required")
    try:
        timeout = float(os.environ.get("HRE_VLM_TIMEOUT", "120"))
    except ValueError as exc:
        raise HREError("worker_config_invalid", "HRE_VLM_TIMEOUT must be a positive number") from exc
    if not math.isfinite(timeout) or timeout <= 0:
        raise HREError("worker_config_invalid", "HRE_VLM_TIMEOUT must be a positive finite number")
    content = [{"type": "text", "text": prompt}]
    case_root = Path(envelope.get("case_root", "."))
    attachments = envelope.get("attachments", [])
    if not isinstance(attachments, list):
        raise HREError("worker_request_invalid", "attachments must be a list")
    for attachment in attachments:
        if not isinstance(attachment, dict) or not isinstance(attachment.get("path"), str):
            raise HREError("worker_attachment_invalid", "Each attachment must specify a path")
        path = Path(attachment["path"])
        if not path.is_absolute():
            path = case_root / path
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise HREError("worker_attachment_missing", "An input attachment could not be read") from exc
        if attachment.get("sha256") and sha256(data).hexdigest() != attachment["sha256"]:
            raise HREError("worker_attachment_changed", "Attachment bytes differ from the frozen request")
        mime = mimetypes.guess_type(path.name)[0]
        if mime not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
            raise HREError("worker_attachment_invalid", "VLM attachments must be PNG, JPEG, WEBP, or GIF images")
        content.append({"type": "text", "text": f"Image role: {attachment.get('role', 'reference')}"})
        content.append({"type": "image_url", "image_url": {
            "url": f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"}})
    body = {"model": model, "messages": [{"role": "user", "content": content}],
            "response_format": {"type": "json_object"}}
    endpoint = base_url.rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint += "/chat/completions"
    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get("HRE_VLM_API_KEY", "")
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    request = Request(endpoint, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    started=time.monotonic()
    try:
        with urlopen(request, timeout=timeout) as response:
            response_body = response.read()
    except HTTPError as exc:
        raise HREError("worker_http_error", f"VLM endpoint returned HTTP {exc.code}; no retry was made") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise HREError("worker_network_error", "VLM request failed; no retry was made") from exc
    try:
        api_response=json.loads(response_body)
        message = api_response["choices"][0]["message"]
        value = json.loads(message["content"])
        if not isinstance(value, dict):
            raise ValueError("Model JSON must be an object")
        observed_model=api_response.get('model') or model
        provenance={'model_observed':{'ui_model_name':observed_model,'exact_model_version':None,
            'transport':'api','observed_at':now(),'operator_steps':['One OpenAI-compatible vision API request; no retry']}}
        observation={'requested_model':model,'returned_model':api_response.get('model'),
            'base_url':base_url,'calls':1,'elapsed_seconds':round(time.monotonic()-started,6),
            'usage':api_response.get('usage'),'adapter_version':'hre.model_workers.v1'}
        if value.get("error") is not None:
            if not isinstance(value["error"], dict) or value.get("payload") is not None:
                raise ValueError("A stage error requires null payload and an error object")
            return {"payload": None, "error": value["error"],"provenance":provenance,"worker_observation":observation}
        payload = value["payload"] if "payload" in value else value
        if not isinstance(payload, dict):
            raise ValueError("Stage payload must be an object")
        return {"payload": payload,"provenance":provenance,"worker_observation":observation}
    except (KeyError, IndexError, TypeError, ValueError, UnicodeError) as exc:
        raise HREError("worker_model_response_invalid", "VLM did not return a valid JSON stage payload or error") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--response", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.response.exists():
            raise HREError("worker_response_exists", "Response path already exists")
        response = run_vlm_worker(_read_object(args.request, "worker_request_invalid"))
        args.response.parent.mkdir(parents=True, exist_ok=True)
        _write_json(args.response, response)
        return 0
    except HREError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
