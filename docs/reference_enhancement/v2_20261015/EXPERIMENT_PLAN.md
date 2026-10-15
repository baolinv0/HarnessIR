> 本文件保留 PR #3 的设计/预注册基线。实际实现、命令和验证边界见 [RUNBOOK.md](RUNBOOK.md) 与 [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)；真实 R1/R2 尚未运行。

# HarnessRefEnhance v2 — 实验计划与可证伪决策协议

**版本**：v2_20261015；**状态**：预注册方案草案，未运行模型、不报告虚构结果。**目的**：用最小生成预算验证生成式参考引导亮度/颜色/影调增强，以及语义文本和 Mask 的真实净增益，而非为发表论文补齐完整消融。

## 1. 测试假设

| ID | 假设 | 可证伪对照 | 不支持时的解释 |
|---|---|---|---|
| H0 | DirectRef G0 能让 A 朝参考 B 的亮度/颜色/Tone 改善且不破坏内容 | A vs G0，独立人评+冻结 ROI 属性；单次输出 | 当前 Executor 的参考外观跟随可能不足、数据不适配或目标不可实现 |
| H1（主比较） | G1 语义/ROI 诊断→短 Prompt 比 G0 直接参考编辑更好 | G1−G0，同 Executor、同 A/B、每臂仅 1 张 C | Harness 额外感知/Composer 可能没有增益，甚至过度保守 |
| H2（能力条件） | 对真正局部任务，同一 Executor 的 G2 Mask 辅助优于 G1 | G2−G1，仅在预登记局部 mask 合格组，同 prompt、同模型、同生成数 | Mask 没起作用、污染/边界副作用大，或执行器不擅长局部控制 |
| H3（评价有效性） | 冻结 ROI 属性距离变化可以解释人工参考接近度 | Per-ROI delta vs 独立人评标签/理由；记录冲突 | 量化不足以代表知觉/内容真实性；不可自动闭环 |

H1 与 H2 不应混为一个结论；G2 如换模型/transport，不能从跨模型差异声称 Mask 因果作用。真正风险是「输出更像 B 但其实复制了 B 的物体/文本」，此情形必须失败。

## 2. 三个生成式实验臂（全部从冻结 A 起始）

| Arm | 模型输入 | 辅助工具 | 预算 | 变量 |
|---|---|---|---|---|
| G0 DirectRef | A+B+固定简短 reference Prompt | 评价侧保留同一冻结 ROI，不用于编辑 | 1 张/对 | 无诊断最小基线 |
| G1 AgentText | A+B+Composer 短 Prompt（从真实诊断和计划内 ROI/T4 证据得到） | T4/ROI/STATS 仅分析；执行器不接彩色地图 | 1 张/对 | 诊断与指令 |
| G2 AgentMask | A+B+**与 G1 同一版、同一字节的动态 Prompt**+已验证的 EDIT_MASK | 与 G1 同源区域证据，但增加经能力探测的 mask 输入 | 1 张/合格局部对 | 唯一新变量是 mask 条件/声明过的适配包装 |

G0/G1 都可使用原 PR #2 的两图手动执行通道。G2 只有 Executor 在真实 probe 中支持且存下 exact payload 时才能入正式对比；仅支持 ChatGPT 桌面两图编辑，不等于支持 mask。

G2 适用集事先标记 local_mask_eligible=true，要求目标确实局部、mask 有可靠面积与边界、未过度覆盖文字/身份区域，且 G0/G1/G2 使用同一 Executor + transport / image resolution / settings。全局亮度/颜色任务不强行加入 mask，不将“G2 不适用”计成 G2 画质失败，但要报告合格比例。若希望在不支持 mask 的桌面端继续研究，只运行 G0/G1；另一个可运行 G2 的执行器须独立重新做 G0/G1 对照。

## 3. 数据准备和入组

### 3.1 真实配对

