"""Explicit v2 commands; legacy CLI defaults are unchanged."""
from pathlib import Path
from .storage import read_json,write_json


def add_v2_parser(groups):
    sub=groups.add_parser('v2',help='Opt-in generative reference enhancement').add_subparsers(dest='action',required=True)
    p=sub.add_parser('create');p.add_argument('--prediction',type=Path,required=True);p.add_argument('--reference',type=Path,required=True)
    p.add_argument('--spec',type=Path,required=True);p.add_argument('--case-root',type=Path,required=True);p.add_argument('--manifest',type=Path)
    for action in ('status','evaluate','capture-g1','probe'):
        p=sub.add_parser(action);p.add_argument('--case-root',type=Path,required=True)
        if action=='capture-g1':p.add_argument('--out',type=Path,required=True)
        if action=='probe':p.add_argument('--proof',type=Path,required=True)
    for action in ('condition-export','stage-export'):
        p=sub.add_parser(action);p.add_argument('--case-root',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p=sub.add_parser('condition-import');p.add_argument('--case-root',type=Path,required=True);p.add_argument('--result',type=Path,required=True)
    p=sub.add_parser('run',help='Run current Controller with configured stage/compiler/editor workers')
    p.add_argument('--case-root',type=Path,required=True);p.add_argument('--workers',type=Path,required=True);p.add_argument('--max-steps',type=int,default=16)
    p=sub.add_parser('stage-run',help='Check one exported analysis/compiler stage without advancing the case')
    p.add_argument('--request',type=Path,required=True);p.add_argument('--workers',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p=sub.add_parser('stage-compare',help='Create a portable side-by-side HTML report from stage-check directories')
    p.add_argument('--checks',type=Path,nargs='+',required=True);p.add_argument('--out',type=Path,required=True)
    p=sub.add_parser('run-freeze');p.add_argument('--manifest',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    for action in ('run-status','blind-export','analyze'):
        p=sub.add_parser(action);p.add_argument('--run',type=Path,required=True)
        if action=='blind-export':p.add_argument('--out',type=Path,required=True)
        if action=='analyze':p.add_argument('--ratings',type=Path,required=True)
    p=sub.add_parser('run-prepare');p.add_argument('--run',type=Path,required=True);p.add_argument('--case-id',required=True);p.add_argument('--arm',choices=['G0','G1','G2'],required=True)
    for action in ('mask-from-roi','mask-from-t4'):
        p=sub.add_parser(action);p.add_argument('--case-root',type=Path,required=True);p.add_argument('--roi-id',action='append',required=True)
        p.add_argument('--purpose',choices=['EVAL_MASK','EDIT_MASK'],required=True);p.add_argument('--out',required=True,help='New case-relative annotations/*.npy path')
        if action=='mask-from-t4':
            p.add_argument('--record',type=Path,required=True);p.add_argument('--class-id',type=int,action='append',required=True);p.add_argument('--erosion',type=int,default=0)


def dispatch_v2(args):
    if args.action=='stage-compare':
        from .stage_comparison import compare_stages
        return {'path':str(compare_stages(args.checks,args.out))}
    if args.action=='condition-export':
        from .condition_handoff import export_condition_request
        return {'path':str(export_condition_request(args.case_root,args.out))}
    if args.action=='condition-import':
        from .workflow import Controller
        return Controller(args.case_root).accept_compiled_condition(args.result)
    if args.action in {'run','stage-export','stage-run'}:
        from .model_runner import run_case,export_worker_request,run_stage
        if args.action=='run':return run_case(args.case_root,read_json(args.workers),max_steps=args.max_steps)
        if args.action=='stage-export':return {'path':str(export_worker_request(args.case_root,args.out))}
        return run_stage(args.request,read_json(args.workers),args.out)
    if args.action in {'mask-from-roi','mask-from-t4'}:
        import numpy as np
        from .storage import CaseStore
        from .models import file_sha256
        from .masks import make_mask_contract,derive_t4_mask,require
        from .reference_evaluator import region_mask
        from .evidence import _immutable
        from .paths import safe_path
        state=CaseStore(args.case_root).load();a=state['inputs'][0]
        spec=read_json(args.case_root/'config.json')['reference_v2'];rois={p['roi_pair_id']:p for p in spec['roi_pairs']}
        require(set(args.roi_id)<=set(rois),'unknown_roi','Target ROI must be frozen before mask derivation')
        require(args.out.startswith('annotations/') and args.out.endswith('.npy'),'mask_encoding','Use a new annotations/*.npy output')
        if args.action=='mask-from-roi':
            mask=np.zeros((a['height'],a['width']),dtype=np.uint8)
            for rid in args.roi_id:mask|=region_mask((*mask.shape,3),rois[rid]['prediction'],args.case_root).astype(np.uint8)
            contract=make_mask_contract(args.case_root,mask,a,purpose=args.purpose,roi_ids=args.roi_id,relative=args.out,
                                       provenance={'kind':'manual','annotation_config_sha256':state['config_sha256'],'derivation':'union of frozen A ROI centres'})
        else:
            record=read_json(args.record)
            contract=derive_t4_mask(args.case_root,record,a,expected_cache_contract=record['cache_contract'],class_ids=args.class_id,purpose=args.purpose,
                                    roi_ids=args.roi_id,relative=args.out,erosion=args.erosion)
        _immutable(safe_path(args.case_root,args.out+'.json'),contract)
        return contract
    if args.action=='create':
        from .reference_contracts import create_reference_case
        return create_reference_case(args.prediction,args.reference,read_json(args.spec),args.case_root,
                                     spec_root=args.spec.parent,manifest=read_json(args.manifest) if args.manifest else None)
    if args.action=='capture-g1':
        from .reference_contracts import capture_g1_prompt
        from .masks import require
        require(not args.out.exists(),'immutable_conflict','Choose a new G1 snapshot output')
        write_json(args.out,capture_g1_prompt(args.case_root));return {'path':str(args.out)}
    if args.action=='probe':
        from .masks import validate_mask_probe
        from .reference_runtime import v2_status
        spec=read_json(args.case_root/'config.json')['reference_v2']
        proof=validate_mask_probe(args.case_root,read_json(args.proof),spec['executor'],allow_fixture=spec['simulation_only'])
        return dict(status='fixture_only' if proof['probe_env']=='fixture' else 'observed_supported',proof=proof,
                    next_step='Use a new G2 revision with this proof frozen; an existing configuration is never upgraded in place.')
    if args.action in {'status','evaluate'}:
        from .reference_runtime import v2_status,evaluate_reference_case
        return (v2_status if args.action=='status' else evaluate_reference_case)(args.case_root)
    from .reference_experiments import freeze_reference_run,prepare_run_arm,reference_run_status,export_reference_blind,summarize_reference_run
    if args.action=='run-freeze':return {'path':str(freeze_reference_run(args.manifest,args.out))}
    if args.action=='run-prepare':return prepare_run_arm(args.run,args.case_id,args.arm)
    if args.action=='run-status':return reference_run_status(args.run)
    if args.action=='blind-export':return {'path':str(export_reference_blind(args.run,args.out))}
    return summarize_reference_run(args.run,args.ratings)

