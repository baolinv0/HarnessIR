"""SYNTHETIC v2 G0/G1/ROI/ITT demonstration. No model, API, or real R1.

Run from a checkout: python engine/examples/reference_v2_demo.py --out /fresh/path
The old demonstration helpers supply clearly labeled synthetic stage payloads.
G2 remains skipped; its positive protocol fixture is in the unit tests only.
"""
import argparse
import importlib.util
from pathlib import Path
from PIL import Image
from hre.models import file_sha256,sha256_bytes,now
from hre.storage import write_json
from hre.reference_contracts import create_reference_case
from hre.reference_experiments import freeze_reference_run,prepare_run_arm,reference_run_status,export_reference_blind,summarize_reference_run
from hre.reference_runtime import evaluate_reference_case
from hre.workflow import Controller
from hre.cli import current_request,import_payload,import_candidate_manual


def run_demo(destination):
    destination=Path(destination).absolute()
    if destination.exists() and any(destination.iterdir()):raise ValueError('Choose a fresh destination; historical files are preserved')
    destination.mkdir(parents=True,exist_ok=True)
    helper_spec=importlib.util.spec_from_file_location('hre_original_synthetic_helpers',Path(__file__).with_name('demo.py'))
    helper=importlib.util.module_from_spec(helper_spec);helper_spec.loader.exec_module(helper)
    helper.image(destination/'A.png',0);helper.image(destination/'B.png',25)
    with Image.open(destination/'B.png') as im:im.resize((96,72),Image.Resampling.NEAREST).save(destination/'B.png')
    executor=dict(executor_id='synthetic_no_model',model_display_name='SYNTHETIC_NO_MODEL',model_exact_version=None,
                  transport='fixture',pipeline_version='v2',adapter_version='fixture',settings={})
    spec=dict(schema_version='ref_enhance_v2',arm_id='G1',executor=executor,task_scope='global',local_mask_eligible=False,
              roi_pairs=[dict(roi_pair_id='wall',prediction={'kind':'box','box':[0,0,.5,.5]},reference={'kind':'box','box':[0,0,.5,.5]},
                              comparability='comparable',reasons=['SYNTHETIC identical color patch'],semantic_label='patch',dimensions=['brightness','color','tone','saturation'])],
              eval_mask=None,edit_mask=None,mask_probe=None,paired_g1=None,files=[],simulation_only=True,assume_srgb=True,tool_profile={})
    create_reference_case(destination/'A.png',destination/'B.png',spec,destination/'source',spec_root=destination,manifest={'case_id':'fixture_one'})
    manifest=dict(schema_version='reference_run_manifest_v2',stage='R0_fixture',seed=20261015,
                  code_commit_sha='c94a4001e5250fd257e8954b56b72ca9c4725409',excluded_rater_ids=['fixture_generator'],
                  cases=[dict(case_id='fixture_one',scene_group_id='fixture_scene',split='dev',source_case_root='source',g2=None)])
    write_json(destination/'manifest.json',manifest);freeze_reference_run(destination/'manifest.json',destination/'run')
    results={}
    for arm in ['G0','G1']:
        root=Path(prepare_run_arm(destination/'run','fixture_one',arm)['case_root']);controller=Controller(root);controller.start()
        while controller.state()['workflow_state'] not in {'COMPLETED','FAILED','CANCELLED','PAUSED'}:
            req=current_request(root);stage=req['stage']
            if stage=='diagnose':result=import_payload(root,helper.diagnosis(),provenance={'transport':'fixture'})
            elif stage=='compose':result=import_payload(root,helper.composition(),provenance={'transport':'fixture'})
            elif stage=='execute':
                output=destination/(arm+'_synthetic_C.png');helper.image(output,20)
                from hre.prompts import build_context,render_stage
                import json
                rendered=json.loads(render_stage('execute',build_context(root,req),case_root=root))['edit_prompt']
                observation=dict(kind='hre_executor_observation_v2',schema_version='ref_enhance_v2',executor=executor,
                                 request_sha256=req['request_sha256'],prompt_sha256=sha256_bytes(rendered.encode()),
                                 input_sha256={role:a['sha256'] for role,a in zip(['A','B'],req['input_assets'])},output_sha256=file_sha256(output),
                                 actual_generation_count=1,observer='Synthetic fixture',observed_at=now(),steps=['Deterministic synthetic generation; no model called'])
                result=import_candidate_manual(root,req['task_id'],output,
                                               dict(actual_generation_count=1,provider_order=0,executor_observation=observation,
                                                    model_observed={'ui_model_name':'SYNTHETIC_NO_MODEL','transport':'fixture','operator_steps':['No model called; deterministic synthetic fixture']}),'submitted')
            elif stage=='verify':result=import_payload(root,helper.verification(True),provenance={'transport':'fixture'})
            else:raise RuntimeError('Unexpected synthetic stage: '+stage)
            if not result.accepted:raise RuntimeError(str(result))
        results[arm]={'state':controller.state()['workflow_state'],'attributes':evaluate_reference_case(root)}
    export_reference_blind(destination/'run',destination/'blind')
    write_json(destination/'empty_ratings.json',dict(schema_version='reference_ratings_v2',
               blind_manifest_sha256=file_sha256(destination/'blind/manifest.json'),raters=[],ratings=[],comparisons=[]))
    summary=summarize_reference_run(destination/'run',destination/'empty_ratings.json')
    output=dict(synthetic=True,actual_model_called=False,real_R1='not_run',real_R2='not_run',G2='skipped_not_eligible',
                cases=results,run_status=reference_run_status(destination/'run'),independent_summary=summary)
    write_json(destination/'SYNTHETIC_V2_DEMO.json',output)
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True)
    result=run_demo(parser.parse_args().out)
    print({'synthetic':True,'actual_model_called':False,'states':{k:v['state'] for k,v in result['cases'].items()},
           'G2':result['G2'],'decision':result['independent_summary']['decision']})
