"""Local synthetic regressions for the final run/execution contract boundary."""
import json
import shutil
from pathlib import Path

import pytest
from PIL import Image, ImageCms

from hre.assets import create_case
from hre.desktop import import_candidate, export_task_bundle
from hre.experiments import freeze_run, export_blind_evaluation, summarize_evaluation
from hre.models import HREError, file_sha256
from hre.protocol import TaskWriter
from hre.storage import read_json, write_json
from hre.workflow import Controller
from test_hre_experiments import run_fixture, formalize
from test_hre_selection import verified


ANNOTATION = {
    'status': 'observed', 'source_anchor': 'prediction',
    'protected_face_regions': [{'region_id': 'face1', 'coordinate_system': 'canonical_norm', 'bbox': [.1, .2, .3, .4], 'instruction': 'Preserve identity and face shape.'}],
    'protected_text_regions': [{'region_id': 'text1', 'coordinate_system': 'canonical_norm', 'bbox': [.4, .5, .8, .7], 'instruction': 'Preserve exact text.', 'text': 'OPEN'}],
    'protected_geometry_landmarks': [{'landmark_id': 'corner', 'coordinate_system': 'canonical_norm', 'point': [.2, .8], 'instruction': 'Preserve corner location.'}],
    'protected_object_regions': [{'region_id': 'cup', 'coordinate_system': 'canonical_norm', 'bbox': [.1, .5, .3, .9], 'instruction': 'Preserve the cup.', 'notes': 'A coordinates only.'}],
    'critical_content_rules_version': 'content_preservation_v1', 'notes': 'Keep all A objects; B is not content ground truth.'}


def frozen(tmp_path, annotation=ANNOTATION):
    _, manifest, profile = run_fixture(tmp_path, cases=1)
    formalize(manifest)
    data = read_json(manifest)
    if annotation is not None:
        data['cases'][0]['content_preservation_annotations'] = annotation
    write_json(manifest, data)
    root = tmp_path / 'formal'
    freeze_run(manifest, profile, root)
    return root, data['cases'][0]


def initialize(root, case):
    ir = root / 'frozen_inputs/case0'
    cr = root / 'records/case0/direct_ref'
    create_case(ir / case['assets'][0]['path'], ir / case['assets'][1]['path'], case,
                read_json(root / 'runtime_configs/case0/direct_ref.json'), cr)
    return cr


def changed_package(tmp_path, monkeypatch, stage):
    import hre.prompts as prompts
    actual = tmp_path / 'changed_package'
    shutil.copytree(Path(str(prompts.files('hre'))) / 'resources', actual / 'resources')
    template = actual / 'resources/prompts' / (stage + '.j2')
    template.write_text(template.read_text().replace('Make visible, natural rendering improvements.', 'Make a substantial increase in color saturation in Image A.') if stage == 'direct_ref' else template.read_text().replace('Inspect attached A, B and C.', 'Inspect only the rendering of C.'))
    monkeypatch.setattr(prompts, 'files', lambda name: actual)
    return template


def execute(cr, tmp_path):
    c = Controller(cr)
    s = c.start()
    tid = s['pending_task']['task_id']
    c.mark_submitted(tid)
    source = tmp_path / 'generated.png'
    Image.new('RGB', (12, 10), 'green').save(source, icc_profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes())
    result = c.consume_done(import_candidate(cr, tid, source, {'actual_generation_count': 1, 'provider_order': 0}))
    assert result.accepted, result
    return c


def complete(c):
    req = read_json(c.root / c.state()['pending_task']['request_path'])
    assert c.consume_done(TaskWriter(c.root).commit_submission(req, verified()['verification'])).accepted


def evaluate(root, tmp_path):
    export_blind_evaluation(root, tmp_path / 'blind')
    mapping = read_json(root / 'private/blind_mapping.json')['items']
    rp = tmp_path / 'ratings.json'
    write_json(rp, {'frozen': True, 'raters': [{'rater_id': r, 'independent': True, 'participated_cases': []} for r in ['r1', 'r2']], 'ratings': [{'code': x['code'], 'rater_id': r, 'style_direction': 'improved', 'content_preservation': 'pass', 'critical_defects': [], 'comparability': 'usable'} for x in mapping for r in ['r1', 'r2']]})
    return next(x for x in mapping if x['arm_id'] == 'direct_ref'), summarize_evaluation(root, rp)


