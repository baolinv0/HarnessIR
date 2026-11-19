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
