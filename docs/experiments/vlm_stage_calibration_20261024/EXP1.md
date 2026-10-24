# HarnessIR–Qwen 实验报告：EXP1 Compose P0/P1 A/B

模板版本：v1.0（依据 `docs/experiments/QWEN_HARNESSIR_EXPERIMENT_REPORT_TEMPLATE.md` 填写）
报告日期：2026-10-23

> 本轮仅实际运行 **E1**。E2/E3/E4 明确标记"未运行"。

## 1. 结论先行

- 实验 ID：EXP1_COMPOSE_P0P1
- 日期：2026-10-23；服务器代码：**仓库无 git 版本控制**（`git log` 无输出），以文件 md5 快照代替 commit（见 §2）。
- 本轮：E1（compose P0/P1 对照）。E2/E3/E4 未运行。
- 数据范围：5 张预定 dev 图（night_0043/0049/0042/0024/0028）× 2 臂（P0/P1）× 2 配对 seed（0/42）= 20 次生成，**20/20 成功**，无失败配对。
- 一句话结论：**P1 compose 改善 Qwen-HarnessIR 的恢复不足**：运动模糊主体（0043 车轮/立面）两 seed 一致地出现有界结构重建，4/5 图暗部亮度提升；未见新的严重内容错误；唯一退步是 0049 全图亮度略降（P0 0.249/0.273 vs P1 0.217/0.226），且该图 P0 光源光晕更膨胀，属亮度-光晕权衡。

| 阶段 | 实际覆盖 | 核心观测 | 达到预设标准？ | 证据强度 | 决策 |
|---|---|---|---|---|---|
| E1：compose P0/P1 | 5图×2臂×2seed，20/20 成功 | P1：2 明显胜 + 3 平/略胜 + 0 败；0 严重内容错误；seed 一致 | **是**（改善多于退步、seed 一致、无新严重错误） | 自动指标（混合）+ 执行者目检（非盲）+ 日志核对；独立盲评材料已备未做 | P1 条件采用，进入 E4 组件池 |
| E2：文字 T0/T1/T2 | 未运行 | — | — | — | — |
| E3：verifier V0/V1 | 未运行 | — | — | — | — |
| E4：端到端 S0/S1 | 未运行 | — | — | — | — |

结论分类：**部分支持偏支持**。区分说明：luma/sharp 为自动指标（结果混合，不作判决依据）；逐图胜负为**实验执行者目检（非盲）**；`grid_s{0,42}.jpg`（X/Y 盲标）+ `blind_key.json` 已生成，可供独立盲评复核。

## 2. 配置、变化项和证据链

| 配置 | 实际值或附件位置 |
|---|---|
| 服务器实现版本 | 无 git 仓库；关键文件 md5：`prompts/compose_p1.txt` a95b24b2、`prompts/compose.txt`(P0模板) 5dea3d8d、`harness/stages/compose.py` c6ace381（含 `HARNESS_COMPOSE_POLICY` 开关，compose.py:266-271）、`harness/stages/execute.py` 1e234d82（RGBA→RGB 修复版）、`tools/exp1_compose_ab.py` af494fd9 |
| Executor | Qwen-Image-2.1（`pretrained_model/Qwen-Image-2.1`，QwenImage21Pipeline，bf16，未量化） |
| VLM | Qwen3-VL-27B @ 8001，`--reasoning-parser qwen3`；diagnosis/compose 采样 temp 0.6 / top_p 0.95 / top_k 20，max_tokens 8192，thinking 开启（内容入 `reasoning_content`，仅解析 content） |
| 推理 | steps 40、CFG 4.0、negative prompt "低画质，模糊，噪声，过曝，过暗"、scheduler 默认 flow-match、seed {0, 42} |
| 几何 | 原图 1024×1024（Real-NoGT-200 已统一），输入/输出均 1024×1024，无 crop/pad |
| 后处理 | RGBA→RGB 转换（本轮前已修复，见 §8）；无 gamma/颜色后处理；交付图 = 生成图 |
| redo | **未启用**（E1 固定首轮单生成，不含 redo/verifier） |
| 指标 | luma = RGB 转灰度均值/255；sharp = 灰度 Laplacian 方差（全图，probe_v1 口径，RGB 转换后计算）；focus ROI 本轮未冻结，见 §8 限制 |
| 设备 | GPU0（RTX PRO 6000 95GB）；torch 2.9.1+cu129.msh，diffusers 0.37.0.dev0 |
| 复现 | `python3 tools/exp1_compose_ab.py`（需 GPU0 空闲 + VLM@8001）；日志 `logs/exp1_compose_ab.log`；结果 `runs/exp1_compose_ab/`（`index.json`、`runs.csv`、每图 `prompt_p0/p1.txt`、raw PNG、grid/roi_compare） |

