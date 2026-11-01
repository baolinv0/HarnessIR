# HarnessRefEnhance 实验协议 V1

版本：`ref_enhance_v1`；设计日期：2026-10-13；状态：**设计与执行模板，未运行模型，未获得真实结果**。本文件遵循 `00_SHARED_CONTRACT.md`，配置见 `config/experiment_profiles.json`，清单样例见 `examples/dataset_manifest.example.json`。

## 1. 问题、可支持的结论与边界

输入 A 是已冻结的 Modular Neural ISP prediction，B 是同场景但非像素对齐的 iPhone 17 外观参考，输出 C 是对 A 的 rendering enhancement。研究问题是：在给定这一对 A/B 时，诊断、受限证据和编辑指令是否帮助改善可比较的亮度、色彩与层次，同时保住 A 的内容。

本协议定位为 **pair-specific reference-guided rendering enhancement**。它不评价 ISP reconstruction，不证明能泛化到任意 iPhone 17 风格，不把 B 当 pixel GT，也不把生成 C 当真实 GT。通过本协议最多能得到这批场景、这些桌面会话条件下的配对结果；论文创新、统计功效、跨设备泛化须另行验证。

预先登记三个问题：

| 问题 | 合法比较 | 主要结果 | 排除的解释 |
|---|---|---|---|
| H1：agent 指令有无单次增益 | AgentSingle − DirectRef；两臂生成上限均为 1 | 独立最终盲评 joint success 的场景配对差值 | 仅依赖更多生成样本 |
| H2：反馈重试是否值得 | AgentAdaptive − DirectBestOf3；两臂生成上限均为 3，同 selector | 同一主指标，并报告实际调用和成本 | 不能用 Adaptive 对一次 DirectRef 宣称策略增益 |
| H3：简单确定性处理是否已足够 | 各生成臂与 dev 冻结的 ColorCurve 比较 | 内容保持、风格改善、失败与耗时 | 仅增加复杂流程，实际等价于简单调色 |

Baseline=A 是必要对照，记 `terminal_reason=baseline_only,success=false,fallback=false`；生成失败后交付 A 才是 fallback。ColorCurve 是建议增加的工程对照；若缺失，不得作“agent 超过简单调色”的结论。H1 为正式主要比较，H2 为预登记次要比较。其他评分、切片、消融视为辅助或探索性结果，不能事后换成主要指标。

## 2. 实验臂与公平条件

| arm_id | 输入 / 指令 | 生成上限 | 可自适应改指令 | 输出选择 |
|---|---|---:|---|---|
| `baseline` | A 原样 | 0 | 否 | A |
| `direct_ref` | 冻结 A+B+固定 DirectRef prompt | 1 | 否 | 同 selector；无可用输出回退 A |
| `agent_single` | A+B；Diagnosis → 按需证据 → Compose | 1 | 生成前可以；生成后不重试 | 同 selector；无可用输出回退 A |
| `agent_adaptive` | 同 AgentSingle；反馈后 Refine | 3 | 是；每次仍从冻结 A+B 开始 | 同 selector；可提前接受 / 停止 |
| `direct_best_of_3` | A+B+与 DirectRef 完全相同的固定 prompt，独立生成 | 3 | 否；不得把 verifier 反馈写入编辑指令 | 同 selector；通常提交满 3 次，共享硬停止规则 |
| `color_curve_dev_frozen` | A；B 的预登记可比较 ROI 统计；dev 冻结的简单颜色/曲线算法 | 0 | 否 | 一次确定性输出；配置全局冻结 |

所有臂共享 canonical A/B、可比较区域标注、输出文件校验、几何约束、Verifier 版本、selector 版本及最终评价 rubric。DirectRef 编辑指令不得按测试图临时优化。DirectBestOf3 的生成会话彼此独立，不在后一次会话保留前一次结果或反馈。AgentAdaptive 每次 Executor 只看 A、B 和本轮编辑文字，不能看到上轮 C、证据可视化或工具伪彩色图。

