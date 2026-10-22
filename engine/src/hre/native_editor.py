"""Single-call Qwen/FireRed editor over explicitly deployed Diffusers weights.

Optional dependencies are imported only when invoked. No downloads, prompt
rewrites, output resizing or retries are performed by this worker.
"""
import argparse
from copy import deepcopy
import json
import math
from pathlib import Path
import re
import sys

from PIL import Image
from .models import HREError,file_sha256,sha256_bytes,now
from .storage import read_json,write_json
from .model_aware import get_model_profile

ADAPTER_VERSION='hre.native_editor.v1'


def require(condition,code,message):
    if not condition:raise HREError(code,message)


def run_native_editor(envelope:dict)->dict:
    require(envelope.get('schema_version')=='hre_worker_request_v1' and envelope.get('kind')=='execute',
            'native_request_invalid','Native editor requires an execute worker request')
    editor=Path(envelope['bundle_path'])/'editor'
    condition=read_json(editor/'condition.json');profile_id=condition.get('profile_id')
    require(profile_id in {'qwen21','firered11'},'native_profile_unsupported','Built-in editor supports Qwen 2.1 and FireRed 1.1')
    profile=get_model_profile(profile_id);executor=deepcopy(envelope['executor']);settings=executor.get('settings',{})
    required={'model_id','revision','seed','num_inference_steps','true_cfg_scale','negative_prompt','device','torch_dtype'}
    if profile_id=='qwen21':required|={'output_resolution','use_kv_cache'}
    require(isinstance(settings,dict) and required<=set(settings) and not set(settings)-required-{'num_images_per_prompt'},
            'native_settings_invalid','Freeze exactly the documented native settings')
    require(isinstance(settings['revision'],str) and bool(re.fullmatch('[0-9a-fA-F]{40}',settings['revision'])),
            'native_settings_invalid','Use a pinned 40-character model commit revision')
    require(type(settings['seed']) is int and settings['seed']>=0 and type(settings['num_inference_steps']) is int and settings['num_inference_steps']>0,
            'native_settings_invalid','Seed and inference steps must be valid integers')
    require(type(settings['true_cfg_scale']) in (int,float) and math.isfinite(settings['true_cfg_scale']) and settings['true_cfg_scale']>0,
            'native_settings_invalid','Freeze a positive finite true_cfg_scale')
    require(isinstance(settings['negative_prompt'],str) and isinstance(settings['device'],str) and bool(settings['device'])
            and settings['torch_dtype'] in {'bfloat16','float16','float32'} and type(settings.get('num_images_per_prompt',1)) is int
            and settings.get('num_images_per_prompt',1)==1,'native_settings_invalid','Invalid dtype, device, negative prompt or output count')
    if profile_id=='qwen21':
        require(type(settings['output_resolution']) is int and settings['output_resolution']>0 and type(settings['use_kv_cache']) is bool,
                'native_settings_invalid','Freeze Qwen output_resolution and use_kv_cache')
    require(settings['model_id']==profile['model_id'],'native_model_mismatch','Configured model does not match the selected profile')
    prompt=(editor/'edit_prompt.txt').read_text('utf-8');request=envelope['request'];assets=request['input_assets']
    require(condition.get('status')=='ok' and condition.get('edit_prompt')==prompt==request['payload']['edit_prompt'],
            'native_condition_mismatch','Native text differs from the accepted execution condition')
    require(len(assets)==2 and [a['role'] for a in assets]==['prediction','reference'],
            'native_input_mismatch','Expected ordered A then B')
    images=[]
    for role,asset in zip(('A','B'),assets):
        path=editor/(role+'.png')
        require(file_sha256(path)==asset['sha256'],'native_input_mismatch','Exported image differs from frozen input')
        with Image.open(path) as im:
            require(im.size==(asset['width'],asset['height']),'native_input_mismatch','Image dimensions differ from frozen input')
            images.append(im.convert('RGB'))
    width,height=images[0].size
    require(condition.get('canvas')=={'source':'A','width':width,'height':height},
            'native_canvas_invalid','Condition must retain A canvas')
    try:
        import torch
        import diffusers
    except ImportError as exc:
        raise HREError('native_dependency_missing','Install compatible torch/diffusers and deploy the pinned model weights in this worker environment') from exc
    expected=dict(executor_id='hre-native-diffusers',model_display_name=profile['display_name'],model_exact_version=settings['revision'],
                  transport='api',pipeline_version=diffusers.__version__,adapter_version=ADAPTER_VERSION,settings=settings)
    require(executor==expected,'native_executor_mismatch','Actual adapter, pipeline or model identity differs from the frozen executor')
    name='QwenImage21Pipeline' if profile_id=='qwen21' else 'QwenImageEditPlusPipeline'
    pipeline=getattr(diffusers,name,None)
    require(pipeline is not None,'native_dependency_missing','Installed Diffusers does not provide '+name)
    output_dir=Path(envelope['output_dir']).absolute();output_dir.mkdir(parents=True,exist_ok=True)
    require(not list(output_dir.glob('candidate_*.png')),'native_output_exists','Use a fresh output directory')
    pipe=pipeline.from_pretrained(settings['model_id'],revision=settings['revision'],local_files_only=True,
                                  torch_dtype=getattr(torch,settings['torch_dtype'])).to(settings['device'])
    factor=getattr(pipe,'vae_scale_factor',None)
    if isinstance(factor,int):
        require(width%(factor*2)==0 and height%(factor*2)==0,'native_canvas_unsupported',
                'A dimensions are not representable by this pipeline; choose an explicitly prepared new case')
    kwargs=dict(image=images,prompt=prompt,width=width,height=height,
                generator=torch.Generator(device=settings['device']).manual_seed(settings['seed']),
                num_inference_steps=settings['num_inference_steps'],true_cfg_scale=settings['true_cfg_scale'],
                negative_prompt=settings['negative_prompt'],num_images_per_prompt=1)
    if profile_id=='qwen21':kwargs.update(output_resolution=settings['output_resolution'],use_kv_cache=settings['use_kv_cache'])
    with torch.inference_mode():result=pipe(**kwargs)
    outputs=getattr(result,'images',None)
    require(isinstance(outputs,(list,tuple)) and len(outputs)>0,'native_output_missing','The single pipeline invocation returned no images')
    paths=[]
    for index,im in enumerate(outputs):
        require(isinstance(im,Image.Image),'native_output_invalid','Pipeline must return PIL images')
        path=output_dir/f'candidate_{index:03d}.png';im.save(path);paths.append(path)
    stamp=now();steps=[f'Loaded pinned {name} from the local cache',
        'Called pipeline once with A then B, accepted native text, explicit A dimensions and one requested image',
        f'Observed and preserved {len(paths)} returned images in provider order']
    receipt=dict(kind='hre_executor_observation_v2',schema_version='ref_enhance_v2',executor=expected,
        request_sha256=request['request_sha256'],prompt_sha256=sha256_bytes(prompt.encode()),
        input_sha256={role:a['sha256'] for role,a in zip(('A','B'),assets)},output_sha256=file_sha256(paths[0]),
        actual_generation_count=len(paths),observer=ADAPTER_VERSION,observed_at=stamp,steps=steps)
    metadata=dict(actual_generation_count=len(paths),provider_order=0,executor_observation=receipt,
        model_observed=dict(ui_model_name=profile['display_name'],exact_model_version=settings['revision'],seed=settings['seed'],
                            observed_at=stamp,transport='api',operator_steps=steps),
        extras=[dict(source=str(path),provider_order=i,complete=True) for i,path in enumerate(paths) if i])
    return dict(image_path=str(paths[0]),metadata=metadata)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request',type=Path,required=True);parser.add_argument('--response',type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        require(not args.response.exists(),'native_output_exists','Response already exists')
        write_json(args.response,run_native_editor(read_json(args.request)))
        return 0
    except (HREError,ImportError,OSError,ValueError,KeyError) as exc:
        print(str(exc),file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
