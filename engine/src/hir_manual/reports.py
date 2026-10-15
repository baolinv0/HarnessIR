import html
import json
import os
import uuid
import zipfile
from pathlib import Path

from .service import history
from .storage import atomic_write, now, read_json, sha256_file, transactions, write_json


def build_report(case):
    state = read_json(case.path("state.json"))
    hist = history(case)
    config = read_json(case.path("case_config.json"))
    selected = next((r for r in hist["rounds"] if r["round"] == state["selected_round"] and r.get("output_asset")), None)
    final_output = None
    if selected:
        source = case.path(selected["output_asset"]["path"])
        relative = "final/selected" + source.suffix
        atomic_write(case.path(relative), source.read_bytes())
        final_output = {"path": relative, "sha256": sha256_file(case.path(relative)), "selected_round": selected["round"]}
    events = [tx["event"] for tx in transactions(case)]
    imported = [e for e in events if e["type"] == "response_accepted"]
    manual_operations = sum(e["type"] == "manual_intervention" for e in events) + sum(e["details"].get("transport_mode") == "clipboard_import" for e in imported)
    capability_path = case.root / "runtime" / "capabilities.json"
    report = {
        "case_id": state["case_id"], "generated_at": now(), "workflow_completed": state["workflow_completed"], "restoration_success": state["restoration_success"], "terminal_reason": state["terminal_reason"], "selected_round": state["selected_round"], "selected_verification": selected.get("verification") if selected else None, "final_output": final_output,
        "state": state, "profile": config["profile_id"], "intent": config["intent"], "executor": config["executor"], "parent_case_id": config.get("parent_case_id"), "branch_type": config["branch_type"], "deviated": state["deviated"], "budget": state["budget"], "manual_operations": manual_operations,
        "capabilities": read_json(capability_path) if capability_path.exists() else {"local_read_write": "untested", "role_dispatch": "untested", "image_edit": "untested", "image_save": "untested"},
        "rounds": hist["rounds"], "diagnosis": hist["diagnosis"], "evidence": hist["evidence"], "events": events,
        "engineering_protocol_complete": state["workflow_completed"], "algorithm_gain_supported": False,
        "limitations": ["单图流程或协议测试不能支持总体算法增益。", "ChatGPT 后端版本未暴露时保持 null；本控制器不调用模型 API。", "宽高比误差容差 2%，允许记录尺寸变化；无自动裁切或颜色回对齐。", "真实 Direct-1 / Harness-1 生成与独立评价需另行完成。"],
    }
    if config.get("engine_version") == "1.1.0":
        local_events = [e["details"] for e in events if e["type"] == "tool_registered"]
        report["local_tools"] = {
            "evidence_profile_id": config.get("evidence_profile_id"),
            "formal_eligible": config.get("evidence_profile", {}).get("formal_eligible", False) and not state["deviated"],
            "frozen_profile": config.get("evidence_profile"),
            "frozen_registry": config.get("tool_registry"),
            "planned": state["required_tools"], "consumed": state["received_tools"],
            "unavailable": [e["details"] for e in events if e["type"] == "tool_unavailable"],
            "bindings": [e.get("binding") for e in local_events if e.get("binding")],
            "costs": [{"tool_id": e["manifest"]["tool_id"], "source": e.get("source", "legacy_import"), "worker": e.get("worker_cost", {})} for e in local_events],
            "cpu_evidence_scope": "interface_validation" if config.get("evidence_profile_id") == "cpu_probe_v1" else None,
        }
    write_json(case.path("final/report.json"), report)
    lines = [f"# HarnessIR Manual: {state['case_id']}", "", f"流程终止: {state['workflow_completed']}", f"恢复成功: {state['restoration_success']}", f"终止原因: {state['terminal_reason']}", f"选定轮次: {state['selected_round']}", f"生成预算: {state['budget']}", f"协议偏离: {state['deviated']}", f"人工操作记录数: {manual_operations}", "", "算法总体增益：未验证。", "", "## 各轮记录", ""]
    for record in hist["rounds"]:
        lines.append(f"- Round {record['round']}: geometry={record.get('valid_geometry')}, verdict={record.get('verification', {}).get('verdict')}, output={record.get('output_asset', {}).get('path')}")
    lines += ["", "完整响应、原始输出、证据、隔离记录与事务见同目录 JSON 和导出 ZIP。", ""]
    atomic_write(case.path("final/report.md"), "\n".join(lines).encode("utf-8"))
    serialized = html.escape(json.dumps(report, ensure_ascii=False, indent=2))
    image_markup = f'<img style="max-width:100%" src="{html.escape(final_output["path"].removeprefix("final/"))}">' if final_output else ""
    html_text = f'<!doctype html><meta charset="utf-8"><title>{html.escape(state["case_id"])}</title><style>body{{max-width:1000px;margin:40px auto;font-family:system-ui}}pre{{white-space:pre-wrap}}</style><h1>HarnessIR 审计报告</h1>{image_markup}<pre>{serialized}</pre>'
    atomic_write(case.path("final/report.html"), html_text.encode("utf-8"))
    return report


def export_case(case, destination: Path) -> Path:
    build_report(case)
    destination = Path(destination).resolve()
    if destination.is_relative_to(case.case_dir):
        raise ValueError("Export ZIP must be outside the case directory")
    if destination.exists():
        raise ValueError("Export destination already exists; choose a new filename")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for path in sorted(case.case_dir.rglob("*")):
                if path.is_file() and path.suffix not in (".tmp", ".part"):
                    relative = path.relative_to(case.case_dir).as_posix()
                    resolved = case.path(relative)
                    z.write(resolved, relative)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination
