# 质量评估方案独立审查与修订记录

日期 2026-11-20。审查范围为文档设计，未运行模型实验。原目标目录 C:/Users/xx.xing/Desktop/HarnessMIR 写入被系统拒绝，改为在原 GitHub 文档分支交付，未绕过 ACL。

三轮使用全新独立上下文 reviewer，三轮 builder 分开执行。requested reviewer 为 gpt-6-astra、xhigh；工具未返回独立模型身份声明，reported model 记为 null。同 OpenAI 家族审查，acceptance_status=provisional，不能称为跨家族验证。停止条件为无已确认未解决的方案缺陷，不是仅达到分数阈值。

| 轮次 | 审查快照 | Score | Verdict | 当轮未解决问题 |
|---|---|---|---|---|
| 1 | 7f26666287095e3278b1ee484f2cb35466d7d9b5 | 8/10 | almost | 3 |
| 2 | 9fe0b4ee499b38c7f174cdb3e8e67f41965461bc | 8/10 | almost | 1 |
| 3 | f2bf9eba7e3a54fdae95f5c5f9f68b20f67ce677 | 9/10 | ready | 0 |

F1 源枚举未知传播、F2 合同有效的系统 Oracle、F3 native/delivered 几何区分、F4 确认失败优先的交付统计均已修复，并由后续独立 reviewer 核查关闭。最终方案快照为 f2bf9eba7e3a54fdae95f5c5f9f68b20f67ce677。

## Method Description

主方案 J3 以同一原 LQ 的 C0、CF、CT、CFT 为候选池。Code 只对确定性执行合同作硬检查；Q-SiT、适用人脸比较器、OCR 及可选专家提供带限制的专业证据。VLM 按源清单覆盖、必需属性、可采纳证据与质量要求判定资格，再只在 eligible 集合中作 listwise 优选。极小非关键人脸跳过专项，Q-SiT 总分默认隐藏，不能以相对最好替代真实内容已验证。

在线冻结请求、区域、用途与预算，保留 unknown 与失败。离线人工独立标注，再以确定性合同有效且人工 pass 构造系统 Oracle。交付风险以确认失败优先的三态合并统计。当前通过仅说明文档范围内未发现未解决设计缺陷，正式实验前仍须完成实现、模型及模板冻结、Pilot 校准与 held-out 验证。

## 验证与范围

实际回读每轮 GitHub 快照。最终方案两张 Mermaid 在 Mermaid 11.4.1、Microsoft Edge 中编译渲染并目视检查，导出无脚本、无 foreignObject 的 SVG。最终修订保持两图源码不变。没有运行 GPU、IQA 模型或恢复实验，没有虚构检测概率或实测收益。没有实验结果可供 result-to-claim。此次未生成 HTML，交付重点为 Markdown、原始审查记录与 SVG。

采用 Model the Domain 将源清单、属性、执行合同和测量状态分开。采用 Explain the Number 修正 Oracle 集合与错交分母。采用 Prove It Works 回读真实提交并验证真实图形产物。

## 第 1 轮审查原文

独立审查原文，供完整归档。

审查对象：`baolinv0/HarnessIR@7f26666287095e3278b1ee484f2cb35466d7d9b5`，比较父版本按任务指定为 `e709f7158d180b1cc37f39cf7c7f39e75eab8ac7`。通过 GitHub 工具直接读取并精读 `QUALITY_EVALUATION_PLAN.md` 全文，同时读取另外两份文档全文及该提交 diff。未修改文件、未运行模型或 GPU、未发布内容。

**Score：8/10。Verdict：almost。Open findings：3。** 当前仍有可构造失败的合同缺口，尚未满足“无任何已确认未解决设计缺陷”的停止条件。

1. **F1｜High：源实例清单的覆盖未知没有确定传播到候选资格，存在漏检对象绕过必需评审的路径。**

   **位置：** QUALITY §4，[第76–78行](https://github.com/baolinv0/HarnessIR/blob/7f26666287095e3278b1ee484f2cb35466d7d9b5/docs/restoration_candidates_v1/QUALITY_EVALUATION_PLAN.md#L76)；§7 第121、137行；§8 第147–155行。

   文档要求无法确认源清单覆盖时记录 `coverage unknown`，但后续 coverage 枚举只有 `complete/missing/failed`，资格判定只遍历已绑定实例的必需检查。没有说明清单级 unknown 存储在哪里、如何产生必需检查缺口，以及不存在实例记录时如何避免空集合通过。

   **具体失败示例：** 用户要求所有重要号码准确。检测器登记了一个号码区域，整图补充仍无法确认另一块模糊招牌是否包含必须处理的号码，于是清单标记 coverage unknown。F1 仅为已登记号码实例化属性；该号码在四候选里均评完且 supported。实现遍历已存在的 required checks，得到全部完成，随后交付候选；那块未登记招牌从未产生 missing 属性。系统同时声称“清单覆盖未知”和“所有必需检查满足”，后者并不成立。

   **最小修复：** 增加显式的源清单覆盖检查及作用范围，并将其接入 required_checks。对必需 selector 无法确认实例枚举完整的情况，保留一个覆盖缺口记录；没有确认拒绝理由时，对受影响候选判 undetermined，不能通过“零匹配实例”视为不适用。预先允许的 tinyface 跳过和非必需范围不因此自动阻塞。同步修正状态枚举与验收例。

2. **F2｜Medium：离线系统 Oracle 和 best_set 没有排除确定性执行合同无效产物，会把合法拒绝统计为选图失败。**

   **位置：** QUALITY §10，[第199–204行](https://github.com/baolinv0/HarnessIR/blob/7f26666287095e3278b1ee484f2cb35466d7d9b5/docs/restoration_candidates_v1/QUALITY_EVALUATION_PLAN.md#L199)；§11 [第235–243行](https://github.com/baolinv0/HarnessIR/blob/7f26666287095e3278b1ee484f2cb35466d7d9b5/docs/restoration_candidates_v1/QUALITY_EVALUATION_PLAN.md#L235)。在线排除规则见§7 第143行。

   人工 acceptable 由感知与必需内容标签合成；best_set 从人工 pass 候选中产生。OraclePass@4、条件选择成功率、best_set agreement 和 avoidable unresolved 均没有声明使用 `contract_valid ∧ human_acceptable=pass` 的可交付集合。独立盲评者通常也不能从正常显示图像判断请求绑定、原生几何或冻结执行配置是否有效。

   **具体失败示例：** CF 因原生尺寸错误而 contract_fail，但视觉自然、内容正确，人工标为 pass；其余三个合同有效候选均因严重模糊被人工标为 fail。系统正确 unresolved，现有公式却得到 OraclePass@4=true，并将此案例计入 avoidable unresolved。另一例是 C0 合同有效且人工 pass，CF 合同无效却更好看；人工 best_set 只含 CF，系统正确选择 C0，却被记录为最佳选择不一致。这会混淆生成/执行失败与 Judge 错选。

   **最小修复：** 保留独立人工感知和内容原始标签；在盲评完成后，由离线代码用确定性执行合同状态构造系统可交付 Oracle 集合。系统 OraclePass@4、条件选择成功率、best_set 和 avoidable unresolved 使用该集合；无效产物的视觉 pass 另报。过滤依据不得使用在线 VLM 的 eligible，以继续保持 Oracle 独立性。需要时先过滤合同有效候选，再让盲评者给出它们的最佳组。

3. **F3｜Medium：新文的 x4 尺寸条款与仍有效的 padding/native/delivered 合同不一致。**

   **位置：** QUALITY §3，[第72行](https://github.com/baolinv0/HarnessIR/blob/7f26666287095e3278b1ee484f2cb35466d7d9b5/docs/restoration_candidates_v1/QUALITY_EVALUATION_PLAN.md#L72)；IMPLEMENTATION §6.2，[第157–168行](https://github.com/baolinv0/HarnessIR/blob/7f26666287095e3278b1ee484f2cb35466d7d9b5/docs/restoration_candidates_v1/IMPLEMENTATION_PLAN_V1_1.md#L157)；CANDIDATE §7.2，[第318–325行](https://github.com/baolinv0/HarnessIR/blob/7f26666287095e3278b1ee484f2cb35466d7d9b5/docs/restoration_candidates_v1/CANDIDATE_GENERATION_DETAIL.md#L318)。

   新文在“输出原生尺寸”的同一句中规定 x4 为原 LQ 的 `4W×4H`。保留有效的执行合同则明确：输入补至8的倍数，native 应为 `4Wpad×4Hpad`，合法裁切后的 delivered 才是 `4W×4H`。新文既管确定性资格，又声明旧执行合同有效，当前给了两种 native 校验目标。

   **具体失败示例：** 原 LQ 为 `257×193`，合法 padding 后为 `264×200`。bridge 正确产生 native `1056×800`，再裁成 delivered `1028×772`。若质量 Gate 依新文将 native 直接与原 LQ 的4倍比较，就把合法候选判 contract_fail；若按旧文接受，则与新权威的原生尺寸表述不一致。

   **最小修复：** 在新文直接区分两个尺寸：native 严格匹配冻结的 padded canvas；delivered 经冻结且可验证的 crop 后严格为 `4W×4H`。合法 crop 不属于 resize 补救，原生错误尺寸仍不得靠 resize 通过。增加上述非8整除输入的正反验收例即可。

其余重点没有确认出新的设计缺陷：J3 主案与 J2 消融区分明确；Q-SiT 问答被限定为项目适配，未伪造原生多维校准分数；小脸跳过、多人位置与上下文、身份与表情区分、测量失效与候选失效、软指标权限、全局一次争议复核、格式修复总额度、unknown 占额、匿名和 GT 隔离、E1 同池同 Judge、E2 预注册及源案例统计均有相应约束。Q-SiT 的解释能力、DeepFace 的工具库定位及 DreamSim 的通用感知相似定位也与查阅的一手资料相容。[Q-SiT论文](https://arxiv.org/html/2503.09197v1)、[DeepFace官方仓库](https://github.com/serengil/deepface)、[DreamSim官方仓库](https://github.com/ssundaram21/dreamsim)。

待 Pilot 校准的阈值、模型、模板、显示容量和实际可靠性属于明确的实验门槛，本轮没有因其尚无结果而追加阻塞项。旧文中已标为历史背景的 J1/J2 预算与实验说明，没有被重复计作缺陷。

**Memory update：** 保持用户已确定的 J3、总体分数默认隐藏、小脸不逐一做 face IQA、同源四候选、可选 DreamSim/PAL、软证据不单项硬淘汰及最多一次争议复核。下一轮应逐项验证 F1 源枚举未知传播、F2 合同有效 Oracle 集合、F3 native/delivered 几何一致性；修复后还需重新检查交叉影响。

`review_completed=true`  
`scope_complete=true`  
`stop_condition_satisfied=false`

审查通过后也只表示文档设计可进入 Pilot，不代表已实现、检测可靠性已验证或生产可用。

## 第 2 轮审查原文

独立审查完成。**Score：8/10；Verdict：almost；Open findings：1。** r1 的三项问题已关闭，但新发现一处会低估已确认错交率的统计缺陷，尚未满足停止标准。

审查对象为 `baolinv0/HarnessIR@9fe0b4ee499b38c7f174cdb3e8e67f41965461bc`，基线为 `7f26666287095e3278b1ee484f2cb35466d7d9b5`。已直接分段读取 `QUALITY_EVALUATION_PLAN.md` 全部 382 行、提交 diff，以及两份旧规格中的冻结、对象、执行几何、预算、交接和 E1/E2 合同。未修改文件、发布内容或运行模型实验。本次为同 OpenAI 家族、独立上下文的审查，不能称为跨模型家族验证。

**F4 — Medium / P2：执行合同未知遮蔽已确认的人工 fail，低估错交风险。**

- **位置：** [QUALITY_EVALUATION_PLAN.md §11，L252–253](https://github.com/baolinv0/HarnessIR/blob/9fe0b4ee499b38c7f174cdb3e8e67f41965461bc/docs/restoration_candidates_v1/QUALITY_EVALUATION_PLAN.md#L252-L253)，并影响 L260–262 的确认错交报告及 risk-coverage 曲线。
- **实际条款：** 可判错交只包括“确定合同无效”或“合同有效且人工 acceptable=fail”；合同不可确认的交付则统一进入未知。因此 `contract_unknown + acceptable=fail` 被排除在确认错交分子和可判交付分母之外。
- **可构造反例：** 已交付图像及其像素绑定保存完整，独立人工确认存在严重伪影，`acceptable=fail`；但部分有效配置或执行回执缺失，离线复核无法确认执行合同。图像不可接受这一结论并不依赖执行合同是否有效。若共有 10 次交付，另外 9 次均为合同有效且人工 pass，现行规则报告可判错交率 `0/9=0%`、未知交付 `1/10`；实际已有一次确认错交，应为 `1/10=10%`。
- **影响：** 原始人工标签虽然保留，主要风险指标仍将已知失败变成未知，可能错误比较策略或操作点的交付风险。这不是待 Pilot 校准的问题。
- **最小修复：** 对交付结果采用明确的 fail 优先合并规则，并保留两项原始状态：
  - `fail`：确定合同无效，**或**人工 `acceptable=fail`。
  - `pass`：合同有效，**且**人工 `acceptable=pass`。
  - `unknown`：其他组合。
  
  可判错交率使用 `fail / (fail + pass)`；未知交付比例只统计最终 `unknown`。补一个“合同不可确认但人工确认 fail”的验收用例。无需改动已修复的 `system_oracle_ids` 定义。

r1 逐项复核结果：

| 问题 | 结果 | 核查依据 |
|---|---|---|
| F1：源枚举未知未传播 required 检查 | **关闭** | §4 L84–88 定义独立 `SourceInventoryCheck`；零实例仍登记，枚举不可确认传播为覆盖缺口；§8 L162–163、验收用例和两张流程图均同步。极小非关键人脸豁免与明确身份准确性要求也已区分。 |
| F2：Oracle/best_set 纳入合同无效的视觉 pass | **关闭** | §10 L214–216 保留人工原始标签，用独立复核合同状态与人工 pass 构造集合，明确禁止 online eligible 过滤；在全部有效 pass 中重新比较，能够选出有效次优。§11 的 Oracle、SelectedPass、条件成功率和 avoidable unresolved 已同步。F4 是新增交付风险合并问题。 |
| F3：x4 原生尺寸与 padded canvas 冲突 | **关闭** | §3 L72–76 与实施规格 §6.2、生成规格 §7.2 一致：`257×193 → pad 264×200 → native 1056×800 → delivered 1028×772`。直接产生交付尺寸的 native 明确 contract_fail；验收用例同步。 |

其余重点范围未发现新的已确认缺陷：匿名与 GT 隔离；一次预规划争议复核及全 variant 一次格式修复；专家 forward 独立计费和 unknown 占额；小脸跳过与检测失败分离；身份、画质、结构及真实性分离；Q-SiT 总分默认隐藏；DreamSim/PAL 可选且非硬门禁；J0–J3 定义；E1 同 Judge、共享 C0 的七次生成预算；E2 预注册、独立评价 seed 和成本分账；按独立源案例统计及 held-out 冻结。

人工 `acceptable` 合并感知与必需内容的规则明确留给预注册用途政策，并容许特定未知微细节，因此未另立一个缺乏充分文本依据的对称 finding；应在实施时验证该冻结政策，而非据此否定既定用途差异。

**Memory update：** F1/F2/F3 已关闭；新增 F4 待修。以后复核交付统计时，应检查“合同状态 × 独立人工标签”的完整组合，已确认 fail 不得被另一项 unknown 遮蔽。继续保留 J3 主方案、小脸不逐一专项 IQA、软证据不单项自动拒绝及一次争议复核的既定约束。

`review_completed=true`  
`scope_complete=true`  
`stop_condition_satisfied=false`  
`open_findings=1`

本报告结论限于文档设计；未验证模型准确性或实际恢复收益。

## 第 3 轮审查原文

审查结论：**Score 9/10；Verdict: ready；Open findings: 0。**

在指定审查范围内，**无已确认未解决的设计缺陷，可进入实施和 Pilot 准备**。本结论不表示质量模型已实现、检测准确性已验证或恢复收益已成立。

审查对象为 `baolinv0/HarnessIR` 的 commit `f2bf9eba7e3a54fdae95f5c5f9f68b20f67ce677`，对照 parent `9fe0b4ee499b38c7f174cdb3e8e67f41965461bc`。已完整分段阅读 [QUALITY_EVALUATION_PLAN.md](https://github.com/baolinv0/HarnessIR/blob/f2bf9eba7e3a54fdae95f5c5f9f68b20f67ce677/docs/restoration_candidates_v1/QUALITY_EVALUATION_PLAN.md)，核对本次 diff、parent 原有错交口径，以及两份关联文档的执行、状态与实验合同。审查只读，未修改或发布文件。

**F1–F4 关闭状态：**

| Finding | 状态 | 核验依据与结果 |
|---|---|---|
| F1：源清单枚举未知未传播 | **Closed** | §4 第84–90行规定独立的 `SourceInventoryCheck`，即使零实例也加入 `required_checks`。必需枚举不可确认、missing 或 failed 均形成覆盖缺口；§8 与资格流程图继续将其传播为 undetermined。已登记实例全部通过不能抵消缺口。 |
| F2：合同无效但人工 pass 污染 Oracle/best_set | **Closed** | §10 第215–216行仅将合同有效且人工 `acceptable=pass` 的候选纳入 `system_oracle_ids`；best_set 在该集合全部候选内重新盲评。§11 的 Oracle、SelectedPass、条件选择成功率、best_set agreement 和 avoidable unresolved 沿用同一集合。人工原始标签独立保留。 |
| F3：x4 native 与 padding/delivered 不一致 | **Closed** | §3 第72–76行分别校验冻结 padded canvas 的 native 与裁切后的 delivered。257×193 → pad 264×200 → native 1056×800 → delivered 1028×772 的实例正确，并与两份执行规格一致。直接生成1028×772的 native 仍为 contract_fail。 |
| F4：合同未知遮蔽人工确认失败 | **Closed** | §11 第245–253行给出完整3×3映射，确认失败优先；第262–272行统一各错交指标与 risk-coverage；第295–296行加入对应验收反例和零分母用例。 |

F4 的九种组合与文字规则一致：

| 执行合同 | 人工 pass | 人工 fail | 人工 unknown |
|---|---|---|---|
| 有效 | pass | fail | unknown |
| 明确无效 | fail | fail | fail |
| 不可确认 | unknown | fail | unknown |

分母和交叉回归核验结果：

- 最终 pass、fail、unknown 互斥，合计为全部实际交付；合同与人工同时失败只计一次。
- 可判错交率为 `fail/(fail+pass)`；未知交付比例为 `unknown/全部交付`；全部交付确认错交比例为 `fail/全部交付`。
- 九次合同有效且人工 pass，加一次合同不可确认但人工 fail，结果为 pass=9、fail=1、unknown=0；可判错交率及全部交付确认错交比例均为10%。
- 全部交付均 unknown 时，可判错交率为 null，并注明 `zero_denominator`；零交付时，交付相关的零分母比率同样为 null。
- 原始合同 unknown 与人工 unknown 单独保留，不再覆盖最终确认失败。
- 此次合并只用于交付评估，没有把合同不可确认或合同无效产物加入系统 Oracle，也没有修改在线资格规则。

上述是对文档逻辑的枚举与算例核验，不是对尚未实现代码的测试结论。

**独立全篇审查结果：**

未确认新的实际失败路径。以下边界在现行规格及关联合同之间保持一致：

- 资格先处理确认拒绝理由，再处理必需未知；仅 eligible 可交付，baseline_retained 同样要求 C0 eligible，best_available 仅供审计。
- 软测量不能单项硬淘汰；来源证据不足不能因专家一致或高置信升级为 supported；错绑测量先拒收该测量，避免混成候选内容错误。
- 极小非关键人脸按冻结规则跳过专项，仍保留整图检查；明确要求准确的极小身份仍保留必需 unverifiable，不能因跳过而通过。
- ReviewPlan 包含源清单及实例检查，多包单独预算与聚合；一次争议复核和整个 variant 一次格式修复的限制明确。unknown 占用预留额度，不自动重试。
- Q-SiT 总分默认不供终审；J3 为异构主方案，J0/J1/J2 保留原消融身份。DreamSim、PAL4VST、AesExpert 保持可选。
- 四候选均从同一原 LQ 独立生成，禁止候选后补抽。E1 共享 C0、最多七次唯一生成；E2 在读取 E1 输出前预注册，使用不同于规划 C0 的评价 seed，禁止结果回流 E1。
- GT 与离线标签隔离；人工先独立逐候选标注，再构造合同有效的系统 Oracle 和重新盲评 best_set。统计单位为源案例或源场景，未把四候选、多脸或多次回答当独立样本。
- 旧文对质量、Judge 和实验的冲突条款已有明确优先级覆盖；其仍有效的生成及执行合同与本次修订相容。

Open findings 明细：**无**。未把明确待 Pilot 冻结的模型、阈值、模板、容量等参数列为已确认文档缺陷；这些仍是正式实验前的实施门槛。

Memoryupdate：在该 commit 上，F1、F2、F3、F4 全部关闭；当前已确认未解决设计缺陷为0。后续实施应保留确认失败优先的九格映射、系统 Oracle 的合同过滤、源清单覆盖传播，以及 native/delivered 分离校验。新实测若发现问题，应作为新证据开启下一轮，而不能由本次文档通过推断模型可靠。

`review_completed=true`  
`scope_complete=true`  
`stop_condition_satisfied=true`  
`open_findings_count=0`

这是同一 OpenAI 模型家族中的独立上下文审查，**不是跨模型家族验证**。

## 代码示例注释审查原文

Audit complete for commit `7f26666287095e3278b1ee484f2cb35466d7d9b5` against `e709f7158d180b1cc37f39cf7c7f39e75eab8ac7`, using actual GitHub file contents and commit diff.

- Touched files: none.
- Deletion count: 0.
- `MUST KILL`: none.
- `REVIEW` keeps: none.
- Skips: explanatory prose, normative contracts, Mermaid node/edge labels, unchanged examples, directory annotations and shell examples outside the specified scope.

The only added fenced examples in scope are the two Mermaid diagrams in `QUALITY_EVALUATION_PLAN.md` (lines 298 and 331). Neither contains comments, suppressions or commented-out code. Existing JSON/Mermaid examples in `IMPLEMENTATION_PLAN_V1_1.md` were unchanged. No eligible additions were found in `CANDIDATE_GENERATION_DETAIL.md`.

No mutation performed; small-face skip and heterogeneous-specialist scope preserved.
