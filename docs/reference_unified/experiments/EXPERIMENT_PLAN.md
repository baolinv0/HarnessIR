# HarnessIR 参考图风格实验计划

日期：2026-11-02。协议版本：`reference-experiment-v1`。配套单文档报告：[EXPERIMENT_REPORT.html](EXPERIMENT_REPORT.html)。

**当前状态：PLAN_READY / EXECUTION_NOT_RUN。** 本次只制定计划、报告规范并上传模板，没有启动 GPU、付费接口或真实质量实验。下述规模与阈值是默认预登记方案；实际数据清单、后端、预算、报告体积等必填项完成后，才能把一次具体实验签为 `FROZEN`。空模板中的 null/NOT_RUN 不是零分或实验结果。

## 1. 问题、主张与完成边界

目标是在保持源图 A 的人物身份、文字、物体、几何和原生细节的同时，让输出 C 采用参考图 B 的可比较摄影外观。重点检查诊断是否识别了正确差异、最终执行条件是否保留限制、模型是否执行了条件、最终验证是否诚实发现失败。好看、变亮、变平滑或流程 accepted 都不能单独证明参考风格迁移成功。

| ID | 待验证主张 | 最低需要的证据 | 对应实验 |
|---|---|---|---|
| C1，唯一主要质量主张 | 固定同一后端、同一图像调用上限时，统一模型感知方案比原生 A+B 直接路径有更多有效交付，同时保护 A | 留出数据、共同输出前标准、独立盲评、固定分母、场景配对差值区间、原生交付和严重损伤门槛 | B1；B3补充预算解释 |
| C2，支持性机制主张 | 同一 A 换成两种有意区分的 B 后，系统能分别向正确的参考端点变化，而非一律美化 | 预先选择的双参考、方向预言、同后端配对输出、独立全图/整区域判断及 A 保护 | B2 |

要排除的解释：收益只来自更大生成预算；参考图没有实际影响；评价只奖励统一提亮/平滑；局部数值掩盖整体失败；小图/插值掩盖原生细节损失；丢掉失败、未知或 no-op 后才得到好看的成功率。

本计划验证**系统包级效果**。主表不能单独归因于 evidence review、语义审计、某个提示词或某个模型。B2 干预 B 时会同时影响诊断、规划和编辑条件，能检验整条系统是否利用 B，不能单独证明底层图像条件分支的因果贡献。不进行新模型训练，也不把 C 自动认证为训练真值。

工程依据：生产代码 `bd25c7a853c73945b17cfa75a569a8e6d45f0eb8` 已完成独立代码审查及 Linux/Windows 专项、Linux 全量 CI；最终文档提交 `1c54a737f7f3c297128f0041f7bf0eefd7b26dda` 的 engine/workflows 相同。这些是软件验证，**不计为本实验图像结果**。实际执行须记录 checkout SHA、dirty diff 与 engine 子树 SHA，不只填写本段版本号。

## 2. 运行前冻结清单

先在报告内填写以下内容并保存完整配置原文及 SHA256；任一必需项缺失则状态 `BLOCKED_SETUP`，可以完成环境诊断，不能宣称质量实验已开始或通过。

| 必填项 | 具体内容 |
|---|---|
| 实验身份 | experiment_id、plan_version/hash、冻结时间/时区、执行者、批准的实验块、固定终止规则 |
| 数据来源 | 实际数据集名称/版本/可发布范围；source_group_id；A/B 原始与显示文件 SHA256、尺寸、方向、ICC/编码/位深、原始到派生转换；去重/拆分清单 |
| A 的输入域 | study spec 使用 `base_model_output` 或 `camera_rgb`；Base 输出必须附真实 Base checkpoint/版本、生成配置和来源，无法核查则 unknown，不自动改称相机域 |
| 模型身份 | profile_id、真实加载模型/权重 hash、pipeline/依赖版本、编译器、执行器、设备/显存、原生输出能力；配置别名不是模型身份凭证 |
| 随机性 | 请求 seed、实际是否支持/观察到 seed、重复编号、运行顺序 seed；不支持时 actual_seed=unknown，禁止填成已控制 |
| 共同标准 | 输出前八维 coverage、A/B 事实、整对象可比性/限制、目标与验收标准、baseline、保护项、伪影项、交付要求、观察协议 |
| 预算 | 各块 planned rows、image attempts 硬上限、stage/compiler/tool caps、GPU-hours/API金额上限、最大并发、超限/未知提交停止规则 |
| 报告运输 | 唯一返回文件名、实际通道允许字节数、预览编码策略、native 证据保存方式/可读性、剩余空间与报告打包自检结果 |
| 评价 | 两名实际独立观察者/资格与暴露、盲化映射管理者、native 观看方式、冲突裁决者、冻结阈值和分析代码版本 |

