"""Interactive workbench for independent, multi-model stage experiments.

Run with ``streamlit run engine/src/hre/stage_lab/ui.py`` after installing
the engine. Model credentials are read by providers from environment variables.
"""
from __future__ import annotations

import base64
import argparse
import difflib
import html
import io
import json
import mimetypes
import os
from pathlib import Path
import tempfile
import uuid
import zipfile


STAGE_LABELS = {
    "diagnose": "1 · 差异观察",
    "plan": "2 · Action 规划",
    "compile": "3 · 原生条件处理",
    "execute": "4 · 图像执行",
    "judge": "5 · 结果判别",
}
STAGE_HINTS = {
    "diagnose": "分别观察 A/B 的全局、语义区域和区域关系差异。可以直接运行，不需要其他阶段。",
    "plan": "选择一份或多份差异结果，或直接提供自己的上下文，比较各模型提出的动作。",
    "compile": "将动作交给模型原生条件处理路径，比较 Caption、VGL、重写文本和画布信息。",
    "execute": "选择动作或编译结果，调用图像模型。每张原始输出都会保留，便于比较实际变化。",
    "judge": "选择已有执行结果或上传候选图，分别交给判别模型；也可以检查给定 action 的完成度。",
}


def run_label(run: dict) -> str:
    """Readable labels retain the identity of repeated experiments."""
    return " · ".join(str(x) for x in (
        STAGE_LABELS.get(run.get("stage"), run.get("stage", "")),
        run.get("model_id", ""), run.get("id", ""), run.get("status", ""),
    ) if x)


def output_text(run: dict) -> str:
    output = run.get("output") or {}
    if output.get("text"):
        return str(output["text"])
    return json.dumps(output["data"], ensure_ascii=False, indent=2) if output.get("data") is not None else ""


def comparison_rows(runs: list[dict]) -> list[dict]:
    rows = []
    for run in runs:
        output = run.get("output") or {}
        row = {
            "运行": run.get("id"), "模型配置": run.get("model_id"),
            "阶段": STAGE_LABELS.get(run.get("stage"), run.get("stage")),
            "状态": run.get("status"), "耗时 / s": round(run.get("duration_s") or 0, 3),
            "上游": ", ".join(run.get("source_runs") or []),
            "图像数": len(output.get("images") or []),
        }
        for key, value in (output.get("metrics") or {}).items():
            if isinstance(value, (str, int, float)):
                row[key] = value
        rows.append(row)
    return rows


def text_diff_html(left: dict, right: dict) -> str:
    table = difflib.HtmlDiff(wrapcolumn=70).make_table(
        output_text(left).splitlines(), output_text(right).splitlines(),
        fromdesc=html.escape(str(left.get("model_id", "左侧"))),
        todesc=html.escape(str(right.get("model_id", "右侧"))),
        context=True, numlines=3,
    )
    return """<style>body{font:13px system-ui;color:#16242d}table{width:100%;border-collapse:collapse}
td{padding:5px;vertical-align:top}th{background:#eef3f5;padding:8px}.diff_header{background:#edf1f2}
.diff_add{background:#d4f4df}.diff_sub{background:#ffe1e1}.diff_chg{background:#fff0b3}
a{color:#166b74}</style>""" + table


def image_comparison_html(source: Path, candidate: Path) -> str:
    """Embed originals; the browser only scales previews, never the saved result."""
    from PIL import Image
    with Image.open(source) as image:
        width, height = image.size
    with Image.open(candidate) as image:
        cw, ch = image.size

    def data_url(path: Path) -> str:
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")

    ratio = width / max(1, height)
    return f"""<style>body{{margin:0;font:13px system-ui;color:#34424a}}.frame{{position:relative;background:#14242b;
aspect-ratio:{ratio};max-height:520px;width:100%;overflow:hidden;border-radius:12px}}
.frame img{{position:absolute;width:100%;height:100%;object-fit:contain;left:0;top:0}}
.clip{{clip-path:inset(0 50% 0 0)}}.line{{position:absolute;left:50%;height:100%;border-left:2px solid white}}
.tag{{position:absolute;bottom:8px;padding:4px 8px;border-radius:5px;background:#10232bd9;color:white}}
input{{width:100%;margin:14px 0 6px}}</style>
<div class="frame"><img src="{data_url(source)}" alt="A 原图">
<img class="clip" id="candidate" src="{data_url(candidate)}" alt="C 候选">
<div class="line" id="line"></div><span class="tag" style="left:8px">C 候选</span>
<span class="tag" style="right:8px">A 原图</span></div>
<input aria-label="A/C 对比位置" type="range" min="0" max="100" value="50"
oninput="document.getElementById('candidate').style.clipPath='inset(0 '+(100-this.value)+'% 0 0)';document.getElementById('line').style.left=this.value+'%'">
<div>A {width}×{height} · C {cw}×{ch}。拖动滑块比较；不同画幅按原比例留边显示。</div>"""


