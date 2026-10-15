import os
import uuid
from pathlib import Path
from filelock import FileLock
from .protocol import validate_schema
from .storage import atomic_write, json_bytes, read_json, resolve_case_path, sha256_bytes, sha256_file, write_json, now
from .tool_registry import canonical_json


def make_cache_key(contract: dict) -> str:
    validate_schema("cache_contract.schema.json", contract)
    return sha256_bytes(canonical_json(contract))


class EvidenceCache:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def path(self, tool_id, key):
        from .tool_registry import TOOL_IDS
        import re
        if tool_id not in TOOL_IDS or not re.fullmatch("[a-f0-9]{64}", key):
            raise ValueError("Invalid cache identity")
        return resolve_case_path(self.root, f"{tool_id}/{key}")

    def lock(self, tool_id, key, timeout=0):
        path = self.path(tool_id, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        return FileLock(str(path) + ".lock", timeout=timeout)

    def lookup(self, contract):
        from .local_evidence import validate_local_evidence
        key = make_cache_key(contract)
        path = self.path(contract["tool_id"], key)
        if not (path / "ready.json").is_file():
            return None
        try:
            ready = read_json(path / "ready.json")
            if ready["cache_key"] != key or sha256_file(path / "evidence.json") != ready["evidence_sha256"] or sha256_file(path / "contract.json") != ready["contract_sha256"]:
                return None
            if read_json(path / "contract.json") != contract:
                return None
            manifest = validate_local_evidence(path, contract)
            if ready["artifact_hashes"] != [{"path": a.path, "sha256": a.sha256} for a in manifest.assets]:
                return None
            return path
        except (OSError, ValueError, KeyError):
            return None

    def publish(self, contract, source_dir):
        """Caller holds key lock. Incomplete/corrupt old versions are retained."""
        from .local_evidence import validate_local_evidence
        manifest = validate_local_evidence(source_dir, contract)
        key = make_cache_key(contract)
        destination = self.path(contract["tool_id"], key)
        if self.lookup(contract):
            return destination
        temporary = destination.parent / ("_tmp_" + uuid.uuid4().hex)
        temporary.mkdir(parents=True)
        for asset in manifest.assets:
            atomic_write(resolve_case_path(temporary, asset.path), resolve_case_path(Path(source_dir), asset.path).read_bytes())
        write_json(temporary / "evidence.json", manifest)
        write_json(temporary / "contract.json", contract)
        validate_local_evidence(temporary, contract)
        if destination.exists():
            archive = destination.parent / ("_rejected_" + key + "_" + uuid.uuid4().hex)
            if not destination.resolve().is_relative_to(self.root) or not archive.resolve().is_relative_to(self.root):
                raise ValueError("Unsafe cache archive path")
            destination.rename(archive)
        temporary.rename(destination)
        write_json(destination / "ready.json", {"cache_key": key, "evidence_sha256": sha256_file(destination / "evidence.json"), "contract_sha256": sha256_file(destination / "contract.json"), "artifact_hashes": [{"path": a.path, "sha256": a.sha256} for a in manifest.assets], "committed_at": now()})
        return destination
