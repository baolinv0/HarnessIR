"""Bounded-memory chunked upload of the validated HarnessIR photo ZIP."""
import argparse
import base64
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
import time
import uuid

import requests
from urllib.parse import quote
import colab_client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--session", default="harnessir_existing_t4")
    parser.add_argument("--chunk-kib", type=int, default=512)
    args = parser.parse_args()
    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    source = Path(receipt["snapshot_archive"]).resolve()
    allowed = colab_client.ROOT / "runtime/sam3_colab/uploads"
    if not source.is_relative_to(allowed) or not receipt["remote_archive"].startswith("/content/harnessir_sam3_"):
        raise ValueError("Only the frozen task input archive is allowed")
    with source.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != receipt["sha256"]:
            raise ValueError("Frozen input archive changed")
    colab_client.configure()
    from colab_cli import common
    common.setup_logging(False)
    common.state.config_path = str(colab_client.PRIVATE / "sessions.json")
    state = common.state.get_session(args.session)

    def call(method, path, payload=None, params=None):
        current = common.state.get_session(args.session)
        if current.endpoint != state.endpoint:
            raise ValueError("Runtime changed during upload")
        query = {"authuser": "0", "colab-runtime-proxy-token": current.token}
        query.update(params or {})
        response = requests.request(method, current.url.rstrip("/") + "/api/contents/" + quote(path.strip("/"), safe="/"),
                                    params=query, json=payload, timeout=(30, 120))
        if response.status_code == 404:
            raise FileNotFoundError("Task file or directory not found")
        if not response.ok:
            raise RuntimeError(f"Contents API HTTP {response.status_code}")
        return response.json()

    directory = PurePosixPath(receipt["remote_directory"])
    for parent in reversed([directory, *directory.parents]):
        if str(parent) in ("/", "/content"):
            continue
        try:
            model = call("GET", str(parent), params={"content": "0"})
            if model["type"] != "directory":
                raise ValueError("Expected task directory")
        except FileNotFoundError:
            call("PUT", str(parent), {"type": "directory", "path": str(parent), "name": parent.name})

    def put_chunk(path, data, index):
        return call("PUT", path, {"type": "file", "format": "base64", "path": path,
                                  "name": PurePosixPath(path).name,
                                  "content": base64.b64encode(data).decode("ascii"), "chunk": index})

    probe_path = str(directory / ("chunk_probe_" + uuid.uuid4().hex + ".bin"))
    probe = b"HarnessIR bounded-memory chunk protocol witness\x00\xff"
    put_chunk(probe_path, probe[:15], 1)
    put_chunk(probe_path, probe[15:], -1)
    model = call("GET", probe_path, params={"content": "1", "format": "base64"})
    if base64.b64decode(model["content"]) != probe:
        raise ValueError("Server chunk protocol witness failed")
    print("CHUNK_PROTOCOL_REAL_ROUNDTRIP_PASSED", flush=True)

    target = receipt["remote_archive"]
    temporary = target + ".uploading_" + uuid.uuid4().hex
    size = source.stat().st_size
    if not 64 <= args.chunk_kib <= 4096:
        raise ValueError("Chunk size must be between64 and4096 KiB")
    chunk_size = args.chunk_kib * 1024
    started = time.monotonic()
    transferred = 0
    with source.open("rb") as stream:
        index = 1
        while data := stream.read(chunk_size):
            transferred += len(data)
            put_chunk(temporary, data, -1 if transferred == size else index)
            index += 1
            if index % 8 == 0 or transferred == size:
                print(json.dumps({"uploaded_bytes": transferred, "total_bytes": size, "percent": round(100 * transferred / size, 1)}), flush=True)
    model = call("GET", temporary, params={"content": "0"})
    if model.get("size") != size:
        raise ValueError("Uploaded byte count differs")
    # Keep previous files intact; this upload uses an immutable hash directory.
    try:
        call("GET", target, params={"content": "0"})
    except FileNotFoundError:
        call("PATCH", temporary, {"path": target.strip("/")})
    else:
        raise ValueError("Target already exists; retain upload for explicit validation rather than overwrite")
    receipt.update(status="uploaded_size_verified_hash_verification_pending", uploaded_bytes=transferred,
                   upload_elapsed_seconds=time.monotonic() - started, chunk_size_bytes=chunk_size,
                   chunk_protocol_verified=True, remote_archive_sha256_verified=False,
                   new_runtime_created=False, model_inferences=0)
    pending = args.receipt.with_suffix(".json.tmp")
    pending.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    pending.replace(args.receipt)
    print(json.dumps({"status": receipt["status"], "remote_archive": target, "bytes": transferred}), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"status": "upload_failed", "error_type": type(error).__name__,
                          "error_message": colab_client.redact_text(str(error))}), file=sys.stderr)
        raise SystemExit(2)
