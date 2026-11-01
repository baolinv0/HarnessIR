# VLM 调用与分阶段能力：服务器实验计划

版本 1.0｜2026-10-24｜工程选择实验，不作通用模型排名。

## 1. 要解决的两个问题

C1：在正确分流、足够预算下，哪套配置能稳定给出真实、有用的视觉差异？区分接口失败与模型观察失败。
C2：更好的诊断能否形成更合理的 action；哪一个 VLM 更适合独立判别结果？D/P/J 分开选模型，不默认最大模型包办。

反对解释：更多 obs 只是拆句/幻觉；增益来自多个参数同时改变；构图差异被错误转成裁切 action；Judge 只偏好更亮/更长解释。

不做：训练、新增编辑器、全参数网格、自动选最好 seed、以 VLM 自评分证明自己、重复测所有失败部署方式。

## 2. S0：准备与调用核验（先做，约 3 次）

### 2.1 冻结环境

记录实际 repo SHA、本地修改 patch、权重完整 ID 与 revision、量化/dtype、vLLM/Transformers/Torch/CUDA 版本、GPU/TP、chat template、启动命令、parser、上下文长度、图像预处理与 max-num-seqs。32B 暂按 Qwen3-VL-32B-Instruct；若服务器不同，替换并明确记录，不能沿用型号标签。

`max-num-seqs=512` 只是已知环境的可用配置，不是架构固定要求。使用现有已跑通启动命令，只记录必要变动。不同权重无需同一量化，但不同量化时结论只覆盖该部署组合。每个服务先预热一次，不计入时延。

建议取证命令（只保存需要的版本信息，不导出完整环境变量）：

```bash
git rev-parse HEAD
git diff --stat
python -m pip show vllm transformers torch
nvidia-smi
hre lab --help
```

### 2.2 模型配置与参数传递

用本目录 models.example.json。端口 8027/8032/8008 是示例，改成实际地址；model 必须匹配服务 served-model-name。需要鉴权时仅添加 api_key_env，密钥不写配置。

Stage Lab 的 parameters 直接进入 HTTP body：top_k 和 chat_template_kwargs 放其中，**不要在 parameters 中加 extra_body**。extra_body 只是 OpenAI Python SDK 调用时的包装。

本轮所有配置：单请求、stream=false、max_tokens=8192、seed=17 或 29；相同图片字节、图像顺序、任务、阶段 prompt、视觉预处理策略。冻结 response_format=json_object（若服务不兼容，则所有对照臂统一取消并记录，不能仅对失败臂偷偷切换）。同一模型温度对照保持所有其他设置相同。

27B 开启服务端 parser，使用当前已验证的 qwen3；未来换 vLLM 版本需重核 parser 支持。Instruct 不传 thinking 开关。不要把“API 接受了参数”当作“参数确实生效”，检查请求及服务模板/日志。

### 2.3 三次 smoke

同一开发案例，每个模型家族一条：27B q27_t06，32B q32_t02，8B q8_t02。检查：

- 请求包含 A/B 图像，而非只有路径文本；A 是内容基底、B 是外观参考。
- 27B reasoning 与最终 content 已分离；记录字段存在性与长度即可。不要把 reasoning 拼回 JSON。
- content 可解析为对象，包含阶段要求字段；区分裸 JSON、去单层代码围栏后合法、schema 不符、截断、HTTP/服务错误。
- 保存 finish_reason、usage、时延、请求 ID。若 token 细分未返回，填 NA，不从字符数伪造 token。

核对过的 Stage Lab provider 会保留 content、usage 和 finish_reasons，但**不保存完整 HTTP 响应和 reasoning 字段**。服务器实现时，在 `_openai` 收到响应后增加一份原始响应落盘（或在已有请求包装层落盘），至少保留最终 content、字段长度、finish_reason、usage、请求参数；不要为补日志额外发起第二次推理并冒充同一请求。此为取证补充要求，不是本包已实现的功能。API 密钥不入日志。

解析失败记不可用，observations 数量记 NA，不记 0；合法空数组才是 0。stage_lab 的 run success 也不能代替 schema 合格。

失败只修服务/协议，再重复该 smoke；不要先关 thinking 掩盖问题。8192 仍截断时，在开发阶段提高到 16384 并为相关对照整组重跑，记录新版本。运行时错误重试保留原记录，不自动修补内容。

