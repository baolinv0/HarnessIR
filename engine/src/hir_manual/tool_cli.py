import argparse
import json
import sys
import uuid
from pathlib import Path
from .service import Controller
from .storage import CasePaths, read_json, write_json, sha256_file, now
from .cases import create_case
from .tool_registry import load_profile, load_registry, check_entry
from .tool_service import ToolService
from .tool_jobs import prepare_job

ROOT = Path(__file__).resolve().parents[3]


def canonical_input(root, source, profile_id):
    store = Path(root) / "runtime/tool_inputs"
    state = create_case(store, Path(source), "Offline tool interface validation; no image restoration generated", {"evidence_profile_id": profile_id, "auto_local_tools": False, "branch_type": "offline_tool_input"})
    return CasePaths(state.case_id, store)


def doctor(root, profile_id, tool_id, source):
    profile, registry = load_profile(profile_id, root), load_registry(root, profile_id)
    entry = registry.tools[tool_id]
    check_entry(entry, require_ready=False)
    case = canonical_input(root, source, profile_id)
    metadata = read_json(case.path("input/metadata.json"))
    job, directory = prepare_job(root, case.path("input/canonical.png"), metadata["original_sha256"], Path(source).stem, tool_id, profile, registry)
    cached, result = ToolService(root)._run_job(job, profile, registry, require_ready=False, force_compute=True)
    if cached:
        manifest = read_json(cached/"evidence.json")
        entry["ready"] = True
        entry["warmup_evidence"] = {"job_id": job.job_id, "cache_key": job.cache_key, "manifest_sha256": sha256_file(cached/"evidence.json"), "validated_at": now(), "result": result}
        registry.registry_status = "partially_ready" if not all(e.get("ready") for e in registry.tools.values()) else "ready"
        write_json(Path(root)/"preprocessing/registry"/f"{profile_id}.json", registry)
    return {"tool": tool_id, "ready": bool(cached), "job_id": job.job_id, "status": job.status, "worker": result, "cache_path": str(cached) if cached else None}


def precompute(root, manifest_file, profile_id, tool_ids):
    profile, registry = load_profile(profile_id, root), load_registry(root, profile_id)
    source = Path(manifest_file)
    rows = read_manifest(source)
    results = []
    service = ToolService(root)
    for row in rows:
        relative = row.get("input_path", row.get("lq", row.get("input")))
        if not relative:
            raise ValueError("Manifest entry has no input path")
        path = Path(relative)
        if not path.is_absolute():
            path = source.parent / path
        case = canonical_input(root, path, profile_id)
        metadata = read_json(case.path("input/metadata.json"))
        for tool in tool_ids:
            check_entry(registry.tools[tool])
            job, directory = prepare_job(root, case.path("input/canonical.png"), metadata["original_sha256"], row.get("sample_id", path.stem), tool, profile, registry)
            cached, result = service._run_job(job, profile, registry)
            record = {"image_id": job.image_id, "tool_id": tool, "status": job.status, "cache_key": job.cache_key, "job_id": job.job_id, "worker": result}
            results.append(record)
            write_json(Path(root)/"runtime/precompute_runs"/(source.stem+"_"+profile_id+".json"), {"formal_eligible": profile.formal_eligible, "results": results})
            if result.get("status") == "resource_wait":
                return {"results": results, "blocked": "resource_wait", "total_images": len(rows)}
    return {"results": results, "total_images": len(rows)}


def read_manifest(source):
    source = Path(source)
    if source.suffix.lower() == ".jsonl":
        from .protocol import strict_loads
        return [strict_loads(line) for line in source.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    from .protocol import strict_loads
    raw = source.read_text(encoding="utf-8-sig").strip()
    data = strict_loads('{"images":' + raw + '}') if raw.startswith("[") else strict_loads(raw)
    rows = data if isinstance(data, list) else data.get("images", data.get("items", []))
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("Manifest must contain a list of image records")
    return rows


def main(argv):
    parser = argparse.ArgumentParser(description="HarnessIR v1.1 isolated local tools")
    parser.add_argument("--root", type=Path, default=ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    doctor_parser = commands.add_parser("doctor-tools")
    doctor_parser.add_argument("--root", type=Path, default=argparse.SUPPRESS)
    doctor_parser.add_argument("--profile", default="cpu_probe_v1")
    doctor_parser.add_argument("--tool", required=True)
    doctor_parser.add_argument("--input", type=Path, required=True)
    tools = commands.add_parser("tools")
    tools.add_argument("--root", type=Path, default=argparse.SUPPRESS)
    actions = tools.add_subparsers(dest="action", required=True)
    run = actions.add_parser("run")
    run.add_argument("--case", required=True)
    for name in ("precompute", "export-missing"):
        command = actions.add_parser(name)
        command.add_argument("--manifest", type=Path, required=True)
        command.add_argument("--profile", default="cpu_probe_v1" if name == "precompute" else "gpu_full_v1")
        command.add_argument("--tool-ids", nargs="+", default=["T2_FACE", "T1_OCR", "T3_DEPTH", "T4_SEGMENTATION"])
        if name == "export-missing":
            command.add_argument("--out", type=Path, required=True)
    command = actions.add_parser("import-cache")
    command.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor-tools":
            result = doctor(args.root, args.profile, args.tool, args.input)
        elif args.action == "run":
            result = ToolService(args.root).run_case(args.case).model_dump()
        elif args.action == "precompute":
            result = precompute(args.root, args.manifest, args.profile, args.tool_ids)
        elif args.action == "export-missing":
            from .bundles import export_missing_jobs
            result = {"bundle": str(export_missing_jobs(args.manifest, load_profile(args.profile,args.root), args.out, args.root, args.tool_ids))}
        else:
            from .bundles import import_cache_bundle
            result = import_cache_bundle(args.bundle, Path(args.root)/"Data/annotations/cache").model_dump()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 3 if (args.command == "doctor-tools" and not result["ready"]) or result.get("blocked") or result.get("rejected") else 0
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
