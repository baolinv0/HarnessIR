# 原始 HarnessIR 五开源执行器适配与对比：工程实施实验方案

版本：v1.1 · 日期：2026-10-24（北京时间）
回传格式更新：仅交一个REPORT.md；实验设计、预算和比较臂沿用v1.0。  
状态：待工程实现、待服务器推理；本文件没有实验成绩或模型排名。  
使用对象：实现工程师、实验执行者、独立图像评审。  
核心定义：保留原始 HarnessIR 的诊断→按需工具→Compose→单图编辑→Verify/Refine，只替换五个图像执行器，并在必要位置添加模型表达适配。

## 0. 执行摘要与范围

### 0.1 必须完成的事情

1. 在原始 HarnessIR 流程接入 Qwen-Image-2.1、FireRed-Image-Edit-1.1、FLUX 3 Image Klein distilled、FIBO 2.0 Dev、MOSS-Image-SFT＋指定社区 Edit LoRA。
2. 五个模型均支持同一张 LQ、同一复原请求的直接编辑与 HarnessIR 编辑；一次执行只请求一张结果。
3. 比较直接编辑 D、原始 HarnessIR O、模型适配 HarnessIR A，先单次生成，再检验有限反馈。
4. 模型适配以必要接口、Compose 表达和匹配的 Refine 表达为主；诊断事实、工具证据、任务边界和评价标准共享。
5. 保存全部生成候选、最终条件、几何变换、失败及选择过程；仅回传按本目录 REPORT_TEMPLATE.md 填写的单文件 `REPORT.md`；完整实验产物在服务器留档。

### 0.2 本轮边界

任务为单图 SDR 复原。第一阶段不训练或微调；使用现成发布权重和现成编辑 LoRA。没有参考图、iPhone 风格目标、多参考检索、模型自动路由、模型集成、视频、RAW/HDR 或端侧部署。20 组 S26/iPhone 参考增强数据不自动作为本轮复原评测集。NB2/ChatGPT 编辑已有同图结果可单列视觉参照，不能混入五开源模型的受控排名。

不更换原始控制器，不要求把工程迁到 `hre models v3`。可以复用该分支四模型 adapter 的原生调用代码，但通过薄接口接入原来的 executor factory；复用不等于迁移任务系统。

### 0.3 最终需要回答

- 哪些模型在指定原生工作流下，能产生更好的单图复原结果？
- 原始 HarnessIR 相对同模型直接编辑，改善或损害了什么？
- 模型专属表达相对原始 Compose，是否增加了“有恢复、内容保持、可交付”的结果？
- 收益来自哪里：内容表达、文字条件、采样机会还是候选选择？
- 反馈是否优于同预算固定提示重采样？失败是工程、证据、编译、生成还是选择问题？

## 1. 冻结依据与原始方法合同

本方案核对的代码快照：`baolinv0/HarnessIR@86284d5d190614369c4e6c47c5ad8ed021c93a35`。工程师实施前记录实际基线 commit、服务器已有改动和补丁；服务器版本才是实际实验对象，不能用远端原版推测本地缺陷。

| 原始行为 | 本实验要求 |
|---|---|
| S1 观察退化并请求 T1 OCR/T2 FACE/T3 DEPTH/T4 SEG | 缓存每图一份诊断、工具计划和工具结果，供五模型 O/A 共享 |
| task type 来自 manifest，诊断不改 type；未知退回 mix | 冻结外部任务标签；blur/noise 等使用独立实验标签，不擅自冒充原版支持的 task block |
| S3 看原图、文字证据、可用 maps；S4 只见原图和文本条件 | 地图、彩色 overlay、mask 不送编辑器；原生 VGL/latent 是条件接口，不是第二张内容参考 |
| 原版 Compose 的 instruction 是较长英文指令 | O 保留实际原文；A 的改写是显式实验因子，改写前后均保存 |
| 默认 enable_redo=false | E1 是 S1–S4 单次执行，不能称已经验证反馈闭环 |
| redo 每次从原始 LQ 重跑 | 禁止把上轮生成图当下一轮编辑输入；反馈只能更新指令 |
| selector 可以选择早期轮次 | 保存 selected_round，不能默认交付最后一轮 |
| 默认部分任务执行颜色对齐 | 主实验统一 `color_adjust=false`；历史默认对齐只作独立附加对照 |
| 原执行层可归一化输出尺寸 | 保存原生尺寸和原图；尺寸异常不能仅因被 resize 回来就称执行正确 |
| resume 原来可基于已有交付文件跳过 | 本实验按生成签名验证缓存；不匹配则新 run，禁止同名旧图复用 |

所有主实验显式保存 resolved config，不能仅记录 configs/default.json；原入口未必自动加载该文件。

工程师先排查跨模型共享问题。RGB/alpha、工具失败处理、任务信息传递、refine 丢字段等若需要修复，形成独立 common-fixes commit，并对全部 D/O/A 适用。尚未确认的服务器问题记录待核对，不能写成已知缺陷。

## 2. 两个主命题与证据地图

