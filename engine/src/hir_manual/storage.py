"""Single-writer, atomic storage and replayable commit journal."""
import hashlib
import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from filelock import FileLock


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def json_bytes(value) -> bytes:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")


def read_json(path: Path) -> dict:
    from .protocol import strict_loads
    return strict_loads(path.read_text(encoding="utf-8"))


def resolve_case_path(case_dir: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not re.fullmatch(r"[A-Za-z0-9_./-]+", relative):
        raise ValueError("Invalid relative case path")
    if relative.startswith("/") or "//" in relative or any(x in ("..", "") for x in relative.split("/")):
        raise ValueError("Path traversal prohibited")
    base = case_dir.resolve()
    path = base.joinpath(*PurePosixPath(relative).parts).resolve()
    if not path.is_relative_to(base) or path == base:
        raise ValueError("Path or junction escapes case root")
    return path


@dataclass(frozen=True)
class CasePaths:
    case_id: str
    root: Path

    def __post_init__(self):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", self.case_id):
            raise ValueError("Invalid case ID")
        if not self.case_dir.is_relative_to(Path(self.root).resolve()):
            raise ValueError("Case root escapes workspace")

    @property
    def case_dir(self) -> Path:
        return (Path(self.root) / "cases" / self.case_id).resolve()

    def path(self, relative: str) -> Path:
        return resolve_case_path(self.case_dir, relative)


def writer_lock(root: Path):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return FileLock(str(root / ".hir-controller.lock"), timeout=0)


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        for attempt, delay in enumerate([0, .1, .2, .4, .8, 1.6]):
            if delay:
                time.sleep(delay)
            try:
                os.replace(temporary, path)
                return
            except PermissionError:
                if attempt == 5:
                    raise
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path: Path, value) -> None:
    atomic_write(path, json_bytes(value))


def commit(case: CasePaths, state, event_type: str, details=None, accepted_response_sha256=None, next_task=None, crash_at=None):
    """Caller owns root lock. Transaction rename is the only commit point."""
    from .protocol import validate_schema
    state = state.model_copy(deep=True)
    previous = state.revision
    state.revision += 1
    state.updated_at = now()
    validate_schema("state.schema.json", state.model_dump())
    tx_id = uuid.uuid4().hex
    task_info = None
    if next_task is not None:
        task_info = {
            "task_id": next_task.task_id,
            "request_sha256": sha256_file(case.path(f"tasks/{next_task.task_id}/request.json")),
            "prompt_sha256": sha256_file(case.path(next_task.prompt_file)),
        }
        if next_task.role in ("compose", "refine") and case.path("tools/evidence_snapshot.json").exists():
            task_info["evidence_snapshot_sha256"] = sha256_file(case.path("tools/evidence_snapshot.json"))
    transaction = {
        "tx_id": tx_id, "previous_revision": previous, "next_state": state.model_dump(),
        "event": {"event_id": tx_id, "type": event_type, "at": state.updated_at, "revision": state.revision, "details": details or {}},
        "accepted_response_sha256": accepted_response_sha256, "next_task_id": state.pending_task_id, "next_task": task_info,
    }
    if crash_at == "before_commit":
        raise RuntimeError("Simulated crash before commit")
    write_json(case.path(f"transactions/{state.revision:08d}_{tx_id}.json"), transaction)
    if crash_at == "after_commit":
        raise RuntimeError("Simulated crash after commit")
    write_json(case.path("state.json"), state)
    if crash_at == "after_state":
        raise RuntimeError("Simulated crash after state")
    with case.path("events.jsonl").open("ab") as f:
        f.write((json.dumps(transaction["event"], ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8"))
        f.flush()
        os.fsync(f.fileno())
    return state


def recover_case(case: CasePaths):
    """Caller owns root lock. Rebuild snapshots exclusively from committed revisions."""
    from .models import State
    from .protocol import validate_schema
    transactions = []
    previous = 0
    for path in sorted(case.path("transactions").glob("*.json")):
        tx = read_json(path)
        validate_schema("state.schema.json", tx["next_state"])
        if tx["previous_revision"] != previous or tx["next_state"]["revision"] != previous + 1:
            raise ValueError("Transaction revision gap; case is blocked")
        previous += 1
        info = tx.get("next_task")
        if info:
            if sha256_file(case.path(f"tasks/{info['task_id']}/request.json")) != info["request_sha256"]:
                raise ValueError("Immutable request changed")
            request = read_json(case.path(f"tasks/{info['task_id']}/request.json"))
            if sha256_file(case.path(request["prompt_file"])) != info["prompt_sha256"]:
                raise ValueError("Immutable prompt changed")
            if info.get("evidence_snapshot_sha256") and sha256_file(case.path("tools/evidence_snapshot.json")) != info["evidence_snapshot_sha256"]:
                raise ValueError("Consumed evidence snapshot changed")
        transactions.append(tx)
    if not transactions:
        raise ValueError("Case has no committed transaction")
    state = State.model_validate(transactions[-1]["next_state"])
    config_file = case.path("case_config.json")
    if sha256_file(config_file) != state.config_sha256:
        raise ValueError("Locked config changed")
    config = read_json(config_file)
    for relative, digest in config["snapshot_hashes"].items():
        if sha256_file(case.path(relative)) != digest:
            raise ValueError(f"Locked snapshot changed: {relative}")
    if sha256_file(case.path("input/canonical.png")) != state.input_sha256:
        raise ValueError("Canonical input missing or changed")
    metadata = read_json(case.path("input/metadata.json"))
    if sha256_file(case.path(metadata["original_path"])) != metadata["original_sha256"]:
        raise ValueError("Original input changed")
    # Accepted bytes, outputs and evidence remain authoritative after a restart
    # and before export, including cases that have already terminated.
    from .protocol import validate_asset
    for tx in transactions:
        details = tx["event"]["details"]
        if tx.get("accepted_response_sha256"):
            accepted_path = case.path(details["accepted_path"])
            if sha256_file(accepted_path) != tx["accepted_response_sha256"]:
                raise ValueError("Accepted response archive changed")
            if read_json(accepted_path) != details["response"]:
                raise ValueError("Accepted response projection changed")
            response = details["response"]
            if response["role"] == "execute":
                for asset in [response["payload"]["output_asset"], *response["payload"]["extra_assets"]]:
                    validate_asset(case, asset)
        if tx["event"]["type"] == "tool_registered":
            for asset in details["manifest"]["assets"]:
                validate_asset(case, asset)
    write_json(case.path("state.json"), state)
    events = b"".join((json.dumps(tx["event"], ensure_ascii=False) + "\n").encode("utf-8") for tx in transactions)
    atomic_write(case.path("events.jsonl"), events)
    return state


def transactions(case: CasePaths) -> list[dict]:
    return [read_json(p) for p in sorted(case.path("transactions").glob("*.json"))]
