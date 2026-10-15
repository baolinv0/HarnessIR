"""Offline, read-only visual audit of real inputs and accepted workflow artifacts.

This renderer never invokes a model, advances a state, reads references, or treats
an existing external file as validated evidence. Embedded images are display
previews; the original files and their hashes remain the experiment identity.
"""
import base64
import difflib
import html
import io
import json
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .local_evidence import PAYLOADS, validate_local_evidence
from .protocol import check_bboxes, validate_schema
from .service import history
from .storage import CasePaths, atomic_write, now, read_json, resolve_case_path, sha256_file, transactions, write_json

TOOLS = {"T1_OCR": "T1 · OCR", "T2_FACE": "T2 · 人脸", "T3_DEPTH": "T3 · 浮点深度", "T4_SEGMENTATION": "T4 · 实例分割"}


def _escape(value):
    return html.escape(str(value), quote=True)


def _json(value):
    return _escape(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def _inside(path, base):
    path, base = Path(path).resolve(), Path(base).resolve()
    if not path.is_relative_to(base) or path == base:
        raise ValueError("Report artifact path escapes its permitted directory")
    return path


def _read(path, maximum=8 * 1024 * 1024):
    if path.stat().st_size > maximum:
        raise ValueError("Report JSON exceeds byte limit")
    return read_json(path)


def _preview(path):
    with Image.open(path) as source:
        if source.width * source.height > 40_000_000:
            raise ValueError("Report image exceeds pixel limit")
        source.load()
        result = source.convert("RGB")
    result.thumbnail((1000, 800), Image.Resampling.LANCZOS)
    return result


def _image(image, caption):
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=86)
    uri = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
    return '<figure><img loading="lazy" src="' + uri + '" alt="' + _escape(caption) + '"><figcaption>' + _escape(caption) + "</figcaption></figure>"


def _asset(base, relative, assets):
    descriptor = next((a for a in assets if a["path"] == relative), None)
    if descriptor is None:
        raise ValueError("Map is not a declared hashed evidence asset")
    path = resolve_case_path(base, relative)
    if sha256_file(path) != descriptor["sha256"]:
        raise ValueError("Evidence asset hash changed")
    return path


def _grid(path):
    if path.suffix == ".npy":
        from .local_evidence import _grid as validated_grid
        array = validated_grid(path.parent, path.name)
    else:
        with Image.open(path) as source:
            source.load()
            array = np.asarray(source)
    if array.size > 120_000_000 or array.dtype.hasobject:
        raise ValueError("Unsupported report array")
    return array


def _mapped(source, view, size, nearest=False):
    """Map a native view grid into the canonical image's thumbnail geometry."""
    matrix = np.linalg.inv(np.asarray(view["view_to_canonical"], dtype=np.float64))
    width, height = size
    coefficients = (matrix[0, 0] / width, matrix[0, 1] / height, matrix[0, 2], matrix[1, 0] / width, matrix[1, 1] / height, matrix[1, 2])
    return source.transform(size, Image.Transform.AFFINE, coefficients, resample=Image.Resampling.NEAREST if nearest else Image.Resampling.BILINEAR)


