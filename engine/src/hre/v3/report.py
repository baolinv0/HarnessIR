"""Portable side-by-side output review; no invented quality scores or rankings."""
from __future__ import annotations

import csv
import html
import io
import json
from pathlib import Path
import shutil

from PIL import Image

from ..models import file_sha256, now
from ..storage import atomic_write, read_json, write_json
from .common import require
from .contracts import load_case


def _copy_image(asset: dict | None, output: Path) -> str | None:
    if not asset:
        return None
    source = Path(asset["path"])
    require(source.is_file() and file_sha256(source) == asset["sha256"], "report_image_modified", "Image changed before report export")
    relative = "images/" + asset["sha256"] + ".png"
    target = output / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.copyfile(source, target)
    require(file_sha256(target) == asset["sha256"], "report_image_modified", "Report asset collision")
    return relative


def _row(case_root: Path, output: Path, labels: dict | None = None) -> dict:
    spec, config, state = load_case(case_root)
    from .runner_journal import Journal
    state = Journal(case_root, state, read_only=True).state
    labels = labels or {}
    selected = state.get("selected_output")
    candidates = []
    for candidate in state.get("candidates", []):
        candidates.append({**{key: candidate.get(key) for key in ("candidate_id", "round", "provider_order", "geometry_valid", "delivery_status", "verification", "appearance_status", "delivery_assessment")},
                           "native_size": [candidate["native"]["width"], candidate["native"]["height"]],
                           "delivered_size": [candidate["delivered"]["width"], candidate["delivered"]["height"]],
                           "native_image": _copy_image(candidate.get("native"), output),
                           "delivered_image": _copy_image(candidate.get("delivered"), output),
                           "native_sha256": (candidate.get("native") or {}).get("sha256"),
                           "delivered_sha256": (candidate.get("delivered") or {}).get("sha256")})
    observations = []
    for item in state.get("observations", []):
        ref = item.get("result")
        if ref:
            path = case_root / ref["path"]
            require(file_sha256(path) == ref["sha256"], "report_receipt_modified", "A run receipt changed before report export")
            result = read_json(path)
            observation = result.get("observation", {})
            observations.append({"operation_id": item["operation_id"], "kind": item["kind"], "charge": item["charge"],
                                 "recovered": item.get("recovered"), "observation": observation, "result": result})
    conditions = []
    for round_record in state.get("rounds", []):
        ref = round_record.get("condition")
        if ref:
            path = case_root / ref["path"]
            require(file_sha256(path) == ref["sha256"], "report_condition_modified", "Frozen round condition changed")
            conditions.append({"round": round_record["round"], "condition": read_json(path)})
    elapsed = {}
    for item in observations:
        observation = item["observation"]
        seconds = observation.get("total_elapsed_seconds", observation.get("elapsed_seconds"))
        if isinstance(seconds, (int, float)):
            elapsed[item["kind"]] = elapsed.get(item["kind"], 0.0) + seconds
    model = config["models"][spec["profile_id"]]
    reference_workflow = None
    if spec.get("workflow_contract") == "reference_retouch_v1":
        reference_workflow = {"version": spec["workflow_contract"], "delivery_requirements": spec.get("delivery_requirements", {}),
                              "compiled_conditions": [{"round": c["round"], "text": c["condition"].get("text"),
                                  "condition_kind": c["condition"].get("condition_kind")} for c in conditions]}
        for name in ("diagnosis", "evidence", "reference_contract"):
            ref = state.get("artifacts", {}).get(name)
            if ref:
                path = (case_root / ref["path"]).resolve()
                require(path.is_relative_to(case_root) and file_sha256(path) == ref["sha256"],
                        "report_artifact_modified", "Reference workflow evidence changed")
                reference_workflow[name] = read_json(path)
    return {"case_root": str(case_root), "case_id": spec["case_id"],
            "dataset_case_id": labels.get("dataset_case_id", spec["case_id"]),
            "profile_id": spec["profile_id"], "model_id": model["editor"]["model_id"],
            "model_revision": model["editor"].get("revision"), "compiler": model["compiler"]["backend"],
            "arm": labels.get("arm", spec["strategy"]), "strategy": spec["strategy"],
            "seed": labels.get("seed", spec["policy"]["seed_schedule"][0]), "seed_schedule": spec["policy"]["seed_schedule"],
            "task_mode": spec["task_mode"], "brief": spec["brief"], "regions": spec.get("regions", []),
            "policy": spec["policy"]["mode"], "status": state["status"], "success": state.get("success", False),
            "quality_status": state.get("quality_status", "not_evaluated"), "selected_kind": state.get("selected_kind"),
            "delivery_assessment": state.get("delivery_assessment"),
            "terminal_reason": state.get("terminal_reason") or state.get("pause_reason"),
            "budget": state.get("budget", {}), "elapsed_seconds": elapsed,
            "source_image": _copy_image(state["inputs"][0], output),
            "reference_image": _copy_image(state["inputs"][1], output) if len(state["inputs"]) > 1 else None,
            "selected_image": _copy_image(selected, output), "selected_sha256": selected.get("sha256") if selected else None,
            "selected_candidate_id": state.get("selected_candidate_id"),
            "geometry": spec["geometry"], "spatial": spec["spatial"], "alpha_policy": spec["alpha_policy"],
            "planning_origin": state.get("planning_origin"), "candidates": candidates, "observations": observations,
            "reference_workflow": reference_workflow,
            "conditions": conditions, "task": spec, "runtime_config": config,
            "deviations": state.get("deviations", [])}


