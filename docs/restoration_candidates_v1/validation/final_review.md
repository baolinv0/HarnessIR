# GitHub 发布前 Best-in-pool 修复独立复核

本轮核实最后一项 P2 统计边界是否已经关闭，以支持完成代码与文档的功能分支发布。结论为 PASS。检查范围内没有新的 Critical、Important 或 Minor 问题，没有需要父代理裁决的行为冲突。

审查对象为 `source/candidates` 当前未提交的 `analysis.py`、`report.py` 和 `test_candidates_oracle.py`，对比包为 `restoration-candidates-62d2b96ee97f9ffc.zip`。本轮未修改应用代码、测试或交付包。

## 注释约束检查

先对实际差异及三个文件检查注释。新增普通注释、TODO/FIXME、lint/type suppression 为 0，建议删除 0，MUST KILL 与 REVIEW keeps 为 0。保留 `analysis.py` 的公开输入合同 docstring。没有执行删除、恢复或应用代码重构。

## 统计行为

两条报告路径保留原始独立最佳集合，并单独计算其是否可用。最佳图不在实际硬契约与 Oracle 合格集合中时，不再将过滤后的空集合当作已知最佳集合。

| 输入情形 | 复核结果 |
| --- | --- |
| 原始最佳只有硬契约失败图，另有正式选中的有效合格图 | 最佳指标为 0/0、value=null、missing_count=1，Oracle/Selected Pass 保持正确 |
| 原始并列最佳混有有效与无效图 | 整项最佳标注记缺失，不推断过滤后的排名 |
| 合格集合非空但最佳缺失或为空 | 最佳指标不进入分母，报告缺失 |
| 最佳集合完整且属于实际合格集合 | 正常计算最佳一致率 |
| Oracle 不完整 | 最佳指标不进入分母，保留缺失与其他主指标的保守规则 |
| 实际没有合格候选 | 保持不适用，不编造一个最佳失败 |
| 同时存在 best_sets.B 与旧 best_set | 单案例与批量均优先读取 B 池字段 |
| 错误容器、未知候选或非质量合格最佳 | 保留显式 oracle_invalid 拒绝 |

生产差异很小，实际合格集合没有被修改。新增的是最佳标注可用性判断和两条路径一致的指标分母/缺失规则，避免通过修正排名掩盖原标注冲突。

## 独立执行证据

按 Prove It Works 原则，实际运行了：

```text
python scripts/cpu_test.py engine/tests/test_candidates_oracle.py engine/tests/test_candidates_analysis.py -q --junitxml=../../artifacts/final-publish/reviewer-best-tests.xml
```

结果为 38 passed。检查了作者保存的 `best-red.xml`，为 7 failed、10 passed；`best-green.xml` 为 38 passed。本轮另外执行 `git diff --check` 通过。

本报告使用新的只读代理和当前可用继承模型，不是跨供应商审查。最终完整候选套件、源码/wheel/ZIP 身份、文档汇编、GitHub 提交与远端读取由父代理核实。没有验证真实 GPU、模型画布能力、显存或研究效果，也没有重审无关的历史基线代码。
