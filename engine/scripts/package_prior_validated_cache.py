"""Transfer only strictly validated original GPU pilot caches, preserving provenance."""
import json
import tarfile
import hashlib
from pathlib import Path
from hir_manual.cache import EvidenceCache, make_cache_key

root=Path(__file__).resolve().parents[2]
ledger=json.loads((root/'runtime/offline_exports/export_98bbbe1252e34e8e8650e7580675a55b/expected.json').read_text(encoding='utf-8'))
cache=EvidenceCache(root/'Data/annotations/cache')
selected=[]
for entry in ledger['entries']:
    contract=entry['contract']
    path=cache.lookup(contract)
    if path is not None:
        selected.append((entry,path))
if len(selected)!=15:raise ValueError('Expected exactly the previously validated 15 real GPU records')
out=root/'runtime/alternatives/yoloe26l/prior_validated_cache.tar'
receipt=[]
with tarfile.open(out.with_suffix('.tar.tmp'),'w') as t:
    for entry,path in selected:
        receipt.append({'image_id':entry['image_id'],'tool_id':entry['contract']['tool_id'],'cache_key':make_cache_key(entry['contract'])})
        for file in path.rglob('*'):
            if file.is_file():
                if file.is_symlink() or not file.resolve().is_relative_to(path):raise ValueError('Unsafe cache member')
                t.add(file,arcname=file.relative_to(root).as_posix(),recursive=False)
out.with_suffix('.tar.tmp').replace(out)
with out.open('rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
data={'entries':receipt,'count':len(receipt),'sha256':sha,'bytes':out.stat().st_size,'credentials_included':False,'GT_included':False,'source_ledger':ledger['bundle_id']}
(out.parent/'prior_cache_transfer.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
print(json.dumps({'count':len(receipt),'bytes':out.stat().st_size,'sha256':sha}))
