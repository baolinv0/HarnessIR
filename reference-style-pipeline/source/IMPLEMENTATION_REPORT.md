# 摄影师式参考修图：独立实现与原始方案代码对比

日期：2026-10-29（更新真实后端验证）。实现者：本次 Codex 独立任务。本文是代码与测试报告，不是已完成真实图像效果实验的 REPORT。

## 1 当前结论与证据范围

**交付了独立工具路线的 Python 实现、PhotoCraft Rust 薄封装源代码、配置/运行/实验入口和合成测试。真实 PhotoCraft 已获批准构建并通过 CPU 合成探针；真实 VLM、真实照片效果及 G/T 人审实验未运行。因此不能宣布完整方案已完成验收，也不能宣布比两个旧方案修图效果更好。**

- 已完成：显式色彩审计、双侧像素 mask/可比性、确定性证据、不可变数值目标/ROI、结构规划校验、确定性有界搜索、原始 A 重渲染、独立原生/逐目标验收、有限反馈、失败回退、输入快照与恢复、G/T 导入及匿名对照报告入口。
- 已实际编译并执行：固定 PhotoCraft 提交的实际 `Document/Adjustment/LayerMask/compose::render` Rust 封装。不是用测试替身替代生产实现；生产二进制不存在时明确报错。
- 本轮补齐：双侧 SAM3 自动调度、配置、超时、权重/版本校验、按侧缓存、产物完整性检查和失败恢复；生产路径接入既有 `harness.perception.segment.run_segment`。本轮又新增 VLM 自动区域发现、基于真实 mask 的对应判断及测量后结构化诊断；兼容的手工配置路线单独保留，不能混称全自动。真实模型未运行，测试使用显式替身。
- 未运行：真实 VLM、4–6 个开发样本、20 对保留集、真实 G/T 盲评。用户已指定 Camera0717 的 S26 RGB→iPhone17 RGB 开发 pilot，明确跳过上游 linear→prediction；本环境原图下载受阻，详见下文。
- 不主张 Photoshop 数值等价；不以测试数量证明摄影风格、自然性或研究新颖性。

## 2 固定版本与工作范围

| 对象 | 固定完整 SHA / 状态 |
|---|---|
| 环境原分支 `work` | `0a0c04883990186c4d7d7e9cd754ffb6673978b9` |
| 指定设计与原始 stage 对照 | `9a42778537b675286341872253214977ad80789f` |
| 原始 reference 对照 | `9073086bd86cff3062eab65bcbc32da6e4fd2114` |
| 本次独立分支 | `codex/reference-tool-retouch-photocraft-20261028`，从指定 stage 提交创建 |
| PhotoCraft | 官方 `storytold/photocraft`，v0.16.0 / `b1794c6e0608ccfc887213dcf58398977c5cb75e` |
| 本次实现提交 | 实际后端验证 `c0a201a4e22eeba0c206352d9c3778b62fd1a638`；初版 `e04b8cb9d4aaebb77b8fc3822d00225341447f6e`；双侧调度 `0b918a3870ea842de6b202fd9023c00360d8ae07`；自动诊断 `3d8b539863060d902b6ea0f5042fc263e0b905bd`；没有推送 |
| `34cd7eb` | 本地 `git cat-file -t` 无此对象，内容未核验，不作为已修复证据 |

指定 PLAN.md 已从 GitHub 指定提交取回并完整读取，大小 **54,843 字节**。当前工作树开始时干净；搜索 `/workspace` 没有 AGENTS.md，`.agents` 未提供项目 skill 文件。未读取工程师的新版本，未修改原始分支，未创建 PR、合并或部署。

原始 reference 分支的代码只通过固定 Git 对象读取，用于对比；没有合并/拷贝其新模块。实际复用 stage 的 CLI、原子 JSON 存储与锁，新增 opt-in 工具路线。原有生成路线没有被替换。

## 3 实现覆盖与接口

