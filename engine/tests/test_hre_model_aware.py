"""Condition contracts test executable combinations, not model quality claims."""
from copy import deepcopy
import json

import pytest

from hre.models import HREError


def assets():
    return [
        dict(role='prediction', asset_id='source_A', path='inputs/A.png',
             sha256='a'*64, pixel_sha256='1'*64, width=128, height=96),
        dict(role='reference', asset_id='source_B', path='inputs/B.png',
             sha256='b'*64, pixel_sha256='2'*64, width=96, height=128),
    ]


def intent():
    return dict(schema_version='reference_targets_v2', preservation_anchor='A',
                targets=[dict(target_id='coat', semantic_label='coat', direction='increase',
                              dimension='brightness', scope='local')])


def request(profile='qwen21', strategy='model_aware', compiler='native'):
    from hre.model_aware import build_condition_request
    return build_condition_request(
        dict(profile_id=profile, strategy=strategy, compiler=compiler),
        brief='Lift existing clothing shadows using B as appearance reference.',
        intent=None if strategy == 'native' else intent(), input_assets=assets(),
        case_id='case_1', source_id='compose_1')


def result(req):
    value = dict(schema_version='model_condition_result_v1',
                 request_id=req['request_id'], profile_id=req['profile_id'],
                 status='ok', edit_prompt='Lift the existing clothing shadows.',
                 canvas=deepcopy(req['canvas']),
                 compiler_observation=dict(compiler_id='observed compiler',
                                           compiler_version=None, settings={}, calls=1))
    if req['profile_id'] == 'fibo2_dev':
        value['edit_prompt'] = json.dumps(dict(
            edit_instruction='Adjust <image_1> using only the appearance of <image_2>.',
            short_description='The original scene with brighter clothing shadows.'))
    if req['profile_id'] == 'qwen21' and req['compiler'] == 'native':
        value['native_output'] = dict(parse_ok=True, ratio_follow='image1', wh_ratio='',
                                      positive_prompt=value['edit_prompt'])
    return value


@pytest.mark.parametrize('profile', ['flux3_klein', 'fibo2_dev', 'qwen21', 'firered11'])
def test_profiles_are_static_declarations_not_capability_proofs(profile):
    from hre.model_aware import get_model_profile
    p = get_model_profile(profile)
    assert p['profile_id'] == profile
    assert p['capability_status'] == 'declared_not_measured'
    assert p['execution_mode'] == 'full_frame_A_B'
    assert p['validated_capabilities'] == []
    assert p['sources']
    p['validated_capabilities'].append('fake')
    assert get_model_profile(profile)['validated_capabilities'] == []


def test_fibo_profile_does_not_advertise_mask_and_multireference_composition():
    from hre.model_aware import get_model_profile
    p = get_model_profile('fibo2_dev')
    assert p['capabilities']['multi_reference_with_mask'] is False
    assert p['capabilities']['mask_preserves_source_pixels'] is False
    assert 'grey' in p['capabilities']['mask_semantics']


@pytest.mark.parametrize('config', [
    dict(profile_id='unknown', strategy='model_aware', compiler='native'),
    dict(profile_id='flux3_klein', strategy='native', compiler='direct'),
    dict(profile_id='fibo2_dev', strategy='model_aware', compiler='direct'),
    dict(profile_id='qwen21', strategy='automatic', compiler='native'),
    dict(profile_id='qwen21', strategy='shared', compiler='native', mask=True),
])
def test_unsupported_model_configs_fail_before_compilation(config):
    from hre.model_aware import validate_model_config
    with pytest.raises(HREError):
        validate_model_config(config)


def test_request_freezes_independent_bindings_and_A_canvas():
    req = request()
    assert req['canvas'] == dict(source='A', width=128, height=96)
    assert [x['role'] for x in req['input_bindings']] == ['A', 'B']
    assert req['input_bindings'][1]['width'] == 96
    assert req['input_bindings'][0]['pixel_sha256'] == '1'*64
    assert req['request_id'] == request()['request_id']
    assert req['intent'] == intent()


