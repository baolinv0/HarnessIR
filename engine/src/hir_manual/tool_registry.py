import re
from pathlib import Path
from .protocol import DESIGN_DIR
from .storage import read_json, sha256_bytes, sha256_file
from .tool_models import EvidenceProfile, ModelRegistry

TOOL_IDS = ("T1_OCR", "T2_FACE", "T3_DEPTH", "T4_SEGMENTATION")
PROFILE_FILES = {"cpu_probe_v1": "cpu_probe.json", "gpu_full_v1": "gpu_full.json", "gpu_yoloe26l_v1": "gpu_yoloe26l.json", "gpu_sam31_v5": "gpu_sam31_v5.json"}
GPU_PROFILE_IDS = ("gpu_full_v1", "gpu_yoloe26l_v1", "gpu_sam31_v5")


def gpu_evidence_origin_matches(profile_id, tool_id, origin_id, formal_eligible):
    """Retain provenance while allowing unchanged T1-T3 contract reuse.

    Alternative evidence cannot be relabelled as original SAM3-protocol evidence.
    The full cache contract is independently checked by every caller.
    """
    if profile_id == "gpu_full_v1":
        return origin_id == "gpu_full_v1" and formal_eligible is True
    if profile_id in ("gpu_yoloe26l_v1", "gpu_sam31_v5"):
        return (origin_id == profile_id and formal_eligible is False) or (tool_id in TOOL_IDS[:3] and origin_id == "gpu_full_v1" and formal_eligible is True)
    return False
LEGACY_CANONICALIZER_VERSION = "hir_rgb8_exif_icc_v1"
CANONICALIZER_VERSION = "hir_rgb8_exif_icc_v2_stablepng"


def canonicalizer_version_from_metadata(metadata):
    """Read the frozen source version; absence in old cases means v1.

    Never default historical metadata to the currently deployed canonicalizer.
    Reading the version does not migrate or rewrite any case file.
    """
    version = metadata.get("canonicalizer_version", LEGACY_CANONICALIZER_VERSION)
    if not isinstance(version, str) or not version.strip():
        raise ValueError("Invalid canonicalizer version in source metadata")
    return version


def load_profile(profile_id="cpu_probe_v1", root=None):
    if profile_id not in PROFILE_FILES:
        raise ValueError("Unsupported frozen evidence profile")
    path = Path(root) / "preprocessing/configs" / PROFILE_FILES[profile_id] if root else None
    if path is None or not path.exists():
        path = DESIGN_DIR / "preprocessing/configs" / PROFILE_FILES[profile_id]
    profile = EvidenceProfile.model_validate(read_json(path))
    if profile.evidence_profile_id != profile_id:
        raise ValueError("Profile identity differs from selected frozen configuration")
    if profile_id == "gpu_yoloe26l_v1" and (profile.formal_eligible or profile.tools["T4_SEGMENTATION"].get("model") != "YOLOE-26l-seg"):
        raise ValueError("Authorized YOLOE alternative must remain separate from formal SAM3 evaluation")
    if profile_id == "gpu_sam31_v5":
        from .sam31_evidence import RAW_CONTRACT
        t4 = profile.tools["T4_SEGMENTATION"]
        if profile.formal_eligible or t4.get("model") != "SAM3.1" or t4.get("raw_contract_sha256") != RAW_CONTRACT or t4.get("execution_mode") != "cache_only":
            raise ValueError("SAM3.1 v5 must retain independent frozen alternative cache-only identity")
    if not profile.offline or profile.auto_download or profile.auto_install or profile.max_active_workers != 1 or profile.batch_size != 1:
        raise ValueError("v1.1 requires offline, one worker, single image, no installs/downloads")
    for parameters in profile.tools.values():
        if parameters.get("prompt_set_id"):
            parameters["prompt_set"] = parameters.get("prompt_set") or read_json(DESIGN_DIR / "preprocessing/configs/prompt_sets" / f"{parameters['prompt_set_id']}.json")
    return profile