报告中的 tracker 就是本次实验执行表，不另要求 GPU 返回 TRACKER.md、JSON、图片目录或压缩包。GPU 内部可以使用这些中间文件；最终必须完整收入一份报告或按下文声明证据缺失。

## 3. 数据、拆分与交付模式

### 3.1 默认样本设计

| 集合 | 默认规模与用途 | 输出前选择规则 |
|---|---|---|
| D_dev | 8 个独立 source groups，每组 1 个 A/B；调试/耗时测量，六臂各 1 repeat | 覆盖人物整脸、文字、复杂材质、低光/高光和不匹配参考；不进入主表推断 |
| D_test | 60 个独立 source groups，每组 1 个 A/B；六臂各 3 repeats | 目标约 48 needs_edit、6 already_satisfied、6 uncertain；由输出前 baseline 判定并冻结，不能为凑数重贴标签 |
| D_swap | 从 D_test 的 needs_edit 中预选 12 groups，增加一个 B2 | 不看任何方法输出，选择两种外观方向明确、均有可比对象的 B1/B2；覆盖至少三类外观方向 |
| D_feedback | 从 D_test 的 needs_edit 中预选 12 groups | 按场景分层随机选择，不挑选主表失败或容易改善的样本；与 D_swap 的重叠须记录 |
| D_camera，可选 | 独立 12 groups，相机/原图域；六臂 3 repeats | 仅域外诊断，不混入 Base 主表，不扩大主试验独立样本数 |

以上是资源约束的默认方案，**没有声称已完成统计功效证明**。D_dev 后、D_test 解封前，可依据预算和独立 pilot 的方差/分歧率一次性调整 N、比例和停止规则，须生成新 plan_version 并冻结。记录假定的最小效应、功效/区间宽度估计、实际可承担规模；若未做功效计算，明确 `power_not_established`。固定 N 后不因测试集结果不显著而继续加样、换模型、换指标直至成功；需要扩展时登记一项新实验，旧结果保留。

同一源照片的裁切、不同 Base 版本、重复拍摄、同场景/同人物连拍、多个参考及三次重复都按预先定义的 source group 聚类。同一 B 或近重复参考不得跨 dev/test；冻结 reference-cluster 清单。默认主试验各 source group 使用互不重复的参考簇；若一个参考簇被多个 A 共用，按 source/reference 复用关系的连接分量组成 analysis_group，在拆分前一并处理，统计按该组聚类并报告实际独立组数。有效独立组不足默认60时，须冻结前调整数据或明确较小规模，不能继续声称60个独立样本。D_swap 的双参考及可选后端复测不增加独立 source-group 数。

用户历史提到的 GGT100K 只作为待核实的数据来源线索。仓库未提供本次实际数据版本、合法输入清单或 A/B/GT 的确切语义；执行者必须核实再填写，不能声称已经使用该数据集。B 通常是外观参考，未证明像素对齐时不得用 C 对 B 的 PSNR/SSIM/LPIPS 作为迁移质量结论。有真正对齐的恢复 GT 时另列辅助表，标记 real_gt；模型生成参考/自监督指标须标 proxy。

### 3.2 冻结图像路径

主实验使用 `source_native`、`full_frame`，`require_native_source_resolution=true`、`require_detail_pass=true`。原生大小/网格、真实 backend 能力必须在生成前预检，原 native C、最终交付 C、显示预览分别绑定。padding/上采样/改报告阈值不能补足 native 信息；不做拉伸。源/参考色彩编码未知时，保留 unknown，正式颜色数值不可用。

