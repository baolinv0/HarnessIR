"""Frozen model-native condition requests; no image or compiler calls occur here.

Profiles describe upstream interfaces, not measured HarnessIR capability.  A
successful validation checks bindings and format only, not visual correctness or
semantic preservation.  Actual compilers are run by the external handoff/backend.
"""
from copy import deepcopy
from importlib.resources import files
import json

from .models import HREError, canonical_json, sha256_bytes


PROFILE_IDS = frozenset({'flux3_klein', 'fibo2_dev', 'qwen21', 'firered11'})
CONFIG_KEYS = frozenset({'profile_id', 'strategy', 'compiler'})
STRATEGIES = frozenset({'native', 'shared', 'model_aware'})
REQUEST_VERSION = 'model_condition_request_v1'
RESULT_VERSION = 'model_condition_result_v1'


def _require(ok, code, message):
    if not ok:
        raise HREError(code, message)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _json(value, code):
    try:
        return canonical_json(value)
    except (TypeError, ValueError) as exc:
        raise HREError(code, 'Finite JSON values required') from exc


def get_model_profile(profile_id: str) -> dict:
    """Return a fresh copy of a reviewed interface declaration."""
    _require(isinstance(profile_id, str) and profile_id in PROFILE_IDS,
             'model_profile', 'Unknown model profile: ' + str(profile_id))
    path = files('hre').joinpath('resources/model_profiles', profile_id + '.json')
    return json.loads(path.read_text('utf-8'))


def validate_model_config(config: dict) -> dict:
    """Validate the explicit fixed strategy.  There is no automatic router."""
    _require(isinstance(config, dict) and set(config) == CONFIG_KEYS,
             'model_config', 'Expected only profile_id, strategy and compiler')
    profile = get_model_profile(config['profile_id'])
    _require(isinstance(config['strategy'], str) and config['strategy'] in STRATEGIES,
             'model_config', 'Use native, shared or model_aware strategy')
    _require(isinstance(config['compiler'], str)
             and config['compiler'] in profile['allowed_compilers'],
             'model_config', 'Compiler is not supported by this model profile')
    _json(config, 'model_config')
    return deepcopy(config)


def _bindings(input_assets):
    _require(isinstance(input_assets, list) and len(input_assets) == 2,
             'condition_inputs', 'This version requires exactly A and B, without editor masks')
    roles = {'prediction': 'A', 'reference': 'B', 'A': 'A', 'B': 'B'}
    result = {}
    for asset in input_assets:
        _require(isinstance(asset, dict) and isinstance(asset.get('role'), str)
                 and asset['role'] in roles,
                 'condition_inputs', 'Use prediction/reference or A/B input roles')
        role = roles[asset['role']]
        _require(role not in result, 'condition_inputs', 'Duplicate input role ' + role)
        _require(all(_text(asset.get(k)) for k in ('asset_id', 'path', 'sha256', 'pixel_sha256')),
                 'condition_inputs', 'Input identity, path and source hashes are required')
        _require(all(type(asset.get(k)) is int and asset[k] > 0 for k in ('width', 'height')),
                 'condition_inputs', 'Positive canonical image dimensions required')
        result[role] = dict(role=role, **{k: asset[k] for k in (
            'asset_id', 'path', 'sha256', 'pixel_sha256', 'width', 'height')})
    _require(set(result) == {'A', 'B'}, 'condition_inputs', 'Both A and B are required')
    return [result['A'], result['B']]


