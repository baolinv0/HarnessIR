"""Inventory human-saved outputs and create evaluation-only visual comparisons.

GT is read only here, for offline visual reference; never sent to restoration
roles. No registration or full-reference quality score is assumed valid.
"""
import base64
import csv
import io
import json
from pathlib import Path
import sys
import numpy as np
from PIL import Image,ImageDraw

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'engine/src'))
from hir_manual.storage import read_json,write_json,sha256_file,now,atomic_write

BATCH=ROOT/'runtime/realzoom/no_t4_20261014'
UPLOAD=BATCH/'manual_upload'
OUT=BATCH/'result_analysis'


def comparison(sid,paths):
    w,h=600,800
    canvas=Image.new('RGB',(len(paths)*w,h+55),'#eeeeee');draw=ImageDraw.Draw(canvas)
    for i,(label,path) in enumerate(paths):
        with Image.open(path) as im:
            im=im.convert('RGB');im.thumbnail((w-12,h-15),Image.Resampling.LANCZOS)
            # Equal presentation size; low-resolution LQ is enlarged only in
            # this labeled visualization, never saved over the original.
            scale=min((w-12)/im.width,(h-15)/im.height)
            if scale>1:im=im.resize((round(im.width*scale),round(im.height*scale)),Image.Resampling.LANCZOS)
            canvas.paste(im,(i*w+(w-im.width)//2,48+(h-15-im.height)//2))
        draw.text((i*w+8,8),label,fill='black')
        draw.text((i*w+8,25),str(path.name),fill='black')
    target=OUT/'comparisons'/f'{sid}.jpg';target.parent.mkdir(parents=True,exist_ok=True);canvas.save(target,quality=95)
    return target


def collect():
    OUT.mkdir(parents=True,exist_ok=True);manifest=read_json(BATCH/'manifest.json');rows=[];found=[]
    for r in manifest['images']:
        sid=r['sample_id'];folder=UPLOAD/sid;source=folder/'input.png'
        if sha256_file(source)!=r['canonical_sha256']:raise ValueError('Changed handoff input: '+sid)
        candidates=sorted(p for p in folder.iterdir() if p.suffix.lower() in ('.jpg','.jpeg','.png','.webp') and p.name.lower()!='input.png')
        info=[]
        with Image.open(source) as orig:input_rgb=np.asarray(orig.convert('RGB'),dtype=np.float32);iw,ih=orig.size
        for p in candidates:
            name=p.stem.lower();arm='direct' if name=='direct' else 'harness' if name=='harness' else 'harness_extra_unconfirmed' if name.startswith('harness') else 'unknown'
            with Image.open(p) as im:
                ow,oh=im.size;mode=im.mode;rgb=np.asarray(im.convert('RGB').resize((iw,ih),Image.Resampling.LANCZOS),dtype=np.float32)
                error=abs((ow/oh)/(iw/ih)-1)
                y=np.dot(rgb,[.299,.587,.114]);input_y=np.dot(input_rgb,[.299,.587,.114])
                retry=sid=='HC_COZ_188' and name=='harness2'
                item=dict(sample_id=sid,filename=p.name,path=str(p),sha256=sha256_file(p),bytes=p.stat().st_size,width=ow,height=oh,source_width=iw,source_height=ih,mode=mode,arm_from_filename=arm,provider_round=None,provider_model=None,provider_session=None,retry_from_original_confirmed=retry,retry_confirmation='user explicitly replied 从原图重试' if retry else None,mean_luma_8bit=float(y.mean()),source_mean_luma_8bit=float(input_y.mean()),mean_luma_delta_8bit=float(y.mean()-input_y.mean()),aspect_relative_error=error,aspect_gate_2pct=error<=.02,width_scale=ow/iw,height_scale=oh/ih,source_resized_L1_mean=float(np.mean(abs(rgb-input_rgb))),source_resized_L1_scope='change magnitude only; not restoration quality',source_pixel_duplicate=bool(np.array_equal(rgb,input_rgb)),mtime_utc=__import__('datetime').datetime.fromtimestamp(p.stat().st_mtime,__import__('datetime').timezone.utc).isoformat())
            info.append(item);found.append(item)
        available={p.name.lower():p for p in candidates}
        paired='direct.jpg' in available and 'harness.jpg' in available
        gt=ROOT/'Data/HardCases/Telephoto/RealZoom'/sid/'gt.jpg'
        figure=None
        if paired:
            figures=[('LQ: display enlargement only',source),('Direct (filename label)',available['direct.jpg']),('Harness (filename label)',available['harness.jpg'])]
            if gt.exists():figures.append(('HR reference: alignment NOT verified',gt))
            figure=comparison(sid,figures)
        extrafig=None
        if 'harness2.jpg' in available:
            extrafig=comparison(sid+'_extra',[('LQ',source),('Harness primary filename',available['harness.jpg']),('Harness2: round/order unknown',available['harness2.jpg']),('HR reference: alignment unverified',gt)])
        rows.append(dict(sample_id=sid,results=info,paired=paired,figure=str(figure) if figure else None,extra_figure=str(extrafig) if extrafig else None,reference=str(gt) if paired and gt.exists() else None,reference_role='cross-focal HR visual reference; not assumed aligned GT',evidence_tools=read_json(folder/'Evidence_Status.json')['planned_tools']))
    result=dict(recorded_at=now(),input_count=len(rows),completed_pairs=sum(r['paired'] for r in rows),result_files=len(found),missing_pairs=[r['sample_id'] for r in rows if not r['paired']],results=rows,images=found,scope='filename-labeled exploratory comparison, not independent Verifier or paper reproduction',round_order_confirmed=False,retry_from_original_user_confirmed_for='HC_COZ_188/harness2.jpg',actual_editor_model_confirmed=False,tool_evidence_used=False,T4_excluded=True,controller_images_imported=False,GT_usage='offline visual reference only; no registration verified; not fed into prompts, generation or candidate selection',quality_metrics_computed=[],paper_url='https://arxiv.org/html/2610.10133v2')
    write_json(OUT/'inventory.json',result)
    with (OUT/'inventory.csv').open('w',newline='',encoding='utf-8-sig') as f:
        fields=['sample_id','filename','arm_from_filename','width','height','source_width','source_height','aspect_relative_error','aspect_gate_2pct','width_scale','height_scale','sha256','provider_model','provider_round'];w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows({k:r.get(k) for k in fields} for r in found)
    print(json.dumps({'pairs':result['completed_pairs'],'result_files':len(found),'missing_pairs':result['missing_pairs'],'geometry_gate_passed':sum(x['aspect_gate_2pct'] for x in found),'geometry_gate_total':len(found),'review_figures':[r['figure'] for r in rows if r['figure']]},ensure_ascii=False))

if __name__=='__main__':collect()