def test_strategy_arms_keep_intent_fixed_but_emit_distinct_compiler_tasks():
    n, s, m = request(strategy='native'), request(strategy='shared'), request()
    assert n['intent'] is None
    assert s['intent'] == m['intent']
    assert len({n['compiler_task'], s['compiler_task'], m['compiler_task']}) == 3
    assert all(x['compiler_task'] for x in (n, s, m))
    assert 'PE-I2I' in m['compiler_task']


def test_missing_reference_or_mixing_native_with_intent_is_rejected():
    from hre.model_aware import build_condition_request
    kwargs = dict(brief='Transfer appearance only', intent=None,
                  case_id='c', source_id='s')
    cfg = dict(profile_id='qwen21', strategy='native', compiler='direct')
    with pytest.raises(HREError, match='condition_inputs'):
        build_condition_request(cfg, input_assets=assets()[:1], **kwargs)
    kwargs['intent'] = intent()
    with pytest.raises(HREError, match='condition_intent'):
        build_condition_request(cfg, input_assets=assets(), **kwargs)


@pytest.mark.parametrize('profile', ['flux3_klein', 'fibo2_dev', 'qwen21', 'firered11'])
def test_valid_native_conditions_keep_exact_final_text(profile):
    from hre.model_aware import validate_compiled_condition
    req = request(profile)
    compiled = result(req)
    out = validate_compiled_condition(req, compiled)
    assert out['edit_prompt'] == compiled['edit_prompt']
    assert out['condition_kind']
    assert out['compiler_observation']['compiler_version'] is None


@pytest.mark.parametrize('profile', ['qwen21', 'firered11'])
def test_direct_supported_models_do_not_require_native_PE_output(profile):
    from hre.model_aware import validate_compiled_condition
    req = request(profile, compiler='direct')
    compiled = result(req)
    compiled['compiler_observation'].update(compiler_id='direct', calls=0)
    assert validate_compiled_condition(req, compiled)['status'] == 'ok'


@pytest.mark.parametrize('change', [
    dict(request_id='other_request'),
    dict(profile_id='flux3_klein'),
    dict(edit_prompt='   '),
    dict(canvas=dict(source='B', width=128, height=96)),
    dict(canvas=dict(source='A', width=96, height=128)),
])
def test_bad_result_cannot_become_executable(change):
    from hre.model_aware import validate_compiled_condition
    req = request()
    compiled = result(req)
    compiled.update(change)
    with pytest.raises(HREError):
        validate_compiled_condition(req, compiled)


@pytest.mark.parametrize('payload', [
    {}, dict(parse_ok=False, ratio_follow='image1', wh_ratio=''),
    dict(parse_ok=True, ratio_follow='image2', wh_ratio=''),
    dict(parse_ok=True, ratio_follow='image1', wh_ratio='16:9'),
])
def test_qwen_PE_parse_failure_or_canvas_override_is_rejected(payload):
    from hre.model_aware import validate_compiled_condition
    req = request()
    compiled = result(req)
    compiled['native_output'] = payload
    with pytest.raises(HREError, match='condition_native_output'):
        validate_compiled_condition(req, compiled)


def test_qwen_official_bracketed_ratio_follow_is_accepted_without_changing_raw_output():
    from hre.model_aware import validate_compiled_condition
    req = request()
    compiled = result(req)
    compiled['native_output']['ratio_follow'] = '<image1>'
    out = validate_compiled_condition(req, compiled)
    assert out['native_output']['ratio_follow'] == '<image1>'
    assert out['canvas']['source'] == 'A'


