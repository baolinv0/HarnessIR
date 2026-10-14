# 首个真实 R1 准备审计（2026-10-14）

审计基线：PR #2，`feat/reference-enhancement-v1`，完整提交 `ffe438f121e1d49d675492797be348927a9381a1`。PR 仍 open、未合并；读取时无 PR 评论。远端可见分支为 main、设计分支、实现分支。本文是本次执行记录，不是已完成的真实图像增强报告。

**结论：软件协议可运行；真实 R1 仍为 not_run，尚不能批准直接扩大到 12 对 pilot。可以准备数据和操作环境，先完成一对真实单次对照。**

## 1. 新结果排查与证据边界

- 最新实现提交仍是上述提交；IMPLEMENTATION_STATUS、IMPLEMENTATION_RUNBOOK、EXPERIMENT_HANDOFF 明确真实 R1、12 对、真实编辑和独立评价尚未运行。
- 当前仓库 checkout 不含 Data、experiments 或真实 A/B/C 实验记录目录；仓库图片为论文网页材料，不具有 prediction/reference 来源证明。
- 可访问文件检索没有解析出可核实的 Modular Neural ISP prediction 与对应 iPhone 17 原始参考配对。其他恢复照片、截图或旧项目说明不能自动充当本实验 A/B。
- 本环境没有接入用户 Windows 文件系统或 ChatGPT 桌面会话，因此不能读取 `C:\Users\Lenovo\...`，也不能实测其桌面派发、两图编辑及原图下载。这里的缺失不证明用户电脑上不存在数据或结果。
- 没有真实编辑 C；不填内容保护、风格改善、真实耗时或费用，也不把 protocol fixture 的 success 当成画质结果。

## 2. 本次实际执行检查

环境：Linux x86_64，Python 3.12.14。Pillow 12.3.0、Pydantic 2.13.5、jsonschema 4.26.0、NumPy 2.3.5、Jinja2 3.1.6、Streamlit 1.65.0、pytest 9.1.1。使用现有依赖解析，并非声称复现 requirements-lock.txt 的全部锁定版本。

| 检查 | 本次结果与范围 |
|---|---|
| `python -m pip install -e ./engine` | 通过；CLI 脚本目录不在 PATH，使用 `python -m hre` 可执行 |
| `python -m hre --help` | 通过 |
| `python -m pytest engine/tests -q` | 298 passed，180.32 秒；含文件/CLI/缓存/实验/UI AppTest |
| `python docs/reference_enhancement/v1_20261013/scripts/validate_package.py` | PASS，181 checks；仅设计合同静态检查 |
| `python -m compileall -q engine/src/hre engine/examples` | 通过 |
| `python engine/examples/demo.py --out EMPTY_DESTINATION` | 合成 DirectRef/AgentSingle 各消费 1，Adaptive 消费 2；三链终止并产出报告；无模型调用 |
| 独立 Controller 初始化与任务导出 | DirectRef 导出 Execute；AgentSingle 导出 Diagnose；执行器子目录恰好 A.png、B.png、edit_prompt.txt |
| `python -m hre capabilities probe --case-root SYNTHETIC_CASE` | Controller 文件读写 passed；四项 ChatGPT 桌面能力均 untested |

以上使用独立临时色块 fixture 验证工程行为；未将其登记为真实 pilot。没有修改 engine 运行代码，没有发现本轮检查能够独立复现的运行代码缺陷。没有重新运行真实 T1–T4，也没有尝试绕过缺失的执行器。

## 3. 阻塞分类

| 类别 | 当前证据 | 解除条件 |
|---|---|---|
| 真实数据缺失 | 未取得身份可核实的一对 A/B | 提供下节列出的原始文件与来源；不能仅靠文件名确认身份 |
| 执行环境未接入 | 用户 Windows/ChatGPT 桌面会话不可访问 | 在该机器手动导出/派发/下载并导入；自动化不能假定通过 |
| 工具接入待验证 | 引擎消费合法缓存；无本实验 A/B 的真实 worker 包 | Diagnosis 实际请求工具后，导出 jobs 并完成绑定验证；不能用恢复项目旧 wrapper 直接替换 |
| 独立评价缺失 | 无真实 C，无独立评分 | 两位未参与本例生成/选图的评审者；分歧由第三位裁决，或保留 unresolved |
| 已确认运行代码缺陷 | 本轮未确认 | 若真实文件/响应触发可复现错误，保留原始失败产物再修复 |

T1–T4 是按 Diagnosis 计划消费，不是每个首例必须全跑。若真实计划为空，可以运行无额外工具的 AgentSingle，但只能记录该条件；若计划要求工具，缺失时应保持 WAIT_EVIDENCE。已有 SAM3.1 或其他恢复缓存的成功报告不能证明本实验对应资产与 HRE 合同已匹配。

## 4. 首个 R1 需补充的具体文件

建议按一个场景提供以下目录；这里列的是需求，不是已存在的资产：

