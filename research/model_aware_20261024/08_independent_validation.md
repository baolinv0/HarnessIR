# 8. Independent Validation Report

## 本轮实际执行

由未参与方案撰写的独立审查代理读取最终源码diff、协议、统计程序，自己运行验证；同一模型家族，`review_independence=same-family`、`acceptance_status=provisional`。不是独立机构复现、不是跨家族接受，也没有人类图像盲评。

原始报告在 [evidence/independent_review.md](evidence/independent_review.md)；脚本与输出在 `scripts/independent_review_probe.py`、`results/independent_review_probe.txt`、`results/independent_review_unittest.txt`。

| 独立检查 | 结果 | 解释边界 |
|---|---|---|
| 新增单测 | 10 passed | 只验证确定性合同 |
| 原始/修复版像素对照 | Harness有/无crop两路、Direct方形/非方形×颜色copy on/off四路，6路逐像素一致 | 非均匀控制图/控制编辑器；color=True采用支持copy的类型，不包含实际Torch AdaIN真实模型实验 |
| 类型覆盖 | 5种合法原始type的31种非空组合可构建Verifier | 规范组装可执行，不代表VLM判断正确 |
| 原生存档失败 | 标native_archive_complete=false，候选仍可交付 | 不把缺原生端点的运行当完整证据 |
| 下游写失败 | 回执仍指向已成功原生存档 | 不掩盖错误，不丢证据路径 |
| 统计 | 已验证scene平均、差中差、两臂同时漏scene拒绝、跨模型cohort错配拒绝 | 构造数据只证明算术与准入，不进入质量结果 |

## 审查发现与响应

| 发现 | 处理 | 当前状态 |
|---|---|---|
| 原生存档写失败导致候选丢弃 | 失败显式记录，继续原交付；native_archive_complete限定义 | 修复且独立复验 |
| 后续交付写失败丢失raw回执 | 异常返回保留native字段 | 修复且独立复验 |
| 两臂同时漏图可悄悄改变cohort | CLI强制冻结期望cohort，逐个匹配身份；未绑定API标false | 修复且独立复验 |
| 主指标/对照可在结果后选择 | paired LPIPS/noGT盲评分开固定；明确H1/H2主contrast | 协议收紧，尚未冻结真实运行 |
| 完例分析的选择偏差 | 明确条件estimand、失败率非劣与MNAR敏感性要求 | 协议收紧；实测仍缺 |
| K相同不等于总成本相同 | 区分候选预算/总成本estimand，要求实际tokens/attempts/费用 | 协议收紧；transport ledger仍未实现 |
| 样本量用错contrast方差 | 功效指定scene级交互SD，保真非劣另行定N | 协议收紧，未声称100/150足够 |

## 剩余不足与科学接受状态

- 高：没有真实Direct/E0–E6、冻结测试、用户实际本地Qwen运行包、独立人类图像评估。**质量结论不接受。**
- 高：logical model calls不是transport attempts；完整成本/服务模型身份回执未实现，尚不能声称等总预算。
- 中：新增存档只有decoded native与交付端点，geometry-only仍会被颜色覆盖；executor输入路径已记录但未新增输入SHA，尚未完成协议要求的完整trace。
- 中：历史云端模型有路由/版本漂移；即使软件同字节，无法未经回执证明exact historical replication。

现有engine完整回归经历三步：初轮452 passed/7 failed（环境依赖）；补环境后engine全部通过，但根新增测试在执行进程载入后修改形成同步快照不一致，联合轮为466 passed/2 failed；稳定代码冻结后的最终全量结果为**469 passed、4 warnings、exit 0**，耗时268.97s，见`results/engine_pytest.txt`；32个Python文件的前后SHA复核全部一致，记录见`results/tested_source_verification.txt`。4条warning来自进程锁测试的多线程fork弃用提示。保留前两轮，不能抹去或将其报告成一开始全绿。

## 对外部独立验证的要求（未执行）

由不参与策略开发的评价者在冻结测试上执行04盲评；原始标签、左右随机种子、评审者匿名ID、时间、重复项、排除与分歧保留。独立复现者从固定commit与manifest执行同预算任务，核对实际模型身份和全部候选，不只复核选出的成功图。没有这一过程，最终接受仅限软件/协议的provisional，不升级为科学复现通过。
