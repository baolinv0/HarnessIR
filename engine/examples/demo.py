"""SYNTHETIC protocol demonstration. No model inference, no real R1, no effect estimate.

Run: python engine/examples/demo.py --out /fresh/path
All images are deterministic color patches and all judgments are synthetic test inputs.
"""
from pathlib import Path
import argparse
import json
import os
from PIL import Image, ImageDraw
from hre.assets import create_case
from hre.cli import current_request, import_payload, import_candidate_manual
from hre.models import now
from hre.workflow import Controller
from hre.reporting import write_report
from hre.storage import write_json


def image(path, boost):
    im=Image.new('RGB',(64,48),(20+boost,35+boost,50+boost))
    draw=ImageDraw.Draw(im)
    draw.rectangle((0,0,31,23),fill=(60+boost,75+boost,90+boost))
    draw.rectangle((32,24,63,47),fill=(100+boost,115+boost,130+boost))
    im.save(path)


def diagnosis():
    return {'reference_usable':'usable','comparability':[{'scope':'global','roi_pair_id':None,'status':'comparable','reasons':['SYNTHETIC: identical patch layout, constant RGB lift'],'confidence':.9}],
            'global_gaps':[{'gap_id':'brightness','dimension':'brightness','observation':'SYNTHETIC: A patches have RGB values 25 below B','desired_change':'Lift comparable patch brightness','priority':1,'confidence':.9,'evidence_ids':[]}],
            'local_gaps':[],'style_targets':[{'priority':1,'target':'Lift synthetic patch brightness','support_gap_ids':['brightness'],'confidence':.9}],
            'preservation_constraints':['Preserve A patch geometry; B appearance only'],'tool_plan':[],'uncertainties':['SYNTHETIC test input; no model observed images']}


def composition():
    return {'edit_prompt':'SYNTHETIC demo: edit frozen A, using B for appearance only. Lift patch brightness; preserve A geometry. No model called.',
            'edit_targets':[{'priority':1,'scope':'global','region_in_a':None,'operation':'Lift patch brightness','source_gap_ids':['brightness'],'confidence':.9}],
            'protected_content':[{'kind':'geometry','instruction':'Preserve A patch geometry','asset_role':'prediction','evidence_ids':[]}],
            'evidence_ids':[],'reference_limitations':['SYNTHETIC patch reference only; no real scene or model inference']}


def verification(improved):
    return {'style_alignment':'improved' if improved else 'unchanged','content_preservation':'pass','critical_defects':[],
            'remaining_issues':[] if improved else [{'dimension':'brightness','observation':'SYNTHETIC brightness gap remains','region_in_a':None,'comparability':'comparable','confidence':.9}],
            'retry_focus':[] if improved else ['SYNTHETIC: increase patch lift'],'confidence':.9,
            'style_observations':[{'dimension':'brightness','a_to_c_change':'SYNTHETIC patch lift','c_vs_b':'SYNTHETIC closer patch RGB values' if improved else 'SYNTHETIC gap remains','comparability':'comparable','confidence':.9}],
            'preservation_observations':[{'kind':k,'observation':('SYNTHETIC patches contain no text or persons; absent by construction' if k in {'text','identity'} else 'SYNTHETIC deterministic patch layout unchanged'),'status':'pass','confidence':.9} for k in ['geometry','composition','scene_content','text','identity']]}


def refinement(round_number,retry_focus):
    return {'edit_prompt':'SYNTHETIC retry: use original frozen A and B; lift patches further while preserving original A geometry. No model called.',
            'changes':[{'priority':1,'previous_instruction':'Lift patch brightness','revised_instruction':'Lift patch brightness by larger constant','reason':'SYNTHETIC first patch lift insufficient','based_on_issue':'SYNTHETIC brightness gap remains'}],
            'retry_focus':list(retry_focus),'source_round':round_number}


def run_demo(destination: Path) -> dict:
    destination=Path(os.path.abspath(destination))
    if destination.exists() and any(destination.iterdir()):raise ValueError('Synthetic demo destination must be empty; historical data is preserved.')
    destination.mkdir(parents=True,exist_ok=True)
    image(destination/'A.png',0);image(destination/'B.png',25)
    output={'synthetic':True,'actual_model_called':False,'real_R1':'not_run','cases':{}}
    for profile in ['direct_ref','agent_single','agent_adaptive']:
        root=destination/profile/'rev1'
        create_case(destination/'A.png',destination/'B.png',{'case_id':f'synthetic_{profile}','simulation_only':True},
                    {'profile_id':profile,'assume_srgb':True,'reference_usable':'usable','reference_limitations':['SYNTHETIC deterministic patches; no actual image model']},root)
        controller=Controller(root);controller.start();seen=0
        provenance={'transport':'fixture','ui_model_name':'SYNTHETIC_NO_MODEL','operator_steps':['Synthetic protocol demonstration only; no model called']}
        while controller.state()['workflow_state'] not in {'COMPLETED','FAILED','CANCELLED','PAUSED'}:
            state=controller.state()
            if state['workflow_state']=='WAIT_EVIDENCE':controller.collect_evidence();continue
            req=current_request(root);stage=req['stage']
            if stage=='diagnose':result=import_payload(root,diagnosis(),provenance=provenance)
            elif stage=='compose':result=import_payload(root,composition(),provenance=provenance)
            elif stage=='execute':
                seen+=1;path=destination/f'C_{profile}_{seen}.png';image(path,5 if profile=='agent_adaptive' and seen==1 else 25)
                result=import_candidate_manual(root,req['task_id'],path,{'actual_generation_count':1,'provider_order':0,'model_observed':{**provenance,'exact_model_version':None,'seed':None,'observed_at':now()}},'submitted')
            elif stage=='verify':result=import_payload(root,verification(profile!='agent_adaptive' or seen>1),provenance=provenance)
            elif stage=='refine':result=import_payload(root,refinement(req['payload']['source_round'],req['payload']['retry_focus']),provenance=provenance)
            else:raise RuntimeError(stage)
            if not result.accepted:raise RuntimeError(f'SYNTHETIC submission rejected: {result}')
        state=controller.state();report=write_report(root)
        output['cases'][profile]={'case_root':str(root.resolve()),'workflow_state':state['workflow_state'],'success':state['success'],
                                  'consumed':state['budget']['consumed'],'terminal_reason':state['terminal_reason'],'report':str(report)}
    write_json(destination/'SYNTHETIC_DEMO.json',output)
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True)
    print(json.dumps(run_demo(parser.parse_args().out),indent=2))
