# v2 实际运行手册

本分支实现生成式 G0/G1、冻结 ROI 评价和条件性 G2。已有 v1 `hre case/task/candidate/response`、Controller、CaseStore、预算与恢复协议继续使用。v2 不调用任何模型 API，不自动租 GPU。未提供真实 A/B 或真实编辑输出时，只能验证工程。

## 1. 安装与零模型演示

在本分支仓库根目录执行：

```bash
python -m pip install -e './engine[test]'
python -m hre --help
python -m pytest engine/tests -q
python engine/examples/reference_v2_demo.py --out /fresh/absolute/demo_directory
```

Windows 将最后一条输出路径替换成新的空目录。不得指向现有 Data 目录根。演示生成确定性色块和明确标注的模拟诊断/验证 JSON，**不调用模型，不是 R1，也不证明 G2 能力**。演示运行 G0/G1、A/B 异大小 ROI、原始候选保留、匿名导出以及缺评审 ITT；缺失人评时 joint success 为 0、决策为 PROBE。

## 2. 先跑真实一对 G0/G1

复制本目录 `examples/G1.spec.json`。填写实际可见的 Executor 名称、transport、adapter/pipeline 版本和可观察设置。不可观测的精确模型版本填 null；设置不提供可观察值时保持空对象，不填写猜测值。`assume_srgb=true` 是对无 ICC 输入的显式假定；已知非 sRGB/HDR 输入应先按原协议提供可追溯的 SDR 导出。

将 `simulation_only` 设置为 false，仅用于真实输入。A/B 的 box/polygon 使用各自规范化坐标；禁止把 A 的坐标当成 B 的坐标。每个区域声明同材质、可比性、原因及要测量的属性。region mask 是对应源图大小的 uint8 {0,1} NPY；所有外部文件列入 spec.files 并包含实际 SHA256。首次可先使用人工 box，无需运行 T1–T4。

```bash
python -m hre v2 create --prediction /data/A.png --reference /data/B.jpg --spec /data/G1.spec.json --case-root /data/case01/G1
python -m hre case start --case-root /data/case01/G1
python -m hre task export --case-root /data/case01/G1 --out /data/handoff
```

按当前任务读取真实 A/B 并获得诊断 JSON；以 `response import --payload` 导入后继续导出 Composer 任务。对所有阶段继续使用原来的手动通道，不把合成测试 payload 用于真实图：

```bash
python -m hre response import --case-root /data/case01/G1 --payload /data/actual_diagnosis.json --metadata /data/analysis_metadata.json
python -m hre task export --case-root /data/case01/G1 --out /data/handoff
python -m hre response import --case-root /data/case01/G1 --payload /data/actual_composition.json --metadata /data/analysis_metadata.json
python -m hre task export --case-root /data/case01/G1 --out /data/handoff
```

G1 Composer 选择 1–3 项有诊断证据的目标，动态英文文本最多 160 个词；local 任务只能包含局部目标。`reference_targets_v2.json` 记录来源，不能将测量转换成任意执行代码。G0 将 spec.arm_id 改为 G0，另建新目录后 start，直接进入 Execute。

G0/G1 的 **editor/** 目录恰好包含 `A.png`、`B.png`、`edit_prompt.txt`。只把这三个文件交给编辑器。analysis 包里的统计、彩色预览、ROI/T4、实验方法名不应额外传给编辑器。输出只接受第一个完整结果；不要点重生成来挑图。

候选 metadata 的 `model_observed.ui_model_name/transport/exact_model_version` 必须与冻结 Executor 的可观察身份一致；例如 `examples/candidate_metadata.json`。文件中实际生成次数和 provider_order 必须来自真实观察，不能照抄未知值。

每个 v2 arm 还必须提交 `executor_observation`：实际观察到的完整 Executor（包括 pipeline、adapter 和 settings）、操作者、带时区时间、交接步骤、实际 request、最终编辑文本、A/B（G2 另加 M）、原始下载输出与生成次数。缺失证明或实际设置偏离均拒绝入组。`request_sha256` 来自导出包 request.json；`prompt_sha256` 是 **editor/edit_prompt.txt 的字节 SHA256**，不是外层 prompt.txt；A/B 摘要来自规范化附件，output 摘要来自原始下载文件。G2 的 M 摘要来自 mask_transport_v2.json。未知值保留未知并暂停核实，不能用计划设置冒充实际观察。这是可追溯的人工观察记录，不是服务端模型身份认证。

```bash
python -m hre candidate import --case-root /data/case01/G1 --task-id ACTUAL_EXECUTE_TASK_ID --image /data/first_downloaded_C.png --metadata /data/candidate_metadata.json --submission submitted
python -m hre task export --case-root /data/case01/G1 --out /data/handoff
python -m hre response import --case-root /data/case01/G1 --payload /data/actual_verification.json --metadata /data/analysis_metadata.json
python -m hre v2 evaluate --case-root /data/case01/G1
python -m hre report --case-root /data/case01/G1
```

若是否提交未知，使用原来的 `task unknown` 或 `--submission unknown`，暂停核实，不自动重发。失败或超预算输出仍保留原始文件，不进入成功排名。v2 每臂只有 1 次生成预算。

## 3. ROI 与 Mask 的使用

`evaluation/reference_attributes_v2_revN.json` 是绑定状态 revision 的只读评价；索引文件可更新，历史结果不可覆盖。报告分区域给出 before、after、delta=before−after，正值表示参考属性距离缩小。色度是区域平均 a*/b* 距离，不是逐像素 ΔE00。近零 baseline 不输出相对收益；不可比/空区域、C 几何失败或内容未通过均为 not_assessable/null。跨属性不合成一个伪质量分数。

