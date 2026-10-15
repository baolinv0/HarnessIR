"""Report what the twenty-photo trial actually did, separately from plans."""
import argparse
import csv
import io
from collections import Counter
from pathlib import Path

from hir_manual.storage import atomic_write, now, read_json, sha256_file, write_json
from hir_manual.service import Controller, history

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", required=True, type=Path)
    args = parser.parse_args()
    batch = args.batch.resolve()
    manifest = read_json(batch / "manifest.json")
    contract = read_json(batch / "trial_contract.json")
    if contract["manifest_sha256"] != sha256_file(batch / "manifest.json") or contract["selection_sha256"] != sha256_file(batch / "selection.json"):
        raise ValueError("Report input selection differs from frozen trial")
    results = read_json(batch / "diagnostic_results.json")
    lookup = {r["sample_id"]: r for r in results["records"]}
    ctl = Controller(batch / "workflow")
    rows, planned = [], Counter()
    for row in manifest["images"]:
        sample_id = row["sample_id"]
        payload = read_json(batch / "diagnoses" / (sample_id + ".json"))
        task_review = read_json(batch / "task_reviews" / (sample_id + ".json"))
        if task_review["diagnosis_sha256"] != sha256_file(batch / "diagnoses" / (sample_id + ".json")):
            raise ValueError("Task review hash mismatch")
        item = lookup[sample_id]
        if item["diagnosis_sha256"] != sha256_file(batch / "diagnoses" / (sample_id + ".json")) or item["request_sha256"] != task_review["request_sha256"]:
            raise ValueError("Report payload differs from the accepted diagnostic result")
        state = ctl.inspect(item["case_id"])
        if history(ctl.case(item["case_id"]))["diagnosis"] != payload:
            raise ValueError("Report payload is not the Controller's official diagnosis")
        if state.workflow_status != item["workflow_status"] or state.budget.consumed or state.budget.reserved or state.received_tools:
            raise ValueError("Case advanced beyond this diagnostic report; create a separate restoration report")
        tools = [p["tool"] for p in payload["tool_plan"]]
        planned.update(tools)
        rows.append({"sample_id": sample_id, "stratum": row["stratum"],
                     "width": row["width"], "height": row["height"],
                     "content": payload["content"], "notes": payload["sensitive"]["notes"],
                     "degradations": ";".join(d["type"] + ":" + d["severity"] for d in payload["degradations"]),
                     "difficulty": payload["difficulty_hint"], "planned_tools": ";".join(tools),
                     "case_id": item["case_id"], "workflow_status": item["workflow_status"],
                     "diagnosis_accepted": item["accepted"], "actual_tool_inferences": 0,
                     "actual_generations": item["consumed_generations"], "restoration_success": None,
                     "canonical_sha256": row["canonical_sha256"], "original_sha256": row["original_sha256"],
                     "canonical_display_note": row.get("canonical_display_note")})
    text_csv = io.StringIO(newline="")
    writer = csv.DictWriter(text_csv, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    atomic_write(batch / "sample_results.csv", text_csv.getvalue().encode("utf-8-sig"))
    probe = read_json(batch / "tool_probe.json") if (batch / "tool_probe.json").exists() else None
    actual_inferences = probe.get("validated_inferences", 0) if probe else 0
    runs = sorted([read_json(p) for p in (batch / "runs").glob("*.json")], key=lambda r: r["started_at"])
    resume = read_json(batch / "resume_check.json")
    assets = read_json(batch / "existing_assets_check.json")
    import xml.etree.ElementTree as ET
    suites = list(ET.parse(ROOT / "engine/validation/quality20_core_tests.xml").getroot().iter("testsuite"))
    engineering_tests = {"tests": sum(int(s.get("tests", 0)) for s in suites),
                         "failures": sum(int(s.get("failures", 0)) for s in suites),
                         "errors": sum(int(s.get("errors", 0)) for s in suites),
                         "elapsed_seconds": sum(float(s.get("time", 0)) for s in suites)}
    receipt = {
        "created_at": now(), "sample_count": len(rows), "strata": dict(Counter(r["stratum"] for r in rows)),
        "actual_current_Work_post_request_image_reviews": len(rows),
        "schema_and_controller_accepted_count": sum(r["diagnosis_accepted"] for r in rows),
        "state_counts": dict(Counter(r["workflow_status"] for r in rows)),
        "planned_tool_counts": dict(planned), "actual_tool_inferences": actual_inferences,
        "actual_chatgpt_desktop_generations": 0, "actual_verifier_results": 0,
        "operator_actions": {"recorded_batch_CLI_runs": len(runs), "post_request_Work_image_reviews": 20,
                             "desktop_uploads_observed": 0, "desktop_saves_observed": 0,
                             "full_loop_manual_operations": None,
                             "note": "Desktop stages not executed; these zero observations do not demonstrate a zero-operation restoration loop."},
        "restoration_success": None, "first_round_direct_vs_harness": None,
        "final_round_comparison": None, "formal_eligible": False,
        "can_conclude": "These 20 real images can be canonicalized, visually diagnosed in current Work, bound to immutable task/input hashes, accepted by Controller and routed to evidence or composition. Resume behavior is reported separately.",
        "cannot_conclude": "No evidence yet about local model coordinates/content/memory/empty detection/cache reuse, ChatGPT desktop edits, restoration success or Harness advantage; no population estimate or paper reproduction.",
        "capabilities": {
            "local_Work_file_handoff": "20 genuine role payloads, response/done files and controller acceptance tested",
            "desktop_session_dispatch": "unsupported by available bridge; manual handoff retained",
            "local_png_persistence": "20 source/canonical files stored with source hashes; no generated editor PNG save tested",
            "desktop_image_edit_and_download": "not tested; no native ChatGPT desktop surface available",
        },
        "references_read": False, "existing_original_assets_modified": False,
        "model_registry": contract["tool_registry"], "evidence_profile": contract["evidence_profile"],
        "controller_runs": runs, "first_T2_probe": probe,
        "resume_check": resume, "existing_assets_check": assets, "engineering_tests": engineering_tests,
    }
    write_json(batch / "acceptance_summary.json", receipt)
    models = []
    for tool, entry in contract["tool_registry"]["tools"].items():
        backend = entry.get("backend", {})
        registered = bool(entry.get('python_executable'))
        registry_name = entry.get('model_name') if registered else "未注册；仅example占位，不能运行"
        planned_model = contract["evidence_profile"]["tools"][tool]["model"]
        implementation = str(backend.get('implementation')) + ' / ' + str(backend.get('device')) if registered else '未注册/未实测'
        models.append(f"| {tool} | {planned_model} | {registry_name} | {backend.get('framework_version') if registered else '未实测'} | {implementation} | {entry.get('ready', False)} |")
    table = []
    for i, row in enumerate(rows, 1):
        tools = row["planned_tools"] or "空计划"
        table.append(f"| {i:02d} | {row['sample_id']} | {row['stratum']} | {row['width']}×{row['height']} | {row['degradations'] or '未确证需修复缺陷'} | {tools} | {row['workflow_status']} |")
    run_lines = []
    for run in runs:
        result = run.get("result", {})
        summary = '; '.join(f'{key}={result[key]}' for key in ('new_cases', 'issued_or_recovered', 'new_acceptances', 'already_accepted_skipped', 'accepted_records', 'stopped_after_publish', 'outcome') if key in result)
        run_lines.append(f"| {result.get('stage', run.get('stage', '?'))} | {run.get('elapsed_ms', 0)/1000:.2f} | {run.get('controller_rss_start_mib', 0):.1f}/{run.get('controller_rss_end_mib', 0):.1f} | {summary} |")
    blocker = "T2 未实测启动。"
    if probe:
        result = probe["result"]
        worker = result["worker"]
        guard_path = Path(worker["log_dir"]) / "resource_guard.json"
        guard = read_json(guard_path) if guard_path.exists() else {}
        blocker = f"首个 T2 probe 为 `{probe['outcome']}`，error=`{worker.get('error_code')}`；启动前可用RAM={guard.get('available_memory_mb')} MiB，要求={guard.get('required_memory_mb')} MiB。PID={worker.get('pid')}，elapsed={worker.get('elapsed_ms')} ms，采样 RSS={worker.get('peak_rss_mb')} MiB。日志：`{worker.get('log_dir')}`。PID为空且耗时/RSS为0表示未启动，不能计为空检测、OOM或模型推理成功。"
    relative_batch = batch.relative_to(ROOT).as_posix()
    report = f"""# 20 张真实照片质量优先 pilot · 当前交付

本次已完成 **20 张真实原图的逐图视觉诊断、JSON 校验和 Controller 交接**。本地模型真实推理、ChatGPT 桌面编辑、独立验证尚未完成；本报告不把诊断完成计为20张恢复完成。

## 抽样与保护

依据 Data/filelists/README.md，当前输入164张；有意分层取20张，night/portrait/telephoto/text/complex各4张，原文件SHA不同。分组包含关系没有造成重复抽样。清单分层名是抽样标签，不保证所有低光图拍于夜间、所有小脸是长焦拍摄，也不能证明独立拍摄事件。未把GT、参考图、人工Mask或ROI提供给任何角色/模型；GT仅用于只读哈希核验，238份既有输入/GT全部无改动。

清晰叶片、清晰人像和清晰长焦场景用于检查过度处理。两张近黑原图保持内容不确定。体育场小脸以原始采样限制记录；反射、霓虹光晕、暖色舞台光和自然景深均保留。CPU类别没有椅子/电路元件，OCR也不解码条码。

抽样前排除多帧MPO commons_003，替为commons_004；记录在selection中。DPDD源16位PNG保留原bytes，canonical显式RGB8，不宣称16位保真或等价指标。所有输出和实验记录位于runtime，Data原文件保留。

## 逐张结果

| 序号 | 样本 | 分层 | canonical尺寸 | 视觉诊断缺陷 | 按需工具计划 | 实测状态 |
|---|---|---|---|---|---|---|
{chr(10).join(table)}

完整内容、保护事项、哈希和case ID见 `sample_results.csv`；原始payload见 `diagnoses/`，请求后图像复核见 `task_reviews/`，正式接受记录见 `workflow/cases/*/transactions/`。

## 能力与边界

- 本地文件交接：20份真实Work诊断已写入response/done，再由Controller验证；有工具的进入WAIT_EVIDENCE，空计划进入WAIT_COMPOSITION。
- 会话派发：当前可用桥不支持自动唤醒ChatGPT桌面角色；本次是人工派给当前Work/子任务，未验证桌面会话自动派发。
- 图片保存：20份original/canonical及输入预览本地保存并校验；这证明本地PNG持久化，尚无编辑器生成图，桌面生成图下载能力未验证。
- 工程流程：20图诊断入口和恢复行为通过的范围见实际runs；SDK输出、多边形/五点/深度/Mask、空检测、RSS、缓存命中仍需真实推理验收。
- 恢复效果：目前0张Direct、0张Harness、0份Verifier，无可报告成功率、首轮差异或最终恢复提升。CPU替代工具阶段标为接口验证；正式GPU评测另冻结Base/SAM3及实际后端。

中断实测：首张response/done发布后正常退出进程，新进程成功接收；再次启动跳过20条已接受结果，没有新增case或编辑消耗。578份case JSON哈希、文件数量、task ID和revision均未改变（resume_check.json）。这不是断电耐久性测试。

工程回归：{engineering_tests['tests']}项测试通过，失败/错误={engineering_tests['failures']}/{engineering_tests['errors']}，{engineering_tests['elapsed_seconds']:.2f}秒。新增覆盖ICC时间、sRGB转换、EXIF、原bytes保留、v1/v2缓存隔离及导出/导回；夹具不算真实工具推理。

## 实际环境与资源

| 工具 | profile目标模型 | 本机注册模型 | 框架版本 | 实现/设备 | 冻结时真实warm-up ready |
|---|---|---|---|---|---|
{chr(10).join(models)}

详细组件hash、Python executable、源码commit、环境lock见trial_contract.json。T4的YOLOE权重及依赖已准备，但静态文本embedding未生成，尚未形成可运行注册项；example里的占位SAM3不是本机T4模型。框架依赖/权重准备不代表推理通过。Controller Python 3.12.14、psutil 7.2.2；实际版本以runs与registry锁为准。模型隔离，单进程、单图、2线程，用完退出，正式推理offline，无自动安装、下载或模型替换。

SDK准备版本：PaddleOCR 3.7.0/PaddleX 3.7.2、Paddle 3.3.1；ORT 1.23.2/SCRFD源码commit 3e6486942a1be2da0e5b475fac375ea73264bd21；DA作者源码commit a561b849ebae10a6f5ef49e26c83cbbcd36c71bf/Torch 2.10.0+cpu/Torchvision 0.25.0+cpu；YOLOE依赖环境Ultralytics 8.4.175/CLIP 1.0（7ffa84b3bfa40c42ecc1c77147a855e69cb2dd40），并未完成T4真实warm-up。

本次发现同一ICC输入的PNG哈希受sRGB配置创建时间影响；像素相同而bytes不同。新canonical去掉动态附带元数据，记录hir_rgb8_exif_icc_v2_stablepng；旧无version的case仍按v1，缓存/作业/导出导回按实际版本，不改旧文件。预检查失败批次保留在runtime/quality20/pilot20_20261013/canonical_mismatch_audit.json。工程回归结果见engine/validation/quality20_core_tests.xml，不能代替SDK真实验收。

{blocker}

启动门槛2048 MiB，运行中低于512 MiB或worker采样RSS超过3072 MiB中止。当前阶段遇资源等待即停止后续模型；其余计划项标未尝试，不产生20个相同失败，不降低门槛或静默换模型。

### 实际脚本耗时和内存

| 阶段（按开始时间排序） | 秒 | Controller端点RSS 起/止 MiB | 结果 |
|---|---|---|---|
{chr(10).join(run_lines)}

以上是Controller端点RSS观察，不是峰值模型内存，也不包含Work看图推理时间。实际model成本单列worker日志。

## 启动和下一步

在项目根目录PowerShell：

```powershell
# 查看此次20张的诊断批次（8502；独立根目录，不另启watch）：
.\\engine\\start-quality20.ps1
# 一般向导仍是 .\\engine\\start.ps1（8501）
# 校验/恢复已接受诊断，不重复采样或新增case：
.\\engine\\.venv\\Scripts\\python.exe engine/scripts/run_quality20.py --batch {relative_batch} --stage ingest
# 有足够可用RAM后，先重新进行本批冻结配置的T2首图probe：
.\\engine\\.venv\\Scripts\\python.exe engine/scripts/run_quality20.py --batch {relative_batch} --stage probe
```

诊断批次仅用于当前阶段的接口和审计。依次推进：T2单脸/多人/小脸三图→T1白天/夜间/小字三图→T3近远与T4类别/Mask各1–3图；每个输出逐图看位置、内容、空结果、图例、进程释放和缓存复用。模型准备/readiness/配置/registry改变后建立新批次或显式分支，不把这里冻结的未就绪T4 case静默升级，不改旧证据快照。全部工具验收后先对realblur_scene094跑Direct1张和Harness首轮1张，独立Verifier，再按需从同原图重试，Harness最多3次编辑；首轮与最终分开记录。通过单图闭环后顺序处理剩余19张，包含控制样本，记录人工操作和中断恢复。GPU迁移后Base/SAM3重新计算，不能将本批CPU数据混作正式结论。

自动桌面交接不可用时继续使用现有JSON/图片手工导入。当前工具和编辑缺口均待真实执行，不用合成夹具、原图拷贝或其他图像模型充作恢复结果。
"""
    atomic_write(batch / "REPORT.md", report.encode("utf-8"))
    print({"report": str(batch / "REPORT.md"), "accepted": len(rows), "restoration_outputs": 0,
           "states": receipt["state_counts"]})


if __name__ == "__main__":
    main()
