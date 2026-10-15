"""Sequential, resumable five-photo real Gemini Harness pilot; no simulated output."""
import argparse, csv, html, json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'engine/src'))
from hir_manual.storage import read_json, write_json, atomic_write, now, sha256_file
from hir_manual.service import Controller, history
from hir_manual.gemini_api import configuration, run_task, BRIDGE_VERSION
from hir_manual.tool_registry import load_profile, load_registry, make_contract, TOOL_IDS
from hir_manual.cache import EvidenceCache, make_cache_key
from hir_manual.tool_service import ToolService
from render_gemini_study import render, image_tag
DIRECTORY = ROOT / 'runtime/gemini_api/five_complete_20261015'
IDS = ('lolv2_00690', 'HC_RAIM_Phase1_011', 'HC_ReWiTe_260_tele', 'commons_002', 'spaq_00002')
INTENT = 'Restore this original low-quality photo conservatively. Reduce noise and recover clarity only where supported; preserve identity, geometry, readable text, natural texture, depth of field and original lighting. Do not invent details or beautify faces.'

def preflight():
    manifest = read_json(ROOT / 'runtime/quality20/pilot20_20261013_stable_v2/manifest.json')
    selected = {r['sample_id']:r for r in manifest['images']}
    profile = load_profile('gpu_sam31_v5', ROOT); registry = load_registry(ROOT, 'gpu_sam31_v5')
    cache = EvidenceCache(ROOT / 'Data/annotations/cache'); records=[]
    for image_id in IDS:
        row=selected[image_id]; source=Path(row['canonical_path'])
        if sha256_file(source) != row['canonical_sha256'] or sha256_file(Path(row['input_path'])) != row['original_sha256']:
            raise ValueError('Original/canonical source changed: '+image_id)
        tools=[]
        for tool in TOOL_IDS:
            print('PREFLIGHT '+image_id+' '+tool,flush=True); started=time.perf_counter()
            contract=make_contract(row['canonical_sha256'], tool, profile, registry.tools[tool], canonicalizer_version=row['canonicalizer_version'])
            directory=cache.lookup(contract)
            if directory is None: raise ValueError('Strict exact-contract cache unavailable: '+image_id+' '+tool)
            evidence=read_json(directory/'evidence.json')
            assets=[dict(path=str(directory/a['path']), kind=a['kind'], bytes=(directory/a['path']).stat().st_size) for a in evidence['assets'] if a['kind'] != 'raw_data']
            tools.append(dict(tool_id=tool, cache_key=make_cache_key(contract), directory=str(directory), model=evidence.get('model_name'), assets=assets))
            print('PREFLIGHT_OK '+image_id+' '+tool+' '+str(round(time.perf_counter()-started,2))+'s',flush=True)
        records.append(dict(image_id=image_id, source=row, canonical_bytes=source.stat().st_size, all_visual_asset_bytes=sum(a['bytes'] for t in tools for a in t['assets']), tools=tools))
        write_json(DIRECTORY/'preflight_partial.json',dict(recorded_at=now(),records=records))
    result=dict(recorded_at=now(), records=records, strict_caches=20, formal_eligible=False)
    write_json(DIRECTORY/'preflight.json',result); return result

