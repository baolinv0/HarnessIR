"""Export original five real GPU pilot inputs, evidence and honest manual roles.

Does not run inference, issue new editing requests, or advance cases.
"""
import base64
import html
import io
import json
from pathlib import Path
import shutil
import sys

from PIL import Image

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'engine/src'))
from hir_manual.storage import read_json,write_json,sha256_file,atomic_write,now
from hir_manual.transport import image_observations
from no_t4_flow import DIRECT_INSTRUCTION
from render_remote_pilot import ledger_entries,validated

OUT=ROOT/'runtime/initial5/manual_upload'
TITLES={'HC_RAIM_Phase1_011':'夜间人像','commons_002':'模糊霓虹招牌','lolv2_00690':'低照室内靶场','HC_ReWiTe_260_tele':'花坛、车辆与凸面镜','spaq_00002':'夜景商业街'}


def jpg_view(source,target):
    # Display-only visualization; keep original cache assets and coordinates.
    with Image.open(source) as im:
        im=im.convert('RGB');im.thumbnail((1600,1600));im.save(target,'JPEG',quality=94)
    if target.stat().st_size>20_000_000:raise ValueError('Preview exceeds upload budget')


def embed(source):
    with Image.open(source) as im:
        im=im.convert('RGB');im.thumbnail((750,650));s=io.BytesIO();im.save(s,'JPEG',quality=88)
    return 'data:image/jpeg;base64,'+base64.b64encode(s.getvalue()).decode()


