"""Portable, self-contained comparisons of stage-lab artifacts."""
from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path

from PIL import Image


def _image(root: Path, value: str, label: str) -> dict:
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    try:
        with Image.open(path) as image:
            width, height = image.size
            mime = Image.MIME.get(image.format) or mimetypes.guess_type(path.name)[0] or "image/png"
        return {"label": label, "path": value, "width": width, "height": height,
                "src": f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"}
    except (OSError, ValueError):
        return {"label": label, "path": value, "error": "图像文件不可用"}


def render_report(cases: list[dict], runs: list[dict], root: Path) -> str:
    """Render output without network dependencies; keep original run records downloadable."""
    root = Path(root)
    case_views = []
    for case in cases:
        case_views.append({"record": case, "images": [
            _image(root, value, role) for role, value in case.get("images", {}).items()
            if isinstance(value, str)
        ]})
    run_views = []
    for run in runs:
        output = run.get("output") or {}
        images = [
            _image(root, value, f"输出 {index + 1}")
            for index, value in enumerate(output.get("images") or []) if isinstance(value, str)
        ]
        if run.get("stage") == "judge":
            for item in (run.get("request") or {}).get("images") or []:
                role = str(item.get("role", ""))
                if role == "C" or (role.startswith("C") and role[1:].isdigit()):
                    images.append({**_image(root, item["path"], f"{role} · 判别输入候选"),
                                   "kind": "input_candidate", "role": role})
        run_views.append({"record": run, "images": images})
    payload = json.dumps({"cases": case_views, "runs": run_views}, ensure_ascii=False, default=str)
    # HTML raw-text elements still recognize </script> inside JSON strings.
    payload = payload.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    return _HTML.replace("__REPORT_DATA__", payload)


def export_report(root: Path, output: Path | None = None, case_id: str | None = None,
                  stage: str | None = None) -> Path:
    """Export all or a filtered stage view as a single HTML file."""
    from .core import list_cases, list_runs

    root = Path(root).resolve()
    cases = list_cases(root)
    if case_id:
        cases = [case for case in cases if case.get("id") == case_id]
    runs = list_runs(root, case_id=case_id, stage=stage)
    destination = Path(output) if output is not None else root / "comparison.html"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render_report(cases, runs, root), encoding="utf-8")
    return destination.resolve()


