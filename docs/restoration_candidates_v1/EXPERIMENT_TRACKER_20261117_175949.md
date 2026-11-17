# 实验执行跟踪表

更新日期为 2026-11-17。协议见 [EXPERIMENT_PLAN.md](EXPERIMENT_PLAN.md)。本表的完成状态必须附证据。计划行不代表实际数据或真实运行已经存在。

状态使用 DONE_CPU、BLOCKED、TODO、NOT_RUN、RUNNING、DONE_REAL 和 INCONCLUSIVE。只有真实模型及独立标注完成后才能把研究行改为 DONE_REAL。

| Run ID | 里程碑 | 目的 | 系统/变体 | 划分/规模 | 指标或产物 | 优先级 | 状态 | 进入条件与证据 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R000 | CPU | 既有实现及恢复检查 | fixture、合同与完整性测试 | 工程检查 | 145 passed、1 skipped | MUST | DONE_CPU | [CPU 验证记录](validation/cpu_results.json)。不是质量结果 |
| R001 | G0 | 关闭最佳集合过滤后的错误分母 | 单案例及批量离线分析 | 复审反例 | 冲突标注正确缺失，回归通过 | MUST | DONE_CPU | 定向38项通过，完整145通过/1跳过，[最终复核](validation/final_review.md)通过 |
| R002 | G1 | 建立实际离线部署清单 | 固定 Qwen 与本地 VLM | 目标 GPU 机 | OS/Python/CUDA、依赖、权重、revision、端点与容量 | MUST | TODO | 填真实环境，核对协议算法名，不能保留占位值 |
| R003 | G1 | 冻结 Pilot 与 E2 目标 | 数据清单、政策、slot_axes、preregister | 10 张，E2 四张 | scene 隔离、LQ 目标、seed、注册 hash | MUST | TODO | 不能在 E1 结果出现后补选 |
| R004 | G2/B1 | 验证真实 x1 | 同原始 LQ，A/B | 独立工程图一张 | 原生几何、回执、恢复无新增调用 | MUST | TODO | R002，通过真实 preflight；不计入 Pilot |
| R005 | G2/B1 | 验证奇数尺寸 x4 | 257×193 LQ，A/B | 独立工程图一张 | pad264×200，native1056×800，交付1028×772 | MUST | TODO | R004，禁止 resize 修正 native |
| R006 | G3/B2 | Pilot 主比较 | A/B 同 J1，每池四槽 | 10 张，最多70次图像调用 | Oracle/Selected Pass、内容错误、失败、成本 | MUST | NOT_RUN | R001-R005 通过，全部配置及清单已冻结 |
| R007 | G3/B3 | Pilot 审核比较 | 固定 B 池 J0/J1 | 同十张 | 选择成功、最佳、误拒/误纳、unresolved | MUST | NOT_RUN | 不新增生成，不改匿名顺序，独立 Oracle |
| R008 | G3/B4 | Pilot 同 seed 机制 | 四槽×两枚 E2 seed | 预注册四张，额外最多32次 | 目标/非目标/联合指标及全部分母 | MUST | NOT_RUN | 原 E1 冻结 F1，不按 E2 重规划 |
| R009 | G3/B5 | Pilot 内容风险及失败 | C0、A/B、J0/J1 | 全部 Pilot 与独立诊断集 | 错字、表情、背景损害、重复及缺评 | MUST | NOT_RUN | 双评及分歧裁定，诊断集与主样本分开 |
| R010 | G4 | 判断额外专家预算是否值得 | 固定 B 池 J2 | Pilot | 质量/失败/实际费用，限定归因 | OPTIONAL | NOT_RUN | Pilot 有支持的审核失败证据才启动 |
| R011 | G4 | 专家分工独立归因 | J1_budget_matched | 待单独冻结 | 匹配调用/token预算的对照 | OPTIONAL | NOT_RUN | 当前无公开 CLI variant，先实现验收；不运行则不作角色因果声明 |
| R012 | G5 | Pilot 后一次修订与冻结 | 代码、协议、数据、分析 | Held-out24张，E2八张 | 新协议与注册 hash、sealed 数据划分 | MUST | TODO | 不读取 held-out 结果来修订 |
| R013 | G5/B2 | Held-out 主检验 | A/B 同 J1 | 24张，最多168次图像调用 | 配对主指标、区间、内容错误及成本 | MUST | NOT_RUN | R012 通过，禁止换入成功 case |
| R014 | G5/B3 | Held-out 审核检验 | 固定 B 池 J0/J1 | 同24张 | 全样本选择、误拒/误纳与缺评 | MUST | NOT_RUN | 同池/同顺序，指标计算脚本固定 |
| R015 | G5/B4 | Held-out 同 seed 检验 | 四槽×两枚 E2 seed | 预注册八张，额外最多64次 | 分槽/注册轴效果、实际轴和产物覆盖 | MUST | NOT_RUN | 保留 fallback、失败、无干预和机制不适用 |
| R016 | G6 | 最终统计与独立审计 | 主实验与可选扩展分开 | 全部预定样本 | 主表、案例、分母、原始标注、成本和声明判断 | MUST | NOT_RUN | 无未关闭统计缺陷，无真值泄漏，无漏失败 |

## 每个实际运行追加的记录

真实运行开始后，在本表增加 case/批次链接或维护附属执行表。每行至少保存 Run ID、case_id、scene_id、命令、代码及配置 hash、开始/结束时间、设备、操作调用数、状态、产物路径、失败/unknown 和费用状态。状态改变后保留历史原因，不能把失败行删除后重编号。

图像调用预算为 Pilot102、held-out232，共334次研究上限。独立工程 smoke 若两个 case 均启用 A/B，另最多14次。VLM、工具、人工标注和未知费用分别记录，不混入图像次数。
