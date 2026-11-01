from copy import deepcopy
from pathlib import Path
import json
import numpy as np
import pytest
from hre.tool_retouch.color import ColorContext,encode_png16,read_png16,srgb_profile
from hre.tool_retouch.masks import prepare_mask
from hre.tool_retouch.evidence import build_pairs
from hre.tool_retouch.workflow import ToolWorkflow
from hre.tool_retouch.solver import Budget,solve
from hre.tool_retouch.verifier import hard_checks,accepted,validate_visual,target_results
from hre.tool_retouch.providers import StructuredProvider,PendingResponse
from hre.tool_retouch.cli import ResumeBackend
from .helpers import fixture,FakeBackend,FakePlanner,FakeReviewer


def test_png16_full_resolution_not_preview(tmp_path):
    x=np.linspace(.01,.99,2051*1027*3,dtype=np.float64).reshape(1027,2051,3)
    p=tmp_path/'large.png';encode_png16(p,x);y,context=ColorContext.load(p)
    assert y.shape==x.shape and context.native_size==(2051,1027) and context.source_bit_depth==16
    assert np.max(abs(x-y))<=.5/65535+1e-8
    with pytest.raises(ValueError):encode_png16(p,x)


def test_missing_icc_is_explicit(tmp_path):
    from PIL import Image
    p=tmp_path/'untagged.png';Image.new('RGB',(32,32),(90,100,110)).save(p)
    with pytest.raises(ValueError):ColorContext.load(p)
    x,c=ColorContext.load(p,True);assert c.assumption=='explicit sRGB'


def test_stable_profile_and_png_bytes(tmp_path):
    x=np.full((10,10,3),.2);encode_png16(tmp_path/'a.png',x);encode_png16(tmp_path/'b.png',x)
    assert (tmp_path/'a.png').read_bytes()==(tmp_path/'b.png').read_bytes()


def test_mask_feather_and_luminance_window():
    a=np.full((33,33,3),.5);m=np.zeros((33,33));m[:,16:]=1
    x,record=prepare_mask(m,a,feather_native=2,density=.5,luminance_range=[0,.1,.6,1])
    assert x[:,15].mean()>0 and x.max()<=.5 and record['raw_hash']!=record['effective_hash']
    with pytest.raises(ValueError):prepare_mask(m,a,luminance_range=[1,0,.5,.7])


def test_zero_support_downgraded_and_bilateral_different_sizes():
    a,b,pairs,*_=fixture();b=np.full((48,32,3),.3)
    spec={k:v for k,v in pairs[0].items() if k in ('id','a_mask','b_mask','semantic','comparability','reasons','provenance')}
    p=build_pairs(a,b,[spec],{'A':np.zeros(a.shape[:2]),'B':np.ones(b.shape[:2])})
    assert p[0]['comparability']=='not_comparable'
    p=build_pairs(a,b,[spec],{'A':np.ones(a.shape[:2]),'B':np.ones(b.shape[:2])})
    assert p[0]['supports']['a'].shape!=p[0]['supports']['b'].shape


def test_identity_returns_original_without_renderer(tmp_path):
    a,b,pairs,p,ca,cb,proposal,c,plan=fixture();b=a.copy();back=FakeBackend()
    r=ToolWorkflow(back,FakePlanner(proposal,plan),FakeReviewer(),p).run(a,b,ca,cb,pairs,{},tmp_path)
    assert r['status']=='already_satisfied' and not back.calls and r['output']=='original_A'


def test_mandatory_unmeasurable_not_accepted():
    a,b,pairs,p,ca,cb,proposal,c,plan=fixture();rows=target_results(a,c,{'face':np.zeros(a.shape[:2],bool)})
    context={'contract':c.data,'contract_sha256':c.sha256,'source_sha256':'a','reference_sha256':'b','candidate_sha256':'c'}
    v=FakeReviewer()('verify',context,{})
    assert not accepted(rows,v)


def test_plan_order_stable_despite_parameter_dict_order():
    from hre.tool_retouch.planner import coordinates
    plan={'operations':[{'tool':'balance','parameters':{'red':{},'blue':{}}}]}
    p=deepcopy(plan);p['operations'][0]['parameters']={'blue':{},'red':{}}
    assert coordinates(plan)==coordinates(p)


def test_preview_budget_one_is_terminal():
    a,b,pairs,p,ca,cb,proposal,c,plan=fixture();limits={**p['limits'],'preview':1};back=FakeBackend()
    best,ranked,trace=solve(a,plan,c,{'face':pairs[0]['supports']['a']},{},back,Budget(limits))
    assert len(back.calls)==1 and best.key=='original_A' and 'budget' in trace['stop']


def test_outside_change_hard_rejected():
    a,b,pairs,p,*_=fixture();c=a.copy();c[0,0]=.9
    assert not hard_checks(a,c,p,np.zeros(a.shape[:2],bool))['pass']


def test_file_provider_binding_and_no_external_url(tmp_path):
    provider=StructuredProvider(tmp_path,{'mode':'files'})
    with pytest.raises(PendingResponse):provider('plan',{}, {})
    request=next(tmp_path.glob('*/request.json'));response=request.parent/'response.json'
    response.write_text(json.dumps({'request_sha256':'bad','observer':'test','payload':{}}))
    with pytest.raises(ValueError):StructuredProvider(tmp_path,{'mode':'files'})('plan',{}, {})
    with pytest.raises(ValueError):StructuredProvider(tmp_path,{'mode':'local_openai','url':'https://example.com','model':'x','timeout':10})


def test_resume_caches_distinct_replay_invocation(tmp_path):
    a,b,pairs,p,ca,cb,proposal,c,plan=fixture();back=FakeBackend();back.receipts=[]
    first=ResumeBackend(back,tmp_path);x=first.render_from_source(a,plan,(0.,),{})
    first.replay(a,plan,(0.,),{},x,0);assert len(back.calls)==2
    resume=ResumeBackend(back,tmp_path);resume.render_from_source(a,plan,(0.,),{});resume.replay(a,plan,(0.,),{},x,0)
    assert len(back.calls)==2


def test_real_segmentation_artifact_import_does_not_infer_pairing(tmp_path):
    from PIL import Image
    from hre.tool_retouch.segmentation import import_harness_segments
    from hre.tool_retouch.color import digest_bytes
    source=tmp_path/'seg';source.mkdir();labels=np.ones((12,16),dtype=np.uint16)
    Image.fromarray(labels).save(source/'seg_ids.png')
    (source/'seg_summary.json').write_text(json.dumps({'reliable':True,'reason':'','classes':[{'id':1,'label':'wall'}]}))
    receipt=dict(source_sha256='a'*64,side='B',producer_version='fixture-only',ids_sha256=digest_bytes((source/'seg_ids.png').read_bytes()),summary_sha256=digest_bytes((source/'seg_summary.json').read_bytes()),observer='synthetic test')
    result=import_harness_segments(source,receipt,tmp_path/'masks')
    assert result['status']=='imported_not_paired' and result['masks']['B-1']['side']=='B'
    assert 'comparability' not in result['regions'][0]
