"""Resumable all-input RealZoom trial. Never reads GT or fabricates outputs."""
import argparse
import base64
import csv
import html
import io
import json
from pathlib import Path
import sys
from PIL import Image

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'engine/src'))
from hir_manual.service import Controller,history
from hir_manual.storage import read_json,write_json,sha256_file,now,atomic_write
from hir_manual.cache import EvidenceCache,make_cache_key
from hir_manual.tool_registry import make_contract,canonicalizer_version_from_metadata
from hir_manual.tool_models import EvidenceProfile
from no_t4_flow import DIRECT_INSTRUCTION

SOURCE=ROOT/'Data/HardCases/Telephoto/RealZoom'
BATCH=ROOT/'runtime/realzoom/no_t4_20261014'
INTENT='保守恢复长焦照片中的实际可见缺陷。保持文字原笔画与排版、建筑窗格和直线、视角、构图、光线与景深；不猜测模糊文字，不重建缺失纹理，不改变场景。'

def prepare():
    BATCH.mkdir(parents=True,exist_ok=True)
    ctl=Controller(ROOT)
    manifest=read_json(BATCH/'manifest.json') if (BATCH/'manifest.json').exists() else dict(created_at=now(),source=str(SOURCE),condition='no_T4',references_read=False,formal_eligible=False,images=[])
    indexed={r['sample_id']:r for r in manifest['images']}
    sources=sorted(SOURCE.rglob('input.jpg'))
    if not sources:raise ValueError('No original input.jpg files')
    for source in sources:
        sid=source.parent.name
        if sid in indexed:
            if sha256_file(source)!=indexed[sid]['original_sha256']:raise ValueError('Original changed: '+sid)
            continue
        config=dict(auto_local_tools=False,evidence_profile_id='gpu_full_v1',branch_type='manual_variant',experiment_condition='RealZoom_no_T4',sample_id=sid,realzoom_batch=BATCH.name,formal_experiment_eligible=False)
        cases={}
        # Recover cases committed before a crash at the manifest write.
        for arm,budget in [('harness',3),('direct',1)]:
            matches=[]
            for path in (ROOT/'cases').glob('*/case_config.json'):
                c=read_json(path)
                if c.get('realzoom_batch')==BATCH.name and c.get('sample_id')==sid and c.get('experiment_arm')==arm:matches.append(path.parent.name)
            if len(matches)>1:raise ValueError('Duplicate committed cases: '+sid)
            cases[arm]=matches[0] if matches else ctl.new(source,INTENT,{**config,'experiment_arm':arm,'max_generations':budget}).case_id
        case=ctl.case(cases['harness']);meta=read_json(case.path('input/metadata.json'))
        row=dict(sample_id=sid,input_path=str(source),original_sha256=meta['original_sha256'],canonical_sha256=meta['canonical_sha256'],width=meta['width'],height=meta['height'],cases=cases)
        manifest['images'].append(row);write_json(BATCH/'manifest.json',manifest)
        print(sid+' prepared',flush=True)
    if set(indexed)-{p.parent.name for p in sources}:raise ValueError('Source set changed')
    return manifest

def diagnose(sid,file):
    manifest=prepare();row=next(r for r in manifest['images'] if r['sample_id']==sid)
    payload=read_json(file);ctl=Controller(ROOT);model='GPT-6.1 Sol 轻度（当前本地 Work 实际看图）'
    for arm,cid in row['cases'].items():
        req=ctl.current_task(cid)
        if req.role!='diagnose':continue
        result=ctl.import_json(cid,req.task_id,json.dumps(payload,ensure_ascii=False),model,ctl.provenance(model,'file','local_work','01a1307e-d7af-7ec1-948d-239bfd73fa89'))
        if not result.accepted:raise ValueError(result.message)
        for item in payload['tool_plan']:
            if item['tool']=='T4_SEGMENTATION' or arm=='direct':
                ctl.operate(cid,'skip_tool',item['tool']+(':Explicit user exclusion of semantic evidence' if arm=='harness' else ':Fixed Direct baseline excludes auxiliary evidence'))
    # Direct advances with the same fixed baseline for every image.
    cid=row['cases']['direct'];req=ctl.current_task(cid)
    if req.role=='compose':
        payload=dict(task_type='conservative_restoration',treat=['visible degradations only'],preserve=['letter strokes, geometry, scene, framing, lighting'],region_notes=[],evidence_used=[],instruction=DIRECT_INSTRUCTION)
        result=ctl.import_json(cid,req.task_id,json.dumps(payload),'Fixed Direct preset (not model inference)',ctl.provenance('Fixed Direct preset (not model inference)','clipboard_import','manual_import'))
        if not result.accepted:raise ValueError(result.message)
    return row

