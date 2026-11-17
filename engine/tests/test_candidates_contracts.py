import pytest
from hre.models import HREError


def test_candidate_prompt_identity_and_frozen_copy():
    from hre.candidates.contracts import candidate_spec, seal, verify_seal
    spec = candidate_spec('CF', 'face_alt', 1, 11, 'Restore supported face boundaries.', 'a' * 64)
    frozen = seal(spec)
    verify_seal(frozen)
    spec['seed'] = 12
    assert frozen['seed'] == 11
    frozen['full_prompt'] = 'changed'
    with pytest.raises(HREError, match='freeze_modified'):
        verify_seal(frozen)


def test_policy_cannot_weaken_required_accuracy():
    from hre.candidates.contracts import parse_task
    task = parse_task({'case_id': 'one', 'source': 'lq.png', 'task_mode': 'sr_x4',
                       'usage_policy': 'information_critical',
                       'critical_attributes': [{'attribute_id': 'number', 'region_selector': 'sign',
                                                'attribute': 'text_content', 'required_for_acceptance': False,
                                                'verification_requirement': 'visible_consistency'}]})
    assert task['critical_attributes'][0]['required_for_acceptance'] is True
    assert task['critical_attributes'][0]['verification_requirement'] == 'verified_content'


def test_unknown_config_key_and_nonfinite_values_rejected():
    from hre.candidates.contracts import parse_config
    with pytest.raises(HREError):
        parse_config({'mode': 'fixture', 'surprise': True})
    with pytest.raises(HREError):
        parse_config({'mode': 'fixture', 'editor': {'settings': {'true_cfg_scale': float('nan')}}})


def test_default_budget_and_modes_are_explicit():
    from hre.candidates.contracts import parse_config, parse_task
    config = parse_config({'mode': 'fixture'})
    assert config['budgets']['image_generation'] == 7
    assert config['review']['max_judge_calls']['J1'] == 3
    assert config['editor']['settings']['num_images_per_prompt'] == 1
    assert config['editor']['settings']['output_resolution'] == 1024
    assert parse_task({'case_id': 'x', 'source': 'lq.png', 'task_mode': 'sr_x4'})['scale'] == 4
    with pytest.raises(HREError):
        parse_task({'case_id': '../x', 'source': 'lq.png'})


def test_raw_credentials_cannot_be_frozen_to_disk():
    from hre.candidates.contracts import parse_config
    with pytest.raises(HREError, match='credential'):
        parse_config({'mode': 'real', 'stages': {'judge': {'base_url': 'http://localhost/v1',
                     'model': 'local', 'api_key': 'secret-value'}}})


def test_information_critical_roi_has_required_content_policy():
    from hre.candidates.contracts import parse_task
    task = parse_task({'case_id': 'critical', 'source': 'input.png', 'usage_policy': 'information_critical',
                       'rois': [{'id': 'sign', 'semantic_type': 'text', 'box': [0, 0, 10, 10]}]})
    assert any(x['region_selector'] == 'sign' and x['verification_requirement'] == 'verified_content'
               for x in task['critical_attributes'])
