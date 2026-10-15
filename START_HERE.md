# HarnessIR Manual Wizard

本目录同时保留上游 HarnessIR 与本地 Manual Wizard，两者使用不同的入口和依赖环境。

**Manual Wizard 从 [README_MANUAL.md](README_MANUAL.md) 开始。**

- Controller、状态机、Web UI、Gemini REST 通路与测试：`engine/`
- T1–T4 部署、独立进程、CPU/GPU 配置与模型 registry：`preprocessing/`
- 基础规格、协议和提示模板：`Design_v1_20261012/`
- 本地工具增量规格和实施计划：`Design_v1_1_20261012/`
- Colab 原版 SAM3 notebook：`colab/`；SAM3.1 独立 runner：`engine/colab/sam31_handoff.py`
- 数据准备与校验脚本：`Data/scripts/`
- 上游论文实现与 Qwen 适配文档：原有 `README.md`、`harness/` 和 `docs/qwen_adaptation/`

设计包的 START_HERE、验收报告与工程阶段报告是历史记录。当前代码入口和执行器选择以 README_MANUAL 及 engine/GEMINI_API 为准。

本仓库发布源码，不包含原始照片、GT、模型权重、缓存、case、运行日志、账号授权或密钥。安装源码不等于已部署模型，也不等于已完成20张恢复验收。
