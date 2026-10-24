#!/usr/bin/env python3
"""Create CPU-only, model-masked review materials from actual v3 report exports.

No inference, quality scores, statistical conclusions or image transformations.
Only reviewer/ is suitable for reviewers; private_mapping.json reveals identities.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
from pathlib import Path, PurePosixPath
import random
import re
import shutil
import sys


FIELDS = ["trial_id", "pair_id", "rater_id", "usable", "appearance_delta",
          "preservation", "naturalness_delta", "critical_error_tags", "notes"]
PNG = b"\x89PNG\r\n\x1a\n"


def require(value, message):
    if not value:
        raise ValueError(message)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare(report_paths: list[Path], out: Path, seed: int) -> dict:
    require(not out.exists(), "--out must be a new directory; existing files are never overwritten")
    report_paths = [path.expanduser().resolve() for path in report_paths]
    require(len(set(report_paths)) == len(report_paths), "Do not supply the same report twice")
    rng, pairs, runs, unavailable, seen_runs, checked = random.Random(seed), {}, [], [], {}, {}

    def asset(report, relative, expected=None):
        require(isinstance(relative, str) and relative and "\\" not in relative and ":" not in relative,
                "Images must be report-relative POSIX paths")
        rel = PurePosixPath(relative)
        require(not rel.is_absolute() and ".." not in rel.parts, "Absolute/traversing image path rejected")
        path = (report.parent / relative).resolve()
        require(path.is_relative_to(report.parent) and path.is_file(), "Missing image or symlink escapes report")
        if path not in checked:
            data = path.read_bytes()
            require(data.startswith(PNG), "Expected a PNG from the v3 report exporter")
            checked[path] = hashlib.sha256(data).hexdigest()
        actual = checked[path]
        filename_hash = rel.stem if re.fullmatch(r"[0-9a-fA-F]{64}", rel.stem) else None
        for known in (expected, filename_hash):
            if known is not None:
                require(isinstance(known, str) and actual == known.lower(), "Image SHA-256 mismatch: " + relative)
        return {"path": path, "sha256": actual}

    for report_path in report_paths:
        data = json.loads(report_path.read_text(encoding="utf-8"))
        require(data.get("schema_version") == "hre_comparison_report_v3", "Expected hre_comparison_report_v3")
        require(isinstance(data.get("runs"), list) and isinstance(data.get("unavailable_runs", []), list),
                "Invalid report run lists")
        unavailable.append({"report": str(report_path), "runs": data.get("unavailable_runs", [])})
        for index, row in enumerate(data["runs"]):
            require(isinstance(row, dict), "Invalid report row")
            pair_id = row.get("dataset_case_id")
            require(isinstance(pair_id, str) and pair_id, "Every run needs dataset_case_id")
            identity = row.get("case_root") or f"{report_path}#{index}"
            signature = hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if identity in seen_runs:
                old, old_signature = seen_runs[identity]
                require(signature == old_signature, "Conflicting exports of one case; supply only its final report")
                old["reports"].append(str(report_path))
                continue
            source = asset(report_path, row.get("source_image"), row.get("source_sha256"))
            reference = asset(report_path, row["reference_image"], row.get("reference_sha256")) if row.get("reference_image") else None
            pair = pairs.setdefault(pair_id, {"source": source, "reference": None})
            require(pair["source"]["sha256"] == source["sha256"], "Different source bytes for pair " + pair_id)
            if reference:
                require(pair["reference"] is None or pair["reference"]["sha256"] == reference["sha256"],
                        "Different reference bytes for pair " + pair_id)
                pair["reference"] = reference
            record = {key: row.get(key) for key in (
                "case_root", "case_id", "profile_id", "model_id", "arm", "strategy", "seed", "task_mode",
                "policy", "status", "terminal_reason", "quality_status", "selected_kind", "selected_candidate_id", "selected_sha256")}
            record.update(run_id=f"R{len(runs) + 1:06d}", dataset_case_id=pair_id,
                          reports=[str(report_path)], trial_id=None, exclusion_reason=None,
                          technical_completed=row.get("status") == "completed", primary_eligible=False)
            seen_runs[identity] = (record, signature)
            runs.append(record)
            if row.get("selected_kind") == "source_baseline":
                record["exclusion_reason"] = "source_fallback_is_not_a_model_delivery"
            elif row.get("selected_kind") not in {"candidate_accepted", "candidate_unaccepted"} or not row.get("selected_image"):
                record["exclusion_reason"] = "paused_without_selected_delivery" if row.get("status") == "paused" else "no_selected_model_delivery"
            else:
                candidates = row.get("candidates", [])
                matches = [c for c in candidates if c.get("candidate_id") == row.get("selected_candidate_id")]
                if len(matches) != 1 or not matches[0].get("geometry_valid") or matches[0].get("delivery_status") == "invalid":
                    record["exclusion_reason"] = "selected_candidate_not_validated"
                    continue
                selected = asset(report_path, row["selected_image"], row.get("selected_sha256"))
                candidate = matches[0]
                if candidate.get("delivered_sha256"):
                    require(selected["sha256"] == candidate["delivered_sha256"], "Selected/candidate hash mismatch")
                if candidate.get("delivered_image"):
                    delivered = asset(report_path, candidate["delivered_image"], candidate.get("delivered_sha256"))
                    require(selected["sha256"] == delivered["sha256"], "Selected image differs from delivered candidate")
                record["selected_sha256"] = selected["sha256"]
                record["matches_source_bytes"] = selected["sha256"] == source["sha256"]
                record["primary_eligible"] = record["technical_completed"]
                entry = pair.setdefault("outputs", {}).setdefault(selected["sha256"], {"asset": selected, "runs": []})
                entry["runs"].append(record)

    require(pairs, "No source images are available in these reports")
    for original_id, pair in pairs.items():
        require(pair["reference"] is not None,
                "Missing reference for " + original_id + "; include its reference-enhancement report for review only")
    trials, pair_map = [], {}
    for original_id, pair in pairs.items():
        alias = "P" + f"{rng.getrandbits(64):016x}"
        pair_map[alias] = {"dataset_case_id": original_id, "source_sha256": pair["source"]["sha256"],
                           "reference_sha256": pair["reference"]["sha256"]}
        entries = [{"asset": pair["source"], "runs": [], "baseline": True}] + list(pair.get("outputs", {}).values())
        for entry in entries:
            trials.append({"pair_id": alias, "source": pair["source"], "reference": pair["reference"],
                           "candidate": entry["asset"], "runs": entry["runs"], "baseline": entry.get("baseline", False)})
    rng.shuffle(trials)
    reviewer = out / "reviewer"
    (reviewer / "assets").mkdir(parents=True)
    copied, cards, rating_rows, mapping = {}, [], [], []

    def copy_asset(value):
        key = value["sha256"]
        if key not in copied:
            name = f"assets/{rng.getrandbits(128):032x}.png"
            target = reviewer / name
            shutil.copyfile(value["path"], target)
            require(hashlib.sha256(target.read_bytes()).hexdigest() == key, "Image changed while copying")
            copied[key] = name
        return copied[key]

    for index, trial in enumerate(trials, 1):
        trial_id = f"T{index:05d}"
        for run in trial["runs"]:
            run["trial_id"] = trial_id
        mapping.append({"trial_id": trial_id, "pair_id": trial["pair_id"],
                        "kind": "independent_source_baseline" if trial["baseline"] else "model_delivery",
                        "candidate_sha256": trial["candidate"]["sha256"], "run_ids": [r["run_id"] for r in trial["runs"]]})
        rating_rows.append({**dict.fromkeys(FIELDS, ""), "trial_id": trial_id, "pair_id": trial["pair_id"]})
        images = "".join(f'<figure><figcaption>{html.escape(label)}</figcaption><a href="{copy_asset(trial[key])}" target="_blank">'
                         f'<img src="{copy_asset(trial[key])}" loading="lazy" alt="{html.escape(label)}"></a></figure>'
                         for key, label in (("source", "A · 原始 baseline prediction"),
                                            ("reference", "B · 未对齐外观参考"), ("candidate", "C · 待评价图像")))
        cards.append(f'<section id="{trial_id}"><h2>{trial_id} · {html.escape(trial["pair_id"])}</h2><div class="grid">{images}</div></section>')
    page = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>前置实拍匿名评审</title>'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><style>'
            'body{font:16px/1.6 system-ui;margin:24px;background:#eee;color:#222}section{background:white;padding:16px;margin:24px 0}'
            '.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}figure{margin:0}img{width:100%;height:440px;object-fit:contain}'
            'figcaption{font-weight:bold}@media(max-width:800px){.grid{grid-template-columns:1fr}img{height:auto}}</style>'
            '<h1>前置实拍 · 模型匿名评审</h1><p>这是 model-masked review，不是双盲实验。A 决定人物和结构，B 只提供外观目标。'
            '比较 C 相对于 A 的改善、自然度与损伤；禁止把 B 的视角或像素差异当作错误。点击图片查看原尺寸。</p>'
            '<p>按预注册规则填写 <a href="ratings.csv" download>ratings.csv</a>；全部评分为空，网页不计算质量或排名。'
            '部分条目为原始基线检查。保留显示顺序，不根据外观猜测模型。</p>' + "".join(cards) + '</html>')
    (reviewer / "index.html").write_text(page, encoding="utf-8")
    with (reviewer / "ratings.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader(); writer.writerows(rating_rows)
    (reviewer / "README.md").write_text(
        "# 匿名评审材料\n\n只把 reviewer/ 发给评审者；组织者保留目录外的 private_mapping.json。\n\n"
        "这是模型身份隐藏的 model-masked review，不是双盲实验；组织者掌握映射，图像风格也可能泄露模型。\n"
        "打开 index.html 逐项查看。每位评审者复制一份 ratings.csv，填写自己的 rater_id；不要协商分数。\n"
        "appearance_delta / naturalness_delta 使用 -2,-1,0,1,2；preservation 使用 no_damage/minor/major/uncertain。\n"
        "critical_error_tags 和 notes 填观察；usable 留空，待按预注册规则汇总。其他评分列也初始化为空。\n"
        "A 是源图，B 是未对齐外观参考；即使某运行未使用 B，评审时仍展示同一 B，运行本身没有因此获得参考。\n"
        "每个 pair 有一个独立源图基线检查；它不算模型收益。同 pair 的字节相同模型结果共用一个 trial，组织者保留全部关联。\n"
        "无有效选中交付的失败或源图 fallback 不作为模型画质 trial，技术分母保留在私有映射。未获 verifier 接受但可交付的结果仍进入人评。\n"
        "failed 等非完成运行若仍有有效选中交付，也进入诊断性人评；私有映射保留 status、terminal_reason、technical_completed 与 primary_eligible。\n"
        "只有技术完成且有效选中交付的运行才可能进入主可用收益；失败图不能计入主可用增强，主比率仍以预注册计划运行数为分母。\n"
        "本工具不产生自动分数、统计检验或最终结论；人评与技术失败率需要组织者分别汇总。\n", encoding="utf-8")
    summary = {"pairs": len(pairs), "quality_trials": len(trials), "baseline_trials": len(pairs),
               "unique_reported_runs": len(runs), "included_model_runs": sum(r["trial_id"] is not None for r in runs),
               "excluded_model_runs": sum(r["trial_id"] is None for r in runs),
               "primary_eligible_runs": sum(r["primary_eligible"] for r in runs),
               "unavailable_report_entries": sum(len(r["runs"]) for r in unavailable)}
    write_json(out / "private_mapping.json", {"schema_version": "front_camera_masked_review_v1", "review_random_seed": seed,
               "reports": [str(p) for p in report_paths], "summary": summary, "pairs": pair_map, "trials": mapping,
               "runs": runs, "unavailable_runs": unavailable,
               "denominator_scope": "Provided report rows and unavailable_runs only; reconcile against the planned manifest. Missing unreported runs cannot be inferred.",
               "scores_generated": False})
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, nargs="+", required=True, help="Actual report.json exports, including references for all pairs")
    parser.add_argument("--out", type=Path, required=True, help="New output directory")
    parser.add_argument("--seed", type=int, required=True, help="Frozen review randomization seed, not an image-generation seed")
    args = parser.parse_args()
    try:
        result = prepare(args.report, args.out.expanduser().resolve(), args.seed)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print("Review preparation failed: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
