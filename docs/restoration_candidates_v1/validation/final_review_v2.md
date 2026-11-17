# R1 至 R4 修复独立复核

目标是确认四类已复现缺陷在当前 CPU 实现中得到修复，避免把统计或恢复问题留给离线 GPU 电脑。结论为 PASS。检查范围内未发现需要修复的新 Critical、Important 或 Minor 问题。

本轮由新的只读代理复核。审查对象是当前未提交源码，相对旧交付包 `restoration-candidates-928831f69511dfbc.zip` 的修复差异，固定基线为 `d44d40fa209a9978d37ce38efa9a6ef89abe7432`。使用了当前可用的继承模型，不是跨供应商复审。

## 修复判断

| 项目 | 判断 | 已核实的机制与证据 |
| --- | --- | --- |
| R1 固定 E2 分母 | 通过 | `analysis.py` 从预注册 slot_axes 或固定默认映射建立评价机会；F1 实际轴单独保存。null、回退、缺失和错轴不删分母。新回归保留 2 case × 2 seed 的分母 4。单轴多槽旧测试仍通过。 |
| R2 输出身份 | 通过 | `runtime.py` 检查已完成 native/delivered 文件及回执哈希、两池匿名整图和 ROI、已有 E2 结果，并核对正式交付路径。缓存检查发生在返回前。完整性异常不会被 _failed_artifact 改写成失败槽。中断后损坏缓存的回归确认原完成记录与操作账本不变。 |
| R3 Oracle 与硬契约 | 通过 | `analysis.py` 与 `report.py` 都使用 evidence.pool_contract_sets。合格集合要求已产出、独立质量合格及实际硬契约通过。缺失或 unknown 不隐含通过，重复和外池 ID 被拒绝。原始质量最佳标签先验证，再与正式合格集合相交。 |
| R4 其他合法轴 | 通过 | 实际 building、grass、other 可以进入产物记录和覆盖报告；人物/文字评价适用性仍由预注册目标决定。其他场景不会被冒充为人物/文字改善，也不会使整个报告中断。 |

读取了 `changes.diff`、修复设计、实际四个生产模块、相关回归测试、原始复审报告和 DECISIONS.tsv。没有修改应用代码、测试或交付包。

## 独立执行

使用工作区 CPU Python 和既有测试入口执行：

```text
python scripts/cpu_test.py engine/tests/test_candidates_analysis.py engine/tests/test_candidates_oracle.py engine/tests/test_candidates_runtime_integrity.py -q --junitxml=../../artifacts/fix-review-v2/reviewer-tests.xml
```

结果为 37 passed。XML 保存在 `artifacts/fix-review-v2/reviewer-tests.xml`。

按 Prove It Works 原则，结论依赖实际执行结果及实际代码路径。复核同时读取了 runtime-red.xml、runtime-integrity-green.xml、statistics-red.xml、statistics-green.xml，确认决策日志中的先复现再修复记录有相应证据。审查时生产文件 SHA-256 和测试计数保存在 `.work/verify-fixes-v2/review-evidence.json`。

## 决策记录与边界

DECISIONS.tsv 的早期无条件交付结论已经由 review-correction 行明确取代。早期错误测试链接也有纠正行。最新设计和运行时验证行均有对应文件，没有发现尚未纠正的虚假验证声明。

没有待父代理裁决的行为冲突，没有建议延期的 Minor 项。该结论不代替修复后 wheel 的安装验证、最终 ZIP 的源码一致性检查和解压运行，这些属于父代理后续交付步骤。没有验证真实 GPU 推理、实际 Diffusers 画布能力、显存或研究效果。
