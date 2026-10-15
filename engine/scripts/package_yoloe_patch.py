"""Whitelist the authorized alternative code/assets; never credentials or GT."""
import json
from pathlib import Path
import tarfile
import hashlib

ROOT=Path(__file__).resolve().parents[2]
out=ROOT/'runtime/alternatives/yoloe26l/code_and_assets.tar'
out.parent.mkdir(parents=True,exist_ok=True)
files=list((ROOT/'engine/src/hir_manual').glob('*.py'))
files.extend(ROOT/'engine/scripts'/name for name in ['run_remote_batch.py','scan_offline_cache.py','freeze_remote_export.py','render_remote_pilot.py','prepare_yoloe_alternative.py'])
files.extend(p for p in (ROOT/'preprocessing').rglob('*.py') if 'environments' not in p.parts and '__pycache__' not in p.parts)
files.extend(ROOT/p for p in ['preprocessing/configs/gpu_yoloe26l.json','preprocessing/registry/gpu_yoloe26l_v1.json','models/yoloe_26l_seg/yoloe-26l-seg.pt','models/yoloe_26l_seg/source_lock.json','models/yoloe_26n_seg/mobileclip2_b.ts'])
clip=ROOT/'models/yoloe_26n_seg/clip_source/CLIP-7ffa84b3bfa40c42ecc1c77147a855e69cb2dd40'
files.extend(p for p in clip.rglob('*') if p.is_file() and not any(x in p.parts for x in ['__pycache__','build','.git']))
files=sorted(set(files))
temporary=out.with_suffix('.tar.tmp')
with tarfile.open(temporary,'w') as archive:
    for path in files:
        if not path.is_relative_to(ROOT) or path.name=='gpu_password.txt' or 'Data' in path.relative_to(ROOT).parts:
            raise ValueError('Unexpected non-whitelisted deployment source')
        archive.add(path,arcname=path.relative_to(ROOT).as_posix(),recursive=False)
temporary.replace(out)
with out.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
receipt={'path':str(out),'sha256':sha,'bytes':out.stat().st_size,'file_count':len(files),'credentials_included':False,'GT_included':False}
(out.parent/'package_receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
print(json.dumps(receipt))
