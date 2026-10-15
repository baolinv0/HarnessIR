"""Offline single-job model worker. Invoked by an isolated Python executable."""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from preprocessing.workers.common import WorkerFailure,enforce_offline


def execute(job_path,out):
    from PIL import Image
    from preprocessing.adapters.common import canonical_json,sha256,write_json
    started=time.perf_counter()
    job=json.loads(job_path.read_text("utf-8"))
    config=json.loads((job_path.parent/"runner_config.json").read_text("utf-8"))
    entry=config["registry_entry"]
    profile=config["profile"]
    contract=job["cache_contract"]
    parameters=contract["parameters"]
    aliases={"PP-OCRv6_medium_det+PP-OCRv6_medium_rec":"PP-OCRv6_medium_det+rec","SCRFD_det_10g.onnx":"SCRFD_det_10g"}
    if entry.get("model_name") != aliases.get(parameters.get("model"),parameters.get("model")):
        raise WorkerFailure("unavailable","registry model differs from frozen profile; no substitution")
    for field in ("implementation","device","precision"):
        if entry.get("backend",{}).get(field)!=parameters.get(field):
            raise WorkerFailure("unavailable","registry backend differs from frozen profile: "+field)
    if hashlib.sha256(canonical_json(contract)).hexdigest()!=job["cache_key"]:
        raise WorkerFailure("unavailable","cache key does not match frozen contract")
    if job["protocol_version"]!="1.1" or job["tool_id"]!=contract["tool_id"]:
        raise WorkerFailure("unavailable","invalid job protocol or tool identity")
    if not profile.get("offline",True) or profile.get("auto_download",False) or profile.get("auto_install",False):
        raise WorkerFailure("unavailable","runtime profile must be offline without install/download")
    if parameters.get("batch_size")!=1 or parameters.get("cpu_threads")!=profile.get("cpu_threads",2):
        raise WorkerFailure("unavailable","worker batch/thread configuration differs from frozen profile")
    if parameters.get("device")=="cpu":
        # The author depth API chooses its input device from CUDA availability.
        # Hide CUDA before framework imports so an explicit CPU profile stays CPU.
        os.environ["CUDA_VISIBLE_DEVICES"]=""
    if entry["model_bundle_sha256"]!=contract["model_bundle_sha256"] or entry["backend"]!=contract["backend"]:
        raise WorkerFailure("unavailable","registry differs from frozen cache contract")
    components=[{"name":c["name"],"sha256":c["sha256"]} for c in entry["components"]]
    if hashlib.sha256(canonical_json(components)).hexdigest()!=entry["model_bundle_sha256"]:
        raise WorkerFailure("model_missing","model bundle hash disagreement")
    for component in entry["components"]:
        path=Path(component["path"])
        if not path.is_file() or sha256(path)!=component["sha256"]:
            raise WorkerFailure("model_missing",f"model component missing or changed: {component['name']}")
    relative=Path(job["canonical_path"])
    canonical=(job_path.parent/relative).resolve()
    if relative.is_absolute() or ".." in relative.parts or not canonical.is_relative_to(job_path.parent.resolve()):
        raise WorkerFailure("unavailable","unsafe canonical path")
    if sha256(canonical)!=contract["canonical_sha256"]:
        raise WorkerFailure("unavailable","canonical image hash mismatch")
    image=Image.open(canonical)
    image.load()
    if image.mode!="RGB":
        raise WorkerFailure("unavailable","canonical image must be RGB")
    if image.size!=(config["source_width"],config["source_height"]):
        raise WorkerFailure("unavailable","canonical source geometry mismatch")
    implementation=entry["backend"]["implementation"]
    supported={"T1_OCR":{"paddleocr_pipeline"},"T2_FACE":{"insightface_scrfd_detector_only"},"T3_DEPTH":{"depth_anything_author_api"},"T4_SEGMENTATION":{"meta_sam3_image_api","ultralytics_yoloe_text"}}
    if implementation not in supported[job["tool_id"]]:
        raise WorkerFailure("unavailable","unknown frozen tool implementation")
    modules={"T1_OCR":"t1_ocr","T2_FACE":"t2_face","T3_DEPTH":"t3_depth","T4_SEGMENTATION":"t4_sam3" if implementation=="meta_sam3_image_api" else "t4_yoloe"}
    result=importlib.import_module("preprocessing.workers."+modules[job["tool_id"]]).run(image,entry,parameters,out)
    if sha256(canonical)!=contract["canonical_sha256"]:
        raise WorkerFailure("unavailable","worker changed canonical image")
    width,height=result["tool_size"]
    checkpoint=entry.get("artifact_paths",{}).get("checkpoint")
    evidence={"protocol_version":"1.1","tool_id":job["tool_id"],"input_sha256":contract["canonical_sha256"],"status":"ok",
              "model_name":entry["model_name"],"checkpoint_sha256":sha256(checkpoint) if checkpoint else None,
              "source_width":image.width,"source_height":image.height,"tool_width":width,"tool_height":height,
              "coordinates":"canonical_norm","source_to_tool":result["source_to_tool"],"detections":result["detections"],"assets":result["assets"],"data":result["data"],"error":None,
              "image_id":job["image_id"],"original_sha256":config["original_sha256"],"evidence_profile_id":job["evidence_profile_id"],
              "model_bundle_sha256":entry["model_bundle_sha256"],"components":components,"backend":entry["backend"],
              "parameters_sha256":hashlib.sha256(canonical_json(parameters)).hexdigest(),"cache_key":job["cache_key"],"views":result["views"],"quality_warnings":result["warnings"],
              "elapsed_ms":(time.perf_counter()-started)*1000,"peak_rss_mb":None,"formal_eligible":bool(profile.get("formal_eligible",False))}
    write_json(out,"evidence.json",evidence)
    write_json(out,"worker_done.json",{"protocol_version":"1.1","job_id":job["job_id"],"status":"ok","evidence_sha256":sha256(out/"evidence.json"),"artifact_hashes":[{"path":a["path"],"sha256":a["sha256"]} for a in evidence["assets"]]})
    return evidence


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job",required=True,type=Path)
    parser.add_argument("--out",required=True,type=Path)
    args=parser.parse_args(argv)
    args.out=args.out.resolve()
    args.out.mkdir(parents=True,exist_ok=True)
    try:
        if not args.job.is_absolute():
            raise WorkerFailure("unavailable","--job must be an absolute JSON path")
        enforce_offline(2)
        execute(args.job.resolve(),args.out)
        return 0
    except Exception as error:
        if isinstance(error,WorkerFailure):
            code=error.code
        elif isinstance(error,(ImportError,ModuleNotFoundError)):
            code="import_error"
        elif isinstance(error,FileNotFoundError):
            code="model_missing"
        elif isinstance(error,MemoryError) or "out of memory" in str(error).lower() or "bad allocation" in str(error).lower():
            code="oom"
        elif isinstance(error,TimeoutError):
            code="timeout"
        else:
            code="unavailable"
        failure={"protocol_version":"1.1","status":"error","code":code,"message":str(error),"exception_type":type(error).__name__}
        (args.out/"worker_error.json").write_text(json.dumps(failure,ensure_ascii=False,allow_nan=False),encoding="utf-8")
        (args.out/"error.json").write_text(json.dumps(failure,ensure_ascii=False,allow_nan=False),encoding="utf-8")
        (args.out/"worker_traceback.log").write_text(traceback.format_exc(),encoding="utf-8")
        print(json.dumps(failure,ensure_ascii=False),file=sys.stderr)
        return 1


if __name__=="__main__":
    raise SystemExit(main())
