# v2 审查与验证记录 — 2026-10-15

> 以下 348 项测试及首轮审查结论属于 0.2.0 历史记录。返回的五条外部反馈和 0.2.1 修正另见本文末尾；测试数量仅证明工程行为，不构成真实参考增强效果证据。

独立审查覆盖相对 PR #3 的全部实现、资源、测试和文档，并追踪既有 Controller、CaseStore、预算、证据和提交协议。首次结论是需修复：无 Critical，7 项 Important、2 项 Minor。以下九项均已修复并添加先失败、后通过的回归测试；没有延期处理的审查项。最终复核在下列已验证范围内未留下阻塞项。

| 首次审查发现 | 最终处理与回归证据 |
| --- | --- |
| 实际 Executor/settings 缺少完整绑定 | 所有 arm 必须提交完整实际观察，与冻结 Executor、可见模型身份、输入/文本/原始输出/次数一致；设置漂移拒绝 |
| G2 可绕过临时交接检查，证明未随接收永久保存 | raw 协议入口核验 typed proof；完整 transitive graph 随 done.artifacts 提交并重映射；清理临时目录仍可恢复，丢失正式证明失败 |
| R1 单个未配对成功可提前升级并误标真实效果 | 要求同 case 的 G0/G1 完成且独立内容通过、ROI 有效；R1 只可 GO_TO_R2，不能标记真实效益验证 |
| 严重缺陷自由文本未可靠触发 STOP | 固定 category + severity + observation；非结构化内容拒绝；identity 等严重缺陷实际触发停止 |
| 独立内容失败仍保留“有效”指标与 H3 | 最终指标按独立评审重新判定，失败/未解决则 null；workflow_attributes 单独保留 |
| H2 没有独立队列与继续条件 | 单独 H2_decision、eligible/capable/skipped/qualified 数；至少 6 配对和 2 局部收益，严重 G2 缺陷停止该路线 |
| 高分辨率评价占用多份全帧 float64 | 保留 RGB8，按行/块转换，均值 float64 累加、全样本分位数一维 float32；3 MP 内存回归与 12 MP 实测通过 |
| mask 形状的 ROI 未进入匿名评审包 | 按 A/B 坐标输出统一匿名区域 PNG，不泄漏 EDIT_MASK 消费或 arm |
| 导入的手工/T4 Mask 来源未验证 | 校验版本化 provenance；手工观察归属或配置派生记录、T4 缓存身份和输入均必须匹配；空来源拒绝 |

最后的兼容性核对另补两项：v2 Execute 必须有版本化上下文，旧引擎无法静默当成 v1 执行；v2 接收事务必须具有 done_sha256，不能通过删掉该字段解除证明绑定。两项均复现失败后修复，包内与项目版本同时为 0.2.0。

## 实际验证结果

| 验证 | 结果 |
| --- | --- |
| 原基线回归 | 298 passed，179.35 秒 |
| 最终全量 `python -m pytest engine/tests -q` | **348 passed**，200.42 秒；含 50 项新增测试 |
| 既有设计包 validator | **181 checks PASS**、9 schemas、6 templates；仅静态设计验证 |
| 编译与补丁空白检查 | compileall、git diff --check 通过 |
| 零模型完整示例 | G0/G1 COMPLETED、G2 skipped_not_eligible；匿名导出与缺评审 ITT 产生 PROBE；actual_model_called=false |
| 独立安装 wheel | 0.2.0 wheel 在仓库之外、独立 venv 内实际导入；确认安装路径，create/start/export/evaluate 通过，editor 恰为 A.png/B.png/edit_prompt.txt |
| UI | Streamlit AppTest 正常展示 untested Mask 状态，不能以勾选启用 |
| 3 MP 内存回归 | RGB8 属性与 spill 的独立子进程峰值 <300 MiB |
| 12 MP 聚焦内存实测 | 3000×4000 的 RGB8 A/C、半幅目标、属性与 spill；峰值 **277544 KiB（约 271 MiB）**、2.88 秒；未缩图、未抽样 |

四条 warning 均来自既有进程锁测试中 Python 3.12 在多线程测试进程执行 fork 的 DeprecationWarning；相关串行化测试通过。12 MP 数字是聚焦 evaluator 进程的本机测量，不是整套 UI/模型会话峰值保证，也未做 48 MP 破坏性 OOM 测试。