## 3. 数据：2 张开发 + 4 张确认，预先固定

一个 case 指一对 A/B。原始 A/B 不需要同构图，但必须记录可比区域。确认集不能参与参数挑选。

| case | split | 建议内容 | 重点 |
|---|---|---|---|
| dev01 | dev | 已有 print-shop 人物案例 | 裁切/可见内容与亮度色温的区分 |
| dev02 | dev | 逆光或夜景人像 | 人物与背景关系、阴影信息边界 |
| hold01 | confirm | 新的混合光室内 | 局部色偏与全局 WB |
| hold02 | confirm | 新的逆光人像 | 肤色/人物亮度/背景高光 |
| hold03 | confirm | 新的夜间街景 | 光晕/剪切/暗部，勿臆造细节 |
| hold04 | confirm | 自然场景或不同构图同场景 | 渲染差异与内容占比的混淆 |

若缺少某类，选现有素材并记录替代；不要等待“完美数据集”。同一场景的相邻帧尽量不要跨 split。

看模型结果前，为每个 case 写 4–8 个关键事实：区域、属性、方向、证据位置、可比性、是否关键。保留不可确定项。它是人工参考清单，不宣称穷尽真值；模型发现新事实可由盲审补入，再对所有臂统一重算。

任务固定为：借鉴 B 的亮度、颜色与影调来改善 A；保持 A 的内容与构图，区别不可比的内容/视角差异；不过度限定最终调节幅度。D 不给 action，P 再判断哪些差异适合迁移。

## 4. S1：D 开发集温度/模式筛选（28 次）

2 case × 7 配置 × 2 seed（17、29）。配置如下；不要把不同家族比较解释成仅参数规模效应。

| ID | 模型 | thinking | temp | top_p/top_k | presence/repetition penalty | 目的 |
|---|---|---|---|---|---|---|
| q27_t06 | Qwen3.8-27B | on | 0.6 | .95/20 | 0/1 | 当前有效配置 |
| q27_t10 | 同上 | on | 1.0 | .95/20 | 0/1 | 仅改温度 |
| q27_off | 同上 | off | .7 | .8/20 | 1.5/1 | 非思考完整配方基线 |
| q32_t02 | Qwen3-VL-32B-Instruct | 不传 | .2 | .8/20 | 1.5/1 | 低温对照 |
| q32_t07 | 同上 | 不传 | .7 | .8/20 | 1.5/1 | 仅改温度 |
| q8_t02 | Qwen3-VL-8B-Instruct | 不传 | .2 | .8/20 | 1.5/1 | 低温对照 |
| q8_t07 | 同上 | 不传 | .7 | .8/20 | 1.5/1 | 仅改温度 |

所有 min_p=0。官方视觉采样参考见第 10 节；8192 是工程预算，不是宣称完整复现官方所有生成设置。若你当前低温配置的其他参数不同，先保存历史快照；本表的温度对照是在统一的其他参数下进行，不能用旧结果混入。

q27_off 对 thinking 配置的比较改变了模式和采样配方，回答“哪套完整用法适合任务”，**不能单独证明 thinking 的因果增益**。如确需分离该原因，再加一个与 q27_t06 完全同参数仅关闭 thinking 的臂；不是默认必跑。

### D 如何评分

以原子观察为单位；同一事实换措辞/拆句只计一次。每条标注 supported / contradicted / unverifiable，并标记 relevant、critical、duplicate、fact_id。

- 原始严格 JSON 成功率、仅去围栏后成功率、字段合格率分别报告；分母为所有预定请求（失败不删除）。禁止 LLM 修复后算原始成功。
- 观察正确率 = supported / (supported + contradicted)；不可核实比例 = unverifiable / 全部去重观察。分母为 0 则 NA。
- 关键事实覆盖率 = 命中人工关键 fact_id 数 / 人工关键 fact_id 总数；每 case 算，再宏平均。端到端覆盖率中不可解析结果按未覆盖计，同时单列可解析条件下覆盖率。
- 有效观察数 = supported 且 relevant 的去重条数；不等于原始 obs。
- 关键错误：把 B 内容当 A、把裁切当影调、虚构文字/身份/细节、把不可比区域当可比。逐条展示。
- seed 稳定性：两次关键 fact_id 交集/并集（全空记 NA），报告关键 action 方向有无翻转，不以字面相似度代替。
- 效率：预热后串行请求端到端秒数、总输出 token、可得的 reasoning/final token。不同 tokenizer 的 token 不是统一计算量单位。

