"""Independent stage runs, reusable inputs and portable comparison reports."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

from . import normalize_stage
from . import core
from .profiles import PROFILES
from .report import export_report


def add_lab_parser(groups):
    lab = groups.add_parser('lab', help='Run and compare independent model stages')
    commands = lab.add_subparsers(dest='lab_command', required=True)

    def command(name, help):
        parser = commands.add_parser(name, help=help)
        parser.add_argument('--root', type=Path, required=True, help='Stage lab directory')
        return parser

    def stage_args(parser, model_flag='--model'):
        parser.add_argument('--case-id', required=True)
        parser.add_argument('--stage', required=True, help='diagnose / plan / compile / execute / judge (or 1–5)')
        if model_flag == '--models':
            parser.add_argument('--models', nargs='+', required=True)
        else:
            parser.add_argument('--model', required=True)
        parser.add_argument('--from-run', nargs='+', action='extend', default=[], help='Saved upstream run IDs')

    def request_args(parser):
        parser.add_argument('--context', type=Path, help='Optional context / action JSON file')
        parser.add_argument('--candidate', type=Path, nargs='+', action='extend', default=[])
        prompt = parser.add_mutually_exclusive_group()
        prompt.add_argument('--prompt', help='Replace the default stage prompt')
        prompt.add_argument('--prompt-file', type=Path)
        parser.add_argument('--profile', choices=list(PROFILES))

    parser = command('init', 'Create a lab with optional model configurations')
    parser.add_argument('--models', type=Path)
    parser = command('models', 'List or update configured models')
    parser.add_argument('--file', type=Path)
    parser = command('add-case', 'Add original image A and appearance reference B')
    parser.add_argument('--prediction', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--case-id')
    parser.add_argument('--task', default='')
    parser.add_argument('--context', type=Path)
    command('cases', 'List cases')
    parser = command('runs', 'List saved stage outputs')
    parser.add_argument('--case-id')
    parser.add_argument('--stage')
    parser = command('run', 'Run models on each selected upstream output')
    stage_args(parser, '--models')
    request_args(parser)
    parser.add_argument('--combine-sources', action='store_true', help='Pass selected outputs together instead of testing each separately')
    parser = command('export', 'Export a request for an external model')
    stage_args(parser)
    request_args(parser)
    parser = command('import', 'Import an external text, JSON or image result')
    stage_args(parser)
    parser.add_argument('--json', dest='json_file', type=Path)
    parser.add_argument('--text-file', type=Path)
    parser.add_argument('--image', type=Path, nargs='+', action='extend', default=[])
    parser = command('report', 'Write a self-contained comparison HTML')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--case-id')
    parser.add_argument('--stage')
    command('demo', 'Run all five stages using labelled synthetic fixtures')
    parser = command('ui', 'Launch the stage comparison interface')
    parser.add_argument('--port', type=int, default=8501)


def _json(path):
    return json.loads(Path(path).read_text(encoding='utf-8')) if path else None


def _models(path):
    value = _json(path)
    return value.get('models', value) if isinstance(value, dict) else value


def _request_args(args):
    return dict(context=_json(args.context), candidates=args.candidate,
                prompt=args.prompt_file.read_text(encoding='utf-8') if args.prompt_file else args.prompt,
                profile=args.profile)


def dispatch_lab(args):
    root = args.root.resolve()
    action = args.lab_command
    if action == 'init':
        return core.init_lab(root, _models(args.models))
    if action == 'models':
        if args.file:
            core.save_models(root, _models(args.file))
        return core.load_lab(root)['models']
    if action == 'add-case':
        return core.add_case(root, args.prediction, args.reference, args.case_id, args.task, _json(args.context))
    if action == 'cases':
        return core.list_cases(root)
    if action == 'runs':
        return core.list_runs(root, args.case_id, args.stage)
    if action == 'run':
        options = _request_args(args)
        # Single input per run makes downstream differences attributable and visible.
        sources = [args.from_run] if args.combine_sources else [[run] for run in args.from_run]
        sources = sources or [[]]
        candidates = options.pop('candidates')
        candidate_groups = [[p] for p in candidates] if candidates and not args.combine_sources else [candidates]
        jobs = [(source, group) for source in sources for group in candidate_groups]
        if normalize_stage(args.stage) == 'judge' and candidates:
            jobs = [(source, []) for source in sources if source]
            jobs += [([], group) for group in candidate_groups]
        rows = []
        for source, group in jobs:
            rows.extend(core.run_stage(root, args.case_id, args.stage, args.models,
                                       source_runs=source, candidates=group, **options))
        return {'accepted': all(row['status'] == 'completed' for row in rows), 'runs': rows,
                'report': str(export_report(root))}
    if action == 'export':
        path = core.export_request(root, args.case_id, args.stage, args.model,
                                   source_runs=args.from_run, **_request_args(args))
        return {'request': str(path), 'bundle_directory': str(path.parent)}
    if action == 'import':
        if not (args.json_file or args.text_file or args.image):
            raise ValueError('Provide --json, --text-file or --image.')
        row = core.import_output(root, args.case_id, args.stage, args.model,
                                 source_runs=args.from_run, data=_json(args.json_file), images=args.image,
                                 text=args.text_file.read_text(encoding='utf-8') if args.text_file else '')
        return {'run': row, 'report': str(export_report(root))}
    if action == 'report':
        return {'report': str(export_report(root, args.out, args.case_id, args.stage))}
    if action == 'demo':
        from .demo import run_demo
        return run_demo(root)
    if action == 'ui':
        path = Path(__file__).with_name('ui.py')
        result = subprocess.run([sys.executable, '-m', 'streamlit', 'run', str(path),
                                 '--server.port', str(args.port), '--', '--root', str(root)])
        return {'accepted': result.returncode == 0, 'returncode': result.returncode}
    raise ValueError(f'Unknown lab command: {action}')
