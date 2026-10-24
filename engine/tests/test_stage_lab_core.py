import json
from pathlib import Path

import pytest
from PIL import Image


def lab(tmp_path):
    from hre.stage_lab.core import init_lab, add_case
    Image.new('RGB', (32, 24), (45, 60, 75)).save(tmp_path / 'a.png')
    Image.new('RGB', (48, 32), (85, 90, 95)).save(tmp_path / 'b.png')
    root = tmp_path / 'lab'
    init_lab(root, {'one': {'provider': 'demo', 'model': 'demo-one'},
                    'two': {'provider': 'demo', 'model': 'demo-two'}})
    add_case(root, tmp_path / 'a.png', tmp_path / 'b.png', 'scene', task='Match rendering, preserve content.')
    return root


def test_each_stage_runs_without_controller_state(tmp_path):
    from hre.stage_lab.core import run_stage, list_runs, import_output
    root = lab(tmp_path)
    for stage in ['diagnose', 'plan', 'compile']:
        results = run_stage(root, 'scene', stage, ['one', 'two'], context={'action': 'Lift the existing subject shadows.'})
        assert [r['status'] for r in results] == ['completed', 'completed']
        assert all((root / 'runs' / r['id'] / 'result.json').exists() for r in results)
    execution = run_stage(root, 'scene', 'execute', ['one'], prompt='Lift existing shadows.')[0]
    assert execution['status'] == 'completed'
    candidate = root / execution['output']['images'][0]
    assert Image.open(candidate).size == (32, 24)
    judged = run_stage(root, 'scene', 'judge', ['one', 'two'], candidates=[candidate])
    assert all(r['status'] == 'completed' for r in judged)
    assert len(list_runs(root)) == 9
    assert not (root / 'state.json').exists()


def test_selected_output_is_reused_without_regenerating_upstream(tmp_path):
    from hre.stage_lab.core import run_stage, import_output, list_runs
    root = lab(tmp_path)
    chosen = import_output(root, 'scene', 'plan', 'human', data={'actions': [{'target': 'shirt', 'change': 'lift shadows'}]})
    result = run_stage(root, 'scene', 'compile', ['one'], source_runs=[chosen['id']], profile='qwen21')[0]
    assert result['source_runs'] == [chosen['id']]
    assert result['request']['context']['upstream'][0]['data']['actions'][0]['target'] == 'shirt'
    assert 'shirt' in result['request']['prompt']
    assert len(list_runs(root)) == 2
    repeated = run_stage(root, 'scene', 'compile', ['one'], source_runs=[chosen['id']])[0]
    assert repeated['id'] != result['id']
    assert len(list_runs(root)) == 3


def test_judge_does_not_receive_upstream_instruction_by_default(tmp_path):
    from hre.stage_lab.core import import_output, run_stage
    root = lab(tmp_path)
    execution = import_output(root, 'scene', 'execute', 'other', text='SECRET_PLAN_MAKE_IT_ORANGE',
                              images=[tmp_path / 'a.png'])
    judged = run_stage(root, 'scene', 'judge', ['one'], source_runs=[execution['id']],
                       context={'plan': {'goal': 'SECRET_GOAL'}, 'targets': ['SECRET_TARGET']})[0]
    prompt = judged['request']['prompt']
    assert 'SECRET_PLAN' not in prompt
    assert 'SECRET_GOAL' not in prompt and 'SECRET_TARGET' not in prompt
    assert 'other' not in prompt
    assert any(im['role'] == 'C' for im in judged['request']['images'])
    aware = run_stage(root, 'scene', 'judge', ['one'], source_runs=[execution['id']],
                      context={'judge_mode': 'action', 'action': 'Lift the shirt shadows.'})[0]
    assert 'Lift the shirt shadows.' in aware['request']['prompt']