人工盲审隐藏模型及温度，随机排列；至少工程负责人核对全部关键错误。有第二位同事时复核分歧和约 20% 条目；没有则注明单人审核，不能称独立验证。

### 选择规则（工程约定，不是统计定律）

每家族选一配置：优先完成输出且无未解决关键错误，其次关键覆盖与有效观察，再看时延。开发集只有 4 请求/臂，只支持初筛。温度 .7 没有明确质量收益则保留较稳定的 .2；27B 若 .6 已充分有效，无须因为官方值是 1.0 就强制替换。冻结选择，再看确认集。

## 5. S2：D 确认集（24 次）

4 case × 每家族选定配置（3）× 2 seed。输入、prompt 与采样按 S1 冻结。逐 case 展示 A/B、并排 summary、共同事实/独有正确事实/冲突/遗漏，不输出仅一张平均分排行榜。

若出现关键错误，明确失败场景；只修解析/服务问题可重跑，修改 prompt/配置属于新版本，旧结果保留。不得在 holdout 上选温度后继续称独立确认集。

工程决策：如果 27B 新增真实关键事实，且未增加关键错误，可以选为 D 默认；优势不足则按质量-延迟折中选择。小样本只作当前工作流决策，不宣称显著领先。

## 6. S3：P 单独测试 + D→P 传播（18 次）

固定 hold01、hold02、hold03，seed=17，editor profile=qwen21。首次失败保留，不挑最好 seed。

P-isolated：每 case 人工编写一份统一观察 JSON（真实差异、不可比区域与不确定性，尽量覆盖 D 的主要信息），作为相同 context 交给三个选定 VLM，共 9 次。检验规划能力，不受各自 D 输出影响。

D-to-P：每 case 使用三个 D 模型的 seed17 结果，交给**同一个**规划模型，共 9 次。规划模型在 P-isolated 结束后按正确性选定并冻结，记录选择理由；这 9 次是开发传播分析，不是新的独立泛化验证。不提供 D 模型名称；如需 import 为 manual，清楚保留源 run 映射。

审核每个 action：观察来源、采纳/修正/拒绝是否合理、目标区域、属性方向、前背景关系、保留内容、预期效果、失败征兆。奖励纠正错误观察，不奖励机械复述。

特别检查 print-shop 类差异：发现 B 更紧凑，应影响 ROI 可比性判断；任务保持 A 构图时不能因此要求裁切 A。局部偏绿不自动导出全局去绿。

报告：关键 action 错误/请求、有效 action 数、支持事实到 action 的利用、无根据 action、遗漏关键可编辑差异。D-to-P 中能直接看 A/B，规划器可能自己纠错；因此测的是“诊断在现有视觉规划器上的增量影响”，不是纯文本因果传播。

## 7. S4：J 独立判别（27 次，无需先生成图片）

同样三个 hold case，每 case 准备 3 个候选 × 3 个选定 VLM × seed17。

- C0=A 的原始副本：已知没有编辑，不应声称曝光/颜色改善。
- C1=确定性温和调节：例如固定 gamma 或 ROI gain，保存操作、参数和 mask；人工确认实际变化方向。它不自动是“好图”。
- C2=C1 加一项明确内容损坏：如擦除固定文字/改变物体局部形状；保存损坏 ROI。选择三模型实际输入分辨率下可见的缺陷，避免把不可见细节漏检当推理失败。

操作记录和标签对 J 隐藏；候选使用中性文件名。对所有模型给完全相同 A/B/C、任务与判别 prompt，不给 D/P 结论或候选作者。单张候选独立调用，避免排序位置偏差。

预先人工标注 C0 的 unchanged、C1 的实际变化方向与保真状态、C2 的损坏位置与性质；参考风格是否改善允许 uncertain，不因“确定性调节”预设 improved。

报告：C0 假改善数/3；C2 损坏检出数/3；C1 变化方向判断正确数/3；关键区域证据正确性；reference_alignment/content_preservation/coordination 分开显示。小分母同时列分子，禁止只报百分比。模型间一致不代表真值；长解释不代表判对。

