# HarnessIR Candidate Generation：工程专项实施规格 v1.1-CG

> 2026-11-19 现行质量评估规格为 [QUALITY_EVALUATION_PLAN.md](./QUALITY_EVALUATION_PLAN.md)。J3 异构专业证据加 VLM 终审是研究主方案。本文 J1 默认、J2 专家、旧评价预算与旧实验评价条款仅保留为历史背景，冲突时以新规格为准。候选生成和执行合同仍有效。设计合同不是已实现或实测结论。

> 日期：2026-11-17  
> 评审修订：2026-11-17。与主规格的逐属性资格、ReviewPlan、完整请求冻结、独立几何及 E2 预注册合同同步。  
> 状态：待实现的工程规格，不是已运行的代码或实测效果。  
> 仓库：baolinv0/HarnessIR  
> **候选生成与执行主规格**：[IMPLEMENTATION_PLAN_V1_1.md](./IMPLEMENTATION_PLAN_V1_1.md)  
> 历史基线：[IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md)  
> 本文件范围：**只细化 Candidate Generation（C0 → 缺陷诊断 → 策略规划 → Prompt 改写 → CF/CT/CFT → 策略效果分析）**；保留主规格已经确定的 Judge、Evidence、运行协议和离线评价，不另起一套 Judge。
>
> **规范优先级**：质量评估、Judge 与相关实验以 QUALITY_EVALUATION_PLAN.md 为准，候选生成和执行以系统主规格为准。不得自行引入新候选数量、新生成模型或新的选择政策。

## 0. 工程师执行摘要（必须遵守）

1. 保留现有 HarnessIR 的 Diagnosis → Tools → Composition，得到原始完整 Prompt **P0**；先从原始 LQ 执行 P0，生成 **C0**。C0 是后续策略规划的观测依据，不是后续图像生成输入。
2. **先发现 C0 的实际缺陷，再定义干预**。人物蜡感、人物过锐、文字欠恢复、文字错字等不能统一映射成“更强生成”。每条候选改动必须可追溯到 Issue 和证据。
3. 两个有依据的策略轴：**F（人物）**、**T（文字）**。典型混合场景四槽为 C0 / CF / CT / CFT；仅有一种或没有明确问题时，按本文件的确定性槽位规则使用 baseline resample，不编造策略。
4. CF 是 **仅改变人物相关语义要求**的完整 Prompt；CT 是 **仅改变文字相关语义要求**；CFT 同时采用相同的 F/T 两种替代策略。**语义正交不意味着输出像素正交**；四个结果都是整图生成，必须检查非目标区域。
5. P0 的全局任务、输出几何、人物/文字已知内容、其他区域与保护要求继续有效。Rewrite 采用**需求解析 → 作用域替换 → 完整 Prompt 编译 → 独立语义审计**；不能自由重新写一篇 Prompt，也不能将矛盾指令直接追加在末尾。
6. Qwen 第一轮固定单一模型、revision、steps、CFG、dtype、几何、后处理；PE=off、color_adjust=off。源图均为冻结的同一 LQ，随机性来自冻结的 seed schedule。实际送入执行器的文本和源图必须与冻结哈希一致。
7. **两个冻结点**：F0 在 C0 之前冻结任务、模型、候选分配算法、预算、seed 与评价政策；F1 在生成 CF/CT/CFT 之前冻结各 Issue、区域、策略、完整 Prompt 和回退策略。看到候选结果后不能更改计划加抽。
8. Code 可以因文件、来源、几何、请求/证据绑定等**确定性错误**排除候选；锐度、OCR confidence、LR consistency、NR-IQA 等软证据不能预先淘汰候选。Judge 保持主规格的 **Eligible → Listwise Best / Unresolved**。
9. 在线 Planner、Rewriter、Judge **不得访问 GT、人工真值或离线评分**。独立离线人工/GT 评估只用于确定研究结论。
10. 第一轮不做硬 Mask、局部裁图融合、跨模型路由、专用人脸/OCR 生成器、PE、训练、RSI、自我迭代或动态扩展生成预算。

## 1. 问题定义：Candidate Generation 究竟回答什么？

核心假设 H-CG：**相同图像生成预算下，利用 C0 的缺陷证据选择针对性恢复策略，比继续对 P0 做随机采样，更容易生成至少一个可接受候选。**

这与“用 Judge 从已有候选中选最佳”不同：

| 子问题 | 决策/测量方 | 输出 |
|---|---|---|
| C0 在什么区域失败？ | Planner（LQ+C0+Evidence） | IssueRecord，带依据和替代解释 |
| 该改变哪个恢复策略？ | Strategy Planner | F/T 干预及保护条件 |
| Prompt 是否只改变允许作用域？ | Rewriter + 独立 Audit | PF/PT/PFT + 完整语义差分 |
| Qwen 是否响应了改动？ | **离线**固定 seed / ROI 对照 | Target Response |
| 非目标区域是否受到破坏？ | 候选 Judge + **离线**区域分析 | Off-target Damage |
| 候选池是否包含合格结果？ | 独立人工/GT Oracle | Oracle Pass@4 |
| 最终能否选中？ | 主规格 J0/J1/J2 与终审 | Selected Pass |

**严格区分**：Observation（观察现象）、Cause Hypothesis（可能原因）、Intervention（主动改变）、Expected Effect（可观察预期）。Planner 可以提出原因假设，但不能根据一次 C0 直接证明 Prompt 是根因；也不能因为 C0 很模糊就认定输入缺少全部信息。

## 2. 模块边界与端到端流程

~~~mermaid
flowchart TD
    A["F0：冻结任务、政策、模型、几何、预算、seed"] --> B["原始 Diagnosis → Tools → Composition"]
    B --> C["冻结 P0；相同 LQ → Qwen → C0"]
    C --> D{"C0 是否生成且契约有效？"}
    D -->|否| X["baseline_failed；记录并停止反馈规划"]
    D -->|是| E["观察 LQ/C0，生成 IssueRecord + ROI"]
    E --> F["按关键性/证据/可执行性选择最多两个问题轴"]
    F --> G["选 F、T 替代策略及 fallback 槽位"]
    G --> H["P0 → 需求 IR → PF/PT/PFT + Semantic Audit"]
    H --> I["F1：冻结 CandidatePlan / 全 Prompt / Hash"]
    I --> J["从同一原始 LQ 执行 CF、CT、CFT"]
    C --> K["四候选池与绑定 Code Evidence"]
    J --> K
    K --> L["固定 Judge：Code Hard Gate → VLM Eligible → Best"]
    K --> M["离线策略研究：Target / Off-target / Joint"]
