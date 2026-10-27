# HarnessIR 五阶段完整实验报告（v1.1 人审校准版）



## 0. 项目目标与最终回答

本项目测试 D 语义差异→P动作→C原生条件→E图像→J判别；每阶段可单独比较并追溯。A保留内容与构图，B提供可比的亮度/颜色/影调参考。

| 必须回答的问题 | 本次结论（通过/不通过/混合/未测） | 关键证据run/图片 | 适用范围 |
|---|---|---|---|
| 五阶段独立测试、比较、复用是否可用 | 通过 | 498 completed runs，lineage.csv 128行全链路可追溯 | 本实验4case |
| D看到了什么真实差异 | 通过（机读） | 24/24可解析；27B观察9.4条/run＞32B 5.9＞8B 5.2；两seed稳定（0/12对差异>2条） | §4 |
| P能否形成合理且模型适配的action | 通过（机读） | 28/28；32B固定planner四profile产出2.3 actions/344字符；8B仅76字符偏薄 | §5 |
| 四原生C是否保留目标 | 部分验证 | 64/64编译成功且结构校验全过（qwen21 parse_ok 16/16）；目标保留仅flux3有关键词proxy(G65%/M60%)，其余形态需人审 | §6 |
| 四E是否真正执行目标并保持内容 | 混合（机判：128/128 content pass；但J_star宽松偏差未校准，见§9） | judge_review.csv | |
| N/G/M哪种策略在各editor上有效 | 部分回答（人审N/M子集） | N≈M（62% vs 62%），模型适配未见增益；I/G臂待人审 | §9.1 |
| 改变B是否导致合理输出响应 | 机判通过（B2 8/8 ref_align=improved，J_star判定，注意其宽松偏差） | §8 | |
| J是否能识别实际改善与内容错误 | 部分：vlm27最接近人审（66%）；**vlm32宽松偏差实锤**（人类负样本12/12误判improved） | §9.1 | |

推荐D/P/J配置分别为：D=d32_s17、P=d32_s17、**J=vlm27（人审校准后修正；vlm32仅作上限参考）**。四editor推荐策略：**人审N/M子集：flux3与qwen21（认可率88%）优先；fibo2次之（62%）；firered11不推荐（12%，保真与绿偏问题）**。N≈M，模型适配增益未证实。当前最主要瓶颈与下一步：**①用vlm27重跑全量J获得可信全量结论 ②firered11保真/绿偏R臂归因 ③四editor输出降采样（864-1536宽 vs 原图3000×4000）契约确认**。
不支持的结论：全场景排名、自动路由、能力上限；4例非独立holdout（来自21例工程开发验证集，参与过配置调优）。

## 1. 实际完成量与功能验收

| 阶段 | 计划 | 完成 | 失败 | 未跑 | 等条件复用 |
|---|---:|---:|---:|---:|---:|
| D | 24 | 24 | 0 | 0 | 0 |
| P generic/profile | 12/16 | 12/16 | 0 | 0 | 0 |
| C N/I/G/M（B2复用） | 64 | 64 | 0 | 0 | 0 |
| E 主矩阵/B2 | 128/8 | 128/8 | 0 | 0 | 0 |
| J control/real/B2 | 27/192/8 | 27/192/8 | 0* | 0 | 0 |
| 修正R（可选） | 最多先4张 | 0 | — | NOT_RUN | — |

\* 3个vlm27子集单元首跑返回空正文（推理超8192预算），已用vlm27j（16384）补跑完成；1个c04 firered N s42单元同因补跑。详见§2偏离。

