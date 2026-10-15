"""Write provisional current-Work qualitative analysis with raw-file evidence."""
import base64
import csv
import html
import io
import json
import re
from PIL import Image
from analyze_realzoom_manual_results import ROOT,BATCH,UPLOAD,OUT,collect
from hir_manual.storage import read_json,write_json,atomic_write,sha256_file,now

FINDINGS={
'HC_COZ_171':dict(content='黑白涂绘与粗糙墙面',direct='大轮廓和滴痕保留，墙面颗粒变得更强、更清楚。',harness='大轮廓同样保留，视觉上与Direct接近，未见稳定的额外恢复收益。',comparison='无明确优势',risk='增强后的颗粒不等于已恢复真实微纹理；HR仅作未配准视觉参考。'),
'HC_COZ_174':dict(content='颗粒地面',direct='整体较克制，但细小颗粒也有重新组织的观感。',harness='白色圆粒和局部对比明显增强，材质比原图更粗、更亮。',comparison='Harness材质重塑风险更高',risk='更锐利不等于更保真；参考中的细碎颗粒不能由当前结果逐点验证。'),
'HC_COZ_176':dict(content='织物与线网',direct='主体织物走向保留，色调和对比变化较小。',harness='线网和纤维更突出，粉紫色及亮暗对比变化更明显。',comparison='没有明确的保真改善',risk='原本交织纤维的真实细节仍未充分恢复；不能把强化纹理当作成功重建。'),
'HC_COZ_187':dict(content='绿色玩偶',direct='玩偶轮廓和面部印记保留，平坦区域仍有明显颗粒。',harness='也保留主体，但同样存在噪声和模糊；相对Direct的收益有限。',comparison='两者去退化不足',risk='保持内容是一项正面观察，但未显示同时明显去噪和恢复细节；HR细节更充分。'),
'HC_COZ_188':dict(content='卡通拼图',direct='整体颜色和明暗更接近输入，部分区域被平滑。',harness='harness.jpg明显偏亮、偏红，纹理和拼图边界变得生硬；从原图重试的harness2.jpg减轻了颜色漂移，但细节仍粗糙。',comparison='主文件Harness不如Direct稳妥；重试需单列',risk='用户已确认harness2从原图重试。未确认是否改提示词、模型或设置，不能归因为Verifier收益，也不能替代主文件做首轮胜率。'),
'HC_COZ_189':dict(content='招财猫印花布',direct='更平滑清楚，但猫脸、花纹线条和色块有重新描画的观感。',harness='保留更多输入的颗粒和模糊，改动更克制；没有明显恢复参考里的织物细节。',comparison='Harness更克制，但未显示显著恢复优势',risk='Direct的清楚与Harness的保守各有代价；单凭好看程度无法判定真实保真。'),
}


def image_uri(path):
    with Image.open(path) as im:
        im=im.convert('RGB');im.thumbnail((2300,1600));s=io.BytesIO();im.save(s,'JPEG',quality=93)
    return 'data:image/jpeg;base64,'+base64.b64encode(s.getvalue()).decode()


