from pathlib import Path
from .evidence import _rewrite
from .storage import atomic_write, read_json, write_json, sha256_file, sha256_bytes, json_bytes
from .tool_models import EvidenceBinding, VisualPack
from .local_evidence import validate_local_evidence
from .protocol import validate_schema


def bind_evidence(case, cache_dir, source="local_compute"):
    manifest = validate_local_evidence(cache_dir, read_json(Path(cache_dir)/"contract.json"))
    if manifest.input_sha256 != read_json(case.path("state.json"))["input_sha256"]:
        raise ValueError("Cache belongs to a different canonical image")
    from PIL import Image
    if sha256_file(case.path("input/canonical.png")) != manifest.input_sha256:
        raise ValueError("Case canonical source changed")
    with Image.open(case.path("input/canonical.png")) as canonical:
        if canonical.size != (manifest.source_width,manifest.source_height):
            raise ValueError("Evidence source dimensions differ from actual canonical")
    old_hash = sha256_file(Path(cache_dir) / "evidence.json")
    prefix = f"tools/{manifest.tool_id}/local/{manifest.cache_key}"
    data = manifest.model_dump()
    replacements = {a["path"]: f"{prefix}/{a['path']}" for a in data["assets"]}
    archived = []
    for asset in data["assets"]:
        original = asset["path"]
        relative = replacements[original]
        target = case.path(relative)
        raw = (Path(cache_dir) / original).read_bytes()
        if asset["kind"] == "json":
            native = read_json(Path(cache_dir)/original)
            rewritten = _rewrite(native, replacements)
            if native != rewritten:
                archive_path = f"{prefix}/source_native/{original}"
                archive_target = case.path(archive_path)
                if archive_target.exists() and archive_target.read_bytes() != raw:
                    raise ValueError("Immutable native evidence archive changed")
                atomic_write(archive_target, raw)
                archived.append({"path": archive_path, "sha256": asset["sha256"], "kind": "json", "width": None, "height": None})
                raw = json_bytes(rewritten)
                asset["sha256"] = sha256_bytes(raw)
        if target.exists() and target.read_bytes() != raw:
            raise ValueError("Immutable case evidence asset changed")
        atomic_write(target, raw)
        asset["path"] = relative
    data["assets"].extend(archived)
    data["data"] = _rewrite(data["data"], replacements)
    data["image_id"] = case.case_id
    data["original_sha256"] = read_json(case.path("input/metadata.json"))["original_sha256"]
    relative = f"{prefix}/evidence.json"
    # Never overwrite an existing case snapshot, even with a newer cache.
    if case.path(relative).exists() and read_json(case.path(relative)) != data:
        raise ValueError("Immutable evidence manifest conflict")
    write_json(case.path(relative), data)
    binding = EvidenceBinding(case_id=case.case_id, tool_id=manifest.tool_id, cache_key=manifest.cache_key, cache_manifest_sha256=old_hash, case_manifest_path=relative, case_manifest_sha256=sha256_file(case.path(relative)), source=source, evidence_profile_id=manifest.evidence_profile_id)
    validate_schema("evidence_binding.schema.json", binding.model_dump())
    write_json(case.path(f"{prefix}/binding.json"), binding)
    return binding, data


def build_composer_pack(case, required_tools):
    from .service import history
    hist = history(case)
    pack = VisualPack()
    for manifest in hist["evidence"]:
        if manifest["tool_id"] in required_tools and manifest["status"] == "ok":
            pack.evidence.append(manifest)
            pack.assets.extend(a for a in manifest["assets"] if a["kind"] in ("photo", "overlay", "map"))
    return pack