J 作为独立选择，可与 D/P 不同。若三个都漏掉关键损坏，保留人工复核，不开启自动放行。

## 8. S5：可选 C/E 小规模验证（12 张生成；不阻塞前四步）

仅当需要回答“更好的 D/P 是否提升图像”时做。选两个有代表性的确认案例，在同一 Qwen-Image-2.1、同一编译路径、同一分辨率/steps/true_cfg/量化下：

1. 人工简洁 direct prompt。
2. 当前生产 D/P 配方（开始实验时冻结；如没有则使用 q8_t02 D→P 并明确记录）。
3. 新选定 D/P 配方。

2 case × 3 条件 × 2 图像 seed（42、43）=12 张。使用固定 seed17 的 D/P，不挑选最漂亮的文字输出。PE-I2I 开或关保持各臂一致：默认直接用 P.edit_prompt 执行，不加重写；若已有生产必须 PE，则三臂同用 PE，另存原始/编译后条件并检查遗漏、增加与目标变化。

C 检查角色 A/B、目标区域、内容约束和意图变化；E 看目标执行、参考属性跟随、内容保真和区域协调。不能为了更像 B 裁掉 A 内容。人工盲审全部 12 张；已测 J 可辅助，不能当唯一真值。两 seed 同方向才称稳定候选收益，否则记混合结果。

若 D/P 更好但 E 不变：说明当前执行器/条件转换可能成为瓶颈，不要继续仅增加诊断文字。若 C 丢目标，先修 C；若 C 保留而 E 不执行，进入独立 executor capacity probe。

## 9. 服务器操作顺序与交付

本计划针对 `feat/stage-model-lab-20261022`；文档与测试台在同一分支。在该分支的服务器工作树运行，记录实际 SHA。确认 `hre lab --help` 有下面子命令。参数示例来自已核对实现；本地扩展可用但记录差异。

```bash
# 在 feat/stage-model-lab-20261022 工作树中执行
cp docs/experiments/vlm_stage_calibration_20261024/models.example.json models.vlm.local.json
# 先编辑模型 ID/base_url；然后生成配对 seed 配置
python - <<'PYCODE'
import json
from pathlib import Path
base=json.loads(Path('models.vlm.local.json').read_text())
for seed in (17,29):
    cfg=json.loads(json.dumps(base))
    for m in cfg.values(): m['parameters']['seed']=seed
    Path(f'models.vlm.s{seed}.json').write_text(json.dumps(cfg,indent=2))
PYCODE
hre lab init --root Data/vlm_calibration_s17 --models models.vlm.s17.json
hre lab init --root Data/vlm_calibration_s29 --models models.vlm.s29.json
# 为每个 root 注册同样 6 对图，下面仅展示一例，路径必须替换
hre lab add-case --root Data/vlm_calibration_s17 --case-id dev01   --prediction /absolute/path/A.png --reference /absolute/path/B.png   --task '借鉴 B 的亮度、颜色与影调来改善 A，保持 A 的内容与构图，区别不可比的内容与视角差异'
# 同样注册到 s29；登记 cases.csv，不能用不同图片代替同一 case
hre lab run --root Data/vlm_calibration_s17 --case-id dev01 --stage diagnose   --models q27_t06 q27_t10 q27_off q32_t02 q32_t07 q8_t02 q8_t07
```

按同样命令跑 dev02 和 s29；S2 仅用冻结后的三个 ID，逐个跑 hold01–04。每个 case×stage×arm×seed 为一条 runs.csv。测试台不会自动去重跳过已有 run，重跑前查 runs，续跑只补未完成项；重试保留 attempt_id。

```bash
hre lab runs --root Data/vlm_calibration_s17 --case-id hold01 --stage diagnose
# P-isolated：shared-observations.json 内容形如 {"observations":[...],"uncertainties":[...]}
hre lab run --root Data/vlm_calibration_s17 --case-id hold01 --stage plan   --models SELECTED_27 SELECTED_32 SELECTED_8 --profile qwen21   --context shared-observations.json
# D-to-P：替换各 D_RUN ID，三个来源 × 一个固定规划器
hre lab run --root Data/vlm_calibration_s17 --case-id hold01 --stage plan   --models FIXED_PLANNER --profile qwen21 --from-run D_RUN_27 D_RUN_32 D_RUN_8
# 独立 J：三个候选 × 三个模型 = 九次，不加 combine-sources
hre lab run --root Data/vlm_calibration_s17 --case-id hold01 --stage judge   --models SELECTED_27 SELECTED_32 SELECTED_8   --candidate /path/C0.png /path/C1.png /path/C2.png
hre lab report --root Data/vlm_calibration_s17 --out Data/vlm_calibration_s17/comparison.html
hre lab report --root Data/vlm_calibration_s29 --out Data/vlm_calibration_s29/comparison.html
```