local spill 使用预先冻结的 EVAL_MASK，同时评价 G1/G2，包括区域外 L*/色度变化和边界变化代理量。它只说明变化发生在哪里，不自动判断幻觉或否决合法的全局色彩调整。

评价保留规范化 RGB8 图像，颜色转换按块/行执行；均值用 float64 累加，精确的全样本分位数使用一维 float32 L*/Y-prime 数组。不会为控制内存缩图或抽样。独立评审未通过或未解决时，最终 attributes/H3 清空为不可评价；流程 Verifier 的原结果另存为 workflow_attributes，仅作审计。

可以从已经冻结的 A ROI 产生新的准备材料，供**新 revision** 入组；不会修改当前 case.config 或其正式能力：

```bash
python -m hre v2 mask-from-roi --case-root /data/case01/G1 --roi-id wall --purpose EVAL_MASK --out annotations/wall_eval.npy
python -m hre v2 mask-from-roi --case-root /data/case01/G1 --roi-id wall --purpose EDIT_MASK --out annotations/wall_edit.npy
```

两份 mask 的合同不同，内部语义明确为 `0_preserve_1_allow_edit`。它们可以像素相同，但用途不能偷换。新 spec 将相应合同及实际文件列入 files，再创建新冻结 revision；旧 revision 不升级。

若使用 T4，先在 spec.tool_profile 冻结原 v1 的真实模型、权重、预处理和参数，允许工具中加入 T4_SEGMENTATION；诊断必须实际计划该工具和 ROI，然后按原 `tools export-missing/import-cache` 消费离线真实结果。

```bash
python -m hre v2 mask-from-t4 --case-root /data/case01/G1 --record /data/case01/G1/evidence/records/ACTUAL_RECORD.json --class-id 1 --roi-id wall --purpose EDIT_MASK --out annotations/t4_wall_edit.npy --erosion 0
```

只接收已诊断计划的 A 原生标签数组。model/revision/weights/preprocess/parameters/输入 SHA 均匹配才可消费。**本实现拒绝非 canonical A 尺寸的 T4 原生数组**；不自动把低分辨率标签图拉伸成“已对齐”Mask。此类缓存需另立明确的栅格化规则并生成可审计的 canonical 标签材料。彩色 segmentation overlay 不能当作内部 mask。

## 4. G2 能力闸门与交接

默认 G2 不可用。不能从 GPT Image API 的参数、Qwen 官网单图示例或 GUI 上传第三张图推断当前 Executor 支持 A+B+Mask。

真实 probe 记录格式由 `hre.masks.validate_mask_probe` 定义，至少包含简单区域、细边缘和保护区负例三项，实际 A/B/M/C、请求、交接和返回文件均需 hash 绑定。正例实际目标变化必须大于非目标变化；负例保护区漂移不能超过一个 RGB8 级。此阈值是功能探测门槛，**不是局部增强画质合格标准**。fixture proof 只在 simulation_only=true 下有效，不能用于真实实验。

```bash
python -m hre v2 probe --case-root /data/case01/G1 --proof /data/case01/G1/capability_probes/proof.json
python -m hre v2 capture-g1 --case-root /data/case01/G1 --out /data/paired_g1.json
```

G2 spec 必须冻结该 `paired_g1` 快照、相同 Executor/settings、同一 A/B/ROI/EVAL_MASK、局部 target ROI 与 EDIT_MASK，以及真实 probe 文件与全部依赖。G1/G2 的最终编辑文本必须逐字节相同；不能给 G2 另加更强指令。

- `separate_mask_image`：editor 增加独立 M.png；它是图片形式的软引导，不能称作原生 mask 参数。
- `native_mask_parameter`：A/B/text 仍在 editor，M.png 放在 transport；`mask_transport_v2.json` 明确指向独立参数。没有该接口的实际执行能力就不能运行。

