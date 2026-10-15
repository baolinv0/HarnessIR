"""Real-file audit: frozen sources, role isolation, resume, false-output guard."""
import importlib.metadata
import platform
import psutil
from realzoom_flow import ROOT,BATCH,prepare,scan,import_result
from hir_manual.service import Controller
from hir_manual.storage import read_json,write_json,sha256_file,now

ctl=Controller(ROOT);m=prepare();ids=[r['cases'] for r in m['images']];assert len(m['images'])==15
assert [r['cases'] for r in prepare()['images']]==ids
records=[]
for r in m['images']:
    assert sha256_file(__import__('pathlib').Path(r['input_path']))==r['original_sha256']
    for arm,cid in r['cases'].items():
        case=ctl.case(cid);state=ctl.inspect(cid);req=ctl.current_task(cid)
        assert state.budget.consumed==0 and not state.workflow_completed
        assert sha256_file(case.path('input/canonical.png'))==r['canonical_sha256']
        if req:
            assert not any('gt.' in a.path.lower() or 'reference' in a.path.lower() for a in req.allowed_assets)
            if req.role=='execute':assert len(req.allowed_assets)==1 and req.allowed_assets[0].path=='input/canonical.png' and set(req.context)<=set(['instruction','instruction_sha256','request_one_image','new_session_required'])
        else:assert arm=='harness' and state.workflow_status=='WAIT_EVIDENCE'
        if arm=='direct':assert req and req.role=='execute'
        records.append(dict(sample_id=r['sample_id'],arm=arm,task_id=req.task_id if req else None,role=req.role if req else None,source_hash_valid=True,GT_read=False))
cid=m['images'][0]['cases']['direct'];before=ctl.inspect(cid).model_dump()
try:
    import_result(m['images'][0]['sample_id'],'direct',ctl.case(cid).path('input/canonical.png'),'audit source-copy guard',None)
    raise AssertionError('Source copy incorrectly accepted')
except ValueError as e:
    assert 'Unchanged source copy' in str(e)
assert ctl.inspect(cid).model_dump()==before
state=scan()
write_json(BATCH/'audit.json',dict(passed=True,checked_at=now(),scope='actual frozen file/role/resume validation; not image restoration acceptance',input_count=15,cases_checked=30,source_copy_rejected=True,source_copy_cost=0,no_duplicate_cases_on_resume=True,actual_generated_images=state['actual_generations'],real_full_cycle_passed=state['real_full_cycle_passed'],records=records))
write_json(BATCH/'environment.json',dict(recorded_at=now(),python=platform.python_version(),controller_packages={p:importlib.metadata.version(p) for p in ['Pillow','pydantic','psutil','jsonschema']},available_memory_mb=psutil.virtual_memory().available/1048576,role_model_display='GPT-6.1 Sol 轻度',model_backend_revision=None,role_entry='current Work visual analysis',executor_actual_run=False,independent_verifier_actual_run=False,desktop_probe=dict(click_error='coordinate input geometry is unavailable',keyboard_new_chat_opened=False),CPU_OCR_preflight=read_json(ROOT/'runtime/realzoom_cpu_ocr_preflight.json')))
print({'actual_file_audit_passed':True,'inputs':15,'cases':30,'source_copy_rejected':True,'real_edits':0})
