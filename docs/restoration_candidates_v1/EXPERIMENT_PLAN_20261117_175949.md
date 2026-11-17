# 修复候选生成与审核选择完整实验计划

版本为 1.0，日期为 2026-11-17。本文将批准方案转为离线 GPU 端可执行的实验顺序，使用现有工程接口。它是实验协议计划，不是真实数据清单、已完成预注册或实验结果。

## 1. 当前状态与执行边界

在线 CPU 电脑负责开发、依赖准备、测试、文档和打包。GPU 电脑不能访问外网，负责真实模型运行。GPU 端的本地 code agent 只做有记录的故障定位和小范围修复，不能改变冻结协议或补造研究结果。

当前 CPU 候选相关测试为 145 通过、1 项 Windows 符号链接权限跳过。真实 GPU 推理、画布能力、显存和模型效果未验证。原复审 P2 的 Best-in-pool Agreement 边界问题已修复，最佳标注与实际合格集合冲突时记为缺失，不再错误计为 0/1。

G0 的单案例与批量路径回归及独立复核已通过。后续先准备真实数据和目标环境，再执行 GPU 工程 smoke。CPU 验证不能替代真实模型与独立标注，也不表示恢复质量已经改善。

本文与 [实施方案](IMPLEMENTATION_PLAN_V1_1.md)、[候选细节](CANDIDATE_GENERATION_DETAIL.md)、[运行手册](RUNBOOK.md) 配套。问题来源见 [review_v3.md](validation/review_v3.md)，关闭复核见 [最终复核](validation/final_review.md)。执行状态只在 [EXPERIMENT_TRACKER.md](EXPERIMENT_TRACKER.md) 更新。

## 2. 研究问题、声明与反证

问题是固定四图预算下，单一恢复 Prompt 的重复采样能否覆盖人物与文字的不同恢复需求，以及审核器能否选择真实合格的图，而不是选择锐利但内容错误的图。

| 声明 | 最低必要证据 | 对应实验 | 不足以支持声明的结果 |
| --- | --- | --- | --- |
| C1，主要声明。反馈规划的候选池比同预算 P0 重采样更容易包含可用答案，并改善最终系统输出 | Held-out 的 A/B 配对 Oracle Pass@4、Selected Pass、内容错误与成本。另以预注册同 seed E2 检查策略方向 | B1、B2、B4、B5 | 只展示几个好例子，或只看锐度，或删掉失败 case |
| C2，支持声明。软证据帮助审核，同时不放宽内容资格 | 同一 B 池、相同匿名次序与模型下 J0/J1 比较，报告选对、误拒、误纳及 unresolved | B3、B5 | 同时改变生成模型、候选图片、政策或预算后归因于软证据 |

必须排除的解释是增益只来自更多生成次数、不同 seed、额外 Judge 调用或挑选成功 case。A/B 每池都是四槽。共享 C0 后每 case 最多七次 E1 图像调用。E2 使用另外两枚相同评价 seed 做配对，不能把 E1 的不同 seed 差异解释为 Prompt 因果作用。

本轮固定一个图像模型及部署版本，不声称 Qwen 优于其他图像模型，也不声称结论跨所有 backbone 泛化。不新增模型训练、长基线清单或昂贵模型搜索。删除性比较由 C0 单图、A 池重采样、J0 与 J1 承担。

## 3. 固定系统与对照

| 对象 | 定义 | 保持一致的条件 |
| --- | --- | --- |
| C0 | 原 Diagnosis → Tools → Composition 得到的完整 P0，以 s0 生成 | 原始 canonical/prepared LQ、模型、部署清单、几何、全部有效参数 |
| A 池 | P0 在 s0、s1、s2、s3 各生成一图 | 与 B 共享同一个 C0，其他三图独立调用 |
| B 池 | C0、CF、CT、CFT 四个终态槽。允许有据可查的其他轴、单轴替代和 P0 fallback | 所有候选从同一 LQ 生成，C0 只用于反馈规划，不作为生成器图像输入 |
| J0 | 只使用固定视觉证据的基线审核 | 与 J1 共享池、匿名顺序、用途政策、逐属性资格和冻结配置 |
| J1 | 在相同视觉输入上增加软证据 | 软数值不能单独淘汰候选。A/B 主比较都使用 J1 |
| J2，可选 | 人物、文字、技术质量、正常观看四视角及终审 | 只在 Pilot 的固定池上判断是否值得增加调用 |

