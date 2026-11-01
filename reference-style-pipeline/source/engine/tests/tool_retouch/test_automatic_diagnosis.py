from copy import deepcopy
import pytest
from hre.tool_retouch.diagnosis import prepare_automatic,validate_correspondence,validate_measured_diagnosis,DIMENSIONS
from hre.tool_retouch.evidence import extract
from hre.tool_retouch.contracts import compile_contract
from hre.tool_retouch.workflow import ToolWorkflow
from hre.tool_retouch.providers import PendingResponse
from hre.tool_retouch.cli import dispatch
from hre.storage import write_json
from argparse import Namespace
from .test_segmentation_dispatch import config,Runner
from .helpers import fixture,FakeBackend,FakeReviewer

class Semantic:
    simulation=True
    def __init__(self):self.stages=[]
    def __call__(self,stage,context,images):
        self.stages.append(stage)
        if stage=='discover_regions':
            assert 'labels' not in context and 'A' in images and 'B' in images
            return dict(labels=['wall'],source_observations=['source content'],reference_observations=['appearance only'],protected_properties=['geometry','identity'],uncertainties=[])
        assert 'mask A-1' in images and 'mask B-1' in images and context['catalog']
        return dict(regions=[dict(id='face',a_mask='A-1',b_mask='B-1',semantic='synthetic patch',comparability='comparable',reasons=['synthetic same instance'])],uncertainties=[])

def diagnosis(obs):
    return dict(deltas=[dict(id='d1',dimension='shadow_midtone_highlight',regions=['face'],evidence_ids=['a:face:Y_linear.P50','b:face:Y_linear.P50'],interpretation='source midtone darker; transfer brightness not texture',transfer='target',uncertainty='')],coverage=[dict(dimension=d,status='targeted' if d=='shadow_midtone_highlight' else 'not_applicable',delta_ids=['d1'] if d=='shadow_midtone_highlight' else [],reason='synthetic fixture') for d in sorted(DIMENSIONS)],protected_properties=['geometry','identity'],uncertainties=[],summary='synthetic measured difference')

def test_automatic_labels_and_correspondence_are_vlm_outputs(tmp_path):
    c,s=config(tmp_path/'input');c.update(masks={},regions=[],edit_masks={});s.update(labels=[],regions=[]);c['segmentation']=s
    c['automatic_diagnosis']={'provider':{'mode':'files'},'user_goal':'transfer appearance while preserving content'}
    semantic=Semantic();runner=Runner();out=tmp_path/'out'
    effective,audit=prepare_automatic(c,tmp_path/'input',out,semantic,runner)
    assert semantic.stages==['discover_regions','correspond_regions'] and len(runner.calls)==2
    assert runner.calls[0][1]['labels']==['wall'] and effective['regions'][0]['id']=='face'
    assert audit['vlm_calls']==2 and audit['simulation'] and effective['edit_masks']['face']['source_mask']=='A-1'
    assert c['regions']==[] and c['segmentation']['labels']==[]
    prepare_automatic(c,tmp_path/'input',out,Semantic(),runner);assert len(runner.calls)==2


def test_correspondence_cannot_invent_mask_or_swap_sides():
    response=Semantic()('correspond_regions',{'catalog':['x']},{'mask A-1':0,'mask B-1':0})
    response['regions'][0]['a_mask']='B-1'
    with pytest.raises(ValueError):validate_correspondence(response,{'A-1':{'side':'A'},'B-1':{'side':'B'}})


def test_measured_diagnosis_contract_linkage_and_preservation():
    a,b,pairs,p,ca,cb,proposal,c,plan=fixture();obs=extract(a,b,pairs);d=diagnosis(obs)
    validate_measured_diagnosis(d,obs,pairs,['identity'])
    proposal['targets'][0]['delta_id']='d1'
    frozen=compile_contract(proposal,obs,pairs,{}, {},p,d)
    assert frozen.data['measured_diagnosis']==d
    for change in ('delta','evidence','protection'):
        bad=deepcopy(proposal)
        if change=='delta':bad['targets'][0]['delta_id']='made_up'
        elif change=='evidence':bad['targets'][0]['evidence_ids']=['a:face:Y_linear.P50']
        else:bad['protected_properties']=['geometry']
        with pytest.raises(ValueError):compile_contract(bad,obs,pairs,{}, {},p,d)


def test_diagnosis_requires_eight_dimensions_and_actual_bilateral_evidence():
    a,b,pairs,p,ca,cb,proposal,c,plan=fixture();obs=extract(a,b,pairs)
    for mode in ('coverage','evidence','uncertainty'):
        d=diagnosis(obs);pp=deepcopy(pairs)
        if mode=='coverage':d['coverage'].pop()
        elif mode=='evidence':d['deltas'][0]['evidence_ids']=['made_up']
        else:pp[0]['comparability']='partially_comparable'
        with pytest.raises(ValueError):validate_measured_diagnosis(d,obs,pp)