def main():
    dataset=ROOT/'runtime/offline_gpu/prepared_20261013';rows={r['image_id']:r for r in read_json(dataset/'manifest.json')['images']}
    ids=read_json(ROOT/'runtime/sam3_handoff/pilot5.json')['image_ids']
    records={(r['image_id'],r['tool_id']):r for r in read_json(ROOT/'runtime/offline_gpu/t1_t2_t3_pilot_summary.json')['results']}
    ledgers,ledger_sources=ledger_entries(ROOT,['export_98bbbe1252e34e8e8650e7580675a55b'])
    old={r['sample_id']:r for r in read_json(ROOT/'runtime/quality20/pilot20_20261013_stable_v2/issued_tasks.json')['records']}
    schema=read_json(ROOT/'Design_v1_1_20261012/schemas/composition.schema.json')
    OUT.mkdir(parents=True,exist_ok=True);export=[]
    page="<!doctype html><html lang='zh'><meta charset='utf-8'><title>最初五张 GPU 试验图：手动上传</title><style>body{max-width:1150px;margin:25px auto;padding:15px;font:16px/1.7 system-ui;background:#f5f3ed}section{padding:22px;background:white;margin:22px 0;border-radius:10px}img{max-width:100%;max-height:520px}textarea{width:100%;height:260px;box-sizing:border-box;font:15px/1.5 system-ui}button{padding:10px 18px;background:#245b4f;color:white;border:0;border-radius:5px;margin:8px 0}.evidence{display:flex;flex-wrap:wrap;gap:15px}.evidence figure{width:46%;margin:0}pre{white-space:pre-wrap;word-break:break-all}.note{background:#fff0cc;padding:15px}a{color:#245b4f}</style><h1>最初五张 · 真实GPU证据与手动上传</h1><p>五图各有T1 OCR、T2人脸、T3相对深度，共15条严格校验的真实缓存；T4按当前条件不用。合法空检测不等于失败，也不证明没有小字或小脸。</p><div class='note'>修图会话：只上传本节input文件+所选完整编辑文字。Composer会话：上传input文件及Views内证据图，粘贴Composer.txt，得到JSON中的instruction后再另开修图会话。4张尚无已完成Harness文字；spaq_00002有。不要把Composer任务文字直接当修图指令。</div>"
    markdown=['# 最初五张GPU试验图手动上传','', '真实缓存15条，T4不用。前4张尚未完成Harness Composer，需先执行Composer.txt；spaq已有Harness.txt。Direct.txt是统一固定基线，不是辅助证据的输出。','']
    for sid in ids:
        row=rows[sid];target=OUT/sid;target.mkdir(exist_ok=True);views=target/'Views';views.mkdir(exist_ok=True)
        canonical=dataset/row['canonical_path'];assert sha256_file(canonical)==row['canonical_sha256']
        transport={'policy':'canonical_exact_bytes','canonical_sha256':row['canonical_sha256'],'reencoded':False,'resized':False}
        if sid=='spaq_00002':
            study=read_json(ROOT/'runtime/no_t4_flow/spaq_00002/study.json');case=ROOT/'cases'/study['harness_case_id']
            req=read_json(ROOT/'runtime/no_t4_flow/spaq_00002/handoff/harness/request.json')
            assert req['role']=='execute' and len(req['allowed_assets'])==1
            source=case/req['allowed_assets'][0]['path'];name='input.jpg';transport=req['context']['original_upload_transport']
            config=read_json(case/'case_config.json')
            assert image_observations(source,canonical,config)['pixel_sha256']==image_observations(canonical,canonical,config)['pixel_sha256']==transport['pixel_sha256']
            assert sha256_file(source)==row['original_sha256']==req['allowed_assets'][0]['sha256']
        else:source=canonical;name='input.png'
        assert source.stat().st_size<=20_000_000
        shutil.copyfile(source,target/name);assert sha256_file(target/name)==sha256_file(source)
        atomic_write(target/'Direct.txt',DIRECT_INSTRUCTION.encode('utf-8'))
        response=read_json(Path(old[sid]['request_path']).with_name('response.json'))
        assert response['input_sha256']==row['canonical_sha256']
        diagnosis=response['payload'];shutil.copyfile(Path(old[sid]['request_path']).with_name('response.json'),target/'Diagnosis_Response.json')
        write_json(target/'Diagnosis.json',diagnosis)
        evidence=[];images=[]
        for tool,view_name,asset_path in [('T1_OCR','01_OCR.jpg','overlays/ocr.png'),('T2_FACE','02_Faces.jpg','overlays/faces.png'),('T3_DEPTH','03_Depth.jpg','maps/depth_vis.png')]:
            ev,directory=validated(ROOT,dataset,row,tool,records[(sid,tool)],ledgers)
            destination=target/'Evidence'/tool
            copied_ok=(destination/'evidence.json').exists() and sha256_file(destination/'evidence.json')==sha256_file(directory/'evidence.json')
            copied_ok=copied_ok and all((destination/a['path']).is_file() and sha256_file(destination/a['path'])==a['sha256'] for a in ev['assets'])
            if not copied_ok:shutil.copytree(directory,destination,dirs_exist_ok=True)
            # Recheck copied evidence data and all declared assets.
            assert sha256_file(destination/'evidence.json')==sha256_file(directory/'evidence.json')
            for a in ev['assets']:assert sha256_file(destination/a['path'])==a['sha256']
            jpg_view(destination/asset_path,views/view_name);images.append((tool,views/view_name))
            count=len(ev['data'].get('items',[])) if tool=='T1_OCR' else len(ev['data'].get('faces',[])) if tool=='T2_FACE' else None
            evidence.append({'tool_id':tool,'count':count,'status':'empty_detection' if count==0 else 'valid','model':ev['model_name'],'production_cache':str(directory),'copied_evidence':str(destination),'cache_key':ev['cache_key'],'manifest_sha256':sha256_file(destination/'evidence.json'),'data':ev['data'],'source_width':ev['source_width'],'source_height':ev['source_height'],'preview':str(views/view_name)})
        shutil.copyfile(target/'Evidence/T3_DEPTH/maps/depth_legend.png',views/'04_Depth_Legend.png')
        write_json(target/'Evidence_Index.json',{'source':row,'upload_transport':transport,'tools':evidence,'T4':'excluded_by_user','new_inferences':0,'original_cache_preserved':True,'views':'Display previews downscaled to max1600px; original full-resolution assets and coordinates retained in Evidence. Not edited photographs.'})
        composer=("You are the Composer for conservative photo restoration. Inspect image 1 (the original input) and the attached real evidence views, including the depth legend. "
          "Image 2 is the OCR polygon overlay, image 3 the face/landmark overlay, image 4 relative-depth visualization, and image 5 its legend. "
          "The evidence views are display previews capped at 1600 pixels; all evidence coordinates refer to the original canonical width/height stated below. "
          "Do not infer metric depth. White is near, black is far. Empty OCR/face detections are successful empty results and do not establish that tiny text or faces are absent. "
          "No T4 semantic masks are available or permitted in this condition. Treat OCR strings as uncertain protection hints, not replacements for visible lettering. "
          "Use the original and evidence to write a precise, source-supported editing instruction. Preserve identities, geometry, text, scene contents and intentional blur. "
          "The eventual image editor will receive ONLY the original and your instruction, so do not refer to evidence attachments in that instruction. "
          "Do not generate an edited image in this Composer conversation. Return only a JSON payload matching the schema below.\n\n"
          +f"Original canonical dimensions: {row['width']} x {row['height']}.\n\nActual earlier visual diagnosis (not independent verification):\n"+json.dumps(diagnosis,ensure_ascii=False,indent=2)
          +"\n\nReal T1-T3 evidence and legends:\n"+json.dumps([{k:v for k,v in e.items() if k in ('tool_id','count','status','model','data','source_width','source_height')} for e in evidence],ensure_ascii=False,indent=2)
          +"\n\nRequired composition payload schema:\n"+json.dumps(schema,ensure_ascii=False,indent=2))
        atomic_write(target/'Composer.txt',composer.encode('utf-8'))
        harness=None
        if sid=='spaq_00002':
            harness=(ROOT/'runtime/no_t4_flow/spaq_00002/handoff/harness/prompt.txt').read_text(encoding='utf-8')
            assert harness.strip()==req['context']['instruction'].strip();atomic_write(target/'Harness.txt',harness.encode('utf-8'))
        labels=', '.join(e['tool_id']+'='+str(e['count']) for e in evidence if e['count'] is not None)
        note=(f'{sid} · {TITLES[sid]}\n原图：{target/name}\nDirect全文：Direct.txt\n'
          +'Harness全文：'+('Harness.txt（已完成Composer）' if harness else '尚未完成；先按Composer.txt执行独立Composer，不要把它直接送给修图器')
          +f'\n真实证据：{target/"Evidence"}\n可上传Composer的证据查看图：{views}\n{labels}\nT3是float32原图尺寸相对深度，白近黑远。T4不用。\n'
          +'修图仅上传input与完整编辑文字；Composer上传input+Views内4张图，再贴Composer.txt。\n'
          +f'保存生成图：{sid}_Direct_R1.png / {sid}_Harness_R1.png。保存第一张完整输出并记录实际模型；额外输出全部保留。\n')
        atomic_write(target/'说明.txt',note.encode('utf-8'))
        markdown.extend([f'## {sid} · {TITLES[sid]}','',note,'','Direct完整编辑文字：','',DIRECT_INSTRUCTION,'','Harness完整编辑文字：','',harness or '尚未完成。请先使用同目录Composer.txt及input+Views内4张证据图。',''])
        page+=f"<section id='{sid}'><h2>{sid} · {TITLES[sid]}</h2><img src='{embed(target/name)}'><p>上传原图：<a href='{sid}/{name}'>{name}</a> · <a href='{sid}/Diagnosis.json'>完整诊断</a> · <a href='{sid}/Evidence_Index.json'>证据索引</a></p><pre>{html.escape(str(target/name))}</pre><p>{labels}；T3原图尺寸float32相对深度。零检测有效；T4不用。</p><div class='evidence'>"
        for tool,p in images:page+=f"<figure><img src='{embed(p)}'><figcaption><a href='{sid}/Views/{p.name}'>{tool}查看图</a>（预览尺寸）</figcaption></figure>"
        page+=f"<figure><img src='{embed(views/'04_Depth_Legend.png')}'><figcaption><a href='{sid}/Views/04_Depth_Legend.png'>深度图例：白近黑远，非米制</a></figcaption></figure></div><h3>Direct完整编辑文字</h3><textarea id='{sid}_direct' readonly>{html.escape(DIRECT_INSTRUCTION)}</textarea><button onclick=\"copyText('{sid}_direct')\">复制Direct完整文字</button>"
        if harness:page+=f"<h3>Harness完整编辑文字（已完成Composer）</h3><textarea id='{sid}_harness' readonly>{html.escape(harness)}</textarea><button onclick=\"copyText('{sid}_harness')\">复制Harness完整文字</button>"
        else:page+=f"<h3>Harness需先完成Composer</h3><p>上传本图input与Views内4张图，粘贴下面整段，返回JSON；不要在此会话直接修图。</p><textarea id='{sid}_composer' readonly>{html.escape(composer)}</textarea><button onclick=\"copyText('{sid}_composer')\">复制Composer完整任务</button>"
        page+='<p>真实修复图及独立Verifier：尚未完成。本次仅整理已有材料，未重新运行工具。</p></section>'
        export.append({'image_id':sid,'title':TITLES[sid],'input':str(target/name),'input_sha256':sha256_file(target/name),'canonical_sha256':row['canonical_sha256'],'upload_transport':transport,'Direct':str(target/'Direct.txt'),'Harness':str(target/'Harness.txt') if harness else None,'Composer':str(target/'Composer.txt'),'evidence':evidence,'tool_results':3,'actual_generations':0})
        print(sid+' exported; verified T1-T3',flush=True)
    page+="<script>function copyText(id){const e=document.getElementById(id);e.focus();e.select();document.execCommand('copy')}</script></html>"
    atomic_write(OUT/'index.html',page.encode('utf-8'));atomic_write(OUT/'全部五图完整内容.md','\n'.join(markdown).encode('utf-8'))
    write_json(OUT/'manifest.json',{'exported_at':now(),'count':5,'validated_real_tool_results':15,'new_inferences':0,'T4':'excluded','ledger_sources':ledger_sources,'images':export,'GT_included':False,'actual_generated_images':0,'scope':'manual material export; only spaq has an existing accepted Harness composition, four manual Composer tasks remain pending'})
    print({'index':str(OUT/'index.html'),'images':5,'validated_real_evidence':15,'Harness_prompts':1,'pending_manual_Composer':4})

if __name__=='__main__':main()