图像模型固定为 `Qwen/Qwen-Image-2.1`。模型 revision、Diffusers 来源与版本、checkpoint 文件清单、所有 VLM 模型与采样设置必须写入实际运行记录。沿用现有直接 Prompt 通路，不额外启用 PE 编译或未登记 wrapper。

默认 steps=40、true_cfg_scale=1、negative_prompt 为空、每次一图、output_resolution=1024、use_kv_cache=true。配置值必须与实际请求及回执一致。改变任何这些值都需要新 case，不能修改已有 F0/F1。

## 4. 数据划分与目标登记

| 划分 | 人物 | 文字 | 混合 | 其他 | 合计 | 用途 |
| --- | --- | --- | --- | --- | --- | --- |
| Pilot | 3 | 3 | 3 | 1 | 10 | 环境、失败原因、评审合同与协议诊断 |
| Held-out | 6 | 6 | 6 | 6 | 24 | 冻结后独立检验，不用于调参 |
| Pilot E2 子集 | 1 | 1 | 1 | 1 | 4 | 同 seed 策略分析 |
| Held-out E2 子集 | 2 | 2 | 2 | 2 | 8 | 冻结后机制验证 |

按唯一 `scene_id` 划分，不允许同一场景不同裁图跨 Pilot 和 held-out。GT、文字真值和人物内容标签必须有可追溯来源。没有合适数据时报告缺额，不能虚构 34 个已完成 case。

每个 case 在首次 E1 输出前登记以下信息。

| 字段 | 登记要求 |
| --- | --- |
| case_id、scene_id、split、scene_class | 唯一身份，主类使用 person、text、mixed、other |
| source、原始文件 SHA-256、尺寸、退化 recipe 与 seed | LQ 的实际来源。GT 放在独立离线标注记录，不进入 TaskSpec 或在线请求 |
| rois | 原 LQ 整数坐标 `[x0,y0,x1,y1)`，语义、重要性和来源。框不能根据生成结果移动 |
| information_levels | 分别记录人物/文字的 legible、partly_legible、unreadable 或 not_applicable |
| roi_size_bins | 人脸框短边、文字行高按 LQ 像素分为 `<16`、`16..31`、`>=32` 或 not_applicable |
| evaluation_targets | 人物、文字的 region_id 与 attribute_id，以及重要 non_target_rois。适用性仅由 LQ 决定 |
| slot_axes | E1 前冻结的评价槽映射。与 F1 的实际干预轴分开保存 |
| case_root、task_config_ref、runtime_config_ref | 目标机上的真实输出目录及配置引用 |

标准混合目标的默认评价映射为 `{"CF":"person","CT":"text","CFT":"joint"}`。单轴多槽必须显式登记，例如两个人物方向使用 `{"CF":"person","CT":"person","CFT":null}`。文字单轴同理按设计登记，不能在看到 F1 后重分配评价槽。

只存在建筑或草地目标时，保留实际产物、失败及覆盖记录。没有预注册人物/文字目标的指标为 not_applicable。本轮不发明其他场景的目标质量公式。

`usage_policy` 与关键属性也必须先冻结。information_critical 不允许通过放宽准确性接受未知身份或未知号码。photo_restoration 允许未知的属性必须预先明确，最终报告仍披露未知状态。

## 5. 预注册、seed 与算法身份

E1 seed schedule 固定为 `[0,1,2,3]`。E2 评价 seed 固定为 `[10001,10002]`，不得与 E1 重合。抽样 seed 为 20261117。

