from copy import deepcopy

from hre.candidates.judge import compile_review_plan, judge_pool, select
from hre.candidates.contracts import parse_config
from hre.candidates.journal import Journal
from hre.models import file_sha256
from hre.storage import read_json
from PIL import Image


def fixture():
    task = {'usage_policy': 'information_critical'}
    bundle = {'source': {'path': 'source.png', 'sha256': 's', 'roi_images': []}, 'candidates': [
        {'candidate_id': 'baseline_s0', 'alias': 'A01', 'image_path': 'a.png', 'image_sha256': 'a', 'hard_gate': 'passed', 'roi_images': []},
        {'candidate_id': 'face_s1', 'alias': 'A02', 'image_path': 'b.png', 'image_sha256': 'b', 'hard_gate': 'passed', 'roi_images': []}],
        'aliases': {'A01': 'baseline_s0', 'A02': 'face_s1'}, 'baseline_id': 'baseline_s0', 'pool_hash': 'pool', 'roi_registry': [],
        'critical_instances': [{'check_id': 'number', 'attribute_id': 'number', 'region_id': 'whole', 'attribute': 'number', 'required_for_acceptance': True, 'verification_requirement': 'verified_content', 'allow_unverifiable': False}]}
    config = {'review': {'max_judge_calls': {'J0': 3, 'J1': 3, 'J2': 7}, 'max_rois_per_package': 6, 'max_images_per_call': 64}, 'tie_order': []}
    plan = compile_review_plan(task, bundle, 'J1', config)
    assessments = []
    for alias in ('A01', 'A02'):
        assessments.append({'candidate_id': alias, 'content_state': 'supported', 'restoration': 'adequate', 'artifact_severity': 'none', 'evidence_refs': ['source_full', alias+'_full'], 'attribute_assessments': [{'attribute_id': 'number', 'region_id': 'whole', 'coverage': 'complete', 'content_state': 'supported', 'evidence_refs': ['source_full', alias+'_full']}]})
    reviews = [{'package_id': 'J1_primary_0', 'assessments': assessments, 'preference_groups': [['A01', 'A02']]}]
    return task, bundle, plan, reviews


def test_verified_content_unknown_never_eligible():
    task, bundle, plan, reviews = fixture()
    for a in reviews[0]['assessments']:
        a['attribute_assessments'][0]['content_state'] = 'unverifiable'
    result = select(task, bundle, plan, reviews)
    assert result['best_candidate'] is None
    assert result['status'] == 'unresolved'


def test_missing_attribute_and_wrong_candidate_evidence_do_not_pass():
    task, bundle, plan, reviews = fixture()
    reviews[0]['assessments'][0]['attribute_assessments'] = []
    reviews[0]['assessments'][1]['attribute_assessments'][0]['evidence_refs'] = ['source_full', 'A01_full']
    assert select(task, bundle, plan, reviews)['eligible_ids'] == []


def test_baseline_wins_valid_tie_and_uncertain_summary_cannot_override():
    task, bundle, plan, reviews = fixture()
    assert select(task, bundle, plan, reviews)['best_candidate'] == bundle['baseline_id']
    reviews[0]['assessments'][0]['restoration'] = 'uncertain'
    assert select(task, bundle, plan, reviews)['best_candidate'] == 'face_s1'


def test_required_packages_must_all_be_present():
    task, bundle, plan, reviews = fixture()
    assert select(task, bundle, plan, [])['best_candidate'] is None


def test_aggregate_verdict_is_required_for_eligibility():
    task, bundle, _, base = fixture()
    plan = compile_review_plan(task, bundle, 'J2', {'review': {}})
    rows = [{**deepcopy(base[0]), 'package_id': package['package_id'], 'kind': 'primary'}
            for package in plan['packages']]
    assert select(task, bundle, plan, rows)['best_candidate'] is None
    assert select(task, bundle, plan, rows)['eligible_ids'] == []
    final = {**deepcopy(base[0]), 'package_id': 'J2_aggregate', 'kind': 'aggregate'}
    for assessment in final['assessments']:
        assessment.update(restoration='insufficient', artifact_severity='major')
    result = select(task, bundle, plan, rows + [final])
    assert result['eligible_ids'] == []
    assert result['best_candidate'] is None
    final['assessments'] = []
    assert select(task, bundle, plan, rows + [final])['eligible_ids'] == []


def test_many_rois_need_explicit_larger_budget():
    task, bundle, _, _ = fixture()
    bundle['roi_registry'] = [{'id': f'r{i}', 'semantic_type': 'person'} for i in range(7)]
    plan = compile_review_plan(task, bundle, 'J1', {'review': {'max_judge_calls': {'J1': 3}, 'max_rois_per_package': 6, 'max_images_per_call': 64}})
    assert plan['status'] == 'unresolved'
    assert plan['reason'] == 'review_budget_insufficient'