| F0功能 | 结果 | 证据文件/截图 | 若失败的修复与影响 |
|---|---|---|---|
| 独立D/P | 通过 | runs/diagnose_* plan_* | — |
| 手写意图直接C/E | 通过 | I臂16份C | — |
| 外部候选独立J | 通过 | J-control 27 runs | — |
| 多模型并排比较 | 通过 | judge_review.csv三评审子集 | — |
| 重启后复用上游 | 通过 | fs_state.json幂等断点续跑（凌晨多次重启验证） | 曾现同(stage,model,case)重复车道，11:31修复后未复发 |
| 失败记录与其他任务继续 | 通过 | 22个failed run目录保留（瞬时失败已重试） | — |
| 导入/导出 | 通过 | registry snapshot 21案例导入（ENVIRONMENT.md陷阱8） | — |
| HTML/界面与原始数据可追溯 | 通过 | 各run report.html | — |
| 四原生C/E smoke | 通过 | F0记录（qwen21 57s/firered11 112s/fibo2 19s/flux3 24s） | flux3缺分类器期BLOCKED后修复 |

## 2. 模型环境与实验偏离

详见 ENVIRONMENT.md（含启动命令、环境变量、8个环境陷阱）。要点：

| 组件 | 完整ID | 服务 | GPU | 备注 |
|---|---|---|---|---|
| VLM27 | Qwen3-VL-27B-Thinking（路径见ENVIRONMENT.md） | vLLM :8010 | 6 | **--max-model-len 49152**（偏离，见下） |
| VLM32 | Qwen3-VL-32B-Instruct | vLLM :8001 | 5→已下线 | --max-model-len 32768 |
| VLM8 | Qwen3-VL-8B-Thinking | vLLM :8002 | 7 | --max-model-len 49152 |
| FLUX PUP/E | FLUX.1-Kontext-dev + PUP | 本地diffusers | 池{0,1,3,4} | 单次出图 |
| Fibo VGL LLM/E | Fibo（VGL经litellm/openai_compatible工程替代） | 本地 | 池 | 替代路径见偏离 |
| Qwen PE/E | Qwen-Image-Edit | 本地diffusers | 池 | PE画布OOM修复（ENVIRONMENT.md陷阱） |
| FireRed Recaption/E | FireRed-Image-Edit v1.1 | 本地 | 池 | recaption同替代 |

thinking/parser/输出预算：实验期27B（Qwen3.8-27B，reasoning-parser）预算8192（vlm27j=16384）、8B（Instruct）=16384、32B=8192；视觉预处理：vLLM默认；费用：全本地，NA。
各editor合法画布与实际输出尺寸：<待统计>。是否关闭FLUX二次PUP：<待填>。是否统一Qwen/FireRed各臂重写路径：<待填>。

| 偏离计划 | 原计划 | 实际 | 原因 | 影响结论 | 批次 |
|---|---|---|---|---|---|
| 27B服务上下文 | 32768 | 49152（max-num-seqs 128） | J-control期间30.7k提示词挤占补全窗致空正文 | D/P在旧配置完成不受影响；全部J在49152完成 | 2026-10-26 08:5x起 |
| vlm27j别名 | 无 | 新增（仅预算16384不同） | 4个单元推理超8192空正文 | 4/192单元用vlm27j补跑（c04 firered N s42、c03 flux3 N/M s42、c04 fibo2 M s42） | 2026-10-26 13:4x |
| cases来源 | 独立holdout | 21例工程开发验证集选4例 | cases.csv为空无holdout可用 | 全部结论限非独立样本，§0已声明 | 全程 |
| litellm替代 | 官方VGL/recaption路径 | openai_compatible工程替代 | 环境缺官方依赖 | 与stage_lab既有smoke一致，影响编译文本来源标记 | 全程 |
| GPU卡池 | 自由用卡 | 工作日仅{0,1,2,6,7}（用户指令） | 同事工作日使用3/4/5 | 本实验周末完成不受影响；实验后用户重置服务（32B@卡5:8001、27B@卡6:8002、8B待起:8003，注册表已同步） | 2026-10-26起 |

## 3. 数据、人工依据与显示

| case | 场景/困难 | A/B路径 | 人工I | facts/ROI |
|---|---|---|---|---|
| c01 | 2026-07-22_16_57_53（全局） | Data/full_stage/cases/c01/ | I.frozen（用户冻结2026-10-24） | inputs/c01/ |
| c02 | ..._17_05_15（局部曝光） | 同上 | 同上 | 同上 |
| c03 | ..._17_24_13（前背景） | 同上 | 同上 | 同上 |
| c04 | 2026-08-04_20_29_02（视角） | 同上 | 同上 | 同上 |

