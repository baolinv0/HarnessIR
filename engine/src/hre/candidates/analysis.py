"""Explicit offline analysis. No function is imported by online model transports.

summarize_cases receives the complete intended paired A/B case-root list, including
missing runs. Existing f0 records must declare experiment.e1_ab=true. Oracle labels
bind candidate IDs and exact output SHA-256; failed slots need no null-hash label.
best_sets may name independent A and B best sets; legacy best_set applies only B.

summarize_effects receives an E2 registration with case_ids, evaluation_seeds and
cases containing case_id, case_root and evaluation_targets. person/text targets
are lists of {region_id,attribute_id}. non_target_rois optionally maps person,
text and joint to the same shape. slot_axes may freeze nonstandard assignments;
otherwise CF/person, CT/text and CFT/joint are fixed evaluation assignments.
F1 actual interventions never determine applicability. Each annotation identifies
case_id,seed,slot_id,evaluation_axis_id,effective_strategy_id,region_id,attribute_id,
pair_hashes={baseline_sha256,candidate_sha256},quality_change,material_damage,
content_conflict,overall_acceptable. Rows must bind actual e2/results.json output
files and their same-seed C0. Duplicate adjudicated rows are rejected. Metrics
remain separate by slot and axis; observed strategies are listed without taking
an A/B maximum. Missing registered cases and seeds stay in intent-to-treat rates.
"""
from collections import Counter, defaultdict
import csv
import io
from pathlib import Path

import numpy as np

from hre.models import file_sha256
from hre.storage import atomic_write, read_json, write_json
from .contracts import VERSION, digest, require, verify_seal
from .evidence import pool_contract_sets


def _ratio(numerator, denominator, missing=0):
    return {'numerator': numerator, 'denominator': denominator,
            'value': numerator / denominator if denominator else None,
            'missing_count': missing}


def _read_optional(path):
    return read_json(path) if path.is_file() else {}


def _bound_output(root, artifact):
    if artifact.get('status') != 'completed' or not artifact.get('delivered_image'):
        return False
    path = Path(artifact['delivered_image'])
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    require(path.is_relative_to(root.resolve()) and path.is_file()
            and artifact.get('sha256') == file_sha256(path),
            'annotation_binding_mismatch', 'Recorded output bytes or path no longer match the case')
    return True


def _csv(path, rows):
    columns = list(dict.fromkeys(key for row in rows for key in row))
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    atomic_write(path, stream.getvalue().encode('utf-8'))


