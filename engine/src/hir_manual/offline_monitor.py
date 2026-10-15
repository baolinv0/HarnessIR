"""Read-only inspection of offline files; presence is never evidence acceptance.

The server's frozen GPU registry is metadata here. Linux executable/weight paths
need not exist on Windows; contracts, successful readiness, source identities,
ready markers and all evidence assets are nevertheless verified locally.
"""
import csv
import io
import re
from collections import Counter
from pathlib import Path

import psutil
from PIL import Image

from .cache import EvidenceCache, make_cache_key
from .local_evidence import validate_local_evidence
from .protocol import validate_schema
from .storage import atomic_write, now, read_json, resolve_case_path, sha256_file, write_json
from .tool_registry import CANONICALIZER_VERSION, LEGACY_CANONICALIZER_VERSION, TOOL_IDS, GPU_PROFILE_IDS, PROFILE_FILES, gpu_evidence_origin_matches, bundle_hash, load_profile, load_registry, make_contract

FLAT_DIRS = {"T1_OCR": "t1_ocr", "T2_FACE": "t2_faces", "T3_DEPTH": "t3_depth", "T4_SEGMENTATION": "t4_semantic"}


def _within(path, base):
    path, base = Path(path).resolve(), Path(base).resolve()
    if not path.is_relative_to(base) or path == base:
        raise ValueError("Offline monitor path escapes its permitted root")
    return path


def _json(path):
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("Monitor JSON exceeds bounded metadata limit")
    return read_json(path)


def _source(dataset, row):
    for field in ("canonical_sha256", "original_sha256"):
        if not re.fullmatch(r"[a-f0-9]{64}", str(row.get(field, ""))):
            raise ValueError("Invalid input SHA256 metadata")
    if row.get("canonicalizer_version") not in (CANONICALIZER_VERSION, LEGACY_CANONICALIZER_VERSION):
        raise ValueError("Unknown canonicalizer version; no automatic migration")
    canonical = resolve_case_path(dataset, row["canonical_path"])
    original = resolve_case_path(dataset, row["original_path"])
    if sha256_file(canonical) != row["canonical_sha256"] or sha256_file(original) != row["original_sha256"]:
        raise ValueError("Original/canonical bytes disagree with prepared hashes")
    with Image.open(canonical) as image:
        if image.format != "PNG" or image.mode != "RGB" or image.size != (row["width"], row["height"]) or image.width * image.height > 40_000_000:
            raise ValueError("Canonical geometry/mode differs from prepared source")
    if row.get("metadata_path"):
        metadata = _json(resolve_case_path(dataset, row["metadata_path"]))
        for key in ("canonical_sha256", "original_sha256", "canonicalizer_version", "width", "height"):
            if metadata.get(key) != row[key]:
                raise ValueError("Prepared source metadata disagrees: " + key)
    return canonical


def _frozen(root, profile_id="gpu_full_v1"):
    if profile_id not in GPU_PROFILE_IDS:
        raise ValueError("Explicit supported GPU evidence profile required")
    registry_path = root / "preprocessing/registry" / (profile_id + ".json")
    profile_path = root / "preprocessing/configs" / PROFILE_FILES[profile_id]
    if not registry_path.is_file() or not profile_path.is_file():
        return None, None, {}, {"status": "pending", "reason": "actual_gpu_registry_or_profile_missing; design examples are not deployment"}
    try:
        actual = _json(registry_path)
        profile, registry = load_profile(profile_id, root), load_registry(root, profile_id)
        if profile.configuration_status in ("design_example_not_deployed", "example") or (profile_id == "gpu_full_v1" and not profile.formal_eligible):
            raise ValueError("GPU profile is not explicitly deployed/formal eligible")
        return profile, registry, actual.get("tools", {}), {"status": "loaded", "registry_sha256": sha256_file(registry_path), "profile_sha256": sha256_file(profile_path), "profile_id": profile_id}
    except (ValueError, OSError, KeyError, TypeError) as exc:
        return None, None, {}, {"status": "pending", "reason": "frozen_gpu_metadata_unavailable", "error": str(exc)}


def _entry(entry):
    if entry.get("ready") is not True:
        raise ValueError("GPU model has no successful frozen readiness record")
    if bundle_hash(entry.get("components", [])) != entry.get("model_bundle_sha256"):
        raise ValueError("Frozen model component/bundle metadata disagrees")
    for item in entry["components"]:
        if not re.fullmatch(r"[a-f0-9]{64}", str(item.get("sha256", ""))):
            raise ValueError("Invalid frozen component SHA256")
    backend = entry["backend"]
    if not str(backend.get("device", "")).startswith("cuda") or backend.get("source_revision") != entry.get("source_revision") or backend.get("environment_lock_sha256") != entry.get("environment_lock_sha256"):
        raise ValueError("GPU backend/source/environment-lock metadata disagrees")