def scan():
    manifest=prepare();ctl=Controller(ROOT);cache=EvidenceCache(ROOT/'Data/annotations/cache');missing=[];records=[]
    for row in manifest['images']:
        cid=row['cases']['harness'];case=ctl.case(cid);state=ctl.inspect(cid);config=read_json(case.path('case_config.json'));meta=read_json(case.path('input/metadata.json'));profile=EvidenceProfile.model_validate(config['evidence_profile'])
        evidence=[]
        for tool in state.required_tools:
            contract=make_contract(state.input_sha256,tool,profile,config['tool_registry']['tools'][tool],canonicalizer_version=canonicalizer_version_from_metadata(meta))
            hit=cache.lookup(contract)
            evidence.append(dict(tool_id=tool,status='valid_cache' if hit else 'missing',cache_key=make_cache_key(contract)))
            if hit and tool not in state.received_tools and state.workflow_status=='WAIT_EVIDENCE':
                state=ctl.accept_local_evidence(cid,hit,'cache_import',{'cache_hit':True,'runtime_elapsed_ms':0.0})
            if not hit:missing.append(dict(sample_id=row['sample_id'],case_id=cid,tool_id=tool,cache_contract=contract,input_path=str(case.path('input/canonical.png'))))
        arms={}
        for arm,armcid in row['cases'].items():
            st=ctl.inspect(armcid);req=ctl.current_task(armcid);acase=ctl.case(armcid);out=BATCH/'handoff'/row['sample_id']/arm;out.mkdir(parents=True,exist_ok=True)
            if req:
                write_json(out/'request.json',req);atomic_write(out/'prompt.txt',acase.path(req.prompt_file).read_bytes())
                write_json(out/'attachments.json',{'assets':[{**a.model_dump(),'absolute_path':str(acase.path(a.path))} for a in req.allowed_assets]})
            rounds=history(acase)['rounds']
            arms[arm]=dict(case_id=armcid,state=st.workflow_status,operation_status=st.operation_status,current_role=req.role if req else None,actual_generations=st.budget.consumed,workflow_completed=st.workflow_completed,restoration_success=st.restoration_success,first_round=next((x for x in rounds if x['round']==1 and x.get('output_asset')),None),final_round=next((x for x in rounds if x['round']==st.selected_round and x.get('output_asset')),None))
        records.append(dict(sample_id=row['sample_id'],evidence=evidence,arms=arms))
    value=dict(recorded_at=now(),input_count=len(records),diagnosed=sum(r['arms']['harness']['current_role']!='diagnose' for r in records),actual_generations=sum(a['actual_generations'] for r in records for a in r['arms'].values()),real_full_cycle_passed=sum(all(a['workflow_completed'] and a['actual_generations']>0 for a in r['arms'].values()) for r in records),records=records,T4='excluded_by_user',references_read=False)
    write_json(BATCH/'status.json',value);write_json(BATCH/'missing_evidence.json',{'jobs':missing,'inference_completed':False,'scope':'Exact-contract missing evidence; not inferred outputs'})
    with (BATCH/'status.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=['sample_id','arm','state','actual_generations','workflow_completed','restoration_success']);w.writeheader()
        for r in records:
            for arm,a in r['arms'].items():w.writerow(dict(sample_id=r['sample_id'],arm=arm,**{k:a[k] for k in w.fieldnames if k not in ('sample_id','arm')}))
    page="<!doctype html><meta charset='utf-8'><title>RealZoom 无T4逐图实测</title><style>body{max-width:1100px;margin:30px auto;font:16px/1.7 system-ui;background:#f5f4ee}section{padding:20px;margin:20px;background:white}img{max-width:100%}pre{white-space:pre-wrap}textarea{width:100%;height:200px}</style><h1>RealZoom 全部15张输入 · 无T4</h1>"
    page+=f"<p>诊断已校验 {value['diagnosed']} / {value['input_count']}；真实编辑输出 {value['actual_generations']}；完整闭环通过 {value['real_full_cycle_passed']}。没有读取GT。缺失证据不算空检测；未生成的结果不显示原图替代。</p>"
    for row,r in zip(manifest['images'],records):
        c=ctl.case(row['cases']['harness'])
        with Image.open(c.path('input/canonical.png')) as im:
            im.thumbnail((1000,800));b=io.BytesIO();im.convert('RGB').save(b,'JPEG',quality=92)
        src='data:image/jpeg;base64,'+base64.b64encode(b.getvalue()).decode()
        payload=BATCH/'diagnoses'/f"{row['sample_id']}.json"
        diagnosis=read_json(payload) if payload.exists() else None
        prompt=BATCH/'handoff'/row['sample_id']/'direct/prompt.txt'
        harness_prompt=BATCH/'handoff'/row['sample_id']/'harness/prompt.txt'
        harness_text=harness_prompt.read_text(encoding='utf-8') if harness_prompt.exists() and r['arms']['harness']['current_role']=='execute' else '等待真实工具证据；尚未形成编辑文字'
        page+=f"<section><h2>{row['sample_id']} · {row['width']}×{row['height']}</h2><img src='{src}'><pre>{html.escape(json.dumps(diagnosis,ensure_ascii=False,indent=2))}</pre><pre>{html.escape(json.dumps(r,ensure_ascii=False,indent=2))}</pre><h3>Direct编辑文字（另开图像编辑会话）</h3><textarea readonly>{html.escape(prompt.read_text(encoding='utf-8') if prompt.exists() and r['arms']['direct']['current_role']=='execute' else '尚未进入编辑')}</textarea><h3>Harness编辑文字</h3><textarea readonly>{html.escape(harness_text)}</textarea><p>真实编辑/独立Verifier结果：待完成。Harness证据不足时保持WAIT_EVIDENCE，不伪造提示词变化或恢复结果。</p></section>"
    atomic_write(BATCH/'report.html',page.encode('utf-8'));return value

def import_result(sid,arm,file,model,session,verification=False,extras=None):
    if not model:raise ValueError('Actual displayed model is required')
    row=next(r for r in prepare()['images'] if r['sample_id']==sid)
    ctl=Controller(ROOT);cid=row['cases'][arm];req=ctl.current_task(cid)
    if not req or req.role!=('verify' if verification else 'execute'):raise ValueError('Arm is not waiting for this role')
    provenance=ctl.provenance(model,'file','manual_import',session)
    if verification:
        if 'instruction' in req.context:raise ValueError('Independent Verifier must not receive Composer instruction')
        result=ctl.import_json(cid,req.task_id,json.dumps(read_json(file),ensure_ascii=False),model,provenance)
    else:
        from hir_manual.transport import image_observations
        case=ctl.case(cid);config=read_json(case.path('case_config.json'));source=case.path('input/canonical.png')
        if image_observations(file,source,config)['pixel_sha256']==image_observations(source,source,config)['pixel_sha256']:raise ValueError('Unchanged source copy is not an actual editor output')
        result=ctl.import_image(cid,req.task_id,file,model,provenance,extras=extras or [],actual_generations=1+len(extras or []))
    if not result.accepted:raise ValueError(result.message)
    return scan()

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['prepare','diagnose','scan','import-edit','import-verification']);p.add_argument('--sample');p.add_argument('--file',type=Path);p.add_argument('--arm',choices=['direct','harness']);p.add_argument('--model');p.add_argument('--session');p.add_argument('--extra',type=Path,action='append',default=[]);a=p.parse_args()
    if a.action.startswith('import-'):v=import_result(a.sample,a.arm,a.file,a.model,a.session,a.action=='import-verification',a.extra)
    else:v=diagnose(a.sample,a.file) if a.action=='diagnose' else globals()[a.action]()
    print(json.dumps(v,ensure_ascii=False,indent=2))
