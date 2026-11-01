"""New explicit CLI route; the existing generator/controller is unchanged."""
from dataclasses import asdict
from pathlib import Path
import json
import shutil
import numpy as np
from ..storage import read_json,write_json,case_lock
from .color import ColorContext,require,digest_bytes,encode_png16,read_png16,resolve_domain
from .evidence import build_pairs,array_hash,pair_manifest,MATERIAL_REGION_PROTOCOL
from .contracts import canonical,strict
from .backend import PhotoCraftAdapter
from .providers import StructuredProvider,PendingResponse
from .workflow import ToolWorkflow,validate_policy
from .masks import prepare_mask

class ResumeBackend:
    """Persist every individual renderer invocation, including a distinct replay invocation.

    A resumed offline handoff reuses completed calls; mismatching request order fails.
    It never starts a new model call or render for an identical completed invocation.
    """
    def __init__(self,backend,root):
        self.backend=backend;self.root=Path(root);self.root.mkdir(exist_ok=True);self.index=0
        self.domain=resolve_domain(getattr(backend,'domain',None));self.identity=backend.identity;self.simulation=backend.simulation
    export_native=PhotoCraftAdapter.export_native
    replay=PhotoCraftAdapter.replay
    STORAGE_VERSION='lossless_float64_npz_v1'
    @staticmethod
    def _validate_cached(output,source,row):
        require(isinstance(output,np.ndarray) and output.shape==source.shape,'render cache shape mismatch')
        require(output.dtype==np.dtype(np.float64),'render cache dtype mismatch')
        require(array_hash(output)==row['output_hash'],'render cache modified')
        return output
    def _restore(self,metadata,source,row):
        version=row.get('storage_version')
        if version is None:
            # Read-only legacy compatibility: old rows have only the array hash.
            # Preserve that check and additionally enforce expected shape/dtype.
            output=np.load(metadata.with_suffix('.npy'),allow_pickle=False)
        else:
            require(version==self.STORAGE_VERSION,'unknown render cache storage version')
            require(row.get('shape')==list(source.shape),'render cache metadata shape mismatch')
            require(row.get('dtype')==np.dtype(np.float64).str,'render cache metadata dtype mismatch')
            pixels=metadata.with_suffix('.npz')
            require(digest_bytes(pixels.read_bytes())==row.get('file_sha256'),'render cache file modified')
            with np.load(pixels,allow_pickle=False) as archive:
                require(archive.files==['output'],'render cache archive members mismatch')
                output=archive['output']
        return self._validate_cached(output,source,row)
    def _persist(self,metadata,source,output,key):
        import os
        require(isinstance(output,np.ndarray) and output.shape==source.shape,'render cache output shape mismatch')
        require(output.dtype==np.dtype(np.float64),'render cache output dtype mismatch')
        pixels=metadata.with_suffix('.npz')
        with pixels.open('xb') as f:
            np.savez_compressed(f,output=output)
            f.flush();os.fsync(f.fileno())
        write_json(metadata,{'key':key,'output_hash':array_hash(output),
            'backend_receipt':self.backend.receipts[-1] if self.backend.receipts else None,
            'storage_version':self.STORAGE_VERSION,'shape':list(output.shape),'dtype':output.dtype.str,
            'file_sha256':digest_bytes(pixels.read_bytes())})
    def render_from_source(self,source,plan,values,masks):
        self.index+=1;key=digest_bytes(canonical(dict(source=array_hash(source),plan=plan,values=values,masks={k:array_hash(v) for k,v in masks.items()},backend=self.identity,color_domain=self.domain.identity)).encode())
        metadata=self.root/f'{self.index:04d}.json';pending=self.root/f'{self.index:04d}.pending'
        if metadata.exists():
            self.last_execution={'kind':'cached_completed_invocation','receipt':str(metadata),'key':key}
            row=read_json(metadata);require(row['key']==key,'resume changed renderer call order')
            return self._restore(metadata,source,row)
        require(not pending.exists(),'renderer outcome uncertain; inspect pending job before explicit new run')
        pending.write_text(key)
        self.last_execution={'kind':'actual_backend_call','receipt':str(metadata),'key':key}
        output=self.backend.render_from_source(source,plan,values,masks)
        self._persist(metadata,source,output,key)
        pending.unlink();return output