def _maps(manifest, base, original):
    """All overlays are annotations, never restoration outputs."""
    data, tool, assets = manifest["data"], manifest["tool_id"], manifest["assets"]
    views = {v["id"]: v for v in manifest["views"]}
    fragments = []
    if tool in ("T1_OCR", "T2_FACE"):
        overlay = original.copy()
        draw = ImageDraw.Draw(overlay)
        width, height = overlay.size
        items = data.get("items", data.get("faces", []))
        for index, item in enumerate(items):
            colour = (255, 197, 58) if tool == "T1_OCR" else (76, 241, 206)
            if "polygon_norm" in item:
                points = [(x * width, y * height) for x, y in item["polygon_norm"]]
                draw.line(points + [points[0]], fill=colour, width=3)
            else:
                x0, y0, x1, y1 = item["bbox_norm"]
                draw.rectangle((x0 * width, y0 * height, x1 * width, y1 * height), outline=colour, width=3)
                for x, y in item.get("landmarks5_norm") or []:
                    draw.ellipse((x * width - 3, y * height - 3, x * width + 3, y * height + 3), fill=(255, 77, 121))
            box = item["bbox_norm"]
            draw.text((box[0] * width, box[1] * height), str(index + 1), fill=colour)
        fragments.append(_image(overlay, "原图坐标标注；仅用于证据检查"))
        if not items:
            fragments.append('<p class="empty">工具成功运行，未检测到对象；这不证明原图中不存在对象。</p>')
        for index, item in enumerate(items):
            fragments.append("<details><summary>" + str(index + 1) + " · " + _escape(item["id"]) + (" · " + _escape(item.get("text")) if tool == "T1_OCR" else "") + "</summary><pre>" + _json(item) + "</pre></details>")
        if tool == "T2_FACE":
            fragments.append("<p>五点按 SCRFD 原生顺序：eye_0、eye_1、nose、mouth_0、mouth_1。小脸定位不代表身份或细节可恢复。</p>")
    elif tool == "T3_DEPTH":
        values = _grid(_asset(base, data["depth_path"], assets))
        valid = _grid(_asset(base, data["valid_mask_path"], assets)) != 0
        if values.dtype != np.float32 or values.shape != valid.shape or not valid.any() or not np.isfinite(values[valid]).all():
            raise ValueError("Invalid float depth or validity mask")
        native = _preview(_asset(base, data["preview_path"], assets))
        # The saved preview is reduced only for standalone display; mapping uses
        # its full native grid, so thumbnail reduction never changes coordinates.
        with Image.open(_asset(base, data["preview_path"], assets)) as image:
            mapped = _mapped(image.convert("RGB"), views[data["view_id"]], original.size)
        alpha = _mapped(Image.fromarray((valid * 140).astype(np.uint8)), views[data["view_id"]], original.size, nearest=True)
        combined = original.copy()
        combined.paste(mapped, mask=alpha)
        fragments.extend([_image(native, "工具原生深度预览；并非恢复图"), _image(combined, "深度证据映射到原图；半透明展示")])
        fragments.append("<p>float32 相对深度；较大值 = " + ("更近" if data["larger_is"] == "near" else "更远") + "；有限值范围 " + _escape(data["finite_value_range"]) + "。不表示米制距离。</p><pre>" + _json({"normalization": data["normalization"], "view": views[data["view_id"]]}) + "</pre>")
    elif tool == "T4_SEGMENTATION":
        palette = _read(_asset(base, data["palette_path"], assets))
        colours = {r["class_id"]: r["rgb"] for r in palette["classes"]}
        combined = original.copy()
        overlap = np.zeros((original.height, original.width), dtype=np.uint16)
        masks = data["native_masks"]
        for item in sorted(masks, key=lambda r: ((r["score"] or 0), -r["prompt_index"], r["id"]), reverse=False):
            mask = _grid(_asset(base, item["mask_path"], assets)) != 0
            mapped = _mapped(Image.fromarray((mask * 110).astype(np.uint8)), views[item["view_id"]], original.size, nearest=True)
            overlap += np.asarray(mapped) != 0
            layer = Image.new("RGB", original.size, tuple(colours[item["prompt_index"] + 1]))
            combined.paste(layer, mask=mapped)
        fragments.append(_image(combined, "原生实例 Mask 映射到原图；实例可重叠"))
        if not masks:
            fragments.append('<p class="empty">工具成功运行，固定类别集中未检测到实例；未知区域保持未知。</p>')
        fragments.append("<p>显示压缩并不覆盖原生实例；当前预览重叠像素 " + str(int((overlap > 1).sum())) + "。标准分类图遵循 " + _escape(data["display_overlap_rule"]) + "，未知编号 0。</p>")
        for entry in palette["classes"]:
            fragments.append('<span class="legend"><i style="background:rgb(' + ",".join(str(int(v)) for v in entry["rgb"]) + ')"></i>' + _escape(str(entry["class_id"]) + " · " + entry["label"]) + "</span>")
        fragments.append("<details><summary>类别、实例与原始 Mask 关联</summary><pre>" + _json(masks) + "</pre></details>")
    return "".join(fragments)


