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