selector 是流程内组件，不是最终裁判。V1 冻结为按生成顺序选最早 accepted：有效 geometry、content=pass、critical_defects 为空、confidence≥0.7、style=improved。没有 accepted 时选最早 usable：有效 geometry、content=pass、critical_defects 为空、confidence≥0.7；允许 style 不满足 improved，但须 `review_required=true,success=false`。没有 usable 时交付 A，`fallback=true`。所有臂复用此规则，不按 confidence 或无参考质量分数排名；同次生成若返回多输出，V1仅供应商顺序首个完整输出成为正式candidate；其他输出只审计、不参与selector，可知额外生成仍计预算。

DirectBestOf3 逐候选运行同 Verifier 与冻结保真/可比较性rubric。它不因普通“已接受”提前停，以便形成固定样本数对照；达到上限、相同 bytes、明确不可用 reference、预算不可观测或执行硬错误时停止。正常跑完 K 记 `terminal_reason=fixed_k_complete`，可选之前最早 accepted 并 `success=true`；固定K完成但无accepted仍记fixed_k_complete且success=false；`budget_exhausted` 专用于Adaptive等未通过的预算耗尽，必须 `success=false`。duplicate 停止时如已存在 accepted，仍可交付该最早 accepted 并 success=true。Adaptive 可按公共合同早停。二者“公平”指同生成上限，不意味着实际次数、时间或总资源成本相同；必须逐一报告这些差异。可另作 DirectBestOf3 前 1/2/3 次候选的描述性成本曲线，不能事后重定义主臂。

ColorCurve 只允许预登记的曝光 / 白平衡 / 饱和度 / 单调 tone curve 等低自由度处理；参数范围与求解规则在 dev 选择后冻结。B 的统计仅从预先标注的同语义且可比较 ROI 计算，可逐对求解冻结规则允许的参数。不得逐测试图手调、换算法、调权重或更换 ROI。没有可信对应区域时该臂按预登记规则停止或 A 回退，失败计入该臂。该输出单独作为 baseline，不能在官方生成结果上继续调色。

## 3. 数据准备、纳入与分组

### 3.1 每一对必须留存的采样清单

1. 给物理场景 / 拍摄事件分配 `scene_group_id`；同一场景的 burst、近重复、重拍、同一 DNG 的不同 prediction，以及其全部生成后代都继承同一 group。
2. 保存 A 的原始输入（如 DNG）、A prediction 原文件、B 原文件。保存原始 SHA256、尺寸、EXIF orientation、capture time / timezone、相机型号、曝光信息和原始 ICC / transfer-function 来源。未知字段写 null / `unknown`，不能估计后伪装成观测。
3. 冻结 baseline repo URL、commit、dirty status / diff hash、checkpoint 文件 SHA256、实际 predict 命令、依赖环境、输入文件 SHA、输出 SHA；无法取得者列为缺口，正式实验不得声称预测来源可复现。
4. A/B 各自 EXIF 定向和 profile 解释后转换为 SDR sRGB canonical PNG。保存转换工具版本、参数、源 profile、目的 profile、profile 文件 hash（若存在）、canonical SHA。不得强行认为两个文件大小或方向相同。无法解释 HDR / HEIC 时先阻止正式入组，完成可解释 SDR 导出后才重新评审。
5. 在看到任何方法输出前，由数据标注者标记光照 / 时间 / 遮挡 / 视角 / 语义组成变化；独立记录 A/B 各自坐标下的 manual ROI 与比较维度。坐标为各图自己的归一化 `[x,y,w,h]`，不能把 A 的框直接贴到 B。
6. 标注主要场景层和交叉内容标签；标注 `reference_usable`、不可比较区域及原因。冻结标注者、时间、规则版本和清单 SHA。
7. 以 group 分配 split，生成去重报告；检查 test group 的原图、参考、生成图、诊断 / 人工反馈均未被用于 prompt、算法或 checkpoint 选择。
8. 原始图、canonical 图、manifest 与参考可用性审批齐备才 `ready_for_enrollment=true`。示例清单中的全零 SHA、占位路径与示例尺寸不得入组。

### 3.2 冻结纳入与剔除规则

