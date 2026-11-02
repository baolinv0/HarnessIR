# Focused Qwen Reference Retouch Experiment: Direct A+B vs v1 vs v2

**协议**：`qwen-reference-3arm-pilot-v1`  
**日期**：2026-11-02  
**状态**：**PLAN_READY / NOT_RUN / NOT_FROZEN**（未运行真实模型；不是结果报告）  
**目标分支**：`codex/reference-unified-20261101`  
**范围**：固定一个真实、身份可核实的 Qwen 图像执行器；相同 A/B、相同一次生成预算；比较 Direct A+B、旧 `reference_retouch_v1`、新 `reference_retouch_v2`。重点评价**全图风格是否更接近 B，以及脸/肤色与背景是否被分别、正确地调整**。本计划是较大六臂研究之前的**诊断性小实验**，不替换既有 [EXPERIMENT_PLAN.md](EXPERIMENT_PLAN.md) 的预注册主试验。

> **核心判别**：新 v2 究竟提高了**最终生成图像的参考跟随与内容保持**，还是主要提高了**目标/提示完整性与失败识别**？三者必须分开量化。不能以 v2 内部 verifier 的 accepted 率作为跨版本优劣的主要证据。

## 0. 仓库实况与版本边界（必读）

| arm_id | 真实路径 | 代码中的关键设置 | 实验含义 |
|---|---|---|---|
| `D_direct_ab` | `hre models` 原生路径 | `strategy=native`，**不传** `workflow_contract` | A+B、共同 brief，**不经 Harness 诊断/目标规划**；仍会使用固定 Qwen 配置中的 native compiler / PE（不等于裸文本绕过 PE） |
| `V1_retouch_ab` | 旧 Reference Retouch | `strategy=model_aware`，`workflow_contract=reference_retouch_v1` | 八维差异、冻结合同、逐目标核验的旧 v1 |
| `V2_unified_ab` | 新 Unified Reference | `strategy=model_aware`，`workflow_contract=reference_retouch_v2` | 证据复核、最终指令审计、全图优先评价、统一反馈等 v2 |

**严格避免错臂**：现有六臂 `hre reference-study` builder 中的 `legacy_aware_ab` **不是** `reference_retouch_v1`，而是未显式选择参考合同的旧 Harness model-aware 路径。因此**不能直接拿六臂 Study 的三个相似标签替代本三臂实验**。本计划使用三个显式 `hre_task_v3` spec / case-root；所有输出在同一个**独立离线评估**下评分。现有 study 的冻结、盲评、评分导入可复用，但**当前没有现成“三臂 v1/v2 专项 Study builder”或下文统计一键命令**，需要实验工程师生成并审核清单、后处理。

此分支已提供 v1/v2 两套实现，优先**在同一 checkout** 运行，减少环境/版本漂移；同时记录 v1 实现与 2026-10-26 旧分支的代码 hash / golden 测试结果，不能只依据 schema 名称声称字节级一致。需要研究“旧分支真实运行结果”时，以第四个独立扩展实验执行并单独计账，不混入本三臂主表。

## 1. 科学问题与预注册假设

- **Q1：效果是否提升？** 相同 Qwen、相同 A/B 和一次图像生成调用下，V2 相比 V1、Direct 是否更常完成**正确的参考外观变化**，且不损坏 A 的身份/结构/真实细节？
- **Q2：区域控制是否提升？** 当 B 要求“肤色保持/小幅改变，但背景应改变”时，V2 是否减少“整张图统一偏黄/统一提亮”，并正确处理背景与脸的**不同方向或不同幅度**？
- **Q3：增量位于哪个环节？** 若 V2 生成画质没有改善，是差异诊断错了、目标或限制在最终条件中丢失了、Qwen 没执行区域要求，还是 verifier 漏检或交付门槛导致停止？

预注册主比较：**V2 − V1**。支持性比较：**V2 − Direct、V1 − Direct**。主效应是**独立盲评的有效参考编辑成功率**（定义见 §6），不是内置系统 `success`。区域差异/偏黄机制是核心次要终点。**不做训练、不更新权重、不引入新 Mask 执行模式、不让不同 arm 挑最漂亮的结果**。

可反驳预期：如果 V2 的最终条件更完整，但 A/B/C 的脸/背景差异没有比 V1 更合理，结论只能是“指令完整性/审计改善”，**不能宣称区域控制能力改善**。

## 2. 固定模型、数据域、生成与交付

