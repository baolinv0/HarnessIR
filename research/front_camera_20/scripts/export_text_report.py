#!/usr/bin/env python3
"""Create one copy/paste Markdown report from server-side experiment records.

Standard library only; never calls a model, reads image pixels, or invents ratings.
Server JSON/CSV/image/log files remain local. The only output is the Markdown file.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone, timedelta
import hashlib
import json
import math
from pathlib import Path
import re
import sys


MODELS = {"qwen21": "Qwen", "firered11": "FireRed", "flux3_klein": "FLUX", "fibo2_dev": "FIBO"}
BATCHES = ("main_reference", "source_only", "pilot")
PARAMS = ("num_inference_steps", "true_cfg_scale", "guidance_scale", "output_resolution",
          "use_kv_cache", "num_images_per_prompt", "max_sequence_length", "geometry_policy",
          "temperature", "top_p", "top_k", "do_sample", "max_new_tokens", "max_tokens", "seed")
PRESERVATION = {"no_damage": "O", "pass": "O", "minor": "m", "major": "D", "fail": "F", "uncertain": "?"}


def require(value, message):
    if not value:
        raise ValueError(message)


def read_json(path, optional=False):
    if optional and not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    require(isinstance(value, dict), "JSON root must be an object")
    return value


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def text(value):
    if value is None or value == "" or value == [] or value == {}:
        return "未记录"
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    value = str(value)
    value = re.sub(r"https?://\S+", "[地址省略]", value)
    value = re.sub(r"(?i)(api[_-]?key|token|password|authorization)\s*[:=]\s*\S+", r"\1=[省略]", value)
    return value.replace("|", "\\|").replace("\r", " ").replace("\n", " ").replace("<", "&lt;").replace(">", "&gt;")


def table(headers, rows):
    return ["| " + " | ".join(map(text, headers)) + " |", "|" + "---|" * len(headers)] + [
        "| " + " | ".join(map(text, row)) + " |" for row in rows]


def unique(values, label):
    require(isinstance(values, list) and values and len(values) == len(set(values)), label + " must be a nonempty unique list")
    return values


def record_key(batch, pair, model, arm, seed, mode):
    return batch, pair, model, arm, seed, mode


def load_records(root, manifest_dir):
    manifests, reports, records, by_key = {}, {}, [], {}
    for batch in BATCHES:
        path = manifest_dir / (batch + ".json")
        if not path.is_file():
            require(not (root / "reports" / batch / "report.json").is_file(), "Report has no matching planned manifest: " + batch)
            continue
        manifest = read_json(path)
        require(manifest.get("schema_version") == "hre_batch_v3", "Expected hre_batch_v3: " + batch)
        models = unique(manifest.get("models"), "models")
        require(set(models) <= set(MODELS), "Unsupported model in manifest")
        seeds = unique(manifest.get("seeds"), "seeds")
        require(all(type(s) is int and s >= 0 for s in seeds), "Seeds must be nonnegative integers")
        arms, cases = manifest.get("arms"), manifest.get("cases")
        require(isinstance(arms, list) and all(isinstance(a, dict) for a in arms), "Invalid arms")
        require(isinstance(cases, list) and all(isinstance(c, dict) for c in cases), "Invalid cases")
        unique([a.get("name") for a in arms], "arm names")
        unique([c.get("id") for c in cases], "case ids")
        require(all(isinstance(a.get("name"), str) and a["name"] and a.get("strategy") in {"native", "shared", "model_aware"} for a in arms), "Invalid arm identity")
        require(all(a.get("policy", "single") in {"single", "feedback", "resample"} and type(a.get("max_generations", 1)) is int and a.get("max_generations", 1) > 0 for a in arms), "Invalid generation policy/cap")
        require(all(isinstance(c.get("id"), str) and c["id"] for c in cases), "Invalid pair identity")
        manifests[batch] = manifest
        for case in cases:
            allowed = unique(case.get("models", models), "case models")
            require(set(allowed) <= set(models), "Case model is outside batch model list")
            mode = case.get("task_mode")
            require(mode in {"restoration", "reference_enhance"}, "Invalid task mode")
            require(mode == ("restoration" if batch == "source_only" else "reference_enhance"), "Task mode conflicts with the front-camera batch role")
            for model in allowed:
                for arm in arms:
                    for seed in seeds:
                        key = record_key(batch, case["id"], model, arm["name"], seed, mode)
                        require(key not in by_key, "Duplicate planned run")
                        rec = {"key": key, "batch": batch, "pair": case["id"], "model": model,
                               "arm": arm["name"], "seed": seed, "mode": mode, "plan": arm,
                               "row": None, "unavailable": False, "rating": None}
                        by_key[key] = rec; records.append(rec)
        report_path = root / "reports" / batch / "report.json"
        report = read_json(report_path, optional=True)
        reports[batch] = report
        if not report:
            continue
        require(report.get("schema_version") == "hre_comparison_report_v3", "Expected actual v3 report: " + batch)
        modes = {c["id"]: c["task_mode"] for c in cases}
        seen = set()
        for unavailable, rows in ((False, report.get("runs", [])), (True, report.get("unavailable_runs", []))):
            require(isinstance(rows, list), "Invalid report rows")
            for row in rows:
                require(isinstance(row, dict) and type(row.get("seed")) is int, "Invalid report identity/seed")
                pair = row.get("dataset_case_id")
                key = record_key(batch, pair, row.get("profile_id"), row.get("arm"), row.get("seed"), row.get("task_mode", modes.get(pair)))
                require(key in by_key, "Unexpected report row outside the frozen manifest: " + batch)
                require(key not in seen, "Duplicate/conflicting report row: " + batch)
                seen.add(key)
                by_key[key].update(row=None if unavailable else row, unavailable=unavailable,
                                   case_root=row.get("case_root"))
    require(manifests and any(b != "pilot" for b in manifests), "No formal main_reference/source_only manifest; cannot infer planned denominators")
    return manifests, reports, records


def delivery(row):
    if not row or row.get("selected_kind") not in {"candidate_accepted", "candidate_unaccepted"} or not row.get("selected_image"):
        return False
    matches = [c for c in row.get("candidates", []) if c.get("candidate_id") == row.get("selected_candidate_id")]
    if len(matches) != 1 or not matches[0].get("geometry_valid") or matches[0].get("delivery_status") == "invalid":
        return False
    candidate = matches[0]
    return bool(row.get("selected_sha256") and (not candidate.get("delivered_sha256")
                or candidate["delivered_sha256"] == row["selected_sha256"]))


def state(rec):
    row = rec["row"] or {}
    if row.get("status") not in {"completed", "failed"}:
        return "P"
    if row.get("selected_kind") == "source_baseline":
        return "B"
    if delivery(row):
        return "C" if row["status"] == "completed" else "F"
    return "X"


def boolean(value):
    value = (value or "").strip().lower()
    if value in {"true", "yes", "y", "1"}:
        return True
    if value in {"false", "no", "n", "0"}:
        return False
    return None


def score(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and -2 <= number <= 2 else None
    except (ValueError, TypeError):
        return None


def load_ratings(path, records):
    if path is None:
        return
    roots = defaultdict(list)
    for rec in records:
        if rec.get("case_root"):
            roots[str(Path(rec["case_root"]).expanduser().resolve())].append(rec)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for line, row in enumerate(csv.DictReader(stream), 2):
            require(None not in row, f"Results line {line}: CSV row has extra columns")
            if not any((v or "").strip() for v in row.values()):
                continue
            if row.get("case_root"):
                matches = roots[str(Path(row["case_root"]).expanduser().resolve())]
            else:
                require(row.get("task_mode"), f"Results line {line}: task_mode or full case_root required; A+B/A-only must not mix")
                matches = [r for r in records if r["pair"] == row.get("pair_id") and r["model"] == row.get("model")
                           and r["arm"] == row.get("arm") and str(r["seed"]) == row.get("seed")
                           and r["mode"] == row["task_mode"] and (not row.get("batch") or r["batch"] == row["batch"])]
            require(len(matches) == 1, f"Results line {line}: ambiguous or unplanned rating")
            rec = matches[0]
            require(rec["rating"] is None, f"Results line {line}: duplicate rating summary")
            a, n = score(row.get("appearance_delta_summary")), score(row.get("naturalness_delta_summary"))
            p, u = row.get("preservation_final", "").strip().lower(), boolean(row.get("usable_final"))
            complete = boolean(row.get("ratings_complete")) is True and a is not None and n is not None and p in PRESERVATION and u is not None
            # Scores may be means/medians; they cannot replace per-rater voting.
            # Y/N is the server's adjudication under the frozen voting protocol.
            conflict = bool(complete and u and p not in {"pass", "no_damage"})
            rec["rating"] = {"complete": complete and not conflict, "conflict": conflict,
                             "a": a, "n": n, "p": p, "u": u}


def counts(records):
    valid = [r for r in records if delivery(r["row"])]
    rated = [r for r in valid if (r["rating"] or {}).get("complete")]
    unresolved = sum(state(r) == "P" for r in records)
    usable = sum(state(r) == "C" and r["rating"]["u"] for r in rated)
    eligible_missing = sum(state(r) == "C" and not (r["rating"] or {}).get("complete") for r in valid)
    rate = "进度，未终态" if unresolved else (f"{usable}/{len(records)}" if not eligible_missing else f"待评：已确认 {usable}/{len(records)}；上界 {usable + eligible_missing}/{len(records)}")
    return [len(records), sum((r["row"] or {}).get("status") == "completed" for r in records), len(valid),
            sum((r["row"] or {}).get("status") == "failed" for r in records), unresolved, len(rated), rate,
            sum(r["rating"]["p"] == "major" for r in rated), len(valid) - len(rated)]


def token(rec):
    prefix, rating = state(rec), rec["rating"] or {}
    if not delivery(rec["row"]):
        return prefix
    if rating.get("conflict"):
        return prefix + ":待核实"
    if not rating.get("complete"):
        return prefix + ":待评"
    return f"{prefix}:{rating['a']:+g}/{PRESERVATION[rating['p']]}/{rating['n']:+g}/{'Y' if rating['u'] else 'N'}"


def total(records, container, name):
    values = [(r["row"] or {}).get(container, {}).get(name) for r in records]
    known = [v for v in values if type(v) in {int, float} and math.isfinite(v) and v >= 0]
    if not known:
        return "未知"
    result = f"{sum(known):g}"
    return result if len(known) == len(values) else result + f"（已知 {len(known)}/{len(values)}）"


def projected(config, keys):
    return {k: config[k] for k in keys if config.get(k) is not None}


def input_hashes(row, role):
    known = set()
    explicit = row.get(role + "_sha256")
    if isinstance(explicit, str) and re.fullmatch(r"[0-9a-fA-F]{64}", explicit):
        known.add(explicit.lower())
    path = row.get(role + "_image")
    match = re.search(r"(?:^|/)([0-9a-fA-F]{64})\.png$", path) if isinstance(path, str) else None
    if match:
        known.add(match.group(1).lower())
    return known


def config_summary(rec):
    row = rec["row"] or {}
    config = row.get("runtime_config", {}).get("models", {}).get(rec["model"], {})
    editor, compiler = config.get("editor", {}), config.get("compiler", {})
    image = projected(editor, ("model_id", "revision", "torch_dtype", "quantization", "cpu_offload", "offload", "enable_model_cpu_offload", "pipeline_version"))
    if not image.get("model_id"):
        image["model_id"] = row.get("model_id")
    if not image.get("revision"):
        image["revision"] = row.get("model_revision")
    image["settings"] = projected(editor.get("settings", {}), PARAMS)
    native = projected(compiler, ("backend", "model_id", "revision", "upstream_revision", "torch_dtype", "offload"))
    native["settings"] = projected(compiler.get("settings", {}), PARAMS)
    if compiler.get("endpoint"):
        native["text_model"] = compiler["endpoint"].get("model")
        native["decoding"] = projected(compiler["endpoint"].get("settings", {}), PARAMS)
    return image, native


def export(root, manifest_dir=None, results=None, out=None):
    root = Path(root).expanduser().resolve()
    out = Path(out).expanduser().resolve() if out else root / "EXPERIMENT_REPORT.md"
    require(not out.exists(), "Output exists; choose a new --out to preserve manual edits")
    if manifest_dir is None:
        candidates = [root / p for p in ("manifests", "manifests-extended") if (root / p).is_dir()]
        require(len(candidates) == 1, "Choose --manifest-dir explicitly when no or multiple manifest directories exist")
        manifest_dir = candidates[0]
    manifest_dir = Path(manifest_dir).expanduser().resolve()
    manifests, reports, records = load_records(root, manifest_dir)
    load_ratings(Path(results).expanduser().resolve() if results else None, records)
    dataset, env = read_json(root / "dataset.json", True), read_json(root / "environment.json", True)
    meta, data_cases = dataset.get("meta", {}), dataset.get("cases", [])
    require(isinstance(data_cases, list), "dataset.cases must be a list")
    metadata_ids = [c["pair_id"] for c in data_cases if isinstance(c, dict) and c.get("pair_id")]
    require(len(metadata_ids) == len(set(metadata_ids)), "Duplicate dataset metadata pair_id")
    groups = {c["pair_id"]: c for c in data_cases if isinstance(c, dict) and c.get("pair_id")}
    grouped = defaultdict(list)
    for rec in records:
        grouped[(rec["batch"], rec["model"], rec["arm"])].append(rec)
    lines = ["# 前置实拍四模型实验回传报告", "", "BEGIN_OF_REPORT", "",
             "只需复制粘贴本文全文；图片、JSON、CSV 和原始日志留在服务器，无附件要求。",
             "机器字段取自服务器记录；人评来自服务器终点评定或随后人工填写，不由 verifier 分数推断。", "",
             "## 1. 身份、数据与配置", "",
             "生成时间（北京时间）：" + datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"), ""]
    identity = [("实验 ID / Git commit", f"{text(env.get('experiment_id'))} / {text(env.get('git_commit'))}"),
                ("开始 / 结束（原记录）", f"{text(env.get('run_start_utc'))} / {text(env.get('run_end_utc'))}"),
                ("baseline / revision", f"{text(meta.get('baseline_id'))} / {text(meta.get('baseline_revision'))}"),
                ("配对数量确认 / 颜色确认 / 分组确认", " / ".join(text(meta.get(k)) for k in ("data_count_confirmed", "color_contract_confirmed", "group_contract_confirmed"))),
                ("A / B 显示编码", f"{text(meta.get('source_encoding'))} / {text(meta.get('reference_encoding'))}"),
                ("A 导出", meta.get("source_export_recipe")), ("B 导出", meta.get("reference_export_recipe")),
                ("参考任务目标", meta.get("brief_reference")), ("无参考任务目标", meta.get("brief_source_only")),
                ("工作尺寸 / 几何", projected(env.get("input_contract", {}), ("source_test_resolution_rule", "reference_test_resolution_rule", "geometry_policy", "grid", "spatial_mode"))),
                ("GPU / 驱动 / CUDA", projected(env.get("gpu", {}), ("models", "count", "memory_gib_per_gpu", "driver", "cuda"))),
                ("图像环境", projected(env.get("environments", {}).get("image", {}), ("python", "torch", "diffusers_commit", "transformers"))),
                ("PE 环境", projected(env.get("environments", {}).get("qwen_pe", {}), ("python", "torch", "transformers"))),
                ("公共 VLM 声明", projected(env.get("public_stage_vlm", {}), ("model_id", "revision", "server_version", "stage_template_hash"))),
                ("评审 / 显示声明", projected(env.get("review", {}), ("rater_count", "display_model", "display_sdr_mode", "icc_profile", "ambient_light", "fit_and_crop_rule")))]
    lines += table(["项目", "记录"], identity)
    lines += ["", "上述 dataset.json / environment.json 是当前声明，不等于已独立验证的冻结像素定义；颜色与尺寸需在服务器核实。"]
    input_sets, input_coverage = defaultdict(set), Counter()
    for rec in records:
        if rec["batch"] == "pilot" or not rec["row"]:
            continue
        for role in ("source", "reference"):
            if role == "reference" and rec["mode"] == "restoration":
                continue
            values = input_hashes(rec["row"], role)
            input_coverage[role + "_total"] += 1
            input_coverage[role + "_known"] += bool(values)
            input_sets[(rec["pair"], role)].update(values)
    input_conflicts = [f"{pair}:{role}" for (pair, role), values in input_sets.items() if len(values) > 1]
    lines += ["", "输入身份核对（仅报告内hash/标准文件名声明，未读取像素）："
              + "；".join(f"{role} 已知 {input_coverage[role + '_known']}/{input_coverage[role + '_total']}" for role in ("source", "reference")) + "。未知hash不视作一致。"]
    if input_conflicts:
        lines += ["**输入不一致：" + text(", ".join(input_conflicts)) + "。同pair出现不同输入hash，暂停模型/策略比较，先核对冻结数据。**"]
    lines += ["", "下列为实际 report 中的白名单配置；缺失不代表使用默认值。出现多配置时分别列出，需解释可比性。", ""]
    config_entries, stages, stage_hashes, model_configs, incomplete_config = {}, set(), set(), defaultdict(set), set()
    for rec in records:
        if not rec["row"]:
            continue
        image, native = config_summary(rec)
        runtime = rec["row"].get("runtime_config", {})
        actual_model = runtime.get("models", {}).get(rec["model"])
        if not isinstance(actual_model, dict) or not isinstance(runtime.get("stage"), dict):
            incomplete_config.add(MODELS[rec["model"]])
        # Hash complete selected configuration, but only display a safe projection.
        # This detects negative prompts, worker/residency and other hidden changes.
        encoded = json.dumps([rec["model"], actual_model, runtime.get("stage")], sort_keys=True)
        short_hash = hashlib.sha256(encoded.encode()).hexdigest()[:12]
        if rec["batch"] != "pilot":
            model_configs[rec["model"]].add(short_hash)
        key = (rec["model"], short_hash)
        entry = config_entries.setdefault(key, {"image": image, "native": native, "batches": set()})
        entry["batches"].add(rec["batch"])
        stage = rec["row"].get("runtime_config", {}).get("stage", {})
        if rec["batch"] != "pilot":
            stages.add(json.dumps({**projected(stage, ("model", "revision")), "sampling": projected(stage.get("settings", {}), PARAMS)}, ensure_ascii=False, sort_keys=True))
            stage_hashes.add(hashlib.sha256(json.dumps(stage, sort_keys=True).encode()).hexdigest())
    config_rows = [[MODELS[m], ",".join(sorted(entry["batches"])), entry["image"], entry["native"], h]
                   for (m, h), entry in config_entries.items()]
    lines += table(["模型", "batch", "editor", "compiler", "完整配置短hash"], config_rows or [["全部", "未报告", "未报告", "未报告", "未记录"]])
    lines += ["", "配置 hash 覆盖完整选中模型 compiler/editor 与公共 stage（含负提示、worker设置）；仅展示白名单字段，凭据和端点原文不输出。pilot配置变化不与正式结果混算。"]
    lines += ["", "实际公共 stage 配置：" + ("；".join(map(text, sorted(stages))) if stages else "未报告"), "",
              "## 2. 计划、覆盖与主结果", ""]
    mixed = [MODELS[m] for m, hashes in model_configs.items() if len(hashes) > 1]
    if mixed or len(stage_hashes) > 1:
        lines += ["**配置混用：" + ", ".join(mixed + (["公共stage"] if len(stage_hashes) > 1 else []))
                  + "。以下计数仅供排错，暂停模型/策略优劣比较；先按配置拆分运行或说明变更，不能将混用结果当作统一实验。**", ""]
    if incomplete_config:
        lines += ["**配置记录不完整：" + ", ".join(sorted(incomplete_config)) + "；比较结论待补齐实际配置后核对。**", ""]
    plan_rows = []
    for batch, manifest in manifests.items():
        planned = [r for r in records if r["batch"] == batch]
        cap = sum(r["plan"].get("max_generations", 1 if r["plan"].get("policy", "single") == "single" else 3) for r in planned)
        plan_rows.append([batch, len(manifest["cases"]), manifest["seeds"], len(planned), cap, digest(manifest_dir / (batch + ".json")), "已读取" if reports[batch] else "未报告"])
    lines += table(["batch", "pair", "seed 顺序", "计划 runs", "生成上限", "manifest hash 前12位", "报告"], plan_rows)
    lines += ["", "pilot 为开发数据，单列且不进入正式结论。以下分母是计划 runs，不是生成候选数或评审人数。", ""]
    summary_rows = []
    for (b, m, a), rs in grouped.items():
        values = counts(rs)
        if results is None:
            values[5:] = ["待按明细复算"] * 4
        summary_rows.append([f"{b} / {MODELS[m]} / {a}", *values])
    lines += table(["batch / 模型 / arm", "计划", "完成", "有效图", "流程失败", "未终态", "人评完成", "主可用", "重大损伤", "待评"], summary_rows)
    lines += ["", "主可用要求流程完成、有有效交付、且服务器人评判可用。未终态时仅报告进度；全终态但待评时显示已确认下界/可能上界，未评不当零分。重大损伤分母为人评完成数。有效图依据报告中的候选/尺寸/hash声明，本工具不重读图像。", "",
              "## 3. 逐图、逐 seed 明细", "",
              "状态：C=正常完成且有效交付；F=流程失败但有效图可供诊断；B=原图回退；X=终态无有效交付；P=未报告/暂停/结果不明。",
              "评分写作 `C:+1/O/0/Y`，依次为外观改善 / 保真 / 自然度 / 服务器人评可用；O=pass或no_damage，m=minor，D=major，F=fail，?=uncertain；Y/N=是/否。只计 C 且 Y 为主可用；F 的 Y 仅为诊断性画质观察。待评、待核实不得填成成功。", ""]
    lines += ["Y/N是服务器按冻结投票/裁决规则形成的终点评定；外观/自然度均分或中位数仅作描述，不替代逐评审投票。请在第6节说明汇总方法。", ""]
    columns, column_of = {}, {}
    for batch, manifest in manifests.items():
        if batch == "pilot":
            continue
        for arm in manifest["arms"]:
            strategy, policy = arm.get("strategy"), arm.get("policy", "single")
            label = "A" if batch == "source_only" else ({"native": "N", "shared": "S", "model_aware": "M"}.get(strategy, arm["name"]))
            if policy in {"resample", "feedback"}:
                label = ("R" if policy == "resample" else "F") + str(arm.get("max_generations", 3))
            if label in columns:
                label += "_" + arm["name"]
            require(label not in columns, "Ambiguous matrix column")
            columns[label] = (batch, arm["name"], manifest["seeds"]); column_of[(batch, arm["name"])] = label
    lines += ["N=参考native，S=参考shared，M=参考aware，A=无参考aware；R/F为可选重采样/反馈。每格以分号分隔各 seed，保持下列顺序：",
              "；".join(text(label) + "=" + text(seeds) for label, (_, _, seeds) in columns.items()), ""]
    pairs_models = list(dict.fromkeys((r["pair"], r["model"]) for r in records if r["batch"] != "pilot"))
    formal_pairs = set(pair for pair, _ in pairs_models)
    lines += [f"预期正式明细行数（按实际模型分配）={len(pairs_models)}；实际输出={len(pairs_models)}。正式 N={len(formal_pairs)}，四模型全覆盖时为 4×N={4 * len(formal_pairs)}。pilot不在此表。", ""]
    matrix, by_slot = [], {(r["batch"], r["pair"], r["model"], r["arm"], r["seed"]): r for r in records}
    for index, (pair, model) in enumerate(pairs_models, 1):
        rid, cells = f"R{index:03d}", []
        for label, (batch, arm, seeds) in columns.items():
            values = []
            for seed in seeds:
                rec = by_slot.get((batch, pair, model, arm, seed))
                if rec:
                    rec["id"] = f"{rid}.{label}.{seed}"; values.append(token(rec))
                else:
                    values.append("未计划")
            cells.append("; ".join(values))
        item = groups.get(pair, {})
        matrix.append([rid, pair, item.get("group_id"), item.get("subject_id"), MODELS[model], *cells])
    lines += table(["行ID", "pair", "场景组", "人物", "模型", *columns], matrix)
    lines += ["", "单次运行 ID = 行ID.列名.seed，例如 R001.M.42；可直接用此 ID 讨论异常。完整路径和原图留服务器。", "",
              "## 4. 实际调用与成本", ""]
    lines += table(["batch / 模型 / arm", "图像调用", "compiler调用", "stage调用", "compiler秒", "image秒", "stage秒"],
                   [[f"{b} / {MODELS[m]} / {a}", *(total(rs, "budget", k) for k in ("generations", "compiler_calls", "stage_calls")),
                     *(total(rs, "elapsed_seconds", k) for k in ("compile", "generate", "stage"))] for (b, m, a), rs in grouped.items()])
    lines += ["", "缺字段显示未知；部分已知值同时显示覆盖数，不是完整总成本。时间可能包含启动/装载，不等于热推理时延；峰值显存和批次 wall time 请在第6节补充。", ""]
    planning_rows = []
    for batch, manifest in manifests.items():
        plans = reports[batch].get("planning", [])
        expected = len(manifest["cases"]) if manifest.get("share_planning", True) and any(a["strategy"] != "native" for a in manifest["arms"]) else 0
        wrapped = [{"row": p} for p in plans]
        planning_rows.append([batch, expected, len(plans), total(wrapped, "budget", "stage_calls") if plans else "未知" if expected else 0])
    lines += table(["共享规划 batch", "计划 pair", "已报告 planning", "额外 stage 调用"], planning_rows)
    lines += ["", "## 5. 异常、缺失与人工核实", ""]
    exceptions, reasons = [], Counter()
    for index, rec in enumerate(records, 1):
        row, rating = rec["row"] or {}, rec["rating"] or {}
        codes = []
        if not rec["row"]:
            codes.append("report_unavailable" if rec["unavailable"] else "not_reported")
        elif state(rec) != "C":
            reason = row.get("terminal_reason")
            codes.append(reason if isinstance(reason, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", reason) else "non_complete_or_no_delivery")
        if rating.get("conflict"):
            codes.append("human_rating_conflict")
        if rating and not delivery(rec["row"]):
            codes.append("human_rating_without_valid_reported_delivery")
        if codes:
            rid = rec.get("id", f"P{index:04d}")
            reasons.update(codes)
            if codes != ["not_reported"]:
                exceptions.append([rid, rec["batch"], rec["pair"], MODELS[rec["model"]], rec["arm"], rec["seed"], state(rec), ",".join(codes)])
    lines += ["异常/缺失计数：" + ("；".join(f"{k}={v}" for k, v in sorted(reasons.items())) if reasons else "机器记录未发现；人眼问题仍需填写"), ""]
    lines += ["未报告的逐次运行已由第3节P标记定位，不再重复列出；pilot未报告数量仅见计划表。"]
    lines += table(["运行ID", "batch", "pair", "模型", "arm", "seed", "状态", "机器原因"], exceptions) if exceptions else ["无额外机器异常记录。"]
    lines += ["", "仅复制机器原因码，不内嵌错误堆栈、凭据或原始配置。请将影响结论的错误现象和处理办法写在下节。", "",
              "## 6. 人工补充与结论（必须在服务器看图后填写）", "",
              "- 数据数量含义、独立场景/人物数、训练/开发重叠：待填写。",
              "- A/B 颜色出口、镜像与方向、实际输入/输出尺寸已核实：待填写。",
              "- 目标优先级、禁止改动、人评人数、显示条件、是否模型匿名、投票/裁决规则、分数汇总方法（均分/中位数）：待填写。",
              "- 峰值显存 / 测量方法、整批 wall time、装载和并发条件：待填写。",
              "- 原生条件审计（目标遗漏/新增、A/B角色、保真条款、FIBO字段一致性）：待填写。",
              "- 可选反馈首轮 condition 文本一致性与实际早停：未运行或待填写。", ""]
    lines += table(["运行ID / pair", "A的问题与B适用性", "观察到的改善/损伤", "是否跨seed一致", "裁决/证据描述"], [["待填写", "", "", "", ""] for _ in range(3)])
    lines += ["", "- 协议偏离、额外重试、未能完成的运行与原因：待填写。",
              "- 参考 A+B 相比 A-only：支持 / 不支持 / 证据不足；依据：待填写。",
              "- aware 相比 shared：按四模型分别填写，不预设冠军。",
              "- 关键失败与下一步：待填写。", "",
              "## 7. 回传边界", "",
              "本文是唯一回传文档，无需图片、CSV、JSON 或日志附件。原始证据留服务器；必要细节用运行ID、数值和短文字内联。",
              "接收方可以核对配置、完整分母、逐图/seed记录和服务器人评结论；未收到图像时不能声称独立视觉验证身份、纹理或伪细节。",
              "若人工直接修改逐图评分，请同步汇总表，或明确标注‘汇总待重算’；缺失保持待评，不将VLM accepted/confidence填为人评分。",
              "", "END_OF_REPORT", ""]
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines))
    return {"output": str(out), "planned_runs": len(records), "reported_runs": sum(r["row"] is not None for r in records),
            "formal_pair_model_rows": len(matrix), "human_summary_supplied": results is not None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-root", type=Path, required=True)
    parser.add_argument("--manifest-dir", type=Path, help="Required if both manifests/ and manifests-extended/ exist")
    parser.add_argument("--results", type=Path, help="Optional server-side per_pair_results.csv; never required as a return attachment")
    parser.add_argument("--out", type=Path, help="New Markdown path; default STUDY_ROOT/EXPERIMENT_REPORT.md")
    args = parser.parse_args()
    try:
        result = export(args.study_root, args.manifest_dir, args.results, args.out)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print("Text report export failed: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