_HTML = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>HarnessIR · 分阶段模型对比</title>
<style>
:root{--ink:#17263b;--muted:#64748b;--accent:#2563eb;--line:#dce4ef;--paper:#fff;--bg:#f3f6fa;--good:#147d64;--bad:#bd344b}*{box-sizing:border-box}body{margin:0;color:var(--ink);background:var(--bg);font:14px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}button,select,input{font:inherit}button{cursor:pointer;border:1px solid var(--line);background:white;color:var(--ink);border-radius:8px;padding:7px 13px}button:hover{border-color:var(--accent);color:var(--accent)}header{background:#14233a;color:white;padding:35px max(24px,calc((100vw - 1360px)/2)) 30px}header p{color:#bfcee3;max-width:800px;margin:8px 0 0}h1{font-size:28px;letter-spacing:-.03em;margin:0}h2{font-size:18px;margin:0 0 12px}h3{font-size:16px;margin:0}main{max-width:1408px;margin:auto;padding:22px 24px 50px}.eyebrow{font-size:11px;letter-spacing:.15em;text-transform:uppercase;color:#8eb9ff;margin-bottom:8px}.filters{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end;background:white;padding:16px;border:1px solid var(--line);border-radius:12px;margin-bottom:18px}.filters label,.pickers label{display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--muted)}select{border:1px solid var(--line);background:white;color:var(--ink);border-radius:7px;min-width:150px;max-width:350px;padding:7px}.filters button{margin-left:auto}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:22px}.stat{padding:15px 18px;border:1px solid var(--line);border-radius:10px;background:white}.stat strong{font-size:25px;display:block;line-height:1.2}.stat span{font-size:12px;color:var(--muted)}.panel{background:white;border:1px solid var(--line);border-radius:12px;padding:18px;margin:0 0 22px}.section-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:25px 0 12px}.section-head h2{margin:0}.small{font-size:12px;color:var(--muted)}.sources{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}.source-case{margin-bottom:20px}.source-case:last-child{margin:0}.source-case p{margin:3px 0 12px;color:var(--muted)}figure{margin:0}figure img{display:block;width:100%;height:240px;object-fit:contain;background:#edf1f6;border-radius:7px;cursor:zoom-in}figcaption{font-size:12px;color:var(--muted);padding:6px 0}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,330px),1fr));gap:16px;align-items:start}.card{min-width:0;background:white;border:1px solid var(--line);border-radius:12px;overflow:hidden}.card-head{padding:16px 17px;border-bottom:1px solid var(--line)}.card-head .top{display:flex;justify-content:space-between;align-items:center;gap:8px}.card-body{padding:15px 17px}.tag{display:inline-block;font-size:11px;padding:2px 7px;border-radius:5px;background:#edf3fe;color:#345b9b;margin:3px 4px 0 0}.ok{color:var(--good);background:#e7f5ef}.error{color:var(--bad);background:#fff0f2}.demo{background:#fff5d9;color:#865b08}.card .meta{color:var(--muted);font-size:11px;margin:8px 0 0;overflow-wrap:anywhere}.copy{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px;line-height:1.8;margin:0 0 12px;max-height:460px;overflow:auto}.empty{padding:34px;text-align:center;color:var(--muted);background:white;border:1px dashed var(--line);border-radius:10px}details{margin:10px 0;border-top:1px solid #edf0f5;padding-top:8px}summary{cursor:pointer;color:#405b7e;font-size:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:420px;overflow:auto;font:12px/1.65 ui-monospace,SFMono-Regular,Consolas,monospace;padding:12px;background:#f4f7fb;border-radius:7px;margin:8px 0 0}table{border-collapse:collapse;width:100%;font-size:12px}td,th{text-align:left;padding:8px 10px;border-bottom:1px solid #e7edf4;vertical-align:top}th{color:var(--muted);font-weight:500}.table-wrap{overflow:auto}.pickers{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:12px}.pickers label{flex:1}.pickers select{max-width:none;width:100%}.diff{font:12px/1.65 ui-monospace,SFMono-Regular,Consolas,monospace;max-height:500px;overflow:auto;border:1px solid var(--line);border-radius:8px}.diff-line{white-space:pre-wrap;overflow-wrap:anywhere;padding:2px 10px;min-height:23px}.diff-line.add{background:#e7f6ee;color:#176346}.diff-line.del{background:#fff0f0;color:#992a3b}.diff-line.same{color:#64748b}.compare-frame{position:relative;background:#edf1f6;border-radius:9px;overflow:hidden;max-height:650px;margin:auto}.compare-frame img{display:block;width:100%;height:100%;object-fit:contain;position:absolute;inset:0}.compare-frame .overlay{clip-path:inset(0 50% 0 0)}.compare-frame .divider{position:absolute;top:0;bottom:0;left:50%;width:2px;background:white;box-shadow:0 0 4px #17263b}.compare-controls{display:flex;gap:12px;align-items:center;margin:10px 0 0}.compare-controls input{flex:1;min-width:40px}.image-note{font-size:12px;color:var(--muted)}dialog{border:none;padding:15px;background:#17263b;border-radius:12px;color:white;max-width:95vw;max-height:95vh}dialog::backdrop{background:#101e32cc}dialog img{display:block;max-width:89vw;max-height:80vh;object-fit:contain}dialog button{float:right;margin-bottom:10px}footer{font-size:12px;color:var(--muted);text-align:center;margin-top:32px}.toggle{display:flex;gap:10px}.stage-list{color:#aec4e3;font-size:12px;margin-top:18px;word-spacing:4px}@media(max-width:650px){main{padding:14px}header{padding:25px 18px}h1{font-size:24px}.stats{grid-template-columns:repeat(2,1fr)}.filters label,.filters select{width:100%}.filters button{width:100%}.pickers{display:block}.pickers label{margin-bottom:10px}}@media print{header{background:white;color:black}.filters,.pickers,button,.compare-controls{display:none}.card,figure,.panel{break-inside:avoid}.copy,pre,.diff{max-height:none;overflow:visible}}
</style></head><body>
<header><div class="eyebrow">HarnessIR · Stage Lab</div><h1>分阶段模型对比</h1><p>查看每个阶段的独立输出，比较模型之间的差异，并追溯后续阶段使用了哪些结果。</p><div class="stage-list">01 差异观察 → 02 Action 规划 → 03 原生条件 → 04 图像执行 → 05 结果判别</div></header>
<main>
<div class="filters"><label>样本<select id="case-filter"></select></label><label>阶段<select id="stage-filter"></select></label><label>模型<select id="model-filter"></select></label><label>状态<select id="status-filter"><option value="">全部状态</option><option value="completed">完成</option><option value="error">失败</option></select></label><button id="download-all">下载当前结果 JSON</button></div>
<div class="stats" id="stats"></div>
<details class="panel" open><summary>输入图像 A / B</summary><div id="sources" style="margin-top:14px"></div></details>
<div class="section-head"><h2>阶段输出</h2><span class="small" id="result-count"></span></div><div id="cards" class="cards"></div>
<div class="section-head"><h2>运行概览</h2><span class="small">耗时与状态用于运行对比，不代表画质排名。</span></div><div class="panel table-wrap" id="run-table"></div>
<div class="panel"><h2>文本差异</h2><p class="small">比较两个运行的原始文本；没有文本时比较结构化输出。</p><div class="pickers"><label>左侧结果<select id="text-left"></select></label><label>右侧结果<select id="text-right"></select></label></div><div id="text-diff" class="diff"></div></div>
<div class="panel"><h2>图像对比</h2><div class="pickers"><label>左侧图像<select id="image-left"></select></label><label>右侧图像<select id="image-right"></select></label></div><div id="image-compare"></div></div>
<footer>本报告可离线打开。保留原始输出，不因美学偏好自动筛选结果。合成演示会明确标注。</footer>
</main><dialog id="zoom"><button id="close-zoom">关闭</button><img id="zoom-image" alt="放大预览"></dialog>
<script id="report-data" type="application/json">__REPORT_DATA__</script>
<script>
'use strict';
const report=JSON.parse(document.getElementById('report-data').textContent);
const stageNames={diagnose:'01 · 差异观察',plan:'02 · Action 规划',compile:'03 · 原生条件',execute:'04 · 图像执行',judge:'05 · 结果判别'};
const $=id=>document.getElementById(id);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pretty=value=>JSON.stringify(value??{},null,2);
const synthetic=r=>Boolean((r.metadata||{}).synthetic||(r.metadata||{}).simulation||(r.metadata||{}).simulation_only||(r.metadata||{}).provider==='demo'||r.provider==='demo'||(r.output?.data||{}).synthetic);
const runText=r=>r.output?.text||pretty(r.output?.data??{});
let visible=[],imageOptions=[];
function option(value,label){return `<option value="${esc(value)}">${esc(label)}</option>`;}
function setOptions(id,items,allLabel){const el=$(id),previous=el.value;el.innerHTML=(allLabel?option('',allLabel):'')+items.map(x=>option(x[0],x[1])).join('');if(items.some(x=>String(x[0])===previous))el.value=previous;}
setOptions('case-filter',report.cases.map(x=>[x.record.id,x.record.name||x.record.id]),'全部样本');
setOptions('stage-filter',Object.entries(stageNames),'全部阶段');
setOptions('model-filter',[...new Set(report.runs.map(x=>x.record.model_id))].sort().map(x=>[x,x]),'全部模型');
function download(name,value){const blob=new Blob([pretty(value)],{type:'application/json;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function figure(im){return im.src?`<figure><img src="${im.src}" alt="${esc(im.label)}" data-zoom="${im.src}"><figcaption>${esc(im.label)} · ${im.width} × ${im.height}</figcaption></figure>`:`<p class="small">${esc(im.label)}：${esc(im.error)}</p>`;}
function tableObject(data){if(!data||!Object.keys(data).length)return '';return `<table>${Object.entries(data).map(([k,v])=>`<tr><th>${esc(k)}</th><td>${esc(typeof v==='object'?JSON.stringify(v):v)}</td></tr>`).join('')}</table>`;}
function card(view){const r=view.record,o=r.output||{},status=r.status==='error'?'失败':r.status==='completed'?'完成':r.status;return `<article class="card"><div class="card-head"><div class="top"><h3>${esc(r.model_id)}</h3><span class="tag ${r.status==='error'?'error':'ok'}">${esc(status)}</span></div><span class="tag">${esc(stageNames[r.stage]||r.stage)}</span>${r.profile?`<span class="tag">${esc(typeof r.profile==='object'?r.profile.id:r.profile)}</span>`:''}${synthetic(r)?'<span class="tag demo">合成演示 · 非模型性能</span>':''}<div class="meta">${esc(r.case_id)} · ${esc(r.id)}<br>${esc(r.created_at)} · ${Number(r.duration_s||0).toFixed(2)} s</div></div><div class="card-body">${r.error?`<pre class="error">${esc(typeof r.error==='object'?pretty(r.error):r.error)}</pre>`:''}${view.images.map(figure).join('')}${o.text?`<div class="copy">${esc(o.text)}</div>`:''}${o.data!=null?`<details ${!o.text?'open':''}><summary>结构化输出</summary><pre>${esc(pretty(o.data))}</pre></details>`:''}${tableObject(o.metrics)}<details><summary>输入与来源 ${esc((r.source_runs||[]).length)} 项</summary><p class="small">${esc((r.source_runs||[]).join(' / ')||'直接输入')}</p><pre>${esc(r.request?.prompt||'')}</pre><pre>${esc(pretty(r.request?.context||{}))}</pre></details><details><summary>用量与运行信息</summary><pre>${esc(pretty({usage:r.usage||{},metadata:r.metadata||{}}))}</pre></details><button data-run-download="${esc(r.id)}">下载本次结果</button></div></article>`;}
function refresh(){const cid=$('case-filter').value,stage=$('stage-filter').value,model=$('model-filter').value,status=$('status-filter').value;visible=report.runs.filter(x=>(!cid||x.record.case_id===cid)&&(!stage||x.record.stage===stage)&&(!model||x.record.model_id===model)&&(!status||x.record.status===status));const records=visible.map(x=>x.record);$('stats').innerHTML=[[records.length,'运行结果'],[records.filter(r=>r.status==='completed').length,'完成'],[records.filter(r=>r.status==='error').length,'失败'],[new Set(records.map(r=>r.model_id)).size,'参与模型']].map(([n,l])=>`<div class="stat"><strong>${n}</strong><span>${l}</span></div>`).join('');const selectedCases=report.cases.filter(x=>!cid||x.record.id===cid);$('sources').innerHTML=selectedCases.map(c=>`<div class="source-case"><h3>${esc(c.record.name||c.record.id)}</h3><p>${esc(c.record.task||'')}</p><div class="sources">${c.images.map(figure).join('')}</div></div>`).join('')||'<div class="empty">尚未添加输入图像。</div>';$('cards').innerHTML=visible.map(card).join('')||'<div class="empty">此筛选条件下没有运行结果。完成任一阶段后即可在这里并排对比。</div>';$('result-count').textContent=`${records.length} 条结果`;$('run-table').innerHTML=`<table><thead><tr><th>样本</th><th>阶段</th><th>模型</th><th>状态</th><th>耗时 / s</th><th>来源</th><th>运行</th></tr></thead><tbody>${records.map(r=>`<tr><td>${esc(r.case_id)}</td><td>${esc(stageNames[r.stage]||r.stage)}</td><td>${esc(r.model_id)}${synthetic(r)?'（合成演示）':''}</td><td>${esc(r.status)}</td><td>${Number(r.duration_s||0).toFixed(2)}</td><td>${esc((r.source_runs||[]).join(', ')||'直接输入')}</td><td>${esc(r.id)}</td></tr>`).join('')}</tbody></table>`;const opts=visible.map(v=>[v.record.id,`${v.record.model_id} · ${stageNames[v.record.stage]||v.record.stage} · ${v.record.case_id} · ${v.record.id}`]);setOptions('text-left',opts);setOptions('text-right',opts);if(opts.length>1&&$('text-left').value===$('text-right').value)$('text-right').selectedIndex=1;imageOptions=[];selectedCases.forEach(c=>c.images.forEach(im=>{if(im.src)imageOptions.push({...im,id:`case:${c.record.id}:${im.label}`,label:`${c.record.id} · ${im.label}`});}));visible.forEach(v=>v.images.forEach((im,i)=>{if(im.src)imageOptions.push({...im,id:`run:${v.record.id}:${i}`,label:`${v.record.case_id} · ${v.record.model_id} · ${v.record.id} · ${im.label}`});}));const imageOpts=imageOptions.map(im=>[im.id,im.label]);setOptions('image-left',imageOpts);setOptions('image-right',imageOpts);if(imageOpts.length>1&&$('image-left').value===$('image-right').value)$('image-right').selectedIndex=imageOpts.length-1;renderDiff();renderImages();}
function renderDiff(){const left=visible.find(x=>x.record.id===$('text-left').value),right=visible.find(x=>x.record.id===$('text-right').value);if(!left||!right){$('text-diff').innerHTML='<div class="empty">暂无可比较的文本。</div>';return;}const aa=runText(left.record).split('\n'),bb=runText(right.record).split('\n'),a=aa.slice(0,400),b=bb.slice(0,400),n=a.length,m=b.length,dp=Array.from({length:n+1},()=>new Uint16Array(m+1));for(let i=n-1;i>=0;i--)for(let j=m-1;j>=0;j--)dp[i][j]=a[i]===b[j]?dp[i+1][j+1]+1:Math.max(dp[i+1][j],dp[i][j+1]);let i=0,j=0,lines=[];while(i<n||j<m){if(i<n&&j<m&&a[i]===b[j]){lines.push(['same','  ',a[i]]);i++;j++;}else if(j<m&&(i===n||dp[i][j+1]>dp[i+1][j])){lines.push(['add','+ ',b[j++]]);}else lines.push(['del','− ',a[i++]]);}let note=aa.length>400||bb.length>400?'<p class="small">差异视图仅展示前 400 行，完整输出保留在结果卡片及 JSON 中。</p>':'';$('text-diff').innerHTML=note+lines.map(([cls,sign,text])=>`<div class="diff-line ${cls}">${sign}${esc(text)}</div>`).join('');}
function renderImages(){const a=imageOptions.find(x=>x.id===$('image-left').value),b=imageOptions.find(x=>x.id===$('image-right').value);if(!a||!b){$('image-compare').innerHTML='<div class="empty">暂无可比较的图像。</div>';return;}const mismatch=a.width!==b.width||a.height!==b.height;$('image-compare').innerHTML=`<div class="compare-frame" style="aspect-ratio:${a.width}/${a.height}"><img src="${b.src}" alt="${esc(b.label)}"><img class="overlay" id="compare-overlay" src="${a.src}" alt="${esc(a.label)}"><div class="divider" id="compare-divider"></div></div><div class="compare-controls"><span class="small">左图</span><input id="wipe" type="range" min="0" max="100" value="50" aria-label="图像分割位置"><span class="small">右图</span></div><p class="image-note">${esc(a.label)}（${a.width} × ${a.height}） / ${esc(b.label)}（${b.width} × ${b.height}）${mismatch?'。尺寸不同：仅按容器等比显示，未进行几何配准。':'。滑动比较；原始像素保留在嵌入图像中。'}</p>`;$('wipe').oninput=e=>{$('compare-overlay').style.clipPath=`inset(0 ${100-e.target.value}% 0 0)`;$('compare-divider').style.left=e.target.value+'%';};}
['case-filter','stage-filter','model-filter','status-filter'].forEach(id=>$(id).onchange=refresh);['text-left','text-right'].forEach(id=>$(id).onchange=renderDiff);['image-left','image-right'].forEach(id=>$(id).onchange=renderImages);$('download-all').onclick=()=>download('stage-results.json',visible.map(x=>x.record));document.addEventListener('click',e=>{const target=e.target;if(target.dataset.zoom){$('zoom-image').src=target.dataset.zoom;$('zoom').showModal();}if(target.dataset.runDownload){const view=report.runs.find(x=>x.record.id===target.dataset.runDownload);if(view)download(view.record.id+'.json',view.record);}});$('close-zoom').onclick=()=>$('zoom').close();$('zoom').addEventListener('click',e=>{if(e.target===$('zoom'))$('zoom').close();});refresh();
</script></body></html>'''