| 设计职责 | 文件 / 关键接口 | 实现与限制 |
|---|---|---|
| 色彩上下文 | `engine/src/hre/tool_retouch/color.py`: `ColorContext.load`, `linearize`, `lab`, `read_png16`, `encode_png16` | RGB8 ICC 经 LittleCMS 转 sRGB；RGB16 PNG 不经过 Pillow RGB8 截断。高精度非规范 sRGB profile 明确拒绝。Lab D65 与线性 Y 分开命名，原始方向/位深/profile/hash 保留。 |
| 双侧区域 | `evidence.py`: `build_pairs`, `pair_manifest` | A/B 独立 shape 和 mask side；剔除边缘、输入截断；低支持降级；保留理由、覆盖率和 provenance。不是语义自动匹配正确性的证明。 |
| 双侧自动分割 | `segmentation.py::schedule_bilateral`, `sam3_worker.py::main`, `cli.inputs` | 顺序 A/B、CPU 子进程、timeout、已存在 checkpoint+哈希、固定版本、离线限制、内容寻址缓存、失败/不确定状态、产物校验，编辑 mask 通过 region ID 绑定。真实模型未运行。 |
| 既有分割产物复用 | `segmentation.py`: `import_harness_segments` | 源图/生产者/产物哈希绑定，实际 16-bit label→独立 mask；拒绝不可靠产物，不从类名推断可比性。没有运行 SAM3。 |
| 自动语义诊断 | `diagnosis.py`: `prepare_automatic`, `validate_discovery`, `validate_correspondence`, `validate_measured_diagnosis` | opt-in VLM 发现词表、真实 mask 对应、测量后八维诊断；目标以 delta_id 关联并冻结。真实服务未运行。 |
| 统计证据 | `evidence.py`: `measure`, `extract` | 固定 P10/25/50/75/90、Lab/IQR、线性 Y、截断、固定亮度层内颜色。不存在未对齐逐像素 B→A 误差。 |
| 冻结参考合同 | `contracts.py`: `FrozenContract`, `compile_contract` | JSON 串不可变/返回副本；源文件/色彩上下文、支持哈希、证据、目标、保护、排除、未知、政策绑定。数值目标只能由真实 observation+tolerance 引用解析；弱对应只接受方向目标。 |
| 关系目标 | `compile_contract`, `target_results` | 两区同一 metric 的差值目标，使用冻结区间/尺度；各组先平均再聚合，不按像素面积投票。 |
| VLM 规划与验证 | `providers.py`: `StructuredProvider`; `planner.py`: `validate_plan` | 文件交接或字面 loopback OpenAI 兼容 API；明确请求/响应哈希；不读密钥、不上传新第三方、不跟随代理/重定向。参数/工具/目标/mask 严格校验，不接受任意命令。真实 VLM 未调用。 |
| 小操作集合 | `planner.py`: `TOOLS`, `instantiate` | 曝光、单调折线中间调曲线、中间调颜色平衡、饱和度。3 全局/3 局部、≤12 参数；identity 始终在安全区间内，VLM 初值仅记录。 |
| 编辑蒙版 | `masks.py`: `prepare_mask` | 原生像素 feather、效果覆盖强度、4 点线性 Y 窗口。原始/effective mask hash 分开。明确 HarnessIR 扩展，不冒称 PhotoCraft `mask.import`。 |
| 确定性求解 | `solver.py`: `solve`, `Budget` | identity 起步、稳定参数顺序、±1/4 区间宽度、无改善减半、最小步长、严格预算、完整缓存键、硬拒绝先于组均衡归一化残差、幅度正则和确定性并列处理。每次从 A 重渲染。 |
| 实际后端接口 | `backend.py`: `PhotoCraftAdapter` | 二进制哈希、固定提交/CPU/U16/域握手；受限私有工作目录；只发送白名单参数和原始 A/mask；超时、字节数、dimensions、warnings、像素域检查。 |
| PhotoCraft 薄封装 | `engine/photocraft_worker/src/main.rs` | 真实 Rust API 创建原始 Raster、Adjustment、外部 mask Surface；CPU 原生 compose 输出 float；没有 trusted_local 通用分派。已实际编译，CPU 合成探针通过；真实照片效果尚未核验。 |
| 原生交付 | `backend.py`: `export_native`, `replay`; `workflow.py`: `ToolWorkflow.run` | 原生 A 再渲染、RGB16+ICC 导出后重新读取/测量，独立 replay；不放大预览。mask 羽化先原生处理再等比缩小，原生使用同一 effective mask。 |
| 独立验收 | `verifier.py`: `hard_checks`, `native_checks`, `validate_visual`, `accepted` | 数值目标逐项、区域外变化/新增截断、未进入搜索目标的细节能量/边缘跳变、全部保护项和 A/B/C/合同哈希绑定视觉回执。未知不当通过。视觉模型仍非可靠身份检测器。 |
| 有限反馈/状态 | `workflow.py`: `ToolWorkflow.run` | ≤3 外层修订；修订必须引用实际反馈，不改变合同/测量 ROI；接受、部分改善、原图已满足、无安全改善、参考不足、执行失败分别记录，另有离线待响应状态。 |
| 恢复与证据保存 | `cli.py`: `inputs`, `ResumeBackend` | 冻结配置、原文件、规范 A/B、ROI、mask；已完成调用按原序号/hash 复用；replay 独立调用，不把缓存假称实际重复渲染；结果不确定不自动重发。 |
| 实验和文本报告 | `experiment.py`: `export_experiment`, `analyze`, `write_case_report` | 同 A/B 与实际强 G 配置绑定、共同显示尺度、原生另看、匿名 X/Y、原始用户目标先于合同、整对图像 ITT、开发/保留集 ID 防泄漏、逐例失败保留。没有自动合成 G 效果。 |

运行说明与完整合成配置生成器：`docs/experiments/reference_retouch_photocraft_20261028/RUNBOOK.md`、`engine/examples/tool_retouch/make_synthetic_inputs.py`。先前形成的逐文件实施清单：同目录 `IMPLEMENTATION_TASKS.md`。

## 4 PhotoCraft 源码核验与真实执行边界

实际只读 checkout 固定提交，对以下 API 做了源码核对：

- `crates/doc/src/lib.rs`：`LayerMask`、`Layer::new`、`Document::new`、`Document::bounds`、`LayerContent::Adjustment`。
- `crates/raster/src/lib.rs`：`Surface::try_write_region`、`PixelFormat`。
- `crates/doc/src/adjust.rs`：`Adjustment::Exposure / Curves / ColorBalance / Vibrance`、`curve_map`、`ToneSpace::Rgb`。
- `crates/compose/src/lib.rs`：`render` 返回原生 `Buffer.px` 浮点 RGBA，U16 调整量化路径。
- `crates/compose/src/adjust.rs`：U16 RGB 曝光通过 gamma 2.2；曲线 map 采用线性段，不用可能过冲的任意样条。
- `crates/engine/src/adjust_params.rs`：暴露的 0..255 曲线语义与参数边界；本封装直接构建类型化 Adjustment，Python/Rust 均先校验窄范围。
- `crates/automation/src/headless.rs`：确认 trusted_local 风险及 render_png 预览性质；本实现不通过它开放任意模型命令。

算子域固定为 **sRGB display / RGB U16 document**，测量中的 `Y_linear` 使用标准 sRGB 线性化；二者不同是显式事实。优化器评价实际后端渲染，不用 NumPy 的“物理曝光”预测来代替 PhotoCraft 曝光。

| 能力 | 源码对应 | 运行证据 |
|---|---|---|
| CPU 原生合成 | 已核对实际 API，已写封装 | 合成探针通过 |
| 外部 mask 绑定 | HarnessIR Surface→LayerMask 扩展已写 | 全零/全一/局部/软边缘通过 |
| 四类操作 | 实际 Adjustment 枚举，双层参数拒绝 | identity 与非零调色通过 |
| RGB16 PNG 往返 | HarnessIR 编解码，不依赖 8bit render_png | 真实 PhotoCraft 合成输出与 RGB16 往返通过 |
| 全零/全一/局部 mask、各操作 identity、重放 | `probe.py` 可执行真实探针 | 真实 CPU 合成探针通过 |
| PS 数值等价 / 跨平台 bitwise / 分带接缝 | 不在本次支持声明中 | 未测 |

### 已授权执行与构建证据

用户于 2026-10-29 00:40:41 UTC 明确批准此前安装、构建及 CPU 合成验证。已从官方 `https://sh.rustup.rs` / `https://static.rust-lang.org` 安装 Rust **1.95.0 minimal** 至 `/workspace/toolchains/rustup` 和 `/workspace/toolchains/cargo`，无需管理员权限，未安装系统库。固定 PhotoCraft 提交构建成功（65 秒），首次构建无接口编译错误，无须修改 Rust 生产源码。