def _case_row(root):
    root = Path(root).resolve()
    frozen = _read_optional(root / 'f0.json')
    if 'freeze_hash' in frozen:
        verify_seal(frozen)
    if frozen:
        require(frozen.get('config', {}).get('experiment', {}).get('e1_ab') is True,
                'study_scope_invalid', 'Paired A/B summary cannot treat an unplanned A pool as a failed control')
    pools = _read_optional(root / 'artifacts.json')
    oracle = _read_optional(root / 'offline' / 'oracle_labels.json')
    all_artifacts = {}
    produced = set()
    for pool in ('A', 'B'):
        artifacts = pools.get(pool, [])
        require(isinstance(artifacts, list) and len(artifacts) <= 4
                and len({a['candidate_id'] for a in artifacts}) == len(artifacts),
                'pool_invalid', 'A/B pools must contain at most four unique slots')
        for artifact in artifacts:
            cid = artifact['candidate_id']
            if cid in all_artifacts:
                require(all_artifacts[cid] == artifact, 'annotation_binding_mismatch', 'Shared candidate records differ between pools')
            all_artifacts[cid] = artifact
            if _bound_output(root, artifact):
                produced.add(cid)
    labels, quality_acceptable, acceptable = {}, set(), set()
    require(isinstance(oracle.get('labels', []), list) and isinstance(oracle.get('best_sets', {}), dict),
            'oracle_invalid', 'Oracle labels must be a list and best_sets must be an object')
    for item in oracle.get('labels', []):
        require(isinstance(item, dict), 'oracle_invalid', 'Each Oracle label must be an object')
        cid = item.get('candidate_id')
        require(cid in produced and cid not in labels and type(item.get('acceptable')) is bool,
                'oracle_invalid', 'Oracle labels need unique produced candidates and boolean acceptable')
        require(item.get('candidate_hash') == all_artifacts[cid]['sha256'],
                'annotation_binding_mismatch', 'Oracle hash differs from actual candidate output')
        require(type(item.get('contract_valid', True)) is bool, 'oracle_invalid', 'contract_valid must be boolean when supplied')
        labels[cid] = item
        if item['acceptable']:
            quality_acceptable.add(cid)
        if item['acceptable'] and item.get('contract_valid', True):
            acceptable.add(cid)
    result = {'case_id': frozen.get('task', {}).get('case_id', root.name),
              'case_root': str(root), 'fixture_only': frozen.get('config', {}).get('mode') == 'fixture',
              'missing_case': not bool(frozen), 'pools': {}}
    for pool in ('A', 'B'):
        artifacts = pools.get(pool, [])
        ids = {a['candidate_id'] for a in artifacts}
        active = ids & produced
        prefix = root if pool == 'B' else root / 'pools' / 'A'
        contract = pool_contract_sets(_read_optional(prefix / 'evidence' / 'bundle.json'), ids)
        valid = contract['passed'] & active
        checked = contract['passed'] | contract['failed']
        acceptable_ids = ids & acceptable & valid
        selection_path = root / 'selection.json' if pool == 'B' else prefix / 'judge' / 'J1' / 'selection.json'
        selection = _read_optional(selection_path)
        if 'freeze_hash' in selection:
            verify_seal(selection)
        selected = selection.get('best_candidate')
        eligible = set(selection.get('eligible_ids', []))
        require(eligible <= ids and (selected is None or selected in eligible & active),
                'selection_binding_mismatch', 'Formal selection must name an eligible produced pool member')
        complete = len(artifacts) == 4 and active <= labels.keys()
        best_value = oracle.get('best_sets', {}).get(pool, oracle.get('best_set') if pool == 'B' else None)
        require(best_value is None or isinstance(best_value, list), 'oracle_invalid', 'Independent best sets must be lists')
        best = set(best_value or [])
        require(best <= ids & quality_acceptable, 'oracle_invalid', 'Each independent best set must belong to its quality-acceptable pool')
        best_available = bool(best) and best <= acceptable_ids
        result['pools'][pool] = {'produced': len(active), 'contract_valid': len(valid), 'contract_missing': 4 - len(checked),
            'missing_slots': 4 - len(artifacts), 'missing_labels': len(active - labels.keys()),
            'oracle_complete': complete, 'oracle_pass_at_4': int(bool(acceptable_ids)),
            'selected_pass': int(complete and selected in acceptable_ids),
            'conditional_denominator': int(bool(acceptable_ids)),
            'best_agreement': int(complete and best_available and selected in best),
            'best_denominator': int(bool(acceptable_ids) and best_available and complete),
            'best_missing': int(not complete or bool(acceptable_ids) and not best_available),
            'avoidable_unresolved': int(complete and bool(acceptable_ids) and selected is None),
            'false_reject': len(acceptable_ids - eligible) if complete else 0,
            'false_reject_denominator': len(acceptable_ids) if complete else 0,
            'false_accept': int(selected is not None and selected not in acceptable_ids) if complete else 0,
            'false_accept_denominator': int(selected is not None) if complete else 0,
            'eligible_false_accept': len(eligible - acceptable_ids) if complete else 0,
            'eligible_denominator': len(eligible) if complete else 0}
    return result


