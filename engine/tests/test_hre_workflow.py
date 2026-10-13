import pytest
from test_hre_protocol import make_case,diagnosis,current_request


def test_baseline_never_reserves_generation(tmp_path):
    from hre.workflow import Controller
    root=make_case(tmp_path,'baseline',0); s=Controller(root).start()
    assert s['workflow_state']=='COMPLETED' and s['terminal_reason']=='baseline_only'
    assert not s['success'] and not s['selection']['fallback']
    assert s['budget']['ledger']==[]


def test_direct_reserves_before_dispatch_and_restart_is_idempotent(tmp_path):
    from hre.workflow import Controller
    root=make_case(tmp_path,'direct_ref',1);c=Controller(root);s=c.start()
    assert s['workflow_state']=='WAIT_EXECUTION' and s['budget']['reserved']==1
    req=current_request(root)
    s=Controller(root).recover()
    assert s['pending_task']['task_id']==req['task_id'] and s['budget']['reserved']==1
    c.mark_submitted(req['task_id']);s=c.mark_submitted(req['task_id'])
    assert s['budget']['consumed']==1 and s['budget']['reserved']==0


def test_diagnosis_acceptance_idempotent_and_pause_late_done(tmp_path):
    from hre.workflow import Controller
    from hre.protocol import TaskWriter
    root=make_case(tmp_path);c=Controller(root);c.start();req=current_request(root)
    done=TaskWriter(root).commit_submission(req,diagnosis())
    c.pause('operator absent')
    assert c.consume_done(done).code=='paused'
    c.resume()
    r=c.consume_done(done)
    assert r.duplicate
    assert c.state()['workflow_state']=='WAIT_COMPOSITION'
    n=c.state()['revision'];assert c.consume_done(done).duplicate;assert c.state()['revision']==n


def test_accepted_unknown_diagnosis_requires_new_task_without_budget(tmp_path):
    from hre.workflow import Controller
    from hre.protocol import TaskWriter
    root=make_case(tmp_path);c=Controller(root);c.start();req=current_request(root)
    p=diagnosis();p['reference_usable']='unknown'
    done=TaskWriter(root).commit_submission(req,p);assert c.consume_done(done).accepted
    assert c.state()['workflow_state']=='PAUSED' and c.state()['pending_task'] is None
    c.resume('retry_analysis');assert current_request(root)['task_id']!=req['task_id']
    assert c.state()['budget']['ledger']==[]


def compose_payload():
    return dict(edit_prompt='Brighten image A while preserving its content.',edit_targets=[dict(priority=1,scope='global',region_in_a=None,operation='brighten A',source_gap_ids=['bright'],confidence=.9)],protected_content=[dict(kind='composition',instruction='preserve A composition',asset_role='prediction',evidence_ids=[])],evidence_ids=[],reference_limitations=['B is appearance reference only'])


def verification(style='improved',confidence=.9,retry_focus=None):
    return dict(style_alignment=style,content_preservation='pass',critical_defects=[],remaining_issues=[],retry_focus=retry_focus or [],confidence=confidence,style_observations=[dict(dimension='brightness',a_to_c_change='C brighter',c_vs_b='C approaches B rendering',comparability='comparable',confidence=.9)],preservation_observations=[dict(kind=k,observation='Same content, or explicitly absent identity/text',status='pass',confidence=.9) for k in ('composition','geometry','identity','text','scene_content')])


def send(root,payload,error=None):
    from hre.protocol import TaskWriter
    from hre.workflow import Controller
    done=TaskWriter(root).commit_submission(current_request(root),payload,error=error)
    result=Controller(root).consume_done(done)
    assert result.accepted,(result.code,result.message)
    return done


def execute_image(root,tmp_path,color=(85,75,65),count=1):
    from hre.workflow import Controller
    from hre.desktop import import_candidate
    from PIL import Image
    from hre.models import now
    c=Controller(root);req=current_request(root);c.mark_submitted(req['task_id'])
    image=tmp_path/f"out_{req['round']}.png";Image.new('RGB',(16,12),color).save(image)
    done=import_candidate(root,req['task_id'],image,{'actual_generation_count':count,'submitted_at':now(),'provider_order':0,'submission_confirmed':True})
    result=c.consume_done(done);assert result.accepted,(result.code,result.message)
    return done


