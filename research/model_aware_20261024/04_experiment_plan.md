# 4. Hypothesis & Experiment Matrix / Experiment Plan

**研究状态：预注册候选协议，未运行质量实验。** 只研究原始单图复原；无参考图、训练、微调或分辨率扩展。首要主张最多两个：C1=在受控条件下确有模型×策略交互；C2=少量必要Stage修改在保真和预算约束下泛化。H1–H5均服务这两项。

## 先排除一个更大的混杂：VLM也换了

用户本地同时把Executor换成Qwen、规划VLM换成Qwen-27B，不能将结果差全归给Executor。必须先固定一个确切的VLM checkpoint/模板/采样/JSON parser，跨NB2与Qwen使用。另在小pilot做2×2：{官方VLM, 本地VLM}×{NB2,Qwen}，冻结工具及任务。Qwen-27B不是完整模型ID，不能凭参数量推断型号。若无法运行官方VLM，限制结论为“固定本地VLM条件下的Executor比较”。规划VLM的输出seed也单独记录。

## 五项假设

| 假设 | 当前支持/替代解释 | 可证伪结果 | 最小可信干预与控制 | 继续/停止 |
|---|---|---|---|---|
| H1 同Harness收益依模型不同 | 论文对两闭源Executor有作者报告；Qwen旧表只有报告值。替代：VLM、原生参数、后处理、任务不同 | E1−E0跨模型差的CI落入预注册等效区，或方向/大小不稳定 | 同scene/意图/规划VLM；每模型E0/E1；固定输入和budget；检验差中差，而非“一个显著另一个不显著” | 交互超最小有用差且无保真退步再谈model-aware；否则优先统一 |
| H2 专属Prompt超等信息统一Prompt | 官方表达/模板差异只提供动机。替代：字数、遗漏约束、编译器额外调用 | 强共享prompt或长度匹配对照追平；交叉policy无模型偏好 | 同一frozen intent；shared、NB-style、Qwen-style均给两模型；各长度档比较；3次重复；composer尝试/输出tokens冻结 | 只有专属交互和实际质量收益均成立才收专属S3 |
| H3 Evidence方式带来额外收益 | 原论文bundle结果；未逐工具解耦。替代：多一次VLM、更长文本、工具错误 | 正确证据与no/shuffled证据无差；收益来自重写而非证据 | 在有该内容子集，用无证据、正确证据、同格式打乱证据；固定S1、S3表达/长度预算、S4；记录证据提及/定位命中 | 工具有效且成本合理再加入；无贡献删掉，不强行四工具齐用 |
| H4 失败差异需不同Refinement | 当前仅under/over/both，六类原因未校准。替代：多次采样、挑图 | feedback修复不超等预算重采样；分类误差高或统一动作同效 | 固定失败队列/触发器，随机分配generic rewrite、定向rewrite、same-prompt resample；K相同，统一selector；另离线比较selector | 先证明纠错动作，再证明路由；否则不用复杂根因router |
| H5 未开发测试保持收益 | 当前未知。替代：挑案例/重复场景/泄漏/过拟合NR指标 | 冻结测试无增益、CI含负/保真退化、seed方向不稳 | 冻结场景分组/哈希/模型/参数/政策；独立保管；解盲一次；失败和超时全报 | 不成立则回退共享或将结论限定为dev；不再调测试集 |

## E0–E6与公平对照

| Arm | 唯一变化 | 冻结项 | 最大图像候选 |
|---|---|---|---|
| E0-native | Direct Executor，官方原生配置、无S1/2/3/5 | 单图、任务要求 | 1 |
| E0-matched | Direct使用与E1相同的executor输入字节/几何/颜色政策 | 与E1配平；区分原生能力与Harness增量 | 1 |
| E1-original | 官方固定commit运行；报告单轮E1s与Redo E1r两条 | 完整原始代码/配置，保留故障 | 1 / K |
| E1-fixed | 本轮确定性修复后控制 | 不改变Prompt/模型/目标 | 1 / K |
| E2 | 仅S3表达policy | S1/S2 payload逐字复用；相同意图/长度档、S4/S5 | 1 |
| E3 | 仅证据编码/路由policy，按子实验一次一因子 | 相同S1与Composer算法、VLM调用数；S4/S5 | 1 |
| E4 | 仅execution某一因子：几何或一个参数或颜色 | prompt逐字相同；其余不动 | 1 |
| E5 | 仅S5中的一个子因子：rewrite或selection或触发 | 第一候选相同；同触发失败池；候选数/selector配平 | K |
| E6 | 组合开发集通过的最少改动 | 测试集一次冻结；再做逐项删除 | K |
| U-K | 强通用prompt/通用rewrite、同调用/同选择预算 | 使用相同任务信息，K相同；如aware有编译器，通用也可用等额重写 | K |
| BO-K | 同prompt独立重采样＋同selector | 相同候选/触发预算 | K |

