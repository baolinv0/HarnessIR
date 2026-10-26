"""Task contracts and deterministic completion rules, independent of providers."""
from copy import deepcopy
import math
import re

REFERENCE_DIMENSIONS={"neutral_balance","chroma_by_hue","skin_rendering","shadow_midtone_highlight",
                      "highlight_transition","local_contrast","subject_background_balance","texture_and_noise_observation"}
ARTIFACT_CHECKS={"naturalness","reference_content_leakage","unsupported_detail"}
_COVERAGE_STATES={"targeted","preserve","already_satisfied","uncertain","not_applicable","excluded"}
_CLOSED_COVERAGE_STATES={"preserve","already_satisfied","not_applicable","excluded"}

class RetouchError(ValueError):
    def __init__(self, code, message):
        self.code=code
        super().__init__(message)

def require(ok, code, message):
    if not ok: raise RetouchError(code,message)

def nonempty(value):
    return isinstance(value,str) and bool(value.strip())

def validate_regions(regions):
    require(isinstance(regions,list),"regions_invalid","区域必须是数组")
    ids=set()
    for r in regions:
        require(isinstance(r,dict) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}",r.get("id","")),"region_id","区域 ID 使用英文/数字")
        require(r["id"] not in ids,"region_id","区域 ID 重复");ids.add(r["id"])
        require(nonempty(r.get("description")),"region_description","请描述对应的材质或对象")
        for k in ("source_box","reference_box"):
            b=r.get(k)
            require(isinstance(b,list) and len(b)==4 and all(type(x) in (int,float) and math.isfinite(x) and 0<=x<=1 for x in b) and b[0]<b[2] and b[1]<b[3],"region_box","A/B 必须各自圈选有效区域")
        require(r.get("comparability","unknown") in ("comparable","conditional","unknown","incomparable"),"region_comparability","无效可比性")
        require(set(r.get("attributes",[])) <= {"brightness","color","tone","saturation"},"region_attributes","未知区域属性")
    return deepcopy(regions)

def validate_analysis(value,*,strict_reference=False):
    require(isinstance(value,dict),"analysis_invalid","诊断必须是 JSON 对象")
    required={"source_diagnosis","reference_profile","correspondence","candidate_deltas","coverage","analysis_status","evidence_requests"}
    require(required<=value.keys(),"analysis_missing","诊断缺少："+", ".join(sorted(required-value.keys())))
    require(isinstance(value["source_diagnosis"],dict),"analysis_invalid","源图诊断必须是对象")
    for key in ("source_degradation","source_appearance","protected_facts"):
        require(isinstance(value["source_diagnosis"].get(key),list),"analysis_invalid","源图诊断缺少 "+key)
    for key in ("reference_profile","correspondence","candidate_deltas","coverage","evidence_requests"):
        require(isinstance(value[key],list),"analysis_invalid",key+" 必须是数组")
    dims=[item.get("attribute") for item in value["reference_profile"] if isinstance(item,dict)]
    require(len(dims)==len(set(dims)) and set(dims)==REFERENCE_DIMENSIONS,"reference_coverage","八类参考外观必须逐项观察或明确标记不适用/不确定")
    coverage={item.get("attribute") for item in value["coverage"] if isinstance(item,dict)}
    require(coverage==REFERENCE_DIMENSIONS,"reference_coverage","参考维度覆盖表不完整")
    for item in value["reference_profile"]:
        require(isinstance(item,dict) and nonempty(item.get("attribute")) and item.get("status") in ("observed","uncertain","not_applicable"),"reference_profile","参考属性需要名称与观察状态")
        require(nonempty(item.get("observation")) and isinstance(item.get("evidence_refs"),list),"reference_profile","参考观察必须附依据")
        require(item["status"]!="observed" or bool(item["evidence_refs"]),"reference_evidence","已观察属性必须引用图像或区域")
    require(value["analysis_status"] in ("transfer_supported","already_close","insufficient_reference","needs_evidence"),"analysis_status","未知诊断状态")
    if strict_reference:
        _validate_reference_analysis(value)
    return deepcopy(value)

