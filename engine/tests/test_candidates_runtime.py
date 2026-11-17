from pathlib import Path

from PIL import Image
import pytest

from hre.models import HREError


def make_case(tmp_path, **config_changes):
    from hre.candidates.runtime import CandidateCase
    image = tmp_path / 'lq.png'
    Image.new('RGB', (33, 25), (80, 110, 130)).save(image)
    task = {'case_id': 'mixed', 'source': str(image), 'task_mode': 'sr_x4',
            'rois': [{'id': 'face01', 'semantic_type': 'person', 'box': [1, 1, 15, 20]},
                     {'id': 'sign01', 'semantic_type': 'text', 'box': [16, 2, 32, 12]}]}
    config = {'mode': 'fixture', **config_changes}
    return CandidateCase.create(tmp_path / 'case', task, config)


def test_cpu_full_workflow_and_resume_make_no_new_calls(tmp_path):
    from hre.candidates.runtime import CandidateCase
    case = make_case(tmp_path)
    state = case.run()
    assert state['phase'] in {'selected', 'baseline_retained'}
    from hre.storage import read_json
    bundle = read_json(case.root / 'evidence' / 'bundle.json')
    assert all(x['hard_gate'] == 'passed' for x in bundle['candidates'])
    selection = case.judge('J0')
    assert selection['best_candidate'] in selection['eligible_ids']
    before = case.journal.snapshot()
    CandidateCase.open(case.root).run()
    assert case.journal.snapshot() == before
    assert Image.open(state['selected_output']).size == (132, 100)
    assert case.write_report().is_file()


def test_frozen_config_mutation_rejected_before_generation(tmp_path):
    from hre.storage import read_json, write_json
    case = make_case(tmp_path)
    frozen = read_json(case.root / 'f0.json')
    frozen['config']['seed_schedule'][0] += 1
    write_json(case.root / 'f0.json', frozen)
    with pytest.raises(HREError, match='freeze_modified'):
        case.run()
    assert not case.journal.snapshot().get('operations')


def test_reopened_case_rejects_resealed_f0_against_original_anchor(tmp_path):
    from hre.candidates.contracts import seal
    from hre.candidates.runtime import CandidateCase
    from hre.storage import read_json, write_json
    case = make_case(tmp_path)
    frozen = read_json(case.root / 'f0.json')
    frozen['config']['seed_schedule'] = [40, 41, 42, 43]
    write_json(case.root / 'f0.json', seal(frozen))
    with pytest.raises(HREError, match='freeze_modified'):
        CandidateCase.open(case.root)
    assert read_json(case.root / 'operations.json')['operations'] == {}


def test_deployment_file_change_after_c0_prevents_alternative_submission(tmp_path, monkeypatch):
    from hre.storage import write_json
    deployment = tmp_path / 'deployment.json'
    write_json(deployment, {'revision': 'initial'})
    case = make_case(tmp_path, editor={'deployment_manifest': str(deployment)})
    execute = case._execute

    def mutate_after_baseline(spec, partition='E1'):
        result = execute(spec, partition)
        if spec['slot_id'] == 'C0':
            write_json(deployment, {'revision': 'changed'})
        return result

    monkeypatch.setattr(case, '_execute', mutate_after_baseline)
    with pytest.raises(HREError, match='external_config_modified'):
        case.run()
    generated = [x for x in case.journal.snapshot()['operations'].values() if x['kind'] == 'image_generation']
    assert len(generated) == 1


def test_e1_ab_has_seven_generation_operations(tmp_path):
    from hre.storage import read_json
    case = make_case(tmp_path, experiment={'e1_ab': True})
    case.run()
    artifacts = read_json(case.root / 'artifacts.json')
    assert len(artifacts['B']) == 4
    assert len(artifacts['A']) == 4
    assert artifacts['A'][0]['candidate_id'] == artifacts['B'][0]['candidate_id']
    assert len({x['candidate_id'] for x in artifacts['A'] + artifacts['B']}) == 7
    all_items = {x['candidate_id']: x for x in artifacts['A'] + artifacts['B']}
    assert all(x.get('pixel_sha256') for x in all_items.values())
    assert sum(bool(x.get('duplicate_of')) for x in all_items.values()) == 6
    for directory in [case.root, case.root / 'pools' / 'A']:
        bundle = read_json(directory / 'evidence' / 'bundle.json')
        assert all(x['hard_gate'] == 'passed' for x in bundle['candidates'])


def test_offline_evaluation_does_not_change_selection(tmp_path):
    from hre.storage import read_json
    from hre.candidates.report import evaluate_offline
    case = make_case(tmp_path)
    case.run()
    selection = read_json(case.root / 'selection.json')
    artifacts = read_json(case.root / 'artifacts.json')['B']
    labels = {'labels': [{'candidate_id': x['candidate_id'], 'candidate_hash': x['sha256'],
                          'acceptable': True} for x in artifacts],
              'best_set': [x['candidate_id'] for x in artifacts]}
    metrics = evaluate_offline(case.root, labels)
    assert metrics['selected_pass']['numerator'] == 1
    assert read_json(case.root / 'selection.json') == selection