SELECTED_*、FIXED_PLANNER、D_RUN_* 均为占位符。禁止 `--combine-sources` 把三个诊断合在一起，否则改变实验问题。所有模型能分批加载，顺序调用，不要求三者同时驻留 GPU。跨模型不同预处理无法完全相同时记录视觉 token/resize，不能假设输入可见细节完全等同。

### 预算与停止条件

| 步骤 | 真实调用数 | 输出 |
|---|---:|---|
| S0 | 3（另有预热） | 协议核验 |
| S1 | 28 | 开发集参数选择 |
| S2 | 24 | 确认集 D 对比 |
| S3 | 18 | P 与 D→P |
| S4 | 27 | J 判别 |
| 核心合计 | 100 | 不含预热/重试，不生成图片 |
| S5 可选 | 12 张 | C/E 下游验证；新增 D/P/C/J 调用另记 |

S0 若与 S1 完全同配置、输入、日志要求，可复用对应 3 次，总新增 97 次。已有历史结果只有全部条件可核实时才能复用。

先实测每个模型一次耗时，再用 各臂请求数×该臂平均秒数 求和估算串行时间；GPU 小时按占用设备数计，加载/预热另记。未知道硬件前不承诺运行分钟数。出现明确质量差且无成本优势的配置不扩展；没有实质差别就选便宜稳定者。不为统计显著性追加大批样本。

### 每阶段可视化与返回包

D：A/B 并排 + 原子事实共同/独有/冲突表；P：观察→采纳/拒绝→action 对照；J：A/B/C、缺陷 ROI 与三模型判断并排；可选 E：同 seed 三臂图片与局部放大。现有 HTML 展示原始输出，语义归类由 observations.csv 与报告人工填写，测试台不会自动计算这些人工指标。

返回 REPORT.md、runs.csv、observations.csv、cases.csv、已脱敏模型配置与启动命令、人工关键事实表、所有请求/最终输出/运行日志、两个 comparison.html；S4 附候选和隐藏操作标签，S5 附全部 12 张图片。图片保留本地完整包或受控下载链接，不要求大图提交 GitHub。不要只回传截图/平均分；失败同样保留。尚未执行项写 NOT_RUN，缺字段写 NA 并说明原因。

## 10. 一手依据与适用边界

核对日期 2026-10-24；服务器需另外保存自己 checkpoint revision 下的模型卡与 generation_config，不把网页 main 的变化当作本地权重变化。

- [Qwen3.8-27B 模型卡](https://huggingface.co/Qwen/Qwen3.8-27B)：当前 thinking 推荐 temp=1.0、top_p=.95、top_k=20；非 thinking 推荐 .7/.8/20，presence_penalty=1.5。当前 .6 作为已验证工程候选，不称官方推荐。
- [Qwen3-VL-32B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-32B-Instruct) 与 [8B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct)：视觉任务 .7/.8/20、presence_penalty=1.5、repetition_penalty=1.0；两者是 Instruct 权重，不传 thinking 开关。
- [vLLM reasoning outputs](https://docs.vllm.ai/en/stable/features/reasoning_outputs/)：parser 分离输出；不是 JSON 合法性或诊断正确性的保证。
- [vLLM structured outputs](https://docs.vllm.ai/en/latest/features/structured_outputs/)：具体格式支持随服务版本变化，保存实际请求与版本。
- [Stage Lab 文档](https://github.com/baolinv0/HarnessIR/blob/8636e25ad68dcb309961241bb9da454ed7ef0347/docs/stage_lab/README.md)：本计划 CLI 与五阶段协议来源。

本实验不检验“低温必然复读/永不复读”，不把 reasoning 长度当能力指标，不由 6 对图推出通用模型排名。