E2 名单在阅读 E1、C0、Judge 和 Oracle 结果之前生成。按 LQ 主类和信息量、尺寸子层抽样。当前 `study.py` 的实际算法名为 `seeded_strata_round_robin_sha256_v1`，先按类 seed 打乱子层顺序，子层内按抽样 seed、case_id 的 SHA-256 排序，再轮转取样。类内不足则取全部并记录 shortfall，不跨类借额，不补入成功 case。

`examples/experiment_protocol.default.json` 是待实例化模板。其旧 `selection_algorithm` 标签与当前输出算法名不同。G1 冻结前必须在实际协议中记录上述实现名称及子层顺序规则，核对 preregister 输出的 `strata`、`shortfalls`、算法名和 hash。不能只改标签后继续声称使用旧的纯字节序子层顺序。

预注册输出包含 case_ids、cases、evaluation_seeds、dataset/protocol hash 及 freeze_hash。保存输入数据清单和协议的原始字节。对 E2 选中 case，在创建 F0 时设置 `experiment.e2_manifest_path`，不能生成后补接。

Pilot 结束后最多修订一次协议。记录修改原因与内容，再冻结 held-out 的名单、配置、代码和分析脚本。持有 held-out 标签的人不得用其结果选择协议或模型。

## 6. 五个实验块

### B1，基础能力与公平基线，必须运行

问题是原始四槽生成与内容资格在真实模型上是否成立。先用独立工程图执行 restoration_x1，再用 257×193 的真实 LQ 执行 sr_x4。两者使用独立新 case，不计入 Pilot。

验证请求中的 Prompt、seed、canonical/prepared LQ hash、部署 hash 和回执。x4 的 LQ pad 为 264×200，请求 native 为 1056×800，精确裁剪为 1028×772。不能通过 resize 修正原生尺寸错误。x1 按 32 网格准备，并裁回原内容尺寸。

成功条件是环境预检通过、原生和交付几何正确、没有隐式下载、正常 resume 不新增调用，修改已选图片后被拒绝。失败说明当前运行环境或适配链路尚不能承载后续研究，不说明方法质量好坏。目标产物为环境记录和一张几何/回执核对表。

### B2，A/B 系统主实验，必须运行

在 Pilot 10 张和冻结的 held-out 24 张上分别生成 A/B。每池四槽，两池同用 J1。人工对七张唯一图独立标注，同一共享 C0 的质量标签复用，但两池最佳集合分别标注。

主指标为 Selected Pass。Oracle Pass@4 判断生成池是否出现好答案。辅以内容错误、ContractValid coverage、误拒/误纳、unresolved 和成本。保存 B−A 配对差值、胜平负和 case bootstrap 区间。

支持 C1 需要 held-out 改善方向与内容安全、失败率和成本一起成立。置信区间跨 0 时报告不确定，不宣布稳定提升。若 Oracle 改善而 Selected Pass 没改善，问题更可能在审核而非生成；若只有 selected 改善，不单凭此断言候选覆盖增加。目标表为 A/B 主结果与全部失败分母。

### B3，固定池 J0/J1 审核比较，必须运行

复用同一 B 池，不新增图像调用。执行 J0，与默认 J1 比较。检查 pool_hash、候选次序、ROI、用途政策、模型和采样配置一致。J0/J1 的差异只能是预先约定的软证据输入。

记录 Selected Pass、Conditional Selection Success、Best-in-pool Agreement、False Reject、False Accept、eligible 误纳、缺评和费用。未解决缺包或关键内容未知时允许 unresolved，不能强行选图。

现有批量主入口固定读取 J1，J0/J2 的比较必须从各自 `judge/<variant>/selection.json` 建立独立离线表，并与同一 Oracle 标签关联。不能覆盖 `selection.json` 来让主汇总假装支持其他 Judge。

若 J1 未改善选图或只增加成本，C2 不获支持。若 J0 已足够好，不把更复杂 J1 作为默认必胜方案。目标表为固定池审核比较与误拒/误纳归因。

### B4，预注册 E2 同 seed 策略分析，必须运行

在预先抽出的 Pilot 4 张、held-out 8 张上，以两枚新 seed 分别执行冻结的四槽 Prompt，每 case 额外八次图像调用。F1 从原 E1 C0 冻结，不重新规划，不根据 E2 修改 Prompt。

