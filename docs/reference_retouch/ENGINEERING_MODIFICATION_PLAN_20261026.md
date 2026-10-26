# HarnessIR 参考 Retouch 完整修改方案与工程交接书

**版本：** v1.0  
**日期：** 2026-10-26（北京时间）  
**交付形式：** 单文件 Markdown，包含工程规格、实施顺序、验收条件、服务器实验计划与唯一回传模板。  
**状态：** 待工程师实现；本文件不是已实施补丁，也不是新增画质实验结果。  
**代码基线：** baolinv0/HarnessIR，分支 codex/reference-retouch-contract-20261026，提交 `16dee77487e4e13f76963f48bc4611d046bd0afe`，PR #11。  
**使用方式：** 工程师按第 12 节分批修改，按第 13 节完成软件验收；用户在服务器执行第 14 节实验，最终只粘贴第 16 节所定义的一份 EXPERIMENT_REPORT.md。

> 这次修改的中心目标：把“参考观察 → 证据 → 目标 → 原生模型条件 → 图像结果 → 逐项目标验证 → 有依据的修订”真正连起来。保留现有工作台和四模型入口，补齐状态与语义传递缺口，不重新建立一套训练系统。

## 0. 给工程师的执行摘要

### 0.1 业务目标

输入 A 是 S26 linear 经已冻结 baseline 后得到的 prediction 的已声明 SDR 显示域版本；输入 B 是同场景、可能不对齐的 iPhone RGB 参考。得到 C，使 A 的亮度、颜色、肤色、影调和主体背景关系接近 B 中有依据的目标，同时保持 A 的身份、表情、对象、文字、几何、构图及可信可见细节。

A/B 不能按对齐 GT 使用。不同照明、材质、视角造成的差别，要在属性级可比性中处理。参考噪声、毛孔、发丝、织物和对象内容不能作为要复制的目标。当前工作是参考外观迁移；其他会话中的严重退化生成性补全策略，不自动纳入本任务。

### 0.2 已作出的工程决策

| 决策 | 本期要求 |
|---|---|
| 基础结构 | 保留 hre-retouch 工作台与 hre models 四模型入口，两者共享小型纯逻辑，不合并整个状态机 |
| 合同发布 | 新增 reference_retouch_v2；保留旧 v3 和 reference_retouch_v1 的历史语义 |
| 工作台版本 | 新案例使用 reference_retouch_delivery_v3；现有 delivery_v2 仍按原严格规则运行，不能被降为 legacy |
| 证据复核 | 增加实际可执行的 evidence_review 阶段；冻结前可以依据新证据修订诊断 |
| 目标与条件 | conditional 的限制必须进入执行条件；unknown/incomparable 不成为执行目标 |
| 逐目标反馈 | 使用一个规范化 feedback 表驱动控制器，不依赖模型重复填写两套建议字段 |
| 不确定结果 | 同一候选允许追加人工/独立复核；不改原记录、不新增图像生成 |
| 尺寸 | 编辑前核对请求尺寸与交付下限；no-edit 路径直接按 A 检查，不受编辑后端画布限制 |
| 四模型 | 保留 Qwen PE-I2I、FireRed Recaption、FLUX PUP、FIBO VGL 原路径，补全输入限制与实际条件审计 |
| 实验 | 新旧合同和 A-only 分开生成清单；共用生成前冻结的离线评价标准 |
| 回传 | 两个入口最终都能导出同一种 EXPERIMENT_REPORT.md；照片、JSON、CSV、日志留服务器 |
| 本期完成标准 | 软件功能闭合 + 可执行实验包；质量提升和模型排名必须等真实服务器结果 |

### 0.3 实施边界

本期不训练/微调模型，不新增 NB、MOSS 或新的编辑模型，不自动扩展到视频、RAW/HDR 联合优化、跨场景相机风格学习。GPT Image 工作台用于参考流程开发与独立运行；最终四开源模型比较单独列账，不将后端 unknown 的宿主输出归入任何已确认模型。

本计划中新增命令、字段和文件均为**待实现接口规格**。已有入口的实际用法见仓库 RUNBOOK；不能把下面的新接口示例描述成当前已可直接执行的命令。

## 1. 审查依据与已确认问题

以下定位以固定提交 16dee774 为准。工程师实现前检查当前分支是否前移；若已包含某项修复，核对验收结果后保留，而不是重复覆盖。

| 编号 | 当前问题 | 影响 | 本计划对应 |
|---|---|---|---|
| F1 | 逐目标 comparability/uncertainty 在共同提示与工作台提示中丢失 | 有条件的参考关系变成无条件编辑 | 第 4、5 节 |
| F2 | needs_evidence 获得统计后直接 compose，仍绑定旧诊断状态 | 新证据不能改变决策 | 第 6 节 |
| F3 | 工作台 uncertain 进入 report，无法给同一候选追加 verify | 人工复核无法闭合 | 第 7 节 |
| F4 | v3 反馈只读旧 issues[].suggested_change | 合法的目标级修正建议被忽略 | 第 8 节 |
| F5 | 画布主动缩小，冻结交付仍要求原尺寸 | 可预知的交付失败在生成后才发现 | 第 9 节 |
| F6 | 旧 front20 清单没有启用新合同，手册仍切旧分支 | 正式实验可能完全没有测到本次改动 | 第 10 节 |
| F7 | 旧 Markdown 把 source_already_satisfied 分类为 X；工作台只导出 JSON | 正确零编辑被误统计，单文档回传未接通 | 第 11 节 |

主要原始依据：