def _compiler_task(config, profile):
    common = (
        'Use the attached brief and ordered images A then B. A is the only content, '
        'identity, text and geometry anchor; B supplies appearance only. Preserve the '
        'requested A canvas. This version performs one full-frame A+B edit, with no '
        'editor mask, crop, bounding-box layout, fusion or automatic retry. Do not '
        'invent measured exposure values, objects or unsupported detail. Return the '
        'actual final native condition, not a description of how to produce it. '
    )
    if config['strategy'] == 'native':
        strategy = (
            'NATIVE arm: use only the original brief and the same A/B images through '
            'the selected native path. No HarnessIR analysis or derived intent is supplied. '
        )
    elif config['strategy'] == 'shared':
        strategy = (
            'SHARED arm: express the frozen intent as plain, model-neutral editing goals '
            'in its recorded order, then use the selected native path. Preserve every '
            'target, relation, constraint and uncertainty; do not add model-specific '
            'planning or reinterpret the goals. '
        )
    else:
        strategy = (
            'MODEL_AWARE arm: keep exactly the same frozen intent as the shared arm. '
            'Adapt its expression using these model-specific rules without adding, '
            'removing, reversing or strengthening targets: ' + profile['model_aware_guidance'] + ' '
        )
    if config['compiler'] == 'direct':
        compiler = (
            'DIRECT path: produce a concise executable editing instruction. Do not '
            'claim to have run PE-I2I or Recaption. Record the actual compiler identity, '
            'settings and calls (zero only if no model call occurred). '
        )
    else:
        compiler = profile['native_compiler']['task'] + ' '
    return common + strategy + compiler + (
        'Record compiler_id, compiler_version, settings and calls in compiler_observation. '
        'Use null for genuinely unobservable identity/version/count values, never a '
        'fabricated value. Preserve native output for audit. If the compiler fails or '
        'cannot satisfy the canvas contract, return status=error with error.code and '
        'error.message; do not generate an image or silently repair the condition.'
    )


def build_condition_request(model_config: dict, *, brief: str, intent: dict | None,
                            input_assets: list[dict], case_id: str, source_id: str) -> dict:
    """Freeze a compiler handoff, retaining existing reference_targets as intent."""
    config = validate_model_config(model_config)
    _require(_text(brief) and _text(case_id) and _text(source_id),
             'condition_request', 'A task brief, case ID and source task ID are required')
    if config['strategy'] == 'native':
        _require(intent is None, 'condition_intent', 'Native baseline must not consume derived intent')
    else:
        _require(isinstance(intent, dict) and bool(intent),
                 'condition_intent', 'Shared/model_aware requires a frozen intent object')
    _json(intent, 'condition_intent')
    bindings = _bindings(input_assets)
    profile = get_model_profile(config['profile_id'])
    request = dict(
        schema_version=REQUEST_VERSION, case_id=case_id, source_id=source_id,
        **config, brief=brief, intent=deepcopy(intent), input_bindings=bindings,
        canvas=dict(source='A', width=bindings[0]['width'], height=bindings[0]['height']),
        compiler_task=_compiler_task(config, profile))
    request['request_id'] = sha256_bytes(_json(request, 'condition_request'))
    return request


def _validate_request(request):
    _require(isinstance(request, dict) and request.get('schema_version') == REQUEST_VERSION,
             'condition_request', 'Unknown condition request format')
    _require(_text(request.get('request_id')),
             'condition_request', 'Frozen condition request ID required')
    digest = sha256_bytes(_json({k: v for k, v in request.items() if k != 'request_id'},
                                'condition_request'))
    _require(request['request_id'] == digest,
             'condition_request', 'Frozen compiler request changed')
    try:
        config = validate_model_config({k: request[k] for k in CONFIG_KEYS})
        rebuilt = build_condition_request(
            config, brief=request['brief'], intent=request['intent'],
            input_assets=request['input_bindings'], case_id=request['case_id'],
            source_id=request['source_id'])
    except KeyError as exc:
        raise HREError('condition_request', 'Incomplete condition request') from exc
    _require(request == rebuilt, 'condition_request', 'Request does not match its frozen inputs')


def _validate_observation(request, observation):
    required = {'compiler_id', 'compiler_version', 'settings', 'calls'}
    _require(isinstance(observation, dict) and required <= set(observation),
             'condition_observation', 'Record actual compiler identity, version, settings and calls')
    _require(all(observation[k] is None or _text(observation[k])
                 for k in ('compiler_id', 'compiler_version')),
             'condition_observation', 'Unknown compiler identity/version must be null')
    calls = observation['calls']
    _require(calls is None or (type(calls) is int and calls >= 0),
             'condition_observation', 'Call count must be a nonnegative integer or null')
    if request['compiler'] == 'native':
        _require(calls is None or calls >= 1, 'condition_observation',
                 'A successful native compilation cannot report zero compiler calls')
    _require(isinstance(observation['settings'], dict),
             'condition_observation', 'Compiler settings must be an object')
    _json(observation, 'condition_observation')