def _case_evidence(case, manifest, expected_hash):
    if manifest.get("protocol_version") != "1.1":
        raise ValueError("Accepted legacy evidence is not a v1.1 verified map")
    validate_schema("evidence_local.schema.json", manifest)
    validate_schema(PAYLOADS[manifest["tool_id"]], manifest["data"])
    check_bboxes(manifest)
    if manifest["input_sha256"] != expected_hash or manifest["status"] != "ok":
        raise ValueError("Evidence image identity or status mismatch")
    # Accepted case history is immutable; check every bound asset again before
    # displaying it, rather than trusting cache presence or a copied thumbnail.
    for asset in manifest["assets"]:
        _asset(case.case_dir, asset["path"], manifest["assets"])
    bindings = [tx["event"]["details"].get("binding") for tx in transactions(case) if tx["event"]["type"] == "tool_registered"]
    binding = next((b for b in bindings if b and b["tool_id"] == manifest["tool_id"] and b["cache_key"] == manifest["cache_key"]), None)
    if not binding:
        raise ValueError("Accepted local evidence has no immutable binding")
    path = case.path(binding["case_manifest_path"])
    if sha256_file(path) != binding["case_manifest_sha256"] or _read(path) != manifest:
        raise ValueError("Bound evidence manifest changed")
    return manifest, case.case_dir


def _external_evidence(record, root, expected_hash):
    if record.get("status") not in ("validated", "empty") or not record.get("evidence_dir"):
        raise ValueError("External file has not passed offline validation")
    directory = _inside(record["evidence_dir"], root)
    contract = _read(directory / "contract.json")
    manifest = validate_local_evidence(directory, contract).model_dump()
    if manifest["input_sha256"] != expected_hash or manifest["tool_id"] != record["tool_id"]:
        raise ValueError("Offline validated evidence belongs to another image/tool")
    return manifest, directory


def _records(path, key="records"):
    if not path.exists():
        return []
    value = _read(path)
    return value.get(key, []) if isinstance(value, dict) else []


def _accepted_outputs(case, expected_hash):
    config = _read(case.path("case_config.json"))
    state = _read(case.path("state.json"))
    if state["input_sha256"] != expected_hash:
        raise ValueError("Case image identity differs from the sample")
    records, rejected = [], []
    for item in history(case)["rounds"]:
        asset = item.get("output_asset")
        if not asset:
            continue
        try:
            path = case.path(asset["path"])
            accepted_prefixes = ("rounds/", "tasks/" + item["task_id"] + "/")
            if not asset["path"].startswith(accepted_prefixes) or sha256_file(path) != asset["sha256"]:
                raise ValueError("Output not an immutable accepted round artifact")
            if asset["sha256"] == expected_hash:
                raise ValueError("Unchanged source copy cannot establish restoration")
            if not item.get("valid_image_constraints", item.get("valid_geometry", False)):
                raise ValueError("Accepted output failed image constraints")
            records.append((item, path))
        except (ValueError, OSError) as exc:
            rejected.append(str(exc))
    return records, rejected, config, state


