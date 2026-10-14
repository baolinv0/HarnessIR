# H08 · 25 图 NB2/Qwen 对比：当前控制策略存在负收益，能力上限尚未测定

返回：[总览](../README.md)。归档日期：2026-10-14；实际运行日期未提供。H08 是开发记录编号，不是软件发布。

## 1. 来源与实验边界

**USER_REPORTED**：本次用户提供实验摘要；本记录转录汇总与失败观察，没有取得原图、输出图、逐图指标、ROI/mask、最终请求、代码/模型 revision 和运行日志，没有重跑图像模型。与 H07 的样本交集和 lineage 未知，不能合并成 36 张独立样本，也不假定本次 precise 就是 H07 的 P2。

用户报告：Real-NoGT-200 的 Low-Light 子集 25 张（exDark 9、JarvisIR-Night 8、ACDC-Night 8），1024×1024。NB2 为云端商业 Executor，Qwen-Image-2.1 为本地 Executor，40 steps / true_cfg=4.0 / seed=0；Qwen3.8-27B 用于诊断、组合与视觉评审。框架有五阶段实现，但本轮关闭 redo，Verifier 未参与迭代决策；因此不能将本轮解释为完整闭环的性能验证。

六列包括输入和五个生成条件。simple/precise 的完整文本、NB2 direct 与 Qwen direct 的任务语义是否一致、几何及颜色后处理、各指标成功样本数、亮度定义、ROI 聚合权重均待日志核实。Qwen 单一 seed 不能估计小物件丢失的发生概率。

## 2. 用户报告的汇总值（原样保留）

| 臂 | global | sky | shadow | shadow_std | CLIPIQA ↑ | MUSIQ ↑ | TOPIQ ↑ |
|---|---:|---:|---:|---:|---:|---:|---:|
| Input LQ | 0.185 | 0.144 | 0.213 | 0.147 | 0.353 | 35.35 | 0.259 |
| NB2 direct | 0.252 | 0.207 | 0.282 | 0.167 | 0.441 | 64.50 | 0.526 |
| NB2 in-fw | 0.208 | 0.157 | 0.246 | 0.163 | 0.408 | 58.13 | 0.459 |
| Qwen2.1 simple | 0.303 | 0.243 | 0.353 | 0.192 | 0.455 | 64.45 | 0.519 |
| Qwen2.1 precise | 0.334 | 0.250 | 0.402 | 0.199 | 0.353 | 54.79 | 0.399 |
| Qwen2.1 in-fw | 0.191 | 0.143 | 0.225 | 0.170 | 0.425 | 54.66 | 0.427 |

机器可读副本：[CSV](../evidence/lowlight_25_arms_reported.csv)、[JSON](../evidence/lowlight_25_arms_reported.json)。这些是转录资产，不是原始评测结果。

由已四舍五入组均值相减：

| 比较（前者−后者） | global | shadow | CLIPIQA | MUSIQ | TOPIQ |
|---|---:|---:|---:|---:|---:|
| NB2 in-fw − direct | −0.044 | −0.036 | −0.033 | −6.37 | −0.067 |
| Qwen in-fw − simple | −0.112 | −0.128 | −0.030 | −9.79 | −0.092 |
| Qwen precise − simple | +0.031 | +0.049 | −0.102 | −9.66 | −0.120 |

NB2/Qwen 框架的全图组均值相对下降分别约 17.46%/36.96%，不等于逐图相对变化均值；NR-IQA 下降没有相同的放大倍数，不能把亮度交互直接称为质量交互。没有逐图数据，不能计算配对置信区间、显著性、等效性或稳定获胜比例。

## 3. 视觉证据及失败项（用户报告，未独立看图）

用户描述 NB2 框架的衣物纤维、教堂细节更保真；Qwen direct 有天空白昼化、偏色、塑料感，night_0042 的眼镜消失并出现新增街道。Fig.1/Fig.3 未附图，不据此作全样本保真排名。NR-IQA 不能验证眼镜身份或背景内容真实性；shadow_std 不能证明纹理恢复。

用户用 Qwen3.8-27B 评审四张代表图，两张成功解析（50%）：

- night_0028：NB2 direct > NB2 in-fw > Qwen precise > Qwen simple > Qwen in-fw > Input。
- night_0049：NB2 in-fw > NB2 direct > Qwen simple > Qwen in-fw > Qwen precise > Input。

以上只支持两个有效样本的报告排序。未解析两张的原始回答、失败原因和缺失偏差待补，不能静默删除。评审与 Controller 使用同一 VLM，需隐藏模型/臂名、随机换位、使用独立人工复核；这不是独立人类盲评。用户报告 stage3 输出预算 4096→16384 后解决 14 张失败，尚无日志证明失败原因和重试 lineage，不视为性能验证。

## 4. 结论修正

