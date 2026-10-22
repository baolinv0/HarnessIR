"""Portable side-by-side stage artifacts, with no synthetic quality rankings."""
import base64
import html
import json
from pathlib import Path
from .models import HREError,file_sha256
from .storage import read_json


def compare_stages(checks:list[Path],out:Path)->Path:
    from .model_runner import _checked_request
    if not checks:raise HREError('comparison_empty','Provide one or more stage-check directories')
    out=Path(out).absolute()
    if out.exists():raise HREError('export_exists','Choose a new comparison output file')
    cards=[];bindings=[]
    for directory in checks:
        directory=Path(directory).absolute();started=read_json(directory/'started.json')
        request_path=Path(started['request_path'])
        if file_sha256(request_path)!=started['request_sha256']:
            raise HREError('worker_request_changed','Stage comparison input changed')
        request=_checked_request(request_path);result=read_json(directory/'response.json')
        report=read_json(directory/'check.json')
        response_path=directory/'response.json'
        if report.get('response_sha256')!=file_sha256(response_path):
            raise HREError('worker_response_changed','Stage comparison output changed')
        identity=request['request'];stage=identity.get('stage','condition')
        model=identity.get('profile_id') or result.get('worker_observation',{}).get('requested_model','external stage worker')
        label=f"{stage} · {model} · {identity.get('strategy','shared analysis')}"
        bindings.append({a['role']:a['sha256'] for a in request['attachments'] if a['role'] in ('A','B')})
        figures=[]
        for attachment in request['attachments']:
            data=base64.b64encode(Path(attachment['path']).read_bytes()).decode()
            figures.append(f'<figure><figcaption>{html.escape(attachment["role"])}</figcaption><img src="data:image/png;base64,{data}"></figure>')
        prompt=result.get('edit_prompt') or result.get('payload',{}).get('edit_prompt','') if result.get('payload',{}) is not None else ''
        prompt_html=f'<h3>Final instruction</h3><pre>{html.escape(prompt)}</pre>' if prompt else ''
        observation=result.get('compiler_observation',result.get('worker_observation',{}))
        cards.append(f'<article><h2>{html.escape(label)}</h2><div class="images">{"".join(figures)}</div>'
                     f'{prompt_html}<p>Contract check: {html.escape(str(report["validated"]))}; case advanced: false</p>'
                     f'<pre>{html.escape(json.dumps(observation,ensure_ascii=False,indent=2))}</pre>'
                     f'<details open><summary>Stage output</summary><pre>{html.escape(json.dumps(result,ensure_ascii=False,indent=2))}</pre></details>'
                     f'<details><summary>Frozen input and instruction</summary><pre>{html.escape(json.dumps(identity,ensure_ascii=False,indent=2))}</pre></details></article>')
    matched=all(item==bindings[0] for item in bindings)
    note='A/B image bytes match across these checks.' if matched else 'A/B image bytes differ. These results are not a controlled model comparison.'
    document='<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>HarnessIR stage comparison</title>'
    document+='<style>body{font:15px system-ui;margin:28px;background:#f3f5f8;color:#172334}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:18px}article{background:white;padding:20px;border:1px solid #d5dce5;border-radius:10px}h2{font-size:19px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f6f8fa;padding:12px;font-size:12px}.images{display:flex;gap:8px}figure{margin:0;flex:1;min-width:0}img{width:100%;max-height:220px;object-fit:contain}summary{cursor:pointer;padding:10px 0}</style>'
    document+=f'<h1>HarnessIR stage comparison</h1><p>{note}</p><p>Contract validation is not a visual quality score. Stage checks do not advance cases or generate editor candidates.</p><main>{"".join(cards)}</main></html>'
    out.parent.mkdir(parents=True,exist_ok=True);out.write_text(document,encoding='utf-8')
    return out
