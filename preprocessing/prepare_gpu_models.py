"""Explicit Linux GPU deployment only. Never called by inference workers.

Exact models and actual versions are frozen; nothing is made ready by install.
SAM3 requires an already authorized official checkpoint, not a substitute.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from preprocessing.prepare_models import (isolated_python, install_requirements, file_components,
    make_entry, source_components, safe_extract, download, sha256, DEPTH_REVISION, SCRFD_REVISION)


def probe(python, code):
    return subprocess.run([str(python), '-c', code], check=True, capture_output=True, text=True).stdout.strip().splitlines()[-1]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--base-python',type=Path,default=Path(sys.executable))
    p.add_argument('--tool',choices=['T1_OCR','T2_FACE','T3_DEPTH','T4_SEGMENTATION'],required=True)
    p.add_argument('--depth-checkpoint',type=Path)
    p.add_argument('--depth-weight-revision')
    p.add_argument('--sam-checkpoint',type=Path)
    p.add_argument('--sam-source',type=Path)
    p.add_argument('--sam-source-revision')
    p.add_argument('--sam-tokenizer',type=Path)
    args=p.parse_args();root=args.root.resolve()
    if sys.platform=='win32':raise ValueError('GPU deployment is explicit Linux only')
    if args.tool=='T4_SEGMENTATION':
        if not all([args.sam_checkpoint,args.sam_source,args.sam_source_revision,args.sam_tokenizer]):
            raise ValueError('SAM3 authorized checkpoint/source commit/tokenizer required; unavailable, no substitution')
        if not args.sam_checkpoint.is_file():raise ValueError('SAM3 official authorized checkpoint is missing')
    names={'T1_OCR':'t1','T2_FACE':'t2','T3_DEPTH':'t3','T4_SEGMENTATION':'t4'}
    env=root/'preprocessing/environments'/('venv_'+names[args.tool]+'_gpu')
    python=isolated_python(env,args.base_python)
    actual_prefix=Path(probe(python,'import sys; print(sys.prefix)')).absolute()
    if actual_prefix != env.absolute():
        raise ValueError('Isolated Python prefix mismatch; do not install into Controller/base environment')
    lock=env.parent/(names[args.tool]+'_gpu.freeze.txt')
    if args.tool=='T2_FACE':
        install_requirements(python,['onnxruntime-gpu[cuda,cudnn]==1.23.2','onnx==1.19.1','numpy==2.3.5','opencv-python-headless==4.13.0.92','Pillow==12.1.0'],lock)
        paths={'checkpoint':root/'models/scrfd/det_10g.onnx','scrfd_source':root/'models/scrfd/scrfd.py'}
        components=file_components([(k,v) for k,v in paths.items()])
        entry=make_entry('SCRFD_det_10g',python,paths,components,SCRFD_REVISION,'onnxruntime',probe(python,'import onnxruntime; print(onnxruntime.__version__)'),'insightface_scrfd_detector_only',sha256(lock))
    elif args.tool=='T1_OCR':
        install_requirements(python,['--index-url','https://www.paddlepaddle.org.cn/packages/stable/cu126/','paddlepaddle-gpu==3.3.1'],lock)
        install_requirements(python,['paddleocr==3.7.0','Pillow==12.1.0'],lock)
        base=root/'models/ppocrv6_medium'
        paths={'detection_model_dir':base/'det/PP-OCRv6_medium_det_infer','recognition_model_dir':base/'rec/PP-OCRv6_medium_rec_infer'}
        files=[]
        for key,directory in paths.items():
            files.extend((key+'/'+f.relative_to(directory).as_posix(),f) for f in sorted(directory.rglob('*')) if f.is_file())
        entry=make_entry('PP-OCRv6_medium_det+rec',python,paths,file_components(files),'paddleocr-3.7.0_paddlepaddle-gpu-3.3.1-cu126','paddlepaddle',probe(python,'import paddle; print(paddle.__version__)'),'paddleocr_pipeline',sha256(lock))
    else:
        if args.tool=='T3_DEPTH' and (not args.depth_checkpoint or not args.depth_checkpoint.is_file() or not args.depth_weight_revision):
            raise ValueError('Official DA-V2 Base checkpoint and immutable weight revision required; Small is not a substitute')
        install_requirements(python,['--index-url','https://download.pytorch.org/whl/cu128','torch==2.10.0','torchvision==0.25.0'],lock)
        if args.tool=='T3_DEPTH':
            install_requirements(python,['opencv-python-headless==4.13.0.92','numpy==2.3.5','Pillow==12.1.0'],lock)
            source=root/'models/depth_anything_v2_small/source'/('Depth-Anything-V2-'+DEPTH_REVISION)
            paths={'checkpoint':args.depth_checkpoint,'source_dir':source}
            components=file_components([('checkpoint',args.depth_checkpoint),*source_components(source)])
            revision=DEPTH_REVISION
            name,impl='Depth-Anything-V2-Base','depth_anything_author_api'
        else:
            actual=probe(args.base_python,'import sys; print("%s.%s" % sys.version_info[:2])')
            if tuple(map(int,actual.split('.'))) < (3,12):raise ValueError('Official SAM3 requires Python>=3.12')
            install_requirements(python,[str(args.sam_source),'Pillow==12.1.0'],lock)
            paths={'checkpoint':args.sam_checkpoint,'source_dir':args.sam_source,'tokenizer':args.sam_tokenizer}
            components=file_components([('checkpoint',args.sam_checkpoint),('tokenizer',args.sam_tokenizer),*source_components(args.sam_source)])
            revision=args.sam_source_revision
            name,impl='SAM3','meta_sam3_image_api'
        entry=make_entry(name,python,paths,components,revision,'torch',probe(python,'import torch; print(torch.__version__)'),impl,sha256(lock))
    entry['backend']['device']='cuda:0'
    entry['environment_lock_file']=str(lock.resolve())
    registry_path=root/'preprocessing/registry/gpu_full_v1.json'
    registry_path.parent.mkdir(parents=True,exist_ok=True)
    from filelock import FileLock
    with FileLock(str(registry_path)+'.lock'):
        registry=json.loads(registry_path.read_text()) if registry_path.is_file() else {'automatic_download':False,'tools':{}}
        registry['tools'][args.tool]=entry;registry['registry_status']='warmup_required'
        # Atomic publication; readiness can only be written by real acceptance.
        temporary=registry_path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(registry,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(registry_path)
    print(json.dumps({'tool':args.tool,'prepared':True,'ready':False,'registry':str(registry_path),'framework_version':entry['backend']['framework_version'],'bundle_sha256':entry['model_bundle_sha256']}),flush=True)


if __name__=='__main__':main()