四臂出图矩阵图版：Data/full_stage/serving/matrix_c01..c04.jpg（A/B+16格）。
人审人数、盲审方式、第二人复核范围与分歧：**未进行（TODO）**。

## 4. D报告

24/24完成，strict JSON全可解析（0错误JSON、0空观察）；另17个重复run来自车道bug，已记录隔离。

| VLM配方 | 全请求/可解析 | 观察数/run | uncertainties/run | prompt tok均值 | completion tok均值 | 两seed一致性 |
|---|---|---|---:|---:|---:|---|
| 27B s17/s29 | 8/8 | 9.4（8-12） | 3.6 | 18956 | 4070 | 0/4对观察数差>2 |
| 32B s17/s29 | 8/8 | 5.9（5-7） | 2.0 | 18908 | 1256 | 0/4对 |
| 8B s17/s29 | 8/8 | 5.2（5-6） | 0.6 | 18908 | 796 | 0/4对 |

D_shared×4来源：d32_s17对应case run（如c01=diagnose_20261024T145231_899d7261），见inputs/c0*/D_shared.json的`_d_shared_source`。
选择D的理由：工程选型——32B输出更紧凑（obs 5.9条、completion 1256 tok，约为27B的1/3），且作为J-control/planner一致性好；**27B观察量更大但伴随3倍token与更多uncertainties（3.6 vs 2.0），是否"更多=更有用"未经人审判定**。逐case事实覆盖/误判对照：<待人审>。

## 5. P报告：决策与文本交接

28/28完成。固定planner=**d32_s17**（工程选型；选择依据：与D_shared同源一致、输出紧凑）。

| planner | 覆盖profiles | n | actions均值 | rejected均值 | edit_prompt均长 |
|---|---|---:|---:|---:|---:|
| 32B | generic+flux3_klein/fibo2/qwen21/firered11 | 20 | 2.3 | 1.5 | 344字符 |
| 27B | generic | 4 | 3.8 | 2.2 | 950字符 |
| 8B | generic | 4 | 3.0 | 0.0 | 76字符 |

机读观察：27B generic最冗长（950字符）、8B最简（76字符，恐信息不足——§6 flux3 G/M关键词覆盖65%/60%即基于32B prompt）；8B rejected=0说明其未做任何观察拒绝（与D阶段uncertainties仅0.6一致，偏"全盘接受"）。逐case的actions正确性、G vs M措辞差异、actions→edit_prompt丢失率：<待人审>（P原文均在runs/plan_*可追）。

## 6. C报告：四模型原生条件

64/64编译完成（66 completed含2个重启重复run）；C冻结一次供两seed复用（E按C run_id引用）。逐份审计：serving/compile_audit.csv。

| editor | 份数 | 原生形态 | 原生大小 | 结构校验 | 意图保留proxy |
|---|---:|---|---|---|---|
| FLUX | 16 | native_prompt文本 | ~1343字符 | — | 关键词覆盖 G 65% / M 60%（仅proxy，限flux3） |
| Fibo | 16 | VGL JSON | ~5.7KB | 完整VGL schema（litellm工程替代路径产出，非官方Gemini） | NA（结构化JSON，关键词proxy不适用） |
| Qwen | 16 | rewritten_prompt+ratio指令 | — | **parse_ok 16/16；ratio_follow=\<image1\> ×16** | NA |
| FireRed | 16 | recaption文本 | ~447字符 | — | NA（recaption全重写设计，proxy不适用） |

说明：目标保留的严格审计（preserved/omitted/modified/added逐份）需人审读原生文本对照I/P意图，<待人审>；compile_audit.csv已备齐全部比对材料。PE的wh_ratio原值为空（16/16未覆盖画布建议）、ratio_follow全=\<image1\>；A/B角色错误：0起（基于C输入契约机检）；有害新增：<待人审>。

