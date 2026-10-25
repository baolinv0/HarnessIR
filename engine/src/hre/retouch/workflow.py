"""Persisted, visible stages. Imported Agent results and API calls stay distinct."""
import base64
from copy import deepcopy
from datetime import datetime,timezone
import io
import json
import math
from pathlib import Path
import re
import threading
import uuid
from PIL import Image,ImageOps,ImageCms
from .contracts import (RetouchError,require,validate_analysis,validate_contract,validate_regions,
                        decide_verification,compile_prompt,validate_reference_composition)
from . import evidence,providers,prompts

STAGES=[("inputs","输入与配对"),("diagnose","参考风格诊断"),("evidence","区域与外观证据"),("compose","目标与编辑提示"),("edit","GPT Image 2 编辑"),("verify","独立逐项验证"),("refine","反馈修正"),("report","过程与交付")]
ACCEPTANCE_VERSION="reference_retouch_delivery_v2"

def delivery_requirements(value):
    """Validate once at case creation; no defaults are retrofitted to old cases."""
    require(isinstance(value,dict) and not set(value)-{
        "require_native_source_resolution","minimum_native_size","require_detail_pass"},
        "delivery_requirements_invalid","交付条件必须是对象，且只能包含已支持的字段")
    result={"require_native_source_resolution":True,"require_detail_pass":False,**deepcopy(value)}
    for key in ("require_native_source_resolution","require_detail_pass"):
        require(type(result[key]) is bool,"delivery_requirements_invalid",key+" 必须是布尔值")
    if "minimum_native_size" in result:
        size=result["minimum_native_size"]
        require(isinstance(size,list) and len(size)==2 and all(type(x) is int and x>0 for x in size),
                "delivery_requirements_invalid","minimum_native_size 必须是两个正整数 [宽,高]")
    return result
def now():return datetime.now(timezone.utc).isoformat()
def write_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    data=json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)
    tmp=path.with_suffix(".tmp");tmp.write_text(data,encoding="utf-8");tmp.replace(path)
def read_json(path):return json.loads(Path(path).read_text(encoding="utf-8"))
def decode_image(value):
    require(isinstance(value,str) and value.startswith("data:image/") and "," in value,"image_missing","请选择 A/B 图像")
    try:data=base64.b64decode(value.split(",",1)[1],validate=True)
    except ValueError:raise RetouchError("image_encoding","图像编码无效") from None
    require(len(data)<=50_000_000,"image_large","单张图像不能超过 50 MB")
    return data

def canonical(data,path):
    try:
        with Image.open(io.BytesIO(data)) as original:
            require(original.width*original.height<=80_000_000,"image_large","图像像素过多")
            im=ImageOps.exif_transpose(original)
            profile=original.info.get("icc_profile")
            if profile:
                im=ImageCms.profileToProfile(im,ImageCms.ImageCmsProfile(io.BytesIO(profile)),ImageCms.createProfile("sRGB"),outputMode="RGB")
                policy="ICC converted to sRGB"
            else:im=im.convert("RGB");policy="assumed sRGB; input has no ICC profile"
            im.save(path,format="PNG")
            return im.size,policy
    except (OSError,ValueError,ImageCms.PyCMSError):
        raise RetouchError("image_invalid","图像无法解码或色彩配置不受支持") from None

def prepare_canvas(source,target):
    with Image.open(source) as im:
        w,h=im.size
        require(max(w/h,h/w)<=3,"aspect_unsupported","首版支持不超过 3:1 的图像；请提供明确裁切策略")
        scale=min(1,3808/max(w,h),math.sqrt(8_100_000/(w*h)))
        if w*h*scale*scale<655360:scale=math.sqrt(655360/(w*h))*1.02
        cw,ch=round(w*scale),round(h*scale)
        ow,oh=math.ceil(cw/16)*16,math.ceil(ch/16)*16
        require(max(ow,oh)<=3840 and ow*oh<=8294400,"canvas_unsupported","无法规划合法输出画布")
        resized=im.resize((cw,ch),Image.Resampling.LANCZOS)
        canvas=Image.new("RGB",(ow,oh));canvas.paste(resized,(0,0))
        if ow>cw:canvas.paste(resized.crop((cw-1,0,cw,ch)).resize((ow-cw,ch)),(cw,0))
        if oh>ch:canvas.paste(canvas.crop((0,ch-1,ow,ch)).resize((ow,oh-ch)),(0,ch))
        canvas.save(target)
        return {"source_size":[w,h],"content_size":[cw,ch],"canvas_size":[ow,oh],"policy":"aspect-preserving scale then right/bottom edge pad"}

