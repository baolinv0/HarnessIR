from pathlib import Path

import pytest

from hre.models import HREError, file_sha256
from hre.storage import read_json, write_json


def artifact(root, name, content=b'image'):
    root.mkdir(parents=True, exist_ok=True)
    path = root / (name + '.png')
    path.write_bytes(content)
    return {'candidate_id': name, 'status': 'completed', 'sha256': file_sha256(path),
            'delivered_image': str(path)}


def paired_case(root, acceptable_a=True, acceptable_b=False):
    a = [artifact(root, 'a' + str(i), bytes([i])) for i in range(4)]
    b = [a[0]] + [artifact(root, 'b' + str(i), bytes([i + 4])) for i in range(1, 4)]
    write_json(root / 'f0.json', {'task': {'case_id': root.name}, 'config': {'mode': 'real', 'experiment': {'e1_ab': True}}})
    write_json(root / 'artifacts.json', {'A': a, 'B': b})
    for prefix, candidates in [(root, b), (root / 'pools' / 'A', a)]:
        write_json(prefix / 'evidence' / 'bundle.json', {'candidates': [
            {'candidate_id': item['candidate_id'], 'hard_gate': 'passed'} for item in candidates]})
    write_json(root / 'selection.json', {'best_candidate': 'b1', 'eligible_ids': ['b1']})
    write_json(root / 'pools' / 'A' / 'judge' / 'J1' / 'selection.json', {'best_candidate': 'a1', 'eligible_ids': ['a1']})
    by_id = {x['candidate_id']: x for x in a + b}
    labels = [{'candidate_id': cid, 'candidate_hash': value['sha256'],
               'acceptable': (cid == 'a1' and acceptable_a) or (cid == 'b1' and acceptable_b)}
              for cid, value in by_id.items()]
    write_json(root / 'offline' / 'oracle_labels.json', {'labels': labels, 'best_sets': {
        'A': ['a1'] if acceptable_a else [], 'B': ['b1'] if acceptable_b else []}})
    return root


def test_paired_analysis_retains_failed_cases_and_bootstraps_cases(tmp_path):
    from hre.candidates.analysis import summarize_cases
    good = paired_case(tmp_path / 'one')
    result = summarize_cases([good, tmp_path / 'missing'], tmp_path / 'report', bootstrap_replicates=100, seed=9)
    assert result['case_count'] == 2
    assert result['pools']['A']['selected_pass']['numerator'] == 1
    assert result['pools']['A']['selected_pass']['denominator'] == 2
    assert result['pools']['B']['false_accept']['value'] == 1
    assert result['paired']['selected_pass']['difference_b_minus_a'] == -0.5
    assert result['paired']['selected_pass']['wins'] == 0
    assert result['paired']['selected_pass']['losses'] == 1
    assert result['paired']['selected_pass']['ties'] == 1
    assert result['paired']['selected_pass']['confidence_interval'] == [-1, 0]
    assert summarize_cases([good, tmp_path / 'missing'], tmp_path / 'repeat', bootstrap_replicates=100, seed=9) == result
    assert (tmp_path / 'report' / 'EXPERIMENT_REPORT.md').is_file()
    assert (tmp_path / 'report' / 'per_case.csv').is_file()
    assert read_json(tmp_path / 'report' / 'summary.json') == result


def test_oracle_and_file_hashes_cannot_be_silently_changed(tmp_path):
    from hre.candidates.analysis import summarize_cases
    root = paired_case(tmp_path / 'one')
    (root / 'a1.png').write_bytes(b'changed')
    with pytest.raises(HREError, match='binding'):
        summarize_cases([root], tmp_path / 'out', bootstrap_replicates=10)


def test_zero_denominators_and_unplanned_pool(tmp_path):
    from hre.candidates.analysis import summarize_cases
    result = summarize_cases([], tmp_path / 'empty', bootstrap_replicates=10)
    assert result['pools']['B']['selected_pass']['value'] is None
    assert result['paired']['oracle_pass_at_4']['confidence_interval'] is None
    root = paired_case(tmp_path / 'one')
    value = read_json(root / 'f0.json')
    value['config']['experiment']['e1_ab'] = False
    write_json(root / 'f0.json', value)
    with pytest.raises(HREError, match='study_scope'):
        summarize_cases([root], tmp_path / 'bad', bootstrap_replicates=10)


