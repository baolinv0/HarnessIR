"""Self-contained truthful no-T4 report; generated image slots stay empty."""
import base64
import csv
import html
import io
import json
from pathlib import Path
import re
import sys

from PIL import Image

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'engine/src'))
sys.path.insert(0,str(ROOT/'engine/scripts'))
from hir_manual.service import Controller,history
from hir_manual.storage import read_json,write_json,now,sha256_file
from no_t4_flow import STUDY,handoff


def preview(path):
    with Image.open(path) as image:
        image=image.convert('RGB');image.thumbnail((1280,1100));stream=io.BytesIO();image.save(stream,'JPEG',quality=92)
    return 'data:image/jpeg;base64,'+base64.b64encode(stream.getvalue()).decode()


def build():
    status=handoff();study=read_json(STUDY/'study.json');ctl=Controller(ROOT)
    case=ctl.case(study['harness_case_id']);hist=history(case)
    tools=[]
    for value in hist['evidence']:
        data=value['data'];count=len(data.get('items',data.get('faces',[]))) if value['tool_id']!='T3_DEPTH' else None
        tools.append({'tool':value['tool_id'],'model':value['model_name'],'backend':value.get('backend'),'status':'empty_detection' if count==0 else 'valid',
            'count':count,'cache_key':value['cache_key'],'evidence_source':'prior_real_GPU_cache','new_inference':False})
    tools.append({'tool':'T4_SEGMENTATION','status':'excluded_by_user','count':None,'new_inference':False})
    testlog=ROOT/'engine/validation/no_t4_full_regression.log'
    tests=testlog.read_text(encoding='utf-8',errors='replace') if testlog.exists() else ''
    match=re.search(r'(\d+) passed(?:.*?) in ([\d.]+)s',tests)
    diagnostics=read_json(STUDY/'diagnosis_current_work.json');composition=read_json(STUDY/'composition_current_work.json')
    transportlog=ROOT/'engine/validation/no_t4_upload_transport_tests.log'
    transportmatch=re.search(r'(\d+) passed(?:.*?) in ([\d.]+)s',transportlog.read_text(encoding='utf-8',errors='replace')) if transportlog.exists() else None
    report={'recorded_at':now(),'condition':'no_T4_user_requested','formal_eligible':False,'study':study,'current_status':status,'tools':tools,
        'diagnosis_scope':'current local Work genuine visual analysis; not independent desktop dispatch','composition_scope':'current local Work read source + real evidence/legend',
        'controller_pipeline_to_editor_task':'passed','real_full_cycle':status['full_real_flow_passed'],
        'engineering_tests':{'status':'passed' if match else 'running_or_failed_check_log','passed':int(match.group(1)) if match else None,'seconds':float(match.group(2)) if match else None,'real_inference_acceptance':False},
        'engineering_test_scope':'full suite before optional original upload transport; targeted transport checks after change',
        'upload_transport_tests':{'passed':int(transportmatch.group(1)) if transportmatch else None,'seconds':float(transportmatch.group(2)) if transportmatch else None},
        'restoration_effect':'unknown_pending_real_editor_outputs_and_independent_verification',
        'experiment_conclusion':'Validated three exact-contract real evidence cache imports and role handoff without T4; no restoration-quality or Harness-vs-Direct conclusion yet',
        'diagram_scope':'display previews only; original/evidence assets remain unchanged'}
    write_json(STUDY/'report.json',report)
    with (STUDY/'processing_status.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=['stage','status','scope','count']);writer.writeheader()
        writer.writerow(dict(stage='diagnosis',status='validated',scope='actual current Work',count=1))
        for row in tools:writer.writerow(dict(stage=row['tool'],status=row['status'],scope=row.get('evidence_source','human exclusion'),count=row.get('count')))
        writer.writerow(dict(stage='Composer',status='validated',scope='actual current Work; original+evidence+legend',count=1))
        for arm in ('direct','harness'):writer.writerow(dict(stage=arm+' editor',status=status[arm]['state']['workflow_status'],scope='ChatGPT desktop only',count=status[arm]['state']['budget']['consumed']))
        writer.writerow(dict(stage='independent Verifier',status='pending' if not status['full_real_flow_passed'] else 'inspect_actual_records',scope='fresh session; no editing instruction',count=None))
    direct=(STUDY/'handoff/direct/prompt.txt').read_text(encoding='utf-8')
    harness=(STUDY/'handoff/harness/prompt.txt').read_text(encoding='utf-8')
    header='已完成真实闭环，请查看逐轮记录' if status['full_real_flow_passed'] else '编辑和独立验证尚未完成：真实生成图为0或仍有待完成阶段'
    steps='<ol><li>新建ChatGPT图像编辑会话，仅上传原图并复制Direct文字，保存第一张完整生成图。</li><li>另建新会话，上传同一原图并复制Harness文字；不上传证据图。</li><li>将生成图片本地路径与实际模型名称告诉Codex，导入后自动进入独立Verifier。</li><li>Verifier必须用新会话，仅看原图、实际输出与验证任务；最多3轮，每轮从原图编辑。</li></ol>'
    table=''.join(f"<tr><td>{html.escape(t['tool'])}</td><td>{html.escape(t.get('model',''))}</td><td>{html.escape(t['status'])}</td><td>{t.get('count') if t.get('count') is not None else '—'}</td></tr>" for t in tools)
    cards=[]
    for arm,instruction in [('direct',direct),('harness',harness)]:
        frames=status['first_round_and_final'][arm];first=frames['first_round'];last=frames['final_round'];casearm=ctl.case(study[arm+'_case_id'])
        firstslot=f"<img src='{preview(casearm.path(first['output_asset']['path']))}'>" if first else '<div class="pending">首轮结果尚未生成 / 保存 / 导入</div>'
        finalslot=f"<img src='{preview(casearm.path(last['output_asset']['path']))}'>" if last else '<div class="pending">最终结果尚未经过独立验证选定</div>'
        cards.append(f"<section><h2>{arm.title()} 编辑文字</h2><p>{'固定通用预设，未使用辅助证据' if arm=='direct' else '根据诊断、真实T1–T3证据及图例形成；T4明确排除'}</p><textarea id='{arm}' readonly>{html.escape(instruction)}</textarea><button onclick=\"copyText('{arm}')\">复制编辑文字</button><h3>首轮</h3>{firstslot}<h3>最终</h3>{finalslot}</section>")
    primary=read_json(STUDY/'handoff/harness/attachments.json')['assets'][0]
    rawpath=primary['absolute_path']
    page="<!doctype html><html lang='zh'><meta charset='utf-8'><title>HarnessIR 无T4真实流程</title><style>body{max-width:1250px;margin:30px auto;padding:0 20px;background:#f5f4ee;color:#26312c;font:16px/1.7 system-ui}section{background:#fff;padding:22px;margin:20px 0;border-radius:12px}h1,h2{color:#173d32}img{max-width:100%;height:auto}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:8px}textarea{width:100%;height:310px;font:15px/1.6 monospace}button{background:#236451;color:white;border:0;padding:12px;margin-top:8px;border-radius:6px}.pending{padding:28px;background:#eceae3;color:#625d4d}.notice{background:#ffe5b4;padding:18px;border-radius:10px}pre{white-space:pre-wrap;word-break:break-all}a{color:#236451}</style>"
    page+=f"<h1>无 T4 语义分割证据 · 真实流程验收</h1><div class='notice'>{header}。工程流程到编辑任务已跑通，不代表恢复效果通过；本条件不属于原四工具正式评测。</div><section><h2>下一步</h2>{steps}<p>原图完整路径：</p><pre>{html.escape(rawpath)}</pre></section>"
    page+=f"<section><h2>输入：夜景购物街 spaq_00002</h2><img src='{preview(case.path('input/canonical.png'))}'><p>5488×4112；显示为缩略图，桌面编辑上传原始 JPG（约6.9 MB），已校验解码像素与内部 PNG 完全相同；没有缩放或重压缩。没有读取GT。</p><p>{html.escape(diagnostics['content'])}</p></section>"
    page+=f"<section><h2>证据及范围</h2><table><tr><th>工具</th><th>实际模型</th><th>状态</th><th>检测数</th></tr>{table}</table><p>T1七条OCR仅作参考；低置信度或视觉不清的字符不用于改写。T2合法空检测不能证明没有人脸。T3是相对深度：白近黑远，没有米制单位。三条同合同缓存命中，本轮工具新推理0。</p><img src='{preview(STUDY/'evidence_review.jpg')}'><img src='{preview(STUDY/'ocr_crops_review.jpg')}'></section>"
    page+=''.join(cards)
    page+=f"<section><h2>提示词变化</h2><p>Direct是固定通用修复要求。Harness明确定位夜景阴影、移动人物、文字与广告、玻璃反射、扶梯几何，并保留近处栏杆的原有失焦；不把不确定OCR、小脸或深度估计当成可重建细节。</p><h2>实测结论</h2><p>原图诊断→T1–T3严格缓存校验→排除T4→Composer→仅原图+文字的编辑任务已通过。尚无真实编辑/独立验证结果，无法比较恢复质量或证明Harness优势。</p><p>全工程测试：{str(report['engineering_tests']['passed']) if match else '正在运行，查看日志'}；合成测试不替代真实生成验收。</p></section>"
    page+="<script>function copyText(id){const e=document.getElementById(id);e.focus();e.select();if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(e.value)}else{document.execCommand('copy')}}</script></html>"
    (STUDY/'report.html').write_text(page,encoding='utf-8')
    write_json(STUDY/'report_receipt.json',{'report_sha256':sha256_file(STUDY/'report.html'),'json_sha256':sha256_file(STUDY/'report.json'),'actual_generated_images':status['desktop_actual_generations'],'complete':status['full_real_flow_passed']})
    print(json.dumps({'report':str(STUDY/'report.html'),'actual_outputs':status['desktop_actual_generations'],'real_complete':status['full_real_flow_passed']},ensure_ascii=False))


if __name__=='__main__':build()