### 2.1 Qwen 身份与公平性

当前仓库实际支持的 profile 是 `qwen21`（配套 Qwen Image 2.1 / PE-I2I），不是“所有 Qwen 版本”的通用别名。本轮默认将**仓库已实现的 `qwen21` 作为 M\***，但先核对服务器**实际**加载的编辑器权重 revision/hash、PE 权重、upstream helper commit、Qwen adapter、VLM endpoint 与推理参数。若现实目标是 Qwen-Image 3.0，则**先实现并验收相应 adapter**，以新协议版本冻结后再运行；绝不能仅把 `profile_id:qwen21` 改标签冒充 3.0，也不能用 2.1 的效果推断 3.0。

三臂锁定同一：`profile_id`、实际 image model checkpoint、PE/compiler backend（首选实际部署的相同 Qwen PE-I2I；若全改 `direct` backend 则另开实验版本）、VLM 权重与设置、设备、scheduler/steps/guidance/negative_prompt、输入格式、尺寸、`colour_policy`、`geometry`、`spatial`、输出选择规则。**允许的差异仅是 arm 的 Harness 策略、合同，以及随之产生的条件**。不同 arm 的文本阶段调用数不强行相同，但逐项记成本；“等预算”仅指**最多 1 次图像生成**。

每 `case_id` 使用 `policy={mode:"single",max_generations:1,seed_schedule:[<frozen_seed>],max_stage_calls:12,max_compiler_calls:1}`。同一 A/B 与 repeat 的三个 arm 请求同一个 seed 数值；如实际 editor/worker 不兑现 seed，则记录 `actual_seed=unknown`，两次是重复尝试而非可证明同随机轨迹。每条正式 run 的 `n=1`，不得隐式 retry、best-of-N、超时后免费重跑。诊断/VLM/审计被阻断、模型失败、输出缺失、预算耗尽和未知提交，都留在**原分母**中；不把无图算成画质零分。

运行前：
1. `python -m hre models doctor --config /ABS/RUNTIME.json --profile qwen21`；检查实际 backend、权重 manifest、真实模型 response 记录与可重复调用。
2. 冻结 checkout SHA、engine 子树 SHA、工作区 dirty diff、全部模型/PE/VLM 身份、runtime.json SHA256、Python/CUDA/diffusers/transformers、GPU、每个源码/输入的 hash、输出尺寸能力。
3. 针对 v2 的 `evidence_review`、`audit_condition` 若暂停，须导入**真实且绑定当前 hash 的独立审查**。不可在程序中填入伪造的 `pass`；对应阶段的人工/模型成本入账。
4. 预检输出原生分辨率。**不能以放大图、padding 或重采样后图像充当原生细节通过**。

### 2.2 A/B 输入域与统一工作尺寸

默认 A：**S26 linear 经既定 baseline 生成的 SDR 显示域 prediction**；B：同场景可能未对齐的 **iPhone RGB 参考**。若某图 A 是 `camera_rgb` 而非 `base_model_output`，必须事前分层并标明，不可混称“相同 Base 输入”。冻结 baseline 模型版本/权重与生成配置，B 不作为像素配准 GT。

若 M* 原生能力无法满足 A 原始大小：**先**离线声明统一 `working_size`，按照同一已记录流程把每个 A 制成 `A_work`、每个 B 制成 `B_work`，所有 arm 使用**完全相同字节**的 A_work/B_work；保留原始 A/B 和转换链 SHA、resize/pad 参数。首轮建议保持纵横比、最长边不超过实际 editor 支持的 1024 网格；**1024 只是候选，需 doctor + 真实模型预检确认**，不是已证实模型输出能力。优先使用 `geometry:{policy:"pad",grid:32}`、`spatial:{mode:"full_frame"}`，禁止仅给某个 arm 缩小脸、裁切背景或启用 crop/fuse。

正式评价声明为“**统一工作域上的 A_work → C**”，不能将其称作恢复原始 3000×4000 的全部细节。V1/V2 内置 `delivery_requirements:{require_native_source_resolution:true,require_detail_pass:false}` 对应同一 A_work；Direct 不传这个合同字段，但**离线强制相同 native 输出尺寸和可信内容门槛**。`require_detail_pass:false` 仅表示不让自动门槛在小实验中因无独立细节证明而阻断所有输出，**不表示细节已通过**；人类仍须对 native C 做放大观察并报告 pass/fail/unknown。如果预检时实际能 source-native，则可在**所有输出之前**另冻 `require_detail_pass:true` 的严格版本，禁止结果出来后改口径。

