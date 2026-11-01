# Reference Style Pipeline：Codex 交接入口

完整计划、可运行源码、测试及脱敏实验记录位于独立目录 [reference-style-pipeline](reference-style-pipeline/START_HERE.md)。现有根工程保持原样。

- [开始与运行命令](reference-style-pipeline/START_HERE.md)
- [实现地图、结论和后续验收](reference-style-pipeline/CODEX_HANDOFF.md)
- [当前计划](reference-style-pipeline/plans/CURRENT_PLAN.md)
- [可利用数据与测试计划](reference-style-pipeline/DATA_AND_TEST_PLAN.md)
- [三轮累计实验报告](reference-style-pipeline/evidence/CUMULATIVE_REPORT_V3_PUBLIC.md)
- [独立审查](reference-style-pipeline/verification/INDEPENDENT_HANDOFF_REVIEW.md)

下一步优先实现整体 B 风格/影调评价，再复核关键区域与主体背景关系，最后用局部指标解释；此评价器尚未实现。A01 单场景观察不代表稳定泛化收益。私有照片、掩码、模型和凭据不随仓库发布；A07/A19 尚未执行新版实验，手机 RGB 验证不能替代 Base 输出验证。

发布环境复核（2026-11-01）：归档 SHA-256 `9858ef10de8ee373886868f4b082e7e532ee9838a7685dced482d9d2c4c02c71`，1,268,077 bytes；内部清单及全部 453 文件一致。按 START_HERE 执行 CLI help 和 scoped unittest，**175 tests / 36.095s / OK**。环境为 Python 3.12.14、NumPy 2.3.5、Pillow 12.3.0、Pydantic 2.13.4、jsonschema 4.26.0、referencing 0.37.0；Pillow 与原审查环境的 13.0.0 不同，未重建私有图片。未运行全仓库测试、新图像实验、Base 域验证、训练或服务器实验。原包文档/日志/补丁的空白格式提示保留，以维持清单哈希。
