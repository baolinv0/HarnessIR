"""Self-contained actual-input/evidence report; never synthesizes edits."""
from pathlib import Path
import argparse,json,re,html,io,base64,csv,sys
from PIL import Image

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'engine/src'))
from hir_manual.cache import EvidenceCache
from hir_manual.storage import sha256_file

def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def picture(path):
    with Image.open(path) as im:
        im=im.convert('RGB');im.thumbnail((700,700));buffer=io.BytesIO();im.save(buffer,format='PNG')
    return '<img src="data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode()+'">'

def build(delivery,destination):
    receipt=read(delivery/'local_validation.json');assert receipt['strictly_validated']
    run=read(delivery/'run.json');rows=read(delivery/'inputs.json')['images']
    page=(delivery/'evidence_gallery.html').read_text(encoding='utf-8')
    sections={re.search(r'<h2>(.*?) — ',s).group(1):s for s in re.findall(r'<section>(.*?)</section>',page,re.S)}
    diagnoses={}
    cases=ROOT/'runtime/quality20/pilot20_20261013_stable_v2/workflow/cases'
    for state_file in cases.glob('*/state.json'):
        for done_file in state_file.parent.glob('tasks/diagnose_*/done.json'):
            done=read(done_file);response=state_file.parent/done['response_file']
            if sha256_file(response)!=done['response_sha256']:continue
            value=read(response)
            diagnoses[value['input_sha256']]=dict(payload=value['payload'],case_id=value['case_id'],source='已校验的历史当前 Work 诊断；不是桌面派发')
    cache=EvidenceCache(ROOT/'Data/annotations/cache');evidence={};warnings=[]
    for tool in ['T1_OCR','T2_FACE','T3_DEPTH']:
        for contract_file in cache.root.glob(tool+'/*/contract.json'):
            try:
                contract=read(contract_file)
                if contract['canonical_sha256'] not in {r['canonical_sha256'] for r in rows}:continue
                directory=cache.lookup(contract)
                if not directory:continue
                manifest=read(directory/'evidence.json');key=(contract['canonical_sha256'],tool)
                if key not in evidence or manifest['formal_eligible']:
                    evidence[key]=(directory,manifest)
            except (ValueError,OSError,KeyError) as exc:warnings.append(str(contract_file)+': '+str(exc))
    cards=[];table=[]
    for row in rows:
        image_id=row['image_id'];metadata=read(delivery/'images'/f'{image_id}.json') if (delivery/'images'/f'{image_id}.json').exists() else {'status':'pending'}
        diagnostic=diagnoses.get(row['canonical_sha256']) or diagnoses.get(row['original_sha256'])
        diagnostic_html='<p>未找到与输入哈希绑定的真实诊断。</p>'
        if diagnostic:
            diagnostic_html='<p>'+html.escape(diagnostic['source'])+'</p><details><summary>真实诊断及工具计划</summary><pre>'+html.escape(json.dumps(diagnostic['payload'],ensure_ascii=False,indent=2))+'</pre></details>'
        tools_html=[];counts={}
        for tool in ['T1_OCR','T2_FACE','T3_DEPTH']:
            item=evidence.get((row['canonical_sha256'],tool))
            if not item:
                tools_html.append('<div><h3>'+tool+'</h3><p>缺失：本轮未补跑此工具。</p></div>');counts[tool]='missing';continue
            directory,manifest=item;counts[tool]='validated_history'
            assets=[a for a in manifest['assets'] if a['kind']=='overlay' or a['path']==manifest.get('data',{}).get('preview_path') or 'legend' in a['path']]
            rendered=''.join(picture(directory/a['path']) for a in assets if Path(a['path']).suffix.lower()=='.png')
            content=html.escape(json.dumps(manifest['data'],ensure_ascii=False,indent=2))
            tools_html.append('<div><h3>'+tool+'</h3><p>'+html.escape(manifest['model_name'])+'；历史真实证据，重新校验；非本轮推理。</p>'+rendered+'<details><summary>原始内容 / 图例 / 空检测</summary><pre>'+content+'</pre></details></div>')
        t4=sections[image_id]
        cards.append('<article><h2>'+html.escape(image_id)+'</h2><p>原图SHA256：'+row['original_sha256']+'；尺寸 '+str(row['width'])+' × '+str(row['height'])+'</p>'+diagnostic_html+'<div class="tools">'+''.join(tools_html)+'</div><h3>T4 SAM3.1 独立替代：原图 / Mask</h3>'+t4+'<details><summary>T4 实例、置信度、资源和失败记录</summary><pre>'+html.escape(json.dumps(metadata,ensure_ascii=False,indent=2))+'</pre></details><p class="pending">编辑结果：未生成。Direct首轮、Harness首轮及最终结果：未运行。独立恢复Verifier：未运行。新增T4证据尚未送入真实Composer，编辑提示词尚无已执行的变化。</p></article>')
        table.append(dict(image_id=image_id,original_sha256=row['original_sha256'],width=row['width'],height=row['height'],T4_status=metadata['status'],instances=len(metadata.get('instances',[])),seconds=metadata.get('elapsed_seconds'),peak_rss_mib=metadata.get('peak_rss_mb'),peak_gpu_mib=metadata.get('peak_gpu_memory_mb'),process_released=metadata.get('process_released'),**counts))
    legend=''.join(re.findall(r'<span\b.*?</span>',page,re.S))
    summary=dict(scope='20-photo SAM3.1 alternative T4 interface test; restoration incomplete',run_id=run['run_id'],statistics=receipt['statistics'],contract=run['contract'],local_validation=receipt['strictly_validated'],direct_edits=0,harness_edits=0,independent_restoration_verifier=0,formal_eligible=False,cache_scan_warnings=warnings)
    destination.mkdir(parents=True,exist_ok=True)
    (destination/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    with (destination/'processing_status.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(table[0]));writer.writeheader();writer.writerows(table)
    document='<!doctype html><meta charset="utf-8"><title>HarnessIR SAM3.1 真实替代测试</title><style>body{font:16px system-ui;background:#edf0f3;margin:24px;color:#202932}article{background:white;padding:20px;margin:20px 0;border-radius:10px}img{max-width:48%;height:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere}.tools{display:grid;grid-template-columns:repeat(3,1fr);gap:15px}.tools img{max-width:100%}.pending{background:#fff3cd;padding:12px}span{display:inline-block;padding:4px;margin:3px}section{margin:10px 0}</style><h1>20张真实照片：SAM3.1独立替代测试</h1><p>原SAM3正式评测未通过；没有恢复效果或Harness优于Direct的结论。左图为原始LQ的规范化显示，右图为分割证据，不是恢复图。T1–T3仅显示已有严格复查的真实缓存，缺失项明确标记。真实诊断来自历史当前Work通道。</p><pre>'+html.escape(json.dumps(receipt['statistics'],ensure_ascii=False))+'</pre><p>本轮固定31类、阈值0.5、1008模型输入、FP32、CPU逐实例映射原图尺寸；空检测不代表图中没有对象。旧配置的加载失败、精度冲突、OOM和900秒超时均保留。</p>'+legend+''.join(cards)
    (destination/'report.html').write_text(document,encoding='utf-8')
    return summary

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--delivery',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    print(json.dumps(build(args.delivery,args.out),ensure_ascii=False))