def summarize_cases(case_roots, output, bootstrap_replicates=10000, seed=20261117):
    require(type(bootstrap_replicates) is int and bootstrap_replicates > 0
            and type(seed) is int and seed >= 0, 'statistics_invalid', 'Use positive replicate count and nonnegative seed')
    roots = [Path(root).resolve() for root in case_roots]
    require(len(set(roots)) == len(roots), 'duplicate_case', 'Registered case roots must be unique')
    rows = [_case_row(root) for root in roots]
    require(len({r['case_id'] for r in rows}) == len(rows), 'duplicate_case', 'Case IDs must be unique')
    count = len(rows)
    result = {'schema_version': VERSION, 'case_count': count,
              'missing_case_count': sum(r['missing_case'] for r in rows),
              'fixture_case_count': sum(r['fixture_only'] for r in rows),
              'statistics': {'resampling_unit': 'case_id', 'bootstrap_replicates': bootstrap_replicates, 'seed': seed},
              'pools': {}, 'paired': {}, 'cases': rows}
    for pool in ('A', 'B'):
        values = [r['pools'][pool] for r in rows]
        sums = Counter()
        for item in values:
            sums.update({k: v for k, v in item.items() if type(v) in {int, bool}})
        missing = count - sums['oracle_complete']
        result['pools'][pool] = {
            'produced_coverage': _ratio(sums['produced'], 4 * count, sums['missing_slots']),
            'contract_valid_coverage': _ratio(sums['contract_valid'], 4 * count, sums['contract_missing']),
            'oracle_pass_at_4': _ratio(sums['oracle_pass_at_4'], count, missing),
            'selected_pass': _ratio(sums['selected_pass'], count, missing),
            'conditional_selection_success': _ratio(sums['selected_pass'], sums['conditional_denominator'], missing),
            'best_in_pool_agreement': _ratio(sums['best_agreement'], sums['best_denominator'], sums['best_missing']),
            'avoidable_unresolved': _ratio(sums['avoidable_unresolved'], sums['conditional_denominator'], missing),
            'false_reject': _ratio(sums['false_reject'], sums['false_reject_denominator'], missing),
            'false_accept': _ratio(sums['false_accept'], sums['false_accept_denominator'], missing),
            'eligible_false_accept': _ratio(sums['eligible_false_accept'], sums['eligible_denominator'], missing),
            'oracle_complete_cases': sums['oracle_complete']}
    random = np.random.default_rng(seed)
    for metric in ('oracle_pass_at_4', 'selected_pass'):
        differences = np.asarray([r['pools']['B'][metric] - r['pools']['A'][metric] for r in rows], dtype=float)
        interval = None
        if count:
            samples = np.empty(bootstrap_replicates)
            for start in range(0, bootstrap_replicates, 1000):
                stop = min(start + 1000, bootstrap_replicates)
                samples[start:stop] = differences[random.integers(0, count, size=(stop - start, count))].mean(axis=1)
            interval = np.quantile(samples, [0.025, 0.975]).tolist()
        result['paired'][metric] = {'difference_b_minus_a': float(differences.mean()) if count else None,
            'confidence_interval': interval, 'wins': int((differences > 0).sum()),
            'ties': int((differences == 0).sum()), 'losses': int((differences < 0).sum()), 'denominator': count}
    output = Path(output)
    write_json(output / 'summary.json', result)
    _csv(output / 'per_case.csv', [{'case_id': row['case_id'], 'pool': pool, **values}
                                 for row in rows for pool, values in row['pools'].items()])
    lines = ['# Experiment report', '', '## Configuration', '',
             f'{count} registered paired cases. Bootstrap resamples whole cases with seed {seed}.', '',
             '## Data', '', f"Missing case records: {result['missing_case_count']}. Fixture cases: {result['fixture_case_count']}.", '',
             '## Coverage', '', 'Counts and denominators are in summary.json and per_case.csv. Missing runs remain in the registered case count.', '',
             '## Judge selection', '', '| Pool | Oracle Pass@4 | Selected Pass |', '|---|---|---|']
    for pool in ('A', 'B'):
        values = result['pools'][pool]
        lines.append(f"| {pool} | {values['oracle_pass_at_4']['value']} | {values['selected_pass']['value']} |")
    lines.extend(['', '## Content errors', '', 'Oracle acceptance is independently annotated and bound to exact candidate hashes.', '',
                  '## Prompt effect', '', 'Use summarize_effects with preregistered same-seed observations for strategy effects.', '',
                  '## Cost', '', 'Provider costs are not inferred from image count. Inspect bound operation receipts; unavailable fees remain unknown.', '',
                  '## Failure cases', '', 'Incomplete Oracle cases use conservative non-success for Selected Pass. False reject and accept exclude incomplete Oracle cases and disclose their count.', '',
                  '## Decision', '', 'This report computes evidence; it does not infer deployment approval or verified content from relative preference.', '',
                  '## Next experiment', '', 'Resolve independent annotation gaps and report unobserved information strata before generalizing.', ''])
    atomic_write(output / 'EXPERIMENT_REPORT.md', '\n'.join(lines).encode('utf-8'))
    return result


def _target_pairs(value):
    require(isinstance(value, list), 'target_registry_invalid', 'Target groups must be lists')
    pairs = []
    for item in value:
        require(isinstance(item, dict) and isinstance(item.get('region_id'), str) and item['region_id']
                and isinstance(item.get('attribute_id'), str) and item['attribute_id'], 'target_registry_invalid', 'Targets need region_id and attribute_id')
        pairs.append((item['region_id'], item['attribute_id']))
    require(len(set(pairs)) == len(pairs), 'target_registry_invalid', 'Duplicate target check')
    return pairs