- **冻结条件**：诊断、工具证据、执行器、输入、seed、推理参数两臂完全一致；逐图串行，臂序 P0→P1。
- **唯一计划变化项**：compose 策略（P0 现行模板 vs P1 两级保真模板），经 `HARNESS_COMPOSE_POLICY` env 切换，两 compose 调用间强制 `/clear` 防上下文污染。
- **预设通过条件**：改善图像数 > 退步图像数；seed 一致；无新的严重内容错误；不以 sharpness 倍数为通过条件。
- **中途变化及偏离**：无。
- **实际发送的最终 prompt**：每图 `runs/exp1_compose_ab/<img>/prompt_p0.txt` / `prompt_p1.txt` 全文存档（各臂 1 条正向 prompt，负向 prompt 见上）。P0/P1 模板 md5 见上表。P1 长度 4108–5244 字符，P0 长度 3885–4634 字符。
- **历史结果复用情况**：无复用——两臂 prompt 必不同，20 张全部新生成；probe 阶段图（不同 prompt/配置）未复用。

**P1 指令行为抽查（0043）**：P1 实发 prompt 含 "restore it to a coherent sedan with a clean roofline, a defined door line and panel edges, and a rear wheel that reads as a wheel with a defined rim, all consistent with the surviving shape and without adding parts the smear does not support"——终态可检查 + 有界许可，符合模板意图；5 条 P1 prompt 均无 "Tier/licence" 等模板术语泄漏（grep 核对）。P0 实发 prompt 未见字面 "涂成平滑表面"，但含 redo 时代 "Do not use redo rounds to invent detail" 类抑制性措辞且无重建许可（`prompt_p0.txt` 可查）。

## 3. 配对结果明细

计划配对 10（5图×2seed），实际成功 10/10，无法比较 0，排除 0。每图 2 seed 为配对观测，**非独立图像**（有效 n=5 图）。无 GT，清晰结构仅报告"合理性/可见结构一致性"，不宣称真实细节重建。

| image_id | split | arm_a | arm_b | seed | 主要指标 A→B（luma / sharp） | 偏好 | 严重内容错误 | 证据 |
|---|---|---|---|---:|---|---|---|---|
| night_0043 | dev | P0 | P1 | 0 | 0.124/261.6 → 0.190/244.6 | **B胜**（车轮+立面重建，更亮） | 无 | roi_compare.jpg, grid_s0.jpg |
| night_0043 | dev | P0 | P1 | 42 | 0.126/222.4 → 0.199/256.4 | **B胜**（同 seed0，一致） | 无 | roi_compare.jpg, grid_s42.jpg |
| night_0049 | dev | P0 | P1 | 0 | 0.249/386.6 → 0.217/313.2 | 平（P0更亮但光晕更膨；文字两臂均未解决） | 无 | roi_compare.jpg |
| night_0049 | dev | P0 | P1 | 42 | 0.273/312.9 → 0.226/271.4 | 平（同 seed0） | 无 | roi_compare.jpg |
| night_0042 | dev | P0 | P1 | 0 | 0.141/171.2 → 0.178/223.6 | B略胜（更亮，斑马线结构相当） | 无 | roi_compare.jpg |
| night_0042 | dev | P0 | P1 | 42 | 0.150/150.9 → 0.223/265.1 | **B胜**（明显更亮更干净） | 无 | roi_compare.jpg |
| night_0024 | dev | P0 | P1 | 0 | 0.095/116.3 → 0.128/191.2 | B略胜（更亮；猫纹理相当） | 无 | roi_compare.jpg |
| night_0024 | dev | P0 | P1 | 42 | 0.109/133.8 → 0.129/158.8 | B略胜（同 seed0） | 无 | roi_compare.jpg |
| night_0028 | dev | P0 | P1 | 0 | 0.135/416.4 → 0.196/398.0 | B略胜（更亮、天空可见；尾灯控制相当；无假字） | 无 | roi_compare.jpg, grid_s0.jpg |
| night_0028 | dev | P0 | P1 | 42 | 0.147/444.5 → 0.201/360.9 | B略胜（同 seed0） | 无 | roi_compare.jpg |