~~~

### 2.1 代码职责

| 模块（拟新增） | 仅允许的职责 | 禁止的职责 |
|---|---|---|
| engine/src/hre/candidates/contracts.py | Schema、严格验证、状态枚举、冻结对象 | 运行模型或计算最终质量评分 |
| engine/src/hre/candidates/planner.py | Issue 识别、排序、策略分配、Rewriter、Audit | 私自生成图像、读取 GT、看到 CF 后重新规划 |
| engine/src/hre/candidates/bridge.py | 复用原前三阶段、精确请求编译、Qwen 调度与回执 | 自行改 Prompt、替 Planner 选策略 |
| engine/src/hre/candidates/evidence.py | ROI/Hash/测量/匿名证据包，区分硬/软证据 | 用软分数提前淘汰候选 |
| engine/src/hre/candidates/runtime.py | F0/F1、预算、状态机、日志、幂等恢复 | 未授权追加候选、unknown 时直接重发 |
| engine/src/hre/candidates/judge.py | **完全采用主规格定义**的 J0/J1/J2 与 Adjudicate | 重定义新的选图政策 |
| engine/src/hre/candidates/report.py | 逐图与批量结果、离线策略效应与错误归因 | 将 GT/Oracle 回流在线模块 |

新模块只增加独立 candidates CLI 入口，不把候选伪装为原 harness 的 redo 轮次；不得破坏现有 SR v0.2 和 reference 等运行路径。

### 2.2 输入前置条件

- LQ 必须是可解释的 SDR 8-bit sRGB/ICC 图像，预先执行 EXIF 方向规范化；原始输入字节与规范化像素都需记录身份，不能静默将长边缩至 1024。
- 支持 restoration_x1 和 sr_x4 两种独立几何任务；RAW、HDR、透明输入若需要转换，必须显式另建数据处理记录，不能混入直接测试。
- F0 冻结 TaskSpec、EvaluationContract、模型与权重 revision、steps/CFG/dtype、PE/颜色处理、seed schedule、候选分配规则、预算、tie_order。
- 原始 diagnosis 与 tool evidence 按旧接口读取。工具缺失时记录 missing，而不是假装无问题。
- C0 必须生成成功并满足**可确定的契约要求**，才能执行依赖 C0 的反馈式规划；若失败则 baseline_failed，不能换一个挑选过的 C0。

## 3. IssueRecord：从 C0 观察变成可审计的研究问题

### 3.1 Schema（示例，字段名为新增拟实现合同）

~~~json
{
  "schema_version": "hre_candidates_v1",
  "issue_id": "F01",
  "region_ids": ["person_01_face"],
  "domain": "person",
  "problem_type": "waxy_skin",
  "severity": "major",
  "task_criticality": "high",
  "observation": "C0 face appears excessively smooth relative to visible structure",
  "source_evidence_refs": ["lq_roi_face_01", "c0_roi_face_01"],
  "cause_hypotheses": [
    "P0 may suppress texture too strongly",
    "Qwen may have an inherent smoothing tendency"
  ],
  "alternative_explanations": ["visible input cues may be insufficient"],
  "desired_change": "recover subtle natural skin texture",
  "protected_attributes": ["expression", "visible facial geometry", "skin color"],
  "expected_observation": "reduced waxy appearance, no major structure regression",
  "support_status": "supported",
  "intervention_feasibility": "plausible",
  "spatial_control_risk": "low"
}
~~~

最低必需字段：issue_id、region_ids、domain、problem_type、severity、observation、source_evidence_refs、alternative_explanations、desired_change、protected_attributes、expected_observation、support_status。cause_hypotheses 不等于已证明原因；可为空。

约束：support_status ∈ {supported, ambiguous, unavailable}；intervention_feasibility ∈ {plausible, limited, unsupported}；spatial_control_risk ∈ {low, medium, high}。任何字段的 VLM 自报数值置信度都**不当作校准概率**。严重度和任务关键性是用于审计的有序类别，不当成不同图像之间可比较的绝对质量分数。

### 3.2 Issue 发现与优先级

建议按以下确定性决策次序执行，不使用不透明的“总分最大”：

1. **任务关键错误优先**：可见人物结构/表情改变、已确认错字、主要主体严重欠恢复、严重伪影，优先于轻微观感差异；未支持的断言不能直接升级为 confirmed content conflict。
2. **可见证据优先**：有对应 LQ/C0 同坐标 ROI 与可解释工具证据；证据不足则标 ambiguous/unavailable，不伪造直接原因。
3. **可操作干预优先**：必须能提出与 P0 真正不同且符合执行器能力的改变；“make it better”不算策略。
4. **可观察验证优先**：能够规定目标属性与非目标保护条件，并评估是否出现方向性响应。
5. 同级时以 F0 冻结的稳定 ROI 排序、任务重要性、issue_id 作为确定性 tie-break，不让生成后验结果影响规划。

Planner 第一轮最多选择两个有根据的问题轴；保留未处理问题列表及理由。不能因为有四个槽位就虚构两个缺陷。

### 3.3 ROI 注册表

每个 ROI 以 EXIF 规范化后的 **LQ 内容坐标**为准：[x0, y0, x1, y1)，右下端点不含；记录 id / semantic_type / importance / box / provenance / availability / key_attributes。

优先采用已有 detector 或合法人工 ROI；必要时 Planner 提议，但记录来源。Pilot 人工校正 ROI **仅可观察 LQ**，不得根据候选优劣移动 ROI，更不能看 GT 来选择在线 ROI。默认每个主图像包最多 6 个主要 ROI，人和文字各最多 3 个；这不是全场景重要实例的总上限。超限按主规格 §8.6 的 ReviewPlan 拆包。必需 ROI 未完成评审时，相应候选为 undetermined，不能仅标 coverage_incomplete 后继续交付。位移时使用相同坐标框加上下文并显式报告位移；不能追着生成结果新位置重新选框。

## 4. 候选策略库（v1 第一轮为受控目录，不是自由 Prompt 搜索）

