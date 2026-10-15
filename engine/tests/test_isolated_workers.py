import hashlib
import importlib.util
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_deployment_extracts_only_exact_detector(tmp_path):
    from preprocessing.prepare_models import extract_scrfd
    archive = tmp_path / "models.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr("buffalo_l/det_10g.onnx", b"detector")
        stream.writestr("buffalo_l/w600k_r50.onnx", b"recognition")
    output = extract_scrfd(archive, tmp_path / "output")
    assert output.read_bytes() == b"detector"
    assert [p.name for p in output.parent.iterdir()] == ["det_10g.onnx"]


def test_deployment_rejects_model_archive_path_traversal(tmp_path):
    from preprocessing.prepare_models import extract_scrfd
    archive = tmp_path / "models.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr("../../det_10g.onnx", b"model")
    with pytest.raises(ValueError, match="unsafe"):
        extract_scrfd(archive, tmp_path / "output")


def test_adapter_imports_do_not_load_model_frameworks():
    code = "import preprocessing.adapters.face, preprocessing.adapters.ocr, preprocessing.adapters.depth, preprocessing.adapters.segmentation; import sys; assert not any(m in sys.modules for m in ['torch','paddle','onnxruntime','insightface'])"
    completed = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr


def test_runtime_offline_guard_blocks_network_and_install_subprocess():
    code = "from preprocessing.workers.common import enforce_offline; enforce_offline(); import socket,subprocess; socket.create_connection(('example.com',443))"
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode != 0
    assert "runtime network is disabled" in result.stderr
    code = "from preprocessing.workers.common import enforce_offline; enforce_offline(); import subprocess,sys; subprocess.run([sys.executable,'-m','pip','install','torch'])"
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode != 0
    assert "runtime package installation is disabled" in result.stderr


def test_missing_model_is_typed_failure_with_no_evidence(tmp_path):
    from preprocessing.prepare_models import canonical_json
    model_hash="b"*64
    components=[{"name":"detector","path":str(tmp_path/"missing.onnx"),"sha256":model_hash}]
    bundle_hash=hashlib.sha256(canonical_json([{"name":"detector","sha256":model_hash}])).hexdigest()
    backend={"implementation":"insightface_scrfd_detector_only","source_revision":"test_only","framework":"onnxruntime","framework_version":"test_only","device":"cpu","precision":"fp32","environment_lock_sha256":"c"*64}
    parameters={"cpu_threads":2,"batch_size":1,"device":"cpu","model":"SCRFD_det_10g.onnx","implementation":"insightface_scrfd_detector_only","precision":"fp32"}
    contract={"tool_id":"T2_FACE","canonical_sha256":"a"*64,"model_bundle_sha256":bundle_hash,"backend":backend,"parameters":parameters}
    job={"protocol_version":"1.1","job_id":"test_missing","tool_id":"T2_FACE","image_id":"fixture","evidence_profile_id":"cpu_probe_v1","canonical_path":"input/canonical.png","cache_contract":contract,"cache_key":hashlib.sha256(canonical_json(contract)).hexdigest()}
    (tmp_path/"job.json").write_text(json.dumps(job),encoding="utf-8")
    config={"registry_entry":{"model_name":"SCRFD_det_10g","components":components,"model_bundle_sha256":bundle_hash,"backend":backend},"profile":{"cpu_threads":2,"offline":True,"auto_download":False,"auto_install":False}}
    (tmp_path/"runner_config.json").write_text(json.dumps(config),encoding="utf-8")
    output=tmp_path/"result"
    result=subprocess.run([sys.executable,str(ROOT/"preprocessing/worker_main.py"),"--job",str(tmp_path/"job.json"),"--out",str(output)],cwd=ROOT,capture_output=True,text=True)
    assert result.returncode==1
    assert json.loads((output/"error.json").read_text("utf-8"))["code"]=="model_missing"
    assert not (output/"evidence.json").exists()
    assert not (output/"worker_done.json").exists()


def test_frozen_download_receipt_rejects_changed_existing_bytes(tmp_path):
    from preprocessing.prepare_models import download
    existing=tmp_path/"checkpoint.pth"
    existing.write_bytes(b"changed")
    with pytest.raises(ValueError,match="hash mismatch"):
        download("https://example.invalid/no_network_should_occur",existing,hashlib.sha256(b"old").hexdigest())