纳入要求：A 的来源已固定；B 可解释为指定 iPhone 17 参考或明确记录的待验证来源；A/B 至少有足够的同语义可比较区域，能就预登记 rendering 维度判断方向；图像授权及本地文件可用；canonical 色彩解释通过。

运行前统一剔除：不同场景、主要内容无法建立同语义比较、显著不同照明 / 时间导致所有目标维度不可判断、profile 无法解释、缺失输入 / 溯源、与其他 split 的近重复未解决。轻微视角变化本身不构成剔除理由，但视角差异区域不得作外观统计。

剔除先于 arm 执行，必须对所有臂一致。输出不好、某臂失败、selector 拒绝、人工不喜欢结果都不是剔除理由。入组后发现 reference 不可用，应保留该 case 的 ITT 记录并标 `reference_unusable_after_enrollment`；单列所有臂一致排除的敏感性分析，不能只删某臂的 case。替换 A/B 必须创建新 revision；旧 revision 不被覆盖，正式冻结集不能静默替换。

### 3.3 分层与防泄漏

主层为 5 个互斥场景类：`outdoor_even_daylight`、`backlit_high_dynamic_range`、`indoor_daylight`、`indoor_artificial_mixed`、`night_lowlight`。按登记规则优先分配 night → mixed indoor → backlit/HDR → indoor daylight → outdoor even；无法归类可记 other，但不临时填入某层冒充配额。人像 / 肤色、可读文字、细纹理、天空 / 植被、运动 / 遮挡是跨层标签，单独报告。

R2 使用 12 对、尽量 12 个独立 group，五层配额为 3/3/2/2/2；人像和文字各至少 4 对，标签可重叠。这是压力覆盖，不是代表性抽样。

R3 建议 **至少 60 对独立正式 test 配对**，每主层至少 12 对；额外准备独立 dev ≥12 对、validation ≥12 对。若数据不足，优先守住 group 隔离并报告缩减，而非把同 burst 拆成多个“独立”样本。推荐总量从 84 对起；若每 group 有多对，test group 数和 pair 数均报告。dev 可调 prompt 与 ColorCurve，validation 仅用于冻结协议 / 预算 / selector，test 不用于任何选择。R2 pilot 全部划入 dev 或 validation，不再作 test。split 随机种子固定为 20261013；这只是分组种子，绝不是图像模型 seed。

对已有数据做 group 分层分配：先构建关联连通分量，再用固定种子在每层按 group 分配；跨层 group 不拆散，用预登记主层计配额。组大小不一时优先接近层配额并记录偏差。冻结 `split_manifest_sha256` 后，所有臂使用完全相同的 case 集。新图只能入新的实验 revision。

## 4. R0–R3 执行顺序与工程闸门

| 阶段 | 工作 | 必须产物 | 允许的结论 |
|---|---|---|---|
| R0：零生成协议测试 | 检查 schema / hash /路径；用 fixture 演练超时、重复、错 case、非法 JSON、预算耗尽、手动导入、失败回退 | 校验日志、状态事件、失败夹具和预算台账 | 合同可被实现；不能说明图像能力 |
| R1：1 对真实链 | 手动验证桌面端读写、两图编辑、派发、落盘四项 capability；至少跑 Baseline、DirectRef、AgentSingle 各 1 次；再分别验证预算 3 两臂 | 真实原始输出、实际提交数、各阶段耗时、独立盲评单例记录 | 这台机器这一条件下链路可执行；不能称自动化已普遍成立 |
| R2：12 对 pilot | 按冻结臂表运行；覆盖五层、人像、文字；检查 selector 偏差、内容破坏、成本和可比较性 | 全部 arm/case 输出、ITT 表、盲评标签、错误类型、候选选择审计 | 工程可行性和后续风险；不证明 power / 新颖性 |
| R3：正式冻结集 | 在 R2 后冻结配置、prompt、split、rubric、预算；盲评独立开展 | preregistration hash、逐 case 数据、scene 配对 CI、成本 / 失败报告 | 仅支持预登记比较范围内的结果 |

