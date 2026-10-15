# HarnessRefEnhance v2 — 工程修改规格（生成式专用）

**基线**：feat/reference-enhancement-v1 @ 1490c574；**状态**：design_only / code_not_modified；**负责人目标**：使 Modular Neural ISP 的 A 在内容不变前提下，向同场景数秒后 iPhone 17 的 B 的亮度、颜色、影调靠近。

## 0. 从可观察事实出发

- A：唯一内容、构图、几何、文字、人物身份来源。
- B：仅作为最终显示外观参考，不是 GT，不从 B 搬运天空纹理、文字、人物或物体。
- A/B 是同场景、数秒内、照明/内容基本稳定的真实采集对。此项是设计的强先验，不应把“昼夜变化、换景”等泛化干扰当主要算法问题。
- 不同相机可能仍有视角、构图、曝光、HDR、动态范围、光谱响应和输出色彩空间差异；记录即可，不应无证据否定亮度/色彩可迁移性。
- 不可迁移性只在信息论或条件下表现出来：例如 A 已发生不可逆裁剪或颜色/纹理丢失、B/A 对应区域确实不相同、两张图色彩变换记录无法解释。对普通可靠区域，应允许充分改变 A 的亮度和色彩。
- Executor 可能因自然语言不精确、全图重绘、细节幻觉与局部编辑泄漏失败；“描述更加具体”不是其精确控制能力的证明。

## 1. 目标函数与验收边界

主要业务目标是：在可信可比区域，C 比 A 更接近 B 的亮度/色度/Tone，同时不引入内容错误。评价双轨：
1. 属性级变化（诊断与归因）：同材质 / 同语义 / 近似同照明的 A/B ROI 对，比较 d(C,B) 与 d(A,B)；
2. 人工独立审核（最终）：参考方向 improved + 内容完整 pass + 无严重伪影/内容幻觉。

仅 d 降低不是成功。反过来，单图 NR-IQA 升高也不是成功。数据缺失、ROI 不可比或输出内容发生形变时，属性结果应为 null/不可解释，不能按 0 缺失补值。

## 2. 推荐系统架构

~~~
A prediction ──┐
                ├── Preflight：来源/颜色/可比性/冻结 ──> Diagnoser ──┐
B iPhone ref ───┘                                                 │
                                                  ROI/STATS/T4(A) ─┤
                                                                   v
                         G0 直接参考 Prompt ───────────────> Editor(A,B)
                         G1 Composer 短文本 ────────────────> Editor(A,B)
                         G2 同一个 G1 Prompt + 合格 Mask ──> Editor(A,B,mask*)
                                     * 仅实测支持的 adapter/transport
                                                                   │
                                                                   v
                                   raw C + 源像素证明/geometry/content
                                                                   │
                             ROI Evaluator(A,B,C) + Independent Review
                                                                   │
                                    保留候选/终止；多轮实验另立合同
~~~

### 2.1 分割信息分为三个通道

| 通道 | 输入到哪里 | 是否需要编辑器理解彩色分割可视化 | 默认策略 |
|---|---|---|---|
| ANALYSIS_MASK | Diagnoser / Composer / 人工预览 | 否 | 可以消费 T4 A 原始语义标签/置信/geometry，并转为简短可定位文字 |
| EVAL_MASK | ROI Evaluator / 内容保护检查 | 否 | 原生二值/语义数组，绑定 A 像素与区域 id；不接入生成 |
| EDIT_MASK | G2 编辑器特定 mask adapter | 依 adapter 类型；禁止把彩色 overlay 偷换为原生 Mask | default OFF；先能力测试 |

彩色语义 overlay 是诊断/UI 辅助视觉，不作为 G0/G1 或 G2 的默认为新增图片。必须区分以下可观测 EDIT_MASK 模式：

