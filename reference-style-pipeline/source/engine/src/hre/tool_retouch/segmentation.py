"""Import real existing HarnessIR SAM3 artifacts without loading/downloading weights.

harness.perception.segment.run_segment produces seg_ids.png + seg_summary.json.
That producer merges semantic instances; matching class names NEVER establishes
that they are the same comparable instance under similar illumination.
"""
from pathlib import Path
import numpy as np
from PIL import Image
from ..storage import read_json,write_json
from .color import require,digest_bytes
from .contracts import strict


def import_harness_segments(directory,receipt,out):
    """Require an attributed source-bound receipt in addition to legacy outputs.

    Legacy segmentation files alone do not prove which A/B generated them. The
    orchestrator must supply the real producer/version and original image hash.
    This API never guesses those facts from the directory or label vocabulary.
    """
    directory=Path(directory);out=Path(out)
    strict(receipt,{'source_sha256','side','producer_version','ids_sha256','summary_sha256','observer'})
    require(receipt['side'] in ('A','B') and receipt['producer_version'] and receipt['observer'],'segment receipt attribution')
    for key in ('source_sha256','ids_sha256','summary_sha256'):
        require(isinstance(receipt[key],str) and len(receipt[key])==64 and all(c in '0123456789abcdef' for c in receipt[key]),'segment receipt hashes')
    ids_path=directory/'seg_ids.png';summary_path=directory/'seg_summary.json'
    require(digest_bytes(ids_path.read_bytes())==receipt['ids_sha256'] and digest_bytes(summary_path.read_bytes())==receipt['summary_sha256'],'segment artifact hash mismatch')
    summary=read_json(summary_path);require(summary.get('reliable') is True and summary.get('classes'),'segmentation unavailable/unreliable')
    with Image.open(ids_path) as im:
        require(im.mode in ('I;16','I;16B','I'),'expected real 16-bit label raster')
        labels=np.asarray(im).copy()
    require(labels.ndim==2 and labels.size>0 and labels.size<=50_000_000,'label dimensions')
    require(not out.exists(),'mask import output must be new');out.mkdir(parents=True)
    masks={};regions=[];seen=set()
    for row in summary['classes']:
        require(type(row['id']) is int and row['id']>0 and row['id'] not in seen and isinstance(row['label'],str) and row['label'],'segment class identity')
        seen.add(row['id']);mask=(labels==row['id']).astype(np.float64)
        require(mask.any(),'summary class absent from label map')
        name=f'{receipt["side"]}-{row["id"]}';path=out/(name+'.npy');np.save(path,mask,allow_pickle=False)
        masks[name]={'path':path.name,'sha256':digest_bytes(path.read_bytes()),'side':receipt['side'],'producer':'harness.perception.segment.run_segment','producer_version':receipt['producer_version']}
        regions.append({'mask_id':name,'semantic':row['label'],'pixels':int(mask.sum()),'instance_limit':'producer merges class instances; comparability requires separate assessment'})
    result={'receipt':receipt,'masks':masks,'regions':regions,'status':'imported_not_paired'}
    write_json(out/'segmentation_import.json',result);return result