| 命题 | 最小证据 | 排除的替代解释 | 对应实验 |
|---|---|---|---|
| C1：对某执行器，模型专属表达能在相同任务和图像生成预算下提高可用复原比例 | 冻结未调试样本上 A 对 O 的配对结果、严重错误及最终条件 | 多一份源图信息、放宽重建范围、换参数/分辨率、挑 seed、后处理 | E1；E2 定位机制 |
| C2：有证据的反馈能比同预算固定条件重采样带来更好的最终交付 | F 与 S 共享首轮、候选上限、seed 和 selector 的比较 | 只因多次采样、只因更好 selector、使用 GT/人工答案 | E3、E4 |

O 对 D 用于量化原始 Harness 的增益；它不是默认成立的前提。某些模型 A≤O 或 O≤D 是合法且必须报告的结果。五模型普遍受益、方法新颖、超过闭源模型、真实细节已恢复，均不由本轮自动成立。

## 3. 工程改造范围与最小接口

### 3.1 改动位置

| 工作包 | 应触及位置/职责 | 完成标志 |
|---|---|---|
| W1 执行器工厂 | 原 `harness/clients.py`、settings、RunConfig、两个 runner | 选择五模型；旧 backend 可继续运行；未知模型明确失败 |
| W2 原生适配 | 五个模型各自加载、条件编译、单次生成 | 单图输入、原生参数可追踪、无隐式第二次生成 |
| W3 Compose profile | 原 S3 附加表达适配；保留原始 composition JSON | O/A 来自同一冻结 O 结果，A 没增加无依据目标 |
| W4 Refine profile | 原 S5 按同一 profile 产生下一轮文本 | 保护事实和任务不丢失，保持短/结构化原生格式 |
| W5 观测及实验导出 | 原执行归档、指标、selector、resume 外围 | raw/canonical/delivery 可追溯；明细齐全；失败不消失 |

不要要求工程师另建通用 Agent 平台。可设一个内部 `ExecutorAdapter`，外部仍与现有 `edit([image_path], prompt)` 或等价接口兼容；增加 sidecar receipt 即可。

### 3.2 三个内部责任必须区分

1. `compile_condition`：把给定文本、源图及明确 profile 转为模型匹配条件，记录改写/JSON/输入绑定。
2. `generate_once`：使用已接受条件和源图一次生成；不自动挑图、重试、调参或扩写第二遍。
3. 原 HarnessIR：决定是否 refine、是否再生成以及最终交付。执行器内部不能再藏一个恢复 Agent。

所有模型可用独立进程/环境，串行运行；复用模型缓存。无需为了本方案开发多 GPU 调度器。出现 OOM/依赖冲突优先修部署，不能只对某 arm 偷降尺寸或换量化。

## 4. 五模型冻结 profile

以下为所读模型/工程资料给出的启动配置，不是已通过本地兼容性验证的最佳参数。E0 后冻结实际配置；之后变更产生新版本，不能覆盖主表中的同名 run。

| profile | 权重与原生条件 | 启动设置 | A 的表达适配假设 |
|---|---|---|---|
| qwen21 | Qwen-Image-2.1；默认官方 PE-I2I，本地固定版本 | 40 steps，true_cfg_scale=1.0，negative=""；记录 output_resolution、KV cache | 具体区域＋可检查恢复终态＋紧凑保护条款；明确允许修复拖影/边缘，避免复述大量禁止事项 |
| firered11 | FireRed-Image-Edit-1.1；固定 Recaption 模板及本地 provider | 40 steps，true_cfg_scale=4.0，negative=" " | 连贯的一次恢复要求，明确主体身份、字形和细结构，避免加入美颜/妆容目标 |
| flux3_klein | distilled 权重＋匹配的原生 i2i PUP | 16 steps；不硬塞其他 pipeline 的 CFG、negative 或 img2img strength | 复原改变与保持条件协调；使用真实 PUP 输出，审核是否新增光照、天气或对象 |
| fibo2_dev | FIBO 2.0 Dev；Thales/VGL 对应 schema 和模板 | 50 steps，guidance_scale=5.0 | 目标 VGL 场景属性与 edit_instruction 一致，冻结 source 对象关系和未知细节 |
| moss_sft_edit | MOSS-Image-SFT＋指定 chinoll Edit LoRA＋配套编辑 workflow | 作者工作流约 30 steps、CFG4、Euler/normal 为起点；冻结 LoRA scale、VAE、SLG及完整 workflow | 使用匹配的 edit_format 和 reference latents，再测简洁恢复要求；不拿纯 T2I 当 I2I |

约束：

- 一个 profile 是权重、LoRA、encoder、VAE、compiler、采样器及预处理的整体。跨模型结论是“指定模型＋指定工作流”的比较。
- Qwen 可增加 direct vs PE 消融，但 D/O/A 内 compiler 选择固定。不能 D/O 用 direct，A 用 PE，再把差异全归给 A。
- FireRed 固定 1.1，不能落入某 demo 的 1.0 默认值；不默认启用妆容/Lightning 等额外 LoRA。
- FLUX 的正常原生基线保留 PUP。PUP 在条件端只调用一次，执行端不可再次隐式扩写。通用本地 VLM 替代 PUP必须另命名。
- FIBO 若由本地 27B 生成 VGL，标为 local-VGL，不声称等同官方外部服务。schema 通过只证明格式合法，不能证明场景忠实。
- MOSS 固定 SFT＋明确编辑 LoRA，不混入 Base、其他 edit_format 或加速 LoRA。`edit_format="Moss-Image-Edit"`、配套 VAE、正负条件路径、参考预缩放及 latent 布局需要完整冻结。参考条件可能被缩放，实际尺寸必须记录。
- 五模型均遵守相同任务目标。不能只给 Qwen 更宽的重建许可，也不能把所有模型强迫成相同步数/CFG。