def _require_roles(refs,*roles):
    require(isinstance(refs,list) and bool(refs) and all(isinstance(ref,str) for ref in refs)
            and len(refs)==len(set(refs)),"reference_evidence","证据引用必须为非空且不重复的实际引用")
    aliases={"A":{"A","source","evidence:source"},"B":{"B","appearance_reference","evidence:reference"},"C":{"C","candidate"}}
    require(all(set(refs)&aliases[role] for role in roles),"reference_evidence","观察需要分别引用 "+"/".join(roles)+" 的证据")

def _validate_reference_coverage(rows,*,closed=False):
    dims=[row.get("attribute") for row in rows if isinstance(row,dict)]
    require(len(dims)==len(rows)==len(REFERENCE_DIMENSIONS) and len(set(dims))==len(dims)
            and set(dims)==REFERENCE_DIMENSIONS,"reference_coverage","八类参考覆盖必须各出现一次")
    states=_CLOSED_COVERAGE_STATES if closed else _COVERAGE_STATES
    require(all(row.get("status") in states and nonempty(row.get("reason")) for row in rows),
            "reference_coverage","参考覆盖状态需要明确依据；已满足不能含待编辑或不确定维度")

def _validate_reference_analysis(value):
    _validate_reference_coverage(value["coverage"])
    for profile in value["reference_profile"]:
        _require_roles(profile["evidence_refs"],"B")
    ids=set()
    for delta in value["candidate_deltas"]:
        require(isinstance(delta,dict),"delta_invalid","候选差异必须为对象")
        for key in ("id","attribute","source_region","reference_region","source_observation","reference_observation","desired_change"):
            require(nonempty(delta.get(key)),"delta_missing","候选差异缺少 "+key)
        require(delta["id"] not in ids,"delta_duplicate","候选差异 ID 不能重复");ids.add(delta["id"])
        require(delta["attribute"] in REFERENCE_DIMENSIONS|{"brightness","color","tone","saturation"},
                "delta_attribute","未知参考属性")
        require(delta.get("comparability") in ("comparable","conditional","unknown","incomparable"),
                "delta_comparability","候选差异需要属性级可比性")
        require(delta["comparability"]!="conditional" or nonempty(delta.get("uncertainty")),
                "delta_condition","条件可比差异需要说明限制")
        _require_roles(delta.get("evidence_refs"),"A","B")

def validate_reference_composition(analysis,value):
    """New cases bind target facts to real diagnosed differences before freezing."""
    validate_analysis(analysis,strict_reference=True)
    validate_contract(value)
    _validate_reference_coverage(value["coverage"])
    status=value["overall_status"]
    if status=="already_satisfied":
        require(analysis["analysis_status"]=="already_close" and not analysis["candidate_deltas"],
                "already_satisfied_unsupported","仅已接近参考且无待解决差异的诊断支持成功保留原图")
        _validate_reference_coverage(analysis["coverage"],closed=True)
        _validate_reference_coverage(value["coverage"],closed=True)
    if status=="ready_to_edit":
        require(analysis["analysis_status"]=="transfer_supported","reference_evidence_insufficient","缺乏支持的参考诊断不能进入图像编辑")
    deltas={delta["id"]:delta for delta in analysis["candidate_deltas"]}
    for target in value["targets"]:
        require(nonempty(target.get("delta_id")) and target["delta_id"] in deltas,
                "target_delta_missing","目标必须引用当前诊断中的 delta_id")
        delta=deltas[target["delta_id"]]
        for key in ("attribute","source_region","reference_region","source_observation","reference_observation","comparability"):
            require(target[key]==delta[key],"target_delta_mismatch","目标更改了诊断事实："+key)
        _require_roles(target["evidence_refs"],"A","B")
        require(set(delta["evidence_refs"])<=set(target["evidence_refs"]),"target_delta_mismatch","目标遗漏了差异的证据")
        if delta["comparability"]=="conditional":
            require(target.get("uncertainty")==delta["uncertainty"],"target_delta_mismatch","目标丢失了条件可比限制")
    return deepcopy(value)