每个场景保留：
- A：Modular Neural ISP 原 prediction；上游 RAW/捕获 id、生成命令、Git commit、checkpoint SHA、色彩空间和导出参数（缺失记 unknown）；
- B：iPhone 17 同场景数秒内参考图；原图/EXIF/ICC、设备/镜头、时间间隔（可观测者录入）、SDR/HDR 输出及可追溯 SDR 规范化；
- 配对证据：scene_group_id、捕获时间差、照明是否稳定、明显移动/遮挡、视角和曝光差别；
- A/B 可比 ROI pairs（各自独立坐标、材质、目标属性、遮挡/裁剪标记）、A 保护内容、G2 合格判定与 mask 来源/版本、同源变体关系；
- 所有文件原始 SHA/规范化像素 SHA、split 和标注冻结时间。

不因原图有几秒差异就先验拒绝 reference；反之对 A 已彻底裁剪的细节不可宣称从 B 忠实恢复。禁止将 B 当 A 的像素 GT 或按同位置比较 A-B 像素。

### 3.2 样本结构与分层

首先不建立新论文级数据集，只使用用户已有真实 A/B：
- R1 开发/链路：3–5 对，尽量覆盖（i）全局亮度差，（ii）白平衡/色彩倾向差，（iii）高光阴影 Tone/对比差，（iv）局部区域明暗差；优先包含 1 对人物或文字，允许一图包含多标签；
- R2 Pilot：12 对，尽量 12 个不同 scene_group；夜景/背光/室内混合光/室内日光/室外均匀光至少覆盖，局部 mask 合格组从同批样本事先标定；计数不足时诚实报告；
- R3 冻结外部验证（只有 R2 GO 后）：建议独立 test ≥60 对且场景 group 隔离；数量取决于效应与业务最小有价值改善，不保证统计功效。

同 RAW、同场景 burst、不同编辑生成候选必须继承同一 scene_group 与 split；R1/R2 的 dev/pilot 样本不得混入独立 test。R1 可用于调 Prompt、Mask 转换和指标；R2 只能依预先冻结的版本做决定，R2 后若改动须开 revision，不能继续把同批结果当独立验证。

## 4. 阶梯流程（每一级仅回答必要问题）

### R0：零生成合同与能力测试

既有 PR #2 文件/事务/预算/几何/恢复/盲评静态行为应回归测试。新增 v2：
1. v1 两图 bundle 原样工作；G0/G1 编辑器只接 A,B,prompt；
2. EDIT_MASK 在 capability=untested/unsupported 时，G2 拒绝发起/冻结，记录 skipped_capability，不进入已确认执行统计；
3. 输入绑定 mask SHA、A pixel SHA、宽高、target ROI、输入角色、mode、模型版本、实际送达情况；
4. 正/负例 probe 确认 mask 语义、A/B/M 顺序及非目标像素变化；彩色 segmentation overlay 不能默认为 mask；
5. 错 A、B、mask、错误坐标/尺寸、mask 反相、能力过期、没有完成输出、重复任务、超预算等必须停机/隔离；
6. A/C 评价 ROI 只从冻结 A 坐标映射；B 仅自身 ROI；变形/缺失标签不输出假指标。

完成结果只是“协议/某执行器 mask 能力可用”，不是画质有益。

### R1：真实生成最小链（3–5 对）

第一对先跑 G0/G1 各一次（并保存直接生成的 raw）；具备 mask 接入能力才运行 G2。若真实链不通，先修工程不扩数据。其余 2–4 对在相同 Executor 下执行。

全部候选必须记录：任务 id、A/B 角色、执行器和可见模型名、可观察 seed/settings、prompt SHA、mask SHA (G2)、文件 SHA、提交/下载/失败、ROI 指标、内容风险、手动 active time。不可观测填 unknown/null。每臂只保留供应商第一个完整结果，拒绝人工挑最漂亮的候选；失败计入 ITT。

R1 只决定是否继续 12 对 pilot，不凭 3–5 个样本宣称 G1/G2 总体有效。

### R2：12 对定点 Pilot

- 同一个 Executor 的 G0/G1，对所有冻结的 12 对各一次；G2 仅对预登记的 mask 合格子集各一次。最大全臂生成上限为 36 张，但实际随 mask 子集、失败而变；不能偷偷补采样。
- G1 短 Prompt 生成后冻结，G2 使用同字节 Prompt，最大限度隔离 mask 变量。
- 每对 G0/G1 的执行先后用冻结种子随机排序（建议 seed=20261015）；有 G2 时也预先随机平衡顺序，尽量同时间段/同模型与参数。无法控制 seed 或内部再生成时记录 unknown 和可观测生成提交数。
- 每张候选使用相同的 ROI、保真 rubric 和评价流程，G2 的局部 spill 用同一 target mask 同时离线计算 G1/G2。
- 对每一张 raw C 保留未选择和失败案例，不在评审前修改 C、颜色修回 A 或重新编辑。
- 正式比较前冻结 evaluator 算法版本、盲评清单、分母、阈值及重要属性；操作者不得在看到 G2 输出后补新增 ROI。