## 5. 共享事实与允许重建的边界

### 5.1 使用原始 composition JSON 作为共享起点

每图首先运行一次 S1–S3，保存 diagnosis、工具结果、maps、原始 composition 和原始 instruction。O 直接使用该 instruction。A 在同一份 composition 上做 profile 表达转换，仍属于 S3。

可增加 sidecar：targets、protected_facts、allowed_reconstruction、unknown_details、visible_text、source_evidence_refs。它用于审计和编译，不要求替换原 HarnessIR schema/控制器。

A 可合并、重排和明确表达现有目标，不能在未记录的情况下加入新任务、人工文字答案或从候选中推导的事实。O/A 的保护对象和允许重建范围一致。发现原始 O 存在明显错误诊断时，保留原记录；修正后的实验另开 common-evidence-fix 版本，不能只修 A。

### 5.2 具体操作定义

- 允许：去噪、减少已定位拖影、恢复有依据的连贯轮廓、打开有可见结构的暗部、减轻眩光/光晕。
- 保持：对象数量、相对位置、视角、可辨识类型、人物身份、可靠可读文字、应保留的夜景/浅景深/湿地反射等。
- 不确定：被完全遮蔽或不可读的事实不生成确定答案；没有 GT 时只能说结构目检合理，不能声称对应真实细节。
- 一般纹理的生成性补全与可核验事实分开标注。不得把所有新高频都判成错误，也不得把所有清晰细节都判成真实恢复。

贯穿例 `night_0043`：恢复左侧车辆水平拖影、连贯车体轮廓和车轮边缘；保持车辆类型、数量、视角、相对位置与夜景；不生成不可读车牌或小 Logo 的确定文字。各模型接受同一边界，仅改变表达形式。

### 5.3 源图证据冻结

OCR/27B 转录仅从 LQ 获得，先于生成结果固定。保存 `bbox/string/source/status/reason`；status 为 accepted/rejected/unknown。自报 confidence、工具置信度或 OCR 与 VLM 一致均不是自动真值。没有可靠依据的字符串不强制注入。

不从模型输出重新 OCR 后把它当源图事实。refine 可以描述残余拖影或字形损伤，不能把上轮生成的猜测写成下一轮的正确答案。

## 6. 主实验臂与唯一变量

| arm | 输入给条件编译器的内容 | S1–S3 | 图像调用 | 用途 |
|---|---|---|---:|---|
| Z | 直接返回源图，不调用生成器 | 无 | 0 | 零操作基线、检查保守回退 |
| D | 冻结的简短任务请求 | 无 | 1 | 原生直接编辑能力 |
| O | 原始 HarnessIR 的实际 instruction | 原样共享缓存 | 1 | 替换执行器后的原方法 |
| A | 同一 O composition 经 profile 表达适配后的 instruction | 相同缓存，S3 内适配 | 1 | 适配效果，主比较 A−O |
| S | A 的首轮最终条件固定，只变预定 seed | 固定 | 主实验2个候选 | 固定条件重采样 |
| F | A 首轮＋Verifier 反馈＋匹配 Refine＋重新编译 | S1/S2冻结 | 主实验2个候选 | 有限反馈，主比较 F−S |

D/O/A 在同模型使用相同 checkpoint、compiler、采样配置、条件/输出尺寸、seed、后处理开关。D 的任务请求须覆盖同一个任务范围，例如“去除相机运动模糊并改善低光可见性，保持内容与夜景”；不能 D 只要求去模糊、O/A 又同时提亮。

D 无工具提示，O/A 有工具，这是 Harness 因子；O/A 的差别只在表达适配。A 若多一次文本改写，计入真实开销。主表不能写“所有推理调用完全相同”，只能写图像生成次数相同。

冻结并保存：原始 instruction→适配文本→原生 compiler 输出→实际 executor 输入。若 compiler 抹平 O/A 差异，应报告该事实，不能仅凭 profile 已配置就宣称适配生效。

## 7. 数据、几何、颜色与缓存协议

### 7.1 默认小规模数据清单

本轮建议总计25张独立场景，5张开发、20张冻结测试。它是工程/方向性试验规模，不是可靠的普遍排名或安全非劣证明。

| 集合 | 数量 | 组成/用途 |
|---|---:|---|
| DEV | 5 | 0043、0049及另外3张预先指定图；用于部署、profile调试、评价校准 |
| TEST | 20 | 不参与提示调试；在查看输出前冻结样本与子集 |
| FEEDBACK | 20 | 与完整TEST一致；主实验测一次反馈，避免只选择失败图 |

