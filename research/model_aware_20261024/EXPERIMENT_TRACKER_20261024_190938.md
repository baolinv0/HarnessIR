# Experiment Tracker

| Run ID | Milestone | Purpose | System/Variant | Split | Metrics | Priority | Status | Notes |
|---|---|---|---|---|---|---|---|---|
| SW001 | sanity | 原始40文件对照 | 官方/目标分支原始快照 | source | SHA256 | MUST | DONE | 40/40相同 |
| SW002 | sanity | S5多类型故障 | original/fixed | fixture | exception/checklists | MUST | DONE | red→green |
| SW003 | sanity | decoded native端点留存 | Direct/Harness fixed | fixture | size/hash | MUST | DONE | 非模型质量 |
| SW004 | sanity | scene统计/交互 | analyze_pairs | fixture | expected contrasts/拒绝不配对 | MUST | DONE | 非研究结果 |
| SW005 | sanity | 旧engine回归 | e1b610e engine | existing tests | pytest | MUST | SEE_08 | 存在失败须如实报告 |
| Q000 | native | 身份/参数/输入parity | NB2/Qwen | dev | receipts | MUST | BLOCKED | B1/B2 |
| Q001 | direct | 六类prompt能力包络 | E0-native/matched | dev | D/F/N/FR/cost | MUST | BLOCKED | 无模型运行 |
| Q002 | baseline | VLM×Executor混杂 | 2×2/E1 | dev | paired/交互 | MUST | BLOCKED | exact VLM版本未知 |
| Q003 | isolation | S3/S2/S4单因素 | E2/E3/E4 | dev | paired/保真/成本 | MUST | BLOCKED | 先Q001 |
| Q004 | mechanism | feedback/resample/select | E5/U-K/BO-K | frozen failure cohort | quality/regret/调用 | MUST | BLOCKED | 先定义同预算 |
| Q005 | generalize | 最小E6与删除/统一对照 | E6/U/E1/E0 | sealed test | CI/分层/多重复 | MUST | BLOCKED | 不预先声称有有效E6 |
| Q006 | validate | 独立人类盲评 | anonymous pairs | sealed test | D/F/N/errors/agreement | MUST | BLOCKED | B4 |
