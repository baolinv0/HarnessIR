from copy import deepcopy
from pathlib import Path

import pytest
from PIL import Image

from hre.candidates.contracts import candidate_spec, digest, seal
from hre.candidates.bridge import build_execution
from hre.candidates.evidence import collect_evidence
from hre.candidates import evidence
from hre.models import HREError, file_sha256
from hre.storage import write_json


def case_data(tmp_path, size=(32, 24), scale=1):
    source_path = tmp_path / 'source.png'
    Image.new('RGB', size, (100, 110, 120)).save(source_path)
    source = {'path': str(source_path), 'sha256': file_sha256(source_path), 'canonical_source_sha256': file_sha256(source_path),
              'width': size[0], 'height': size[1]}
    step = 8 if scale == 4 else 32
    padded = tuple((value + step - 1) // step * step for value in size)
    prepared_path = tmp_path / 'prepared.png'
    Image.new('RGB', padded, (100, 110, 120)).save(prepared_path)
    geometry = {'scale': scale, 'width': size[0], 'height': size[1], 'padded_width': padded[0], 'padded_height': padded[1],
                'canvas_width': padded[0] * scale, 'canvas_height': padded[1] * scale,
                'crop': [0, 0, size[0] * scale, size[1] * scale], 'projection': [[scale, 0, 0], [0, scale, 0], [0, 0, 1]], 'pad_mode': 'edge'}
    prepared = {'source': source, 'path': str(prepared_path), 'sha256': file_sha256(prepared_path),
                'prepared_source_sha256': file_sha256(prepared_path), 'geometry': geometry, 'geometry_sha256': digest(geometry)}
    task = {'case_id': 'case', 'task_mode': 'sr_x4' if scale == 4 else 'restoration_x1', 'scale': scale,
            'usage_policy': 'photo_restoration', 'critical_attributes': [],
            'rois': [{'id': 'face', 'semantic_type': 'person', 'box': [1, 2, 8, 12], 'importance': 'high', 'provenance': 'manual_lq'}]}
    specs, artifacts = [], []
    for index, (slot, strategy) in enumerate([('C0', 'baseline'), ('CF', 'face_alt')]):
        spec = candidate_spec(slot, strategy, index, index, 'Frozen complete prompt.', source['canonical_source_sha256'])
        directory = tmp_path / 'candidates' / spec['candidate_id']
        directory.mkdir(parents=True)
        native, delivered = directory / 'native.png', directory / 'delivered.png'
        Image.new('RGB', (geometry['canvas_width'], geometry['canvas_height']), (100 + index, 110, 120)).save(native)
        Image.new('RGB', (size[0] * scale, size[1] * scale), (100 + index, 110, 120)).save(delivered)
        manifest = build_execution(spec, prepared, {})
        manifest_path = tmp_path / 'execution_manifests' / (spec['candidate_id'] + '.json')
        write_json(manifest_path, manifest)
        receipt = {'canonical_source_sha256': source['canonical_source_sha256'],
                   'prepared_source_sha256': prepared['prepared_source_sha256'], 'geometry_sha256': prepared['geometry_sha256'],
                   'condition_text_sha256': spec['prompt_hash'], 'execution_manifest_sha256': manifest['execution_manifest_sha256'],
                   'seed': index, 'fixture_only': True, 'native_sha256': file_sha256(native),
                   'delivered_sha256': file_sha256(delivered), 'editor_config_sha256': digest(manifest['editor']),
                   'execution_request_sha256': digest(manifest['request'])}
        artifacts.append({'candidate_id': spec['candidate_id'], 'status': 'completed', 'native_image': str(native),
                          'delivered_image': str(delivered), 'native_sha256': file_sha256(native), 'sha256': file_sha256(delivered),
                          'width': size[0] * scale, 'height': size[1] * scale, 'receipt': receipt,
                          'manifest_sha256': manifest['execution_manifest_sha256'], 'manifest_path': str(manifest_path)})
        specs.append(spec)
    plan = seal({'candidate_specs': specs, 'roi_registry': task['rois'], 'source_hash': source['canonical_source_sha256'],
                 'plan_origin': 'fixture'})
    return task, plan, artifacts, source, prepared, {'mode': 'fixture', 'seed_schedule': [0, 1, 2, 3]}


def test_anonymous_copy_and_roi_projection_are_hash_bound(tmp_path):
    task, plan, artifacts, source, prepared, config = case_data(tmp_path, (257, 193), 4)
    bundle = collect_evidence(tmp_path, task, plan, artifacts, source, prepared, config)
    assert all(entry['hard_gate'] == 'passed' for entry in bundle['candidates'])
    assert sorted(bundle['aliases'].values()) == sorted(item['candidate_id'] for item in artifacts)
    for entry in bundle['candidates']:
        assert Path(entry['image_path']).name == entry['alias'] + '.png'
        assert file_sha256(Path(entry['image_path'])) == entry['image_sha256']
        crop = entry['roi_images'][0]
        assert Image.open(crop['path']).size == (28, 40)
        assert crop['ref_id'] == entry['alias'] + '_face'
    assert Image.open(bundle['source']['roi_images'][0]['path']).size == (7, 10)
    assert {item['attribute_id'] for item in bundle['critical_instances']} >= {'__restoration__', '__artifacts__'}


@pytest.mark.parametrize('mutation', ['output_hash', 'source_binding', 'seed_binding', 'native_size', 'manifest_changed'])
def test_hard_contract_failures_are_not_quality_scores(tmp_path, mutation):
    task, plan, artifacts, source, prepared, config = case_data(tmp_path)
    candidate = artifacts[1]
    if mutation == 'output_hash':
        candidate['sha256'] = '0' * 64
    elif mutation == 'source_binding':
        candidate['receipt']['canonical_source_sha256'] = '0' * 64
    elif mutation == 'seed_binding':
        candidate['receipt']['seed'] = 91
    elif mutation == 'native_size':
        Image.new('RGB', (8, 8)).save(candidate['native_image'])
        candidate['native_sha256'] = file_sha256(Path(candidate['native_image']))
    else:
        import json
        path = Path(candidate['manifest_path'])
        changed = json.loads(path.read_text())
        changed['request']['seed'] = 99
        write_json(path, changed)
    bundle = collect_evidence(tmp_path, task, plan, artifacts, source, prepared, config)
    gates = {item['candidate_id']: item['hard_gate'] for item in bundle['candidates']}
    assert gates[artifacts[0]['candidate_id']] == 'passed'
    assert gates[artifacts[1]['candidate_id']] == 'failed'


def test_soft_metrics_do_not_reject_flat_or_clipped_candidate(tmp_path):
    task, plan, artifacts, source, prepared, config = case_data(tmp_path)
    candidate = artifacts[1]
    Image.new('RGB', (32, 32), (255, 255, 255)).save(candidate['native_image'])
    candidate['native_sha256'] = file_sha256(Path(candidate['native_image']))
    candidate['receipt']['native_sha256'] = candidate['native_sha256']
    Image.new('RGB', (32, 24), (255, 255, 255)).save(candidate['delivered_image'])
    candidate['sha256'] = file_sha256(Path(candidate['delivered_image']))
    candidate['receipt']['delivered_sha256'] = candidate['sha256']
    bundle = collect_evidence(tmp_path, task, plan, artifacts, source, prepared, config)
    assert all(item['hard_gate'] == 'passed' for item in bundle['candidates'])
    assert any(item['method_id'] == 'clipping_ratio' and item['value'] == 1 for item in bundle['measurements'])
    assert all(item['candidate_id'].startswith('A') for item in bundle['measurements'])


def test_missing_required_roi_cannot_become_vacuous_acceptance(tmp_path):
    task, plan, artifacts, source, prepared, config = case_data(tmp_path)
    task['critical_attributes'] = [{'attribute_id': 'number', 'region_selector': 'all_text', 'attribute': 'characters',
                                    'required_for_acceptance': True, 'verification_requirement': 'verified_content'}]
    bundle = collect_evidence(tmp_path, task, plan, artifacts, source, prepared, config)
    entry = next(item for item in bundle['critical_instances'] if item['attribute_id'] == 'number')
    assert entry['available'] is False
    assert entry['region_id'] == '__missing__'


def test_plan_mutation_and_offline_artifacts_are_rejected(tmp_path):
    task, plan, artifacts, source, prepared, config = case_data(tmp_path)
    plan['roi_registry'][0]['box'][0] = 0
    with pytest.raises(HREError):
        collect_evidence(tmp_path, task, plan, artifacts, source, prepared, config)
    plan = seal(plan)
    offline = tmp_path / 'offline'
    offline.mkdir()
    path = offline / 'truth.png'
    Image.new('RGB', (32, 24)).save(path)
    artifacts[1]['delivered_image'] = str(path)
    artifacts[1]['sha256'] = file_sha256(path)
    bundle = collect_evidence(tmp_path, task, plan, artifacts, source, prepared, config)
    assert next(item for item in bundle['candidates'] if item['candidate_id'] == artifacts[1]['candidate_id'])['hard_gate'] == 'failed'


def test_source_modification_fails_every_candidate(tmp_path):
    task, plan, artifacts, source, prepared, config = case_data(tmp_path)
    Image.new('RGB', (32, 24), (0, 0, 0)).save(source['path'])
    bundle = collect_evidence(tmp_path, task, plan, artifacts, source, prepared, config)
    assert all(item['hard_gate'] == 'failed' for item in bundle['candidates'])


def test_independent_pool_outputs_keep_case_source_trust_boundary(tmp_path):
    task, plan, artifacts, source, prepared, config = case_data(tmp_path)
    output = tmp_path / 'pools' / 'A'
    bundle = collect_evidence(tmp_path, task, plan, artifacts, source, prepared, config, output_root=output)
    assert all(item['hard_gate'] == 'passed' for item in bundle['candidates'])
    assert Path(bundle['source']['path']).is_relative_to(output)
    assert (output / 'evidence' / 'bundle.json').is_file()
    assert not (tmp_path / 'evidence' / 'bundle.json').exists()
    with pytest.raises(HREError):
        collect_evidence(tmp_path, task, plan, artifacts, source, prepared, config, output_root=tmp_path.parent)


def test_soft_measurement_failure_never_changes_hard_gate(tmp_path, monkeypatch):
    task, plan, artifacts, source, prepared, config = case_data(tmp_path)
    def failed_measurement(*args, **kwargs):
        raise ValueError('scripted measurement failure')
    monkeypatch.setattr(evidence, '_measurements', failed_measurement)
    bundle = collect_evidence(tmp_path, task, plan, artifacts, source, prepared, config)
    assert all(item['hard_gate'] == 'passed' for item in bundle['candidates'])
    assert len(bundle['measurements']) == 2
    assert all(item['status'] == 'failed' and item['value'] is None for item in bundle['measurements'])
