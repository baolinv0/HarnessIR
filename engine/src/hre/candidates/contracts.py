from copy import deepcopy
from hashlib import sha256
import re
from urllib.parse import urlsplit

from hre.models import HREError, canonical_json

VERSION = 'hre_candidates_v1'


def require(condition, code, message):
    if not condition:
        raise HREError(code, message)


def digest(value):
    try:
        return sha256(canonical_json(value)).hexdigest()
    except (TypeError, ValueError) as exc:
        raise HREError('invalid_contract', 'JSON values must be finite and serializable') from exc


def text_hash(text):
    require(isinstance(text, str), 'invalid_prompt', 'Prompt must be text')
    return sha256(text.encode('utf-8')).hexdigest()


def seal(value):
    result = deepcopy(value)
    result.pop('freeze_hash', None)
    result['freeze_hash'] = digest(result)
    return result


def verify_seal(value):
    expected = value.get('freeze_hash')
    require(isinstance(expected, str) and seal(value)['freeze_hash'] == expected,
            'freeze_modified', 'Frozen record changed')


def _keys(value, allowed, name):
    require(isinstance(value, dict), 'invalid_contract', name + ' must be an object')
    require(not set(value) - set(allowed), 'unknown_field', name + ' has unknown fields: ' + str(sorted(set(value) - set(allowed))))
    digest(value)


