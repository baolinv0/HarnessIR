"""Create a readable manual handoff, copying only current issued editor inputs."""
import base64
import html
import io
import shutil
from pathlib import Path

from PIL import Image
from realzoom_flow import ROOT,BATCH
from hir_manual.service import Controller
from hir_manual.storage import read_json,write_json,sha256_file,atomic_write,now


def main():
    ctl=Controller(ROOT);manifest=read_json(BATCH/'manifest.json');status=read_json(BATCH/'status.json')
    states={r['sample_id']:r for r in status['records']};out=BATCH/'manual_upload';out.mkdir(exist_ok=True)
    page="<!doctype html><html lang='zh'><meta charset='utf-8'><title>RealZoom 手动上传清单</title><style>body{max-width:1100px;margin:25px auto;padding:15px;background:#f5f3ec;font:16px/1.7 system-ui}section{background:white;margin:22px 0;padding:22px;border-radius:10px}img{max-width:100%;max-height:380px}textarea{width:100%;height:230px;box-sizing:border-box;font:15px/1.6 system-ui}button{padding:10px 18px;margin:8px 0;background:#23564c;color:white;border:0;border-radius:5px}pre{white-space:pre-wrap;word-break:break-all}.pending{background:#fff1ca;padding:12px}a{color:#23564c}</style><h1>RealZoom：逐图原图与完整编辑文字</h1><p>每次只上传本节 input.png，并粘贴所选组的完整编辑文字。Direct/Harness分别新建会话。GT、诊断JSON及工具证据不上传给图像编辑器；证据供Composer查看。保存第一张完整生成图，勿截图，勿按美观挑选。</p><p>本批目前没有已接受的T1–T4工具证据。7张缺8条所需证据，其余8张诊断未要求工具；诊断不算工具证据。T4按用户要求排除。</p>"
    ledger=[];markdown=['# RealZoom手动上传清单','', '每张上传 input.png（当前编辑任务声明的canonical原图副本，无缩放重编码），并粘贴相应完整.txt文字。没有GT文件。诊断只供查阅，不能代替工具证据。','']
    for row in manifest['images']:
        sid=row['sample_id'];target=out/sid;target.mkdir(exist_ok=True)
        direct_case=ctl.case(row['cases']['direct']);direct_req=ctl.current_task(direct_case.case_id)
        if not direct_req or direct_req.role!='execute':raise ValueError('Refresh handoff for changed Direct stage: '+sid)
        assert len(direct_req.allowed_assets)==1
        a=direct_req.allowed_assets[0];assert a.path=='input/canonical.png'
        raw=direct_case.path(a.path);assert sha256_file(raw)==a.sha256==row['canonical_sha256']
        shutil.copyfile(raw,target/'input.png');assert sha256_file(target/'input.png')==a.sha256
        direct=direct_case.path(direct_req.prompt_file).read_text(encoding='utf-8')
        atomic_write(target/'Direct.txt',direct.encode('utf-8'))
        shutil.copyfile(BATCH/'diagnoses'/f'{sid}.json',target/'Diagnosis.json')
        hc=ctl.case(row['cases']['harness']);hr=ctl.current_task(hc.case_id)
        harness=None
        if hr and hr.role=='execute':
            assert len(hr.allowed_assets)==1 and hr.allowed_assets[0].sha256==a.sha256
            harness=hc.path(hr.prompt_file).read_text(encoding='utf-8');atomic_write(target/'Harness.txt',harness.encode('utf-8'))
        elif (target/'Harness.txt').exists():raise ValueError('Stale Harness prompt; preserve and review before re-export')
        ev=states[sid]['evidence'];label='；'.join(('OCR' if x['tool_id']=='T1_OCR' else '深度')+'证据缺失' for x in ev) if ev else '诊断未要求工具，无工具证据'
        if any(x['status']!='missing' for x in ev):raise ValueError('New evidence available; rerender review rather than label missing')
        write_json(target/'Evidence_Status.json',{'sample_id':sid,'actual_evidence_files':[],'planned_tools':ev,'T2':'not_requested','T4':'excluded_by_user','explanation':label,'diagnosis_is_not_tool_evidence':True})
        note=f'{sid}\n上传：{target / "input.png"}\nDirect完整文字：Direct.txt\nHarness完整文字：'+('Harness.txt' if harness else '尚无，等待真实工具证据；不要把诊断任务prompt当编辑文字')+f'\n证据：{label}，没有可上传的工具输出文件。\n诊断：Diagnosis.json，仅供查阅，不上传给编辑器。\n保存命名：{sid}_Direct_R1.png / {sid}_Harness_R1.png\n'
        atomic_write(target/'说明.txt',note.encode('utf-8'))
        with Image.open(raw) as im:
            im.thumbnail((600,450));b=io.BytesIO();im.convert('RGB').save(b,'JPEG',quality=90)
        preview='data:image/jpeg;base64,'+base64.b64encode(b.getvalue()).decode()
        page+=f"<section id='{sid}'><h2>{sid} · {row['width']}×{row['height']}</h2><img src='{preview}'><p>上传原图：<a href='{sid}/input.png' download>{sid}/input.png</a></p><pre>{html.escape(str(target/'input.png'))}</pre><p class='pending'>证据：{html.escape(label)}；T4不用。<a href='{sid}/Evidence_Status.json'>状态记录</a> · <a href='{sid}/Diagnosis.json'>完整诊断</a></p><h3>Direct：整段复制</h3><textarea id='{sid}_direct' readonly>{html.escape(direct)}</textarea><button onclick=\"copyText('{sid}_direct')\">复制Direct完整文字</button>"
        if harness:page+=f"<h3>Harness：整段复制</h3><textarea id='{sid}_harness' readonly>{html.escape(harness)}</textarea><button onclick=\"copyText('{sid}_harness')\">复制Harness完整文字</button>"
        else:page+="<h3>Harness：等待工具证据，尚无正式编辑文字</h3><p>可以先做Direct；不把Direct结果冒记为Harness结果。</p>"
        page+=f"<p>保存名称：{sid}_Direct_R1.png / {sid}_Harness_R1.png。保留完整下载文件。</p></section>"
        markdown.extend([f'## {sid}', '',f'原图：{target/"input.png"}',f'证据：{label}；T4排除。',f'诊断：{target/"Diagnosis.json"}','','Direct完整编辑文字：','',direct,'','Harness完整编辑文字：','',harness or '尚未形成，等待真实工具证据。',''])
        ledger.append({'sample_id':sid,'input':str(target/'input.png'),'input_sha256':a.sha256,'direct_task_id':direct_req.task_id,'direct_prompt':str(target/'Direct.txt'),'harness_task_id':hr.task_id if harness else None,'harness_prompt':str(target/'Harness.txt') if harness else None,'evidence_status':label,'actual_evidence_files':[]})
    page+="<script>function copyText(id){const x=document.getElementById(id);x.focus();x.select();document.execCommand('copy')}</script></html>"
    atomic_write(out/'index.html',page.encode('utf-8'));atomic_write(out/'全部图像完整内容.md','\n'.join(markdown).encode('utf-8'));write_json(out/'manifest.json',{'exported_at':now(),'images':ledger,'count':len(ledger),'evidence_files_exported':0,'references_included':False})
    print({'manual_handoff':str(out/'index.html'),'images':len(ledger),'direct_prompts':len(ledger),'harness_prompts':sum(x['harness_prompt'] is not None for x in ledger),'evidence_files':0})

if __name__=='__main__':main()