指标说明：luma 提升 4/5 图（0049 除外）且 seed 一致；全图 sharp 两臂互有胜负（0049/0028 P0 更高，0042/0024 P1 更高，0043 分裂），与预期一致——全局 sharp 对"涂开 vs 噪声/光晕"无判别力，判决以 ROI 目检为准。P1 未见新增物体、假字、几何扭曲；0028 路面 "UNL" 字形 LQ 已存在，非 P1 新增。0043 P1 车轮为**有界重建**（prompt 限定 "consistent with the surviving shape"），无 GT 可核对真实性，按合理结构一致性报告。

## 4. E1：Qwen compose 适配

**假设：** 让 compose 为 Qwen 写出可检查的恢复终态、按区域给出合理重建许可，并明确保留内容，能改善当前 prompt 的恢复不足。

- P0：服务器现有 compose（`prompts/compose.txt` 模板 + 现行规则块，含 redo 时代抑制性措辞、无重建许可）。
- P1：面向 Qwen 的 compose（`prompts/compose_p1.txt`，两级保真：Tier-1 严格保护人脸/文字/几何/已清晰结构；Tier-2 对被 blur/underexposure 破坏的区域授予有界重建许可，终态可检查 + 明确保留内容 + 禁止挪用）。
- 固定诊断、工具证据、执行器、输入与配置；本阶段**未启用**文字转录与 redo。
- P0/P1 完整 prompt 已逐图存档；P0 未见字面"将不确定结构统一涂成平滑表面"，但其保真条款无例外许可，等效抑制（与 probe 实验 A→C 5.25× 的发现一致，见 `runs/probe_executor_capacity/REPORT.md`）。
- 5 张预定 dev 图 ×2臂×2配对seed = 20 次生成（上限 20，无复用）。
- 运动模糊（0043/0049）：P1 在 0043 恢复车轮/立面结构、轮廓连续、无结构位移；0049 招牌涂抹两臂相当。低光（0024/0028/0042）：P1 暗部更亮且高光/尾灯控制不劣于 P0。

**通过判断执行**：逐图偏好 = 2 明显胜 + 3 平/略胜 + 0 负（seed 两两一致）；严重错误 0；未用 sharpness 倍数做判决。

**结果：通过。失败与反例**：0049 P1 全图 luma 下降约 0.03–0.05（P0 更亮），为唯一可量化退步；同图 P0 光源光晕更膨胀，属权衡而非纯退步。**进入 E4：是**（条件：与 E2 转录、E3 ROI-verifier 组合验证后再进默认路径）。

## 5. E2：文字转录与执行器绘字

**未运行。** 预备依据（probe 阶段，非本轮）：0049 "highball" 在 5/5 条注入转录臂渲染正确，5/5 纯许可臂失败 → 文字需 T2 注入路线；候选图：0049（highball）、0028（路面 UNL / PARK）。

## 6. E3：固定候选池的 verifier 重放

**未运行。** 预备候选池：`runs/full25_redo4/`（23 张 redo 候选）+ 本轮 20 张 E1 候选。注意 redo 全量运行已观察到"verifier 选了更暗候选"案例（night_0024），E3 需 ROI 数值 + 禁用全局 `luma_lift<=0` 硬拒。

## 7. E4：25张冻结方案端到端 A/B

**未运行。** 计划：S0 = 现行管线（含已修复 bug）；S1 = S0 + P1 compose（+ 视 E2/E3 结果加入转录与 verifier 改造）；redo 预算两臂一致；dev 5 图与其余 20 图分开汇报。

## 8. 图像证据和异常台账

每图已存：LQ（`lq.png`）、4 张原始无损候选（`p0_s0/p0_s42/p1_s0/p1_s42.png`）、全图对照（`roi_compare.jpg`，同位置同尺度 5 联：LQ/P0s0/P1s0/P0s42/P1s42）、盲评 grid（`grid_s0/s42.jpg`，X/Y 盲标）+ `blind_key.json`、实发 prompt 全文、逐图指标（`index.json`）、机读明细（`runs.csv`，20 行）。

| 异常ID | 问题 | 影响范围 | 处理/是否重跑 | 对结论影响 |
|---|---|---|---|---|
| ANOM-1 | RGBA alpha 通道污染 luma/sharp 指标（probe 阶段发现） | 所有含 alpha 输出的历史指标 | 已修复（execute.py RGB 转换 + probe 脚本）；本轮 20 张全部按 RGB 口径计算 | 本轮指标可信；redo 全量运行的旧指标仅定性参考 |
| ANOM-2 | 0049 P1 全图 luma 低于 P0（-0.03~-0.05） | 单图 | 记录为反例，未重跑（属方法行为差异） | E4 需 E3 的 ROI 级判断避免全局亮度硬规则误杀 |
| ANOM-3 | 指标口径限制：focus ROI 未在输入 LQ 上冻结，sharp 为全图口径 | 本轮全部配对 | 判决改用 ROI 目检；E3 起冻结 ROI | 自动指标仅作辅助，已在 §3 声明 |

