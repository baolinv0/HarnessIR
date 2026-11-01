from argparse import Namespace
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import numpy as np
import pytest
from hre.tool_retouch.color import encode_png16,digest_bytes
from hre.tool_retouch.cli import dispatch,inputs
from hre.tool_retouch.workflow import ToolWorkflow
from hre.tool_retouch.experiment import export_experiment,analyze
from hre.storage import write_json,read_json
from .helpers import fixture,FakeBackend,FakePlanner,FakeReviewer


def setup_case(root):
    root.mkdir();a,b,pairs,p,ca,cb,proposal,c,plan=fixture()
    encode_png16(root/'A.png',a);encode_png16(root/'B.png',b)
    for side in ('A','B'):np.save(root/(side+'.npy'),np.ones(a.shape[:2]))
    ref=lambda file: {'path':file,'sha256':digest_bytes((root/file).read_bytes()),'assume_srgb':False}
    config=dict(case_id='synthetic',source=ref('A.png'),reference=ref('B.png'),masks={s:dict(path=s+'.npy',sha256=digest_bytes((root/(s+'.npy')).read_bytes()),side=s,producer='test fixture',producer_version='1') for s in ('A','B')},regions=[{k:v for k,v in pairs[0].items() if k in ('id','a_mask','b_mask','semantic','comparability','reasons','provenance')}],edit_masks={},support_policy=dict(edge=1,min_pixels=32,min_coverage=.4),policy=p,backend=dict(executable='missing-worker',sha256='0'*64,timeout=1),planner={'mode':'files'},reviewer={'mode':'files'},provenance=dict(source_chain='synthetic',reference_chain='synthetic',capture_interval_seconds=None,limitations=['test only'],split='development'))
    write_json(root/'config.json',config)
    return config,proposal,plan


def test_cli_audit_resume_and_missing_backend(tmp_path):
    config,_,_=setup_case(tmp_path/'case');out=tmp_path/'out'
    args=Namespace(tool_action='audit',config=tmp_path/'case/config.json',out=out)
    assert dispatch(args)['status']=='audited'
    assert dispatch(args)['status']=='audited'
    args.tool_action='run';r=dispatch(args)
    assert r['status']=='execution_failed' and r['accepted'] is False and r['output']=='original_A'
    assert dispatch(args)==r
    config['source']['assume_srgb']=True;write_json(args.config,config)
    with pytest.raises(ValueError):dispatch(args)


def test_cli_does_not_write_existing_unrelated_directory(tmp_path):
    config,_,_=setup_case(tmp_path/'case');out=tmp_path/'out';out.mkdir();(out/'precious').write_text('keep')
    with pytest.raises(ValueError):dispatch(Namespace(tool_action='audit',config=tmp_path/'case/config.json',out=out))
    assert list(out.iterdir())==[out/'precious']


def test_paired_export_and_complete_ratings(tmp_path):
    config,proposal,plan=setup_case(tmp_path/'case');run=tmp_path/'run';run.mkdir()
    a,b,ca,cb,pairs,masks,audit=inputs(config,tmp_path/'case',run)
    r=ToolWorkflow(FakeBackend(),FakePlanner(proposal,plan),FakeReviewer(),config['policy']).run(a,b,ca,cb,pairs,masks,run)
    assert r['status']=='accepted'
    manifest=dict(protocol_id='synthetic-comparison',split='development',seed=17,development_case_ids=['synthetic'],baseline=dict(model='TEST_DOUBLE',version='1',prompt_sha256='p',seed=1,configuration_sha256='q'),original_user_goal='test only',cases=[dict(case_id='synthetic',tool_run='run',G=dict(status='output',path='case/B.png',sha256=config['reference']['sha256'],source_sha256=config['source']['sha256'],reference_sha256=config['reference']['sha256'],baseline_configuration_sha256='q'),source_sha256=config['source']['sha256'],reference_sha256=config['reference']['sha256'])])
    write_json(tmp_path/'experiment.json',manifest);out=tmp_path/'experiment'
    result=export_experiment(tmp_path/'experiment.json',out);assert result['pairs']==1
    assert not (out/'review/private_mapping.json').exists()
    ratings=read_json(out/'ratings.template.json');ratings['reviewer']='synthetic test';ratings['ratings'][0].update(winner='tie',reference_match='tie',content='tie',naturalness='tie')
    write_json(tmp_path/'ratings.json',ratings)
    assert analyze(out,tmp_path/'ratings.json')['wins']=={'tie':1}
    manifest['split']='held_out';write_json(tmp_path/'leak.json',manifest)
    with pytest.raises(ValueError):export_experiment(tmp_path/'leak.json',tmp_path/'bad')
