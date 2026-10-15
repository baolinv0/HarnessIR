# 独立审查与汇总决议

四专题并行设计后，由独立Agent进行跨文档工程/实验审查，主Agent修正。以下记录设计矛盾及修复，不是运行系统测试结果。

| 问题 | 汇总后的决议 |
|---|---|
| Baseline零生成预算不能进入state | baseline专属0预算，无模型步骤，baseline_only/successfalse/fallbackfalse |
| Direct臂缺Composer任务与snapshot | 固定DirectRef prompt artifact、空证据快照，diagnosis_task_id可null且仅Direct允许 |
| profile名称不同 | 统一direct_best_of_3；mode可描述fixed_prompt_best_of_k |
| Refine计划新工具但无tool_plan | V1只用diagnosis_planned_only，Refine不动态新增工具 |
| Verify来自Compose会让Direct缺上下文 | 所有臂用相同冻结入组限制与保护rubric |
| geometry/证据有的文档给Verify、有的禁止 | Controller保存snapshot/geometry绑定，Verify/Refine不接工具报告/地图 |
| 小幅aspect差可形成拉伸 | 0.5%仅初筛，raw_w*A_h==raw_h*A_w才允许纯scale；raw不覆盖 |
| master/derived候选与选图可能不一致 | Verify C与Selection.asset_id绑定同一实际评审资产，master/raw保留 |
| cache复用带旧case asset引用 | materialize按hash/role/geometry映射全部payload引用，新record/hash，原cache不修改 |
| stage证据ID正则比协议更窄 | 所有evidence_ids引用统一公共IDregex |
| refine例子round错误 | envelope指下一轮，source_round与失败C仍指当前轮 |
| 多输出策略不一致 | V1供应商顺序首个完整图是唯一candidate；其他raw审计，已知采样入预算 |
| fixedK完成与失败耗尽混用 | fixed_k_complete按可观测预算停止；success由selector；Adaptive未通过耗尽才budget_exhausted |
| 总评pass绕过细项fail/缺观察 | Schema要求五类保真覆盖，pass无critical defect；improved须可比style观察 |
| 合法业务error没有状态路径 | 明确PAUSED/恢复与no_supported_refinement终止；格式修复不替看图 |
| 重新观察沿用已接收task导致conflict | 新task_id、旧回复保留、candidate/source_round不变，纯分析不消耗生成 |
| STATS值没有统一物理/显示定义 | display_stats_v1参数冻结入config/cache；显示域代理不称传感器亮度 |
| pilot GO/STOP可能同时命中 | STOP优先，再全部GO，否则PROBE；属于工程heuristic |

协议格式与模板由静态校验器验证；状态迁移、可比较性、真实内容保真、模型能力与效果仍需工程实现及真实R1/R2/R3证据。静态检查的具体范围见VALIDATION_REPORT。

独立审查最终结论：00–07、总入口、Schema、模板、配置、夹具与验证记录已复核，未发现剩余P0/P1阻断项，可交工程师实施。最后确认了未知提交仅保留reservation、确认提交才consumed、专属业务error优先于一般error、状态表列数一致。此结论是设计可实施性审查，不是产品或算法效果验收。