@pytest.mark.parametrize('annotation', [ANNOTATION, None, [], ['Preserve all A objects.']])
def test_annotations_survive_freeze_import_and_verify(tmp_path, annotation):
    root, case = frozen(tmp_path, annotation)
    cr = initialize(root, case)
    c = execute(cr, tmp_path)
    assert c.state()['workflow_state'] == 'WAIT_VERIFICATION'
    directory = cr / Path(c.state()['pending_task']['request_path']).parent
    bundle = json.loads((directory / 'prompt.txt').read_text())
    assert [x['label'] for x in bundle['image_bindings']] == ['A', 'B', 'C']
    if isinstance(annotation, dict):
        assert bundle['input_context']['protected_content']['annotations'] == annotation
        assert bundle['input_context']['protected_content']['rubric']
    complete(c)
    record, summary = evaluate(root, tmp_path)
    assert record['protocol_violations'] == []
    assert summary['arms']['direct_ref']['joint_success'] == 1


@pytest.mark.parametrize('annotation', ['invalid', 1, {'status': 'observed'}, {**ANNOTATION, 'protected_face_regions': ['unknown']}, {**ANNOTATION, 'source_anchor': 'reference'}])
def test_invalid_annotations_rejected_before_admission(tmp_path, annotation):
    with pytest.raises((HREError, ValueError)):
        frozen(tmp_path, annotation)
    assert not (tmp_path / 'formal/run.json').exists()


@pytest.mark.parametrize('stage', ['direct_ref', 'verify'])
def test_installed_template_change_after_initialization_cannot_change_dispatch(tmp_path, monkeypatch, stage):
    root, case = frozen(tmp_path, [])
    cr = initialize(root, case)
    changed_package(tmp_path, monkeypatch, stage)
    c = execute(cr, tmp_path)
    req = read_json(cr / c.state()['pending_task']['request_path'])
    if stage == 'verify':
        assert 'Inspect attached A, B and C.' in (cr / Path(c.state()['pending_task']['request_path']).with_name('prompt.txt')).read_text()
    else:
        source = next(cr.glob('tasks/direct_prompt_*/manifest.json'))
        assert 'Make visible, natural rendering improvements.' in read_json(source)['edit_prompt']
    export_task_bundle(req, tmp_path / 'exchange', case_root=cr)
    complete(c)
    record, summary = evaluate(root, tmp_path)
    assert record['status'] == 'completed' and record['protocol_violations'] == []
    assert summary['arms']['direct_ref']['joint_success'] == 1


@pytest.mark.parametrize('stage', ['direct_ref', 'verify'])
def test_template_drift_before_initialization_remains_itt_with_actual_cost(tmp_path, monkeypatch, stage):
    root, case = frozen(tmp_path, [])
    changed_package(tmp_path, monkeypatch, stage)
    c = execute(initialize(root, case), tmp_path)
    complete(c)
    record, summary = evaluate(root, tmp_path)
    assert record['status'] == 'protocol_violation'
    assert 'executed_prompt_templates_differ_from_frozen_run' in record['protocol_violations']
    assert record['costs']['accounted_generations'] == 1
    assert summary['arms']['direct_ref']['denominator'] == 1
    assert summary['arms']['direct_ref']['joint_success'] == 0


def test_installed_template_change_after_completed_does_not_retroinvalidate(tmp_path, monkeypatch):
    root, case = frozen(tmp_path, [])
    c = execute(initialize(root, case), tmp_path)
    complete(c)
    changed_package(tmp_path, monkeypatch, 'verify')
    record, summary = evaluate(root, tmp_path)
    assert record['protocol_violations'] == []
    assert summary['arms']['direct_ref']['joint_success'] == 1


