"""Explicit opt-in real CPU backend tests. Planner/reviewer remain test doubles."""
import os
from pathlib import Path
import pytest
from hre.tool_retouch.backend import PhotoCraftAdapter
from hre.tool_retouch.color import digest_bytes
from hre.tool_retouch.probe import probe
from hre.tool_retouch.workflow import ToolWorkflow
from .helpers import fixture, FakePlanner, FakeReviewer

@pytest.fixture
def actual_backend():
    executable=os.environ.get('HRE_TEST_PHOTOCRAFT_WORKER')
    if not executable:
        pytest.skip('real PhotoCraft opt-in binary not configured')
    return PhotoCraftAdapter(executable,digest_bytes(Path(executable).read_bytes()))

def test_actual_cpu_probe(actual_backend,tmp_path):
    result=probe(actual_backend,tmp_path/'probe')
    assert result['pass'],result
    assert not actual_backend.simulation

def test_actual_backend_workflow(actual_backend,tmp_path):
    a,b,pairs,policy,ca,cb,proposal,contract,plan=fixture((96,128))
    result=ToolWorkflow(actual_backend,FakePlanner(proposal,plan),FakeReviewer(),policy).run(a,b,ca,cb,pairs,{},tmp_path)
    assert result['success'],result
    assert result['simulation'] and not result['real_effect_validated']
    assert result['delivery']['native_checks']['pass']
    assert actual_backend.receipts

def test_actual_process_timeout_falls_back(actual_backend,tmp_path):
    a,b,pairs,policy,ca,cb,proposal,contract,plan=fixture()
    actual_backend.timeout=1e-9
    result=ToolWorkflow(actual_backend,FakePlanner(proposal,plan),FakeReviewer(),policy).run(a,b,ca,cb,pairs,{},tmp_path)
    assert result['status']=='execution_failed',result
    assert not result['success'] and result['output']=='original_A'

def test_actual_worker_rejects_unsafe_requests(actual_backend,tmp_path):
    import json
    import subprocess
    import numpy as np
    from hre.tool_retouch.color import srgb_profile
    np.full((1,1,3),.25,dtype='<f4').tofile(tmp_path/'source.f32')
    (tmp_path/'working.icc').write_bytes(srgb_profile())
    for tool,values in [('exposure',{'ev':2.}),('shell',{}),('exposure',{'wrong':0.})]:
        (tmp_path/'request.json').write_text(json.dumps({'width':1,'height':1,'operations':[{'tool':tool,'mask':False,'values':values}]}))
        result=subprocess.run([str(actual_backend.executable)],cwd=tmp_path,env=actual_backend._env(),capture_output=True,text=True,timeout=30)
        assert result.returncode==2 and result.stderr
        assert not (tmp_path/'output.f32').exists()