def _prompts(case):
    fragments = []
    previous = ""
    for record in history(case)["rounds"]:
        composition = record.get("composition")
        if not composition:
            continue
        instruction = composition["instruction"]
        diff = "\n".join(difflib.unified_diff(previous.splitlines(), instruction.splitlines(), fromfile="上一轮指令", tofile="当前指令", lineterm="")) if previous else "首轮指令；尚无上一轮。"
        fragments.append("<details open><summary>已接受编辑指令 · Round " + _escape(record["round"]) + "</summary><pre>" + _escape(instruction) + "</pre><details><summary>提示词变化</summary><pre>" + _escape(diff) + "</pre></details><details><summary>Composer 完整 JSON</summary><pre>" + _json(composition) + "</pre></details></details>")
        previous = instruction
    state = _read(case.path("state.json"))
    if state.get("pending_task_id"):
        request = _read(case.path("tasks/" + state["pending_task_id"] + "/request.json"))
        # These are the actual immutable task prompt files, not invented editing
        # instructions; a pending Composer has not yet returned an instruction.
        if request["role"] in ("compose", "refine", "execute", "verify"):
            task_info = next((tx.get("next_task") for tx in reversed(list(transactions(case))) if tx.get("next_task") and tx["next_task"]["task_id"] == request["task_id"]), None)
            prompt_path = case.path(request["prompt_file"])
            if not task_info or sha256_file(prompt_path) != task_info["prompt_sha256"]:
                return "".join(fragments) + '<p class="rejected">待执行任务提示词哈希改变；拒绝显示未验证指令。</p>'
            prompt = prompt_path.read_text(encoding="utf-8")
            fragments.append("<details><summary>待执行任务原文 · " + _escape(request["role"]) + "（未完成）</summary><pre>" + _escape(prompt) + "</pre></details>")
    return "".join(fragments) or '<p class="missing">Composer 尚未返回编辑指令；没有提示词变化可评价。</p>'


