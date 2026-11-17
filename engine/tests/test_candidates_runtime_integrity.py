from pathlib import Path

from PIL import Image
import pytest

from hre.candidates.contracts import candidate_spec
from hre.candidates.runtime import CandidateCase
from hre.models import HREError
from hre.storage import read_json, write_json


@pytest.fixture
def case(tmp_path):
    source = tmp_path / 'lq.png'
    Image.new('RGB', (17, 13), 'blue').save(source)
    return CandidateCase.create(tmp_path / 'case', {'case_id': 'integrity', 'source': str(source)}, {'mode': 'fixture'})


@pytest.mark.parametrize('action', ['resume', 'report'])
@pytest.mark.parametrize('mutation', ['replace', 'remove'])
def test_terminal_delivery_rejects_changed_anonymous_copy(case, action, mutation):
    state = case.run()
    path = Path(state['selected_output'])
    if mutation == 'replace':
        Image.new('RGB', (17, 13), 'red').save(path)
    else:
        path.unlink()
    before = (case.root / 'operations.json').read_bytes()
    reopened = CandidateCase.open(case.root)
    with pytest.raises(HREError, match='output_modified'):
        reopened.run() if action == 'resume' else reopened.write_report()
    assert (case.root / 'operations.json').read_bytes() == before


@pytest.mark.parametrize('partition', ['E1', 'E2'])
@pytest.mark.parametrize('field', ['delivered_image', 'native_image'])
def test_cached_generation_rejects_changed_files_without_new_calls(case, partition, field):
    spec = candidate_spec('C0', 'baseline', 0, 1, 'Restore visible details.', case.frozen['source']['sha256'])
    artifact = case._execute(spec, partition)
    Image.new('RGB', (17, 13), 'red').save(artifact[field])
    before = (case.root / 'operations.json').read_bytes()
    cached_before = (case.root / 'candidates' / spec['candidate_id'] / 'artifact.json').read_bytes()
    with pytest.raises(HREError, match='output_modified'):
        case._execute(spec, partition)
    assert (case.root / 'operations.json').read_bytes() == before
    assert (case.root / 'candidates' / spec['candidate_id'] / 'artifact.json').read_bytes() == cached_before


def test_e2_result_integrity_is_checked_before_other_case_actions(case):
    spec = candidate_spec('C0', 'baseline', 0, 10001, 'Restore visible details.', case.frozen['source']['sha256'])
    artifact = case._execute(spec, 'E2')
    write_json(case.root / 'e2' / 'results.json', {'records': [{'artifact': artifact}]})
    Image.new('RGB', (17, 13), 'red').save(artifact['delivered_image'])
    before = (case.root / 'operations.json').read_bytes()
    with pytest.raises(HREError, match='output_modified'):
        CandidateCase.open(case.root).run()
    assert (case.root / 'operations.json').read_bytes() == before


def test_frozen_delivery_path_cannot_be_replaced_by_case_state(case, tmp_path):
    case.run()
    replacement = tmp_path / 'unreviewed.png'
    Image.new('RGB', (17, 13), 'green').save(replacement)
    state = read_json(case.root / 'case.json')
    state['selected_output'] = str(replacement)
    write_json(case.root / 'case.json', state)
    with pytest.raises(HREError, match='selection_binding_mismatch'):
        CandidateCase.open(case.root).run()


def test_corrupt_partial_candidate_is_not_replaced_by_failed_slot(case, monkeypatch):
    execute = case._execute
    interrupted = {}

    def interrupt_after_first_alternative(spec, partition='E1'):
        artifact = execute(spec, partition)
        if spec['slot_id'] != 'C0' and not interrupted:
            interrupted.update(artifact=artifact, spec=spec)
            raise KeyboardInterrupt('process ended before the pool was saved')
        return artifact

    monkeypatch.setattr(case, '_execute', interrupt_after_first_alternative)
    with pytest.raises(KeyboardInterrupt):
        case.run()
    artifact = interrupted['artifact']
    Image.new('RGB', (17, 13), 'red').save(artifact['delivered_image'])
    record_path = case.root / 'candidates' / artifact['candidate_id'] / 'artifact.json'
    saved = record_path.read_bytes()
    before = (case.root / 'operations.json').read_bytes()
    with pytest.raises(HREError, match='output_modified'):
        CandidateCase.open(case.root).run()
    assert record_path.read_bytes() == saved
    assert read_json(record_path)['status'] == 'completed'
    assert (case.root / 'operations.json').read_bytes() == before