- native_mask_parameter：编辑接口含独立 mask 参数（例如特定图片编辑 API）；定义透明区/可编辑区、作用于第几张图、输出尺寸与是否仅软约束。不能从 API 文档推断桌面模式具备该参数。
- separate_mask_image：模型把原图、B、单独 mask 图片作为有语义的多图输入，例如 Qwen 展示的做法。这是**基于图片提示的软条件**，不宣称后台做硬二值裁剪，不能简写成 native mask。
- painted_annotation：在原图上画圈/涂色；可能遮盖输入信息或污染输出，只作为独立探索条件，v2 核心 G2 不采用。
- unsupported/untested：G2 skipped_capability，不用 G1 假冒。

每个 mask adapter 必须提供独立的真实能力证明（mask 修改是否定位、角色 A/B/M 是否保持、输出与非目标区漂移、方向含义），并保存 input_order、preprocess 及真实交接。

### 2.2 Mask 生成和几何约束

- 以冻结 canonical A 的像素坐标建立 EDIT_MASK。可来自已验证的 T4 segmentation 或人工 ROI；如边界质量不足优先保守小区域/腐蚀，不自动扩大到不确定部分。
- EVAL_MASK 与 EDIT_MASK 互不等价。EVAL_MASK 只用于诊断/度量，EDIT_MASK 是允许尝试修改的目标集合；同一原生标签缓存可派生，但须保存派生规则和独立 SHA。
- 统一使用 explicit allow_edit 逻辑：内部数组 uint8 {0=非目标,1=目标}；输出给某模型时由 adapter 显式编码其 alpha/黑白语义；严禁依靠 mask 颜色自行推断 edit 方向。
- 记录 alpha / threshold / dilation / erosion / feather 参数、坐标系统、几何、类别、质量、mask_sha256、source T4 model/version/preprocess/input A pixel SHA、target_roi_ids。
- A/B 两图尺寸可以不同，绝不将 A 的坐标直接作为 B 坐标。对 B 只能使用独立预标注 ROI / segmentation。
- 避免 Edit Mask 覆盖小字、关键身份特征；当目标刚好为脸，内容身份保护优先于漂白/局部增强目标。
- G2 仅用于局部编辑问题；整图 WB/整体 Tone 直接沿用 G0/G1，不强制套全图 mask。
- 输出 C 必须保留 raw bytes，strict geometry 与尺寸校验延续 v1。尺寸一致不表示内容不变；存在内容变化还须独立检查。

## 3. Prompt contract：少量目标，不重复禁止变化

G0：冻结固定直连 Prompt。Editor 实际输入仅 A+B+prompt，不接诊断、T4、ROI 或评估数值。

G1：Diagnoser 看 A+B+可信可比的 ROI 信息与证据；Composer 只选 1–3 个方向明确的目标，输出短英文 Prompt。描述包含（a）目标区域/全局，（b）向 B 改变的亮度/颜色/层次方向，（c）一句必要的 A 内容保真约束。**不要**“保持 A 原有曝光/颜色/对比”，因为会抵消增强需求；也不要让提示变成包含所有小物体的恢复清单。

G2：直接**复用被冻结的 G1 完整编辑文本**，唯一变量是受支持的独立 Edit Mask 条件。若 mask 模式需要固定包装句说明编辑范围，必须对 G1 同时提供中性、等效的限定句，记录对照是否严格只有 mask 差异。不允许因看到了 mask 编辑失败而修改提示后与旧 G1 做因果比较。

分析/Compose 工具证据只出现在文本生成阶段；Verifier 与最终盲评不能窥见 G1/G2 方法名、Composer 提示或未经冻结的评分。Mask 评价可供独立定量审计与人工标注参考，但最终盲评的统一内容必须对三个臂一致。

### 3.1 建议的新结构化 target（不是任意执行代码）

~~~
{
  "version": "reference_targets_v2",
  "source_assets": {"A_pixel_sha256": "<actual>", "B_pixel_sha256": "<actual>"},
  "targets": [
    {"target_id": "t01", "scope": "local",
     "dimension": "brightness",
     "roi_pair_id": "wall_01",
     "direction": "lift_midtones",
     "confidence_kind": "observational",
     "comparability": "comparable",
     "observed_support": "A wall is darker than B in the same lighting"}
  ],
  "preservation_anchor": "A",
  "unsupported_targets": []
}
~~~

