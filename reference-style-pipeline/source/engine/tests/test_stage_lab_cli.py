import json
from pathlib import Path

from hre.cli import main


def test_demo_and_stage_fanout(tmp_path, capsys):
    root = tmp_path / 'lab'
    assert main(['lab', 'demo', '--root', str(root)]) == 0
    demo = json.loads(capsys.readouterr().out)
    assert demo['synthetic'] is True
    assert Path(demo['report']).is_file()
    from hre.stage_lab.core import list_runs
    rows = list_runs(root)
    assert {r['stage'] for r in rows} == {'diagnose', 'plan', 'compile', 'execute', 'judge'}
    assert all(r['status'] == 'completed' for r in rows)
    sources = [r['id'] for r in rows if r['stage'] == 'diagnose']
    assert main(['lab', 'run', '--root', str(root), '--case-id', demo['case_id'],
                 '--stage', 'plan', '--models', 'demo_soft', 'demo_strong', '--from-run', *sources]) == 0
    result = json.loads(capsys.readouterr().out)
    assert len(result['runs']) == 4
    assert all(len(r['source_runs']) == 1 for r in result['runs'])
    executions = [r['id'] for r in rows if r['stage'] == 'execute']
    candidate = root / 'cases' / demo['case_id'] / 'A.png'
    assert main(['lab', 'run', '--root', str(root), '--case-id', demo['case_id'],
                 '--stage', 'judge', '--models', 'demo_soft', '--from-run', *executions,
                 '--candidate', str(candidate)]) == 0
    judged = json.loads(capsys.readouterr().out)['runs']
    assert [r['source_runs'] for r in judged] == [[executions[0]], [executions[1]], []]


def test_export_import_and_error_exit(tmp_path, capsys):
    root = tmp_path / 'lab'
    main(['lab', 'demo', '--root', str(root)])
    demo = json.loads(capsys.readouterr().out)
    common = ['--root', str(root), '--case-id', demo['case_id'], '--stage', 'plan']
    assert main(['lab', 'export', *common, '--model', 'demo_soft']) == 0
    exported = json.loads(capsys.readouterr().out)
    assert Path(exported['request']).exists()
    response = tmp_path / 'external.json'
    response.write_text('{"actions":[{"region":"subject","change":"lift"}]}')
    assert main(['lab', 'import', *common, '--model', 'external', '--json', str(response)]) == 0
    imported = json.loads(capsys.readouterr().out)
    assert imported['run']['output']['data']['actions'][0]['region'] == 'subject'
    from hre.stage_lab.core import save_models
    save_models(root, {'bad': {'provider': 'does_not_exist'}})
    assert main(['lab', 'run', *common, '--models', 'bad']) == 2
    assert json.loads(capsys.readouterr().out)['accepted'] is False