色彩：保存 ICC/色彩空间/位深/方向/色域与显示变换；支持时统一到可审计的 sRGB SDR 工作副本，分析用相同色度变换。未知编码仅允许披露条件下的视觉评估，不得输出正式数值色差结论。B 的不同视角、照明、材质造成的差异不可强制像素对齐。

## 3. 数据集、切片和避免筛选偏差

以**已知的 20 对真实 A/B**为默认候选池，先检查是否确有 20 个可用且独立的 source groups；如果不足，减少测试规模并记录，**不能复制同场景当独立样本**。不上传图像、路径中的个人信息、采集身份。

- **D_dev：4 个独立 groups**，仅检查环境、证据质量、输出尺寸、审计能否完成、独立评分能否执行。不用于最终效果判断。最多 `4 × 3 arms × 1 repeat = 12` 个生成槽。
- **D_test：16 个封闭独立 groups**，三臂每组 **2 次**（相同冻结 seed schedule），最多 `16 × 3 × 2 = 96` 个生成槽。组内顺序用冻结的 `ordering_seed=20261102` 平衡随机化；不同 arm 保持同场景临近运行，记录进程/时间/缓存。
- **M0 零编辑控制（附加）：4 个预选 A_work**，令 B_work=A_work 并明确“当前外观已满足”，`4 × 3 × 1 = 12` 槽上限；支持正确 no-op 时 v1/v2 的实际生成应为 0。它们与真实 D_test 重复 A，**不进入16组主成功率的分母**。
- **M1 同 A 换 B 的参考干预（附加）：预先选 4 个 D_test groups**，制作有文件 hash 的 B2（优先同场景经**明确、温和的确定性色调变换**获得的参考，事先保证不裁切、不改对象/照明结构；如用另拍 B2 必须完整核实可比性）。每 arm 再生成 1 次，最多 `4 × 3 = 12` 槽；原 B 端点用已经冻结的 D_test r0 记录，不重复扣费，也不把 B2 当真实 iPhone GT。先写下针对 B1/B2 的预期变化方向。

**总预算**：默认最多 **132 个首次图像提交槽**（12+96+12+12），减去真实 no-op 和生成前阻断；两个测试重复不能构成 32 个独立场景。先 D_dev，再锁完整 D_test 清单、盲评规则、原生规格、模型身份与计划 hash，随后才可开始主测试。

**四个预选的真实 D_test 切片（各 4 groups；若实际不存在，不人为凑假样本）**：

| slice | 典型 A/B 差异 | 关键反例 |
|---|---|---|
| S1 肤色基本合理、背景暖/偏黄有差异 | 背景需要变暖/降黄，脸应保持或小幅校正 | 把整张图统一加黄，脸偏黄 |
| S2 面部偏暗、背景已接近 B | 面部曝光/层次需要变化，背景应少动 | 整张图一起提亮，高光失控 |
| S3 混合光与宽动态 | 局部暖冷、阴影/高光关系不同 | 平均 WB 看似接近，整图自然度下降 |
| S4 色彩总体接近但局部关系残差 | 较少修改、保持自然肌理与图像色彩关系 | 过度美化/提亮/锐化或误判 no-op |

切片与标签**在生成前**由 A/B 的独立检查确定，每组记录全部八维的 targeted/preserve/uncertain/N/A、`comparability`、mandatory、具体区域、方向预测与不可比解释。四组分层数量是**目标配额**不是虚构已有数据事实：达不到时标记 sample shortage，不根据 C 调换图。D_test 不参与 prompt、阈值、权重或评价准则优化；调完仅能创建新 study revision。

## 4. 可执行三臂任务与命令

**三臂使用同一条冻结的“任务语义 brief”**，不把 V2 的审计规范和理想评价文字事先偷偷加给 Direct。建议：

> Use image A as the immutable source of identity, objects, expression, text, composition and authentic detail. Use B only for supported photographic appearance (overall tone, brightness, color, skin rendering and subject/background relations). Match the observable and comparable reference appearance; preserve content and natural detail. Do not copy B objects or invent detail. If already matched, preserve A. Return one image.

真正的提示差异应由各 arm 的正常 pipeline 产生；审查时保留所有**最终条件**、native PE 输出、hash、prompt 字符串和接口回执。

