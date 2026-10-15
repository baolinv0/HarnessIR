"""Synthetic protocol fixtures only; never used as real model evidence."""
import sys
from pathlib import Path
from PIL import Image
from hir_manual.storage import atomic_write, write_json, sha256_file, sha256_bytes
from hir_manual.tool_registry import bundle_hash, load_profile, make_contract
from hir_manual.cache import make_cache_key


def synthetic_registry(root):
    weight = Path(root) / "fixture_weight.bin"
    atomic_write(weight, b"synthetic fixture - not a trained model")
    components = [{"name": "synthetic fixture", "path": str(weight), "sha256": sha256_file(weight)}]
    entry = {"ready": True, "model_name": "synthetic protocol fixture, no model called", "python_executable": sys.executable, "components": components, "model_bundle_sha256": bundle_hash(components), "source_revision": "fixture", "environment_lock_sha256": "0"*64, "backend": {"implementation": "fixture", "source_revision": "fixture", "framework": "fixture", "framework_version": "0", "device": "cpu", "precision": "fp32", "environment_lock_sha256": "0"*64}}
    entry["model_name"]="SCRFD_det_10g"
    entry["backend"]["implementation"]="insightface_scrfd_detector_only"
    write_json(Path(root)/"preprocessing/registry/cpu_probe_v1.json", {"registry_status": "synthetic_test_only", "automatic_download": False, "tools": {"T2_FACE": entry}})
    return entry


def face_evidence(directory, contract, width=64, height=48):
    directory = Path(directory)
    write_json(directory/"raw/faces.json", {"faces": [], "fixture_only": True})
    overlay = directory / "maps/faces.png"
    overlay.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (width,height)).save(overlay)
    components = [{"name": "synthetic fixture", "sha256": sha256_bytes(b"synthetic fixture - not a trained model")}]
    manifest = {"protocol_version": "1.1", "tool_id": "T2_FACE", "input_sha256": contract["canonical_sha256"], "status": "ok", "model_name": "synthetic protocol fixture, no model called", "checkpoint_sha256": None, "source_width": width, "source_height": height, "tool_width": width, "tool_height": height, "coordinates": "canonical_norm", "source_to_tool": [[1,0,0],[0,1,0],[0,0,1]], "detections": [], "assets": [{"path":"raw/faces.json","sha256":sha256_file(directory/"raw/faces.json"),"kind":"json","width":None,"height":None},{"path":"maps/faces.png","sha256":sha256_file(overlay),"kind":"overlay","width":width,"height":height}], "data":{"faces":[],"native_result_path":"raw/faces.json"},"error":None,"image_id":"synthetic fixture","original_sha256":"1"*64,"evidence_profile_id":"cpu_probe_v1","model_bundle_sha256":bundle_hash(components),"components":components,"backend":contract["backend"],"parameters_sha256":sha256_bytes(__import__('hir_manual.tool_registry',fromlist=['canonical_json']).canonical_json(contract['parameters'])),"cache_key":make_cache_key(contract),"views":[{"id":"full","grid_shape":[height,width],"view_to_canonical":[[1/width,0,0],[0,1/height,0],[0,0,1]],"kind":"full_frame"}],"quality_warnings":["synthetic_fixture_no_model_called"],"elapsed_ms":0,"peak_rss_mb":None,"formal_eligible":False}
    write_json(directory/"evidence.json", manifest)
    manifest["model_name"]="SCRFD_det_10g"
    write_json(directory/"evidence.json", manifest)
    return manifest
