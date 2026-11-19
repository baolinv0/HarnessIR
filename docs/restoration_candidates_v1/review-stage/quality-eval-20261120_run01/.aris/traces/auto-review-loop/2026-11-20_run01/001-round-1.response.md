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