如果设备确实只能处理较小网格，另冻 `declared_working_size` 子实验：先产出真实工作尺寸 A，之后所有臂共用同一 A；报告原始与工作尺寸，单独计分。不能把失败的 source_native 行事后迁入 working-size 表，不能用工作尺寸结果声称解决了原生交付。

## 4. 实验矩阵：最多五个核心块

### B0 — 预检与诊断校准（MUST）

在 D_dev 上做六臂实际链路资格检查，最多 48 个首次图像提交槽。另跑清楚标记为合成协议样本的 A=A no-op、不可行尺寸、未知编码、缺少 C support、错候选复核和评分冲突；后者只验证软件路径，不进入视觉效果统计。

检查清单：实际 A/B 是否按正确顺序进入请求；checkpoint 与响应身份是否可验证；diagnosis → effective diagnosis → frozen intent → 最终原生 condition/audit → native C → whole-image review → local explanations → delivery/feedback 是否全部可追溯；no-op 的 compiler/image 计数是否确为 0；原生预检失败是否在生成前拦截；未知提交是否保留预算占用而非盲目重试。

人工核查八维事实/可比性/限制，不用模型自身诊断充当正确答案。统计诊断问题、条件丢失、编译审计失败、执行不跟随、验证漏检的**实际出现数/可检查数**，不能把未生成的阶段记成成功。模型调用、调试失败、重跑及 token/GPU 时间全部入账。

Go：至少一条真实后端 A+B 链路及必需交付门槛成立，预算/报告运输可行，独立评价可用。Stop：身份未知、语义审计未完成、原生能力不足、证据无法保存或预算未冻结时，记录具体阻塞，不用 dummy 图/其他模型悄悄替代。

### B1 — 六臂主表（MUST；C1）

| arm_id（与当前 builder 一致） | 实际比较对象 |
|---|---|
| legacy_native_ab | 原生 A+B 路径，无 Harness 诊断规划 |
| legacy_shared_ab | 历史 Harness shared 路径 |
| legacy_aware_ab | 历史 Harness model-aware 路径 |
| retouch_shared_ab | 新 reference_retouch_v2 shared 路径 |
| retouch_aware_ab | 新 reference_retouch_v2 model-aware 路径，预登记主方法 |
| legacy_aware_a | 真实 source-only restoration；独立 A-only brief/regions，运行时无 B/共同评价/baseline 泄漏 |

固定 M* 一个主后端，60 groups × 6 arms × 3 repeats = **1080 planned rows，最多 1080 首次图像提交槽**。每任务 `single/max_generations=1`，每次请求 n=1；支持 no-op 的真实 S 可以用零图像调用终结，仍保留 planned row。A 本身作为共同离线 baseline，不额外生成一张 A。

M* 默认考虑仓库 `qwen21` 别名，只有能力/身份核实后才冻结；仓库其他合法 profile_id 为 `firered11`、`flux3_klein`、`fibo2_dev`。别名、目录名称或配置成功均不证明相应真实权重已经部署。不能看 D_test 结果后挑最佳后端充当 M*。可选扩展是在预选 12 groups 上用其余三后端重复六臂三次，另加最多 648 槽，按后端分别报告。

六臂用同一源/参考、原生交付门槛和共同离线评价。各 package 的原生规划可能不同；现有 builder 不自动把它们锁成同一个 intent。故主要结论为包级比较，不叫纯编译器消融。生成调度顺序按冻结 seed 在每个 group 内平衡随机化，避免按方法分时段部署漂移；可批量加载模型，但必须报告时段、版本和缓存。

唯一主要对比：`retouch_aware_ab − legacy_native_ab`，主指标为输出前 baseline=needs_edit 的有效编辑成功率差。另列全部任务成功、六轴事实、A 保护、严重损伤、native/detail、失败/unknown、no-op 正确率与实际成本。其他四臂、模型排名和切片均为次要/探索性，不事后替换主对比。

