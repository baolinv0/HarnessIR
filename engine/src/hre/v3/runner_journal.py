"""Append-only hash journal for opt-in v3 cases.

The immutable entry is the commit point. state.json is a recoverable projection,
so a crash between the journal append and projection write does not lose a
submitted-operation marker or make a generation eligible for resubmission.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from ..models import now
from ..storage import read_json, write_json
from .common import digest, require


def immutable_json(path: Path, value: dict) -> dict:
    if path.exists():
        require(read_json(path) == value, "artifact_changed", "Immutable artifact differs: " + str(path))
    else:
        write_json(path, value)
    return value


class Journal:
    """Caller must hold the existing per-case OS lock during all mutations."""

    def __init__(self, root: Path, initial: dict, *, read_only: bool = False):
        self.root = root
        self.read_only = read_only
        self.directory = root / "journal"
        if not read_only:
            self.directory.mkdir(exist_ok=True)
        self.sequence = 0
        self.head = None
        self.state = deepcopy(initial)
        entries = sorted(self.directory.glob("*.json"))
        for index, path in enumerate(entries):
            require(path.name == f"{index:06d}.json", "journal_gap", "Journal sequence is not contiguous")
            entry = read_json(path)
            require(entry.get("sequence") == index and entry.get("previous_hash") == self.head,
                    "journal_modified", "Journal sequence or parent changed")
            require(entry.get("entry_hash") == digest({k: v for k, v in entry.items() if k != "entry_hash"}),
                    "journal_modified", "Journal content hash changed")
            value = entry.get("state")
            require(isinstance(value, dict) and value.get("case_id") == initial["case_id"]
                    and value.get("freeze_sha256") == initial.get("freeze_sha256"),
                    "journal_case_mismatch", "Journal belongs to another frozen case")
            self.state = value
            self.head = entry["entry_hash"]
            self.sequence = index + 1
        if entries and not read_only:
            write_json(root / "state.json", self.state)
        elif not entries and not read_only:
            self.commit(self.state, "created", {})

    def commit(self, state: dict, event: str, details: dict | None = None) -> dict:
        require(not self.read_only, "journal_read_only", "A report reader cannot mutate the run journal")
        value = deepcopy(state)
        value["updated_at"] = now()
        entry = {"schema_version": "hre_journal_v3", "sequence": self.sequence,
                 "previous_hash": self.head, "at": value["updated_at"],
                 "event": event, "details": details or {}, "state": value}
        entry["entry_hash"] = digest(entry)
        immutable_json(self.directory / f"{self.sequence:06d}.json", entry)
        self.state, self.head = value, entry["entry_hash"]
        self.sequence += 1
        write_json(self.root / "state.json", value)
        return value