R0 必测：① output A/B 身份或 SHA 错误；② request / response round、attempt 不匹配；③图像缺失或损坏；④第三次后再生成被拒；⑤生成已提交但落盘超时仍计预算；⑥相同 bytes 立即停止；⑦未知 reference 可用性不自动成功；⑧无 usable 候选只回退 A；⑨可用但未严格接受的候选 `success=false`；⑩ format repair 不触发新看图 / 新生成；⑪ICC/EXIF转换未说明时不能入组；⑫未授权会话自动化不可宣称成功。

R1 go 条件：四项 capability 均有本机观测，A/B 未串图，原始 C 与 SHA 已落盘，身份 / 状态 / 预算日志齐全，人工接管可恢复且步骤可追踪；R1 的图像好坏只记单例，不因一张好图批准正式研究。

R2 的以下数值是**预登记工程 heuristic，不是科学显著性或功效保证**：

| 决策 | 可测条件 |
|---|---|
| `GO`：进入 R3 | 身份、hash、预算违规均为 0；关键 provenance 与评审记录完整率 100%；AgentSingle 与 Adaptive 各至少 11/12 case 有有效生成候选；AgentSingle 严重内容破坏 ≤1/12；single 最终 joint success ≥7/12 且比 DirectRef 至少多 2/12；若计划声明重试增益，Adaptive joint success ≥8/12 且比 DirectBestOf3 至少多 1/12 |
| `PROBE`：补定位再冻结 | 安全 / 记账条件通过但效果未过 GO；或不可判断 reference ≥3/12；或 selector 与最终裁判 success 分歧 ≥3/12；分别只改数据准入、指令、工具、selector 中已定位的一项，在新的 dev revision 复测，不能继续用同结果调 test |
| `STOP`：先修复，不扩大实验 | 任一串图、test 泄漏、未记账生成、无说明色彩转换；或 AgentSingle / Adaptive 任一严重内容破坏 ≥3/12；或 AgentSingle joint success 比 DirectRef 少 ≥3/12；记录失败并停止扩大运行 |

如数据不足满足 12 个独立 group，R2 只能记 exploratory probe。若 single 没有增益，而 Adaptive 与 BestOf3 相当，优先考虑“更多采样解释了改善”，不得以 Adaptive 超过 DirectRef 声称 agent 策略有效。GO 仅批准投入正式验证，不表示结论成立。

## 5. 桌面真实执行与计费 / 失败记账

运行前输出 manifest / config / prompt / selector / rubric 的 SHA 与版本。在 case 内随机排列方法执行顺序；用固定分配种子 20261013，在可能条件下以会话日期 / UI 模型名称分 block 平衡。同一 case 的主比较尽量在同一时段与同一可见模型设置执行；切换模型 /服务后另记 block，不把跨版本差异混入无说明的平均值。

逐次生成保存 `case_id,case_revision,state_revision_issued,arm_id,round,attempt,request_sha256,submission_time,completion_time,status,error_type,ui_model_name,model_version,model_seed,session_id,operator,manual_steps,output_assets`。不能读取的 model version / seed 必须是 `unknown`，session_id 不可观测时 null。保存模型可见文字，不记录未授权的隐私会话。

`max_generations` 是每 case/arm 的生成提交上限，含首次提交、失败提交、人工点击重新生成及可知后台重生成。一次已提交请求即使超时、错误或没有图，仍计 1；纯文本 Diagnosis / Compose / Verify / Refine 与 JSON repair 不计图像生成，但记入阶段调用、耗时及成本。传输 attempt 增加不自动等于新生成；是否产生额外提交必须单独记录。

桌面端无法保证内部隐藏采样数可知。记录 `observed_generation_submissions`、`known_backend_regenerations`、`backend_regeneration_count_status=known|unknown` 与 `accounted_generations`。内部次数未知时只声称“可观测提交预算受控”，不得声称控制了真实内部总采样。发送状态不确定时按可能已提交保守占用 1 个预算位，并暂停人工核对；不能通过再次点击绕过上限。外部已知 regeneration 超限属于协议违规，保留 ITT，不把超出的好图纳入正式结果。