### 4.1 人物轴 F：Face / Hair / Body / Hands

| ID | C0 观察 | 允许的替代目标 | 保护条件 | 主要失败风险 |
|---|---|---|---|---|
| F1 under_restored_features | 五官/眉眼/唇线、头发可见边界仍断裂模糊 | 恢复可见结构连续性与有依据的细节 | 表情、可见几何、身份相关外观、发型及姿态 | 虚构五官、改变外貌 |
| F2 waxy_skin | 过平滑、塑料肤质、头发/衣料细节被抹平 | 恢复自然、低对比、非规则微纹理 | 大尺度肤色/阴影、可见面部形状、表情 | 假毛孔、过度纹理 |
| F3 over_generated_detail | 假毛孔、假皱纹、锐化光晕 | 抑制无依据高频和边缘硬化 | 已有真实边界、自然层次 | 全部重新抹平 |
| F4 structural_inconsistency | 手指、四肢、五官、轮廓或姿态与可见输入冲突 | 根据可见结构减少不一致，控制生成性几何 | 可见指头数/肢体结构、轮廓、表情 | 编造不可证实结构 |

注意：F2 不是“增加更多毛孔”；F3 不是“让脸更柔和”式全局抹平；F4 不等于美化脸型或改变人脸身份。对不可确认的微细节，采用自然性评价，不用“看起来像”声称身份真实。

**建议的 Rewriter 语义片段（示例，不是所有场景的固定模板）：**

- F1: “Restore continuity of facial and hair boundaries already suggested by the source; preserve visible expression and geometry; avoid inventing facial features.”
- F2: “Reduce waxy smoothing; recover subtle irregular low-contrast skin texture without dense artificial pores; retain natural shading and skin color.”
- F3: “Reduce unsupported pore-like high frequencies and sharpening halos while keeping genuine visible facial boundaries.”
- F4: “Resolve visible structural inconsistencies according to source cues; do not invent fingers, landmarks, accessories, or a new pose.”

每次只能选与 Issue 证据一致的具体方向；不得自动把 F1–F4 全部拼入 PF。

### 4.2 文字轴 T：Visual Restoration 与 Content Fidelity 分离

LQ 信息状态在**生成前、仅根据 LQ**标注：
- **legible**：目标字符及部分笔画可由 LQ/可信输入 OCR 确认 → 允许恢复已知笔画与布局。
- **partly_legible**：部分字符/笔画有依据，其他部分未知 → 增强有依据部分，未知保持 unknown。
- **unreadable**：无法确认字符 → 可改善可见性、标牌结构和已有痕迹，但不能声称恢复了真实词语。

| ID | C0 观察 | 允许的替代方向 | 明确禁止 |
|---|---|---|---|
| T1 merged_strokes | 可确认字符笔画粘连 | 分离已有可见笔画，恢复间距/边缘 | 重新拼写字符 |
| T2 broken_strokes | 有依据的笔画断裂 | 恢复已有笔画连续性 | 用语言模型补出缺失全文 |
| T3 invented_or_wrong_text | C0 产生与 LQ 可确认内容冲突的清晰错字 | 抑制无依据的文本补全，以 LQ 笔画证据校正 | 将候选 OCR 或常识当 GT |
| T4 unreadable_source | 原 LQ 无法辨识关键字符 | 修复标牌轮廓/可见性，保留真实性未知 | 强制生成完整可读品牌/数字 |

**建议的 Rewriter 语义片段（示例）：**

- T1/T2: “Restore visible stroke separation and continuity supported by the source; preserve confirmed characters, layout and spacing; do not insert text.”
- T3: “Prioritize source-supported stroke evidence and suppress unsupported character structures; do not treat OCR of generated outputs as original text.”
- T4: “Improve the sign region's visual structure without claiming readable character content that cannot be confirmed from the source.”

两种用途必须遵从主规格 §8.5 的逐属性政策。photo_restoration 可对预先允许的自然微细节接受未知，但不得声称文字真实。information_critical 的关键号码、身份或文字，以及用户明确要求准确的属性，必须有 required_for_acceptance=true 且采用 verified_content；no_visible_conflict 或 unverifiable 都不能进入 eligible。F0 冻结属性规则，F1 解析 ROI 实例，禁止为了通过临时放宽准确性要求或切换用途。

### 4.3 多人物、多招牌与空间冲突

例：Person 1 蜡感需增强纹理；Person 2 假毛孔需减少高频；Person 3 远景完全模糊无法确认身份。不能简单写“增强所有人物纹理”。

Planner 应为每个实例登记 ROI、单独期望、保护要求和覆盖状态。**同一个人物轴可以包含多个实例**，但如果重要实例需要互相反向的指令，而且当前 full_frame 文本控制无法可靠分离，必须标记 spatial_control_risk=high 和 coverage_limited。此时可以选择最关键且可执行的一项干预，并在报告中标注未覆盖实例；不要大量追加互斥区域指令、也不要暗中增加局部 Mask/融合。

同理多块招牌仍属于文字问题轴，不为每个字符或招牌各增加一个候选槽；未覆盖的重要文字仍必须进入后续 Judge 的全图/区域验收。

## 5. 四个候选槽位与自适应分配

### 5.1 人物+文字混合场景

| 展示名 | 持久 strategy_id | 人物策略 | 文字策略 | 输入 |
|---|---|---|---|---|
| C0 | baseline | P0 原版 | P0 原版 | LQ |
| CF | face_alt | F 替代 | 原版 | LQ |
| CT | text_alt | 原版 | T 替代 | LQ |
| CFT | joint_alt | **相同 F** | **相同 T** | LQ |

P_F = Rewrite(P0, ΔF)；P_T = Rewrite(P0, ΔT)；P_FT = Rewrite(P0, ΔF, ΔT)。这里 Δ 是语义作用域的干预，不是像素 delta，不是固定“生成强度”。

Candidate ID 不复用现有 sr_v02 的 C0–C3 命名空间，采用 strategy_id + sample_index + seed（例：face_alt_s1_seed101）。C0/CF/CT/CFT 只用于展示。

### 5.2 非典型场景的固定槽位政策

