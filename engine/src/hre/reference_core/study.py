"""Frozen six-arm plans and file-bound independent observations.

Runtime tasks never receive common B-derived offline evaluation or ratings.
Records prove local identity, not a remote model call or the truth of a rating.
"""
from copy import deepcopy
import json
from pathlib import Path
import re

from PIL import Image, ImageOps
from hre.models import canonical_json, file_sha256, sha256_bytes
from hre.paths import safe_path
from hre.storage import case_lock
from .contracts import validate_semantics, size
from .delivery import assess_delivery
from .evaluation import AXES
from .native_detail import validate_detail, detail_status, decision_fields as detail_fields

ARMS = ('legacy_native_ab', 'legacy_shared_ab', 'legacy_aware_ab',
        'retouch_shared_ab', 'retouch_aware_ab', 'legacy_aware_a')
ARTIFACTS = ('naturalness', 'reference_content_leakage', 'unsupported_detail')


def _check(ok, message):
    if not ok: raise ValueError(message)


def _exact(value, keys):
    _check(isinstance(value, dict) and set(value) == set(keys), 'Missing or unknown study fields')


def _id(value):
    _check(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', value), 'Invalid study identity')


def _text(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 20000


def _record(payload):
    return dict(content_hash=sha256_bytes(canonical_json(payload)), payload=deepcopy(payload))


def _read(path):
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    _exact(value, ('content_hash', 'payload'))
    _check(value['content_hash'] == sha256_bytes(canonical_json(value['payload'])), 'Study record hash mismatch')
    return value


def _immutable(path, payload):
    value = _record(payload)
    if path.exists():
        _check(_read(path) == value, 'Immutable study identity cannot change')
        return value
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as out: out.write(canonical_json(value))
    return value


def _image(path):
    path = Path(path).absolute()
    _check(path.is_file(), 'Actual frozen image required')
    with Image.open(path) as image:
        _check(image.format in ('PNG', 'JPEG') and image.mode == 'RGB' and getattr(image, 'n_frames', 1) == 1,
               'Study inputs are explicit opaque SDR PNG/JPEG artifacts')
        native = list(image.size); orientation = image.getexif().get(274, 1)
        _check(type(orientation) is int and 1 <= orientation <= 8, 'Invalid image orientation')
        dimensions = list(ImageOps.exif_transpose(image).size)
    return dict(path=str(path), sha256=file_sha256(path), size=dimensions, native_size=native, orientation=orientation)


def _evaluation(value):
    _exact(value, ('schema_version', 'semantics', 'protections', 'artifact_checks', 'review_protocol'))
    _check(value['schema_version'] == 'front_camera_evaluation_contract_v2', 'Unknown common evaluation contract')
    validate_semantics(value['semantics'])
    for key in ('protections', 'artifact_checks'):
        _check(isinstance(value[key], list) and value[key] and all(_text(x) for x in value[key])
               and len(value[key]) == len(set(value[key])), 'Freeze unique protection/artifact IDs')
    _check(set(value['artifact_checks']) == set(ARTIFACTS), 'All artifact checks required')
    _check(_text(value['review_protocol']), 'Freeze actual independent review protocol')


def build_study(root, spec):
    from hre.v3.contracts import CATALOG, normalise_spec
    _exact(spec, ('schema_version', 'study_id', 'runtime_config_path', 'models', 'repeats', 'seed_start',
                  'delivery_mode', 'working_size', 'pairs'))
    _check(spec['schema_version'] == 'hre_reference_study_v1', 'Unknown study version'); _id(spec['study_id'])
    _check(isinstance(spec['models'], list) and spec['models'] and len(set(spec['models'])) == len(spec['models'])
           and set(spec['models']) <= set(CATALOG), 'Use unique implemented models')
    _check(type(spec['repeats']) is int and 1 <= spec['repeats'] <= 100 and type(spec['seed_start']) is int
           and 0 <= spec['seed_start'] < 2**63 - 200, 'Explicit bounded repeat/seed schedule required')
    _check(spec['delivery_mode'] in ('source_native', 'declared_working_size'), 'Unknown delivery mode')
    if spec['delivery_mode'] == 'declared_working_size': size(spec['working_size'])
    else: _check(spec['working_size'] is None, 'Native study has no substituted working size')
    config = Path(spec['runtime_config_path']).absolute()
    _check(config.is_file() and isinstance(json.loads(config.read_text(encoding='utf-8')), dict), 'Supply actual runtime config file')
    _check(isinstance(spec['pairs'], list) and spec['pairs'], 'Study pairs required')
    pairs = []; ids = set(); tasks = {}; runs = []
    for pair in spec['pairs']:
        _exact(pair, ('pair_id', 'source', 'reference', 'input_domain', 'base_model_version', 'brief_ab', 'brief_a',
                      'brief_a_origin', 'regions_ab', 'regions_a', 'evaluation', 'baseline'))
        _id(pair['pair_id']); _check(pair['pair_id'] not in ids, 'Duplicate pair'); ids.add(pair['pair_id'])
        _check(pair['input_domain'] in ('camera_rgb', 'base_model_output'), 'Declare input domain')
        _check(_text(pair['base_model_version']) if pair['input_domain'] == 'base_model_output' else pair['base_model_version'] is None,
               'Base lineage and camera RGB must remain distinct')
        _check(_text(pair['brief_ab']) and _text(pair['brief_a']) and pair['brief_a_origin'] == 'source_only', 'Source-only brief attestation required')
        _check(isinstance(pair['regions_ab'], list) and isinstance(pair['regions_a'], list), 'Separate runtime regions required')
        _check(all(isinstance(r, dict) and 'reference_box' not in r for r in pair['regions_a']), 'A-only regions cannot reference B')
        _evaluation(pair['evaluation'])
        baseline = pair['baseline']; _exact(baseline, ('status', 'targets', 'reason'))
        _check(baseline['status'] in ('already_satisfied', 'needs_edit', 'uncertain') and _text(baseline['reason']), 'Freeze pre-output baseline')
        targets = pair['evaluation']['semantics']['targets']; expected = {t['target_id'] for t in targets}
        _check(isinstance(baseline['targets'], list) and len(baseline['targets']) == len(expected)
               and {t.get('target_id') for t in baseline['targets']} == expected, 'Complete baseline target states required')
        for target in baseline['targets']:
            _exact(target, ('target_id', 'status'))
            _check(target['status'] in ('achieved', 'partial', 'unmet', 'uncertain'), 'Unknown baseline target state')
        mandatory = {t['target_id'] for t in targets if t['mandatory']}
        states = [t['status'] for t in baseline['targets'] if t['target_id'] in mandatory]
        _check(states, 'Study needs explicit mandatory task criteria')
        derived = 'uncertain' if 'uncertain' in states else 'already_satisfied' if all(x == 'achieved' for x in states) else 'needs_edit'
        _check(baseline['status'] == derived, 'Baseline summary contradicts mandatory target states')
        source, reference = _image(pair['source']), _image(pair['reference'])
        if spec['delivery_mode'] == 'declared_working_size':
            _check(source['size'] == spec['working_size'], 'Freeze actual common working A before study creation')
        frozen = dict(deepcopy(pair), source=source, reference=reference)
        evaluation = _record(deepcopy(pair['evaluation'])); frozen['evaluation_hash'] = evaluation['content_hash']
        pairs.append(frozen)
        for model in spec['models']:
            for arm in ARMS:
                for repeat in range(spec['repeats']):
                    run_id = '__'.join((pair['pair_id'], model, arm, str(repeat)))
                    _id(run_id)
                    a_only = arm == 'legacy_aware_a'
                    strategy = 'native' if arm == 'legacy_native_ab' else 'shared' if arm in ('legacy_shared_ab', 'retouch_shared_ab') else 'model_aware'
                    task = dict(schema_version='hre_task_v3', case_id=run_id, profile_id=model,
                                task_mode='restoration' if a_only else 'reference_enhance', strategy=strategy,
                                brief=pair['brief_a'] if a_only else pair['brief_ab'], source={'path': source['path']},
                                regions=deepcopy(pair['regions_a'] if a_only else pair['regions_ab']),
                                policy={'mode': 'single', 'max_generations': 1, 'seed_schedule': [spec['seed_start'] + repeat]})
                    if not a_only: task['reference'] = {'path': reference['path']}
                    if arm.startswith('retouch_'):
                        task.update(workflow_contract='reference_retouch_v2', delivery_requirements=deepcopy(pair['evaluation']['semantics']['delivery_requirements']))
                    task = normalise_spec(task)
                    relative = 'tasks/' + run_id + '.json'; tasks[relative] = task
                    runs.append(dict(run_id=run_id, pair_id=pair['pair_id'], model=model, arm_id=arm, repeat=repeat,
                                     task_path=relative, task_hash=sha256_bytes(canonical_json(task)), evaluation_hash=evaluation['content_hash']))
    payload = dict(schema_version=spec['schema_version'], study_id=spec['study_id'], source_spec=deepcopy(spec),
                   runtime_config={'path': str(config), 'sha256': file_sha256(config)}, pairs=pairs, runs=runs,
                   state='frozen_before_outputs', semantic_truth='caller_attested_inputs_and_pre-output_baseline', quality_experiments='NOT_RUN')
    root = Path(root).absolute(); root.mkdir(parents=True, exist_ok=True)
    with case_lock(root):
        if (root / 'study.json').exists():
            previous = load_study(root); _check(previous == _record(payload), 'Study is frozen; create a new revision'); return previous
        _check(not any(root.iterdir()) or all(p.name == 'case.lock' for p in root.iterdir()), 'Study directory must be new')
        for relative, task in tasks.items():
            path = safe_path(root, relative); path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(canonical_json(task))
        plan = _immutable(root / 'study.json', payload)
        lines = ['# Frozen study run commands', '', 'Configure the actual backend/weights first. No model calls were made by this builder.', '']
        for run in runs:
            task = str(root / run['task_path']); case = str(root / 'runs' / run['run_id'])
            lines += [f'## {run["run_id"]}', '```text',
                      f'python -m hre models create --case-root "{case}" --spec "{task}" --config "{config}"',
                      f'python -m hre models run --case-root "{case}"', '```', '']
        (root / 'RUN_COMMANDS.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
        return plan


def load_study(root):
    root = Path(root); plan = _read(root / 'study.json'); p = plan['payload']
    config = p['runtime_config']; _check(file_sha256(Path(config['path'])) == config['sha256'], 'Frozen runtime config changed')
    for pair in p['pairs']:
        for role in ('source', 'reference'):
            _check(file_sha256(Path(pair[role]['path'])) == pair[role]['sha256'], 'Frozen study input changed')
    for run in p['runs']:
        _check(file_sha256(safe_path(root, run['task_path'], must_exist=True)) == run['task_hash'], 'Frozen runtime task changed')
    return plan


def _run(plan, run_id):
    _id(run_id); matches = [r for r in plan['payload']['runs'] if r['run_id'] == run_id]
    _check(len(matches) == 1, 'Unknown planned run')
    run = matches[0]; pair = next(p for p in plan['payload']['pairs'] if p['pair_id'] == run['pair_id'])
    return run, pair


def import_result(root, spec):
    _exact(spec, ('run_id', 'study_hash', 'outcome_role', 'candidate_path', 'candidate_sha256', 'geometry_valid', 'provenance')
           + (('predecessor_hash',) if 'predecessor_hash' in spec else ()))
    _check(spec['outcome_role'] in ('G', 'S', 'B', 'X', 'P') and type(spec['geometry_valid']) is bool and _text(spec['provenance']), 'Actual outcome/provenance required')
    root = Path(root)
    with case_lock(root):
        plan = load_study(root); run, pair = _run(plan, spec['run_id'])
        _check(spec['study_hash'] == plan['content_hash'], 'Result belongs to another study')
        candidate = None
        if spec['outcome_role'] in ('G', 'S', 'B'):
            candidate = _image(spec['candidate_path'])
            _check(candidate['sha256'] == spec['candidate_sha256'], 'Candidate file hash mismatch')
            if spec['outcome_role'] == 'S': _check(candidate['sha256'] == pair['source']['sha256'], 'No-edit must return frozen A')
        else: _check(spec['candidate_path'] is None and spec['candidate_sha256'] is None, 'Pending/no-output cannot claim a candidate')
        path = safe_path(root, 'results/' + run['run_id'] + '.json')
        if path.exists() and 'predecessor_hash' in spec:
            replay_path = safe_path(root, 'result_updates/' + run['run_id'] + '/' + spec['predecessor_hash'] + '.json')
            if replay_path.exists():
                return _immutable(replay_path, dict(**deepcopy(spec), candidate=candidate,
                                  observation_basis='local_file_bound_caller_attestation_not_remote_model_authentication'))
            previous = _result(root, run['run_id'])
            _check(previous['payload']['outcome_role'] == 'P' and spec['predecessor_hash'] == previous['content_hash'],
                   'Only the current pending result may be resolved by an appended identity')
            path = safe_path(root, 'result_updates/' + run['run_id'] + '/' + previous['content_hash'] + '.json')
        else:
            _check('predecessor_hash' not in spec, 'First result cannot reference a predecessor')
        return _immutable(path, dict(**deepcopy(spec), candidate=candidate,
                          observation_basis='local_file_bound_caller_attestation_not_remote_model_authentication'))


def _result(root, run_id):
    current = _read(safe_path(root, 'results/' + run_id + '.json', must_exist=True))
    visited = set()
    while True:
        _check(current['content_hash'] not in visited, 'Cyclic result resolution'); visited.add(current['content_hash'])
        path = safe_path(root, 'result_updates/' + run_id + '/' + current['content_hash'] + '.json')
        if not path.exists(): return current
        later = _read(path)
        _check(current['payload']['outcome_role'] == 'P' and later['payload']['predecessor_hash'] == current['content_hash']
               and later['payload']['run_id'] == run_id, 'Broken result revision binding')
        current = later


def _checks(rows, expected, identity, statuses):
    _check(isinstance(rows, list) and len(rows) == len(expected) and {r.get(identity) for r in rows if isinstance(r, dict)} == set(expected),
           'Exact independent evaluation coverage required')
    for row in rows:
        _exact(row, (identity, 'status')); _check(row['status'] in statuses, 'Unknown rating state')


def import_rating(root, spec):
    _exact(spec, ('rating_id', 'run_id', 'result_hash', 'evaluation_hash', 'reviewer_id', 'independence', 'exposure',
                  'targets', 'protections', 'artifact_checks', 'overall', 'relative_to_A', 'confidence')
           + (('native_detail',) if 'native_detail' in spec else ()))
    _id(spec['rating_id']); _id(spec['reviewer_id'])
    _check(spec['independence'] in ('independent', 'same_model', 'unknown') and _text(spec['exposure']), 'Review independence/exposure disclosure required')
    _check(spec['relative_to_A'] in ('improved', 'same', 'worse', 'uncertain') and spec['confidence'] in ('high', 'medium', 'low', 'unknown'), 'Explicit improvement/confidence required')
    root = Path(root)
    with case_lock(root):
        plan = load_study(root); run, pair = _run(plan, spec['run_id']); evaluation = pair['evaluation']
        result = _result(root, run['run_id'])
        _check(result['content_hash'] == spec['result_hash'] and result['payload']['candidate'] is not None, 'Bind an actual candidate result')
        _check(spec['evaluation_hash'] == run['evaluation_hash'], 'Wrong common offline evaluation')
        _checks(spec['targets'], [t['target_id'] for t in evaluation['semantics']['targets']], 'target_id', ('achieved', 'partial', 'unmet', 'uncertain'))
        _checks(spec['protections'], evaluation['protections'], 'item', ('pass', 'fail', 'uncertain'))
        _checks(spec['artifact_checks'], evaluation['artifact_checks'], 'item', ('pass', 'fail', 'uncertain'))
        _exact(spec['overall'], AXES)
        _check(all(v in ('achieved', 'partial', 'unmet', 'uncertain') for v in spec['overall'].values()), 'Complete whole-image judgement required')
        if 'native_detail' in spec:
            candidate=result['payload']['candidate']
            validate_detail(spec['native_detail'],dict(source_sha256=pair['source']['sha256'],native_sha256=candidate['sha256'],
                native_size=candidate['native_size'],result_hash=result['content_hash'],evaluation_hash=run['evaluation_hash'],selected_sha256=candidate['sha256']))
        return _immutable(safe_path(root, 'ratings/' + spec['rating_id'] + '.json'), deepcopy(spec))


def adjudicate(root, spec):
    _exact(spec, ('adjudication_id', 'run_id', 'result_hash', 'rating_hashes', 'selected_rating_hash', 'reason'))
    _id(spec['adjudication_id']); _check(_text(spec['reason']), 'Adjudication reason required')
    root = Path(root)
    with case_lock(root):
        plan = load_study(root); run, _ = _run(plan, spec['run_id'])
        ratings = [_read(p) for p in (root / 'ratings').glob('*.json')]
        ratings = [r for r in ratings if r['payload']['run_id'] == run['run_id'] and r['payload']['result_hash'] == spec['result_hash']]
        expected = {r['content_hash'] for r in ratings}
        _check(len(expected) >= 2 and len(spec['rating_hashes']) == len(expected) and set(spec['rating_hashes']) == expected
               and spec['selected_rating_hash'] in expected, 'Bind all conflicting ratings without hiding others')
        directory = root / 'adjudications'
        for p in directory.glob('*.json') if directory.exists() else []:
            _check(_read(p)['payload']['run_id'] != run['run_id'], 'Adjudication frozen; use a new study revision')
        return _immutable(safe_path(root, 'adjudications/' + spec['adjudication_id'] + '.json'), deepcopy(spec))


def _rating_status(rating, pair):
    p = rating['payload']; mandatory = {t['target_id'] for t in pair['evaluation']['semantics']['targets'] if t['mandatory']}
    states = [t['status'] for t in p['targets'] if t['target_id'] in mandatory] + list(p['overall'].values())
    checks = [c['status'] for c in p['protections'] + p['artifact_checks']]
    if any(s in ('partial', 'unmet') for s in states) or 'fail' in checks: return False
    if 'uncertain' in states + checks or p['independence'] != 'independent' or p['confidence'] != 'high': return None
    return True


def _decision_fields(rating):
    """Compare conclusions before boolean collapse; identity/prose is not a vote."""
    p=rating['payload']
    return dict(targets=sorted(p['targets'],key=lambda r:r['target_id']),protections=sorted(p['protections'],key=lambda r:r['item']),
        artifact_checks=sorted(p['artifact_checks'],key=lambda r:r['item']),overall=deepcopy(p['overall']),
        relative_to_A=p['relative_to_A'],confidence=p['confidence'],independence=p['independence'],native_detail=detail_fields(p.get('native_detail')))


def summarize(root):
    root = Path(root); plan = load_study(root)
    ratings = [_read(p) for p in (root / 'ratings').glob('*.json')] if (root / 'ratings').exists() else []
    adjudications = [_read(p) for p in (root / 'adjudications').glob('*.json')] if (root / 'adjudications').exists() else []
    rows = []
    for run in plan['payload']['runs']:
        _, pair = _run(plan, run['run_id']); path = root / 'results' / (run['run_id'] + '.json')
        result = _result(root, run['run_id']) if path.exists() else None; p = None if result is None else result['payload']
        role = 'P' if p is None else p['outcome_role']; success = None; delivery = None; selected = None; adjudication_hash=None
        observations = [] if result is None else [r for r in ratings if r['payload']['run_id'] == run['run_id'] and r['payload']['result_hash'] == result['content_hash']]
        fields=[_decision_fields(r) for r in observations]
        conflict_fields=sorted(key for key in fields[0] if any(f[key]!=fields[0][key] for f in fields[1:])) if fields else []
        if p is not None and p['candidate'] is not None:
            _check(file_sha256(Path(p['candidate']['path'])) == p['candidate']['sha256'], 'Candidate artifact changed')
        if role in ('B', 'X'): success = False
        elif role in ('G', 'S'):
            decisions = [a for a in adjudications if a['payload']['run_id'] == run['run_id']]
            if decisions:
                a = decisions[0]['payload']; _check(a['result_hash'] == result['content_hash'] and set(a['rating_hashes']) == {r['content_hash'] for r in observations}, 'Adjudication became stale')
                selected = next(r for r in observations if r['content_hash'] == a['selected_rating_hash'])
                adjudication_hash=decisions[0]['content_hash']
                success = _rating_status(selected, pair)
            elif observations and not conflict_fields:
                selected=min(observations,key=lambda r:r['content_hash']);success=_rating_status(selected,pair)
        if p is not None and p['candidate'] is not None:
            detail=None if selected is None else selected['payload'].get('native_detail')
            if detail is not None:
                validate_detail(detail,dict(source_sha256=pair['source']['sha256'],native_sha256=p['candidate']['sha256'],native_size=p['candidate']['native_size'],
                    result_hash=result['content_hash'],evaluation_hash=run['evaluation_hash'],selected_sha256=p['candidate']['sha256']))
            delivery = assess_delivery(pair['source']['size'], p['candidate']['size'], pair['evaluation']['semantics']['delivery_requirements'],
                detail=detail_status(detail),geometry_valid=p['geometry_valid'])
            delivery['native_detail_review_id']=None if detail is None else detail['review_id']
        if role in ('G','S'):
            if delivery['status'] == 'fail': success = False
            elif delivery['status'] != 'pass': success = None if success is not False else False
        edit = False if role in ('S', 'B', 'X') or success is False else None if success is None or selected is None else selected['payload']['relative_to_A'] == 'improved' if selected['payload']['relative_to_A'] != 'uncertain' else None
        rows.append(dict(**run, outcome_role=role, task_success=success, effective_edit_success=edit,
                         in_task_denominator=True, in_edit_denominator=pair['baseline']['status'] == 'needs_edit',
                         baseline_status=pair['baseline']['status'], baseline_conflict=bool(role == 'S' and success is True and pair['baseline']['status'] == 'needs_edit'),
                         delivery=delivery, result_hash=None if result is None else result['content_hash'],
                         rating_conflict=bool(conflict_fields),rating_conflict_fields=conflict_fields,
                         selected_rating_hash=None if selected is None else selected['content_hash'],adjudication_hash=adjudication_hash,
                         rating_hashes=[r['content_hash'] for r in observations]))
    def counts(key, denominator):
        included = [r[key] for r in rows if r[denominator]]
        true = sum(v is True for v in included); false = sum(v is False for v in included); unknown = sum(v is None for v in included); total = len(included)
        return dict(true=true, false=false, unknown=unknown, denominator=total,
                    confirmed_fraction=None if not total else true / total, possible_upper_fraction=None if not total else (true + unknown) / total)
    return dict(study_hash=plan['content_hash'], runs=rows, task_success=counts('task_success', 'in_task_denominator'),
                effective_edit_success=counts('effective_edit_success', 'in_edit_denominator'), actual_remote_model_authentication='not_established_by_local_imports')


def render_report(root):
    plan = load_study(root); summary = summarize(root)
    lines = ['# Reference study report', '', 'Frozen plan: ' + plan['content_hash'],
             'Local file-bound observations; unrun rows are unknown. No hidden aggregate or automatic model-quality claim.', '',
             '## Frozen inputs, evaluation and baseline', '```json', json.dumps(plan['payload'], ensure_ascii=False, indent=2), '```',
             '', '## Planned outcomes', '| Run | Role | Task success | Effective edit | Baseline | Delivery |', '|---|---|---|---|---|---|']
    for row in summary['runs']:
        lines.append('| ' + ' | '.join(str(x) for x in (row['run_id'], row['outcome_role'], row['task_success'], row['effective_edit_success'],
                      row['baseline_status'], None if row['delivery'] is None else row['delivery']['status'])) + ' |')
    lines += ['', '## Complete result and denominator records', '```json', json.dumps(summary, ensure_ascii=False, indent=2), '```']
    for group in ('results', 'result_updates', 'ratings', 'adjudications'):
        lines += ['', '## ' + group.title(), '```json', json.dumps([_read(p) for p in sorted((Path(root) / group).rglob('*.json'))]
                  if (Path(root) / group).exists() else [], ensure_ascii=False, indent=2), '```']
    return '\n'.join(lines) + '\n'


def prepare_blind(root, out):
    """Copy actual bytes to neutral packet names; keep the arm map separate."""
    root = Path(root); plan = load_study(root); out = Path(out).absolute()
    _check(not out.exists(), 'Blind packet destination must be new')
    packets = []; mapping = []
    for run in plan['payload']['runs']:
        if not (root / 'results' / (run['run_id'] + '.json')).exists(): continue
        result = _result(root, run['run_id']); candidate = result['payload']['candidate']
        if candidate is None: continue
        _, pair = _run(plan, run['run_id']); neutral = 'packet_' + str(len(packets) + 1).zfill(4)
        images = []
        for role, image in (('A', pair['source']), ('B', pair['reference']), ('C', candidate)):
            data = Path(image['path']).read_bytes()
            _check(sha256_bytes(data) == image['sha256'], 'Blind artifact changed')
            with Image.open(Path(image['path'])) as decoded:
                suffix = '.png' if decoded.format == 'PNG' else '.jpg'
            path = safe_path(out, 'packets/' + neutral + '/' + role + suffix)
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
            images.append(dict(role=role, path=str(path), sha256=image['sha256']))
        packet = dict(packet_id=neutral, images=images, evaluation=deepcopy(pair['evaluation']),
                      native_detail_binding=dict(source_sha256=pair['source']['sha256'],native_sha256=candidate['sha256'],native_size=candidate['native_size'],
                          result_hash=result['content_hash'],evaluation_hash=run['evaluation_hash'],selected_sha256=candidate['sha256']),
                      viewing_protocol='Whole-image first, whole-region second, numbers last. Disclose earlier exposure. No method identities provided.')
        path = safe_path(out, 'packets/' + neutral + '/review.json'); path.write_bytes(canonical_json(packet)); packets.append(str(path))
        mapping.append(dict(packet_id=neutral, run_id=run['run_id'], result_hash=result['content_hash'], evaluation_hash=run['evaluation_hash']))
    out.mkdir(parents=True, exist_ok=True)
    _immutable(out / 'PRIVATE_MAPPING.json', dict(study_hash=plan['content_hash'], items=mapping))
    return dict(packets=packets, private_mapping=str(out / 'PRIVATE_MAPPING.json'), scope='method_labels_blinded_not_new_observer_guarantee')


def import_blind_rating(root, blind_root, packet_id, spec):
    """Resolve neutral IDs after review; never provide the private map to raters."""
    _id(packet_id)
    _check(not any(k in spec for k in ('run_id', 'result_hash', 'evaluation_hash')), 'Blind rating must use only neutral packet identity')
    plan = load_study(root); mapping = _read(Path(blind_root) / 'PRIVATE_MAPPING.json')['payload']
    _check(mapping['study_hash'] == plan['content_hash'], 'Blind mapping belongs to another study')
    matches = [m for m in mapping['items'] if m['packet_id'] == packet_id]
    _check(len(matches) == 1, 'Unknown neutral packet'); item = matches[0]
    packet = json.loads(safe_path(Path(blind_root), 'packets/' + packet_id + '/review.json', must_exist=True).read_text(encoding='utf-8'))
    run, pair = _run(plan, item['run_id']); result = _result(Path(root), run['run_id'])
    _check(result['content_hash'] == item['result_hash'] and item['evaluation_hash'] == run['evaluation_hash'], 'Blind candidate identity became stale')
    expected = {'A': pair['source']['sha256'], 'B': pair['reference']['sha256'], 'C': result['payload']['candidate']['sha256']}
    _check(packet['packet_id'] == packet_id and {i['role']: i['sha256'] for i in packet['images']} == expected
           and _record(packet['evaluation'])['content_hash'] == run['evaluation_hash'], 'Blind packet content changed')
    _check(all(file_sha256(Path(i['path'])) == i['sha256'] for i in packet['images']), 'Blind display artifact changed')
    if 'native_detail' in spec:
        expected_detail=dict(source_sha256=pair['source']['sha256'],native_sha256=result['payload']['candidate']['sha256'],native_size=result['payload']['candidate']['native_size'],
            result_hash=result['content_hash'],evaluation_hash=run['evaluation_hash'],selected_sha256=result['payload']['candidate']['sha256'])
        _check(packet.get('native_detail_binding')==expected_detail,'Blind native-detail binding changed or absent')
        validate_detail(spec['native_detail'],expected_detail)
    return import_rating(root, dict(deepcopy(spec), run_id=run['run_id'], result_hash=item['result_hash'], evaluation_hash=item['evaluation_hash']))