对**每一** `(group,repeat)` 复制完整的 `hre_task_v3` JSON，除三处 arm 差异之外其余相同。示意为（绝对路径须替换；`case_id` 每条唯一）：

```json
{
  "schema_version": "hre_task_v3",
  "case_id": "G01_R0_V2",
  "task_mode": "reference_enhance",
  "profile_id": "qwen21",
  "strategy": "model_aware",
  "workflow_contract": "reference_retouch_v2",
  "brief": "Use A for content and B only for comparable photographic appearance; adjust the supported tone, color, skin and subject/background relations. Preserve A identity, text, geometry and authentic detail. Do not invent content. If already matched, preserve A. Return one image.",
  "source": {"path": "/ABS/private/G01_A_work.png"},
  "reference": {"path": "/ABS/private/G01_B_work.png"},
  "regions": [],
  "geometry": {"policy": "pad", "grid": 32},
  "spatial": {"mode": "full_frame"},
  "colour_policy": "require_icc",
  "delivery_requirements": {
    "require_native_source_resolution": true,
    "require_detail_pass": false
  },
  "policy": {
    "mode": "single",
    "max_generations": 1,
    "seed_schedule": [2026110201],
    "max_stage_calls": 12,
    "max_compiler_calls": 1
  }
}
```

- **V2**：上例。若工作副本无 ICC，但转换过程已明确并归档 sRGB 编码，则统一将**所有 arm** 的 `colour_policy` 设为 `assume_srgb`，同时披露显式 sRGB 转换依据；`require_icc` 不能仅因图看起来正常而绕过。
- **V1**：将 `case_id` 改成 `G01_R0_V1`，`workflow_contract` 改 `reference_retouch_v1`，其它字段（包括 `strategy=model_aware`）保持一致。
- **Direct**：`case_id=G01_R0_DIRECT`、`strategy=native`，并**删除** `workflow_contract`、`delivery_requirements` 两个键（旧无合同路径不能接收后者）；其余保持一致。Direct 的外部目标/交付仍由公共离线评估强制执行。
- `regions:[]` 只用于最小示例。正式 S1/S2/S3 逐图按 A/B **各自坐标**加经审核的整脸、背景、相关材质证据框，或冻结无框时的证据缺失；Direct 虽不使用 Harness 诊断规划，输入 `regions` 字段可保持相同，但不得向其单独泄漏事后标签。八维**离线评价**保持一致，不能把 V2 内部预测当作所有 arm 的共同 GT。
- `max_stage_calls:12` 是**调用次数上限，不是要求各臂消耗相同**；如果 v2 因 VLM 审计/人工证据需要额外阶段，应事前提高三臂共同上限并形成新冻结版本，不能按结果临时加码。

以第一条为例（其余 case 按同样方式创建独立根目录；这是 CLI 实际支持的调用，不是虚构 batch 参数）：

```bash
python -m pip install -e "./engine[test]"
python -m hre models doctor --config /ABS/server-config/runtime.json --profile qwen21

python -m hre models create --case-root /ABS/runs/focused/G01_R0_V2 \
  --spec /ABS/specs/G01_R0_V2.json --config /ABS/server-config/runtime.json
python -m hre models dry-run --case-root /ABS/runs/focused/G01_R0_V2
python -m hre models run --case-root /ABS/runs/focused/G01_R0_V2
python -m hre models show --case-root /ABS/runs/focused/G01_R0_V2
python -m hre models report --run /ABS/runs/focused/G01_R0_V2 \
  --out /ABS/reports/focused/G01_R0_V2
```

`dry-run` 不生成图片；`run` 可能停在 `evidence_review` / `audit_condition` 等待真实独立审查。使用 `python -m hre models evidence-review-import --help`、`condition-audit-import --help` 和 `resume --help` 核对实际待处理输入，不写伪造侧车。真实未知提交使用 `reconcile` 根据回执处理，禁止盲重试。每条 run 的 `task.json/config.json/state.json`、最终 condition、native C、delivered C、审计链均冻结并归档。

批量自动化由工程师**新增一个不改变模型算法的 trial orchestrator**（或显式脚本循环），必须先生成所有 `3 × (group,repeat)` specs，逐个调用现有 create/dry-run/run/resume/show，并登记运行返回码；现有六臂 builder **不自动支持**这三个专有 arm。不得偷偷使用 `batch share_planning=true`，它会混淆 v1/v2 各自规划合同。

## 5. 区域证据：为什么“整体偏黄”可被真正测到