| 情形 | 四个槽位（包含 C0） |
|---|---|
| 人物+文字均有有据问题 | baseline、face_alt、text_alt、joint_alt |
| 只有人物，且确实有两个**机制不同且有据**的替代方向 | baseline、face_alt_A、face_alt_B、baseline_resample |
| 只有文字，且确实有两个有据的替代方向 | baseline、text_alt_A、text_alt_B、baseline_resample |
| 建筑+草地为主要争议 | baseline、building_alt、grass_alt、joint_alt（实际记录真实名字） |
| 只有一个可执行方向 | baseline、该方向、baseline_resample、baseline_resample |
| 没有明确问题或只有不可支持假设 | baseline、baseline_resample ×3 |
| C0 失败 | baseline_failed；停止反馈式策略规划，不替换 C0、不隐藏失败 |

当仅一个问题轴却有 A/B 两方向时，两者必须反映真实不同的恢复决策（如减少蜡感 vs 保护可见边界），不能为占槽位而发明“弱/中/强”。分配和 fallback 顺序在 F0 预注册。

## 6. Prompt Rewriter：从 P0 到 PF/PT/PFT 的可审计编译

### 6.1 原始 P0 不应当被自由重写

用中间需求表示（IR）描述 P0 的**语义要求和引用关系**：

- **G**：全局恢复目标、退化类型、输出几何与色彩约定；
- **F0**：人物恢复目标及相关保护；
- **T0**：文字恢复目标及已知内容约束；
- **O**：建筑、草地、背景等其他区域要求；
- **R**：任务级内容/身份/文字/几何保护及不可妥协条件。

推荐公式：PF=G+F1+T0+O+R；PT=G+F0+T1+O+R；PFT=G+F1+T1+O+R。**这只是语义组合，不是简单字符串拼接。** P0 的一个自然语言句子可能同时包含 F/T/R；解析器必须保存原文字、要求 ID、来源片段及交叉约束。

推荐中间需求条目：

~~~json
{
  "requirement_id": "REQ_FACE_02",
  "source_span": "avoid restoring any fine facial detail",
  "scope": ["person_01_face.texture"],
  "kind": "restoration_strategy",
  "mutable_by": ["face_alt", "joint_alt"],
  "protected_links": ["REQ_GLOBAL_IDENTITY", "REQ_GLOBAL_COLOR"],
  "original_text_hash": "sha256-of-source-span"
}
~~~

如果解析不能可靠定位可改写片段，保留 P0 原文和未覆盖要求；进入审计/预定 fallback，不可丢弃未理解的原始约束。

### 6.2 受控改写规则

1. **先分离保护属性与恢复策略**。允许改变“不要恢复任何面部微纹理”等与目标恢复冲突的策略性约束，不允许删除已知身份/表情、文字内容、背景结构等保护要求。
2. PF 只替换 scope=人物恢复属性；PT 只替换 scope=文字恢复属性；PFT 引用**与 PF/PT 完全相同的已冻结 F/T 干预**，不是重新生成第三个新方向。
3. 输出**完整 Prompt**和机器可读 diff；保留 P0 原文字节快照。不要在 P0 后直接添加互相矛盾的新要求。
4. x1/x4 的共有 geometry wrapper 所有候选相同；其字节及哈希单独可审计。C0 的真实执行 Prompt 与用户可读的原始 P0 及共有 wrapper 关系必须明确记录。
5. Prompt Rewriter 只改文本语义，不调用生成器；Planner/Bridge 之间仅传不可变 CandidateSpec。

### 6.3 Rewriter 输出 Schema（建议）

~~~json
{
  "schema_version": "hre_candidates_v1",
  "strategy_id": "face_alt",
  "base_prompt_id": "P0",
  "issue_refs": ["F01"],
  "changed_requirements": [
    {
      "requirement_id": "REQ_FACE_02",
      "scope": "person_01_face.texture",
      "old_text": "avoid restoring any fine facial detail",
      "new_text": "recover subtle natural skin texture without artificial pores"
    }
  ],
  "retained_requirements": [
    "REQ_TASK", "REQ_GEOMETRY", "REQ_TEXT_CONTENT",
    "REQ_GLOBAL_COLOR", "REQ_BACKGROUND", "REQ_GLOBAL_IDENTITY"
  ],
  "expected_effect": [
    {"region_id": "person_01_face", "attribute": "natural_texture", "direction": "improve"}
  ],
  "full_prompt": "FULL EXECUTOR PROMPT HERE",
  "audit_status": "pending"
}
~~~

持久化 Prompt 的原文、完整 executor condition、UTF-8 字节哈希、需求级差分、改写器版本、Issue refs 和审计回执。代码必须校验引用有效、列表唯一、字段枚举合法，不能只比较字符变化。

### 6.4 独立语义 Audit：**强制**且不得伪装成生成成功

审计项：
- 全局任务、x1/x4 倍率、输出尺寸、共享要求是否被保留；
- PF 是否只改人物恢复策略；PT 是否只改文字恢复策略；
- PFT 是否包含 PF、PT 的同一替代方向且没有相互矛盾；
- 人物表情、可见结构、肤色、文字已知字符、建筑与背景保护是否保留；
- 是否把 OCR 猜测、候选生成结果或语义常识写成原始真实文本；
- 是否遗漏未被明确允许修改的恢复目标或加了新的任务；
- 检查是否带有生成结果/GT 信息泄漏。

允许最多**一次**语义修复，修复之后重新审计；仍失败则将该策略槽按照 F0 预注册规则改为 P0 baseline_resample，记录 plan_fallback 和原失败证据，不能仍标记 face_alt/text_alt。超时 unknown 的请求按 runtime 协议对账，不能假装失败后直接重发。

**Audit 通过只证明 Prompt 满足规划合同，不证明 Qwen 遵守了 Prompt。**

## 7. Qwen 执行 Bridge：保证生成条件可复现

### 7.1 路由与来源

第一轮使用主规格的现有 v3 Qwen 接口：profile_id=qwen21；task_mode=restoration；strategy=native；intent=null；inputs=[source]；spatial.mode=full_frame；明确 canvas 与 seed。此处 native 是请求路由语义，**不是取消原 Composer**。