def validate_compiled_condition(request: dict, result: dict) -> dict:
    """Validate actual native output; errors raise before an editor may run.

    This is structural validation. It intentionally does not claim semantic
    fidelity merely because a Caption/VGL is well formed.
    """
    _validate_request(request)
    _require(isinstance(result, dict) and result.get('schema_version') == RESULT_VERSION,
             'condition_result', 'Unknown condition result format')
    _json(result, 'condition_result')
    _require(result.get('request_id') == request['request_id']
             and result.get('profile_id') == request['profile_id'],
             'condition_binding', 'Result belongs to another request or model profile')
    _require(result.get('status') in ('ok', 'error'),
             'condition_result', 'Condition status must be ok or error')
    if result['status'] == 'error':
        error = result.get('error')
        _require(isinstance(error, dict) and _text(error.get('code'))
                 and _text(error.get('message')), 'condition_result',
                 'An error result needs error.code and error.message')
        raise HREError('condition_compile_failed', error['code'] + ': ' + error['message'])
    _require(result.get('canvas') == request['canvas'],
             'condition_canvas', 'Compiled condition must retain the explicit A canvas')
    _require(_text(result.get('edit_prompt')),
             'condition_result', 'Final native edit_prompt is empty')
    _validate_observation(request, result.get('compiler_observation'))
    profile = get_model_profile(request['profile_id'])
    if request['profile_id'] == 'fibo2_dev':
        try:
            native = json.loads(result['edit_prompt'])
            _json(native, 'condition_native_output')
        except (ValueError, TypeError) as exc:
            raise HREError('condition_native_output', 'Fibo edit_prompt must be native JSON') from exc
        _require(isinstance(native, dict) and _text(native.get('edit_instruction')),
                 'condition_native_output', 'Fibo VGL requires a nonempty edit_instruction')
    if request['profile_id'] == 'qwen21' and request['compiler'] == 'native':
        native = result.get('native_output')
        _require(isinstance(native, dict) and native.get('parse_ok') is True,
                 'condition_native_output', 'Qwen PE-I2I output must parse successfully')
        # The official value is <image1>; accept the unbracketed transport form.
        _require(native.get('ratio_follow') in ('image1', '<image1>')
                 and 'wh_ratio' in native and native['wh_ratio'] in ('', None),
                 'condition_native_output', 'Qwen PE must follow image1=A without a ratio override')
        _require(_text(native.get('positive_prompt'))
                 and native['positive_prompt'] == result['edit_prompt'],
                 'condition_native_output', 'edit_prompt must exactly match the actual Qwen PE positive_prompt')
    kind = profile['condition_kind']
    _require('condition_kind' not in result or result['condition_kind'] == kind,
             'condition_result', 'Condition kind differs from the model profile')
    return {**deepcopy(result), 'condition_kind': kind}