@pytest.mark.parametrize('positive_prompt', [None, '', 'A different final PE instruction.'])
def test_qwen_final_prompt_must_equal_actual_PE_positive_prompt(positive_prompt):
    from hre.model_aware import validate_compiled_condition
    req = request()
    compiled = result(req)
    compiled['native_output']['positive_prompt'] = positive_prompt
    with pytest.raises(HREError, match='condition_native_output'):
        validate_compiled_condition(req, compiled)


@pytest.mark.parametrize('prompt', ['plain text', '{}', '{"edit_instruction":""}',
                                   '{"edit_instruction":"change", "a":NaN}'])
def test_fibo_requires_valid_native_edit_instruction(prompt):
    from hre.model_aware import validate_compiled_condition
    req = request('fibo2_dev')
    compiled = result(req)
    compiled['edit_prompt'] = prompt
    with pytest.raises(HREError, match='condition_native_output'):
        validate_compiled_condition(req, compiled)


def test_compile_error_preserves_failure_and_never_returns_a_prompt():
    from hre.model_aware import validate_compiled_condition
    req = request()
    compiled = result(req)
    compiled.update(status='error', edit_prompt=None,
                    error=dict(code='provider_unavailable', message='No compiler result.'))
    with pytest.raises(HREError, match='condition_compile_failed.*provider_unavailable'):
        validate_compiled_condition(req, compiled)


@pytest.mark.parametrize('observation', [
    {}, dict(compiler_id=None, compiler_version=None, settings={}, calls=-1),
    dict(compiler_id=None, compiler_version=None, settings={}, calls=True),
    dict(compiler_id=None, compiler_version=None, settings={}, calls=0),
])
def test_native_compiler_costs_must_be_observed_or_explicitly_unknown(observation):
    from hre.model_aware import validate_compiled_condition
    req = request()
    compiled = result(req)
    compiled['compiler_observation'] = observation
    with pytest.raises(HREError, match='condition_observation'):
        validate_compiled_condition(req, compiled)


def test_unobservable_version_or_call_count_is_not_fabricated():
    from hre.model_aware import validate_compiled_condition
    req = request()
    compiled = result(req)
    compiled['compiler_observation'] = dict(compiler_id=None, compiler_version=None,
                                           settings={'temperature': None}, calls=None)
    assert validate_compiled_condition(req, compiled)['compiler_observation']['calls'] is None


def test_mutated_frozen_request_is_rejected():
    from hre.model_aware import validate_compiled_condition
    req = request()
    compiled = result(req)
    req['intent']['targets'][0]['direction'] = 'decrease'
    with pytest.raises(HREError, match='condition_request'):
        validate_compiled_condition(req, compiled)


@pytest.mark.parametrize('profile', ['qwen21', 'firered11'])
def test_direct_renderer_is_deterministic_and_records_zero_external_calls(profile):
    from hre.model_aware import compile_direct_condition, validate_compiled_condition
    req = request(profile, compiler='direct')
    before = deepcopy(req)
    compiled = compile_direct_condition(req)
    assert compiled == compile_direct_condition(req)
    assert req == before
    assert compiled['compiler_observation']['calls'] == 0
    assert compiled['compiler_observation']['compiler_id'] == 'hre-direct'
    assert compiled['compiler_observation']['compiler_version']
    assert 'coat' in compiled['edit_prompt']
    assert 'increase' in compiled['edit_prompt']
    assert validate_compiled_condition(req, compiled) == compiled


def test_direct_strategy_rendering_preserves_shared_targets_and_relations():
    from hre.model_aware import build_condition_request, compile_direct_condition
    frozen = intent()
    frozen['region_relations'] = [dict(subject='coat', object='background',
                                      target='subject remains below background midtones')]
    def build(strategy):
        return build_condition_request(
            dict(profile_id='qwen21', strategy=strategy, compiler='direct'),
            brief='Retain the night scene.', intent=None if strategy == 'native' else frozen,
            input_assets=assets(), case_id='c', source_id='s')
    n, s, m = [compile_direct_condition(build(x)) for x in ('native', 'shared', 'model_aware')]
    assert len({x['edit_prompt'] for x in (n, s, m)}) == 3
    assert 'coat' not in n['edit_prompt']
    for output in (s, m):
        assert 'coat' in output['edit_prompt']
        assert 'subject remains below background midtones' in output['edit_prompt']