def export_report(root: Path, output: Path) -> dict:
    root, output = Path(root).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    records = []
    errors = []
    if (root / "batch.state.json").is_file():
        batch = read_json(root / "batch.state.json")
        inputs = [(Path(row["case_root"]), row) for row in batch["runs"]]
        planning = batch.get("planning", [])
    else:
        inputs, planning = [(root, {})], []
    for case_root, labels in inputs:
        try:
            records.append(_row(case_root, output, labels))
        except Exception as exc:
            errors.append({**labels, "case_root": str(case_root), "error": str(exc)})
    report = {"schema_version": "hre_comparison_report_v3", "created_at": now(), "runs": records,
              "planning": planning, "unavailable_runs": errors,
              "interpretation": "Verifier decisions are observations, not ground-truth quality measurements. Native outputs, delivered outputs and source-baseline selections are distinct."}
    write_json(output / "report.json", report)
    fields = ["dataset_case_id", "profile_id", "model_id", "model_revision", "compiler", "arm", "seed", "task_mode", "policy",
              "status", "quality_status", "selected_kind", "generations", "stage_calls", "compiler_calls",
              "compiler_seconds", "image_seconds", "selected_sha256", "case_root"]
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for record in records:
        values = {**record, **record["budget"], "compiler_seconds": record["elapsed_seconds"].get("compile"),
                  "image_seconds": record["elapsed_seconds"].get("generate")}
        writer.writerow({key: values.get(key) for key in fields})
    atomic_write(output / "comparisons.csv", stream.getvalue().encode("utf-8-sig"))
    # Only compact viewer data is embedded; full native responses stay in JSON.
    viewer = [{key: value for key, value in row.items() if key not in {"observations", "conditions", "task", "runtime_config"}} for row in records]
    data = json.dumps(viewer, ensure_ascii=False).replace("<", "\\u003c")
    failures = html.escape(json.dumps(errors, ensure_ascii=False, indent=2))
    page = _HTML.replace("__DATA__", data).replace("__ERRORS__", failures)
    atomic_write(output / "index.html", page.encode("utf-8"))
    return {"html": str(output / "index.html"), "csv": str(output / "comparisons.csv"),
            "json": str(output / "report.json"), "runs": len(records), "unavailable": len(errors)}