| 原判断 | 当前证据允许的表述 |
|---|---|
| 框架对 NB2 有益、对 Qwen 有害 | 两种 Executor 的框架臂均降低三项 NR-IQA 均值；NB2 的保真改善仍需单独盲评验证 |
| 强模型任何臂始终胜过弱模型 | 不成立：Qwen simple CLIPIQA 0.455 > NB2 direct 0.441；MUSIQ 64.45 与 64.50 数值接近；Qwen simple 三项都高于 NB2 in-fw，Qwen in-fw CLIPIQA 也高于 NB2 in-fw |
| Qwen 本来提亮能力有限 | 汇总不支持此说：Qwen simple/precise 都比 NB2 更亮；待研究的是提亮与保真的联合可控性 |
| 执行器是瓶颈，框架没有问题 | 未建立：Executor、目标表达、采样与控制策略可能交互，未隔离贡献；框架仍可能有 Executor 适配不足 |
| Qwen 已达能力天花板，Prompt 无法避免小物件丢失 | 未建立：有限 Prompt、单配置、单 seed 不定义模型可达上界，也不能估计随机丢失概率 |
| precise 的 CLIPIQA 下降证明白昼化是原因 | 亮度与评分同向/反向共变是事实；白昼化、过平滑、内容变化及指标偏好未单独归因 |
| 多轮 refinement 可以补救 | 待实验；可能累积重绘/漂移，必须有同调用预算的重复采样对照 |

**当前工作结论：在用户报告的 25 张样本和当前实现/配置下，框架相对简单请求未显示三项 NR-IQA 均值收益。Qwen 在可见性、夜景照明关系和内容保真之间的控制存在失败观察；尚不能分辨能力限制、采样配置和控制策略各自的贡献。** 这是失败诊断的起点，不是对框架正确性或 Executor 天花板的最终裁决。

## 5. 官方接口核查（2026-10-14）

### 配置先验收

