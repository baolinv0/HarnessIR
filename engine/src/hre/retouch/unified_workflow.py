"""Explicit delivery_v3 workbench path; legacy saved cases keep their code path."""
import hashlib
import io
import json
import math
from copy import deepcopy
from pathlib import Path
import uuid
from PIL import Image,ImageCms,ImageOps
from .contracts import (require,RetouchError,validate_analysis,validate_reference_composition,
    decide_verification,compile_prompt)
from ..reference_core.contracts import validate_semantics,size
from ..reference_core.delivery import assess_delivery,preflight
from ..reference_core.rendering import render_target_limits
from ..reference_core.feedback import normalize_feedback
from ..reference_core.holistic import WHOLE_SCHEMA,validate_whole,verdict_gate

VERSION="reference_retouch_delivery_v3"


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def unified(c):return c.get("acceptance_version")==VERSION


def audited_canonical(data,path):
    """Display conversion is separate from formal numerical encoding eligibility."""
    from .workflow import canonical
    from ..reference_style.color import _chunks
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.load()
            require(im.format in {"PNG","JPEG"} and im.mode=="RGB" and getattr(im,"n_frames",1)==1,
                    "encoding_unsupported","新合同仅支持不透明 RGB8 SDR PNG/JPEG；不隐式丢弃透明或高位深")
            require(im.width*im.height<=50_000_000,"image_large","图像超过支持的像素上限")
            profile=im.info.get("icc_profile");known=bool(profile)
            if im.format=="PNG":
                require(data[24]==8,"encoding_unsupported","高位深必须使用独立受支持的精度路径")
                chunks=list(_chunks(data));tags=dict(chunks)
                require(all(len([k for k,v in chunks if k==tag])<=1 for tag in (b'iCCP',b'sRGB',b'gAMA',b'cHRM')),
                        "encoding_conflict","重复色彩元数据")
                require(b'iCCP' not in tags or profile is not None,"encoding_invalid","ICC 元数据未能实际解码")
                require(b'gAMA' not in tags or len(tags[b'gAMA'])==4,"encoding_invalid","无效 gamma chunk")
                require(b'cHRM' not in tags or len(tags[b'cHRM'])==32,"encoding_invalid","无效 primaries chunk")
                if (profile or b'sRGB' in tags) and (b'gAMA' in tags or b'cHRM' in tags):
                    import struct
                    require(b'gAMA' not in tags or int.from_bytes(tags[b'gAMA'],'big')==45455,"encoding_conflict","不一致的 gamma 声明")
                    require(b'cHRM' not in tags or struct.unpack('>8I',tags[b'cHRM'])==(31270,32900,64000,33000,30000,60000,15000,6000),
                        "encoding_conflict","无法审计一致的 primaries 声明")
                    if profile:
                        from ..reference_style.color import _is_srgb
                        _is_srgb(profile)
                if b'sRGB' in tags:
                    require(tags[b'sRGB'] in (b'\0',b'\1',b'\2',b'\3'),"encoding_conflict","无效 sRGB rendering intent")
                    require(b'gAMA' not in tags or int.from_bytes(tags[b'gAMA'],'big')==45455,"encoding_conflict","sRGB 与 gamma 元数据冲突")
                    if profile:
                        # Multiple declarations must describe exactly the same audited space.
                        from ..reference_style.color import _is_srgb
                        _is_srgb(profile)
                    known=True
                elif not profile and (b'gAMA' in tags or b'cHRM' in tags):
                    require(False,"encoding_unsupported","孤立 gamma/primaries 不能当作已知 sRGB")
            if profile:
                p=ImageCms.ImageCmsProfile(io.BytesIO(profile))
                require(p.profile.xcolor_space.strip()=="RGB","encoding_unsupported","ICC 不是 RGB 编码")
        dimensions,policy=canonical(data,path)
    except RetouchError:raise
    except (ValueError,OSError,ImageCms.PyCMSError) as exc:
        raise RetouchError("encoding_invalid","色彩编码无效、冲突或不受支持") from exc
    return dimensions,dict(status="known" if known else "unknown",numeric_eligible=known,
        source_sha256=hashlib.sha256(data).hexdigest(),selected_sha256=sha(path),
        conversion=policy if known else "display-only sRGB interpretation; unknown source encoding",assumed_source_encoding=not known)


def semantics(contract,requirements):
    return validate_semantics(dict(coverage=contract["coverage"],targets=contract["targets"],delivery_requirements=requirements))


def compiled(contract,correction=None):
    return compile_prompt(contract,correction)+"\n\n"+"\n\n".join(render_target_limits(t) for t in contract["targets"])+(
        "\nApply appearance changes to whole face/object/material units. Preserve facial geometry and expression. "
        "Do not isolate individual eyes, lips or small face patches as independent edit units.")