**评估区域 ≠ 编辑控制 Mask**：本轮不改变执行器的 `full_frame` 策略；脸/背景 mask/ROI 仅供测量和解释，以免把“新增 Mask 执行能力”与“更好的 Harness”混为一个变量。

输出前为 A、B **各自**冻结语义定义：`whole_face`（全脸，剔除背景/头发，禁止只取局部白净脸颊）、`background_material`（真实同类/同材质可比区域）、`neutral_anchor`（确实有可信中性材料才使用）、`whole_frame`。记录可见区域、遮挡、光源、色彩管理、B/A 的属性级可比性与 exclusions。生成之后单独验证 C 的对应语义区域；**不能默认 A mask 在 C 中仍像素精确，也不能强行用 B 的像素坐标套在 A/C 上**。脸/文字/物体重绘导致区域不可追踪时，记为内容风险和 measurement unavailable，而不是跳过失败样本。

对属性可比的整个区域，在相同可信 sRGB→Lab/D65 处理下，记录 robust 中位数 / 分位数：
- \(L^*\) 的面部与背景亮度、阴影/高光分位数及 `L_face − L_bg`（不是照度真值）；
- \(a^*,b^*\)、中性色偏色向量、可比材质的色度 C*，特别跟踪脸与背景的 **\(\Delta b^*\)**（偏黄方向）；\(\Delta E_{00}\) 仅作区域统计差异的**辅助解释**，不是未配准照片的逐像素 GT 分数；
- 各区域在 B 方向的变化是否匹配：\(\Delta b^*_{face}=med(b^*_{C,face})−med(b^*_{A,face})\)，\(\Delta b^*_{background}\) 同理；预先记录 B−A 的目标方向/可比限制。当背景应动而脸应保持时，优先检查 \(|\Delta b^*_{face}|\) 是否出现不应有的大漂移及背景是否按预期方向移动。
- 标准化距离仅在同一材质、光照条件允许时作诊断：\(\Delta d_R=d(C_R,B_R)−d(A_R,B_R)\)，负数表示区域统计更接近 B，**不自动表示修图成功**。若 B/A 不可比，记录 `not_comparable`，不填 0 或对数值强排名。

**主机制观测（每一输出均登记）**：`skin_over_yellow`（脸明显比 B 更黄）、`background_followed`（背景按 B 目标变化）、`face_followed`（脸按 B 目标变化/合理保持）、`global_unwanted_cast`（超出 B 的整图色偏）、`separation_preserved`（脸与背景影调/色彩关系合理）。每项取 `yes/no/uncertain/not_applicable` + 真实视觉/统计证据。只有通过两名独立评审的**整图与整区域判断**，才可下最终结论；局部 ROI 指标不得推翻全图严重偏黄的肉眼结果。

## 6. 独立、共用、分层评价（先整体，再局部，再数字）

在看任何 C 前，研究者以 A/B 锁定每组的：允许改变的全图六轴（tone/color/brightness/lighting naturalness/material relationships/processing appearance）、具体 mandatory 区域目标与方向、允许保持的维度、内容/细节保护项、不可比区域、`needs_edit` / `already_satisfied` / `uncertain` 基线。对于源图已经接近 B 的目标，**不改变**也可以算满足；不允许 v2 生成后放宽目标或拿 v2 的输出反推阈值。

1. **盲评第一屏：整张 A/B/C**。先给 2 名独立、未接触 arm/prompt/verdict 的评审，固定相同色彩显示与缩放，记录六轴相对 B 的接近程度、变化方向/幅度、过度编辑、自然度及 A 内容保护；不展示生成指令或局部数值。
2. **第二屏：整脸 + 背景 + 相关完整材质**。分别报告与 B 的可比目标是否达成、肤色与背景是否被错误同向改变、明显局部色偏、边缘/纹理失真和相邻区域关系；严禁以一块脸颊像素替代全脸。
3. **第三屏：原生 1:1 检查**。核对 A/C 身份、轮廓、表情、文字、毛发/纹理、伪造细节；尺寸与“真实细节保真”分别登记，放大 preview 不通过此关。
4. **第四屏：解释性 Lab/亮度/中性锚统计**。与先前评价出现冲突时保留冲突原因与缺证，并作独立裁决，不反向改写前面的全图观察。
5. 最后才揭露匿名 arm 映射，并检查系统内部 `whole_image_review`、逐目标 `verify`、`semantic_audit` 是否识别相同失败。**不能让生成模型自己当主要验收人**。