G2 下载导入还需 candidate_metadata.mask_delivery 指向真实 `mask_delivery_v2` 记录，绑定 request、实际 A/B/M、同一 prompt、executor、原始 transport request/response 和原始输出 SHA。只勾选“已送达”不够。即使绕过 desktop 直接提交协议，Controller 入口仍验证交接证明。接收清单必须同时提交完整执行观察、交接审计、receipt、原始 request/response 和编码 M；这些文件复制到不可变 submission，接收事务另绑定 done.json 摘要。清理临时交接目录后仍可核验；丢失或修改已提交证明会使恢复失败。所有模式均声明 soft guidance，不声称边界被硬锁定。

## 5. 冻结 R1/R2、盲评与决策

输入 case 先在无生成结果、无已消耗预算时登记。模板见 `examples/run_manifest.json`。R1 3–5 对、R2 12 对；`R0_fixture` 仅接收模拟数据，不能冒充 R1。R3 才可使用 test；同场景/输入不能跨 split。每个计划 case 都保留 G0/G1/G2 行，不适用或无能力的 G2 记录 skipped 原因。

```bash
python -m hre v2 run-freeze --manifest /data/run_manifest.json --out /data/runs/r1_revision1
python -m hre v2 run-status --run /data/runs/r1_revision1
python -m hre v2 run-prepare --run /data/runs/r1_revision1 --case-id case01 --arm G0
python -m hre v2 run-prepare --run /data/runs/r1_revision1 --case-id case01 --arm G1
```

按冻结 execution_order 执行图像生成；可先做 G1 的诊断/Compose 以冻结文本，再按随机顺序生成。准备 G2 时，G1 必须已有唯一的 Execute prompt。Controller 任务的执行、导出、提交、候选和验证命令与前节相同。冻结后改变代码/模板/evaluator、ROI、mask 或模型必须创建新 run revision。

```bash
python -m hre v2 blind-export --run /data/runs/r1_revision1 --out /data/review/r1_revision1
python -m hre v2 analyze --run /data/runs/r1_revision1 --ratings /data/review/actual_ratings.json
```

评审包与 private mapping 必须分开。每项只显示 A/B/匿名 C 和统一区域信息，不显示 arm、prompt、模型/工具/EDIT_MASK 或流程 Verifier。box/polygon 保留坐标，mask 形状的评价区域导出为匿名白色目标 PNG，各 arm 一致。失败/缺候选以 A 作为交付回退，但失败事实保留在 private ITT。最终评审必须由两名独立评审者完成；分歧需第三人 adjudication，否则 unknown，不算成功。run.excluded_rater_ids 登记生成者/Composer/操作者，防止其以独立评审身份提交。样例 `examples/ratings.json` 为空评审，只能产生 unknown，不能复制成通过结果。

严重缺陷必须是结构化记录，例如 `{"category":"identity","severity":"critical","observation":"实际观察到的身份变化"}`。category 仅可为 identity、text、geometry、scene_content、content_transfer、seam、color_artifact、clipping、other；具体说明写在 observation，不能把任意短语当 category。无严重缺陷填空列表；存在严重缺陷不能同时声明 content=pass。

输出包括每个计划行、eligible/capable/skipped 数量、joint_success、成对 win/tie/loss/unknown、H3 属性方向冲突、失败原因和可观察成本。R1 至少需要同一 case 的 G0/G1 都完成、内容独立通过、ROI 可评价且至少一臂成功，才能建议 GO_TO_R2；单个未配对成功不能升级，R1 也不会设置 real_effect_validated。

`decision/H1_decision` 只针对 G1 vs G0；`H2_decision` 单独针对 G2 vs G1。H2 需要至少 6 个完成并有明确独立结论的能力合格局部配对、至少 2 个盲评偏好 G2 且属性更接近或区域外变化减少的样例，并且 G2 无严重缺陷。区域外减少使用 0.1 L*/a*b* 单位的工程阈值，完整条件记录在结果中。无能力时 H2=SKIPPED，不阻断 G0/G1；G2 严重缺陷会单独 STOP。R2 GO 是预声明的工程净收益启发式，不能称统计显著性。workflow.success 和 ROI 指标不代替独立评审。

## 6. 本分支的验收边界

代码、离线协议和合成数值测试可以在本地 CPU 运行。v2 最低引擎版本为 0.2.0；执行模板带显式版本合同，不能把 v2 case 交给旧引擎当成普通 direct_ref 执行。真实 R1/R2 仍需要用户真实 A/B、实际编辑器首个完整 C、可观察的模型/交接事实和独立评审。本仓库未包含这些数据，交付中不声称已取得真实增强收益或生产 Mask 能力。主分支与 PR #2 的已有分叉仍需单独集成，不覆盖其 engine/Data。
