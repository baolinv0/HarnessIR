"""Generate unambiguously synthetic input/audit configuration; never executes a backend."""
from pathlib import Path
from copy import deepcopy
import argparse,json
import numpy as np
from hre.tool_retouch.color import encode_png16,digest_bytes
from hre.tool_retouch.workflow import DEFAULT_POLICY

p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);args=p.parse_args()
args.out.mkdir(parents=True,exist_ok=False);root=args.out
x=np.linspace(.08,.55,256);a=np.broadcast_to(x[None,:,None],(192,256,3)).copy();b=a*1.12
encode_png16(root/'A.png',a);encode_png16(root/'B.png',b)
for role in ('A','B'):np.save(root/(role+'-mask.npy'),np.ones(a.shape[:2]),allow_pickle=False)
hashfile=lambda name:digest_bytes((root/name).read_bytes())
policy=deepcopy(DEFAULT_POLICY);policy['tolerances']={'synthetic_Y_only':.003}
config={'case_id':'SYNTHETIC-only','source':{'path':'A.png','sha256':hashfile('A.png'),'assume_srgb':False},'reference':{'path':'B.png','sha256':hashfile('B.png'),'assume_srgb':False},
 'masks':{role:{'path':role+'-mask.npy','sha256':hashfile(role+'-mask.npy'),'side':role,'producer':'synthetic fixture','producer_version':'1'} for role in ('A','B')},
 'regions':[{'id':'patch','a_mask':'A','b_mask':'B','semantic':'synthetic color ramp','comparability':'comparable','reasons':['synthetic identical support; not real scene evidence'],'provenance':'automatic'}],
 'edit_masks':{'patch_edit':{'source_mask':'A','feather_native':2.,'density':1.,'luminance_range':None}},'support_policy':{'edge':1,'min_pixels':32,'min_coverage':.4},'policy':policy,
 'backend':{'executable':'/path/to/approved/harnessir-photocraft-worker','sha256':'REPLACE_WITH_BUILT_BINARY_SHA256','timeout':120},
 'planner':{'mode':'files'},'reviewer':{'mode':'files'},
 'provenance':{'source_chain':'synthetic sRGB ramp','reference_chain':'synthetic display RGB multiplier 1.12','capture_interval_seconds':None,'limitations':['not photographed','not S26 prediction/iPhone experiment'],'split':'development'}}
(root/'config.json').write_text(json.dumps(config,indent=2),encoding='utf8')
print(root/'config.json')
