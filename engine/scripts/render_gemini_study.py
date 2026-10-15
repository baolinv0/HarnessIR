"""Render actual role responses/images; pending stages remain visibly pending."""
import base64
import html
import io
import json
from pathlib import Path
import sys
from PIL import Image
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'engine/src'))
from hir_manual.service import Controller, history
from hir_manual.storage import read_json, write_json, atomic_write, now

def image_tag(path):
    with Image.open(path) as image:
        image = image.convert('RGB'); image.thumbnail((900, 900))
        buffer = io.BytesIO(); image.save(buffer, format='PNG')
    return '<img src="data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode() + '">'

def render(study_dir):
    study = read_json(study_dir / 'study.json'); ctl = Controller(ROOT); cards = []; summary = dict(recorded_at=now(), formal_eligible=False, arms={})
    for arm in ('direct', 'harness'):
        case_id = study.get(arm + '_case_id')
        if not case_id:
            cards.append('<article><h2>' + arm + '</h2><p>尚未运行。</p></article>'); continue
        case = ctl.case(case_id); state = ctl.inspect(case_id); hist = history(case)
        receipts = [read_json(p) for p in case.path('tasks').glob('*/api/receipt.json')]
        earlier_attempts = [read_json(p) for p in case.path('tasks').glob('*/api/attempts/*.json')]
        summary['arms'][arm] = dict(case_id=case_id, state=state.model_dump(), receipts=receipts,
            earlier_unknown_attempts=earlier_attempts,
            api_returned_images=sum(r.get('generated_images', 0) for r in receipts),
            first_round=next((r for r in hist['rounds'] if r['round'] == 1 and r.get('output_asset')), None),
            final_round=next((r for r in hist['rounds'] if r['round'] == state.selected_round and r.get('output_asset')), None))
        body = '<h2>' + arm + ' · ' + state.workflow_status + '</h2><h3>原始输入</h3>' + image_tag(case.path('input/canonical.png'))
        body += '<h3>真实诊断</h3><pre>' + html.escape(json.dumps(hist['diagnosis'], ensure_ascii=False, indent=2)) + '</pre>'
        body += '<h3>按需证据与图例</h3>'
        if not hist['evidence']:
            body += '<p>Direct 固定基线不使用辅助证据；Harness缺失时不得伪造。</p>'
        for evidence in hist['evidence']:
            body += '<p>' + html.escape(evidence['tool_id'] + ' ' + evidence['model_name']) + '</p>'
            for asset in evidence['assets']:
                if asset['kind'] in ('overlay', 'map'):
                    body += image_tag(case.path(asset['path']))
        body += '<h3>提示词、首轮、重试与独立验证</h3>'
        for row in hist['rounds']:
            body += '<h4>Round ' + str(row['round']) + '</h4>'
            if row.get('composition'):
                body += '<pre>' + html.escape(row['composition']['instruction']) + '</pre>'
            if row.get('output_asset'):
                body += image_tag(case.path(row['output_asset']['path']))
            else: body += '<p>尚无生成结果。</p>'
            body += '<pre>' + html.escape(json.dumps(row.get('verification', '独立Verifier尚未运行'), ensure_ascii=False, indent=2)) + '</pre>'
        body += '<h3>实际调用与成本记录（unknown调用费用未知）</h3><pre>' + html.escape(json.dumps(receipts + earlier_attempts, ensure_ascii=False, indent=2)) + '</pre>'
        cards.append('<article>' + body + '</article>')
    previous_ids = list(study.get('failed_case_ids', [])) + list(study.get('superseded_180_second_cases', {}).values())
    prior_calls = []
    for previous_id in previous_ids:
        for file in ctl.case(previous_id).path('tasks').glob('*/api/receipt.json'):
            prior_calls.append(read_json(file))
    summary['prior_configuration_calls'] = prior_calls
    audit_path = study_dir / 'quality_audit.json'
    if audit_path.exists():
        audit = read_json(audit_path); summary['visual_audit'] = audit
        cards.append('<article><h2>视觉审计与结论边界</h2><pre>' + html.escape(json.dumps(audit, ensure_ascii=False, indent=2)) + '</pre><p>独立模型判断保留原文；格式校验不证明视觉坐标或质量判断正确，需复核项不能用于精确指标。</p></article>')
    if prior_calls:
        cards.append('<article><h2>保留的旧配置失败 / 超时</h2><pre>' + html.escape(json.dumps(prior_calls, ensure_ascii=False, indent=2)) + '</pre><p>未知调用的返回与费用未知，不计为成功。</p></article>')
    write_json(study_dir / 'summary.json', summary)
    document = '<!doctype html><meta charset="utf-8"><title>HarnessIR Gemini API 实测</title><style>body{font:16px system-ui;background:#eef1f4;padding:24px}article{background:white;padding:22px;margin:20px 0}img{max-width:48%;height:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><h1>Gemini API 可选通路真实测试</h1><p>独立替代通路，不是ChatGPT桌面结果。生成结果的合理性不能证明原图不可辨认的细节真实。首轮与最终分开记录；未完成环节明确显示。合成工程测试不代替恢复验收。</p>' + ''.join(cards)
    atomic_write(study_dir / 'report.html', document.encode('utf-8'))
    return {'report': str(study_dir / 'report.html'), 'arms': {k:v['state']['workflow_status'] for k,v in summary['arms'].items()}}

if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(); p.add_argument('--study', type=Path, default=ROOT / 'runtime/gemini_api/pilot_20261015'); a = p.parse_args()
    print(json.dumps(render(a.study), ensure_ascii=False))