def test_missing_required_roi_cannot_vacuously_pass():
    task, bundle, _, reviews = fixture()
    bundle['critical_instances'][0].update(region_id='__missing__', available=False)
    plan = compile_review_plan(task, bundle, 'J1', {'review': {}})
    assert select(task, bundle, plan, reviews)['best_candidate'] is None


def test_fixture_judge_real_journal_replays_and_j2_has_independent_calls(tmp_path):
    task, bundle, _, _ = fixture()
    for index, record in enumerate([bundle['source']] + bundle['candidates']):
        path = tmp_path / f'view{index}.png'
        Image.new('RGB', (32, 32), (index * 40, 50, 70)).save(path)
        if index == 0:
            record.update(path=str(path), sha256=file_sha256(path))
        else:
            record.update(image_path=str(path), image_sha256=file_sha256(path))
    config = parse_config({'mode': 'fixture'})
    journal = Journal(tmp_path / 'case', config['budgets'])
    result = judge_pool(tmp_path / 'case', task, config, bundle, journal, 'J1')
    assert result['best_candidate'] == 'baseline_s0'
    count = len(journal.snapshot()['operations'])
    assert judge_pool(tmp_path / 'case', task, config, bundle, journal, 'J1') == result
    assert len(journal.snapshot()['operations']) == count == 1
    result = judge_pool(tmp_path / 'case', task, config, bundle, journal, 'J2')
    assert result['best_candidate'] == 'baseline_s0'
    operations = list(journal.snapshot()['operations'].values())
    assert sum(op['kind'] == 'judge_J2_primary' for op in operations) == 4
    assert sum(op['kind'] == 'judge_J2_aggregate' for op in operations) == 1
    for operation in operations:
        request = read_json(journal.root / operation['request_path'])
        assert 'baseline_s0' not in request['prompt']
        assert 'face_s1' not in request['prompt']


def test_budget_failure_calls_no_judge(tmp_path):
    task, bundle, _, _ = fixture()
    config = parse_config({'mode': 'fixture', 'budgets': {'judge_J1_total': 0}})
    journal = Journal(tmp_path, config['budgets'])
    result = judge_pool(tmp_path, task, config, bundle, journal, 'J1')
    assert result['reason'] == 'review_budget_insufficient'
    assert journal.snapshot()['operations'] == {}


def test_primary_only_budget_can_complete_without_optional_repair(tmp_path):
    task, bundle, _, _ = fixture()
    config = parse_config({'mode': 'fixture', 'review': {'max_judge_calls': {'J1': 1}}})
    plan = compile_review_plan(task, bundle, 'J1', config)
    assert plan['status'] == 'ready'
    assert plan['budget']['format_repair'] == plan['budget']['dispute'] == 0


def test_expert_role_instructions_are_explicit_in_requests(tmp_path):
    task, bundle, _, _ = fixture()
    for index, record in enumerate([bundle['source']] + bundle['candidates']):
        path = tmp_path / f'role{index}.png'
        Image.new('RGB', (32, 32), (20 * index, 50, 70)).save(path)
        record.update(**({'path': str(path), 'sha256': file_sha256(path)} if index == 0
                         else {'image_path': str(path), 'image_sha256': file_sha256(path)}))
    config = parse_config({'mode': 'fixture'})
    journal = Journal(tmp_path / 'case', config['budgets'])
    judge_pool(journal.root, task, config, bundle, journal, 'J2')
    prompts = [read_json(journal.root / x['request_path'])['prompt'] for x in journal.snapshot()['operations'].values() if x['kind'] == 'judge_J2_primary']
    assert len(prompts) == 4
    for keyword in ('expression', 'strokes', 'background', 'normal viewing'):
        assert any(keyword in prompt for prompt in prompts)


def test_opposing_attribute_assessments_cannot_vote_into_eligibility():
    task, bundle, _, reviews = fixture()
    plan = compile_review_plan(task, bundle, 'J2', {'review': {}})
    rows = []
    for package in plan['packages']:
        review = deepcopy(reviews[0])
        review['package_id'] = package['package_id']
        rows.append(review)
    rows[0]['assessments'][0]['attribute_assessments'][0]['content_state'] = 'conflict'
    assert select(task, bundle, plan, rows)['eligibility_decisions']['baseline_s0'] == 'undetermined'


def test_summary_conflict_cannot_be_overridden_by_supported_attributes():
    task, bundle, plan, reviews = fixture()
    reviews[0]['assessments'][0]['content_state'] = 'conflict'
    assert select(task, bundle, plan, reviews)['best_candidate'] == 'face_s1'


def test_frozen_slot_tie_order_applies_when_baseline_rejected():
    task, bundle, _, reviews = fixture()
    bundle['candidates'][0]['slot_id'] = 'CT'
    bundle['candidates'][1]['slot_id'] = 'CF'
    bundle['baseline_id'] = None
    plan = compile_review_plan(task, bundle, 'J1', {'review': {}, 'tie_order': ['CF', 'CT']})
    assert select(task, bundle, plan, reviews)['best_candidate'] == 'face_s1'