def ready_execute(root):
    from hre.workflow import Controller
    c=Controller(root);c.start();send(root,diagnosis());send(root,compose_payload())
    assert c.state()['workflow_state']=='WAIT_EXECUTION'


def test_actual_adaptive_image_refinement_and_last_slot_acceptance(tmp_path):
    from hre.workflow import Controller
    root=make_case(tmp_path,max_generations=2);ready_execute(root);execute_image(root,tmp_path)
    assert Controller(root).state()['workflow_state']=='WAIT_VERIFICATION'
    send(root,verification('unchanged',retry_focus=['brighten more']))
    req=current_request(root);assert req['round']==1 and req['payload']['source_round']==0
    send(root,dict(edit_prompt='Brighten image A more, keeping all geometry.',changes=[dict(priority=1,previous_instruction='brighten',revised_instruction='brighten more',reason='still dark',based_on_issue='brighten more')],retry_focus=['brighten more'],source_round=0))
    req=current_request(root);assert req['round']==1
    assert [a['role'] for a in req['input_assets']]==['prediction','reference']
    execute_image(root,tmp_path,(110,100,90));send(root,verification())
    s=Controller(root).state();assert s['workflow_state']=='COMPLETED' and s['success']
    assert s['terminal_reason']=='accepted' and s['budget']['consumed']==2
    assert s['selection']['selected_round']==1


def test_fixed_k_does_not_stop_on_first_accepted(tmp_path):
    from hre.workflow import Controller
    root=make_case(tmp_path,'direct_best_of_3',3);c=Controller(root);c.start()
    for r in range(3):
        execute_image(root,tmp_path,(60+r*10,65,70));send(root,verification('improved' if r==0 else 'unchanged'))
        s=c.state()
        if r<2:assert s['workflow_state']=='WAIT_EXECUTION' and s['budget']['reserved']==1
    assert s['terminal_reason']=='fixed_k_complete' and s['success']
    assert s['selection']['selected_round']==0 and s['budget']['consumed']==3


def test_duplicate_canonical_a_stops_without_verification(tmp_path):
    from hre.workflow import Controller
    root=make_case(tmp_path,'direct_ref',1);c=Controller(root);c.start()
    execute_image(root,tmp_path,(50,40,30))
    s=c.state();assert s['workflow_state']=='COMPLETED'
    assert s['terminal_reason'] in ('duplicate_output','canonical_duplicate_output') and not s['success']
    assert s['candidates']==[] and s['budget']['consumed']==1


def test_uncertain_intent_holds_reservation_until_reconciled(tmp_path):
    from hre.workflow import Controller
    from hre.storage import write_json
    root=make_case(tmp_path,'direct_ref',1);c=Controller(root);c.start();req=current_request(root)
    write_json(root/f"tasks/{req['task_id']}/submission_intent.json",{'task_id':req['task_id'],'submitted':None})
    s=c.recover();assert s['workflow_state']=='PAUSED' and s['budget']['reserved']==1
    with pytest.raises(Exception):c.resume()
    c.mark_submitted(req['task_id']);s=c.resume()
    assert s['workflow_state']=='WAIT_EXECUTION' and s['budget']['consumed']==1


def test_unknown_verification_new_task_same_candidate_without_generation(tmp_path):
    from hre.workflow import Controller
    root=make_case(tmp_path);ready_execute(root);execute_image(root,tmp_path)
    old=current_request(root);send(root,verification('uncertain',confidence=.4))
    c=Controller(root);s=c.state();assert s['workflow_state']=='PAUSED' and s['pending_task'] is None
    c.resume('retry_analysis');new=current_request(root)
    assert new['task_id']!=old['task_id'] and new['round']==old['round']
    assert new['payload']['candidate_id']==old['payload']['candidate_id'] and c.state()['budget']['consumed']==1


def test_extra_sampling_is_recorded_untruncated_and_failed(tmp_path):
    from hre.workflow import Controller
    root=make_case(tmp_path,'direct_ref',1);c=Controller(root);c.start();req=current_request(root)
    s=c.mark_submitted(req['task_id'],3)
    assert s['workflow_state']=='FAILED' and s['terminal_reason']=='extra_sampling'
    assert s['budget']['consumed']==3 and not s['success']