def _intent_instructions(intent):
    """Render only explicit human-readable goals, never diagnostics or metrics."""
    def phrase(value):
        return ' '.join(value.split()) if _text(value) else None

    pairs = intent.get('roi_pairs', [])
    labels = {pair['roi_pair_id']: phrase(pair['semantic_label']) for pair in pairs
              if isinstance(pair, dict) and _text(pair.get('roi_pair_id'))
              and _text(pair.get('semantic_label'))} if isinstance(pairs, list) else {}

    def roi_label(value):
        return labels.get(value) if isinstance(value, str) else None

    lines = []
    targets = intent.get('targets', [])
    if isinstance(targets, list):
        for target in targets:
            if not isinstance(target, dict):
                continue
            operation = phrase(target.get('operation')) or phrase(target.get('direction'))
            target_state = phrase(target.get('target_state'))
            if not operation and not target_state:
                continue
            # ROI/target IDs are audit identities, not a semantic localization.
            region = next((phrase(target.get(k)) for k in ('semantic_label', 'region', 'region_name')
                           if phrase(target.get(k))), None)
            region = region or roi_label(target.get('roi_pair_id'))
            scope = region or ('whole image' if target.get('scope') == 'global'
                               else 'the local region specified in the brief')
            dimension = phrase(target.get('dimension'))
            if operation:
                attribute = ' (' + dimension.replace('_', ' ') + ')' if dimension else ''
                lines.append(f'- {scope}{attribute}: {operation}.')
            if target_state:
                lines.append(f'- Desired appearance in {scope}: {target_state}')
            preserve = target.get('preserve', [])
            if isinstance(preserve, list):
                preserved = [phrase(x) for x in preserve if phrase(x)]
                if preserved:
                    lines.append(f'- Preserve in {scope}: ' + ', '.join(preserved) + '.')

    relations = intent.get('region_relations', [])
    if isinstance(relations, list):
        for relation in relations:
            if not isinstance(relation, dict):
                continue
            subject = phrase(relation.get('subject')) or roi_label(relation.get('subject_roi_id'))
            other = phrase(relation.get('object')) or roi_label(relation.get('object_roi_id'))
            target = phrase(relation.get('target'))
            # A statistics source or an untyped numeric object is not a target.
            # No EV/L* amount or relational direction is inferred here.
            if not (subject and other and target):
                continue
            attribute = phrase(relation.get('attribute'))
            label = ' (' + attribute.replace('_', ' ') + ')' if attribute else ''
            lines.append(f'- Relation between {subject} and {other}{label}: {target}')

    protected = intent.get('protected_content', [])
    if isinstance(protected, list):
        for entry in protected:
            instruction = phrase(entry.get('instruction')) if isinstance(entry, dict) else phrase(entry)
            if instruction:
                lines.append('- ' + instruction)
    return '\n'.join(lines)


def compile_direct_condition(request: dict) -> dict:
    """Render an executable Qwen/FireRed instruction without a model call.

    This is a deterministic HarnessIR baseline, not PE-I2I or Recaption.  The
    native compiler paths remain external and are never simulated here.
    """
    _validate_request(request)
    _require(request['compiler'] == 'direct', 'condition_compiler',
             'The native compiler must run externally; no native output is synthesized')
    parts = [
        'Edit image A (the first image). Use image B (the second image) only as an '
        'appearance reference. Keep A as the source of scene contents, identity, '
        'text, framing and geometry.',
        request['brief'],
    ]
    if request['strategy'] != 'native':
        if request['strategy'] == 'shared':
            parts.append('Apply the following frozen appearance goals in their listed order.')
        elif request['profile_id'] == 'qwen21':
            parts.append(
                'Apply the following appearance goals together. Maintain the stated '
                'subject/background relationships while changing the permitted brightness '
                'and colors. Keep the recorded scene illumination and preservation '
                'constraints consistent across regions; do not resolve uncertainty by '
                'inventing detail.')
        else:
            parts.append(
                'Make one coherent full-frame appearance edit using the following goals. '
                'Retain the specified relationships between local changes and the whole '
                'scene, and preserve fine structures and text under the stated constraints.')
        goals = _intent_instructions(request['intent'])
        if goals:
            parts.append(goals)
    parts.append(
        'Return the edited A at its original canvas dimensions. Do not transfer '
        'objects or composition from B. Perform the requested full-frame edit without '
        'cropping, adding an editor mask, or creating a new scene.')
    result = dict(
        schema_version=RESULT_VERSION, request_id=request['request_id'],
        profile_id=request['profile_id'], status='ok', edit_prompt='\n\n'.join(parts),
        canvas=deepcopy(request['canvas']),
        compiler_observation=dict(
            compiler_id='hre-direct', compiler_version='1', calls=0,
            settings=dict(strategy=request['strategy'], profile_id=request['profile_id'],
                          rendering='deterministic')))
    return validate_compiled_condition(request, result)