- worker SHA256：`2c87bc8bfb9a5a69388afebbbb82ff1875e566b03ca8599768803f2b88ae0f74`，2,869,248 字节。
- Cargo.lock SHA256：`a339f9ff3f2bd91edc174721858ddd17de106455d966bfac8d7c2cc0c9a2817f`；已提交 lock、完整 dependency tree、构建日志与探针 JSON。
- 20 条真实 CPU 检查全部通过：空计划、四算子 identity/非零、三类 mask、RGB16 导出/ICC、三次独立 replay、软蒙版边缘、1409×1537（超过 2MP）原生 identity 往返。
- 三次 replay 最大像素误差 0；软蒙版对真实两端输出插值最大误差 2.92063e-5；超过 2MP 的 identity+导出往返最大误差 7.65335e-6。
- 新增真实后端 pytest：完整 probe、Python workflow、真实进程 timeout 回退、Rust 越界/未知工具/参数键拒绝。workflow 的 planner/reviewer 仍为明确替身，因此不称真实自动 Agent 验证。

运行范围仅 CPU 合成数据。真实 VLM/SAM3 未运行，不下载大模型，不用 GPU、付费服务或管理员权限。后续用户已授权 Camera0717 S26→iPhone17 RGB 迁移测试，并明确跳过上游 linear→prediction。3 对开发 pilot 的 Drive 引用和父任务提供的哈希已保存；本环境原图下载受阻，不以缺少 linear prediction 作为本轮阻塞。

## 5 测试证据

### 已完成

- 自动诊断阶段新增测试：**44 项通过**，`engine/tests/tool_retouch/`。包括 >2MP 原生 RGB16 往返、显式 ICC 假设、稳定 profile、mask 羽化与亮度窗口、不同尺寸双侧支持、低支持降级、合同不可变、未知命令/NaN/bool/越界拒绝、确定性搜索/预算/缓存隔离、原始 A 重渲染、原图已满足、原生尺寸损坏、视觉硬失败/遗漏目标、未测数值目标不能通过、逐保护项校验、服务异常回退、离线回执绑定、恢复中的独立 replay、CLI 不覆盖无关目录、G/T 匿名导出/整对评审/分组防泄漏。
- `python -m compileall -q engine/src/hre/tool_retouch` 通过；`git diff --check` 通过。
- 实际 CLI 合成输入生成 + audit 通过；不存在 PhotoCraft 二进制时 `run` 返回 `execution_failed`、`success=false`、`output=original_A`、exit code 2。
- 测试用 `FakeBackend` / `FakePlanner` / `FakeReviewer` 只在测试目录；测试结果明确 simulation=true、real_effect_validated=false。其显示 RGB 乘法不声称与 PhotoCraft 相同。

### 既有回归

首轮完整回归：**403 通过、6 失败、1 跳过**，耗时 385.40 秒。失败均为缺 `streamlit` 的已有 UI 测试；更早收集阶段还发现缺 Jinja2，补入临时依赖后继续。

前一阶段全量为 426 项通过，最后新增 importer 后仅跑定向，**该数字不是本轮最终全量**。

前一轮 `0b918a3` 已有 434 全量 / 37 定向通过，**不是本轮自动诊断补齐后的最终结果**。前一阶段代码固定 `3d8b539863060d902b6ea0f5042fc263e0b905bd`：定向 **44 项通过（2.06 秒）**，当时完整回归 **441 项通过、0 失败、4 警告（413.59 秒）**。4 条警告来自既有 multiprocessing fork 测试。全量与定向均针对同一代码/测试提交；之后只更新文档、样例和日志。

真实后端补齐代码提交 `c0a201a4e22eeba0c206352d9c3778b62fd1a638`：定向 **48 项通过（5.92 秒）**，其中 4 项使用真实 PhotoCraft worker；同代码提交的最终全量回归 **445 项通过、0 失败、4 条既有 multiprocessing 警告（460.16 秒）**。全量与定向均显式启用实际 worker，代码/测试自该提交后未变。真实后端测试通过不代表真实 VLM 或照片效果通过。

最终验证环境：Python 3.12.14；NumPy 2.5.4；Pillow 13.0.0；pytest 9.2.0；Streamlit 1.66.1；Jinja2 3.1.6。依赖安装在 `/tmp/harness-test-deps`，未更改项目依赖声明或系统安装。该临时环境不是仓库旧 requirements-lock 的同版本闭包，版本如实记录。

### 未运行

真实本地 VLM、真实 SAM3（调度已有替身测试）、真实源图风格/内容/自然性、正式 G/T 成对实验、人审一致性、跨平台重放、性能/峰值内存评估。真实 PhotoCraft M0 的上述合成子项已有证据；不据此将真实模型、真实照片或整体 M1/M2/M3 写为已通过。

## 6 独立第二遍代码审查与修复

审查由本任务进行第二遍源码检查与定向回归，没有调用其他代理，也不冒称独立第三方审计。

1. **参数字典顺序与 cache 语义不一致**：canonical JSON 忽略键顺序，而坐标搜索原先依赖插入顺序；改为稳定排序，新增顺序等价测试。
2. **未测数值目标误通过风险**：数值目标缺失原先与纯感知目标同为 residual=None；现在结果显式带 kind，仅感知/保护可依赖视觉，未测数值目标不可 accepted。
3. **保护覆盖不足**：仅 overall content 不够；新增冻结保护项逐项回执校验，任何 fail/uncertain 不得 accepted。
4. **离线恢复序列化差异**：tuple/list roundtrip 导致冻结快照误判变化；改为 canonical 比较，CLI audit→run 重复验证。
5. **颜色 profile 非确定时间戳**：规范化 ICC 创建日期和 profile ID，保证相同环境导出的字节可重现。
6. **高精度 ICC 近似过宽**：不再凭描述与 8bit 网格近似判断 RGB16 可接受；比较规范 sRGB 色度/TRC 标签，其他高精度空间 fail closed。
7. **回退仍 exit 0**：接入现有 CLI `accepted=false` 返回约定，缺后端/失败 exit 2。
8. **反馈缺依据**：第二轮起必须引用实际当前反馈；原生硬失败和视觉/保护失败保留为结构修订证据。
9. **恢复时重复消耗后端**：对每个独立调用持久化输入/输出哈希；真实 replay 与第一次渲染不同调用序号，恢复只复用已完成的同次调用。
10. **输出目录覆盖风险**：拒绝在已有无关文件目录中初始化，原始输入和旧 run 不覆盖。
11. **SAM3 缓存 roundtrip**：新调度首轮测试发现首次运行/缓存恢复的 tuple/list 元数据不同，已统一 canonical binding；新增按侧缓存、参数变更失效、B 失败不重试、缓存污染、尺寸异常、缺 checkpoint、CLI 编辑区域绑定等 7 项测试。

