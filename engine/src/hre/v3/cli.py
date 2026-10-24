"""Public opt-in ``hre models`` commands; legacy CLI semantics stay unchanged."""
from __future__ import annotations

from pathlib import Path

from ..storage import read_json
from .contracts import CATALOG


def add_models_parser(groups):
    group = groups.add_parser("models", help="Four-model v3 restoration/reference enhancement")
    commands = group.add_subparsers(dest="model_action", required=True)
    commands.add_parser("catalog", help="List the four implemented native model adapters")
    parser = commands.add_parser("init", help="Write complete editable runtime/task/batch examples")
    parser.add_argument("--out", type=Path, required=True)
    parser = commands.add_parser("doctor", help="Check local dependencies and weights without inference")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--profile", choices=list(CATALOG), action="append")
    parser = commands.add_parser("lock", help="Hash a locally deployed checkpoint once")
    parser.add_argument("--path", type=Path, required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser = commands.add_parser("create", help="Create an immutable task revision")
    parser.add_argument("--case-root", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    for action in ("run", "resume", "prepare", "show", "dry-run"):
        parser = commands.add_parser(action)
        parser.add_argument("--case-root", type=Path, required=True)
        if action in {"run", "resume", "prepare"}:
            parser.add_argument("--max-steps", type=int)
        if action == "prepare":
            parser.add_argument("--through", choices=["compose", "condition"], default="compose")
    parser = commands.add_parser("reconcile", help="Resolve a confirmed outcome; never guess whether a call ran")
    parser.add_argument("--case-root", type=Path, required=True)
    parser.add_argument("--decision", choices=["confirmed_result", "not_submitted", "consumed_failed", "stop"], required=True)
    parser.add_argument("--result", type=Path)
    parser.add_argument("--evidence", required=True, help="Concrete observation supporting this decision")
    parser.add_argument("--operation-id")
    parser = commands.add_parser("batch", help="Execute or resume a frozen model/arm/seed comparison matrix")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser = commands.add_parser("report", help="Export HTML comparison, CSV and complete JSON records")
    parser.add_argument("--run", type=Path, required=True, help="One v3 case or batch root")
    parser.add_argument("--out", type=Path, required=True)


def dispatch_models(args):
    from .batch import resolve_config_paths, resolve_spec_paths
    action = args.model_action
    if action == "catalog":
        return {"schema_version": "hre_catalog_v3", "models": CATALOG, "gpu_tests": "not_run_in_this_delivery"}
    if action == "init":
        from .deployment import write_examples
        return write_examples(args.out)
    if action == "lock":
        from .deployment import lock_checkpoint
        return lock_checkpoint(args.path, args.model_id, args.revision, args.out)
    if action in {"doctor", "create", "batch"}:
        config_path = args.config.resolve()
        config = resolve_config_paths(read_json(config_path), config_path.parent)
    if action == "doctor":
        from .deployment import doctor
        result = doctor(config, args.profile)
        return {**result, "accepted": result["ready"]}
    if action == "create":
        from .contracts import create_case
        spec_path = args.spec.resolve()
        spec = resolve_spec_paths(read_json(spec_path), spec_path.parent)
        return create_case(args.case_root, spec, config)
    if action == "batch":
        from .batch import run_batch
        result = run_batch(read_json(args.manifest), config, args.out, base=args.manifest.resolve().parent, resume=args.resume)
        return {**result, "accepted": result["status"] == "completed"}
    if action == "report":
        from .report import export_report
        return export_report(args.run, args.out)
    if action in {"show", "dry-run"}:
        from .contracts import load_case
        spec, config, state = load_case(args.case_root)
        if action == "show":
            from .runner_journal import Journal
            return Journal(args.case_root.resolve(), state, read_only=True).state
        model = config["models"][spec["profile_id"]]
        return {"schema_version": "hre_dry_run_v3", "task_mode": spec["task_mode"], "profile_id": spec["profile_id"],
                "strategy": spec["strategy"], "input_roles": [asset["role"] for asset in state["inputs"]],
                "source_canvas": state["canvas"], "geometry": spec["geometry"], "spatial": spec["spatial"],
                "compiler": model["compiler"]["backend"], "pipeline": CATALOG[spec["profile_id"]]["pipeline"],
                "policy": spec["policy"], "model_calls": 0,
                "steps": (["diagnose", "evidence", "compose"] if spec["strategy"] != "native" and not spec.get("shared_intent") else [])
                         + ["prepare_geometry", "compile", "generate", "deliver", "verify"]
                         + (["refine_and_recompile_if_supported"] if spec["policy"]["mode"] == "feedback" else [])}
    if action == "reconcile":
        from .runner import reconcile
        return reconcile(args.case_root, args.decision, result_path=args.result,
                         evidence=args.evidence, operation_id=args.operation_id)
    if action in {"run", "resume", "prepare"}:
        from .runner import run_case
        result = run_case(args.case_root, max_steps=args.max_steps,
                          stop_after=args.through if action == "prepare" else None)
        return {**result, "accepted": result["status"] in {"completed", "ready"}}
    raise ValueError("Unknown models command: " + action)