_HTML = r'''<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>HarnessIR · 四模型对比</title>
<style>
*{box-sizing:border-box}body{font:15px/1.6 system-ui,sans-serif;margin:0;background:#f3f5f8;color:#172336}
header{background:#14243c;color:white;padding:28px 4vw}h1{font-size:26px;margin:0 0 6px}p{margin:8px 0}
main{padding:22px 4vw}nav{display:flex;gap:16px;flex-wrap:wrap;align-items:center;margin-bottom:20px}
select,button{font:inherit;padding:7px;border:1px solid #bdc8d7;border-radius:6px;background:white}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:18px;margin:20px 0}
.card{background:white;border:1px solid #dce1e9;border-radius:10px;overflow:hidden;min-width:0}.card h2,.body{padding:12px 16px;margin:0}.card h2{font-size:17px}
.card img{display:block;max-width:100%;max-height:65vh;object-fit:contain;margin:auto;cursor:zoom-in;background:#e5e8ed}
.tag{font-size:12px;padding:3px 7px;border-radius:4px;background:#e9eef5;display:inline-block;margin:3px 4px 3px 0}
.bad{color:#9b3030;background:#fff0ed}.small{font-size:13px;color:#506179}.row{display:flex;gap:16px;flex-wrap:wrap}.row>.card{flex:1;min-width:280px}
details{padding:8px 0}summary{cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}
dialog{max-width:96vw;max-height:96vh;padding:14px;border:0;border-radius:8px}dialog img{max-width:none;max-height:none;cursor:zoom-out}dialog::backdrop{background:#000c}
a{color:#1762a3}#zoomBox{overflow:auto;max-width:90vw;max-height:84vh}label{font-weight:600}
</style>
<header><h1>HarnessIR · Qwen / FireRed / FLUX / FIBO</h1><p>原生结果、交付结果和原图基线分别展示。Verifier 判断不等同于真实画质结论。</p></header>
<main><nav><label>案例 <select id="case"></select></label><label>对比臂 <select id="arm"></select></label><label>种子 <select id="seed"></select></label>
<a href="comparisons.csv">CSV</a><a href="report.json">完整记录 JSON</a></nav>
<p id="brief"></p><div class="row" id="inputs"></div><div class="grid" id="models"></div>
<details><summary>未能导出的运行</summary><pre>__ERRORS__</pre></details></main>
<dialog id="zoom"><button id="close">关闭</button><div id="zoomBox"></div></dialog>
<script>
const rows=__DATA__;
const $=id=>document.getElementById(id);const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function options(id,values){const previous=$(id).value;$(id).innerHTML=[...new Set(values)].map(v=>`<option>${esc(v)}</option>`).join('');if(values.map(String).includes(previous))$(id).value=previous;}
function image(src,label){return src?`<img src="${esc(src)}" alt="${esc(label)}" loading="lazy" onclick="zoomImage(this.src)">`:'<div class="body small">暂无图像</div>';}
function zoomImage(src){$('zoomBox').innerHTML=image(src,'原尺寸图像');$('zoom').showModal();$('zoomBox').querySelector('img').onclick=()=>$('zoom').close();}
$('close').onclick=()=>$('zoom').close();
function render(){const matching=rows.filter(r=>r.dataset_case_id===$('case').value&&r.arm===$('arm').value&&String(r.seed)===$('seed').value);const first=matching[0];
 $('brief').textContent=first?first.brief:'该组合没有可导出结果';$('inputs').innerHTML=first?`<div class="card"><h2>原始 source</h2>${image(first.source_image,'原始source')}</div>`+(first.reference_image?`<div class="card"><h2>外观 reference</h2>${image(first.reference_image,'参考')}</div>`:''):'';
 $('models').innerHTML=matching.map(r=>`<article class="card"><h2>${esc(r.profile_id)}</h2>${image(r.selected_image,r.profile_id)}<div class="body">
 <span class="tag ${['accepted','already_satisfied'].includes(r.quality_status)?'':'bad'}">${esc(r.quality_status)}</span><span class="tag">${esc(r.selected_kind||r.status)}</span>
 <p class="small">${esc(r.compiler)} · ${esc(r.policy)} · 生成 ${r.budget.generations??0} · 编译调用 ${r.budget.compiler_calls??0}</p>
 ${r.selected_kind==='source_baseline'?'<p class="bad">当前展示原图基线；没有合格的模型交付图。</p>':''}
 ${r.selected_kind==='source_already_satisfied'?'<p>参考目标已经满足，零次图像生成保留原图。</p>':''}
 ${r.delivery_assessment?`<details><summary>原图交付门槛：${r.delivery_assessment.pass?'通过':'未通过'}</summary><pre>${esc(JSON.stringify(r.delivery_assessment,null,2))}</pre></details>`:''}
 ${r.reference_workflow?`<details><summary>参考分析 → 证据 → 冻结目标 → 实际编辑条件</summary><pre>${esc(JSON.stringify(r.reference_workflow,null,2))}</pre></details>`:''}
 <details><summary>全部候选与分项验收 (${r.candidates.length})</summary>${r.candidates.map(c=>`<p>轮次 ${c.round} · provider ${c.provider_order} · geometry=${esc(c.geometry_valid)}</p><div class="small">原生输出 ${esc(c.native_size?.join(' × '))}</div>${image(c.native_image,'原生输出')}<div class="small">交付输出 ${esc(c.delivered_size?.join(' × '))}</div>${image(c.delivered_image,'交付输出')}${c.delivery_assessment?`<p>外观：${esc(c.appearance_status)} · 交付条件：${c.delivery_assessment.pass?'通过':'未通过'}</p><pre>${esc(JSON.stringify(c.delivery_assessment,null,2))}</pre>`:''}<pre>${esc(JSON.stringify(c.verification,null,2))}</pre>`).join('')}</details>
 <details><summary>几何、预算与版本</summary><pre>${esc(JSON.stringify({revision:r.model_revision,geometry:r.geometry,spatial:r.spatial,budget:r.budget,seconds:r.elapsed_seconds,deviations:r.deviations,reason:r.terminal_reason},null,2))}</pre></details></div></article>`).join('');}
function update(){const subset=rows.filter(r=>r.dataset_case_id===$('case').value);options('arm',subset.map(r=>r.arm));options('seed',subset.filter(r=>r.arm===$('arm').value).map(r=>r.seed));render();}
options('case',rows.map(r=>r.dataset_case_id));$('case').onchange=update;$('arm').onchange=()=>{const sub=rows.filter(r=>r.dataset_case_id===$('case').value&&r.arm===$('arm').value);options('seed',sub.map(r=>r.seed));render();};$('seed').onchange=render;update();
</script></html>'''