def test_configuration_only_external_contract_cannot_pass_template_binding(tmp_path):
    root, case = frozen(tmp_path, [])
    cr = initialize(root, case)
    c = execute(cr, tmp_path)
    complete(c)
    plan = read_json(root / 'planned_outcomes.json')
    o = next(x for x in plan['outcomes'] if x['arm_id'] == 'direct_ref')
    o.update(status='completed', selected_asset=c.state()['candidates'][0]['asset'], selected_asset_root=o['case_root'])
    o['execution_contract'] = {'path': (cr / 'config.json').relative_to(root).as_posix(), 'sha256': file_sha256(cr / 'config.json'), 'selected_asset_id': o['selected_asset']['asset_id'], 'selected_asset_sha256': o['selected_asset']['sha256']}
    # Retain the actual execution files as external inputs, without local auto-discovery.
    external = root / 'external_records/case0/direct_ref'
    external.parent.mkdir(parents=True)
    shutil.move(cr, external)
    o['selected_asset_root'] = external.relative_to(root).as_posix()
    o['execution_contract']['path'] = (external / 'config.json').relative_to(root).as_posix()
    write_json(root / 'planned_outcomes.json', plan)
    record, summary = evaluate(root, tmp_path)
    assert record['status'] == 'protocol_violation'
    assert summary['arms']['direct_ref']['joint_success'] == 0


def test_actual_template_files_and_sidecar_cannot_be_rewritten(tmp_path):
    root, case = frozen(tmp_path, [])
    cr = initialize(root, case)
    path = cr / 'prompts/execute.j2'
    path.write_text(path.read_text().replace('A', 'Altered A'))
    manifest = read_json(cr / 'prompts/manifest.json')
    manifest['templates']['execute']['sha256'] = file_sha256(path)
    write_json(cr / 'prompts/manifest.json', manifest)
    with pytest.raises(HREError, match='File hash mismatch'):
        Controller(cr).start()
    assert read_json(cr / 'state.json')['budget']['consumed'] == 0


def test_invalid_case_annotation_cannot_initialize_or_charge(tmp_path):
    root, case = frozen(tmp_path, [])
    config = read_json(root / 'runtime_configs/case0/direct_ref.json')
    config['protected_content'] = {'status': 'observed'}
    ir = root / 'frozen_inputs/case0'
    cr = root / 'bad_case'
    with pytest.raises(HREError, match='invalid_content_annotations'):
        create_case(ir / case['assets'][0]['path'], ir / case['assets'][1]['path'], case, config, cr)
    assert not (cr / 'state.json').exists()


def test_authentic_external_journal_preserves_execution_proof_and_cost(tmp_path):
    root, case = frozen(tmp_path, [])
    cr = initialize(root, case)
    c = execute(cr, tmp_path)
    complete(c)
    plan = read_json(root / 'planned_outcomes.json')
    o = next(x for x in plan['outcomes'] if x['arm_id'] == 'direct_ref')
    asset = c.state()['candidates'][0]['asset']
    external = root / 'external_records/case0/direct_ref'
    external.parent.mkdir(parents=True)
    shutil.move(cr, external)
    o.update(status='completed', selected_asset=asset, selected_asset_root=external.relative_to(root).as_posix())
    o['execution_contract'] = {'path': (external / 'config.json').relative_to(root).as_posix(), 'sha256': file_sha256(external / 'config.json'), 'selected_asset_id': asset['asset_id'], 'selected_asset_sha256': asset['sha256'], 'execution_record_root': external.relative_to(root).as_posix()}
    write_json(root / 'planned_outcomes.json', plan)
    record, summary = evaluate(root, tmp_path)
    assert record['status'] == 'completed' and record['protocol_violations'] == []
    assert record['costs']['accounted_generations'] == 1
    assert summary['arms']['direct_ref']['joint_success'] == 1


def test_proof_free_historical_journal_is_not_backfilled(tmp_path):
    root, case = frozen(tmp_path, [])
    cr = initialize(root, case)
    c = execute(cr, tmp_path)
    complete(c)
    # Model an old journal without execution-time source references. Current
    # source files and matching package hashes cannot replace that missing proof.
    for path in (cr / 'transactions').glob('*.json'):
        tx = read_json(path)
        if tx['next_task']:
            tx['next_task'].pop('template_source_proof')
            tx['next_task'].pop('dispatch_sha256')
            write_json(path, tx)
    record, summary = evaluate(root, tmp_path)
    assert record['status'] == 'protocol_violation'
    assert 'unverified_prompt_execution' in record['protocol_violations']
    assert record['costs']['accounted_generations'] == 1
    assert summary['arms']['direct_ref']['joint_success'] == 0