def test_format_repair_same_task_only_once_and_stale_attempt_quarantined(tmp_path):
    from hre.workflow import Controller
    from hre.protocol import TaskWriter
    root=make_case(tmp_path);c=Controller(root);c.start();old=current_request(root)
    done=TaskWriter(root).commit_submission(old,diagnosis());new=c.retry_transport()
    assert new['task_id']==old['task_id'] and new['attempt']==1
    assert c.state()['budget']['consumed']==0
    result=c.consume_done(done);assert not result.accepted and result.code=='identity_mismatch'
    assert c.state()['pending_task']['attempt']==1
    s=c.retry_transport();assert s['workflow_state']=='PAUSED'


def test_same_task_distinct_valid_responses_conflict_after_accepted(tmp_path):
    from hre.workflow import Controller
    from hre.protocol import TaskWriter
    root=make_case(tmp_path);c=Controller(root);c.start();req=current_request(root)
    first=TaskWriter(root).commit_submission(req,diagnosis());assert c.consume_done(first).accepted
    d=diagnosis();d['uncertainties']=['different observation']
    second=TaskWriter(root).commit_submission(req,d)
    result=c.consume_done(second);assert result.code=='conflict' and not result.accepted
    assert c.state()['workflow_state']=='WAIT_COMPOSITION'


def test_cancel_does_not_accept_late_done_or_forget_late_charges(tmp_path):
    from hre.workflow import Controller
    from hre.protocol import TaskWriter
    root=make_case(tmp_path,'direct_ref',1);c=Controller(root);c.start();req=current_request(root)
    done=TaskWriter(root).commit_submission(req,None,error=dict(code='editor_failed',message='no image',retryable=True))
    s=c.cancel('operator cancelled');assert not s['success']
    assert c.consume_done(done).code=='terminal_state'
    s=c.mark_submitted(req['task_id']);assert s['budget']['consumed']==1 and s['workflow_state']=='CANCELLED'


def test_execute_error_keeps_reserved_unknown_and_submitted_failure_charged(tmp_path):
    from hre.workflow import Controller
    root=make_case(tmp_path,'direct_ref',1);c=Controller(root);c.start()
    send(root,None,error=dict(code='timeout',message='submission unknown',retryable=True))
    s=c.state();assert s['workflow_state']=='PAUSED' and s['pending_task'] is None
    assert s['budget']['reserved']==1 and s['budget']['consumed']==0
    with pytest.raises(Exception):c.resume('retry_analysis')
    c.mark_submitted(s['budget']['ledger'][0]['task_id'])
    assert c.state()['budget']['consumed']==1


def test_two_threads_accept_same_done_once(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from hre.workflow import Controller
    from hre.protocol import TaskWriter
    root=make_case(tmp_path);Controller(root).start();req=current_request(root)
    done=TaskWriter(root).commit_submission(req,diagnosis())
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:Controller(root).consume_done(done),range(2)))
    assert sum(r.accepted and not r.duplicate for r in results)==1
    assert sum(r.duplicate for r in results)==1
    assert Controller(root).state()['workflow_state']=='WAIT_COMPOSITION'


def test_nonempty_stats_plan_frozen_before_compose(tmp_path):
    from hre.workflow import Controller
    root=make_case(tmp_path);c=Controller(root);c.start()
    d=diagnosis();d['tool_plan']=[dict(tool='STATS',roles=['prediction','reference'],purpose='brightness observations',roi_pair_ids=[],required=True)]
    send(root,d);assert c.state()['workflow_state']=='WAIT_EVIDENCE'
    s=c.collect_evidence();assert s['workflow_state']=='WAIT_COMPOSITION'
    assert s['evidence_plan'][0]['status']=='ok'
    send(root,compose_payload());assert c.state()['budget']['reserved']==1


def test_operator_unknown_submission_is_durable_and_requires_reconciliation(tmp_path):
    from hre.workflow import Controller
    root=make_case(tmp_path,'direct_ref',1);c=Controller(root);c.start();req=current_request(root)
    s=c.mark_submission_unknown(req['task_id'])
    assert s['workflow_state']=='PAUSED' and s['budget']['ledger'][0]['outcome']=='unknown'
    assert s['pending_task']['task_id']==req['task_id']
    c.recover()
    with pytest.raises(Exception):c.resume()
    c.mark_submitted(req['task_id']);s=c.resume()
    assert s['workflow_state']=='WAIT_EXECUTION' and s['budget']['consumed']==1