def render_gallery(root: Path, batch: Path, out: Path, offline_status: dict | None = None) -> Path:
    """Save a self-contained report.html and machine-readable summary.json.

    offline_status records accept only validated/empty standard evidence dirs;
    raw server files need the root importer's validation before visualization.
    """
    root = Path(root).resolve()
    batch = _inside(batch, root / "runtime")
    out = _inside(out, root / "runtime")
    manifest = _read(batch / "manifest.json")
    accepted = {r["sample_id"]: r for r in _records(batch / "diagnostic_results.json")}
    external = {(r.get("image_id"), r.get("tool_id")): r for r in (offline_status or {}).get("records", [])}
    case_roots = [batch / "workflow", root]
    candidates = []
    for case_root in case_roots:
        for directory in (case_root / "cases").glob("*"):
            try:
                case = CasePaths(directory.name, case_root)
                config, state = _read(case.path("case_config.json")), _read(case.path("state.json"))
                if sha256_file(case.path("case_config.json")) != state["config_sha256"]:
                    continue
                candidates.append((case, config, state))
            except (ValueError, OSError, KeyError):
                continue
    sections, summaries, index = [], [], []
    totals = Counter()
    for number, sample in enumerate(manifest["images"], 1):
        image_id = sample["sample_id"]
        anchor = "sample-" + str(number)
        index.append('<a href="#' + anchor + '">' + str(number).zfill(2) + " · " + _escape(image_id) + "</a>")
        errors, cards = [], []
        summary = {"image_id": image_id, "canonical_sha256": sample["canonical_sha256"], "tools": {}, "direct_outputs": 0, "harness_outputs": 0, "verified_outputs": 0, "restoration_success": None, "errors": errors}
        try:
            canonical = _inside(sample["canonical_path"], batch)
            if sha256_file(canonical) != sample["canonical_sha256"]:
                raise ValueError("Canonical input hash changed")
            original = _preview(canonical)
            cards.append(_image(original, "输入原图的 sRGB 显示预览；无恢复处理"))
        except (ValueError, OSError) as exc:
            errors.append(str(exc))
            original = None
        case_id = accepted.get(image_id, {}).get("case_id")
        case = next((c for c, config, state in candidates if c.case_id == case_id), None)
        hist = history(case) if case else {"diagnosis": None, "evidence": [], "rounds": []}
        diagnosis = hist["diagnosis"]
        if not diagnosis:
            path = batch / "diagnoses" / (image_id + ".json")
            try:
                path = _inside(path, batch / "diagnoses")
                diagnosis = _read(path)
                validate_schema("diagnosis.schema.json", diagnosis)
            except (ValueError, OSError):
                diagnosis = None
        if diagnosis:
            cards.append("<div class=diagnosis><h3>诊断</h3><p>" + _escape(diagnosis["content"]) + "</p><p>" + _escape(diagnosis["sensitive"]["notes"]) + "</p><p>工具计划：" + _escape(", ".join(p["tool"] for p in diagnosis["tool_plan"]) or "空计划") + "</p><details><summary>诊断完整内容</summary><pre>" + _json(diagnosis) + "</pre></details></div>")
            totals["diagnoses"] += 1
        else:
            cards.append('<p class="missing">诊断缺失或无效。</p>')
        local = {m["tool_id"]: m for m in hist["evidence"]}
        for tool, title in TOOLS.items():
            record = external.get((image_id, tool))
            status = record.get("status", "pending") if record else "pending"
            body = '<p class="missing">证据尚未生成或未完成校验。</p>'
            if tool in local or (record and status in ("validated", "empty")):
                try:
                    evidence, base = _case_evidence(case, local[tool], sample["canonical_sha256"]) if tool in local else _external_evidence(record, root, sample["canonical_sha256"])
                    if original is None:
                        raise ValueError("Input invalid; evidence overlay disabled")
                    if (evidence["source_width"], evidence["source_height"]) != (sample["width"], sample["height"]):
                        raise ValueError("Evidence original dimensions disagree with actual input")
                    body = _maps(evidence, base, original)
                    data = evidence["data"]
                    empty = tool != "T3_DEPTH" and not data.get("items", data.get("faces", data.get("native_masks", [])))
                    status = "empty" if empty else "validated"
                    body += "<details><summary>模型、合同及资源记录</summary><pre>" + _json({k: evidence[k] for k in ("model_name", "model_bundle_sha256", "backend", "evidence_profile_id", "formal_eligible", "cache_key", "elapsed_ms", "peak_rss_mb", "quality_warnings")}) + "</pre></details>"
                    totals["evidence_validated"] += 1
                except (ValueError, OSError, KeyError, TypeError) as exc:
                    status = "rejected"
                    errors.append(tool + ": " + str(exc))
                    body = '<p class="rejected">证据拒绝显示：' + _escape(exc) + "</p>"
            elif record:
                body = "<p class=" + ("rejected" if status == "rejected" else "missing") + ">" + _escape(status) + "：外部文件尚未被接受为有效证据。</p><pre>" + _json({k: record[k] for k in ("status", "error", "errors", "reason", "source_paths") if k in record}) + "</pre>"
            summary["tools"][tool] = status
            cards.append("<div class=evidence><h3>" + title + " <span class=badge>" + _escape(status) + "</span></h3>" + body + "</div>")
        output_cards = []
        for kind in ("direct", "harness"):
            matches = [(c, config, state) for c, config, state in candidates if state.get("input_sha256") == sample["canonical_sha256"] and (c.case_id == case_id if kind == "harness" else str(config.get("branch_type", "")).lower() in ("direct", "direct_baseline", "direct_1"))]
            images = []
            for output_case, config, state in matches:
                try:
                    records, rejected, config, state = _accepted_outputs(output_case, sample["canonical_sha256"])
                    errors.extend(rejected)
                    for record, path in records:
                        summary[kind + "_outputs"] += 1
                        verification = record.get("verification")
                        if verification:
                            summary["verified_outputs"] += 1
                        caption = kind.title() + " · Round " + str(record["round"]) + (" · 首轮" if record["round"] == 1 else " · 后续轮次")
                        if state.get("selected_round") == record["round"]:
                            caption += " · Controller 最终选定轮次"
                        images.append(_image(_preview(path), caption) + "<p>实际接受输出 SHA256：" + _escape(record["output_asset"]["sha256"]) + "</p><details><summary>独立 Verifier 记录</summary><pre>" + _json(verification if verification else {"status": "pending", "restoration_success": None}) + "</pre></details>")
                    if kind == "harness":
                        summary["workflow_status"] = state["workflow_status"]
                        # Completion/success comes only from Controller state;
                        # missing Verifier/output never becomes a success claim.
                        if records and any(r.get("verification") for r, _ in records):
                            summary["restoration_success"] = state.get("restoration_success")
                except (ValueError, OSError) as exc:
                    errors.append(str(exc))
            output_cards.append("<div class=output><h3>" + kind.title() + " 真实输出</h3>" + ("".join(images) or '<p class="missing">尚无已接受真实编辑输出；原图不会充当恢复结果。</p>') + "</div>")
        cards.extend(output_cards)
        cards.append("<div class=prompts><h3>提示词与变化</h3>" + (_prompts(case) if case else '<p class="missing">未找到已接受 case。</p>') + "</div>")
        cards.append("<details class=identity><summary>输入与 case 身份</summary><pre>" + _json({"original_sha256": sample["original_sha256"], "canonical_sha256": sample["canonical_sha256"], "dimensions": [sample["width"], sample["height"]], "canonical_display_note": sample.get("canonical_display_note"), "case_id": case_id, "stratum": sample["stratum"]}) + "</pre></details>")
        if errors:
            cards.append('<div class="rejected"><h3>校验/显示问题</h3><pre>' + _json(errors) + "</pre></div>")
        totals["direct_outputs"] += summary["direct_outputs"]
        totals["harness_outputs"] += summary["harness_outputs"]
        totals["verified_outputs"] += summary["verified_outputs"]
        sections.append('<section id="' + anchor + '"><h2>' + str(number).zfill(2) + " · " + _escape(image_id) + "</h2><div class=grid>" + "".join(cards) + "</div></section>")
        summaries.append(summary)
    summary = {"created_at": now(), "batch": str(batch), "input_count": len(summaries), "diagnoses": totals["diagnoses"], "validated_evidence_count": totals["evidence_validated"], "direct_output_count": totals["direct_outputs"], "harness_output_count": totals["harness_outputs"], "independent_verifier_count": totals["verified_outputs"], "restoration_effect_conclusion": "unassessed_without_real_outputs_and_independent_verification", "references_read": False, "display_previews_only": True, "self_contained_html": True, "records": summaries}
    css = "body{margin:0;background:#eef1f4;color:#20303d;font:15px system-ui,sans-serif}header,main{max-width:1440px;margin:auto;padding:28px}header{background:#122734;color:white}h1{margin:0 0 16px}nav{display:flex;gap:8px;flex-wrap:wrap}nav a{padding:6px 9px;background:#fff1;color:white;border-radius:4px}section{background:white;border-radius:10px;margin:22px 0;padding:24px;scroll-margin-top:12px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,380px),1fr));gap:20px}.grid>div,.grid>figure,.grid>details{border:1px solid #dde4ea;padding:14px;border-radius:6px;margin:0}img{max-width:100%;height:auto;border-radius:4px}figcaption{color:#607585;margin:8px 0}figure{margin:10px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;max-height:500px;overflow:auto}summary{cursor:pointer;padding:8px 0}.badge{font-size:12px;background:#e8edf0;padding:3px 6px;border-radius:4px}.missing{color:#896424}.rejected{color:#a43838}.empty{color:#25704b}.legend{display:inline-block;margin:5px}.legend i{display:inline-block;width:14px;height:14px;margin-right:5px;border:1px solid #777}.prompts,.identity{grid-column:1/-1}h3{margin-top:0}.notice{line-height:1.8}a{color:#22639a}"
    document = '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'"><title>HarnessIR · 20图离线证据与恢复审计</title><style>' + css + '</style></head><body><header><h1>HarnessIR · 离线证据与恢复审计</h1><p class=notice>逐图展示真实输入、已接受诊断、经过校验的证据、编辑指令与真实输出。灰色缺失项表示未完成，空检测与运行错误分别记录。预览缩小用于显示，不替代原始数组、实例 Mask 或照片；没有联网资源、模型调用或引用 GT。</p><p>样本 ' + str(len(summaries)) + " · 诊断 " + str(totals["diagnoses"]) + " · 有效证据 " + str(totals["evidence_validated"]) + " · Direct 输出 " + str(totals["direct_outputs"]) + " · Harness 输出 " + str(totals["harness_outputs"]) + " · 独立验证 " + str(totals["verified_outputs"]) + "</p><nav>" + "".join(index) + "</nav></header><main>" + "".join(sections) + "</main></body></html>"
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "summary.json", summary)
    atomic_write(out / "report.html", document.encode("utf-8"))
    return out / "report.html"
