import pytest

from hre.candidates.cli import make_fixture
from hre.candidates.contracts import seal
from hre.candidates.report import evaluate_offline
from hre.candidates.runtime import CandidateCase
from hre.storage import read_json, write_json


@pytest.mark.parametrize('gate,contract_label', [('passed', True), ('passed', False), ('failed', True), ('unknown', True), (None, True)])
def test_single_case_oracle_requires_actual_hard_contract(tmp_path, gate, contract_label):
    location = make_fixture(tmp_path / 'fixture')
    case = CandidateCase.open(location['case_root'])
    case.run()
    artifacts = read_json(case.root / 'artifacts.json')['B']
    labels = {'labels': [{'candidate_id': item['candidate_id'], 'candidate_hash': item['sha256'],
                         'acceptable': True, 'contract_valid': contract_label} for item in artifacts],
              'best_set': [item['candidate_id'] for item in artifacts]}
    write_json(case.root / 'selection.json', seal({'best_candidate': None, 'eligible_ids': []}))
    write_json(case.root / 'evidence' / 'bundle.json', seal({'candidates': [
        {'candidate_id': item['candidate_id'], 'hard_gate': gate} for item in artifacts] if gate else []}))
    result = evaluate_offline(case.root, labels)
    accepted = gate == 'passed' and contract_label
    assert result['oracle_pass_at_4']['numerator'] == int(accepted)
    assert result['false_reject']['denominator'] == (4 if accepted else 0)
    assert result['avoidable_unresolved']['denominator'] == int(accepted)


@pytest.mark.parametrize('best_kind,complete,has_accepted,expected', [
    ('invalid', True, True, (0, 0, None, 1)),
    ('mixed', True, True, (0, 0, None, 1)),
    ('empty', True, True, (0, 0, None, 1)),
    ('missing', True, True, (0, 0, None, 1)),
    ('valid', True, True, (1, 1, 1, 0)),
    ('valid', False, True, (0, 0, None, 1)),
    ('invalid', True, False, (0, 0, None, 0)),
    ('pool_valid', True, True, (1, 1, 1, 0)),
])
def test_single_and_batch_best_agreement_require_usable_annotation(tmp_path, best_kind, complete, has_accepted, expected):
    from hre.candidates.analysis import summarize_cases
    location = make_fixture(tmp_path / 'fixture')
    case = CandidateCase.open(location['case_root'])
    case.run()
    pools = read_json(case.root / 'artifacts.json')
    selected = read_json(case.root / 'selection.json')['best_candidate']
    favorite = next(item['candidate_id'] for item in pools['B'] if item['candidate_id'] != selected)
    bundle = read_json(case.root / 'evidence' / 'bundle.json')
    for item in bundle['candidates']:
        if item['candidate_id'] == favorite or not has_accepted:
            item['hard_gate'] = 'failed'
    write_json(case.root / 'evidence' / 'bundle.json', seal(bundle))
    artifacts = {item['candidate_id']: item for pool in pools.values() for item in pool}
    labels = {'labels': [{'candidate_id': cid, 'candidate_hash': item['sha256'],
                          'acceptable': cid in {selected, favorite}} for cid, item in artifacts.items()]}
    if best_kind == 'invalid':
        labels['best_set'] = [favorite]
    elif best_kind == 'mixed':
        labels['best_set'] = [selected, favorite]
    elif best_kind == 'empty':
        labels['best_set'] = []
    elif best_kind == 'valid':
        labels['best_set'] = [selected]
    elif best_kind == 'pool_valid':
        labels.update(best_set=[favorite], best_sets={'B': [selected]})
    if not complete:
        missing_id = next(cid for cid in artifacts if cid not in {selected, favorite} and cid in {item['candidate_id'] for item in pools['B']})
        labels['labels'] = [row for row in labels['labels'] if row['candidate_id'] != missing_id]
    single = evaluate_offline(case.root, labels)
    batch = summarize_cases([case.root], tmp_path / 'summary', bootstrap_replicates=10)['pools']['B']
    for result in (single, batch):
        metric = result['best_in_pool_agreement']
        assert (metric['numerator'], metric['denominator'], metric['value'], metric['missing_count']) == expected
        assert result['selected_pass']['value'] == int(complete and has_accepted)
        assert result['oracle_pass_at_4']['value'] == int(has_accepted)


@pytest.mark.parametrize('best_fields', [
    {'best_set': 'not-a-list'},
    {'best_sets': []},
    {'best_sets': {'B': {}}},
    {'best_set': ['not-a-produced-candidate']},
])
def test_both_oracle_paths_reject_malformed_or_unknown_best_annotations(tmp_path, best_fields):
    from hre.candidates.analysis import summarize_cases
    from hre.models import HREError
    location = make_fixture(tmp_path / 'fixture')
    case = CandidateCase.open(location['case_root'])
    case.run()
    artifacts = {item['candidate_id']: item for pool in read_json(case.root / 'artifacts.json').values() for item in pool}
    labels = {'labels': [{'candidate_id': cid, 'candidate_hash': item['sha256'], 'acceptable': True}
                         for cid, item in artifacts.items()], **best_fields}
    write_json(case.root / 'offline' / 'oracle_labels.json', labels)
    with pytest.raises(HREError, match='oracle_invalid'):
        evaluate_offline(case.root, labels)
    with pytest.raises(HREError, match='oracle_invalid'):
        summarize_cases([case.root], tmp_path / 'summary', bootstrap_replicates=10)