TEST 按主问题分四组，每组5张：运动/失焦模糊、低光、噪声/压缩、混合退化。文字、人脸、高光、细纹理、夜景为可重叠标签。若现有数据不满足分组，先修订 manifest 和样本数，不能用不存在的图填数。0043/0049 已被观察，始终属于开发集。重复裁剪或同场景近帧不能算独立测试场景。

正式广泛结论可在策略冻结后扩展到原论文提供的 Real-NoGT/Real-Paired 等数据；先核查数据、许可和原始分组。没有测试完整集合时，必须写真实子集及筛选方式。

### 7.2 几何与颜色

1. canonical 输入为 EXIF/ICC 处理后 sRGB 8-bit RGB；透明输入需要事先固定合成规则，并保留原文件及 alpha，不将 alpha 当第四个颜色通道。
2. 主实验沿用原方法的1024长边工作图。S1–S3/tools 使用未 pad 工作图；S4 使用同一份预先保存的1024×1024居中黑 pad 图。坐标、有效内容框和反变换落盘。
3. 保存 raw native 输出、按固定内容框裁回的工作图、实际 delivery。主指标和ROI评估在相同未pad工作图坐标与尺度上完成；不得根据输出做自由配准来掩盖形变。
4. 记录原生输出宽高及每次 resize。如果编辑器未遵守预先要求的画布，标 execution_contract_violation；用于排查的尺寸归一化不能取消这条记录。
5. 主实验 color_adjust=false、gamma=false、锐化/去噪后处理=false。需要的后处理另存候选并重新验证，不覆盖 raw。
6. 各模型内部条件缩放必须记录。若 MOSS 参考编码为512而其他模型更高，不能称输入有效分辨率相同。需要时增加所有模型512条件的匹配分辨率对照，作为附加实验。
7. 默认全图执行；mask/bbox/crop-fuse、原生比例画布与2K输出均独立成臂，不混入主表。

### 7.3 生成签名与恢复

生成签名至少包括：source/canonical字节hash、实际执行条件及negative、checkpoint/LoRA/encoder/VAE标识、compiler与profile版本、steps/scheduler/CFG/seed、条件预处理、画布、执行源码与pipeline版本。指标签名单独包含RGB转换、灰度/亮度定义、ROI和实现版本。原生compiler得到的D条件不得注入O/A缓存中的诊断字段或工具事实；compiler可以按自身原生流程看源图，但不得额外调用Harness工具或重新规划。

改 prompt/参数应重新生成；仅修指标应只重算。相同整数 seed 仅表示配对记录，不表示不同架构拥有同一噪声。seed schedule 固定为 `[0,42]`（DEV）、`[42]`（TEST）、主反馈候选 `[42,1042]`；第三候选2042仅用于独立可选扩展。不因为某 seed 好看而更换。

模型调用返回状态不明时先对账，不能盲目重发；失败调用、额外输出和人工重跑都单列记账。

确认性数据生成不自动重抽直到成功。只有明确尚未提交的基础设施故障，允许至多一次相同条件/seed的传输重试并单列；已经消耗生成尝试的失败按原计划保留。返回状态未知先对账；任何重新生成不得覆盖失败记录。

## 8. 实验块与执行顺序

### E0：部署与链路可用性，必须

每模型最多3次图像调用，最多15次。使用 DEV 中清晰简单图、含文字/人物图或严重退化图完成：源图绑定检查、一次最小编辑、一次完整 O/A 链路冒烟。可合并检查，不能把增加调用藏在“一次实验”内。

检查：选定权重真实加载；源图进入原生image/latent条件；最终prompt实际进入executor；一次调用只生成计划内数量；全部组件版本和采样参数可追溯；raw→canonical→delivery正常；无外部参考、隐式第二次PUP/生成。

通过仅表示工程可用。MOSS 若不能按指定工作流证明图像条件有效，标该profile BLOCKED；保留计划位置与原因，不拿纯文生图补数、不将其工程失败解释为复原能力最差。其余模型继续。BLOCKED模型不进入画质效应均值，不补成平局；明确报告实际可执行的K个模型，同时保留五模型原计划。

### E1：首轮 D/O/A 主比较，必须

**DEV：**5图×5模型×3臂×2seed＝150次。先运行，再只在 DEV 调 profile。最多两轮有记录的profile修订；150为最终冻结版本的计划数，之前调试、失败与废弃版本额外计入探索成本，不能称总调用仍为150。

**冻结门：**profile、compiler、参数、ROI、任务边界、源图事实和评审规则全部固定；对A最终条件抽查目标遗漏、事实新增、文字改变。有问题先修DEV，不能进入TEST后继续调。

**TEST：**20图×5模型×3臂×1seed＝300次。D/O/A均单次生成、不运行在线refine；最终独立评价可另运行。O的共享诊断/工具/Compose缓存每图只产生一次，A使用同一份O composition；五模型不反复重新规划。

**主要对比：**每模型A−O；**次要对比：**每模型O−D；D/O/A与Z的改善和内容错误同时报告。不能把五模型平均值替代某模型自己的结果。

