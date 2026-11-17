from copy import deepcopy
from pathlib import Path

import pytest
from PIL import Image

from hre.candidates import planner
from hre.models import HREError, file_sha256


def context(tmp_path):
    source_path = tmp_path / 'source.png'
    Image.new('RGB', (32, 24), (80, 90, 100)).save(source_path)
    source = {'path': str(source_path), 'sha256': file_sha256(source_path),
              'canonical_source_sha256': file_sha256(source_path), 'width': 32, 'height': 24}
    task = {'case_id': 'sample', 'task_mode': 'restoration_x1', 'scale': 1,
            'usage_policy': 'photo_restoration', 'critical_attributes': [],
            'rois': [{'id': 'face', 'semantic_type': 'person', 'box': [1, 1, 12, 18],
                      'importance': 'high', 'provenance': 'manual_lq'},
                     {'id': 'sign', 'semantic_type': 'text', 'box': [16, 2, 30, 10],
                      'importance': 'high', 'provenance': 'manual_lq'}]}
    prompt = ('Restore the image. Restore face details gently. Restore visible text strokes. '
              'Preserve identity, expression, layout and colors.')
    baseline = {'P0': prompt, 'C0': {'status': 'completed', 'delivered_image': str(source_path)}}
    config = {'mode': 'fixture', 'seed_schedule': [0, 11, 22, 33],
              'fixture': {'issues': [issue('F01', 'person', 'face', 'waxy_skin'),
                                     issue('T01', 'text', 'sign', 'merged_strokes')]}}
    return task, config, baseline, source


def issue(identifier, domain, region, problem):
    return {'schema_version': 'hre_candidates_v1', 'issue_id': identifier,
            'region_ids': [region], 'domain': domain, 'problem_type': problem,
            'attribute': 'natural_texture' if domain == 'person' else 'stroke_continuity',
            'severity': 'major', 'task_criticality': 'high',
            'observation': 'Synthetic fixture observation', 'evidence_refs': ['source_full', 'c0_full'],
            'cause_hypotheses': [], 'alternative_explanations': [],
            'desired_change': 'Recover subtle natural texture' if domain == 'person' else 'Restore visible stroke separation',
            'protected_attributes': ['identity', 'expression', 'layout'],
            'expected_observation': 'Synthetic fixture target response', 'support': 'supported',
            'intervention_feasibility': 'plausible', 'spatial_control_risk': 'low'}


@pytest.fixture(autouse=True)
def scripted_boundary(monkeypatch):
    monkeypatch.setattr(planner, 'call_json', lambda *args, **kwargs: deepcopy(kwargs['fixture_response']))


def test_mixed_plan_changes_only_declared_scopes(tmp_path):
    task, config, baseline, source = context(tmp_path)
    plan = planner.build_plan(tmp_path, task, config, baseline, source, None)
    specs = {item['slot_id']: item for item in plan['candidate_specs']}
    assert plan['plan_origin'] == 'fixture'
    assert len(specs) == 4
    assert [item['seed'] for item in plan['candidate_specs']] == [0, 11, 22, 33]
    assert specs['CF']['full_prompt'] != baseline['P0']
    assert 'Restore visible text strokes.' in specs['CF']['full_prompt']
    assert 'Restore face details gently.' in specs['CT']['full_prompt']
    for item in specs.values():
        assert 'Preserve identity, expression, layout and colors.' in item['full_prompt']
    assert specs['CFT']['dependency_ids'] == ['CF', 'CT']


def test_unsupported_issues_become_baseline_resamples(tmp_path):
    task, config, baseline, source = context(tmp_path)
    for entry in config['fixture']['issues']:
        entry['support'] = 'ambiguous'
    plan = planner.build_plan(tmp_path, task, config, baseline, source, None)
    assert all(item['full_prompt'] == baseline['P0'] for item in plan['candidate_specs'])
    assert [item['effective_strategy_id'] for item in plan['candidate_specs']][1:] == ['baseline_resample'] * 3


def test_single_axis_mechanisms_have_separate_strategy_labels(tmp_path):
    task, config, baseline, source = context(tmp_path)
    config['fixture']['issues'] = [issue('F01', 'person', 'face', 'waxy_skin'),
                                  issue('F02', 'person', 'face', 'under_restored_features')]
    plan = planner.build_plan(tmp_path, task, config, baseline, source, None)
    assert [entry['effective_strategy_id'] for entry in plan['candidate_specs']] == [
        'baseline', 'face_alt_A', 'face_alt_B', 'baseline_resample']
    assert [entry['evaluation_axis_id'] for entry in plan['candidate_specs']][1:3] == ['person', 'person']


def test_face_audit_failure_also_reverts_joint_and_keeps_seeds(tmp_path):
    task, config, baseline, source = context(tmp_path)
    config['fixture']['audits'] = {'CF': False, 'CT': True, 'CFT': True}
    plan = planner.build_plan(tmp_path, task, config, baseline, source, None)
    specs = {entry['slot_id']: entry for entry in plan['candidate_specs']}
    assert specs['CF']['effective_strategy_id'] == 'baseline_resample'
    assert specs['CFT']['effective_strategy_id'] == 'baseline_resample'
    assert specs['CT']['effective_strategy_id'] == 'text_alt'
    assert specs['CF']['seed'] == 11 and specs['CFT']['seed'] == 33
    assert plan['joint_applicability'] == 'not_applicable'