每个实际替代槽与同 seed P0 图配对。统计 Target Improvement、Off-target Regression、Joint Success、Joint Compatibility 及覆盖。每个槽、预注册评价轴分别报告，不能事后取 A/B 中效果最好者。

注册分母保留 C0 失败、fallback、错轴、无有效干预、执行失败和缺评。Joint Compatibility 只解释两单项本已成功且无回退的完整配对，不得用机制 not_applicable 删除端到端 Joint Success 的失败。

支持机制需要有证据的目标改善，同时没有重要非目标退化。单纯更锐利、像素变化或不同 seed 的好看输出不算机制证据。目标产物为策略效果表、同坐标 ROI 图和原始裁定记录。

### B5，内容风险、简化与失败诊断，必须运行

从全部预定 case 报告失败类型，不只选成功示例。固定反例至少覆盖清晰错字、自然但换表情、人物改善而背景严重欠修、草地改善而人物受损、低锐但自然图。若真实数据缺少某类反例，单独列出补充诊断集，不能伪称它属于预注册主样本。

按任务政策分层报告错字、身份/表情/姿态冲突、结构损坏和严重背景伪影。比较内部基线 C0、A 池、B 池及 J0/J1，判断新增规划和证据成本是否值得保留。

成功条件是失败、未知和缺评可追溯，简化的对照能解释必要复杂度。负结果应直接约束声明，不能靠增加组件掩盖。目标产物为失败分类表与正常观看、ROI、GT 三阶段的案例说明。

## 7. 可选实验及实施边界

J2 只在 Pilot 出现明确选图失败且有改善空间时启动。复用固定 B 池，默认每池每 variant 最多七次调用。若 J2 不改善选择且提高成本，保留默认 J1。未运行时写 J2=not_run，不阻止检验生成假设。

若要把 J2 收益归因于专家分工，需要 `J1_budget_matched`，匹配模型、证据、必需检查、primary/aggregate/repair/dispute 上限及输出 token 额度。当前公开 CLI 没有该 variant，须先完成独立实现和验收，再增加协议版本。本计划不提供虚构命令。未做时只报告多角色、多预算系统效果。

`J_soft_gate`、模型更换、更多候选、其他 backbone 和新策略搜索均为可选扩展。不得用未预注册阈值删除候选，不占用本轮主实验声明。SSIM、LPIPS、CER 和身份模型指标只在离线侧补充，工具未部署时明确 missing，不能填 0 或进入在线 Judge。

## 8. 阶段、顺序与验收

| 里程碑 | 工作 | 进入下一阶段的条件 | 停止条件 |
| --- | --- | --- | --- |
| G0，CPU 统计验收 | 关闭最新 Best-in-pool 边界问题，补回归，重新验证源码/wheel | 单案例和批量的冲突最佳标签被拒绝或正确记缺失；完整候选测试通过 | 把失效最佳标注算成确定失败，或文件损坏触发重新生成 |
| G1，数据与离线环境 | 填目标 OS/Python/GPU、依赖、权重、端点，核对协议算法与数据目标 | 真实环境清单、文件 hash、LQ 目标登记完整；无占位配置 | 无真实数据清单、不可控隐式下载、模型 revision 不明确 |
| G2，真实工程 smoke | B1 的 x1、奇数尺寸 x4，验证恢复与回执 | 原生几何及请求身份正确，恢复不重复调用 | 只能靠 resize、改 seed、删账本或 fixture 才成功 |
| G3，Pilot | 冻结 Pilot 与 E2 名单，运行 B2-B5 | 全 case、失败和标注完整；能区分覆盖问题与选择问题 | 无独立 Oracle、预算不足、unknown 未说明或 GT 泄漏 |
| G4，可选 J2 | 只针对 G3 支持的审核研究 | 固定池与成本匹配条件明确，或严格限定归因 | 以角色名替代证据，或只保留成功案例 |
| G5，Freeze/Held-out | Pilot 后最多一次修订，冻结 24 张与 E2 8 张 | 代码、实际依赖、配置、协议和分析身份全部固定 | 阅读 held-out 结果后调 Prompt、政策、阈值或清单 |
| G6，分析与复核 | 全样本汇总、失败审计、声明判定 | 所有分母、缺失数、hash、原始记录、统计与复核可追溯 | 悬而未决的统计缺陷、漏失败、未披露费用或缺评 |

