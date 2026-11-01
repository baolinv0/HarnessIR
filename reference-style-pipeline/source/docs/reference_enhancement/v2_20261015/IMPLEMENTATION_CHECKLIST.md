> 本文件保留 PR #3 的设计/预注册基线。实际实现、命令和验证边界见 [RUNBOOK.md](RUNBOOK.md) 与 [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)；真实 R1/R2 尚未运行。

# HarnessRefEnhance v2 — 工程实施清单与验收合同

**基线**：PR #2 的 feat/reference-enhancement-v1；**交付意图**：仅增量支持生成式 G0/G1/G2，保留 v1 和原恢复入口。**此文档是后续工程任务，不代表代码已改。**

## 0. 实施次序（不得绕过真实能力核查）

P0-A：保持 G0/G1 双图链可运行 → P0-B：支持可信的冻结 ROI 与 A/B/C 属性报告 → P0-C：检验生成端能力并条件启用 G2 → P1：完整 3–5 对 R1 → P1：12 对 R2 → P2：反馈重试与规模化。

不必为了第一轮验证直接接入所有 T1–T4。T4 分割可离线预计算并按原本 hash 契约注册；无可信 mask 的样本可以只用人工 ROI，不能把空分割识别结果伪装为“无物体”。新增 Mask Editor 时切勿修改原 v1 two-image requirement。

## 1. 交付任务分解

| ID | 涉及模块 | 具体修改 | 验收 |
|---|---|---|---|
| V2-01 | engine/src/hre/experiments.py + 新 v2 config | 新建独立 G0/G1/G2 profile；保留 v1 profile、已有 experiment freezing 和旧 CLI 默认 | v1 298 项回归继续通过；v2 三臂生成 cap=1；未经资格证明 G2 不运行 |
| V2-02 | engine/src/hre/capabilities.py + desktop.py | mask-capability 独立探测与版本冻结；区分 native_mask_parameter、separate_mask_image、untested；严格存实际递送 payload 及 A/B/M 输入顺序 | 没有本次 Executor probe 时 G2 为 skipped_capability；错误 mask/反相/版本不匹配被拒绝 |
| V2-03 | evidence.py + tools (T4) | 将 T4 A 语义结果转 EVAL_MASK / 可选 EDIT_MASK；保留模型/权重/预处理/hash/coords；手工 mask 同样审计 | 缓存错 A SHA、错尺寸、错 role、过期模型、错 target ROI 不能误命中 |
| V2-04 | prompts.py + resources/prompts | G1 短文本模板只写 1–3 个证据支持的 rendering 目标；G2 使用完全同字节的 G1 Prompt；每臂各自冻结 | 不出现“保持 A 原曝光/颜色”的逻辑冲突；G2 不得另写更强指令再对比 G1 |
| V2-05 | 新 reference_evaluator.py + roi.py/stats.py | 对固定区域计算 A/B/C Lab L*/a*/b*、显示亮度分位数、clip 与局部 spill；提供区域独立 masks | 不可比 ROI、near-zero baseline、NaN/空 ROI、非对齐不产生伪造分数；输出 delta 定义一致 |
| V2-06 | workflow.py / selection.py | v2 选择仍需内容保真；第一次输出规范及预算幂等；新属性 evaluator 独立于流程 verifier | ROI 好但改掉文字/脸不得 success；任何超预算候选不得候选排名 |
| V2-07 | experiments.py / reporting.py | 增加 G0/G1/G2 比较表、mask eligible 计数、ITT、paired win/tie/loss、failure reason、操作时间和未知成本 | 每个计划 case/arm 都有 planned 或结果；失败保留；G2 仅和同 Executor 的 G1 配对 |
| V2-08 | ui.py + CLI | 展示 A/B/C 及 ROI、mask 预览，显示 EDIT_MASK 真正送达的模式/版本/能力和是否仅软引导 | UI 不会将 unknown capability 显示为支持；不能以人工勾选越过 mask/身份校验 |
| V2-09 | docs 与测试 | 运行手册、Schema 示例、最小样本清单、运行日志、能力探针证据、迁移说明 | 新环境能从零完成 R0 和首对 G0/G1，G2 条件性运行，不覆盖既有 Data |

