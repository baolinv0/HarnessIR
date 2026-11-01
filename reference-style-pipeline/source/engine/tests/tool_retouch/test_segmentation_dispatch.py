from copy import deepcopy
from pathlib import Path
import numpy as np
import pytest
from PIL import Image
from hre.storage import write_json,read_json
from hre.tool_retouch.color import digest_bytes
from hre.tool_retouch.segmentation import schedule_bilateral
from .test_cli_experiment import setup_case


def config(root):
    c,_,_=setup_case(root);(root/'weights.pt').write_bytes(b'TEST_DOUBLE_NOT_MODEL')
    s=dict(checkpoint='weights.pt',checkpoint_sha256=digest_bytes((root/'weights.pt').read_bytes()),labels=['wall'],conf=.15,iou=.7,imgsz=128,timeout=10,producer_version='TEST_DOUBLE',regions=[dict(id='wall',a_label='wall',b_label='wall',semantic='synthetic',comparability='comparable',reasons=['explicit synthetic correspondence, not inferred from label'])])
    return c,s

class Runner:
    def __init__(self,fail=None):self.calls=[];self.fail=fail
    def __call__(self,image,job,request):
        self.calls.append((image.size,request.copy()))
        if self.fail==len(self.calls):raise RuntimeError('synthetic model failure')
        Image.fromarray(np.ones((image.height,image.width),np.uint16)).save(job/'seg_ids.png')
        write_json(job/'seg_summary.json',dict(reliable=True,reason='',classes=[dict(id=1,label='wall')]))


def test_bilateral_sequential_cache_and_source_binding(tmp_path):
    c,s=config(tmp_path/'input');runner=Runner();cache=tmp_path/'cache'
    r=schedule_bilateral(c,s,tmp_path/'input',cache,runner)
    assert len(runner.calls)==2 and r['simulation']
    assert r['receipts']['A']['binding']['source_sha256']!=r['receipts']['B']['binding']['source_sha256']
    assert r['regions'][0]['a_mask'].startswith('A') and r['regions'][0]['b_mask'].startswith('B')
    assert schedule_bilateral(c,s,tmp_path/'input',cache,runner)==r and len(runner.calls)==2
    s=deepcopy(s);s['conf']=.2;schedule_bilateral(c,s,tmp_path/'input',cache,runner);assert len(runner.calls)==4


def test_failure_recorded_no_silent_retry(tmp_path):
    c,s=config(tmp_path/'input');runner=Runner(fail=2);cache=tmp_path/'cache'
    with pytest.raises(RuntimeError):schedule_bilateral(c,s,tmp_path/'input',cache,runner)
    states=[read_json(p)['status'] for p in cache.glob('*/state.json')];assert sorted(states)==['completed','failed']
    with pytest.raises(ValueError,match='prior failure'):schedule_bilateral(c,s,tmp_path/'input',cache,runner)
    assert len(runner.calls)==2


def test_missing_checkpoint_never_calls_model(tmp_path):
    c,s=config(tmp_path/'input');s['checkpoint']='missing';runner=Runner()
    with pytest.raises(ValueError,match='unavailable'):schedule_bilateral(c,s,tmp_path/'input',tmp_path/'cache',runner)
    assert not runner.calls


def test_corrupt_cache_rejected(tmp_path):
    c,s=config(tmp_path/'input');runner=Runner();cache=tmp_path/'cache'
    r=schedule_bilateral(c,s,tmp_path/'input',cache,runner)
    Path(r['masks']['A-1']['path']).write_bytes(b'corrupt')
    with pytest.raises(ValueError,match='cached mask modified'):schedule_bilateral(c,s,tmp_path/'input',cache,runner)
    assert len(runner.calls)==2


def test_wrong_dimensions_rejected(tmp_path):
    c,s=config(tmp_path/'input')
    def bad(image,job,request):
        Image.fromarray(np.ones((3,3),np.uint16)).save(job/'seg_ids.png')
        write_json(job/'seg_summary.json',dict(reliable=True,classes=[dict(id=1,label='wall')]))
    with pytest.raises(ValueError,match='dimensions'):schedule_bilateral(c,s,tmp_path/'input',tmp_path/'cache',bad)


def test_cli_automatic_inputs_and_edit_region_alias(tmp_path,monkeypatch):
    from hre.tool_retouch.cli import inputs
    import hre.tool_retouch.segmentation as module
    c,s=config(tmp_path/'input');c['masks']={};c['regions']=[];c['segmentation']=s
    c['edit_masks']={'wall_edit':dict(source_mask='region:wall',feather_native=0,density=1,luminance_range=None)}
    runner=Runner();real=module.schedule_bilateral
    monkeypatch.setattr(module,'schedule_bilateral',lambda *args:real(*args,runner=runner))
    out=tmp_path/'run';out.mkdir();r=inputs(c,tmp_path/'input',out)
    assert r[4][0]['id']=='wall' and 'wall_edit' in r[5] and 'segmentation' in r[6]
    inputs(c,tmp_path/'input',out);assert len(runner.calls)==2


def test_absent_label_not_assumed_comparable(tmp_path):
    c,s=config(tmp_path/'input');s['regions'][0]['b_label']='missing'
    with pytest.raises(ValueError,match='absent'):schedule_bilateral(c,s,tmp_path/'input',tmp_path/'cache',Runner())