class UnifiedWorkbenchMixin:
    def get(self,id):
        c=self._load(id);self._check_unified_frozen(c)
        return self._view(c)

    def create(self,request):
        if request.get("acceptance_version")!=VERSION:
            require(request.get("acceptance_version") in (None,"reference_retouch_delivery_v2"),"acceptance_version","未知验收合同版本")
            return super().create(request)
        from .workflow import delivery_requirements,decode_image,now,write_json
        with self.lock:
            require(isinstance(request.get("brief"),str) and request["brief"].strip(),"brief_missing","需要编辑意图")
            mode=request.get("delivery_mode","source_native")
            require(mode in {"source_native","declared_working_size"},"delivery_mode","未知交付模式")
            working=size(request.get("working_size"),"working_size") if mode=="declared_working_size" else None
            requirements=delivery_requirements(request.get("delivery_requirements",{}))
            identifier="case_"+uuid.uuid4().hex[:12];p=self.root/identifier;(p/"assets").mkdir(parents=True)
            images={};encodings={}
            for role,key in (("source","source_data"),("reference","reference_data")):
                data=decode_image(request.get(key));(p/"assets"/(role+".original")).write_bytes(data)
                dimensions,encoding=audited_canonical(data,p/"assets"/(role+".png"));encodings[role]=encoding
                images[role]=dict(url=f"/api/cases/{identifier}/assets/{role}.png",width=dimensions[0],height=dimensions[1],name=request.get(role+"_name",role))
            source=[images["source"]["width"],images["source"]["height"]]
            if working:
                require(abs(math.log((working[0]/working[1])/(source[0]/source[1])))<=1/working[0]+1/working[1],
                    "working_geometry","声明工作尺寸必须保留完整构图与长宽比")
            images["candidate"]=None
            c=dict(id=identifier,schema_version="reference_retouch_v1",acceptance_version=VERSION,created_at=now(),
                brief=request["brief"].strip(),delivery_requirements=requirements,delivery_mode=mode,
                declared_working_size=working,appearance_status=None,delivery_assessment=None,delivery_preflight=None,
                source_name=request.get("source_name","A"),reference_name=request.get("reference_name","B"),
                status="ready",phase="diagnose",images=images,colour_policy=encodings,
                geometry=dict(source_size=source,task_size=working or source,policy="not_prepared"),
                regions=[],analysis=None,initial_diagnosis=None,effective_diagnosis=None,evidence=None,evidence_review=None,
                contract=None,prompt=None,verification=None,refinement=None,rounds=[],events=[],calls=dict(analysis=0,images=0),
                waiting_stage=None,summaries={},pending_image=None,max_analysis_calls=12)
            self._event(c,"inputs","canonicalized","已保存原始 A/B 与审计的显示副本；编辑画布尚未准备")
            frozen={key:deepcopy(c[key]) for key in ("acceptance_version","brief","delivery_requirements","delivery_mode","declared_working_size","colour_policy")}
            frozen["task_geometry"]={key:c["geometry"][key] for key in ("source_size","task_size")}
            write_json(p/"freeze.json",frozen);c["freeze_sha256"]=sha(p/"freeze.json")
            return self._save(c)

    def _check_unified_frozen(self,c):
        from .workflow import read_json
        if not unified(c):return
        p=self._dir(c["id"])
        require(sha(p/"freeze.json")==c["freeze_sha256"],"case_modified","冻结案例身份已改变")
        frozen=read_json(p/"freeze.json")
        require(all(c[key]==value for key,value in frozen.items() if key!="task_geometry") and
            all(c["geometry"][key]==value for key,value in frozen["task_geometry"].items()),"case_modified","交付模式或原始任务要求已改变")
        for role,encoding in c["colour_policy"].items():
            require(sha(p/"assets"/(role+".original"))==encoding["source_sha256"] and
                sha(p/"assets"/(role+".png"))==encoding["selected_sha256"],"input_modified","冻结原始/显示输入字节已改变")
        if c.get("contract") is not None:require(digest(c["contract"])==c["contract_sha256"],"contract_frozen","冻结目标事实已改变")
        if c["geometry"].get("working_sha256"):
            require(sha(p/"assets/source_work.png")==c["geometry"]["working_sha256"],"input_modified","工作画布字节已改变")

    def regions(self,id,regions):
        c=self._load(id)
        if not unified(c):return super().regions(id,regions)
        with self.lock:
            self._check_unified_frozen(c)
            result=super().regions(id,regions)
            c=self._load(id);c["evidence_review"]=None;c["effective_diagnosis"]=None
            if c["initial_diagnosis"] is not None:c.update(phase="evidence",status="ready")
            return self._save(c)

    def _view(self,c):
        result=super()._view(c)
        if unified(c):
            pos=next(i for i,row in enumerate(result["stages"]) if row["id"]=="compose")
            result["stages"].insert(pos,dict(id="evidence_review",title="证据复核与有效诊断",status="completed" if c.get("evidence_review") else "ready" if c["phase"]=="evidence_review" else "pending",summary="保留初始诊断与独立复核"))
            pos=next(i for i,row in enumerate(result["stages"]) if row["id"]=="verify")
            result["stages"].insert(pos,dict(id="whole_image_review",title="先整体、后区域",status="completed" if c["rounds"] and c["rounds"][-1].get("whole_image_review") else "ready" if c["phase"]=="whole_image_review" else "pending",summary="六轴参考风格与独立 A 内容保持"))
        return result

    def _delivery_assessment(self,c,round=None,verification=None,source_result=False):
        if not unified(c):return super()._delivery_assessment(c,round,verification,source_result)
        r=round or (c["rounds"][-1] if c["rounds"] else {})
        native=self._image_size(c,c["images"]["source"]["url"] if source_result else r.get("native_url"))
        delivered=self._image_size(c,c["images"]["source"]["url"] if source_result else r.get("candidate_url"))
        content=native if source_result else r.get("candidate_geometry",{}).get("native_content_size",native)
        result=assess_delivery(c["geometry"]["task_size"],content,c["delivery_requirements"],
            detail="pass" if source_result else (verification or {}).get("detail_preservation","uncertain"))
        return {**result,"requirements_frozen":True,"native_size":native,"native_content_size":content,"delivered_size":delivered,
            "required_native_size":result["minimum_native_size"],"size_status":result["native_resolution"],
            "reasons":["交付按冻结任务模式与原生内容尺寸检查；padding/插值不增加原生细节"]}

    def _prepare_unified_edit(self,c):
        from .workflow import prepare_canvas
        self._check_unified_frozen(c)
        if c["geometry"].get("canvas_size"):return c
        p=self._dir(c["id"])/"assets"
        if c["delivery_mode"]=="declared_working_size":
            working=c["declared_working_size"]
            original=c["geometry"]["source_size"]
            require(abs(math.log((working[0]/working[1])/(original[0]/original[1])))<=1/working[0]+1/working[1],
                    "working_geometry","执行前复核：声明工作尺寸不能拉伸 A 的构图")
            require(all(x%16==0 for x in working) and min(working)>0 and max(working)<=3840 and 655360<=working[0]*working[1]<=8294400,
                    "canvas_unsupported","声明工作尺寸不在已支持的图像 API 范围")
            with Image.open(p/"source.png") as image:image.resize(tuple(working),Image.Resampling.LANCZOS).save(p/"source_work.png")
            plan=dict(source_size=c["geometry"]["source_size"],content_size=working,canvas_size=working,policy="declared_working_size")
        else:
            try:plan=prepare_canvas(p/"source.png",p/"source_work.png")
            except RetouchError as exc:
                c["delivery_preflight"]={"status":"infeasible","pass":False,"reason":str(exc)}
                c.update(status="delivery_not_met",phase="report");self._save(c);return c
        c["geometry"].update(plan)
        c["geometry"]["working_sha256"]=sha(p/"source_work.png")
        c["delivery_preflight"]=preflight(c["geometry"]["task_size"],plan["content_size"],c["delivery_requirements"])
        if c["delivery_preflight"]["status"]!="feasible":c.update(status="delivery_not_met",phase="report")
        self._event(c,"edit","delivery_preflight","已在任何图像调用之前核对冻结原生交付条件")
        self._save(c);return c

    def export(self,id,stage):
        c=self._load(id)
        if not unified(c):return super().export(id,stage)
        self._check_unified_frozen(c)
        if stage=="review":
            require(c["rounds"] and c["rounds"][-1].get("verification_versions"),"verification_required","先取得候选初次验证")
            r=c["rounds"][-1]
            return {**self.export(id,"verify"),"stage":"review","whole_image_request":self.export(id,"whole_image_review"),
                "review_binding":dict(candidate_id=r["candidate_id"],round=r["index"],native_sha256=r["native_sha256"],delivered_sha256=r["delivered_sha256"],predecessor_sha256=digest(r["verification_versions"][-1]))}
        if stage=="edit":
            require(c["contract"] is not None and c["prompt"],"contract_required","先冻结目标")
            c=self._prepare_unified_edit(c)
            require(c["delivery_preflight"]["status"]=="feasible","delivery_preflight","已知交付不可行，停止编辑")
            from . import providers
            return dict(stage=stage,case_id=id,prompt=c["prompt"],images=self._images(c,working=True),geometry=c["geometry"],
                semantic_audit=deepcopy(c["prompt_audit"]),settings=dict(model=providers.settings()["image_model"],n=1,
                    size="%dx%d"%tuple(c["geometry"]["canvas_size"]),quality="high",output_format="png"))
        from . import prompts
        require(stage in set(prompts.NAMES)|{"evidence_review","whole_image_review"},"stage_invalid","未知阶段")
        context=dict(brief=c["brief"],regions=c["regions"],colour_policy=c["colour_policy"],acceptance_version=VERSION,
            available_evidence_refs=sorted(self._evidence_refs(c)))
        if stage=="whole_image_review":
            require(c["rounds"],"candidate_required","需要真实候选")
            r=c["rounds"][-1]
            images=self._images(c,include_candidate=True)
            images.append(dict(role="candidate_native",path=str(self._dir(id)/"assets"/Path(r["native_url"]).name),url=r["native_url"]))
            return dict(stage=stage,case_id=id,instruction=("Inspect the complete A/B/C frames FIRST, before regional metrics or local checks. "
                "Return the supplied schema. Bind exact image_sha256. Disclose actual display conditions, independence and prior exposure. "
                "For each of six axes report reference_status, relation to B, direction, magnitude, confidence and evidence. "
                "Closeness does not prove achievement. Separately judge A preservation. Retain uncertainty/conflicts without aggregate scores."),
                context=dict(image_sha256=self._whole_bindings(c),response_schema=WHOLE_SCHEMA),images=images)
        if stage=="evidence_review":
            require(c["initial_diagnosis"] is not None and c["evidence"] is not None and c["contract"] is None,"evidence_review_required","先取得初始诊断与实际证据")
            context.update(initial_diagnosis=c["initial_diagnosis"],initial_diagnosis_sha256=digest(c["initial_diagnosis"]),
                evidence=c["evidence"],evidence_sha256=digest(c["evidence"]))
            instruction=("Review actual A/B and fresh evidence against initial_diagnosis. Return initial_diagnosis_sha256, evidence_sha256, "
                "resolution (resolved/unresolved), reason and effective_diagnosis with the complete diagnosis field layout. "
                "Keep initial diagnosis immutable. Statistics alone cannot resolve semantic correspondence or conflicting evidence. "
                "Use eight exact attributes; preserve source protected facts and independent A/B observations. If support is missing, mark unresolved.")
        else:
            instruction=prompts.instruction(stage,strict_reference=True)
        if stage in {"compose","refine"}:
            context.update(analysis=c["effective_diagnosis"],initial_diagnosis=c["initial_diagnosis"],evidence=c["evidence"],evidence_review=c["evidence_review"])
            instruction+=" Use only the separately reviewed effective diagnosis. All targets have exact eight-dimension attributes, supported comparability and whole face/object/material scope."
        if stage in {"verify","refine"}:
            require(c["images"]["candidate"] is not None,"candidate_required","需要真实候选")
            context.update(evaluation_contract=c["contract"],geometry=c["geometry"],candidate_geometry=c["rounds"][-1]["candidate_geometry"],
                delivery_requirements=c["delivery_requirements"],delivery_assessment=self._delivery_assessment(c),
                protection_check_items=c["contract"]["protected_facts"],evidence=c["evidence"],
                candidate_attribute_deltas=c.get("candidate_attribute_deltas",[]))
            context["whole_image_review"]=c["rounds"][-1].get("effective_whole_image_review",c["rounds"][-1].get("whole_image_review"))
            context["whole_image_review_sha256"]=digest(context["whole_image_review"])
            context["required_verification_extensions"]={"overall_style":context["whole_image_review"]["overall_style"] if context["whole_image_review"] else None,
                "whole_image_review_sha256":context["whole_image_review_sha256"]}
            instruction+=" Copy the archived whole-image overall_style exactly; include whole_image_review_sha256. Regional or numerical preferences cannot cancel it."
            context["available_evidence_refs"] += ["C","candidate_native"]
        if stage=="refine":
            context.update(verification=c["verification"],normalized_feedback=c.get("normalized_feedback"),remaining_generations=3-c["calls"]["images"])
            instruction+=" Cite normalized_feedback.actionable_feedback_refs exactly. Revise execution expression only; pending mandatory review blocks refinement."
        images=self._images(c,include_candidate=stage in {"verify","refine"})
        if stage=="verify":
            r=c["rounds"][-1];images.append(dict(role="candidate_native",path=str(self._dir(id)/"assets"/Path(r["native_url"]).name),url=r["native_url"]))
        return dict(stage=stage,case_id=id,instruction=instruction,context=context,images=images)

    def import_stage(self,id,stage,payload,provenance="manual_agent",observation=None):
        from .workflow import write_json
        c=self._load(id)
        if not unified(c):return super().import_stage(id,stage,payload,provenance,observation)
        with self.lock:
            self._check_unified_frozen(c)
            require(provenance in {"manual_agent","human","vlm_api"},"provenance_invalid","来源必须如实记录")
            json.dumps(payload,allow_nan=False)
            if stage=="diagnose":
                require(c["contract"] is None and c["initial_diagnosis"] is None,"diagnosis_frozen","初始诊断已归档；新证据须独立复核")
                value=validate_analysis(payload,strict_reference=True);self._check_refs(c,value["reference_profile"]+value["candidate_deltas"])
                c.update(analysis=value,initial_diagnosis=deepcopy(value),phase="evidence",status="ready")
            elif stage=="evidence_review":
                require(c["contract"] is None and c["initial_diagnosis"] is not None and c["evidence"] is not None,"evidence_review_required","目标冻结前先取得实际证据")
                require(payload.get("initial_diagnosis_sha256")==digest(c["initial_diagnosis"]) and payload.get("evidence_sha256")==digest(c["evidence"]),
                    "evidence_review_binding","复核必须绑定初始诊断和新证据")
                require(payload.get("resolution") in {"resolved","unresolved"} and isinstance(payload.get("reason"),str) and bool(payload["reason"].strip()),"evidence_review_invalid","复核需要明确结论及依据")
                effective=validate_analysis(payload.get("effective_diagnosis"),strict_reference=True)
                self._check_refs(c,effective["reference_profile"]+effective["candidate_deltas"])
                protected=c["initial_diagnosis"]["source_diagnosis"]["protected_facts"]
                require(all(p in effective["source_diagnosis"]["protected_facts"] for p in protected),"source_protection_missing","证据复核不能丢失源图保护事实")
                require(payload["resolution"]!="resolved" or effective["analysis_status"]!="needs_evidence","evidence_review_unresolved","尚需证据不能标记已解决")
                c.update(evidence_review=deepcopy(payload),effective_diagnosis=effective,phase="compose" if payload["resolution"]=="resolved" else "evidence_review",
                    status="ready" if payload["resolution"]=="resolved" else "needs_review")
            elif stage=="compose":
                require(c["contract"] is None,"contract_frozen","目标已冻结")
                review=c.get("evidence_review")
                require(review and review["resolution"]=="resolved" and review["evidence_sha256"]==digest(c["evidence"]),"evidence_review_required","需要当前实际证据的有效复核")
                value=validate_reference_composition(c["effective_diagnosis"],payload.get("contract",payload));semantics(value,c["delivery_requirements"])
                self._check_refs(c,value["targets"])
                require(all(p in value["protected_facts"] for p in c["effective_diagnosis"]["source_diagnosis"]["protected_facts"]),"source_protection_missing","冻结保护事实不能丢失")
                if value["overall_status"] in {"insufficient_evidence","preference_conflict"}:
                    c.update(contract_draft=value,status="needs_review",phase="compose")
                else:
                    c["contract"]=value;c["contract_sha256"]=digest(value)
                    if value["overall_status"]=="already_satisfied":
                        require(c["calls"]["images"]==0,"already_satisfied_invalid","已满足必须零图像调用")
                        c.update(status="already_satisfied",phase="report",result_url=c["images"]["source"]["url"],appearance_status="already_satisfied")
                        c["delivery_assessment"]=self._delivery_assessment(c,source_result=True)
                        if c["delivery_assessment"]["status"]!="pass":c["status"]="delivery_not_met"
                    else:
                        c.update(prompt=compiled(value),phase="edit",status="ready")
                        c["prompt_audit"]=self._prompt_audit(c)
            elif stage=="verify":
                require(c["phase"]=="verify" and not c.get("pending_image"),"verification_stage","需要等待验证的真实候选；复核使用独立追加入口")
                self._accept_verification(c,payload)
            elif stage=="whole_image_review":
                require(c["phase"]=="whole_image_review" and c["rounds"] and not c.get("pending_image"),"stage_order","先整体观察，再进入区域验证")
                try:whole=validate_whole(payload,self._whole_bindings(c))
                except ValueError as exc:raise RetouchError("whole_image_review_invalid",str(exc)) from exc
                c["rounds"][-1]["whole_image_review"]=whole
                c.update(phase="verify",status="ready")
            elif stage=="refine":
                feedback=c.get("normalized_feedback")
                require(feedback is not None and c["verification"] is not None,"verification_required","需要当前候选的规范反馈")
                require(c["status"] not in {"accepted","already_satisfied","delivery_not_met"},"already_complete","案例已结束")
                require(payload.get("action") in {"revise","stop","needs_review"} and "contract" not in payload and "targets" not in payload,"contract_frozen","仅允许修改执行表达")
                require(digest(c["contract"])==c["contract_sha256"],"contract_frozen","冻结目标已改变")
                if payload["action"]=="revise":
                    require(feedback["action"]=="revise_prompt","feedback_pending","先解决必需复核或停止状态")
                    refs=payload.get("feedback_refs",[]);allowed=set(feedback["actionable_feedback_refs"])
                    require(bool(refs) and set(refs)<=allowed and bool(payload.get("correction")),"refinement_unsupported","仅能引用当前规范反馈的支持修正")
                    require(c["calls"]["images"]<3,"budget_exhausted","预算已用完")
                    require(set(payload.get("changed_target_ids",[]))<={t["target_id"] for t in c["contract"]["targets"]},"refinement_targets","未知目标")
                    c.update(prompt=compiled(c["contract"],payload["correction"]),phase="edit",status="ready")
                    c["prompt_audit"]=self._prompt_audit(c)
                else:c.update(phase="report" if payload["action"]=="stop" else "verify",status="task_not_met" if payload["action"]=="stop" else "needs_review")
                c["refinement"]=deepcopy(payload)
            else:raise RetouchError("stage_invalid","未知导入阶段")
            c["waiting_stage"]=None;c["summaries"][stage]="已保存并校验实际观察"
            origin={"provenance":provenance,**(observation or {})}
            self._event(c,stage,"observed_import","实际观察已校验、绑定并归档",origin)
            write_json(self._dir(id)/"artifacts"/(stage+f"_{len(c['events']):03d}.json"),dict(payload=payload,observation=origin))
            return self._save(c)

    def _prompt_audit(self,c):
        spans=[]
        for t in c["contract"]["targets"]:
            fragment=render_target_limits(t);start=c["prompt"].index(fragment)
            spans.append(dict(target_id=t["target_id"],start=start,end=start+len(fragment)))
        return dict(mode="deterministic_structural",status="pass",prompt_sha256=hashlib.sha256(c["prompt"].encode()).hexdigest(),
            contract_sha256=digest(c["contract"]),target_spans=spans)

    def _accept_verification(self,c,payload,review=False):
        require(c["rounds"],"candidate_required","需要实际候选")
        if "detail_preservation" in payload:require(payload["detail_preservation"] in {"pass","fail","uncertain"},"detail_preservation_invalid","无效细节检查")
        r=c["rounds"][-1];whole=r.get("effective_whole_image_review",r.get("whole_image_review"))
        require(isinstance(whole,dict) and payload.get("whole_image_review_sha256")==digest(whole) and payload.get("overall_style")==whole["overall_style"],
            "whole_image_review_required","必须绑定先行整体观察；局部验证不能修改整体结论")
        verdict=decide_verification(c["contract"],payload,strict_reference=True)
        gate=verdict_gate(whole)
        if gate=="reject":verdict="reject"
        elif gate=="uncertain" and verdict!="reject":verdict="uncertain"
        elif gate=="revise" and verdict=="accept":verdict="revise"
        self._check_refs(c,payload["target_results"]+payload["preservation_checks"]+payload["artifact_checks"],extra={"C","candidate_native"})
        v={**deepcopy(payload),"whole_image_review":deepcopy(whole),"reported_global_status":payload.get("global_status"),"global_status":verdict}
        r=c["rounds"][-1];versions=r.setdefault("verification_versions",[])
        observation=dict(version=len(versions),verification=v,predecessor_sha256=digest(versions[-1]) if versions else None,
            candidate_id=r["candidate_id"],native_sha256=r["native_sha256"],delivered_sha256=r["delivered_sha256"])
        versions.append(observation)
        if not review:r["verification"]=deepcopy(v)
        r["effective_verification"]=v;c["verification"]=v
        c["delivery_assessment"]=self._delivery_assessment(c,verification=v)
        c["appearance_status"]=verdict
        feedback=normalize_feedback(c["contract"],v,candidate_id=r["candidate_id"],round_index=r["index"],delivery=c["delivery_assessment"])
        c["normalized_feedback"]=feedback;r.update(feedback=deepcopy(feedback),delivery_assessment=c["delivery_assessment"],appearance_status=verdict,status=verdict)
        if c["delivery_assessment"]["status"]=="fail":c.update(status="delivery_not_met",phase="report")
        elif feedback["action"] in {"manual_review","gather_evidence"}:c.update(status="needs_review",phase="verify")
        elif verdict=="accept":c.update(status="accepted",phase="report",result_url=r["candidate_url"])
        elif feedback["action"]=="revise_prompt" and c["calls"]["images"]<3:c.update(status="needs_revision",phase="refine")
        else:c.update(status="task_not_met",phase="report")

    def review_candidate(self,id,review,provenance="human"):
        from .workflow import write_json
        with self.lock:
            c=self._load(id);require(unified(c),"review_version","需要 delivery_v3 案例")
            self._check_unified_frozen(c)
            require(provenance in {"human","manual_agent"} and not c.get("pending_image") and bool(c["rounds"]),"review_candidate","候选或来源无效")
            r=c["rounds"][-1];versions=r.get("verification_versions",[])
            require(review.get("candidate_id")==r["candidate_id"] and review.get("round")==r["index"] and
                review.get("native_sha256")==r["native_sha256"] and review.get("delivered_sha256")==r["delivered_sha256"],"review_binding","复核不属于同一候选")
            p=self._dir(id)/"assets"
            require(sha(p/Path(r["native_url"]).name)==r["native_sha256"] and sha(p/Path(r["candidate_url"]).name)==r["delivered_sha256"],"review_binding","候选字节已改变")
            require(versions and review.get("predecessor_sha256")==digest(versions[-1]),"review_predecessor","需要精确上一观察版本")
            try:whole=validate_whole(review.get("whole_image_review"),self._whole_bindings(c))
            except ValueError as exc:raise RetouchError("whole_image_review_invalid",str(exc)) from exc
            r["effective_whole_image_review"]=whole
            self._accept_verification(c,review["verification"],review=True)
            write_json(self._dir(id)/"reviews"/(r["candidate_id"]+f"_v{len(versions)-1:03d}.json"),versions[-1])
            self._event(c,"verify","same_candidate_review","同一候选追加观察；历史判断和图像调用数保持可追溯",provenance)
            return self._save(c)

    def candidate(self,id,data,model,provenance="manual_import",note="",observation=None,pending_attempt_id=None,submitted_prompt=None,external_geometry=None):
        c=self._load(id)
        if not unified(c):return super().candidate(id,data,model,provenance,note,observation,pending_attempt_id,submitted_prompt,external_geometry)
        from .workflow import decode_image
        from . import providers,evidence
        with self.lock:
            self._check_unified_frozen(c)
            require(c["contract"] is not None and c["prompt"],"contract_required","需要冻结目标")
            internal=provenance=="images_api";pending=c.get("pending_image")
            require(model in providers.ALLOWED_MODELS or not internal and model=="unknown","model_mismatch","实际型号需要可观察依据")
            if pending:require(pending_attempt_id==pending["attempt_id"],"pending_receipt_required","结果未知的请求必须精确关联回执")
            else:require(c["phase"]=="edit" and not internal and c["calls"]["images"]<3,"stage_order","需要有依据的编辑阶段和剩余预算")
            if isinstance(data,str):data=decode_image(data)
            index=len(c["rounds"]);p=self._dir(id)/"assets";raw=p/f"candidate_{index}.original";raw.write_bytes(data)
            native=p/f"candidate_{index}_native.png";dimensions,encoding=audited_canonical(data,native)
            original=tuple(c["geometry"]["task_size"]);canvas=tuple(c["geometry"].get("canvas_size",original))
            require(external_geometry is None or not internal and isinstance(external_geometry,dict) and external_geometry.get("policy")=="full_frame_resize" and external_geometry.get("source_frame_confirmed") is True,
                "candidate_geometry","外部映射需要明确确认完整源构图")
            require(submitted_prompt is None or not internal and isinstance(submitted_prompt,str) and bool(submitted_prompt.strip()),"submitted_prompt_invalid","外部提交提示词需要非空文本")
            if dimensions not in (original,canvas):require(external_geometry is not None,"candidate_geometry","候选画布不匹配；需要显式完整构图映射")
            mapped=bool(external_geometry)
            require(not mapped or abs(math.log((dimensions[0]/dimensions[1])/(original[0]/original[1])))<=1/dimensions[0]+1/dimensions[1],"candidate_geometry","外部输出长宽比不匹配")
            content=list(dimensions);policy="source_size_identity"
            with Image.open(native) as im:
                if not mapped and dimensions==canvas and dimensions!=original:
                    content=c["geometry"]["content_size"];im=im.crop((0,0,*content));policy="prepared_canvas_inverse"
                if im.size!=original:im=im.resize(original,Image.Resampling.LANCZOS);policy="full_frame_resize" if mapped else policy
                delivered=p/f"candidate_{index}.png";im.save(delivered)
            if not pending:c["calls"]["images"]+=1
            url=f"/api/cases/{id}/assets/{delivered.name}";native_url=f"/api/cases/{id}/assets/{native.name}"
            r=dict(index=index,candidate_id=f"c{index:03d}",candidate_url=url,native_url=native_url,native_sha256=sha(native),
                raw_sha256=sha(raw),raw_path=str(raw),delivered_sha256=sha(delivered),encoding=encoding,
                candidate_geometry=dict(native_size=list(dimensions),native_content_size=list(content),delivered_size=list(original),policy=policy,
                    source_frame_declaration=mapped),prompt=submitted_prompt if submitted_prompt is not None else c["prompt"],
                prompt_source="api_request" if internal else "external_submitted" if submitted_prompt else "case_compiled_unconfirmed",
                verification=None,status="awaiting_verification",model=model,observation={"provenance":provenance,"note":note,**(observation or {})})
            c["rounds"].append(r);c["images"]["candidate"]=dict(url=url,width=original[0],height=original[1],name=f"C{index+1}")
            c.update(pending_image=None,verification=None,phase="whole_image_review",status="ready",waiting_stage=None,appearance_status=None)
            c["delivery_assessment"]=self._delivery_assessment(c)
            eligible=all(c["colour_policy"][role]["numeric_eligible"] for role in ("source","reference")) and encoding["numeric_eligible"]
            # A/B boxes never assert a C support. Only a separately reviewed C mapping permits regional numbers.
            c["candidate_attribute_deltas"]=[]
            c["candidate_measurement_status"]={"status":"unavailable","reason":"No genuine C regional support or separately reviewed C mapping", "encoding_eligible":eligible}
            self._event(c,"edit","candidate_received","原始/原生/交付 C 身份分别归档；待独立检查",provenance)
            return self._save(c)

    def step(self,id,stage):
        from .workflow import write_json
        from . import evidence,providers
        c=self._load(id)
        if not unified(c):return super().step(id,stage)
        with self.lock:
            self._check_unified_frozen(c)
            if stage=="evidence":
                require(c["contract"] is None,"revision_required","冻结后新证据需要新任务修订，不能改变目标")
                p=self._dir(id)/"assets"
                eligible=all(v["numeric_eligible"] for v in c["colour_policy"].values())
                c["evidence"]=evidence.collect(p/"source.png",p/"reference.png",c["regions"]) if eligible else dict(status="unavailable",reason="Unknown/assumed source encoding cannot enter formal numerical evidence",regions=[])
                c["evidence_review"]=None;c["effective_diagnosis"]=None
                c.update(phase="evidence_review",status="ready",waiting_stage=None)
                self._event(c,stage,"measured","数值资格及真实输入已核对；需要独立证据复核")
                return self._save(c)
            if stage=="edit":
                require(c["phase"]=="edit" and c["status"] not in {"submission_unknown","already_satisfied","accepted","delivery_not_met"},"stage_order","当前不允许提交编辑")
                c=self._prepare_unified_edit(c)
                if c["delivery_preflight"]["status"]!="feasible":return self._view(c)
                require(c["prompt_audit"]["prompt_sha256"]==hashlib.sha256(c["prompt"].encode()).hexdigest() and
                    c["prompt_audit"]["contract_sha256"]==digest(c["contract"]),"prompt_modified","实际编辑提示与审计不一致")
            if stage in {"diagnose","evidence_review","compose","whole_image_review","verify","refine"}:
                require(c["status"]!="submission_unknown","submission_unknown","先核对结果未知的请求")
                require(c["phase"]==stage,"stage_order","按冻结阶段顺序执行；复核请使用追加入口")
                req=self.export(id,stage)
                write_json(self._dir(id)/"requests"/(stage+f"_{len(c['events']):03d}.json"),req)
                if not providers.settings()["analysis_configured"]:
                    c.update(waiting_stage=stage,status="needs_input");self._event(c,stage,"provider_missing","接口未配置；可导出并导入真实复核")
                    return self._save(c)
                require(c["calls"]["analysis"]<c["max_analysis_calls"],"analysis_budget_exhausted","分析预算已用完")
                c["calls"]["analysis"]+=1;self._save(c)
                receipt=self._dir(id)/"receipts"/(stage+f"_{c['calls']['analysis']:03d}.json")
                try:
                    payload,observation=providers.analyze(req,on_response=lambda raw:write_json(receipt,raw))
                    return self.import_stage(id,stage,payload,"vlm_api",observation)
                except RetouchError as exc:
                    c=self._load(id);c.update(waiting_stage=stage,status="needs_input")
                    self._event(c,stage,"result_rejected",str(exc));self._save(c);raise
            return super().step(id,stage)

    def _whole_bindings(self,c):
        r=c["rounds"][-1];p=self._dir(c["id"])/"assets"
        result=dict(source=sha(p/"source.png"),appearance_reference=sha(p/"reference.png"),
            candidate=sha(p/Path(r["candidate_url"]).name),candidate_native=sha(p/Path(r["native_url"]).name))
        require(result["candidate"]==r["delivered_sha256"] and result["candidate_native"]==r["native_sha256"],"candidate_modified","实际显示候选字节已改变")
        return result