- [S1：目标与范围](https://github.com/baolinv0/HarnessIR/blob/16dee77487e4e13f76963f48bc4611d046bd0afe/docs/reference_retouch/GOALS.md)
- [S2：新运行手册与完成边界](https://github.com/baolinv0/HarnessIR/blob/16dee77487e4e13f76963f48bc4611d046bd0afe/docs/reference_retouch/RUNBOOK.md)
- [S3：工作台提示编译](https://github.com/baolinv0/HarnessIR/blob/16dee77487e4e13f76963f48bc4611d046bd0afe/engine/src/hre/retouch/contracts.py#L199-L211)
- [S4：四模型共同提示编译](https://github.com/baolinv0/HarnessIR/blob/16dee77487e4e13f76963f48bc4611d046bd0afe/engine/src/hre/v3/common.py#L228-L251)
- [S5：证据到 compose 的路径](https://github.com/baolinv0/HarnessIR/blob/16dee77487e4e13f76963f48bc4611d046bd0afe/engine/src/hre/v3/runner.py#L477-L487)
- [S6：新合同对旧诊断的约束](https://github.com/baolinv0/HarnessIR/blob/16dee77487e4e13f76963f48bc4611d046bd0afe/engine/src/hre/v3/reference_retouch.py#L216-L243)
- [S7：工作台验证与复核状态](https://github.com/baolinv0/HarnessIR/blob/16dee77487e4e13f76963f48bc4611d046bd0afe/engine/src/hre/retouch/workflow.py#L269-L308)
- [S8：旧 feedback 判断](https://github.com/baolinv0/HarnessIR/blob/16dee77487e4e13f76963f48bc4611d046bd0afe/engine/src/hre/v3/runner.py#L655-L676)
- [S9：画布规划与尺寸验收](https://github.com/baolinv0/HarnessIR/blob/16dee77487e4e13f76963f48bc4611d046bd0afe/engine/src/hre/retouch/workflow.py#L61-L138)
- [S10：旧清单生成器](https://github.com/baolinv0/HarnessIR/blob/16dee77487e4e13f76963f48bc4611d046bd0afe/research/front_camera_20/scripts/build_manifests.py#L139-L202)
- [S11：旧单文档分类](https://github.com/baolinv0/HarnessIR/blob/16dee77487e4e13f76963f48bc4611d046bd0afe/research/front_camera_20/scripts/export_text_report.py#L131-L150)
- [S12：工作台 JSON 报告出口](https://github.com/baolinv0/HarnessIR/blob/16dee77487e4e13f76963f48bc4611d046bd0afe/engine/src/hre/retouch/server.py#L45-L48)
- [S13：已有实验及证据边界](https://github.com/baolinv0/HarnessIR/blob/16dee77487e4e13f76963f48bc4611d046bd0afe/docs/reference_retouch/CASE_EXPERIMENT.md)
- [S14：四模型原生适配与运行说明](https://github.com/baolinv0/HarnessIR/blob/16dee77487e4e13f76963f48bc4611d046bd0afe/docs/four_model_v3/DESIGN_AND_COMPLETION.md)
- [S15：现有盲评准备脚本与源图排除路径](https://github.com/baolinv0/HarnessIR/blob/16dee77487e4e13f76963f48bc4611d046bd0afe/research/front_camera_20/scripts/prepare_blind_review.py#L21-L179)
- [S16：FIBO 可选 source_vgl 与差异审计](https://github.com/baolinv0/HarnessIR/blob/16dee77487e4e13f76963f48bc4611d046bd0afe/engine/src/hre/v3/fibo.py#L186-L281)

本次方案不重复开展模型效果实验。已有 CI 或软件用例通过，仅证明其实际覆盖的工程行为；单开发案例不能支持四模型排名或跨场景稳定性。

## 2. 架构与版本：局部改造，显式隔离

### 2.1 两个入口、统一规则

维持两个入口：

1. `hre-retouch`：网页分步操作、真实接口调用、导入 Agent/人工观察、候选与原生图查看。
2. `hre models`：四模型部署、批量运行、恢复、机器报告。

新增一份小型共享纯逻辑模块 `engine/src/hre/reference_policy.py`，负责可迁移目标判定、目标限制渲染片段、规范化反馈、交付可满足性与报告状态映射。该模块不访问网络、不加载模型、不管理文件和预算。两个入口各自做字段映射和状态持久化，避免引入第三套工作流。

建议纯函数职责：

~~~python
execution_eligibility(target) -> decision
render_target_constraints(target) -> structured_text
normalize_feedback(contract, verification, candidate_identity) -> list
assess_delivery_feasibility(source, planned_canvas, requirements, action) -> assessment
derive_report_outcome(run_record) -> normalized_outcome
~~~

这些是待实现接口；工程师可以微调命名，但职责、输入依据与验收行为必须保持。

### 2.2 版本分派表

| 输入/案例 | 处理方式 |
|---|---|
| v3 任务未指定 workflow_contract | 保留原行为及原请求身份 |
| reference_retouch_v1 | 保留当前已冻结 schema、模板与历史语义 |
| reference_retouch_v2 | 启用本计划的新复核、反馈、审计和状态 |
| 工作台无 acceptance_version 的历史案例 | 保留原历史展示/验收方式 |
| 工作台 reference_retouch_delivery_v2 | 保留现有严格追溯、伪影与交付逻辑 |
| 新工作台 reference_retouch_delivery_v3 | 启用本计划的修订与复核路径 |
| 未知版本 | 明确拒绝，不能回退到宽松 legacy |

新增 `v3/workflow_contracts.py` 统一返回 legacy/v1/v2 实现。不要继续在各文件分散比较版本字符串，也不要仅把旧 ACCEPTANCE_VERSION 常量改成 v3，导致旧 delivery_v2 案例掉入宽松分支。

### 2.3 兼容与历史规则

- 不原地改写历史 state、frozen contract、prompt、评分或图像。
- v1/v2 的 shared planning 禁止混用；版本、输入、brief、区域和证据身份全部匹配才可导入。
- 请求中实际会影响条件和判定的版本/策略进入 request hash。
- 历史案例重评：创建独立重评记录，引用原候选 hash 和新评价版本；不冒充新一次生成。
- 导出历史结果时标记未冻结的新字段为 not_recorded/unknown，不按当前默认值补齐。
- 正式报告不合并不同目标合同、不同尺寸协议或不同采样配置的指标。

## 3. 数据合同与冻结边界

### 3.1 必须分开的三类对象

| 对象 | 何时形成 | 谁可以修改 | 用途 |
|---|---|---|---|
| 用户任务范围 user_request | 建案例时冻结 | 修改需新任务 | 请求属性、保护内容、允许变更和交付要求 |
| 系统执行合同 execution_contract | 证据复核后、生成前冻结 | 反馈不能修改；发现错误另开 revision | 当前方法的实际目标与执行依据 |
| 共同离线评价合同 evaluation_contract | 正式生成前由实验设计者冻结 | 正式测试期间不修改 | 所有臂使用同一把尺子，防止方法自选容易目标 |

共同离线评价合同不能泄漏到真正 A-only 的诊断、提示、执行或内部验证。执行合同不替代离线标准。内部 accepted 不能直接当最终人评成功。

### 3.2 目标最小字段

新合同保留八维覆盖。执行目标统一映射为：

~~~json
{
  "target_id": "t_skin_mid",
  "delta_id": "d_skin_mid",
  "attribute": "skin_rendering",
  "source_region": "source_face_mid",
  "reference_region": "reference_face_mid",
  "source_observation": "A 中可观察的肤色状态",
  "reference_observation": "B 中可观察的肤色状态",
  "comparability": "conditional",
  "allowed_change": "只对可比中间调肤色做方向性调整",
  "limitations": [
    {
      "constraint_id": "c_skin_illumination",
      "text": "两图混合照明不同；不匹配阴影区绝对亮度或物理光向"
    }
  ],
  "evidence_refs": ["source", "appearance_reference", "evidence:face_mid"],
  "mandatory": true,
  "priority": 1,
  "acceptance_criterion": "冻结的可观察完成标准",
  "execution_instruction": "当前轮完整执行表达"
}
~~~

以上为结构示例，字符串不是本实验的实际观察。workbench 的 target_id 和 v3 的 id 可以保留外部差异，但进入公共逻辑时须显式映射；不能靠猜字段名兼容。

- A/B 区域用各自坐标；属性级可比性可以不同。
- 每条 conditional 必须有非空的限制；现有 uncertainty 文本在 v2 中转成 limitations，并保留原始文本。
- unknown/incomparable 只留在差异、排除或待复核表，不能留在执行 targets 中。optional 也不能绕过这一条。
- 用户必需请求不能被 compose 静默降为 optional、excluded 或 not_applicable。无法支持时明确 unresolved_required_requirement，并转复核/终止；用户改变要求需新任务。
- 数字容差来自已运行测量或开发集事前校准，并记录单位与来源。不能让 VLM 编造“色温差 300K”或凭空设定 ΔE 门槛。
- 必需目标不得限死为三条；提示可以归并操作，但映射必须覆盖全部目标。
- texture_and_noise_observation 用于保持/风险判断，不成为复制 B 纹理的执行目标。

### 3.3 可修改和不可修改字段

冻结后允许变化：execution_instruction、局部执行优先说明、针对当前反馈的修正文本、编译尝试记录。

冻结后不允许变化：target_id/delta_id、源/参考观察、区域、可比性、limitations、mandatory、成功标准、用户请求、证据依据、保护项、交付要求。

必须以字段白名单应用更新，再重新计算冻结投影 hash。不能让 refine 重新生成整份合同后仅靠“看起来一样”接受。

### 3.4 共同离线评价的最小生产合同

新增 `front_camera_evaluation_contract_v2`，每个 pair/reference_variant 单独冻结。它由实验设计者查看 A/B 后确认，不能从某一方法生成后的 execution_contract 直接复制。至少包含：

| 字段组 | 必需内容 |
|---|---|
| 身份 | evaluation_id、pair_id、reference_variant_id、A/B/工作输入 hash、user_request hash、版本、冻结时间与合同 hash |
| 任务目标 | 稳定 target_id、mandatory、A/B 独立区域、可比性、限制、可观察完成标准；覆盖用户必需请求 |
| 保护与质量 | 稳定 protection_id、伪影检查 check_id、严重损伤规则、minor_issue 是否允许、自然度规则 |
| 交付 | 冻结公共工作尺寸/源尺寸要求、允许变换与细节要求 |
| 人评 | review_protocol_hash、人数、目标状态枚举、联合通过/复核规则、相对 A 改善尺度及正向门槛 |
| 事前基线 | baseline_status、逐目标 A 的状态、判断来源与时间、未确定原因；独立 baseline_record hash |

baseline_status 在看见正式输出前确定：全部必需任务目标已满足为 already_satisfied；有可判定的必需目标缺口且无阻塞未知为 needs_edit；必需依据或状态不能判清为 uncertain。未知不能靠空 targets 变成已满足。交付条件另行检查，不能由 already_satisfied 推定尺寸通过。

后来 baseline trial 的独立人评与事前状态冲突时，报告冲突并保留原分母；不得依据结果重新划分 needs_edit 子集。若必须改变评价目标或数据依据，创建新的 study revision，旧结果不改标为新实验。

evaluation_contract、baseline_record 和最终人评只进入离线评价目录。正式运行器只收到自己的合法执行合同；A-only 的 request/context/cache 中不得包含上述 B 派生内容。

## 4. 目标限制进入提示：必做修补

### 4.1 控制器确定性渲染

每个执行目标至少输出：

1. 目标 ID、优先级、必需/可选。
2. A 的状态与应用区域。
3. B 的实际观察和独立对应区域。
4. 可比性、允许变化、限制与明确排除项。
5. 完整执行指令。
6. 冻结的成功标准。

例子：

~~~text
Target t_skin_mid — mandatory
Source fact: ...
Reference fact: ...
Comparability: conditional
Allowed change: 调整可比中间调的肤色方向。
Limit: 两图混合照明不同；不将阴影或高光的绝对亮度当作匹配目标。
Preserve: A 的身份、表情、脸部结构与真实可见纹理。
Success: ...
~~~

不能把该限制只留在 JSON、日志或顶层 uncertainties；下游实际条件必须能看到。必需与可选分别组织；可选改善不能抵消必需项失败，也不能覆盖内容保护。

### 4.2 编译前校验

- 每个执行 target 均由有效诊断支持，证据引用真实存在。
- 所有必需目标与关键限制有渲染位置。
- 不可比、未知或被排除的差异没有混入编辑指令。
- 不存在“保持全部颜色不变”与已授权调色的矛盾。
- 输入顺序与角色固定为 A 内容、B 参考。
- 条件完整但模型能力未知，标记 capability_unknown，不用高 confidence 自动放行能力结论。

工作台 compile_prompt 与 v3 render_instruction 应调用同一限制片段生成逻辑。原生编译器收到的内容与报告展示的内容必须一致。

## 5. 四模型原生条件与编译审计

### 5.1 每个模型的工程要求

| 模型路径 | 本期修改 | 审查实际输出 | 不擅自改变 |
|---|---|---|---|
| Qwen PE-I2I | 将完整源/参考角色、目标、允许范围与限制送入既有 PE 输入；保留原始返回与最终文本 | 重写后是否丢目标、反转限制、引入美颜/对象修改 | 权重、采样参数、PE 协议、输出画布策略 |
| FireRed Recaption | 文本输入必须自包含角色与区域限制；不能依赖重写器从未收到的图像恢复语义 | Recaption 是否把局部方向性变化扩成全局变更 | 原有全图/已实现 ROI 机制；不临时增加未经验证的拼接 |
| FLUX PUP | 最终目标状态描述中保留 A 内容事实、B 的外观作用和 conditional 范围 | PUP 是否改写构图、复制 B 对象、把参考描述当场景替换 | 原有 PUP/布局机制、输入数约束与实际 helper |
| FIBO VGL | 按锁定 schema 表达 A 内容和允许外观变化；有 source_vgl 时核对字段差异 | 可用的 VGL 差异路径、引用图角色、编辑指令与合同是否一致 | VGL schema、原生 helper；不凭空发明字段路径 |

这里描述的是仓库现有路径的接入责任，不宣称某模型已经在真实数据上优于其他模型。所有具体模型 ID、权重 revision、编译器 revision、推理参数由部署配置锁定。

FIBO 分两种合法输入：有冻结的 source_vgl 时，绑定其 hash 并输出真实 source_snapshot_changed_paths；没有 source_vgl 时，记录 source_field_diff=not_available，通过 A、冻结保护事实和目标 VGL 做语义审计，不能声称已验证源字段未变。当前适配器的 source_vgl 是可选项，缺少时原差异字段为 null（S16）。本期不隐式增加 caption/source VGL 生成；若以后增加该阶段，单列其调用预算、输入和冻结身份，不藏在一次 compiler 中。

### 5.2 两层审计

**第一层：确定性结构审计，所有新合同任务必做。**

核对输入身份、合同 hash、实际条件 hash、原生响应、目标与限制的映射。文本位置必须真能取出对应片段；VGL JSON Pointer 必须存在。生成调用使用已审计的同一份条件，不能审计后再悄悄改写。

**第二层：重写后的语义覆盖审计。**

对 PE/Recaption/PUP/VGL 重写路径，提供 VLM 或人工审计入口。新合同正式臂默认开启；没有可用审计器则等待人工，不能静默记 pass。直接确定性渲染、没有二次重写的工作台提示可以使用结构完整性检查，报告明确其方式。

审计读取冻结目标、关键限制和实际原生条件，逐项返回：

~~~json
{
  "schema_version": "hre_condition_audit_v2",
  "condition_sha256": "<实际条件哈希>",
  "contract_sha256": "<冻结合同哈希>",
  "method": "vlm",
  "items": [
    {
      "target_id": "t_skin_mid",
      "constraint_id": "c_skin_illumination",
      "status": "preserved",
      "location": {"kind": "text_span", "start": 120, "end": 215},
      "excerpt": "<实际条件中的原文>",
      "reason": "<为什么该片段覆盖该限制>"
    }
  ]
}
~~~

status 为 preserved/missing/contradictory/uncertain。模型原生输出不用强行包含 target_id；控制器保存目标到真实文本或字段的审计映射即可。

- mandatory 目标或关键限制 missing/contradictory：不生成，记录 compile_coverage_failed。
- uncertain：暂停审查；不把它转成 pass。
- optional 目标遗漏：如未影响用户必需请求，可继续但必须披露；关键保护限制遗漏始终阻止生成。
- 编译重试默认不自动触发。经明确修正再编译需记录尝试并计费/计预算。
- 语义审计是可复核判断，不是数学证明。hash 只能证明使用同一份条件，不能证明语义等价。
- 最终图像 verifier 不接收模型名、策略标签或编辑提示，仍只按 A/B/C 与冻结目标判断。

为隔离效果来源，正式六臂主结果把“新合同+审计”视为一个整体系统变体；如需单独声称仅目标结构带来收益，再增加小子集的 audit 开关消融，不能从主表直接推出。

## 6. 证据复核：让测量真正改变决策

### 6.1 状态转换

~~~mermaid
flowchart TD
    D["初始诊断"] --> E["按需收集证据"]
    E --> G{"需要复核？"}
    G -->|否| C["编译并冻结目标"]
    G -->|是| R["证据复核"]
    R -->|证据支持| C
    R -->|仍不足或冲突| H["待人工或明确停止"]
    C --> N{"目标已满足？"}
    N -->|是| A["交付原图并检查要求"]
    N -->|否| P["尺寸预检与原生条件编译"]
~~~

evidence_review 是真实阶段，不是只放一个 ground-evidence 模板。两个入口使用同一阶段职责；工作台可以显示“证据复核”，v3 注册同名阶段。

触发：needs_evidence；已取得请求的新证据；诊断与测量存在显式冲突；拟升级 unknown/conditional 的对应关系。每次任务默认最多一次自动复核，仍不足时进入 review_pending 或停止。

### 6.2 复核输入与输出

输入必须包含初始诊断、实际测量、区域定义、A/B 图、各自身份 hash、用户请求、允许引用列表。重新 diagnose 不能丢掉 evidence。

输出包括：

~~~json
{
  "schema_version": "hre_reference_evidence_review_v2",
  "basis": {
    "diagnosis_sha256": "<旧诊断>",
    "evidence_sha256": "<新证据>"
  },
  "resolution": "resolved",
  "diagnosis": {"schema_version": "hre_reference_diagnosis_v2"},
  "review_reason": "<新增证据解决了什么，仍保留什么不确定性>"
}
~~~

diagnosis 在真实实现中必须是完整合规对象；示例仅展示外层。resolution 为 resolved/still_insufficient/reference_rejected。

控制器校验：输入和证据属于当前案例；新判断有新增依据；保留用户请求与保护事实；被移除的差异有理由；不可比较性升级可追溯。复核后仍不知道就停止，不要求模型强行写 supported。

### 6.3 工件与冻结

建议工件：

~~~text
diagnosis.initial.json
evidence.v001.json
diagnosis.review.v001.json
diagnosis.effective.json
reference_contract.json
~~~

compose 绑定 effective diagnosis；initial 永久保留。effective 可以是明确的引用指针，不能覆盖旧诊断。复核前后差异由代码计算，并进入报告。

冻结后的新证据若推翻目标依据：标记 contract_revision_required，另建任务 revision。不能在看过输出后改变当前验收标准。

## 7. 不确定结果复核：同一候选追加观察

### 7.0 按复核对象区分恢复路径

复核有四类，不能全部要求已经存在 candidate。统一 reviews 入口使用 review_kind 作为严格的判别字段：

| review_kind | 当前情形 | 必须绑定的依据 | 允许的恢复结果 |
|---|---|---|---|
| evidence | 目标冻结前的证据不足/冲突 | user_request hash、有效诊断 revision/hash、evidence hash | 追加有效诊断修订，进入 compose 或继续待复核 |
| condition | 已冻结目标、尚未生成，原生条件审计 uncertain | contract hash、condition hash、当前 audit revision/hash | 追加审计，放行该条件或保留编译失败 |
| candidate | 已有候选的目标/内容/细节 uncertain | candidate hash、contract hash、当前 verification hash | 追加验证，按同一规则完成/修订/停止 |
| adjudication | 同一复核对象存在冲突观察 | 原对象身份及所有冲突观察 hash | 有记录的裁决；不能改对象或标准 |

evidence 不要求 candidate 或尚未存在的 execution_contract；condition 不要求 candidate；candidate 必须有真实候选。输入 schema 按 review_kind 分支校验，不把全部身份字段做成可任意缺失的一个对象。

预生成人工复核通过与否只改变该复核对象的有效记录，不消耗图像预算。condition 人工审阅不能把真实 missing/contradictory 或结构错误改成口头 pass；如必须修正条件，则建立有记录的新编译尝试并计预算。evidence 在合同已经冻结后不允许重写目标依据，转 contract_revision_required。

CLI 建议统一为 hre models review --kind evidence|condition|candidate|adjudication，绑定 --expected-subject-sha 和实际 observation；工作台 API 携带同义字段。以下 7.1–7.2 描述 candidate 分支的详细行为。

expected-subject-sha 指当前有效复核依据的版本：evidence 使用有效 diagnosis hash，condition 使用 audit hash，candidate 使用 verification hash，adjudication 使用完整冲突集合 hash。对象自身的图像/条件/合同身份仍在 observation 中独立校验；不能仅凭相同 candidate 像素 hash 接受过期观察。


### 7.1 新状态与入口

将 uncertain 的控制状态改为 review_pending，用户界面可以同时提供报告预览，但不是不可恢复的终态。

建议新增接口：

~~~text
POST /api/cases/{id}/reviews
hre models review --case-root ... --kind candidate --candidate-id ... --observation ... --expected-subject-sha ...
~~~

均为待实现接口。默认接收人工/独立 Agent 的实际观察；自动重验是可配置操作，仍计入分析调用预算。

复核请求至少绑定：

~~~json
{
  "review_kind": "candidate",
  "request_id": "<幂等导入标识>",
  "candidate_id": "<同一候选>",
  "candidate_sha256": "<候选哈希>",
  "contract_sha256": "<原冻结合同>",
  "expected_verification_sha256": "<当前有效验证>",
  "provenance": "human",
  "reason": "重新检查原生局部后解决原不确定性",
  "verification": {"schema_version": "hre_reference_verification_v2"}
}
~~~

第一版要求提交完整的新 verification，避免局部合并造成未检查项被误认为通过。若支持局部观察，必须由确定性合并保留全部原项并再次校验覆盖。

### 7.2 规则

- 只能复核原候选，不改变像素、目标、尺寸门槛或交付定义。
- 保留 verification.v000、v001 及评审来源，记录哪一个是当前有效观察。
- 使用 expected hash 拒绝过期写入；相同导入不能重复生成修订或计数。
- 重新验证不增加 generation_count；自动接口调用计入 analysis_calls，人工次数另记。
- 更新后复用同一判定函数决定 accepted/refine/review_pending/task_not_met。
- 新旧观察冲突，不能默认“最后一个 pass 胜出”。状态为 review_conflict，需明确 adjudication，保留双方原始记录。
- uncertainty 仅因看不清时，不允许用“再生成一张”绕过复核。
- 审阅已 accepted 的历史结果属于审计修订，不篡改历史快照。

## 8. 逐目标反馈：统一数据与决策

### 8.1 权威反馈表

v2 verification 使用一个 feedback 列表。target_results、preservation_checks、artifact_checks 可以通过 feedback_ids 引用它；旧 issues 若保留，仅为派生兼容视图，不参与另一套控制决策。

~~~json
{
  "target_results": [
    {
      "id": "t_skin_mid",
      "status": "partial",
      "observation": "实际可观察残差",
      "remaining_gap": "具体未达成项",
      "evidence_refs": ["source", "appearance_reference", "candidate"],
      "feedback_ids": ["fb_skin_01"]
    }
  ],
  "feedback": [
    {
      "id": "fb_skin_01",
      "scope": "target",
      "subject_id": "t_skin_mid",
      "recommended_action": "revise_prompt",
      "correction": "保持已达成亮度，仅修正剩余冷灰色",
      "evidence_refs": ["source", "appearance_reference", "candidate"],
      "reason": "残差与可支持修正的依据"
    }
  ]
}
~~~

scope：target/preservation/artifact/delivery。recommended_action：revise_prompt/gather_evidence/manual_review/stop。

引用绑定 round、candidate_id、verification hash；未知 target、另一候选或过期轮次拒绝。不存在可靠修正时可以停止，预算有余额不构成继续生成的理由。原生尺寸能力不足不能转成“再强调高清”的 prompt 修正。

### 8.2 控制器决策顺序

1. 文件/几何/回执不合法：执行失败或待核对。
2. 冻结目标被改变：拒绝更新。
3. 已确认不可满足的交付能力，或必需失败项的可靠结论为 stop：停止，保留失败原因；其他目标的 revise_prompt 不能覆盖它。
4. mandatory、保护项或必需伪影检查 uncertain，或合法 manual_review/gather_evidence 尚未完成：review_pending，先解决再判断能否 refine。
5. mandatory partial/unmet 或已确认的保护/伪影失败：只有合法 recommended_action=revise_prompt、具体允许的 correction 且预算足够才进入 refine；否则 task_not_met。冻结后 gather_evidence 仅用于核验当前候选；若要改变目标依据，转 contract_revision_required。
6. 所有必需外观与保护通过：单独检查 delivery。
7. delivery 通过才整体完成；外观通过而交付失败仍单列 delivery_not_met。

新控制器从规范化 feedback 生成 actionable_feedback_refs，不再要求 VLM 同时填写 suggested_correction 与 suggested_change。同一候选若同时存在未解决的必需项不确定性和可修正残差，先复核不确定性；不能因另一条 revise_prompt 跳过它。delivery 的确定性能力失败直接停止，不进入 prompt refine。

### 8.3 refine 只提交执行更新

~~~json
{
  "action": "revise",
  "parent_intent_sha256": "<上一意图>",
  "feedback_refs": ["feedback:r000:fb_skin_01"],
  "edit_updates": [
    {"target_id": "t_skin_mid", "instruction": "<保留完整目标并加入修正>"}
  ],
  "scope_updates": [
    {"scope": "preservation", "subject_id": "p_identity", "instruction": "<针对已记录内容损伤的执行保护>"}
  ],
  "reason": "<依据>"
}
~~~

代码以白名单应用 instruction 更新，并确认 frozen_contract hash 不变。新合同为保护项分配稳定 protection_id，固定伪影使用既有 check_id。target 反馈只更新 edit_updates；preservation/artifact 反馈只能更新执行计划中该 ID 对应的保护指令，不能改保护事实或验收状态。scope_updates 必须引用当前合法反馈，并进入下一轮完整渲染及审计；不能虚构 target_id 承载非目标问题。无实质变化则停止。下一轮使用原始 A+B，不将 C 当新源图；已达成目标继续包含在完整条件中。


## 9. 交付预检、图像角色与预算

### 9.1 保存原始输入，延后准备编辑画布

建案例时保存原始字节、方向/颜色转换记录、冻结分析输入 A/B 与各自 hash。只有确认需要编辑后，才为具体后端准备 source_work。

“零编辑像素相等”以冻结后的 A 为比较对象；如果发生 ICC 转换或 EXIF 方向规范化，不应宣称输出与上传文件字节相同。原文件始终保留。

no-edit 路径跳过编辑画布限制，直接检查 A 的原生尺寸和冻结交付要求。A+A 控制器检查必须是明确的“只匹配已有参考外观”任务；不能仅因图片相同就忽略用户另有的修图要求。

### 9.2 新增 delivery_preflight

~~~json
{
  "execution_mode": "api",
  "constraints_source": "locked_adapter_canvas_planner",
  "source_size": [3072, 4096],
  "planned_content_size": [2465, 3286],
  "planned_canvas_size": [2480, 3296],
  "required_native_size": [3072, 4096],
  "status": "infeasible",
  "reason_codes": ["planned_content_below_required_size"]
}
~~~

status 为 feasible/infeasible/unknown。这是当前实现画布规划的示例，不代表未经核验的外部模型上限。

- feasible 只表示计划可满足；实际输出仍按原生文件复查。
- infeasible：图像调用前停止，显示冲突；计数保持未调用。
- unknown：外部导入可以保留能力未知，导入后按真实文件检查；不能预写通过。
- 已知 padding 不算有效原生内容分辨率。不能用加边或插值满足“原生源分辨率”。
- 原生与交付图分别保存；原生文件、有效内容尺寸、去 padding/裁切/缩放变换均可追溯。
- 外观通过但交付不足：delivery_not_met；不以反复强调高清来消耗剩余生成预算。

### 9.3 两种事前声明的交付模式

| 模式 | 适用目的 | 必须记录 |
|---|---|---|
| source_native | 验证原尺寸交付能力 | 源尺寸、实际原生有效内容尺寸、原始细节限制 |
| declared_working_size | 在统一工作尺寸比较参考外观迁移 | 冻结工作 A、统一尺寸、缩放方法及与原尺寸实验不同的结论边界 |

网页建案例时提供选择及尺寸预览。运行后更改模式必须复制输入创建新任务，不能降低原任务标准。

四模型主实验默认采用可由全部选定配置满足的**统一、事前冻结工作画布**来比较外观迁移，并另外报告原尺寸能力。具体宽高由服务器 dry-run/capability 检查确定后冻结；若业务坚持原尺寸，则明确把能力不足计入失败，不用事后放大掩盖。

不应把不同模型各自更小的 A 混作同一输入。需要模型专用 padding 时，来源像素和规范化处理相同，分别记录变换；有效内容尺寸仍按公共要求验收。

### 9.4 调用预算与恢复

所有新 VLM 阶段进入已有 Journal/回执逻辑，先保存请求与提交事件，再保存真实响应和校验结果。操作身份绑定阶段、round、attempt、输入、合同和候选版本。无效响应消耗已发生的调用；人工导入不伪装成 API 调用。

设最多生成 G 个候选、每次请求一张：

| 调用 | 最大次数 |
|---|---:|
| 初始诊断 | 1 |
| 自动证据复核 | 1 |
| 初始 compose | 1 |
| 图像验证 | G |
| feedback refine | G−1 |
| 重写条件的语义审计 | G（若由 VLM 执行） |
| 同候选的自动追加复核 | 默认最多 1 次 |
| 原生 compiler | G，独立计数 |
| 图像调用 | G |

因此新四模型任务的文本阶段预算可设为 `3G+3`：单轮 G=1 为 6，最多三轮 G=3 为 12。确定性提示工作台无重写语义审计时上限为 `2G+3`，三轮为 9。这些是上限；未执行的阶段不计调用。额外重新编译不属于默认预算，须事前声明。

将工作台硬编码的 3/8 改为**新案例冻结 policy**；历史案例继续旧预算。分析预算耗尽时允许人工复核，仍禁止新增远程调用。

区分 request_count、returned_candidate_count、imported_candidate_count、compiler_calls、analysis_calls、unknown_submissions。已提交但无明确结果的请求保持未知；恢复或人工核对同一回执，不能盲重发。

费用/耗时采用已知零、已知值、未知三态。导入一张外部图只能证明本地导入数为 1；没有回执时不能推断外部生成次数或费用。

## 10. 新实验清单：三个场景批次、六个正式臂

### 10.1 选择最小兼容实现

本期**不把现有 hre_batch_v3 重写成任意混合合同引擎**。新增上层 study builder，将一次实验拆成三个合法子批次，复用现有 run_batch：

~~~text
legacy_reference:
    legacy_native_ab
    legacy_shared_ab
    legacy_aware_ab

retouch_reference:
    retouch_shared_ab
    retouch_aware_ab

source_only:
    legacy_aware_a
~~~

只在 retouch_reference 子批次的 case 中设置 reference_retouch_v2 和对应 delivery_requirements。native/A-only 不携带新合同。这既解决当前 case-level 透传限制，也避免一次批次的 shared planning 被新旧合同错误共用。

### 10.2 正式臂定义

| arm_id | strategy | 运行合同 | B 的运行时可见范围 | 目的 |
|---|---|---|---|---|
| legacy_native_ab | native | 旧 v3，无新字段 | 保留旧原生编译/编辑 A+B 语义 | 原生参考编辑基线 |
| legacy_shared_ab | shared | 旧 v3 | 旧 A/B 全链 | 旧统一表达 |
| legacy_aware_ab | model_aware | 旧 v3 | 旧 A/B 全链 | 旧模型适配系统 |
| retouch_shared_ab | shared | reference_retouch_v2 | 新 A/B 全链 | 新合同与统一表达 |
| retouch_aware_ab | model_aware | reference_retouch_v2 | 新 A/B 全链 | 新合同与模型表达指导 |
| legacy_aware_a | model_aware | 旧 restoration | 全链不读取 B 或 B 派生信息 | 真正 A-only 对照 |

native 仍使用该模型本身的原生编译路径，不等于“关闭 PE/PUP/Recaption/VGL”。shared 与 aware 都保留原生 compiler，差别是 Harness 的表达/策略指导；不能把它们命名成 compiler on/off。

### 10.3 共享规划与泄漏约束

- 旧 shared/aware 共享旧初始 intent；新 shared/aware 共享新初始合同。
- 跨模型共享的是模型无关规划，不共享某个模型原生 prompt/VGL。
- 新旧规划分别保存；shared planning key 包含场景、合同版本、输入、brief、区域、证据及规划配置 hash。
- A-only 的 brief、ROI 描述、诊断、证据、缓存、编译及内部验证均独立，只由 A 得到。
- B 可以被共同离线评价器查看；该评价记录不得回流到 A-only 的运行器。
- “保留由 A/B 得到的文字，仅从编辑器移除 B”是参考视觉条件消融，不能叫 A-only。
- 计划、离线评价合同和运行时配置分别存放；不能把包含 B 的上层 study 原样作为 A-only context。

### 10.4 上层 study 锁与 run 身份

建议 `front_camera_study_v2` 必含：

~~~json
{
  "schema_version": "front_camera_study_v2",
  "study_id": "front-retouch-v2",
  "code_commit": "<工程师完成后的实际提交>",
  "data_revision": "<冻结数据版本>",
  "models": ["<四个实际 catalog profile_id>"],
  "replicates": [{"replicate_id": "r01", "seed": 42}],
  "evaluation_contract_hash": "<共同评价合同集合>",
  "scenarios": ["legacy_reference", "retouch_reference", "source_only"],
  "planned_runs": []
}
~~~

每项 planned_run 至少包含：run_id、experiment_block_id、reference_variant_id、trajectory_id、pair_id、split、group_id、model_profile、arm_id、scenario、workflow_contract、replicate_id、seed_or_null、输入 hash、config hash、delivery/evaluation hash、预算和输出位置映射。

run_id 是稳定唯一键。不得只用 pair/model/arm/seed 猜关联，也不复用不同 task_mode 下同名 aware_single。输出目录和记录都带 block/variant/scenario/arm/replicate。一个 run 是一次系统任务或完整反馈轨迹；轨迹内候选不是额外独立 run，单独使用 candidate_id。共享候选通过 artifact hash 和 operation_id 关联，不能因此合并两臂的任务记录。

E3 复用 E1 首轮时，另建实验轨迹并记录 parent_run_id、shared_operation_ids；逻辑 run、轨迹、物理操作和图像工件是不同身份。只去重实际调用与共享标注成本，不合并实验分母。E1 原始参考使用 reference_variant_id=original，单轮也给出稳定 trajectory_id。

GPT 工作台单独使用 replicate_id；不支持 seed 的后端填 null，不能伪造相同噪声配对。四模型只使用实际接口支持并确实传入的 seed。

### 10.5 生成与运行接口

建议新增脚本：

~~~text
research/front_camera_20/scripts/build_study_v2.py
research/front_camera_20/scripts/run_study_v2.py
research/front_camera_20/scripts/export_study_report.py
~~~

职责：

- build：校验数据/任务、拆分三批次、冻结 planned_runs、预算与 hash；零模型调用。
- run：遍历已冻结批次，调用现有引擎，支持恢复；不隐式重建清单。
- export：读取计划与结果及最终人评，生成一个 Markdown；缺失运行仍保留计划行。

新增命令示例（实现后才可执行）：

~~~bash
python3 research/front_camera_20/scripts/build_study_v2.py \
  --dataset /data/front20/study-v2/dataset.json \
  --config /data/front20/runtime.json \
  --out /data/front20/study-v2/plan \
  --seeds 42 --check-files

python3 research/front_camera_20/scripts/run_study_v2.py \
  --plan /data/front20/study-v2/plan/study.lock.json \
  --out /data/front20/study-v2/runs

python3 research/front_camera_20/scripts/export_study_report.py \
  --study-root /data/front20/study-v2
~~~

恢复使用同一 plan/config；若提供 --resume，必须重新验证已冻结身份。冲突时拒绝，不能覆盖。旧 build_manifests.py 和旧报告仍支持历史实验，不改写其配置含义。

当前新版 README/RUNBOOK 必须指向实际实现分支和固定提交；不得让用户照新方案又切回旧实现。旧手册可标记“历史 v1 实验入口”并链接新版。

### 10.6 盲评准备、导入与裁决必须接通

现有 prepare_blind_review.py 只有总体评分字段，并把 source_baseline 排除为模型交付，不能直接承载新版逐目标评价和正确 S 类零编辑（S15）。保留其旧版行为，新增 `prepare_study_review.py` 和 `import_study_review.py`；允许工程师改为原脚本的显式 v2 分支，但必须保持下列责任。

1. **生成前冻结评价。** build 校验第 3.4 节的 evaluation_contract 与 baseline_record 完整、时间早于正式运行；缺少则拒绝正式 study lock。E2 每种参考变体使用对应合同，不套用 original 的判断。
2. **生成模型身份隐藏的评审包。** prepare 从 study.lock 和规范化 RunRecord 读取真实选中输出；绑定 canonical run_id、候选/源图像 hash、evaluation hash、review_protocol hash，生成 trial_id、匿名展示与逐目标表单。评审看到 A/B/C、共同目标和原生局部入口，看不到模型/arm/提示/内部 verdict。组织者私有映射不进入评审包；这属于 model-masked review，不称双盲。
3. **严格导入每人观察。** observation 至少包含 trial_id、rater_id、evaluation/candidate/protocol hash、全部 mandatory target_results、保护/自然度/严重损伤、relative_A_improvement、必要原因与时间。拒绝未知目标、缺必需项、过期 hash、重复/冲突覆盖。每位评审的完整联合判断由这些字段和冻结规则计算，不能由分项平均分推定。
4. **形成可追溯裁决。** rating_decision 至少包含 rating_id、trial_id、有效观察集合 hash、n_valid_raters、joint_task_support、joint_improvement_support、严重损伤否决/复核结果、rule_version、decision_source、adjudication_id、最终 task_verdict/improvement_verdict（pass/fail/unknown）及原因。规则自动汇总和人工裁决明确区分；人工裁决引用被裁决观察，不能覆盖原票。共同任务视觉裁决包含目标、保护和自然度，尺寸交付由各 run 的客观记录另判。
5. **关联所有计划记录。** 未启动、无交付、失败仍保留 run。诊断性候选可供观察但不能成为主成功分子。B 类失败回退保持失败；S 类必须确由 source_already_satisfied 分支交付冻结 A，不能从“文件刚好等于 A”推断。

baseline trial 可与多个正确来源的 S 共用，但复用键必须包含 pair_id、冻结 A hash、reference_variant_id、B hash、evaluation_contract hash、review_protocol hash；C=A 以冻结显示域像素身份核对。不同参考/合同必须重新评价。同图 G 结果也可复用合格视觉 trial，但保留其生成身份及真实成本，不改记为 S。

每个 run 独立保留 output_code、selected_kind、selection_reason、trial_id、delivery_status。合法 S 只有共同视觉裁决 pass 且本 run 交付 pass 才能计任务成功；S 的相对 A 改善为 0、有效编辑改善为 false。若其事前 baseline_status=needs_edit，仍留在改善率分母。共享 trial 只减少重复标注，不减少 planned run，也不制造独立人评样本。

建议新增命令（均待实现）：

~~~bash
python3 research/front_camera_20/scripts/prepare_study_review.py \
  --study-root /data/front20/study-v2 \
  --out /data/front20/study-v2/review-v001

python3 research/front_camera_20/scripts/import_study_review.py \
  --study-root /data/front20/study-v2 \
  --review /data/front20/study-v2/review-v001 \
  --observations /data/front20/study-v2/review-v001/completed-ratings
~~~

这些 JSON/CSV/HTML 和照片只在服务器使用；最终 exporter 读取冻结裁决并写入一个 Markdown，用户无需回传它们。评价导入目录与执行器物理/逻辑隔离，不回流到 A-only 或正式反馈循环。

若评价合同准备或离线辅助评价使用 VLM，其调用与耗时单列为 evaluation_cost；不藏入人工零成本，也不混入编辑器自身的线上预算。

## 11. 单文件报告与统计语义

### 11.1 一个输出，两类读取器

新 report adapter 将 v3 batch/report 与 workbench case 转为统一 RunRecord；再由同一 Markdown renderer 输出。

工作台新增“复制/导出实验报告”按钮和 report.md 入口。单案例未关联 planned study 时，只生成单案例记录，显示“计划覆盖未知”，不从已有文件推断完成率。

### 11.2 输出类型与成功分开

建议报告输出事实码：

| 码 | 含义 |
|---|---|
| G | 已交付生成候选；质量与交付条件另看结果列 |
| S | 声明已满足并交付冻结 A；正确性仍需共同离线判断 |
| B | 失败后回退原图 |
| X | 没有有效选中交付 |
| P | 未启动、未完成或提交结果待核对 |

保留原 execution_status、quality_status 与 selected_kind，供核查。S 不自动等于实验成功，G 不自动等于可用；交付 fail/unknown 不应被事实码掩盖。旧 exporter 的 C/F 等历史显示码按旧版本解释，不直接混表。

新文档必须能显示：

- 方法内部判断。
- 共同离线目标判断。
- 内容保持/自然度。
- 原生交付。
- 相对 A 的实际改善。
- 待评、未知和失败原因。

### 11.3 两个核心指标

**任务完成率：** 在指定实验块/参考变体/模型/臂的全部正式 planned run 中，已完成任务的有效选中结果满足共同参考目标、内容、自然度和交付要求的比例。允许生成交付与经共同标准确认的正确零编辑；运行失败的诊断性候选和原图回退不进入成功分子，也不能伪装成零编辑成功。

**有效编辑改善率：** 在同一统计分层中，事前 baseline_status=needs_edit 的全部 planned run 中，已完成任务的有效选中生成输出获得相对 A 的有意义改善，且共同目标、内容、自然度和交付均通过的比例。

E1 主表纳入条件为 experiment_block_id=E1、split=test、reference_variant_id=original 和六个核心臂；E2 干预按 reference_variant_id 单列；E3 按轨迹及预算模式单列，不能把三轮候选并入 E1 分母。E0 开发控制不进入正式指标。三个实验块可出现在同一 Markdown，但各自显示计划数、缺失与评价覆盖。额外保存 delivery_role=selected_system_output/diagnostic_candidate/source_fallback，避免有效图像文件被误当完整成功任务。

另外报告错误停止、内容损伤、交付失败、回退、未知和未评比例。baseline_status=uncertain 单列，不在看见结果后调整分母。

推荐报告 confirmed_success/planned、evaluated/planned、unknown/planned，并给出在未知项全部失败/全部成功时的范围；只有评价完整时才给出最终点估计。必要时同时给已评子集比例，名称必须写明“已评子集”。

每个 run 输出 task_success 和 effective_edit_success，取 true/false/unknown；另以 in_task_denominator、in_edit_denominator 表示本统计层是否纳入。明确失败为 false，尚未运行/复核未结/未评为 unknown；不因未知都在分母中便把它们的实际质量写成失败。S 的 effective_edit_success=false，无论是否纳入改善分母。

task_success 由合法完成与选中身份、共同视觉 task_verdict 和本 run 交付结论按三值逻辑计算；确定失败优先于未知。B 或已确认无交付的 X 为 false；P 缺结果时为 unknown。effective_edit_success 还要求有效生成输出与正向 improvement_verdict。评价完整但系统未合法完成的诊断图不得成为成功。

文档应能依据这些字段和冻结裁决复算 success，不要求接收方猜图片质量。多数票只能从原始投票或服务器已冻结裁决得出，不能用均分反推。目标逐项多数通过也不替代联合 task_verdict。

### 11.4 单文件必须包含的字段

- 代码/数据/合同版本；模型、VLM、compiler 身份与实际参数。
- 总样本数、dev/test、场景组、重复数、计划臂数。
- 全部 planned run 的身份及状态；不能只列已成功的结果。
- 每个 mandatory 目标的结果；失败/未知的具体 ID 和短观察。
- 保护/自然度/参考内容污染/无依据细节检查。
- 原生尺寸、有效内容尺寸、交付尺寸、变换、交付结论。
- 生成请求、返回候选、外部导入、分析与编译调用、耗时/费用覆盖。
- 人评来源、人数、裁决规则与最终观察。
- 协议偏离、缺失和结论边界。

允许按 pair×model 分组，把六臂和重复压缩在同一组内；**每个预定 run 必须保留一项可数记录**，不能只保留均分或挑选案例。失败/未知行自动展开一句原因。

renderer 必须遵循最小可复算协议：

- 每个 run 的 block/variant/trajectory/parent、pair/group、model/profile、arm、replicate/seed、split 与 evaluation/config ID 在行内或同文档字典中完整还原；唯一 hash 本身不承担这些语义。
- 每个 rating_id 的联合 task/improvement 最终裁决、有效人数、联合支持数、规则版本和裁决来源在同文档可查。未知人数填 unknown，不能伪造投票；有裁决无原票时不输出一致性统计。
- 每个 run 引用一个 geometry_id；同文档列出 A 工作尺寸、原生画布、有效内容、交付尺寸、全部变换与客观检查。成功行也必须有映射，不能只给失败行尺寸。
- 每个 run 显式输出两项 success 和两项分母标记。exporter 从逐行记录重算汇总、计划覆盖、未知范围和配对映射，核对后再写表，不直接复制预先算好的总数。
- 短 ID 在报告内必须唯一，碰撞时自动加长；所有引用需能解析到本文件。缺失数据标 unknown/not_recorded，并报告影响，不能随意补默认值。

### 11.5 输出与数据保护

用字段允许列表生成 Markdown，不 dump 原始 runtime、config、state、异常栈或回执。公共模型 ID、revision、配置短 hash、匿名 pair/group ID、必要参数和错误码可以输出。

照片、完整文件路径、原始照片名、敏感 OCR、密钥、endpoint、base64、原始投票、完整测量及日志留服务器。报告成本为 unknown 时不能填 0。导出不覆盖人工已经编辑的报告，改用新文件名或显式另存。

输出包含 BEGIN_OF_REPORT、END_OF_REPORT、预期 run 数和实际明细数。很长时用户可以分段粘贴同一份文档，仍然不要求分散附件。

## 12. 文件修改地图与分批实施顺序

### 12.1 文件地图

下表 reference_policy.py、v3/、retouch/ 的共同路径前缀是 `engine/src/hre/`；实验脚本位于 `research/front_camera_20/scripts/`。其他路径相对仓库根目录。新增文件名可以在保持职责的前提下调整，最终 README 必须准确指向实际路径。

| 文件/模块 | 要修改的职责 |
|---|---|
| 新增 reference_policy.py | 可执行目标、限制渲染、反馈与交付/报告映射的公共纯函数 |
| 新增 v3/workflow_contracts.py | legacy/v1/v2 显式分派 |
| 新增 v3/reference_retouch_v2.py | 新 schema、证据复核、统一 feedback、冻结投影 |
| v3/reference_retouch.py | 保留 v1；必要的路由调整不改变旧模板语义 |
| v3/contracts.py | 新任务 policy、版本、目标与请求合法性 |
| v3/stages.py | evidence_review/condition_audit 的模板、请求与响应校验 |
| v3/runner.py、runner_journal.py、cli.py | 新状态、有效诊断、统一反馈决策、类型化复核CLI、预算/幂等与恢复 |
| v3/common.py | 每目标完整渲染条件限制与优先级 |
| 新增 v3/condition_audit.py | 原生条件覆盖、真实位置校验与放行规则 |
| v3/dispatch.py | 实际条件、合同与审计身份绑定 |
| v3/qwen.py、firered.py、flux.py、fibo.py | 接入完整表达、保留原生输出和审计所需信息 |
| v3/report.py | 导出新工件、分项状态、复核历史摘要、原生交付 |
| retouch/contracts.py、prompts.py | 新版目标、复核与反馈；历史策略分派 |
| retouch/workflow.py | ground/evidence_review、review、交付预检、延后画布、可配置预算 |
| retouch/server.py、retouch/static/app.js/index.html | 对应按钮/API、尺寸预览、待复核与单 Markdown 导出 |
| 新 study builder/runner/exporter | 三批次六臂、run_id、规划隔离、完整分母 |
| 新 prepare_study_review/import_study_review 或旧脚本显式 v2 分支 | 第3.4节评价合同、逐目标盲评、S类baseline映射、观察导入与联合裁决；保留旧版评分语义 |
| front_camera_20 README/RUNBOOK/报告模板 | 唯一当前入口，保留历史方案入口与单文件回传 |
| 有关 engine/tests | 按第 13 节增加针对性机制用例 |

### 12.2 六个可独立审查的实施批次

| 批次 | 主要任务 | 完成出口 |
|---|---|---|
| P0 版本与合同 | 路由、公共字段映射、v2 schema、历史保护 | 新旧案例明确分派，未知版本拒绝 |
| P1 语义传递 | 目标可执行性、conditional 限制、原生条件审计 | 每项关键限制可追溯到实际条件 |
| P2 复核与反馈 | evidence_review、effective diagnosis、统一 feedback、review | 证据不足与结果不确定都有合法恢复路径 |
| P3 交付与恢复 | 延后画布、preflight、预算、未知提交/幂等 | 可预知不合格不花图像调用，恢复不重复提交 |
| P4 实验与报告 | 三批次六臂、共同评价冻结/盲评/导入/裁决、单 Markdown | 用户能只用一份文档复算身份、分母与关键结果 |
| P5 集成与文档 | 负例检查、打包、运行说明、真实部署待执行项 | 工程师交付同一入口与明确 NOT_RUN 边界 |

P1 与 P2 可在 P0 后并行，P4 可先做规范化 report adapter，最终在 P3 后联调。每批使用小而可审查的提交；不要把所有变动压成无法定位的一次大提交。

### 12.3 完成定义

工程交付完成须同时满足：

- 已确认的 F1–F7 均有对应实现和验收记录。
- 两个入口使用相同目标语义，但能恢复各自历史版本。
- 不通过修改成功标准、隐式重试、漏记缺失行来“修复”失败。
- 实际编译、输入角色、工作画布、原生输出和候选选择均可追溯。
- 新批量清单确实启用新合同，source-only 全链隔离。
- 单 Markdown 能完整表达已生成、零编辑、回退、交付失败、待复核和未运行。
- 真实 GPU/模型实验未完成的字段保持 NOT_RUN，不能因软件通过填写画质结论。

## 13. 工程验收：针对真实缺口，不替代模型实验

工程师在修改后执行必要的软件检查；用户负责服务器真实权重与画质实验。无需为纯文字改动增加无意义测试，也不要反复跑整套测试替代针对性用例。

| 编号 | 场景/输入 | 必须结果 |
|---|---|---|
| A01 | 载入旧 v3、reference_v1、workbench delivery_v2 | 请求身份、历史状态与验收语义不变 |
| A02 | 未知版本或 v1 planning 导入 v2 | 明确拒绝；不静默回退/升级 |
| A03 | mandatory conditional 缺限制 | 拒绝冻结 |
| A04 | optional + incomparable/unknown 放入 targets | 拒绝；保留待复核/排除说明 |
| A05 | 合法条件“只匹配中间调，不匹配阴影绝对亮度” | 提示及原生条件审计可定位完整限制 |
| A06 | 原生重写遗漏必需目标/反转限制 | 审计失败，图像调用为 0 |
| A07 | 审计引用不存在路径；FIBO无source_vgl | 前者拒绝；后者记录diff不可用并走真实语义审计，不伪造字段一致 |
| A08 | needs_evidence → 实测支持；自动仍不足后人工解决 | 保存新诊断，使用effective diagnosis进入compose；不要求不存在的candidate/冻结合同 |
| A09 | 证据仍不足；生成前condition audit uncertain | 不生成；人工按对象hash解决后，放行同一条件且仅调用一次图像接口 |
| A10 | 使用另一案例证据或旧 evidence hash | 拒绝，不能推进目标冻结 |
| A11 | 冻结后改 ROI、mandatory 或阈值 | 拒绝；新合同 revision 才能变更 |
| A12 | partial有反馈但issues为空；只有保护/伪影revise反馈 | 目标反馈正确refine；保护/伪影通过合法scope_updates修订，冻结事实不变 |
| A13 | partial无可靠修正、stop、manual_review与混合反馈 | 分别停止/待人工；stop不refine，必需未知先复核，不自动补采样 |
| A14 | refine 引用旧候选/旧验证/未知目标 | 拒绝；当前合同不变 |
| A15 | uncertain 后人工完整复核通过 | 追加版本，图像计数不变，重新计算结论 |
| A16 | 第三张候选 uncertain，生成预算耗尽 | 仍能人工复核；不能追加生成 |
| A17 | 重复 review request_id | 幂等返回；不重复追加/计数 |
| A18 | 两次独立复核互相冲突 | review_conflict，需有记录裁决 |
| A19 | 3072×4096 需要编辑，规划2480×3296，要求原尺寸 | 预检失败；图像调用0 |
| A20 | 同尺寸 A 已满足且交付要求不超过 A | 交付冻结 A，零编译零生成 |
| A21 | no-edit 但要求比 A 更大 | 交付失败仍零生成，报告不冒充成功 |
| A22 | padding 达标但有效内容不足 | 原生源尺寸门槛失败 |
| A23 | 外观全pass，但原生尺寸fail或细节required且unknown | 整体不接受，分项原因可见 |
| A24 | evidence_review/audit/edit 请求提交后结果未知 | 恢复不盲重发，回执可核对 |
| A25 | 三批次六臂，同时存在E1/E2/共享首轮E3 | 合同正确；native/A-only无新合同；E1仍为24NR，其他块独立分母 |
| A26 | A-only planning/ROI/cache/context | 无 B 或 B 派生内容；共同离线评价不回流 |
| A27 | S/B/G复用相同图像的trial；参考变体不同 | 只在完整评价身份相同时复用；S/B来源保留，S不自动成功，B不进成功分子 |
| A28 | 计划100项、只返回80项；同文档可复算 | 分母100且20项缺失可数；身份/geometry/rating映射完整，逐行重算与汇总一致 |
| A29 | 成本缺失、外部导入、已知零调用 | 分别unknown/imported/known_zero，不混写 |
| A30 | 生成 Markdown 后含密钥/endpoint测试标记 | 允许列表过滤；报告无敏感标记 |
| A31 | 用户手填报告已存在 | 默认拒绝覆盖，另存新版本 |
| A32 | 双入口导出同一规范化样例 | 统计口径一致，BEGIN/END与明细数闭合 |
| A33 | 共享首轮的 feedback/resample | 首轮条件/候选hash相同，物理调用不重复计数 |
| A34 | 错误hash/缺目标/过期的执行复核或离线人评导入 | 有拒绝原因，不错误推进；完整人评按联合规则裁决，不由分项多数拼成功 |

最终只补一次与改动相称的集成检查和安装/静态资源检查；真实接口及画质验证放服务器执行。工程记录区分“静态核对、合成用例、真实 API、真实模型、人工画质”五类证据。

## 14. 服务器实验计划：先证明机制，再比较效果

### 14.1 两个主要待验证主张

| 主张 | 最低有说服力的证据 | 必须排除的替代解释 |
|---|---|---|
| C1：新参考合同及其控制流程能提高有保真约束的任务完成效果 | 同模型、同冻结输入/交付协议、同生成上限下，新 aware 对旧 aware 的配对结果；共同独立评价；失败/未知完整保留 | 更容易的自定目标、更多候选、只做通用提亮、漏记失败 |
| C2：在同一合同下，保留模型原生接口并加针对性表达有实际收益 | 每个模型的新 aware 与新 shared 比较；实际条件审计；同时报告质量和成本 | 模型本体变强、换权重/参数、某一臂拥有额外输入 |

主张尚未成立。当前工程任务的目的是使它们可验证，不预写正结果。单个模块的独立因果作用，需要相应移除实验；六臂主结果只能支持完整变体的效应。

### 14.2 数据与划分

首先在数据清单填明 raw_image_count、paired_case_count、dev_pair_count、test_pair_count、scene_group_count、subject_count，不把“20张成对”自动解释为20对正式测试。

默认建议：

| 实际数据 | 开发/正式建议 | 解释边界 |
|---|---|---|
| 20对总样本 | 4对开发 + 16对正式 | 小规模配对研究 |
| 20张合计，即10对 | 2对开发 + 8对正式 | 更小规模探索性研究 |
| 20对正式，另有开发集 | 保留20对正式 | 开发集单列，不再次混入 |

正式 N 始终由 split=test 计算。同一场景组、连拍或近重复不跨开发/正式；记录同一人物重复出现的事实。开发样本用于调整提示、阈值、工作画布和接口，正式样本冻结后不逐图改参数。

必须完成的数据字段：

- S26 baseline checkpoint/代码 revision、prediction 的来源与范围、是否见过这批图。
- linear prediction 到 SDR A 的具体变换、transfer function、色彩空间、位深/范围、裁切和方向。
- iPhone B 的来源格式及 SDR 导出过程；ICC/HDR/gain map 不明确时先处理，不直接当 sRGB。
- 源图与参考图配对、姿态/照明/遮挡差异及独立 ROI。
- 原图 hash、冻结 A/B hash、公共工作画布 hash、合法变换。
- 模型、VLM、原生 compiler 与依赖 revision；量化/精度/设备、采样参数。

保留源 linear 与原始照片用于服务器追溯；编辑器输入使用已声明的显示域。不要把像素是否线性作为由文件扩展名猜测的事实。

### 14.3 五个实验块与顺序

| 块 | 内容 | 运行阶段 | 必须/可选 | 能回答的问题 |
|---|---|---|---|---|
| E0 | 数据、接口、颜色、A+A no-edit、明显需编辑、交付失败、困难验证器负例 | 开发集 | 必须 | 控制器和执行链是否符合任务 |
| E1 | 四模型六臂单轮主矩阵 + 原始 A 基线 | 冻结正式集 | 必须 | 新旧系统与模型表达指导的整体效果 |
| E2 | 参考干预：暖/冷属性替换、错配参考、已知可解释调色变换 | 预选小子集 | 至少完成可支撑参考利用判断的控制；规模事前冻结 | 模型是否对正确参考属性做出响应 |
| E3 | 三次上限反馈 vs 固定条件重采样 | 主结果有信号后，预选子集 | 可选 | 收益是否来自有依据反馈 |
| E4 | 失败归因、可视化人评、统计与单文档报告 | 复用全部输出 | 必须 | 哪些结论成立，哪些仍不确定 |

E0 的 A+A 精确像素控制只验证明确 no-edit 任务的控制路径；若要验证 VLM 能否识别“外观已接近但像素不同”，必须另做真实困难 no-edit 样本。二者不能混为诊断能力证据。

E2 的已知变换只覆盖其定义的颜色/曲线问题，不自动代表真实相机 look。错配 B 应限制/拒绝不支持属性，而非奖励任何输出都向 B 靠近。参考属性替换应尽量保持内容和几何不变；若重拍导致光照变化，须标记混杂因素。

### 14.4 六臂对照的解释

| 对照 | 支持的解释 |
|---|---|
| legacy_aware_ab − legacy_shared_ab | 旧合同下的模型表达指导效应 |
| retouch_aware_ab − retouch_shared_ab | 新合同下的模型表达指导效应 |
| retouch_shared_ab − legacy_shared_ab | 新合同及其新增阶段的整体效应 |
| retouch_aware_ab − legacy_aware_ab | 新参考系统在适配策略下的整体效应 |
| legacy_aware_ab − legacy_aware_a | 旧参考模式完整流程相对 A-only restoration 流程的总效应 |
| retouch_aware_ab − legacy_aware_a | 完整新参考系统相对无参考系统的总效应 |
| 四模型在同一 arm 下比较 | 固定策略下各完整系统的质量/成本表现 |

新旧 A/B 对 A-only 的差值均不能单独证明 B 的因果作用：当前 reference_enhance 和 restoration 的 task_mode、提示目标也不同（S4）。六臂保留完整流程比较；若以后要隔离参考信息本身，需另做除 B 信息外机制匹配的消融。不能用不同采样、不同工作尺寸的输出直接归因为架构差异。

所有模型内部的成对实验固定权重、原生 compiler、采样和输入预处理。不同模型采用各自事前冻结的合理配置，并报告实际成本；相同 seed 数或相同步数不等于计算量相等。

### 14.5 预算

设 M=4，N=正式对数，R=预定 seed/重复数，六臂每 run 最多一张：

~~~text
核心 planned runs = 6 × M × N × R = 24NR
核心图像调用上限 = 24NR
~~~

零编辑、输入拒绝、编译审计失败会降低实际图像调用，但不得从计划分母删除。

| N | R | 计划 run / 单轮生成上限 |
|---:|---:|---:|
| 16 | 1 | 384 |
| 16 | 3 | 1152 |
| 8 | 1 | 192 |
| 20 | 1 | 480 |
| 20 | 3 | 1440 |

默认先冻结 R=1 的完整六臂，不为节省次数先选“看起来好的”模型。需要估计随机波动时，再按事前定义的扩展执行额外重复；开发阶段可观察重复性，但不能从正式单次输出宣称稳定性。

若 E2 对 K 个预选 pair、M 个模型、R 次重复，每个 pair 增加 J 个参考条件，只运行新 aware 单轮，则新增上限为 M×K×R×J。A+A 控制的计划记录仍存在，正确 no-edit 实际图像调用为0。

GPU 小时、金额和标注小时不在未测量前虚构。用开发样本实际耗时/显存与每例人评时间估算，并保留区间；共享 planning 的成本单列，防止给每个模型重复计费。

### 14.6 反馈实验的公平比较

默认比较“同为三次生成上限”的系统，不声称实际算力相等。

- feedback3：有支持的残差才修订；提前完成或无依据时停止。
- resample3：冻结初始条件，按事前 seed schedule 重采样。
- 同一 source/reference、同一初始合同与首轮实际编译条件。
- 首轮候选确实复用时记录同一 artifact/hash，不重算成两次物理生成。
- 两臂用同一事前定义的候选选择规则。系统内部选择与人类 oracle best-of-k 分开报告，不能把人挑最好图当系统交付。
- 全部候选保留；不因某臂多出图就只展示最好的一张。
- 每轮仍从原始 A+B 生成；反馈不改变冻结目标。

两臂各三次、完全不共享时上限 6MKR；共用首轮时 5MKR；若首轮可完全复用核心新 aware 结果，新增物理调用上限 4MKR。适用条件必须逐项核对，不能只因图片文件相同就假设所有请求条件一致。

如果研究需要固定各三候选，另设实验调度模式：无支持修正时反馈臂剩余调用明确标为原条件重采样，不编造反馈；不改变生产任务的已完成状态。实际失败或未知提交不得盲补，必须记录偏离。

### 14.7 人工评价与统计

推荐三人独立盲评；若只有一人，则按一人观察报告，不能编造多数票或一致性。查看 A/B/C、共同离线标准和需要的原生局部；隐藏模型、arm、生成提示和内部 verifier verdict。

每位评审记录：

- 各 mandatory 目标：achieved/partial/unmet/uncertain。
- 内容保持：pass/minor_issue/major_damage/uncertain。
- 自然度与伪影：pass/fail/uncertain，并说明具体观察。
- 相对 A 的外观改善：−2 明显退步、−1 退步、0 无明显变化、+1 改善、+2 明显改善。
- 最终任务判断与需复核项。

多人判断采用事前冻结规则。建议以“至少2/3评审分别满足完整联合条件”为通过基础，不能把不同人的各项目多数票拼成实际上无人支持的完整成功。任何明确严重内容损伤进入复核，确认后判失败。minor_issue 是否可接受必须事前规定并记录裁决。

任务完成看共同目标、内容、自然度与交付；有效编辑改善还要求在 needs_edit 子集上获得正向改善。均分/中位数仅作描述，不反推投票。只有最终裁决而没有原始票时，不计算评审一致性。

主分析按同 pair 配对，重复先在 pair 内聚合。置信区间和重采样以 scene_group 为单位；同人物多场景不支持人群泛化。小 N 优先报告每对胜/平/负、差值和区间；未排除零效应时写“未证实”，不强行选冠军。

四模型对应多个主要检验时预先声明比较族；若报告显著性可用 Holm 等多重比较调整。不要把每个 seed、每个 crop 或每个目标都当新增独立样本。

A/B 非对齐，不用全图 A/B PSNR、SSIM 作为主质量依据。可比 ROI 的 L*/色度/影调关系作为辅助描述，单列照明或材质混杂。A/C 内容指标需要允许合法颜色变化；高分或自然观感都不认证原始高频细节真实性。

### 14.8 决策规则

- 机制失败或数据/身份无法核对：停止该阶段扩展，保留结果，修复后建立新 revision。
- 新合同的配对任务完成与有效改善提高，且没有确认的严重内容损伤、成本可接受：支持继续该模型配置；强度依据区间和样本范围表述。
- 方向有利但区间宽/跨 seed 不稳：保留候选方向，增加独立场景或重复后再判断。
- 新流程只增加调用、没有改善或更易停在 uncertain：回看诊断质量、合同难度和审计误拒，不能直接进一步堆约束。
- 模型表达指导只对部分模型有效：按模型保留；不要求四模型统一胜出。
- 已确认损伤或参考目标退步：不因平均“更好看”抵消，明确失败机制。

除非有独立标定与更多场景证据，不能将本实验写成“恢复了 iPhone 的真实 ISP”“学会完整相机风格”或“认证细节真实”。

## 15. 运行里程碑与工程进度表

本表嵌入同一文件，避免额外交付 tracker。所有状态初始为 TODO/NOT_RUN；工程师只填真实完成情况。

| 里程碑 | 输出 | 放行条件 | 当前状态 |
|---|---|---|---|
| M0 基线与范围 | 固定 commit、数据口径、模型身份清单 | 不混用历史版本；未知字段列明 | TODO |
| M1 新合同与语义 | P0/P1 完成 | 限制不丢失，原生条件可追溯 | TODO |
| M2 闭环恢复 | P2/P3 完成 | 证据/人工复核/反馈/预算负例通过 | TODO |
| M3 实验与回传 | P4/P5 完成 | 三批次六臂合法，单Markdown可复算 | TODO |
| M4 开发实跑 | E0和开发校准 | 附件/颜色/尺寸/身份正确；冻结正式配置 | NOT_RUN |
| M5 正式核心 | E1及预定E2 | 全计划行可追踪，独立人评完整或明确缺失 | NOT_RUN |
| M6 反馈扩展 | E3 | 主结果有支持，预算与选择器已冻结 | NOT_RUN |
| M7 最终回传 | E4 | 一个Markdown含全部必要记录与边界 | NOT_RUN |

每个修复记录：问题编号、代码提交、已执行验收编号、结果、未覆盖项。不得只写“测试通过”而省略验证范围。

工程师开工建议：

1. 从固定基线建立自己的工作分支，检查是否存在后续已完成修复。
2. 先实现新版本路由和共享数据规则；旧案例作为兼容样例保留。
3. 分批实现并记录第13节结果。
4. 把所有新增命令实际跑过 --help/无模型构建检查后写入新 RUNBOOK。
5. 交付代码、唯一当前运行入口和本文件更新版；模型实验字段保持 NOT_RUN。

本方案不要求现在配置远端 API、购买算力或替用户执行服务器实验。

## 16. 唯一回传文档模板

以下模板由导出器自动填入事实；缺少的人评与观察由用户补写。**最终只复制粘贴一份 EXPERIMENT_REPORT.md。** 原始图像与日志全部留服务器。实际模板不能把省略号当已记录结果；生成器须按 planned_runs 自动展开全部预定记录。

---

BEGIN_OF_REPORT

# HarnessIR 参考 Retouch 实验报告

## A. 身份、范围与数据

- 报告版本：
- study_id：
- 执行日期：
- 代码 commit：
- 数据版本/短 hash：
- 实际原始图像数 / 配对数：
- dev / test 对数：
- 场景组数 / 人物数：
- 模型范围：
- 工作台开发记录是否单列：
- S26 baseline checkpoint / prediction 来源：
- prediction → SDR A 的转换：
- iPhone B 的 SDR/色彩处理：
- A/B 不对齐及主要混杂情况：
- 公共工作尺寸 / 原尺寸交付模式：
- 共同离线评价合同版本/短 hash：
- 人评人数、盲态、投票与裁决规则：
- 审计方式：结构 / VLM / 人工：
- 复核与未知项处理规则：
- 完成状态：NOT_RUN / PARTIAL / COMPLETE：

## B. 模型与冻结配置

| 模型 | 实际权重ID/revision | 原生compiler/revision | 精度/量化 | 关键采样参数 | VLM配置 | 工作画布 | 配置短hash |
|---|---|---|---|---|---|---|---|
| Qwen | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 |
| FireRed | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 |
| FLUX | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 |
| FIBO | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 |

GPT/外部开发线单列：实际声明模型、身份是否核对、unknown原因、repeat标识；不混入四模型表的分母。

## C. 共同评价目标与输入基线

每对样本至少列出实际 mandatory 目标的语义和标准，不能仅给无法从文字理解的 hash。

| evaluation_id / pair / group / reference_variant | baseline_status与事前记录ID | 目标ID与必需性 | A/B区域与属性 | 冻结完成标准 | 可比性与限制 |
|---|---|---|---|---|---|
| 自动按评价合同展开 | needs_edit/already_satisfied/uncertain | 待填 | 待填 | 待填 | 待填 |

- 各 evaluation_id 的保护/伪影/自然度要求、正向改善门槛、review_protocol与规则版本：
- 事前 baseline_status 与后续独立裁决冲突时，列明冲突及原分母保持情况：

## D. 计划与覆盖

- 各实验块 E1/E2/E3 的正式 N / R / reference_variant：
- 计划臂数：
- 预期 planned run 数：
- 实际明细行数：
- 未启动 / 运行失败 / 提交未知 / 待复核 / 未评数量：
- 新旧合同与A-only规划是否隔离：
- 所有 source/reference/config hash 是否一致：
- 发现的冻结不一致与处理：
- 费用/耗时测量覆盖率：

## E. 汇总结果

| 实验块/变体/模型/臂 | 计划数 | 已评数 | 确认任务完成数 | needs_edit分母/有效改善数 | 正确零编辑数 | 错误停止数 | 确认损伤数 | 交付失败数 | 未知数 |
|---|---:|---:|---:|---|---:|---:|---:|---:|---:|
| 按四模型六臂自动展开 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 |

- 主要配对比较：新aware − 旧aware；新aware − 新shared：
- 每对胜/平/负：
- 效应量及区间：
- 重复与场景组聚合方式：
- 尚未完成评价时的已确认比例与可能范围：
- 内部verifier通过率仅作附加诊断，不能替代人评：

## F. 全部逐run记录与评价字典

事实码：G=生成交付，S=声明已满足返回A，B=失败回退，X=无有效交付，P=未完成/待核对。
检查状态 P/F/U 表示 pass/fail/unknown，与事实码所在列区分；“未评”不得写0。可以按 pair×model 分组压缩显示，但每个 arm/replicate 都必须保留独立记录。以下字典与结果表都属于这一份报告，不要求另交附件。

### F1. 完整运行身份

可把相同字段放组标题，组标题必须明确适用的 run_id，不能只给一个无法解码的 hash。

| run_id | block / variant / trajectory / parent | pair / group / split | model / profile / config | arm / replicate / seed | evaluation_id | 输入短hash |
|---|---|---|---|---|---|---|
| 自动按全部planned run展开 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 |

### F2. 联合评价与裁决字典

同一 trial 可供多个 run 引用，保留全部关联；没有评价的 run 填 rating_id=none。人数不可核对填 unknown。任务视觉裁决涵盖目标、保护、自然度；交付在 F3 按各 run 判定。

| rating_id / trial_id | evaluation_id / 图像短hash | 有效人数 / 完整任务联合支持数 / 完整改善联合支持数 | 严重损伤与复核 | task_verdict / improvement_verdict | 规则版本 / 来源 / adjudication_id | 原因摘要 |
|---|---|---|---|---|---|---|
| 自动按被引用裁决展开 | 待填 | 待填 | 待填 | pass/fail/unknown | 待填 | 待填 |

### F3. 每个计划run的结果

target状态串包含共同合同的每个必需ID；可用 `全部achieved(t1,t2)` 等明确表示，失败/未知项在G展开。改善分值只作描述，成功依赖F2的联合裁决。

| run_id | 事实码 / 执行状态 / delivery_role | 内部判断 | 必需target状态 / 内容 / 自然度 | rating_id / 相对A改善 | geometry_id / 交付 | task_success / effective_edit_success | 任务分母标记 / 改善分母标记 |
|---|---|---|---|---|---|---|---|
| 自动按全部planned run展开 | 待填 | 待填 | 待评 | none/待评 | 待填 | true/false/unknown | true/false |

F3行数必须等于全部planned run数；F1身份与F3一一对应。汇总E由F3及本文件字典重新计算。缺失输出仍有F3行，不能因没有rating_id被删除。

## G. 必需失败、复核和交付明细

### G1. 全部交付几何字典

每个run都必须引用下表，包括成功、S零编辑和失败。共享相同几何可复用geometry_id，无原生输出填not_available。

| geometry_id | 冻结A工作尺寸 | 原生画布尺寸 | 原生有效内容尺寸 | 交付尺寸 | padding/裁切/缩放及顺序 | 冻结要求 / 客观交付检查 |
|---|---|---|---|---|---|---|
| 自动按被引用记录展开 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 |

### G2. 必需失败、未知与协议异常

| run_id | 目标/保护/约束ID | 状态与具体观察 | geometry_id | 审计/复核修订 | 停止/失败原因 |
|---|---|---|---|---|---|
| 对所有失败/未知/协议异常自动展开 | 待填 | 待填 | 待填 | 待填 | 待填 |

- 所有通过项可用紧凑目标状态串表示。
- 必需项fail/unknown必须写一句实际观察。
- 复核后的结果注明原结论、追加证据、来源和裁决；原生尺寸不足不能被人评外观pass覆盖。

## H. 调用与成本

| 实验块/模型/臂 | 图像请求 | 返回候选 | 外部导入 | 分析调用 | compiler调用 | 其中条件审计调用 | 未知提交 | 可核对耗时/费用 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 自动展开 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填/unknown |

- 共享planning成本：
- 离线评价/合同准备调用及人工标注成本：
- 共享首轮候选与物理调用去重方式：
- 表中analysis_calls已包含VLM条件审计，不能重复相加；compiler独立计数：
- 已知零调用与未提供成本的区分：
- GPU/显存测量方法及覆盖：
- feedback为同上限还是同实际候选数：

## I. 关键观察与协议偏离

- 最明显的参考跟随改善：
- 最明显的内容/自然度失败：
- conditional限制是否进入实际条件并被输出遵守：
- 证据复核是否改变了正确决策：
- 错误no-edit与不必要编辑：
- 反馈改善是否超过重采样：
- 真实A+A、错配B、已知变换控制的结果：
- 数据/配置/预算/评价偏离及影响：
- 缺失结果与尚需完成的评价：

## J. 结论与下一步

- C1：支持 / 部分支持 / 未证实 / 反对；依据：
- C2：支持 / 部分支持 / 未证实 / 反对；依据：
- 建议保留的模型/策略与适用场景：
- 不应继续投入的路径及理由：
- 最关键未解决问题：
- 下轮最小验证动作：
- 本报告仅有文字回传，图像质量判断依据服务器端实际人评；接收方未独立查看照片的部分不能写为独立视觉复核。
- 若未提供原始投票，仅可分析最终裁决，不能重算评审一致性。

**预期记录数：**  
**实际记录数：**  
**缺失记录数：**

END_OF_REPORT

---

## 17. 可直接复制给工程师的任务说明

> 请基于 HarnessIR 的固定提交 16dee77487e4e13f76963f48bc4611d046bd0afe，按本文件实施参考 Retouch 完善，不执行真实画质实验、不增加模型训练。
>
> 保留现有 GPT Image 工作台和 Qwen/FireRed/FLUX/FIBO 的原生接口。通过显式新版本完成：逐目标可比性限制进入实际条件；证据复核形成有效诊断；生成前及候选阶段有各自合法复核；规范化反馈驱动执行修订；编辑前交付可满足性检查；三个场景批次的六臂实验；共同评价冻结、盲评、导入与裁决；工作台和v3共用可复算的单Markdown回传。
>
> 用户任务范围、目标、证据、必需性和成功标准必须有清楚的冻结边界。不得通过删除校验、静默降级旧案例、改验收标准、重复未知提交或漏记失败行来通过验收。
>
> 按 P0–P5 分批提交；记录已执行的 A01–A34 用例。最后提供准确的运行入口、固定代码版本和可由服务器执行的清单。真实模型和画质结果保持 NOT_RUN，由用户部署完成后回传 EXPERIMENT_REPORT.md。
>
> 本文件中的新命令和 schema 是待实现规格。若当前分支已有后续修复，先比较差异并记录已满足项；不要覆盖他人的有效修改。涉及字段命名微调时同步更新数据映射、示例、验收和报告。

## 18. 文档状态与变更记录

| 日期 | 版本 | 内容 | 实现状态 |
|---|---|---|---|
| 2026-10-26 | v1.0 | 基于16dee774审查，形成完整工程规格、实验与单文档回传设计 | 待工程师实现 |

- 来源事实：固定提交中的代码、运行手册和脱敏开发实验。
- 设计决策：本文件明确标注的新版本、阶段、接口、预算、清单与报告规格。
- 证据边界：未执行本计划的真实模型实验，没有新增画质或性能结论。
- 方案核对：针对流程、四模型接口和实验报告进行了同模型家族的分工交叉核对；这不是跨模型独立学术验收。
- review_independence: same-family
- acceptance_status: provisional
- 按用户单文件要求，实施tracker、版本记录与回传模板均合并在本文，不要求另交清单文档或报告附件。