- **P0/PF/PT/PFT 均从同一冻结的规范化 LQ 执行**，不将 C0/CF/CT 作为生成模型 image input；
- 复用 dispatch.seal_condition / dispatch.generate 的绑定能力；候选专属 bridge 直接以冻结完整 Prompt 构建 condition.text，避免通用 render_instruction 再加保持源画布模板改变策略或 x4 逻辑；
- 必须测试 **frozen full_prompt SHA = actual condition.text SHA**，并记录模型实际调用入口、request binding、步骤/CFG/seed、模型 revision 和所有后处理；
- 基线 request_binding 不含 seed，不能单独承担冻结校验。按主规格 §6.3 保存 FrozenExecutionRequest，并在 submitted 与模型调用前重新比较 execution_manifest_sha256。C0 在生成前冻结，其余候选在 F1 冻结；只改 seed 或 editor config 也必须在提交前拒绝；
- PE=off、color_adjust=off；若保留必要的固定色彩/解码处理，四个候选完全相同且 native 与 delivered 都归档；
- full_frame 的区域指令没有硬 Mask 保障；任何非目标区域变化均须留给后续整图评审和离线损害统计。

### 7.2 x1 / x4 几何（严格）

设规范化 LQ 为 W×H：

| mode | 输入 pad | 原生期望 canvas | 最终 delivered |
|---|---|---|---|
| restoration_x1 | 右/下补到 32 的倍数 | Wpad×Hpad | W×H |
| sr_x4 | 右/下补到 8 的倍数 | 4Wpad×4Hpad | 4W×4H |

pad/crop 记录坐标、填充模式和像素内容；ROI 坐标按 x1 或 x4 投影。若 Qwen 实际 adapter 不支持该画布尺寸，preflight=blocked；不得悄悄使用缩放/插值伪造严格 x4。原生输出尺寸错误直接 contract_fail，不用 resize 兜底。保留 native.png、delivered.png 与 hash；Composer 看到未 padding 的 LQ，避免 padding 边框影响语义。

几何由候选 bridge 独立拥有，遵从主规格 §6.2。复用 diagnosis、tools、visual pack、compose 的函数，不调用旧 run_sample、prepare_lq 或 run_execute 组织新链路。工具自行缩放时显式映射工具坐标至规范化 LQ。严格 x4 不直接复用现有 v3 spatial.prepare_request 或 deliver_outputs，它们以同源画布交付为目标。

来源记录必须区分原始文件、规范化 LQ 与 padding 后实际执行输入。canonical_source_sha256 绑定规范化 LQ，prepared_source_sha256 绑定 Qwen 实际输入，geometry_sha256 连接来源及输出 crop。四候选共享同一 canonical source，固定几何下也共享 prepared source；两种来源 hash 无须彼此相等。不得把合法 padding 当作来源错误，也不得把 C0 作为准备输入。

### 7.3 CandidateSpec 与回执

~~~json
{
  "schema_version": "hre_candidates_v1",
  "candidate_id": "face_alt_s1_seed101",
  "strategy_id": "face_alt",
  "source_sha256": "hash-of-frozen-LQ",
  "canonical_source_sha256": "hash-of-frozen-LQ",
  "prepared_source_sha256": "hash-of-padded-executor-input",
  "geometry_sha256": "hash-of-frozen-pad-crop-and-roi-map",
  "execution_manifest_sha256": "hash-of-complete-frozen-execution-manifest",
  "prompt_path": "plan/prompts/PF.txt",
  "prompt_sha256": "hash-of-frozen-PF",
  "seed": 101,
  "executor_profile": "qwen21",
  "spatial_mode": "full_frame",
  "geometry_mode": "sr_x4",
  "scale": 4,
  "issue_refs": ["F01"],
  "status": "planned"
}
~~~

上例 seed 和 hash 是说明值，不是全局固定配置。source_sha256 是 canonical_source_sha256 的兼容名称，两者必须相等。execution_manifest_sha256 的计算范围严格采用主规格 §6.3，包含实际请求的 seed、完整 condition hash、两种来源、几何与展开默认值后的有效 editor config。runtime 在 submitted 前重新计算并比较清单，差异报 execution_manifest_mismatch，不得先执行后补记。

校验通过后，每个外部操作先持久化 request、operation ID、预算预占和 submitted，再执行；结束后存原始响应、回执、实际 condition/尺寸/哈希/模型 revision、耗时和成本。无回执不能仅凭有一个 PNG 判定调用完成。

## 8. 运行状态与异常语义

状态继承主规格：created → baseline_ready → plan_frozen → candidates_complete → evidence_ready → reviewed → selected / baseline_retained / unresolved；辅助状态 blocked、failed、unknown。

| 异常 | 处理合同 |
|---|---|
| C0 调用或尺寸契约失败 | baseline_failed；不进行依赖 C0 的反馈规划；全部样本计入生成失败分母 |
| 无可靠可执行策略 | 按冻结规则做 P0 resample；不编造 F/T |
| PF/PT/PFT 语义审计失败 | 允许一次修复；再次失败记录 plan_fallback → baseline_resample |
| 请求提交后断连/无回执 | unknown；人工或既有机制 reconcile，不自动重复提交 |
| 生成明确失败 | 记录 failed、调用/耗时，按 F0 已登记的恢复策略处理，不临时补抽 |
| 原生几何/哈希/来源错误 | contract_fail；不能以 resize 或改文件名补救 |
| 文字/人物非目标区域变化 | 保留候选送整图 Judge；记录 off-target 风险，不先验宣称空间保持 |
| 交付像素完全重复 | 保留独立调用与成本；可共享评价，但候选 ID 全部保留 |
| 四个候选都不合格或必需属性均未确定 | 不增加第 5 个候选，交既定 Judge 返回 unresolved |
| 重要 ROI 缺评、必需评审包失败或 unknown | 相应候选 undetermined，不以总评代替逐项；无 eligible 则 unresolved |
| ReviewPlan 容纳不了必需包及聚合调用 | 首次评审前 unresolved，原因 review_budget_insufficient，不静默缩减覆盖 |
| seed、有效执行配置或来源变换与冻结清单不符 | submitted 前 execution_manifest_mismatch，生成器零调用 |

精确重复用 delivered 像素 hash；第一轮不用近似相似度淘汰图像，避免忽略笔画或表情微小而重要的变化。单 GPU 默认串行执行，复用已加载模型；多 GPU worker 只消费冻结请求，不允许自行再规划。

## 9. Evidence / Judge 的交接合同（不重写 Judge）

> 本节涉及的旧 J1 默认、旧 J2 专家设定、评价预算和验收条款已由 QUALITY_EVALUATION_PLAN.md 覆盖。生成策略与执行约束保持有效，当前评价主方案为 J3。