def test_explicit_generation_retry_consumes_failures_until_three_slot_guard(tmp_path):
    from hre.workflow import Controller
    root=make_case(tmp_path);ready_execute(root);c=Controller(root)
    for r in range(3):
        req=current_request(root);assert req['round']==r
        c.mark_submitted(req['task_id']);send(root,None,error=dict(code='generation_failed',message='editor produced no image',retryable=True))
        assert c.state()['budget']['consumed']==r+1
        if r<2:c.resume('retry_generation')
    s=c.resume('retry_generation')
    assert s['workflow_state']=='COMPLETED' and s['terminal_reason']=='budget_exhausted'
    assert not s['success'] and s['selection']['fallback']


def test_explicit_retry_after_confirmed_release_reserves_new_generation(tmp_path):
    from hre.workflow import Controller
    root=make_case(tmp_path,'direct_ref',1);c=Controller(root);c.start();old=current_request(root)
    c.release_unsubmitted(old['task_id']);s=c.resume('retry_generation')
    assert s['budget']['consumed']==0 and s['budget']['reserved']==1
    assert current_request(root)['task_id']!=old['task_id']
    assert current_request(root)['payload']['generation_id']!=old['payload']['generation_id']


def test_direct_uses_frozen_prompt_template_and_diagnosis_only_declares_real_tools(tmp_path):
    import json
    from hre.workflow import Controller
    from hre.prompts import render_stage
    root=make_case(tmp_path,'direct_ref',1);Controller(root).start();req=current_request(root)
    bindings=[dict(label=label,asset_id=a['asset_id'],canonical_sha256=a['sha256']) for label,a in zip(['A','B'],req['input_assets'])]
    assert req['payload']['edit_prompt']==json.loads(render_stage('direct_ref',{'image_bindings':bindings}))['edit_prompt']
    other=tmp_path/'other';other.mkdir();root=make_case(other);Controller(root).start();req=current_request(root)
    assert req['payload']['available_tools']==['STATS','ROI_COMPARE']


def test_diagnosis_targets_need_comparability_of_their_own_scope(tmp_path):
    from hre.workflow import Controller
    root=make_case(tmp_path);c=Controller(root);c.start();d=diagnosis()
    d['comparability'][0]['status']='not_comparable'
    send(root,d)
    s=c.state();assert s['workflow_state']=='PAUSED' and s['budget']['reserved']==0


def test_dispatch_expected_revision_rejects_stale_ui_event(tmp_path):
    from hre.workflow import Controller,dispatch_event
    root=make_case(tmp_path);c=Controller(root);s=c.start()
    with pytest.raises(Exception):dispatch_event(root,'pause_requested',{'reason':'stale view','expected_revision':0})
    assert c.state()['revision']==s['revision']


def test_fatal_event_selects_known_candidate_but_never_success(tmp_path):
    from hre.workflow import Controller,dispatch_event
    root=make_case(tmp_path,'direct_best_of_3',3);c=Controller(root);c.start();execute_image(root,tmp_path);send(root,verification())
    s=dispatch_event(root,'fatal_integrity_error',{'reason':'Operator confirmed corrupted external session'})
    assert s['workflow_state']=='FAILED' and not s['success']
    assert s['selection']['kind']=='candidate' and s['selection']['review_required']


def test_low_confidence_missing_observations_pauses_even_with_retry_text(tmp_path):
    from hre.workflow import Controller
    root=make_case(tmp_path);ready_execute(root);execute_image(root,tmp_path)
    p=verification('uncertain',confidence=.4,retry_focus=['increase brightness'])
    p['content_preservation']='uncertain';p['preservation_observations']=[]
    send(root,p);s=Controller(root).state()
    assert s['workflow_state']=='PAUSED' and s['pending_task'] is None
    assert s['budget']['consumed']==1


def test_relative_case_root_is_supported(tmp_path,monkeypatch):
    from hre.workflow import Controller
    root=make_case(tmp_path);monkeypatch.chdir(tmp_path)
    s=Controller(root.relative_to(tmp_path)).start()
    assert s['workflow_state']=='WAIT_DIAGNOSIS'


