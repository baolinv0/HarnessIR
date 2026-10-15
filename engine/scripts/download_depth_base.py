"""Explicit official author checkpoint download, immutable revision + hash."""
import json
from pathlib import Path
import sys
import urllib.request

root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root))
from preprocessing.prepare_models import download, write_json

model='depth-anything/Depth-Anything-V2-Base'
with urllib.request.urlopen('https://huggingface.co/api/models/'+model,timeout=40) as response:
    metadata=json.load(response)
revision=metadata['sha']
if metadata['id']!=model or len(revision)!=40:raise ValueError('Official model/revision identity mismatch')
out=root/'models/depth_anything_v2_base'
receipt=download('https://huggingface.co/'+model+'/resolve/'+revision+'/depth_anything_v2_vitb.pth',out/'depth_anything_v2_vitb.pth')
write_json(out/'source_lock.json',{'official_repo':model,'weight_revision':revision,'weight':receipt,'model_name':'Depth-Anything-V2-Base','encoder':'vitb','depth_kind':'relative'})
print(json.dumps({'status':'downloaded_not_inferred','revision':revision,'sha256':receipt['sha256'],'bytes':(out/'depth_anything_v2_vitb.pth').stat().st_size}))