class Workbench:
    def __init__(self,root):
        self.root=Path(root).resolve();self.root.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock()
    def _dir(self,id):
        require(isinstance(id,str) and re.fullmatch(r"[A-Za-z0-9_-]{1,64}",id),"case_id","无效案例 ID")
        p=self.root/id;require(p.is_dir(),"case_missing","案例不存在");return p
    def _load(self,id):return read_json(self._dir(id)/"state.json")
    def _save(self,c):
        c["updated_at"]=now();write_json(self._dir(c["id"])/"state.json",c)
        return self._view(c)
    def _event(self,c,stage,kind,message,provenance=None):
        c["events"].append({"stage":stage,"kind":kind,"message":message,"time":now(),"provenance":provenance})
    def _image_size(self,c,url):
        """Read local PNG bytes, never infer native resolution from a resized view."""
        if not isinstance(url,str) or not url.startswith(f"/api/cases/{c['id']}/assets/"):return None
        name=url.rsplit("/",1)[-1]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+\.png",name):return None
        assets=self._dir(c["id"])/"assets";path=(assets/name).resolve()
        if not path.is_relative_to(assets.resolve()) or not path.is_file():return None
        try:
            with Image.open(path) as image:
                image.load();return list(image.size)
        except (OSError,ValueError):return None
    def _delivery_assessment(self,c,round=None,verification=None,source_result=False):
        round=round or (c["rounds"][-1] if c["rounds"] else {})
        native_url=c["images"]["source"]["url"] if source_result else round.get("native_url")
        delivered_url=c["images"]["source"]["url"] if source_result else round.get("candidate_url")
        native=self._image_size(c,native_url);delivered=self._image_size(c,delivered_url)
        frozen=c.get("acceptance_version")==ACCEPTANCE_VERSION
        assessment={"requirements_frozen":frozen,"status":"not_frozen" if not frozen else "pending",
                    "native_size":native,"delivered_size":delivered,"required_native_size":None,
                    "size_status":"not_frozen" if not frozen else "pending",
                    "detail_preservation":"not_frozen" if not frozen else "not_required","reasons":[]}
        if not frozen:
            assessment["reasons"]=["历史案例未冻结独立交付门槛；保留当时验收结论，尺寸仅作信息展示"]
            return assessment
        requirements=c["delivery_requirements"]
        required=list(requirements.get("minimum_native_size",[1,1]))
        if requirements["require_native_source_resolution"]:
            source=c["geometry"]["source_size"]
            required=[max(required[i],source[i]) for i in range(2)]
        assessment["required_native_size"]=required
        if native is None:
            assessment.update(size_status="uncertain",status="uncertain" if native_url else "pending")
            assessment["reasons"].append("尚无可核对的原生图像文件")
        elif any(native[i]<required[i] for i in range(2)):
            assessment.update(size_status="fail",status="fail")
            assessment["reasons"].append("原生结果低于冻结的尺寸要求；对比图插值不能补足原始细节")
        else:assessment.update(size_status="pass",status="pass")
        declared=round.get("candidate_geometry",{}).get("native_size") if not source_result else native
        if native is not None and declared is not None and native!=declared:
            assessment.update(size_status="fail",status="fail")
            assessment["reasons"].append("原生文件与几何记录的尺寸不一致，需要核对结果来源")
        if requirements["require_detail_pass"]:
            detail="pass" if source_result else (verification or {}).get("detail_preservation","uncertain")
            assessment["detail_preservation"]=detail
            if detail!="pass":
                if detail=="fail":assessment["status"]="fail"
                elif assessment["status"] not in ("fail","pending"):assessment["status"]="uncertain"
                assessment["reasons"].append("源细节保真未明确通过；自然度或外观通过不能替代该项")
        if assessment["status"]=="pass":assessment["reasons"].append("本次已冻结的交付条件通过；未要求的细节真实性不作认证")
        return assessment
    def _view(self,c):
        c=deepcopy(c)
        c.setdefault("appearance_status",(c.get("verification") or {}).get("global_status"))
        if not c.get("delivery_assessment"):
            c["delivery_assessment"]=self._delivery_assessment(c,source_result=c.get("status")=="already_satisfied")
        for row in c["rounds"]:
            row.setdefault("appearance_status",(row.get("verification") or {}).get("global_status"))
            if not row.get("delivery_assessment"):row["delivery_assessment"]=self._delivery_assessment(c,row,row.get("verification"))
        complete={"inputs":True,"diagnose":c["analysis"] is not None,"evidence":c["evidence"] is not None,
                  "compose":c["contract"] is not None,"edit":c["images"]["candidate"] is not None,
                  "verify":c["verification"] is not None,"refine":c.get("refinement") is not None,
                  "report":c["status"] in ("accepted","task_not_met","already_satisfied","uncertain","delivery_not_met")}
        c["stages"]=[{"id":k,"title":title,"status":"completed" if complete[k] else ("needs_input" if c.get("waiting_stage")==k else ("ready" if c["phase"]==k else "pending")),"summary":c.get("summaries",{}).get(k,"")} for k,title in STAGES]
        return c
    def get(self,id):return self._view(self._load(id))
    def list(self):
        result=[]
        for p in sorted(self.root.glob("*/state.json"),key=lambda p:p.stat().st_mtime,reverse=True):
            c=read_json(p);result.append({k:c.get(k) for k in ("id","brief","status","created_at","source_name","reference_name")})
        return result
    def create(self,request):
        with self.lock:
            require(isinstance(request.get("brief"),str) and request["brief"].strip(),"brief_missing","请写明希望迁移的外观")
            requirements=delivery_requirements(request["delivery_requirements"] if "delivery_requirements" in request else {})
            id="case_"+uuid.uuid4().hex[:12];p=self.root/id;p.mkdir();(p/"assets").mkdir()
            images={};policies={}
            try:
                for role,key in (("source","source_data"),("reference","reference_data")):
                    data=decode_image(request.get(key));(p/"assets"/(role+".original")).write_bytes(data)
                    size,policy=canonical(data,p/"assets"/(role+".png"));policies[role]=policy
                    images[role]={"url":f"/api/cases/{id}/assets/{role}.png","width":size[0],"height":size[1],"name":request.get(role+"_name",role)}
                plan=prepare_canvas(p/"assets/source.png",p/"assets/source_work.png")
            except Exception:
                # Preserve partially supplied files for diagnosis but never list as a valid case.
                raise
            images["candidate"]=None
            c={"id":id,"schema_version":"reference_retouch_v1","created_at":now(),"brief":request["brief"].strip(),
               "acceptance_version":ACCEPTANCE_VERSION,"delivery_requirements":requirements,
               "appearance_status":None,"delivery_assessment":None,
               "source_name":request.get("source_name","A"),"reference_name":request.get("reference_name","B"),
               "status":"ready","phase":"diagnose","images":images,"colour_policy":policies,"geometry":plan,
               "regions":[],"analysis":None,"evidence":None,"contract":None,"prompt":None,"verification":None,
               "refinement":None,"rounds":[],"events":[],"calls":{"analysis":0,"images":0},"waiting_stage":None,"summaries":{},"pending_image":None}
            self._event(c,"inputs","canonicalized","已保存原始 A/B、显示域副本及画布；未执行任何模型")
            return self._save(c)
    def regions(self,id,regions):
        with self.lock:
            c=self._load(id);require(c["contract"] is None,"contract_frozen","目标已冻结；新区域需创建新案例")
            c["regions"]=validate_regions(regions);c["evidence"]=None
            self._event(c,"evidence","regions_updated","A/B 分别圈选，等待重新计算区域证据")
            return self._save(c)
    def _images(self,c,working=False,include_candidate=False):
        p=self._dir(c["id"])/"assets"
        rows=[{"role":"source","path":str(p/("source_work.png" if working else "source.png")),"url":c["images"]["source"]["url"]},
              {"role":"appearance_reference","path":str(p/"reference.png"),"url":c["images"]["reference"]["url"]}]
        if include_candidate and c["images"]["candidate"]:
            rows.append({"role":"candidate","path":str(p/Path(c["images"]["candidate"]["url"]).name),"url":c["images"]["candidate"]["url"]})
        return rows
    def _evidence_refs(self,c):
        return {"A","B","source","appearance_reference","evidence:source","evidence:reference"}|{"evidence:"+r["id"] for r in c["regions"]}
    def _check_refs(self,c,items,extra=()):
        allowed=self._evidence_refs(c)|set(extra)
        for row in items:
            refs=row.get("evidence_refs",[])
            require(isinstance(refs,list) and all(isinstance(x,str) for x in refs) and set(refs)<=allowed,
                    "unsupported_evidence","引用了本案例没有提供的图像或区域证据")
    def export(self,id,stage):
        c=self._load(id)
        if stage=="edit":
            require(c["contract"] is not None and c["prompt"],"contract_required","先编译并冻结目标")
            return {"stage":"edit","case_id":id,"prompt":c["prompt"],"images":self._images(c,working=True),
                    "geometry":c["geometry"],"settings":{"model":providers.settings()["image_model"],"n":1,"size":"%dx%d"%tuple(c["geometry"]["canvas_size"]),"quality":"high","output_format":"png"}}
        require(stage in prompts.NAMES,"stage_invalid","未知阶段")
        if stage in ("verify","refine"):
            require(c["images"]["candidate"] is not None and c["contract"] is not None,"candidate_required","需要实际候选图与目标合同")
        context={"brief":c["brief"],"regions":c["regions"],"colour_policy":c["colour_policy"],"available_evidence_refs":sorted(self._evidence_refs(c))}
        if stage in ("compose","refine"):context.update(analysis=c["analysis"],evidence=c["evidence"])
        if stage in ("verify","refine"):context["evaluation_contract"]=deepcopy(c["contract"])
        if stage=="verify":
            context.update(candidate_attribute_deltas=c.get("candidate_attribute_deltas",[]),evidence=c["evidence"],geometry=c["geometry"],
                           candidate_geometry=deepcopy(c["rounds"][-1].get("candidate_geometry",{})),
                           protection_check_items=c["contract"]["protected_facts"])
            context["available_evidence_refs"].append("C")
            if c.get("acceptance_version")==ACCEPTANCE_VERSION:
                context.update(acceptance_version=ACCEPTANCE_VERSION,delivery_requirements=deepcopy(c["delivery_requirements"]),
                               delivery_assessment=self._delivery_assessment(c))
                context["available_evidence_refs"].append("candidate_native")
        if stage=="refine":context.update(verification=c["verification"],remaining_generations=3-c["calls"]["images"])
        strict=c.get("acceptance_version")==ACCEPTANCE_VERSION
        if strict:context["acceptance_version"]=ACCEPTANCE_VERSION
        instruction=prompts.instruction(stage,strict_reference=strict);images=self._images(c,include_candidate=stage in ("verify","refine"))
        if stage=="verify" and c.get("acceptance_version")==ACCEPTANCE_VERSION:
            native=c["rounds"][-1].get("native_url")
            if native:
                images.append({"role":"candidate_native","path":str(self._dir(id)/"assets"/Path(native).name),"url":native})
            instruction+=(" Inspect candidate_native at native resolution against A for authentic visible detail. "
                          "Record detail_preservation as pass, fail or uncertain; if original high-frequency detail cannot be certified, use uncertain. "
                          "Naturalness and appearance success do not certify source-detail authenticity. The controller checks native dimensions separately.")
        return {"stage":stage,"case_id":id,"instruction":instruction,"context":context,"images":images}
    def import_stage(self,id,stage,payload,provenance="manual_agent",observation=None):
        with self.lock:
            c=self._load(id)
            require(stage in prompts.NAMES,"stage_invalid","未知导入阶段")
            require(provenance in ("manual_agent","human","vlm_api"),"provenance_invalid","请明确观察来自 Agent、人工或真实接口")
            if stage=="diagnose":
                require(c["contract"] is None,"contract_frozen","目标冻结后不能覆盖诊断")
                c["analysis"]=validate_analysis(payload,strict_reference=c.get("acceptance_version")==ACCEPTANCE_VERSION)
                self._check_refs(c,c["analysis"]["reference_profile"]+c["analysis"]["candidate_deltas"])
                c["phase"]="evidence";c["status"]="ready"
                c["summaries"][stage]="源图、参考外观与可迁移差异已分别记录"
            elif stage=="compose":
                require(c["analysis"] is not None,"analysis_required","先完成参考诊断")
                require(c["contract"] is None,"contract_frozen","目标合同已经冻结，不能覆盖")
                value=validate_contract(payload.get("contract",payload));self._check_refs(c,value["targets"])
                if c.get("acceptance_version")==ACCEPTANCE_VERSION:validate_reference_composition(c["analysis"],value)
                def fact_text(item):return item if isinstance(item,str) else str(item.get("description",item))
                observed={fact_text(item) for item in c["analysis"]["source_diagnosis"]["protected_facts"]}
                protected={fact_text(item) for item in value["protected_facts"]}
                require(observed<=protected,"source_protection_missing","目标合同遗漏了诊断中已经明确的源图保护事实")
                if value["overall_status"] in ("insufficient_evidence","preference_conflict"):
                    c["contract_draft"]=value;c["status"]="needs_review";c["phase"]="compose"
                else:c["contract"]=value
                if value["overall_status"]=="already_satisfied":
                    c["status"]="already_satisfied";c["phase"]="report";c["result_url"]=c["images"]["source"]["url"]
                    if c.get("acceptance_version")==ACCEPTANCE_VERSION:
                        c["appearance_status"]="already_satisfied";c["delivery_assessment"]=self._delivery_assessment(c,source_result=True)
                        if c["delivery_assessment"]["status"]!="pass":c["status"]="delivery_not_met"
                elif value["overall_status"]=="ready_to_edit":c["prompt"]=compile_prompt(c["contract"]);c["phase"]="edit";c["status"]="ready"
                c["summaries"][stage]=(f"已冻结 {len(value['targets'])} 个目标；保留参考依据与验收标准" if c["contract"] else "目标草案证据不足，尚未冻结")
            elif stage=="verify":
                require(c["images"]["candidate"] is not None and c["contract"] is not None,"candidate_required","请先执行或导入实际候选")
                require(c["phase"]=="verify" and not c.get("pending_image") and c["status"] not in ("accepted","already_satisfied"),
                        "verification_stage","当前没有已收到且等待验证的新候选；先核对未完成请求")
                if c.get("acceptance_version")==ACCEPTANCE_VERSION and "detail_preservation" in payload:
                    require(payload["detail_preservation"] in ("pass","fail","uncertain"),"detail_preservation_invalid","细节检查必须是 pass、fail 或 uncertain")
                result=decide_verification(c["contract"],payload,strict_reference=c.get("acceptance_version")==ACCEPTANCE_VERSION);v=deepcopy(payload)
                self._check_refs(c,v["target_results"]+v["preservation_checks"]+v["artifact_checks"],extra={"C","candidate_native"})
                v["reported_global_status"]=v.get("global_status");v["global_status"]=result
                c["verification"]=v;c["rounds"][-1]["verification"]=v;c["rounds"][-1]["status"]=result
                c["phase"]="report" if result in ("accept","uncertain") else "refine"
                c["status"]={"accept":"accepted","uncertain":"uncertain"}.get(result,"needs_revision")
                if c.get("acceptance_version")==ACCEPTANCE_VERSION:
                    c["appearance_status"]=result;c["delivery_assessment"]=self._delivery_assessment(c,verification=v)
                    c["rounds"][-1].update(appearance_status=result,delivery_assessment=deepcopy(c["delivery_assessment"]))
                    if result=="accept" and c["delivery_assessment"]["status"]!="pass":
                        c["status"]="delivery_not_met";c["phase"]="report";c["rounds"][-1]["status"]="delivery_not_met"
                        self._event(c,"verify","delivery_not_met","外观检查通过，但冻结交付条件未满足；不以重复采样代替能力核对")
                if c["calls"]["images"]>=3 and result!="accept":c["status"]="task_not_met";c["phase"]="report"
                c["summaries"][stage]="逐目标判定："+result
            else:
                require(c["verification"] is not None,"verification_required","先完成独立验证")
                require(c["status"] not in ("accepted","already_satisfied","delivery_not_met"),"already_complete","当前案例已结束；交付能力不足需要新案例明确新要求")
                require(isinstance(payload,dict) and payload.get("action") in ("revise","stop","needs_review"),"refinement_invalid","修订需要 action")
                require("contract" not in payload and "targets" not in payload,"contract_frozen","反馈不能修改冻结目标")
                c["refinement"]=deepcopy(payload)
                if payload["action"]=="revise":
                    require(c["calls"]["images"]<3,"budget_exhausted","图像预算已用完")
                    require(bool(payload.get("correction")) and bool(payload.get("feedback_refs")),"refinement_unsupported","修正必须指出具体问题与验证依据")
                    known={t["target_id"] for t in c["contract"]["targets"]}
                    require(set(payload.get("changed_target_ids",[]))<=known,"refinement_targets","修正包含未知目标")
                    actionable={"verification:"+row["target_id"] for row in c["verification"]["target_results"]
                                if row["status"] in ("partial","unmet")}
                    for kind in ("preservation_checks","artifact_checks"):
                        actionable.update("verification:"+kind+":"+str(i) for i,row in enumerate(c["verification"][kind]) if row["status"]=="fail")
                    require(bool(set(payload["feedback_refs"]) & actionable) and set(payload["feedback_refs"])<=actionable,
                            "refinement_unsupported","反馈必须引用当前实际未完成目标或损伤观察")
                    c["prompt"]=compile_prompt(c["contract"],payload["correction"])
                    c["phase"]="edit";c["status"]="ready";c["verification"]=None
                else:c["phase"]="report";c["status"]="task_not_met" if payload["action"]=="stop" else "uncertain"
                c["summaries"][stage]=str(payload.get("reason",payload["action"]))
            c["waiting_stage"]=None
            event={"provenance":provenance,**(observation or {})}
            self._event(c,stage,"observed_import","已接收并校验本阶段真实观察",event)
            write_json(self._dir(id)/"artifacts"/(stage+f"_{len(c['events']):03}.json"),{"payload":payload,"observation":event})
            return self._save(c)
    def candidate(self,id,data,model,provenance="manual_import",note="",observation=None,pending_attempt_id=None,
                  submitted_prompt=None,external_geometry=None):
        with self.lock:
            c=self._load(id);require(c["contract"] is not None and c["prompt"],"contract_required","请先冻结目标")
            internal=provenance=="images_api"
            require(model in providers.ALLOWED_MODELS or (not internal and model=="unknown"),
                    "model_mismatch","仅接入 GPT Image 2；外部输出无法确认后端时请明确填写 unknown")
            require(c["status"]!="accepted","already_complete","当前案例已通过")
            if submitted_prompt is not None:
                require(not internal and isinstance(submitted_prompt,str) and bool(submitted_prompt.strip()),
                        "submitted_prompt_invalid","实际外部提示词必须是非空文本；内部接口使用已记录请求")
            if external_geometry is not None:
                require(not internal and isinstance(external_geometry,dict) and
                        external_geometry.get("policy")=="full_frame_resize" and
                        external_geometry.get("source_frame_confirmed") is True,
                        "candidate_geometry","外部缩放需要明确确认保留源图完整构图")
            pending=c.get("pending_image")
            resolving=bool(pending)
            if resolving:
                require(pending_attempt_id==pending["attempt_id"],"pending_receipt_required","请明确核对并关联之前结果未知的同一次请求")
            else:
                require(c["phase"]=="edit" and not internal,"stage_order","请先完成有依据的反馈，再导入新一轮结果")
                require(c["calls"]["images"]<3,"budget_exhausted","预算已用完")
            if isinstance(data,str):data=decode_image(data)
            index=len(c["rounds"]);p=self._dir(id)/"assets";native=p/f"candidate_{index}_native.png"
            size,policy=canonical(data,native)
            original=tuple(c["geometry"]["source_size"]);canvas=tuple(c["geometry"]["canvas_size"])
            aspect_error=abs(math.log((size[0]/size[1])/(original[0]/original[1])))
            external_resize=not internal and external_geometry is not None and size!=original
            if size not in (original,canvas) or external_resize:
                require(not internal and external_geometry is not None,"candidate_geometry",
                        "候选尺寸不符合原始或已声明画布；外部完整构图输出需显式声明缩放")
                require(aspect_error<=1/size[0]+1/size[1],"candidate_geometry",
                        "外部输出长宽比与源图不符，不能将裁切或构图变化静默拉伸为源图")
            mapping={"native_size":list(size),"delivered_size":list(original),"aspect_error":aspect_error,
                     "source_frame_declaration":bool(external_geometry and external_geometry.get("source_frame_confirmed")),
                     "scale_factors":[original[0]/size[0],original[1]/size[1]],
                     "policy":"full_frame_resize" if external_resize else "source_size_identity"}
            with Image.open(native) as im:
                if external_resize:
                    im=im.resize(original,Image.Resampling.LANCZOS)
                elif size!=original and size==canvas:
                    cw,ch=c["geometry"]["content_size"];im=im.crop((0,0,cw,ch))
                    if im.size!=original:im=im.resize(original,Image.Resampling.LANCZOS)
                    mapping.update(policy="prepared_canvas_inverse",content_size=[cw,ch],
                                   scale_factors=[original[0]/cw,original[1]/ch])
                delivered=p/f"candidate_{index}.png";im.save(delivered)
            if not resolving:c["calls"]["images"]+=1
            c["pending_image"]=None
            url=f"/api/cases/{id}/assets/candidate_{index}.png"
            c["images"]["candidate"]={"url":url,"width":original[0],"height":original[1],"name":f"C{index+1}"}
            identity=deepcopy(observation or {}) if internal else {
                "model_identity":"unverified" if model=="unknown" else "user_declared","note":note,"provider":provenance}
            c["rounds"].append({"index":index,"candidate_url":url,
                                "native_url":f"/api/cases/{id}/assets/{native.name}","candidate_geometry":mapping,
                                "prompt":submitted_prompt if submitted_prompt is not None else c["prompt"],
                                "prompt_source":"api_request" if internal else ("external_submitted" if submitted_prompt is not None else "case_compiled_unconfirmed"),
                                "verification":None,"status":"awaiting_verification","model":model,"observation":identity})
            c["verification"]=None;c["phase"]="verify";c["status"]="ready";c["waiting_stage"]=None
            if c.get("acceptance_version")==ACCEPTANCE_VERSION:
                c["appearance_status"]=None;c["delivery_assessment"]=self._delivery_assessment(c)
            c["candidate_attribute_deltas"]=evidence.candidate_deltas(p/"source.png",p/"reference.png",delivered,c["regions"])
            self._event(c,"edit","candidate_received","已保存原生/交付图；等待 A/B/C 独立验证",provenance)
            c["summaries"]["edit"]=f"已收到第 {index+1} 张候选；尚未代表达标"
            return self._save(c)
    def step(self,id,stage):
        with self.lock:
            c=self._load(id)
            if stage=="evidence":
                p=self._dir(id)/"assets";c["evidence"]=evidence.collect(p/"source.png",p/"reference.png",c["regions"])
                c["summaries"]["evidence"]=f"已测量全图及 {len(c['regions'])} 对独立区域"
                if c["analysis"] is not None and c["contract"] is None:c["phase"]="compose"
                self._event(c,stage,"measured","实际像素测量完成；未推断语义对应")
                c["waiting_stage"]=None;return self._save(c)
            require(stage in prompts.NAMES or stage=="edit","stage_invalid","未知步骤")
            require(c["status"]!="submission_unknown","submission_unknown","上一图像请求结果未知；先核对回执或导入实际结果，不能重发")
            require(c["status"] not in ("accepted","already_satisfied","delivery_not_met"),"already_complete","当前案例已经结束")
            if stage=="edit":require(c["phase"]=="edit","stage_order","请先冻结目标或完成有证据的反馈")
            if stage=="compose":require(c["analysis"] is not None,"analysis_required","先完成参考诊断")
            if stage=="compose":require(c["contract"] is None,"contract_frozen","目标已冻结，不重复调用编译器")
            if stage=="diagnose":require(c["contract"] is None,"contract_frozen","目标已冻结，不重复调用诊断器")
            if stage=="refine":require(c["verification"] is not None and c["phase"]=="refine","verification_required","先完成当前候选的独立验证")
            if stage=="verify":require(c["phase"]=="verify","stage_order","当前没有等待验证的新候选")
            req=self.export(id,stage);write_json(self._dir(id)/"requests"/(stage+f"_{len(c['events']):03}.json"),req)
            configured=providers.settings()["image_configured" if stage=="edit" else "analysis_configured"]
            if not configured:
                c["waiting_stage"]=stage;c["status"]="needs_input"
                self._event(c,stage,"provider_missing","接口未配置：导出任务交给 Agent，或导入实际结果")
                return self._save(c)
            if stage=="edit":
                require(c["calls"]["images"]<3,"budget_exhausted","图像预算已用完")
                req["attempt_id"]="attempt_"+uuid.uuid4().hex
                c["pending_image"]={"attempt_id":req["attempt_id"],"request":req}
                write_json(self._dir(id)/"requests"/(req["attempt_id"]+".json"),req)
                c["calls"]["images"]+=1;c["status"]="submission_unknown"
                self._event(c,stage,"submitted","已发起一次 GPT Image 2 调用；未知结果不自动重发")
                self._save(c)
                receipt=self._dir(id)/"receipts"/(req["attempt_id"]+".json")
                try:
                    data,observation=providers.edit(req,on_response=lambda raw:write_json(receipt,raw))
                    native_receipt=receipt.with_suffix(".image");native_receipt.write_bytes(data)
                    return self.candidate(id,data,req["settings"]["model"],"images_api",observation=observation,pending_attempt_id=req["attempt_id"])
                except RetouchError as exc:
                    c=self._load(id)
                    if hasattr(exc,"actual_generation_count"):
                        c["calls"]["images"]+=max(0,exc.actual_generation_count-1)
                        c["status"]="task_not_met";c["phase"]="report";c["pending_image"]=None
                    self._event(c,stage,"result_requires_review",str(exc))
                    c["summaries"][stage]="实际回执已保存；结果需要核对，不能自动重发"
                    self._save(c);raise
            require(c["calls"]["analysis"]<8,"analysis_budget_exhausted","本案例最多八次分析接口调用")
            c["calls"]["analysis"]+=1;self._save(c)
            receipt=self._dir(id)/"receipts"/(stage+f"_{c['calls']['analysis']:03}.json")
            try:
                payload,observation=providers.analyze(req,on_response=lambda raw:write_json(receipt,raw))
                return self.import_stage(id,stage,payload,"vlm_api",observation)
            except RetouchError as exc:
                c=self._load(id);c["waiting_stage"]=stage;c["status"]="needs_input"
                self._event(c,stage,"result_rejected",str(exc))
                self._save(c);raise
