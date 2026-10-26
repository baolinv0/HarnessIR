"""Explicit provider boundaries; no implicit retries or unsupported settings."""
import base64
import json
import os
import uuid
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from .contracts import RetouchError,require

ALLOWED_MODELS={"gpt-image-2","gpt-image-2-2026-04-21"}
def settings():
    model=os.environ.get("HRE_RETOUCH_IMAGE_MODEL","gpt-image-2")
    require(model in ALLOWED_MODELS,"model_mismatch","本流程仅支持 GPT Image 2")
    return {"analysis_configured":bool(os.environ.get("HRE_RETOUCH_VLM_BASE_URL") and os.environ.get("HRE_RETOUCH_VLM_MODEL")),
            "image_configured":bool(os.environ.get("OPENAI_API_KEY")),
            "analysis_model":os.environ.get("HRE_RETOUCH_VLM_MODEL"),
            "image_model":model,"max_generations":3}

def image_data(path):
    return "data:image/png;base64,"+base64.b64encode(Path(path).read_bytes()).decode()

def _post(url,body,headers,timeout=600,on_response=None):
    try:
        with urlopen(Request(url,data=body,headers=headers,method="POST"),timeout=timeout) as r:
            text=r.read().decode("utf-8")
            if on_response:on_response({"http_status":r.status,"raw_response":text})
            return json.loads(text)
    except HTTPError as exc:
        if on_response:on_response({"http_status":exc.code,"raw_response":exc.read().decode("utf-8",errors="replace")})
        # Do not leak endpoint/key or arbitrary provider response text to the UI.
        raise RetouchError("provider_http_error",f"模型接口返回 HTTP {exc.code}") from None
    except (URLError,TimeoutError,OSError,json.JSONDecodeError):
        raise RetouchError("provider_connection_error","模型请求失败或结果未知；请检查本地服务日志") from None

def analyze(request,on_response=None):
    require(settings()["analysis_configured"],"analysis_unconfigured","未配置视觉分析接口；可以导出本步任务并导入 Agent 分析")
    content=[{"type":"text","text":json.dumps(request["context"],ensure_ascii=False)}]
    for item in request["images"]:
        content+=[{"type":"text","text":"Image role: "+item["role"]},{"type":"image_url","image_url":{"url":image_data(item["path"])}}]
    body={"model":os.environ["HRE_RETOUCH_VLM_MODEL"],"messages":[{"role":"system","content":request["instruction"]},{"role":"user","content":content}],"response_format":{"type":"json_object"}}
    headers={"Content-Type":"application/json"}
    key=os.environ.get("HRE_RETOUCH_VLM_API_KEY",os.environ.get("OPENAI_API_KEY",""))
    if key: headers["Authorization"]="Bearer "+key
    response=_post(os.environ["HRE_RETOUCH_VLM_BASE_URL"].rstrip("/")+"/chat/completions",json.dumps(body).encode(),headers,on_response=on_response)
    text=response["choices"][0]["message"]["content"]
    try: payload=json.loads(text)
    except (ValueError,TypeError): raise RetouchError("analysis_json_invalid","分析接口未返回合法 JSON") from None
    if isinstance(payload,dict) and payload.get("error"): raise RetouchError("analysis_reported_error","分析模型未能实际观察输入或报告错误")
    return payload,{"provider":"vlm_api","model":response.get("model",body["model"]),"usage":response.get("usage"),"response_id":response.get("id")}

def multipart_edit(request):
    """Return multipart body for a real ordered A/B request; easily testable."""
    boundary="hre-"+uuid.uuid4().hex;parts=[]
    for key,value in request["settings"].items():
        parts.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n").encode())
    parts.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"prompt\"\r\n\r\n{request['prompt']}\r\n").encode())
    require([x["role"] for x in request["images"]]==["source","appearance_reference"],"image_roles","编辑必须输入原始 A 与参考 B")
    for index,item in enumerate(request["images"]):
        data=Path(item["path"]).read_bytes()
        name="source.png" if index==0 else "reference.png"
        parts.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"image[]\"; filename=\"{name}\"\r\nContent-Type: image/png\r\n\r\n").encode()+data+b"\r\n")
    parts.append((f"--{boundary}--\r\n").encode())
    return b"".join(parts),"multipart/form-data; boundary="+boundary

def edit(request,on_response=None):
    require(settings()["image_configured"],"image_unconfigured","未配置 GPT Image 2 接口；请导出编辑任务，或导入实际生成图")
    require(request["settings"].get("model") in ALLOWED_MODELS,"model_mismatch","编辑模型不匹配")
    require(not set(request["settings"]) - {"model","n","size","quality","output_format","background"},"unsupported_setting","存在未支持的图像参数")
    body,mime=multipart_edit(request)
    response=_post(os.environ.get("OPENAI_BASE_URL","https://api.openai.com/v1").rstrip("/")+"/images/edits",body,
                   {"Content-Type":mime,"Authorization":"Bearer "+os.environ["OPENAI_API_KEY"]},on_response=on_response)
    rows=response.get("data",[])
    if len(rows)!=1:
        err=RetouchError("generation_count","接口没有返回恰好一张图；全部原始回执已保存")
        err.actual_generation_count=len(rows)
        raise err
    require(bool(rows[0].get("b64_json")),"image_response","接口未返回 base64 图像")
    try: data=base64.b64decode(rows[0]["b64_json"],validate=True)
    except ValueError: raise RetouchError("image_response","接口图像编码无效") from None
    return data,{"provider":"images_api","model":request["settings"]["model"],"model_identity":"requested_exact_model","usage":response.get("usage"),"created":response.get("created"),"actual_generation_count":len(rows)}