**主结果 `effective_reference_success`（每输出 1/0/unknown）**：该组输出前所有 mandatory 且**可比**的参考外观目标达到 / 已合理满足；预注册全图目标无显著非目标偏移；所需整脸与背景关系正确；无已知严重 A 身份/对象/文字/几何/真实细节损伤；满足共同的 native/交付规格。两名独立评审一致，或经预先指定的第三方裁决，才能定 1/0。缺图、无真实 native、评审未完成或重要不可比导致不能判断时记 **unknown**，绝不默认为 0 或从计划分母中删除。另报保守成功率 `confirmed_success / all_planned` 与 `confirmed_success / evaluable`，并将 unknown 率并列披露。

**与主结果分开**：
- 全图 B 风格跟随（六轴逐项 + 相对于 A 的更近/不变/更远）；肤色 vs 背景（逐区域 pass/fail/unknown）、整图偏黄与局部过黄频率；
- A 保护/严重损伤率、native 尺寸与细节不确定性、no-op 合法率；
- 系统自身的 accept/reject/uncertain、误接受严重问题、误拒绝优良输出、阻断/跳过生成率；
- Prompt 目标覆盖、最终 PE 条件语义覆盖、输入 B 是否实际被引用、额外阶段调用、GPU 秒、失败/超时/人工审查成本。

**不能以 v2 内置的“六轴全部 achieved”门槛直接判定 V1/Direct**：统一离线评审应只要求本 A/B **事前**标定的 mandatory 目标完成，并对非目标轴设置“不得显著恶化”的保护条件。三臂的生成图评判尺度完全一致。

## 7. 统计、报告与有条件继续

分析的独立单位是**16 个 source group**；每 group 的两次生成属于同一组重复，先归并（每 arm 的 confirmed 率 0/0.5/1，另报告 unknown/缺图），再对组等权。主效应为 \(\Delta_{21}=\operatorname{mean}_g(S_{V2,g}−S_{V1,g})\)，其次 \(\Delta_{20}\)、\(\Delta_{10}\)。报告每组配对结果、v2 wins/ties/loses、实际生成成功数、unknown、质量/保护/交付拆分；附按 group 成对 bootstrap 的描述性 95% CI（`analysis_seed=20261102`，10,000 次，保留组内两个 repeat），**样本量小，不以显著性或宽 CI 支持顶会级普适结论**。若 unknown 大量出现，再给所有 unknown 视为成功/失败的效应范围作敏感性分析。

**冻结后用于是否扩展六臂的工程 Go 建议（不是统计定律）**：
- V2 相比 V1 的独立盲评 \(\Delta_{21} \ge +0.15\)，且方向在 S1/S2（明确脸/背景差异）中一致；或 V2 质量持平但**已知严重错误 accept** 明显减少，且成本可接受——后一种仅批准继续验证“可靠性”，不宣称画质提升；
- 重大 A 损伤不多于 V1，且不出现新的系统性整脸偏黄；任何单例重大身份/结构破坏需要单独调查，不被均值掩盖；
- V2 的 audit/analysis 不得因缺证、审计不确定、尺寸预检而屏蔽大多数样本；两名评审对核心全图/脸背景结论分歧可被透明裁决；
- 若达不到，停止扩大实验，按 §8 排查；不能通过改 prompts、取消失败 case、额外抽样后仍用同一 study_id 宣称通过。

**预期解释范围**：本实验是三种**pipeline package** 对照。V2 不只是一个 Prompt 修改；整体差异不能因果归因到 evidence_review、whole_image_review 或 audit_condition 的某一单模块。确认机制需下一轮固定 V2 只删除一个模块的合法消融（不能破坏 frozen contract 或绕过安全审计；允许只在隔离分析环境产生原本被 gate 阻断的非交付草稿）。M1 干预 B 检验**整个系统**对参考输入的条件响应，不证明编辑器单独的因果贡献。

## 8. 失败定位：每个失败必须落到哪一层

