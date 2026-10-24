# Independent review — HarnessIR / 2026-10-24

- `independence=same-family`
- `acceptance=provisional`
- 原始基线：`e1b610ef034d467c8c9172e530d38a930956a3bb`。
- 审查范围：当前未提交代码差异，`research/model_aware_20261024` 的 01/03/04/05，统计脚本及新增测试。未参与初始方案生成；本次提出审查反馈后，主代理修改了代码和协议，我复核了修改。不是人类评估、跨模型家族评估，也不是对方案身份未知的盲审。
- 未修改仓库源码；仅创建本报告及仓库外的审查 probe/日志。02 的官方身份核验由另一代理负责，本报告不冒称重新验证了所有外部官方来源。

## 决定

多类型 verifier 的一行函数名修复正确。新增 decoded-native 存档在受测的正常 RGB/PNG 路径上保持交付像素不变；审查中发现的两个异常路径问题已修复并复验。统计脚本按 image 内重复、scene 内 image、scene 间 bootstrap 处理，没有把 seed/裁块当独立 scene；交互按相同场景的策略差中差计算，并检查跨模型 image/replicate cohort。

可暂定接受这些软件修复和研究协议草案。不能接受“模型质量提升已成立”“五阶段都必须 model-aware”“已等总成本验证”“已完成科学复现”等结论。当前质量实验和独立人类图像评价均未发生。

## 尚存阻塞与高风险

### B1 / 阻塞：没有可执行的真实模型环境或质量数据

本次独立环境检查得到 `torch=false,diffusers=false,transformers=false`，没有 HARNESS/HRE 的 API/MODEL/URL 环境配置名称。未调用真实 NB2/Qwen，也没有取得用户那次运行的完整版本、参数、prompt、原生结果和逐轮 trace。因此无法对 F001 的实际 Qwen/NB2 差异归因，不能判定 executor 上限。位置：`05_failure_casebook.md:13`、`:20`、`:25`，`04_experiment_plan.md:7`。当前 unknown/作者或用户报告/实际观察的措辞恰当。

### R1 / 高：当前 runner 尚不能直接支撑等总预算确认实验

`harness/clients.py:52` 的 `_retry` 对异常重试，`:223`–`:237` 的图像调用只有最终返回图，没有每个 transport attempt/可能已计费生成的独立 ledger；`harness/pipeline.py:225`–`:228` 仍只记逻辑 `mfm_calls=1`。这不是本轮新增回归，但真实运行时会使“候选 K 相同”与总调用/成本相同脱节。04 新增 `:94` 已正确承认区别，尚未实现或测量配平。

解锁条件：真实模型试验前落实每次提交、重试、超时未知计费、返回候选、VLM tokens/费用/耗时的记录与上限；否则仅可声称候选预算相同，并报告质量–成本结果。

### R2 / 高：确认检验仍需真实冻结包与独立评价执行

04 的 `:65`、`:92`、`:93`、`:95`、`:97` 已改善主终点、交互、失败选择偏差和功效定义，但它仍是候选协议。实际数据来源/scene 分组、policy 文本/长度档、主检验 family（H2 同时包含交互与 Qwen 主效应）、alpha 分配/多重比较、δ/非劣界、缺失敏感性规则、人工偏好 CI 的实现与样本量计算尚未冻结验证。仅写“H1/H2 Holm”不等于完成这些分析。

`04_experiment_plan.md:69` 的至少三位独立评价者、匿名顺序与一致性流程合理；当前没有这些评分。`03_model_stage_matrix.md:34` 正确禁止 verifier 单次自述被当根因。解锁条件是冻结上述文件/hash、建立独立测试保管和评价流程，并按真实主 contrast 和保真稀有错误精度确定 N。不能从目前软件通过推导确认结果。

## 中低风险与边界

### M1 / 中：完整三端点 trace 合同尚未实现

`harness/stages/execute.py:99`–`:115` 保存 native 图及其 hash，只记录输入路径/尺寸；`:160`–`:169` 的 geometry-normalized 图仍写入将被颜色处理覆盖的交付路径。`harness/pipeline.py:243`–`:252`、`run_baseline.py:99`–`:105` 仍原位颜色处理。因此 `04_experiment_plan.md:85` 要求的输入字节 hash 与 native/geometry-normalized/delivered 三端点图及 hash 尚不齐全；无法靠当前落盘文件完全分开几何与颜色效应。F003 `:38`–`:39` 没有夸大本轮实现，措辞可接受。

真实 E4 前应补该端点合同或明确这是阻塞。`native_archive_complete` 仅表示 native 存档成功，不能用于判定整个 trace/实验完整性；当前命名已比审查中间版 `audit_complete` 准确。

### M2 / 中：条件质量效果不能自动推广到全冻结群体

脚本 `analyze_pairs.py:24`、`:34`、`:36` 拒绝 non-OK、非配对或不符 expected cohort 的输入，适合明确登记的完整质量 cohort。失败本身可能由策略引起，故共同成功样本上的改善并非全体改善。04 `:93` 已承认 post-treatment selection bias、增加 failure 非劣界和敏感性要求；这些尚未执行。任何由输出是否好看来重建 expected cohort 的行为仍会破坏因果解释。`cohort_bound=true` 只证明与给定清单匹配，不证明清单在输出前冻结或数据可信。

