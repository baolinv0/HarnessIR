# HarnessRefEnhance：参考引导图像增强工程方案

实现入口：**[安装与命令](engine/README.md)**、**[运行与恢复手册](docs/reference_enhancement/IMPLEMENTATION_RUNBOOK.md)**、**[实现与验证记录](docs/reference_enhancement/IMPLEMENTATION_STATUS.md)**。设计依据见 **[工程交付总方案](docs/reference_enhancement/v1_20261013/START_HERE.md)**。

任务：编辑 Modular Neural ISP prediction，利用同场景、非像素对齐的 iPhone 17 图像指导外观增强，同时保持 prediction 的内容与几何。

2026-10-13：四个并行 Agent 完成设计后，六个实现 Agent 分别完成图像与事务存储、状态与预算、离线证据、提示与桌面交接、实验与报告、CLI 与 Streamlit 界面，并接受独立审查。运行代码在 `engine/src/hre/`；UI 与 CLI 共用 Controller。

安装后可运行 `python -m hre --help`。真实编辑采用可审计的手动任务导出与结果导入；内置 CPU STATS/ROI 可运行，T1–T4 消费外部离线 worker 的真实结果。合成演示验证本地协议，不代表模型增强有效。真实 R1、12 对 pilot 和桌面自动能力仍待真实数据与会话验证。

Executor 第一阶段使用 ChatGPT 桌面两图编辑；自动能力逐项实测。本方案属于本 fork 的新增强任务。
