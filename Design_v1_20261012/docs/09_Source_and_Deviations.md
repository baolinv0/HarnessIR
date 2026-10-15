# 来源、锁定与与官方差异

## 已核验的一手来源

- 官方仓库：https://github.com/PolyU-VCLab/HarnessIR
- 本包锁定 commit：`3c48c206bb15027366dd9326e8e1fa552c6e6542`（2026-10-08）。文件 SHA 与 bytes SHA-256 见 `reference/source_lock.json`。
- 论文入口：https://arxiv.org/abs/2610.10133 （本包工程依据主要为上述锁定代码；未声称完成全文复现审计）。
- ChatGPT Work：https://learn.chatgpt.com/docs/get-started-with-work
- 本地 / 云端说明：https://learn.chatgpt.com/docs/use-chatgpt
- 图像生成 / 编辑：https://learn.chatgpt.com/docs/image-generation
- 本地访问条件：https://learn.chatgpt.com/docs/enterprise/cloud-local-access

核验日期：2026-10-12。官方说明支持在工具可用时进行本地文件操作，并有图像生成 / 编辑能力；这不是一个特定 Windows 账户上的能力通过证明，也未建立本方案所需的“文件变化自动唤醒会话”保证。

## 官方代码核对发现

Diagnoser 的字段是 content / degradations / sensitive / tool_plan / difficulty_hint / difficulty_reason；不是此前示意的 degradation_types / severity 字典。工具计划由 VLM 按图决定。Composer 返回 instruction 及区域 / treat / preserve 等信息，接收原图与工具视觉证据。Verifier 不看生成 Prompt；可比较所有历史输出；needs_redo=false 不一定代表成功，也可能表示剩余信息不可恢复。官方 best_round 从 0 开始。

官方默认 configs/default.json 关闭 redo；本方案默认最多 3 次是为了你要求的闭环，单次对照单列。原版 Composer 指令长度规定为 400–800 英文词；适配版选择 150–350 英文词，属工程设计假设，需实测。不能据此称“忠实原 Prompt”。

## 差异登记

| 项目 | 锁定官方实现 | 本方案 | 影响 |
|---|---|---|---|
| VLM | 配置中的 Gemini 路径 | 用户选择的 ChatGPT 显示模型 | 诊断、工具计划、策略与评审可能变化 |
| Executor | 配置支持 NB2 与 GPT image 路径 | ChatGPT 桌面图像编辑，后端可能不暴露 | 无法保证同参数 / 分辨率 / seed |
| 交接 | API 同步调用 | 文件与用户会话；能力探测后增强 | 人工操作与时延需报告 |
| Prompt | 官方原文 / per-type blocks | 本包适配版与固定 checklist | 修复力度与判定规则可能变化 |
| Schema | 原字段 + 宽松解析 | 保留核心字段，严格外层协议与类型 | 格式错误阻塞，不隐式 coercion |
| 几何 | size_match exact 等 gate | 宽高比 ≤2%，尺寸变化记录 | 原版 gate 结果不能直接等同 |
| 颜色与后处理 | 原 pipeline 可执行相应对齐 | 默认保留原始生成图，无对齐 | 与原结果的外观 / 指标可能变化 |
| 选图 | verifier / continuous / NR fallback | first accepted，最后比较索引，失败 fallback 标记 incomplete | 不能混称同一 best-of-N |
| 重试 | 默认关闭；启用时从原图 | 默认上限 3、成功停止 | 需控制生成预算 |
| 工具 | 仓库指定模型 | 本地现有工具上传，模型与权重写 metadata | 证据质量不一致 |

所有适配版任务使用 profile_id=`chatgpt_adapted_v1`。官方快照仅供比对，放在 `reference/official/`，保留 MIT LICENSE；它不是第二套已验收运行模式。要验证原 Prompt，需要另建冻结 profile、正确装配 TASK_BLOCK / 色彩规则 / measurements / 图片顺序，再单独验收。不要仅换文件名就标“official”。

`source_lock.json` 保留来源与哈希；官方完整 Prompt 不与适配模板混写。任何未来模板修改新建 profile_id，旧 case 始终可追溯。