**开发阶段继续条件（工程筛选，非显著性结论）：**A改善方向不完全依赖单seed，适配文本遵守任务边界，没有新出现且可复现的严重内容错误。某模型A无收益时保留O，照样报告负结果；不以必须凑齐五个正结果为目标。

### E2：适配机制与文字条件，定向实验

在DEV预先固定每模型至多2张图，使用已有A候选，新增一个最关键的删除适配臂 `A_minus_component`，2seed。上限2图×5模型×1新增臂×2seed＝20次。只删除一个表达部件，其余一致。

候选机制：Qwen去掉具体恢复终态或改回冗长保护表达；FireRed去掉连贯编辑组织但保持全部事实；FLUX去掉Harness特定保留/改变组织，继续保留PUP；FIBO去掉本轮Harness提供的属性一致性约束，继续使用合法VGL；MOSS比较匹配格式下两种提示表达，不故意错接latent作为弱对照。每次选择具体机制，不能同时删三个部件后声称某一句话有效。

文字分支仅在确有文字问题时运行：固定最多2张DEV文字图，比较T0无字符串注入、Tauto仅LQ自动接纳转录、Toracle人工独立核实转录。其他提示模板相同，且Tauto在看到oracle前冻结。每模型每图每臂2seed。若T0/Tauto/Toracle中只有一个与E1的A完全同条件可复用，其余两臂新增上限2图×5模型×2臂×2seed＝40次；不匹配则最多60次，不能虚报复用。

Toracle只测执行器条件上限，不能计入自动系统收益。真文字未知的ROI不做oracle、不算CER真值。分开统计转录覆盖/正确、执行器遵从、最终文字正确、布局变化和无依据新增文字。

E2 的新策略只在DEV调试。若E1 TEST已运行，E2结果不能用于改写同一TEST主表；需要新冻结版本和未看输出的数据。

### E3：固定候选池的 verifier 检验，必须记录；V1为条件启用

复用E1候选和已有redo，无新增图像生成。每图一个固定pool，至少包含O/A，必要时包含D、Z及已有候选；记录精确pool成员，V0/V1看相同成员和相同展示顺序。展示顺序随机但对两者配对固定。

- V0：原始共同verifier/gates/selector版本，五模型不换标准。
- V1：若开发，增加固定ROI测量及清晰度/曝光数值的解释；不按模型设宽松标准。它是独立实验因子。

先在DEV校准V1，TEST池用于冻结后的评估。人工先盲评候选可接受集合/最佳集合，之后比较V0/V1。报告最佳集合命中、可接受选择率、严重错选、正确控光误拒、假字/形变误接纳；允许最佳集合并列。

数值固定定义：sRGB编码值先转RGB，再用 `Y'=0.2126R+0.7152G+0.0722B` 得显示域亮度代理（不是线性辐射/EV）；范围0–1。ROI从LQ一次固定；暗部source mask可固定Y'≤0.10，输出近黑比例用Y'≤0.02；高光统计any-channel≥0.98与all-channel≥0.98；阈值在DEV冻结。报告中位数、P10/P50/P90、分母和mask hash。

清晰度辅助用固定RGB→灰度、固定尺度/ROI的Laplacian方差，禁止把倍率当恢复能力倍数。不得将“全图均值下降”“LQ-SSIM下降”自动解释为复原失败。

保留原有视觉/结构gate信息，但记录其误拒：尺寸、相对LQ结构/色度门限不是图像真实内容正确性的证明。主反馈实验V0或V1的选择在TEST输出生成前冻结，F/S使用完全同版；E3结果若事后促成换selector，需要独立新验证。

### E4：反馈改写 vs 固定条件重采样，必须，先小规模

在完整20张TEST上，五模型各运行F/S。共享E1-A的seed42首轮候选和该首轮verdict；第二候选的seed为1042。主实验测一次refine的价值；第三候选seed2042只作为可选扩展。

- S固定首轮编译后的完整条件，不再次PE/PUP/VGL，只换seed。
- F仅按具体可支持反馈修改指令，重新编译；保持事实/原始证据，且每轮输入原始LQ。若首图已被接受或没有可支持的新动作，F第二候选退化为相同条件resample，不重新PE/PUP/VGL，不强行编造refine。记录accepted/no_supported_action/refine_applied/compiler_noop与实际改写率。若F/S完整生成签名相同，可生成一次并共同引用，200次新增因此只是上限。
- 固定候选预算比较使用2个候选；为隔离采样机会，两臂都执行同样计划内2次尝试（工程失败计为消耗尝试）。S/F之后交同一selector选择。该实验停止规则是预算耗尽，不把一臂早停造成机会差当反馈增益。
- 另外从F日志离线重放“首次可接受即停止”的生产政策，报告节约调用；这不是实际少生成的成本，只能标为模拟调用预算。
- 所有候选合法但未被接受时仍标quality_not_met；所有候选都违反合同或生成失败时，可交源图fallback但失败状态保留。候选选择遵循冻结原规则，不把严重gate失败样本从评价分母删除。

上限20图×5模型×2政策×2候选＝400候选位。两臂共享100张首轮，各自的首轮均可复用，所以最多新增200次图像调用；实际distinct候选最多300张（100首轮＋200新增）。复用必须签名完全匹配。可选第三候选最多再新增200次，单独报告它的边际收益，不能悄悄并回两候选主结果。