### B2 — 同 A 双参考干预（MUST；C2）

12 groups × 两方法（retouch_aware_ab、legacy_native_ab）× 3 repeats。B1 端点可以引用主表已经冻结并实际完成的原 run_id；新 B2 端点另冻 A/B2 事实、目标和可比性，再生成 **72 个新增单次任务槽**。复用是分析引用，不把旧图片导入伪装成新调用，不修改原任务身份，不重复计费/计样本。

在生成前写下每组 B1/B2 的方向预言，如全图暖冷、调性/高光过渡、材质关系；不能以两张不同内容图片的颜色均值差代替外观判据。A 与 B 的光照/材质不可比时记录 conditional/unknown，不能要求拷贝 B 内容。对每个 C1/C2，盲评同时检查它是否更符合自己请求的 B 端点、是否保留 A。

每组记录三次重复的双向跟随 `true/false/unknown`、方向/幅度/置信度和保护项。至少两次已确认双向跟随且任一次没有已知严重 A 损伤才记 group confirmed；未知不算确认。默认机制检查目标为至少 10/12 groups confirmed，同时披露所有 12 组结果与区间；这是有限样本的支持性探针，不是普遍风格因果或统计等价证明。若 C 不随 B 变化，优先核查输入、最终 condition、编译器/执行器和验证漏检；不能仅因 C 看起来漂亮判成功。

### B3 — 三次图像预算下的反馈与简化检查（MUST）

在预选 12 groups 上，新冻三个合法 task 变体，各 3 repeats，最多三次生成：

| 变体 | strategy / contract | policy | 检验点 |
|---|---|---|---|
| F1 | model_aware / reference_retouch_v2 | feedback, max_generations=3 | 完整反馈路径 |
| F2 | 与 F1 相同 | resample, max_generations=3 | 删除反馈修订后的简单重复生成，隔离反馈收益 |
| F3 | native / historical | resample, max_generations=3 | 强于单次 Direct 的图像预算对照 |

**12 × 3 × 3 × 3 = 324 个新增图像提交槽上限。** 现有 native 不支持 feedback，不能设置非法 native+feedback。从新 spec/新 case_id 开始，policy/seed_schedule/预算全部在创建前冻结；不能修改主表已冻结的 single 任务，不能假定不同 policy 的 r0 条件/请求 hash 一致并强制复用。F1/F2 每轮从原始 A+B 执行，保留所有未选和失败候选；pending review/unknown submission 不得变成免费重试。

共同评价实际最终交付的 C，而非事后人选的最漂亮候选。F1 vs F2 是反馈删除比较；F1 vs F3 为包级预算对照。记录逐轮建议、目标/保护/伪影/交付作用域、condition 差分、最终语义审计、候选身份与实际收益。只允许反馈改变表达，不能更换冻结目标、放宽标准或私下调容忍阈值。

“等预算”仅指相同最多三次图像提交，不等于相同 VLM token、GPU 时间、编译器/工具调用或金额。报告实际全部成本、每个额外成功的增量成本和 round0→final 改善/退化。F2 或 F3 若已达到相同效果而更省成本，则不能声称复杂反馈必要；不显著也不能叫统计等价。

### B4 — 失败定位与边界（MUST；复用已有输出）

对所有失败/未知自动汇总，按预先固定规则选展示案例：每类首个失败、首个高置信误放行、首个 no-op 错误、最大已知 native 失败，以及冻结随机 seed 抽取的成功样本。无法展示全部大图时仍保留每个 run 的预览/账本，不只挑好看的案例。

至少区分：输入/编码或数据域；A/B 整对象不可比；诊断事实错误或漏目标；条件/限制丢失；原生编译不一致；执行器不跟随；A 身份/文字/几何/纹理受损；整体与局部冲突；验证误放行/误拒绝；native/detail 失败；接口/预算/证据缺失。每项报告分母是可检查记录，不把缺证归入某个已确认模型缺陷。独立观察存在分歧则保留两份，显式裁决。