阶段与原工程编号对应为 phase_P0/P1/P2/P3 → P5 Pilot → 可选 P4 → P6。不要把 baseline_prompt P0 与工程阶段 phase_P0 混用。当前已完成的是 CPU 实现与部分验证，不是 G2 之后的真实结果。

## 9. 运行前必须实例化的输入

在目标机建立独立 config、data、runs、annotations、reports 目录。路径由操作者按实际机器填写。下面命令使用 `/srv` 作为 Linux 目标示例；目标若是 Windows，按 [运行手册](RUNBOOK.md) 改用 PowerShell 和实际绝对路径。

必须准备实际 dataset manifest、LQ evaluation_target_registry、每图 TaskSpec、每图 runtime、目标 OS/Python/CUDA/driver/GPU 清单、wheelhouse、checkpoint/deployment manifest、VLM 启动参数、实际代码快照及协议。GT 和 Oracle 放在单独离线目录，不能放入在线请求配置。

从 `engine/examples/restoration_candidates_v1/runtime.real.example.json` 复制配置，并替换每个部署占位值。六个 VLM 阶段可共用服务器，但必须实测图像容量和 JSON 输出合同。配置只保存 api_key_env，不能写入密钥值。

所有主实验 case 设置 `mode=real`、`experiment.e1_ab=true`。未入 E2 的图像上限为 7；入 E2 的 case 在 F0 前设置为 15，并附 e2_manifest_path。仅四图 B 池工程诊断的 E1+E2 上限为 12，不能把它混入七图 A/B 主比较。

默认每 variant 的 Judge 总上限为 J0=3、J1=3、J2=7。A/B 两池分别记账。默认每包最多六个 ROI、每调用最多 64 张图。实际端点不足时在 F0 前配置能力和全部分类/总预算。必需分包或终审放不下时为 unresolved，不能删 ROI 或临时放宽资格。

## 10. 命令顺序

先按 RUNBOOK 完成离线依赖安装、包 hash 核验和 checkpoint 准备。在解压工程根目录运行以下命令。CPU fixture 的 PASS 不能替代真实 GPU smoke。

```bash
export PYTHONPATH="$PWD/engine/src"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
python -m hre candidates fixture --out /srv/runs/engineering-cpu-smoke
python -m hre candidates run --case-root /srv/runs/engineering-cpu-smoke/case
python -m hre candidates resume --case-root /srv/runs/engineering-cpu-smoke/case
python -m hre candidates preflight --config /srv/config/runtime.smoke.json
```

准备独立 x1 和 x4 的 TaskSpec，分别执行，不复用 case_root。真实 smoke 通过后再进入研究 case。

```bash
python -m hre candidates create --case-root /srv/runs/gpu-smoke-x1 --spec /srv/config/task.smoke-x1.json --config /srv/config/runtime.smoke.json
python -m hre candidates run --case-root /srv/runs/gpu-smoke-x1
python -m hre candidates create --case-root /srv/runs/gpu-smoke-x4 --spec /srv/config/task.smoke-x4.json --config /srv/config/runtime.smoke.json
python -m hre candidates run --case-root /srv/runs/gpu-smoke-x4
```

G0-G2 通过、实际 Pilot 清单完整后，在任何 Pilot E1 结果出现前预注册。`/srv/config/protocol.pilot.json` 是按第 5 节核对并实例化后的协议，不是未经审查的模板别名。

```bash
python -m hre candidates preregister --dataset /srv/config/dataset_manifest.json --protocol /srv/config/protocol.pilot.json --split pilot --out /srv/config/e2_pilot_manifest.json
```