def _case_effect_data(case, seeds, registration_hash):
    root = Path(case['case_root']).resolve()
    payload = _read_optional(root / 'e2' / 'results.json')
    if payload:
        require(payload.get('case_id') == case['case_id'], 'annotation_binding_mismatch', 'E2 result belongs to another registered case')
        if payload.get('registration_hash'):
            require(payload['registration_hash'] == registration_hash, 'annotation_binding_mismatch', 'E2 result uses another preregistration')
    records = {}
    for record in payload.get('records', []):
        key = (record.get('seed'), record.get('slot_id'))
        require(key[0] in seeds and isinstance(key[1], str) and key not in records,
                'e2_record_invalid', 'E2 output has a duplicate or unregistered operation')
        record = dict(record)
        record['produced'] = _bound_output(root, record['artifact'])
        records[key] = record
    axes = dict(case.get('slot_axes', {'CF': 'person', 'CT': 'text', 'CFT': 'joint'}))
    require(all(isinstance(slot, str) and slot != 'C0' and axis in {None, 'person', 'text', 'joint'}
                for slot, axis in axes.items()),
            'target_registry_invalid', 'Registered evaluation slots must map to person, text, joint or null')
    actual_axes = {}
    plan = _read_optional(root / 'plan' / 'plan.json')
    if plan:
        if 'freeze_hash' in plan:
            verify_seal(plan)
        actual_axes = {s['slot_id']: s.get('evaluation_axis_id') for s in plan.get('candidate_specs', []) if s['slot_id'] != 'C0'}
    for (_, slot), record in records.items():
        if slot != 'C0':
            actual = record.get('evaluation_axis_id')
            require(actual in {None, 'person', 'text', 'joint', 'building', 'grass', 'other'},
                    'e2_record_invalid', 'Actual E2 axis is not a supported issue domain')
            if not plan and slot not in actual_axes:
                actual_axes[slot] = actual
            require(slot in actual_axes and actual == actual_axes[slot],
                    'annotation_binding_mismatch', 'Actual E2 slot axis differs from its frozen assignment')
    targets = case.get('evaluation_targets', {})
    target_groups = {axis: _target_pairs(targets.get(axis, [])) for axis in ('person', 'text')}
    non_targets = targets.get('non_target_rois', {})
    require(isinstance(non_targets, dict), 'target_registry_invalid', 'non_target_rois must map evaluation axes to checks')
    return {'case': case, 'records': records, 'axes': axes, 'actual_axes': actual_axes, 'targets': target_groups,
            'non_targets': {axis: _target_pairs(non_targets.get(axis, target_groups['text' if axis == 'person' else 'person'] if axis != 'joint' else []))
                            for axis in ('person', 'text', 'joint')}}


