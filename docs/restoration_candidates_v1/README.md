# 修复候选工程与实验文档

先读 [完整方案与实施计划](PROJECT_PLAN.md)，实验原稿见 [完整实验计划](EXPERIMENT_PLAN.md)，再按 [实验跟踪表](EXPERIMENT_TRACKER.md) 执行。计划包含当前已知统计问题、离线 GPU 环境准备、Pilot、held-out、E1/E2、独立标注、预算、验收和失败处理。

| 文档 | 用途 |
| --- | --- |
| [PROJECT_PLAN.md](PROJECT_PLAN.md) | 完整方法、模块、合同、阶段验收和实验全文 |
| [EXPERIMENT_PLAN.md](EXPERIMENT_PLAN.md) | 当前完整实验计划，不代表真实数据已经预注册 |
| [EXPERIMENT_TRACKER.md](EXPERIMENT_TRACKER.md) | 运行顺序、进入条件、当前状态和证据 |
| [IMPLEMENTATION_PLAN_V1_1.md](IMPLEMENTATION_PLAN_V1_1.md) | 批准的实现与实验合同 |
| [CANDIDATE_GENERATION_DETAIL.md](CANDIDATE_GENERATION_DETAIL.md) | 候选生成细节 |
| [RUNBOOK.md](RUNBOOK.md) | 环境、离线安装、实际 CLI、恢复与汇总操作 |
| [OFFLINE_AGENT_HANDOFF.md](OFFLINE_AGENT_HANDOFF.md) | GPU 端 code agent 的诊断和修复范围 |
| [VALIDATION.md](VALIDATION.md) | 历史 CPU 实现验证，结合最近复审阅读 |
| [FIX_REVIEW_V2.md](FIX_REVIEW_V2.md) | 前一轮四类问题的修复说明 |
| [最近复审](validation/review_v3.md) | 原 Best-in-pool 问题来源，关闭结果见最终复核 |

GPU 权重、依赖和真实数据需要另外准备。CPU fixture 不计入研究结论。最近统计问题已完成 CPU 回归与 [最终复核](validation/final_review.md)。最新版文档不表示已经完成真实 GPU 或研究效果验证。