Candidate Generation 交付一个**冻结且完整的候选池**：

- 原始 LQ 与每个候选 full-frame，以及同坐标关键人物/文字 ROI；
- 源图、请求、Prompt、输出、ROI、几何、每项测量的 SHA/版本绑定；
- Code 硬契约及软指标（clipping、edge energy、可用时 OCR/face、LR consistency proxy、NR-IQA 等）；
- 候选匿名映射（本地保存），向 Judge 仅传 A01…A04、匿名图像/证据、独立 EvaluationContract；
- 缺失、stale、failed、not_applicable 均显式标记，不把 null 当 0 或通过；
- 交付 F0 关键属性规则与 F1 解析后的必需实例，生成独立 ReviewPlan，绑定各候选和 ROI 的 required_check_ids、包、角色、预算及聚合规则；
- 人物合格不能覆盖关键号码未知。逐属性 AttributeAssessment 与评审 coverage 采用主规格 §8.3–§8.6；缺项不能自动 eligible；
- 生成策略名、Prompt、seed、模型信息和 GT/Oracle 指标**不进入 Judge 请求**。

**Judge 的现行定义在 QUALITY_EVALUATION_PLAN.md**。J3 是异构专业证据加单 VLM 终审的研究主方案，J0、J1、J2 保留原定义用于消融。只有 eligible 进入 listwise，无可交付结果则 unresolved。小脸跳过、证据可采纳性、单包和多包预算、专家 forward 及 unknown 恢复均复用新规格，不另发明选择逻辑。

## 10. 最小实验：覆盖率、策略响应和最终选择分开

> 本节涉及的旧 J1 默认、旧 J2 专家设定、评价预算和验收条款已由 QUALITY_EVALUATION_PLAN.md 覆盖。生成策略与执行约束保持有效，当前评价主方案为 J3。

### 10.1 E1：等 4 图预算，比较策略候选池与 P0 多 seed

| Seed | A：baseline multi-sample | B：strategy pool |
|---|---|---|
| s0 | P0 → C0（共享） | P0 → C0（共享） |
| s1 | P0 → A1 | PF → CF |
| s2 | P0 → A2 | PT → CT |
| s3 | P0 → A3 | PFT → CFT |

每张图**最多 7 次实际图像生成**（共享 C0）；生成失败必须留在分母，记录 partial pool。seed schedule 在 F0 冻结，必要时跨 case 预注册轮换 F/T 与 seed 的对应位置，以减轻固定偏置。B 多出 Planner/Rewriter/Audit 成本，因此“4 张图预算相同”不等于总 token/时延相同。

E1 主要比较 **Oracle Pass@4**（人工独立终审认定至少有一个合格结果）、Oracle Improvement@4、Content Error、总成本。在比较 A/B 最终系统质量时，**两组使用相同冻结的 J3**；不要一边用 J0、一边用 J2，同时改变生成和选图两项变量。

### 10.2 E2：同 seed 的 4 策略 × 2 seed 因子补充

| 策略 | seed A | seed B |
|---|---|---|
| P0 | P0-A | P0-B |
| PF | PF-A | PF-B |
| PT | PT-A | PT-B |
| PFT | PFT-A | PFT-B |

E2 样本选取严格采用主规格 §10.2.1。在读取 E1 输出、Judge 或 Oracle 之前，按原 LQ 的场景、人物/文字尺寸和信息可确认程度分层抽样，冻结 e2_manifest.json。记录 case 清单、各层样本数、抽样算法、随机 seed、缺额处理和 hash；不得依据 C0 或其他候选的恢复成功与否选样。

两个评价 seed 预先固定，均不同于用于规划的 C0 seed。每图先冻结原 C0 导出的 F1，再在相同评价 seed 下执行四策略，不重做 Planner、不修改 Prompt。仅一轴或发生 fallback 时原样保留并标 joint=not_applicable，C0 失败与生成失败保留在清单和对应分母中，不补选成功 case。

E2 另外计入实际生成次数和成本，不混入 E1 的每图 7 次预算。仅比较 seed 不同的 CF 与 C0 **不能证明策略因果效应**。事后挑选案例只进入 exploratory 失败或机制分析，不并入预注册的策略收益估计。

需要同时记录三个结果：

1. **Target Response**：同 seed 下 PF 的目标人物、PT 的目标文字在既定任务标准下是否改善（不以“像素变化越大越好”替代改善）。
2. **Off-target Damage**：CF 是否损害文字/建筑/草地等重要非目标 ROI；CT 是否损害人物/背景。变化幅度、语义质量与内容错误分开报告。
3. **Joint Compatibility**：PFT 是否能同时保留 F/T 两项改善，还是出现相互干扰；**PF 和 PT 分别有效不能推断 PFT 一定有效**。

对于有 GT 合成退化，可离线加入匹配 ROI 的 PSNR/LPIPS、人工已知字符转录 CER、可见表情/姿态判断；对于真实无 GT，只评价自然性、显式冲突、未知状态，不声称恢复了真实身份/字符。

### 10.3 E3：Judge 消融沿用主规格

固定完全相同候选池运行 J0/J1/J2，独立人工/GT 得到 Oracle。J1 比 J0 验证软数值证据贡献。J2 比 J1 仅验证多角色、多调用预算下的系统收益；声称角色分工有独立贡献，必须运行主规格 §10.3 的离线 J1_budget_matched 对照，匹配模型、候选池、图像与软证据覆盖、资格政策、分类调用限额和总输出 token 额度，并披露实际成本差异。未运行时明确归因限制。**本文件不改默认生产 Judge、不改四专家职责。**

### 10.4 数据、统计、分母

