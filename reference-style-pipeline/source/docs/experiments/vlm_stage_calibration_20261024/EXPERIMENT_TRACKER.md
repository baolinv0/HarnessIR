# 执行清单

所有状态初始 TODO；运行后改为 DONE / PARTIAL / FAILED / NOT_RUN。重复请求填写 runs.csv，不改写历史结果。

| 顺序 | 工作 | 请求数 | 状态 | 输出/决定 |
|---|---|---:|---|---|
| 0a | 冻结 SHA、权重、启动命令与 6 对图 | 0 | TODO | 环境表、cases.csv |
| 0b | 人工关键事实与候选构造标签 | 0 | TODO | facts.json、candidate_labels.json |
| S0 | 3 家族协议 smoke | 3 | TODO | 分流、finish_reason、schema |
| S1 | 2 dev×7 配置×2 seed | 28 | TODO | 每家族选一配置 |
| S2 | 4 confirm×3 配置×2 seed | 24 | TODO | D 逐场景比较 |
| S3a | 3 case×3 planner，同一人工观察 | 9 | TODO | 冻结 planner |
| S3b | 3 case×3 D，固定 planner | 9 | TODO | 观察到 action 的传播 |
| S4 | 3 case×3 C×3 judge | 27 | TODO | J 错误类型与选型 |
| S5 | 可选 2 case×3 编辑条件×2 seed | 12 张 | NOT_RUN | 图像收益 |
| 返回 | 填报告、原始结果、HTML 与全部失败 | 0 | TODO | REPORT.md + 证据包 |

若从 S0 复用 3 条到 S1，注明对应 run_id；总新增 97 次。不要把预热或失败重试漏出实际成本。
