# 四模型前置实拍实验报告（唯一回传文档）

BEGIN_OF_REPORT

> 填完本文件后直接复制粘贴正文。图片、JSON、CSV、模型与原始日志留在服务器，不需要作为附件返回。所有待填写项均表示未知，不能当作 0。可用服务器脚本自动生成运行事实，再补人工观察。

## 1. 实验身份与数据合同

- 报告 ID / 实验日期（北京时间）：【待填写】
- 实际 Git commit / 是否有本地修改：【待填写】
- 状态：NOT_RUN / PARTIAL / COMPLETED【选择实际状态】
- “20 张”的含义：【20 对 / 合计 20 张即 10 对 / 其他】
- 正式 N / 开发 D / 独立场景组数 / 人物数：【待填写】
- 原始 S26 linear → baseline：【baseline 名称、代码与权重版本、是否用过本批数据训练/调参】
- prediction 原始编码：【文件类型、位深、范围、RGB/BGR、色域/白点/transfer；是否已做 WB、CCM、tone mapping、gamma】
- A 的实际显示出口：【明确转换步骤及版本；不能仅填“见脚本”】
- iPhone 型号/模式、原始编码与 B 的显示出口：【格式、ICC、SDR/HDR、导出方式及转换】
- A/B 原尺寸、统一工作尺寸、交付尺寸、镜像/旋转/裁切规则：【待填写】
- 正式集与开发集分组规则、baseline 训练重叠：【待填写】
- 目标优先级与必须保持项：【例如肤色自然 > 脸部曝光 > 局部影调；身份/表情/几何保持】
- GPU 型号×数量/显存、Torch/Diffusers/Transformers/CUDA：【待填写】
- 公共 S1/S3/S5 VLM 完整 ID/revision 与采样设置：【待填写】
- 评审人数、显示条件、是否隐藏模型、争议裁决规则：【待填写】
- 外观/自然度汇总数字的含义：【单人分 / 均分 / 中位数；最终 Y/N 另按冻结投票规则裁决】
- seed_order：【42】或【42,1042,2042】，后文每格严格使用此顺序。
- 输入合同/计划短 hash：【待填写；完整 hash 保留服务器】

| 模型 | 实际 editor ID/revision | compiler ID/revision/helper | steps / CFG / dtype / offload | 配置短 hash |
|---|---|---|---|---|
| Qwen | 待填写 | 待填写 | 待填写 | 待填写 |
| FireRed | 待填写 | 待填写 | 待填写 | 待填写 |
| FLUX | 待填写 | 待填写 | 待填写 | 待填写 |
| FIBO | 待填写 | 待填写 | 待填写 | 待填写 |

本次比较完整编译/编辑系统。N/S/M 均保留各自原生 compiler；M 相对 S 的差异是模型表达指导。A-only 的规划、编译、执行、内部验证不得接收 B。

## 2. 计划与完成度

臂缩写：N=native A+B；S=shared A+B；M=model_aware A+B；A=model_aware A-only。R3/F3 为可选最多三轮重采样/反馈，未安排写 NA。每模型×臂×pair×seed 为一次计划运行，三轮候选不扩成三个独立样本。

- 实际运行的臂与 pilot：【待填写】
- 三种主策略是否在同一 batch 共享初始 intent：【待填写】
- 无参考消融是否独立规划且全链移除 B：【待填写】
- 反馈与重采样是否同生成上限、首轮文本条件是否一致：【未运行 / 待填写】
- 预期正式明细行数：4×N=【待填写】；实际明细行数：【待填写】。

| 模型 | 臂 | 计划 | 正常完成 | 有效图 | 终态失败 | 未终态/未报告 | 人评完成 | 主可用 | 重大损伤 | 待评 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Qwen | N | 待填写 | — | — | — | — | — | — | — | — |
| Qwen | S | 待填写 | — | — | — | — | — | — | — | — |
| Qwen | M | 待填写 | — | — | — | — | — | — | — | — |
| Qwen | A | 待填写 | — | — | — | — | — | — | — | — |
| FireRed | N | 待填写 | — | — | — | — | — | — | — | — |
| FireRed | S | 待填写 | — | — | — | — | — | — | — | — |
| FireRed | M | 待填写 | — | — | — | — | — | — | — | — |
| FireRed | A | 待填写 | — | — | — | — | — | — | — | — |
| FLUX | N | 待填写 | — | — | — | — | — | — | — | — |
| FLUX | S | 待填写 | — | — | — | — | — | — | — | — |
| FLUX | M | 待填写 | — | — | — | — | — | — | — | — |
| FLUX | A | 待填写 | — | — | — | — | — | — | — | — |
| FIBO | N | 待填写 | — | — | — | — | — | — | — | — |
| FIBO | S | 待填写 | — | — | — | — | — | — | — | — |
| FIBO | M | 待填写 | — | — | — | — | — | — | — | — |
| FIBO | A | 待填写 | — | — | — | — | — | — | — | — |

若人工评分直接填写在第3节，汇总表的人工列可写“待按明细复算”，无需再手工做一次汇总。

