"""Offline-only CLI. `run` audits inputs and stops; no automatic stage advance."""
import argparse
import json
from pathlib import Path

from hre.models import HREError
from hre.storage import read_json
from . import coordinator


def main(argv=None):
    parser = argparse.ArgumentParser(prog='hre reference-style')
    commands = parser.add_subparsers(dest='command', required=True)
    run = commands.add_parser('run', help='Audit A/B and stop at the S1 gate')
    run.add_argument('--config', type=Path, required=True)
    run.add_argument('--out', type=Path, required=True)
    for name in ('status', 'export', 'import', 'unknown'):
        sub = commands.add_parser(name)
        sub.add_argument('--root', type=Path, required=True)
        if name == 'export':
            sub.add_argument('--stage', choices=('ab_diagnosis', 'edit', 'abc_diagnosis'), required=True)
            sub.add_argument('--context', type=Path, required=True)
            sub.add_argument('--candidate-hash')
        elif name == 'import':
            sub.add_argument('--receipt', type=Path, required=True)
            sub.add_argument('--output', type=Path, required=True)
        elif name == 'unknown':
            sub.add_argument('--attempt-id', required=True)
            sub.add_argument('--reason', required=True)
    for name in ('evidence-import','supports-freeze','measure-ab','ab-export','targets-freeze','targets-compile'):
        sub=commands.add_parser(name)
        sub.add_argument('--root',type=Path,required=True)
        if name=='evidence-import':
            sub.add_argument('--manifest',type=Path,required=True)
            sub.add_argument('--asset',type=Path)
        elif name in ('supports-freeze','targets-freeze'):sub.add_argument('--spec',type=Path,required=True)
        elif name=='measure-ab':sub.add_argument('--snapshot-id',required=True)
        elif name=='ab-export':sub.add_argument('--report-id',required=True)
        else:sub.add_argument('--version',required=True)
    for name in ('edit-export','submission-record','candidate-derive'):
        sub=commands.add_parser(name);sub.add_argument('--root',type=Path,required=True)
        if name=='edit-export':sub.add_argument('--compiled-id',required=True)
        elif name=='submission-record':
            sub.add_argument('--manifest',type=Path,required=True);sub.add_argument('--prompt-file',type=Path,required=True)
        else:
            sub.add_argument('--response-id',required=True);sub.add_argument('--spec',type=Path,required=True)
    s4_specs=('budget-configure','attempt-failed','evaluation-version','candidate-supports','evaluate-candidate','facts-freeze',
              'policy-install','verification-rule-install','adjudication-install','verify-candidate','feedback-freeze','label-select')
    for name in s4_specs+('abc-export','feedback-compile','run-report'):
        sub=commands.add_parser(name);sub.add_argument('--root',type=Path,required=True)
        if name in s4_specs:sub.add_argument('--spec',type=Path,required=True)
        elif name=='abc-export':
            sub.add_argument('--evaluation-id',required=True);sub.add_argument('--view',choices=('image_first','evidence'),required=True)
        elif name=='feedback-compile':
            sub.add_argument('--compiled-id',required=True);sub.add_argument('--feedback-id',required=True)
        else:sub.add_argument('--out',type=Path,required=True)
    for name in ('semantic-freeze','delivery-preflight','complete-no-edit','holistic-import','holistic-resolve','holistic-report','native-detail-request','native-detail-import'):
        sub=commands.add_parser(name);sub.add_argument('--root',type=Path,required=True)
        if name=='holistic-report':sub.add_argument('--candidate-hash',required=True);sub.add_argument('--out',type=Path,required=True)
        elif name=='native-detail-request':sub.add_argument('--evaluation-id',required=True)
        elif name!='complete-no-edit':sub.add_argument('--spec',type=Path,required=True)
    args = parser.parse_args(argv)
    try:
        if args.command in ('semantic-freeze','delivery-preflight','complete-no-edit','holistic-import','holistic-resolve','holistic-report','native-detail-request','native-detail-import'):
            from . import unified
            if args.command=='semantic-freeze':value=unified.freeze_semantics(args.root,read_json(args.spec))
            elif args.command=='delivery-preflight':value=unified.record_preflight(args.root,read_json(args.spec))
            elif args.command=='complete-no-edit':value=unified.complete_no_edit(args.root)
            elif args.command=='holistic-import':value=unified.import_holistic(args.root,read_json(args.spec))
            elif args.command=='holistic-resolve':value=unified.resolve_holistic(args.root,read_json(args.spec))
            elif args.command=='native-detail-request':value=unified.detail_request(args.root,args.evaluation_id)
            elif args.command=='native-detail-import':value=unified.import_detail(args.root,read_json(args.spec))
            else:
                from hre.reference_core.cli import _report
                value=_report(args.out,unified.holistic_report(args.root,args.candidate_hash))
        elif args.command == 'run':
            value = coordinator.create_sample(read_json(args.config), args.out)
        elif args.command == 'status':
            value = coordinator.status(args.root)
        elif args.command == 'export':
            value = coordinator.export_request(args.root, args.stage, read_json(args.context), args.candidate_hash)
        elif args.command == 'import':
            value = coordinator.import_response(args.root, read_json(args.receipt), args.output)
        elif args.command=='unknown':
            value = coordinator.mark_unknown(args.root, args.attempt_id, args.reason)
        elif args.command in ('edit-export','submission-record','candidate-derive'):
            from . import s3_handoff,s3_candidate
            if args.command=='edit-export':value=s3_handoff.export_edit(args.root,args.compiled_id)
            elif args.command=='submission-record':value=s3_handoff.record_submission(args.root,read_json(args.manifest),args.prompt_file)
            else:value=s3_candidate.derive_candidate(args.root,args.response_id,read_json(args.spec))
        elif args.command in s4_specs+('abc-export','feedback-compile','run-report'):
            from . import s4_budget,s4_evaluate,s4_review,s4_verify,s4_feedback
            if args.command=='abc-export':value=s4_review.export_abc(args.root,args.evaluation_id,args.view)
            elif args.command=='feedback-compile':value=s4_feedback.compile_feedback(args.root,args.compiled_id,args.feedback_id)
            elif args.command=='run-report':value=s4_verify.export_report(args.root,args.out)
            else:
                operations={'budget-configure':s4_budget.configure_budget,'attempt-failed':s4_budget.record_failure,'evaluation-version':s4_evaluate.freeze_version,
                    'candidate-supports':s4_evaluate.freeze_supports,'evaluate-candidate':s4_evaluate.evaluate,'facts-freeze':s4_review.freeze_facts,
                    'policy-install':s4_verify.install_policy,'verification-rule-install':s4_verify.install_rule,'adjudication-install':s4_verify.install_adjudication,
                    'verify-candidate':s4_verify.verify,'feedback-freeze':s4_feedback.freeze_feedback,'label-select':s4_verify.select}
                value=operations[args.command](args.root,read_json(args.spec))
        else:
            from . import s2_evidence,s2_measure,s2_stage
            if args.command=='evidence-import':value=s2_evidence.import_evidence(args.root,read_json(args.manifest),args.asset)
            elif args.command=='supports-freeze':value=s2_evidence.freeze_supports(args.root,read_json(args.spec))
            elif args.command=='measure-ab':value=s2_measure.measure_ab(args.root,args.snapshot_id)
            elif args.command=='ab-export':value=s2_stage.export_ab_diagnosis(args.root,args.report_id)
            elif args.command=='targets-freeze':value=s2_stage.freeze_targets(args.root,read_json(args.spec))
            else:value=s2_stage.compile_targets(args.root,args.version)
        print(json.dumps(value, ensure_ascii=False, allow_nan=False))
        return 0
    except (HREError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'accepted': False, 'code': getattr(exc, 'code', 'input_error'), 'message': str(exc)}))
        return 2