A首轮生成失败但已有合法条件时，F/S均无图像反馈，第二步使用该条件按计划重采样；首轮失败仍占候选位。若A连合法条件都未产生，F/S记相同前置失败并保留分母，不补造首图或绕过编译失败。

成功解释：F优于S且严重内容错误不增加，支持该profile有反馈收益。F≈S说明收益可能仅来自采样；F<S检查refine目标丢失、过度纠错与selector。另报告实际actionable反馈子集，不能只用该事后子集替代完整20张结果；本轮仍为小样本试验。

## 9. 评价协议：改善与保真分别判断

### 9.1 两个主结果与成对判断

对每张结果独立填写：

1. `target_improved`：yes/no/uncertain，是否解决预先指定退化；需要命名可见依据。
2. `severe_content_error`：yes/no/uncertain，是否存在确定严重事实/几何/身份/文字错误。
3. `usable_restoration`：合法交付、目标改善yes、严重内容错误no且没有使任务不可用的明显伪影，三者同时成立才为yes。uncertain保持未知，不冒充no或tie。

主指标为每模型A−O的确定可用复原率差；配对偏好W/T/L/U和严重内容错误率差同时报告。缺失/失败在“所有计划图像上的确定成功率”中不算成功，且单列原因。确定成功率是保守可识别量；每臂同时报告可用率边界 `[S/N,(S+U)/N]`，S为确定成功数、U为可用性未知数。A−O的真实可用率差边界为 `[(S_A−S_O−U_O)/N,(S_A+U_A−S_O)/N]`；不能因未知率不同而虚称真实成功率提高。对于内容错误未知的图，严重错误率同时给“已确认错误/N”和“(已确认错误＋未知)/N”边界，不能把未知当安全。

配对偏好：先判断两臂是否可用；一可用一不可用时可用者胜；都可用时比较目标退化、附带损伤与自然度；两者都不可用可以记录相对偏好，但不计为可用成功；无法判断写U。运行失败是工程结局，不伪装成图像盲评的主观负分，单独在运行完成率中体现。

### 9.2 人工盲评

两名评审独立查看LQ、随机左右排列的候选、同尺度ROI，隐藏模型、arm、prompt及自动分数。先在DEV校准规则，不展示TEST结果进行训练。记录每位原始标注，分歧交第三人或保留U，不覆盖原始记录。评审名单以ID记录。

同一组图在相同显示设置观察：全图fit-to-screen＋100%ROI；放大倍率一致。关键ROI包含主要退化位置及所有明显退步位置。文字真值由独立可靠来源核实，不能因为某输出看起来像英文单词就认定正确。

### 9.3 自动指标与独立评价

- 无GT：局部亮度/高光、sharpness、MANIQA/CLIP-IQA/MUSIQ/TOPIQ等只作辅助；固定版本、尺度和方向。NR指标高不证明事实正确。
- 有真实配准GT：PSNR/SSIM/LPIPS/DISTS按冻结尺寸、颜色域、边界规则计算；GT不进入生成、反馈、gate或selector。
- 参考增强的iPhone图不是本任务的像素GT。相对LQ的SSIM是相似性，不是复原质量真值。
- 可另运行固定独立D/F评价器；D为退化消除、F为内容保持，逐图DF=sqrt(D*F)后求均值，同时展示D/F。它不能替代人评；运行时verifier的自评分不作独立科学证据。
- 独立最终评价至少依靠未参与生成/选择的盲评人员；使用另一VLM时记录版本和与运行时模型的关联，不能虚称完全独立。

### 9.4 统计与验收含义

- 实验单位为独立图像/场景。DEV两seed、候选和ROI不扩充样本量；多帧同场景按scene聚类。
- TEST报告N_plan、N_run、N_valid、N_judged、N_unknown、N_fail；W/T/L/U分母明确。不能只看accepted图片。
- 对可用率差和偏好净胜率，在图像/scene层配对bootstrap 10,000次给95%CI；20图CI可能很宽，不能由“无显著差异”宣称等效。偏好存在U时，另给净胜率可识别范围 `[(W−L−U)/N,(W−L+U)/N]`。若跨模型汇总，以同一源图整簇保留其全部模型结果，不能把20图×5模型当100张独立图。
- 本轮明确为pilot：每模型A−O、O−D和F−S报告原始计数、未调整95%CI及不确定性，不用显著性成败语言。若后续要同时确认C1/C2，预注册5个A−O＋5个F−S为共同10比较家族并控制多重比较；O−D描述性报告，或事先设计层级检验，不能事后拆家族挑结果。
- 方向性工程采用门槛（本方案建议，非领域标准）：20张TEST上A相对O净增加至少4张确定可用复原（20个百分点）、已确认严重内容错误数不增加，才建议扩大适配验证；同时给可判定配对增益/损失和未知配对数。CI跨0时仍只能称试验性候选，未知边界不能支持虚假的正增益。该门槛不证明安全非劣。
- 确认性结论：预注册主要终点CI支持正增益，且内容错误风险已通过足够样本独立检查；达不到则写部分支持或证据不足。样本量应由DEV/首轮方差和预期最小效应另行确定，不能承诺25图足够。