逐 case 执行下面步骤。示例 case_id 是路径示意，不代表已经存在真实样本。先核对该 case 是否在 E2 清单内，选用 image_generation=7 或 15 的冻结 runtime。

```bash
python -m hre candidates create --case-root /srv/runs/pilot/pilot_001 --spec /srv/config/pilot_001.task.json --config /srv/config/pilot_001.runtime.json
python -m hre candidates run --case-root /srv/runs/pilot/pilot_001
python -m hre candidates judge --case-root /srv/runs/pilot/pilot_001 --variant J0 --pool B
python -m hre candidates report --case-root /srv/runs/pilot/pilot_001
```

默认 run 已执行 A/B 的 J1。仅对预注册 E2 case 追加以下命令；仅在 G4 条件满足时执行 J2。

```bash
python -m hre candidates e2 --case-root /srv/runs/pilot/pilot_001
python -m hre candidates judge --case-root /srv/runs/pilot/pilot_001 --variant J2 --pool B
```

人工裁定完成后才运行离线评估。Oracle 文件覆盖两池七个唯一候选，分别提供 best_sets.A/B。GT 几何必须等于交付图，不能通过 resize 凑齐。

```bash
python -m hre candidates evaluate-offline --case-root /srv/runs/pilot/pilot_001 --labels /srv/annotations/pilot_001.oracle.json --gt /srv/gt/pilot_001.png
python -m hre candidates summarize-offline --cases /srv/runs/pilot/pilot_001 /srv/runs/pilot/pilot_002 --out /srv/reports/pilot --bootstrap-replicates 10000 --seed 20261117
python -m hre candidates effects-offline --registration /srv/config/e2_pilot_manifest.json --annotations /srv/annotations/pilot.effects.json --out /srv/reports/pilot-e2
```

`--cases` 示例只显示两个路径。正式调用必须展开全部十个 Pilot 预定目录，包括缺失、失败或 unknown 的 case。Held-out 同理传入全部 24 个预定目录。不能只列成功目录。Held-out 在修订后单独 preregister，使用 split=held_out 和新的实际协议/输出路径。

## 11. 独立标注协议

两名评审互不读取在线 Judge、策略名称、Prompt 或另一评审结论。先以匿名随机次序看正常尺寸整图，记录自然度和可用性，再看固定坐标 ROI，最后在独立内容检查中查看 GT。两阶段记录分别保存，不能把“更好看”直接当作真实性通过。

E1 每张图记录合格与否、已确认内容错误、适用属性、证据引用和评审身份。最佳集合必须位于实际硬契约有效且人工质量合格的集合中。最佳标注与硬契约冲突时复核或记缺失，不把失效最佳图直接过滤后算一次选错。该行为已通过 G0 的单案例与批量回归验收。

E2 先匿名随机左右比较同 seed 替代图和 P0。每个注册 ROI/属性记录 improved、tied、worse 或 undetermined，以及 material_damage、content_conflict、overall_acceptable、图像 hash、证据与理由。两人分歧交第三人裁定，无裁定为 undetermined。只有一人时明确 single_rater。

原始表保留 rater_id、adjudication、左右顺序、可见性和理由。裁定后转换为当前 `analysis.py` 文档定义的 annotation JSON。转换记录将匿名 pair 关联到实际 slot、axis、effective_strategy_id 和 pair_hashes，不丢弃原始表。

原始 GT、Oracle、效果标注和未匿名对照只在离线侧可读。在线配置和请求日志必须审计，确认没有这些真值路径、标签或文字答案。

## 12. 统计合同与结果解释

令 U 为实际硬契约通过集合，A 为 U 中独立 Oracle 确认合格的集合，B 为 A 中独立并列最佳集合，S 为在线正式选择。软证据不决定 U。