def _image_path(root: Path, value: str | dict) -> Path:
    if isinstance(value, dict):
        value = value.get("path", "")
    path = Path(value)
    return path if path.is_absolute() else root / path


def _display_images(run: dict) -> list[dict]:
    images = [{"path": value, "label": f"输出 {index + 1}"}
              for index, value in enumerate((run.get("output") or {}).get("images") or [])]
    if run.get("stage") == "judge":
        for item in (run.get("request") or {}).get("images") or []:
            role = str(item.get("role", ""))
            if role == "C" or (role.startswith("C") and role[1:].isdigit()):
                images.append({"path": item["path"], "label": f"{role} · 判别输入候选"})
    return images


def _save_upload(upload, directory: Path, prefix: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    suffix = Path(upload.name).suffix.lower() or ".png"
    path = directory / f"{prefix}_{uuid.uuid4().hex[:10]}{suffix}"
    path.write_bytes(upload.getvalue())
    return path


def _parse_context(value: str) -> dict:
    result = json.loads(value or "{}")
    if not isinstance(result, dict):
        raise ValueError("补充上下文应为 JSON 对象，例如 {\"action\": \"温和提亮人物衣服\"}。")
    return result


def _archive(path: Path) -> tuple[bytes, str, str]:
    if path.is_file():
        return path.read_bytes(), path.name, mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for item in sorted(path.rglob("*")):
            if item.is_file():
                archive.write(item, item.relative_to(path))
    return buffer.getvalue(), path.name + ".zip", "application/zip"


def _show_output(st, root: Path, run: dict) -> None:
    st.markdown(f"**{run.get('model_id', '模型')}**")
    st.caption(f"{run.get('id', '')} · {run.get('status', '')} · {run.get('duration_s', 0):.2f} s")
    metadata = run.get("metadata") or {}
    if metadata.get("synthetic") or metadata.get("simulation") or metadata.get("provider") == "demo":
        st.info("演示数据，不代表真实模型性能。")
    if run.get("error"):
        st.error(str(run["error"]))
    output = run.get("output") or {}
    for index, image in enumerate(_display_images(run)):
        path = _image_path(root, image["path"])
        if path.is_file():
            st.image(str(path), caption=f"{image['label']} · {path.name}", use_column_width=True)
            st.download_button("下载原始图像", path.read_bytes(), file_name=path.name,
                               key=f"image_{run['id']}_{index}")
    if output.get("text"):
        st.text(str(output["text"]))
    if output.get("data") is not None:
        with st.expander("结构化输出", expanded=not bool(output.get("text"))):
            st.json(output["data"])
    if output.get("metrics"):
        with st.expander("输出统计（变化观察）"):
            st.json(output["metrics"])
    with st.expander("输入、上游与运行记录"):
        st.caption("上游：" + (", ".join(run.get("source_runs") or []) or "直接输入"))
        st.code((run.get("request") or {}).get("prompt", ""), language=None)
        st.json({k: run.get(k) for k in ("profile", "usage", "metadata", "source_runs")})
    st.download_button("下载完整 JSON", json.dumps(run, ensure_ascii=False, indent=2),
                       file_name=f"{run['id']}.json", mime="application/json", key=f"json_{run['id']}")


def main() -> None:
    import streamlit as st
    from hre.stage_lab import normalize_stage
    from hre.stage_lab.core import (
        add_case, export_request, import_output, init_lab, list_cases, list_runs,
        load_lab, run_stage, save_models,
    )
    from hre.stage_lab.report import export_report

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--root", default=os.environ.get("HRE_LAB_ROOT", "Data/stage_lab"))
    args, _ = parser.parse_known_args()

    st.set_page_config(page_title="HarnessIR · 分阶段测试", page_icon="◧", layout="wide")
    st.markdown("""<style>.block-container{padding-top:2rem;max-width:1600px}
[data-testid=stMetricValue]{font-size:1.8rem}h1{letter-spacing:-.035em}
[data-testid=stSidebar]{background:#eff4f4}</style>""", unsafe_allow_html=True)
    st.title("HarnessIR · 分阶段测试")
    st.caption("独立运行每个阶段，保留每个模型的输出，并排比较后选择下一步输入。")

    with st.sidebar:
        st.subheader("测试工作区")
        workspace = st.text_input("工作区目录", value=args.root)
        root = Path(workspace).expanduser().absolute()
        if st.button("创建 / 打开工作区", use_container_width=True):
            try:
                init_lab(root)
                st.success("工作区已就绪")
            except Exception as exc:
                st.error(str(exc))
        st.caption(str(root))

    try:
        config = load_lab(root)
    except (FileNotFoundError, ValueError, OSError) as exc:
        st.info("选择目录并点击“创建 / 打开工作区”，然后添加 A/B 图像和模型配置。")
        return

    with st.expander("添加 A/B 样本", expanded=not bool(list_cases(root))):
        source_mode = st.radio("图像来源", ["上传图像", "本地路径"], horizontal=True)
        left, right = st.columns(2)
        if source_mode == "上传图像":
            with left:
                image_a = st.file_uploader("A · 待增强原图", type=["png", "jpg", "jpeg", "webp", "tif", "tiff"])
            with right:
                image_b = st.file_uploader("B · 外观参考图", type=["png", "jpg", "jpeg", "webp", "tif", "tiff"])
        else:
            image_a = left.text_input("A · 文件路径")
            image_b = right.text_input("B · 文件路径")
        case_name = st.text_input("样本 ID（可留空）")
        task = st.text_area("任务说明", value="以 A 为内容来源，借鉴 B 的影调与色彩，保持 A 的内容与构图。", height=75)
        if st.button("添加样本"):
            try:
                if not image_a or not image_b:
                    raise ValueError("请提供 A 和 B 两张图像。")
                with tempfile.TemporaryDirectory() as directory:
                    if source_mode == "上传图像":
                        pa = _save_upload(image_a, Path(directory), "A")
                        pb = _save_upload(image_b, Path(directory), "B")
                    else:
                        pa, pb = Path(image_a).expanduser(), Path(image_b).expanduser()
                    case = add_case(root, pa, pb, case_id=case_name.strip() or None, task=task)
                st.session_state["stage_lab_new_case"] = case["id"]
                st.success("样本已添加")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    models = config.get("models") or {}
    with st.expander("模型配置"):
        st.caption("每个别名是一套可比较的配置。API 密钥填写环境变量名 api_key_env；本页不需要输入密钥。命令型配置可连接本地 PUP、VGL、PE 或图像模型。")
        model_text = st.text_area("models JSON", value=json.dumps(models, ensure_ascii=False, indent=2),
                                  height=250, key=f"models_{root}")
        if st.button("保存模型配置"):
            try:
                parsed = _parse_context(model_text)
                save_models(root, parsed)
                st.success("模型配置已保存")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
        if models:
            st.dataframe([{"配置": name, "模型": spec.get("model", ""), "接口": spec.get("provider", ""),
                           "阶段": ", ".join(spec.get("stages") or STAGE_LABELS)}
                          for name, spec in models.items()], hide_index=True, use_container_width=True)

    cases = list_cases(root)
    if not cases:
        st.info("先添加一对 A/B 图像，即可从任意阶段开始。")
        return
    by_case = {item["id"]: item for item in cases}
    ids = list(by_case)
    new_case = st.session_state.pop("stage_lab_new_case", None)
    with st.sidebar:
        case_id = st.selectbox("当前样本", ids, index=ids.index(new_case) if new_case in ids else 0)
        stage = st.radio("测试阶段", list(STAGE_LABELS), format_func=STAGE_LABELS.get)
    case = by_case[case_id]
    all_runs = list_runs(root, case_id=case_id)
    by_run = {run["id"]: run for run in all_runs}
    st.subheader(STAGE_LABELS[stage])
    st.write(STAGE_HINTS[stage])
    with st.expander("查看 A/B 与任务", expanded=True):
        for col, role in zip(st.columns(2), ("A", "B")):
            with col:
                path = _image_path(root, case["images"][role])
                st.image(str(path), caption=f"{role} · {'内容原图' if role == 'A' else '外观参考'}", use_column_width=True)
        st.write(case.get("task", ""))

    available_models = [name for name, spec in models.items()
                        if not spec.get("stages") or stage in [normalize_stage(value) for value in spec["stages"]]]
    model_ids = st.multiselect("本阶段测试的模型配置", available_models,
                              default=available_models[:2], key=f"models_selected_{stage}")
    prior_stage = dict(zip(list(STAGE_LABELS)[1:], list(STAGE_LABELS)[:-1])).get(stage)
    source_options = [run["id"] for run in all_runs if run.get("status") == "completed"]
    preferred_sources = [run["id"] for run in all_runs
                         if run.get("stage") == prior_stage and run.get("status") == "completed"]
    selected_sources = st.multiselect(
        "上游结果（可留空，直接提供输入）", source_options,
        default=preferred_sources[-1:] if stage != "diagnose" else [],
        format_func=lambda rid: run_label(by_run[rid]), key=f"upstream_{case_id}_{stage}",
    )
    independent_sources = st.checkbox("分别测试每个上游结果", value=True, key=f"independent_{stage}",
                                     help="勾选：每份上游结果分别交给所有选中模型。取消：将选中结果作为同一次调用的共同上下文。")
    candidate_uploads = []
    judge_mode = "blind"
    judge_action = ""
    if stage == "judge":
        judge_mode = st.radio("判别方式", ["blind", "action"], horizontal=True,
                              format_func=lambda value: "独立看图判别" if value == "blind" else "检查 Action 完成度")
        if judge_mode == "action":
            judge_action = st.text_area("待检查的 Action", key=f"judge_action_{case_id}",
                                        help="写明预期修改，或在补充上下文 JSON 中提供 action / actions。")
        else:
            st.caption("独立看图模式只使用 A/B/C 图像与原始任务。")
        candidate_uploads = st.file_uploader("直接上传候选 C（可多张，每张分别判别）", type=["png", "jpg", "jpeg", "webp"],
                                             accept_multiple_files=True, key=f"candidate_{case_id}") or []
    with st.expander("直接输入与模型策略"):
        context_text = st.text_area("补充上下文 JSON", value="{}", height=120, key=f"context_{stage}",
                                    help="例如 {\"action\": \"提高人物衣服暗部可见度，保持逆光关系\"}。可用于跳过前序阶段。")
        prompt_override = st.text_area("自定义本次 Prompt（可留空）", height=110, key=f"prompt_{stage}")
        profiles = ["", "generic", "flux3_klein", "fibo2", "qwen21", "firered11"]
        profile = st.selectbox("条件策略", profiles, format_func=lambda p: p or "使用各模型配置", key=f"profile_{stage}")
    group_count = len(selected_sources) if independent_sources and selected_sources else 1
    if candidate_uploads:
        group_count = (len(selected_sources) if selected_sources else 0) + len(candidate_uploads)
    st.caption(f"本次计划：{group_count} 组输入 × {len(model_ids)} 个模型配置。每次输出独立保存，可重复运行。")

    run_col, export_col = st.columns([1, 1])
    run_clicked = run_col.button("运行本阶段并对比", type="primary", use_container_width=True)
    export_clicked = export_col.button("导出本阶段请求", use_container_width=True)
    if run_clicked or export_clicked:
        try:
            if not model_ids:
                raise ValueError("至少选择一个模型配置。")
            context = _parse_context(context_text)
            if stage == "judge":
                context["judge_mode"] = judge_mode
                if judge_action.strip():
                    context["action"] = judge_action.strip()
            groups = [[rid] for rid in selected_sources] if independent_sources and selected_sources else [selected_sources]
            jobs = [(group, None) for group in groups]
            if candidate_uploads:
                jobs = [(group, None) for group in groups if group]
                for upload in candidate_uploads:
                    jobs.append(([], [_save_upload(upload, root / "uploads", "candidate")]))
            outputs = []
            exports = []
            progress = st.progress(0.0)
            for index, (sources, candidates) in enumerate(jobs):
                kwargs = dict(source_runs=sources, context=context, candidates=candidates,
                              prompt=prompt_override.strip() or None, profile=profile or None)
                with st.spinner(f"处理第 {index + 1}/{len(jobs)} 组输入…"):
                    if run_clicked:
                        outputs.extend(run_stage(root, case_id, stage, model_ids, **kwargs))
                    else:
                        for model_id in model_ids:
                            exports.append(str(export_request(root, case_id, stage, model_id, **kwargs)))
                progress.progress((index + 1) / max(1, len(jobs)))
            if run_clicked:
                completed = sum(run.get("status") == "completed" for run in outputs)
                st.success(f"已保存 {len(outputs)} 次运行：{completed} 次完成，{len(outputs) - completed} 次失败。")
                st.session_state[f"latest_{case_id}_{stage}"] = [run["id"] for run in outputs]
                export_report(root)
                st.rerun()
            else:
                st.session_state[f"exports_{case_id}_{stage}"] = exports
        except Exception as exc:
            st.error(str(exc))

    for index, value in enumerate(st.session_state.get(f"exports_{case_id}_{stage}", [])):
        path = Path(value)
        if path.exists():
            bundle = path.parent if path.name == "request.json" else path
            data, filename, mime = _archive(bundle)
            st.download_button(f"下载请求 {index + 1} · {filename}", data, file_name=filename, mime=mime,
                               key=f"export_{case_id}_{stage}_{index}")

    with st.expander("导入外部模型结果"):
        st.caption("可以把其他工具或服务器得到的文本、JSON 或图像导入同一阶段，立即并排比较。")
        import_model = st.text_input("结果所属模型配置", value=model_ids[0] if model_ids else "external", key=f"import_model_{stage}")
        imported_text = st.text_area("输出文本 / JSON", height=130, key=f"import_text_{stage}")
        imported_images = st.file_uploader("结果图像", type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=True, key=f"import_images_{stage}") or []
        if st.button("导入并加入对比", key=f"import_{stage}"):
            try:
                data = None
                if imported_text.strip():
                    try:
                        data = json.loads(imported_text)
                    except json.JSONDecodeError:
                        pass
                if not imported_text.strip() and not imported_images:
                    raise ValueError("请提供输出文本、JSON 或图像。")
                paths = [_save_upload(upload, root / "uploads", "external") for upload in imported_images]
                imported = import_output(root, case_id, stage, import_model.strip() or "external",
                                         source_runs=selected_sources, text=imported_text, data=data, images=paths)
                st.session_state[f"latest_{case_id}_{stage}"] = [imported["id"]]
                export_report(root)
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    runs = list_runs(root, case_id=case_id, stage=stage)
    st.divider()
    st.subheader("本阶段结果对比")
    if not runs:
        st.info("运行或导入结果后，这里会显示各模型的文本、结构化输出、图像和耗时。")
        return
    rows = comparison_rows(runs)
    st.dataframe(rows, hide_index=True, use_container_width=True)
    runs_by_id = {run["id"]: run for run in runs}
    latest = [rid for rid in st.session_state.get(f"latest_{case_id}_{stage}", []) if rid in runs_by_id]
    selected_runs = st.multiselect("并排显示的结果", list(runs_by_id), default=latest or list(runs_by_id)[-4:],
                                   format_func=lambda rid: run_label(runs_by_id[rid]), key=f"compare_{case_id}_{stage}_{len(runs)}")
    shown = [runs_by_id[rid] for rid in selected_runs]
    for offset in range(0, len(shown), 4):
        chunk = shown[offset:offset + 4]
        for column, run in zip(st.columns(len(chunk)), chunk):
            with column:
                _show_output(st, root, run)

    if len(shown) >= 2:
        with st.expander("文本差异对照"):
            left, right = st.columns(2)
            left_id = left.selectbox("左侧结果", selected_runs, key=f"diff_left_{stage}", format_func=lambda rid: run_label(runs_by_id[rid]))
            right_id = right.selectbox("右侧结果", selected_runs, index=1, key=f"diff_right_{stage}", format_func=lambda rid: run_label(runs_by_id[rid]))
            st.components.v1.html(text_diff_html(runs_by_id[left_id], runs_by_id[right_id]), height=400, scrolling=True)
    image_choices = {f"{run['id']}:{index}": {**item, "run": run}
                     for run in shown for index, item in enumerate(_display_images(run))}
    if image_choices:
        with st.expander("A/C 滑动对比"):
            image_id = st.selectbox("候选结果", list(image_choices),
                                    format_func=lambda key: f"{run_label(image_choices[key]['run'])} · {image_choices[key]['label']}",
                                    key=f"wipe_{stage}")
            image_path = _image_path(root, image_choices[image_id]["path"])
            if image_path.is_file():
                st.components.v1.html(image_comparison_html(_image_path(root, case["images"]["A"]), image_path), height=590)

    export_all = st.checkbox("导出工作区所有阶段", value=True)
    if st.button("生成可离线打开的 HTML 对比页"):
        report = export_report(root, case_id=None if export_all else case_id, stage=None if export_all else stage)
        st.session_state["stage_lab_report"] = str(report)
    report_value = st.session_state.get("stage_lab_report")
    if report_value and Path(report_value).is_file():
        report_path = Path(report_value)
        st.download_button("下载 HTML 对比页", report_path.read_bytes(), file_name=report_path.name, mime="text/html")
    st.download_button("下载本阶段结果 JSON", json.dumps(runs, ensure_ascii=False, indent=2),
                       file_name=f"{case_id}_{stage}_results.json", mime="application/json")


if __name__ == "__main__":
    main()
