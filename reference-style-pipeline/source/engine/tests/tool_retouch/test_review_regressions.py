from copy import deepcopy
import pytest
from hre.tool_retouch.workflow import ToolWorkflow
from .helpers import fixture,FakeBackend,FakePlanner,FakeReviewer

@pytest.mark.parametrize('missing',['content','naturalness','protection','native'])
def test_unconfirmed_candidate_never_delivered(tmp_path,missing):
    a,b,pairs,p,ca,cb,proposal,c,plan=fixture((96,128));p['limits']['outer']=1
    class Review(FakeReviewer):
        def __call__(self,*args):
            r=super().__call__(*args)
            if missing=='protection':r['preservation_checks'][0]['status']='uncertain'
            elif missing=='native':r['native_inspected']=False
            else:r[missing]='uncertain'
            return r
    r=ToolWorkflow(FakeBackend(),FakePlanner(proposal,plan),Review(),p).run(a,b,ca,cb,pairs,{},tmp_path)
    assert r['output']=='original_A',r

@pytest.mark.parametrize('mixed',[False,True])
def test_perceptual_failure_reaches_budgeted_native_review(tmp_path,mixed):
    a,b,pairs,p,ca,cb,proposal,c,plan=fixture((96,128));b=a.copy();p['limits']['outer']=1
    target=deepcopy(proposal['targets'][0]);target.update(id='appearance',kind='perceptual',metric=None,tolerance_id=None,direction=None,description='source looks too flat; test judgment only')
    proposal['targets']=([proposal['targets'][0]] if mixed else [])+[target]
    plan['operations'][0]['target_ids']=['appearance']
    class Review(FakeReviewer):
        def __init__(self):super().__init__();self.n=0
        def __call__(self,*args):
            self.n+=1;r=super().__call__(*args)
            if self.n==1:
                for t in r['target_results']:
                    if t['id']=='appearance':t.update(status='unmet',observation='test-only perceptual difference')
            return r
    r=ToolWorkflow(FakeBackend(),FakePlanner(proposal,plan),Review(),p).run(a,b,ca,cb,pairs,{},tmp_path)
    assert r['budget']['native']>0 and r['output']!='original_A',r

@pytest.mark.parametrize('bounds',[(0.,.02),(-.02,0.),(-.001,.02)])
def test_narrow_legal_bounds_evaluate_nonidentity(bounds):
    from dataclasses import asdict
    from hre.tool_retouch.planner import validate_plan
    from hre.tool_retouch.contracts import compile_contract
    from hre.tool_retouch.evidence import extract
    from hre.tool_retouch.solver import solve,Budget
    a,b,pairs,p,ca,cb,proposal,c,plan=fixture()
    chosen=bounds[1] if bounds[1]>0 else bounds[0];b=a*2**chosen;p['tolerances']['Y']=.000001
    c=compile_contract(proposal,extract(a,b,pairs),pairs,asdict(ca),asdict(cb),p)
    plan['operations'][0]['parameters']['ev'].update(lower=bounds[0],upper=bounds[1],suggested=chosen,min_step=.015625)
    validate_plan(plan,c.data,{})
    best,ranked,trace=solve(a,plan,c,{'face':pairs[0]['supports']['a']},{},FakeBackend(),Budget(p['limits']))
    assert trace['preview_renders']>1 and best.values!=(0.,),trace

def test_unused_mask_does_not_change_global_acceptance(tmp_path):
    import numpy as np
    a,b,pairs,p,ca,cb,proposal,c,plan=fixture((96,128));a[:,:64]=.2;a[:,64:]=.6;b=a*1.2;p['limits']['outer']=1
    mask=np.zeros(a.shape[:2]);mask[:,64:]=1
    results=[]
    for name,masks in [('none',{}),('unused',{'unused':mask})]:
        results.append(ToolWorkflow(FakeBackend(),FakePlanner(proposal,plan),FakeReviewer(),p).run(a,b,ca,cb,pairs,masks,tmp_path/name))
    assert results[0]['status']==results[1]['status']=='accepted',[(r['status'],r.get('reason')) for r in results]

