from pathlib import Path
import json
import pytest
from test_hre_cli import create, invoke


def test_wait_state_operations_do_not_offer_candidate_import_for_analysis():
    from hre.ui import allowed_operations
    assert 'candidate' not in allowed_operations('WAIT_DIAGNOSIS')
    assert 'response' in allowed_operations('WAIT_DIAGNOSIS')
    assert 'candidate' in allowed_operations('WAIT_EXECUTION')
    assert 'resume' in allowed_operations('PAUSED')
    assert not ({'start','response','candidate','resume'} & set(allowed_operations('COMPLETED')))


def test_streamlit_renders_real_case_and_pause_resume(tmp_path,monkeypatch):
    from streamlit.testing.v1 import AppTest
    root=create(tmp_path);invoke('case','start','--case-root',root)
    monkeypatch.setenv('HRE_DATA_ROOT',str(tmp_path/'cases'))
    script=Path(__file__).parents[1]/'src'/'hre'/'ui.py'
    app=AppTest.from_file(str(script)).run()
    assert not app.exception
    assert len(app.tabs)==6
    assert any('WAIT_EXECUTION' in str(t.value) for t in app.markdown)
    next(b for b in app.button if b.label=='Pause').click().run()
    assert not app.exception
    assert invoke('case','show','--case-root',root)['workflow_state']=='PAUSED'
    next(b for b in app.button if b.label=='Resume').click().run()
    assert not app.exception
    assert invoke('case','show','--case-root',root)['workflow_state']=='WAIT_EXECUTION'


@pytest.mark.parametrize('status', ['WAIT_DIAGNOSIS','WAIT_COMPOSITION','WAIT_VERIFICATION','WAIT_REFINEMENT'])
def test_each_analysis_wait_allows_response_and_forbids_execution(status):
    from hre.ui import allowed_operations
    operations=set(allowed_operations(status))
    assert {'task','response','pause','cancel'} <= operations
    assert not {'candidate','submitted','start','resume'} & operations


def test_evidence_wait_requires_evidence_action_and_no_manual_stage_override():
    from hre.ui import allowed_operations
    operations=set(allowed_operations('WAIT_EVIDENCE'))
    assert {'evidence','pause','cancel'} <= operations
    assert not {'response','candidate','submitted','start'} & operations


def test_streamlit_analysis_displays_task_without_candidate_controls(tmp_path,monkeypatch):
    from streamlit.testing.v1 import AppTest
    root=create(tmp_path,'agent_single');invoke('case','start','--case-root',root)
    monkeypatch.setenv('HRE_DATA_ROOT',str(tmp_path/'cases'))
    app=AppTest.from_file(str(Path(__file__).parents[1]/'src'/'hre'/'ui.py')).run()
    assert not app.exception
    labels={b.label for b in app.button}
    assert 'Validate and import response' in labels
    assert 'Validate and import raw candidate' not in labels
    assert 'Start' not in labels


def test_ui_uploaded_extras_bind_only_declared_sources_and_keep_observed_order(tmp_path):
    from io import BytesIO
    from hre.ui import bind_uploaded_extras
    extra=BytesIO(b'actual raw partial bytes');extra.name='../unsafe_name.png'
    metadata={'actual_generation_count':2,'provider_order':1,'model_observed':{'ui_model_name':'unknown'}}
    rows=[{'source':'../unsafe_name.png','provider_order':0,'complete':False}]
    output=bind_uploaded_extras(metadata,[extra],rows,tmp_path)
    record=output['extras'][0]
    assert record['provider_order']==0 and record['complete'] is False
    assert Path(record['source']).parent==tmp_path and Path(record['source']).read_bytes()==extra.getvalue()
    assert output['model_observed']==metadata['model_observed'] and metadata.get('extras') is None
    with pytest.raises(Exception,match='filename'):
        bind_uploaded_extras(metadata,[extra],[{'source':'other.png','provider_order':0,'complete':False}],tmp_path/'other')


def test_streamlit_execution_exposes_extra_uploads_and_explicit_order_table(tmp_path,monkeypatch):
    from streamlit.testing.v1 import AppTest
    root=create(tmp_path);invoke('case','start','--case-root',root)
    monkeypatch.setenv('HRE_DATA_ROOT',str(tmp_path/'cases'))
    app=AppTest.from_file(str(Path(__file__).parents[1]/'src'/'hre'/'ui.py')).run()
    assert not app.exception
    assert any('Extra upload order/completion JSON' in field.label for field in app.text_area)
    assert any('Extra raw outputs' in field.label for field in app.get('file_uploader'))


@pytest.mark.parametrize('failed',[True,False])
def test_streamlit_explicit_new_generation_retry_after_failure_or_confirmed_release(tmp_path,monkeypatch,failed):
    from streamlit.testing.v1 import AppTest
    root=create(tmp_path,'direct_best_of_3');initial=invoke('case','start','--case-root',root)
    monkeypatch.setenv('HRE_DATA_ROOT',str(tmp_path/'cases'))
    app=AppTest.from_file(str(Path(__file__).parents[1]/'src'/'hre'/'ui.py')).run()
    if failed:
        next(button for button in app.button if button.label=='Record submitted execution failure').click().run()
    else:
        next(button for button in app.button if button.label=='Pause').click().run()
        next(button for button in app.button if button.label=='Confirm never submitted and release reservation').click().run()
    assert not app.exception
    paused=invoke('case','show','--case-root',root)
    assert paused['workflow_state']=='PAUSED' and paused['pending_task'] is None
    next(button for button in app.button if button.label=='Retry generation (new task and reserved budget)').click().run()
    assert not app.exception
    after=invoke('case','show','--case-root',root)
    assert after['workflow_state']=='WAIT_EXECUTION'
    assert after['pending_task']['task_id']!=initial['pending_task']['task_id']
    assert after['budget']['ledger'][-1]['generation_id']!=initial['budget']['ledger'][0]['generation_id']
    assert after['budget']['consumed']==(1 if failed else 0) and after['budget']['reserved']==1