def test_joint_only_audit_failure_preserves_singles(tmp_path):
    task, config, baseline, source = context(tmp_path)
    config['fixture']['audits'] = {'CF': True, 'CT': True, 'CFT': False}
    plan = planner.build_plan(tmp_path, task, config, baseline, source, None)
    assert [entry['effective_strategy_id'] for entry in plan['candidate_specs']] == [
        'baseline', 'face_alt', 'text_alt', 'baseline_resample']


def test_issue_unknown_fields_or_dangling_refs_are_rejected(tmp_path):
    task, config, baseline, source = context(tmp_path)
    config['fixture']['issues'][0]['evidence_refs'] = ['offline_truth']
    with pytest.raises(HREError):
        planner.build_plan(tmp_path, task, config, baseline, source, None)
    config['fixture']['issues'][0]['evidence_refs'] = ['source_full']
    config['fixture']['issues'][0]['support_status'] = 'supported'
    with pytest.raises(HREError):
        planner.build_plan(tmp_path, task, config, baseline, source, None)


def test_baseline_failure_does_not_call_planner(tmp_path, monkeypatch):
    task, config, baseline, source = context(tmp_path)
    baseline['C0']['status'] = 'failed'
    monkeypatch.setattr(planner, 'call_json', lambda *args, **kwargs: pytest.fail('Planner called after failed C0'))
    with pytest.raises(HREError) as exc:
        planner.build_plan(tmp_path, task, config, baseline, source, None)
    assert exc.value.code == 'baseline_failed'


def test_cannot_change_task_roi_after_observing_candidate(tmp_path):
    task, config, baseline, source = context(tmp_path)
    proposed = deepcopy(task['rois'])
    proposed[0]['box'] = [2, 1, 13, 18]
    config['fixture']['roi_registry'] = proposed
    with pytest.raises(HREError) as exc:
        planner.build_plan(tmp_path, task, config, baseline, source, None)
    assert exc.value.code == 'roi_registry_modified'


def test_compile_rejects_edits_to_protected_requirement():
    prompt = 'Restore face detail. Preserve identity.'
    ir = planner.requirements_from_prompt(prompt)
    protected = next(item for item in ir if item['kind'] == 'protection')
    with pytest.raises(HREError) as exc:
        planner.compile_prompt(prompt, ir, {protected['requirement_id']: 'Change identity.'}, ['person'])
    assert exc.value.code == 'protected_requirement_modified'


def test_compile_retains_unparsed_literal_text():
    prompt = 'Restore face detail. A unique unparsed global constraint.'
    ir = planner.requirements_from_prompt(prompt)
    target = next(item for item in ir if item['scope'] == ['person.*'])
    compiled = planner.compile_prompt(prompt, ir, {target['requirement_id']: 'Reduce synthetic wax.'}, ['person'])
    assert compiled == 'Reduce synthetic wax. A unique unparsed global constraint.'


def test_text_priority_does_not_swap_person_and_text_slots(tmp_path):
    task, config, baseline, source = context(tmp_path)
    config['fixture']['issues'][0]['task_criticality'] = 'low'
    plan = planner.build_plan(tmp_path, task, config, baseline, source, None)
    specs = {item['slot_id']: item for item in plan['candidate_specs']}
    assert specs['CF']['effective_strategy_id'] == 'face_alt'
    assert specs['CT']['effective_strategy_id'] == 'text_alt'


def test_prompt_file_preserves_exact_utf8_newlines(tmp_path):
    task, config, baseline, source = context(tmp_path)
    baseline['P0'] = baseline['P0'].replace('. ', '.\n')
    plan = planner.build_plan(tmp_path, task, config, baseline, source, None)
    for item in plan['candidate_specs']:
        assert (tmp_path / 'plan' / 'prompts' / (item['slot_id'] + '.txt')).read_bytes() == item['full_prompt'].encode('utf-8')


def test_source_bytes_are_checked_before_any_planner_call(tmp_path, monkeypatch):
    task, config, baseline, source = context(tmp_path)
    Image.new('RGB', (32, 24)).save(source['path'])
    monkeypatch.setattr(planner, 'call_json', lambda *args, **kwargs: pytest.fail('Planner called with changed source'))
    with pytest.raises(HREError) as exc:
        planner.build_plan(tmp_path, task, config, baseline, source, None)
    assert exc.value.code == 'source_modified'


def test_planner_roi_evidence_refs_resolve_to_real_crops(tmp_path):
    task, config, baseline, source = context(tmp_path)
    config['fixture']['issues'][0]['evidence_refs'] = ['lq_roi_face', 'c0_roi_face']
    plan = planner.build_plan(tmp_path, task, config, baseline, source, None)
    for ref in ['lq_roi_face', 'c0_roi_face']:
        item = plan['evidence_registry'][ref]
        assert file_sha256(Path(item['path'])) == item['sha256']
        assert Image.open(item['path']).size == (11, 17)