```text
r1_input/
  originals/prediction_A.png
  originals/iphone17_reference_B.jpg
  source_provenance.json
  comparability_and_protection.json
  baseline_environment.txt
  baseline_predict_command.txt
  raw_source/（有实际 RAW 时保留）
```

1. **A 原始 prediction 文件**：未经再编辑；其上游 RAW/输入身份、baseline 仓库完整 commit、checkpoint SHA256、实际推理命令和环境。若资料缺失，明确 unknown，只允许带来源缺口的探索性 pilot，不宣称来源可复现。
2. **B 原始参考照片**：真实 iPhone 17、同场景配对关系；保留 EXIF/ICC/拍摄时间等可观察信息。原始 HDR/HEIC 若引擎不能接受，另给有说明的 SDR sRGB 导出，保留原文件和转换记录。不要对齐到 A 或当作像素 GT。
3. **身份与比较标注**：case_id、case_revision、scene_group_id、validation/dev split；共同区域、遮挡/人物运动/光照变化和参考局限。分别在 A/B 自身坐标标 ROI；在 A 的规范坐标标脸、文字、对象和几何保护项。不能在看到 C 后回填有利标注。
4. **冻结执行条件**：现有实验 profiles、安装代码身份、六模板、共同色彩与几何策略、单次预算、可见编辑模型设置和执行顺序。没有 ICC 的 SDR 图需要明确 sRGB 假设；不能静默默认。
5. **真实执行后才产生**：每臂原始下载 C、current task/request、候选 metadata、response/done、阶段观察、成本表。模型精确版本、seed、套餐边际费用不可观测时保留 null/unknown。
6. **独立评价后才产生**：blind export、真实 ratings 与必要 adjudication，使用实际导出 codes/SHA；流程 Verify 不可冒充独立评价。

SHA、asset 字典、任务身份及冻结配置应由现有引擎从真实文件生成；不要手写示例哈希。具体组装命令沿用 [EXPERIMENT_HANDOFF.md](EXPERIMENT_HANDOFF.md)，所有 `hre` 命令可以替换为 `python -m hre`。

## 5. 拿到文件后的最小执行顺序

1. 先核实 A/B 来源、比较限制与保护标注，创建真实 case；再按交接文档组装 run manifest。冻结 `baseline/direct_ref/agent_single`，两生成臂上限都为 1，保留 freezer 的执行顺序和模板证明。
2. 从 frozen_inputs 与 runtime_configs 初始化各 planned record，不能把独立临时 case 的结果事后补接到 frozen run。
3. DirectRef 导出 Execute，使用新编辑会话；仅上传 editor/A.png、editor/B.png 与 edit_prompt.txt。AgentSingle 导出 Diagnose，导入真实 JSON，收集实际计划证据，再 Compose→Execute。两臂尽量同一时段、相同可见模型设置。
4. 记录实际提交与开始/完成时间。每臂保存供应商顺序第一张完整原始 C，不挑最好图；候选 metadata 写实际 generation_count/provider_order。提交不明时暂停，不重复生成。
5. 导入候选、真实 Verify，生成报告；核对 selected hash、success、terminal_reason 和预算。内容损坏、风格不变、fallback 都保留为真实结果。
6. 导出盲评包，独立评审 C 相对 B 的外观方向与 C 相对 A 的内容；不能用 B/C 的像素 PSNR 评价非对齐风格改善。冻结评分后分析，报告所有失败与实际/未知成本。

## 6. 首例优先观察项与 pilot 闸门

**尚无第一例真实结果，因此不存在“本次真实实验已暴露”的画质问题。** 以下只是必须优先实测的风险，不是已证明缺陷：

- 默认 strict 几何合同要求 C 尺寸与 A 一致。若桌面编辑器返回其他尺寸，保存 raw 并记录候选失败；不能静默 resize/crop。确需支持等比例转换时，新建 revision，统一两臂策略，并遵守引擎的精确宽高比条件。
- 两图角色是否被执行器颠倒，是否把 B 的人物、文字或位置复制到 A；尺寸一致并不证明内容保持。
- AgentSingle 是否把“保护内容”误写成禁止亮度/颜色改善，导致流程通过但外观 unchanged；真实 Verify 与独立评价是否分歧。
- 旧 T1–T4 缓存的模型版本、输入 SHA、role、canonical 尺寸/坐标与 HRE wrapper 是否匹配；原生缓存需按导出的 jobs 合同转换注册。
- 手工提交/下载是否能准确记录次数、首个完整输出、耗时和暂停恢复，而不是仅凭“下载了一张图”推断预算。

**当前判断：可准备 R1，尚未具备直接放行完整 12 对 pilot 的实测证据。** 先完成上述最小单次真实对照；若要按现有完整 R1 协议宣布通过，还需真实观察四项能力与恢复，并单独验证预算 3 的 DirectBestOf3/Adaptive 两臂。随后再冻结 12 对压力覆盖集（尽量 12 个独立 scene group，五场景层 3/3/2/2/2，人像与文字各至少 4 对，可重叠），保留所有 planned failures，使用独立盲评和成本记录。R1 通过只证明该环境链路可运行，不证明 AgentSingle 有收益。