建议将 v2 Schema/Config 放在新的命名空间，例如 engine/src/hre/resources/v2/ 与 docs/reference_enhancement/v2_20261015/；所有存盘协议带版本号，不通过可选新字段悄悄改变 v1 输入合同。

## 2. 新的最小文件合同（示意，不是已实现 Schema）

~~~
case/
  originals/                 # A、B 原件与 SHA
  canonical/                 # A、B 冻结 SDR / 色彩假设
  annotations/
    roi_pairs_v2.json        # 标注于看到输出前
    eval_masks/              # A 侧目标/非目标区域
    edit_masks/              # G2 可选条件；含 mask source/encoding
    mask_contracts.json      # 独立 mask provenance/角色/adapter 语义
  profiles/                  # G0/G1/G2 与固定评价版本
  tasks/
    G0/editor/               # 恰好 A.png B.png edit_prompt.txt
    G1/editor/               # 恰好 A.png B.png edit_prompt.txt
    G2/editor/               # 仅经 mask probe 后，按特定 adapter 合同生成
  candidates/                # raw C、实际返回、输出顺序/生成次数
  evaluation/
    roi_attributes.json      # 每个 ROI: before, after, delta, status
    content_checks.json
    blind_ratings.json
  report/
    case_summary.json
~~~

**注**：上述仅为 v2 目标布局，不能当作当前 PR #2 的已存在目录或可直接运行命令。真实代码实现时应复用已有 CaseStore、request、dispatch、done 和 journal 机制，而非自建第二套状态源。

## 3. 能力探针必须记录的字段

- executor_id/model_display_name/model_exact_version(if observable)/transport/pipeline_version/adapter_version；
- accepts_A_and_B、accepts_mask、mask_mode、mask_encoder、mask_applies_to_first_image、allow_edit_semantics、mask_size_rule；
- real_command_or_UI_steps、input_order、prompt_sha256、mask_sha256、A/B pixel_sha256、start/stop、raw_response_artifacts；
- pass/fail/untested、proof_file_sha256、probe_env；版本变化要求重新 probe。

至少做 2 个真实局部编辑 probe：简单背景区域与含细边缘/高对比交界区域；还要做一个不应改变区域的负例。人工确认 mask 真正送达、指向 A 而不是 B，且没有把彩色 Mask 当风格参照。此能力测试不代表局部增强画质已合格。

### 3.1 关于 Qwen-Image-2.1

官方公开示例包含**原图 + 单独 mask 图片**，但是否能在项目使用的 ComfyUI/Diffusers/自建适配接口中，同时携带 A+B+Mask 并保持 A 为编辑底图，必须真实核查。单图局部编辑能力≠双图参考局部增强能力。不能写死假定存在标准独立 alpha-mask 参数；该类型若只是多图语义提示，应标 separate_mask_image / soft guidance。若不可满足，则该 Executor 暂不支持 G2。

### 3.2 关于 ChatGPT 桌面

现有 v1 仅约束 A+B+Prompt 并以人工交接为有效通道。即便 GPT Image API 有 mask 参数，也不能据此认定桌面 UI 的两图编辑支持原生 mask。ChatGPT 桌面如实测没有独立 mask 控制，就只用于 G0/G1；G2 skipped，而不是人为上传彩色 overlay 来冒充正式 Mask。

## 4. 测试矩阵（可写成工程单测）