此 target 是 Composer 的可验证诊断中间件，不是要求生成模型接受数值 θ。若 Schema 变更必须升级 version；不应在 v1 strict Schema 中塞 additionalProperties。

## 4. ROI A/B/C 闭环定义

### 4.1 入组前冻结（避免看结果后挑 ROI）
每个 ROI 对有 pair_id、A_polygon_or_mask、B_polygon_or_mask（各自坐标）、同语义材质标签、comparability、reasons、importance、target_dimensions、area_pixels、source/annotation SHA、visible_saturation/occlusion 标记。至少有一个可比区域，否则只允许生成/人工预览，不宣称参考属性可证。

手工 ROI 是首轮可信基准；分割可协助但不自动声称 A/B 语义严格对应。对动态物体、新遮挡及真实饱和区域标 absent/unreliable；同场景数秒的强先验不改变这个处理。

### 4.2 评价关系
- A、C：先通过原有 geometry 与内容审查；C 借用与 A 同坐标的 ROI，严格 crop/warp 禁止。只有等比例缩放且合同允许才使用明确映射。
- B：使用冻结的独立 B ROI；不以 B/C 像素 PSNR/SSIM/LPIPS 作为参考质量。
- 每个 ROI / dimension 记录 d_before=d(A_roi,B_roi)、d_after=d(C_roi,B_roi)、delta=d_before-d_after（正值=距离缩小）。
- brightness：比较 Lab L* 的 mean/median 或稳健分位数；避免把 Gamma sRGB Y' 称作传感器亮度。
- chromaticity：同语义区域平均 a*, b* 的距离/偏向；平均 Lab 差不是空间像素配准 ΔE2000，不能虚称逐像素 ΔE00。
- tone：p10/p50/p90 的 L* 或显示亮度统计、明暗层次宽度、clip 比例；只评价实际可比范围。
- saturation：同语义区域饱和度均值/分位数；独立报告方向与过饱和风险。
- local spill：G2 的编辑区域外统计变化/边界不连续，可同时在 G1 上用**完全相同的冻结目标 mask**计算，不因某臂没消费 mask 就缺指标。非目标变化要区分必要的全局统一颜色调整与异常内容改变；只在局部任务评价 spill。
- content：文字/人物/小结构/几何/纹理幻觉及新增物体的失败标注，是硬门禁。

近零 d_before 不能用相对改善比例放大噪声；保留绝对差、样本量与距离异常，必要时把其目标设为保持/不适用。多个 ROI 不可未经预设权重任意取平均，更不能以选中最优 ROI 报胜。

### 4.3 闭环的第一步是观察，不是自动重试

v2 第一阶段：Evaluator 离线生成属性差分与失败原因报告，**不**自动用于当轮选择/改 Prompt。独立盲评后检查是否能准确识别亮度欠调、色彩越界、局部污染、重绘。只有真实数据显示评价可信，才将失败原因用于下一版本 Refine（最多一次新生成、每轮从 A+B 起），同预算对照 Direct 两次生成。

## 5. 执行器与适配器合同

已有 v1 Editor bundle 必须恰好包含 A.png、B.png、edit_prompt.txt；这是 v1 的真实协议。v2 不能“悄悄塞入 mask.png”：
- 新建 opt-in schema_version = ref_enhance_v2；旧 v1 config/stages 原样保留；
- G0/G1 使用 v1 two-image interface；
- G2 增加 mode=separate_mask_image 或 native_mask_parameter、mask binding、adapter id/version、observed capabilities、原始 transport 请求/返回、输入顺序与真实已送达证据；
- 对不同 transport，独立报告其是否支持多图+Mask、Mask 是否作用在 A、对端是否接受 B、哪些模型参数可设置；
- 不允许从 ChatGPT 桌面 GUI 无法触达的 API 参数推断能使用。若桌面不支持，G2 仅能在经过实际测试且有权限的本地/其他 Executor 中做同 Executor 对照，并与桌面 G0/G1 结果分开报告；
- 不绕开现有无外部 API 的 V1 设计。新 transport/API 若需要采用，另立明确授权/配置变更，不静默开启；
- 新增 G2 仍必须遵循 v1 的 submitted/unknown/count、first complete、raw master、fallback、SHA、不可事后篡改/人工挑图等规则。