def summarize_effects(registration, annotations, output):
    if 'freeze_hash' in registration:
        verify_seal(registration)
    ids, seeds = registration.get('case_ids'), registration.get('evaluation_seeds')
    cases = registration.get('cases', [])
    require(isinstance(ids, list) and all(isinstance(cid, str) and cid for cid in ids)
            and len(set(ids)) == len(ids) and isinstance(seeds, list)
            and len(seeds) == 2 and len(set(seeds)) == 2 and all(type(s) is int for s in seeds),
            'registration_invalid', 'Use unique registered case IDs and exactly two evaluation seeds')
    require(isinstance(cases, list) and len({c['case_id'] for c in cases}) == len(cases)
            and {c['case_id'] for c in cases} == set(ids), 'registration_invalid', 'Every registered case needs evaluation targets and case_root metadata')
    require(isinstance(annotations, list), 'annotation_invalid', 'Adjudicated annotations must be a list')
    data = {case['case_id']: _case_effect_data(case, seeds, digest(registration)) for case in cases}
    rows = {}
    overall_by_pair = {}
    for row in annotations:
        require(isinstance(row, dict) and row.get('case_id') in data and row.get('seed') in seeds,
                'annotation_invalid', 'Annotation is outside the preregistered case and seed set')
        cid, seed, slot = row['case_id'], row['seed'], row.get('slot_id')
        case_data = data[cid]
        require(slot in case_data['actual_axes'], 'annotation_binding_mismatch', 'Annotate an intervention slot, not C0 or an unknown slot')
        record, baseline = case_data['records'].get((seed, slot)), case_data['records'].get((seed, 'C0'))
        require(record is not None and baseline is not None and record['produced'] and baseline['produced']
                and row.get('evaluation_axis_id') == record.get('evaluation_axis_id')
                and row.get('effective_strategy_id') == record.get('effective_strategy_id'),
                'annotation_binding_mismatch', 'Annotation slot, axis or strategy does not match produced E2 records')
        pair_hashes = row.get('pair_hashes', {})
        require(pair_hashes == {'baseline_sha256': baseline['artifact']['sha256'], 'candidate_sha256': record['artifact']['sha256']},
                'annotation_binding_mismatch', 'Annotation hashes must match actual same-seed candidate and C0 output')
        require(row.get('quality_change') in {'improved', 'tied', 'worse', 'undetermined'}
                and type(row.get('material_damage')) is bool and type(row.get('content_conflict')) is bool
                and 'overall_acceptable' in row and (row['overall_acceptable'] is None or type(row['overall_acceptable']) is bool),
                'annotation_invalid', 'Annotation requires explicit ordinal quality, damage, conflict and overall acceptance')
        pair_key = (cid, seed, slot)
        if pair_key in overall_by_pair:
            require(overall_by_pair[pair_key] == row['overall_acceptable'], 'annotation_invalid', 'Whole-image acceptance must agree across ROI annotations')
        overall_by_pair[pair_key] = row['overall_acceptable']
        key = (cid, seed, slot, row.get('region_id'), row.get('attribute_id'))
        require(isinstance(key[3], str) and isinstance(key[4], str) and key not in rows,
                'duplicate_annotation', 'Each adjudicated case/seed/slot/region/attribute check must occur once')
        axis = case_data['axes'].get(slot)
        permitted = set(case_data['targets']['person'] + case_data['targets']['text'] + case_data['non_targets'].get(axis, []))
        require((key[3], key[4]) in permitted, 'annotation_invalid', 'Unregistered ROI or attribute cannot enter strategy analysis')
        rows[key] = row
    totals = defaultdict(Counter)
    pair_records = []
    outcomes = {}
    for cid in ids:
        item = data[cid]
        for slot, axis in item['axes'].items():
            if axis is None:
                continue
            targets = item['targets']['person'] + item['targets']['text'] if axis == 'joint' else item['targets'][axis]
            if not targets or axis == 'joint' and not all(item['targets'].values()):
                continue
            group_key = slot + ':' + axis
            for seed in seeds:
                record = item['records'].get((seed, slot))
                baseline = item['records'].get((seed, 'C0'))
                paired = bool(record and baseline and record['produced'] and baseline['produced'])
                actual_axis = record.get('evaluation_axis_id') if record else None
                strategy = record.get('effective_strategy_id') if record else None
                fallback = actual_axis != axis or strategy is None or strategy in {'baseline', 'baseline_resample'}
                target_rows = [rows.get((cid, seed, slot, *target)) for target in targets]
                complete = paired and all(r is not None and r['quality_change'] != 'undetermined' for r in target_rows)
                improved = bool(complete and not fallback and all(r['quality_change'] == 'improved'
                                and not r['material_damage'] and not r['content_conflict'] for r in target_rows))
                protected = item['non_targets'][axis]
                protected_rows = [rows.get((cid, seed, slot, *target)) for target in protected]
                protected_complete = paired and all(r is not None and r['quality_change'] != 'undetermined' for r in protected_rows)
                damage = bool(protected_complete and any(r['material_damage'] or r['content_conflict'] for r in protected_rows))
                overall = complete and all(r['overall_acceptable'] is True for r in target_rows)
                joint_success = bool(axis == 'joint' and improved and overall and protected_complete and not damage)
                summary = totals[group_key]
                summary['planned'] += 1
                summary['target_success'] += improved
                summary['target_missing'] += not complete
                if protected:
                    summary['protected_planned'] += 1
                    summary['protected_complete'] += protected_complete
                    summary['protected_damage'] += damage
                if axis == 'joint':
                    summary['joint_success'] += joint_success
                outcomes[(cid, seed, slot)] = {'axis': axis, 'improved': improved, 'joint_success': joint_success,
                                              'complete': complete, 'fallback': fallback}
                pair_records.append({'case_id': cid, 'seed': seed, 'slot_id': slot, 'evaluation_axis_id': axis,
                                     'actual_evaluation_axis_id': actual_axis,
                                     'effective_strategy_id': strategy, 'target_complete': bool(complete),
                                     'target_improved': improved, 'protected_complete': bool(protected_complete),
                                     'off_target_damage': damage, 'joint_success': joint_success})
    observations = []
    case_coverage = []
    applicable_slots = {(pair['case_id'], pair['slot_id']) for pair in pair_records}
    for cid in ids:
        item = data[cid]
        case_coverage.append({'case_id': cid, 'recorded_outputs': len(item['records']),
                              'produced_outputs': sum(record['produced'] for record in item['records'].values()),
                              'registered_slot_axes': item['axes'], 'actual_slot_axes': item['actual_axes'],
                              'evaluation_applicability': {slot: 'applicable' if (cid, slot) in applicable_slots else 'not_applicable'
                                                           for slot in item['axes']}})
        for (seed, slot), record in item['records'].items():
            observations.append({'case_id': cid, 'seed': seed, 'slot_id': slot,
                                 'actual_evaluation_axis_id': record.get('evaluation_axis_id'),
                                 'effective_strategy_id': record.get('effective_strategy_id'),
                                 'produced': record['produced']})
    result = {'schema_version': VERSION, 'registration_sha256': digest(registration), 'case_count': len(ids),
              'evaluation_seeds': seeds, 'annotation_count': len(rows), 'slots': {}, 'joint_compatibility': None,
              'rule': 'per_slot_axis_intent_to_treat_no_posthoc_max', 'pairs': pair_records,
              'observations': observations, 'case_coverage': case_coverage}
    for key, counts in sorted(totals.items()):
        result['slots'][key] = {'target_improvement': _ratio(counts['target_success'], counts['planned'], counts['target_missing']),
            'off_target_regression': _ratio(counts['protected_damage'], counts['protected_complete'], counts['protected_planned'] - counts['protected_complete']),
            'joint_success': _ratio(counts['joint_success'], counts['planned'], counts['target_missing']) if key.endswith(':joint') else _ratio(0, 0),
            'observed_strategies': dict(Counter(p['effective_strategy_id'] or 'missing' for p in pair_records if p['slot_id'] + ':' + p['evaluation_axis_id'] == key))}
    compatibility_success = compatibility_denominator = joint_planned = 0
    for cid in ids:
        for seed in seeds:
            candidates = {slot: outcome for (case_id, evaluation_seed, slot), outcome in outcomes.items() if case_id == cid and evaluation_seed == seed}
            joint = [x for x in candidates.values() if x['axis'] == 'joint']
            if not joint:
                continue
            joint_planned += len(joint)
            person = [x for x in candidates.values() if x['axis'] == 'person']
            text = [x for x in candidates.values() if x['axis'] == 'text']
            applicable = len(person) == len(text) == len(joint) == 1 and all(x['improved'] and not x['fallback'] for x in person + text)
            if applicable and joint[0]['complete'] and not joint[0]['fallback']:
                compatibility_denominator += 1
                compatibility_success += joint[0]['joint_success']
    result['joint_compatibility'] = {**_ratio(compatibility_success, compatibility_denominator, joint_planned - compatibility_denominator),
                                      'registered_joint_pairs': joint_planned}
    output = Path(output)
    write_json(output / 'strategy_effects.json', result)
    _csv(output / 'strategy_effect.csv', pair_records)
    lines = ['# Strategy effect report', '', f'{len(ids)} preregistered cases, two paired evaluation seeds.', '',
             '| Slot and axis | Target improvement | Joint success | Off-target regression |', '|---|---|---|---|']
    for key, value in result['slots'].items():
        lines.append(f"| {key} | {value['target_improvement']['value']} | {value['joint_success']['value']} | {value['off_target_regression']['value']} |")
    lines.extend(['', 'Intent-to-treat target and joint rates retain missing cases, seeds and fallback outcomes as non-success.',
                  'Off-target regression uses complete protected-ROI comparisons and separately reports unavailable comparisons.',
                  'Joint compatibility is conditional on one independently successful single-axis strategy per axis. Multiple alternatives are not reduced by posthoc best selection.', ''])
    atomic_write(output / 'EXPERIMENT_REPORT.md', '\n'.join(lines).encode('utf-8'))
    return result