## 7 与两个原始方案的代码级比较（修正路径范围）

**撤回上一版跨路径推断。** 原始 reference 主要比较对象是固定 `9073086bd86cff3062eab65bcbc32da6e4fd2114` 下 `hre v3`、`workflow_contract=reference_retouch_v1`。独立 `hre-retouch` 工作台是另一条实现路径。上一版用工作台的 evidence/refine 行为“更正”此前 v3 观察不成立；以下分别列证据，不互相替代。`34cd7eb` 仍未取得，不能用其报告改写这里的固定 SHA 结论。

### 7.1 主对照：stage 与 v3 reference 主路线

| 维度 | stage `9a427785` | v3 reference `9073086` | 本次工具路线 |
|---|---|---|---|
| 诊断 | `stage_lab/core.py::_make_request` 构造阶段输入，上游诊断/计划由 provider 输出 | `v3/reference_retouch.py::DIAGNOSIS_SCHEMA/_diagnosis`：八维参考 profile、candidate_deltas、coverage、source protections，明确 needs_evidence 等状态 | 新 `diagnosis.prepare_automatic` 先 VLM 区域发现，再实际 mask 对应；`ToolWorkflow.run` 在测量后调用独立 diagnose，并校验八维覆盖和真实双侧 evidence。 |
| evidence 后状态 | stage 是独立实验台，不是本次的冻结目标状态机 | `runner.py::run_case` 466–484：diagnose→evidence→compose，**没有 evidence→diagnose 回边**；`_initial_context` 将旧 diagnosis 和新 evidence 同时给 compose | measured diagnose 明确在 `extract` 后执行，避免旧 readiness 状态阻止利用新测量。 |
| 目标与合同 | 主要由阶段 prompt/provider 决定 | `_composition` 217–243：target.delta_id、A/B facts/regions/comparability/evidence 与诊断一致，条件 uncertainty 沿袭，ready_to_edit 要求旧 diagnosis 为 transfer_supported；`frozen_contract` 冻结目标除 instruction 外字段 | diagnose delta→target.delta_id；目标不得换地区/丢证据/遗漏 transfer=target，保护/uncertainties 不得丢失；数值由程序 observation+tolerance 解析；诊断也进入冻结合同。 |
| 执行编译 | `stage_lab/providers.py::call_provider` 接 API/local worker/import，生成式执行保留 | `runner.run_case` condition 阶段将**完整 intent**保留在 original/prepared/compile request；`common.render_instruction` 是文本投影，不显式输出单个 target.uncertainty/comparability，只输出顶层 intent.uncertainties | 执行是白名单 Adjustment 计划和从原始 A 重渲染，不将参数求解压成生成提示。合同中完整诊断/条件限制对 planner 可见；数值执行窄范围校验。 |
| 反馈触发 | `run_stage` 提供复用/独立阶段，不等同自动验收闭环 | `runner.py` 657–676：actionable 只由 issues 中有 suggested_change 且 kind 非 uncertain/execution_contract_violation 的条目形成；无 actionable 或 verdict=uncertain 则停止；不是由 target_results 单独触发 | 数值逐目标/native/visual/preservation 结果成为反馈对象；外层修订须引用当前实际反馈 ID，目标/ROI 冻结，预算有界。 |
| 反馈可见性 | 可向后续阶段附上游输出 | refine 的 context 包含完整 verification，因此 **target_results.suggested_correction 可被看到**；但 actionable_feedback_refs 仍仅 issues，`validate_stage` 要求引用其中一项，故“看得到”不等于“会独立触发” | 未满足目标可直接作为反馈数据；无实际反馈不能自由改计划。数值/视觉都不修改目标合同。 |
| 验收 | `_make_request(judge)` 默认移除上游叙事；completed 只表示运行完成 | `_verification` 251–271 验证逐目标与 mandatory achieved、保护/伪影；runner `_accepted/_reference_delivery` 还核对 geometry/delivery。不能说旧 v3 只有 overall improved | 重新测量每个目标、数值硬拒绝、原生边缘/细节检查、独立逐保护项/视觉回执、精度导出/replay。真实运行效果尚未验证。 |
| 分辨率 | `_image_metrics` 记录真实宽高/是否匹配 A，无确定性原生重渲染 | `_reference_delivery` 检查输出、画布与交付；生成器能力仍决定实际尺寸。完整请求保留几何约束不等于已保证 native 输出 | 从原生 A 重渲染并读取 RGB16 导出再测；Rust 路径已编译并通过合成原生 probe；不能扩展成真实照片效果通过。 |
| 测试与取舍 | 原有 stage/provider/UI 测试 | 本次只读固定 v3 代码，不运行其真实模型效果；不能将工作台测试当 v3 修复证据 | 新自动链路以测试替身验证；真实模型未运行，PhotoCraft 已有 CPU 合成证据。低维确定性控制可审计，但工具表达能力/分割质量仍需真实数据检验。 |

#### 三个重点问题的精确结论

1. **evidence 后是否重诊断：否。** `runner.py` 483 设置 phase=compose。compose 同时看到 evidence 与旧 diagnosis；`_composition` 会再次验证旧 diagnosis，而不是调用 VLM 重诊断。若旧 status=needs_evidence，新 evidence 本身不会把它改成 transfer_supported；ready_to_edit 的状态约束仍使用旧状态。这是固定 v3 路径结论。
2. **target-level uncertainty 是否入执行：结构化请求中保留，通用文本投影未显式展开。** `reference_retouch._composition` 235 检查条件 uncertainty，`frozen_contract` 保留它；runner condition 阶段复制整个 intent。`common.render_instruction` 240–249 的 target 文本不包含 target.uncertainty/comparability，只追加顶层 uncertainties。不能泛化为所有自定义 compiler 都永远看不到，也不能据顶层 uncertainties 推定每条 target 限制都已进入最终生成指令。
3. **target_results 修正是否独立触发：否。** verifier schema 存 suggested_correction，完整 verification 进入 refine context；但 runner 657–660 的进入条件及 675–676 的 actionable refs 都只检查 issues[].suggested_change。只有 target_results 有建议、issues 没有 actionable 时，直接 no_supported_refinement。若由另一个 issue 触发，target_results 可以辅助后续修订；两者必须区分。

