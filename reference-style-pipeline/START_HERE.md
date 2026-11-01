# 从这里开始：Reference Style Pipeline → Codex 交接

## 先读结论

这是 A 内容/结构 + B 参考影调/色彩/亮度的**全画面参考迁移文件协议与实现**，不是已证明稳定有效的自动修图系统。最新源码包括 S0–S4、camera_rgb 域说明、具体视觉目标和 faithful mapping。当前实际执行由人/对话代理读取文件，在 ChatGPT 中诊断并调用 imagegen，再导回真实产物；**代码不自动调用模型**。

三轮 A01 试验 + 评价审计的最新结论：Full 在该例肤色黄偏/彩度上有改善证据，亮度变化分区混合；旧粗评的总体 tie **不等于无细粒度收益或两图等价**。单对单次结果仍不证明方法稳定优越。先前候选均未被批准为训练标签。

**下一优先级：整体评价 → 关键区域复核 → 局部指标解释。** 不要继续拿零散区域均值替代全图影调、光照自然度、材质关系和 B 整体贴近度；也不要为迎合反馈倒调权重。新评价规范尚未实现，不要把本交接文字当作已完成功能。

## 目录与阅读顺序

1. `CODEX_HANDOFF.md`：完整需求、实现地图、手工边界、下一步验收。
2. `plans/CURRENT_PLAN.md`：阶段计划和真实完成/未完成状态。
3. `DATA_AND_TEST_PLAN.md`：可利用的 Camera0717 数据、私有获取与颜色/来源要求。
4. `evidence/CUMULATIVE_REPORT_V3_PUBLIC.md`：保留全部三轮历史与最后评价核查的公开脱敏副本。
5. `source/docs/REFERENCE_STYLE_S4.md` 及同目录 S2/S3、CAMERA_RGB、VISUAL_GOALS、FAITHFUL_MAPPING：准确 API/命令。早期阶段文档里的“后续未实现”是历史状态，以上述当前文档/源码为准。
6. `verification/`：源码来源、脱敏差异、当前测试和独立审查；`evidence/round1..3/`：实际提示、文字输出、评审、统计，而非新模拟结果。

## 立即运行：不需要私人图片/模型

已在 Python 3.12.14、NumPy 2.3.5、Pillow 13.0.0、Pydantic 2.13.4、jsonschema 4.26.0、referencing 0.37.0 验证。复现环境请用隔离 venv，通过正常官方包渠道按这些记录版本安装；本交接没有安装步骤副作用。

```sh
cd reference-style-pipeline/source   # 根据实际 checkout 位置调整这一行
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$PWD/engine/src"
python3 -m hre reference-style --help
python3 -m unittest discover -s engine/tests/reference_style -v
```

交接时 scoped **175 项通过**（作者和独立审查分别重新跑）。这覆盖协议、颜色/角色/哈希、目标、回执、候选、ABC、预算及 private policy 边界，不等于真实图片质量通过。整个老 HarnessIR pytest suite 没有在此环境跑通（pytest/Jinja2/Streamlit 未安装，部分历史测试还需要旧机器模型/worker/数据路径）。不要把 scoped pass 写成全仓库通过。

生产元数据位于 `source/engine/pyproject.toml`。若需要完整 HRE/UI，再在隔离环境安装 engine 项目及其声明依赖；当前离线 reference-style 测试不依赖 Qwen/GPU/MediaPipe。MediaPipe 只在另外的真实证据生成阶段需要。

## 私有输入的第一步（不是继续生成授权）

先按 `DATA_AND_TEST_PLAN.md` 取得并核验私人图片，编辑 `examples/camera_rgb_inputs.example.json` 的来源说明/路径；本例不是 Base 输出。运行：

```sh
# 仍在 source/，PYTHONPATH 同上
python3 -m hre reference-style run --config ../examples/camera_rgb_inputs.example.json --out ../local_runs/A01_new
python3 -m hre reference-style budget-configure --root ../local_runs/A01_new --spec ../examples/single_pass_budget.example.json
python3 -m hre reference-style status --root ../local_runs/A01_new
python3 -m hre reference-style run-report --root ../local_runs/A01_new --out ../local_runs/A01_new/REPORT.md
```

这只做输入审计；不会自动出图。示例 1 edit / 3 diagnostics / 0 feedback / total 4 只是曾用单轮上限，**不是新增调用授权或费用额度**。任何新实验先与用户明确预算、条件和评价，再调用。

## 可直接粘贴给 Codex 的启动语

> 请先阅读 reference-style-pipeline/START_HERE.md、CODEX_HANDOFF.md、DATA_AND_TEST_PLAN.md 及 evidence/CUMULATIVE_REPORT_V3_PUBLIC.md。保留现有 HarnessIR，不盲目覆盖根目录。验证 reference_style 的 175 项测试与源码清单，然后先设计并实现更敏感的评价流程：整体 B 风格/影调/光照自然度/关系为先，关键整区域复核，再用局部数值解释；区分可见改善、用户自然度判断与方法稳定性，不把旧 tie 当成等价。新评价尚未实现；不要先增加生成次数或自动跑私有数据。所有模型输出必须真实，camera_rgb 不能冒充 Base，结构容忍只允许事后 verifier 使用，不进编辑提示。提出小步计划并安排独立测试/审查；真实照片只在私有 local data 中使用，禁止提交图片/掩膜/凭据。

## 仓库集成

本目录应作为独立 `reference-style-pipeline/` 加入现有仓库新分支，不覆盖根 `README`、`engine` 或未知上游改动。`source/` 保留可运行的独立源码，不是 base64 或仅补丁。公开版只有两个历史文档因私有服务标识脱敏与冻结来源不同，功能代码未变；详见 `verification/PUBLIC_REDACTIONS.json`。保留 MIT 许可及上游公开学术署名。
