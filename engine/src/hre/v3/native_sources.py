"""Audited native protocols: verify installed source bytes, not a version label."""
from hashlib import sha1, sha256
from pathlib import Path

from .common import require


DIFFUSERS_COMMIT = "aaf57d03a3edfbd9de457d2872417a92f149a91d"
# Git blob IDs returned for the inspected files at DIFFUSERS_COMMIT.  This is a
# protocol compatibility guard; it does not authenticate every installed package.
DIFFUSERS_BLOBS = {
    "pipelines/qwenimage21/pipeline_qwenimage21.py": "7cb519cde4a2e79a0bfc97abefc892490bde137e",
    "pipelines/qwenimage/pipeline_qwenimage_edit_plus.py": "8b17f17c0e3e9ccbb502bb17ecdfcdf6a2af0ee3",
    "modular_pipelines/modular_pipeline.py": "28e485eddbc16c65cc0f5d187d9811ddaec21be7",
    "modular_pipelines/flux3/prompt_upsampler.py": "b70fc5c1692c13dda7de45fdd08dcdfd7c3a44e9",
    "modular_pipelines/flux3/modular_blocks_flux3_distilled.py": "d23f894c6df705b853cbe15a59fc5ae9d9b1057e",
    "modular_pipelines/flux3/image_processor.py": "f52df6243e32f016a31b498af2e051742d841a43",
    "modular_pipelines/flux3/encoders.py": "bd407a35be42559d2e464a3d274f8e2069d5c138",
    "modular_pipelines/flux3/before_denoise.py": "bf6428dc58f4705ab860d42343aad736627ca510",
    "pipelines/bria_fibo2/pipeline_bria_fibo2.py": "6ee1da888e60db9445dd192a50294ce748065378",
    "pipelines/bria_fibo2/image_processor.py": "25e34fe060924629ca6d7a7b2115efb581e489d4",
}


def verify_source_file(path: Path, relative: str) -> dict:
    path = Path(path).resolve()
    require(relative in DIFFUSERS_BLOBS and path.is_file(), "native_source_missing", "Audited native source is unavailable")
    data = path.read_bytes()
    blob = sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()
    require(blob == DIFFUSERS_BLOBS[relative], "native_source_mismatch",
            f"Installed Diffusers source {relative} differs from audited commit {DIFFUSERS_COMMIT}")
    return {"path": str(path), "relative_path": relative, "sha256": sha256(data).hexdigest(),
            "git_blob": blob, "inspected_upstream_commit": DIFFUSERS_COMMIT,
            "verification": "installed_source_bytes_match_audited_blob"}


def verify_module(module, relative: str) -> dict:
    return verify_source_file(Path(module.__file__), relative)
