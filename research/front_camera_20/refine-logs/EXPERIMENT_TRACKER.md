# 实验跟踪表

**状态：所有实际模型实验 `NOT_RUN`。** 一行表示一项冻结任务块，不代表已经运行。真实样本未提供；CPU 脚本检查与模型实验分开记录。

| Run ID | Milestone | Purpose | System / Variant | Split | Metrics | Priority | Status | Notes |
|---|---|---|---|---|---|---|---|---|
| R000 | M0 | 确认20的计数、配对、目标 | 全部 | 全数据 | 配对完整性 | MUST | WAITING_INPUT | DATA_REQUIREMENTS.md |
| R001 | M0 | 冻结颜色/尺寸/方向/分组 | 全部 | 全数据 | hash / metadata / 人工核验 | MUST | WAITING_INPUT | 不猜linear含义 |
| R010 | M1 | doctor与native compiler检查 | 四模型 | dev/额外样本 | 环境/协议 | MUST | NOT_RUN | 不改正式设置 |
| R011 | M1 | pilot与成本测量 | aware single | dev | 交付/调用/耗时/资源 | MUST | NOT_RUN | 4D图像上限 |
| R020 | M2 | 主参考三策略 | native/shared/aware | test | 可用增强/保真/成本 | MUST | NOT_RUN | 12NS图像上限 |
| R021 | M2 | 模型表达指导增益 | 复用R020 | test | aware−shared配对差 | MUST | NOT_RUN | 不新增生成 |
| R030 | M2 | 全链无参考消融 | aware A-only | test | 参考增益/损伤 | CORE | NOT_RUN | 4NS图像上限 |
| R040 | M3 | 固定条件重采样 | aware resample3 | test | 最终质量/实际成本 | OPTIONAL | NOT_SCHEDULED | 同主batch预先加入 |
| R041 | M3 | 有据反馈 | aware feedback3 | test | 改善/早停/实际成本 | OPTIONAL | NOT_SCHEDULED | 检查首轮文本条件差异 |
| R050 | M4 | 模型身份隐藏评审 | 全部有效交付+A基线 | test | 原始评分/缺失/复核 | MUST | NOT_RUN | 不给评审private_mapping |
| R060 | M5 | 汇总完整分母 | 全部计划run | test | 成功/失败/blocked/missing | MUST | NOT_RUN | 不只统计报告成功行 |
| R061 | M5 | 报告、全例与回传 | 全部 | 全部 | 证据可追溯性 | MUST | NOT_RUN | 回填EXPERIMENT_REPORT |

## 实际运行登记（服务器填写）

| 时间 | Block / batch目录 | manifest hash | runtime hash / commit | 开始/结束 | 实际状态 | 日志/报告路径 |
|---|---|---|---|---|---|---|
| 待填写 | 待填写 | 待填写 | 待填写 | 待填写 | NOT_RUN | 待填写 |

## 偏离登记

| 时间 | 原设置 / 改动 | 原因 | 受影响pair/model/seed | 新实验版本 | 原结果保留位置 |
|---|---|---|---|---|---|
| 待填写 | 待填写 | 待填写 | 待填写 | 待填写 | 待填写 |
