# NEXT_STEPS_R1 — 真实参考增强实验执行计划

**基线**：HarnessRefEnhance v0.2.1，修复提交 \`2d10351d6af0020d52f46b0e61ad458974db0648\`，PR #4  
**记录日期**：2026-10-15  
**状态**：PLANNED / real G0-G1 **not_run**；以下是执行方案，**不是实验完成报告**。  
**依据**：[设计](DESIGN.md) · [冻结实验合同](EXPERIMENT_PLAN.md) · [实际 CLI 手册](RUNBOOK.md) · [实现状态](IMPLEMENTATION_STATUS.md)

## 0. 本轮要回答的问题与停止扩张原则

本轮只回答：针对数秒间隔拍摄、基本相同照明与内容的同场景真实配对 A（Modular Neural ISP prediction）/B（iPhone 17 外观参考），生成式编辑能否在保留 A 内容的同时改善其亮度、颜色和 Tone？**G1（Diagnose + ROI/证据 + Composer）是否比 G0（A+B 直接编辑）产生可观察的净增益？**

- 本轮只做生成式编辑；不训练新模型，不增加确定性 Renderer，不修改 Neural ISP。
- G0/G1 均为 **同一 Executor、相同可观测设置、同一原始 A+B、每 arm 最多一次生成**。只接受供应商顺序中第一个完整输出，保留 raw C；不人为挑图，不用失败图片继续编辑。
- 不把 B 当成像素 GT，不拿 A/B/C 非对齐像素 PSNR、SSIM 或 NR-IQA 均值宣称风格成功。
- G2 Mask 维持 **SKIPPED/untested**。真实 A+B+Mask 的同 Executor 能力探针及入组前冻结的 Mask/ROI 空间政策通过之前，**不执行 G2、不阻塞 G0/G1**。
- 本轮不追加“为了完整性”的多模型、多 seed、多轮 refine 或大样本实验。结果负面时允许停止并保留证据。

## 1. 实施前：冻结 3–5 对完整 R1 队列（必须先于首次生成）

**数据入组负责人**：实验执行人；**独立评审**：至少两位未参与同 case 指令/生成/选图的评审者，分歧再引入第三位。具体身份在实际 manifest 填写，不在此文档虚构。

- [ ] 选定 **3–5 对真实 A/B**，优先 3 对做最小闭环；覆盖至少：整体亮度/曝光差、白平衡/色彩倾向差、局部或高低光 Tone 差；尽量包含文字/人物保护风险。若同一张覆盖多个属性，避免为凑数重复同场景。
- [ ] 确认 A 是未经修改的 Modular Neural ISP prediction；记录上游 RAW/capture 标识、checkpoint、推理命令、颜色导出及实际 SHA。未知项明确 \`unknown\`，不得编造。
- [ ] 确认 B 的 iPhone 17 来源和数秒配对关系；保留原图、EXIF/ICC、可观测时间差、设备与镜头、SDR/HDR 导出说明。不可解释的 HDR / ICC 不应无记录强行转换为 sRGB。
- [ ] 在看任何生成 C **之前**固定每对 A/B 的独立 ROI（各自坐标）、同材质/稳定光照可比较性、目标属性（brightness/color/tone/saturation）、不可比原因，以及 A 上需保护的人物、文字、几何。允许首轮只使用可信手工 box/polygon，不强迫运行 T1–T4。
- [ ] 冻结所有入组 \`scene_group_id\`、\`split=dev\`、ROI/标注、A/B 原件及 canonical SHA、实际 Executor 身份与可观察设置。G2 不适用时 \`g2:null\`；若后续增加 G2，须新实验 revision，不追溯修改现有 G1 实验。
- [ ] 确认 \`simulation_only=false\`；\`excluded_rater_ids\` 排除生成者、提示词撰写/选择人员。R1 必须先完整冻结 3–5 对；**禁止先跑一对再看效果补选剩余数据**。
- [ ] 安装/校验当前 v0.2.1 engine；实际 \`code_commit_sha\`、包/资源/环境、Prompt、统计定义写入 run；冻结后换安装源码、模型、Prompt、ROI 或颜色策略必须建立新 run revision。

**输出**：\`r1_manifest.json\`、每对的真实 \`G1.spec.json\`、可追溯原图与标注/ROI、冻结 run 目录。模板位于 \`examples/G1.spec.json\` 和 \`examples/run_manifest.json\`，示例值和占位符不得充当真实证据。

## 2. R0：执行环境与手动交接检查（零真实生成收益声明）

- [ ] 在本机执行 v0.2.1 \`python -m hre --help\`，核查版本与运行环境；必要时重新运行 \`python -m pytest engine/tests -q\`，区分仓库报告（362 passed）与本机实际结果。
- [ ] 对真实 A/B 创建冻结运行计划并核对 \`run-status\`：G0/G1 均为 planned，每对一轮，G2 为 \`skipped_not_eligible\` 或 \`skipped_capability\`，不把 skipped 作为生成失败。
- [ ] 检查 G0/G1 Export 的 \`editor/\` **恰好**只有 \`A.png\`、\`B.png\`、\`edit_prompt.txt\`；A=编辑底图、B=外观参考；图片尺寸和颜色转换可追踪。禁止把彩色 segmentation overlay / ROI 图作为额外编辑器附件。
- [ ] 用真实桌面会话核查两图角色与首个完整输出的手动派发/保存；所有可观察设置及操作者步骤记录到 \`executor_observation\`。若桌面 API/自动操作未经实测，使用原手动文件交接协议。
- [ ] 记录无法观测的 exact model version、seed、后台采样与账单为 null/unknown；若提交事实不确定则按已有 \`task unknown\` 暂停，**不要直接点击重发导致超预算**。

**闸门**：错误 A/B 身份、图片原件/颜色无法追溯、导出多余附件、预算/提交不确定而仍推进，均先停机修复，不进入正式计分。

## 3. 第一对真实 G0/G1（R1-First Pair）

- [ ] 用 \`run-prepare\` 初始化同一 \`case_id\` 的 G0 和 G1；遵循冻结 \`execution_order\`。G1 可先运行 Diagnose→计划内证据→Compose 以冻结 Prompt；实际图像生成的先后仍按冻结顺序。
- [ ] G0：仅上传 A+B+冻结 DirectRef Prompt。G1：Diagnoser 观察 A/B，Composer 选择 **1–3 个确有证据的亮度/颜色/Tone 方向**，最终英文编辑 Prompt 不超过 160 词；执行器仍只接 A+B+文本。不能增加“保持 A 原曝光/原颜色”的相互矛盾条款。
- [ ] 两臂各提交一次，保留原始下载的第一张完整 C（即使不好）；记录提交/完成时间、Executor/Settings、request SHA、编辑 prompt bytes SHA、A/B/C SHA、实际次数、人工 active time、失败与未知成本。
- [ ] 导入候选与真实 Verify；分别核对 C 对 A 的内容/几何/文字/人脸/小目标保真，及 C 朝 B 的可比 ROI 亮度、色度、影调变化。比较 \`before=d(A_roi,B_roi)\` 与 \`after=d(C_roi,B_roi)\`、\`delta=before-after\`。正 delta 只代表该属性的距离缩小，不自动意味着“整体成功”。
- [ ] 手工审看典型失败方向：G1 过度保守、G0/G1 只变亮不变 Tone、局部过度改变、文字/人脸/物体虚构、场景重绘、纹理变形、高光失层次。定量 ROI、内容审查和主观偏好分开登记。
- [ ] 导出 **\`r1_progress\`** 中间盲评包，两名独立评审对 G0/G1 做 style/content/critical defect 与同场景成对偏好；H3 要求 ROI×属性粒度时填 \`roi_attributes\`，不可用整图 \`attributes\` 代替。
- [ ] 汇总首对：\`FIRST_PAIR_PASSED\` 仅表示可以继续同一队列；若没有提升则记录 PROBE/失败，不为了制造通过而重试、换 Prompt 或换模型。

**必留产物**：原始 A/B/C，冻结 G0/G1 Prompt，诊断/证据与 response/done，实际执行观察、预算台账，geometry/Verify，ROI 指标，独立评审与首对总结。不得把合成示例里的 positive flag 当真实结果。

### 命令骨架（填写实际路径、ID、metadata；与 RUNBOOK 合同一致）

\`\`\`bash
# 在真实 G1 输入 case 全部准备完成且未生成 C 后冻结队列
python -m hre v2 run-freeze --manifest /data/r1_manifest.json --out /data/runs/r1_v1
python -m hre v2 run-status --run /data/runs/r1_v1
python -m hre v2 run-prepare --run /data/runs/r1_v1 --case-id case01 --arm G0
python -m hre v2 run-prepare --run /data/runs/r1_v1 --case-id case01 --arm G1

# 两臂分别启动并导出当前任务；G1 依次导入真实 Diagnose/Compose 回复
python -m hre case start --case-root /data/runs/r1_v1/cases/case01/G0
python -m hre task export --case-root /data/runs/r1_v1/cases/case01/G0 --out /data/handoff_case01_G0
python -m hre case start --case-root /data/runs/r1_v1/cases/case01/G1
python -m hre task export --case-root /data/runs/r1_v1/cases/case01/G1 --out /data/handoff_case01_G1

# 按 RUNBOOK 导入真实 stage payload、首个完整 C 和 metadata，再 Verify。
# 下方命令只负责读取冻结评价；不能自动替代独立人评：
python -m hre v2 evaluate --case-root /data/runs/r1_v1/cases/case01/G0
python -m hre v2 evaluate --case-root /data/runs/r1_v1/cases/case01/G1

# 完成首对后可先出进度包，但不能用进度包放行 R2
python -m hre v2 blind-export --run /data/runs/r1_v1 --out /data/review/r1_progress_1
python -m hre v2 analyze --run /data/runs/r1_v1 --ratings /data/review/r1_progress_ratings.json
\`\`\`

注：示例路径为占位；\`run-freeze\` 所要求的 source input cases 必须事先按 \`v2 create\` 正式准备。真实 Diagnosis/Compose/Verify 的 JSON 导入及 candidate metadata 字段见 [RUNBOOK.md](RUNBOOK.md)。所有 \`--out\` 指向新目录，禁止覆盖现有 Data。

## 4. 继续剩余冻结 R1（3–5 对，不扩新臂）

- [ ] 对剩余每对重复相同 G0/G1 的单次生成和验证，保持模型/设置、出图选择、Prompt 约束及评价规则不变；逐 case 的正式输出及失败均留在 ITT。
- [ ] 首对 \`r1_progress\` 的盲评快照不可变；跑完剩余 arm 后使用**新的评审输出目录**导出 \`final\` 盲评包、新匿名代码和全量独立评价。旧首对 ratings 不得替代最后总评。
- [ ] 如遇第三评审裁决，保留两份原始意见、第三人意见与分歧原因。review 未解决、内容保真失败、ROI 不可评价的样本不算 joint success。
- [ ] 输出每个 case 的 G0/G1 联合成功、G1−G0 成对 win/tie/loss/unknown、亮度/颜色/Tone 分 ROI 距离、内容严重缺陷、actual submissions、人工时间/未知费用与流程阻塞类别；记录 G1 是否仅变得保守/仅变得更亮但损害夜感等替代解释。

## 5. 决策与 GO / PROBE / STOP（v0.2.1 的真实协议）

- **FIRST_PAIR_PASSED**：只有至少一对已完成、独立审查且存在联合成功，但 R1 队列未完成；**只允许继续 R1，绝不放行 R2**。
- **GO_TO_R2**：冻结的全部 3–5 对 G0/G1 都完成、独立内容审查有效、ROI 有效，且至少一对出现 joint success，并经过 \`final\` 全队列盲评；这只说明**可投入 Pilot**，不说明 G1 比 G0 好或统计显著。
- **PROBE**：候选失败、参考方向不足、指标不可比较、评审缺失或系统返回 PROBE；优先归因原因，不为了凑 GO 大量补跑。修改 Prompt/ROI/模型要新 revision，不改原队列。
- **STOP**：发现身份/文字/内容转移、几何等严重风险或 A/B 串图、证据/预算丢失；先记录和隔离，审查原因，不继续无效投入。按现有系统区分对 arm 的失败、对整个运行链的工程阻断。
- **G2**：继续 SKIPPED。另有真实 A+B+Mask probe、同 Executor G1/G2 paired prompt、冻结 Mask/ROI coverage/outside policy 和局部样本，才进入后续独立条件性试验。

**重要解释**：R1 的 GO_TO_R2 是工程就绪门槛，不是证明 Agent 增益。真正判断 G1 增益必须看 G1 vs G0 的成对偏好、joint success 差、内容缺陷和成本。若 G0 已经足够好、G1 没有可观察净收益，下一步可以优先采用 G0，停止增加 Agent 复杂度。

## 6. 完成定义（DoD）与交接

| 交付件 | 必须包含 | 未完成则状态 |
|---|---|---|
| 采集/入组账本 | 真实 A/B、上游来源、时间/设备、色彩/ROI、scene_group 与冻结 hash | 不能宣称真实 R1 |
| 执行事实 | G0/G1 每臂一个 planned row、真实 first C 或真实失败/暂停、model/setting/prompt/input/output 绑定、次数与时间 | 不可将缺失结果当成功 |
| ROI + 保真 | 逐 ROI/属性 before/after/delta/可比性、内容/几何/文字/人脸保护和不确定性 | 缺失指标标 not_assessable |
| 独立盲评 | 至少两名独立评审、冲突裁决、盲码与最终完整快照，匿名方法偏好 | unresolved；禁止 GO_TO_R2 |
| 结论与下一步 | 首对状态、完整 R1 状态、G1/G0 净胜负、失败类型、时间/成本、是否需要 R2 | 不得宣称已验证增强有效性 |

**下一执行动作**：整理真实 3–5 对 A/B，完成 G1 输入 case 和 R1 manifest 冻结，按冻住的次序跑首对 G0/G1。没有真实数据就只报告准备缺项；不创建模拟照片伪装真实实验。默认不再新增模型或 Agent 结构。

本计划只记录下一步动作和通过条件；实际产物/执行时间/评价记录由本轮真实 run 存档。