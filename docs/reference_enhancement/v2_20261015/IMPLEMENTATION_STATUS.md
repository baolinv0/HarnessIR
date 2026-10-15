# v2 实现状态 — 2026-10-15

本工程增量基于 PR #3 `c94a4001e5250fd257e8954b56b72ca9c4725409`，版本为 0.2.0。生成与人工模型会话继续走既有手动交接；Controller/CaseStore 是唯一工作流状态。安装、真实首例、Mask 与实验命令见 [RUNBOOK.md](RUNBOOK.md)，审查和验证证据见 [REVIEW_AND_VALIDATION.md](REVIEW_AND_VALIDATION.md)。

| 方案能力 | 实际实现与验收范围 |
| --- | --- |
| G0 DirectRef | 冻结 A/B 和固定文本；一次生成；editor 仅 A、B、文本 |
| G1 AgentText | 真实诊断/离线证据进入 Composer；1–3 个受支持目标，动态文本最多 160 词；一次生成 |
| G2 条件性 Mask | 同 Executor/settings、同 A/B、同 ROI/EVAL_MASK、同字节 G1 最终文本；三类实际能力 probe 与本次完整交接证明均必需 |
| Mask | uint8 {0,1}、canonical A 坐标、0 保留/1 允许编辑；EDIT_MASK/EVAL_MASK 分用途；独立图片与原生参数明确区分；手工或 T4 来源严格核验 |
| ROI 评价 | A/B 各自的 box/polygon/binary mask；C 沿冻结 A 坐标；亮度、色度、影调、饱和度逐属性 before/after/delta，无总体质量分数 |
| 内容与几何 | 几何或独立内容审查失败/未解决，最终属性与 H3 不可评价；流程 Verifier 仅保留为审计数据 |
| 局部影响 | 同一预冻结 EVAL_MASK 的区域外变化与边界变化代理量；不声明像素硬锁定 |
| 证据与恢复 | 所有 v2 arm 提交完整实际 Executor 观察；G2 原始请求、返回、receipt、编码 M 与审计记录进入 submission；事务绑定 done.json 摘要 |
| 实验 | R0_fixture、R1 3–5 对、R2 12 对、条件性 R3；冻结版本/随机顺序/场景 split/输入；计划、失败、缺失、skipped 全部保留 |
| 盲评与决策 | 匿名图像/统一评价区域、两名独立评审与第三人裁决；ITT、joint success、配对偏好、H3；H1/H2 独立门槛 |
| CLI/UI/分发 | 显式 `hre v2`、既有六区 UI 中的状态与评价；v2 schema/template 随 wheel 分发；v1 默认路径回归通过 |

内部沿用 v1 request/state schema，但 `reference_v2` 配置、执行模板版本合同、Mask transport 与评估文件显式版本化。旧引擎缺少 v2 执行上下文时会拒绝渲染；不把 Mask 隐藏成普通两图任务。

T1–T4 仍消费外部离线 worker 的真实结果，不捏造模型输出。T4 只有实际诊断计划、完整缓存身份与 canonical A 原生标签尺寸均匹配时才能派生 Mask；低分辨率标签需要另行定义可审计栅格化规则，本实现不隐式拉伸。

| 实验事实 | 状态 |
| --- | --- |
| 合成 G0/G1 完整链、评价、匿名导出与缺评审 ITT | 通过；未调用模型；缺独立评审时 PROBE |
| G2 正/负协议、精确配对、交接/恢复证明 | 合成 fixture 测试通过；仅工程证据 |
| 实际编辑器 A+B+Mask 能力 R0 | 未运行；默认 untested，不能通过 UI 勾选启用 |
| 真实 R1 / R2 / R3 | 未运行；无真实 A/B、实际首个完整输出与独立评审数据 |
| 真实增强收益、Mask 因果收益或总体显著性 | 未建立；不能由测试通过推导 |

样例 spec、candidate metadata、probe 和 ratings 均为待填写模板，未知值保留 null/占位，不能照抄为通过记录。代码不自动调用模型、不自动重试选优、不引入确定性 Renderer。此实现 PR 以 PR #3 分支为基线，原 main 与 PR #2 的分叉集成另行处理。