def test_error_in_one_model_does_not_stop_batch(tmp_path):
    from hre.stage_lab.core import save_models, load_lab, run_stage
    root = lab(tmp_path)
    models = load_lab(root)['models']
    models['bad'] = {'provider': 'missing', 'model': 'not-a-model'}
    save_models(root, models)
    rows = run_stage(root, 'scene', 'diagnose', ['bad', 'one'])
    assert [r['status'] for r in rows] == ['error', 'completed']
    assert rows[0]['error']


def test_export_import_supports_external_runs_and_preserves_image_bytes(tmp_path):
    from hre.stage_lab.core import export_request, import_output, list_runs
    root = lab(tmp_path)
    bundle = export_request(root, 'scene', 'execute', 'one', prompt='Change only tone.')
    request = json.loads(bundle.read_text())
    assert request['stage'] == 'execute'
    assert [i['role'] for i in request['images']] == ['A', 'B']
    assert all(not Path(i['path']).is_absolute() and (bundle.parent / i['path']).is_file()
               for i in request['images'])
    assert 'Change only tone.' in request['prompt']
    row = import_output(root, 'scene', 'execute', 'external-model', images=[tmp_path / 'b.png'])
    output = root / row['output']['images'][0]
    assert output.read_bytes() == (tmp_path / 'b.png').read_bytes()
    assert row['output']['metrics']['size_matches_A'] is False


def test_cross_case_source_fails_clearly(tmp_path):
    from hre.stage_lab.core import add_case, import_output, run_stage
    root = lab(tmp_path)
    add_case(root, tmp_path/'a.png', tmp_path/'b.png', 'second')
    chosen = import_output(root, 'scene', 'diagnose', 'external', data={'observation': 'subject dark'})
    with pytest.raises(ValueError, match='case'):
        run_stage(root, 'second', 'plan', ['one'], source_runs=[chosen['id']])


def test_native_prompt_override_matches_recorded_request(tmp_path):
    from hre.stage_lab.core import import_output, run_stage
    from hre.stage_lab.native_workers import compiled_condition, instruction
    root = lab(tmp_path)
    chosen = import_output(root, 'scene', 'compile', 'external', data={'native_prompt': 'OLD'})
    row = run_stage(root, 'scene', 'execute', ['one'], source_runs=[chosen['id']], prompt='NEW')[0]
    assert compiled_condition(row['request'])[0] == row['request']['prompt'] == 'NEW'
    row = run_stage(root, 'scene', 'compile', ['one'], context={'instruction': 'OLD'}, prompt='NEW')[0]
    assert instruction(row['request']) == 'NEW'


@pytest.mark.parametrize('data,expected', [
    ('EXACT_COMPILED_TEXT', 'EXACT_COMPILED_TEXT'),
    ({'short_description': 'A night scene', 'edit_instruction': 'lift shirt'}, None),
    ({'vgl': {'edit_instruction': 'retain A geometry'}}, None),
])
def test_http_and_native_execute_use_same_imported_condition(tmp_path, data, expected):
    from hre.stage_lab.core import import_output, run_stage
    from hre.stage_lab.native_workers import compiled_condition
    root = lab(tmp_path)
    compiled = import_output(root, 'scene', 'compile', 'external', data=data)
    row = run_stage(root, 'scene', 'execute', ['one'], source_runs=[compiled['id']])[0]
    assert row['request']['prompt'] == compiled_condition(row['request'])[0]
    if expected:
        assert row['request']['prompt'] == expected
    else:
        assert json.loads(row['request']['prompt']) == data.get('vgl', data)


def test_judge_retains_external_candidate_after_original_is_removed(tmp_path):
    from hre.stage_lab.core import run_stage
    root = lab(tmp_path)
    candidate = tmp_path / 'temporary_candidate.png'
    Image.new('RGB', (32, 24), 'orange').save(candidate)
    expected = candidate.read_bytes()
    judged = run_stage(root, 'scene', 'judge', ['one'], candidates=[candidate])[0]
    candidate.unlink()
    stored = next(Path(i['path']) for i in judged['request']['images'] if i['role'] == 'C')
    assert stored.is_relative_to(root / 'runs' / judged['id'])
    assert stored.read_bytes() == expected