def _memory_requirement(manifest):
    """Conservative transient validator working set; arrays remain file-mapped.

    T4 validates one class union at a time with bounded comparison tiles. Extra
    decoder/page-cache costs are conservatively budgeted; this is an estimate.
    """
    data = manifest.get("data", {})
    if manifest.get("tool_id") == "T4_SEGMENTATION":
        masks = data.get("native_masks", [])
        pixels = max((int(r["grid_shape"][0]) * int(r["grid_shape"][1]) for r in masks), default=int(manifest["source_width"]) * int(manifest["source_height"]))
        transient_bytes = pixels * 24
    elif manifest.get("tool_id") == "T3_DEPTH":
        shape = data["grid_shape"]
        transient_bytes = int(shape[0]) * int(shape[1]) * 16
    else:
        transient_bytes = 0
    return transient_bytes / 1024**2 * 1.15 + 128


def _inspect(cache, row, tool, contract, profile_id="gpu_full_v1"):
    key = make_cache_key(contract)
    record = {"image_id": row["image_id"], "tool_id": tool, "status": "pending", "evidence_dir": None, "source_paths": [], "cache_key": key, "canonical_sha256": row["canonical_sha256"], "original_sha256": row["original_sha256"], "canonicalizer_version": row["canonicalizer_version"], "ready": True, "formal_eligible": False}
    try:
        directory = cache.path(tool, key)
    except ValueError as exc:
        record.update(status="rejected", reason="cache_path_escapes_root", error=str(exc))
        return record
    if not directory.exists():
        record["reason"] = "same_contract_cache_missing"
        return record
    record["source_paths"] = [str(path) for path in (directory / "evidence.json", directory / "contract.json", directory / "ready.json") if path.is_file()]
    if any(directory.glob("*.part")) or any(directory.glob("*.tmp")) or not all((directory / name).is_file() for name in ("evidence.json", "contract.json", "ready.json")):
        record["reason"] = "incomplete_cache_commit; partial files are not evidence"
        return record
    try:
        evidence_raw, actual_contract, marker = _json(directory / "evidence.json"), _json(directory / "contract.json"), _json(directory / "ready.json")
        validate_schema("evidence_local.schema.json", evidence_raw)
        if actual_contract != contract or make_cache_key(actual_contract) != key:
            raise ValueError("Cache contract differs from current frozen GPU contract")
        if marker.get("cache_key") != key or marker.get("evidence_sha256") != sha256_file(directory / "evidence.json") or marker.get("contract_sha256") != sha256_file(directory / "contract.json"):
            raise ValueError("Cache ready marker disagrees with committed files")
        if not gpu_evidence_origin_matches(profile_id, tool, evidence_raw["evidence_profile_id"], evidence_raw["formal_eligible"]) or evidence_raw["input_sha256"] != row["canonical_sha256"] or evidence_raw["original_sha256"] != row["original_sha256"] or (evidence_raw["source_width"], evidence_raw["source_height"]) != (row["width"], row["height"]):
            raise ValueError("GPU profile, original/canonical SHA or source dimensions disagree")
        needed, available = _memory_requirement(evidence_raw), psutil.virtual_memory().available / 1024**2
        if available < needed:
            record.update(reason="validation_memory_wait", estimated_required_memory_mb=needed, available_memory_mb=available)
            return record
        evidence = validate_local_evidence(directory, contract)
        if marker.get("artifact_hashes") != [{"path": a.path, "sha256": a.sha256} for a in evidence.assets]:
            raise ValueError("Cache ready marker asset association differs")
        if not gpu_evidence_origin_matches(profile_id, tool, evidence.evidence_profile_id, evidence.formal_eligible) or evidence.input_sha256 != row["canonical_sha256"] or evidence.original_sha256 != row["original_sha256"] or (evidence.source_width, evidence.source_height) != (row["width"], row["height"]):
            raise ValueError("GPU profile, original/canonical SHA or source dimensions disagree")
        data = evidence.data
        empty = tool != "T3_DEPTH" and not data.get("items", data.get("faces", data.get("native_masks", [])))
        record.update(status="empty" if empty else "validated", reason="successful_empty_detection" if empty else "strict_same_contract_cache_valid", evidence_dir=str(directory), formal_eligible=profile_id == "gpu_full_v1", evidence_origin_profile=evidence.evidence_profile_id, model_name=evidence.model_name, backend=evidence.backend, elapsed_ms=evidence.elapsed_ms, peak_rss_mb=evidence.peak_rss_mb, evidence_sha256=sha256_file(directory / "evidence.json"), quality_warnings=evidence.quality_warnings)
    except (ValueError, OSError, KeyError, TypeError, OverflowError) as exc:
        record.update(status="rejected", reason="cache_validation_failed", error=str(exc))
    return record


