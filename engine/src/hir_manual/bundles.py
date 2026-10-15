"""Offline jobs/results transfer. Imports are bound to a locally frozen export."""
import os
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from .cache import EvidenceCache, make_cache_key
from .local_evidence import validate_local_evidence
from .storage import atomic_write, read_json, write_json, sha256_file, resolve_case_path
from .tool_registry import load_registry, make_contract, canonicalizer_version_from_metadata
from .tool_models import ImportSummary


def export_missing_jobs(dataset_manifest, profile, output, root, tool_ids):
    from .tool_cli import read_manifest, canonical_input
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError("Export destination exists; choose a fresh bundle")
    registry = load_registry(root, profile.evidence_profile_id)
    cache = EvidenceCache(root / "Data/annotations/cache")
    bundle_id = "export_" + uuid.uuid4().hex
    directory = root / "runtime/offline_exports" / bundle_id
    directory.mkdir(parents=True)
    entries, unresolved, seen = [], [], set()
    rows = read_manifest(dataset_manifest)
    for row in rows:
        source = Path(row.get("input_path", row.get("lq", row.get("input", ""))))
        if not str(source) or str(source) == ".":
            raise ValueError("Manifest entry has no source")
        if not source.is_absolute():
            source = Path(dataset_manifest).resolve().parent / source
        case = canonical_input(root, source, profile.evidence_profile_id)
        metadata = read_json(case.path("input/metadata.json"))
        canonical_sha = sha256_file(case.path("input/canonical.png"))
        relative = f"inputs/{canonical_sha}.png"
        atomic_write(directory / relative, case.path("input/canonical.png").read_bytes())
        for tool in tool_ids:
            try:
                contract = make_contract(canonical_sha, tool, profile, registry.tools[tool], canonicalizer_version=canonicalizer_version_from_metadata(metadata))
            except (ValueError, KeyError, TypeError) as exc:
                unresolved.append({"image_id": row.get("sample_id", source.stem), "input_path": relative, "tool_id": tool, "reason": str(exc)})
                continue
            key = make_cache_key(contract)
            if (tool, key) in seen or cache.lookup(contract):
                continue
            seen.add((tool, key))
            entries.append({"image_id": row.get("sample_id", source.stem), "tool_id": tool, "cache_key": key, "contract": contract, "input_path": relative, "canonical_sha256": canonical_sha, "original_sha256": metadata["original_sha256"]})
    index = {"protocol_version": "1.1", "bundle_kind": "missing_jobs", "bundle_id": bundle_id, "profile": profile.model_dump(), "entries": entries, "unresolved": unresolved, "manifest_images": len(rows)}
    write_json(directory / "bundle.json", index)
    # The ledger is local authority for later import, retained outside the ZIP.
    write_json(directory / "expected.json", index)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(directory / "bundle.json", "bundle.json")
            for file in sorted((directory / "inputs").glob("*.png")) if (directory / "inputs").exists() else []:
                archive.write(file, file.relative_to(directory).as_posix())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


def _extract(bundle, destination):
    with zipfile.ZipFile(bundle) as archive:
        infos = archive.infolist()
        seen, size = set(), 0
        for info in infos:
            name = info.filename
            path = PurePosixPath(name)
            normalized = name.rstrip("/").casefold()
            if normalized in seen or path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name or ((info.external_attr >> 16) & 0o170000) == 0o120000:
                raise ValueError("Unsafe or duplicate bundle member")
            seen.add(normalized)
            size += info.file_size
            if size > 8 * 1024**3 or len(infos) > 100000:
                raise ValueError("Bundle exceeds import budget")
            resolve_case_path(destination, name.rstrip("/"))
        archive.extractall(destination)


def import_cache_bundle(bundle, cache_root):
    cache_root = Path(cache_root).resolve()
    root = cache_root.parents[2]
    temporary = root / "runtime/bundle_imports" / ("import_" + uuid.uuid4().hex)
    temporary.mkdir(parents=True)
    summary = ImportSummary()
    try:
        _extract(bundle, temporary)
        index = read_json(temporary / "bundle.json")
        if index.get("protocol_version") != "1.1" or index.get("bundle_kind") != "cache_results":
            raise ValueError("Expected a protocol 1.1 cache_results bundle")
        bundle_id = index.get("bundle_id", "")
        import re
        if not re.fullmatch(r"export_[a-f0-9]{32}", bundle_id):
            raise ValueError("Invalid local export identity")
        ledger_dir = root / "runtime/offline_exports" / bundle_id
        ledger = read_json(ledger_dir / "expected.json")
        expected = {(e["tool_id"], e["cache_key"]): e for e in ledger["entries"]}
        identities, validated = set(), []
        cache = EvidenceCache(cache_root)
        # Validate the entire bundle before publishing any entry.
        for entry in index["entries"]:
            identity = (entry["tool_id"], entry["cache_key"])
            if identity in identities:
                raise ValueError("Duplicate result entry")
            identities.add(identity)
            if identity not in expected:
                raise ValueError("Result not requested by the frozen local export")
            wanted = expected[identity]
            if entry["contract"] != wanted["contract"] or make_cache_key(entry["contract"]) != entry["cache_key"]:
                raise ValueError("Imported contract differs from frozen export")
            if sha256_file(resolve_case_path(ledger_dir, wanted["input_path"])) != wanted["canonical_sha256"]:
                raise ValueError("Local canonical source changed")
            if sha256_file(resolve_case_path(temporary, entry["input_path"])) != wanted["canonical_sha256"]:
                raise ValueError("Imported canonical SHA mismatch")
            source = resolve_case_path(temporary, entry["evidence_dir"])
            manifest = validate_local_evidence(source, wanted["contract"])
            if manifest.original_sha256 != wanted["original_sha256"]:
                raise ValueError("Imported original SHA mismatch")
            from PIL import Image
            with Image.open(resolve_case_path(temporary,entry["input_path"])) as canonical:
                if canonical.size != (manifest.source_width,manifest.source_height):
                    raise ValueError("Imported source geometry differs from canonical")
            validated.append((wanted["contract"], source))
        for contract, source in validated:
            with cache.lock(contract["tool_id"], make_cache_key(contract), timeout=30):
                if cache.lookup(contract):
                    summary.existing += 1
                else:
                    cache.publish(contract, source)
                    summary.imported += 1
    except (ValueError, OSError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        summary.rejected += 1
        summary.messages.append(str(exc))
    write_json(temporary / "import_summary.json", summary)
    return summary