def report(study):
    ctl=Controller(ROOT); cards=[]; rows=[]; summaries=[]
    for item in study['records']:
        image_id=item['image_id']; cid=item.get('case_id')
        if not cid: continue
        case=ctl.case(cid); state=ctl.inspect(cid); hist=history(case)
        single=DIRECTORY/image_id; write_json(single/'study.json',dict(harness_case_id=cid,image_id=image_id,formal_eligible=False))
        render(single)
        body='<h2>'+html.escape(image_id)+' · '+state.workflow_status+'</h2><p>'+html.escape(item.get('blocked_reason',''))+'</p>'
        body+='<h3>原始输入</h3>'+image_tag(case.path('input/canonical.png'))
        body+='<h3>全部四工具可用证据（实际Composer使用依诊断计划）</h3>'
        for tool in item['tools']:
            body+='<h4>'+tool['tool_id']+' · '+html.escape(str(tool['model']))+'</h4>'
            for asset in tool['assets']:
                if asset['kind'] in ('overlay','map','crop'):
                    body+=image_tag(Path(asset['path']))
        body+='<h3>诊断与实际工具计划</h3><pre>'+html.escape(json.dumps(hist['diagnosis'],ensure_ascii=False,indent=2))+'</pre>'
        for r in hist['rounds']:
            body+='<h3>Round '+str(r['round'])+'</h3><pre>'+html.escape(json.dumps(r.get('composition'),ensure_ascii=False,indent=2))+'</pre>'
            if r.get('output_asset'): body+=image_tag(case.path(r['output_asset']['path']))
            body+='<pre>'+html.escape(json.dumps(r.get('verification'),ensure_ascii=False,indent=2))+'</pre>'
            rows.append(dict(image_id=image_id,case_id=cid,round=r['round'],state=state.workflow_status,selected=r['round']==state.selected_round,output=r.get('output_asset',{}).get('path'),verification=json.dumps(r.get('verification'),ensure_ascii=False)))
        cards.append('<article>'+body+'</article>')
        receipts=[read_json(p) for p in case.path('tasks').glob('*/api/receipt.json')]
        body_audit=json.dumps(receipts,ensure_ascii=False,indent=2)
        cards[-1]=cards[-1].replace('</article>','<h3>真实 API 调用、版本、耗时</h3><pre>'+html.escape(body_audit)+'</pre></article>')
        summaries.append(dict(image_id=image_id,case_id=cid,state=state.model_dump(),blocked_reason=item.get('blocked_reason'),history=hist,receipts=receipts))
    write_json(DIRECTORY/'results.json',dict(recorded_at=now(),formal_eligible=False,records=summaries))
    import io
    stream=io.StringIO(); writer=csv.DictWriter(stream,fieldnames=['image_id','case_id','round','state','selected','output','verification']);writer.writeheader();writer.writerows(rows)
    atomic_write(DIRECTORY/'results.csv',stream.getvalue().encode('utf-8-sig'))
    audit=DIRECTORY/'root_audit/quality_audit.json'
    if audit.exists(): cards.append('<article><h2>单独视觉审计（未进入任何角色输入）</h2><pre>'+html.escape(json.dumps(read_json(audit),ensure_ascii=False,indent=2))+'</pre></article>')
    document='<!doctype html><meta charset="utf-8"><title>Five real HarnessIR Gemini pipelines</title><style>body{font:16px system-ui;background:#edf0f4;padding:24px}article{background:white;padding:20px;margin:20px 0}img{max-width:45%;height:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><h1>5张真实 HarnessIR · Gemini API + SAM3.1 替代通路</h1><p>原图保留；证据按需提供给Composer；Executor只有原图与文字；Verifier独立请求；最多3次且重试从原图。模型判定不是GT证明，未完成和失败明确显示。</p>'+''.join(cards)
    atomic_write(DIRECTORY/'report.html',document.encode('utf-8'))