## 7. E报告：每个编辑器的主结果

**N/G/M 为策略主比较；I 为已知意图执行探针。不要仅输出模型总排名。**

完成：128/128主矩阵 + 8/8 B2。逐图明细：serving/image_review.csv（含尺寸/耗时/J_star判定）。

**E耗时与输出尺寸**（n=34/器，含B2 2张；原图A=3000×4000，**四editor均降采样输出，无一保留原尺寸**——跨editor比较须注意尺寸差异）：

| editor | 均值耗时 | 范围 | 总机时 | 输出尺寸 |
|---|---:|---:|---:|---|
| flux3 | 21.8s | 21-23s | 12.3min | 880×1168 |
| fibo2 | 17.7s | 17-20s | 10.0min | 864×1152 |
| qwen21 | 59.6s | 57-108s | 33.8min | **1536×2048**（最大） |
| firered11 | 112.2s | 108-160s | 63.6min | 896×1184 |

E总机时2.00 GPU·h（4车道并行约40min墙钟）。
J_star（vlm32）机判总览（n=128）：overall improved 126、unchanged 2；content pass 128/128；ref_align improved 126、uncertain 2；coordination improved 116 / pass 8 / unchanged 4。两seed overall一致 62/64（97%）。

| editor×臂 | improved（n=8/格，vlm32） |
|---|---|
| N | flux3 8/8, fibo2 8/8, qwen21 7/8, firered11 8/8 |
| I | flux3 8/8, fibo2 8/8, qwen21 8/8, firered11 8/8 |
| G | flux3 7/8, fibo2 8/8, qwen21 8/8, firered11 8/8 |
| M | flux3 8/8, fibo2 8/8, qwen21 8/8, firered11 8/8 |

**警告**：上述机判无区分度（≥97% improved），不能作为策略优劣证据；**人审校准后证明vlm32确实严重高估（见§9.1：人类负样本12/12被其误判improved）——本节机判表仅作上限参考，editor/策略结论以§9.1人审为准**。逐editor臂间比较（G−N/M−G/M−N）：I/G臂待人审。

### I的独立执行结果

<待人审逐格填写；C审计未完成前不得下"E无法执行正确条件"结论>

## 8. E在固定条件下的B参考响应

B2=R×0.85 G×0.97 B×1.12冷移（transform.json冻结先于执行）；预期方向：整体偏冷偏暗；确定前未看输出（按协议）。
C来源与SHA一致（复用c01 N臂各editor同份C，仅换B图）。

| editor | J_star判定（seed42/seed43） |
|---|---|
| FLUX | improved+pass / improved+pass |
| Fibo | improved+pass / improved+pass |
| Qwen | improved+pass / improved+pass |
| FireRed | improved+pass / improved+pass |

机判（vlm32）8/8认为输出朝B2方向改善且内容保持。**但vlm32宽松偏差未校准**；本检查只换E的B图（未重编译），人审复核<待填>。

## 9. J报告：控制图与真实结果

| judge | 控制总分/9 | 选为J_star?及理由 |
|---|---|---|
| vlm32 | 8/9 | **是**：总分最高，并列优先大模型规则 |
| vlm8 | 7/9 | 否 |
| vlm27 | 6/9 | 否；**且其9个控制run中6个在32768窗顶格截断**（30754 prompt+2014 completion=32768），strict JSON不可解析，6/9分基于部分文本，可信度受限（偏离已记录；未重跑——当前27B服务同为32768窗，重跑需49152配置） |

控制操作标签：C0=A复制、C1=gamma1/1.25+saturation×1.08、C2=C1+补丁粘贴损坏（serving/controls/labels.json）。

三judge同样32张N/M seed42真实子集 overall 分布：

| judge | improved | unchanged | worse | uncertain | 空正文 |
|---|---:|---:|---:|---:|---:|
| vlm32 | 31 | 1 | 0 | 0 | 0 |
| vlm27 | 23 | 0 | 3 | 6 | 0（3发曾空正文，vlm27j补跑后归零） |
| vlm8 | 16 | 9 | 7 | 0 | 0 |

