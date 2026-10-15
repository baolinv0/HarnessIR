"""Human-authorized no-T4 real-photo workflow; never fabricates editor output.

Use existing GPU T1-T3 contracts/cache and auditable skip_tool operations.
Direct is a declared fixed text baseline; Harness Composer is a real role task.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'engine/src'))
from hir_manual.service import Controller,history
from hir_manual.storage import read_json,write_json,sha256_file,atomic_write,now
from hir_manual.tool_models import EvidenceProfile
from hir_manual.tool_registry import make_contract,canonicalizer_version_from_metadata
from hir_manual.cache import EvidenceCache

STUDY=ROOT/'runtime/no_t4_flow/spaq_00002'
DIRECT_INSTRUCTION=("Restore this photograph conservatively. Reduce visible noise and blur where the original supports an improvement, "
    "and improve visibility without changing the scene or its lighting character. Preserve the original framing, perspective, "
    "objects, people, facial identity, text, colours, and natural texture. Do not invent missing details, replace unreadable text, "
    "beautify faces, add or remove objects, or introduce sharpening halos. Return one restored photograph with the same aspect ratio.")


def prepare():
    if (STUDY/'study.json').exists():return read_json(STUDY/'study.json')
    batch=ROOT/'runtime/quality20/pilot20_20261013_stable_v2'
    selected=next(r for r in read_json(batch/'manifest.json')['images'] if r['sample_id']=='spaq_00002')
    previous=next(r for r in read_json(batch/'issued_tasks.json')['records'] if r['sample_id']=='spaq_00002')
    ctl=Controller(ROOT)
    config=dict(evidence_profile_id='gpu_full_v1',auto_local_tools=False,branch_type='manual_variant',
        parent_case_id=previous['case_id'],experiment_condition='no_T4_user_requested',
        formal_experiment_eligible=False,semantic_evidence_policy='excluded_by_user',semantic_exclusion_reason='先不用语义分割证据测试完整流程',
        desktop_original_rgb_equivalent_upload=True)
    intent=read_json(Path(previous['request_path']).parents[2]/'case_config.json')['intent']
    harness=ctl.new(Path(selected['input_path']),intent,{**config,'max_generations':3,'experiment_arm':'Harness_T1_T2_T3'})
    direct=ctl.new(Path(selected['input_path']),intent,{**config,'max_generations':1,'experiment_arm':'Direct_fixed_text_no_tools'})
    if harness.input_sha256!=selected['canonical_sha256'] or direct.input_sha256!=harness.input_sha256:
        raise ValueError('Fresh cases differ from frozen source; never reuse evidence')
    value=dict(created_at=now(),image_id='spaq_00002',original_sha256=selected['original_sha256'],canonical_sha256=harness.input_sha256,
        condition='no_T4',formal_eligible=False,harness_case_id=harness.case_id,direct_case_id=direct.case_id,
        original_diagnosis_response= str(Path(previous['request_path']).with_name('response.json')),
        desktop_executor='ChatGPT desktop original+instruction only',verifier='independent fresh session',
        first_round_vs_final='record separately',generations_actual=0,restoration_success=None)
    STUDY.mkdir(parents=True,exist_ok=True);write_json(STUDY/'study.json',value)
    write_json(STUDY/'condition.json',config)
    atomic_write(STUDY/'direct_instruction.txt',DIRECT_INSTRUCTION.encode('utf-8'))
    return value


def diagnose(payload_file,model):
    study=prepare();payload=read_json(payload_file);ctl=Controller(ROOT)
    for arm in ('harness','direct'):
        case_id=study[arm+'_case_id'];req=ctl.current_task(case_id)
        if req is None or req.role!='diagnose':continue
        provenance=ctl.provenance(model,'file','local_work','01a1307e-d7af-7ec1-948d-239bfd73fa89')
        result=ctl.import_json(case_id,req.task_id,json.dumps(payload,ensure_ascii=False),model,provenance)
        if not result.accepted:raise ValueError(result.message)
        planned=[r['tool'] for r in payload['tool_plan']]
        for tool in planned:
            if arm=='direct' or tool=='T4_SEGMENTATION':
                ctl.operate(case_id,'skip_tool',tool+(':Fixed Direct baseline excludes all auxiliary evidence' if arm=='direct' else ':User requested no semantic segmentation evidence for this flow test'))
    return study


def evidence():
    study=prepare();ctl=Controller(ROOT);case=ctl.case(study['harness_case_id']);state=ctl.inspect(case.case_id)
    if state.workflow_status!='WAIT_EVIDENCE':return state.model_dump()
    config=read_json(case.path('case_config.json'));meta=read_json(case.path('input/metadata.json'))
    profile=EvidenceProfile.model_validate(config['evidence_profile']);cache=EvidenceCache(ROOT/'Data/annotations/cache')
    for tool in list(state.required_tools):
        if tool=='T4_SEGMENTATION':raise ValueError('T4 must be explicitly excluded before cache intake')
        contract=make_contract(state.input_sha256,tool,profile,config['tool_registry']['tools'][tool],canonicalizer_version=canonicalizer_version_from_metadata(meta))
        path=cache.lookup(contract)
        if path is None:raise ValueError('No exact validated real cache for '+tool+'; do not simulate')
        state=ctl.accept_local_evidence(case.case_id,path,'cache_import',{'cache_hit':True,'runtime_elapsed_ms':0.0,'not_new_inference':True,'cost_source':'prior strictly validated real GPU pilot; retained original logs'})
    return state.model_dump()


def direct():
    study=prepare();ctl=Controller(ROOT);req=ctl.current_task(study['direct_case_id'])
    if req.role!='compose':return req.model_dump()
    payload=dict(task_type='conservative_restoration',treat=['visible degradations conservatively'],preserve=['scene, framing, identities, text, texture, lighting'],region_notes=[],evidence_used=[],instruction=DIRECT_INSTRUCTION)
    result=ctl.import_json(req.case_id,req.task_id,json.dumps(payload), 'Fixed Direct preset (not model inference)',
                           ctl.provenance('Fixed Direct preset (not model inference)','clipboard_import','manual_import'))
    if not result.accepted:raise ValueError(result.message)
    return ctl.current_task(req.case_id).model_dump()


def compose(payload_file, model):
    study=prepare();ctl=Controller(ROOT);req=ctl.current_task(study['harness_case_id'])
    if req.role!='compose':return req.model_dump()
    payload=read_json(payload_file)
    result=ctl.import_json(req.case_id,req.task_id,json.dumps(payload,ensure_ascii=False),model,
                          ctl.provenance(model,'file','local_work','01a1307e-d7af-7ec1-948d-239bfd73fa89'))
    if not result.accepted:raise ValueError(result.message)
    return ctl.current_task(req.case_id).model_dump()


def import_edit(arm, image_file, model, session=None, extras=None):
    study=prepare();ctl=Controller(ROOT);case_id=study[arm+'_case_id'];req=ctl.current_task(case_id)
    if req is None or req.role!='execute':raise ValueError('This arm is not waiting for an editor output')
    from hir_manual.transport import image_observations
    canonical=ctl.case(case_id).path('input/canonical.png')
    config=read_json(ctl.case(case_id).path('case_config.json'))
    observed=image_observations(Path(image_file),canonical,config)
    original=image_observations(canonical,canonical,config)
    if observed['pixel_sha256']==original['pixel_sha256']:
        raise ValueError('An unchanged source copy is not an actual generated editor result')
    files=[Path(p) for p in (extras or [])]
    result=ctl.import_image(case_id,req.task_id,Path(image_file),model,
        ctl.provenance(model,'file','manual_import',session),extras=files,actual_generations=1+len(files))
    if not result.accepted:raise ValueError(result.message)
    return handoff()


def import_verification(arm, payload_file, model, session=None):
    study=prepare();ctl=Controller(ROOT);case_id=study[arm+'_case_id'];req=ctl.current_task(case_id)
    if req is None or req.role!='verify':raise ValueError('This arm is not waiting for independent verification')
    result=ctl.import_json(case_id,req.task_id,json.dumps(read_json(payload_file),ensure_ascii=False),model,
        ctl.provenance(model,'file','manual_import',session))
    if not result.accepted:raise ValueError(result.message)
    return handoff()


def handoff():
    study=prepare();ctl=Controller(ROOT);value={}
    for arm in ('direct','harness'):
        case_id=study[arm+'_case_id'];req=ctl.current_task(case_id);state=ctl.inspect(case_id)
        value[arm]=dict(case_id=case_id,state=state.model_dump(),role=req.role if req else None,task_id=req.task_id if req else None)
        if req:
            case=ctl.case(case_id);directory=STUDY/'handoff'/arm;directory.mkdir(parents=True,exist_ok=True)
            atomic_write(directory/'prompt.txt',case.path(req.prompt_file).read_bytes())
            write_json(directory/'request.json',req)
            write_json(directory/'attachments.json',{'assets':[{**a.model_dump(),'absolute_path':str(case.path(a.path))} for a in req.allowed_assets]})
            if req.role=='execute':
                config=read_json(case.path('case_config.json'))
                expected=read_json(case.path('input/metadata.json'))['original_path'] if config.get('desktop_original_rgb_equivalent_upload') else 'input/canonical.png'
                if len(req.allowed_assets)!=1 or req.allowed_assets[0].path!=expected:raise ValueError('Executor must receive only verified original')
                command=(f'& engine/.venv/Scripts/python.exe engine/scripts/no_t4_flow.py import-edit --arm {arm} '
                         "--file 'C:\\path\\generated.png' --model 'ACTUAL_DESKTOP_MODEL_NAME'\n")
                atomic_write(directory/'import_generated_image.ps1.txt',command.encode('utf-8'))
            if req.role=='verify':
                assert 'instruction' not in req.context
    closed=all(v['state']['workflow_completed'] and v['state']['budget']['consumed']>0 for v in value.values())
    value.update(recorded_at=now(),desktop_actual_generations=sum(v['state']['budget']['consumed'] for v in value.values()),
                 full_real_flow_passed=closed,formal_eligible=False,
                 blocker=None if closed else 'Desktop capture/input unavailable; manual editor output and independent verification pending')
    value['first_round_and_final']={}
    for arm in ('direct','harness'):
        state=value[arm]['state'];rounds=history(ctl.case(state['case_id']))['rounds']
        value['first_round_and_final'][arm]={'first_round':next((r for r in rounds if r['round']==1 and r.get('output_asset')),None),
            'final_round':next((r for r in rounds if r['round']==state.get('selected_round') and r.get('output_asset')),None),
            'restoration_success':state['restoration_success']}
    write_json(STUDY/'current_status.json',value)
    return value


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['prepare','diagnose','evidence','direct','compose','handoff','import-edit','import-verification']);p.add_argument('--file',type=Path);p.add_argument('--model');p.add_argument('--arm',choices=['direct','harness']);p.add_argument('--session');p.add_argument('--extra',type=Path,action='append',default=[]);a=p.parse_args()
    if a.action in ('diagnose','compose'):value=globals()[a.action](a.file,a.model)
    elif a.action=='import-edit':value=import_edit(a.arm,a.file,a.model,a.session,a.extra)
    elif a.action=='import-verification':value=import_verification(a.arm,a.file,a.model,a.session)
    else:value=globals()[a.action]()
    print(json.dumps(value,ensure_ascii=False,indent=2))
