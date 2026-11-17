import pytest
from hre.models import HREError
from hre.candidates.study import preregister


def test_preregister_retains_shortfalls_and_disjoint_paired_seeds():
    dataset = {'cases': [{'case_id': 'a', 'scene_id': 'a', 'split': 'pilot', 'scene_class': 'person', 'information_level': 'legible', 'size_bin': 'small'}]}
    protocol = {'e1': {'seed_schedule': [0, 1, 2, 3]}, 'e2': {'sampling_seed': 1, 'evaluation_seeds': [100, 101], 'pilot': {'scene_quotas': {'person': 2, 'mixed': 1}}}}
    result = preregister(dataset, protocol, 'pilot')
    assert result['case_ids'] == ['a']
    assert result['shortfalls'] == {'person': 1, 'mixed': 1}
    assert result['evaluation_seeds'] == [100, 101]
    assert preregister(dataset, protocol, 'pilot') == result


def test_preregister_rejects_seed_overlap_and_scene_split_leak():
    protocol = {'e1': {'seed_schedule': [0]}, 'e2': {'sampling_seed': 1, 'evaluation_seeds': [0, 2], 'pilot': {'scene_quotas': {'person': 1}}}}
    with pytest.raises(HREError):
        preregister({'cases': []}, protocol, 'pilot')
    protocol['e2']['evaluation_seeds'] = [1, 2]
    with pytest.raises(HREError):
        preregister({'cases': [{'case_id': 'a', 'scene_id': 'same', 'split': 'pilot', 'scene_class': 'person'}, {'case_id': 'b', 'scene_id': 'same', 'split': 'held_out', 'scene_class': 'person'}]}, protocol, 'pilot')