正常完成与有效图分别统计；流程失败但有合法选中图可以人评诊断，不能计主可用；source_baseline 回退不是编辑成功。计划数必须来自清单，不能把已有报告数当计划数。

主可用=正常完成且有效图，并按冻结规则通过服务器人工评审。自动 verifier accepted/confidence 不能当人工分。人评未齐时只报已确认计数；全部运行终态已知后可列主可用下界 k/n_plan、上界 (k+正常完成且待评数)/n_plan，待评清零后才给最终主率。若还有未运行/暂停/结果不明，不给最终比例。重大损伤率只对已评分图可知，不把未评或无图当无损伤。

## 3. 全样本记录（不能只选好例子）

本模板的 front001–front020 仅为占位；根据实际 N 替换，不足/多余行按真实数据调整。组与人物 ID 必须直接填写在本表，不能只写“见 metadata”。

每格为按 seed_order 排列的结果，以分号分开。例如三 seed：`C:+1/O/0/Y; C:待评; X`。

- 状态：C=正常完成且有效图；F=流程失败但有效图；B=原图回退；X=终态无有效选中交付；P=未报告/暂停/未完成；NA=未安排。
- 有人评时：`状态:外观/保真/自然度/人评可用`。外观与自然度为 -2..+2；O=pass/no_damage，m=minor，D=major，F=fail，?=uncertain；Y/N=人工判定可用/不可用。注意保真 F 在斜杠内，流程 F 在冒号前。
- **只有 C 且人工 Y、保真已通过，才可计主可用**；Y 必须由服务器按预定的至少2/3认可和争议复核规则裁决。minor/uncertain 需先裁决，保真矛盾记待核实。外观/自然度的均分或中位数仅描述评分，不能用均分阈值反推多数票。
- C/F 没有人评写“待评”，不得从自动 accepted 填 Y。F 的人工 Y 仅表示该图诊断观感可用，主系统结果仍不可用。

| pair | group / subject | 模型 | N | S | M | A |
|---|---|---|---|---|---|---|
| front001 | 待填写 | Qwen | P | P | P | P |
| front001 | 待填写 | FireRed | P | P | P | P |
| front001 | 待填写 | FLUX | P | P | P | P |
| front001 | 待填写 | FIBO | P | P | P | P |
| front002 | 待填写 | Qwen | P | P | P | P |
| front002 | 待填写 | FireRed | P | P | P | P |
| front002 | 待填写 | FLUX | P | P | P | P |
| front002 | 待填写 | FIBO | P | P | P | P |
| front003 | 待填写 | Qwen | P | P | P | P |
| front003 | 待填写 | FireRed | P | P | P | P |
| front003 | 待填写 | FLUX | P | P | P | P |
| front003 | 待填写 | FIBO | P | P | P | P |
| front004 | 待填写 | Qwen | P | P | P | P |
| front004 | 待填写 | FireRed | P | P | P | P |
| front004 | 待填写 | FLUX | P | P | P | P |
| front004 | 待填写 | FIBO | P | P | P | P |
| front005 | 待填写 | Qwen | P | P | P | P |
| front005 | 待填写 | FireRed | P | P | P | P |
| front005 | 待填写 | FLUX | P | P | P | P |
| front005 | 待填写 | FIBO | P | P | P | P |
| front006 | 待填写 | Qwen | P | P | P | P |
| front006 | 待填写 | FireRed | P | P | P | P |
| front006 | 待填写 | FLUX | P | P | P | P |
| front006 | 待填写 | FIBO | P | P | P | P |
| front007 | 待填写 | Qwen | P | P | P | P |
| front007 | 待填写 | FireRed | P | P | P | P |
| front007 | 待填写 | FLUX | P | P | P | P |
| front007 | 待填写 | FIBO | P | P | P | P |
| front008 | 待填写 | Qwen | P | P | P | P |
| front008 | 待填写 | FireRed | P | P | P | P |
| front008 | 待填写 | FLUX | P | P | P | P |
| front008 | 待填写 | FIBO | P | P | P | P |
| front009 | 待填写 | Qwen | P | P | P | P |
| front009 | 待填写 | FireRed | P | P | P | P |
| front009 | 待填写 | FLUX | P | P | P | P |
| front009 | 待填写 | FIBO | P | P | P | P |
| front010 | 待填写 | Qwen | P | P | P | P |
| front010 | 待填写 | FireRed | P | P | P | P |
| front010 | 待填写 | FLUX | P | P | P | P |
| front010 | 待填写 | FIBO | P | P | P | P |
| front011 | 待填写 | Qwen | P | P | P | P |
| front011 | 待填写 | FireRed | P | P | P | P |
| front011 | 待填写 | FLUX | P | P | P | P |
| front011 | 待填写 | FIBO | P | P | P | P |
| front012 | 待填写 | Qwen | P | P | P | P |
| front012 | 待填写 | FireRed | P | P | P | P |
| front012 | 待填写 | FLUX | P | P | P | P |
| front012 | 待填写 | FIBO | P | P | P | P |
| front013 | 待填写 | Qwen | P | P | P | P |
| front013 | 待填写 | FireRed | P | P | P | P |
| front013 | 待填写 | FLUX | P | P | P | P |
| front013 | 待填写 | FIBO | P | P | P | P |
| front014 | 待填写 | Qwen | P | P | P | P |
| front014 | 待填写 | FireRed | P | P | P | P |
| front014 | 待填写 | FLUX | P | P | P | P |
| front014 | 待填写 | FIBO | P | P | P | P |
| front015 | 待填写 | Qwen | P | P | P | P |
| front015 | 待填写 | FireRed | P | P | P | P |
| front015 | 待填写 | FLUX | P | P | P | P |
| front015 | 待填写 | FIBO | P | P | P | P |
| front016 | 待填写 | Qwen | P | P | P | P |
| front016 | 待填写 | FireRed | P | P | P | P |
| front016 | 待填写 | FLUX | P | P | P | P |
| front016 | 待填写 | FIBO | P | P | P | P |
| front017 | 待填写 | Qwen | P | P | P | P |
| front017 | 待填写 | FireRed | P | P | P | P |
| front017 | 待填写 | FLUX | P | P | P | P |
| front017 | 待填写 | FIBO | P | P | P | P |
| front018 | 待填写 | Qwen | P | P | P | P |
| front018 | 待填写 | FireRed | P | P | P | P |
| front018 | 待填写 | FLUX | P | P | P | P |
| front018 | 待填写 | FIBO | P | P | P | P |
| front019 | 待填写 | Qwen | P | P | P | P |
| front019 | 待填写 | FireRed | P | P | P | P |
| front019 | 待填写 | FLUX | P | P | P | P |
| front019 | 待填写 | FIBO | P | P | P | P |
| front020 | 待填写 | Qwen | P | P | P | P |
| front020 | 待填写 | FireRed | P | P | P | P |
| front020 | 待填写 | FLUX | P | P | P | P |
| front020 | 待填写 | FIBO | P | P | P | P |