@pytest.mark.parametrize('crash_point',['state','accepted_projection'])
def test_recover_after_response_commit_replays_next_task_without_reaccepting(tmp_path,monkeypatch,crash_point):
    import hre.storage as storage
    from hre.workflow import Controller
    from hre.protocol import TaskWriter
    root=make_case(tmp_path);c=Controller(root);c.start();req=current_request(root)
    done=TaskWriter(root).commit_submission(req,diagnosis())
    class Crash(BaseException):pass
    if crash_point=='state':
        real=storage.write_json
        def crashing(path,data):
            if path.name=='state.json':raise Crash()
            return real(path,data)
        with monkeypatch.context() as m:
            m.setattr(storage,'write_json',crashing)
            with pytest.raises(Crash):c.consume_done(done)
    else:
        with monkeypatch.context() as m:
            m.setattr(storage.CaseStore,'_project',lambda *args:(_ for _ in ()).throw(Crash()))
            with pytest.raises(Crash):c.consume_done(done)
    s=c.recover();assert s['workflow_state']=='WAIT_COMPOSITION'
    tid=s['pending_task']['task_id'];rev=s['revision']
    assert c.consume_done(done).duplicate
    s=c.recover();assert s['revision']==rev and s['pending_task']['task_id']==tid


def test_baseline_terminal_selection_projection_is_written(tmp_path):
    from hre.workflow import Controller
    from hre.storage import read_json
    root=make_case(tmp_path,'baseline',0);s=Controller(root).start()
    artifact=read_json(root/'final/selection.json')
    assert artifact['selection']==s['selection'] and artifact['success'] is False


@pytest.mark.parametrize('edit_prompt',["Edit Image C. Keep original exposure and color. Save output to /tmp/edit.png and return JSON.","Copy person from Image B into A.","Keep the original exposure and color unchanged."])
def test_composition_editor_contract_violation_cannot_dispatch(tmp_path,edit_prompt):
    from hre.workflow import Controller
    from hre.protocol import TaskWriter
    root=make_case(tmp_path);c=Controller(root);c.start();send(root,diagnosis());req=current_request(root)
    p=compose_payload();p['edit_prompt']=edit_prompt;done=TaskWriter(root).commit_submission(req,p)
    result=c.consume_done(done)
    assert not result.accepted
    assert c.state()['workflow_state']!='WAIT_EXECUTION' and c.state()['budget']['ledger']==[]


def test_refinement_content_copy_cannot_dispatch(tmp_path):
    from hre.workflow import Controller
    from hre.protocol import TaskWriter
    root=make_case(tmp_path);ready_execute(root);execute_image(root,tmp_path);send(root,verification('unchanged',retry_focus=['brighten more']))
    req=current_request(root);payload=dict(edit_prompt='Copy person from Image B into A.',changes=[dict(priority=1,previous_instruction='brighten',revised_instruction='copy person from B',reason='different person',based_on_issue='brighten more')],retry_focus=['brighten more'],source_round=0)
    done=TaskWriter(root).commit_submission(req,payload);result=Controller(root).consume_done(done)
    assert not result.accepted and Controller(root).state()['budget']['consumed']==1
    assert Controller(root).state()['budget']['reserved']==0


def test_composition_priorities_must_be_unique_and_contiguous(tmp_path):
    from hre.workflow import Controller
    from hre.protocol import TaskWriter
    root=make_case(tmp_path);c=Controller(root);c.start();send(root,diagnosis());req=current_request(root)
    p=compose_payload();p['edit_targets'][0]['priority']=3
    result=c.consume_done(TaskWriter(root).commit_submission(req,p))
    assert not result.accepted and c.state()['budget']['reserved']==0


def test_negated_reference_copy_protection_is_valid_editor_instruction(tmp_path):
    from hre.workflow import Controller
    root=make_case(tmp_path);c=Controller(root);c.start();send(root,diagnosis())
    p=compose_payload();p['edit_prompt']='Brighten Image A. Do not copy person or objects from Image B.'
    c._composition_semantics(p,current_request(root),c.state())


def test_prohibited_editor_text_pauses_for_operator_correction(tmp_path):
    from hre.workflow import Controller
    from hre.protocol import TaskWriter
    root=make_case(tmp_path);c=Controller(root);c.start();send(root,diagnosis());req=current_request(root)
    p=compose_payload();p['edit_prompt']='Edit Image C and save output to /tmp/edit.png.'
    assert not c.consume_done(TaskWriter(root).commit_submission(req,p)).accepted
    assert c.state()['workflow_state']=='PAUSED' and c.state()['pending_task']['task_id']==req['task_id']


