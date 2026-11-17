"""Public file-based search commands."""
from __future__ import annotations

from pathlib import Path

from ..storage import read_json
from .study import SPLITS


def add_search_parser(groups) -> None:
    group = groups.add_parser("search", help="Iterate on texture-only restoration with human proposals and blind review")
    actions = group.add_subparsers(dest="search_action", required=True)

    def action(name, help_text):
        parser = actions.add_parser(name, help=help_text)
        parser.add_argument("--study", type=Path, required=True)
        return parser

    parser = actions.add_parser("measure", help="Measure a calibration pair in the shared comparison canvas")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--regions", type=Path, help="Optional JSON object with a regions array")

    parser = action("init", "Freeze scenes, texture thresholds, runtime and budgets")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    action("status", "List known proposals and the current version per model")
    parser = action("propose", "Register a versioned JSON proposal")
    parser.add_argument("--proposal", type=Path, required=True)
    for name, help_text in (("run", "Execute or resume a version on one frozen split"),
                            ("review", "Export a blind independent rating packet")):
        parser = action(name, help_text)
        parser.add_argument("--split", choices=SPLITS, required=True)
        parser.add_argument("--profile", required=True)
        parser.add_argument("--candidate", required=True, action="append" if name == "review" else "store")
        if name == "review":
            parser.add_argument("--out", type=Path, required=True)
    parser = action("score", "Validate ratings and compute independent texture metrics")
    parser.add_argument("--ratings", type=Path, required=True)
    parser = action("feedback", "Export reviewed development evidence for VS Code Chat")
    parser.add_argument("--packet", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser = action("promote", "Keep a challenger that passes the independent selection rule")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--packet", required=True)
    parser.add_argument("--reason", required=True)
    parser = action("freeze", "Lock the active versions before any final test runs")
    parser.add_argument("--reason", required=True)


def dispatch_search(args) -> dict:
    from . import review, study

    name = args.search_action
    if name == "measure":
        from .texture import measure
        regions = read_json(args.regions)["regions"] if args.regions else []
        return measure(args.source, args.output, regions)
    root = args.study.resolve()
    if name == "init":
        return study.initialize(root, args.manifest, args.config)
    if name == "propose":
        return study.register(root, read_json(args.proposal))
    if name == "run":
        return study.run(root, args.split, args.profile, args.candidate)
    if name == "review":
        return review.make_review(root, args.split, args.profile, args.candidate, args.out)
    if name == "score":
        return review.score(root, read_json(args.ratings))
    if name == "feedback":
        return review.export_feedback(root, args.packet, args.out)
    if name == "promote":
        return review.promote(root, args.profile, args.candidate, args.packet, args.reason)
    if name == "freeze":
        return study.freeze_final(root, args.reason)
    frozen = study.load_study(root)
    return {"profiles": frozen["profiles"], "active": study.incumbents(root, frozen),
            "candidates": sorted(path.stem for path in (root / "versions").glob("*.json")),
            "test_unlocked": (root / "final.json").is_file()}
