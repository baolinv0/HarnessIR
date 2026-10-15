"""Run with: python -m streamlit run src/hir_manual/ui.py"""
import os
import uuid
from pathlib import Path

import streamlit as st
from filelock import Timeout

from hir_manual.service import Controller, history
from hir_manual.storage import atomic_write, read_json, now

ROOT = Path(os.environ.get("HIR_ROOT", Path(__file__).resolve().parents[3])).resolve()


def stage_upload(upload):
    path = ROOT / "runtime" / "uploads" / (uuid.uuid4().hex + Path(upload.name).suffix.lower())
    atomic_write(path, upload.getvalue())
    return path


def show_result(result):
    if result.accepted:
        st.success(result.message)
    else:
        st.error(f"{result.code}: {result.message}")


st.set_page_config(page_title="HarnessIR Manual", page_icon="📷", layout="wide")
st.title("HarnessIR Manual Wizard")
st.caption("v1.1 · 按需工具 · ChatGPT 桌面 / 可选 Gemini API · 固定原图 · 可审计状态推进")
ctl = Controller(ROOT)
with st.sidebar:
    st.caption(str(ROOT))
    with st.expander("新建单图恢复", expanded=True):
        uploaded = st.file_uploader("原图", type=["png", "jpg", "jpeg", "tiff", "webp", "bmp"])
        input_path = st.text_input("或本地原图路径")
        intent = st.text_area("固定恢复要求", value="改善实际成像缺陷，保留内容、自然颜色和拍摄氛围；不编造无法可靠辨认的细节。")
        route = st.selectbox("执行通路", ["ChatGPT 桌面 / 手工交接", "Gemini API（独立替代实验）"])
        evidence_profile = st.selectbox("工具证据配置", ["cpu_probe_v1", "gpu_full_v1", "gpu_yoloe26l_v1", "gpu_sam31_v5"])
        if route.startswith("Gemini"):
            image_model = st.text_input("图像模型 ID", value="gemini-3-pro-image")
            text_model = st.text_input("诊断 / Composer / 独立验证模型 ID", value="gemini-3.1-pro-preview")
            st.caption("通过官方 API 上传当前角色允许的图片；密钥只从本机文件或环境变量读取。旧 case 不会切换通路。")
        if st.button("新建 case", type="primary"):
            try:
                source = stage_upload(uploaded) if uploaded else Path(input_path)
                config = {"auto_local_tools": True, "evidence_profile_id": evidence_profile}
                if route.startswith("Gemini"):
                    from hir_manual.gemini_api import configuration
                    config.update(configuration(image_model, text_model))
                state = ctl.new(source, intent, config)
                st.session_state["selected_case"] = state.case_id
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    st.caption("角色分别使用 Diagnoser、Composer/Refiner、Verifier 会话。每轮图像编辑新建会话。")


