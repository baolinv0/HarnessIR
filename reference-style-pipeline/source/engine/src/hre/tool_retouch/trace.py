"""Append-only factual stage records, including pauses/failures and resumed attempts."""
from pathlib import Path
from datetime import datetime,timezone
import time,uuid,json
import numpy as np
from .contracts import canonical
from .color import digest_bytes
from .evidence import array_hash

def snapshot(value):
    if isinstance(value,np.ndarray):return {'pixel_sha256':array_hash(value),'shape':list(value.shape),'dtype':str(value.dtype)}
    if hasattr(value,'data') and hasattr(value,'sha256'):return {'contract_sha256':value.sha256,'contract':value.data}
    if isinstance(value,dict):return {str(k):snapshot(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [snapshot(v) for v in value]
    if isinstance(value,np.generic):return value.item()
    if isinstance(value,float) and not np.isfinite(value):return None
    if value is None or isinstance(value,(str,int,float,bool)):return value
    return {'type':type(value).__name__}

def operation_diff(previous,current):
    a={x['id']:x for x in (previous or {}).get('operations',[])};b={x['id']:x for x in current.get('operations',[])}
    return {'added':[b[k] for k in sorted(b.keys()-a.keys())],'removed':[a[k] for k in sorted(a.keys()-b.keys())],
            'modified':[{'id':k,'before':a[k],'after':b[k]} for k in sorted(a.keys()&b.keys()) if a[k]!=b[k]]}

class StageTrace:
    def __init__(self,root):
        self.root=Path(root)/'trace';self.root.mkdir(parents=True,exist_ok=True);self.attempt=uuid.uuid4().hex
    def record(self,stage,inputs,output,*,status='completed',seconds=None,source='deterministic_program',change='',impact='',image_changed=False):
        sequence=len(list(self.root.glob('*.json')))+1
        inp,out=snapshot(inputs),snapshot(output)
        row={'sequence':sequence,'attempt':self.attempt,'utc':datetime.now(timezone.utc).isoformat(),'stage':stage,'status':status,'seconds':seconds,
             'source':source,'inputs':inp,'input_sha256':digest_bytes(canonical(inp).encode()),'output':out,'output_sha256':digest_bytes(canonical(out).encode()),
             'previous_stage_sequence':sequence-1 if sequence>1 else None,'change_from_previous_stage':change,'impact_on_next_stage':impact,'image_changed':image_changed}
        with (self.root/f'{sequence:06d}.json').open('x') as f:f.write(canonical(row))
        return output
    def call(self,stage,fn,inputs,*,source='deterministic_program',change='',impact='',image_changed=False):
        start=time.monotonic()
        try:output=fn()
        except Exception as exc:
            self.record(stage,inputs,{'error':type(exc).__name__,'reason':str(exc)},status='waiting_for_response' if type(exc).__name__=='PendingResponse' else 'failed',seconds=time.monotonic()-start,source=source,change='阶段未完成；不推定新结果',impact='阻塞依赖此输出的下一阶段',image_changed=False)
            raise
        self.record(stage,inputs,output,seconds=time.monotonic()-start,source=source,change=change,impact=impact,image_changed=image_changed)
        return output

def provider_source(provider):
    if getattr(provider,'simulation',False):return 'test_double'
    config=getattr(provider,'config',{})
    return config.get('provider',config.get('model','offline_import' if config.get('mode')=='files' else type(provider).__name__))