可选 camera 域上最多 12×6×3=216 槽，作为域外诊断单列。ROI/颜色数字只解释已绑定的真正对应 A/B/C 支撑；无 C support、未知编码或不可比光照时写 unavailable。整脸/整对象/整材质是单位，不恢复拆眼鼻嘴编辑，不让局部统计覆盖全图观感。

## 5. 统一评价与统计

### 5.1 评价顺序与独立性

1. **先冻结 baseline 与共同 rubric，后看任何输出。** 八维目标和源图保护独立；baseline 只有 needs_edit/already_satisfied/uncertain/其他实际合法值，不从结果回填。
2. 对最终选定候选导出中性 A/B/C 盲包；方法、提示词、内部 accepted、policy 和映射不交给评审。A/B 角色保持明确。观察者此前见图、模型身份及参与生成的事实必须披露；方法标签盲不等于从未见图。
3. 两名独立观察者分别先看全图六轴：tone、color、brightness、lighting_naturalness、material_relationships、processing_appearance；记录 relative direction、magnitude、confidence、evidence。同时独立检查 A 的身份/表情、文字、内容、几何、纹理及伪影。
4. 再看整区域关系，最后看解释数字；有冲突就保留，不能局部数值抵消全图观察。必须实际以 native pixels 1:1/native zoom 查看 A/C 才可填写 detail；缩略图、尺寸相等或模型自评不等于细节通过。
5. 完整决策字段分歧，包括 relative_to_A、目标、保护、六轴、伪影、置信度、独立性和 detail，均保持待裁决。裁决引用全部相关评分和确切 candidate/result/evaluation 身份，追加新记录；不得取第一票、默认平均或覆盖旧文件。

执行者/生成模型自己的判断只能放内部诊断区。VLM 辅助评分与人类观察分别列；没有实际独立人类 native review 时报告 pending/unknown，不能伪填 reviewer_id、独立性或跨模型身份。先锁评分再揭盲并组装最终 HTML；包含映射、prompt 和结果的最终总报告不能反过来充当事前盲包。

### 5.2 指标、分母与缺失

| 项目 | 定义/约束 |
|---|---|
| task_success | 按共同冻结标准同时满足 mandatory targets、A 保护、伪影/全图与交付。输出前已满足且真实 S 返回 A 可成功；内部 accepted 不直接代替离线评价 |
| effective_edit_success | 只在输出前 needs_edit 的固定分母内，真实 G、task_success 且相对 A 改善被确认；S/B/X 不计有效编辑，未知保持未知 |
| outcome_role | G 实际生成；S 有证据已满足返回 A；B 失败回退；X 无有效输出；P 未完成/待核对。未跑不是 X，失败回退 A 不是 S |
| 质量分解 | 六轴与八维目标分别报告 achieved/partial/unmet/uncertain；保护/严重损伤、文字泄漏、native 尺寸/detail 分别报告，不加权成隐藏总分 |
| 原始计数 | 每个 block/arm/domain/model：planned/attempted/generated/selected/G/S/B/X/P、baseline 组数、评分/裁决/unknown 数，均带分母；重复与 group 数分开 |
| unknown 范围 | 对固定 N 个 planned slots，k 为已确认成功、u 为未决，给 [k/N,(k+u)/N]；不把 unknown 当失败后又叫真实成功率，也不删掉它算 complete-case 主表 |
| 成本 | 所有实际提交、后台额外输出、失败、未知占用、compiler/stage/tool/token、GPU walltime/peak VRAM、金额与可核查收据；无真实报价/身份写 unknown |

当前 study.summarize 提供逐 planned run 与 true/false/unknown 分母；不得重定义其原始字段。全图六轴的独立判断、严重损伤、成本和过程审计另外保留。若共同研究 rubric 比现有表格更严格，定义扩展的独立主要终点，并同时保留原始 engine task_success，不能把自算值冒写为 engine 输出。

### 5.3 配对推断及默认判定

分析独立单位是预先冻结的 source group；存在引用复用时按第3节 analysis_group 连接分量。每组先汇总固定三次重复，组间等权；重复、双参考、多个后端都不能当新独立场景。以预登记 analysis_seed=20261102 对独立组配对重采样 10,000 次，保留组内全部方法/重复，给主差值 95% 区间。实际分析代码、随机种子、原始计数与中间 group 表都嵌入报告。