| 指标 | 规则 | 失败和未知 |
| --- | --- | --- |
| Produced / ContractValid coverage | 已产出/实际硬通过槽数除以全部预定槽数 | 所有预定 case 保留；失败不删除 |
| Oracle Pass@4 | A 非空的 case 比例 | 不完整 Oracle 披露 missing；未确认者不能算合格 |
| Selected Pass | S 属于 A 的 case 比例 | 无选择、失败或不完整 Oracle 保守记非成功 |
| Conditional Selection Success | A 非空时正式选对比例 | 不能用无答案 case 稀释条件分母 |
| Best-in-pool Agreement | A 非空且有效最佳标注完整时 S 属于 B 的比例 | 冲突或缺失最佳标注单独计缺失。G0 通过后才作为正式结果 |
| False Reject / False Accept | 对实际 A 与 eligible/正式交付计算 | 只在 Oracle 完整 case 计算，同时披露全体数和完整数 |
| Target Improvement | 槽的全部预定目标均改善且无新增目标内容错误 | 分母是预注册适用 case × 两 seeds。回退、失败、缺评不成功 |
| Off-target Regression | 至少一个重要非目标 ROI 有实质损害 | 分母只用预定且完整配对评审，另报全部预定、失败、缺失数 |
| Joint Success | 全部双目标改善，整体合格且无重要非目标损害 | 保留全部注册双目标机会，不能按 F1 删减 |
| Joint Compatibility | 两单项已成功时，联合保留二者的比例 | 仅完整、无回退机制子集。其他为 not_applicable 并披露占比 |
| Exact Duplicate Rate | 至少两图 case 中像素 hash 唯一数少于成功槽数的比例 | 额外报告不足两图数，不删重复槽或成本 |
| Perceptual Diversity Collapse | 完整盲评或裁定认为成功槽无可辨差异的比例 | 缺评单列，统计不显著不等于感知坍塌 |

全部比例保存 numerator、denominator 和 missing_count。零分母为 null，并说明不适用。A/B 使用按 case 重采样的配对 bootstrap，10000 次、seed=20261117，报告 B−A 差值的 2.5%/97.5% 分位数及胜平负。不能把同一 case 的候选、ROI、两枚 seed 当独立样本。

当前汇总 CLI 自动输出 E1 Oracle/选择配对统计与 E2 人物/文字注册槽指标。内容错误分型、精确重复率、感知坍塌、完整硬件成本和 J0/J2 对比需要依据原始记录在独立离线表中计算并复核，不得因没有专用汇总命令而省略。可选 GT 指标只作补充，不单凭 PSNR 选择在线输出。

Pilot 结果只用于诊断。Held-out 仍是小样本，报告区间和局限。没有稳定证据时结论为未获支持或不确定，不预设提升百分点，不把小样本负结果包装成已证明等效。

## 13. 计算与人工预算

| 项目 | Pilot | Held-out | 合计 |
| --- | --- | --- | --- |
| E1 case | 10 | 24 | 34 |
| E1 图像调用上限 | 70 | 168 | 238 |
| E2 case | 4 | 8 | 12 |
| E2 额外图像调用上限 | 32 | 64 | 96 |
| 研究图像调用总上限 | 102 | 232 | 334 |

独立 x1/x4 工程 smoke 若均开启 A/B，另预留最多 14 次图像调用，不计入研究总量。CPU fixture 不消耗真实图像模型调用。J0/J1/J2 使用固定图像池，不新增图像生成，但增加 VLM 调用和人工核查成本。

默认单 case 的基线/Planner/Rewriter/Audit 合计最多八次 VLM 调用，工具最多六次，分别按日志核对。两池 J1 默认再预留最多六次，B 池 J0 最多三次，可选 B 池 J2 最多七次。实际分包容量可能要求在首次生成前冻结更高的 Judge 上限，不能沿用这些数值却暗中超支。

当前不知道 GPU 型号、可用显存或单次耗时，不填写虚构 GPU-hours。G2 实测每图耗时 t_img、各阶段耗时和显存峰值，再估算研究图像计算上限 `334 × t_img / 3600` GPU-hours，另加真实基线工具与 VLM 占用。共享 GPU 时不能把重叠 wall-clock 简单相加。记录费用或 token 缺失为 unknown。

