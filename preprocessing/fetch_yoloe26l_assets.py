"""Explicit official asset preparation, with GitHub release digest verification."""
import hashlib
import json
from pathlib import Path
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]


def fetch(root=ROOT):
    root = Path(root)
    api = "https://api.github.com/repos/ultralytics/assets/releases/tags/v8.4.0"
    request = urllib.request.Request(api, headers={"Accept": "application/vnd.github+json", "User-Agent": "HarnessIR-offline-preparation"})
    with urllib.request.urlopen(request, timeout=30) as response:
        release = json.load(response)
    selected = [a for a in release["assets"] if a["name"] == "yoloe-26l-seg.pt"]
    if len(selected) != 1:
        raise ValueError("Official exact YOLOE-26l text checkpoint missing/ambiguous")
    asset = selected[0]
    expected = asset.get("digest", "")
    if not expected.startswith("sha256:"):
        raise ValueError("Official asset SHA256 is required before accepting weights")
    expected = expected.removeprefix("sha256:")
    if not 0 < asset["size"] < 1024**3:
        raise ValueError("Unexpected official checkpoint size")
    directory = root / "models/yoloe_26l_seg"
    directory.mkdir(parents=True, exist_ok=True)
    checkpoint = directory / asset["name"]
    def digest(path):
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    if checkpoint.exists():
        if checkpoint.stat().st_size != asset["size"] or digest(checkpoint) != expected:
            raise ValueError("Existing checkpoint differs; do not overwrite or replace it")
    else:
        part = checkpoint.with_suffix(".pt.part")
        url = asset["browser_download_url"] + "?harnessir_prepare=" + uuid.uuid4().hex
        request = urllib.request.Request(url, headers={"User-Agent": "HarnessIR-offline-preparation"})
        with urllib.request.urlopen(request, timeout=60) as source, part.open("xb") as target:
            copied = 0
            while block := source.read(1024 * 1024):
                copied += len(block)
                if copied > asset["size"]:
                    raise ValueError("Official transfer exceeds declared size")
                target.write(block)
        if part.stat().st_size != asset["size"] or digest(part) != expected:
            raise ValueError("Official checkpoint SHA256/size verification failed")
        part.replace(checkpoint)
    receipt = {"repository": "ultralytics/assets", "release": "v8.4.0", "release_id": release["id"], "asset_id": asset["id"], "url": asset["browser_download_url"], "api": api, "sha256": expected, "bytes": asset["size"], "checkpoint": str(checkpoint.resolve()), "model": "YOLOE-26l-seg", "inference_completed": False}
    temp = directory / "source_lock.json.tmp"
    temp.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    temp.replace(directory / "source_lock.json")
    return receipt


if __name__ == "__main__":
    print(json.dumps(fetch(), ensure_ascii=False))