### 7.2 独立 retouch 工作台（单独对比，不代表 v3）

| 连接点 | 固定工作台代码观察 | 与 v3 的关系 |
|---|---|---|
| evidence | `retouch/workflow.py::step('evidence')` 在已有 analysis 且无 contract 时将 phase 更新为 compose | 是工作台的阶段推进；没有证明 v3 evidence 后重诊断，也不否定 v3 的旧 diagnosis readiness 限制。 |
| uncertainty | `retouch/contracts.py::validate_reference_composition` 沿袭条件限制；`compile_prompt` 目标行未专门输出 uncertainty | 只能说明工作台自己的文本投影，不能用它替代审查 v3/common.render_instruction。 |
| 反馈 | `workflow.import_stage('refine')` 的 actionable 集合包含 partial/unmet target_results 和 failed preservation/artifact checks | 工作台允许目标反馈，**不能推翻 v3 仅 issues 触发的观察**。 |
| 验收 | `retouch/contracts.py::decide_verification` 要求所有目标和保护/伪影检查；`_delivery_assessment` 分开外观和交付 | 与 v3 有概念相似性，但函数、状态、schema 不同，不混用测试和修复结论。 |
| 产品入口 | 独立 HTTP/UI 工作台 | 本次只复用 stage 的 CLI/存储，不宣称已把任一旧 UI 接入新执行器。 |

以上源码均由固定 Git 对象读取。没有读取工程师新实现，未合并另一个分支，也没有把未知 `34cd7eb` 视为修复。

### 7.3 自动链路覆盖审计（修正“选工具即诊断”的混淆）

| 内容 | 本轮前 | 本轮新增真实入口/函数 | 是否仍需用户填写 |
|---|---|---|---|
| 语义区域标签 | SAM3 配置 labels；用户预填 | `cli.inputs` 检测 automatic_diagnosis → `diagnosis.prepare_automatic` → `StructuredProvider('discover_regions')`，查看 A/B 返回词表、观察、保护项 | automatic 路线禁止预填 labels；普通兼容路线仍可手填，不能混称全自动。 |
| 像素 mask | 实际 SAM3 调度或文件导入 | `schedule_bilateral(...allow_unpaired=True)` 按 VLM 词表分别执行 A/B；mask 仍来自真实分割，VLM 不能生成像素 | 用户只提供已批准的本地 checkpoint、哈希、版本与算力配置；测试用 runner 替身。 |
| A/B 对应和可比等级 | 配置 regions/reasons | `StructuredProvider('correspond_regions')` 查看真实 mask overlays/crops 和实际 catalog；`validate_correspondence` 限定真实 A/B mask ID，随后 build_pairs 做支持降级 | automatic 路线不需预填对应；未知对应仍可被判 not_comparable，并且同标签不保证同实例。 |
| 参考差异解释 | 旧 contract prompt 合并解释与目标，未独立校验诊断覆盖 | `ToolWorkflow.run`: extract 后调用 diagnose；`validate_measured_diagnosis` 检验真实双侧 evidence、八维 coverage、target/preserve/exclude/uncertain、保护项与弱对应不确定性 | 由 VLM 解释；程序不把每个数值差强制当修复目标。 |
| 目标合同 | 原本已由 VLM contract 输出，程序解析数值；不是用户预填全部目标 | diagnose→contract；`compile_contract(...diagnosis=...)` 校验 delta_id、区域/证据沿袭、保护/uncertainty、覆盖所有 transfer=target，然后冻结 | VLM 选择目标；用户仍需预先冻结开发容差、保护阈值和预算，这是实验政策，不是每例语义诊断。 |
| 工具选择/幅度 | VLM plan + 程序 search | 保留 plan/solve；把完整 measured_diagnosis 一起传给 planner | 不把会选择工具当作上述诊断已正确，分别保存请求、回包和校验结果。 |

新入口示例 `engine/examples/tool_retouch/config.automatic.example.json`：`masks={}`、`regions=[]`、`edit_masks={}`、segmentation.labels/regions 均空，automatic_diagnosis 提供真实本地 VLM 或离线回执配置及原始完整用户目标。缺真实服务/权重时仍暂停或失败，不伪造结果。

预算统一记账：discovery + correspondence 先计 2 次，measured diagnosis + contract 再计 2 次，首次 plan + 独立 verify 共 2 次；典型完整路径 6 次，仍受总 8 次约束。离线预处理请求可在相同目录恢复，配置与文件哈希不可更改。真实 VLM/SAM3 尚未运行；新增端到端替身测试只证明入口和结构约束连接，不证明摄影师判断能力。

## 8 工程师后续对照清单

工程师实现到位后，双方固定代码 SHA，用同一合成回归与同一保留图像对逐项比较：

1. A/B ICC/位深/方向/处理链；是否有无记录的 RGB16→RGB8 或 profile assignment 冒充 conversion。
2. A/B mask 是否独立产生；有效内部支持和排除规则是否冻结；局部编辑能否偷改验收 ROI。
3. 数值目标是否只能来自实际证据；部分可比是否被设为精确硬目标；mandatory 是否被反馈放宽。
4. 操作白名单、类型/NaN/边界校验、曲线单调、真实后端参数域；是否存在模型任意命令入口。
5. identity 起点、稳定坐标顺序、预算、缓存键、同分/回退策略；是否每次从 A 重渲染。
6. 外部 mask→LayerMask 实际语义、覆盖强度/feather/native 映射；全零/全一/局部效果。
7. PhotoCraft build/commit/CPU/ICC/位深；原生 compose/导出是否绕开 8bit render_png。
8. 原生失败、视觉硬失败、未测目标、遗漏保护项、服务未知状态，是否能被错误标 accepted。
9. 真实自动区域/分割是否闭环；人工辅助是否混入自动结果；两份实现的调度、失败恢复与真实分割质量分别验证。
10. 同一冻结强 G、同一合同与原始完整用户目标、共同显示尺度/原生细节、匿名评审、失败全纳入、图像对为单位。
11. 两份实现逐目标/逐例差异与错误复现，最后再比较真实图像效果；不按代码行数或通过测试数量选优。