| 位置 | 可观测证据 | 判定与后续 |
|---|---|---|
| 输入/参考 | 原始 A/B SHA、编码/亮度域、A/B 角色、区域可比性 | B 不可比 / 错配 / 错编码不能怪模型 |
| Diagnose / Evidence | 初始与复核诊断、八维 coverage、目标证据 | 没发现脸与背景不同目标 → **理解/诊断缺陷** |
| Freeze / Compose | frozen targets、限制、区域、mandatory、最终 prompt | 诊断正确但限制漏掉 → **规划/编译缺陷** |
| Qwen PE / Condition | PE native_output、最终 condition、真实 semantic audit | 目标存在但 PE 重写丢失 → **条件传递缺陷** |
| Executor | 相同 A/B、最后条件与真实 native C | 条件完整但全图偏黄/脸背景同改 → **模型执行或控制能力限制（待进一步机制验证）** |
| Verify | 两名盲评 vs 系统 pass/uncertain、全图/局部冲突 | 错误放行/拒绝 → **评价缺陷**，不是生成质量增益 |
| Delivery | 原生内容大小、输出 C 字节、细节证据、预检 | 拉伸/上采样/缺像素 → **交付缺陷** |

强制标注 `root_cause=confirmed/probable/unknown`，只有具备相关阶段真实输入/输出才能标 confirmed。参考材质、光线、构图不等价的样本标 `comparability_limited`；应更谨慎地报告，而不是硬要求颜色一致。**v2 停止生成是系统行为的事实，不等于它生成了更好的图像**。

## 9. 执行阶段与检查点

| 顺序 | 阶段 | 退出条件 | 若不满足 |
|---|---|---|---|
| P0 | 冻结 Qwen/PE/VLM、数据 hash、ICC、工作尺寸 | 真实部署 ready、3 臂合法 dry-run、native 能力已核实 | BLOCKED_SETUP |
| P1 | D_dev 四组，校准独立评分流程 | 全部处理链能留存证据；失败和 unknown 可统计；不调整 D_test | REPAIR_SOFTWARE / RE-FREEZE |
| P2 | 锁 D_test 16组、标签、目标与配对随机顺序 | 事前任务/评分/阈值/manifest SHA 全部可追溯 | NOT_FROZEN |
| P3 | 三臂 × 双重复真实推理 | 96 planned rows 无一遗漏；失败/暂停/无图原样保留 | BLOCKED / INCOMPLETE |
| P4 | M0 零编辑与 M1 双参考机制 | 24 planned rows 与主表区别报告；同组不能变独立场景 | MECHANISM_INCOMPLETE |
| P5 | 独立盲评、原生细节、Lab 与裁决 | 评审映射、样本顺序、分歧记录可回溯 | RATING_PENDING |
| P6 | 分析与科研判断 | 三臂并列、证据层缺陷、预算与下一步明确 | REPORT_INCOMPLETE |

按冻结上限执行，不把成功样例抽出来替换失败项。可在任何阶段停止以避免浪费 GPU，但必须保留未运行的计划行与拒绝/失败原因。

## 10. 工程交付物与报告模板

在 GPU/私有存储保存：
- `FROZEN_MANIFEST.json`：全部 groups、source lineage、A/B_work SHA、slices、目标/区域可比性、盲评协议、运行矩阵、seed、模型、runtime、版本和预算；
- `SPEC_LEDGER.jsonl`：每个预计划 row 的 arm、原始 spec、case_root、种子、状态及所有调用（无图同样有一行）；
- 每次 `hre models` 的 state、初始/有效诊断、evidence、frozen targets、最终 native condition、PE、semantic audit、native C、delivered C、审核、反馈、人工独立评分及 SHA；
- `RATINGS_BLIND.jsonl`（评审输入不包含 arm 名）与解盲映射单独保存；所有评价冲突和裁决记录；
- 视觉板（A、B、三臂 C；全图为主、整脸/背景次之、1:1 native 细节）+ 每个 group 的表；不得只挑成功图。

**最终唯一报告**：`FOCUSED_QWEN_V1_V2_REPORT.md`（可内嵌缩略图，native 大图留有真实可访问且 SHA 可验证的证据路径；如果图片尚未持久保管，标 EVIDENCE_INCOMPLETE）。报告必须具有这些固定标题：

```markdown
# Focused Qwen Direct vs v1 vs v2 — Experiment Report
## 0. Status / Frozen IDs / Actual model provenance
## 1. Data groups and slice coverage (planned vs actual)
## 2. Budget, calls, failures, paused and unknown submissions
## 3. Primary paired quality result: V2-V1 / V2-Direct / V1-Direct
## 4. Whole-image tone/color/brightness and reference fidelity
## 5. Face vs background: over-yellow, exposure, local relationships
## 6. Source preservation, native resolution and detail
## 7. Diagnostic → final condition → executor → verification trace
## 8. No-op and B-swap interventions
## 9. Blind ratings, conflicts, adjudication, descriptive uncertainty
## 10. Cost, limitations, mechanism hypotheses and next experiment
## Appendix: Complete planned ledger + per-case results + visualization index
```