### R3：正式外部验证（条件性）

R2 通过后才开始。使用冻结代码/模型/Prompt/ROI/Mask/评价版本，独立场景 test，不重试到满意；定义 business-relevant 最小差值及成本边界，按 scene-group paired CI 报告效应。没有足够数据/功效时可以做产品 A/B 决策，但不可过度宣称总体统计显著。

## 5. 指标和可执行计算约束

### 5.1 必须同时报告三种结果

**A. 参考方向**（每个提前冻结的可信 ROI）：
- 亮度：L* 的 mean/median/p10/p50/p90；d_before、d_after 与 delta；
- 色彩：a*,b* 的区域均值偏差（可分中性白墙/肤色/植被等标签）；可加饱和度方向；
- Tone：暗部/中间调/高光的稳健分位数距离与 highlight/shadow clipped fraction；
- 一张照片需明确可比范围和目标属性，没有可信 ROI 记 not_assessable。

示意：D_before=distance(stats(A_roi),stats(B_roi)); D_after=distance(stats(C_on_A_roi),stats(B_roi)); improvement=D_before-D_after。距离的聚合/单位要由 evaluator 版本定义，**不可**把不同物理意义的数值未经标准化直接相加；near-zero baseline 单独记录，不算无限大相对收益。

**B. 内容真实性**（以 A 为锚）：
- composition/geometry/identity/text/scene content；
- 新增虚构细节、小件消失、脸/文字改变、明显重绘、接缝/色斑、严重剪切为独立 failure 类；
- geometry pixel gate 无法代替内容审查；分割/OCR 漏检不能当作不存在保护内容。

**C. Mask 净效应**（仅局部 mask 合格样本）：
- 非目标区域颜色/亮度异常变化（spill）与局部边界不连续，定义为冻结 mask 外的变动与人工审查，且仅在局部 task 使用；
- 目标 ROI 是否确有增强；mask 带来局部更接近 B 但严重内容重绘，仍失败；
- mask 失效/边界反相、output 变形、标签渗透单列。

### 5.2 核心业务成功/成对偏好

独立审核给出 style_direction={improved,unchanged,worse,uncertain}，content={pass,fail,uncertain}、critical_defects。联合成功须：改善可比目标且内容 pass 且无重大缺陷；missing/uncertain/超预算/不合法输出在主 ITT 口径下不算成功，原因单列。

主比较 H1：G1 vs G0 同 scene-group 的最终 joint_success 与独立人类成对 win/tie/loss；属性 delta 用于解释，不单独反过来决定成功。
H2：只在 mask eligible 且能力真实支持的配对子集比较 G2 vs G1，报告 n_eligible 与 skipped/missing；不拿 12 对总数和局部子集的未经配对均值做对照。
H3：ROI 方向与盲评在 case/attribute 层一致性与冲突案例，不能拿高相关自动替代人工。

### 5.3 评审盲化

冻结输出后匿名导出，隐藏 G0/G1/G2、Prompt、diag、工具/Mask 消费信息和流程 verifier 判断。每张评审展示明确内容锚 A 与外观参考 B，以及匿名 C；二名独立评审者，重大分歧第三人裁决。标出 brightness / color / tone 是否朝 B 改善和文字/人物/结构有无错误。不能让生成者或 prompt 作者评自己的案例。

评审者不看来源模型/方法，也不允许在看到可见 G0/G1/G2 结果后更改“何为更接近参考”的 rubric。评价数据与揭盲映射分别冻结。首例单人审查只算操作探索，不作正式证据。

## 6. 数据输出与统一表格