可选 R3/F3 若运行，在上表加两列或复制同结构表。逐 seed 保留最终结果；首轮未做人评则写“首轮未评”，不得用自动 verifier 代替。所有失败/回退的短原因填下节。

## 4. 成本与关键异常

| 模型 / batch / 臂 | 实际图像/编译/stage调用 | compiler秒 / image秒 | 共享规划调用/秒（单列） | 整批时间/显存与测量方式 |
|---|---|---|---|---|
| 待填写 | 待填写 | 待填写 | 待填写 | 待填写 |

耗时说明：【是否含装载、worker是否驻留、是否并发、显存采样间隔】。未测量写“未测量”，不能填0或冒称热推理延迟。

| pair / 模型 / 臂 / seed | 阶段与错误代码 | 是否仍有有效图 | 恢复/重试与额外调用 | 对结论影响 |
|---|---|---|---|---|
| 待填写；若确实没有异常写“无” | 待填写 | 待填写 | 待填写 | 待填写 |

记录全部异常的数量和定位 ID；只摘关键错误文本，不粘完整 stack trace、原始 JSON、凭据或图片编码。原始日志留服务器。

## 5. 服务器人工观察与协议偏离

每例用2–4句话描述具体位置和变化，建议3–5例覆盖典型改善、重大损伤、无变化/不确定；若某类未出现据实写明，不补造案例。

| pair / 模型 / 臂 / seed | A的问题、B是否适合作参考 | 输出具体改善或损伤 | 如何核对；是否有争议及裁决 |
|---|---|---|---|
| 待填写 | 待填写 | 待填写 | 待填写 |

- 条件审计：PE/Recaption/PUP/VGL 是否遗漏目标、增加内容或混淆 A/B：【待填写；未审计写未审计】。
- 协议偏离：改变了哪些输入/尺寸/模型/参数/seed/评审规则，何时改变、影响哪些 runs：【待填写；无则写无】。
- 相同模型/臂是否存在多个配置版本，是否分开统计：【待填写】。
- 保留原始图、原生条件、每轮输出、原始评分和日志的位置：【仅写服务器留存确认/简短定位，不要求回传】。

## 6. 初步结论与回传完整性

- 每模型 M 相对 S/N 是否改善，哪些pair支持/反对：【待填写】。
- A+B 相对 A-only 的收益及保真代价：【待填写】。
- seed稳定性与场景/人物覆盖限制：【待填写】。
- 尚缺的人评、运行或无法判断的内容：【待填写】。
- 后续优先验证对象与依据：【待填写，不强制选唯一冠军】。

**本报告未回传图像；画质判断来自服务器端人工评审。接收者可核对实验执行、统计和配对趋势，但未独立复核像素内容。仅有最终人评/裁决时，也不能重算原始投票过程或评审间一致性。**

- [ ] 基本配置、颜色出口、组/人物对应关系已写在本文。
- [ ] 所有正式pair、四模型、已安排臂和全部seed均有记录。
- [ ] 失败、待评、未运行与0值明确区分；没有用自动分冒充人评。
- [ ] 摘要与逐例一致，异常和偏离已说明。

报告 ID：【与开头一致】；实际明细行数：【待填写】。

END_OF_REPORT
