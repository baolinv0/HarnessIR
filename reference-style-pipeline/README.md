# Reference Style Pipeline — Codex handoff

**[中文启动入口：START_HERE.md](START_HERE.md)** · [完整需求/实现地图](CODEX_HANDOFF.md) · [可用数据与测试计划](DATA_AND_TEST_PLAN.md)

这里是独立、可运行的 `source/` 快照及公开脱敏的实验记录，不覆盖上层 HarnessIR。
当前是显式 file-based / current_chat_offline 流程，不是自动模型 runner。

- scoped reference-style 175 项测试重新通过；不代表全仓库/真实风格通过。
- 最新本例证据：Full 黄偏/肤色彩度改善可见，局部亮度混合；旧总体 tie 不证明等价。
- 下一优先：**整体评价 → 关键区域复核 → 局部解释指标**。新评价尚未实现。
- 私人照片、裁块、mask、模型、凭据不在仓库。Camera0717 目前只有 A01 做过新版真实试验。
- [累计历史与评价核查](evidence/CUMULATIVE_REPORT_V3_PUBLIC.md) · [来源与验证边界](verification/SOURCE_PROVENANCE.md)
