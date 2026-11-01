"""Synthetic legacy UI host-timing probe; no production patches or model calls.

Uses the public AppTest run(timeout=30) option explicitly. This is separate
from the unchanged legacy tests' three-second default, not a replacement result.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(REPO / 'engine/src'), str(REPO / 'engine/tests')]
from streamlit.testing.v1 import AppTest
from test_hre_cli import create, invoke

SCRIPT = REPO / 'engine/src/hre/ui.py'
results = {'fixture_kind': 'synthetic local UI only', 'timeout_seconds': 30, 'scenarios': []}


def click(app, label):
    next(button for button in app.button if button.label == label).click().run(timeout=30)
    assert not app.exception


with tempfile.TemporaryDirectory(prefix='unified-ui-timing-') as directory:
    parent = Path(directory)
    p = parent / 'pause'
    p.mkdir()
    root = create(p)
    invoke('case', 'start', '--case-root', root)
    os.environ['HRE_DATA_ROOT'] = str(p / 'cases')
    app = AppTest.from_file(str(SCRIPT)).run(timeout=30)
    assert not app.exception and len(app.tabs) == 6
    click(app, 'Pause')
    assert invoke('case', 'show', '--case-root', root)['workflow_state'] == 'PAUSED'
    click(app, 'Resume')
    assert invoke('case', 'show', '--case-root', root)['workflow_state'] == 'WAIT_EXECUTION'
    results['scenarios'].append({'scenario': 'pause_resume', 'pass': True})

    for failed in (True, False):
        p = parent / str(failed)
        p.mkdir()
        root = create(p, 'direct_best_of_3')
        initial = invoke('case', 'start', '--case-root', root)
        os.environ['HRE_DATA_ROOT'] = str(p / 'cases')
        app = AppTest.from_file(str(SCRIPT)).run(timeout=30)
        assert not app.exception
        if failed:
            click(app, 'Record submitted execution failure')
        else:
            click(app, 'Pause')
            click(app, 'Confirm never submitted and release reservation')
        paused = invoke('case', 'show', '--case-root', root)
        assert paused['workflow_state'] == 'PAUSED' and paused['pending_task'] is None
        click(app, 'Retry generation (new task and reserved budget)')
        after = invoke('case', 'show', '--case-root', root)
        assert after['workflow_state'] == 'WAIT_EXECUTION'
        assert after['pending_task']['task_id'] != initial['pending_task']['task_id']
        assert after['budget']['ledger'][-1]['generation_id'] != initial['budget']['ledger'][0]['generation_id']
        assert after['budget']['consumed'] == (1 if failed else 0) and after['budget']['reserved'] == 1
        results['scenarios'].append({'scenario': 'failed_retry' if failed else 'released_retry', 'pass': True})
print(json.dumps(results, indent=2))