当前 [Diffusers Qwen-Image 2.1 文档](https://huggingface.co/docs/diffusers/main/en/api/pipelines/qwenimage21) 推荐 40 步、无 guidance；`QwenImage21Pipeline` 的 `true_cfg_scale` 默认 1.0，>1 且提供 `negative_prompt` 或负向 embeddings 时才启用 CFG。当前 [源码](https://github.com/huggingface/diffusers/blob/main/src/diffusers/pipelines/qwenimage21/pipeline_qwenimage21.py) 也检查这一条件。

[2511 官方模型卡](https://huggingface.co/Qwen/Qwen-Image-Edit-2511) 示例使用 `QwenImageEditPlusPipeline`、true_cfg_scale=4.0、negative_prompt=" "、40 步和 guidance_scale=1.0。不能把这一组直接假定为 2.1 的推荐设置。

本地 true_cfg=4.0 可能是合理实验参数、被包装器转换、实际未启用或有其他实现，**不能仅凭摘要判定配错或模型身份错误**。下一轮核验 pipeline 类、checkpoint/revision、Diffusers commit、negative prompt、实际 CFG 分支、调度器及步数。先做官方默认与现有配置的配对小试，不把修改配置后的结果追溯替换 H08。

### 区域提示与硬约束分开

[Qwen 官方 README](https://github.com/QwenLM/Qwen-Image-2.1) 明确支持圆圈、涂画及独立 mask 来指定局部编辑；这支持测试视觉区域提示。当前上述 Diffusers 调用签名未提供 `mask_image`、`bbox`、`lift_strength` 或逐区域像素增益参数。把区域 JSON 写出来本身不会建立 Executor 的空间执行能力；文本“+30%”也不是已标定曝光算子。

若需要确定的天空保持/区域增益，可另外测试掩码加权调色、受控合成及边缘融合；外部限制只能保证所实现的区域属性，不能保证编辑区内内容真实。attention injection 是待开发的推理算法，不记作现成接口或 Prompt 修改。多种路径单独命名与验收，不能混入同一臂。

## 6. 下一轮优先级（PROPOSED，未执行）

1. **证据与配置**：补全25图逐臂结果和2份LVLM失败记录；先核验 CFG 是否生效，再对比当前/官方默认配置×simple/原Compose。可用分层6张开发图、3个配对seed作起始小试（最多72次Qwen生成；若配置实际等价先避免重复）。这只是开发预算，不声称统计充分。保留所有旧结果，核验全组同样预处理/后处理。
2. **D + 低成本 E**：固定上述配置与诊断，分开验证移除冲突条款、压缩重复内容、正向区域目标；保存逐句diff，不删除用户硬约束。删句同时缩短文本，应与保留含义的压缩对照解释。加一个确定性 tone/gain 基线，再按资源选一个有官方代码/权重的专用低光方法；SuLowSN 等名称和实现需先核实。候选效果由可见性、夜感、内容保真共同评价，不把 shadow mean 当优化目标。
3. **B 等预算闭环**：若单次路径可靠，最多3次生成，并和同一 Executor 的3次独立采样+同一选择器比较。分别报告候选生成收益与选择收益、总耗时/成本、失败/接受/回退率。首轮可从原始LQ按更新Prompt重生成以限制累积重绘，若以前一输出作输入则单列实验；保留原图与历史最佳候选并支持停止，不能默认最后一轮最好。
4. **A 先验收局部性**：先测区域文本、视觉mask提示的遵循度和区域外改动，再决定是否做外部合成或自定义注意力控制。分割类别不等于曝光需求；人、建筑或天空都可能本已正确曝光，彩色夜空也不应一律压黑。根据实图证据确定编辑区域。
5. **C/F 后置**：25张先作为开发/失败集，不同时用作训练与泛化测试。NB2 direct三项NR-IQA较高不意味着最适合当教师；先按内容保真与目标风格筛选/拒收teacher候选，补独立训练与测试数据，再作LoRA可行性试验。rank8–16不保证防过拟合，CLIPIQA≥.48也不是质量充分条件。F需另定义参考风格和可训练标签，不能从本轮低光迁移成TM伪GT有效性结论。

H07 的官方 PE P3/P4 尚未报告执行。若继续测试，保持同一目标/Executor/配置，P4只增加冻结诊断证据；不预设PE能纠正过强提亮。该对照可作为D之后的可选分支，不能把所有新功能一起加入。

**评价与决策**：先对现有25张完成隐藏臂名的人工配对复核，分别评价目标可见性、夜景关系、高光、纹理/小物件/文字及新增内容。报告逐图配对差异、置信区间、失败率和三个来源的分组结果；seed是图内重复。NR-IQA只作辅助，shadow/sky统计只作解释；GT缺失不妨碍原图内容保持检查。不能为所有照片设置shadow≥.28、sky≤.18等统一“真值”。配置/Prompt在开发集确定后，用独立未参与调参样本验收；样本扩容依据方差与目标效应，不机械以100张当充分条件。
## 7. 下一轮第一步已执行：CFG × D 消融 × 确定性基线（2026-10-14，生产端IMAGE_VALIDATED报告）

生产端报告配置核查与6图×5臂×3seed×2配置实测已完成，详见[配置核查](../evidence/qwen21_config_audit_20261014.md)与[cfg×D消融](../evidence/cfg_d_ablation_20261014.md)。本次只读报告，未独立取得原始图像/分数/运行脚本；报告中的生产端位置不等于当前仓库可访问资产。要点：

- **CFG 分支查明**：本地 pipeline=QwenImage21Pipeline、diffusers 0.41.0、步数 40、调度器 FlowMatchEuler 均与官方一致；neg=" "+true_cfg=4.0 使 `do_true_cfg=True`，CFG 确实启用，非配错但非官方默认（1.0）。
- **CFG是受控实验因素**：cfg4.0的NR-IQA均值较高，simple也更亮。H08绑定cfg4，不与默认混报；此轮未给统计区间/检验，不能称为已证统计显著的混杂偏差。
- **框架负收益复现**：compose−simple 在 cfg1.0 −0.031、cfg4.0 −0.030 CLIPIQA（后者与 H08 的 −0.030 一致），非单一配置造成。
- **机制线索**：drop_guards较compose略升但未恢复到simple；cfg4下compact/region_target三指标组均值高于simple，cfg1只有部分指标领先。支持继续检验压缩重写，不确定纯长度主因；region_target相对compact的MUSIQ还下降，区域目标独立贡献待分离。
- **确定性 tone/gain 基线**把图拉亮（global 0.275）但 CLIPIQA 反降至 0.186：更亮≠更高分，该基线只作亮度参照。

限制：6 图开发集非泛化测试；region_target 的区域目标独立贡献未分离；无 redo/闭环；保真未独立盲评；NB2 未重跑。

H08-n1报告审查：`claim_supported=partial`、`review_independence=same-family`、`acceptance_status=provisional`、`integrity_status=unavailable`。新上下文审查只判断报告与主张关系，不独立验证生产执行。I-17生产侧报告已补齐，I-01开放；H08-n1与H08按报告精度均为−0.030不能证明独立复制。旧“显著混杂/纯长度主因/两配置均反超”表述修正，生产端所有组均值原样保留。先补资产与lineage，独立样本验收冻结单次候选，再做等预算B。

## 8. 审查状态与关联

总体原主张“弱Executor是瓶颈、框架没问题、强模型全面胜出”的新上下文审查：`claim_supported=no`；C1策略交互=partial、C2执行器唯一瓶颈/全面胜出=no、C3数值与两个有效排序=partial、C4能力天花板=no、C5保守约束/截断归因=partial。以上较窄观察可保留；不把no改写为全部实验无效。

`review_independence=same-family`、`acceptance_status=provisional`、`integrity_status=unavailable`。审查者为独立新上下文的GPT-6-Astra，审查的是材料与主张关系，没有独立看图或重跑实验。对总体断言缺证据的判断置信度高，对真实保真排序、具体机制和能力上限置信度低。完整请求/答复保留在本地审查轨迹，不上传含宿主内部信息的记录。原图完整性审计未执行。

关联 I-01/I-02/I-05/I-08/I-10/I-13–I-15，新增 I-16（过度归因）、I-17（配置）、I-18（评审覆盖）、I-19（局部接口）、I-20（闭环预算/漂移）、I-21（教师/数据隔离）。本次只维护文档，不部署PE、改造推理、训练或运行新实验。
