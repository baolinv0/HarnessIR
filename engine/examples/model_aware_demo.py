"""Executable SYNTHETIC demonstration of both parallel entry points.

No learned model is loaded. This checks orchestration, never image quality.
PYTHONPATH=engine/src python engine/examples/model_aware_demo.py --out /new/path
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

from hre.models import file_sha256,now,sha256_bytes
from hre.storage import read_json,write_json


def helpers():
    spec=importlib.util.spec_from_file_location('synthetic_helpers',Path(__file__).with_name('demo.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def fixture_worker(request_path,response_path):
    value=read_json(request_path);helper=helpers()
    if value['kind']=='stage':
        stage=value['request']['stage']
        payload={'diagnose':helper.diagnosis,'compose':helper.composition,'verify':lambda:helper.verification(True)}[stage]()
        write_json(response_path,{'payload':payload})
        return
    if value['kind']!='execute':raise ValueError('Fixture only implements stage and execute')
    output=Path(value['output_dir'])/'SYNTHETIC_C.png';helper.image(output,20)
    req=value['request'];executor=value['executor'];prompt=json.loads(value['prompt'])['edit_prompt']
    observation=dict(kind='hre_executor_observation_v2',schema_version='ref_enhance_v2',executor=executor,
        request_sha256=req['request_sha256'],prompt_sha256=sha256_bytes(prompt.encode()),
        input_sha256={a['role']:a['sha256'] for a in value['attachments']},output_sha256=file_sha256(output),
        actual_generation_count=1,observer='SYNTHETIC fixture worker',observed_at=now(),
        steps=['Deterministic RGB patch image; no image model called'])
    write_json(response_path,dict(image_path=str(output),metadata=dict(actual_generation_count=1,provider_order=0,
        executor_observation=observation,model_observed=dict(ui_model_name=executor['model_display_name'],
        exact_model_version=None,transport='fixture',operator_steps=['Synthetic orchestration demonstration only']))))


def run_demo(out):
    from hre.reference_contracts import create_reference_case
    from hre.model_runner import export_worker_request,run_stage,run_case
    from hre.workflow import Controller
    out=Path(out).absolute()
    if out.exists():raise ValueError('Choose a new demonstration directory')
    out.mkdir(parents=True);helper=helpers()
    helper.image(out/'A.png',0);helper.image(out/'B.png',25)
    executor=dict(executor_id='synthetic_no_model',model_display_name='SYNTHETIC_NO_MODEL',model_exact_version=None,
                  transport='fixture',pipeline_version='model_aware_fixture_v1',adapter_version='fixture',settings={})
    spec=dict(schema_version='ref_enhance_v2',arm_id='G1',executor=executor,task_scope='global',local_mask_eligible=False,
        roi_pairs=[dict(roi_pair_id='patch',prediction={'kind':'box','box':[0,0,.5,.5]},reference={'kind':'box','box':[0,0,.5,.5]},
                       comparability='comparable',reasons=['SYNTHETIC constant color patches'],semantic_label='patch',dimensions=['brightness','color','tone','saturation'])],
        eval_mask=None,edit_mask=None,mask_probe=None,paired_g1=None,files=[],simulation_only=True,assume_srgb=True,tool_profile={},
        model_aware=dict(profile_id='qwen21',strategy='model_aware',compiler='direct'))
    root=out/'case';create_reference_case(out/'A.png',out/'B.png',spec,root,spec_root=out,manifest={'case_id':'model_aware_fixture'})
    command=[sys.executable,str(Path(__file__).absolute())]
    config=dict(schema_version='hre_workers_v1',workers={'stage':command,'execute':command},timeout_seconds=60)
    write_json(out/'workers.json',config)
    Controller(root).start()
    frozen=export_worker_request(root,out/'diagnose_export')
    check=run_stage(frozen,config,out/'diagnose_check')
    result=run_case(root,config)
    report=dict(synthetic=True,actual_model_called=False,stage_check=check,full_run=result,
                quality_claim='not_established',real_R1='not_run',real_R2='not_run')
    write_json(out/'SYNTHETIC_MODEL_AWARE_DEMO.json',report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path);parser.add_argument('--request',type=Path);parser.add_argument('--response',type=Path)
    args=parser.parse_args()
    if args.request and args.response:fixture_worker(args.request,args.response)
    elif args.out:
        report=run_demo(args.out)
        print(json.dumps({'synthetic':True,'actual_model_called':False,'workflow_state':report['full_run']['workflow_state'],
                          'consumed':report['full_run']['budget']['consumed'],'stage_check':report['stage_check']['validated']}))
    else:parser.error('Supply --out, or --request and --response')