`E1-original`保留研究对象真实性；不把bug修复收益冒称模型专属策略收益。多类型原版失败作为工程失败率；主质量比较在统一修复控制上进行。E4不能把几何、CFG、steps、AdaIN同时更改。E3改变证据后最终prompt有差是中介；不是同时改变S3 policy。

## B0：Direct capability probe，先于策略开发

每模型对固定开发图测试六类指令：通用增强、明确退化、强保真、相对积极恢复、区域修复、官方推荐条件/编译。第六类是独立配置轴，不能把“额外PE调用＋新参数＋新Prompt”打包后归因为表达。先运行6种×5代表图×2模型×1重复=60候选作链路排错；再以有代表性子集3重复确认。

每个prompt明确相同任务/区域/可读文本/结构约束。积极臂可以允许不确定区域生成式重建，但必须标记任务变化；其清晰度收益不能与保真目标的“真实恢复”混算。严重模糊分：GT验证恢复、可核对粗结构的先验重建、无真值细节不可验证。

Qwen先复现确切官方配置，再以单因素检查steps/true_cfg/cache/precision/PE。NB2若Seed不受支持，记录seed=null、独立request ID/时间/服务版本，用重复调用衡量波动，不伪造Seed。不同模型内部数值相同不代表计算预算或能力公平；重点是同模型不同策略可比，同时报告模型间实际时延/成本。

## 数据、冻结与样本量