- Pilot：10 张有 GT，建议人物问题 3、文字 3、混合 3、其他/无明显问题 1；重点验证接口和失败归因，不由 10 张推断稳定提升。
- Pilot 后修订一次协议并冻结；Held-out：24 张，人物、文字、混合、其他各 6，按场景源切分，避免同场景裁图泄漏。
- 重要人物/文字尺寸、LQ 可确认程度、退化 recipe/seed、ROI、用途政策及 GT 来源全部记录。
- 指标以图像 case 为单位统计，报告样本数、失败数、配对胜/平/负、case-level bootstrap 区间；不能把四候选当成四个独立样本。
- 主指标按主规格：Produced / ContractValid coverage、Oracle Pass@4、Selected Pass、Conditional Selection Success、Best-in-pool Agreement、False Reject/Accept、Avoidable Unresolved、Content Error、Cost。
- 策略专项增加 Target Improvement Rate（明确目标 ROI 适用样本的改善比例）、Off-target Regression Rate（非目标重要 ROI 发生实质退化的比例）、Joint Success Rate（两目标同改且整图可接受的比例）、Diversity Collapse Rate（注明严格像素重复与感知无差异的不同判据）。
- 结果不能只报成功 case 子集；baseline_failed、contract_fail 和 unresolved 必须计入对应总分母。

## 11. 一张混合场景图的端到端示例

场景：夜间街道有前景人物、招牌、建筑、草地；输入 LQ。原版 C0：人脸蜡感，可确认招牌笔画仍粘连；建筑结构正常，草地局部模糊但次要。

Issue：
- F01：person_01_face / waxy_skin → 干预 F2：减少过平滑、恢复自然低对比肤质；保留肤色/可见结构/表情。
- T01：sign_01 / merged_strokes（LQ 部分字符已确认）→ 干预 T1：恢复可见笔画分离和间距；不能补出新的词语。
- Building/grass：登记为背景保护/次要残余问题，不把“草地更绿”变成恢复目标。

Plan：
- C0：P0 原版；
- CF：仅将 P0 中 F 相关要求换成上述 F2，T0 与全局保护保持；
- CT：仅将 P0 中 T 相关要求换成上述 T1，F0 与全局保护保持；
- CFT：同时使用同一 F2/T1；不是把 CF/CT 拼图，也不是把 C0 当下一轮输入。

**可能输出及归因**：
- CF 人物改善但招牌/建筑明显恶化 → 目标有效、非目标损害高，提示空间控制瓶颈；
- CT 招牌更锐但确实出现错字 → 文字内容冲突，即使 OCR confidence 提升仍可能不合格；
- CFT 没有同时保留 F/T 收益 → 联合指令干扰，记录 joint failure；
- PF/PT/PFT 与 P0 语义差异明确，但目标区域无稳定变化 → 执行器策略响应弱或模型能力限制，不应通过无限改写 Prompt 掩盖问题。

真实输出必须用图像/ROI/证据佐证；此处仅为可复现的测试设计示例，并非运行结果。

## 12. 工程任务、优先级与验收门槛

> 本节涉及的旧 J1 默认、旧 J2 专家设定、评价预算和验收条款已由 QUALITY_EVALUATION_PLAN.md 覆盖。生成策略与执行约束保持有效，当前评价主方案为 J3。

| 里程碑 | 开发工作 | DoD（需要提供的证据） |
|---|---|---|
| P0 基线与 preflight | 以 codex/evidence-sr-v02-20261111 的锁定 revision 为候选起点，复查远端 SHA/未提交 diff/模型环境，独立 worktree | baseline_record、可执行性/阻塞原因，旧入口不受影响 |
| P1 真实 baseline | 复用前三阶段并归档 P0/C0、完整 condition/source/model hash、严格 x1/x4 geometry | fixture + 至少 1 张真实输出；C0 与原输入和原要求均可追踪 |
| P2 Planner | IssueRecord、ROI、原因假设、策略优先级、两轴分配、多实例风险、fallback | F1–F4/T1–T4、无人物/文字、ROI 超限、contradictory targets 均有测试和可解释输出 |
| P3 Rewriter / Audit | Requirements IR、限定作用域编辑、完整 PF/PT/PFT、独立审计及一次修复 | 可展示每一需求 old/new/retained；语义冲突不能悄悄放行 |
| P4 多候选执行与记录 | bridge / runtime / 完整请求冻结 / 独立 pad-crop / journal / resume | 同一 canonical 与 prepared source；seed、配置及变换提交前校验；严格原生尺寸；unknown 不重复生成 |
| P5 Judge 交接 | 完整冻结图池、逐关键属性、ReviewPlan、匿名 ROI、主规格 J0/J1 | 不泄漏策略或 GT；缺评和关键 unknown 不进入 eligible；预算不足准确 unresolved |
| P6 Pilot | 10 图 E1、预注册 E2、固定池 J0/J1；离线人工/GT；有选图研究依据再做 J2 | 七图对照、Prompt diff、目标/非目标 ROI、失败及成本；专家角色归因有预算对照或明确限制 |
| P7 Held-out + Review | 冻结后 24 图；配对统计、独立代码复审 | 论文级证据边界、完整回归测试、所有失败报告与代码 commit |

### 12.1 必须编写的测试（建议命名）

- test_candidates_same_source.py：所有生成输入都是冻结 LQ，C0 不被送作 CF/CT/CFT 输入。
- test_candidates_freeze_and_budget.py：F0/F1 只读、seed schedule 稳定、未知/超时不能隐式补抽。
- test_candidates_issue_priority.py：F2 蜡感与 F3 假纹理方向不同；缺证据不生成策略；原因假设与观测分离。
- test_candidates_multitarget.py：多人相反策略、两招牌 ROI、coverage_incomplete、spatial_control_risk。
- test_candidates_rewriter.py：PF/T/FT 范围受控、原要求不漏、联合策略一致、一次修复/fallback。
- test_candidates_bridge.py：实际送达 Prompt hash、source binding、PE off、x1/x4 padding/crop 与原生错误尺寸。
- test_candidates_evidence.py：ROI/hash/stale/missing/匿名、GT 隔离、软指标不可硬筛。
- test_candidates_runtime.py：completed 幂等、submitted 未回执标 unknown、重复像素保留调用成本。
- test_candidates_pool_report.py：七次生成预算、失败仍入分母、E1/E2 分开统计、对应图像和 ROI 存在。
- test_candidates_regression.py：原 harness / sr_v02 / reference / v3 入口和 wheel prompt 资源回归。
- test_candidates_execution_manifest.py：condition 不变而 seed、steps、CFG、revision、output_resolution、prepared source 或 crop 改变时，submitted 前拒绝且生成器零调用；合法 padding 允许 canonical/prepared hash 不同。
- test_candidates_attribute_eligibility.py：人物合格但关键号码 unknown、漏掉必需属性、required ROI 缺评、候选总评与逐项矛盾，不得错误交付。
- test_candidates_review_plan.py：ROI 超限分包、缺包、聚合容量不足、unknown 占额、修复占总额度、预算不足时零评审；重要覆盖不足不能 selected。
- test_candidates_e2_preregistration.py：清单及评价 seed 先于 E1 输出固定，不使用 C0 seed 作评价 seed，不补选成功 case，exploratory 与预注册指标隔离。

