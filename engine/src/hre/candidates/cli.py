import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw

from hre.models import HREError
from hre.storage import read_json, write_json
from .contracts import VERSION, parse_config, require
from .runtime import CandidateCase


def make_fixture(out):
    out = Path(out).resolve()
    require(not out.exists() or not any(out.iterdir()), 'fixture_exists', 'Use a fresh fixture directory')
    out.mkdir(parents=True, exist_ok=True)
    image = Image.new('RGB', (65, 49), (70, 85, 100))
    draw = ImageDraw.Draw(image)
    draw.ellipse((3, 4, 27, 36), fill=(165, 125, 105))
    draw.rectangle((32, 4, 62, 23), fill=(210, 205, 180))
    draw.text((36, 8), '12', fill=(35, 35, 40))
    image.save(out / 'lq.png')
    task = {'schema_version': VERSION, 'case_id': 'cpu_mixed', 'source': {'path': str(out / 'lq.png')},
            'task_mode': 'sr_x4', 'usage_policy': 'photo_restoration',
            'rois': [{'id': 'person_01', 'semantic_type': 'person', 'box': [3, 4, 28, 37], 'provenance': 'synthetic_fixture'},
                     {'id': 'sign_01', 'semantic_type': 'text', 'box': [32, 4, 63, 24], 'provenance': 'synthetic_fixture'}],
            'critical_attributes': [{'attribute_id': 'expression', 'region_selector': 'person_01', 'attribute': 'expression', 'verification_requirement': 'visible_consistency'},
                                    {'attribute_id': 'text_content', 'region_selector': 'sign_01', 'attribute': 'text_content', 'verification_requirement': 'visible_consistency', 'allow_unverifiable': True}]}
    config = {'schema_version': VERSION, 'mode': 'fixture', 'experiment': {'e1_ab': True},
              'fixture': {'baseline_prompt': 'Restore the image. Restore face details gently. Restore visible text strokes. Preserve identity, expression, layout and colors.'}}
    write_json(out / 'task.json', task)
    write_json(out / 'runtime.fixture.json', config)
    case = CandidateCase.create(out / 'case', task, config)
    return {'case_root': str(case.root), 'fixture_only': True, 'next_command': f'python -m hre candidates run --case-root "{case.root}"'}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='hre candidates', description='Independent frozen restoration candidate workflow')
    commands = parser.add_subparsers(dest='command', required=True)
    item = commands.add_parser('fixture', help='Create a synthetic CPU-only software fixture')
    item.add_argument('--out', type=Path, required=True)
    item = commands.add_parser('summarize-offline')
    item.add_argument('--cases', type=Path, nargs='+', required=True)
    item.add_argument('--out', type=Path, required=True)
    item.add_argument('--bootstrap-replicates', type=int, default=10000)
    item.add_argument('--seed', type=int, default=20261117)
    item = commands.add_parser('effects-offline')
    item.add_argument('--registration', type=Path, required=True)
    item.add_argument('--annotations', type=Path, required=True)
    item.add_argument('--out', type=Path, required=True)
    item = commands.add_parser('preflight')
    item.add_argument('--config', type=Path, required=True)
    item = commands.add_parser('create')
    item.add_argument('--case-root', type=Path, required=True)
    item.add_argument('--spec', type=Path, required=True)
    item.add_argument('--config', type=Path, required=True)
    for name in ('run', 'resume', 'report', 'e2'):
        item = commands.add_parser(name)
        item.add_argument('--case-root', type=Path, required=True)
    item = commands.add_parser('judge')
    item.add_argument('--case-root', type=Path, required=True)
    item.add_argument('--variant', choices=('J0', 'J1', 'J2'), required=True)
    item.add_argument('--pool', choices=('A', 'B'), default='B')
    item = commands.add_parser('reconcile')
    item.add_argument('--case-root', type=Path, required=True)
    item.add_argument('--operation-id', required=True)
    item.add_argument('--pool', choices=('A', 'B'), default='B')
    item.add_argument('--resolution', type=Path, required=True)
    item = commands.add_parser('evaluate-offline')
    item.add_argument('--case-root', type=Path, required=True)
    item.add_argument('--labels', type=Path, required=True)
    item.add_argument('--gt', type=Path)
    item = commands.add_parser('preregister')
    item.add_argument('--dataset', type=Path, required=True)
    item.add_argument('--protocol', type=Path, required=True)
    item.add_argument('--split', choices=('pilot', 'held_out'), required=True)
    item.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'fixture':
            result = make_fixture(args.out)
        elif args.command == 'summarize-offline':
            from .analysis import summarize_cases
            result = summarize_cases(args.cases, args.out, args.bootstrap_replicates, args.seed)
        elif args.command == 'effects-offline':
            from .analysis import summarize_effects
            annotation_record = read_json(args.annotations)
            result = summarize_effects(read_json(args.registration), annotation_record['annotations'], args.out)
        elif args.command == 'preflight':
            from .bridge import preflight
            result = preflight(parse_config(read_json(args.config)))
        elif args.command == 'create':
            result = CandidateCase.create(args.case_root, read_json(args.spec), read_json(args.config)).state()
        elif args.command == 'preregister':
            from .study import preregister
            require(not args.out.exists(), 'registration_exists', 'Do not overwrite a frozen registration')
            result = preregister(read_json(args.dataset), read_json(args.protocol), args.split)
            write_json(args.out, result)
        else:
            case = CandidateCase.open(args.case_root)
            if args.command in ('run', 'resume'):
                result = case.run()
            elif args.command == 'judge':
                result = case.judge(args.variant, args.pool)
            elif args.command == 'report':
                result = {'report': str(case.write_report())}
            elif args.command == 'reconcile':
                result = case.reconcile(args.operation_id, read_json(args.resolution), args.pool)
            elif args.command == 'e2':
                result = case.run_e2()
            else:
                from .report import evaluate_offline
                result = evaluate_offline(case.root, read_json(args.labels), args.gt)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False, default=str))
        status = result.get('phase', result.get('status'))
        return 2 if status in {'blocked', 'failed', 'unknown'} or result.get('accepted') is False else 0
    except (HREError, OSError, ValueError, KeyError) as error:
        print(json.dumps({'accepted': False, 'code': getattr(error, 'code', 'input_error'), 'message': str(error)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