## 10. 必须记录的输出与失败分类

建议保留现有目录，额外文件可用sidecar，不要求重写实验系统。

每个 image/model/arm/seed/candidate 记录：

- ID、split、scene、任务与标签；source/canonical/geometry/ROI hash。
- 模型、revision、LoRA与scale、encoder/VAE、dtype/quant/offload、pipeline与源码版本。
- 诊断/工具证据/原始composition；适配前后instruction；native compiler原始与最终输出；actual executor request。
- steps/CFG/scheduler/negative/seed、输入顺序及所有内部条件尺寸、原生输出尺寸。
- raw/canonical/delivery路径及hash；后处理；原始候选→选中候选→交付关系。
- runtime verdict、gate值、停止/选择原因；独立评审及指标版本。
- 每次调用和失败、加载/编译/生成/VAE/工具/verify耗时、端到端耗时、峰值显存。

失败码至少区分：deployment_failed、source_condition_invalid、compiler_failed、condition_goal_drift、generation_failed、unknown_submission、execution_contract_violation、residual_degradation、content_damage、text_failure、selection_error、metric_failed、not_run、blocked。

“工具没有请求”“工具运行失败”“工具输出空”“工具证据不可靠”四种情况分别记。任何失败不能通过原图回退、丢行或重新编号消失。

## 11. 预算、耗时与资源安排

| 块 | 计划图像调用 | 说明 |
|---|---:|---|
| E0 | ≤15 | 部署冒烟上限 |
| E1 DEV最终版本 | 150 | 不含之前探索/失败/修订成本 |
| E1 TEST | 300 | 五模型三臂单次生成 |
| E3 | 0 | 复用候选，另计VLM/人工成本 |
| E4 | ≤200新增 | 完整20图，两候选，首轮完全复用时 |
| 核心合计 | ≤665 | 只对已定义最终版本且复用成立；探索额外单列 |
| E2删除适配 | ≤20新增 | 每模型最多一个关键删除项 |
| E2文字条件 | ≤40新增，不能复用则≤60 | 可选，仅确有文字问题时 |
| 可选第三候选 | ≤200新增 | 不并入E4两候选主表 |

这不是硬性消耗指标。profile被BLOCKED或样本不满足条件时按真实计划修订，并保留缺失原因。

没有服务器计时，禁止填写虚构GPU小时。E0实测每模型热启动生成时间tg、冷加载tl、条件编译tc及S1/S2/S5时间。计划GPU小时≈Σ(新增生成数_m*tg_m＋编译数_m*tc_m＋实际冷加载数_m*tl_m)/3600；区分GPU占用与CPU/网络墙钟。共享planning只收一次实际成本，另给按单独部署每模型运行的成本口径。

E1 TEST两名评审的主要配对为20图×5模型×2对比(A/O、O/D)×2评审＝400条配对判断，另有单图质量/错误、E3/E4及分歧处理。人工时长先用DEV10条计时估算。

## 12. 实施里程碑与交接验收

| 里程碑 | 工程交付/动作 | 停止或继续 |
|---|---|---|
| M0 | 固定基线、共用修复、resolved配置、25图manifest | 数据/版本未定不开始TEST |
| M1 | 五executor工厂、原生调用、raw归档、E0 | 某profile失败则BLOCKED，其余继续 |
| M2 | 共享S1–S3缓存、D/O/A、profile与Refine；DEV | 只有DEV可调；保留负结果 |
| M3 | 冻结profile、ROI、评价和完整20图反馈计划；完成TEST | TEST上不再改提示、阈值、样本或selector |
| M4 | 固定池E3、同预算E4 | 选择错误与生成错误分开 |
| M5 | 单文件REPORT；其余明细、图像、配置日志留服务器 | 报告内计数/关联一致，证据索引齐全 |

工程验收与画质验收分开：合同/CPU检查只证明接口、预算、hash、几何、缓存和条件传递；真实权重推理、显存/耗时、语义忠实与恢复质量必须有服务器证据。不要为通过测试伪造PUP/VGL/native输出。

机制解释以实际完成的受控实验为限：未运行E2不能宣称某个文字/表达部件单独有效；未运行V1不能声称局部测量改善了选择。F−S验证的是整个反馈改写＋重新编译路径的增量价值。

最小必要的软件检查：一次调用计数；最终条件未被改写；profile/seed改变不复用旧图；refine仍来自原LQ；alpha不污染统计；ROI反映射正确；GT不进入在线路径；失败/未知状态不会重复提交；selector输出能回溯候选。除此无需为文档本身或无风险包装层堆砌测试。

## 13. 最终只回传一个REPORT.md

用户通过复制粘贴回传文档。唯一必需提交物为 `REPORT.md`：按本目录模板填写，包含本轮结论、五模型设置、样本/完成计数、主结果、关键逐图记录、异常/协议偏离、证据索引和限制。未运行阶段只写“未运行＋原因”，不必复制空表。