@pytest.mark.parametrize('fault',['export','replay'])
def test_delivery_failure_has_specific_evidence(tmp_path,fault):
    import json
    class Broken(FakeBackend):
        def export_native(self,path,image):
            image=image.copy()
            if fault=='export':image[:10]=1.
            return super().export_native(path,image)
        def replay(self,*args):
            if fault=='replay':return {'pass':False,'max_error':.2,'tolerance':0.,'pixel_sha256':'observed-test-hash'}
            return super().replay(*args)
    a,b,pairs,p,ca,cb,proposal,c,plan=fixture((96,128));p['limits']['outer']=1
    r=ToolWorkflow(Broken(),FakePlanner(proposal,plan),FakeReviewer(),p).run(a,b,ca,cb,pairs,{},tmp_path)
    rows=[json.loads(x.read_text()) for x in (tmp_path/'trace').glob('*.json')]
    if fault=='export':assert any(x['stage']=='exported_native_acceptance' and x['output']['checks']['pass'] is False for x in rows)
    else:assert any(x['stage']=='replay' and x['output'].get('max_error')==.2 for x in rows)

def test_active_masks_exclude_identity_and_unused():
    import numpy as np
    from hre.tool_retouch.verifier import active_local_masks
    a,b,pairs,p,ca,cb,proposal,c,plan=fixture();plan['operations'][0]['mask_id']='used'
    masks={'used':np.ones(a.shape[:2]),'unused':np.zeros(a.shape[:2])}
    assert active_local_masks(plan,(0.,),masks)=={}
    assert set(active_local_masks(plan,(.25,),masks))=={'used'}

def test_actual_local_step_detected_without_penalizing_existing_edge_gain():
    import numpy as np
    from hre.tool_retouch.verifier import native_checks
    from hre.tool_retouch.color import linearize,encode_srgb
    a,b,pairs,p,ca,cb,proposal,c,plan=fixture((64,64))
    mask=np.zeros(a.shape[:2]);mask[:,32:]=1
    flat=np.full_like(a,.3);halo=flat.copy();halo[:,32:]=.7
    checks=native_checks(flat,halo,p,np.ones(mask.shape,bool),{'used':mask})
    assert not checks['pass'] and checks['edge_jump']>p['max_edge_jump']
    ramp=np.broadcast_to(np.linspace(.1,.5,64)[None,:,None],a.shape).copy();ramp[:,32:]+=.15
    toned=encode_srgb(linearize(ramp)*1.15)
    checks=native_checks(ramp,toned,p,np.ones(mask.shape,bool),{'used':mask})
    assert checks['edge_jump']<1e-6,checks

def test_unassigned_perceptual_goal_is_explicitly_unsupported(tmp_path):
    a,b,pairs,p,ca,cb,proposal,c,plan=fixture();b=a.copy();p['limits']['outer']=1
    proposal['targets'][0].update(kind='perceptual',metric=None,tolerance_id=None,direction=None)
    plan['operations']=[]
    class Review(FakeReviewer):
        def __call__(self,*args):
            r=super().__call__(*args);r['target_results'][0]['status']='unmet';return r
    r=ToolWorkflow(FakeBackend(),FakePlanner(proposal,plan),Review(),p).run(a,b,ca,cb,pairs,{},tmp_path)
    assert r['unsupported_targets'][0]['id']=='tone' and 'unsupported' in r['reason'] and r['output']=='original_A'

@pytest.mark.parametrize('unsafe_middle',[False,True])
def test_visual_recovery_to_original_is_not_an_improvement(tmp_path,unsafe_middle):
    a,b,pairs,p,ca,cb,proposal,c,plan=fixture();b=a.copy();p['limits'].update(outer=2,native=2,replay=2)
    proposal['targets'][0].update(kind='perceptual',metric=None,tolerance_id=None,direction=None)
    class Planner(FakePlanner):
        def __call__(self,stage,context,images):
            r=super().__call__(stage,context,images)
            if stage=='plan':r['feedback_ids']=[f['id'] for f in context['feedback']]
            return r
    class Review(FakeReviewer):
        def __init__(self):super().__init__();self.calls=0
        def __call__(self,*args):
            r=super().__call__(*args);self.calls+=1
            r['target_results'][0]['status']='unmet' if self.calls==2 else 'partial'
            if self.calls==2 and unsafe_middle:r['content']='uncertain'
            return r
    review=Review()
    r=ToolWorkflow(FakeBackend(),Planner(proposal,plan),review,p).run(a,b,ca,cb,pairs,{},tmp_path)
    assert review.calls==3,r
    assert r['output']=='original_A' and r['status']=='no_safe_improvement',r