### L1 / 低：小 N fixture 的 bootstrap CI 不是可靠实际功效证明

`analyze_pairs.py:50` 允许两个 scene，这适合确定性 fixture；不能把两 scene 的狭窄/退化 percentile CI 解释为总体质量证据。04 `:53`、`:97` 的功效/精度门槛应决定真实入组量。统计脚本只做单指标 mean contrast 的 cluster bootstrap；未实现多重比较、盲评可靠性、失败界限或成本分析，04 `:63` 已如实说明。

## 审查前发现、当前已解决

| 初始问题 | 最终状态与位置 | 复验 |
|---|---|---|
| native 存档目录写失败时，一张已经生成且原本能交付的图被整个 S4 异常丢弃 | `execute.py:110`–`:119` 捕获存档 OSError，记录 `archive_error`/`native_archive_complete=false`，继续交付 | 用文件占据 `raw_outputs`：正常交付，审计失败明确可见 |
| native 成功后，下游交付保存失败，异常返回丢失 native 回执 | `execute.py:144` 初始化并在 `:181` 异常返回保留 native 元数据 | 用目录占据 `output.png`：交付失败、native 文件与 hash 仍在回执 |
| 只检查两臂对称性，两臂同时漏掉同一困难 scene 仍会出统计结果 | `analyze_pairs.py:36`–`:39` 比对 expected；CLI `:86` 强制 `--cohort`；API `:64` 标明是否绑定 | 冻结 cohort 包含 c、两臂均无 c：拒绝；CLI exit 1 |
| 主 paired/noGT 终点由 OR 连接；完例效果与全体效果、K 与总预算、交互功效方差边界不明确 | 04 `:65`、`:92`–`:97` 已分别固定或明确冻结/实施要求 | 静态复核通过；不是这些分析已经运行 |

审查中曾在主代理新增 expected-cohort 测试、尚未完成对应实现的瞬间看到一次 `TypeError: summarize() got an unexpected keyword argument 'expected'`；最终实现后重跑 10 项全部通过，不把该中间状态算作当前缺陷。

## 具体验证结果

- `harness/types.py:186` 调用已存在的 `_colour_clause_verify`，与单类型 verify 在 `:213` 的选择一致；五种合法类型的全部 31 个非空组合均能构建 verifier。此修复不会触发单元素 `['mix']` 的多类型分支，也不能解释所有用户 Qwen 效果。
- 将原始 base 的 execute/baseline 源码动态装入隔离模块，使用非均匀 RGB 测试图及确定性 fake editor：execute 的 crop/不 crop 两路，baseline 的 square 开关 × color-adjust 开关四路，修改前后交付 `tobytes()` 全部相同。这是有限软件路径验证，不是任意 PIL 模式或生成模型画质的证明。
- 新增 unittest 共 10 项通过；`git diff --check` 通过。
- CLI 在合成 arithmetic fixture 上得到预期差中差并输出 `cohort_bound=true`，整 scene 漏失被拒绝；跨模型 sample 身份错配也被拒绝。这里的数字仅用于计算正确性检查，不能进入任何模型成绩表。
- 已目视检查 LQ caseboard。05 `:11` 只描述可见拖影/暗部/光源，没有从单图断言唯一物理退化原因；`:23` 对未知字符/轮辐保留 unverifiable，恰当。
- 01 `:61`、05 `:32`/`:39` 明确软件复现不支持画质收益；03 `:11` 明确差异化只是候选。未发现把本轮单测包装成生成质量证据的措辞。

## 已运行命令与可复现证据

工作目录 `/workspace/scratch/7d29333b7554/HarnessIR`。主要命令：

```bash
git status --short
git diff e1b610ef034d467c8c9172e530d38a930956a3bb -- harness/stages/execute.py harness/types.py run_baseline.py
git diff --check
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/workspace/scratch/7d29333b7554/testdeps:. python -m unittest discover -s tests -v > /workspace/scratch/7d29333b7554/independent_review_unittest.txt 2>&1
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/workspace/scratch/7d29333b7554/testdeps:. python /workspace/scratch/7d29333b7554/independent_review_probe.py > /workspace/scratch/7d29333b7554/independent_review_probe.txt
```

另外用 `nl -ba`/`rg` 读取上述报告、代码和测试；用 Python `importlib.util.find_spec` 检查运行依赖，只列出相关环境变量名称，未读取或打印凭据。完整 probe 源码和结果分别在：

- `/workspace/scratch/7d29333b7554/independent_review_probe.py`
- `/workspace/scratch/7d29333b7554/independent_review_probe.txt`
- `/workspace/scratch/7d29333b7554/independent_review_unittest.txt`

未运行原有 engine 全套回归，因为本轮未改 engine，且本审查的结论针对原始单图 harness 的改动；不冒认其他代理运行的 engine 检查为本人的验证。
