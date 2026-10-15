"""Explicit online deployment; this module is never imported by inference workers.

The controller environment runs this stdlib-only CLI. Every download is saved with
its URL, immutable source revision, and SHA-256. The isolated environment's actual
pip freeze is hashed. A registry stays unready until an actual worker warm-up is
accepted by the controller. No dependency or model repair occurs at runtime.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
SCRFD_REVISION = "3e6486942a1be2da0e5b475fac375ea73264bd21"
SCRFD_SOURCE = f"https://raw.githubusercontent.com/deepinsight/insightface/{SCRFD_REVISION}/python-package/insightface/model_zoo/scrfd.py"
SCRFD_ARCHIVE = "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip"


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json(value))


def download(url, path, expected_sha256=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        temporary = path.with_suffix(path.suffix + ".part")
        request = urllib.request.Request(url, headers={"User-Agent": "HarnessIR-explicit-model-deployment/1.1"})
        with urllib.request.urlopen(request, timeout=120) as source, temporary.open("wb") as target:
            shutil.copyfileobj(source, target)
        temporary.replace(path)
    actual = sha256(path)
    if expected_sha256 is not None and actual != expected_sha256:
        raise ValueError(f"download hash mismatch: {path.name}")
    return {"url": url, "sha256": actual, "path": str(path.resolve())}


def extract_scrfd(archive, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as stream:
        candidates = []
        for info in stream.infolist():
            name = PurePosixPath(info.filename)
            if name.is_absolute() or ".." in name.parts or "\\" in info.filename or ":" in info.filename:
                raise ValueError("unsafe model archive member")
            if name.name == "det_10g.onnx":
                candidates.append(info)
        if len(candidates) != 1:
            raise ValueError("official SCRFD archive must contain exactly one det_10g.onnx")
        checkpoint = out / "det_10g.onnx"
        with stream.open(candidates[0]) as source, checkpoint.open("wb") as target:
            shutil.copyfileobj(source, target)
    return checkpoint


def isolated_python(environment, base_python):
    environment = Path(environment)
    executable = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not executable.exists():
        subprocess.run([str(base_python), "-m", "venv", str(environment)], check=True)
    # Linux venv interpreters are symlinks. Resolving them launches the base
    # interpreter and bypasses the venv's site-packages and isolation.
    return executable.absolute()


def install_requirements(python, requirements, lock_path):
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "--report", str(lock_path.with_suffix(".install-report.json")), *requirements], check=True)
    lock = subprocess.run([str(python), "-m", "pip", "freeze", "--all"], check=True, capture_output=True).stdout
    lock_path.write_bytes(lock)
    return sha256(lock_path)


def make_entry(model_name, python, paths, components, revision, framework, version, implementation, lock_hash):
    return {"model_name": model_name, "python_executable": str(python), "components": components,
            "model_bundle_sha256": hashlib.sha256(canonical_json([{"name": c["name"], "sha256": c["sha256"]} for c in components])).hexdigest(),
            "source_revision": revision, "environment_lock_sha256": lock_hash, "ready": False,
            "warmup_evidence": None, "artifact_paths": {k: str(Path(v).resolve()) for k, v in paths.items()},
            "backend": {"implementation": implementation, "source_revision": revision,
                        "framework": framework, "framework_version": version, "device": "cpu", "precision": "fp32",
                        "environment_lock_sha256": lock_hash}}


def prepare_scrfd(args):
    model_dir = args.root / "models" / "scrfd"
    source = model_dir / "scrfd.py"
    archive = args.root / "runtime" / "downloads" / "buffalo_l_v0.7.zip"
    receipt_path = model_dir / "source_lock.json"
    previous = json.loads(receipt_path.read_text("utf-8")) if receipt_path.exists() else {}
    source_receipt = download(SCRFD_SOURCE, source, previous.get("source", {}).get("sha256"))
    weight_receipt = download(SCRFD_ARCHIVE, archive, previous.get("archive", {}).get("sha256"))
    checkpoint = extract_scrfd(archive, model_dir)
    python = isolated_python(args.root / "preprocessing" / "environments" / "venv_t2_cpu", args.base_python)
    lock_path = args.root / "preprocessing" / "environments" / "t2_cpu.freeze.txt"
    lock_hash = install_requirements(python, ["onnxruntime==1.23.2", "onnx==1.20.1", "opencv-python-headless==4.13.0.92", "numpy==2.3.5", "Pillow==12.1.0"], lock_path)
    version = subprocess.run([str(python), "-c", "import onnxruntime; print(onnxruntime.__version__)"], check=True, capture_output=True, text=True).stdout.strip()
    components = [{"name": name, "path": str(path.resolve()), "sha256": sha256(path)} for name, path in [("detector", checkpoint), ("scrfd_source", source)]]
    write_json(receipt_path, {"source_revision": SCRFD_REVISION, "source": source_receipt, "archive": weight_receipt, "components": components})
    entry=make_entry("SCRFD_det_10g", python, {"checkpoint": checkpoint, "scrfd_source": source}, components,
                     SCRFD_REVISION, "onnxruntime", version, "insightface_scrfd_detector_only", lock_hash)
    entry["environment_lock_file"]=str(lock_path.resolve())
    return entry


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool", required=True, choices=["T1_OCR", "T2_FACE", "T3_DEPTH", "T4_SEGMENTATION"])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--base-python", type=Path, default=Path(sys.executable))
    parser.add_argument("--registry", type=Path)
    args = parser.parse_args(argv)
    args.root = args.root.resolve()
    entry = prepare_scrfd(args) if args.tool == "T2_FACE" else prepare_other(args)
    registry_path = args.registry or args.root / "preprocessing" / "registry" / "cpu_probe_v1.json"
    registry = json.loads(registry_path.read_text("utf-8")) if registry_path.exists() else {"automatic_download": False, "tools": {}}
    registry["registry_status"] = "warmup_required"
    registry["tools"][args.tool] = entry
    write_json(registry_path, registry)
    print(json.dumps({"registry": str(registry_path.resolve()), "tool": args.tool, "ready": False, "warmup_required": True}))
    return 0


def prepare_other(args):
    if args.tool == "T1_OCR":
        return prepare_ocr(args)
    if args.tool == "T3_DEPTH":
        return prepare_depth(args)
    return prepare_yoloe(args)


def safe_extract(archive, destination):
    destination=Path(destination).resolve()
    destination.mkdir(parents=True,exist_ok=True)
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as stream:
            selected=[]
            skipped=[]
            for info in stream.infolist():
                member=PurePosixPath(info.filename)
                if member.is_absolute() or ".." in member.parts or ":" in info.filename or "\\" in info.filename:
                    raise ValueError("unsafe deployment archive member")
                if ((info.external_attr>>16)&0o170000)==0o120000:
                    skipped.append(info.filename)
                else:
                    selected.append(info)
            stream.extractall(destination,members=selected)
            write_json(destination/"extraction_receipt.json",{"archive_sha256":sha256(archive),"skipped_symbolic_links":skipped})
    else:
        with tarfile.open(archive) as stream:
            for info in stream.getmembers():
                member=PurePosixPath(info.name)
                if member.is_absolute() or ".." in member.parts or ":" in info.name or "\\" in info.name or info.issym() or info.islnk():
                    raise ValueError("unsafe deployment archive member")
            stream.extractall(destination,filter="data")


def file_components(items):
    return [{"name":name,"path":str(Path(path).resolve()),"sha256":sha256(path)} for name,path in items]


def source_components(source, prefix="source"):
    return [(f"{prefix}/{path.relative_to(source).as_posix()}",path) for path in sorted(Path(source).rglob("*.py")) if "__pycache__" not in path.parts]


def previous_receipt(path):
    return json.loads(Path(path).read_text("utf-8")) if Path(path).exists() else {}


def prepare_ocr(args):
    model_dir=args.root/"models"/"ppocrv6_medium"
    receipt_path=model_dir/"source_lock.json"
    old=previous_receipt(receipt_path)
    downloads={}
    model_paths={}
    component_items=[]
    for suffix,name in [("det","PP-OCRv6_medium_det"),("rec","PP-OCRv6_medium_rec")]:
        url=f"https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/{name}_infer.tar"
        archive=args.root/"runtime"/"downloads"/(name+"_infer.tar")
        downloads[suffix]=download(url,archive,old.get("downloads",{}).get(suffix,{}).get("sha256"))
        extraction=model_dir/suffix
        safe_extract(archive,extraction)
        configs=list(extraction.rglob("inference.yml"))
        if len(configs)!=1:
            raise ValueError(f"official {name} archive must contain one inference.yml")
        directory=configs[0].parent
        model_paths["detection_model_dir" if suffix=="det" else "recognition_model_dir"]=directory
        component_items.extend([(f"{suffix}/{p.relative_to(directory).as_posix()}",p) for p in sorted(directory.rglob("*")) if p.is_file()])
    python=isolated_python(args.root/"preprocessing"/"environments"/"venv_t1_cpu",args.base_python)
    lock=args.root/"preprocessing"/"environments"/"t1_cpu.freeze.txt"
    lock_hash=install_requirements(python,["paddlepaddle==3.3.1","paddleocr==3.7.0","Pillow==12.1.0"],lock)
    version=subprocess.run([str(python),"-c","import paddle; print(paddle.__version__)"],check=True,capture_output=True,text=True).stdout.strip().splitlines()[-1]
    components=file_components(component_items)
    revision="paddleocr-3.7.0_paddlepaddle-3.3.1"
    write_json(receipt_path,{"source_revision":revision,"downloads":downloads,"components":components,"sdk_install_report":str(lock.with_suffix(".install-report.json"))})
    entry=make_entry("PP-OCRv6_medium_det+rec",python,model_paths,components,revision,"paddlepaddle",version,"paddleocr_pipeline",lock_hash)
    entry["environment_lock_file"]=str(lock.resolve())
    return entry


DEPTH_REVISION="a561b849ebae10a6f5ef49e26c83cbbcd36c71bf"
DEPTH_SMALL_WEIGHT_REVISION="03876f8651c73a60fe4c2c48294e09fcb6838fcf"
CLIP_REVISION="7ffa84b3bfa40c42ecc1c77147a855e69cb2dd40"


def prepare_torch_environment(args, name):
    python=isolated_python(args.root/"preprocessing"/"environments"/name,args.base_python)
    lock=args.root/"preprocessing"/"environments"/(name+".freeze.txt")
    install_requirements(python,["--index-url","https://download.pytorch.org/whl/cpu","torch==2.10.0","torchvision==0.25.0"],lock)
    return python,lock


def prepare_depth(args):
    model_dir=args.root/"models"/"depth_anything_v2_small"
    receipt_path=model_dir/"source_lock.json"
    old=previous_receipt(receipt_path)
    source_archive=args.root/"runtime"/"downloads"/("depth_anything_v2_"+DEPTH_REVISION+".zip")
    source_receipt=download(f"https://codeload.github.com/DepthAnything/Depth-Anything-V2/zip/{DEPTH_REVISION}",source_archive,old.get("source",{}).get("sha256"))
    extraction=model_dir/"source"
    safe_extract(source_archive,extraction)
    source=extraction/("Depth-Anything-V2-"+DEPTH_REVISION)
    checkpoint=model_dir/"depth_anything_v2_vits.pth"
    weight_receipt=download(f"https://huggingface.co/depth-anything/Depth-Anything-V2-Small/resolve/{DEPTH_SMALL_WEIGHT_REVISION}/depth_anything_v2_vits.pth",checkpoint,old.get("weight",{}).get("sha256"))
    python,lock=prepare_torch_environment(args,"venv_t3_cpu")
    lock_hash=install_requirements(python,["opencv-python-headless==4.13.0.92","numpy==2.3.5","Pillow==12.1.0"],lock)
    version=subprocess.run([str(python),"-c","import torch; print(torch.__version__)"],check=True,capture_output=True,text=True).stdout.strip()
    components=file_components([("checkpoint",checkpoint),*source_components(source)])
    write_json(receipt_path,{"source_revision":DEPTH_REVISION,"weight_revision":DEPTH_SMALL_WEIGHT_REVISION,"source":source_receipt,"weight":weight_receipt,"components":components})
    entry=make_entry("Depth-Anything-V2-Small",python,{"checkpoint":checkpoint,"source_dir":source},components,DEPTH_REVISION,"torch",version,"depth_anything_author_api",lock_hash)
    entry["environment_lock_file"]=str(lock.resolve())
    return entry


def prepare_yoloe(args):
    model_dir=args.root/"models"/"yoloe_26n_seg"
    receipt_path=model_dir/"source_lock.json"
    old=previous_receipt(receipt_path)
    checkpoint=model_dir/"yoloe-26n-seg.pt"
    weights=download("https://github.com/ultralytics/assets/releases/download/v8.4.0/yoloe-26n-seg.pt",checkpoint,old.get("weight",{}).get("sha256"))
    text_encoder=model_dir/"mobileclip2_b.ts"
    language=download("https://github.com/ultralytics/assets/releases/download/v8.4.0/mobileclip2_b.ts",text_encoder,old.get("language",{}).get("sha256"))
    clip_archive=args.root/"runtime"/"downloads"/("clip_"+CLIP_REVISION+".zip")
    clip_receipt=download(f"https://codeload.github.com/ultralytics/CLIP/zip/{CLIP_REVISION}",clip_archive,old.get("clip_source",{}).get("sha256"))
    extraction=model_dir/"clip_source"
    safe_extract(clip_archive,extraction)
    clip_source=extraction/("CLIP-"+CLIP_REVISION)
    prompt_path=model_dir/"cpu_scene_v1.json"
    prompt=json.loads((ROOT/"Design_v1_1_20261012"/"preprocessing"/"configs"/"prompt_sets"/"cpu_scene_v1.json").read_text("utf-8"))
    write_json(prompt_path,prompt)
    python,lock=prepare_torch_environment(args,"venv_t4_cpu")
    install_requirements(python,["ultralytics==8.4.175","Pillow==12.1.0",str(clip_source)],lock)
    embedding_path=model_dir/"cpu_scene_v1_embeddings.npz"
    # Explicit preparation step. Use official text encoder with its local file;
    # worker uses the saved array and never calls get_text_pe or downloads CLIP.
    code="import json,sys,torch; from ultralytics import YOLOE; from ultralytics.nn.text_model import MobileCLIPTS; torch.set_num_threads(2); m=YOLOE(sys.argv[1]); m.to('cpu'); labels=json.load(open(sys.argv[2],encoding='utf-8'))['labels']; m.model.clip_model=MobileCLIPTS(device=torch.device('cpu'),weight=sys.argv[3]); embeddings=m.model.get_text_pe(labels,cache_clip_model=True); m.set_classes(labels,embeddings); m.save_prompt_embeddings(sys.argv[4])"
    sys.path.insert(0,str(args.root/"engine/src"))
    from hir_manual.resource_monitor import monitor_process
    from hir_manual.tool_registry import load_profile
    profile=load_profile("cpu_probe_v1",args.root)
    profile.tools["_active"]={"timeout_seconds":profile.tools["T4_SEGMENTATION"]["timeout_seconds"]}
    measured=monitor_process([str(python),"-c",code,str(checkpoint.resolve()),str(prompt_path.resolve()),str(text_encoder.resolve()),str(embedding_path.resolve())],model_dir,profile,args.root/"runtime/preparation_logs/t4_text_embeddings",environment={"CUDA_VISIBLE_DEVICES":""})
    if measured.status != "completed":
        write_json(receipt_path,{"source_revision":"ultralytics-8.4.175_clip-"+CLIP_REVISION,"weight":weights,"language":language,"clip_source":clip_receipt,"preparation_status":measured.status,"text_embedding_preparation":measured.model_dump()})
        raise RuntimeError("Text embedding preparation "+measured.status+"; retain downloaded assets and retry without changing the model")
    # Freeze again after embedding preparation; incidental automatic installs
    # are captured here and prohibited by the offline worker audit hook.
    freeze=subprocess.run([str(python),"-m","pip","freeze","--all"],check=True,capture_output=True).stdout
    lock.write_bytes(freeze)
    version=subprocess.run([str(python),"-c","import torch; print(torch.__version__)"],check=True,capture_output=True,text=True).stdout.strip()
    tokenizer=clip_source/"clip"/"bpe_simple_vocab_16e6.txt.gz"
    if not tokenizer.is_file():
        raise ValueError("deployed CLIP tokenizer vocabulary missing")
    components=file_components([("checkpoint",checkpoint),("text_encoder",text_encoder),("tokenizer_vocabulary",tokenizer),("prompt_set",prompt_path),("text_embeddings",embedding_path),*source_components(clip_source,"clip_source")])
    revision="ultralytics-8.4.175_clip-"+CLIP_REVISION
    write_json(receipt_path,{"source_revision":revision,"weight":weights,"language":language,"clip_source":clip_receipt,"components":components,"sdk_install_report":str(lock.with_suffix(".install-report.json"))})
    entry=make_entry("YOLOE-26n-seg",python,{"checkpoint":checkpoint,"text_embeddings":embedding_path,"prompt_set":prompt_path,"text_encoder":text_encoder},components,revision,"torch",version,"ultralytics_yoloe_text",sha256(lock))
    entry["environment_lock_file"]=str(lock.resolve())
    return entry


if __name__ == "__main__":
    raise SystemExit(main())