每臂报告：生成上限；实际提交分布；可知后台重生成；文本 / 看图阶段调用；失败与重试原因；wall time；操作员 active minutes；可观察账单 / credit 成本及货币；订阅成本分摊方法（若使用）和不可观测成本字段。桌面套餐边际费用未知时写 null / unknown，不编造 API token、GPU FLOP 或 dollar。总开销包含失败、repair、未选择候选及 regeneration；不能只报告最终成功一张的开销。

输出默认 `strict`：保留生成原文件，输出必须直接满足已冻结的尺寸 /宽高比合同；不 warp、crop 或自动 colour adjustment。R1 后如确需 `aspect_preserving_resize`，必须创建新配置版本，对各生成臂统一采用，原文件仍保留；宽高比相对 A 偏差 ≤0.5% 才允许等比例 resize，超阈值仍失败。不能把 geometry 变化通过形变“修正”后继续评分；最终评审同时能审计 raw / normalized 的对应关系。

## 6. 独立最终盲评

流程 selector 完成并锁定交付 C 后，才生成 eval bundle。由独立脚本重命名候选为随机代码、删除方法 / prompt / verifier 信息，用独立种子 20261014 随机排列候选。A 与 B 角色始终明确，防止把 content anchor 搞错；屏幕上的 A/B 面板位置、候选 X/Y 顺序与方法运行顺序独立随机化。映射由评审不能读取的文件保存，全部标签冻结后才揭盲。Baseline 可能因与 A 相同而被猜到，此盲化局限必须报告。

最低配置为 2 名未参与该 case prompt 编写 / 选图的独立评审者。评审者不看诊断、过程评分、重试次数或 arm 名称，使用同一冻结 rubric；不能用 Agent prompt 临时推导评分标准。两人对 content pass/fail 或总体 style 方向冲突时由第三名独立评审者裁决；未能裁决保留 uncertain / abstention。若只能有 1 名评审者，标 pilot 局限，不能把多次重复打分当多个独立场景。若改用模型评审，单独报告 evaluator 的版本可观察性、独立会话与人工抽审；V1 首选独立人工评审。

| 评价维度 | 锚点与固定判据 | 标签 |
|---|---|---|
| 可比较性 | 先看冻结 ROI /限制；不对未匹配视角、遮挡、不同照明区域推断渲染优劣 | usable / partial / unusable / uncertain |
| 风格方向 | 仅相对 B 判断预登记可比亮度、色偏、饱和度、tone/层次；判断 C 比 A 是否有可见总体改善，不能以复制 B 的物体或纹理获分 | improved / unchanged / worse / uncertain |
| 属性接近度 | 各可判断属性的 0–4 ordinal：0 明显偏离，1 较偏离，2 部分接近，3 接近，4 高度接近；不能判断记 null | 每属性 0–4 +原因；辅助指标 |
| 内容保持 | 对 A 判断构图、几何、身份、人体、物体、可读文字、重要纹理；风格差异本身不算内容破坏 | pass / fail / uncertain；minor / critical 缺陷清单 |
| 方法偏好 | 两张匿名候选在参考风格与原内容共同约束下选优；内容严重破坏不能胜过内容完好候选 | X / Y / tie / uncertain / abstain |

评审者只能在冻结可比较维度内评价风格；使用 neutral colour /亮度等通用语言，不显示逐 case 的 agent 编辑目标。整体 improved 要有相对 A 朝 B 的明确可见 rendering 改善，同时没有另一可比关键维度的明显恶化；证据不足记 uncertain。临界差异允许 unchanged / tie。图像打不开、无法评审或评审者主动弃权分别记录 error / uncertain / abstain，不强迫二选一。标签、原始评分、理由及裁决均保存，分歧率作为附加指标。

最终 `joint_success = (style_direction == improved) AND (content_preservation == pass) AND (critical_defects == 0)`。同 bytes 的 A 回退不可能满足 improved。最终联合成功与 Controller `success` 分别记录，允许二者不同。最终 evaluator 不使用流程 confidence≥0.7 作决定，也不因 verifier 通过而默认成功。

## 7. 指标、分母与统计