def test_failed_slots_need_no_impossible_oracle_hash_label(tmp_path):
    from hre.storage import read_json
    from hre.candidates.report import evaluate_offline
    case = make_case(tmp_path, fixture={'image_behaviors': {'CF': 'failed'}})
    case.run()
    artifacts = read_json(case.root / 'artifacts.json')['B']
    labels = {'labels': [{'candidate_id': x['candidate_id'], 'candidate_hash': x['sha256'], 'acceptable': True}
                         for x in artifacts if x['status'] == 'completed']}
    assert any(x['status'] == 'failed' for x in artifacts)
    assert evaluate_offline(case.root, labels)['oracle_complete'] is True


def test_offline_label_cannot_bind_tampered_image(tmp_path):
    from hre.storage import read_json
    from hre.candidates.report import evaluate_offline
    case = make_case(tmp_path)
    case.run()
    item = read_json(case.root / 'artifacts.json')['B'][0]
    Image.new('RGB', (132, 100), 'red').save(item['delivered_image'])
    with pytest.raises(HREError, match='modified'):
        evaluate_offline(case.root, {'labels': [{'candidate_id': item['candidate_id'], 'candidate_hash': item['sha256'], 'acceptable': True}]})


def test_reconciled_judge_result_is_consumed_by_resume_without_new_calls(tmp_path, monkeypatch):
    from hre.candidates.contracts import digest
    from hre.storage import write_json
    case = make_case(tmp_path)
    invoke = case.journal.invoke
    lost = {}

    def lose_once(operation_id, kind, request, callback, **kwargs):
        if kind == 'judge_J1_primary' and not lost:
            def callback_with_lost_receipt():
                lost.update(operation_id=operation_id, response=callback())
                raise TimeoutError('receipt lost')
            return invoke(operation_id, kind, request, callback_with_lost_receipt, **kwargs)
        return invoke(operation_id, kind, request, callback, **kwargs)

    monkeypatch.setattr(case.journal, 'invoke', lose_once)
    assert case.run()['phase'] == 'unresolved'
    operation = case.journal.snapshot()['operations'][lost['operation_id']]
    write_json(case.root / 'reconciliation' / 'response.json', lost['response'])
    write_json(case.root / 'reconciliation' / 'receipt.json', {
        'operation_id': lost['operation_id'], 'request_sha256': operation['request_sha256'],
        'response_sha256': digest(lost['response'])})
    resolution = {'schema_version': 'hre_candidates_v1', 'record_type': 'reconciliation',
                  'operation_id': lost['operation_id'], 'request_sha256': operation['request_sha256'],
                  'decision': 'confirmed_completed', 'operator': 'test', 'reason': 'bound worker receipt',
                  'evidence_refs': ['reconciliation/receipt.json'], 'response_path': 'reconciliation/response.json',
                  'receipt_path': 'reconciliation/receipt.json'}
    case.reconcile(lost['operation_id'], resolution)
    before = len(case.journal.snapshot()['operations'])
    assert case.run()['phase'] in {'selected', 'baseline_retained'}
    assert len(case.journal.snapshot()['operations']) == before
    state = case.state()
    case.reconcile(lost['operation_id'], resolution)
    assert case.state() == state


def test_e2_uses_registered_seeds_and_frozen_prompts_without_replanning(tmp_path, monkeypatch):
    from hre.candidates.contracts import candidate_spec, seal
    from hre.candidates.runtime import CandidateCase
    from hre.storage import read_json, write_json
    import hre.candidates.bridge as bridge
    image = tmp_path / 'lq.png'
    Image.new('RGB', (17, 13), 'blue').save(image)
    registration = seal({'schema_version': 'hre_candidates_v1', 'record_type': 'e2_preregistration',
                         'case_ids': ['paired'], 'evaluation_seeds': [10001, 10002]})
    path = tmp_path / 'registration.json'
    write_json(path, registration)
    case = CandidateCase.create(tmp_path / 'case', {'case_id': 'paired', 'source': str(image)},
                                {'mode': 'real', 'experiment': {'e2_manifest_path': str(path)},
                                 'budgets': {'image_generation': 12}})
    specs = [candidate_spec(slot, strategy, index, index, 'Frozen prompt ' + slot, case.frozen['source']['sha256'])
             for index, (slot, strategy) in enumerate(zip(['C0', 'CF', 'CT', 'CFT'], ['baseline', 'face_alt', 'text_alt', 'joint_alt']))]
    plan = seal({'candidate_specs': specs, 'plan_origin': 'planner'})
    write_json(case.root / 'plan' / 'plan.json', plan)
    write_json(case.root / 'baseline' / 'context.json', {'P0': specs[0]['full_prompt']})
    case._phase('plan_frozen', f1_hash=plan['freeze_hash'])
    monkeypatch.setattr(bridge, 'preflight', lambda config: {'status': 'ready'})
    observed = []

    def observe(spec, partition):
        observed.append((spec['slot_id'], spec['seed'], spec['full_prompt'], partition))
        return {'candidate_id': spec['candidate_id'], 'status': 'failed', 'sha256': None, 'delivered_image': None}

    monkeypatch.setattr(case, '_execute', observe)
    result = case.run_e2()
    assert len(result['records']) == len(observed) == 8
    assert {row[1] for row in observed} == {10001, 10002}
    assert all(prompt == next(x['full_prompt'] for x in specs if x['slot_id'] == slot) and partition == 'E2'
               for slot, seed, prompt, partition in observed)
    assert read_json(case.root / 'plan' / 'plan.json') == plan