## 6. 保持和需要修改的代码边界

- **保持**：harness/ 原恢复管线、main Qwen 文档与代码、v1 冻结的 profiles/实验、原执行器的有条件颜色后处理（不能复用到 hre）、v1 hash/交易/预算/盲评机制。
- **修改（需另 PR 代码实现）**：
  - engine/src/hre/desktop.py：实现 mask-capable export / import，能力标志及 G2 硬闸门；每个 provider 的输入编码独立；
  - engine/src/hre/capabilities.py：新增 mask delivery + target-region proof，按 transport + 模型版本存 probe；
  - engine/src/hre/prompts.py、engine/src/hre/resources/prompts/：G1 精简、目标 schema；G2 重用 G1 prompt；严禁混淆 Execute 图片绑定；
  - engine/src/hre/evidence.py：T4 A 原生 mask/缓存的 v2 绑定、目标 mask 派生审计；不消费未经诊断计划的结果；
  - engine/src/hre/roi.py、stats.py：A/B/C mask/polygon ROI 的逐属性评价和局部泄漏；保留旧函数行为；
  - 新增 engine/src/hre/reference_evaluator.py：冻结评价配置，输出 per_roi/per_attribute、unknown、误差方向；
  - engine/src/hre/experiments.py / reporting.py / selection.py：独立 v2 experiment profiles 与分臂、ITT、盲评、拒绝无 mask proof 的 G2；
  - engine/src/hre/ui.py：A/B/C/Mask 对比、局部目标/泄漏显示，显式能力未验证状态。
- 建议先以新文件/新 schema 扩展，不更改 v1 运行默认值；每个新实验记录精确代码 commit、模型版本、prompt/ROI/Mask SHA。

## 7. 常见失败与应对

| 失败 | 不正确处理 | 正确处理 |
|---|---|---|
| 非目标物体/天空被重绘 | 只看颜色更像 B 就通过 | 标 content failure / spill；保留 raw |
| 彩色标签渗入生成图 | 增加更多颜色标注 | 禁止 overlay 作为正式 mask，区分 mask 通道及生成接口 |
| 原生/独立 mask 未精准遵循 | 声称 mask 硬锁像素 | 记录 observed mask compliance、边界误差、unsupported |
| 参考差异来自裁剪/缺失信号 | 要求模型填补 B 细节 | 标不可忠实恢复范围；不作忠实迁移成功 |
| 局部变化微弱 | 只以无幻觉判通过 | 不接受 unchanged；属性差与人工判断分列 |
| 全局色彩调整引起合法非目标变化 | 机械拒绝所有背景色差 | 区分 global 与 local task；local 才按空间 leakage 判 |
| ROI 在 C 出来后才选 | 报告最好看的 ROI | 所有有效 ROI 入组前冻结，未冻结的只能探索报告 |
| 编辑器只能两图输入 | 用三张普通图冒充 native mask | G2 skipped_capability；G0/G1 仍可继续 |

## 8. 交付时的可证伪主张

- 「G1 有用」仅当同模型/单次预算对照 G0，在独立评价中改善且内容代价可接受；并说明额外 VLM/工具费用。
- 「G2 有用」仅当同一 mask-capable 模型/参数下，G2 对照 G1 的局部 spill/幻觉下降或属性改善，且不存在明显增加的其他失败。
- 「ROI Evaluator 有用」仅当可解释的指标方向与冻结盲评足够一致，且错误案例被列出，不凭单个 metric 宣称通用。
- 都失败时接受结论：Harness 复杂度无法超越当前 Executor 的 reference-following 能力；不继续堆叠 Agent/Mask/工具。