def test_structured_edit_operation_cannot_conflict_with_safe_edit_prompt(tmp_path):
    from hre.workflow import Controller
    from hre.protocol import TaskWriter
    root=make_case(tmp_path);c=Controller(root);c.start();send(root,diagnosis());req=current_request(root)
    p=compose_payload();p['edit_targets'][0]['operation']='Copy person from Image B into A.'
    result=c.consume_done(TaskWriter(root).commit_submission(req,p))
    assert not result.accepted and c.state()['budget']['reserved']==0


@pytest.mark.parametrize('entrypoint',['direct','dispatch'])
def test_evidence_resolution_releases_lock_and_stale_result_cannot_dispatch(tmp_path,monkeypatch,entrypoint):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from hre.workflow import Controller,dispatch_event
    from hre.evidence import EvidenceService
    from hre.models import HREError
    root=make_case(tmp_path);c=Controller(root);c.start();d=diagnosis()
    d['tool_plan']=[dict(tool='STATS',roles=['prediction'],purpose='brightness',roi_pair_ids=[],required=True)]
    send(root,d);entered=Event();pause_completed=Event();observed=[];real=EvidenceService.resolve
    def slow_actual_resolution(service,state):
        entered.set();observed.append(pause_completed.wait(timeout=1))
        return real(service,state)
    monkeypatch.setattr(EvidenceService,'resolve',slow_actual_resolution)
    with ThreadPoolExecutor(max_workers=2) as pool:
        revision=c.state()['revision']
        collecting=pool.submit(c.collect_evidence if entrypoint=='direct' else lambda:dispatch_event(root,'evidence_ready',dict(expected_revision=revision)));assert entered.wait(timeout=1)
        def pausing():
            result=Controller(root).pause('operator needs review');pause_completed.set();return result
        pausing_result=pool.submit(pausing)
        assert pausing_result.result(timeout=5)['workflow_state']=='PAUSED'
        try:collecting.result(timeout=5)
        except HREError as error:assert error.code=='stale_state'
    assert observed==[True]
    assert c.state()['workflow_state']=='PAUSED' and c.state()['pending_task'] is None


@pytest.mark.parametrize('terminal',['COMPLETED','FAILED','CANCELLED'])
def test_late_actual_generation_delta_preserves_completed_selection_and_success(tmp_path,terminal):
    from hre.workflow import Controller
    root=make_case(tmp_path,'direct_ref' if terminal=='COMPLETED' else 'direct_best_of_3',1 if terminal=='COMPLETED' else 3);c=Controller(root);c.start();req=current_request(root)
    execute_image(root,tmp_path);send(root,verification())
    if terminal=='FAILED':c.fail_integrity('audited integrity failure')
    elif terminal=='CANCELLED':c.cancel('operator cancellation')
    old=c.state();updated=c.mark_submitted(req['task_id'],4)
    assert updated['budget']['consumed']==4
    assert any(d['code']=='extra_sampling' for d in updated['deviations'])
    assert {k:updated[k] for k in ('workflow_state','terminal_reason','success','selection')}=={k:old[k] for k in ('workflow_state','terminal_reason','success','selection')}
    recovered=c.recover()
    assert recovered['selection']==old['selection'] and recovered['success']==old['success']
    from hre.storage import read_json
    event=read_json(sorted((root/'transactions').glob('*.json'))[-1])['event']
    assert event['payload']['charged_delta']==3 and event['payload']['terminal_accounting_only'] is True


@pytest.mark.parametrize('active_stage',['execute','verify'])
def test_repeated_historical_release_does_not_clear_new_execution(tmp_path,active_stage):
    from hre.workflow import Controller
    root=make_case(tmp_path,'direct_ref',1);c=Controller(root);c.start();req=current_request(root)
    c.release_unsubmitted(req['task_id']);c.resume('retry_generation');new=current_request(root)
    if active_stage=='verify':execute_image(root,tmp_path)
    before=c.state();active=current_request(root)
    after=c.release_unsubmitted(req['task_id'])
    assert after==before
    assert after['pending_task']['task_id']==active['task_id']
    assert after['budget']==before['budget']
    if active_stage=='execute':execute_image(root,tmp_path)
    send(root,verification());assert c.state()['success'] is True