ITT 集合是冻结后计划对每臂运行的全部入组 case。取消、失败、超时、非法输出、超预算、缺评审、uncertain / abstention 全部保留。主要 joint success 将这些未证实成功的情况保守记 0，并按原因单列；缺失不是伪造为“人判断风格更差”。同时报告仅完成评审的条件结果和同规则剔除后的敏感性分析，不能用条件结果替换 ITT。

| 指标 | 分母 / 用途 |
|---|---|
| 最终 joint success rate | 全部入组 case；主要指标，Baseline 按定义为 0 |
| style improved / unchanged / worse / uncertain rates | 全部入组 case；另列无图 /缺评审比例 |
| content pass / fail / uncertain rates、critical defect rate | 全部入组 case；failure 无图与真实视觉内容破坏分开 |
| valid candidate / delivery / fallback / Controller accept rates | 全部入组 case；流程可靠性，与最终质量分开 |
| pairwise win / loss / tie / uncertain / abstain rates | 全部入组配对比较；另列 wins/(wins+losses) 作为条件比例并显式给分母 |
| selector regret / disagreement | 对原始候选全部独立盲评分的预登记 audit 子集；最终最优可用候选与 selector 交付的差值，只描述不重新选图 |
| 生成、文本调用、失败、cost / time | 全部计划 case，含失败和未选候选；均值、中位数、P90、分布和未知比例 |

主要估计使用 **场景配对**：先对每个 `scene_group_id` 内 case 计算每臂 mean joint success，再计算 AgentSingle−DirectRef 的 group 差值，最后对 group 等权平均。H2 同法。case 加权差值可另报，但不冒充场景独立性。

正式 CI 建议 paired scene cluster bootstrap：固定分析种子 20261015，10,000 次有放回采样 scene group，每次同时抽取该组所有臂、case 与既有评审标签，计算宏平均差值，报告 percentile 95% CI。不独立 bootstrap 两个臂、不把同组多图或多评审者当独立 n。R2 的 12 组 CI 可输出但标不稳定、仅描述；不凭“跨过零 / 没跨过零”证明或否定创新。

Wilson 区间只用于**独立二项单位**的单臂比例：例如每 group 恰一对且每对一份最终裁决时的 joint success / content failure。若一组多对、同 case 多候选 /多次尝试、重叠评审记录，不能直接把记录数放进 Wilson n；改用 group bootstrap 或只作描述。配对差值、偏好含 tie / abstention 的多分类率也不直接套 Wilson。所有报告明确 n_pairs、n_groups、n_raters、n_valid 和分母。

R3 的 ≥60 对是工程起点，不保证对任意效应有足够 power。R2 后可用观察到的方差和预先选定最小有价值差值做样本量规划，但必须在 test 前记录假设、目标与上限；不能边看 test 结果边加样本直到“显著”。只一个主要比较；其他比较如给统计检验，需预登记多重比较处理或明确探索性。

## 8. 工具统计能说明什么

不能对非对齐 B 直接计算 PSNR / SSIM / LPIPS 并称其为质量或准确率。A→C 的几何 / OCR /身份检查只服务内容保持；光度变化不能被误当 restoration 错误。任何自动检测阈值均须 dev 校准并冻结，保留不确定性，不能代替最终独立内容裁决。

全局 histogram、均值、对比度可作运行观察，但会受天空比例、视角、遮挡、语义组成变化影响，不作为成功指标。可信辅助统计限定在 **预登记、同语义、同照明且组成可比较** 的 A/B/C manual ROI：记录 mask、像素数、有效面积、sRGB/linear-light 空间、统计维度、工具版本；报告亮度分位数、中性区域色偏等条件统计。C 的 ROI 按 A 坐标检查几何后映射；B 使用独立 ROI。无可信比较区域就记不可计算，不能把 null 当 0 误差。ROI_COMPARE 的改进方向只算辅助证据，不生成一张假“对齐参考 GT”。

## 9. 消融与后续 pseudo-target 防护

先完成 H1/H2，再在 dev 或新冻结扩展集考虑：去掉局部工具证据、只用全局诊断、固定 selector 与不同 selector 的 audit、只 Refine 不加新工具、相同一次预算不同 prompt。每项一次只改变一个因素，保持生成上限与最终 rubric。不需要为 R1 的工程证明跑完整消融矩阵。

