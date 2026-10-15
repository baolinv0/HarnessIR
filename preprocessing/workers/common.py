from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path


class WorkerFailure(RuntimeError):
    def __init__(self,code,message):
        self.code=code
        super().__init__(message)


def enforce_offline(threads=2):
    # Set before importing any framework or SDK. The audit hook also catches
    # requests/hub/urllib and subprocess-based auto-install/download attempts.
    settings={"HF_HUB_OFFLINE":"1","TRANSFORMERS_OFFLINE":"1","HF_DATASETS_OFFLINE":"1",
              "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK":"True","PADDLE_PDX_MODEL_SOURCE":"BOS",
              "YOLO_OFFLINE":"true","YOLO_AUTOINSTALL":"false","YOLO_VERBOSE":"false",
              "OMP_NUM_THREADS":str(threads),"MKL_NUM_THREADS":str(threads),"OPENBLAS_NUM_THREADS":str(threads),
              "NUMEXPR_NUM_THREADS":str(threads),"VECLIB_MAXIMUM_THREADS":str(threads)}
    os.environ.update(settings)
    def audit(event,args):
        if event in ("socket.connect","socket.getaddrinfo","socket.sendto","socket.sendmsg"):
            raise WorkerFailure("unavailable","runtime network is disabled")
        if event in ("subprocess.Popen","os.system","os.posix_spawn"):
            command=args[1] if event=="subprocess.Popen" else args[0]
            tokens=[str(part).lower() for part in command] if isinstance(command,(list,tuple)) else shlex.split(str(command).lower())
            names=[Path(part).stem for part in tokens]
            if any(name in ("pip","pip3","uv","conda","curl","wget","git","powershell","pwsh") for name in names) or "-m pip" in " ".join(tokens):
                raise WorkerFailure("unavailable","runtime package installation is disabled")
    sys.addaudithook(audit)


def require_artifact(entry,key,directory=False):
    value=entry.get("artifact_paths",{}).get(key)
    path=Path(value) if value else None
    if path is None or (not path.is_dir() if directory else not path.is_file()):
        raise WorkerFailure("model_missing",f"required offline artifact unavailable: {key}")
    return path.resolve()


def assert_framework_version(actual,entry):
    if actual!=entry["backend"]["framework_version"]:
        raise WorkerFailure("unavailable",f"framework version differs from registry: actual {actual}")


def require_torch_device(torch,parameters):
    device=parameters["device"]
    if device!="cpu" and (not device.startswith("cuda") or not torch.cuda.is_available()):
        raise WorkerFailure("unavailable","frozen GPU backend unavailable; no CPU substitution")
    torch.set_num_threads(parameters["cpu_threads"])
    torch.set_num_interop_threads(1)
    if device.startswith("cuda"):
        torch.backends.cuda.matmul.allow_tf32=False
        torch.backends.cudnn.allow_tf32=False
    return device


def source_view(image,parameters):
    from PIL import Image
    limit=parameters.get("source_view_long_edge")
    if limit and max(image.size)>limit:
        ratio=limit/max(image.size)
        return image.resize((max(1,round(image.width*ratio)),max(1,round(image.height*ratio))),Image.Resampling.BILINEAR)
    return image.copy()


def serializable(value):
    import numpy as np
    if isinstance(value,dict):
        return {str(k):serializable(v) for k,v in value.items() if k not in ("input_img","output_img","vis_font")}
    if isinstance(value,(list,tuple)):
        return [serializable(v) for v in value]
    if isinstance(value,np.ndarray):
        return value.tolist()
    if isinstance(value,np.generic):
        return value.item()
    if value is None or isinstance(value,(str,int,float,bool)):
        return value
    return str(type(value).__name__)


def result_dict(result):
    value=getattr(result,"json",result)
    if callable(value):
        value=value()
    if isinstance(value,str):
        import json
        value=json.loads(value)
    return value.get("res",value)