def schedule_bilateral(source_specs, config, base, cache, runner=None, allow_unpaired=False):
    """Sequential A/B SAM3 dispatch with per-side immutable content-addressed cache.

    runner injection is for tests only. The production runner invokes the existing
    HarnessIR run_segment interface in an isolated CPU subprocess with timeout.
    Failed/uncertain calls are recorded and never silently retried in the same cache.
    """
    import json, sys, subprocess, os, importlib.metadata
    from dataclasses import asdict
    from .color import ColorContext
    from .contracts import canonical, number
    from ..storage import case_lock
    strict(config,{'checkpoint','checkpoint_sha256','labels','conf','iou','imgsz','timeout','producer_version','regions'})
    require(isinstance(config['labels'],list) and 1<=len(config['labels'])<=32 and all(isinstance(x,str) and x.strip() for x in config['labels']) and len(set(config['labels']))==len(config['labels']),'unique segmentation vocabulary')
    require(all(number(config[k]) and 0<config[k]<=1 for k in ('conf','iou')),'segmentation thresholds')
    require(type(config['imgsz']) is int and 32<=config['imgsz']<=2048 and number(config['timeout']) and 0<config['timeout']<=600,'segmentation size/timeout')
    require(isinstance(config['producer_version'],str) and config['producer_version'],'pin actual ultralytics version')
    base=Path(base);cache=Path(cache);cache.mkdir(parents=True,exist_ok=True)
    checkpoint=(base/config['checkpoint']).resolve()
    require(checkpoint.is_file(),'SAM3 checkpoint unavailable; no download attempted')
    # Stream large weights rather than materializing a multi-GB file twice.
    import hashlib
    h=hashlib.sha256()
    with checkpoint.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    require(h.hexdigest()==config['checkpoint_sha256'],'SAM3 checkpoint hash mismatch')
    implementation=Path(__file__).resolve().parents[4]/'harness/perception/segment.py'
    model_impl=implementation.parent/'_models.py'
    require(implementation.is_file() and model_impl.is_file(),'existing HarnessIR SAM3 source unavailable')
    code_hash={p.name:digest_bytes(p.read_bytes()) for p in (implementation,model_impl,Path(__file__).with_name('sam3_worker.py'),Path(__file__))}
    if runner is None:
        require(importlib.metadata.version('ultralytics')==config['producer_version'],'SAM3 installed version mismatch')
    masks={};catalog={};receipts={}
    with case_lock(cache):
        for side,role in [('A','source'),('B','reference')]:
            spec=source_specs[role];path=(base/spec['path']).resolve()
            require(digest_bytes(path.read_bytes())==spec['sha256'],'segmentation source hash mismatch')
            pixels,color=ColorContext.load(path,spec['assume_srgb'])
            binding={'side':side,'source_sha256':spec['sha256'],'color':asdict(color),'checkpoint_sha256':config['checkpoint_sha256'],
                     'labels':config['labels'],'conf':config['conf'],'iou':config['iou'],'imgsz':config['imgsz'],
                     'producer_version':config['producer_version'],'source_code':code_hash,'device':'cpu','input_domain':'canonical_sRGB_RGB8_quantized_for_segmentation_only',
                     'simulation':runner is not None}
            binding=json.loads(canonical(binding))
            key=digest_bytes(canonical(binding).encode());job=cache/key;job.mkdir(exist_ok=True);state=job/'state.json'
            if state.exists():
                row=read_json(state)
                require(row['binding']==json.loads(canonical(binding)),'segmentation cache binding changed')
                require(row['status']=='completed','segmentation prior failure/uncertain outcome; inspect state and use explicit new cache')
            else:
                write_json(state,{'status':'running','binding':binding})
                try:
                    image=Image.fromarray(np.rint(pixels*255).astype(np.uint8));image.save(job/'input.png')
                    request={k:config[k] for k in ('labels','conf','iou','imgsz','producer_version')};request['checkpoint']=str(checkpoint)
                    write_json(job/'request.json',request)
                    if runner is not None:runner(image,job,request)
                    else:
                        env=os.environ.copy();env.update(TOOL_DEVICE='cpu',CUDA_VISIBLE_DEVICES='',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',OMP_NUM_THREADS='1')
                        # Path is fixed package code, never a model-proposed command.
                        completed=subprocess.run([sys.executable,'-m','hre.tool_retouch.sam3_worker',str(job.resolve())],env=env,capture_output=True,text=True,timeout=config['timeout'])
                        (job/'worker.log').write_text(completed.stdout+'\n'+completed.stderr)
                        require(completed.returncode==0,'SAM3 worker failed; inspect worker.log')
                    receipt={'source_sha256':spec['sha256'],'side':side,'producer_version':config['producer_version'],
                             'ids_sha256':digest_bytes((job/'seg_ids.png').read_bytes()),'summary_sha256':digest_bytes((job/'seg_summary.json').read_bytes()),
                             'observer':'synthetic injected runner' if runner else 'HarnessIR local SAM3 CPU worker'}
                    with Image.open(job/'seg_ids.png') as im:require(im.size==(pixels.shape[1],pixels.shape[0]),'SAM3 output dimensions changed')
                    imported=import_harness_segments(job,receipt,job/'masks')
                    row={'status':'completed','binding':binding,'receipt':receipt,'imported':imported};write_json(state,row)
                except Exception as exc:
                    write_json(state,{'status':'failed','binding':binding,'reason':type(exc).__name__+': '+str(exc)})
                    raise
            require(digest_bytes((job/'seg_ids.png').read_bytes())==row['receipt']['ids_sha256'] and digest_bytes((job/'seg_summary.json').read_bytes())==row['receipt']['summary_sha256'],'cached SAM3 artifacts modified')
            receipts[side]={'key':key,'receipt':row['receipt'],'binding':row['binding']}
            for region in row['imported']['regions']:
                name=region['mask_id'];label=region['semantic'];mask_spec=row['imported']['masks'][name]
                mask_path=job/'masks'/mask_spec['path'];require(digest_bytes(mask_path.read_bytes())==mask_spec['sha256'],'cached mask modified')
                require((side,label) not in catalog,'ambiguous duplicate class label')
                catalog[side,label]=name;masks[name]={**mask_spec,'path':str(mask_path.resolve())}
        regions=[]
        for r in config['regions']:
            strict(r,{'id','a_label','b_label','semantic','comparability','reasons'})
            require(( 'A',r['a_label']) in catalog and ('B',r['b_label']) in catalog,'requested semantic region absent on one side')
            require(r['comparability'] in ('comparable','partially_comparable','not_comparable') and isinstance(r['reasons'],list) and r['reasons'],'explicit correspondence assessment required; equal label alone is insufficient')
            regions.append({'id':r['id'],'a_mask':catalog['A',r['a_label']],'b_mask':catalog['B',r['b_label']],
                            'semantic':r['semantic'],'comparability':r['comparability'],'reasons':r['reasons'],'provenance':'automatic'})
        require((allow_unpaired and not regions) or 1<=len(regions)<=6,'need 1..6 assessed bilateral region pairs')
        result={'masks':masks,'regions':regions,'catalog':[{'side':side,'label':label,'mask_id':name} for (side,label),name in catalog.items()],'receipts':receipts,'simulation':runner is not None}
        write_json(cache/'bilateral.json',result);return result