def test_workflow_diagnoses_after_measurement_and_counts_preprocessing(tmp_path):
    a,b,pairs,p,ca,cb,proposal,c,plan=fixture();stages=[]
    proposal['targets'][0]['delta_id']='d1'
    class Planner:
        simulation=True
        def __call__(self,stage,context,images):
            stages.append(stage)
            if stage=='diagnose':
                assert context['observations']['a:face:Y_linear.P50']['value']>0
                return diagnosis(context['observations'])
            if stage=='contract':assert context['measured_diagnosis']['deltas'][0]['id']=='d1';return proposal
            return plan
    audit=dict(vlm_calls=2,user_goal='appearance transfer',discovery={'protected_properties':['identity']},simulation=True)
    result=ToolWorkflow(FakeBackend(),Planner(),FakeReviewer(),p,automatic_diagnosis=audit).run(a,b,ca,cb,pairs,{},tmp_path)
    assert stages==['diagnose','contract','plan'] and result['status']=='accepted'
    assert result['budget']['vlm']==6 and result['measured_diagnosis']['deltas'][0]['id']=='d1'


def test_cli_offline_discovery_pause_is_resumable_without_backend(tmp_path):
    c,s=config(tmp_path/'input');c.update(masks={},regions=[],edit_masks={});s.update(labels=[],regions=[]);c['segmentation']=s
    c['automatic_diagnosis']={'provider':{'mode':'files'},'user_goal':'preserve A and transfer B appearance'}
    path=tmp_path/'input/config.json';write_json(path,c)
    args=Namespace(tool_action='run',config=path,out=tmp_path/'out')
    first=dispatch(args);second=dispatch(args)
    assert first['status']==second['status']=='waiting_for_response' and first['accepted'] is False
    assert len(list((args.out/'semantic_vlm').glob('*/request.json')))==1


def test_cli_full_automatic_chain_with_explicit_test_doubles(tmp_path,monkeypatch):
    import hre.tool_retouch.segmentation as segment_module
    import hre.tool_retouch.diagnosis as diagnosis_module
    import hre.tool_retouch.cli as cli_module
    c,s=config(tmp_path/'input');c.update(masks={},regions=[],edit_masks={});s.update(labels=[],regions=[]);c['segmentation']=s
    c['automatic_diagnosis']={'provider':{'mode':'files'},'user_goal':'transfer measured appearance; preserve identity'}
    _,_,_,_,_,_,proposal,_,plan=fixture();proposal['targets'][0]['delta_id']='d1'
    class Planner:
        simulation=True
        def __call__(self,stage,context,images):
            if stage=='diagnose':return diagnosis(context['observations'])
            return proposal if stage=='contract' else plan
    real=segment_module.schedule_bilateral;runner=Runner()
    monkeypatch.setattr(segment_module,'schedule_bilateral',lambda *a,**kw:real(*a,**{**kw,'runner':runner}))
    monkeypatch.setattr(diagnosis_module,'StructuredProvider',lambda *a:Semantic())
    # Observe the actual contexts returned by the unchanged input pipeline.
    # Required keyword-only parameters fail if CLI forgets domain propagation.
    actual_inputs=cli_module.inputs;contexts={};calls=[]
    def inputs_spy(*args,**kwargs):
        result=actual_inputs(*args,**kwargs)
        contexts.update(A=result[2].domain,B=result[3].domain,C=result[2].domain)
        return result
    def provider_spy(root,provider_config,*,image_domain):
        assert set(image_domain)=={'A','B','C'}
        assert all(image_domain[side] is contexts[side] for side in ('A','B','C'))
        assert provider_config==c[root.name]
        calls.append(root.name)
        return FakeReviewer() if root.name=='reviewer' else Planner()
    backend=FakeBackend();backend.receipts=[]
    def backend_spy(executable,sha256,timeout,*,domain):
        assert domain is contexts['A']
        assert domain.id=='srgb'  # Legacy automatic preprocessing remains sRGB-only.
        assert executable==(tmp_path/'input'/c['backend']['executable']).resolve()
        assert sha256==c['backend']['sha256'] and timeout==c['backend']['timeout']
        backend.domain=domain
        calls.append('backend')
        return backend
    monkeypatch.setattr(cli_module,'inputs',inputs_spy)
    monkeypatch.setattr(cli_module,'StructuredProvider',provider_spy)
    monkeypatch.setattr(cli_module,'PhotoCraftAdapter',backend_spy)
    path=tmp_path/'input/config.json';write_json(path,c)
    r=dispatch(Namespace(tool_action='run',config=path,out=tmp_path/'out'))
    assert r['status']=='accepted' and r['simulation'] and r['budget']['vlm']==6 and len(runner.calls)==2
    assert calls==['backend','planner','reviewer']
