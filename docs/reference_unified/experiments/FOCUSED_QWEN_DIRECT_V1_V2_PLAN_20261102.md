# Focused Qwen 三臂实验 v1.1：先校准差异辨别，再比较编辑收益

**协议：** `qwen-reference-3arm-pilot-v1.1`  
**修订日期：** 2026-11-02  
**状态：** `PLAN_REVISED / CALIBRATION_NOT_RUN / FORMAL_TEST_NOT_FROZEN`  
**范围：** 固定 Qwen 的 Direct A+B、Reference Retouch v1、Unified v2；本次修改校准与共同评价计划，不修改生产生成代码，不增加实验臂。  
**Goal：** 使评价链能够分辨“都自然，但肤色色相/彩度不同”，不再把自然度合格当作参考匹配。  
**Architecture：** 保留现有执行合同、全图优先观察和私有验收规则；增加离线差异感知校准层，将观察事实、参考可比性、编辑目标、结果验收分开。  
**Tech Stack：** 现有 hre/Python、实际部署的 VLM、经审计的 sRGB/CIELAB 测量、独立人审；无新增训练。  
**Spec/历史：** [原 v1 固定版本](https://github.com/baolinv0/HarnessIR/blob/cebafcd0e1f8d842115863ff4676f72eb751e53f/docs/reference_unified/experiments/FOCUSED_QWEN_DIRECT_V1_V2_PLAN_20261102.md)。本文件是其修订版，不追溯改写已冻结任务或旧评分。

> **执行决定：** 保留 21 组池、4 dev / 16 test / 1 备用及 132 个生成槽上限。暂不将 17 个 S1 草案视为“脸部已匹配 B”。先完成 E3-CAL，再复核 E3 差异和目标；未达到自动辨别资格时使用独立人审为主，而不是强迫 VLM 给出差异或继续放宽阈值。

## 0. 本次确认了什么，尚未确认什么

仓库源码核对基线为 `cebafcd0e1f8d842115863ff4676f72eb751e53f`。本次只修订文档，未运行 VLM、GPU、生图或当前服务器测试。

| 证据 | 当前结论 |
|---|---|
| 用户提供的 E3 摘要 | 21 组草案：S1=17、S2=4（G03/G07/G16/G21）；S3/S4 未分配样本。用户观察到肤色比较主要回答“都自然、可接受”，辨别出亮度而未充分辨别肤色色差 |
| 用户报告 E1/E2/P0 与三臂 ready | 视为服务器运行报告；本次未取得原始日志，不将 967/967 测试通过表述为独立复跑结果 |
| 本地 `manifest/label_draft.json`、`label_review.html`、实际请求与响应 | 本次未读到其完整内容；不能断言具体 Prompt、图像降采样或 VLM 能力是唯一根因 |
| 远端源码 | 可确认结构化合同、数值测量、全图评价和私有验收规则；不能假设这些模块已全部进入服务器 E3 的真实调用链 |

**必须分清两个“校准”：**

- **差异感知校准（本次新增计划）**：验证给定 VLM/视图/问题表达能否检测、定位和描述色彩差异，并允许不知道。
- **验收容差校准（已有机制）**：在可信观察之后，规定任务上多大的残差可接受。调整容差不能让观察器看见此前没看见的差异。

不校准到指定相机的“肤色审美”；不以泛化的标准肤色、统一变粉、统一提亮为目标。B 是当前可比外观的参考，不是像素对齐 GT。

## 1. 当前方案梳理：已有结构与真实缺口

以下路径均相对于仓库根目录；源码证据链接在 §12。

| 组件 | 已核对的实现 | 本轮相关缺口/边界 |
|---|---|---|
| `v3/reference_retouch_v2.py` | 八维诊断、A/B 各自观察、candidate_deltas、可比性、冻结目标、证据复核 | `skin_rendering` 仍是一个属性；观察和方向主要为文本，没有强制逐项区分脸部明度、黄蓝、红绿和彩度。schema 合法不证明辨别正确 |
| 同文件 `stage_instruction()` | 全图优先；诊断声明仅有 `basic_statistics`；整脸/整物体为观察/编辑约束 | 不能把单独安装的 reference_style Lab 工具当作已注入 E3 的证据。`never intraface patches` 的宽泛限制也不能直接等同于“禁止分析受光区/阴影区” |
| `reference_style/s2_measure.py` | 审计数组上的 linear Y、L*、a*、b*、chroma；分位数、均值、B−A 与区域关系差；可用性检查 | 已有数值基础，应复用而不是重新发明“肤色分数”。真实语义支持、色彩编码和 A/B 可比性不足时，仍不可认证为匹配证据 |
| `reference_style/s4_review.py` | image-first/evidence 两阶段 A/B/C 观察；事实与验收政策分离 | 还需实测观察者能否分辨细小颜色变化；不能只检查是否返回 achieved/uncertain |
| `reference_core/holistic.py` | 全图六轴；方向、幅度、置信度、来源图绑定；A 内容保护 | 全图 color 轴正确不等于 face 色彩判断正确；不能用整体结论替代细粒度差异，也不能反过来用局部数值覆盖全图失败 |
| `reference_style/s4_verify.py` | 导入经批准的 policy/rule、视觉锚与 numeric_tolerances；绑定真实目标；数值/视觉冲突保留；缺校准不自动成功 | 这是规则安装与执行，不是从数据自动学习阈值，也不是视觉辨别力测试。`high confidence` 是声明，非经过验证的概率校准 |
| 原实验计划 S1 | “肤色基本合理”并暗含“脸应保持/小幅改” | 自然度和参考一致性混在一起；容易在完成色彩比较前就把脸标成 preserve |

**旧链路可概括为：** A/B → 八维观察/证据 → 目标与编辑 → A/B/C 全图/逐目标观察 → 验收规则。

**新增前置层：** 用已知变化和独立人工观察，先验证“负责产生观察的配置”；不改写旧三臂的生成行为。

## 2. 修改边界：先测清楚，不把修评价变成改方法

本轮主实验的生成侧保持原样：Direct、v1、v2 使用同一真实 Qwen 与 compiler、共同 brief、A/B、几何和每 run 一次生成上限。

新校准器服务两处：

1. **E3 离线标注**：生成前形成共同的 A/B 差异事实、可比性和独立验收目标。
2. **三臂共同离线评价**：判断 C 相对 B 的残差，以及 C 相对 A 是否改善或过改。

**不把修订后的比较 Prompt、人工答案或私有容差只塞给 V2 的在线诊断/Compose。** 否则测到的是新方法，而非原 Direct/v1/v2 的比较。运行时语义审计可以核查该方法自己的目标是否被传递，但不能用离线标准答案替该方法补写肤色目标。

若后续确需把校准后的感知器接入在线 V2，使用新方法身份和新试验版本；本次不实现、不额外安排该实验臂。

本计划中的 mask 仅用于测量与确定性校准样本构造，不改变三臂的 `full_frame` 执行模式。整体风格、影调、自然度、A 内容与原生细节检查全部保留。

## 3. 修订后的校准/评价流程

### C0：先查图像实际上怎样进入模型

工程师先归档实际 E3 入口与调用链，不能只看 HTML 缩略图。每个请求绑定：A/B 原件、工作副本、上传文件 SHA、角色顺序、EXIF 方向、色彩转换、编码/位深、resize/pad、模型 processor 设置、最终张量或图像 token/patch 信息（可取得时）、全图与脸部在模型输入中的实际像素规模。

网页显示尺寸不等于模型输入尺寸；把图片 CSS 放大也不增加输入信息。禁止在比较视图中自动白平衡、自动增强、分别归一化亮度或修图式肤色对齐。

冻结实际 VLM 权重/revision、endpoint 返回身份、Prompt/schema、采样参数及视图策略。编辑器 Qwen 与评价 VLM 分开登记，不能用模型别名替代版本证明。

### C1：先观察差异，再判断自然度与是否编辑

比较方向固定为 **B 相对于 A**。模型先看原色全图并保存观察，再看相同面部显示尺度的完整面部视图（保留比例和周边上下文，不单独拉伸），最后才接触数值。

全图与面部分别登记：

| 字段 | 最低要求 |
|---|---|
| 明度/影调 | 更亮/更暗/未见可辨差异/无法判断；面部受光与阴影关系单列 |
| 黄—蓝倾向 | B 的黄感更多/更少/未见可辨差异/无法判断；不能用更亮代答 |
| 红—绿倾向 | B 的红感更多/更少/未见可辨差异/无法判断；“偏粉”等词保留为视觉描述，不直接等同于单个 a* 值 |
| 彩度/颜色浓度 | 更强/更克制/未见可辨差异/无法判断；数值 C* 不冒称完整的感知饱和度 |
| 空间分布 | 整脸/受光侧/阴影侧/额头/脸颊等观察位置；允许分析子区域，但不是独立编辑授权 |
| 脸—背景关系 | 同向不同幅度、不同方向、仅一方有差异、均未见可辨差异、无法判断 |
| 自然度 | A、B 各自单独记录；“都自然”不替代以上字段 |

观察状态必须区分 `different`、`no_visible_difference`、`uncertain`、`not_observable`。后两者不能映射为 `preserve`、`already_satisfied` 或零差值。`no_visible_difference` 也只是当前条件下的观察，不是统计等价证明。

随后另做 **可比性判断**（comparable/conditional/incomparable/unknown）与 **目标决策**（match/preserve/defer）。即使无法确定差异来自光照还是处理，也可以记录可见差异；只是不能自动授权编辑。

### C2：数值证据独立计算，不能由 VLM 猜

优先复用既有色彩审计与 `s2_measure`。工作域统一后，固定同一参考白的 Lab；当前 evidence 路径使用 Lab_D65，不能直接混入 ICC PCS 的 Lab_D50 数值。[CIE/ICC 依据见 §12]

分别记录 A/B/C 对应皮肤/材质支持域上的分布：L*、a*、b*、C* 的中位数与分位数。A/B/C 各有独立支持域及质量记录；人脸框不等于皮肤 mask，相同尺寸不等于配准。

- 整脸用于整体外观判断；皮肤支持剔除非皮肤内容。受光/阴影或额头/脸颊的诊断子区只用于解释，必须有真实支持，不许生成伪 mask。
- 明确区分 `observation_support` 与 `edit_scope=whole_face`。在独立分析侧增加子区，不静默修改历史 v2 的 schema、Prompt 或旧 ROI 语义。
- 不对未配准 A/B 算逐像素 PSNR/SSIM 或逐像素颜色误差。跨图区域统计仅在材质与照明可比范围内解释。
- 方向使用 Δx_AB = stat(x_B) − stat(x_A)，x 为 L*/a*/b*/C*。颜色匹配不由总 ΔE 一票决定，更不能用亮度收益抵消黄偏加剧。
- 不凭全图色彩均值断言整图白平衡；全图空间、材质比例变化必须保留在解释中。
- 色彩未知、支持不足或明显不可比时，数值状态为 unavailable/visual_only，值用 null，不用 0。视觉原色观察可继续，但不能制造数值通过。
- 现有测量保留有效支持像素与端点；额外排除/重采样规则必须事前版本化，不能为了让结果更接近 B 而改变 ROI。

视觉首轮不见数值。第二轮 evidence review 可以看到合格数值，保存独立的观察版本；不能以第二轮复述数字证明 VLM 首轮“看出了”颜色。

### C3：将观察结果与目标、容差分开

建议新增离线 sidecar `reference_difference_observation_v1`，而不是给历史 `hre_reference_diagnosis_v2` 偷加必填字段。

每条 `region × attribute` 记录至少包含：`observation_id`、输入/视图 hash、region/support ID、属性、比较方向、观察状态、方向、视觉幅度、置信度、可见依据、comparable 状态与原因；数值有独立计算记录。另存 `naturalness_A/B`、reviewer 与暴露信息。

同一张脸允许“明度匹配、黄感不同、彩度无法判断”，不得只给整个 skin_rendering 一个 preserve。缺少颜色判断必须显式待复核。

分开保存三种容差：

| 类型 | 用途 | 禁止替代 |
|---|---|---|
| 数值/编码误差界限 | 验证变换、量化和零扰动链的数值误差 | 不是人眼 JND |
| 差异辨别能力记录 | 给定 VLM/视图在已验证扰动上的正确/漏检/误报范围 | 不是任务允许残差 |
| 任务验收容差 | 人工确认的参考外观目标允许何种残差 | 不能为迁就 VLM 漏检而放宽 |

不预设一个通用“ΔE<2 即匹配”或“Δb<某值就看不见”。任务容差从 dev 的真实观察依据冻结；不足时保留人工判定/unknown。批准、hash 绑定或 high-confidence 字段不等于阈值已实证有效。

### C4：验证器必须保留带方向的残差

对于每个候选 C，分开回答：C 与 B 还差什么、C 相对 A 是否朝 B 前进、有没有越过 B、内容与自然度是否受损。

在数字可比时，保存 `e_A = stat(A) − stat(B)`、`e_C = stat(C) − stat(B)` 和 `|e_A| − |e_C|`。跨越 B 只作为过冲线索，不自动拒绝；是否仍可接受取决于真实视觉与冻结目标。更暖不等于更接近，变亮也不能替代色相改进。

匿名候选比较允许偏好、并列、无法判定。`tie` 与 `uncertain` 分开；“两者都自然”不能直接推出 tie。视觉先行，区域/数字用于解释，内容保护和原生交付单列，不给隐式加权总分。

## 4. E3-CAL：在原四组 dev 上完成最小辨别力校准

### 4.1 数据隔离

保留原 D_dev=G01/G03/G08/G09。建议 G01/G03 用于比较配置，G08/G09 用于配置锁定后的确认；若后两者已参与该配置调参，必须记录 exposure，称回归检查而非未见确认。不得挪用 D_test 调 Prompt、幅度或阈值；G20 仍保留备用身份。

所有数值扰动仅是**校准探针**，不是新真实场景，不计入主试验样本数。扰动参数提供数学方向；“人眼可辨/自然度/匹配好坏”的标签由实际独立观察建立，不能从参数大小自动推导。

### 4.2 默认扰动集：每个 dev 源图 19 对

以已审计 A_work 为基图，使用真实确认的皮肤与背景支持，构造以下确定性变体。所有数值是初始工程探针，不是已验证知觉阈值。

| 家族 | 变体 | 每源图对数 |
|---|---|---:|
| 零变化 | 同字节 X/X；变换编解码的误差另做软件测试 | 1 |
| 明度 | 皮肤 ΔL*=−4、+4，固定其 a*/b* | 2 |
| 红绿 | 皮肤 Δa*=−4、−2、+2、+4，固定 L*/b* | 4 |
| 黄蓝 | 皮肤 Δb*=−4、−2、+2、+4，固定 L*/a* | 4 |
| 彩度 | 皮肤 (a*,b*) 同比乘 0.8、0.9、1.1、1.2，固定 L* 与色相方向 | 4 |
| 区域选择性 | 仅背景 Δb*=+4；脸+4/背景−4；脸−4/背景+4 | 3 |
| 明度干扰 | 皮肤 ΔL*=+4 与 Δb*=−4 同时存在 | 1 |
| 合计 | 4 个 dev × 19；两图顺序互换不增加独立样本数 | 76 |

输出经过编码后重新测量实际 ΔL/Δa/Δb/ΔC；需要固定的坐标若被变换、量化或色域处理破坏，标 `FIXTURE_INVALID`，不能误算为模型错误。不得静默 clip 后仍宣称“只变 a*”。不可用变体保留在探针账本中；若重新生成，使用显式版本且在观察模型结果前冻结。边缘羽化、alpha 范围、色域处理、支持路径和全部参数都归档；测试集不用于挑选“模型刚好能看见”的幅度。

受控地固定 Lab 坐标用于拆分诊断，不等于宣称物理曝光、真实白平衡或所有知觉属性完全独立。

另保留 4 个真实 dev A/B 对。每个 dev 加两个 A/B/C 校准包（肤色、背景各一个）：固定参考变换强度 t=1，候选含 t=0、0.75、1.75；视为“无修改/接近/过量”的构造来源，不把系数自动当最终视觉标签。自然度、参考接近性、并列和过冲以实际独立人审为准。

### 4.3 有序排查，不一次同时换所有东西

| 配置 | 唯一增量 | 用途 |
|---|---|---|
| R0 | 保存当前真实 E3 Prompt、schema 和输入视图，不修饰结果 | 重现原问题 |
| R1 | 同样输入，改为逐属性有方向的差异问题，独立自然度字段 | 判断是否主要是任务/输出定义问题 |
| R2 | 在 R1 上增加经审计的完整面部同尺度视图，仍先看全图，不见数值 | 判断是否主要是观察条件问题 |
| R3（辅助） | 对已冻结的视觉观察追加合格数值证据与冲突复核 | 判断能否通过证据辅助补足；不算纯视觉能力 |

只在 G01/G03 比较 R0/R1/R2，选一个锁定配置，再运行 G08/G09。确认结果不得用于回头选另一个“最好配置”而仍声称确认成功。失败后转人工主评；再调参属于新版本与已暴露数据。

每源图每配置最多 44 次视觉请求：19 对×2 顺序 + 1 个真实 A/B×2 + 2 个 A/B/C 包×2 候选排列。调试两组最多 3×88=264 次，锁定后两组最多 88 次，合计视觉调用上限 **352**。若对选定配置的四组追加一次 evidence 模式，上限另加 **176**；总 VLM 请求上限 **528**，不是生图预算。每个请求限一次已计账执行，失败/未知不无限重试；实际少于上限如实记录。人工观察、CPU 变换及 token/GPU 时间另计。

原三臂 132 个图像生成槽不变；不调用图像编辑器生成校准标签。该小校准仅建立局部资格，不证明跨肤色、光照和相机的泛化。

## 5. 校准通过条件与失败退路

以下是**本轮建议的预登记工程门槛**，不是论文或行业统一标准。正式查看确认结果前冻结；只能报告真实分母，不能合并 a/b/彩度后用亮度高分掩盖肤色失败。

| 检查 | 通过要求 |
|---|---|
| 证据与软件有效性 | 输入/角色/视图绑定、合法色彩域、支持和变换身份均可核查；缺证不伪通过；错误 hash、缺轴或自然度替代差异的负例被拒绝 |
| 空变换 | 确认组真实 X/X 对不报有方向色差；全部保留。样本很少，0 次误报不表述为总体误报率为零 |
| 肤色色度方向 | 对独立人审确认可辨的 a*、b*、彩度各单列；每轴至少 8 个不同基础变体、覆盖至少 2 个源图，否则该轴资格为 INSUFFICIENT_CALIBRATION；正确检测且方向正确率≥85%，明确可辨样本上的 uncertain/no-difference 计漏检 |
| 顺序一致性 | 原顺序和互换顺序，在换算回同一 A/B 角色后≥90%一致；空变换仍无差异。全回答 uncertain 不得凭一致性通过 |
| 区域选择性 | 确认组 6 个基础区域探针至少 5 个正确指出改变区域与方向，并不误称未改区域同向变化；不足有效样本则不认证该能力 |
| 参考接近性 | 确认组 4 个 A/B/C 基础包中至少 3 个匹配独立人审的排序/并列；仅“都自然”不算正确排序。人审无法排序则保留未知，不能补造标签 |
| 真实 dev A/B | 对明确可辨的肤色色差不能再只回“都自然”；逐轴与独立人审核对。确认组无足够真实阳性色差时，明确缺少真实迁移证据，不能只凭合成通过宣称已解决 E3 |

所有指标同时报告 correct、wrong_direction、missed、uncertain、not_observable、invalid_fixture；顺序互换和重复不是新独立样本。VLM 自报置信度不当作实际正确率。

资格状态只允许：

- `VISUAL_COMPARATOR_QUALIFIED_FOR_PILOT`：满足对应条件，可辅助草拟；最终 E3 与主结果仍由独立人审确认。
- `EVIDENCE_ASSISTED_ONLY`：视觉未通过但数值辅助有效；报告“证据辅助”，不称视觉感知已修复。
- `HUMAN_PRIMARY`：视觉和证据辅助不足；保持人审为主，VLM 不决定 preserve/已匹配或三臂排名。
- `BLOCKED_INPUT`：连输入或色彩/区域依据都不可核查，先修输入，不进行正式质量判断。

不因校准失败就取消三臂研究；但没有可靠共同评价也不能启动正式结果比较。不得“问到通过”、通过降级样本或放宽容差制造资格。

## 6. E3 标注修订：名单保留，肤色结论重审

### 6.1 当前选择（用户报告；不是本次图像验收）

| 集合 | 明确名单 |
|---|---|
| D_dev | G01、G03、G08、G09 |
| D_test | G02、G04、G05、G06、G07、G10、G11、G12、G13、G14、G15、G16、G17、G18、G19、G21 |
| 备用 | G20 |
| M0 | G07、G16、G21、G10 |
| M1 | G11=warm、G12=cool、G13=warm、G14=cool |

草案测试分布 13×S1 + 3×S2，S2 为 G07/G16/G21。这个比例在肤色复核后可能变化；不为了维持比例硬留标签，不根据编辑结果调整名单。核对 dev/test 的同场景近重复与 source_group，不只看编号。

### 6.2 新标注顺序与切片规则

**先盲于原切片做逐轴差异 → 再判可比性 → 再定 match/preserve/defer → 最后生成切片/辅助标签。** 标注器首轮不接收旧的“S1=脸该保”提示。

S1 的原自然度预设停用：`skin_naturalness=acceptable` 绝不自动推出 `skin_match=achieved`。只有相对 B 的肤色目标确已满足，才给 preserve；否则记录 face_color_delta 及黄蓝/红绿/彩度方向。

保留 S1/S2 等主切片用于历史索引，增加非互斥标签：`face_color_delta`、`face_lightness_delta`、`background_color_delta`、`background_lightness_delta`、`face_background_relation`、`mixed_illumination`、`wide_dynamic_range`。脸与背景可能都需变但幅度不同，不强迫归入“脸保持”。

S3/S4 无主切片样本时写 sample shortage；主切片=0 不足以证明所有图都没有混合光等辅助特征。M0 不补齐自然 S4，M1 合成参考也不补齐真实缺样。

冻结比较配置后，对 21 组生成新观察，由实际独立评审确认。保留 `label_draft.json`，新增 `label_reviewed_v2.json`、逐项修改理由和旧新版本关系；`21/21 请求/结构成功` 不等于 `21/21 语义正确`。D_test 的独立目标可以在生成前标注，但不能反过来调整比较器、数值阈值或 prompts。

G20 只按生成前的数据有效性替补规则启用；不得因正式输出差而替换。已有冻结任务/输出不原地改目标，新版本单独记账。

### 6.3 M0/M1 边界

M0 必须使用 A_work 的同字节自参考，区分零调用返回 A 与生成后看起来相似。主分母不包括 M0。

M1 的 B2 变换参数、真实编码后图像、hash 与方向预期在生成前冻结。全图 warm/cool 会改变参考脸部时，C 脸部随之改变可能正是正确跟随；不能套用 B1 的“脸保持”规则。B1 端点引用已冻结主测试 r0，B2 使用相同请求 seed 和执行参数，仍记录是否实际支持 seed。M1 只检验系统随参考的响应，不单独证明区域解耦。

## 7. 三臂实验：保留的执行合同与预算

| Arm | 设置 | 解释 |
|---|---|---|
| D_direct_ab | `strategy=native`；删除 `workflow_contract` 和 `delivery_requirements` | 无 Harness 诊断规划；仍走冻结的 Qwen compiler/PE，不冒充绕过 PE 的裸提示 |
| V1_retouch_ab | `strategy=model_aware`；`workflow_contract=reference_retouch_v1` | 原 v1 合同与生成行为 |
| V2_unified_ab | `strategy=model_aware`；`workflow_contract=reference_retouch_v2` | 原 v2 合同与生成行为；新校准器在外部，不偷偷增强该臂 |

六臂 builder 的 `legacy_aware_ab` 不是本次 V1；使用各自合法 spec 和 case-root。服务器若已有专用三臂 orchestrator，先记录真实路径/commit 并核对，不重复创建或覆盖。本次未核验该本地实现。

固定同一实际 Qwen checkpoint、PE/compiler、stage VLM、editor settings、A/B 字节、公共 brief、几何、输出选择。远端已审查 profile 为 `qwen21`，不能用这个标签冒充其他 Qwen 权重；真实部署不同须先验证对应 adapter。当前计划不迁移模型版本。

A 为 S26 baseline 输出的已声明 SDR 工作图，B 为同场景可能未对齐的 iPhone RGB；保存 baseline 身份、原件→工作图转换和色彩依据。工作尺寸在真实预检后固定，不能假设通用 1024 能力；同一三臂使用同字节 A_work/B_work，保留比例，不拉伸。工作域成功不能宣称原始全分辨率细节已恢复。

每 run：`single`、`max_generations=1`、`n=1`、一个冻结 seed；默认 `max_stage_calls=12`、`max_compiler_calls=1`。同 group/repeat 三臂请求同 seed，实际不支持时记 unknown。无隐式重试、best-of-N、额外补样；unknown submission 先按真实回执核对，不免费重跑。

V1/V2 默认 `require_native_source_resolution=true, require_detail_pass=false`，对应事前 A_work；Direct 由共同离线规格检查。false 不等于细节通过；独立 native 1:1 检查仍必需。尺寸、真实细节、颜色参考接近性分别报告。padding/上采样不冒充原生信息。

**共同 brief（冻结原意，不按 arm 手工改写）：**

> Use image A as the immutable source of identity, objects, expression, text, composition and authentic detail. Use B only for supported photographic appearance (overall tone, brightness, color, skin rendering and subject/background relations). Match the observable and comparable reference appearance; preserve content and natural detail. Do not copy B objects or invent detail. If already matched, preserve A. Return one image.

完整 v1/v2 spec 以 [已有 v1 示例](../../../engine/examples/reference_retouch/reference.example.json) / [v2 示例](../../../engine/examples/reference_unified/task.example.json) 为结构依据，替换成上面的单次 policy、共同 brief、实际路径与冻结参数。两个示例文件的默认 feedback 配置不能原样用于本 pilot。

```bash
python -m hre models doctor --config /ABS/runtime.json --profile qwen21
python -m hre models create --case-root /ABS/runs/G01_R0_V2 \
  --spec /ABS/specs/G01_R0_V2.json --config /ABS/runtime.json
python -m hre models dry-run --case-root /ABS/runs/G01_R0_V2
python -m hre models run --case-root /ABS/runs/G01_R0_V2
python -m hre models show --case-root /ABS/runs/G01_R0_V2
python -m hre models report --run /ABS/runs/G01_R0_V2 --out /ABS/reports/G01_R0_V2
```

审计暂停使用实际绑定的 evidence-review/condition-audit 导入与 resume；不得伪填 pass。运行器内部判断与共同离线人审结果分开保存；内置 rejected 但实际生成的 C 仍应进入离线盲评。

| 阶段 | 最大生成槽 | 限定 |
|---|---:|---|
| E3-CAL | 0 | 仅确定性变换、VLM 与人审；分析调用另计 |
| D_dev | 4×3×1=12 | 若已运行，保留旧结果和实际消费，不静默重新获得额度 |
| D_test | 16×3×2=96 | 仍只有 16 个独立 source groups |
| M0 | 4×3×1=12 | 正确 no-op 可零生图 |
| M1 | 4×3×1=12 | 仅新增 B2 端点 |
| 总计 | **132** | 每个 planned row、失败、无图、暂停、未知均保留 |

运行顺序在 group 内平衡随机化，`ordering_seed=20261102`，记录真实时序/缓存/进程。工程测试和 doctor ready 只证明相应运行条件，不证明差异辨别或图像质量。

## 8. 正式评价与结论边界

主比较 **V2−V1**；V2−Direct、V1−Direct 为支持性。共同评价顺序为全图→整脸/背景→native 1:1→数值解释。评审不见 arm、生成 prompt、内部 verdict；两名独立评审和真实裁决记录不得伪造。

生成前冻结：各图 mandatory 参考目标、允许保持/不适用轴、可比性限制、A 保护项、原生交付和 baseline needs_edit/already_satisfied/uncertain。自然度及“好看”不是参考接近性的替代指标。

主结果 `effective_reference_success`：所需参考目标达成、无显著非目标恶化、脸/背景关系正确、A 关键内容保护和共同交付满足；证据不全为 unknown。另记已知执行失败/无图，不能给无图虚构画质零分。

报告 confirmed/all_planned、confirmed/evaluable、unknown 与执行失败数。所有计划行参与任务完成分母；有效编辑分母使用**输出前 needs_edit** groups，并单列正确 no-op，不拿 no-op 充当编辑改善。全图、面部色度、背景、内容/细节、交付、误接受/误拒绝分别报告，不以局部综合色差替代全图。

新增肤色表必须分别列黄蓝、红绿、彩度、明度的正确方向/残差/不确定，不以 skin 总 pass 掩盖颜色失败。每组两个重复先归并，再以 source group 等权；切片结果按复核后实际标签显示，S2 少样只给方向性解释，S3/S4 未覆盖不填零成功率。

配对描述区间按 group bootstrap 10,000 次，`analysis_seed=20261102`，保存组内全部方法/重复；报告 unknown 最好/最坏情形。16 个小样本不证明普适有效性。扩展六臂的工程参考仍为 V2−V1 确认收益约 +15 个百分点、关键切片方向一致、无新增系统性严重损伤且成本可接受；若仅失败检测更好，只能主张可靠性增益。该门槛不是显著性保证。

失败链保留：输入/编码/可比性 → 差异漏检 → 目标遗漏 → PE/condition 丢失 → 执行不跟随 → verifier 漏检 → 交付。根因只在具备证据时标 confirmed，否则 probable/unknown。若新共同评价发现 v1/v2 都漏了肤色目标，这是实验结果，不回头替 V2 改 Prompt 再混算。

## 9. 工程修改地图与逐步验收

以下为**待实现工作包**；新路径是建议命名，不声称已在服务器存在。先定位本地已实现 E3、编排器、盲评页面与审查注入入口，生成 `calibration/IMPLEMENTATION_MAP.md`，映射到真实文件/commit；同功能优先修改原模块，不重复造一套。

建议新模块集中在 `research/focused_3arm/calibration/`，软件测试放 `engine/tests/test_focused_calibration.py`（或本地工程既有测试目录，记录映射）。不修改历史 v1/v2 templates/request identities。

| 工作包 | 输入→产物/接口 | 核心负例与通过依据 |
|---|---|---|
| K0 调用链实况 | E3 实际代码/请求→`IMPLEMENTATION_MAP.md`、输入视图与 prompt/model manifest | HTML 缩略图与模型输入不一致能被发现；错误 hash/顺序不能过 |
| K1 差异协议 | `contracts.py`：`validate_observation(record, bindings) -> dict`；`prompts.py`：`build_compare_request(packet, mode) -> dict` | “都自然”缺颜色轴失败；uncertain 不转 preserve；左右互换回映正确；无数值时不能伪填 |
| K2 证据包 | `views.py`：`build_review_packet(pair, supports, config) -> manifest`；`measurements.py`：`measure_pair(packet) -> records` | 全脸与子区职责分离；无 mask/未知编码数值不可用；不额外美化/归一化；D50/D65 混用被拒绝 |
| K3 已知变化 | `fixtures.py`：`build_calibration_cases(dev, recipe_config) -> manifest` | 零变化保留像素；编码后测量验证；clip 改变指定轴时标无效；真值参数不进入 VLM 请求 |
| K4 校准资格 | `calibrate.py`：`evaluate_configuration(manifest, responses, human_labels) -> report` | 每轴分母、漏检/反向/未知分开；顺序互换不增 N；全 unknown 不可通过；数字辅助不冒充视觉 |
| K5 E3/盲评接入 | `label_reviewed_v2.json`、`selection.v2.json`、共同评价版本/hash | 不给 v2 单独注入答案；旧标注不覆盖；主切片不预置脸保持；C 支持缺失时区域指标不可用 |

每个工作包先写可复现负例并确认失败，再做最小修改并验证；保留原相关回归测试。K1–K4 的合成测试通过不代表真实 VLM 通过，二者分别记账。

最低回归测试名称/断言：

```text
test_naturalness_cannot_substitute_chromatic_difference
test_uncertain_does_not_become_preserve_or_zero
test_role_swap_remaps_signed_direction
test_unknown_encoding_blocks_numeric_pass
test_d50_d65_mismatch_rejected
test_invalid_gamut_fixture_not_scored_as_model_failure
test_skin_subregion_observation_does_not_authorize_patch_edit
test_visual_result_is_archived_before_numeric_evidence
test_old_slice_label_and_transform_truth_absent_from_request
test_no_reference_answer_injected_only_to_v2
test_candidate_support_not_inferred_from_equal_dimensions
test_original_verdicts_and_labels_remain_immutable
```

建议完成后执行相应新增测试及现有 `reference_style`、`reference_core`、v1/v2 兼容测试；执行者记录真实命令和结果，不在此计划预填 PASS。若本地 `E1 967/967` 已有日志，归档其准确源码版本与范围，新增修改后仍需重新运行相关集合。

## 10. 执行顺序与冻结点

| 顺序 | 行动 | 放行条件 |
|---|---|---|
| E3-CAL-0 | 记录实际入口、输入视图、模型和旧 E3 输出 | 能重现“亮度有、肤色色差缺失”的实际例子；不是猜测 Prompt |
| E3-CAL-1 | dev 变体、人审与 R0/R1/R2 比较 | 输入合法、每轴证据完整、选定配置 |
| E3-CAL-2 | 锁定后确认，决定视觉/证据辅助/人工主评模式 | 按 §5 真实结果固定模式，不看 D_test 调参 |
| E3-R | 21组重新做差异与目标复核 | 保存旧新标注、分歧、可比性和切片变化；不因自然度默认保持脸 |
| P1/P2 | 现有 dev 运行检查与正式 manifest 冻结 | 固定 comparator、目标、评分、模型、全部三臂 spec、顺序和剩余预算 |
| P3/P4 | 96槽主实验 + M0/M1 | 不静默加码；全部失败/未知留账 |
| P5/P6 | 独立盲评、数值解释、报告 | 区分生成收益、传递收益、失败检测收益与不可判断 |

若已经有正式 D_test 输出：记录本次变更为评价版本修订，对全部保留候选统一重评，旧分数不删除；若用这些输出调过比较器，明确 exploratory，不能再称未见确认。不得只重评某个 arm。

## 11. 交付与报告

只回传一份 `FOCUSED_QWEN_V1_V2_REPORT.md`；服务器内部可有 JSON/图像/日志，但报告包含校准章节、完整计划账本和可核对证据索引。

必须新增：

- 当前方案/本次变更与源码、runtime、Prompt/视图/色彩配置身份；部署与测试仅按真实证据。
- CAL 各配置、每轴方向/检测/漏检/误报/unknown、顺序与区域一致性；合成与真实分别报告；human labels、分歧与资格模式。
- 原 21 组草案→复核差异：肤色目标新增/删除/保持/未定，谁确认、依据何在；保留原 S1=17 的历史事实，不强留新计数。
- 全图优先的 A/B/C 可视化、整脸/背景与必要诊断子区；数字不能代替照片观察。报告预览与 native 图分别绑定，私有图不上传公开仓库。
- 主结果和肤色逐轴表；内置 verifier 与独立评价的误放行/误拒绝；完整分母、source-group 配对表与成本。
- 未读图、未运行、缺原生图、未知编码、缺支持或未完成人审均标明；真实可访问持久证据路径与 SHA，不能只留不可访问的 GPU 临时路径。

冻结配置文件、人工标签及容差在私有目录；提交代码和脱敏计划可以公开。公开仓库不得包含私有照片、原始请求中的身份信息或密钥。

## 12. 核对依据与引用

所有实现结论限于以下固定源码；新增接口、门槛、扰动与工作包均为本修订的设计，不是已经完成的功能。

- [Reference v2 schema](https://github.com/baolinv0/HarnessIR/blob/cebafcd0e1f8d842115863ff4676f72eb751e53f/engine/src/hre/v3/reference_retouch_v2.py#L17-L103) 与 [阶段指令](https://github.com/baolinv0/HarnessIR/blob/cebafcd0e1f8d842115863ff4676f72eb751e53f/engine/src/hre/v3/reference_retouch_v2.py#L350-L406)。
- [A/B 区域分布测量](https://github.com/baolinv0/HarnessIR/blob/cebafcd0e1f8d842115863ff4676f72eb751e53f/engine/src/hre/reference_style/s2_measure.py) 与 [公开证据投影](https://github.com/baolinv0/HarnessIR/blob/cebafcd0e1f8d842115863ff4676f72eb751e53f/engine/src/hre/reference_style/s2_public.py)。
- [图像优先与证据复核](https://github.com/baolinv0/HarnessIR/blob/cebafcd0e1f8d842115863ff4676f72eb751e53f/engine/src/hre/reference_style/s4_review.py)、[私有验收规则](https://github.com/baolinv0/HarnessIR/blob/cebafcd0e1f8d842115863ff4676f72eb751e53f/engine/src/hre/reference_style/s4_verify.py)、[全图六轴 gate](https://github.com/baolinv0/HarnessIR/blob/cebafcd0e1f8d842115863ff4676f72eb751e53f/engine/src/hre/reference_core/holistic.py)。
- [原完整六臂计划](EXPERIMENT_PLAN.md)、[统一运行手册](../RUNBOOK.md)、[四模型部署与命令](../../four_model_v3/RUNBOOK.md)。本修订不自动启动或改写大六臂研究。
- [CIE：CIELAB 定义及参考白](https://cie.co.at/eilv/157)：Lab 和由其导出的明度/彩度/色相量须声明参考白；不据此设通用摄影匹配阈值。
- [ICC：D50 PCS 与色适应](https://www.color.org/whyd50/)、[ICC sRGB profiles](https://registry.color.org/rgb-registry/srgbprofiles)：用于约束数值色彩链，不表明服务器实际显示器已校准。

**完成定义：当前交付是修订计划。代码补丁、真实校准结果、21组图像复核、三臂生成结果均须由后续实际执行给出，不以本文件代替。**