def test_unsafe_candidate_cannot_lower_existing_best_safe_anchor(tmp_path):
    a,b,pairs,p,ca,cb,proposal,c,plan=fixture();b=a.copy();p['limits']['outer']=2
    proposal['targets'][0].update(kind='perceptual',metric=None,tolerance_id=None,direction=None)
    class Planner(FakePlanner):
        def __call__(self,stage,context,images):
            r=super().__call__(stage,context,images)
            if stage=='plan':r['feedback_ids']=[f['id'] for f in context['feedback']]
            return r
    class Review(FakeReviewer):
        def __init__(self):super().__init__();self.calls=0
        def __call__(self,*args):
            r=super().__call__(*args);self.calls+=1
            r['target_results'][0]['status']={1:'unmet',2:'partial',3:'unmet',4:'partial'}[self.calls]
            if self.calls==3:r['content']='uncertain'
            return r
    review=Review();r=ToolWorkflow(FakeBackend(),Planner(proposal,plan),review,p).run(a,b,ca,cb,pairs,{},tmp_path)
    assert review.calls==4 and r['status']=='improved_incomplete',r
    assert r['output']=='candidate-1-1.png',r

def test_single_round_unsafe_uncertain_then_unmet_cannot_beat_partial_original(tmp_path):
    a,b,pairs,p,ca,cb,proposal,c,plan=fixture();b=a.copy();p['limits'].update(outer=1,native=2,replay=2)
    proposal['targets'][0].update(kind='perceptual',metric=None,tolerance_id=None,direction=None)
    class Review(FakeReviewer):
        def __init__(self):super().__init__();self.calls=0
        def __call__(self,*args):
            r=super().__call__(*args);self.calls+=1
            r['target_results'][0]['status']={1:'partial',2:'uncertain',3:'unmet'}[self.calls]
            if self.calls==2:r['content']='fail'
            return r
    review=Review();r=ToolWorkflow(FakeBackend(),FakePlanner(proposal,plan),review,p).run(a,b,ca,cb,pairs,{},tmp_path)
    assert review.calls==3 and r['output']=='original_A' and r['status']=='no_safe_improvement',r

def test_unknown_best_safe_effect_is_not_a_lower_perceptual_rank(tmp_path):
    a,b,pairs,p,ca,cb,proposal,c,plan=fixture();p['limits'].update(outer=2,native=2,replay=2)
    target=deepcopy(proposal['targets'][0]);target.update(id='appearance',kind='perceptual',metric=None,tolerance_id=None,direction=None)
    proposal['targets'].append(target)
    class Planner(FakePlanner):
        def __call__(self,stage,context,images):
            r=super().__call__(stage,context,images)
            if stage=='plan':r['feedback_ids']=[f['id'] for f in context['feedback']]
            return r
    class Review(FakeReviewer):
        def __init__(self):super().__init__();self.calls=0
        def __call__(self,*args):
            r=super().__call__(*args);self.calls+=1
            for t in r['target_results']:
                if t['id']=='appearance':t['status']='uncertain' if self.calls==1 else 'unmet'
            return r
    review=Review();r=ToolWorkflow(FakeBackend(),Planner(proposal,plan),review,p).run(a,b,ca,cb,pairs,{},tmp_path)
    assert review.calls==2 and r['status']=='improved_incomplete',r
    assert r['output']=='candidate-1-1.png',r

def test_original_unknown_becoming_unmet_is_recorded_not_quality_progress(tmp_path):
    import json
    a,b,pairs,p,ca,cb,proposal,c,plan=fixture();b=a.copy();p['limits'].update(outer=1,native=1,replay=1)
    proposal['targets'][0].update(kind='perceptual',metric=None,tolerance_id=None,direction=None)
    trigger=deepcopy(proposal['targets'][0]);trigger['id']='known_unmet';proposal['targets'].append(trigger)
    plan['operations'][0]['target_ids']=['known_unmet']
    class Review(FakeReviewer):
        def __init__(self):super().__init__();self.calls=0
        def __call__(self,*args):
            r=super().__call__(*args);self.calls+=1
            for t in r['target_results']:
                t['status']='uncertain' if self.calls==1 and t['id']=='tone' else 'unmet'
            return r
    review=Review();r=ToolWorkflow(FakeBackend(),FakePlanner(proposal,plan),review,p).run(a,b,ca,cb,pairs,{},tmp_path)
    assert review.calls==2 and r['output']=='original_A' and r['status']=='no_safe_improvement',r
    comparisons=[json.loads(x.read_text())['output'] for x in (tmp_path/'trace').glob('*.json') if json.loads(x.read_text())['stage']=='perceptual_comparison']
    assert len(comparisons)==1 and comparisons[0]['quality_improved'] is False
    assert comparisons[0]['unknown_resolutions']==[{'id':'tone','from':'uncertain','to':'unmet'}]