def _discovered(cache_root):
    discoveries = []
    for tool, directory_name in FLAT_DIRS.items():
        directory = cache_root / directory_name
        if directory.is_dir():
            for file in sorted(directory.iterdir()):
                if not file.is_file():
                    continue
                try:
                    path = _within(file, cache_root)
                    discoveries.append({"tool_id": tool, "image_id": file.stem, "status": "discovered-but-unvalidated", "source_path": str(path), "bytes": file.stat().st_size, "reason": "flat server output lacks a locally frozen standard contract/ready/asset ledger; no import performed", "incomplete": file.suffix in (".part", ".tmp")})
                except ValueError:
                    discoveries.append({"tool_id": tool, "image_id": file.stem, "status": "rejected", "reason": "flat file or junction escapes cache root; no content read"})
    for name in ("manifest.json", "processing_status.csv"):
        file = cache_root / name
        if file.is_file():
            discoveries.append({"status": "discovered-but-unvalidated", "source_path": str(_within(file, cache_root)), "bytes": file.stat().st_size, "reason": "external producer index; never treated as validation authority"})
    return discoveries


def scan_offline_cache(root: Path, dataset: Path, out: Path, batch: Path | None = None, profile_id="gpu_full_v1"):
    """Write status JSON + CSV only; all case, source and cache files are read-only."""
    root = Path(root).resolve()
    dataset = _within(dataset, root / "runtime")
    out = _within(out, root / "runtime")
    manifest = _json(dataset / "manifest.json")
    rows = manifest.get("images", [])
    if not isinstance(rows, list) or not rows:
        raise ValueError("Prepared dataset has no valid image records")
    ids = [r.get("image_id") for r in rows]
    if len(ids) != len(set(ids)) or not all(isinstance(i, str) and re.fullmatch(r"[A-Za-z0-9_-]+", i) for i in ids):
        raise ValueError("Prepared dataset has duplicate/unsafe IDs")
    profile, registry, actual_tools, frozen_status = _frozen(root, profile_id)
    cache = EvidenceCache(root / "Data/annotations/cache")
    records, source_checks = [], []
    for row in rows:
        source_error = None
        try:
            _source(dataset, row)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            source_error = str(exc)
        source_checks.append({"image_id": row["image_id"], "status": "rejected" if source_error else "verified", "error": source_error})
        for tool in TOOL_IDS:
            common = {"image_id": row["image_id"], "tool_id": tool, "status": "pending", "evidence_dir": None, "source_paths": [], "formal_eligible": False, "ready": False}
            if source_error:
                common.update(status="rejected", reason="prepared_source_validation_failed", error=source_error)
                records.append(common)
                continue
            if profile is None or tool not in actual_tools:
                common.update(reason="actual_frozen_gpu_tool_metadata_missing")
                records.append(common)
                continue
            try:
                entry = registry.tools[tool]
                _entry(entry)
                contract = make_contract(row["canonical_sha256"], tool, profile, entry, canonicalizer_version=row["canonicalizer_version"])
            except (ValueError, OSError, KeyError, TypeError) as exc:
                common.update(reason="gpu_tool_unavailable_or_not_ready", error=str(exc))
                records.append(common)
                continue
            records.append(_inspect(cache, row, tool, contract, profile_id))
    counts = Counter(r["status"] for r in records)
    accepted = counts["validated"] + counts["empty"]
    source_count = manifest.get("source_count", len(rows) + len(manifest.get("rejected", [])))
    accounting_complete = source_count == len(rows) + len(manifest.get("rejected", []))
    selected = records
    selected_ids = None
    if batch is not None:
        batch = _within(batch, root / "runtime")
        selected_ids = {r["sample_id"] for r in _json(batch / "manifest.json")["images"]}
        selected = [r for r in records if r["image_id"] in selected_ids]
    status = {"generated_at": now(), "cache_root": str(cache.root), "dataset": str(dataset), "dataset_manifest_sha256": sha256_file(dataset / "manifest.json"), "prepared_image_count": len(rows), "source_count": source_count, "source_accounting_complete": accounting_complete, "unsupported_original_inputs": manifest.get("rejected", []), "expected_tool_results": len(rows) * 4, "accepted_gpu_results": accepted, "complete": accepted == len(rows) * 4 and all(r["status"] == "verified" for r in source_checks) and accounting_complete, "all_tool_results_complete": accepted == len(rows) * 4, "counts": dict(counts), "frozen_gpu_metadata": frozen_status, "source_checks": source_checks, "records": selected, "all_records": records, "gallery_image_ids": sorted(selected_ids) if selected_ids is not None else None, "flat_discoveries": _discovered(cache.root), "read_only": True, "case_states_modified": False, "imports_performed": 0, "restoration_output_count": 0, "scope": "GPU evidence files only; does not establish editing, independent verification or restoration effects"}
    status["profile_id"] = profile_id
    status["original_sam3_protocol_eligible"] = profile_id == "gpu_full_v1" and bool(profile and profile.formal_eligible)
    write_json(out, status)
    stream = io.StringIO(newline="")
    columns = ["image_id", "tool_id", "status", "reason", "ready", "formal_eligible", "cache_key", "elapsed_ms", "peak_rss_mb", "evidence_dir", "error"]
    writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(records)
    atomic_write(out.with_suffix(".csv"), stream.getvalue().encode("utf-8"))
    return status
