"""Transport tests for MiniMax-H3-Image (no GPU/server required)."""
from __future__ import annotations

import base64
import io

import pytest
import requests
from PIL import Image

from harness import settings
from harness.clients import MFMClient
from harness.h3_client import _canvas, edit, endpoint


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), (20, 30, 40)).save(buffer, "PNG")
    return buffer.getvalue()


class Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {"data": [{"b64_json": base64.b64encode(_png()).decode("ascii")}]}


def test_sglang_edit_transport(monkeypatch):
    captured = []

    def fake_post(url, **kwargs):
        captured.append((url, kwargs))
        return Response()

    monkeypatch.setattr("harness.h3_client.requests.post", fake_post)
    monkeypatch.setenv("HARNESS_H3_SEED", "42")
    result = edit([Image.new("RGB", (1024, 1024))],
                  "Repair the motion blur.", base_url="http://127.0.0.1:30000",
                  image_size="1K", timeout_sec=30)
    assert result.mode == "RGB" and result.size == (64, 64)
    assert len(captured) == 1
    url, call = captured[0]
    assert url == "http://127.0.0.1:30000/v1/images/edits"
    assert call["data"]["size"] == "1024x1024"
    assert call["data"]["seed"] == "42"
    assert call["data"]["generator_device"] == "cpu"
    assert call["data"]["response_format"] == "b64_json"
    assert "<Picture 1>" in call["data"]["prompt"]
    assert len(call["files"]) == 1 and call["files"][0][0] == "image"
    assert call["files"][0][1][2] == "image/png"
    assert call["headers"] == {}
    assert call["timeout"] == 30


def test_mfm_h3_does_not_require_gemini_credentials(monkeypatch):
    monkeypatch.setattr(settings, "MFM_H3_BASE_URL", "http://127.0.0.1:30000")
    monkeypatch.setenv("HARNESS_H3_SEED", "1234")
    monkeypatch.setattr("harness.h3_client.requests.post", lambda *a, **kw: Response())
    editor = MFMClient(model="minimax-h3-image")
    output = editor.edit([Image.new("RGB", (1024, 1024))], "Restore the photograph.")
    assert output.size == (64, 64)


def test_h3_rejects_bad_url_and_size():
    with pytest.raises(ValueError):
        endpoint("https://alice:password@example.com")
    with pytest.raises(ValueError):
        endpoint("http://127.0.0.1:30000?token=secret")
    with pytest.raises(ValueError):
        _canvas(Image.new("RGB", (1024, 1024)), "wide")
    assert endpoint("http://127.0.0.1:30000/v1") == "http://127.0.0.1:30000/v1/images/edits"


def test_h3_timeout_does_not_auto_retry(monkeypatch):
    calls = []

    def timeout(*args, **kwargs):
        calls.append(1)
        raise requests.Timeout("request failed")

    monkeypatch.setattr("harness.h3_client.requests.post", timeout)
    with pytest.raises(requests.Timeout):
        MFMClient(model="minimax-h3-image").edit(
            [Image.new("RGB", (1024, 1024))], "Restore the image.")
    assert len(calls) == 1


def test_h3_rejects_missing_image_payload(monkeypatch):
    class Empty:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": []}

    monkeypatch.setattr("harness.h3_client.requests.post", lambda *a, **kw: Empty())
    with pytest.raises(ValueError, match="valid base64-encoded image"):
        edit([Image.new("RGB", (1024, 1024))], "Restore",
             base_url="http://127.0.0.1:30000", image_size="1K", timeout_sec=30)