若未来把 C 用作训练目标，必须另立协议：C 只能称 **审查后的、对 A 几何对齐的 candidate / pseudo-target**，并保留原始生成图、严格内容审查、拒绝原因与选择来源。B 永远不是 pixel GT；模型输出也不因视觉漂亮而变 GT。不能使用正式 test 的 A、B、候选、评分、诊断或人类反馈训练 / 调参；所有 pseudo-target 继承源 A 的 group 与 split。训练 pseudo-target 构建、选择器训练、下游独立测试分别冻结，不能在同一参考集合既产生 target 又宣传泛化收益。

## 10. 实施产物与执行检查

建议结果布局：`runs/<experiment_id>/manifest.json`、`config_snapshot.json`、`events.jsonl`、`generation_ledger.jsonl`、`case_arm_outcomes.jsonl`、`eval/blind_bundle_manifest.json`、`eval/ratings.jsonl`、`eval/unblinding_map.json`、`analysis/summary.json` 与原始候选目录。盲化映射仅分析负责人持有；manifest / config / prompts / rubric / selector 的内容 hash 写入每轮记录。

执行前检查：所有占位字段已替换；所有实际路径位于合法 case 根；输入 SHA 和 canonical 参数校验通过；split 无 group 泄漏；profiles 与状态机上限一致；能力状态有真实证据；最终 rubric 已冻结。执行后检查：计划 case×arm 记录齐全；未选择与失败候选仍在；budget 不被 round / attempt 重置；selector 输出已锁定；blind ratings 在揭盲前冻结；ITT 表包含全部计划 case。

交付报告至少包含两张比较表：①单次 Baseline / DirectRef / AgentSingle / ColorCurve，②3 次上限 DirectBestOf3 / Adaptive。每行列 n_pairs、n_groups、joint success、style /content各率、fallback、实际生成均值/P90、全部成本和 unknown 比例；同时给场景配对差值及 CI。未实际运行的行写 `not_run`，不能填写示例成功率当结果。

本轮待实施：Controller / selector 统一版本与规则、桌面 capability probe、数据入组审批、独立盲评打包与分析脚本。所有 GO / PROBE / STOP 均需真实日志和评分后执行，当前不授予任何阶段通过。

## 汇总审查补充决议

V1 Refine不新增工具计划，始终使用diagnosis_planned_only冻结快照。Direct臂不经过Compose，固定prompt artifact与空证据快照；所有臂Verify使用同一冻结入组限制与保护rubric。固定K完整运行的终止原因统一fixed_k_complete，success由selector决定；未通过的Adaptive耗尽才记budget_exhausted。可选纯scale派生除0.5%初筛上界，还须raw_w*A_h==raw_h*A_w，比例稍有差异也不warp。

冲突决策顺序固定：先检查任一STOP条件；无STOP再检查全部适用GO条件；其余PROBE。严重内容缺陷由冻结rubric给出，评审分歧按第三名裁决或保留uncertain，不由流程confidence覆盖。统计定义采用config.common.stats_metric/display_stats_v1；Yprime为显示域亮度代理，不能称传感器线性亮度或物理照度。


实施补充（最终集成修复）：run 冻结的六模板 SHA 映射写入每个 runtime config；case 初始化记录实际模板源身份，最终导出比较实际执行冻结 contract 与 run frozen prompts，而非评估时已安装包。执行前包漂移保留 ITT 分母与真实成本、joint success=0；初始化后安装包变更不追溯否定已有真实证明。外部候选的 execution_contract 还需 execution_record_root，包含实际 case 冻结源、请求/渲染/dispatch 与事务链，绑定 case/revision/arm/A/B/config/selected asset；只有 config 文件的候选无法证明模板执行。结构化 content_preservation_annotations 在入组与 case 初始化时验证，A 保护坐标与所有规则/notes 在 Verify context 中无损保留；缺失标注统一为空列表，非法形状在 generation 前拒绝。具体字段与手交步骤见 ../EXPERIMENT_HANDOFF.md。真实 R1/pilot 仍为 not_run。