def main():
    p=argparse.ArgumentParser();p.add_argument('--preflight-only',action='store_true');p.add_argument('--use-validated-preflight',action='store_true');p.add_argument('--key-file',type=Path,default=Path('C:/Users/Lenovo/Desktop/key.txt'));a=p.parse_args()
    if a.use_validated_preflight:
        frozen=read_json(DIRECTORY/'preflight.json')
        profile=load_profile('gpu_sam31_v5',ROOT); registry=load_registry(ROOT,'gpu_sam31_v5')
        if frozen.get('strict_caches')!=20 or [r['image_id'] for r in frozen['records']]!=list(IDS):raise ValueError('Incomplete prior preflight')
        for record in frozen['records']:
            source=record['source']
            if sha256_file(Path(source['canonical_path']))!=source['canonical_sha256']:raise ValueError('Source changed after preflight')
            for tool in record['tools']:
                directory=Path(tool['directory']); ready=read_json(directory/'ready.json')
                expected=make_contract(source['canonical_sha256'],tool['tool_id'],profile,registry.tools[tool['tool_id']],canonicalizer_version=source['canonicalizer_version'])
                if read_json(directory/'contract.json')!=expected:raise ValueError('Frozen contract changed')
                if sha256_file(directory/'contract.json')!=ready['contract_sha256'] or sha256_file(directory/'evidence.json')!=ready['evidence_sha256']:raise ValueError('Evidence changed after semantic preflight')
                for asset in ready['artifact_hashes']:
                    if sha256_file(directory/asset['path'])!=asset['sha256']:raise ValueError('Asset changed after semantic preflight')
    else:frozen=preflight()
    print(json.dumps([{k:r[k] for k in ('image_id','canonical_bytes','all_visual_asset_bytes')} for r in frozen['records']]),flush=True)
    if a.preflight_only:return
    study_path=DIRECTORY/'study.json';ctl=Controller(ROOT)
    if study_path.exists(): study=read_json(study_path)
    else:
        cfg=configuration('gemini-3-pro-image','gemini-3.1-pro-preview',600,media_transport='files_api_v1')
        cfg.update(evidence_profile_id='gpu_sam31_v5',auto_local_tools=False,max_generations=3)
        study=dict(created_at=now(),formal_eligible=False,configuration=cfg,bridge_version=BRIDGE_VERSION,records=frozen['records'])
        write_json(study_path,study)
    for item in study['records']:
        if not item.get('case_id'):
            state=ctl.new(Path(item['source']['input_path']),INTENT,study['configuration'])
            if state.input_sha256 != item['source']['canonical_sha256']:raise ValueError('New case canonical hash differs')
            item['case_id']=state.case_id
            write_json(study_path,study)
    print('CASES '+json.dumps({r['image_id']:r['case_id'] for r in study['records']}),flush=True)
    for item in study['records']:
        cid=item['case_id'];image_id=item['image_id']
        if item.get('blocked_reason'):continue
        previous_block=DIRECTORY/image_id/'blocked.json'
        if previous_block.exists():
            item['blocked_reason']=read_json(previous_block)['reason'];write_json(study_path,study);continue
        for step in range(20):
            state=ctl.inspect(cid)
            if state.workflow_status=='FINISHED' or state.operation_status!='active':break
            print(now()+' '+image_id+' '+state.workflow_status,flush=True)
            started=time.perf_counter()
            try:
                if state.workflow_status=='WAIT_EVIDENCE':
                    result=ToolService(ROOT).run_case(cid).model_dump()
                    if result['workflow_status']=='WAIT_EVIDENCE':raise ValueError('Required evidence unresolved despite preflight')
                else:result=run_task(ROOT,cid,a.key_file)
                write_json(DIRECTORY/image_id/'steps'/f'{state.revision}_{state.workflow_status}_{state.pending_task_id or "evidence"}.json',dict(at=now(),elapsed_seconds=time.perf_counter()-started,result=result))
            except Exception as error:
                item['blocked_reason']=str(error) if isinstance(error,(ValueError,RuntimeError)) else type(error).__name__
                write_json(DIRECTORY/image_id/'blocked.json',dict(at=now(),state=state.model_dump(),reason=item['blocked_reason']))
                print(image_id+' BLOCKED '+item['blocked_reason'],flush=True);break
            write_json(study_path,study)
        write_json(study_path,study); report(study)
        final=ctl.inspect(cid);print(image_id+' RESULT '+final.workflow_status+' restoration_success='+str(final.restoration_success),flush=True)
    report(study)
if __name__=='__main__': main()
