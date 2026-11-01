"""Explicit test doubles, deliberately not production fallbacks or PhotoCraft claims."""
from copy import deepcopy
from dataclasses import asdict
import numpy as np
from hre.tool_retouch.color import ColorContext,encode_png16,read_png16
from hre.tool_retouch.evidence import build_pairs,extract
from hre.tool_retouch.contracts import compile_contract
from hre.tool_retouch.workflow import DEFAULT_POLICY
from hre.tool_retouch.planner import instantiate,TOOLS
from hre.tool_retouch.backend import PhotoCraftAdapter

class FakeBackend:
    simulation=True
    identity={'backend':'TEST_DOUBLE','domain':'display RGB multiply, NOT PhotoCraft'}
    def __init__(self):self.calls=[]
    def render_from_source(self,a,plan,values,masks):
        self.calls.append((a.copy(),values));x=a.copy()
        for op in instantiate(plan,values):
            assert op['tool']=='exposure'
            mask=masks[op['mask_id']][...,None] if op['mask_id'] else 1.
            x=x+mask*(np.clip(x*2**op['values']['ev'],0,1)-x)
        return x
    export_native=PhotoCraftAdapter.export_native
    replay=PhotoCraftAdapter.replay

def fixture(shape=(24,24)):
    x=np.linspace(.15,.3,shape[1])[None,:,None];a=np.broadcast_to(x,(*shape,3)).copy();b=a*1.2
    masks={'A':np.ones(shape),'B':np.ones(shape)}
    pairs=build_pairs(a,b,[dict(id='face',a_mask='A',b_mask='B',semantic='synthetic patch',comparability='comparable',reasons=['synthetic identical support'],provenance='automatic')],masks)
    policy=deepcopy(DEFAULT_POLICY);policy['preview_side']=64;policy['tolerances']={'Y':.002}
    context=ColorContext('a'*64,(shape[1],shape[0]),16,'f'*64,None,1)
    ref=ColorContext('b'*64,(shape[1],shape[0]),16,'f'*64,None,1)
    proposal={'targets':[dict(id='tone',kind='interval',regions=['face'],metric='Y_linear.P50',evidence_ids=['a:face:Y_linear.P50','b:face:Y_linear.P50'],tolerance_id='Y',mandatory=True,direction=None,description='synthetic brightness')], 'protected_properties':['geometry','identity'],'exclusions':[],'uncertainties':[]}
    contract=compile_contract(proposal,extract(a,b,pairs),pairs,asdict(context),asdict(ref),policy)
    plan=dict(operations=[dict(id='o1',tool='exposure',target_ids=['tone'],mask_id=None,parameters={'ev':{'lower':-1.,'upper':1.,'suggested':.9,'min_step':.015625}},expected_effect='raise middle tones',protect_target_ids=[])],reason='synthetic example',feedback_ids=[])
    return a,b,pairs,policy,context,ref,proposal,contract,plan

class FakePlanner:
    simulation=True
    def __init__(self,proposal,plan):self.proposal=proposal;self.plan=plan
    def __call__(self,stage,context,images):return deepcopy(self.proposal if stage=='contract' else self.plan)

class FakeReviewer:
    simulation=True
    def __init__(self,status='pass',omit=False):self.status=status;self.omit=omit
    def __call__(self,stage,context,images):
        result={k:context[k] for k in ('contract_sha256','source_sha256','reference_sha256','candidate_sha256')}
        result.update(observer='TEST_DOUBLE no real visual review',target_results=[{'id':t['id'],'status':'achieved','observation':'synthetic fixture'} for t in context['contract']['targets']],content=self.status,naturalness='pass',reference_match='pass',native_inspected=True,notes='TEST DOUBLE',preservation_checks=[{'item':p,'status':self.status,'observation':'TEST DOUBLE'} for p in context['contract']['protected_properties']])
        if self.omit:result['target_results']=[]
        return result
