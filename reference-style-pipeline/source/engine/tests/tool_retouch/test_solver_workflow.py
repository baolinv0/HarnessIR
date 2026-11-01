from copy import deepcopy
import numpy as np
import pytest
from hre.tool_retouch.solver import Budget,solve
from hre.tool_retouch.workflow import ToolWorkflow
from hre.tool_retouch.planner import validate_plan
from hre.tool_retouch.contracts import compile_contract
from hre.tool_retouch.evidence import extract
from .helpers import fixture,FakeBackend,FakePlanner,FakeReviewer


def test_search_determinism_budget_and_original():
    a,b,pairs,policy,ca,cb,proposal,c,plan=fixture()
    support={'face':pairs[0]['supports']['a']};answers=[]
    for _ in range(2):
        back=FakeBackend();budget=Budget(policy['limits']);best,ranked,trace=solve(a,plan,c,support,{},back,budget)
        assert 0<len(back.calls)<=40 and budget.used['preview']==len(back.calls)
        assert all(np.array_equal(original,a) for original,_ in back.calls)
        assert best.loss<trace['baseline_loss'];answers.append(best.values)
    assert answers[0]==answers[1]


def test_cache_binds_masks_and_plan():
    a,b,pairs,p,*rest=fixture();c,plan=rest[-2:];support={'face':pairs[0]['supports']['a']};cache={};back=FakeBackend()
    solve(a,plan,c,support,{},back,Budget(p['limits']),cache);n=len(back.calls)
    solve(a,plan,c,support,{},back,Budget(p['limits']),cache);assert len(back.calls)==n
    plan=deepcopy(plan);plan['operations'][0]['mask_id']='m'
    solve(a,plan,c,support,{'m':np.ones(a.shape[:2])},back,Budget(p['limits']),cache);assert len(back.calls)>n


def test_workflow_native_and_frozen(tmp_path):
    a,b,pairs,p,ca,cb,proposal,c,plan=fixture((96,128));back=FakeBackend()
    result=ToolWorkflow(back,FakePlanner(proposal,plan),FakeReviewer(),p).run(a,b,ca,cb,pairs,{},tmp_path)
    assert result['status']=='accepted',result
    assert result['simulation'] and not result['real_effect_validated']
    assert result['budget']['native']==1 and result['budget']['replay']==1
    assert result['delivery']['native_checks']['pass']
    assert (tmp_path/result['output']).exists() and (tmp_path/'contract.json').exists()
    assert back.calls[-1][0].shape==a.shape


@pytest.mark.parametrize('reviewer',[FakeReviewer('fail'),FakeReviewer(omit=True)])
def test_visual_hard_fail_or_missing_target_never_passes(tmp_path,reviewer):
    a,b,pairs,p,ca,cb,proposal,c,plan=fixture()
    result=ToolWorkflow(FakeBackend(),FakePlanner(proposal,plan),reviewer,p).run(a,b,ca,cb,pairs,{},tmp_path)
    assert not result['success'] and result['output']=='original_A'


def test_backend_exception_falls_back(tmp_path):
    class Broken(FakeBackend):
        def render_from_source(self,*args):raise OSError('worker crashed')
    a,b,pairs,p,ca,cb,proposal,c,plan=fixture()
    r=ToolWorkflow(Broken(),FakePlanner(proposal,plan),FakeReviewer(),p).run(a,b,ca,cb,pairs,{},tmp_path)
    assert r['status']=='execution_failed' and r['output']=='original_A'


def test_partial_interval_rejected():
    a,b,pairs,p,ca,cb,proposal,c,plan=fixture();pairs[0]['comparability']='partially_comparable'
    with pytest.raises(ValueError):compile_contract(proposal,extract(a,b,pairs),pairs,{}, {},p)


def test_unknown_key_nan_bounds():
    a,b,pairs,p,ca,cb,proposal,c,plan=fixture()
    for value in [float('nan'),2.,True]:
        bad=deepcopy(plan);bad['operations'][0]['parameters']['ev']['suggested']=value
        with pytest.raises(ValueError):validate_plan(bad,c.data,{})
    bad=deepcopy(plan);bad['operations'][0]['shell']='id'
    with pytest.raises(ValueError):validate_plan(bad,c.data,{})


def test_native_damage_rejected(tmp_path):
    class NativeDamage(FakeBackend):
        def render_from_source(self,a,*args):
            result=super().render_from_source(a,*args)
            return result[::2] if a.shape[0]>64 else result
    a,b,pairs,p,ca,cb,proposal,c,plan=fixture((128,128))
    r=ToolWorkflow(NativeDamage(),FakePlanner(proposal,plan),FakeReviewer(),p).run(a,b,ca,cb,pairs,{},tmp_path)
    assert not r['success'] and r['output']=='original_A'