@st.fragment(run_every="1s")
def wizard():
    try:
        ctl.scan()
        cases = ctl.list_cases()
        if not cases:
            st.info("先上传原图并新建 case。")
            return
        ids = [c["case_id"] for c in cases]
        previous = st.session_state.get("selected_case")
        case_id = st.selectbox("当前 case", ids, index=ids.index(previous) if previous in ids else 0, format_func=lambda cid: next(f"{cid} · {c['workflow_status']} · {c['operation_status']}" for c in cases if c["case_id"] == cid))
        st.session_state["selected_case"] = case_id
        case = ctl.case(case_id)
        state = ctl.inspect(case_id)
        req = ctl.current_task(case_id)
        columns = st.columns(4)
        columns[0].metric("当前阶段", state.workflow_status)
        columns[1].metric("轮次", state.round)
        columns[2].metric("已生成 / 预算", f"{state.budget.consumed} / {state.budget.max_generations}")
        columns[3].metric("保留槽位", state.budget.reserved)
        st.info(state.next_action.message)
        config = read_json(case.path("case_config.json"))
        if config.get("executor") == "gemini_api_image":
            st.caption("当前 case：Gemini API 独立替代通路；每个角色为独立无历史请求。")
            key_path = st.text_input("API 密钥文件路径（留空使用 GEMINI_API_KEY）", key="gemini_key_path")
            if req and req.role in ("diagnose", "compose", "execute", "verify", "refine") and st.button("通过 Gemini API 执行当前一步"):
                try:
                    from hir_manual.gemini_api import run_task
                    with st.spinner("等待 API 返回并校验；不会自动重复提交"):
                        receipt = run_task(ROOT, case_id, Path(key_path) if key_path else None)
                    st.success("API 返回已保存并校验：" + receipt["status"])
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
        if config.get("engine_version") == "1.1.0":
            scope = {"cpu_probe_v1": "CPU接口验证", "gpu_yoloe26l_v1": "GPU工具替代实验（YOLOE）"}.get(config.get("evidence_profile_id"), "GPU目标配置")
            st.caption(f"证据配置：{config.get('evidence_profile_id')} · {scope} · 单图/单进程 · {config.get('evidence_profile',{}).get('cpu_threads',2)}线程")
            unavailable = ctl.unavailable_tools(case_id)
            if unavailable:
                st.info("部分计划证据不可用，已明确记录偏离：" + "、".join(f"{tool} ({item['code']})" for tool,item in unavailable.items()))
            from hir_manual.storage import transactions
            costs = [tx["event"]["details"] for tx in transactions(case) if tx["event"]["type"] == "tool_registered" and tx["event"]["details"].get("binding")]
            if costs:
                with st.expander("工具模型、缓存与成本"):
                    st.dataframe([{"tool":d["manifest"]["tool_id"],"model":d["manifest"]["model_name"],"backend":d["manifest"]["backend"]["implementation"],"source":d.get("source"),"cache_key":d["binding"]["cache_key"],"compute_elapsed_ms":d["manifest"]["elapsed_ms"],"sampled_rss_mb":d["manifest"]["peak_rss_mb"],"current_runtime_ms":d.get("worker_cost",{}).get("runtime_elapsed_ms",d.get("worker_cost",{}).get("elapsed_ms"))} for d in costs],hide_index=True)
        if state.block_reason:
            st.error(state.block_reason)
        if state.workflow_completed:
            st.success("恢复成功" if state.restoration_success else f"流程终止，恢复未通过：{state.terminal_reason}")
        capfile = ROOT / "runtime" / "capabilities.json"
        capabilities = read_json(capfile) if capfile.exists() else {}
        st.caption(f"派发：{capabilities.get('role_dispatch', 'untested')} · 图像编辑：{capabilities.get('image_edit', 'untested')} · 自动保存：{capabilities.get('image_save', 'untested')}。当前使用手动发送 / 文件或 JSON 导入。")
        left, right = st.columns(2)
        left.image(str(case.path("input/canonical.png")), caption="固定 canonical 原图")
        hist = history(case)
        outputs = [r for r in hist["rounds"] if r.get("output_asset")]
        if outputs:
            right.image(str(case.path(outputs[-1]["output_asset"]["path"])), caption=f"最新输出 Round {outputs[-1]['round']}")
        if req:
            st.subheader("当前任务")
            st.caption(f"{req.role} · {req.task_id} · {case.path(f'tasks/{req.task_id}')}")
            if st.button("打开任务目录", key="open_task"):
                os.startfile(case.path(f"tasks/{req.task_id}"))
            repair = case.path(f"tasks/{req.task_id}/format_repair.txt")
            prompt_path = repair if repair.exists() and state.next_action.code == "format_repair" else case.path(req.prompt_file)
            prompt = prompt_path.read_text(encoding="utf-8")
            st.code(prompt, language="text")  # Native code-block copy button copies exact prompt.
            st.download_button("下载当前完整任务", prompt, file_name=f"{req.task_id}.txt")
            with st.expander("要上传的图片（按显示顺序）", expanded=True):
                for i, asset in enumerate(req.allowed_assets, 1):
                    st.caption(f"{i}. {case.path(asset.path)} · {asset.sha256[:12]}")
                    st.download_button(f"下载附件 {i}", case.path(asset.path).read_bytes(), file_name=Path(asset.path).name, key=f"asset_{req.task_id}_{i}")
                    if asset.kind in ("map", "overlay"):
                        st.image(str(case.path(asset.path)), caption=asset.path)
            model = st.text_input("实际模型显示名（按 ChatGPT 界面填写）", key=f"model_{req.role}")
            if req.role != "execute":
                with st.form(f"payload_{req.task_id}"):
                    raw = st.text_area("粘贴模型返回的 JSON", height=220)
                    json_file = st.file_uploader("或导入 JSON 文件", type=["json", "txt"], key=f"json_{req.task_id}")
                    submit = st.form_submit_button("导入 JSON 并自动推进")
                    if submit:
                        result = ctl.import_json(case_id, req.task_id, json_file.getvalue().decode("utf-8") if json_file else raw, model)
                        show_result(result)
                        if result.accepted:
                            st.rerun()
            else:
                if st.button("已向编辑器提交一次生成"):
                    ctl.operate(case_id, "submitted")
                    st.rerun()
                with st.form(f"image_{req.task_id}"):
                    output = st.file_uploader("第一张完整生成图", type=["png", "jpg", "jpeg", "webp"])
                    output_path = st.text_input("或已保存图片的完整路径")
                    extras = st.file_uploader("同一次请求的其余图片（按提供顺序）", type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=True)
                    confirmed = st.checkbox("这是当前任务的原始生成结果，已保留提供顺序")
                    if st.form_submit_button("提交图片并自动进入验证"):
                        if not confirmed:
                            st.error("请确认任务归属和提供顺序。")
                        else:
                            extra_paths = [stage_upload(x) for x in extras]
                            result = ctl.import_image(case_id, req.task_id, stage_upload(output) if output else Path(output_path), model, extras=extra_paths, actual_generations=1 + len(extra_paths))
                            show_result(result)
                            if result.accepted:
                                st.rerun()
        if state.workflow_status == "WAIT_EVIDENCE":
            st.subheader("缺失工具证据")
            config = read_json(case.path("case_config.json"))
            if config.get("auto_local_tools"):
                from hir_manual.resource_monitor import available_mb
                st.caption(f"证据配置：{config.get('evidence_profile_id')} · CPU接口验证 · 1进程/2线程 · 当前可用RAM {available_mb():.0f} MiB")
                jobs = [read_json(p) for p in (ROOT/"runtime/tool_jobs").glob("*/job.json") if read_json(p).get("case_id") == case_id]
                if jobs:
                    st.dataframe([{k:j[k] for k in ("tool_id", "status", "cache_key", "attempt", "last_error")} for j in jobs], hide_index=True)
                else:
                    st.caption("按计划查询缓存并等待模型 readiness；没有可用内存时保持资源等待。")
            st.write(state.next_action.required_artifacts)
            st.caption("1.1 evidence.json 的资产路径相对证据目录；legacy 1.0 路径相对 case。所有原始数据、地图和图例需登记并带 SHA，不能仅填路径代替模型看图。")
            manifest_path = st.text_input("evidence.json 的本地完整路径")
            if st.button("登记工具证据"):
                ctl.register_evidence(case_id, Path(manifest_path))
                st.rerun()
            with st.expander("记录探索性跳过工具"):
                tool = st.selectbox("要跳过的工具", state.next_action.required_artifacts)
                reason = st.text_input("干预理由")
                if st.button("记录 skip_tool 偏离"):
                    ctl.operate(case_id, "skip_tool", tool + ":" + reason)
                    st.rerun()
        buttons = st.columns(5)
        if not state.workflow_completed:
            if buttons[0].button("暂停"):
                ctl.operate(case_id, "pause")
                st.rerun()
            if buttons[1].button("继续"):
                ctl.operate(case_id, "resume")
                st.rerun()
            if buttons[2].button("取消 case"):
                ctl.operate(case_id, "cancel")
                st.rerun()
        if buttons[3].button("导出报告和 ZIP"):
            output = ROOT / "runtime" / "exports" / (case_id + "_" + uuid.uuid4().hex[:8] + ".zip")
            ctl.export(case_id, output)
            st.session_state["last_export"] = str(output)
        if buttons[4].button("建立 manual_variant"):
            child = ctl.manual_variant(case_id)
            st.session_state["selected_case"] = child.case_id
            st.rerun()
        if st.session_state.get("last_export"):
            path = Path(st.session_state["last_export"])
            st.download_button("下载最近导出 ZIP", path.read_bytes(), file_name=path.name)
        with st.expander("历史与审计"):
            st.json(state.model_dump())
            st.json(hist)
    except Timeout:
        st.info("Controller 正在处理文件，请稍候。如果另开了 CLI watch，请先停止该进程。")
    except Exception as exc:
        st.error(str(exc))


wizard()
