"""Synthetic manual handoff checks, not a real desktop editing experiment."""
import importlib.util
from pathlib import Path

from PIL import Image
import pytest

from hir_manual.service import Controller
from hir_manual.storage import read_json

ROOT=Path(__file__).resolve().parents[2]


def setup_study(tmp_path,photo,fixture_json,monkeypatch):
    spec=importlib.util.spec_from_file_location('no_t4_flow',ROOT/'engine/scripts/no_t4_flow.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setattr(module,'ROOT',tmp_path);monkeypatch.setattr(module,'STUDY',tmp_path/'study')
    ctl=Controller(tmp_path);ids={}
    for arm in ('direct','harness'):
        state=ctl.new(photo,'Synthetic handoff fixture',{'auto_local_tools':False})
        diagnosis=fixture_json('diagnosis');diagnosis['tool_plan']=[]
        assert ctl.import_json(state.case_id,state.pending_task_id,diagnosis,'synthetic fixture').accepted
        req=ctl.current_task(state.case_id)
        assert ctl.import_json(state.case_id,req.task_id,fixture_json('composition'),'synthetic fixture').accepted
        ids[arm+'_case_id']=state.case_id
    monkeypatch.setattr(module,'prepare',lambda:ids)
    return module,ctl,ids


def test_source_copy_rejected_without_generation_cost(tmp_path,photo,fixture_json,monkeypatch):
    module,ctl,ids=setup_study(tmp_path,photo,fixture_json,monkeypatch)
    source=ctl.case(ids['harness_case_id']).path('input/canonical.png')
    with pytest.raises(ValueError,match='unchanged source copy'):
        module.import_edit('harness',source,'synthetic fixture')
    state=ctl.inspect(ids['harness_case_id'])
    assert state.workflow_status=='WAIT_EXECUTION' and state.budget.consumed==0


def test_import_issues_independent_verifier_and_separates_first_final(tmp_path,photo,fixture_json,monkeypatch):
    module,ctl,ids=setup_study(tmp_path,photo,fixture_json,monkeypatch)
    generated=tmp_path/'synthetic_output.png';Image.new('RGB',(64,48),(40,60,80)).save(generated)
    result=module.import_edit('harness',generated,'synthetic fixture','synthetic-editor')
    assert result['desktop_actual_generations']==1 and not result['full_real_flow_passed']
    req=ctl.current_task(ids['harness_case_id'])
    assert req.role=='verify' and req.context['independent_session_required']
    assert 'instruction' not in req.context
    assert [a.path for a in req.allowed_assets][0]=='input/canonical.png' and len(req.allowed_assets)==2
    assert result['first_round_and_final']['harness']['first_round']['round']==1
    assert result['first_round_and_final']['harness']['final_round'] is None
