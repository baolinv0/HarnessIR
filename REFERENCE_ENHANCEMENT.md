## 参考 Retouch 全流程整合（2026-10-26）

在原有参考增强闭环上新增显式 `workflow_contract=reference_retouch_v1`：八维参考诊断、差异与目标追溯、冻结逐属性验收、已满足时零生成返回原图，以及独立的原生交付门槛。旧 v3 模板、请求与历史案例语义保持不变。

先用 GPT Image 工作台完成可视化的单编辑器流程；通过共同目标合同接入原 `hre models` 运行器。入口、修改依据与仍待实测的边界见 [新运行手册](docs/reference_retouch/RUNBOOK.md)、[目标](docs/reference_retouch/GOALS.md)、[实际单案例实验](docs/reference_retouch/CASE_EXPERIMENT.md)。原生接口可运行与真实模型画质合格分开报告，尚无四模型质量排名。

## Model-Aware 并行运行（2026-10-22）

新增 [Model-Aware 运行手册](MODEL_AWARE.md)：`hre v2 run` 直接贯通模型专属条件编译与原有执行/验证；`stage-export / stage-run / stage-compare` 独立检查并可视化比较各阶段。两部分共享冻结输入与编译代码，阶段测试不是主流程运行的前置条件。真实模型部署与质量实验状态见手册，合成演示不作为效果证据。

## v2 生成式参考增强设计（2026-10-15）

基于已实现的 v1 hre 工程，新增 **G0 DirectRef / G1 AgentText / G2 条件性 AgentMask** 实验设计，以及非对齐 ROI 的 A/B/C 属性评价。只保留生成式编辑，不引入确定性 Renderer；Mask 仅在相同 Executor 真实验证后启用。v2 运行代码已实现；**真实 G0/G1/G2 增强收益与实际 Executor Mask 能力尚未验证**。运行入口见 [v2 手册](docs/reference_enhancement/v2_20261015/RUNBOOK.md) 和 [实现验证记录](docs/reference_enhancement/v2_20261015/IMPLEMENTATION_STATUS.md)。

- [v2 总入口](docs/reference_enhancement/v2_20261015/START_HERE.md)
- [工程设计](docs/reference_enhancement/v2_20261015/DESIGN.md)
- [实验计划](docs/reference_enhancement/v2_20261015/EXPERIMENT_PLAN.md)
- [工程任务与验收](docs/reference_enhancement/v2_20261015/IMPLEMENTATION_CHECKLIST.md)

旧 v1 设计、实现与真实 R1 未跑状态保留如下。

# HarnessRefEnhance：参考引导图像增强工程方案

实现入口：**[安装与命令](engine/README.md)**、**[运行与恢复手册](docs/reference_enhancement/IMPLEMENTATION_RUNBOOK.md)**、**[实现与验证记录](docs/reference_enhancement/IMPLEMENTATION_STATUS.md)**。设计依据见 **[工程交付总方案](docs/reference_enhancement/v1_20261013/START_HERE.md)**。

任务：编辑 Modular Neural ISP prediction，利用同场景、非像素对齐的 iPhone 17 图像指导外观增强，同时保持 prediction 的内容与几何。

2026-10-13：四个并行 Agent 完成设计后，六个实现 Agent 分别完成图像与事务存储、状态与预算、离线证据、提示与桌面交接、实验与报告、CLI 与 Streamlit 界面，并接受独立审查。运行代码在 `engine/src/hre/`；UI 与 CLI 共用 Controller。

安装后可运行 `python -m hre --help`。真实编辑采用可审计的手动任务导出与结果导入；内置 CPU STATS/ROI 可运行，T1–T4 消费外部离线 worker 的真实结果。合成演示验证本地协议，不代表模型增强有效。真实 R1、12 对 pilot 和桌面自动能力仍待真实数据与会话验证。

Executor 第一阶段使用 ChatGPT 桌面两图编辑；自动能力逐项实测。本方案属于本 fork 的新增强任务。
