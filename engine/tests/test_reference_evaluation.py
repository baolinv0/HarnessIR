"""Whole-frame observations remain authoritative records, not a hidden score."""
from copy import deepcopy
from pathlib import Path
import hashlib
import pytest
from PIL import Image

from hre.reference_core import evaluation


def review_spec(tmp_path, stage='whole_image', predecessor=None):
    images = []
    for role in ('A', 'B', 'C'):
        path = tmp_path / (role + '.png')
        if not path.exists():
            Image.new('RGB', (12, 10), (40, 80, 120)).save(path)
        images.append(dict(role=role, path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    observation = dict(reference_status='achieved', relation='closer', direction='less_yellow', magnitude='slight',
                       confidence='medium', evidence='Whole-frame comparison against B.')
    return dict(schema_version='hre_holistic_review_v1', review_id='r_' + stage,
                sample_id='sample1', stage=stage, predecessor_hash=predecessor,
                images=images, display=dict(method='side_by_side', scale='fit', color_basis='assumed_srgb',
                                          note='Synthetic protocol fixture, no actual visual rating.'),
                reviewer=dict(reviewer_id='synthetic', independence='independent', prior_exposure='fixture_only'),
                whole_image={key: deepcopy(observation) for key in evaluation.AXES} if stage == 'whole_image' else None,
                preservation={key: dict(status='pass', confidence='high', evidence='Synthetic fixture.')
                              for key in evaluation.PROTECTIONS} if stage == 'whole_image' else None,
                regions=[], metrics=[], conflicts=[])


def test_whole_frame_then_regions_then_numbers_never_cancel_observations(tmp_path):
    root = tmp_path / 'review'
    first = evaluation.append_review(root, review_spec(tmp_path))
    second_spec = review_spec(tmp_path, 'whole_regions', first['content_hash'])
    second_spec['regions'] = [dict(region_id='face', semantic_class='face', unit_scope='whole_object_or_material',
                                    observations={'color': dict(reference_status='partial', relation='farther', direction='more_red', magnitude='slight',
                                                               confidence='medium', evidence='Synthetic regional disagreement.')})]
    second = evaluation.append_review(root, second_spec)
    third_spec = review_spec(tmp_path, 'explanations', second['content_hash'])
    third_spec['conflicts'] = ['Region color differs from the whole-frame observation; no weighting was declared.']
    third = evaluation.append_review(root, third_spec)
    text = evaluation.render_report(root)
    assert text.index('Whole-image') < text.index('Whole-region') < text.index('Explanatory')
    assert 'less_yellow' in text and 'more_red' in text
    assert third['payload']['whole_image_hash'] == first['content_hash']
    assert 'aggregate_score' not in third['payload']


def test_cannot_start_with_metrics_or_skip_stage(tmp_path):
    with pytest.raises(ValueError):
        evaluation.append_review(tmp_path / 'review', review_spec(tmp_path, 'explanations', 'a' * 64))


def test_missing_whole_image_axis_cannot_be_hidden(tmp_path):
    spec = review_spec(tmp_path)
    del spec['whole_image']['lighting_naturalness']
    with pytest.raises(ValueError):
        evaluation.append_review(tmp_path / 'review', spec)


def test_unknown_remains_uncertain_and_no_posthoc_weights(tmp_path):
    spec = review_spec(tmp_path)
    spec['whole_image']['tone'].update(reference_status='uncertain', relation='uncertain', magnitude='unknown', confidence='unknown')
    record = evaluation.append_review(tmp_path / 'review', spec)
    assert record['payload']['whole_image']['tone']['relation'] == 'uncertain'
    spec['weights'] = {'skin': 10}
    with pytest.raises(ValueError):
        evaluation.append_review(tmp_path / 'other', spec)


def test_changed_image_or_replayed_review_is_not_silently_replaced(tmp_path):
    root = tmp_path / 'review'
    spec = review_spec(tmp_path)
    first = evaluation.append_review(root, spec)
    assert evaluation.append_review(root, spec) == first
    changed = deepcopy(spec)
    changed['whole_image']['tone']['relation'] = 'farther'
    with pytest.raises(ValueError):
        evaluation.append_review(root, changed)
    Path(spec['images'][0]['path']).write_bytes(b'changed')
    with pytest.raises(ValueError):
        evaluation.render_report(root)


def test_local_numbers_require_whole_region_stage_and_finite_values(tmp_path):
    first = evaluation.append_review(tmp_path / 'review', review_spec(tmp_path))
    spec = review_spec(tmp_path, 'whole_regions', first['content_hash'])
    spec['metrics'] = [{'value': 1}]
    with pytest.raises(ValueError):
        evaluation.append_review(tmp_path / 'review', spec)