def e2_registration(tmp_path):
    root = tmp_path / 'one'
    records = []
    for slot, axis, strategy in [('C0', None, 'baseline'), ('CF', 'person', 'face_alt'),
                                 ('CT', 'text', 'text_alt'), ('CFT', 'joint', 'joint_alt')]:
        records.append({'seed': 10, 'slot_id': slot, 'evaluation_axis_id': axis,
                        'effective_strategy_id': strategy,
                        'artifact': artifact(root, slot, slot.encode())})
    write_json(root / 'e2' / 'results.json', {'case_id': 'one', 'records': records})
    targets = {'person': [{'region_id': 'face', 'attribute_id': 'texture'}],
               'text': [{'region_id': 'sign', 'attribute_id': 'strokes'}],
               'non_target_rois': {'person': [{'region_id': 'sign', 'attribute_id': 'strokes'}],
                                   'text': [{'region_id': 'face', 'attribute_id': 'texture'}], 'joint': []}}
    registration = {'case_ids': ['one', 'missing'], 'evaluation_seeds': [10, 11],
                    'cases': [{'case_id': 'one', 'case_root': str(root), 'evaluation_targets': targets},
                              {'case_id': 'missing', 'case_root': str(tmp_path / 'missing'), 'evaluation_targets': targets}]}
    rows = []
    base = records[0]['artifact']['sha256']
    for record in records[1:]:
        for region, attribute in [('face', 'texture'), ('sign', 'strokes')]:
            targeted = record['evaluation_axis_id'] == 'joint' or (record['evaluation_axis_id'] == 'person' and region == 'face') or (record['evaluation_axis_id'] == 'text' and region == 'sign')
            rows.append({'case_id': 'one', 'seed': 10, 'slot_id': record['slot_id'],
                         'evaluation_axis_id': record['evaluation_axis_id'],
                         'effective_strategy_id': record['effective_strategy_id'],
                         'region_id': region, 'attribute_id': attribute,
                         'pair_hashes': {'baseline_sha256': base, 'candidate_sha256': record['artifact']['sha256']},
                         'quality_change': 'improved' if targeted else 'tied',
                         'material_damage': False, 'content_conflict': False, 'overall_acceptable': True})
    return registration, rows


def test_effects_keep_missing_seed_and_case_in_intent_to_treat(tmp_path):
    from hre.candidates.analysis import summarize_effects
    registration, rows = e2_registration(tmp_path)
    result = summarize_effects(registration, rows, tmp_path / 'effects')
    cf = result['slots']['CF:person']
    assert cf['target_improvement']['value'] == 0.25
    assert cf['target_improvement']['denominator'] == 4
    assert cf['off_target_regression']['denominator'] == 1
    assert cf['off_target_regression']['missing_count'] == 3
    assert result['slots']['CFT:joint']['joint_success']['value'] == 0.25
    assert result['joint_compatibility']['denominator'] == 1
    assert result['joint_compatibility']['value'] == 1


def test_effect_annotations_must_bind_the_actual_pair(tmp_path):
    from hre.candidates.analysis import summarize_effects
    registration, rows = e2_registration(tmp_path)
    rows[0]['pair_hashes']['candidate_sha256'] = '0' * 64
    with pytest.raises(HREError, match='binding'):
        summarize_effects(registration, rows, tmp_path / 'effects')


def test_duplicate_effect_row_and_posthoc_slot_relabel_are_rejected(tmp_path):
    from hre.candidates.analysis import summarize_effects
    registration, rows = e2_registration(tmp_path)
    with pytest.raises(HREError, match='duplicate'):
        summarize_effects(registration, rows + [rows[0]], tmp_path / 'dup')
    rows[0]['evaluation_axis_id'] = 'text'
    with pytest.raises(HREError, match='binding'):
        summarize_effects(registration, rows, tmp_path / 'wrong_axis')


def test_known_generation_failure_needs_no_impossible_null_hash_label(tmp_path):
    from hre.candidates.analysis import summarize_cases
    root = paired_case(tmp_path / 'one')
    pools = read_json(root / 'artifacts.json')
    pools['A'][3] = {'candidate_id': 'a3', 'status': 'failed', 'delivered_image': None, 'sha256': None}
    write_json(root / 'artifacts.json', pools)
    labels = read_json(root / 'offline' / 'oracle_labels.json')
    labels['labels'] = [x for x in labels['labels'] if x['candidate_id'] != 'a3']
    write_json(root / 'offline' / 'oracle_labels.json', labels)
    result = summarize_cases([root], tmp_path / 'out', bootstrap_replicates=10)
    assert result['pools']['A']['oracle_complete_cases'] == 1
    assert result['pools']['A']['produced_coverage']['value'] == 0.75