## 9 未完成、受阻与下一步

| 事项 | 当前状态 | 精确原因 / 下一步 |
|---|---|---|
| Rust 1.95.0 安装、PhotoCraft build/probe | **已批准、已完成** | 官方工具链已安装，固定提交编译成功，20 条真实 CPU 合成检查通过。 |
| Cargo.lock 与实际 worker hash | 已产生并保存 | 详见第 4 节及 verification/photocraft-build.json、photocraft-dependencies.txt。 |
| 双侧 SAM3 调度与语义对应 | 调度实现完成，真实模型未运行 | `segmentation.schedule_bilateral` + `sam3_worker` 复用既有 run_segment；新 automatic_diagnosis 路线由 VLM 提出词表并在真实 mask 上判断对应，手工配置路线仅兼容；不下载模型。源图/权重/版本/参数/源码/按侧产物全部绑定，失败不自动重试。本环境 torch/ultralytics 未安装，无已提供的 checkpoint；缺的是本地运行依赖/资产和真实效果证据，而不是调度代码。 |
| 真实 VLM | 未运行 | 没有已提供的本地服务配置/模型；常用 loopback 端口未监听（不代表其他端口都不存在）。真实接口和文件交接可用，缺服务失败关闭。 |
| Camera0717 真实 RGB 迁移 | 原图传输受阻，未运行 | 6 个 Drive 原文件引用已取得；本环境无 download_file 工具，认证 file_uri 地址的连接被网络代理以 403 拒绝，没有原图落盘。未改公开链接或绕过代理。上游 linear→prediction 已按用户要求跳过，不是阻塞。 |
| 公平 G/T 与人审 | 未运行 | 仍缺冻结强 G 输出/配置和人审；本轮 RGB 开发 pilot 不冒充保留集成绩。 |
| 高精度非 sRGB / RAW / TIFF / alpha | 当前不支持、明确拒绝 | 需增加经过实际往返验证的高精度 CMS/I/O；当前保证支持路径不偷偷降精度。 |
| 分带/大图性能 | 未验证 | 当前 full-frame CPU，原生 >2MP 编解码测试通过；实际 PhotoCraft >2MP 合成往返通过；更大真实图内存/速度仍需测量。 |
| 工程师新实现对比 | 未进行 | 尚未提供，且本任务明确要求保持独立。 |

本报告保留完成、失败和未运行三类证据。Git diff 与本地提交供审查；未经授权不会推送实现。


## 10 可交付附件

Library 批量上传路径此前两次及本次获授权恢复尝试（共三次）均在 `tools/list` 阶段返回 `network`，尚未进入上传。原报告 ID `[PRIVATE_LIBRARY_ID]` 仍指向旧版，未更新为本地最终报告；完整实现补丁尚未上传，未取得 Library ID。没有成功上传项或不确定写入。本次已使用刷新后的受支持 helper 恢复尝试，仍在上传前失败；没有切换直接写入或再次重试。

最终报告全文已在任务消息中提供。完整实现补丁保留在本地，由指定 stage 基线生成，包含 Rust、Python、测试、配置及文档；本地路径及校验信息仅作为保留证据，不代表附件已交付，也不声称旧 Library 附件与当前本地报告一致。

## 11 Camera0717 开发 pilot 与最小阻塞

用户明确本轮直接用 RGB 输入测试迁移，已跳过上游 linear→prediction。父任务按场景选 01（背光展柜）、07（粉红招牌卖场）、19（夜间蓝色商场招牌），避开 17/18 疑似交叉、12/13 差异及缺图；不按结果指标筛选。Drive ID、文件名、字节数和父任务核验 SHA256 已保存于 verification/camera0717-pilot-inputs.json。

本环境只取得 6 个原文件引用，下载工具未提供；认证下载连接被代理 CONNECT 403 拒绝，原图目录为空，未进行本环境像素/EXIF/ICC 核验。父任务报告 P3 JPEG、S26 方向 8、iPhone 缺拍摄时间等元数据，不能写成本环境已实测。照片传输与模型服务是当前具体阻塞，非输入 RGB 本身。

恢复需要：通过受支持机制把已授权的 6 张原图送入本环境并核对哈希；为自动链提供已安装的本地 VLM 端点和 SAM3 依赖/checkpoint，或在 files 模式逐阶段提供真实模型回执。离线接口见 RUNBOOK 第 4/7 节；绑定 request_sha256、observer、payload，不接受伪造回包。真实图像的实际 ICC 转换和原生后端检查可在原图到位后先进行，不必等待模型。

### 第一方 Library ZIP 传输尝试

父任务提供已授权的 6 图原始 ZIP：`[PRIVATE_LIBRARY_ID]`，版本 0，`[PRIVATE_BACKING_FILE_ID]`，9,502,530 字节，父任务提供 SHA256 `031beb6db543206d1d9a8793d6c3d3b058d442b2dd9f8bdc1337734192ecf761`。

官方 prepare_materialize 已成功解析该引用，指定本环境 `/workspace/camera0717_inputs`；返回签名下载 transfer，workspace_path 为 null，并未复制到本机。随后按当前 Library materialization skill，用完整 transfer 对象调用刷新后的官方 library_file_transfer.py，返回 `library file transfer failed: download failed`，退出码 1。helper 未暴露更具体 HTTP 原因，不能把它断言成新的 403 或访问审批拒绝。

本机核对 ZIP 不存在，目录存在。此项是已知传输失败，非成功或不确定写入；未验证 ZIP 哈希、未解包、未核验 6 图像素/ICC/方向，也未执行真实 RGB 非身份调色/导出。未重试被拒绝的 Drive 连接，未修改代理或更换环境。仅在获得支持的本机文件传输能力后才能继续真实图像部分；合成 PhotoCraft 验收结果保持不变。

## 12 当前聊天协议、逐阶段trace与交接准备

用户允许使用当前对话模型作真实视觉判断；新增 files 配置 `{"mode":"files","provider":"current_chat_offline"}`，请求包含该来源标签，回执外壳 observer 必须一致。没有部署或冒充 Qwen 服务，没有生成真实视觉回包；当前对话已见规划上下文时不声称独立盲评。精确请求/回执字段、各阶段图像/统计要求、PNG审阅包导出脚本、暂停与恢复命令见 CURRENT_CHAT_PROTOCOL.md。新来源配置须使用新运行目录，不改旧冻结配置。

