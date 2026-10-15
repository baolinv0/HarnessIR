"""Save a five-photo real GPU pilot visual audit from locally validated caches.

No model call, image enhancement, GT read, import or case transition occurs.
Only already saved source/overlay/map images are displayed. Future T1/T3 result
updates must match their own frozen local expected export ledger.
"""
import argparse
import base64
import html
import json
import re
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from hir_manual.cache import EvidenceCache, make_cache_key
from hir_manual.local_evidence import validate_local_evidence
from hir_manual.offline_gallery import _image, _preview
from hir_manual.storage import atomic_write, now, read_json, resolve_case_path, sha256_file, write_json
from hir_manual.tool_registry import gpu_evidence_origin_matches

ORDER = ("T2_FACE", "T1_OCR", "T3_DEPTH", "T4_SEGMENTATION")
DEFAULT_EXPORT = "export_326cd299107343c7a41b4fbac9ccdc37"


def escaped(value):
    return html.escape(str(value), quote=True)


def serialized(value):
    return escaped(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def inside(path, root):
    path = Path(path).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        raise ValueError("Pilot report path escapes workspace")
    return path


def ledger_entries(root, ledger_arguments):
    arguments = list(ledger_arguments or [])
    if not arguments:
        binding = root / "runtime/offline_gpu/export_binding.json"
        if binding.is_file():
            value = read_json(binding)
            arguments.extend(value.get("ledger_ids", []))
            if value.get("bundle_id"):
                arguments.append(value["bundle_id"])
        if not arguments:
            arguments.append(DEFAULT_EXPORT)
    entries, sources = {}, []
    for argument in arguments:
        if re.fullmatch(r"export_[a-f0-9]{32}", str(argument)):
            path = root / "runtime/offline_exports" / str(argument) / "expected.json"
        else:
            path = inside(argument, root / "runtime/offline_exports")
            if path.name != "expected.json":
                raise ValueError("A ledger must be the locally frozen expected.json")
        ledger = read_json(path)
        if ledger.get("bundle_kind") != "missing_jobs" or ledger.get("protocol_version") != "1.1" or path.parent.name != ledger["bundle_id"]:
            raise ValueError("Unrecognized local expected ledger")
        sources.append({"bundle_id": ledger["bundle_id"], "path": str(path), "sha256": sha256_file(path)})
        for entry in ledger["entries"]:
            identity = (entry["image_id"], entry["tool_id"], entry["cache_key"])
            if make_cache_key(entry["contract"]) != entry["cache_key"]:
                raise ValueError("Frozen ledger contract/cache identity disagrees")
            if identity in entries and entries[identity][0] != entry:
                raise ValueError("Ambiguous conflicting frozen ledger entry")
            entries[identity] = (entry, path.parent)
    return entries, sources


def validated(root, dataset, row, tool, record, ledgers, profile_id="gpu_full_v1"):
    if record.get("status") not in ("ok", "empty") or record.get("actual_inference_confirmed") is not True or record.get("process_released") is not True:
        raise ValueError("No successful released real inference record")
    key = record["cache_key"]
    wanted, ledger_root = ledgers.get((row["image_id"], tool, key), (None, None))
    if wanted is None:
        raise ValueError("No matching locally frozen expected export ledger")
    contract = record["contract"]
    if contract != wanted["contract"] or make_cache_key(contract) != key or contract["canonicalizer_version"] != row["canonicalizer_version"]:
        raise ValueError("Actual inference contract differs from frozen local expectation")
    if wanted["original_sha256"] != row["original_sha256"] or wanted["canonical_sha256"] != row["canonical_sha256"]:
        raise ValueError("Frozen expected source identity differs")
    frozen_input = resolve_case_path(ledger_root, wanted["input_path"])
    if sha256_file(frozen_input) != row["canonical_sha256"]:
        raise ValueError("Local frozen export input changed")
    cache = EvidenceCache(root / "Data/annotations/cache")
    directory = cache.lookup(contract)
    if directory is None:
        raise ValueError("Local standard cache has not completed strict validation/import")
    evidence = validate_local_evidence(directory, contract)
    if record.get("evidence_sha256") != sha256_file(directory / "evidence.json"):
        raise ValueError("Actual pilot record does not bind this local evidence manifest")
    if not gpu_evidence_origin_matches(profile_id, tool, evidence.evidence_profile_id, evidence.formal_eligible) or not evidence.backend["device"].startswith("cuda") or evidence.original_sha256 != row["original_sha256"] or (evidence.source_width, evidence.source_height) != (row["width"], row["height"]):
        raise ValueError("Actual evidence does not match source size and selected GPU protocol")
    return evidence.model_dump(), directory


def actual_images(evidence, directory):
    fragments, image = [], None
    for asset in evidence["assets"]:
        if asset["kind"] not in ("overlay", "map"):
            continue
        path = resolve_case_path(directory, asset["path"])
        if sha256_file(path) != asset["sha256"]:
            raise ValueError("Pilot displayed asset changed")
        candidate = _preview(path)
        if image is None and asset["kind"] == "overlay":
            image = candidate.copy()
        fragments.append(_image(candidate, "实际工具 " + asset["kind"] + " · " + asset["path"] + "；显示缩小，不替代原始坐标"))
    return "".join(fragments), image


def visual_reviews(root, path):
    if path is None:
        return {}, None
    path = inside(path, root / "runtime/reports/gpu_pilot")
    if path.stat().st_size > 2_000_000:
        raise ValueError("Visual review exceeds report input limit")
    value = read_json(path)
    if value.get("protocol_version") != "tool_visual_review_v1" or value.get("independent_restoration_verifier") is not False or value.get("gt_read") is not False:
        raise ValueError("Unrecognized tool-only visual review")
    reviews = {}
    for review in value["records"]:
        identity = (review["image_id"], review["tool_id"])
        if identity in reviews or identity[1] not in ORDER:
            raise ValueError("Duplicate or unknown tool visual review")
        reviews[identity] = review
    return reviews, {"path": str(path), "sha256": sha256_file(path), "created_at": value["created_at"], "method": value["method"]}


def bind_visual_review(review, evidence, directory, row):
    if review is None:
        return None
    if review["evidence_sha256"] != sha256_file(directory / "evidence.json") or review["canonical_sha256"] != row["canonical_sha256"]:
        raise ValueError("Visual review belongs to different input/evidence")
    assets = {a["path"]: a for a in evidence["assets"]}
    for viewed in review["viewed_assets"]:
        descriptor = assets.get(viewed["path"])
        if descriptor is None or descriptor["sha256"] != viewed["sha256"] or sha256_file(resolve_case_path(directory, viewed["path"])) != viewed["sha256"]:
            raise ValueError("Visual review asset identity changed")
    candidates = {i["id"]: i for i in evidence["data"].get("items", [])}
    for check in review.get("candidate_checks", []):
        item = candidates.get(check["id"])
        if item is None or check["model_candidate"] != item["text"]:
            raise ValueError("Visual review refers to changed OCR candidate")
    if review.get("depth_samples"):
        if evidence["tool_id"] != "T3_DEPTH" or review["depth_samples_asset"] != evidence["data"]["depth_path"]:
            raise ValueError("Depth sample review refers to another asset/tool")
        grid = np.load(resolve_case_path(directory, review["depth_samples_asset"]), allow_pickle=False, mmap_mode="r")
        for sample in review["depth_samples"]:
            x, y = sample["source_pixel_xy"]
            if type(x) is not int or type(y) is not int or not (0 <= x < row["width"] and 0 <= y < row["height"]) or float(grid[y, x]) != sample["relative_depth_value"]:
                raise ValueError("Depth sample visual review does not match immutable float grid")
        del grid
    return review


def native_crop(directory, descriptor, caption):
    path = resolve_case_path(directory, descriptor["path"])
    if sha256_file(path) != descriptor["sha256"]:
        raise ValueError("Native OCR crop changed")
    with Image.open(path) as picture:
        if picture.size != (descriptor["width"], descriptor["height"]) or picture.width * picture.height > 40_000_000:
            raise ValueError("Native OCR crop dimensions disagree")
        picture.load()
    # Embed the saved PNG bytes without JPEG conversion, upscaling or any edit.
    uri = "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    return '<figure class=native-crop><img loading="lazy" src="' + uri + '" alt="' + escaped(caption) + '"><figcaption>' + escaped(caption) + "</figcaption></figure>"


def ocr_candidates(evidence, directory, review):
    assets = {a["path"]: a for a in evidence["assets"]}
    native = read_json(resolve_case_path(directory, evidence["data"]["native_result_path"]))
    recognizer = {r["detection_id"]: r["crop_path"] for r in native["native_recognition"]}
    checks = {r["id"]: r for r in (review or {}).get("candidate_checks", [])}
    blocks = ['<p class=caution>以下为模型候选，置信度及模型 ambiguous=false 不能证明文字真实或识别正确。当前 Work 目视检查结论单独列出，不修改缓存。</p>']
    for item in evidence["data"]["items"]:
        block = '<article class=candidate><h4>' + escaped(item["id"]) + " · 模型候选：" + escaped(item["text"]) + "</h4>"
        block += "<p>检测置信度=" + escaped(item["detection_confidence"]) + "；识别置信度=" + escaped(item["recognition_confidence"]) + "；模型 ambiguous=" + escaped(item["ambiguous"]) + "。</p>"
        check = checks.get(item["id"])
        block += '<p class=caution>当前 Work 目视检查：' + (escaped(check["status"]) + " · " + escaped(check["note"]) if check else "尚无已绑定逐项检查") + "</p>"
        identifier = item["id"].removeprefix("text_")
        if not re.fullmatch(r"\d{4}", identifier):
            raise ValueError("OCR candidate has unsupported crop association")
        for relative, title in (("crops/item_" + identifier + ".png", "原图边界框原生裁剪"), (recognizer[item["id"]], "SDK 实际识别输入裁剪；可能已透视校正")):
            descriptor = assets.get(relative)
            if descriptor is None or descriptor["kind"] != "photo":
                raise ValueError("OCR crop is not a declared evidence photo")
            caption = title + " · " + str(descriptor["width"]) + "×" + str(descriptor["height"]) + " px · " + relative
            block += native_crop(directory, descriptor, caption)
        block += "<details><summary>原图归一化多边形及原始候选</summary><pre>" + serialized(item) + "</pre></details></article>"
        blocks.append(block)
    return "".join(blocks)


def render(root, dataset, summaries, out, ledger_arguments=None, visual_review_path=None, profile_id="gpu_full_v1"):
    root = Path(root).resolve()
    dataset = inside(dataset, root / "runtime")
    out = inside(out, root / "runtime/reports/gpu_pilot")
    manifest = read_json(dataset / "manifest.json")
    rows = {r["image_id"]: r for r in manifest["images"]}
    ids = manifest["pilot_ids"]
    if len(ids) != 5 or len(set(ids)) != 5 or not set(ids) <= set(rows):
        raise ValueError("Five distinct prepared real-photo pilot IDs required")
    records, summary_files = {}, []
    for path in summaries:
        path = inside(path, root / "runtime")
        value = read_json(path)
        summary_files.append({"path": str(path), "sha256": sha256_file(path), "stage": value["stage"], "complete": value["complete"]})
        for record in value["results"]:
            identity = (record["image_id"], record["tool_id"])
            # A later summary is authoritative for that actual phase, without
            # discarding successful earlier-tool records absent from it.
            records[identity] = record
    ledgers, ledger_sources = ledger_entries(root, ledger_arguments)
    reviews, review_source = visual_reviews(root, visual_review_path)
    summary = {"created_at": now(), "scope": "real five-photo GPU tool pilot; no edited/restored images", "pilot_ids": ids, "input_count": 5, "actual_summary_files": summary_files, "locally_frozen_ledgers": ledger_sources, "tool_counts": {}, "four_tool_gate_passed": False, "restoration_output_count": 0, "independent_verifier_count": 0, "restoration_effect": None, "gt_read": False, "records": [], "profile_id": profile_id, "original_sam3_protocol_eligible": profile_id == "gpu_full_v1"}
    summary["tool_visual_review_source"] = review_source
    summary["tool_visual_review_count"] = 0
    summary["tool_visual_review_rejections"] = []
    sections, tiles, combined_tiles, depth_tiles = [], [], [], []
    for number, image_id in enumerate(ids, 1):
        row = rows[image_id]
        canonical = resolve_case_path(dataset, row["canonical_path"])
        original_path = resolve_case_path(dataset, row["original_path"])
        if sha256_file(canonical) != row["canonical_sha256"] or sha256_file(original_path) != row["original_sha256"]:
            raise ValueError("Prepared pilot original/canonical hashes changed")
        before = _preview(canonical)
        if image_id == "HC_RAIM_Phase1_011":
            out.mkdir(parents=True, exist_ok=True)
            before.save(out / "HC_RAIM_Phase1_011_before_preview.png")
        fragments = [_image(before, "输入 canonical 的显示预览；无恢复处理")]
        image_summary = {"image_id": image_id, "original_sha256": row["original_sha256"], "canonical_sha256": row["canonical_sha256"], "source_size": [row["width"], row["height"]], "tools": {}}
        thumbnail = t1_thumbnail = depth_thumbnail = None
        for tool in ORDER:
            record = records.get((image_id, tool))
            details = {"status": "missing", "count": None, "error": None}
            block = "<h3>" + escaped(tool) + "</h3>"
            if record and record.get("status") in ("ok", "empty"):
                try:
                    evidence, directory = validated(root, dataset, row, tool, record, ledgers, profile_id)
                    data = evidence["data"]
                    items = data.get("faces", data.get("items", data.get("native_masks")))
                    empty = tool != "T3_DEPTH" and not items
                    details.update(status="empty" if empty else "validated", count=len(items) if items is not None else None, evidence_sha256=sha256_file(directory / "evidence.json"), cache_key=record["cache_key"], elapsed_ms=record["elapsed_ms"], peak_rss_mb=record.get("peak_rss_mb"), gpu=record.get("gpu"), process_released=record["process_released"], model=evidence["model_name"], components=evidence["components"], backend=evidence["backend"], frozen_contract=record["contract"], cache_dir=str(directory), data=data)
                    review = None
                    try:
                        review = bind_visual_review(reviews.get((image_id, tool)), evidence, directory, row)
                    except (ValueError, OSError, KeyError, TypeError) as exc:
                        summary["tool_visual_review_rejections"].append({"image_id": image_id, "tool_id": tool, "reason": str(exc)})
                        block += '<p class=error>人工质检记录拒绝：' + escaped(exc) + "</p>"
                    if review is not None:
                        details["tool_visual_review"] = review
                        summary["tool_visual_review_count"] += 1
                        block += '<p class=caution>当前 Work 对工具证据的目视检查：' + escaped(review["note"]) + "</p><p>此记录只审查工具证据，不计作独立恢复 Verifier。</p>"
                        if review.get("depth_samples"):
                            block += "<details><summary>原图坐标中实际浮点抽样（定性示例，不是深度真值）</summary><pre>" + serialized(review["depth_samples"]) + "</pre></details>"
                    images, overlay = actual_images(evidence, directory)
                    if tool == "T1_OCR":
                        t1_thumbnail = overlay
                    if tool == "T3_DEPTH":
                        depth_thumbnail = _preview(resolve_case_path(directory, data["preview_path"]))
                    block += '<p class="valid">' + escaped(details["status"]) + " · count=" + escaped(details["count"]) + " · elapsed=" + f'{record["elapsed_ms"] / 1000:.3f}s' + " · process released=true</p>" + images
                    gpu = record.get("gpu", {})
                    block += "<p>RSS 采样峰值=" + escaped(record.get("peak_rss_mb")) + " MiB；GPU device-wide 采样峰值=" + escaped(gpu.get("peak_device_used_mib")) + " MiB；worker PID 采样峰值=" + escaped(gpu.get("peak_worker_pid_used_mib")) + " MiB。</p>"
                    if tool == "T2_FACE":
                        thumbnail = overlay
                        if image_id == "HC_RAIM_Phase1_011" and overlay:
                            overlay.save(out / "HC_RAIM_Phase1_011_T2_actual_overlay_preview.png")
                        block += "<p>五点为原生 SCRFD 顺序：eye_0、eye_1、nose、mouth_0、mouth_1。原图坐标及每点数值保存在下方真实记录。</p>"
                        for item in items:
                            block += "<p>" + escaped(item["id"]) + " · confidence=" + escaped(item["confidence"]) + " · 原图人脸范围=" + escaped(item["source_face_pixels"]) + " px</p>"
                        if empty:
                            block += '<p class="caution">空检测是该640×640全图检测配置的实际输出，不能证明图中没有人物或人脸。</p>'
                        if image_id == "spaq_00002":
                            block += '<p class="caution">原图可见人群。小脸缩到640检测输入后可能只有数个像素；本次empty需要人工复核，不能当作无人物或恢复可靠性的证据。</p>'
                    if tool == "T3_DEPTH":
                        block += "<p>float32相对深度；较大值=" + escaped(data["larger_is"]) + "；归一化/颜色图例=" + escaped(data["normalization"]) + "。不表示米制距离。</p>"
                    if tool == "T1_OCR":
                        block += ocr_candidates(evidence, directory, review)
                        if empty:
                            block += '<p class=caution>成功空检测仅代表当前 full-frame 配置无候选，不能证明原图无文字；小字和发光/倾斜文字仍可能漏检。</p>'
                    block += "<details><summary>实际输出与模型/资源详情</summary><pre>" + serialized(details) + "</pre></details>"
                except (ValueError, OSError, KeyError, TypeError) as exc:
                    details.update(status="rejected", error=str(exc))
                    block += '<p class="error">拒绝显示：' + escaped(exc) + "</p>"
            elif record:
                unavailable = record.get("error_code") in ("unavailable", "not_ready") and record.get("actual_inference_confirmed") is not True
                details.update(status="unavailable" if unavailable else "failed" if record.get("status") == "failed" else "missing", error=record.get("message"), error_code=record.get("error_code"), actual_inference_confirmed=record.get("actual_inference_confirmed", False))
                block += '<p class="missing">尚无有效证据；实际状态 ' + escaped(record.get("status")) + "</p><pre>" + serialized({k: record.get(k) for k in ("error_code", "message", "job_id")}) + "</pre>"
            else:
                block += '<p class="missing">该工具尚未有通过本地冻结合同验证的真实证据。未检测与未运行分别记录。</p>'
            image_summary["tools"][tool] = details
            fragments.append("<div class=tool>" + block + "</div>")
        if thumbnail is not None:
            tiles.append((image_id, before, thumbnail, image_summary["tools"]["T2_FACE"]["status"]))
        else:
            tiles.append((image_id, before, None, "missing"))
        combined_tiles.append((image_id, before, t1_thumbnail, thumbnail, image_summary))
        depth_tiles.append((image_id, before, depth_thumbnail, image_summary["tools"]["T3_DEPTH"]["status"]))
        fragments.append("<details class=identity><summary>原始身份与几何</summary><pre>" + serialized({k: row[k] for k in ("original_sha256", "canonical_sha256", "canonicalizer_version", "width", "height")}) + "</pre></details>")
        sections.append("<section><h2>" + str(number).zfill(2) + " · " + escaped(image_id) + "</h2><div class=grid>" + "".join(fragments) + "</div></section>")
        summary["records"].append(image_summary)
    for tool in ORDER:
        counts = Counter(r["tools"][tool]["status"] for r in summary["records"])
        summary["tool_counts"][tool] = dict(counts)
    summary["t2_engineering_passed"] = all(r["tools"]["T2_FACE"]["status"] in ("validated", "empty") for r in summary["records"])
    summary["t1_engineering_passed"] = all(r["tools"]["T1_OCR"]["status"] in ("validated", "empty") for r in summary["records"])
    summary["t3_engineering_passed"] = all(r["tools"]["T3_DEPTH"]["status"] == "validated" for r in summary["records"])
    summary["t1_candidate_count"] = sum(r["tools"]["T1_OCR"].get("count") or 0 for r in summary["records"])
    summary["four_tool_gate_passed"] = all(r["tools"][tool]["status"] in ("validated", "empty") for r in summary["records"] for tool in ORDER)
    summary["t2_quality_conclusion"] = "Five-photo detection/geometry evidence available; empty crowd requires review. No population face-detection accuracy or restoration gain established."
    summary["t1_quality_conclusion"] = "Protocol validity and successful empty detections do not establish OCR accuracy. Candidate-level visual findings remain qualitative; no GT or restoration verification used."
    canvas = Image.new("RGB", (1200, 5 * 285 + 75), "#edf1f4")
    draw = ImageDraw.Draw(canvas)
    draw.text((20, 15), "REAL GPU PILOT: Input / Actual T2 overlay (not restored)", fill="#243645")
    draw.text((20, 40), "T1/T3/T4 shown in HTML. Missing evidence is never an empty detection.", fill="#243645")
    for number, (image_id, before, overlay, status) in enumerate(tiles):
        top = 75 + number * 285
        draw.text((20, top), image_id + " / " + status, fill="#243645")
        for x, picture in ((20, before), (620, overlay)):
            if picture is None:
                draw.rectangle((x, top + 22, x + 550, top + 275), outline="#a8b7c2")
                draw.text((x + 20, top + 100), "No validated actual overlay", fill="#8d4d25")
            else:
                thumb = picture.copy()
                thumb.thumbnail((550, 250), Image.Resampling.LANCZOS)
                canvas.paste(thumb, (x + (550 - thumb.width) // 2, top + 22))
    out.mkdir(parents=True, exist_ok=True)
    canvas.save(out / "contact_sheet_inputs_T2_actual.png")
    combined = Image.new("RGB", (1800, 5 * 285 + 75), "#edf1f4")
    combined_draw = ImageDraw.Draw(combined)
    combined_draw.text((20, 15), "REAL GPU PILOT: Input / Actual T1 overlay / Actual T2 overlay (not restored)", fill="#243645")
    combined_draw.text((20, 40), "Empty means successful no detections in this configuration; it does not establish absent text or faces.", fill="#243645")
    for number, (image_id, before, t1_overlay, t2_overlay, row_summary) in enumerate(combined_tiles):
        top = 75 + number * 285
        combined_draw.text((20, top), image_id + " / T1 " + row_summary["tools"]["T1_OCR"]["status"] + " / T2 " + row_summary["tools"]["T2_FACE"]["status"], fill="#243645")
        for x, picture in ((20, before), (620, t1_overlay), (1220, t2_overlay)):
            if picture is None:
                combined_draw.rectangle((x, top + 22, x + 550, top + 275), outline="#a8b7c2")
                combined_draw.text((x + 20, top + 100), "No validated actual overlay", fill="#8d4d25")
            else:
                thumb = picture.copy()
                thumb.thumbnail((550, 250), Image.Resampling.LANCZOS)
                combined.paste(thumb, (x + (550 - thumb.width) // 2, top + 22))
    combined.save(out / "contact_sheet_inputs_T1_T2_actual.png")
    depth_canvas = Image.new("RGB", (1200, 5 * 285 + 95), "#edf1f4")
    depth_draw = ImageDraw.Draw(depth_canvas)
    depth_draw.text((20, 15), "REAL GPU PILOT: Input / Actual saved T3 relative depth preview", fill="#243645")
    depth_draw.text((20, 40), "Black=far; white=near; per-image min/max. Not metric distance or a restoration.", fill="#243645")
    depth_draw.text((20, 65), "Invalid pixels also display black; consult the valid mask and per-image saved legend in HTML.", fill="#243645")
    for number, (image_id, before, depth_picture, status) in enumerate(depth_tiles):
        top = 95 + number * 285
        depth_draw.text((20, top), image_id + " / T3 " + status, fill="#243645")
        for x, picture in ((20, before), (620, depth_picture)):
            if picture is None:
                depth_draw.rectangle((x, top + 22, x + 550, top + 275), outline="#a8b7c2")
                depth_draw.text((x + 20, top + 100), "No validated actual depth preview", fill="#8d4d25")
            else:
                thumb = picture.copy()
                thumb.thumbnail((550, 250), Image.Resampling.LANCZOS)
                depth_canvas.paste(thumb, (x + (550 - thumb.width) // 2, top + 22))
    depth_canvas.save(out / "contact_sheet_inputs_T3_actual.png")
    css = "body{background:#eef2f5;color:#213442;font:15px system-ui;margin:0}header,main{max-width:1300px;margin:auto;padding:28px}header{background:#173449;color:white}section{background:white;padding:22px;margin:18px 0;border-radius:8px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,360px),1fr));gap:18px}.tool{padding:14px;border:1px solid #d9e3e9;border-radius:6px}.identity{grid-column:1/-1}img{max-width:100%;height:auto}figure{margin:0 0 14px}figcaption{color:#667b8b;margin:7px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:600px;overflow:auto;font-size:12px}summary{cursor:pointer;padding:8px 0}.valid{color:#216851}.missing,.caution{color:#946a2d}.error{color:#ad4141}h3{margin-top:0}"
    header = "<h1>真实 GPU 五图 pilot · 证据可视化</h1><p>T2 工程交付：" + ("5/5严格验证通过" if summary["t2_engineering_passed"] else "尚未5/5通过") + "。四工具gate：" + ("协议证据齐全，仍需独立人工质检" if summary["four_tool_gate_passed"] else "尚未通过") + "。恢复图片：0；独立Verifier：0；恢复效果：尚无结果。</p><p>只有实际canonical和已保存工具资产。empty表示模型成功但没有检测，missing表示未有有效证据。模型权重、后端、资源和原始五点坐标逐图保留；GPU显存是采样值，device-wide包含其他进程。此报告不把部署成功或合成测试当作真实推理验收。</p>"
    if profile_id == "gpu_yoloe26l_v1":
        header += "<p><strong>用户授权的 GPU 工具替代实验：T4 使用 YOLOE-26l，保留31类提示词。此配置不计入原 SAM3 协议正式评测；T1–T3 仅复用完全一致的合同，并保留原运行来源。</strong></p>"
    document = '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'"><title>HarnessIR · 真实GPU五图证据</title><style>' + css + "</style></head><body><header>" + header + "</header><main>" + "".join(sections) + "</main></body></html>"
    t1_note = "<p>T1 工程交付：" + ("5/5 严格验证通过" if summary["t1_engineering_passed"] else "尚未 5/5 通过") + "；模型文字候选 " + str(summary["t1_candidate_count"]) + " 个。已绑定工具 Work 目视检查 " + str(summary["tool_visual_review_count"]) + " 项；候选正确性及漏检仍须结合原始裁剪检查。目视检查不是准确率评测，也不是独立恢复验证。</p>"
    t3_note = "<p>T3 工程交付：" + ("5/5 严格验证通过" if summary["t3_engineering_passed"] else "尚未 5/5 通过") + "；相对深度 larger=near，逐图保留实际图例、float32 网格合同和定性查看记录。方向视觉合理不能代表绝对深度准确。</p>"
    document = document.replace("</header>", t1_note + t3_note + "</header>", 1)
    atomic_write(out / "report.html", document.encode("utf-8"))
    write_json(out / "summary.json", summary)
    return out / "report.html"


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--dataset", type=Path, default=root / "runtime/offline_gpu/prepared_20261013")
    parser.add_argument("--summaries", nargs="+", type=Path, default=[root / "runtime/offline_gpu/t2_pilot_summary.json"])
    parser.add_argument("--ledger", nargs="+", help="Frozen export IDs or their locally retained expected.json paths")
    parser.add_argument("--visual-review", type=Path, help="Hash-bound tool-only visual notes under runtime/reports/gpu_pilot")
    parser.add_argument("--out", type=Path, default=root / "runtime/reports/gpu_pilot/t2_20261013")
    parser.add_argument("--profile", choices=("gpu_full_v1", "gpu_yoloe26l_v1"), default="gpu_full_v1")
    args = parser.parse_args()
    path = render(args.root, args.dataset, args.summaries, args.out, args.ledger, args.visual_review, args.profile)
    value = read_json(path.parent / "summary.json")
    print(json.dumps({"report": str(path), "t2_engineering_passed": value["t2_engineering_passed"], "tool_counts": value["tool_counts"], "four_tool_gate_passed": value["four_tool_gate_passed"], "restoration_outputs": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
