import json
import pytest
from hre.tool_retouch.trace import StageTrace,operation_diff
from hre.tool_retouch.providers import PendingResponse
from hre.tool_retouch.workflow import ToolWorkflow
from .helpers import fixture,FakeBackend,FakePlanner,FakeReviewer

def test_pause_trace_is_append_only(tmp_path):
    trace=StageTrace(tmp_path)
    def pending():raise PendingResponse('actual request not yet answered')
    with pytest.raises(PendingResponse):trace.call('discover_regions',pending,{'hash':'original'},source='current_chat_offline')
    first=(tmp_path/'trace/000001.json').read_bytes()
    StageTrace(tmp_path).record('discover_regions',{}, {},status='not_run',change='test record only')
    assert (tmp_path/'trace/000001.json').read_bytes()==first
    r=json.loads(first);assert r['status']=='waiting_for_response' and not r['image_changed']

def test_report_records_real_stage_outputs_and_render_index(tmp_path):
    a,b,pairs,p,ca,cb,proposal,c,plan=fixture((96,128))
    result=ToolWorkflow(FakeBackend(),FakePlanner(proposal,plan),FakeReviewer(),p).run(a,b,ca,cb,pairs,{},tmp_path)
    assert result['success'],result
    records=[json.loads(x.read_text()) for x in sorted((tmp_path/'trace').glob('*.json'))]
    stages=[x['stage'] for x in records]
    assert stages.index('statistics')<stages.index('contract_frozen')<stages.index('native_render')<stages.index('verify')
    assert all(not r['image_changed'] for r in records if r['stage'] in ('statistics','contract','plan','verify'))
    diff=next(r['output'] for r in records if r['stage']=='round_comparison')
    assert diff['all_renders_from_original_A'] and diff['operations']['added']
    assert diff['current']['targets'] and diff['reference_observations']
    report=(tmp_path/'REPORT.md').read_text();assert 'native-attempt-1-1.png' in report and 'test_double' in report and '未记录阶段' in report

def test_operation_diff_tracks_parameters_and_removals():
    a={'operations':[{'id':'a','values':{'ev':0}}, {'id':'b','values':{}}]}
    b={'operations':[{'id':'a','values':{'ev':.1}}, {'id':'c','values':{}}]}
    d=operation_diff(a,b)
    assert d['modified'][0]['id']=='a' and d['removed'][0]['id']=='b' and d['added'][0]['id']=='c'

def test_missing_input_exports_failure_report(tmp_path):
    from argparse import Namespace
    from hre.tool_retouch.cli import dispatch
    from hre.storage import write_json
    from .test_cli_experiment import setup_case
    config,_,_=setup_case(tmp_path/'case');config['source']['path']='missing.jpg'
    path=tmp_path/'case/config.json';write_json(path,config)
    r=dispatch(Namespace(tool_action='run',config=path,out=tmp_path/'out'))
    assert r['status']=='execution_failed'
    record=json.loads((tmp_path/'out/trace/000001.json').read_text())
    assert record['stage']=='input_preparation' and record['status']=='failed'
    assert (tmp_path/'out/REPORT.md').is_file()