@pytest.mark.parametrize('entrypoint',['direct','dispatch'])
@pytest.mark.parametrize('blocking_reason,terminal_reason',[('unusable_reference','unusable_reference'),('required_evidence_missing','evidence_unavailable'),('execute_error:timeout','generation_error'),('verify_error:unavailable','verification_error'),('format_repair_limit_exhausted','protocol_integrity_error')])
def test_stop_from_paused_fails_with_frozen_blocking_reason(tmp_path,blocking_reason,terminal_reason,entrypoint):
    from hre.workflow import Controller,dispatch_event
    from hre.storage import read_json
    root=make_case(tmp_path);c=Controller(root);c.start();c.pause(blocking_reason)
    stopped=c.resume('stop') if entrypoint=='direct' else dispatch_event(root,'stop_requested',{})
    assert stopped['workflow_state']=='FAILED' and stopped['success'] is False
    assert stopped['terminal_reason']==terminal_reason
    events=[read_json(p)['event'] for p in sorted((root/'transactions').glob('*.json'))]
    assert events[-1]['payload']['blocking_reason']==blocking_reason


@pytest.mark.parametrize('invented_field',['retry_focus','based_on_issue'])
def test_refinement_requires_actual_accepted_verifier_issue_membership(tmp_path,invented_field):
    from hre.workflow import Controller
    from hre.protocol import TaskWriter
    root=make_case(tmp_path);ready_execute(root);execute_image(root,tmp_path);send(root,verification('unchanged',retry_focus=['brighten more']))
    request=current_request(root)
    payload=dict(edit_prompt='Brighten image A more while preserving content.',changes=[dict(priority=1,previous_instruction=request['payload']['previous_edit_prompt'],revised_instruction='Brighten image A more.',reason='still dark',based_on_issue='brighten more')],retry_focus=['brighten more'],source_round=request['payload']['source_round'])
    if invented_field=='retry_focus':payload['retry_focus']=['invented issue']
    else:payload['changes'][0]['based_on_issue']='invented unrelated observation'
    result=Controller(root).consume_done(TaskWriter(root).commit_submission(request,payload))
    assert not result.accepted and result.code=='unsupported_refinement_issue'
    assert Controller(root).state()['budget']['consumed']==1 and Controller(root).state()['budget']['reserved']==0


def test_refinement_accepts_real_remaining_issue_and_clipping_reduction(tmp_path):
    from hre.workflow import Controller
    root=make_case(tmp_path);ready_execute(root);execute_image(root,tmp_path)
    feedback=verification('unchanged',retry_focus=['reduce highlight clipping'])
    feedback['remaining_issues']=[dict(dimension='highlight_rolloff',observation='Highlights clip too severely',region_in_a=None,comparability='comparable',confidence=.9)]
    send(root,feedback);request=current_request(root)
    payload=dict(edit_prompt='Reduce excessive highlight brightness in image A to prevent clipping. Do not copy objects from image B.',changes=[dict(priority=1,previous_instruction=request['payload']['previous_edit_prompt'],revised_instruction='Reduce excessive highlights to prevent clipping.',reason='visible clipping',based_on_issue='Highlights clip too severely')],retry_focus=['reduce highlight clipping'],source_round=request['payload']['source_round'])
    send(root,payload)
    assert Controller(root).state()['workflow_state']=='WAIT_EXECUTION' and Controller(root).state()['budget']['reserved']==1


def test_stop_keeps_accepted_candidate_for_review_and_generic_pause_reason(tmp_path):
    from hre.workflow import Controller,dispatch_event
    from hre.reporting import write_report
    from hre.storage import read_json
    root=make_case(tmp_path,'direct_best_of_3',3);c=Controller(root);c.start();execute_image(root,tmp_path);send(root,verification());c.pause('operator review')
    s=dispatch_event(root,'stop_requested',{})
    assert s['workflow_state']=='FAILED' and s['terminal_reason']=='operator_stop' and not s['success']
    assert s['selection']['kind']=='candidate' and s['selection']['review_required'] and not s['selection']['fallback']
    report=write_report(root);summary=read_json(report.with_name('summary.json'))
    assert summary['workflow_state']=='FAILED' and summary['success'] is False
