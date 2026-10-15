import argparse
import json
import sys
import time
from pathlib import Path

from filelock import Timeout

from .service import Controller
from .storage import read_json, writer_lock

DEFAULT_ROOT = Path(__file__).resolve().parents[3]


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    arguments = sys.argv[1:] if argv is None else argv
    command_index = 2 if len(arguments) > 2 and arguments[0] == "--root" else 0
    if len(arguments) > command_index and arguments[command_index] in ("tools", "doctor-tools"):
        from .tool_cli import main as tools_main
        return tools_main(arguments)
    parser = argparse.ArgumentParser(description="HarnessIR Manual · ChatGPT 桌面图像编辑文件向导")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    subs = parser.add_subparsers(dest="command", required=True)
    for command in ("new", "inspect", "watch", "import-json", "import-image", "write-response", "evidence", "export", "pause", "resume", "cancel", "submitted", "skip-tool", "variant", "probe", "dispatch"):
        sub = subs.add_parser(command)
        sub.add_argument("--root", type=Path, default=argparse.SUPPRESS)
        if command not in ("new", "watch", "probe"):
            sub.add_argument("--case", required=True)
        if command == "new":
            sub.add_argument("--input", type=Path, required=True)
            sub.add_argument("--intent", required=True)
            sub.add_argument("--max-generations", type=int, default=3)
            sub.add_argument("--evidence-profile", default="cpu_probe_v1")
            sub.add_argument("--manual-tools", action="store_true")
        if command in ("import-json", "import-image", "write-response"):
            sub.add_argument("--task", required=True)
            sub.add_argument("--file", type=Path, required=True)
            sub.add_argument("--model", required=True, help="实际 UI 模型显示名称")
            sub.add_argument("--session")
        if command == "import-image":
            sub.add_argument("--extra", type=Path, action="append", default=[])
        if command == "evidence":
            sub.add_argument("--file", type=Path, required=True)
        if command == "export":
            sub.add_argument("--out", type=Path, required=True)
        if command == "skip-tool":
            sub.add_argument("--tool", required=True)
            sub.add_argument("--reason", required=True)
        if command == "variant":
            sub.add_argument("--intent")
        if command == "watch":
            sub.add_argument("--once", action="store_true")
        if command == "probe":
            sub.add_argument("--response", type=Path)
    args = parser.parse_args(argv)
    ctl = Controller(args.root)
    try:
        cmd = args.command
        if cmd == "new":
            result = ctl.new(args.input, args.intent, {"max_generations": args.max_generations, "evidence_profile_id": args.evidence_profile, "auto_local_tools": not args.manual_tools})
        elif cmd == "inspect":
            state = ctl.inspect(args.case)
            req = ctl.current_task(args.case)
            result = {"state": state.model_dump(), "task": req.model_dump() if req else None, "task_directory": str(ctl.case(args.case).path(f"tasks/{req.task_id}")) if req else None}
        elif cmd in ("import-json", "write-response"):
            raw = args.file.read_text(encoding="utf-8")
            provenance = ctl.provenance(args.model, "file" if cmd == "write-response" else "clipboard_import", "local_work" if cmd == "write-response" else "manual_import", args.session)
            if cmd == "write-response":
                from .transport import import_payload
                from .protocol import strict_loads
                payload = strict_loads(raw)
                if "protocol_version" not in payload and "provenance" not in payload:
                    request = read_json(ctl.case(args.case).path(f"tasks/{args.task}/request.json"))
                    envelope = {k: request[k] for k in ("protocol_version", "task_id", "case_id", "role", "round", "expected_state_revision", "input_sha256")}
                    envelope.update(status="ok", payload=payload, error=None, provenance=provenance)
                    raw = json.dumps(envelope, ensure_ascii=False, allow_nan=False)
                # Role bridge only writes response/done; it never changes state.
                result = import_payload(ctl.case(args.case), args.task, raw, provenance)
            else:
                result = ctl.import_json(args.case, args.task, raw, args.model, provenance)
        elif cmd == "import-image":
            result = ctl.import_image(args.case, args.task, args.file, args.model, extras=args.extra, actual_generations=1 + len(args.extra))
        elif cmd == "evidence":
            result = ctl.register_evidence(args.case, args.file)
        elif cmd == "export":
            result = {"zip": str(ctl.export(args.case, args.out))}
        elif cmd in ("pause", "resume", "cancel", "submitted"):
            result = ctl.operate(args.case, cmd)
        elif cmd == "skip-tool":
            result = ctl.operate(args.case, "skip_tool", args.tool + ":" + args.reason)
        elif cmd == "variant":
            result = ctl.manual_variant(args.case, args.intent)
        elif cmd == "dispatch":
            from .capabilities import dispatch
            result = dispatch(ctl, args.case)
        elif cmd == "probe":
            from .capabilities import prepare_probe, complete_probe
            result = complete_probe(args.root, args.response) if args.response else prepare_probe(args.root)
        else:
            from filelock import FileLock
            with FileLock(str(args.root / ".hir-watcher.lock"), timeout=0):
                while True:
                    results = ctl.scan()
                    for item in results:
                        if item.code != "already_processed":
                            print(item.model_dump_json(), flush=True)
                    if args.once:
                        break
                    time.sleep(1)
            return 0
        if hasattr(result, "model_dump"):
            result = result.model_dump()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if not isinstance(result, dict) or result.get("accepted", True) else 2
    except KeyboardInterrupt:
        return 0
    except (ValueError, OSError, Timeout) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
