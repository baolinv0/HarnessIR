"""Small file-backed runner. Stages are independent; upstream runs are explicit inputs."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import time
import uuid

import numpy as np
from PIL import Image

from . import normalize_stage
from .profiles import get_profile
from .prompts import ROLE_BRIEF, build_prompt, condition_text

DEFAULT_TASK = 'Borrow the comparable tonal and color rendering of B while preserving the content and composition of A.'


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex[:8] + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[\w][\w.-]*', value) or value in ('.', '..'):
        raise ValueError('Use a nonempty ID with letters, digits, underscore, dot or hyphen.')
    return value


def _new_id(stage='run'):
    return f'{stage}_{datetime.now(timezone.utc):%Y%m%dT%H%M%S}_{uuid.uuid4().hex[:8]}'


def init_lab(root: Path, models: dict | None = None) -> dict:
    root = Path(root).resolve()
    if (root / 'lab.json').exists():
        value = load_lab(root)
        if models is not None:
            save_models(root, models)
            value['models'] = models
        return value
    value = {'schema_version': 'stage_lab_v1', 'models': models or {}}
    _write(root / 'lab.json', value)
    return value


def load_lab(root: Path) -> dict:
    return _read(Path(root) / 'lab.json')


def save_models(root: Path, models: dict) -> None:
    if not isinstance(models, dict) or not all(isinstance(v, dict) for v in models.values()):
        raise ValueError('Models must be an object mapping model IDs to provider configurations.')
    for name in models:
        _id(name)
    value = load_lab(root)
    value['models'] = models
    _write(Path(root) / 'lab.json', value)


def add_case(root: Path, prediction: Path, reference: Path, case_id: str | None = None,
             task: str = '', context: dict | None = None) -> dict:
    root = Path(root).resolve()
    load_lab(root)
    case_id = _id(case_id or _new_id('case'))
    directory = root / 'cases' / case_id
    if directory.exists():
        raise ValueError(f'Case {case_id} already exists; use another case ID.')
    sources = [Path(prediction).resolve(), Path(reference).resolve()]
    for source in sources:
        with Image.open(source) as image:
            image.verify()
    directory.mkdir(parents=True)
    images, sizes, hashes = {}, {}, {}
    for role, source in zip(('A', 'B'), sources):
        target = directory / (role + source.suffix.lower())
        shutil.copyfile(source, target)
        images[role] = target.relative_to(root).as_posix()
        with Image.open(target) as image:
            sizes[role] = list(image.size)
        hashes[role] = hashlib.sha256(target.read_bytes()).hexdigest()
    case = {'id': case_id, 'task': task or DEFAULT_TASK, 'images': images,
            'image_sizes': sizes, 'image_sha256': hashes, 'context': context or {}}
    _write(directory / 'case.json', case)
    return case


def list_cases(root: Path) -> list[dict]:
    return [_read(p) for p in sorted((Path(root) / 'cases').glob('*/case.json'))]


def list_runs(root: Path, case_id=None, stage=None) -> list[dict]:
    stage = normalize_stage(stage) if stage else None
    rows = [_read(p) for p in (Path(root) / 'runs').glob('*/result.json')]
    rows.sort(key=lambda row: (row.get('created_at', ''), row['id']))
    return [r for r in rows if (case_id is None or r['case_id'] == case_id)
            and (stage is None or r['stage'] == stage)]


def _sources(root, case_id, source_runs):
    rows = []
    for run_id in source_runs or []:
        row = _read(root / 'runs' / _id(run_id) / 'result.json')
        if row['case_id'] != case_id:
            raise ValueError(f'Source run {run_id} belongs to another case.')
        if row['status'] != 'completed':
            raise ValueError(f'Source run {run_id} has no completed output.')
        rows.append(row)
    return rows


def _make_request(root, case_id, stage, model, *, source_runs=None, context=None,
                  candidates=None, prompt=None, profile=None):
    case = _read(root / 'cases' / _id(case_id) / 'case.json')
    sources = _sources(root, case_id, source_runs)
    combined = {**deepcopy(case.get('context', {})), **deepcopy(context or {})}
    upstream = [{'stage': r['stage'], 'model_id': r['model_id'],
                 'data': r['output'].get('data'), 'text': r['output'].get('text', ''),
                 'images': [str(root / p) for p in r['output'].get('images', [])]}
                for r in sources]
    if stage != 'judge':
        combined['upstream'] = upstream
    else:
        # Labels/provenance live in result.json, never in the default judge message.
        combined.pop('upstream', None)
        if combined.get('judge_mode') != 'action':
            combined = {'judge_mode': 'blind'}
    images = [{'role': role, 'path': str(root / p)} for role, p in case['images'].items()]
    candidate_paths = [Path(p).resolve() for p in candidates or []]
    if stage == 'judge' and not candidate_paths:
        candidate_paths = [root / p for r in sources if r['stage'] == 'execute'
                           for p in r['output'].get('images', [])]
    for i, candidate in enumerate(candidate_paths):
        if not candidate.is_file():
            raise ValueError(f'Candidate image does not exist: {candidate}')
        images.append({'role': 'C' if i == 0 else f'C{i + 1}', 'path': str(candidate)})
    if stage == 'judge' and not candidate_paths:
        raise ValueError('Judge needs a candidate image or a selected execute result.')
    chosen_profile = get_profile(profile or model.get('profile'))
    if prompt is not None and stage == 'compile':
        combined['instruction'] = prompt
    elif stage == 'compile' and not any(r['stage'] == 'plan' for r in upstream):
        combined.setdefault('instruction', condition_text(combined, ROLE_BRIEF + case['task']))
    request = {'stage': stage, 'case_id': case_id, 'images': images, 'context': combined,
               'profile': chosen_profile, 'parameters': deepcopy(model.get('parameters', {})),
               'prompt_override': prompt is not None}
    request['prompt'] = build_prompt(stage, case['task'], combined, chosen_profile, prompt)
    return request


def _image_metrics(original, candidate):
    with Image.open(original) as a, Image.open(candidate) as c:
        av = np.asarray(a.convert('RGB'), dtype=np.float64) / 255
        cv = np.asarray(c.convert('RGB'), dtype=np.float64) / 255
        y = np.array([.2126, .7152, .0722])
        ay, cy = av @ y, cv @ y
        metrics = {'width': c.width, 'height': c.height, 'size_matches_A': a.size == c.size,
                   'mean_luma': round(float(cy.mean()), 6),
                   'mean_luma_delta_A': round(float(cy.mean() - ay.mean()), 6),
                   'dark_fraction': round(float((cy < .05).mean()), 6),
                   'bright_fraction': round(float((cy > .95).mean()), 6)}
        if a.size == c.size:
            metrics['mean_abs_rgb_change_A'] = round(float(np.abs(cv - av).mean()), 6)
        return metrics


def _store_output(root, directory, case_id, output):
    output = deepcopy(output)
    stored = []
    for i, filename in enumerate(output.get('images', [])):
        source = Path(filename)
        if not source.is_absolute():
            source = directory / source
        with Image.open(source) as image:
            image.verify()
        target = directory / f'output_{i:02d}{source.suffix.lower() or ".png"}'
        if source.resolve() != target.resolve():
            shutil.copyfile(source, target)
        stored.append(target.relative_to(root).as_posix())
    output['images'] = stored
    output.setdefault('text', '')
    output.setdefault('data', None)
    output.setdefault('metrics', {})
    if stored:
        case = _read(root / 'cases' / case_id / 'case.json')
        output['metrics'].update(_image_metrics(root / case['images']['A'], root / stored[0]))
    return {key: output[key] for key in ('text', 'data', 'images', 'metrics')}


def _record(root, case_id, stage, model_id, request, source_runs=None):
    run_id = _new_id(stage)
    directory = root / 'runs' / run_id
    directory.mkdir(parents=True)
    # Keep the actual judged candidate even when a user supplied a temporary upload.
    for item in request['images']:
        if item['role'].startswith('C'):
            source = Path(item['path'])
            target = directory / ('input_' + item['role'] + source.suffix)
            shutil.copyfile(source, target)
            item['path'] = str(target)
    row = {'id': run_id, 'case_id': case_id, 'stage': stage, 'model_id': model_id,
           'profile': request['profile']['id'], 'created_at': datetime.now(timezone.utc).isoformat(),
           'source_runs': source_runs or [], 'request': request, 'status': 'running',
           'output': {'text': '', 'data': None, 'images': [], 'metrics': {}},
           'duration_s': 0., 'usage': {}, 'metadata': {}, 'error': None}
    _write(directory / 'request.json', request)
    return row, directory


def run_stage(root: Path, case_id: str, stage: str, model_ids: list[str], *,
              source_runs=None, context=None, candidates=None, prompt=None, profile=None) -> list[dict]:
    from .providers import call_provider
    root = Path(root).resolve()
    stage = normalize_stage(stage)
    models = load_lab(root)['models']
    if not model_ids:
        raise ValueError('Select at least one model.')
    unknown = set(model_ids) - set(models)
    if unknown:
        raise ValueError(f'Unknown model IDs: {", ".join(sorted(unknown))}')
    rows = []
    for model_id in model_ids:
        model = models[model_id]
        request = _make_request(root, case_id, stage, model, source_runs=source_runs,
                                context=context, candidates=candidates, prompt=prompt, profile=profile)
        row, directory = _record(root, case_id, stage, model_id, request, source_runs)
        start = time.perf_counter()
        try:
            if model.get('stages') and stage not in [normalize_stage(s) for s in model['stages']]:
                raise ValueError(f'Model {model_id} is not configured for stage {stage}.')
            response = call_provider(model, request, directory)
            row['output'] = _store_output(root, directory, case_id, response)
            if stage == 'execute' and not row['output']['images']:
                raise ValueError('Execute returned no image. Check the provider endpoint or import an image output.')
            row.update(status='completed', usage=response.get('usage', {}), metadata=response.get('metadata', {}))
        except Exception as exc:
            row.update(status='error', error=f'{type(exc).__name__}: {exc}')
        row['duration_s'] = round(time.perf_counter() - start, 4)
        row['provider'] = model.get('provider')
        row['model'] = model.get('model', model_id)
        _write(directory / 'result.json', row)
        rows.append(row)
    return rows


def import_output(root: Path, case_id: str, stage: str, model_id: str, *, source_runs=None,
                  data=None, text='', images=None) -> dict:
    root = Path(root).resolve()
    stage = normalize_stage(stage)
    models = load_lab(root)['models']
    # An imported judge has already run elsewhere; its image inputs can be absent.
    request_stage = 'plan' if stage == 'judge' else stage
    request = _make_request(root, case_id, request_stage, models.get(model_id, {}), source_runs=source_runs)
    request['stage'] = stage
    request['prompt'] = ''
    row, directory = _record(root, case_id, stage, model_id, request, source_runs)
    row['output'] = _store_output(root, directory, case_id,
                                  {'text': text, 'data': data, 'images': [str(Path(p).resolve()) for p in images or []]})
    if stage == 'execute' and not row['output']['images']:
        raise ValueError('Importing execute requires at least one output image.')
    row.update(status='completed', metadata={'imported': True})
    _write(directory / 'result.json', row)
    return row


def export_request(root: Path, case_id: str, stage: str, model_id: str, *, source_runs=None,
                   context=None, candidates=None, prompt=None, profile=None) -> Path:
    root = Path(root).resolve()
    stage = normalize_stage(stage)
    models = load_lab(root)['models']
    request = _make_request(root, case_id, stage, models.get(model_id, {}), source_runs=source_runs,
                            context=context, candidates=candidates, prompt=prompt, profile=profile)
    directory = root / 'exports' / _new_id(stage)
    directory.mkdir(parents=True)
    for item in request['images']:
        source = Path(item['path'])
        target = directory / (item['role'] + source.suffix)
        shutil.copyfile(source, target)
        item['path'] = target.name
    request['image_path_base'] = 'request_directory'
    (directory / 'prompt.txt').write_text(request['prompt'], encoding='utf-8')
    _write(directory / 'request.json', request)
    return directory / 'request.json'