严重 A 损伤的 rubric 在输出前逐项冻结：人物身份/表情实质改变；文字语义错误；物体增删/重要几何移位；源图可见真实结构/纹理被成片抹除或幻造。单纯未达到 B 的外观目标与严重损伤分别记录。新增严重度观察属于报告扩展记录，精确绑定候选/hash/观察者/证据，不冒充现有 engine rating 的合法字段；有分歧先保留unknown并显式裁决，统计安全上界时未知按最坏情况处理。

有 unknown 时，每组先形成成功比例的下/上界；主对比的保守边界为 mean(final_lower−direct_upper)、mean(final_upper−direct_lower)。对配对 group 重采样，报告下界 bootstrap 的 2.5% 分位至上界 bootstrap 的 97.5% 分位，并报告 unknown 原因。没有唯一点估计时不填中点当成绩。样本太少/全部相同使 bootstrap 退化时明确说明，不能由零宽区间宣称普遍确定。

默认 C1 Go 同时要求：① needs_edit 主对比的保守差值下界至少 +10 个百分点，配对区间低界>0；②最终方法所有 planned source groups 的严重 A 损伤风险，一侧95% Clopper–Pearson 上界≤5%，group 中任一重复严重损伤即记损伤，未知按最坏情况进入上界；③native/detail/证据与评价可核查，报告不得在缺证下认证交付。0次损伤/60组的一侧精确上界为 `1−0.05^(1/60)`，说明重复不能虚增安全样本量。此门槛是预登记工程目标，不是通用行业标准；正式冻结前可改，输出后不能放宽。

C1 未达标写 unsupported/inconclusive，并区分点效应不足、区间太宽、安全/交付失败、证据不足。C2 作为支持性机制结果单列比例与区间，不用它替代 C1。其余多臂比较、模型/域/场景切片明确 secondary/exploratory；若做多重显著性检验，事前定义比较族和 Holm 校正，不从所有表中挑一个未校正 p 值宣布主张成立。不同方向、幅度、自然度和纹理指标不事后拼加权分数。

## 6. 运行顺序、预算和停止规则

| 阶段 | 必须完成的工作 | 最大图像槽（默认） | 出口 |
|---|---|---:|---|
| M0/B0 | 依赖/真实模型身份/原生输出/色彩/运输预检，D_dev八组六臂一次 | 48 | 数据/标准/后端/预算可冻结；否则BLOCKED_SETUP |
| M1/B1 | 固定主后端六臂D_test，三次重复 | 1080 | 全 planned rows、独立评分/unknown均入报告，不先据主表挑子集 |
| M2/B2 | 预选双参考两方法的新 B2 端点 | 72 | 每组双向跟随、A保护和限制 |
| M3/B3 | 三种独立新任务策略，各三次重复、至多三次图像 | 324 | actual-final、逐轮账本和成本比较 |
| M4/B4 | 复用已有结果做全失败与过程定位，整理单文档 | 0 | 完整报告自检、主张判定、归档 |
| 可选 | 其余三后端预选12组 / camera域12组 | 648 / 216 | 分域分模型附表，不回写主要结论 |

核心最大 **1524 图像提交槽**；加两项可选最多 **2388 槽**。这些是预算上限，不是已经生成的图片数。no-op、已知不可行或待复核可以少用，所有 planned rows 仍在。实际提交未知时保持 P/预算占用；不自动续租、换模型或偷偷重发。

GPU-hours 预估用 D_dev 实测分模型 t_edit、t_compiler、t_tools 和加载时间：`sum(actual/planned edit calls × measured seconds)/3600 + other GPU work`；API/评分成本另外核算。仅算术举例：1524 槽若每槽60秒，编辑约25.4 GPU-hours，120秒约50.8；这不是模型速度、可用显存或价格测量。native/source-native不满足时不得以这张估算表批准运行。人评预算同样按 `待评候选数 × 2观察者 × 实测每份时间` 冻结；缺少人评不能把生成模型自评替代。

