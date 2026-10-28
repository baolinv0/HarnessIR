# 五阶段执行清单

| 阶段 | 工作 | 预定量 | 状态 | 证据/选择 |
|---|---|---:|---|---|
| 准备 | 数据/ROI/人工I/N/原生配方冻结 | 4 cases | TODO | |
| F0 | 工具功能与真实四模型smoke | 复用N | TODO | |
| D | 三VLM、两seed | 24 | TODO/REUSE | |
| P1 | generic planner比较 | 12 | TODO/REUSE | |
| P2 | 固定planner、四profile | 16 | TODO | |
| C | N/I/G/M显式原生编译并冻结 | 64 | TODO | |
| E1 | 四模型四臂seed42 | 64张 | TODO | |
| E2 | 同C、seed43 | 64张 | TODO | |
| B | c01 B2参考响应 | 0C/8E，复用原条件 | TODO | |
| J-control | 三模型已知候选 | 27 | TODO/REUSE | |
| J-real | J_star全部128 + 另两模型各32 | 192 | TODO | |
| J-B2 | J_star新增8张 | 8 | TODO | |
| 人审 | 全部生成图与关键条件 | 136图/64C | TODO | |
| R | 必要时单变量修正坏C | 最多先4张 | NOT_RUN | |
| 汇总 | 功能/能力/策略增益/归因完整报告 | 1包 | TODO | |

状态：TODO/RUNNING/DONE/PARTIAL/FAILED/BLOCKED/REUSED/NOT_RUN。REUSED填原run及条件一致性依据。续跑前查已有记录，不覆盖历史失败。