每个 (scene_group,case,arm) 一行，至少包含：
- identifiers: run_id,case_id,scene_group_id,split,arm_id,executor_model,transport,model_version,config_sha;
- assets: A_raw/pixel_sha,B_raw/pixel_sha,C_raw/pixel_sha; prompt_sha; mask_mode/mask_sha; ROI_manifest_sha;
- delivery: intended_submissions,observed_submissions,backend_regenerations_status,execution_success,geometry_pass,unknown/failed/fallback;
- attribute: per_roi/dimension/before/after/delta/validity/area; mask_target_spill and boundary warnings;
- review: blind_code,raters/adjudication,style,content,critical,win_tie_loss,review_unknown;
- cost: wall_time,operator_active_time,model/tool calls,credit/cost if observed,missing_cost_flag.

所有无法解释的结果保持 unknown/null，并提供失败原因；不能删除失败样本形成条件性胜率。run/report 中要同时给 n_pairs、n_groups、n_mask_eligible、n_evaluable、n_failed、n_unknown。

## 7. R1 / R2 的建议闸门（工程启发式，非显著性检验）

### R1 → R2
GO：真实 A/B/C 角色、源 SHA、Prompt/MASK 证明、候选保存和预算均无错，G0/G1 至少完成一对有真实审核的样本；如要跑 G2，mask adapter 的实际能力 probe 需 pass；属性 evaluator 已在人工设计的非对齐 ROI 与负例上校验。
PROBE：模型画质弱、指令偏保守、ROI 可比性不足，但合同正确；只对定位的一项变量修复后再做一小批 dev。
STOP：A/B 颠倒、预算失真、候选来源/颜色无法追踪、mask 被误当原生约束、生成内容泄漏到评估协议等。

### R2 → 是否继续大规模

判断优先级：安全/身份/内容严重缺陷 → 独立偏好 → 相同预算的净增益 → 操作成本。建议以 12 对独立场景为目标：
- G1 的继续信号：G1 相对 G0 至少净胜 3 对（wins-losses≥3，不将 tie 隐藏），内容严重失败不高于 G0，且主要改善不是仅靠过度重绘；须同时报告 joint_success 差。**这是部署试验门槛而非统计显著性**。
- G2 的继续信号：预登记合格组建议至少 6 对才能形成初步经验；相对 G1 在至少 2 对上同时显示局部参考改善或明显 spill 减少且无新增严重幻觉；若 G2 失败/不可用则放弃 G2，不妨碍 G0/G1。
- 不满足改进但不存在严重缺陷：PROBE，针对实际失败类型调整一种机制后用新 dev revision 小规模复测；不要为实验完备性强行继续。
- 如果 G1 没有胜出 G0，或 mask 的边界/内容风险超过收益，停止复杂化，把 G0 作为更简单的产品候选；若连 G0 也不能稳定改善，则优先重新考虑 Executor 而不是不断丰富 Composer。
- 任一系统性严重身份/文字重绘问题，或事实证明角色/评价链串图：STOP 当前推广。

## 8. 预算、阶段交付及不允许的结论

- R0：不生成参考增强 C；R1：G0/G1 每对 1 次，G2 对合格且能力通过的局部样本 1 次；R2：12 对 G0/G1 共 24 次，G2 最多再 12 次，总上限 36 次可观测生成提交（不含 R1），发生失败/后台已知重生也计预算。
- 提示和 VLM 观察另统计 wall time、人工 active time、显式调用和未知账单；不能把桌面订阅称零成本。
- **暂不启用 Adaptive/BestOf3**。后续若验证 feedback 有用，需构建预算严格相同的 DirectBestOf2 对照，且重新开 v2.1 实验，不用多次 Agent 结果与单次 DirectRef 比较。
- 不允许声称 B 是 GT、A/B/C 像素 PSNR 证明风格趋近、Mask 被硬执行、分割一定有害、G2 的跨模型结果说明 Mask 增益、R1/R2 的 12 张有统计代表性、已跑真实案例。

## 9. 交付检查

最终必须交付：frozen_manifest + ROI/mask prelabel + capability_probes + G0/G1/G2 exact prompts + raw C + per-attribute A/B/C statistics + content observations + independent blinded ratings + ITT tables + reason-coded failures + costs + decision memo。

若无法获得这些原始证据，即使生成案例视觉上好看，也仅能报告 exploratory sample；不可写“已通过参考增强正式验收”。