停止条件：冻结GPU-hours/API金额/图像槽任一耗尽；磁盘/原生证据无法保存；后端/模型版本漂移；接口不确定提交；身份/条件审计失败；强制review未完成。保存中间账本并返回同一HTML，状态 PARTIAL/BLOCKED，未完成行保持P。技术错误修复可以用新protocol amendment继续，但旧失败、成本、条件改变和受影响区间必须保留，不补跑至通过后删除原失败。

## 7. 真实实现对应与执行入口

当前代码已经支持：固定六臂 study、single/max_generations=1 的 runnable tasks、输入/评价/baseline冻结、结果/盲评/裁决导入、含全部原始记录的单份 Markdown；独立三阶段评价和同候选/native-detail追加复核。它**不自动提供**任意消融矩阵、分组置信区间或 HTML 总报告生成。

先按 [RUNBOOK](../RUNBOOK.md) 配置真实 runtime；以 `engine/examples/reference_unified/study.example.json` 为字段依据，把所有示例图像/事实/版本替换成实际值，设置 `models:[M*]`、`repeats:3`、source_native 和真实detail门槛。source-only的brief/regions独立撰写，不能从共同B派生。模型/原生配置以实际 `--help` 与冻结生成的 RUN_COMMANDS.md 为准。

```text
python -m hre reference-study build --root runs/experiment-v1/main --spec /absolute/main-study.json
# 执行生成的 runs/experiment-v1/main/RUN_COMMANDS.md；先核对各行输入/配置与预算。
python -m hre reference-study result --root runs/experiment-v1/main --spec /absolute/RESULT.json
python -m hre reference-study blind --root runs/experiment-v1/main --out runs/experiment-v1/blind
python -m hre reference-study rate --root runs/experiment-v1/main --blind-root runs/experiment-v1/blind --packet-id packet_0001 --spec /absolute/NEUTRAL_RATING.json
python -m hre reference-study adjudicate --root runs/experiment-v1/main --spec /absolute/ADJUDICATION.json
python -m hre reference-study report --root runs/experiment-v1/main --out runs/experiment-v1/main-engine-report.md
```

build 本身不调用模型。RESULT 是对实际文件和调用记录的绑定，不认证一个虚构远端模型；不能手造 G 或人评。没有裁决需求时不创建假的 ADJUDICATION。P 的真实结果追加必须按实际 schema 写 predecessor；不是覆盖历史JSON。

B2/B3 从实际 runtime 生成的 spec 派生**新的未创建任务**，修改 case_id、A/B、policy、seed_schedule和上限，使用现有 `hre models` 创建/运行入口；必须在各自生成前冻 spec/common offline rubric/实验账本。六臂 builder 不接受自定义 F1/F2/F3 臂，不能改完 frozen task 后冒称原 study 已覆盖。B2/B3 的离线记录和所有 planned rows 放入报告扩展账本，主表 engine Markdown作为原样附录。执行者须制作/审查后处理程序或手工汇编；本次文档不宣称这些研究层统计/HTML汇编程序已经是CLI功能。

```text
python -m hre models create --case-root runs/experiment-v1/custom/CASE_ID --spec /absolute/TASK.json --config /absolute/RUNTIME.json
python -m hre models prepare --case-root runs/experiment-v1/custom/CASE_ID --through condition
python -m hre models show --case-root runs/experiment-v1/custom/CASE_ID
# 必需审计/证据通过后才运行；先确认CLI当前提示的待处理项。
python -m hre models run --case-root runs/experiment-v1/custom/CASE_ID
python -m hre models resume --case-root runs/experiment-v1/custom/CASE_ID
```

create 接收完整合法 TASK.json，不是只含policy的小片段。F1可采用 `policy={mode:feedback,max_generations:3,seed_schedule:[42,43,44],max_stage_calls:15,max_compiler_calls:3}` 作为首个repeat的字段示意；各repeat实际seed和cap在全矩阵中冻结。F2更换mode为resample，其余受控字段相同；F3使用native策略且不附新retouch合同。`models report` 产生的HTML/CSV/JSON是单case/batch软件报告，并非本计划的完整单文件实验报告，仍需收入总报告。

