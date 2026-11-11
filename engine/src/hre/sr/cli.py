"""Explicit SR commands; importing the command tree never loads native models."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..models import HREError
from ..storage import read_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hre sr", description="Frozen x4 SR candidates, paired evidence Judge and dev8/test16 study")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("create", "run", "resume", "show", "report", "reconcile"):
        item = commands.add_parser(name)
        item.add_argument("--case-root", type=Path, required=True)
        if name == "create":
            item.add_argument("--spec", type=Path, required=True)
            item.add_argument("--config", type=Path, required=True)
        if name == "reconcile":
            item.add_argument("--operation", required=True)
            item.add_argument("--note", required=True, help="Explicitly abandon an unknown result without resubmitting")
        if name == "report":
            item.add_argument("--oracle", type=Path, help="Optional hash-bound offline labels; never sent online")
    item = commands.add_parser("preflight")
    item.add_argument("--config", type=Path, required=True)
    studies = commands.add_parser("study").add_subparsers(dest="action", required=True)
    for name in ("create", "run", "freeze", "report"):
        item = studies.add_parser(name)
        item.add_argument("--root", type=Path, required=True)
        if name == "create":
            item.add_argument("--manifest", type=Path, required=True)
            item.add_argument("--config", type=Path, required=True)
        if name == "run":
            item.add_argument("--phase", choices=("dev", "test"), required=True)
        if name == "freeze":
            item.add_argument("--selection", type=Path, required=True)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        from .runtime import create_case, preflight, reconcile_unknown, report, run_case
        if args.command == "study":
            from .study import create_study, freeze_study, run_study, study_report
            if args.action == "create":
                value = create_study(args.root, read_json(args.manifest), read_json(args.config))
            elif args.action == "run":
                value = run_study(args.root, args.phase)
            elif args.action == "freeze":
                value = freeze_study(args.root, read_json(args.selection))
            else:
                value = study_report(args.root)
        elif args.command == "create":
            value = create_case(args.case_root, read_json(args.spec), read_json(args.config))
        elif args.command in {"run", "resume"}:
            value = run_case(args.case_root)
        elif args.command == "preflight":
            value = preflight(read_json(args.config))
        elif args.command == "reconcile":
            value = reconcile_unknown(args.case_root, args.operation, args.note)
        else:
            value = report(args.case_root, read_json(args.oracle) if args.command == "report" and args.oracle else None)
        print(json.dumps(value, ensure_ascii=False, allow_nan=False))
        return 2 if args.command in {"run", "resume", "preflight"} and value.get("status") in {"blocked", "unresolved"} else 0
    except (HREError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"accepted": False, "code": getattr(exc, "code", "sr_input_error"), "message": str(exc)}, ensure_ascii=False))
        return 2