def test_incomplete_oracle_does_not_invent_false_accept_labels(tmp_path):
    from hre.candidates.analysis import summarize_cases
    root = paired_case(tmp_path / 'one', acceptable_b=True)
    labels = read_json(root / 'offline' / 'oracle_labels.json')
    labels['labels'] = [x for x in labels['labels'] if x['candidate_id'] != 'b3']
    write_json(root / 'offline' / 'oracle_labels.json', labels)
    result = summarize_cases([root], tmp_path / 'out', bootstrap_replicates=10)
    assert result['pools']['B']['selected_pass']['value'] == 0
    assert result['pools']['B']['false_accept']['denominator'] == 0
    assert result['pools']['B']['false_accept']['missing_count'] == 1


def test_single_axis_alternatives_stay_separate_without_posthoc_best(tmp_path):
    from hre.candidates.analysis import summarize_effects
    registration, rows = e2_registration(tmp_path)
    for case in registration['cases']:
        case['slot_axes'] = {'CF': 'person', 'CT': 'person', 'CFT': None}
    root = Path(registration['cases'][0]['case_root'])
    result = read_json(root / 'e2' / 'results.json')
    for record in result['records']:
        if record['slot_id'] == 'CT':
            record.update(evaluation_axis_id='person', effective_strategy_id='face_alt_B')
        if record['slot_id'] == 'CFT':
            record.update(evaluation_axis_id=None, effective_strategy_id='baseline_resample')
    write_json(root / 'e2' / 'results.json', result)
    rows = [row for row in rows if row['slot_id'] != 'CFT']
    for row in rows:
        if row['slot_id'] == 'CT':
            row.update(evaluation_axis_id='person', effective_strategy_id='face_alt_B', quality_change='tied')
    summary = summarize_effects(registration, rows, tmp_path / 'effects')
    assert summary['slots']['CF:person']['target_improvement']['value'] == 0.25
    assert summary['slots']['CT:person']['target_improvement']['value'] == 0
    assert summary['joint_compatibility']['value'] is None


def test_fallback_and_unrated_roi_are_not_counted_as_success(tmp_path):
    from hre.candidates.analysis import summarize_effects
    registration, rows = e2_registration(tmp_path)
    root = Path(registration['cases'][0]['case_root'])
    result = read_json(root / 'e2' / 'results.json')
    for record in result['records']:
        if record['slot_id'] == 'CF':
            record['effective_strategy_id'] = 'baseline_resample'
    write_json(root / 'e2' / 'results.json', result)
    for row in rows:
        if row['slot_id'] == 'CF':
            row['effective_strategy_id'] = 'baseline_resample'
        if row['slot_id'] == 'CT' and row['region_id'] == 'sign':
            row['quality_change'] = 'undetermined'
    summary = summarize_effects(registration, rows, tmp_path / 'effects')
    assert summary['slots']['CF:person']['target_improvement']['value'] == 0
    assert summary['slots']['CT:text']['target_improvement']['value'] == 0
    assert summary['slots']['CT:text']['target_improvement']['missing_count'] == 4
    assert summary['joint_compatibility']['denominator'] == 0


def test_null_actual_axes_do_not_remove_preregistered_targets(tmp_path):
    from hre.candidates.analysis import summarize_effects
    from hre.candidates.contracts import seal
    registration, _ = e2_registration(tmp_path)
    root = Path(registration['cases'][0]['case_root'])
    results = read_json(root / 'e2' / 'results.json')
    for record in results['records']:
        record['evaluation_axis_id'] = None
        if record['slot_id'] != 'C0':
            record['effective_strategy_id'] = 'baseline_resample'
    write_json(root / 'e2' / 'results.json', results)
    write_json(root / 'plan' / 'plan.json', seal({'candidate_specs': [
        {'slot_id': item['slot_id'], 'evaluation_axis_id': None} for item in results['records']]}))
    summary = summarize_effects(registration, [], tmp_path / 'effects')
    for key in ('CF:person', 'CT:text', 'CFT:joint'):
        assert summary['slots'][key]['target_improvement']['denominator'] == 4
        assert summary['slots'][key]['target_improvement']['numerator'] == 0
    assert summary['joint_compatibility']['registered_joint_pairs'] == 4