| 编号 | 输入/故障 | 预期 |
|---|---|---|
| T-01 | v1 case 导入/冻结/输出 | 行为无变更，不需要 v2 字段 |
| T-02 | G2 未探测 capability | fail_closed / skipped_capability，0 已确认图像生成 |
| T-03 | mask 像素尺寸与 A 不匹配 | 拒绝，不能自动 warp/crop |
| T-04 | mask 角色指向 B 或交换 A/B | 拒绝并留审计证据 |
| T-05 | mask 反相/编码未声明/不匹配 | 拒绝，不猜测白/黑/alpha 语义 |
| T-06 | segmentation overlay 以普通彩色图冒充 EDIT_MASK | 拒绝 |
| T-07 | G2 Prompt 与 G1 SHA 不同（无冻结、无声明） | 不能进入 H2 同变量对照 |
| T-08 | 同场景、异大小 A/B ROI 坐标 | 按各自标注计算，无像素配准假定 |
| T-09 | A/B ROI 不可比或未标注 | invalid/not_assessable，不算成功/失败参考距离 |
| T-10 | A/C geometry fail | 不进行可解释 ROI 距离，内容风险保留 |
| T-11 | A/B 原本属性距离近零 | 绝对值可报，相对收益标不适用 |
| T-12 | G2 正确改善 ROI 但发明文字/纹理 | 内容 gate fail，不能进入正式成功 |
| T-13 | G2 mask 外颜色明显漂移 | spill 升高，不能据目标 ROI 改善忽略 |
| T-14 | G1 局部任务没有消费 mask | 仍可用同冻结 Eval Mask 离线计算 spill，保证 H2 公平 |
| T-15 | 旧 mask 缓存 SHA 相同但模型版本/预处理不同 | 不可命中 |
| T-16 | 用户中断/恢复、重复导入、后台已知重生成 | 预算/日志幂等，未知提交暂停不再次自动提交 |
| T-17 | 两审稿人分歧、缺评审/候选 | unresolved/unknown，ITT 中保守不算成功 |
| T-18 | 更改 prompt / ROI / mask / model 参数 | 新 revision + 新 hash，不修改已冻结案例 |

还需 3 个有人工预期的微型 RGB8 合成 fixture（平坦墙、两区不同颜色、局部亮度差）验证属性公式的方向与数值，避免在真实图上临时校准数学实现。该 fixture 只证明指标实现，不证明图像模型效果。

## 5. 各阶段交付要求

**M0：版本隔离+回归**：能在新 checkout 运行现有 v1 CLI、合成演示和测试，v2 处于禁用；记录锁定环境。禁止因 PR #2 与 main 分叉直接把 main 的 engine 目录覆盖到新分支。

**M1：G0/G1 + A/B/C ROI**：新增 v2 profile、prompt 记录、参考属性评价，在真实一对 A/B 上保存 G0/G1 两张 C + ROI 解释；完成后可决定是否需要 G2。不要把 v1 synthetic pass 当真实效果。

**M2：G2 capability + mask**：选择一个允许且真实支持双图+mask 的执行器，probe 原生模式，完成真实局部 edit 后才能修改 G2 状态为 supported；保存失败、混淆、渗色/边界观察。模型或接入改变需重新 probe。

**M3：R1 小样本**：3–5 对，每臂一次、保存 raw/盲评/属性报告；全部关键失败可追溯。只有 G0/G1 或 G2 真正有可信收益，才进入下一步。

**M4：R2 Pilot**：12 对，按 EXPERIMENT_PLAN.md 的预算、随机顺序和独立评价冻结结果。GO/PROBE/STOP 必须有失败例和反例支撑，不能仅附漂亮视觉案例。

## 6. 对工程师的交付边界

- 本次文档 PR **只新增实施方案和实验计划**，未完成 M0–M4，也没有取得任何真实 G0/G1/G2 输出。
- 实施前首先拉取 PR #2 对应基线，并检查它与 main 的冲突。**新代码应在新 PR 中提交**，不得直接改写本次冻结的文档实验结论。
- 外部编辑服务、图像模型运行、GPU、桌面能力均应明示来源及权限；没有模型连接时不得虚构已经通过的 probe 或结果。
- 追求项目的产品性价比，先验证 G0/G1；只有 G1 确有差别、局部 Mask 潜在需求充分，才让工程师投入 G2 对接。不要让 mask 的工程复杂度取代研究问题本身。