新增 trace.py：每次实际阶段写独立不可覆盖序号JSON，记录attempt、时间、状态、耗时、来源、输入/输出及其哈希、相对前阶段变化、下一步影响。暂停/失败也留痕，恢复尝试不覆盖旧证据。analysis阶段明确图像未改变；色彩转正/转换与编辑候选变化另标。新 REPORT.md 按trace实际顺序展开，列出未记录阶段及A/B/实际原生C索引，不凭记忆补结论。

每次原生候选保存 native-attempt PNG（包括被原生检查拒绝的合法像素输出），记录新增/删除/修改操作、有效参数、mask版本、前一个实际候选与当前逐目标统计/残差、A基线、B观测、保护指标、视觉判断和反馈。每个C仍从原始A重放；轮间记录只作比较。保存搜索ledger，不把未编辑图像的阶段伪造为中间效果图。来源区分test_double、current_chat_offline、SAM3_cpu、PhotoCraft_cpu；轻量分割尚未执行。

初次trace回归发现实例化操作缺少id导致比较KeyError，已按原计划operation id明确绑定修复，并增加参数差异/删除、暂停append-only、实际报告与渲染索引测试。

父任务确认图像为前置人像；模型候选是MediaPipe SelfieMulticlass固定6类，优先脸部皮肤/头发/眼镜等保护/衣服/背景，不推断身份。当前SAM3调度确实硬编码；协议文档列出白名单backend、能力声明、cache隔离、统一回执、固定类约束与id0重映射的最小改动。未实现未核验的MediaPipe生产API，未下载权重或安装组件，也未换环境。固定face-skin不保证排除眼镜/牙齿，固定类不等价于开放语义。

真实迁移当前只缺：原图在执行环境可读，以及获批的轻量分割依赖/权重与实际适配。当前聊天已可通过files提供视觉回执，不再以必须部署新VLM服务作为阻塞；但必须先看到实际请求图像，不用假回复填补。

将准备一个单文件交接ZIP：指定基线与当前SHA、全部实际变更文件、完整patch、报告、运行说明、协议和Cargo.lock。不含二进制、构建缓存、凭据或用户照片。ZIP只是本地准备，只有官方单文件创建成功后才报告Library交付成功。旧独立报告Library ID不因ZIP创建而更新。

trace回归另发现输入失败捕获改变了旧冻结配置拒绝行为，已恢复：修改已冻结输入/配置继续抛错，不覆盖先前result；失败trace仍追加。输入首次准备失败则导出单例失败报告。恢复的渲染在每候选execution字段注明cached_completed_invocation，不当作新的实际后端执行。

此前445项全量回归针对真实后端补齐提交c0a201a；**不是新增聊天/trace代码后的全量结果**。本轮执行tool_retouch全部定向测试及已有hre CLI回归；本轮没有重跑整套engine/tests，最终数字与SHA另存verification/current-chat-trace-tests.json。

本轮最终代码 `41bec3058b74bd20ec29e0747c0231308009105a`：**79 项通过、0 失败（63.13秒）**，覆盖全部tool_retouch及已有hre CLI测试，显式启用实际PhotoCraft worker。当前聊天视觉回执及MediaPipe尚未真实运行。之后只改报告/日志并打包。

## 13 独立审查反馈的五项复现与修复

修复前交接SHA `313f34d14d321fa2a32e6e18094a423be2730e8a` 全量回归 **451通过、4条既有警告，385.86秒**；并行独立新增12个边界用例全部失败，证明此前全量通过未覆盖以下问题。复现期间未修改被测工作树。

1. 安全候选：content/naturalness/任一保护uncertain或native_inspected=false曾进入best_safe。现在safe_visual独立要求肯定安全证据；目标可未完全达成，但未知安全不能交付。无安全候选回退A并记录unconfirmed_safety。
2. 感知目标：原图视觉否定反馈曾丢弃，纯感知或数值已匹配时loss=0阻断候选。现在保留真实baseline视觉反馈，对被实际反馈判partial/unmet且计划分配了支持操作的感知目标允许预算内非identity候选；不伪造感知loss，不增加预算，已满足mandatory数值目标不可退化。原生安全、重放与逐目标视觉仍必须通过。未分配操作、或当前算子不支持的texture/noise诊断目标明确unsupported。
3. 窄区间：初始step改为max(width/4,min_step)，边界裁剪、identity/重复候选去重，保证合法非对称/窄范围仍有候选；保留identity起点、确定顺序、缓存和原预算。
4. 无关mask：原生接缝检查仅用实际非identity局部操作的effective mask，不受未使用catalog或identity局部操作影响。边缘指标比较候选梯度相对源梯度的超额，使用非mask边界处的中位响应增益，保留raw delta jump供审查；它是保守启发式，不是视觉光晕证明。测试覆盖未用mask不改变全局验收、identity mask排除、平坦区域真实局部阶跃拒绝、已有内容边缘的统一影调增益不过罚。
5. 交付证据：export、exported_native_acceptance、replay均有独立stage回执；导出后拒绝在continue前保存checks/targets，重放不一致在抛错前保存max_error/tolerance/pixel hash。异常也记录精确阶段，不只留泛化执行失败。

修复代码SHA `11ebb85bc8293c8975cdc875108f625962c6a5f5`：全部tool_retouch定向 **69通过（16.69秒）**，启用真实PhotoCraft。该提交全量因新增MPO范围主动中止：150通过、152.36秒，未完成，不能算全量通过；最终MPO代码将重新运行全量，不沿用451/445作为最终数字。新增15个回归用例（12个原问题复现+3个补充）仅验证控制/安全/证据路径，不证明真实照片完美迁移。真实模型与照片执行由父任务在已获批准的环境推进；本任务不迁移、不下载MediaPipe、不并行修改父任务分割后端。

下一交接ZIP改为完整受版本管理源码快照：包含engine全部运行/测试文件（含hre.storage和engine/pyproject.toml）、harness、configs、prompts、脚本、文本配置与文档，另附完整patch、SHA/哈希清单。排除.git、缓存、虚拟环境、构建二进制、权重、照片/凭据及无关大型docs静态图。原交接只有变更文件的限制已修正；不再要求父环境自行补齐缺失基线模块。

