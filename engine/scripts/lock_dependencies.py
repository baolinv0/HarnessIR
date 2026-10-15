"""Record only the controller's dependency closure, excluding bundled doc tools."""
from importlib.metadata import distribution
from pathlib import Path
from packaging.requirements import Requirement

pending = ["hir-manual", "pytest"]
versions = {}
visited = set()
while pending:
    name = pending.pop()
    dist = distribution(name)
    key = dist.metadata["Name"]
    if key.lower() in visited:
        continue
    visited.add(key.lower())
    if key.lower() != "hir-manual":
        versions[key] = dist.version
    for raw in dist.requires or []:
        requirement = Requirement(raw)
        if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
            pending.append(requirement.name)
destination = Path(__file__).resolve().parents[1] / "requirements.lock.txt"
destination.write_text("# Python 3.12 / Windows; generated from installed controller dependencies\n" + "\n".join(f"{k}=={v}" for k, v in sorted(versions.items(), key=lambda item: item[0].lower())) + "\n", encoding="utf-8")
print(f"Locked {len(versions)} packages: {destination}")
