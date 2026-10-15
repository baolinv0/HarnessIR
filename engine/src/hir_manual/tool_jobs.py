import uuid
from pathlib import Path
from PIL import Image
from .cache import make_cache_key
from .storage import atomic_write, read_json, write_json
from .tool_registry import canonicalizer_version_from_metadata, make_contract
from .tool_models import ToolJob


def prepare_job(root, canonical, original_sha256, image_id, tool_id, profile, registry, case_id=None, canonicalizer_version=None):
    from .storage import sha256_file
    entry = registry.tools[tool_id]
    # Offline doctor/precompute also pass a canonical case path. Infer its
    # recorded version when the optional argument is omitted; standalone legacy
    # PNG callers without metadata retain v1 rather than claiming v2.
    metadata_path = Path(canonical).with_name("metadata.json")
    metadata = read_json(metadata_path) if metadata_path.exists() else {}
    recorded_version = canonicalizer_version_from_metadata(metadata)
    if canonicalizer_version is None:
        canonicalizer_version = recorded_version
    elif metadata_path.exists() and canonicalizer_version != recorded_version:
        raise ValueError("Job canonicalizer version differs from source metadata")
    contract = make_contract(sha256_file(canonical), tool_id, profile, entry, canonicalizer_version=canonicalizer_version)
    job = ToolJob(job_id="tool_"+uuid.uuid4().hex, case_id=case_id, image_id=image_id, tool_id=tool_id, evidence_profile_id=profile.evidence_profile_id, cache_contract=contract, cache_key=make_cache_key(contract), canonical_path="input/canonical.png", timeout_seconds=profile.tools[tool_id]["timeout_seconds"])
    directory = Path(root) / "runtime/tool_jobs" / job.job_id
    atomic_write(directory / "input/canonical.png", Path(canonical).read_bytes())
    with Image.open(canonical) as im:
        width,height = im.size
    write_json(directory / "job.json", job)
    write_json(directory / "runner_config.json", {"registry_entry": entry, "profile": profile.model_dump(), "original_sha256": original_sha256, "source_width": width, "source_height": height})
    return job, directory


def update_job(directory, job, status, last_error=None):
    from .protocol import validate_schema
    job.status = status
    job.last_error = last_error
    validate_schema("tool_job.schema.json", job.model_dump())
    write_json(Path(directory) / "job.json", job)
    return job