def add_parser(groups):
    sub=groups.add_parser('tool-retouch',help='Explicit deterministic PhotoCraft reference route').add_subparsers(dest='tool_action',required=True)
    for action in ('run','audit'):
        p=sub.add_parser(action);p.add_argument('--config',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p=sub.add_parser('capabilities');p.add_argument('--executable',type=Path,required=True);p.add_argument('--sha256',required=True)
    p=sub.add_parser('experiment');p.add_argument('--manifest',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p=sub.add_parser('analyze');p.add_argument('--experiment',type=Path,required=True);p.add_argument('--ratings',type=Path,required=True)
    p=sub.add_parser('probe');p.add_argument('--executable',type=Path,required=True);p.add_argument('--sha256',required=True);p.add_argument('--out',type=Path,required=True)

def inputs(config,base,out):
    validate_policy(config['policy'])
    working_space=config.get('working_space','srgb');require(working_space in ('srgb','display_p3'),'unknown working space')
    if working_space=='display_p3':require('automatic_diagnosis' not in config and 'segmentation' not in config,'use explicit P3 mask bridge; legacy automatic preprocessing is sRGB-only')
    segmentation_receipts=None;automatic_audit=None
    if 'automatic_diagnosis' in config:
        from .diagnosis import prepare_automatic
        config,automatic_audit=prepare_automatic(config,base,out)
    if 'segmentation' in config:
        from copy import deepcopy
        from .segmentation import schedule_bilateral
        require(not config['masks'] and not config['regions'],'automatic segmentation must not mix predeclared mask inputs')
        original=deepcopy(config);generated=schedule_bilateral(config,config['segmentation'],base,out/'segmentation')
        config=deepcopy(config);config.pop('segmentation')
        config['masks']=generated['masks'];config['regions']=generated['regions']
        for edit in config['edit_masks'].values():
            if edit['source_mask'].startswith('region:'):
                matches=[r for r in generated['regions'] if r['id']==edit['source_mask'][7:]]
                require(len(matches)==1,'unknown segmentation region edit binding')
                edit['source_mask']=matches[0]['a_mask']
        segmentation_receipts={'configuration':original['segmentation'],'receipts':generated['receipts']}
    strict(config,{'case_id','source','reference','masks','regions','edit_masks','support_policy','policy','backend','planner','reviewer','provenance'} | ({'working_space'} if 'working_space' in config else set()))
    working_space=config.get('working_space','srgb');require(working_space in ('srgb','display_p3'),'unknown working space')
    validate_policy(config['policy'])
    require(isinstance(config['case_id'],str) and config['case_id'],'case identity required')
    strict(config['provenance'],{'source_chain','reference_chain','capture_interval_seconds','limitations','split'})
    require(config['provenance']['source_chain'] and config['provenance']['reference_chain'] and config['provenance']['split'] in ('development','held_out'),'explicit provenance and split')
    paths={}
    for name in ('source','reference'):
        spec=config[name];strict(spec,{'path','sha256','assume_srgb'})
        require(type(spec['assume_srgb']) is bool,'explicit color assumption')
        paths[name]=(base/spec['path']).resolve();require(digest_bytes(paths[name].read_bytes())==spec['sha256'],'input hash mismatch')
    data={}
    for role in ('source','reference'):data[role]=ColorContext.load(paths[role],config[role]['assume_srgb'],working_space=working_space)
    a,ca=data['source'];b,cb=data['reference'];masks={}
    for name,spec in config['masks'].items():
        strict(spec,{'path','sha256','side','producer','producer_version'})
        require(isinstance(name,str) and name and spec['side'] in ('A','B') and spec['producer'] and spec['producer_version'],'bilateral mask provenance')
        p=(base/spec['path']).resolve();raw=p.read_bytes();require(digest_bytes(raw)==spec['sha256'],'mask hash mismatch')
        masks[name]=np.load(p,allow_pickle=False);paths['mask-'+name]=p
    for r in config['regions']:
        require(config['masks'][r['a_mask']]['side']=='A' and config['masks'][r['b_mask']]['side']=='B','cannot reuse B-coordinate mask on A')
    strict(config['support_policy'],{'edge','min_pixels','min_coverage'})
    pairs=build_pairs(a,b,config['regions'],masks,max_regions=9 if config['policy'].get('material_region_protocol')==MATERIAL_REGION_PROTOCOL else 6,**config['support_policy'])
    edited={};edit_records={}
    for name,spec in config['edit_masks'].items():
        strict(spec,{'source_mask','feather_native','density','luminance_range'})
        require(config['masks'][spec['source_mask']]['side']=='A','edit mask must bind A')
        edited[name],edit_records[name]=prepare_mask(masks[spec['source_mask']],a,domain=ca.domain,**{k:v for k,v in spec.items() if k!='source_mask'})
    audit={'source':asdict(ca),'reference':asdict(cb),'regions':pair_manifest(pairs),'edit_masks':edit_records,'provenance':config['provenance']}
    if segmentation_receipts is not None:audit['segmentation']=segmentation_receipts
    if automatic_audit is not None:audit['automatic_diagnosis']=automatic_audit
    snapshot={'config':config,'audit':audit}
    frozen=out/'input_snapshot.json'
    if frozen.exists():require(canonical(read_json(frozen))==canonical(snapshot),'frozen input/config changed; create a new output directory')
    else:
        write_json(frozen,snapshot);(out/'inputs').mkdir(exist_ok=True)
        for i,(name,p) in enumerate(paths.items()):
            target=out/'inputs'/f'{i:03d}{p.suffix}'
            require(not target.exists(),'input snapshot collision');shutil.copyfile(p,target)
        for side,image in [('A',a),('B',b)]:encode_png16(out/'inputs'/f'{side}-working.png',image,domain=ca.domain if side=='A' else cb.domain)
        np.savez_compressed(out/'evaluation_supports.npz',**{f'{i}_{role}':v for i,p in enumerate(pairs) for role,v in p['supports'].items()})
        np.savez_compressed(out/'effective_edit_masks.npz',**edited)
    return a,b,ca,cb,pairs,edited,audit

def dispatch(args):
    if args.tool_action=='capabilities':return PhotoCraftAdapter(args.executable,args.sha256).inspect_capabilities()
    if args.tool_action=='probe':
        from .probe import probe
        return probe(PhotoCraftAdapter(args.executable,args.sha256),args.out)
    if args.tool_action=='experiment':
        from .experiment import export_experiment
        return export_experiment(args.manifest,args.out)
    if args.tool_action=='analyze':
        from .experiment import analyze
        return analyze(args.experiment,args.ratings)
    config=read_json(args.config);out=args.out.resolve()
    require(not out.exists() or (out/'input_snapshot.json').is_file() or (out/'preprocess_binding.json').is_file() or not any(out.iterdir()),'output must be empty or an existing tool-retouch run')
    out.mkdir(parents=True,exist_ok=True)
    with case_lock(out):
        try:a,b,ca,cb,pairs,masks,audit=inputs(config,args.config.resolve().parent,out)
        except PendingResponse as exc:
            result={'status':'waiting_for_response','success':False,'accepted':False,'output':'original_A','reason':str(exc)}
            write_json(out/'result.json',result)
            from .experiment import write_case_report
            write_case_report(out,result)
            return result
        except Exception as exc:
            from .trace import StageTrace
            from .experiment import write_case_report
            result={'status':'execution_failed','success':False,'accepted':False,'output':'original_A','reason':type(exc).__name__+': '+str(exc),'real_effect_validated':False}
            StageTrace(out).record('input_preparation',{'configuration':config},{'error':result['reason']},status='failed',change='输入准备未完成；没有推定像素或分割结果',impact='阻止依赖输入的后续阶段')
            if (out/'input_snapshot.json').exists():raise  # Preserve frozen-run rejection and prior result.
            write_json(out/'result.json',result);write_case_report(out,result)
            return result
        from .trace import StageTrace
        StageTrace(out).record('input_audit_complete',{'source':config['source'],'reference':config['reference']},audit,change='输入/颜色/双侧支持校验完成；分析不编辑图像',impact='允许统计、合同与后端执行')
        if args.tool_action=='audit':return {'audit':audit,'status':'audited','success':False}
        if (out/'result.json').exists():
            prior=read_json(out/'result.json')
            if prior['status']!='waiting_for_response':return {**prior,'accepted':prior['success']}
        try:
            strict(config['backend'],{'executable','sha256','timeout'})
            backend=PhotoCraftAdapter((args.config.resolve().parent/config['backend']['executable']).resolve(),config['backend']['sha256'],config['backend']['timeout'],domain=ca.domain)
            result=ToolWorkflow(ResumeBackend(backend,out/'renders'),StructuredProvider(out/'planner',config['planner'],image_domain={'A':ca.domain,'B':cb.domain,'C':ca.domain}),StructuredProvider(out/'reviewer',config['reviewer'],image_domain={'A':ca.domain,'B':cb.domain,'C':ca.domain}),config['policy'],automatic_diagnosis=audit.get('automatic_diagnosis')).run(a,b,ca,cb,pairs,masks,out)
        except Exception as exc:
            result={'status':'execution_failed','success':False,'output':'original_A','reason':type(exc).__name__+': '+str(exc),'real_effect_validated':False}
            write_json(out/'result.json',result)
        from .experiment import write_case_report
        write_case_report(out,result)
        return {**result,'accepted':result['success']}