测试使用预制 mock VLM/Qwen 和少量**故意带错误的图像 fixture**；测试通过只是工程逻辑有效，不得声称模型恢复效果已提升。

## 13. 目录、交付及工程师运行说明

> 本节涉及的旧 J1 默认、旧 J2 专家设定、评价预算和验收条款已由 QUALITY_EVALUATION_PLAN.md 覆盖。生成策略与执行约束保持有效，当前评价主方案为 J3。

每 case 建议存储：

~~~text
case001/
  case.json                  # TaskSpec / 用户目标 / 执行环境身份
  freeze.json                # F0/F1、预算与哈希
  execution_manifests/       # C0 及其余候选的只读完整执行清单
  baseline/
    diagnosis.json
    tool_evidence.json
    P0.txt
    C0_native.png
    C0_delivered.png
    receipt.json
  plan/
    issues.json
    roi_registry.json
    requirements_ir.json
    candidate_plan.json
    audit.json
    prompts/
      PF.txt
      PT.txt
      PFT.txt
  candidates/
    face_alt_s1_seed101/
      request.json
      condition.json
      native.png
      delivered.png
      receipt.json
    text_alt_s2_seed102/
    joint_alt_s3_seed103/
  evidence/
    measurements.json
    anonymous_images/
    roi_comparison/
    change_maps/
  judge/                     # 主规格各 variant 的 ReviewPlan、覆盖、请求与逐属性结果
  selection.json
  report.md
  contact_sheet.png
  offline/                   # 仅评估程序读取
    oracle_labels.json
    gt_metrics.json
~~~

以上是逻辑目录示例。失败时对应图片可以不存在，必须存状态、错误、回执及绑定，不能伪造完成。实际候选 ID、seed 由冻结配置决定，不使用示例值硬编码。

**逐图报告（必须能仅靠报告回顾研发决策）**：
1. LQ、P0、C0、问题定位与 Issue 对照：哪些是真观察，哪些仍是原因假设。
2. F/T 策略、各作用域原要求和替换要求、完整 Prompt SHA、审计与 fallback。
3. A/B 七图整图+同坐标关键 ROI、Change Map、人物/文字/背景完整覆盖情况。
4. PF/PT/PFT 的 Target Response、Off-target Damage、Joint Compatibility 与失败归因；不要将纯像素变化当改善。
5. 主规格 Judge 的逐属性结果、ReviewPlan 与必需覆盖、合格集合、最终选择、未知真实性状态、独立人工 best_set；J2 未运行标 not_run。
6. 完整数据/模型/执行身份、计费/时间/失败与 unknown 状态。
7. 下一轮研究建议：是诊断失败、策略无效、空间控制不足、执行器响应弱，还是 Judge 错选。

**批量报告**沿用主规格 EXPERIMENT_REPORT.md 和 per_case.csv、per_candidate.csv、judge_comparison.csv，并新增可选 strategy_effect.csv（按 case/strategy/seed/ROI 归档方向性响应及损害），不改主规格口径。

**提交前验收**：提供可复现提交 SHA、config/task 样例、README/runbook、单测/集成/回归日志、1 图真实输出、10 图 Pilot、24 图 Held-out、E2 预注册清单及 hash、ReviewPlan 与逐属性覆盖、完整执行清单、所有失败及 unknown 记录、独立代码复审结果。J2 未运行时标 not_run；未做预算匹配对照时不得声称专家角色贡献。生产质量和研究收益需要真实模型与独立评价证据；工程完备不等于论文假设成立。

## 14. Research Decision：失败时如何决定后续方向

> 本节涉及的旧 J1 默认、旧 J2 专家设定、评价预算和验收条款已由 QUALITY_EVALUATION_PLAN.md 覆盖。生成策略与执行约束保持有效，当前评价主方案为 J3。

| 有证据的观测 | 首要解释 | 下一步实验，而不是立即增补的新模块 |
|---|---|---|
| C0 有明显缺陷，但 Planner 漏报 | 缺陷识别/证据覆盖不足 | 固定输出的诊断召回与 ROI 覆盖分析 |
| Planner 发现蜡感却选择增强锐化 | 策略映射错误 | Issue→Strategy 消融，比较有限目录策略 |
| PF 改动文本但审计发现丢失保护条件 | Prompt 编译/约束维护失败 | 修 Requirements IR 和语义 Audit |
| PF/PT 语义可靠、同 seed 目标区域无方向性响应 | Qwen 对该干预的响应弱，或提示方式不适配 | 同 seed、同图、多次重复确认，再研究 Executor Capability |
| 目标变好、非目标退化严重 | full-frame 的空间控制不足 | 在新协议中验证局部工具/Mask，而非首轮偷加 |
| CF/CT 分别有效，CFT 失败 | 联合指令干扰 | 研究共同指令压缩、目标冲突或后续组合控制 |
| B 池有合格候选，但 Judge 没选中 | 选择机制/证据分配失败 | 在冻结池上优化 J1/J2，不修改生成策略 |
| B 池没有合格候选 | 生成覆盖不足 | 改 Planner/Executor，而非继续叠专家 |
| A/B E1 有收益但同 seed E2 不稳定 | 随机性、多样性或 seed 偏置可能解释收益 | 扩大同 seed 因子样本、跨 seed 复验 |

**最终可提交的科研结论必须分层**：
- 工程已实现：能否复现 Prompt/输出、策略审计与全流程；
- 系统级候选覆盖：同预算 B 是否比 A 更常包含合格结果；
- 策略机制：F/T 同 seed 是否真实改善目标且避免非目标损害；
- Judge 收益：J1/J2 是否比 J0 更接近独立 Oracle；
- 真实性边界：无 GT 情况下未知内容不宣称已验证。

> **工程师最先完成 P0–P4**，形成一张真实场景的 C0/CF/CT/CFT + Prompt Diff + ROI 对照；通过该门槛再运行 10 图 Pilot。**不要首先扩充模型、候选数量、专家或工具链。**
