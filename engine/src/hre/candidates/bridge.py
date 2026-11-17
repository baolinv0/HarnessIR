from copy import deepcopy
import importlib
import importlib.metadata
import importlib.util
import io
from pathlib import Path
import re
import shutil
import subprocess
import sys

from PIL import Image, ImageCms, ImageFilter, ImageOps

from hre.models import HREError, file_sha256
from hre.storage import atomic_write, read_json, write_json
from .contracts import VERSION, digest, require, text_hash
from .transport import call_json, validate_endpoint


def _save_png(path, image):
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    atomic_write(Path(path), buffer.getvalue())


def canonicalize_source(path, directory):
    path, directory = Path(path).resolve(), Path(directory).resolve()
    require(path.is_file(), 'source_missing', 'Source image is missing')
    directory.mkdir(parents=True, exist_ok=True)
    original_hash = file_sha256(path)
    original_path = directory / 'source.original'
    atomic_write(original_path, path.read_bytes())
    require(file_sha256(original_path) == original_hash == file_sha256(path), 'source_modified', 'Source changed during import')
    with Image.open(original_path) as image:
        image.load()
        require(image.mode in {'RGB', 'RGBA', 'L', 'LA', 'P', 'CMYK'}, 'source_format_invalid', 'Prepare HDR and high-bit-depth input explicitly')
        image = ImageOps.exif_transpose(image)
        if image.mode in {'RGBA', 'LA'} or 'transparency' in image.info:
            require(image.convert('RGBA').getchannel('A').getextrema() == (255, 255), 'source_alpha_unsupported', 'Transparent input needs an explicit conversion workflow')
        profile = image.info.get('icc_profile')
        require(image.mode != 'CMYK' or profile, 'source_colour_unknown', 'CMYK input requires an ICC profile')
        colour_operation = 'assumed_srgb'
        if profile:
            try:
                original_profile = ImageCms.ImageCmsProfile(io.BytesIO(profile))
                base = image if image.mode in {'RGB', 'CMYK', 'L'} else image.convert('RGB')
                canonical = ImageCms.profileToProfile(base, original_profile, ImageCms.createProfile('sRGB'), outputMode='RGB')
                colour_operation = 'icc_to_srgb'
            except (OSError, ValueError, ImageCms.PyCMSError) as exc:
                raise HREError('source_icc_invalid', 'Input ICC profile cannot be interpreted') from exc
        else:
            canonical = image.convert('RGB')
        canonical_path = directory / 'source.png'
        _save_png(canonical_path, canonical)
        result = {'path': str(canonical_path), 'sha256': file_sha256(canonical_path),
                  'width': canonical.width, 'height': canonical.height, 'mode': 'RGB',
                  'original_path': str(original_path), 'original_sha256': original_hash,
                  'canonicalization': {'exif_transpose': True, 'colour_operation': colour_operation, 'alpha_policy': 'require_opaque'}}
    result['canonical_source_sha256'] = result['sha256']
    return result