def validate_contract(value):
    require(isinstance(value,dict),"contract_invalid","目标合同必须是对象")
    for key in ("targets","protected_facts","excluded_reference_traits","coverage"):
        require(isinstance(value.get(key),list),"contract_missing","目标合同缺少数组："+key)
    require(value.get("overall_status") in ("ready_to_edit","already_satisfied","insufficient_evidence","preference_conflict"),"contract_status","未知合同状态")
    require(nonempty(value.get("acceptance_rule")),"contract_acceptance","需要明确的完成规则")
    ids=set()
    for t in value["targets"]:
        require(isinstance(t,dict),"target_invalid","目标必须是对象")
        for key in ("target_id","attribute","source_region","reference_region","source_observation","reference_observation","desired_change","acceptance_criterion"):
            require(nonempty(t.get(key)),"target_missing","目标缺少："+key)
        require(t["attribute"] in (REFERENCE_DIMENSIONS-{"texture_and_noise_observation"})|{"brightness","color","tone","saturation"},
                "target_scope","目标超出当前摄影外观迁移范围")
        require(t["target_id"] not in ids,"target_duplicate","目标 ID 重复");ids.add(t["target_id"])
        require(type(t.get("mandatory")) is bool,"target_mandatory","目标必须明确是否必需")
        require(isinstance(t.get("evidence_refs"),list) and bool(t["evidence_refs"]),"target_evidence","目标需要参考证据")
        require(t.get("comparability") in ("comparable","conditional","unknown","incomparable"),"target_comparability","目标需要可比性")
        require(not t["mandatory"] or t["comparability"] in ("comparable","conditional"),"target_uncomparable","必需目标没有可靠的区域对应")
        if t.get("comparability")=="conditional":
            require(nonempty(t.get("uncertainty")),"target_condition","条件可比目标必须说明限制")
    if value["overall_status"]=="ready_to_edit":
        require(bool(value["targets"]),"targets_empty","没有支持的目标，不能开始编辑")
        require(any(t["mandatory"] for t in value["targets"]),"targets_optional","至少指定一个必需目标")
        require(bool(value["protected_facts"]),"source_protection_missing","必须明确源图保护事实")
    if value["overall_status"]=="already_satisfied":
        require(not value["targets"],"already_satisfied_conflict","已满足路径不能同时要求新的编辑")
    coverage=value["coverage"]
    dims=[r.get("attribute") for r in coverage if isinstance(r,dict)]
    require(len(dims)==len(coverage) and len(dims)==len(set(dims)) and set(dims)==REFERENCE_DIMENSIONS,
            "contract_coverage","目标必须逐项交代八类参考外观的用途")
    mapped=set()
    for row in coverage:
        require(row.get("status") in ("targeted","preserve","already_satisfied","uncertain","not_applicable","excluded")
                and nonempty(row.get("reason")),"contract_coverage","每项参考外观需要用途状态与理由")
        refs=row.get("target_ids")
        require(isinstance(refs,list) and set(refs)<=ids,"contract_coverage","参考用途指向了不存在的目标")
        require(row["status"]!="targeted" or bool(refs),"contract_coverage","用于迁移的属性必须指向具体目标")
        mapped.update(refs)
    require(mapped==ids,"contract_coverage","每个目标必须能追溯到参考外观维度")
    return deepcopy(value)

