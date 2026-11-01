"""Frozen plans, real local candidate identities, and explicit missing rows."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pytest
from PIL import Image

from hre.reference_core import study
from hre.reference_core.contracts import DIMENSIONS


def specification(tmp_path):
    a, b = tmp_path / 'a.png', tmp_path / 'b.png'
    Image.new('RGB', (16, 16), (80, 80, 80)).save(a)
    Image.new('RGB', (16, 16), (120, 100, 90)).save(b)
    config = tmp_path / 'runtime.json'; config.write_text('{}', encoding='utf-8')
    target = dict(target_id='t1', attribute='neutral_balance', source_observation='Cool gray.',
                  reference_observation='Neutral.', comparability='comparable', uncertainty='',
                  mandatory=True, acceptance_criterion='Match reference neutral rendering without changing A content.')
    coverage = [dict(attribute=attribute, status='targeted' if attribute == 'neutral_balance' else 'preserve',
                     reason='Synthetic protocol fixture.', target_ids=['t1'] if attribute == 'neutral_balance' else [])
                for attribute in sorted(DIMENSIONS)]
    semantics = dict(coverage=coverage, targets=[target], delivery_requirements={})
    evaluation = dict(schema_version='front_camera_evaluation_contract_v2', semantics=semantics,
                      protections=['identity', 'geometry', 'text'],
                      artifact_checks=['naturalness', 'reference_content_leakage', 'unsupported_detail'],
                      review_protocol='Whole-image first, complete regions second, numbers explain only.')
    return dict(schema_version='hre_reference_study_v1', study_id='fixture', runtime_config_path=str(config),
                models=['qwen21'], repeats=1, seed_start=42, delivery_mode='source_native', working_size=None,
                pairs=[dict(pair_id='pair1', source=str(a), reference=str(b), input_domain='camera_rgb', base_model_version=None,
                            brief_ab='B_ONLY_SENTINEL: match B faithfully.', brief_a='Restore A using only visible A evidence.',
                            brief_a_origin='source_only', regions_ab=[], regions_a=[], evaluation=evaluation,
                            baseline=dict(status='needs_edit', targets=[dict(target_id='t1', status='unmet')],
                                          reason='Frozen before outputs.'))])


def result_spec(plan, run, path, role='G'):
    return dict(run_id=run['run_id'], study_hash=plan['content_hash'], outcome_role=role,
                candidate_path=str(path), candidate_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                geometry_valid=True, provenance='Synthetic protocol fixture; no remote call.')


def rating_spec(result, run, rating_id='rating1', reviewer='reviewer1'):
    return dict(rating_id=rating_id, run_id=run['run_id'], result_hash=result['content_hash'],
                evaluation_hash=run['evaluation_hash'], reviewer_id=reviewer, independence='independent',
                exposure='Synthetic fixture only.', targets=[dict(target_id='t1', status='achieved')],
                protections=[dict(item=x, status='pass') for x in ('identity', 'geometry', 'text')],
                artifact_checks=[dict(item=x, status='pass') for x in ('naturalness', 'reference_content_leakage', 'unsupported_detail')],
                overall={key: 'achieved' for key in study.AXES}, relative_to_A='improved', confidence='high')


def test_six_arms_are_runnable_and_a_only_has_no_reference_payload(tmp_path):
    plan = study.build_study(tmp_path / 'study', specification(tmp_path))
    assert {r['arm_id'] for r in plan['payload']['runs']} == set(study.ARMS)
    root = tmp_path / 'study'
    for run in plan['payload']['runs']:
        task = json.loads((root / run['task_path']).read_text(encoding='utf-8'))
        if run['arm_id'] == 'legacy_aware_a':
            assert task['task_mode'] == 'restoration' and 'reference' not in task and 'workflow_contract' not in task
            assert 'B_ONLY_SENTINEL' not in json.dumps(task)
        elif run['arm_id'].startswith('retouch_'):
            assert task['workflow_contract'] == 'reference_retouch_v2'
        assert 'baseline' not in task and 'semantics' not in task.get('evaluation', {})
    assert 'hre models create' in (root / 'RUN_COMMANDS.md').read_text(encoding='utf-8')


def test_unrun_rows_and_unknowns_are_not_dropped_or_counted_as_failures(tmp_path):
    root = tmp_path / 'study'; plan = study.build_study(root, specification(tmp_path))
    summary = study.summarize(root)
    assert len(summary['runs']) == 6 and summary['task_success']['unknown'] == 6
    assert summary['task_success']['false'] == 0
    assert all(row['outcome_role'] == 'P' for row in summary['runs'])
    text = study.render_report(root)
    assert all(run['run_id'] in text for run in plan['payload']['runs'])


def test_accepted_native_too_small_is_delivery_failure(tmp_path):
    root = tmp_path / 'study'; plan = study.build_study(root, specification(tmp_path)); run = plan['payload']['runs'][0]
    path = tmp_path / 'small.png'; Image.new('RGB', (8, 8), 'gray').save(path)
    result = study.import_result(root, result_spec(plan, run, path))
    study.import_rating(root, rating_spec(result, run))
    row = study.summarize(root)['runs'][0]
    assert row['task_success'] is False and row['delivery']['status'] == 'fail'


def test_conflicting_independent_ratings_require_explicit_adjudication(tmp_path):
    root = tmp_path / 'study'; spec = specification(tmp_path); plan = study.build_study(root, spec); run = plan['payload']['runs'][0]
    result = study.import_result(root, result_spec(plan, run, Path(spec['pairs'][0]['reference'])))
    first = study.import_rating(root, rating_spec(result, run))
    second_spec = rating_spec(result, run, 'rating2', 'reviewer2'); second_spec['overall']['color'] = 'unmet'
    second = study.import_rating(root, second_spec)
    assert study.summarize(root)['runs'][0]['task_success'] is None
    adjudication = dict(adjudication_id='a1', run_id=run['run_id'], result_hash=result['content_hash'],
                        rating_hashes=[first['content_hash'], second['content_hash']], selected_rating_hash=second['content_hash'],
                        reason='Explicit fixture adjudication preserves both original ratings.')
    study.adjudicate(root, adjudication)
    assert study.summarize(root)['runs'][0]['task_success'] is False


def test_already_satisfied_is_task_success_but_never_effective_edit(tmp_path):
    root = tmp_path / 'study'; spec = specification(tmp_path)
    spec['pairs'][0]['baseline']['status'] = 'already_satisfied'
    spec['pairs'][0]['baseline']['targets'][0]['status'] = 'achieved'
    plan = study.build_study(root, spec); run = plan['payload']['runs'][0]
    result = study.import_result(root, result_spec(plan, run, Path(spec['pairs'][0]['source']), 'S'))
    rating = rating_spec(result, run); rating['relative_to_A'] = 'same'
    study.import_rating(root, rating)
    row = study.summarize(root)['runs'][0]
    assert row['task_success'] is True and row['effective_edit_success'] is False
    assert row['in_edit_denominator'] is False


def test_fallback_and_bad_identity_never_become_success(tmp_path):
    root = tmp_path / 'study'; spec = specification(tmp_path); plan = study.build_study(root, spec); run = plan['payload']['runs'][0]
    result = study.import_result(root, result_spec(plan, run, Path(spec['pairs'][0]['source']), 'B'))
    study.import_rating(root, rating_spec(result, run))
    assert study.summarize(root)['runs'][0]['task_success'] is False
    changed = result_spec(plan, run, Path(spec['pairs'][0]['reference']))
    with pytest.raises(ValueError): study.import_result(root, changed)


def test_baseline_and_plan_cannot_be_changed_after_results(tmp_path):
    root = tmp_path / 'study'; spec = specification(tmp_path); study.build_study(root, spec)
    spec['pairs'][0]['baseline']['status'] = 'already_satisfied'
    with pytest.raises(ValueError): study.build_study(root, spec)


def test_no_declared_working_size_without_matching_frozen_input(tmp_path):
    spec = specification(tmp_path); spec.update(delivery_mode='declared_working_size', working_size=[8, 8])
    with pytest.raises(ValueError): study.build_study(tmp_path / 'study', spec)


def test_pending_result_can_resolve_by_append_without_overwriting_old_record(tmp_path):
    root = tmp_path / 'study'; spec = specification(tmp_path); plan = study.build_study(root, spec); run = plan['payload']['runs'][0]
    pending = result_spec(plan, run, Path(spec['pairs'][0]['source']), 'P')
    pending.update(candidate_path=None, candidate_sha256=None)
    first = study.import_result(root, pending)
    before = (root / 'results' / (run['run_id'] + '.json')).read_bytes()
    completed = result_spec(plan, run, Path(spec['pairs'][0]['reference']))
    completed['predecessor_hash'] = first['content_hash']
    result = study.import_result(root, completed)
    assert (root / 'results' / (run['run_id'] + '.json')).read_bytes() == before
    study.import_rating(root, rating_spec(result, run))
    assert study.summarize(root)['runs'][0]['outcome_role'] == 'G'


def test_blind_packets_contain_neutral_artifacts_and_no_method_names(tmp_path):
    root = tmp_path / 'study'; spec = specification(tmp_path); plan = study.build_study(root, spec); run = plan['payload']['runs'][0]
    study.import_result(root, result_spec(plan, run, Path(spec['pairs'][0]['reference'])))
    packets = study.prepare_blind(root, tmp_path / 'blind')
    assert len(packets['packets']) == 1
    packet = json.loads(Path(packets['packets'][0]).read_text(encoding='utf-8'))
    text = json.dumps(packet)
    assert 'arm_id' not in text and 'qwen21' not in text and run['run_id'] not in text
    assert {i['role'] for i in packet['images']} == {'A', 'B', 'C'}


def test_neutral_rating_import_uses_bound_private_mapping(tmp_path):
    root = tmp_path / 'study'; spec = specification(tmp_path); plan = study.build_study(root, spec); run = plan['payload']['runs'][0]
    result = study.import_result(root, result_spec(plan, run, Path(spec['pairs'][0]['reference'])))
    study.prepare_blind(root, tmp_path / 'blind')
    rating = rating_spec(result, run)
    for key in ('run_id', 'result_hash', 'evaluation_hash'): del rating[key]
    imported = study.import_blind_rating(root, tmp_path / 'blind', 'packet_0001', rating)
    assert imported['payload']['run_id'] == run['run_id']