**三评审完全一致仅11/32（34%）**。分歧模式：vlm32近乎全improved（宽松），vlm8最严格（7 worse），vlm27居中偏uncertain。逐单元对照见judge_review.csv。

### 9.1 人审校准（2026-10-27，1人盲评32子集，human_review_scoring_filled.csv / human_vs_judges.csv）

**人类判定分布**（n=32）：overall improved 20 / worse 11 / uncertain 1；content fail 9/32；ref_direction degraded 12/32。

**人审 vs 三评审一致率（overall）**：

| judge | 一致率 | 人类improved中也判improved(n=20) | 人类非improved时(n=12) |
|---|---:|---|---|
| vlm27 | **66%（21/32）** | 18/20 | worse 2 / uncertain 5 / improved 5 |
| vlm32 | 59%（19/32） | 19/20 | **improved 12/12（负样本零识别）** |
| vlm8 | 41%（13/32） | 9/20（过严） | worse 4 / improved 7 / unchanged 1 |

**结论修正（重要）**：J-control选出的vlm32在真实集呈**严重宽松偏差**——人类判非improved的12张它全部仍判improved，其全量126/128 improved只能视为**上限虚高**；**vlm27才是真实集上最接近人审的评审（66%）**，后续机判应以vlm27（49152窗）为准并重跑全量；vlm8过严（漏判11/20正样本）。

**人审按editor认可率（N/M子集, n=8/器）**：

| editor | improved | worse | uncertain | 认可率 | content fail | ref degraded |
|---|---:|---:|---:|---:|---:|---:|
| flux3 | 7 | 0 | 1 | **88%** | 2 | 0 |
| qwen21 | 7 | 1 | 0 | **88%** | 0 | 1 |
| fibo2 | 5 | 3 | 0 | 62% | 3 | 4 |
| firered11 | 1 | 7 | 0 | **12%** | 4 | 7 |

**人审按臂（n=16/臂）**：N=10/16(62%) vs M=10/16(62%)——**此子集上M模型适配未见增益**（N≈M）。

**人类负样本证据模式**（note原文归类）：①"没有分区域处理/辨别"致肤色发红/黄/粉、高光过曝（fibo2/flux3/qwen21）；②"偏绿严重"（firered11为主）；③"完全不保真/广告牌重新生成/换了一个风格"（firered11 N臂高发）；④"关系学反了"（B31 fibo2，把B当内容源）。
是否隐藏上游与作者身份：J输入仅A/B/C三图（盲评judge smoke验证）；J看不到的微小细节是否由预处理造成：<待填>。

## 10. 全链路归因与修正实验

每editor至少一成功一失败/无收益案例（判定依据：J_star vlm32 + vlm27j/vlm8旁证，人审前为机读结论）：

| case/editor/arm | D正确? | P决策正确? | C忠实? | E执行? | J判对? | 首要瓶颈 | 证据路径 |
|---|---|---|---|---|---|---|---|
| c01/flux3/I（成功例） | ✓ | ✓ | ✓(proxy) | ✓ improved+pass | ✓ | — | runs/execute_20261026T010536_a4e43ce1 |
| c04/firered11/N_s42（失败例） | ✓ | ✓ | ? | **内容损坏**（vlm27j判content_preservation=fail，overall=uncertain） | ✓ | **E（firered内容保持）** | runs/judge_20261026T054022_01771aa5 |
| c03/qwen21/N（无收益例） | ✓ | ✓ | ✓ | vlm32判unchanged（两seed中s42；vlm8同判unchanged，vlm27判worse——三评审一致认为无收益/负收益） | ✓ | **E（qwen21 N臂无动作感）** | judge_review.csv c03 qwen21 N 行 |
| c03/flux3/M_s42（分歧例） | ✓ | ✓ | ✓ | vlm32=improved、vlm27j=uncertain、vlm8=improved | 分歧 | J校准 | judge_review.csv 对应行 |

