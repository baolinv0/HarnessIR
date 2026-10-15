"""Self-contained normalized evidence gallery from actual validated cache records."""
import base64
import csv
import html
import io
import json
from pathlib import Path
import sys
from PIL import Image
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'engine/src'))
from hir_manual.storage import read_json, write_json, sha256_file, atomic_write, now
from hir_manual.sam31_evidence import RAW_CONTRACT, RUN_ID, WEIGHT_SHA

def picture(path):
    with Image.open(path) as image:
        image = image.convert('RGB'); image.thumbnail((700, 700))
        buffer = io.BytesIO(); image.save(buffer, format='PNG')
    return '<img src="data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode() + '">'

def main():
    batch = read_json(ROOT / 'runtime/sam31_normalization/batch_png_v2/summary.json')
    if not batch['completed'] or len(batch['records']) != 20 or any(r['status'] not in ('imported', 'existing') for r in batch['records']):
        raise ValueError('Full20 normalization is not complete; do not publish complete index')
    native = ROOT / 'Data/annotations/cache/alternatives/SAM31' / RAW_CONTRACT / RUN_ID
    frozen = {r['image_id']: r for r in read_json(native / 'inputs.json')['images']}
    local = {r['sample_id']: r for r in read_json(ROOT / 'runtime/quality20/pilot20_20261013_stable_v2/manifest.json')['images']}
    destination = ROOT / 'runtime/reports/sam31_normalized/20261015'
    cards = []; rows = []
    for record in batch['records']:
        image_id = record['image_id']; directory = Path(record['directory'])
        manifest = read_json(directory / 'evidence.json'); source = frozen[image_id]
        canonical = Path(local[image_id]['canonical_path'])
        if sha256_file(canonical) != source['canonical_sha256']:
            raise ValueError('Gallery source does not match frozen canonical')
        ready = read_json(directory / 'ready.json')
        if (manifest['input_sha256'] != source['canonical_sha256'] or manifest['original_sha256'] != source['original_sha256']
                or manifest['cache_key'] != record['cache_key'] or ready['cache_key'] != record['cache_key']
                or manifest['checkpoint_sha256'] != WEIGHT_SHA or manifest['formal_eligible'] is not False):
            raise ValueError('Gallery source/model/cache association differs from validated batch')
        if sha256_file(directory / 'evidence.json') != ready['evidence_sha256']:
            raise ValueError('Manifest no longer matches validated ready marker')
        for asset in manifest['assets']:
            if sha256_file(directory / asset['path']) != asset['sha256']:
                raise ValueError('Gallery asset changed after normalization')
        count = len(manifest['data']['native_masks'])
        row = dict(image_id=image_id, canonical_sha256=source['canonical_sha256'], original_sha256=source['original_sha256'],
                   width=source['width'], height=source['height'], model=manifest['model_name'],
                   checkpoint_sha256=manifest['checkpoint_sha256'], cache_key=record['cache_key'],
                   detection='nonempty' if count else 'legal_empty', instances=count,
                   normalization_seconds=record['elapsed_seconds'], normalization_peak_rss_mib=record['peak_rss_mib_sampled'],
                   process_released=record['process_released'], cache_directory=str(directory), formal_eligible=False)
        rows.append(row)
        cards.append('<article><h2>' + html.escape(image_id) + '</h2><p>原始输入 / 标准语义证据。' + str(count) + ' 个实例；0为未分配区域，不能解释成可靠背景。显示图只展示固定优先级类别，原生实例重叠仍完整保存。</p>' +
            picture(canonical) + picture(directory / manifest['data']['preview_path']) + picture(directory / 'maps/segmentation_legend.png') +
            '<details><summary>合同、原始内容与耗时</summary><pre>' + html.escape(json.dumps(row, ensure_ascii=False, indent=2)) + '</pre><pre>' + html.escape(json.dumps(manifest['data'], ensure_ascii=False, indent=2)) + '</pre></details></article>')
    summary = dict(recorded_at=now(), scope='SAM3.1 accepted native20 normalized to v1.1 alternative cache; not restoration',
        images=20, nonempty=sum(r['detection']=='nonempty' for r in rows), legal_empty=sum(r['detection']=='legal_empty' for r in rows),
        failed=0, missing=0, production_v1_1_registered=True, formal_eligible=False, new_model_inferences=0,
        normalization_version='sam31_stream_lossless_png_v2', checkpoint_sha256=WEIGHT_SHA,
        normalization_total_seconds=sum(r['normalization_seconds'] for r in rows),
        normalization_peak_rss_mib_sampled=max(r['normalization_peak_rss_mib'] for r in rows),
        all_processes_released=all(r['process_released'] for r in rows), records=rows)
    write_json(destination / 'summary.json', summary)
    with (destination / 'processing_status.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    atomic_write(destination / 'report.html', ('<!doctype html><meta charset="utf-8"><title>SAM3.1标准证据20图</title><style>body{font:16px system-ui;background:#eef1f4;padding:24px}article{background:white;margin:20px 0;padding:20px}img{max-width:45%;height:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><h1>SAM3.1标准证据：20张真实原图</h1><p>18非空、2合法空，原生NPZ保留，实例PNG逐像素一致。此次只是标准缓存导入，没有重跑模型，也没有生成恢复图。原SAM3正式评测资格为false；工程通过不证明分割准确率或恢复提升。</p>' + ''.join(cards)).encode('utf-8'))
    index = ROOT / 'Data/annotations/cache/indexes/sam31_png_v2_20261015'
    write_json(index / 'manifest.json', summary)
    atomic_write(index / 'processing_status.csv', (destination / 'processing_status.csv').read_bytes())
    print(json.dumps({k:v for k,v in summary.items() if k != 'records'}, ensure_ascii=False))

if __name__ == '__main__': main()