def decide_verification(contract,value,*,strict_reference=False):
    validate_contract(contract)
    require(isinstance(value,dict),"verification_invalid","验证必须是对象")
    rows=value.get("target_results")
    require(isinstance(rows,list),"verification_missing","缺少逐目标验证")
    expected={t["target_id"] for t in contract["targets"]}
    ids=[r.get("target_id") for r in rows if isinstance(r,dict)]
    require(len(ids)==len(rows) and len(set(ids))==len(ids) and set(ids)==expected,"verification_coverage","验证必须覆盖全部且仅覆盖已冻结目标")
    require(all(r.get("status") in ("achieved","partial","unmet","uncertain") and nonempty(r.get("observation"))
                and isinstance(r.get("evidence_refs"),list) and bool(r["evidence_refs"]) for r in rows),"verification_status","目标结果需要状态、实际观察与证据")
    checks=[]
    for key in ("preservation_checks","artifact_checks"):
        items=value.get(key)
        require(isinstance(items,list) and bool(items),"verification_checks","缺少内容保持/伪影检查")
        require(all(isinstance(i,dict) and i.get("status") in ("pass","fail","uncertain") and nonempty(i.get("observation"))
                    and isinstance(i.get("evidence_refs"),list) and bool(i["evidence_refs"]) for i in items),"verification_checks","检查需要状态、具体观察和依据")
        checks+=items
    protected={_text(item) for item in contract["protected_facts"]}
    checked={i.get("item") for i in value["preservation_checks"]}
    require(protected<=checked,"preservation_coverage","每项冻结的源图保护事实必须单独检查")
    if strict_reference:
        artifacts=[item.get("item") for item in value["artifact_checks"]]
        require(len(artifacts)==len(set(artifacts)) and set(artifacts)==ARTIFACT_CHECKS,
                "artifact_coverage","必须各检查一次 naturalness、reference_content_leakage、unsupported_detail")
        preservation=[item.get("item") for item in value["preservation_checks"]]
        require(len(preservation)==len(set(preservation)) and set(preservation)==protected,
                "preservation_coverage","源图保护项必须精确逐项检查，不得遗漏、重复或替换")
        for row in rows:_require_roles(row["evidence_refs"],"A","B","C")
        for row in value["preservation_checks"]:_require_roles(row["evidence_refs"],"A","C")
        for row in value["artifact_checks"]:
            _require_roles(row["evidence_refs"],*(('B','C') if row["item"]=='reference_content_leakage' else ('A','C')))
    if any(i["status"]=="fail" for i in checks): return "reject"
    mandatory={t["target_id"] for t in contract["targets"] if t["mandatory"]}
    if any(i["status"]=="uncertain" for i in checks) or any(r["target_id"] in mandatory and r["status"]=="uncertain" for r in rows): return "uncertain"
    if any(r["target_id"] in mandatory and r["status"]!="achieved" for r in rows): return "revise"
    return "accept"

def _text(item):
    if isinstance(item,str): return item
    return str(item.get("description",item.get("observation",item)))

def compile_prompt(contract,correction=None):
    validate_contract(contract)
    lines=["Edit image 1 using image 2 as an appearance reference.",
           "Image 1 is the source and defines identity, expression, objects, readable text, authentic visible detail, viewpoint, framing and scene geometry.",
           "Image 2 defines only the selected photographic appearance below. Apply all required changes to image 1:"]
    for t in contract["targets"]:
        lines.append(f"[{t['target_id']}] Source region: {t['source_region']}; corresponding reference region: {t['reference_region']}. Source appearance: {t['source_observation']}. Reference observation: {t['reference_observation']}. Change: {t['desired_change']}. Success: {t['acceptance_criterion']}.")
    lines.append("Preserve source facts: "+"; ".join(_text(x) for x in contract["protected_facts"]))
    lines.append("Exclude these reference traits: "+"; ".join(_text(x) for x in contract["excluded_reference_traits"]))
    if correction: lines.append("Targeted correction, while retaining every goal above: "+str(correction))
    lines+=["Keep the source lighting direction and natural texture. Leave unreadable text and genuinely missing detail unresolved.",
            "Return one photorealistic edited photograph on the declared canvas with the source composition. No captions, labels, collage or additional objects."]
    return "\n".join(lines)