无超时、无解析错误、无排除 seed、无配置偏离。耗时：0043=738s、0049=1340s、0042=1374s、0024=803s、0028=729s（每图含 2 次 compose + 4 次生成，共约 82 min GPU0）。

## 9. 最终结论、证据强度和决策

| 结论 | 支持的原始证据 ID | 限制或替代解释 | 判断 | 下一步最小动作 |
|---|---|---|---|---|
| P1 compose 解除"恢复不足"抑制，运动模糊区出现有界结构重建 | roi_compare/grid（0043 两 seed 车轮）；prompt_p1.txt 终态句；probe A→C/D 因果链 | 无 GT，重建真实性不可证；仅 5 图 dev | **支持**（执行者目检，待独立盲评复核） | 独立盲评（材料已备）；E4 验证 25 图 |
| P1 提升暗部亮度 | index.json luma 4/5 图、两 seed 一致 | 0049 反向；luma 非质量本身 | 部分支持 | E3 冻结 ROI 后量化暗部/高光分区指标 |
| P1 不引入新的严重内容错误 | 20/20 候选目检 + grep prompt 无术语泄漏 | 5 图样本小；文字场景未受激励（E1 无转录） | 部分支持 | E2 文字臂重点查假字 |
| 全图 sharp 不可作判决指标 | §3 sharp 与目检背离（0049/0028） | — | 支持（反例确证） | E3 起 ROI 口径 |

- **批准进入默认路径的组件**：无（需 E4 通过后批准）。
- **条件采用的组件及适用样本**：P1 compose——进入 E4 组件池；适用 blur/underexpose 混合退化（0043/0042/0024/0028 类）。
- **拒绝或暂缓的组件**：暂缓"全局 luma/sharp 作通过/选择标准"。
- **需要人工审核或回退的失败类型**：0049 类"亮度-光晕权衡"单图退步；文字区域在 E2 前的任何"清晰假字"候选。
- **尚不能得出的外推结论**：① 文字场景收益（需 E2 转录）；② 全 25 图端到端收益（需 E4）；③ P1 对 redo 轮次的交互（本轮未启用 redo）。
- **下一轮最小可信实验**：E2（0049+0028，T0/T1/T2，同一 P1 基底）→ E3（固定候选池 verifier 重放）→ E4（25 图 S0/S1）。

## 10. 提交附件与字段契约

- 主文档：本报告；证据目录：`runs/exp1_compose_ab/`（raw PNG×20、prompt×10、grid×10、roi_compare×5、index.json、runs.csv、blind_key.json）。
- 机读明细：`runs/exp1_compose_ab/runs.csv`（20 行；含 experiment_id/sample_id/split/stage/arm/seed/round_idx/status/luma/focus_sharp_global/raw_output_path/prompt_path/metric_version；redo/verifier/transcript 相关字段本轮不适用，留待 E2–E4）。
- 配置与版本：§2 文件 md5 快照；VLM/executor 参数见 §2 与驱动脚本 `tools/exp1_compose_ab.py`。
- 日志：`logs/exp1_compose_ab.log`（逐阶段时间戳 + 逐图耗时）。

## 11. 交付前检查

- [x] 记录真实服务器实现版本（无 git，以 md5 快照代替并显式声明）
- [x] 区分已执行（E1）/ 未执行（E2/E3/E4）/ 执行者目检（非盲）/ 待独立盲评
- [x] 每个结论有输出、指标、prompt 与记录 ID（§3/§8 路径）
- [x] 对照变化项明确（仅 compose 策略；seed 配对；非"换 seed 冒充 prompt 效应"）
- [x] RGB/alpha 口径一致（ANOM-1 已修复并声明）；luma/sharp 定义写明；ROI 未冻结的限制已声明
- [x] 文字相关统计不适用（E1 未注入转录，无 oracle 声明）
- [x] 候选→交付可追溯（本轮无 verifier/后处理，交付=生成）
- [x] 失败/排除/退步全部记录（0 失败；0049 退步已记）；样本数（5图）与生成数（20）不混淆
- [x] 提供实际图像（roi_compare/grid 路径；本报告嵌入结论基于全尺寸 PNG 目检）