def prepare_source(source, task, directory):
    import numpy as np
    require(file_sha256(Path(source['path'])) == source['sha256'], 'source_modified', 'Canonical source changed')
    mode = task['task_mode']
    require(mode in {'restoration_x1', 'sr_x4'}, 'task_mode_invalid', 'Unknown candidates geometry')
    scale, grid = (4, 8) if mode == 'sr_x4' else (1, 32)
    require(task.get('scale', scale) == scale, 'scale_mismatch', 'Scale and mode disagree')
    width, height = source['width'], source['height']
    padded_width, padded_height = ((width + grid - 1) // grid * grid, (height + grid - 1) // grid * grid)
    with Image.open(source['path']) as image:
        require(image.size == (width, height), 'source_modified', 'Canonical source dimensions changed')
        pixels = np.asarray(image.convert('RGB'))
        padded = np.pad(pixels, ((0, padded_height - height), (0, padded_width - width), (0, 0)), mode='edge')
    geometry = {'mode': mode, 'scale': scale, 'width': width, 'height': height,
                'padded_width': padded_width, 'padded_height': padded_height,
                'canvas_width': scale * padded_width, 'canvas_height': scale * padded_height,
                'pad_mode': 'edge', 'pad': [0, 0, padded_width - width, padded_height - height],
                'crop': [0, 0, scale * width, scale * height], 'projection': [[scale, 0, 0], [0, scale, 0], [0, 0, 1]]}
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'prepared.png'
    _save_png(path, Image.fromarray(padded))
    return {'source': deepcopy(source), 'path': str(path), 'sha256': file_sha256(path),
            'prepared_source_sha256': file_sha256(path), 'geometry': geometry, 'geometry_sha256': digest(geometry)}


def _editor_config(editor):
    result = deepcopy(editor)
    defaults = {'num_inference_steps': 40, 'true_cfg_scale': 1.0, 'negative_prompt': '',
                'num_images_per_prompt': 1, 'output_resolution': 1024, 'use_kv_cache': True}
    supplied = result.get('settings', {})
    require(not set(supplied) - set(defaults), 'editor_settings_invalid', 'Unknown Qwen setting')
    result['settings'] = {**defaults, **supplied}
    for key, value in {'model_id': 'Qwen/Qwen-Image-2.1', 'local_path': None, 'revision': None,
                       'pipeline_version': None, 'device': 'cuda:0', 'torch_dtype': 'bfloat16'}.items():
        result.setdefault(key, value)
    require(result['model_id'] == 'Qwen/Qwen-Image-2.1' and result['settings']['num_images_per_prompt'] == 1,
            'model_identity_mismatch', 'Use one fixed original Qwen-Image-2.1 image per invocation')
    digest(result)
    return result


def build_execution(spec, prepared, editor):
    spec, prepared = deepcopy(spec), deepcopy(prepared)
    require(spec.get('prompt_hash') == text_hash(spec['full_prompt']), 'prompt_modified', 'Candidate prompt hash differs')
    require(spec['source_hash'] == prepared['source']['canonical_source_sha256'], 'source_binding_mismatch', 'Plan and prepared source differ')
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', spec['candidate_id']), 'candidate_id_invalid', 'Unsafe candidate ID')
    geometry = prepared['geometry']
    request = {'schema_version': 'hre_model_request_v3', 'profile_id': 'qwen21', 'task_mode': 'restoration',
               'strategy': 'native', 'intent': None, 'seed': spec['seed'], 'brief': spec['full_prompt'],
               'inputs': [{'role': 'source', 'path': prepared['path'], 'sha256': prepared['prepared_source_sha256'],
                           'width': geometry['padded_width'], 'height': geometry['padded_height'], 'mode': 'RGB'}],
               'canvas': {'width': geometry['canvas_width'], 'height': geometry['canvas_height']}, 'spatial': {'mode': 'full_frame'}}
    expanded_editor = _editor_config(editor)
    deployment = expanded_editor.get('deployment_manifest')
    deployment_hash = file_sha256(Path(deployment)) if deployment and Path(deployment).is_file() else None
    manifest = {'schema_version': VERSION, 'spec': spec, 'request': request, 'editor': expanded_editor,
                'prepared': prepared, 'condition_text_sha256': spec['prompt_hash'], 'deployment_manifest_sha256': deployment_hash}
    manifest['execution_manifest_sha256'] = digest(manifest)
    return manifest


def _validate_execution(manifest, config):
    expected = manifest.get('execution_manifest_sha256')
    content = {key: value for key, value in manifest.items() if key != 'execution_manifest_sha256'}
    require(expected == digest(content), 'execution_manifest_mismatch', 'Frozen execution content changed before submission')
    rebuilt = build_execution(manifest['spec'], manifest['prepared'], manifest['editor'])
    require(rebuilt == manifest, 'execution_manifest_mismatch', 'Request differs from its frozen planning inputs')
    prepared = manifest['prepared']
    require(digest(prepared['geometry']) == prepared['geometry_sha256'], 'execution_manifest_mismatch', 'Geometry mapping changed')
    for path, expected_hash in [(prepared['path'], prepared['prepared_source_sha256']),
                                (prepared['source']['path'], prepared['source']['canonical_source_sha256'])]:
        require(Path(path).is_file() and file_sha256(Path(path)) == expected_hash, 'execution_manifest_mismatch', 'Bound source bytes changed before submission')
    if 'editor' in config:
        require(_editor_config(config['editor']) == manifest['editor'], 'execution_manifest_mismatch', 'Effective editor settings changed')
    if config.get('mode') == 'real':
        require(manifest.get('deployment_manifest_sha256'), 'deployment_manifest_missing', 'Real execution requires a frozen local deployment manifest')
        from hre.v3.common import model_identity
        model_identity(manifest['editor'], 'Qwen/Qwen-Image-2.1')
    with Image.open(prepared['path']) as image:
        require(image.size == (prepared['geometry']['padded_width'], prepared['geometry']['padded_height']),
                'execution_manifest_mismatch', 'Prepared source dimensions changed')


def execute_image(manifest, root, journal, config, partition='E1'):
    _validate_execution(manifest, config)
    require(config.get('mode') in {'fixture', 'real'}, 'mode_invalid', 'Declare fixture or real execution')
    require(isinstance(partition, str) and re.fullmatch(r'[A-Za-z0-9_.-]+', partition), 'partition_invalid', 'Invalid experiment partition')
    root = Path(root).resolve()
    spec, prepared = manifest['spec'], manifest['prepared']
    candidate_id = spec['candidate_id']
    directory = root / ('candidates' if partition == 'E1' else partition) / candidate_id
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = root / 'execution_manifests' / (partition + '_' + candidate_id + '.json')
    if manifest_path.exists():
        require(read_json(manifest_path) == manifest, 'execution_manifest_mismatch', 'Stored execution manifest differs')
    else:
        write_json(manifest_path, manifest)
    from hre.v3.dispatch import seal_condition
    condition = seal_condition(manifest['request'], {'backend': 'direct'},
                               {'text': spec['full_prompt'], 'condition_kind': 'semantic_instruction', 'native_output': None,
                                'observation': {'compiler_id': 'candidates_prompt_passthrough_v1', 'calls_attempted': 0,
                                                'calls_completed': 0, 'fallback_used': False}, 'warnings': []})
    require(condition['text_sha256'] == manifest['condition_text_sha256'], 'prompt_modified', 'Dispatch changed full prompt bytes')
    write_json(directory / 'request.json', manifest['request'])
    write_json(directory / 'condition.json', condition)
    geometry = prepared['geometry']
    def invoke():
        _validate_execution(manifest, config)
        if config['mode'] == 'real':
            from hre.v3.dispatch import generate
            return generate(manifest['request'], condition, manifest['editor'], directory / 'native')
        behaviors = config.get('fixture', {}).get('image_behaviors', {})
        behavior = behaviors.get(candidate_id, behaviors.get(spec['slot_id'], behaviors.get(spec['strategy_id'], 'normal')))
        require(behavior in {'normal', 'duplicate', 'wrong_size', 'failed', 'unknown', 'sharpen', 'smooth'}, 'fixture_behavior_invalid', 'Unknown scripted image behavior')
        if behavior == 'failed':
            raise HREError('fixture_generation_failed', 'Scripted fixture generation failure')
        if behavior == 'unknown':
            raise TimeoutError('Scripted fixture response loss')
        size = (geometry['canvas_width'], geometry['canvas_height'])
        if behavior == 'wrong_size':
            size = (size[0] - 1, size[1])
        with Image.open(prepared['path']) as source_image:
            image = source_image.convert('RGB').resize(size, Image.Resampling.LANCZOS)
        if behavior == 'sharpen':
            image = image.filter(ImageFilter.UnsharpMask(radius=1, percent=100, threshold=2))
        if behavior == 'smooth':
            image = image.filter(ImageFilter.GaussianBlur(radius=0.6))
        native_path = directory / 'native' / 'native_000.png'
        _save_png(native_path, image)
        return {'outputs': [{'path': str(native_path), 'sha256': file_sha256(native_path), 'width': image.width,
                             'height': image.height, 'mode': 'RGB', 'provider_order': 0}],
                'observation': {'fixture_only': True, 'actual_generation_count': 1,
                                'implementation': 'cpu_fixture_interpolation_not_a_model', 'behavior': behavior}}
    raw = journal.invoke(partition + '/image/' + candidate_id, 'image_generation',
                         {'mode': config['mode'], 'execution_manifest_sha256': manifest['execution_manifest_sha256'], 'manifest': manifest}, invoke)
    outputs = raw.get('outputs', [])
    require(len(outputs) == 1 and raw.get('observation', {}).get('actual_generation_count') == 1, 'generation_count_mismatch', 'Exactly one native image is required')
    native = outputs[0]
    native_path = Path(native['path']).resolve()
    require(native_path.is_relative_to(directory) and native_path.is_file() and file_sha256(native_path) == native['sha256'],
            'native_output_modified', 'Native output path or bytes differ from the saved response')
    with Image.open(native_path) as image:
        image.load()
        require(image.size == (geometry['canvas_width'], geometry['canvas_height']), 'native_geometry_invalid', 'Wrong native dimensions cannot be fixed by resizing')
        require(image.mode in {'RGB', 'RGBA'}, 'native_format_invalid', 'Native output must be eight-bit RGB or opaque RGBA')
        if image.mode == 'RGBA':
            require(image.getchannel('A').getextrema() == (255, 255), 'native_alpha_invalid', 'Native output contains unsupported transparency')
        delivered = image.convert('RGB').crop(tuple(geometry['crop']))
        delivered_path = directory / 'delivered.png'
        _save_png(delivered_path, delivered)
    receipt = {'schema_version': VERSION, 'candidate_id': candidate_id, 'fixture_only': config['mode'] == 'fixture',
               'canonical_source_sha256': prepared['source']['canonical_source_sha256'],
               'prepared_source_sha256': prepared['prepared_source_sha256'], 'geometry_sha256': prepared['geometry_sha256'],
               'condition_text_sha256': manifest['condition_text_sha256'], 'execution_manifest_sha256': manifest['execution_manifest_sha256'],
               'editor_config_sha256': digest(manifest['editor']), 'execution_request_sha256': digest(manifest['request']),
               'deployment_manifest_sha256': manifest.get('deployment_manifest_sha256'),
               'native_sha256': native['sha256'], 'delivered_sha256': file_sha256(delivered_path),
               'seed': spec['seed'], 'observation': raw.get('observation', {}), 'cost_status': 'unknown'}
    write_json(directory / 'receipt.json', receipt)
    return {'schema_version': VERSION, 'candidate_id': candidate_id, 'status': 'completed', 'native_image': str(native_path),
            'delivered_image': str(delivered_path), 'native_sha256': native['sha256'], 'sha256': receipt['delivered_sha256'],
            'width': delivered.width, 'height': delivered.height, 'receipt': receipt,
            'manifest_sha256': manifest['execution_manifest_sha256'], 'manifest_path': str(manifest_path)}


class _StageClient:
    def __init__(self, root, config, journal, kind):
        self.root, self.config, self.journal, self.kind = root, config, journal, kind
        self.index = 0

    def chat_json(self, user, images=None, *, system=''):
        _verify_harness_identity(self.config)
        operation_id = 'E1/baseline/' + self.kind + '/' + str(self.index)
        self.index += 1
        return call_json(self.root, self.config, self.journal, operation_id, self.kind, user, images or [], system=system)


def compose_baseline(root, task, config, journal, source):
    root = Path(root).resolve()
    require(file_sha256(Path(source['path'])) == source['canonical_source_sha256'], 'source_modified', 'Canonical source changed before baseline')
    if config.get('mode') == 'fixture':
        diagnosis = call_json(root, config, journal, 'E1/baseline/diagnosis/0', 'diagnosis',
                              'Synthetic baseline diagnosis fixture', [source['path']], fixture_response={'content': 'synthetic fixture', 'tool_plan': []})
        baseline_prompt = config.get('fixture', {}).get('baseline_prompt', 'Restore the visible source while preserving expression, confirmed text and geometry.')
        require(isinstance(baseline_prompt, str) and baseline_prompt.strip(), 'fixture_prompt_invalid', 'Fixture baseline prompt must be explicit nonempty text')
        composed = call_json(root, config, journal, 'E1/baseline/compose/0', 'compose',
                             'Synthetic baseline composition fixture', [source['path']], fixture_response={'prompt': baseline_prompt})
        result = {'P0': composed['prompt'], 'prompt_hash': text_hash(composed['prompt']), 'diagnosis': diagnosis,
                  'tool_evidence': {'unavailable': ['fixture has no real perception tools']},
                  'visual_pack': {'paths': [source['path']]}, 'fixture_only': True}
    else:
        _verify_harness_identity(config)
        harness_root = Path(config.get('harness_source_root') or '').resolve()
        require((harness_root / 'harness' / '__init__.py').is_file(), 'harness_source_missing', 'Set the complete harness source root')
        if str(harness_root) not in sys.path:
            sys.path.insert(0, str(harness_root))
        package = importlib.import_module('harness')
        require(Path(package.__file__).resolve().is_relative_to(harness_root), 'harness_import_mismatch', 'harness imported from another source checkout')
        from harness.stages.diagnosis import run_diagnosis
        from harness.stages.compose import run_compose
        from harness.stages.tools import ToolEvidence, _RUNNERS
        from harness.stages.visuals import build_visual_pack, render_text_evidence
        diagnosis_object = run_diagnosis(_StageClient(root, config, journal, 'diagnosis'), source['path'],
                                         user_intent=task.get('user_intent'), task_type='+'.join(task.get('task_types', ['mix'])))
        requested = diagnosis_object.requested_tools
        require(len(requested) <= config['budgets']['tool'], 'budget_exhausted', 'Tool plan exceeds the frozen call budget')
        evidence_object = ToolEvidence()
        targets = {'T1_OCR': 'ocr', 'T2_FACE': 'faces', 'T3_DEPTH': 'depth', 'T4_SEGMENTATION': 'segmentation'}
        for index, name in enumerate(requested):
            require(name in _RUNNERS, 'tool_invalid', 'Unknown original harness tool')
            try:
                outcome = journal.invoke('E1/baseline/tool/' + str(index) + '_' + name, 'tool',
                                         {'tool': name, 'source_sha256': source['sha256']},
                                         lambda tool=name: {'result': _RUNNERS[tool](Path(source['path']), root / 'baseline' / 'tools')})
                if outcome['result'] is None:
                    evidence_object.unavailable.append(name + ': unavailable')
                else:
                    setattr(evidence_object, targets[name], outcome['result'])
            except HREError as exc:
                if exc.code == 'operation_unknown':
                    raise
                evidence_object.unavailable.append(name + ': ' + exc.code)
        tool_evidence = evidence_object.to_dict()
        pack = build_visual_pack(source['path'], tool_evidence, root / 'baseline' / 'visual_pack')
        composition = run_compose(_StageClient(root, config, journal, 'compose'), task.get('task_types', ['mix']),
                                  diagnosis_object.to_dict(), render_text_evidence(tool_evidence, pack), pack, task.get('user_intent'))
        result = {'P0': composition.prompt, 'prompt_hash': text_hash(composition.prompt), 'diagnosis': diagnosis_object.to_dict(),
                  'tool_evidence': tool_evidence, 'visual_pack': pack.to_dict(), 'composition': composition.to_dict(), 'fixture_only': False}
    directory = root / 'baseline'
    write_json(directory / 'context.json', result)
    atomic_write(directory / 'P0.txt', result['P0'].encode('utf-8'))
    return result


def _verify_harness_identity(config):
    root = Path(config.get('harness_source_root') or '').resolve()
    expected_sha = config.get('harness_sha')
    require(isinstance(expected_sha, str) and re.fullmatch(r'[0-9a-f]{40}', expected_sha), 'harness_identity_invalid', 'Freeze the source baseline commit')
    required_files = {'harness/stages/diagnosis.py', 'harness/stages/compose.py', 'harness/stages/tools.py', 'harness/stages/visuals.py',
                      'prompts/diagnosis.txt', 'prompts/compose.txt', 'prompts/compose_blocks.txt'}
    manifest_path = root / 'SOURCE_IDENTITY.json'
    if manifest_path.is_file():
        manifest = read_json(manifest_path)
        require(manifest.get('baseline_sha') == expected_sha, 'harness_identity_mismatch', 'Offline source baseline differs from frozen configuration')
        files = manifest.get('source_files', {})
        require(isinstance(files, dict) and required_files <= files.keys(), 'harness_identity_invalid', 'Offline source identity must cover stage and prompt resources')
        for relative, expected_hash in files.items():
            logical_path = root / relative
            path = logical_path.resolve()
            require(isinstance(relative, str) and not Path(relative).is_absolute() and '..' not in Path(relative).parts and
                    (relative.startswith('harness/') or relative.startswith('prompts/')) and
                    path.is_relative_to(root) and not logical_path.is_symlink() and path.is_file() and file_sha256(path) == expected_hash,
                    'harness_source_modified', 'Frozen offline source component changed: ' + str(relative))
        return {'kind': 'offline_source_manifest', 'baseline_sha': expected_sha, 'manifest_sha256': file_sha256(manifest_path)}
    require(shutil.which('git') and (root / '.git').exists(), 'harness_identity_missing', 'Provide SOURCE_IDENTITY.json for an offline source archive')
    ancestor = subprocess.run(['git', '-C', str(root), 'merge-base', '--is-ancestor', expected_sha, 'HEAD'], capture_output=True, check=False)
    require(ancestor.returncode == 0, 'harness_identity_mismatch', 'Frozen harness baseline is not an ancestor of this checkout')
    difference = subprocess.run(['git', '-C', str(root), 'diff', '--exit-code', expected_sha, '--', 'harness', 'prompts'], capture_output=True, check=False)
    require(difference.returncode == 0 and all((root / relative).is_file() for relative in required_files),
            'harness_source_modified', 'Original harness or prompt bytes differ from the frozen baseline')
    return {'kind': 'git_baseline_diff', 'baseline_sha': expected_sha}


def preflight(config):
    checks = []
    mode = config.get('mode')
    require(mode in {'fixture', 'real'}, 'mode_invalid', 'Declare fixture or real mode')
    if mode == 'fixture':
        return {'status': 'ready', 'software_ready': True, 'gpu_ready': False, 'mode': mode,
                'fixture_only': True, 'checks': [], 'limitations': ['Synthetic CPU fixtures do not verify native model execution or quality']}
    root = Path(config.get('harness_source_root') or '').resolve()
    for relative in ['harness/stages/diagnosis.py', 'harness/stages/compose.py', 'harness/stages/tools.py', 'prompts/diagnosis.txt', 'prompts/compose.txt']:
        checks.append({'check': 'source:' + relative, 'passed': (root / relative).is_file()})
    try:
        identity = _verify_harness_identity(config)
        checks.append({'check': 'harness_source_identity', 'passed': True, 'identity': identity})
    except (HREError, OSError, ValueError) as exc:
        checks.append({'check': 'harness_source_identity', 'passed': False, 'reason': str(exc)})
    editor = _editor_config(config.get('editor', {}))
    deployment = editor.get('deployment_manifest')
    checks.append({'check': 'deployment_manifest', 'passed': bool(deployment and Path(deployment).is_file())})
    try:
        from hre.v3.common import model_identity
        identity = model_identity(editor, 'Qwen/Qwen-Image-2.1')
        checks.append({'check': 'weights_identity', 'passed': True, 'identity': identity})
    except (HREError, OSError, ValueError) as exc:
        checks.append({'check': 'weights_identity', 'passed': False, 'reason': str(exc)})
    for name in ['cv2', 'numpy', 'torch', 'diffusers', 'transformers']:
        try:
            present = importlib.util.find_spec(name) is not None
        except (ValueError, ImportError):
            present = False
        checks.append({'check': 'dependency:' + name, 'passed': present})
    if any(item['check'] == 'dependency:diffusers' and item['passed'] for item in checks):
        try:
            diffusers = importlib.import_module('diffusers')
            require(diffusers.__version__ == editor.get('pipeline_version'), 'pipeline_version_mismatch', 'Installed Diffusers differs from frozen editor version')
            pipeline_class = getattr(diffusers, 'QwenImage21Pipeline', None)
            require(pipeline_class is not None, 'qwen_pipeline_missing', 'Installed Diffusers has no original Qwen 2.1 pipeline')
            from hre.v3.native_sources import verify_module
            verify_module(importlib.import_module(pipeline_class.__module__), 'pipelines/qwenimage21/pipeline_qwenimage21.py')
            checks.append({'check': 'pipeline_source_identity', 'passed': True})
        except Exception as exc:
            checks.append({'check': 'pipeline_source_identity', 'passed': False, 'reason': str(exc)})
    gpu_ready = False
    if any(item['check'] == 'dependency:torch' and item['passed'] for item in checks):
        try:
            import torch
            gpu_ready = bool(torch.cuda.is_available())
        except Exception as exc:
            checks.append({'check': 'torch_runtime', 'passed': False, 'reason': type(exc).__name__})
    checks.append({'check': 'cuda_available', 'passed': gpu_ready})
    for name in ['diagnoser', 'composer', 'planner', 'rewriter', 'audit', 'judge']:
        stage = config.get('stages', {}).get(name, {})
        try:
            validate_endpoint(stage, config.get('review', {}).get('max_output_tokens', 8192))
            if stage.get('api_key_env'):
                import os
                require(stage['api_key_env'] in os.environ, 'credential_missing', 'Credential environment variable is missing')
            checks.append({'check': 'stage:' + name, 'passed': True})
        except (HREError, TypeError, ValueError) as exc:
            checks.append({'check': 'stage:' + name, 'passed': False, 'reason': str(exc)})
    software_ready = all(item['passed'] for item in checks if item['check'] != 'cuda_available')
    return {'status': 'ready' if software_ready and gpu_ready else 'blocked', 'software_ready': software_ready,
            'gpu_ready': gpu_ready, 'mode': mode, 'fixture_only': False, 'checks': checks,
            'limitations': ['Preflight checks deployment prerequisites; it does not invoke a model or prove requested x1/x4 canvas support']}