## 8. GPU唯一返回物：单文件报告合同

唯一提交文件：`EXPERIMENT_REPORT.html`，直接复制配套模板后填充。报告必须离线可打开；CSS/JS/图像/机器可读JSON/配置原文/原始评价和日志摘录全部内联，不依赖旁边目录、CDN或登录后才出现的图。GitHub代码页不负责渲染HTML；下载原始文件后本地浏览器阅读。模板在GitHub只是NOT_RUN格式规范，不是已完成成绩。

必须包含：冻结计划与变更；全部source/model/domain/provenance；集成tracker；各块/臂/重复的完整planned ledger；每条真实提交/未知/失败/no-op；全部评分、分歧、裁决与native-detail身份；分母、原始计数、group表/统计代码；全部方法主表及参考干预/反馈/失败分析；成本/硬件；可核查视觉证据；结论-证据映射及未完成项。现有 `main-engine-report.md` 全文嵌入附录，不只写一个GPU本地路径。

### 图像与体积

每个实际生成结果至少有内嵌预览，写明它是缩放/重编码图，不将其hash伪装为原始native SHA。代表性A/B/C全图和native1:1 crops按输出前选择规则展示；crop附原生坐标、原图尺寸、来源SHA/变换和观看条件。无对应native观察时，detail保持unknown。

原native数据若可放入运输预算，内嵌原始bytes及SHA，预览与原件分开。放不下时，报告内必须记录真实持久化evidence_uri、SHA、大小、访问核查时间和结果；它是证据保管位置，不算额外返回文档。GPU临时路径或不存在的链接不是持久证据。若原生数据无法内嵌或可靠保留，记录 `EVIDENCE_INCOMPLETE`，相关交付/训练标签/可复现主张不能认证通过；不能声称单文件包含了未携带的完整原始像素。

在D_dev实际测试一次报告回传并冻结最大字节数。首先保留完整数值/逐run数据/评分和失败，其次统一缩略预览质量和代表性面板。不能仅保留成功图片，不能截断账本、删未知、隐藏stderr或把图像换成文字“looks good”。若预算仍不足，在测试集解封前调整尚未冻结的规模、分阶段执行并由接收方最终合并；每个GPU任务仍只交回一份完整HTML。不得在结果出来后删除行来“压缩报告”。

### 回传前检查

- HTML内JSON能解析；模板占位只允许出现在明确NOT_RUN/PENDING区；实际结果使用null而非字符串伪数字。
- 主表/摘要由同一真实账本计算，planned数与冻结清单相符；所有未跑/失败/未知均能定位，重复引用不双计调用。
- 无外部执行资源或断开的本地图片路径；内嵌data URI可解码，native/preview/crop身份区分，图像发布范围符合冻结设置。
- 原始配置、实际命令/退出码、受影响版本和过程日志齐全；不嵌入密钥。
- 全文单文件可离线打开，字节数满足实测通道预算；完成真实传输后比对报告文件SHA256，校验值通过交付消息另报，不能把自引用文件hash写进同一文件后又称相同hash。
- 当前报告里的软件CI、合成协议验证与真实实验分区；没有真实输出就保持NOT_RUN，没有独立评分就不写质量通过。

## 9. 结论写法与交付完成条件

每条结论引用本报告的 block/group/run、评分/裁决及图像证据ID，标记 supported / qualified / inconclusive / unsupported / NOT_RUN。结论包括负结果、失败、未知、开销及偏离，不写“总体效果不错”替代记录。若C1不成立，按B4定位最主要失败层，下一版改动须新冻任务/再用新留出数据检验；不能用同一测试集不断调prompt后仍称留出验证。

计划完成不等于主张通过。允许最终报告为真实的PARTIAL/NEGATIVE/BLOCKED；只要完整保留已批准计划、全部事实和限制，就完成了诚实交付。只有足量真实证据及冻结标准通过时才填写质量主张 supported。执行结束的唯一报告必须足够让接收者在没有GPU目录的情况下复算数值、理解视觉证据和发现其证据边界。
