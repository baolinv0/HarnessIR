# 实验执行跟踪

所有状态初始为NOT_RUN。只记录已观察事实。计划数不等于实际调用数；探索版本另行追加。

| Run ID | Milestone | Purpose | System / Variant | Split | Metrics | Priority | Status | Notes |
|--------|-----------|---------|------------------|-------|---------|----------|--------|-------|
| M0-FREEZE | M0 | 基线/数据/协议冻结 | 全模型 | DEV/TEST | 版本与文件完整性 | MUST | NOT_RUN | 25图需绑定真实路径 |
| E0-Q | M1 | 原生链路 | qwen21 | DEV | 工程回执 | MUST | NOT_RUN | 最多3次 |
| E0-R | M1 | 原生链路 | firered11 | DEV | 工程回执 | MUST | NOT_RUN | 最多3次 |
| E0-X | M1 | 原生链路 | flux3_klein | DEV | 工程回执 | MUST | NOT_RUN | 最多3次 |
| E0-F | M1 | 原生链路 | fibo2_dev | DEV | 工程回执 | MUST | NOT_RUN | 最多3次 |
| E0-M | M1 | 编辑LoRA链路 | moss_sft_edit | DEV | 工程回执 | MUST | NOT_RUN | 最多3次；BLOCKED单列 |
| E1-DEV | M2 | 开发与冻结 | 五模型D/O/A | DEV5×2seed | 改善/保真/条件审计 | MUST | NOT_RUN | 最终版本150次 |
| E2-MECH | M2 | 单部件删除 | A/A_minus | DEV | 机制定位 | CONDITIONAL | NOT_RUN | 最多20新增 |
| E2-TEXT | M2 | 转录与绘字 | T0/Tauto/Toracle | DEV文字图 | 覆盖/正确/CER/布局 | OPTIONAL | NOT_RUN | 最多40新增，复用不成立则60 |
| M3-FREEZE | M3 | TEST前冻结 | 五模型profile/ROI/selector | 全部 | hash/版本 | MUST | NOT_RUN | 后续改动开新版本 |
| E1-TEST | M3 | 首轮主比较 | 五模型D/O/A | TEST20 | 可用率/偏好/严重错误 | MUST | NOT_RUN | 300次 |
| E3-POOL | M4 | 固定池选择 | V0；V1可选 | DEV/TEST | 最佳命中/错选/gate误拒 | MUST | NOT_RUN | 0图像生成 |
| E4-2C | M4 | 一次反馈价值 | F/S | TEST20 | 可用率/偏好/内容错误/成本 | MUST | NOT_RUN | 复用首图，最多200新增 |
| E4-3C | M4 | 第三候选边际收益 | F/S第三候选 | TEST20 | 边际改善/成本 | OPTIONAL | NOT_RUN | 最多200新增，单独报告 |
| M5-REPORT | M5 | 证据交接 | REPORT+附件 | 全部 | 完整性/计数一致 | MUST | NOT_RUN | 使用REPORT_TEMPLATE |
