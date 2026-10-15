"""Read-only comparison with the pre-existing dataset SHA manifest."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[2]
data = root / "Data"
rows = json.loads((data / "manifest.json").read_text(encoding="utf-8"))
entries = []
for row in rows:
    entries.append((row["input_path"], row["input_sha256"]))
    if row.get("gt_path"):
        entries.append((row["gt_path"], row["gt_sha256"]))
failures = []
for relative, expected in entries:
    with (data / relative).open("rb") as f:
        actual = hashlib.file_digest(f, "sha256").hexdigest()
    if actual != expected:
        failures.append(relative)
report = {"read_only": True, "manifest": "Data/manifest.json", "checked_files": len(entries), "sha256_mismatches": failures, "passed": not failures}
destination = root / "engine" / "validation" / "existing_assets.json"
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report))
raise SystemExit(0 if not failures else 1)