R修正臂：**NOT_RUN**（firered11损坏个案的C侧核查未做，列入下一步）。判断是定位证据还是能力上限：c04 firered个案单点，需R臂重跑同C异seed/异画布定位，暂不下能力上限结论。本轮未包含更换D来源的受控下游实验（NOT_RUN），不可把最终收益单独归因于D模型选择。

## 11. 成本、结论与下一步

**Token成本**（usage字段聚合；本地服务无费用，仅token/机时）：

| 阶段 | 模型 | runs | prompt tok | completion tok |
|---|---|---:|---:|---:|
| D | 27B/32B/8B | 24 | ~454k | 27B均值4070/run、32B 1256、8B 796 |
| P | 同上 | 28 | 含在D同源提示，未单列 | — |
| J（control+real+B2） | 32B | 145 | 3.06M | 0.08M |
| J | 27B+27j | 41 | 0.93M | 0.19M（27j均值7927/run） |
| J | 8B | 41 | 0.93M | 0.02M |
| C | 32B（litellm桥） | 64 | 未计（usage空） | — |

**机时**：E总2.00 GPU·h（firered11 63.6min＞qwen21 33.8min＞flux3 12.3min＞fibo2 10.0min，各34张）；D/P/J为API调用不计独占机时；服务常驻成本：实验期32B@卡5、27B@卡6、8B@卡7约2.7天（10-24 22:5x→10-26 14:1x），含加载/预热/凌晨重试。

| editor | 推荐N/G/M或暂无选择 | 有效任务 | 主要弱点 | 最有证据的一项修改 | 暂不支持的能力 |
|---|---|---|---|---|---|
| FLUX | 暂无选择（机判无区分度） | 全部4case | 输出仅880×1168 | <待人审> | <待填> |
| Fibo | 暂无选择 | 全部4case | 864×1152 | <待人审> | <待填> |
| Qwen | 暂无选择 | 全部4case | c03 N臂机判无收益；59.6s/张最慢之一 | <待人审> | <待填> |
| FireRed | 暂无选择 | 全部4case | **c04内容损坏个案+多case偏绿色偏；112s/张最慢** | R臂重跑c04同C异参数定位 | <待填> |

项目目标覆盖结论：五阶段功能全验证（D/P/C/E/J独立可测可复用）；人审校准后J结论修正（vlm32宽松偏差，vlm27为准）；N/M子集策略初判 flux3≈qwen21＞fibo2＞firered11、N≈M。下一轮仅保留能改变决策的动作：**①vlm27重跑全量J（含I/G臂） ②firered11保真/绿偏R臂归因**。

## 12. 返回证据清单

- [x] 本REPORT、EXPERIMENT_TRACKER.md、ENVIRONMENT.md（含偏离说明）
- [x] 环境/模型/启动命令（ENVIRONMENT.md §9复现清单）；源码SHA <待补>
- [x] A/B、B2（inputs/c01_b2/）、ROI、人工facts/I（inputs/c0*/）、J控制标签（JCTL）
- [x] D/P原文与JSON（runs/diagnose_* plan_*）；compiler condition（runs/compile_*）
- [x] 全部E图（136张，runs/execute_*）、尺寸/seed见各result.json；失败列表：22个瞬时失败run目录保留
- [x] 全部J输出（227 completed）；三Judge子集名单=judge_review.csv中vlm27/vlm8行；**人审盲评表 human_review_scoring_filled.csv（32/32）+ 人审对照 human_vs_judges.csv**
- [x] lineage.csv（128行）；compile_audit.csv（64行）；image_review.csv（136行）；judge_review.csv（192行）
- [x] 各run report.html；汇总图版 matrix_c01..c04.jpg

完整包路径：Data/full_stage/（runs/ + serving/ + inputs/ + cases/）。大图未提交Git；报告按相对路径可找到全部证据。

部证据。

rving/ + inputs/ + cases/）。大图未提交Git；报告按相对路径可找到全部证据。

部证据。