以下产物仍按实验要求生成并保存在服务器，但不要求用户上传或打包：逐候选/逐图CSV或JSONL、完整resolved config、版本/补丁、所有实际prompts与compiler输出、LQ/原始候选/delivery/拼图、verifier/gate/selector日志、人工原始标注及指标文件。报告内保留其ID、服务器路径和hash即可；路径/hash用于追溯，不代表接收方已经读取证据。

原BLOCKED.md与DEVIATIONS.md的必要内容直接写入REPORT的“异常与偏离”，不要求另交文件。工程师可在服务器继续使用已有目录和辅助文件，无需重写实验系统。

复制粘贴的报告中至少嵌入：

- 五模型D/O/A及F/S的完成数、原始W/T/L/U、成功/严重错误/未知计数与区间。
- 每个已测TEST图×模型一行的紧凑汇总；失败、未判定与回退必须列出。
- 每个实际运行模型至少一条适配审计例，含关键原始/适配/实际执行文本、最终condition hash、是否遗漏目标/新增事实。完整长条件可以留服务器，未回传原文时明确其证据限制。
- 所有严重退步的文字记录、局部测量摘要、评审人数/盲法/分歧及证据索引。

独立人工盲评仍是实验评价要求；未完成就如实标记。仅收到文字报告、没有可读取图像时，接收方可以检查计数、配置一致性和推断边界，不能独立核验画质。视觉结论注明“执行者目检/评审报告，接收方未独立图像核验”，不因此宣称确认性验证完成。

## 14. 原始来源与证据边界

### 原 HarnessIR 与现有实现（固定代码）

- [五阶段原流程](https://github.com/baolinv0/HarnessIR/blob/86284d5d190614369c4e6c47c5ad8ed021c93a35/harness/pipeline.py)
- [原 Compose](https://github.com/baolinv0/HarnessIR/blob/86284d5d190614369c4e6c47c5ad8ed021c93a35/prompts/compose.txt)
- [原 task blocks](https://github.com/baolinv0/HarnessIR/blob/86284d5d190614369c4e6c47c5ad8ed021c93a35/prompts/compose_blocks.txt)
- [原 Verify](https://github.com/baolinv0/HarnessIR/blob/86284d5d190614369c4e6c47c5ad8ed021c93a35/prompts/verify.txt)
- [执行与几何](https://github.com/baolinv0/HarnessIR/blob/86284d5d190614369c4e6c47c5ad8ed021c93a35/harness/stages/execute.py)
- [最终选择规则](https://github.com/baolinv0/HarnessIR/blob/86284d5d190614369c4e6c47c5ad8ed021c93a35/harness/selection.py)
- [默认配置](https://github.com/baolinv0/HarnessIR/blob/86284d5d190614369c4e6c47c5ad8ed021c93a35/configs/default.json)
- [可复用四模型原生适配说明](https://github.com/baolinv0/HarnessIR/blob/86284d5d190614369c4e6c47c5ad8ed021c93a35/docs/four_model_v3/DESIGN_AND_COMPLETION.md)

### 模型接口原始来源

- [Qwen-Image-2.1](https://github.com/QwenLM/Qwen-Image-2.1)；[PE-I2I](https://huggingface.co/Qwen/Qwen-Image-2.1-PE-I2I/blob/main/system_prompt.txt)
- [FireRed](https://github.com/FireRedTeam/FireRed-Image-Edit)；[1.1模型卡](https://huggingface.co/FireRedTeam/FireRed-Image-Edit-1.1)
- [FLUX Klein官方文档](https://docs.bfl.ai/flux_3/flux3_image_klein)；[PUP](https://huggingface.co/black-forest-labs/flux-3-image-klein-pup)
- [FIBO Dev模型卡](https://huggingface.co/briaai/Fibo-2.0-dev)；[VGL](https://github.com/Bria-AI/vgl)
- [MOSS官方基座](https://github.com/OpenMOSS/MOSS-Image)；[社区编辑LoRA](https://huggingface.co/chinoll/Moss-Image-Edit)；[配套工作流](https://github.com/Chenkin-x/ComfyUI-Moss-Image-Edit/blob/main/README.en.md)；[ComfyUI编辑条件实现](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_extras/nodes_moss_image.py)

上游链接可能更新，工程师下载时需固定实际revision/文件hash。这里的接口与启动参数不是严重复原效果证据。权重/LoRA可用性与用途按实际下载版本记录，不用“开源”一词推导完整商业授权。

## 15. 最终检查

- [ ] 保留原始五阶段及source-only语义；没有引入参考迁移任务。
- [ ] D/O/A同模型原生compiler、采样、尺寸一致。
- [ ] A表达改写与新增信息/宽松重建许可没有混淆。
- [ ] Compose与Refine的profile一致；最终条件实际送到executor。
- [ ] F/S首轮、预算、seed和selector匹配。
- [ ] 原生输出、交付、回退与失败全部可追踪。
- [ ] TEST冻结，DEV与TEST结果分开。
- [ ] 人评独立于运行时verifier；指标不替代事实核验。
- [ ] 统计以图像/scene为单位；小样本边界明确。
- [ ] 软件可用、真实推理、画质收益三种状态分开填写。
