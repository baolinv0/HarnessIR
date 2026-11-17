"""Native H3 request transport and distilled FLUX.2 pipeline contracts."""
import base64
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

from PIL import Image

from hre.models import file_sha256
from hre.v3 import flux2, h3
from hre.v3.common import runtime_clear
from hre.v3.dispatch import compile_condition, generate


def editing_request(tmp_path, name):
    source = tmp_path / "source.png"
    Image.new("RGB", (32, 64), (7, 87, 129)).save(source)
    return {"schema_version": "hre_model_request_v3", "request_id": "native-test", "profile_id": name,
            "task_mode": "restoration", "strategy": "native", "brief": "Restore visible fabric texture.",
            "intent": None, "seed": 271, "canvas": {"width": 32, "height": 64},
            "spatial": {"mode": "full_frame"}, "inputs": [{"role": "source", "path": str(source),
                "sha256": file_sha256(source), "width": 32, "height": 64, "mode": "RGB"}]}


def test_h3_submits_one_multipart_edit_and_retains_native_bytes(tmp_path):
    request = editing_request(tmp_path, "minimax_h3")
    native = io.BytesIO()
    Image.new("RGB", (32, 64), "blue").save(native, format="PNG")
    data = native.getvalue()
    observed = []

    class Server(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            msg = BytesParser(policy=policy.default).parsebytes(
                f'Content-Type: {self.headers["Content-Type"]}\r\n\r\n'.encode() + body,
            )
            fields = {part.get_param("name", header="content-disposition"): part.get_payload(decode=True)
                      for part in msg.iter_parts()}
            observed.append((self.path, fields))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"data": [{"b64_json": base64.b64encode(data).decode()}]}).encode())

    with ThreadingHTTPServer(("127.0.0.1", 0), Server) as server:
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            condition = compile_condition(request, {"backend": "direct"})
            result = generate(request, condition, {"model_id": h3.MODEL_ID, "revision": "a" * 40,
                "base_url": f"http://127.0.0.1:{server.server_port}/v1", "settings": {"min_generation_area": 1024}},
                tmp_path / "native")
        finally:
            server.shutdown()
            thread.join()
    assert len(observed) == 1
    path, fields = observed[0]
    assert path == "/v1/images/edits"
    assert fields["image"] == (tmp_path / "source.png").read_bytes()
    assert fields["prompt"].decode() == condition["text"]
    assert fields["prompt"].startswith(b"Edit <Picture 1>")
    assert fields["seed"] == b"271" and fields["size"] == b"32x64"
    assert fields["min_generation_area"] == b"1024"
    assert Path(result["outputs"][0]["path"]).read_bytes() == data


def test_flux2_passes_source_and_uses_fixed_native_recipe(tmp_path, monkeypatch):
    request = editing_request(tmp_path, "flux2_klein")
    observed = {}

    class Pipeline:
        @classmethod
        def from_pretrained(cls, path, **kwargs):
            observed.update(path=path, loading=kwargs)
            return cls()

        def to(self, device):
            return self

        def __call__(self, **kwargs):
            observed.update(kwargs)
            return SimpleNamespace(images=[Image.new("RGB", (32, 64), "green")])

    class Generator:
        def __init__(self, device):
            self.device = device

        def manual_seed(self, value):
            self.seed = value
            return self

    from contextlib import nullcontext
    monkeypatch.setitem(sys.modules, "diffusers", SimpleNamespace(__version__="test", Flux2KleinPipeline=Pipeline))
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(bfloat16="bf16", Generator=Generator, inference_mode=nullcontext))
    runtime_clear()
    try:
        condition = compile_condition(request, {"backend": "direct"})
        result = generate(request, condition, {"model_id": flux2.MODEL_ID, "revision": "b" * 40,
            "local_path": str(tmp_path), "device": "cpu", "pipeline_version": "test"}, tmp_path / "native")
    finally:
        runtime_clear()
    assert observed["image"].getpixel((0, 0)) == (7, 87, 129)
    assert (observed["width"], observed["height"]) == (32, 64)
    assert observed["num_inference_steps"] == 4 and observed["guidance_scale"] == 1.0
    assert observed["generator"].seed == 271 and observed["loading"]["local_files_only"]
    assert result["observation"]["actual_generation_count"] == 1
