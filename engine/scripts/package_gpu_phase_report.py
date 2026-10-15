"""Save a truthful delivery snapshot from already validated real-run records.

This only packages artifacts. It never launches models, accepts role responses,
changes cases, or approves the four-tool pilot.
"""
import csv
from collections import Counter
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tarfile
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def publish_without_overwrite(destination, source):
    # Hard-link publication is atomic and refuses an existing producer's file.
    temporary = destination.parent / (destination.name + "." + uuid.uuid4().hex + ".part")
    with temporary.open("xb") as stream:
        stream.write(source.read_bytes())
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.link(temporary, destination)
    except FileExistsError:
        pass
    finally:
        temporary.unlink()


def main():
    out = ROOT / "runtime/reports/gpu_phase/20261013"
    out.mkdir(parents=True, exist_ok=True)
    status = read(ROOT / "runtime/offline_monitor/status.json")
    summary = read(ROOT / "runtime/offline_gpu/t1_t2_t3_pilot_summary.json")
    inventory = read(ROOT / "runtime/remote_monitor/phase_inventory.json")
    manifest = read(ROOT / "runtime/offline_gpu/prepared_20261013/manifest.json")
    acceptance = read(ROOT / "runtime/quality20/pilot20_20261013_stable_v2/acceptance_summary.json")
    reviews = read(ROOT / "runtime/reports/gpu_pilot/t1_t2_t3_20261013/summary.json")
    junit = ET.parse(ROOT / "engine/validation/offline_gpu_core_tests_final.xml").getroot()
    suites = list(junit.iter("testsuite"))
    tests = {key: sum(int(s.attrib.get(key, 0)) for s in suites) for key in ("tests", "failures", "errors", "skipped")}
    tests["elapsed_seconds"] = sum(float(s.attrib.get("time", 0)) for s in suites)
    assert tests["tests"] == 259 and tests["failures"] == tests["errors"] == 0
    assert status["accepted_gpu_results"] == summary["actual_inference_confirmed_count"] == 15
    assert reviews["input_count"] == 5 and summary["complete"] is False
    per_tool = {}
    for tool in ("T1_OCR", "T2_FACE", "T3_DEPTH", "T4_SEGMENTATION"):
        rows = [r for r in summary["results"] if r["tool_id"] == tool]
        counter = Counter(r["status"] for r in rows)
        completed = [r for r in rows if r.get("actual_inference_confirmed") is True]
        assert all(r.get("process_released") is True for r in completed)
        unavailable = sum(r.get("error_code") == "unavailable" for r in rows)
        failures = sum(r.get("status") == "failed" and r.get("error_code") != "unavailable" for r in rows)
        per_tool[tool] = {
            "nonempty": counter["ok"], "empty": counter["empty"],
            "runtime_failed_current": failures, "availability_failed": unavailable,
            "missing_not_attempted": status["prepared_image_count"] - len(rows),
            "actual_completed_inferences": len(completed),
            "elapsed_seconds_range": [round(min(r["elapsed_ms"] for r in completed) / 1000, 3), round(max(r["elapsed_ms"] for r in completed) / 1000, 3)] if completed else None,
            "peak_rss_mib_range": [round(min(r["peak_rss_mb"] for r in completed), 3), round(max(r["peak_rss_mb"] for r in completed), 3)] if completed else None,
            "sampled_device_used_mib_range": [min(r["peak_device_used_mib"] for r in completed), max(r["peak_device_used_mib"] for r in completed)] if completed else None,
            "all_completed_workers_released": all(r["process_released"] for r in completed) if completed else None,
        }
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scope": "partial real GPU five-photo pilot; full dataset and restoration are incomplete",
        "source_count": status["source_count"], "prepared_count": status["prepared_image_count"],
        "excluded_sources": status["unsupported_original_inputs"], "tool_statistics": per_tool,
        "expected_tool_results": status["expected_tool_results"], "locally_validated_results": status["accepted_gpu_results"],
        "latest_new_model_executions": summary["model_executions_this_run"], "latest_cache_hits": summary["cache_hits_this_run"],
        "historical_failed_inference_attempts": [{"tool_id": "T2_FACE", "image_id": "commons_002", "job_id": "tool_706479d525de4c30b11ceb82bf1b39c7", "error_code": "import_error", "message": "No module named 'onnx'", "counted_as_empty": False}],
        "engineering_tests": tests, "models": inventory["models"], "shutdown": read(ROOT / "runtime/remote_monitor/shutdown_record.json"),
        "four_tool_pilot_passed": False, "full_processing_started": False,
        "diagnostic_pilot": {"count": acceptance["sample_count"], "states": acceptance["state_counts"], "scope": "current local Work/file handoff; desktop automatic dispatch not demonstrated"},
        "direct_outputs": 0, "harness_outputs": 0, "independent_restoration_verifiers": 0,
        "restoration_effect": None, "harness_advantage": None,
        "gpu_sampling_note": "Device-wide 1-second observations, not exact allocator peak or exclusive per-process VRAM. RSS sampled worker tree at 200ms.",
        "cache_protocol": "existing v1.1 <TOOL_ID>/<cache_key>/{contract.json,evidence.json,ready.json,assets}",
        "blockers": ["SAM3 official authorized checkpoint unavailable; T4 model never started", "ChatGPT desktop automatic session/edit-save bridge not demonstrated; retain manual import", "2 unsupported inputs need explicit frame/colour handling before a new frozen dataset"],
    }
    atomic(out / "summary.json", report)
    shutil.copyfile(ROOT / "runtime/offline_gpu/pilot_processing_status.csv", out / "pilot_processing_status.csv")
    shutil.copyfile(ROOT / "runtime/offline_monitor/status.csv", out / "all_processing_status.csv")
    shutil.copyfile(ROOT / "runtime/reports/offline20/current/report.html", out / "20_photo_diagnosis_and_evidence.html")
    shutil.copyfile(ROOT / "runtime/reports/gpu_pilot/t1_t2_t3_20261013/report.html", out / "5_photo_real_gpu_tools.html")
    shutil.copyfile(ROOT / "runtime/reports/gpu_pilot/t1_t2_t3_20261013/contact_sheet_inputs_T3_actual.png", out / "inputs_and_actual_relative_depth.png")
    # Unpack only small environment freezes from the already returned archive.
    with tarfile.open(ROOT / "runtime/offline_gpu/deployment_receipts.tar") as archive:
        for item in archive:
            if item.isfile() and item.name.endswith(".freeze.txt") and item.size < 1024 * 1024:
                source = archive.extractfile(item)
                (out / Path(item.name).name).write_bytes(source.read())
    cache_index = {
        "protocol_version": "1.1", "index_kind": "frozen_gpu_phase_index", "complete": False,
        "generated_at": report["created_at"], "dataset_manifest_sha256": digest(ROOT / "runtime/offline_gpu/prepared_20261013/manifest.json"),
        "prepared_dataset_root": str(ROOT / "runtime/offline_gpu/prepared_20261013"),
        "expected_results": status["expected_tool_results"], "accepted_results": status["accepted_gpu_results"],
        "statistics": per_tool, "models": inventory["models"], "excluded_sources": report["excluded_sources"],
        "images": manifest["images"], "results": status["all_records"],
        "note": "Index only. Contract, ready marker, asset hash and schema validation remain mandatory; failed/unavailable rows are not caches.",
    }
    atomic(out / "cache_manifest.json", cache_index)
    cache_root = ROOT / "Data/annotations/cache"
    # Preserve existing files written by any other producer. Use exclusive creation.
    for destination, source in ((cache_root / "manifest.json", out / "cache_manifest.json"), (cache_root / "processing_status.csv", out / "all_processing_status.csv")):
        publish_without_overwrite(destination, source)
    lines = ["# HarnessIR GPU 阶段交付 · 2026-10-13", "", "**全量未完成。** 已完成5张真实照片的 T1/T2/T3 推理与导回校验，共15份有效缓存。T4 SAM3 未启动；四工具五图门槛未通过，未启动全量。", "", "## 数据与结果", "", "实际原始低质量输入164张，准备162张；未将74张参考/GT用于模型或角色输入。commons_003 多帧MPO、HC_WildDark_283 不明确/透明颜色模式被拒绝，原文件保留。", "", "| 工具 | 非空成功 | 合法空检测 | 当前运行失败 | 可用性失败（未启动） | 未尝试缺失 |", "|---|---:|---:|---:|---:|---:|"]
    for tool, row in per_tool.items():
        lines.append(f"| {tool} | {row['nonempty']} | {row['empty']} | {row['runtime_failed_current']} | {row['availability_failed']} | {row['missing_not_attempted']} |")
    lines += ["", "T4 全部162项都受授权权重缺失阻塞，上表将已进行可用性检查的1项与未尝试的161项分开。历史T2首次启动缺onnx的真实失败已留档；显式部署修复后重跑通过，未计为空检测。最近一次运行5次新推理、10次同合同缓存命中。没有OOM或超时；15次进程均释放。", "", "## 实际环境与成本", "", "服务器Python3.12.15；Controller与每个工具独立venv，单进程、单图、2线程、完成退出。GPU报告4080 SUPER / 32760 MiB，驱动580.105.08；cgroup内存上限约62GiB，数据盘50GB。结束后设备显存0MiB。部署可下载，推理关闭安装、下载及替换。", "", "| 工具 | 实际模型/框架 | 单图耗时范围 | RSS峰值范围（MiB） |", "|---|---|---|---|"]
    versions = {"T1_OCR": "PP-OCRv6 Medium det+rec / PaddleGPU3.3.1 cu126 / PaddleOCR3.7.0", "T2_FACE": "SCRFD det_10g.onnx / ORT-GPU1.23.2 CUDAExecutionProvider / onnx1.19.1", "T3_DEPTH": "DA-V2 Base vitb / Torch2.10.0+cu128", "T4_SEGMENTATION": "SAM3，未部署/未推理"}
    for tool, row in per_tool.items():
        sec, rss = row['elapsed_seconds_range'], row['peak_rss_mib_range']
        lines.append(f"| {tool} | {versions[tool]} | {sec if sec else '未运行'} | {rss if rss else '未运行'} |")
    lines += ["", "耗时包含每图加载与推理，RSS为200ms采样进程树峰值。显存是1秒设备整体采样，不是精确模型分配峰值；逐图值见pilot_processing_status.csv。环境全锁与权重/源码哈希见本目录freeze文件、summary.json及缓存contract。", "", "DA-V2 Base官方revision a4e71a6c2ce52fe50df0f212066b0d4a87be9b5e，checkpoint SHA256 0d2b7002e62d39d655571c371333340bd88f67ab95050c03591555aa05645328。浮点原图尺寸网格、白近黑远相对深度，不是米制距离。T1保留多边形/原识别字符串/置信度，T2保留框/五点/置信度。坐标使用canonical原图显示域，原始SHA、规范化版本及映射均可追溯。", "", "## 工程、效果与结论", "", f"工程测试{tests['tests']}项全部通过（约269秒）；原始20图真实Work诊断均被Controller接受，14 WAIT_EVIDENCE、6 WAIT_COMPOSITION。原20图CPU case不升级、不回写GPU证据，本报告独立展示新GPU缓存。", "", "本地读写及15份真实GPU缓存导回、schema/合同/源图/资产哈希/尺寸校验通过。角色交接实测范围是当前Work加文件通道；ChatGPT桌面自动派发尚未证实。证据PNG已保存，但ChatGPT编辑图保存未实测。Direct=0、Harness=0、独立恢复Verifier=0；没有可报告的恢复效果、首轮/最终对照或提示词改进结论。手工JSON及图片导入通道保留。", "", "质量观察：OCR有错读和小文字漏检；640整图人脸检测漏掉复杂场景小脸。五图深度没有明显整体反转，但镜面、发光物和复杂场景灰阶压缩不构成几何准确性验证。工具输出有效不能推出恢复有效，更不能推出Harness优于Direct。合成工程测试未替代真实推理。", "", "## 关机与阻塞", "", "**未成功设置系统关机。** PID1=bash的实例不支持系统关机；没有声称停止租赁计费。本次固定计算截止北京时间2026-10-13 09:38，保留15分钟回传，不重新延长。请通过服务商控制台关闭实例。", "", "SAM3官方权重需要已获得授权的checkpoint或授权凭据文件路径；未改用SAM3.1/YOLOE。需要补齐T4五图、查看Mask和图例、通过绑定实际摘要的review后，才能全量162图；截止后需新的明确运行窗口。随后新建GPU case，按原图重试最多3次，真实ChatGPT桌面编辑并独立Verifier，首轮/最终分开记录。", "", "## 启动与断点续跑", "", "项目根目录PowerShell：", "", "```powershell", "./engine/start.ps1", "# 原20图诊断界面", "./engine/start-quality20.ps1", "& engine/.venv/Scripts/python.exe engine/scripts/scan_offline_cache.py --root . --dataset runtime/offline_gpu/prepared_20261013 --batch runtime/quality20/pilot20_20261013_stable_v2 --out runtime/offline_monitor/status.json", "& engine/.venv/Scripts/python.exe engine/scripts/render_offline_gallery.py --root . --batch runtime/quality20/pilot20_20261013_stable_v2 --out runtime/reports/offline20/current --offline-status runtime/offline_monitor/status.json", "```", "", "服务器相同冻结合同断点续跑（不会安装、下载或替换模型）：", "", "```bash", "BASE=/root/autodl-tmp/harnessir_20261013", '"$BASE/controller/bin/python" "$BASE/project/engine/scripts/run_remote_batch.py" --root "$BASE/project" --dataset "$BASE/dataset" --stage pilot --shutdown-record "$BASE/project/runtime/remote/shutdown_record.json"', "# all仍需20条真实结果及绑定摘要的pilot_review；缺SAM3或超过截止会阻止启动。", '"$BASE/controller/bin/python" "$BASE/project/engine/scripts/run_remote_batch.py" --root "$BASE/project" --dataset "$BASE/dataset" --stage all --shutdown-record "$BASE/project/runtime/remote/shutdown_record.json" --pilot-review "$BASE/project/runtime/remote/pilot_review.json"', "```", "", "读取已导回的真实RAIM深度缓存示例：", "", "```powershell", '& engine/.venv/Scripts/python.exe -c "import json,numpy as np; from pathlib import Path; p=Path(\'Data/annotations/cache/T3_DEPTH/81358758a24a26a781b17019215488904a5cfeb8b38e045b5bf975faa9e50f31\'); e=json.loads((p/\'evidence.json\').read_text(encoding=\'utf-8\')); d=np.load(p/e[\'data\'][\'depth_path\'],mmap_mode=\'r\',allow_pickle=False); print(e[\'image_id\'],e[\'model_name\'],d.shape,d.dtype,e[\'data\'][\'larger_is\'])"', "```", "", "## 保存位置", "", "缓存：Data/annotations/cache（保留原有<TOOL_ID>/<cache_key>生产协议；manifest只是索引，不能绕过ready及合同验证）。", "", "本目录20_photo_diagnosis_and_evidence.html与5_photo_real_gpu_tools.html均为无外部依赖HTML；提供输入、真实诊断、已到证据、图例、尚未生成的编辑结果和提示词状态。", "", "运行/错误/GPU采样归档：runtime/offline_gpu/t1_t2_t3_pilot_logs.tar；部署/完整环境锁：runtime/offline_gpu/deployment_receipts.tar；预检查与关机实况：runtime/remote_monitor/server_preflight.json、shutdown_record.json；最终测试：engine/validation/offline_gpu_core_tests_final.xml及.log。", "", "半小时巡检任务harnessir已启用； unchanged时安静，收到权重/新证据后继续。电脑与Codex需保持运行。邮件发送成功回执另存runtime/offline_monitor/email_receipts.json，未发送时不宣称已发送。"]
    (out / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    atomic(out / "delivery_hashes.json", {p.name: {"bytes": p.stat().st_size, "sha256": digest(p)} for p in out.iterdir() if p.is_file() and p.name != "delivery_hashes.json"})
    print(json.dumps({"directory": str(out), "valid_results": 15, "full_complete": False, "tests": tests}, ensure_ascii=False))


if __name__ == "__main__":
    main()