def main():
    collect();inventory=read_json(OUT/'inventory.json');observations=[]
    for row in inventory['results']:
        if not row['paired']:continue
        sid=row['sample_id'];f=FINDINGS[sid];folder=UPLOAD/sid
        words={arm:len(re.findall(r'\b[A-Za-z]+\b',(folder/(arm+'.txt')).read_text(encoding='utf-8'))) for arm in ['Direct','Harness']}
        observations.append(dict(sample_id=sid,**f,prompt_words=words,comparison_file=row['figure'],reviewer='current Work, aware of labels and authored local prompts; not blind or independent Verifier',reference_alignment_verified=False))
    conclusion='已发现6组成对结果及1张从原图重试结果。当前样本未显示Harness相对Direct稳定、明显的去退化与保真双重优势；部分Harness结果的材质、色调改动更明显。此为本地改编条件的探索性观察，既不能作为论文效果已复现的证据，也不足以推翻论文。'
    protocol=[
      '全部6组未要求T1–T3、T4按条件排除，因此这是基于诊断的提示词对照，未测试工具证据的增益。论文允许简单图像不调用工具，不能把无工具本身当作失败原因。',
      '本地Direct是67词的固定保真指令，已经限制改字、身份、补造细节；它与论文附录的简短分类请求不同。',
      '本地Harness约110–123词，是保守模板与逐图观察的组合。该比较不能等同于锁定官方Composer全流程。',
      '实际图像执行模型、会话、参数和随机性尚未确认；不能把单次成对差异全归因为提示词。',
      '当前分析由参与原提示词编写的Work完成，知道分组；不是独立或盲评，不生成官方D/F/DF分数。',
      '13张保存结果均为不同文件，且不是源图像素复制；它们通过本地宽高比检查，但尺寸增大不是去退化或保真的证明。',
      'COZ是跨焦段LR/HR；当前pixel_metrics_ready=false。HR仅在本离线分析中查看，未进入任何诊断、编辑、Verifier或选图输入。不报告未配准PSNR/SSIM/LPIPS。',
      'harness2用户确认从原图重试，符合从原图出发的方向；是否改词、是否独立验证触发及模型一致性未确认。重复样本单列，不扩大独立场景数。',
      '已有结果6/15，缺9组，其中原本可直接编辑的183、184也尚无保存结果。未把未完成样本计为成功，亦未把6张无文字/建筑样本外推到文字、建筑或人脸。',
    ]
    paper_claims=[
      dict(claim='图像特定指令旨在同时提高去退化与内容保真，降低生成式重绘风险。',local='只看到有限内容保留与个别增强；未看到稳定的双重改善。'),
      dict(claim='独立评价需同时考虑恢复程度和内容保真，清晰或无参考美观分数不能单独证明成功。',local='174材质重塑、188颜色漂移说明必须保留这两个评价维度。'),
      dict(claim='验证失败后可从原图重新执行；最多三次。',local='188重试起点已获用户确认，尚未验证完整闭环或重试因果收益。'),
    ]
    report=dict(recorded_at=now(),conclusion=conclusion,inventory_file=str(OUT/'inventory.json'),paired_scenes=6,result_files=13,confirmed_extra_retry=1,restoration_success_rate=None,harness_win_rate=None,formal_DF_score=None,observations=observations,protocol_limits=protocol,paper_claim_comparison=paper_claims,paper_url=inventory['paper_url'],paper_sections='3.2–3.4, 4.1–4.2, Appendix A.1',actual_executor_model=None,controller_case_states_changed=False,independent_verifier_completed=False,next_steps=['先冻结实际模型、Direct/Harness是否同模型/同设置、首轮顺序及188重试提示词，再做盲评。','先检验174材质与188色调失败是否能通过固定规则从原图重试改善；保留原失败与所有轮次。','补齐183、184；文字/建筑样本需另行跑通，不能用当前6张代替。','若要评价原论文主张，另冻结接近官方的请求、Composer与独立Verifier配置，并做同预算对照。'])
    write_json(OUT/'analysis.json',report)
    with (OUT/'analysis.csv').open('w',newline='',encoding='utf-8-sig') as f:
        fields=['sample_id','content','direct','harness','comparison','risk'];w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows({k:r[k] for k in fields} for r in observations)
    md=['# RealZoom手动增强结果分析','',conclusion,'','范围：6组成对结果+1张用户确认从原图重试，共13张。实际模型未确认。不是独立Verifier或论文正式复现。','','## 逐图观察','']
    for row in observations:
        md.extend([f"### {row['sample_id']} · {row['content']}",'',f"Direct：{row['direct']}",f"Harness：{row['harness']}",f"判断：{row['comparison']}",f"边界：{row['risk']}",f"对照图：{row['comparison_file']}",''])
    md.extend(['## 论文对应与限制','',f"论文原文：{inventory['paper_url']}",'']+['- '+x for x in protocol]+['','## 下一步','']+['- '+x for x in report['next_steps']])
    atomic_write(OUT/'REPORT.md','\n'.join(md).encode('utf-8'))
    page="<!doctype html><html lang='zh'><meta charset='utf-8'><title>RealZoom手动增强结果分析</title><style>body{max-width:1450px;margin:25px auto;padding:0 20px;background:#f6f4ef;font:16px/1.7 system-ui;color:#22382f}section{padding:22px;margin:20px 0;background:white;border-radius:12px}img{max-width:100%;height:auto}.notice{padding:18px;background:#ffe3b1}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:8px}pre{white-space:pre-wrap;word-break:break-all}a{color:#246354}</style>"
    page+=f"<h1>RealZoom 手动增强：结果与论文主张对照</h1><div class='notice'>{html.escape(conclusion)}</div><section><h2>实际发现</h2><p>6组Direct/Harness、1张额外重试，共13张不同保存结果。9组尚缺，其中183、184原已可编辑。6组均无工具证据；不是T1–T4增益评测。实际图像模型未确认，当前Work知晓标签并曾写提示词，结论为非盲探索性分析，独立Verifier尚未执行。</p><p>宽高比门槛13/13通过，输出边长约放大4.5–9.7倍；不等于恢复成功。HR只作离线视觉参考，跨焦段配准未核实，不计算像素质量指标。</p></section>"
    page+="<section><h2>论文主张与本次结果</h2><p><a href='https://arxiv.org/html/2610.10133v2'>HarnessIR论文原文</a>，§3.2–3.4、§4.1–4.2与附录A.1。论文的目标是改善去退化同时保留内容，并采用独立评价及失败后从原图重试；不能仅凭好看或变清楚判断成功。</p><ul>"
    for c in paper_claims:page+=f"<li>{html.escape(c['claim'])} 本批：{html.escape(c['local'])}</li>"
    page+='</ul></section>'
    for o in observations:
        sid=o['sample_id'];r=next(x for x in inventory['results'] if x['sample_id']==sid)
        page+=f"<section><h2>{sid} · {o['content']}</h2><p>从左到右：原图（仅显示放大）、Direct、Harness、跨焦段HR参考（未核实配准）。<a href='comparisons/{sid}.jpg'>打开对照图</a></p><img src='{image_uri(r['figure'])}'><p><b>Direct：</b>{html.escape(o['direct'])}</p><p><b>Harness：</b>{html.escape(o['harness'])}</p><p><b>观察结论：</b>{html.escape(o['comparison'])}</p><p>{html.escape(o['risk'])}</p>"
        if r['extra_figure']:page+=f"<h3>重试单列（从原图，用户已确认）</h3><p>原图 / harness.jpg / harness2.jpg / HR参考。不用重试结果替换主文件做同预算对比。</p><img src='{image_uri(r['extra_figure'])}'>"
        page+='<table><tr><th>文件</th><th>尺寸</th><th>边长倍率</th><th>亮度均值变化（0–255，非质量分）</th></tr>'
        for f in r['results']:page+=f"<tr><td>{html.escape(f['filename'])}</td><td>{f['width']}×{f['height']}</td><td>{f['width_scale']:.3f}×</td><td>{f['mean_luma_delta_8bit']:+.2f}</td></tr>"
        page+='</table></section>'
    page+='<section><h2>协议差异与判断边界</h2><ul>'+''.join('<li>'+html.escape(x)+'</li>' for x in protocol)+'</ul><h2>下一步</h2><ul>'+''.join('<li>'+html.escape(x)+'</li>' for x in report['next_steps'])+'</ul></section></html>'
    atomic_write(OUT/'report.html',page.encode('utf-8'));write_json(OUT/'report_receipt.json',{'report_sha256':sha256_file(OUT/'report.html'),'analysis_sha256':sha256_file(OUT/'analysis.json'),'inventory_sha256':sha256_file(OUT/'inventory.json'),'actual_discovered_outputs':13,'paired_scenes':6,'formal_quality_evaluation_passed':False})
    print({'report':str(OUT/'report.html'),'paired_scenes':6,'saved_files':13,'formal_quality_pass':False})

if __name__=='__main__':main()