def load_registry(root, profile_id="cpu_probe_v1"):
    path = Path(root) / "preprocessing/registry" / f"{profile_id}.json"
    if not path.exists():
        return ModelRegistry.model_validate(read_json(DESIGN_DIR / "preprocessing/configs/model_registry.example.json"))
    data = read_json(DESIGN_DIR / "preprocessing/configs/model_registry.example.json")
    actual = read_json(path)
    data.update({k: v for k, v in actual.items() if k != "tools"})
    data["tools"].update(actual["tools"])
    result = ModelRegistry.model_validate(data)
    if result.automatic_download:
        raise ValueError("Runtime automatic downloads prohibited")
    return result


def canonical_json(value):
    import json
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def bundle_hash(components):
    names = [c["name"] for c in components]
    if not components or len(names) != len(set(names)):
        raise ValueError("Model bundle needs unique ordered component names")
    normalized = [{"name": c["name"], "sha256": c["sha256"]} for c in components]
    return sha256_bytes(canonical_json(normalized))


def check_entry(entry, require_ready=True):
    if entry.get("execution_mode") == "cache_only" or entry.get("model_name") == "SAM3.1":
        raise ValueError("model_missing: SAM3.1 alternative is imported-cache-only; import missing evidence manually")
    if require_ready and not entry.get("ready"):
        raise ValueError("model_missing: model has no validated warm-up readiness")
    executable = entry.get("python_executable")
    if not executable or not Path(executable).is_file():
        raise ValueError("model_missing: isolated Python executable unavailable")
    if bundle_hash(entry.get("components", [])) != entry.get("model_bundle_sha256"):
        raise ValueError("Model bundle digest mismatch")
    for component in entry["components"]:
        if sha256_file(Path(component["path"])) != component["sha256"]:
            raise ValueError("Model component changed; prepare a new registry/config")
    backend = entry["backend"]
    if backend["source_revision"] != entry["source_revision"] or backend["environment_lock_sha256"] != entry["environment_lock_sha256"]:
        raise ValueError("Registry/backend lock disagreement")
    lock_file = entry.get("environment_lock_file")
    if lock_file and sha256_file(Path(lock_file)) != entry["environment_lock_sha256"]:
        raise ValueError("Environment lock changed")
    return entry


def make_contract(canonical_sha, tool_id, profile, entry, canonicalizer_version=None):
    from .protocol import validate_schema
    parameters = dict(profile.tools[tool_id])
    parameters.update(cpu_threads=profile.cpu_threads, batch_size=profile.batch_size)
    model_aliases = {"PP-OCRv6_medium_det+PP-OCRv6_medium_rec": "PP-OCRv6_medium_det+rec", "SCRFD_det_10g.onnx": "SCRFD_det_10g"}
    if entry.get("model_name") != model_aliases.get(parameters["model"], parameters["model"]):
        raise ValueError("unavailable: registry model differs from frozen profile; no model substitution allowed")
    for field in ("implementation", "device", "precision"):
        if entry.get("backend", {}).get(field) != parameters[field]:
            raise ValueError("unavailable: registry backend differs from frozen profile: " + field)
    prompt_hash = None
    if parameters.get("prompt_set_id"):
        prompt = parameters.get("prompt_set")
        if prompt is None:
            raise ValueError("Prompt set was not frozen into the evidence profile; create a new configuration")
        parameters["prompt_set"] = prompt
        prompt_hash = sha256_bytes(canonical_json(prompt))
    # Omitted version preserves the historical API contract. Case-aware callers
    # must pass the version read from that case's immutable input metadata.
    version = canonicalizer_version_from_metadata({} if canonicalizer_version is None else {"canonicalizer_version": canonicalizer_version})
    contract = {"contract_version": "1.1", "canonical_sha256": canonical_sha, "canonicalizer_version": version, "tool_id": tool_id, "model_bundle_sha256": entry["model_bundle_sha256"], "backend": entry["backend"], "parameters": parameters, "prompt_set_sha256": prompt_hash, "adapter_version": "hir_local_adapters_v1.1", "roi_policy_id": parameters["roi_policy_id"]}
    validate_schema("cache_contract.schema.json", contract)
    return contract