- 本轮night_0043和任何已看过/调过prompt的图只能入dev/casebook，不能伪装冻结测试。
- 先登记source、scene/session、设备、LQ/GT SHA256、许可、配准、像素空间、退化/强度、文字/人脸/细线/重复纹理标签。相同场景、裁块、邻帧、不同退化版本必须同组。去重用文件/像素hash并对近重复人工复核。
- 开发pilot建议30个独立scene，噪声/模糊/低光/压缩/混合各6；这是**建议配额，当前未满足**。论文MiO100/作者真实图可用于对齐，但不能将其种类或数量臆配到五类。
- 冻结确认目标100 paired scenes（每类20）+50 noGT scenes（每类10），来源与配额须在输出前核验；不足则如实降低范围/提高不确定性，不复制裁块凑N。
- 数据候选限本任务：作者MiO/RP中适用样本；[SIDD官方](https://abdokamel.github.io/sidd/)用于真实噪声；[RealBlur官方](https://github.com/rimchang/RealBlur)用于真实模糊；[LOL-v2原工作](https://github.com/flyywh/CVPR-2020-Semi-Low-Light)用于低光；JPEG/混合可在独立清晰scene上预注册退化核/顺序并冻结。GT不是完美真理：动态/配准/曝光差必须标记，低光正常曝光图也不一定代表唯一合法夜景影调。
- 不声称覆盖任意退化。作者Real-NoGT里的haze/rain/snow不自动成为本次五类样本；本研究不额外开发天气恢复策略。
- 样本量以pilot的**scene级配对差SD**估计。近似N=((1.96+1.282)·SD/δ)^2用于90% power/双侧5%；不是完成证明。主δ在解盲前定，N不足标inconclusive。多个seed绝不当独立scene扩样本量。

## 评价与主分析

**paired：**主要报告PSNR-Y/SSIM-Y以便对齐官方，另PSNR-RGB作为颜色诊断；LPIPS、DISTS用RGB。固定pyiqa版本/权重SHA、范围[0,1]、色彩转换、边界裁切和对齐。不得为每张生成结果单独做可优化配准。若采用RealBlur官方评测中的对齐/强度补偿，单独报告该协议结果，并保留严格固定对齐结果，不能把补偿后的指标当颜色保真。分辨率合同不满足先记工程失败，不偷偷resize后当native能力。

**noGT：**独立盲评去退化D、保真F、自然度N分别评；1:1局部与同尺寸全图；文字已知部分做CER/逐字符核对，未知标unverifiable；轮廓/数量/遮挡/细线标有害变更。NR-IQA仅次要，不能证明细节真实。VLM-DF作为作者可比性辅项，最终判定不使用同一生成/选择VLM唯一裁判。

**统计：**每image先跨3seed/重复平均，再按scene平均；以scene为bootstrap cluster，10,000次、95%CI；按退化/强度、敏感内容分层，分层不足只描述。相同冻结scene上计算模型×policy差中差；也可拟合 `score ~ model*policy + degradation + (1|scene)`，检验交互而非比较两个p值。预注册H1/H2为确认项，Holm校正；其余探索/机制项单列。使用实际failure率及CI，完例质量分析与全样本故障率并排；不删难例，也不把缺失分数填0。

统计脚本CSV：`scene_id,sample_id,replicate,model,arm,metric,value,status`。它拒绝不完整配对、重复、非有限值和非OK记录；先完整报告错误队列，再登记质量cohort。方向 `PSNR/SSIM=1`、`LPIPS/DISTS=-1`。脚本只做一个指标的cluster bootstrap和模型交互；不自动完成多重比较、混合模型、人工可靠性或证明数据来源。

**候选准入门槛（建议值，须在冻结前定稿）：**paired确认endpoint固定为LPIPS绝对降低≥0.01且scene CI支持正效应；noGT确认endpoint固定为独立盲评净偏好优势≥10个百分点且CI>0，分层分别判定，不允许看到结果后在两者中择优；同时PSNR非劣界−0.10dB、SSIM非劣界−0.002、严重结构/身份/文字错误率增加≤2个百分点的单侧95%上界、CER非劣界+1个百分点。界限冲突时报告Pareto，不能用DF掩盖。多seed/重复的增益方向及失败尾部单列；小样本未排除保真风险不算通过。上述阈值是本协议的产品判断候选，不是论文或已验证感知阈值。

## 独立盲评执行

评价者不得参与prompt/策略开发；匿名随机A/B左右和顺序，不给模型/arm/在线verdict；可见LQ，paired场景可见GT，但真值不可比区先mask并记录。先用独立校准集统一标注，不用最终测试图调准则。每对至少3人；评价去退化/保真/自然度及整体偏好、无法判断，严重错误需坐标与类别。10%重复测评者一致性，记录Krippendorff alpha/原始分歧，争议由未参与开发者复核。客观画质不以多数票确定未知文字真值；无GT细节一律保留“真实性不可验证”。解盲前锁定分数/排除项/统计代码与hash。

## 五个实验区块与执行次序

| 块 | 目的与最小输出 | Gate | 成本记法 |
|---|---|---|---|
| B0 Sanity/Direct | 身份/单图/几何/配置；6类prompt能力包络 | 原生接口可运行、GT正确；错误先修再测 | 60排错候选；真正时延/费用尚未知 |
| B1 Baseline/交互 | E0matched/E1s；VLM×Executor小2×2 | 若主要差源自VLM/后处理，先改归因 | 以N×模型×重复×候选记录 |
| B2 单阶段隔离 | E2/E3/E4；prompt crossover和正确/打乱证据 | 有主效应且过保真门槛才保留 | 每因子单列，不打包寻优 |
| B3 S5机制 | feedback vs同prompt resample；统一selector；候选池重排 | 额外采样/选优解释完收益则拒绝专属S5 | 首候选复用，追加K−1调用 |
| B4 Frozen/generalization | E6、强共享等预算、E1、Direct；有效块删除 | 只解盲一次，过CI/保真/成本门槛才采用 | 若K=2、N=150、2模型、3重复，5臂上界7200生成，未授权/启动此配额 |

B4五臂是E0(1)、E1s(1)、E1r(2)、U2(2)、E6(2)，即150×2×3×8=7200上界；不是必须一口气跑完的费用承诺。增加删除臂需额外登记。先根据B0实测中位时延/显存/费用定预算，满足统计效能再启动冻结；当前没有GPU小时、货币成本或完成日期的可靠估计。若B2没有有效改动，停止E6，不制造组合系统。

## Trace最小合同

每run记录：研究/arm/policy/软件commit、模型精确ID+revision+pipeline版本、数据与划分hash、planner设置、任务要求、实际executor输入字节hash、原图/预处理图/地图/证据/最终prompt及语义条目ID、原生参数/seed或null/每次request ID、transport attempts/异常/usage/真实耗时/候选数、decoded native/geometry normalized/delivered三个端点图与hash、颜色模式、每轮verdict及候选池/选择理由、独立评价/失败根因及不确定性。配置与资产改变即新run，不按文件存在简单resume。

所有生成输出、失败、无效证据、重试、丢失输出均保留。GT只能离线评分；开发/在线selector不得读测试GT。人工评价者与保管测试集者分离。未执行条目保持BLOCKED/TODO，绝不写示例分数冒充结果。


## 独立审查后锁定的解释边界

1. **确认contrast先固定。** H1主要interaction为同一metric的`(E1-fixed−E0-matched)_Qwen − (E1-fixed−E0-matched)_NB2`；H2以同一套Qwen式renderer与强共享renderer跨两模型交叉，检验renderer×Executor交互，另检验Qwen自身的paired主效应。NB2式renderer是预注册的次要反向检验。不能在看分数后换对照、换metric、把探索interaction改成确认项。H1即便成立，也不能单独推出专属policy必要。
2. **失败不能靠删行解决。** 完例质量估计只代表共同成功cohort；并排报告失败率不能消除post-treatment selection bias。全冻结群体结论还需预先定义的failure estimand、执行失败率非劣界（候选+1个百分点，单侧95%CI）及MNAR敏感性/界限分析。如果置信范围或缺失敏感性不能排除反转，只报条件质量效果/全体失败率，不声称总体质量改善。无实际输出不得私自以0或LQ替代；若系统预先定义失败交付LQ，则必须作为真实交付策略全样本评分，另列原生执行失败。
3. **K相同只表示候选预算相同。** feedback还消耗VLM tokens、工具和transport attempts。候选等预算与总成本等预算是两个estimand；U-K/BO-K先控制候选池与selector，再按实测total model calls/tokens/费用/时延设置等总预算上限。只有实测配平（预注册容差，例如成本±5%，并公开节省未用额度）后才能声称超等总预算；否则只报质量–成本Pareto。重试/超时未知计费不得当零成本。
4. **统计CLI现在强制`--cohort`。** 文件列`scene_id,sample_id,replicate`是预先冻结的期望quality cohort，保存SHA；若两臂一起漏同一图，脚本仍拒绝。API的未绑定fixture模式输出`cohort_bound=false`，不能进入确认结果。完整冻结全人群manifest与经审计的quality cohort分开存，任何排除均在解盲前按规则记录并保留失败端点。

5. **功效使用实际主contrast方差。** H1用scene级difference-in-differences的SD；H2用预注册renderer×Executor交互的SD，而不是单模型差值SD。保真/严重错误率非劣验证也单独做功效与精度设计，稀有错误可能决定更大的N；100 paired/50 noGT是待核验目标配额，不是足够样本量的承诺。最终取主要质量、交互与保真门槛所需N的最大值；预算不足则缩小可支持主张或报inconclusive，不能放宽测试后阈值。

6. **H2/H3的语义控制。** 开发时将退化目标、区域、保护对象、不确定项和优先级拆成编号原子意图，由不知policy/模型的审阅者逐项核对最终prompt是否添加、删除或加强目标。长度用同模型可观测text tokens（若有）及英文词/字符双记录，按±5%候选容差或预定义长度档比较；不能将Qwen短prompt只与另一模型长prompt相比。PE/原生rewriter单列因子并配平改写尝试；schema通过或Composer自述evidence_used不作为语义保持证明。H3先缓存同一工具真实结果再做信息通道干预，工具调用/证据准确/表达保留/输出局部效应分别登记；实际按需调用节省成本另测，不用离线缓存冒称在线耗时。