def test_direct_renderer_never_fabricates_a_native_compiler_result():
    from hre.model_aware import compile_direct_condition
    with pytest.raises(HREError, match='condition_compiler'):
        compile_direct_condition(request('flux3_klein'))


def test_direct_prompt_excludes_long_evidence_and_internal_identifiers():
    from hre.model_aware import build_condition_request, compile_direct_condition
    frozen = intent()
    frozen['targets'][0].update(
        source_gap_ids=['INTERNAL_GAP'], observed_support='RAW_EVIDENCE ' * 3000,
        comparability_sources={'frozen_roi': [{'sha256': 'PRIVATE_SHA'}]},
        raw_stats={'median': 29.127}, target_state='Clothing remains shadowed.')
    frozen['protected_content'] = [dict(instruction='Preserve existing sign text.',
                                        evidence_ids=['INTERNAL_PROTECTION'])]
    frozen['workflow_state'] = 'INTERNAL_WORKFLOW'
    req = build_condition_request(
        dict(profile_id='qwen21', strategy='model_aware', compiler='direct'),
        brief='Lift supported clothing shadows.', intent=frozen, input_assets=assets(),
        case_id='c', source_id='s')
    prompt = compile_direct_condition(req)['edit_prompt']
    assert 'Clothing remains shadowed.' in prompt
    assert 'Preserve existing sign text.' in prompt
    assert all(token not in prompt for token in (
        'INTERNAL_GAP', 'RAW_EVIDENCE', 'PRIVATE_SHA', '29.127',
        'INTERNAL_PROTECTION', 'INTERNAL_WORKFLOW'))
    assert len(prompt.split()) < 220
    assert req['intent'] == frozen


def test_direct_prompt_never_infers_relations_from_metrics_or_source_names():
    from hre.model_aware import build_condition_request, compile_direct_condition
    frozen = intent()
    frozen['region_relations'] = [
        dict(subject='coat', object='background', attribute='relative_brightness',
             target_source='reference_roi_statistics', measured_difference=12.345),
        dict(subject='coat', object='background', attribute='relative_brightness',
             target={'unknown_numeric_field': 0.987}),
    ]
    req = build_condition_request(
        dict(profile_id='firered11', strategy='shared', compiler='direct'),
        brief='Lift supported clothing shadows.', intent=frozen, input_assets=assets(),
        case_id='c', source_id='s')
    prompt = compile_direct_condition(req)['edit_prompt']
    assert all(token not in prompt for token in (
        'reference_roi_statistics', '12.345', '0.987', 'unknown_numeric_field'))
    assert '12' not in prompt


def test_direct_relations_resolve_frozen_roi_ids_to_semantic_names():
    from hre.model_aware import build_condition_request, compile_direct_condition
    frozen = intent()
    frozen['roi_pairs'] = [
        dict(roi_pair_id='roi_001', semantic_label='dark blue clothing'),
        dict(roi_pair_id='roi_002', semantic_label='illuminated shopfront'),
    ]
    frozen['region_relations'] = [dict(
        subject_roi_id='roi_001', object_roi_id='roi_002',
        attribute='relative_brightness', target='clothing remains darker than the shopfront')]
    req = build_condition_request(
        dict(profile_id='qwen21', strategy='model_aware', compiler='direct'),
        brief='Lift supported clothing shadows.', intent=frozen, input_assets=assets(),
        case_id='c', source_id='s')
    prompt = compile_direct_condition(req)['edit_prompt']
    assert 'dark blue clothing' in prompt and 'illuminated shopfront' in prompt
    assert 'clothing remains darker than the shopfront' in prompt
    assert 'roi_001' not in prompt and 'roi_002' not in prompt
