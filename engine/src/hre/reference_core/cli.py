"""Installed entry points for independent review and frozen study operations."""
import argparse
import json
from pathlib import Path

from hre.models import HREError
from . import evaluation, study


def _json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _relative(value, key, base):
    if value.get(key) is not None:
        path = Path(value[key]).expanduser()
        value[key] = str(path.resolve() if path.is_absolute() else (base / path).resolve())


def _report(path, text):
    path = path.absolute(); path.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode('utf-8')
    if path.exists():
        if path.read_bytes() != data: raise ValueError('Report snapshot exists; select a new output filename')
    else:
        with path.open('xb') as out: out.write(data)
    return {'path': str(path)}


def main(argv):
    mode, *rest = argv
    parser = argparse.ArgumentParser(prog='hre ' + mode)
    groups = parser.add_subparsers(dest='action', required=True)
    if mode == 'reference-study':
        for action in ('build', 'result', 'rate', 'adjudicate', 'blind', 'report'):
            command = groups.add_parser(action, aliases=['study-' + action])
            command.add_argument('--root', type=Path, required=True)
            if action in ('blind', 'report'): command.add_argument('--out', type=Path, required=True)
            else: command.add_argument('--spec', type=Path, required=True)
            if action == 'rate':
                command.add_argument('--blind-root', type=Path)
                command.add_argument('--packet-id')
    else:
        command = groups.add_parser('import'); command.add_argument('--root', type=Path, required=True); command.add_argument('--spec', type=Path, required=True)
        command = groups.add_parser('resolve'); command.add_argument('--root',type=Path,required=True);command.add_argument('--spec',type=Path,required=True)
        command = groups.add_parser('report'); command.add_argument('--root', type=Path, required=True); command.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(rest)
    try:
        action = args.action.removeprefix('study-')
        if mode == 'reference-evaluate':
            if action == 'report': value = _report(args.out, evaluation.render_report(args.root))
            else:
                spec = _json(args.spec)
                for item in spec.get('images', []): _relative(item, 'path', args.spec.resolve().parent)
                for metric in spec.get('metrics', []): _relative(metric, 'evidence_path', args.spec.resolve().parent)
                value = evaluation.append_resolution(args.root,spec) if action=='resolve' else evaluation.append_review(args.root, spec)
        elif action == 'report': value = _report(args.out, study.render_report(args.root))
        elif action == 'blind': value = study.prepare_blind(args.root, args.out)
        else:
            spec = _json(args.spec); base = args.spec.resolve().parent
            if action == 'build':
                _relative(spec, 'runtime_config_path', base)
                for pair in spec.get('pairs', []):
                    for key in ('source', 'reference'): _relative(pair, key, base)
                value = study.build_study(args.root, spec)
            elif action == 'result':
                _relative(spec, 'candidate_path', base); value = study.import_result(args.root, spec)
            elif action == 'rate':
                if bool(args.blind_root) != bool(args.packet_id): raise ValueError('Supply both --blind-root and --packet-id')
                value = study.import_blind_rating(args.root, args.blind_root, args.packet_id, spec) if args.blind_root else study.import_rating(args.root, spec)
            else: value = study.adjudicate(args.root, spec)
        print(json.dumps(value, ensure_ascii=False, allow_nan=False)); return 0
    except (HREError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'accepted': False, 'code': getattr(exc, 'code', 'input_error'), 'message': str(exc)}, ensure_ascii=False)); return 2