def parse_task(value):
    _keys(value, {'schema_version', 'case_id', 'source', 'task_mode', 'scale', 'usage_policy',
                  'user_intent', 'critical_attributes', 'rois', 'task_types'}, 'TaskSpec')
    task = deepcopy(value)
    task.setdefault('schema_version', VERSION)
    require(task['schema_version'] == VERSION, 'schema_version_invalid', 'Use hre_candidates_v1')
    require(isinstance(task.get('case_id'), str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', task['case_id']), 'case_id_invalid', 'Use a simple case ID')
    source = task.get('source')
    if isinstance(source, str):
        source = {'path': source}
    _keys(source, {'path'}, 'source')
    require(isinstance(source.get('path'), str) and bool(source['path']), 'source_missing', 'Supply an image path')
    task['source'] = source
    task.setdefault('task_mode', 'restoration_x1')
    require(task['task_mode'] in {'restoration_x1', 'sr_x4'}, 'task_mode_invalid', 'Use restoration_x1 or sr_x4')
    scale = 4 if task['task_mode'] == 'sr_x4' else 1
    require(task.get('scale', scale) == scale, 'scale_mismatch', 'Scale must match task_mode')
    task['scale'] = scale
    task.setdefault('usage_policy', 'photo_restoration')
    require(task['usage_policy'] in {'photo_restoration', 'information_critical'}, 'usage_policy_invalid', 'Unknown usage policy')
    task.setdefault('user_intent', None)
    require(task['user_intent'] is None or isinstance(task['user_intent'], str), 'intent_invalid', 'Intent must be text or null')
    task.setdefault('task_types', ['mix'])
    require(isinstance(task['task_types'], list) and task['task_types'] and all(isinstance(x, str) and x for x in task['task_types']), 'task_types_invalid', 'Supply task type names')
    task.setdefault('rois', [])
    require(isinstance(task['rois'], list), 'roi_invalid', 'rois must be a list')
    roi_ids = []
    for roi in task['rois']:
        _keys(roi, {'id', 'semantic_type', 'box', 'importance', 'provenance', 'availability', 'key_attributes'}, 'ROI')
        require(isinstance(roi.get('id'), str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', roi['id']), 'roi_invalid', 'ROI ID must be stable')
        roi.setdefault('semantic_type', 'other')
        require(roi['semantic_type'] in {'person', 'text', 'building', 'grass', 'other'}, 'roi_invalid', 'Unknown ROI type')
        box = roi.get('box')
        require(isinstance(box, list) and len(box) == 4 and all(type(x) is int for x in box) and 0 <= box[0] < box[2] and 0 <= box[1] < box[3], 'roi_invalid', 'Use integer LQ [x0,y0,x1,y1) coordinates')
        roi.setdefault('importance', 'high')
        roi.setdefault('provenance', 'input_annotation')
        roi_ids.append(roi['id'])
    require(len(roi_ids) == len(set(roi_ids)), 'duplicate_id', 'ROI IDs must be unique')
    task.setdefault('critical_attributes', [])
    require(isinstance(task['critical_attributes'], list), 'attribute_invalid', 'critical_attributes must be a list')
    if task['usage_policy'] == 'information_critical':
        for roi in task['rois']:
            content_attribute = {'person': 'identity', 'text': 'text_content'}.get(roi['semantic_type'])
            if content_attribute and not any(x.get('region_selector') == roi['id'] and x.get('attribute') == content_attribute for x in task['critical_attributes']):
                task['critical_attributes'].append({'attribute_id': roi['id'] + '_' + content_attribute,
                                                    'region_selector': roi['id'], 'attribute': content_attribute,
                                                    'required_for_acceptance': True, 'verification_requirement': 'verified_content'})
        require(bool(task['critical_attributes']), 'attribute_policy_missing', 'Information-critical tasks must declare required content attributes or person/text ROIs')
    ids = []
    for item in task['critical_attributes']:
        _keys(item, {'attribute_id', 'region_selector', 'attribute', 'required_for_acceptance', 'verification_requirement', 'allow_unverifiable'}, 'CriticalAttribute')
        for key in ('attribute_id', 'region_selector', 'attribute'):
            require(isinstance(item.get(key), str) and bool(item[key]), 'attribute_invalid', 'Missing ' + key)
        item.setdefault('required_for_acceptance', True)
        item.setdefault('verification_requirement', 'visible_consistency')
        item.setdefault('allow_unverifiable', False)
        require(type(item['required_for_acceptance']) is bool and type(item['allow_unverifiable']) is bool, 'attribute_invalid', 'Policy flags must be booleans')
        require(item['verification_requirement'] in {'visible_consistency', 'verified_content'}, 'attribute_invalid', 'Unknown verification requirement')
        if task['usage_policy'] == 'information_critical':
            item.update(required_for_acceptance=True, verification_requirement='verified_content', allow_unverifiable=False)
        if item['verification_requirement'] == 'verified_content':
            item['required_for_acceptance'] = True
            item['allow_unverifiable'] = False
        ids.append(item['attribute_id'])
    require(len(ids) == len(set(ids)), 'duplicate_id', 'Attribute IDs must be unique')
    return task


def parse_config(value):
    _keys(value, {'schema_version', 'mode', 'harness_source_root', 'harness_sha', 'stages', 'editor',
                  'budgets', 'review', 'fixture', 'experiment', 'seed_schedule', 'tie_order'}, 'RuntimeConfig')
    config = deepcopy(value)
    config.setdefault('schema_version', VERSION)
    require(config['schema_version'] == VERSION, 'schema_version_invalid', 'Use hre_candidates_v1')
    require(config.get('mode') in {'fixture', 'real'}, 'mode_invalid', 'Explicit mode fixture or real is required')
    config.setdefault('harness_source_root', None)
    config.setdefault('harness_sha', 'd44d40fa209a9978d37ce38efa9a6ef89abe7432')
    config.setdefault('stages', {})
    _keys(config['stages'], {'diagnoser', 'composer', 'planner', 'rewriter', 'audit', 'judge'}, 'stages')
    for name, endpoint in config['stages'].items():
        require(isinstance(endpoint, dict), 'config_invalid', name + ' endpoint must be an object')
        require(not set(endpoint) & {'api_key', 'authorization', 'password', 'token'}, 'credential_forbidden', 'Store credential environment-variable names only')
        _keys(endpoint, {'base_url', 'model', 'api_key_env', 'timeout_seconds', 'settings', 'response_format'}, name + ' endpoint')
        if endpoint.get('base_url'):
            parsed = urlsplit(endpoint['base_url'])
            require(parsed.scheme in {'http', 'https'} and parsed.netloc and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment,
                    'credential_or_endpoint_invalid', 'Endpoint URL must not contain credentials, queries or fragments')
        require(endpoint.get('api_key_env') is None or isinstance(endpoint['api_key_env'], str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', endpoint['api_key_env']), 'credential_env_invalid', 'Use an environment-variable name for credentials')
        _keys(endpoint.get('settings', {}), {'temperature', 'top_p', 'max_tokens', 'seed', 'frequency_penalty', 'presence_penalty'}, name + ' settings')
    config.setdefault('fixture', {})
    config.setdefault('experiment', {})
    _keys(config['experiment'], {'e1_ab', 'e2_manifest_path'}, 'experiment')
    config['experiment'] = {'e1_ab': False, 'e2_manifest_path': None, **config['experiment']}
    require(type(config['experiment']['e1_ab']) is bool, 'config_invalid', 'e1_ab must be boolean')
    editor = config.setdefault('editor', {})
    _keys(editor, {'model_id', 'local_path', 'revision', 'deployment_manifest', 'pipeline_version', 'device', 'torch_dtype', 'settings', 'worker', 'adapter_version', 'verify_weight_hashes'}, 'editor')
    for key, val in {'model_id': 'Qwen/Qwen-Image-2.1', 'local_path': None, 'revision': None, 'pipeline_version': None, 'device': 'cuda:0', 'torch_dtype': 'bfloat16'}.items():
        editor.setdefault(key, val)
    require(editor['model_id'] == 'Qwen/Qwen-Image-2.1', 'model_identity_mismatch', 'First round uses only Qwen-Image-2.1')
    settings = editor.setdefault('settings', {})
    defaults = {'num_inference_steps': 40, 'true_cfg_scale': 1.0, 'negative_prompt': '', 'num_images_per_prompt': 1, 'output_resolution': 1024, 'use_kv_cache': True}
    _keys(settings, set(defaults), 'editor.settings')
    editor['settings'] = {**defaults, **settings}
    settings = editor['settings']
    require(type(settings['num_inference_steps']) is int and settings['num_inference_steps'] > 0 and type(settings['output_resolution']) is int and settings['output_resolution'] > 0, 'config_invalid', 'Steps and resolution must be positive integers')
    require(type(settings['true_cfg_scale']) in {float, int} and settings['true_cfg_scale'] > 0 and settings['num_images_per_prompt'] == 1 and type(settings['use_kv_cache']) is bool, 'config_invalid', 'Invalid generation settings')
    config.setdefault('seed_schedule', [0, 1, 2, 3])
    require(isinstance(config['seed_schedule'], list) and len(config['seed_schedule']) == 4 and all(type(x) is int and 0 <= x < 2**63 for x in config['seed_schedule']), 'seed_schedule_invalid', 'Freeze four integer seeds')
    config.setdefault('tie_order', ['C0', 'CF', 'CT', 'CFT'])
    require(isinstance(config['tie_order'], list) and len(set(config['tie_order'])) == len(config['tie_order']), 'tie_order_invalid', 'Tie order must be unique')
    review = config.setdefault('review', {})
    _keys(review, {'max_rois_per_package', 'max_images_per_call', 'max_judge_calls', 'max_output_tokens'}, 'review')
    review = {'max_rois_per_package': 6, 'max_images_per_call': 64, 'max_output_tokens': 8192, **review}
    review['max_judge_calls'] = {'J0': 3, 'J1': 3, 'J2': 7, **review.get('max_judge_calls', {})}
    for key in ('max_rois_per_package', 'max_images_per_call', 'max_output_tokens'):
        require(type(review[key]) is int and review[key] > 0, 'config_invalid', key + ' must be positive')
    require(all(k in {'J0', 'J1', 'J2'} and type(v) is int and v >= 0 for k, v in review['max_judge_calls'].items()), 'config_invalid', 'Invalid Judge budgets')
    config['review'] = review
    limits = {'image_generation': 7, 'diagnosis': 1, 'compose': 2, 'planner': 1, 'rewriter': 2, 'audit': 2, 'tool': 6}
    for variant, count in review['max_judge_calls'].items():
        limits.update({f'judge_{variant}_primary': 4 if variant == 'J2' else max(1, count - 2), f'judge_{variant}_aggregate': max(1, count - 2), f'judge_{variant}_dispute': 1, f'judge_{variant}_format_repair': 1, f'judge_{variant}_total': count})
    supplied = config.setdefault('budgets', {})
    _keys(supplied, set(limits), 'budgets')
    limits.update(supplied)
    require(all(type(x) is int and x >= 0 for x in limits.values()), 'budget_invalid', 'Call limits must be nonnegative integers')
    config['budgets'] = limits
    digest(config)
    return config


def candidate_spec(slot_id, strategy_id, sample_index, seed, full_prompt, source_hash,
                   issue_refs=None, expected_effect=None, evaluation_axis_id=None):
    require(isinstance(full_prompt, str) and full_prompt.strip(), 'invalid_prompt', 'Complete prompt is required')
    require(type(seed) is int and 0 <= seed < 2**63 and type(sample_index) is int and sample_index >= 0, 'candidate_invalid', 'Invalid sample index or seed')
    require(isinstance(source_hash, str) and re.fullmatch('[0-9a-f]{64}', source_hash), 'source_hash_invalid', 'Supply canonical source SHA-256')
    return {'schema_version': VERSION, 'candidate_id': f'{strategy_id}_s{sample_index}_seed{seed}',
            'slot_id': slot_id, 'strategy_id': strategy_id, 'planned_strategy_id': strategy_id,
            'effective_strategy_id': strategy_id, 'sample_index': sample_index, 'seed': seed,
            'full_prompt': full_prompt, 'prompt_hash': text_hash(full_prompt), 'source_hash': source_hash,
            'issue_refs': deepcopy(issue_refs or []), 'expected_effect': deepcopy(expected_effect or []),
            'evaluation_axis_id': evaluation_axis_id, 'dependency_ids': []}