## 14 MPO primary-frame RGB输入支持

父环境实际发现iP17的1/7/19.jpg被Pillow13识别为MPO（8/8/2帧），旧代码因格式白名单拒绝。此为父环境实图观察，不冒充本环境已读照片。已增加MPO显式primary frame 0 SDR路径：保留原字节，读取frame0模式/EXIF/ICC，转正后实际ICC转换到sRGB；ColorContext新增source_format、frame_count、frame_index和frame_policy。辅助帧不读取为照片或linear RGB，不自动应用gain map/HDR/stereo合成。

仅支持RGB primary，MPO帧数限1..64；malformed MPO警告不允许Pillow静默退回JPEG解释，明确拒绝；异常容器/非RGB primary失败关闭。添加2/8帧fixture、方向/ICC/原hash/辅助帧隔离、超帧数、非RGB与损坏目录共5个回归测试。此前3项失败已复现（原非RGB拒绝已成立），修复后通过。此支持是格式边界，不声称已验证实际iPhone HDR重建。新增ColorContext字段改变冻结快照，旧运行不得覆写，应新建run。

最终源代码SHA `f7cc9855ab8e9f207434ed5cc46ffe8e8c71d6e7`。74项tool_retouch定向通过（提交后9.17秒）；包含五项核心修复及MPO。**同一最终源码的完整engine/tests为471通过、0失败、4条既有multiprocessing警告，435.61秒**。两次均启用真实PhotoCraft worker，期间源码与测试未变；随后仅更新文档/日志。完整源码包独立解包后CLI帮助及20项修复/MPO测试亦通过，不依赖原仓库补基线模块。仍不因此宣称完整实拍效果验收。

## 15 最终交接状态与证据分级

五项独立审查问题及MPO支持已复现、修复，最终源码f7cc9855的全量471/定向74通过；verification/review-mpo-final-tests.json记录具体命令、版本、耗时和真实worker哈希。修复前451和中止的150仅作历史基线，不能替代最终结果。

交接ZIP为git archive完整源码，明确含engine/pyproject.toml、hre.storage、所有运行/测试源码、harness分割接口、配置、prompts、文本文档及Cargo.lock；附相对指定stage的完整patch和逐文件哈希。只排除10张无关docs静态图，以及本来未受版本管理的缓存/二进制/权重/凭据/实拍输入。请保留父环境独立MediaPipe适配文件，勿用本快照覆盖其新后端工作。

Library同一交接文件 `[PRIVATE_LIBRARY_ID]` 已成功保存候选版本1，候选代码与最终测试源码相同；本地最终报告/日志更新后将替换该ZIP，最终版本/哈希以工具回执和任务消息为准。旧独立IMPLEMENTATION_REPORT Library ID仍未更新；最新报告在完整ZIP中。

完成：真实PhotoCraft CPU合成探针、接口/安全/预算/trace/MPO与回归、完整源码交接。失败历史：初始新增边界12项失败及MPO格式3项失败均已修复；中止全量明确未完成；本环境原图传输失败仍保留，不伪造成功。未运行：本环境真实Camera0717迁移、实际当前聊天视觉回执和MediaPipe。父环境独立执行的实拍/分割结果由父任务报告，不混入本环境通过数字。

## 16 感知晋升基准的窄范围复查修复

v2之后的独立复查发现，最新候选（即便更差/不安全）会降低下一候选的感知比较基准。已先复现三个序列失败：原图partial→safe/unmet→safe/partial、unsafe中间候选、当前best_safe被unsafe降低基准后同级候选取代。补充单轮原图partial→unsafe/uncertain→safe/unmet，以及safe数值改善但感知uncertain→下一候选感知unmet的序列。后者另复现失败，证明uncertain不能当更低效果等级。

生产修改仅workflow：保存独立baseline_visual；最新visual_anchor仍用于反馈规划，晋升改为比较best_safe.visual（存在时）或原图baseline_visual；uncertain从效果排序删除，前后任一感知目标未知均不据此声明感知进步。未改变数值目标、数值比较分支、既有协议或预算。当时五个新增回归均通过；随后补充原图unknown-resolution用例，最终共六个。

最小diff：verification/workflow_visual_anchor_fix.patch，针对v2交付提交3b5bdcd。最终源代码 `88847e9071805594fed5bff15db1ed1f53bd584a`；tool_retouch全部定向 **79通过（9.07秒）**，启用真实PhotoCraft worker。新的完整engine/tests正在该源码上运行；此前471属于v2，不能当本轮最终全量结果。中间运行因补充uncertain边界中止，不作为完整通过证据。

同一Library交接ZIP将先提供此修复候选，方便父环境立即应用最小diff；完整全量完成后仅更新日志和报告。父环境实拍结果仍由父任务记录。

## 17 Anchor最终验证与交接

最终源码 `ba9f5877910913a38d3072d1c2b1b2dc9c45af77`：**完整engine/tests 477通过、0失败、4条既有multiprocessing警告，413.89秒；tool_retouch定向80通过，14.26秒**。定向测试在提交前执行，提交的是相同源码/测试字节；全量在该提交运行，期间源码未改变，均启用真实PhotoCraft worker。证据在verification/visual-anchor-final-tests.json与对应日志，不能用旧471或中止运行替代。

六个anchor回归覆盖：原图partial→safe unmet→safe partial；不安全中间候选；已有best_safe不被后续更差/未知候选降低基准；单轮partial→unsafe uncertain→safe unmet；已有安全候选uncertain→unmet不算进步；原图uncertain→unmet（另一已知未满足目标实际触发候选）只记unknown_resolutions、不记quality_improved。新增perceptual_comparison trace区分未知消解与已知质量变化；未知状态不具有更低质量等级。

生产代码相对v2仅workflow.py发生变化：晋升基准与最新反馈分离、unknown不排序、独立比较回执；数值目标、数值比较分支、协议、预算及其余四项修复/MPO不变。最小补丁verification/workflow_visual_anchor_fix.patch针对v2；父环境已接入v3时可用workflow_v3_to_final.patch，仅补充明确比较回执。完整源码ZIP保持snapshot/与逐文件清单，更新同一Library文件，实际最终版本及哈希由工具回执确认；本段不预先宣称上传成功。
