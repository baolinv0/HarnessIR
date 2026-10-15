"""Controller-only types; no inference framework may be imported here."""
from pathlib import Path
from pydantic import Field
from .models import Model, EvidenceManifest


class EvidenceProfile(Model):
    evidence_profile_id: str
    configuration_status: str
    formal_eligible: bool
    offline: bool = True
    auto_download: bool = False
    auto_install: bool = False
    max_active_workers: int = 1
    batch_size: int = 1
    cpu_threads: int = 2
    keep_worker_alive: bool = False
    worker_lifetime: str = "single_job"
    min_available_memory_mb: int
    abort_available_memory_mb: int
    max_worker_rss_mb: int
    memory_sample_interval_ms: int = 200
    evidence_failure_policy: str
    tools: dict


class ModelRegistry(Model):
    registry_status: str
    automatic_download: bool = False
    tools: dict


class ToolJob(Model):
    protocol_version: str = "1.1"
    job_id: str
    case_id: str | None
    image_id: str
    tool_id: str
    evidence_profile_id: str
    cache_contract: dict
    cache_key: str
    canonical_path: str
    status: str = "queued"
    attempt: int = 1
    timeout_seconds: int
    last_error: str | None = None


class LocalEvidenceManifest(EvidenceManifest):
    protocol_version: str = "1.1"
    image_id: str
    original_sha256: str
    evidence_profile_id: str
    model_bundle_sha256: str
    components: list[dict]
    backend: dict
    parameters_sha256: str
    cache_key: str
    views: list[dict]
    quality_warnings: list[str]
    elapsed_ms: float | int
    peak_rss_mb: float | int | None
    formal_eligible: bool


class EvidenceBinding(Model):
    case_id: str
    tool_id: str
    cache_key: str
    cache_manifest_sha256: str
    case_manifest_path: str
    case_manifest_sha256: str
    source: str
    evidence_profile_id: str


class WorkerResult(Model):
    status: str
    error_code: str | None = None
    message: str | None = None
    returncode: int | None = None
    elapsed_ms: float = 0.0
    peak_rss_mb: float = 0.0
    log_dir: str
    output_dir: str
    pid: int | None = None
    process_released: bool = True


class VisualPack(Model):
    evidence: list[dict] = Field(default_factory=list)
    assets: list[dict] = Field(default_factory=list)
    unavailable: list[dict] = Field(default_factory=list)


class ImportSummary(Model):
    imported: int = 0
    existing: int = 0
    rejected: int = 0
    messages: list[str] = Field(default_factory=list)