最终验证环境：Python 3.12.14、Pillow 12.3.0、NumPy 2.3.5、pydantic 2.13.5、jsonschema 4.26.0、Jinja2 3.1.6、Streamlit 1.66.0、pytest 9.1.1。未重写原 v1 requirements-lock 来冒充此环境。最终 wheel SHA256：`a63fa4e82a21a68beacc84d207239c0556b34e745db84ceff2da15649d8a20f0`。

测试输入、Executor 观察和 G2 能力证明均为明确标注的合成 fixture，真实 R0 能力、R1/R2/R3 尚未运行。审查与测试结论只确认当前工程实现和离线协议，不确认增强效果、实际编辑器 Mask 能力或统计显著性。

## 0.2.1 返回审查意见的处置

本次返回意见针对 PR #4 `f872e248`。逐项核对源码并构造反例后，五项意见均落实为修正。其中 R1 的原实验条文也写了“至少完成一对”即可 GO，存在阶段定义歧义；本次同时修改实验合同，明确首对信号与完整队列准入。

| 反馈 | 修正与验证 |
| --- | --- |
| P0 Mask/ROI 空间一致性 | G1 生成前显式冻结任务专属 policy；按每个 A ROI 检查 EDIT/EVAL 覆盖率，按 ROI 并集记录目标外 Mask 占比及扩张比。错误区域、漏掉多目标之一、覆盖/扩张超出容许范围拒绝；G0/G1 独立运行不被该 G2 政策阻塞 |
| P0 R1 完整队列放行 | 一对通过仅 FIRST_PAIR_PASSED；全部预登记 3–5 对 G0/G1 执行、独立内容审查、ROI 有效性明确通过且至少一对联合成功，才 GO_TO_R2。每对状态保留，缺失/失败/缺评审阻止放行；R1 不标记真实效益验证 |
| P1 H3 粒度 | 评审包分配中性 ROI ID，roi_attributes 按 ROI/dimension 录入和独立裁决；整图 attributes 不广播。无标签或未裁决保持 unknown；错误/重复 ID 拒绝；局部标签分歧不改写整图共识 |
| P1 可比较性传播 | 保留冻结 ROI 和 Diagnosis 的原状态、理由及置信信息，任一 partly_comparable 继续保留不确定性；多来源局部目标保留全部 ROI ID |
| P2 端点指标命名 | 分开任一通道端点比例与编码显示亮度端点比例；饱和红色反例通过。evaluator 升为 r2，不推断传感器裁剪或 HDR 恢复 |

独立复核另发现一项关联缺陷：首对盲评锁住快照后，剩余 R1 完成也无法最终汇总。已补回归并修复：中间快照按 manifest SHA 不可变保存，后续同队列可导出新最终包；历史评分始终绑定历史快照，最终评分不能复用旧匿名代码，最终包仍只冻结一次。独立复核实际重跑“首对通过→同队列完成剩余样本→新最终评审→GO_TO_R2”，以及无进展、完成行改变、评分重绑定、重复最终导出等拒绝路径，全部通过；复核范围内无剩余待修项。

本轮先运行反例：10 项初始反馈回归失败，修正后 63 项相关测试通过；关联快照缺陷另有一项先失败、后通过的端到端回归。本轮共新增 14 项测试，最终验证如下：

| 0.2.1 最终验证 | 结果 |
| --- | --- |
| 完整回归 | **362 passed**，246.29 秒；4 条既有进程锁测试的 multiprocessing fork 弃用警告 |
| 静态与源码 | 既有设计 validator **181 PASS**；compileall、完整暂存 diff 空白检查、文档链接/示例 JSON 检查通过 |
| 独立安装 wheel | 0.2.1，在仓库外的独立 venv 实际导入并完成 create/start/export/evaluate；editor 恰为 A/B/text；53 个包内源码/资源文件逐字节匹配当前源码 |
| 合成完整链 | G0/G1 COMPLETED，G2 skipped_not_eligible，缺独立评审仍 PROBE；未调用模型 |
| 独立复核 | 五条返回意见的修正无新增待修项；另发现并修复的中间快照问题通过独立同队列续跑与拒绝路径验证 |

0.2.1 wheel SHA256：`d75353b39e9819e4c660a525a18c94494903963f424957ad713552fc0cf3f69c`。R1 门槛回归使用人工色块和模拟阶段标记，只测试决策分支，不产生真实 R1 证据。

真实 R1/R2 与实际 Executor Mask 能力仍未运行。当前缺少已确认配对的真实 A/B、实际编辑输出和独立人评；这些是下一步实验输入，不由上述单测替代。修正完成后的实验优先级仍为首对 G0/G1 → 完整 3–5 对 R1 → 决定 R2；G2 单独等待真实能力和空间政策通过。