@pytest.mark.parametrize('actual_axis', ['building', 'grass', 'other'])
def test_other_actual_axes_retain_registered_denominators(tmp_path, actual_axis):
    from hre.candidates.analysis import summarize_effects
    from hre.candidates.contracts import seal
    registration, _ = e2_registration(tmp_path)
    root = Path(registration['cases'][0]['case_root'])
    results = read_json(root / 'e2' / 'results.json')
    for record in results['records']:
        if record['slot_id'] == 'CF':
            record.update(evaluation_axis_id=actual_axis, effective_strategy_id=actual_axis + '_alt')
    write_json(root / 'e2' / 'results.json', results)
    write_json(root / 'plan' / 'plan.json', seal({'candidate_specs': [
        {'slot_id': item['slot_id'], 'evaluation_axis_id': item['evaluation_axis_id']}
        for item in results['records']]}))
    summary = summarize_effects(registration, [], tmp_path / 'effects')
    assert summary['slots']['CF:person']['target_improvement']['denominator'] == 4
    assert summary['slots']['CF:person']['target_improvement']['numerator'] == 0
    pair = next(item for item in summary['pairs'] if item['case_id'] == 'one' and item['slot_id'] == 'CF' and item['seed'] == 10)
    assert pair['actual_evaluation_axis_id'] == actual_axis
    assert (tmp_path / 'effects' / 'EXPERIMENT_REPORT.md').exists()


def test_other_only_case_retains_output_coverage_without_invented_target_metrics(tmp_path):
    from hre.candidates.analysis import summarize_effects
    registration, _ = e2_registration(tmp_path)
    for case in registration['cases']:
        case['evaluation_targets'] = {'person': [], 'text': []}
    root = Path(registration['cases'][0]['case_root'])
    results = read_json(root / 'e2' / 'results.json')
    for record in results['records']:
        if record['slot_id'] != 'C0':
            record.update(evaluation_axis_id='building', effective_strategy_id='building_alt')
    write_json(root / 'e2' / 'results.json', results)
    summary = summarize_effects(registration, [], tmp_path / 'effects')
    assert summary['slots'] == {}
    assert summary['case_coverage'][0]['produced_outputs'] == 4
    assert summary['case_coverage'][1]['produced_outputs'] == 0
    assert set(summary['case_coverage'][0]['evaluation_applicability'].values()) == {'not_applicable'}
    assert {item['actual_evaluation_axis_id'] for item in summary['observations'] if item['slot_id'] != 'C0'} == {'building'}


@pytest.mark.parametrize('gate', ['failed', 'unknown', None])
def test_oracle_quality_cannot_override_actual_hard_contract(tmp_path, gate):
    from hre.candidates.analysis import summarize_cases
    root = paired_case(tmp_path / 'one')
    candidates = read_json(root / 'artifacts.json')['A']
    write_json(root / 'pools' / 'A' / 'evidence' / 'bundle.json', {'candidates': [
        {'candidate_id': item['candidate_id'], 'hard_gate': gate} for item in candidates] if gate else []})
    write_json(root / 'pools' / 'A' / 'judge' / 'J1' / 'selection.json', {'best_candidate': None, 'eligible_ids': []})
    labels = read_json(root / 'offline' / 'oracle_labels.json')
    for label in labels['labels']:
        label['contract_valid'] = True
    write_json(root / 'offline' / 'oracle_labels.json', labels)
    result = summarize_cases([root], tmp_path / 'summary', bootstrap_replicates=10)
    assert result['pools']['A']['oracle_pass_at_4']['numerator'] == 0
    assert result['pools']['A']['avoidable_unresolved']['denominator'] == 0
    assert result['pools']['A']['false_reject']['denominator'] == 0


@pytest.mark.parametrize('candidates', [
    [{'candidate_id': 'other_pool', 'hard_gate': 'passed'}],
    [{'candidate_id': 'a1', 'hard_gate': 'passed'}, {'candidate_id': 'a1', 'hard_gate': 'failed'}],
])
def test_contract_registry_rejects_foreign_or_duplicate_candidates(tmp_path, candidates):
    from hre.candidates.analysis import summarize_cases
    root = paired_case(tmp_path / 'one')
    write_json(root / 'pools' / 'A' / 'evidence' / 'bundle.json', {'candidates': candidates})
    with pytest.raises(HREError, match='evidence_binding_mismatch'):
        summarize_cases([root], tmp_path / 'summary', bootstrap_replicates=10)


def test_quality_best_with_negative_contract_label_is_reported_as_ineligible(tmp_path):
    from hre.candidates.analysis import summarize_cases
    root = paired_case(tmp_path / 'one')
    labels = read_json(root / 'offline' / 'oracle_labels.json')
    for label in labels['labels']:
        if label['candidate_id'] == 'a1':
            label['contract_valid'] = False
    write_json(root / 'offline' / 'oracle_labels.json', labels)
    summary = summarize_cases([root], tmp_path / 'summary', bootstrap_replicates=10)
    assert summary['pools']['A']['oracle_pass_at_4']['numerator'] == 0
    assert summary['pools']['A']['best_in_pool_agreement']['numerator'] == 0