核心结果表必填（即使结果未知，也要填写 `NOT_RUN/unknown`）：

| Arm | Planned | Generated | Confirmed success / all | Whole-frame closer | Skin correct | Background correct | Global unwanted yellow | Major A damage | Native gate | Stage/compiler/image calls |
|---|---:|---:|---|---|---|---|---|---|---|---|---|
| Direct A+B | 32 | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |
| Ref Retouch v1 | 32 | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |
| Unified v2 | 32 | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |

> 上表 `Planned=32` 仅针对 16 个 D_test × 2 repeats 的主测试，不包含 D_dev、M0、M1。计算组级效应时仍以 16 个 group 为独立单位。无模型执行就不能填实际质量数据；系统日志/脚本的成功状态不能替代盲评。

## 11. 质量门槛与审查清单

1. **执行路径审计**：三条 task spec 能被 `normalise_spec` 接受；Direct 没有 `workflow_contract`；v1/v2 分别命中对应的 selector；3 臂都为同一确证 Qwen 与 compiler backend；保留所有 final condition。
2. **数据核对**：每个 `(group,repeat)` 的 A/B SHA 三臂一致；原始 A → A_work 与 B → B_work 可追溯；真实 paired vs synthetic B2 清楚区分；测试集的分层先于结果。
3. **调用真实性**：实际返回的 `request/response/native SHA` 可核对；v2 等待审计不是 pass；超时/未知不自动重试；no-op 0 calls 有实际证据。
4. **独立评价**：无 arm/prompt/verifier 泄漏；评分顺序全图→整区域→数值；评价规范在生成前冻结；两评审分歧与裁决原样保留。
5. **科研结论一致性**：不把 V2 规则更严格当画质好；不把 ROI Lab 小差异当同场景未配准参考的 GT；不把重复 seed 当独立 N；不把 M0/M1 加入主 N；不把通过测试当 GPU 实验完成。
6. **未完成项显式列出**：若没有真实部署确认、独立盲评、native 图像或区域支持，则对应效果结论是 **UNKNOWN / NOT_RUN**，不可填优秀数字。

## 12. 下一轮决策树

- **V2 画质与区域正确性提升**：以这个实验为 pilot，进入较大 [六臂计划](EXPERIMENT_PLAN.md) 的独立留出验证，扩充场景与模型；再做关键模块消融。
- **V2 检测更好但出图无改善**：保留 v2 审计/评测骨架，将研发集中在**Qwen 的区域执行能力**：先诊断 native condition 是否包含“脸保持、背景修改”的分离指令；再单独设计 mask / region-conditioned / crop-and-fuse 的**新 arm**，不要将其混进本轮 v2。
- **Direct 更好**：审查 Harness 是否过度约束或改写了本来有效的 Qwen 编辑条件；逐层追踪 Prompt、PE、图像和验收边界，先查 execution suppression。
- **三者均失败**：优先检查 A/B 可比性、输入域、Qwen 部署与当前任务能否由该 executor 完成；不能通过增加更多 Prompt 限制或隐藏失败解决。
- **结果主要 unknown**：补齐真实证据/评分/尺寸后重开冻结实验；不要将未知当失败或成功去制造优势。

## 参考实现（固定仓库路径）

- [v1 原生任务示例](../../../engine/examples/reference_retouch/reference.example.json)
- [v2 新任务示例](../../../engine/examples/reference_unified/task.example.json)
- [模型部署、native/shared/model-aware、区域与命令](../../four_model_v3/RUNBOOK.md)
- [v3 task/预算验证](../../../engine/src/hre/v3/contracts.py)
- [Reference v1 校验](../../../engine/src/hre/v3/reference_retouch.py) / [v2 校验和阶段指令](../../../engine/src/hre/v3/reference_retouch_v2.py)
- [统一 whole-image gate](../../../engine/src/hre/reference_core/holistic.py)
- [统一六臂完整实验计划](EXPERIMENT_PLAN.md) / [新运行手册](../RUNBOOK.md)

**本文件为可执行的研究协议与工程交接，不声称已部署真实 Qwen、完成推理、验证任何性能提升或生成实验数据。**