若全部成功，E1 有 238 张唯一输出，E2 有 96 张。两名评审至少形成 668 份单图检查，另有每池最佳判定。E2 有 72 个替代图对，双评至少 144 次配对评审，每对可能含多个 ROI/属性。第三人裁定、失败处理和反例诊断另记，不估造人天。

执行进度按门槛而非固定日历。G0/G1 完成才安排真实 smoke，实测吞吐后再预约 Pilot 与 held-out 时段。预算不足时先保留核心 B1-B5，取消可选 J2；调整主实验配额需要在该划分首次 E1 输出前修订并冻结。

## 14. 失败、恢复和离线 agent 修复边界

blocked 先检查依赖、真实路径、checkpoint 身份、端点和容量，不改方法绕过。unknown 表示调用可能已执行，消耗已保留预算，不自动重发。失败、重复图和 unresolved 都留在预定分母与成本记录里。

有确认回执或未执行证明时，按 RUNBOOK 将绑定证据放入 case/reconciliation。A 池使用 case/pools/A/reconciliation 并传入 `--pool A`。reconcile 本身不生成图，之后 resume 只重放完成调用。仅有一张 PNG 不构成完成或费用证明。

output_modified、freeze_modified 或 selection_binding_mismatch 必须保留现场，查明来源。只有精确恢复原字节才能继续原记录。不能删账本、重置 seed、伪造回执或把真实运行切换为 fixture。原生尺寸错误不能靠 resize 修补。

离线 code agent 的修复记录至少含错误码、复现命令、环境版本、最小 diff、回归结果、实际模型 smoke、受影响 case 与全部未知费用。改变在线生成、选择或协议的修复必须决定是否使已生成结果失效。Held-out 中途若必须改变算法，停止该轮，报告已消耗样本，不能在同一封存划分上调完继续声称独立测试。

## 15. 交付物、表图与最终决策

每 case 保存 F0/F1、完整 Prompt、Issue/审计/fallback、执行清单、原生/交付回执、操作账本、匿名整图/ROI、Evidence、各 Judge 选择、contact_sheet 和逐图报告。E2 保存注册 hash、每个 seed/slot 的原始产物和同 seed 对照。

全局至少交付实际 dataset/目标/协议/E2 清单、环境锁、代码快照和 hash、完整原始/裁定标注、case 清单、失败与未知表、E1 主结果、J0/J1 比较、E2 效果、内容错误、成本表，以及实验报告和独立审计意见。当前源码未提交时保存精确源码包和 diff；正式冻结优先使用可复现 commit，不能将旧基线 SHA 冒充新实现 commit。

主表一为 A/B 的覆盖、Oracle/Selected Pass、内容错误及成本。主表二为固定池 J0/J1 的选择和误拒/误纳。主表三为同 seed E2 的目标、非目标和联合指标。主图显示机制配对与保留失败的案例，附录提供逐 case 结果、未知、政策差异及可选 J2。

只有 Selected Pass、内容错误、合法最佳一致率、失败率和成本共同支持，才提出部署建议。仅候选 Oracle 改善时先改进选图研究；仅主观锐度改善时不成立；证据不足时保留原方案或报告不确定。

## 16. 研究启动与报告冻结清单

- [x] G0 的最新 Best-in-pool 边界缺陷已关闭，两条报告路径有回归证据与独立复核。
- [ ] 目标机系统、依赖、权重、模型、VLM 容量、实际算法与预算已登记。
- [ ] 真实 x1/x4 smoke 通过，恢复与对账不重复调用。
- [ ] 真实数据、LQ 目标、政策、slot_axes 和 E2 名单在本划分 E1 前冻结。
- [ ] Pilot 全部 case、失败与独立 Oracle 已完成并报告。
- [ ] Pilot 后最多一次修订，held-out 数据与结果未参与调参。
- [ ] Held-out 全部预定 case 和 E2 seeds 保留，无成功替换。
- [ ] 所有比例、置信区间、缺失与内容错误可由原始记录重算。
- [ ] 主实验与可选扩展分开，未执行项目明确 not_run 或 missing。
- [ ] 生成、审核、统计、成本与 GT 隔离经过独立复核。
