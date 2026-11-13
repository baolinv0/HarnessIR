# HarnessRefEnhance Implementation Plan

> **For agentic workers:** 用任务级实现与审查执行本计划。步骤使用 checkbox 跟踪；可使用 superpowers:subagent-driven-development 或 superpowers:executing-plans。本交付尚未执行这些产品实现任务。

**Goal:** 将冻结 prediction A 与非对齐 reference B 组织成可恢复、可追溯的参考引导增强实验，用户只处理缺失输入与桌面能力未覆盖的交接。

**Architecture:** 独立 `engine/src/hre/`，Controller 是唯一状态写入者；角色执行者只消费任务并返回响应。缓存预生成与 case 的按需消费分离；桌面适配器依据实测 capability 使用文件交接或手动导入。

**Tech Stack:** Python 3.10+、Streamlit、Pydantic v2、Jinja2 StrictUndefined、jsonschema Draft 2020-12、Pillow；工具推理依赖置于独立环境，非 Controller 必装。

**Spec:** [公共合同](00_SHARED_CONTRACT.md)、[PRD](01_PRD.md)、[状态与协议](02_STATE_AND_PROTOCOL.md)、[Prompts](03_PROMPTS.md)、[实验](04_EXPERIMENTS.md)。

## Global Constraints

- `schema_version=ref_enhance_v1`；A 为唯一编辑主图；B 为外观参考；每次生成仍用冻结 A+B。
- `max_generations=3,format_repair_limit=1`；round 从 0 开始；已提交的失败生成也计预算，传输重发不重复计费。
- 无 API；不假定桌面自动读写、会话派发或自动存图；未经探测通过的能力保持关闭。
- 默认 geometry strict；禁止 in-place color_adjust、warp、内容复制；raw/canonical/评审派生图各自存档。
- success 只能由冻结的接受规则产生；预算用尽、结束、拿到图像均不等于成功。
- 保留既有 `harness/`、`engine/` 实现、`Data/` 和历史 cases；新旧 schema/state 不混用。

## Review Focus

1. A/B 同名但 bytes 不同：不能命中错误缓存或接收旧会话响应（M1/M3）。
2. 存图成功、done 未完成或重启时事务未提交：不得提前推进，不重复提交生成（M2）。
3. 合法外观改变导致 SSIM/chroma 变化：不当成几何破坏；裁剪/换场景必须拒绝（M4）。
4. reference 中人物移动/窗口光线变化：标不可比较，不让 Composer 复制参考内容（M3/M4）。
5. Verifier 串行响应的状态已过期、critical defects 与 pass 矛盾：拒收或拒绝成功，最终图与报告一致（M2/M5）。

## 文件与职责

| 路径（拟创建） | 职责 |
|---|---|
| `engine/pyproject.toml` | controller依赖、`hre` CLI入口；已有文件则增量编辑 |
| `engine/src/hre/models.py`、`schemas/` | 类型与本包schema的同名字段 |
| `engine/src/hre/assets.py`、`paths.py` | 图像定向/色域、hash、相对路径约束 |
| `engine/src/hre/storage.py`、`protocol.py` | 原子写、done校验、身份与去重、事务恢复 |
| `engine/src/hre/workflow.py`、`budget.py` | 状态事件、生成预留账本、停止决策 |
| `engine/src/hre/evidence.py`、`stats.py`、`roi.py` | offline缓存绑定、基础统计、人工对应ROI |
| `engine/src/hre/prompts.py`、`prompts/` | 模板渲染与附件角色清单 |
| `engine/src/hre/desktop.py`、`capabilities.py` | 支持能力探测与任务包导出，不抓聊天历史 |
| `engine/src/hre/geometry.py`、`selection.py` | 几何检查、接受与最终选图 |
| `engine/src/hre/reporting.py`、`experiments.py` | 实验冻结、报告、blind export、比较统计 |
| `engine/src/hre/cli.py`、`ui.py` | 单用户入口，CLI/UI共同调用Controller |
| `engine/tests/test_hre_*.py` | 各里程碑失败条件与协议测试 |

下述函数是拟实现接口，不是已存在的运行能力。使用 `Path`；`CaseState,Asset,TaskRequest,TaskResponse,EvidenceSnapshot,Verification,Selection` 由同名 schema 生成/映射；`ImportResult(accepted:bool,code:str,duplicate:bool)` 与 `GateResult(status:str,observations:dict)` 为控制器内部类型。
主接口签名为实现计划的代码合同；02 的其他示意函数在适配器内调用，不能创建两套状态推进逻辑。

## M1：冻结双图 case 与类型（先完成）

**Files:** models.py、assets.py、paths.py；tests/test_hre_assets.py。

**Interfaces:**
`canonicalize_image(source:Path,destination:Path,role:str,profile:dict)->Asset`；
`create_case(prediction:Path,reference:Path,manifest:dict,config:dict,case_root:Path)->CaseState`。
source manifest 保留 baseline repo/ref/checkpoint/命令、scene group 与文件哈希；未知值显式 unknown，正式集入组要求见04。

- [ ] 写测试：A/B不同尺寸允许；EXIF旋转后正确；sRGB ICC正确转换；未知HDR拒绝正式入组；路径越界拒绝；相同名字异hash隔离；源文件不被修改。
- [ ] 运行 `python -m pytest engine/tests/test_hre_assets.py -q`，确认目标接口尚未实现时失败。
- [ ] 实现类型及图像冻结；确保canonical PNG具有可解释sRGB配置、记录原图SHA与转换过程；不对A/B做配准。
- [ ] 同命令通过并保存输入/输出hash；提交此可独立验收任务。

**Deliverable:** 两图 case 可创建/加载，不能调用模型。

## M2：文件交接、状态机与预算

**Files:** storage.py、protocol.py、workflow.py、budget.py；tests/test_hre_protocol.py、test_hre_workflow.py。

**Interfaces:**
`issue_task(case_id:str,stage:str)->TaskRequest`；
`ingest_response(case_id:str,response_path:Path,done_path:Path)->ImportResult`；
`dispatch_event(case_id:str,event:str,payload:dict)->CaseState`；
`recover_case(case_id:str)->CaseState`；
`reserve_generation(case_id:str,task_id:str)->str`。
身份逐项核对 schema/case_revision/state_revision_issued/task/stage/round/attempt/request/config/prompt/input_assets；request hash按02算法计算。

- [ ] 写测试：分片文件无done不读；done hash错拒收；相同响应二次幂等；同task不同bytes隔离；旧任务/错误图/错误config拒收；state+event提交各断点重启恢复。
- [ ] 写预算测试：执行任务发出前原子预留；用户确认实际提交后记账；失败生成计数；结果未知时保持预留不自动再提交；已确认没提交的预留可解除，需事件证据。
- [ ] 运行 `python -m pytest engine/tests/test_hre_protocol.py engine/tests/test_hre_workflow.py -q`，先记录失败。
- [ ] 按02状态表实现有限状态机与单writer锁；手动导入只包装响应/done并走同一链；format repair最多1次，不能替代视觉分析。
- [ ] 运行通过；重启模拟回到正确stage且generation次数不增长；提交。

**Deliverable:** 合成诊断→证据→Compose→执行→验证→refine/终止链通过；界面和模型仍可缺席。

## M3：证据缓存、统计与可比较区域

**Files:** evidence.py、stats.py、roi.py；tests/test_hre_evidence.py、test_hre_stats.py。

**Interfaces:**
`resolve_evidence(case_id:str,tool_plan:list[dict],cache_root:Path)->EvidenceSnapshot`；
`compute_stats(asset:Asset,mask_path:Path|None)->dict`；
`compare_rois(prediction:Asset,reference:Asset,roi_pairs:list[dict])->dict`。

- [ ] 写测试：T1/T2/T3/T4旧编号保持；计划外缓存不可进入Compose；A/B/C同图不同角色绑定；换权重/阈值/坐标/profile不命中；空检测与error不同；证据shape/label关联错误拒收。
- [ ] 用确定性合成sRGB色块测均值/分位/clip比例及Lab转换，并确认空mask不输出虚假的0；区域像素数/边界明确记录。
- [ ] 运行 `python -m pytest engine/tests/test_hre_evidence.py engine/tests/test_hre_stats.py -q`，记录失败。
- [ ] 实现基础STATS，无GPU；manual ROI在A/B各自坐标内独立绘制；保存同材质/同照明可比较结论与不可比较原因。暂不实现自动matcher。
- [ ] 缓存键与快照按02固定；预生成全部证据不会让所有证据被消费。工具不可用则等待或使用预先冻结的替代profile，不能静默更换模型。
- [ ] 测试通过并提交。

**Deliverable:** 本地查缓存和统计可运行；T1–T4真实推理由已有独立worker提供，缺少时使用合法人工证据而不伪装已跑模型。

## M4：Prompt、桌面适配与真实一对链

**Files:** prompts.py、desktop.py、capabilities.py、geometry.py；tests/test_hre_prompts.py、test_hre_execution.py。

**Interfaces:**
`render_stage(stage:str,context:dict)->str`；
`export_task_bundle(task:TaskRequest,destination:Path)->Path`；
`run_capability_probe(name:str,case_root:Path)->dict`；
`import_candidate(case_id:str,task_id:str,image_path:Path,metadata:dict)->ImportResult`；
`check_geometry(prediction:Asset,candidate:Asset,policy:dict)->GateResult`。

- [ ] 用03样例与StrictUndefined测6个模板可渲染，缺字段报错；execute附件只有A/B，refine的C仅分析，不进入新execute。
- [ ] 测 strict尺寸不同拒绝；预冻结纯scale派生图保raw与transform，aspect差>.005拒绝；不能通过自动crop/warp“修复”移动。
- [ ] 运行 `python -m pytest engine/tests/test_hre_prompts.py engine/tests/test_hre_execution.py -q`，先记录失败。
- [ ] 实现适配与导出；分别实测本地读图、JSON写入、角色会话派发、两图编辑、输出保存，保存每项证据与 `capabilities.json`。不能完成则用明确手动通道。
- [ ] 用户提供一对A/B后跑真实R1：诊断必须真实看到两图，C来自真实编辑而非mock；导入可trace到task。不宣称完全无人值守。
- [ ] 协议测试通过，真实链完成或准确记录受阻环节；提交。

**Deliverable:** 一对图完成真实可审计闭环，自动化等级按实测报告。

## M5：验证规则、选图与报告

**Files:** selection.py、reporting.py；tests/test_hre_selection.py、test_hre_reporting.py。

**Interfaces:**
`decide_after_verify(state:CaseState,verification:Verification,geometry:GateResult)->dict`；
`select_final(rounds:list[dict],baseline:Asset)->Selection`；
`write_report(case_id:str)->Path`。

- [ ] 测style improved但content fail不接受；uncertain/低置信不接受；critical defect覆盖矛盾pass；预算尽终止但不成功；duplicate停止；最早accepted→最早usable review_required→baseline fallback。
- [ ] 测最终report的图片hash、selected round、success来自同一Selection；一个可用旧候选与最后坏候选并存不交付最后坏图。
- [ ] 运行 `python -m pytest engine/tests/test_hre_selection.py engine/tests/test_hre_reporting.py -q`，先记录失败。
- [ ] 实现冻结规则、报告和JSON摘要；成功阈值0.7是工程heuristic，报告中明确不代表概率校准；NR分数与confidence不作质量排序。
- [ ] 测试通过，人工核对一次完成与一次失败报告；提交。

**Deliverable:** 停止与成功分开，最终图和结论一致。

## M6：UI、批处理实验与盲评导出

**Files:** cli.py、ui.py、experiments.py；tests/test_hre_cli.py、test_hre_experiments.py。

**Interfaces:**
`freeze_run(manifest:Path,profile:Path,destination:Path)->Path`；
`export_blind_evaluation(run_root:Path,destination:Path)->Path`；
`summarize_evaluation(run_root:Path,ratings:Path)->dict`。
UI调用M1–M5公共服务，不单独改state。

- [ ] 测每个WAIT状态仅允许当前操作；PAUSED可恢复；旧revision不进入新结果；blind包不含method/prompt/verifier判断，解盲键另存；失败不从分母消失。
- [ ] 运行 `python -m pytest engine/tests/test_hre_cli.py engine/tests/test_hre_experiments.py -q`，先记录失败。
- [ ] 实现首页/详情/历史/证据状态与manual入口；冻结实验配置、场景分组与实际成本；按04跑12对pilot，随后才能决定正式集。
- [ ] 跑完整 `python -m pytest engine/tests -q`；保存测试结果、R1/pilot产物与known limitations；提交。

**Deliverable:** 研究者能不重复描述任务而继续case；能形成公平对照与blind包。

## 拟实现命令与工程师最终回报

以下为M6应提供的CLI，不是本包现成命令：

```bash
python -m pip install -e ./engine
hre capabilities probe --case-root Data/ref_enhance_cases
hre case create --prediction prediction.png --reference reference.png --manifest manifest.json --config config.json
hre watch --case-root Data/ref_enhance_cases
hre task export --case-id case_0001 --out exchange
hre response import --case-id case_0001 --response response.json --done response.done.json
hre candidate import --case-id case_0001 --task-id task_id --image output.png --metadata metadata.json
hre report --case-id case_0001
hre run freeze --manifest manifest.json --profile experiment_profiles.json --out runs/ref_enhance
hre evaluation export --run runs/ref_enhance --out evaluation_blind
python -m streamlit run engine/src/hre/ui.py
```

正式manifest与profile需先经入组校验，示例不能直接当真实样本执行。CLI名称可以不带图像模型API；M1–M5实现后M6统一打包这些命令。

工程师交付：代码commit、实际启动命令、依赖lock、测试与真实能力probe日志、一对R1完整case、12对pilot（若已有数据）、自动与人工步骤清单、失败样本表、下一步。任何未跑环节写“未运行”，不能把静态schema通过写成增强成功。

审查后补充：aspect_preserving_resize的0.5%为拒绝初筛边界，派生到A精确尺寸还必须raw_w*A_h==raw_h*A_w；不允许小幅拉伸。固定K臂正常完成即fixed_k_complete（由selector决定success），Adaptive未通过耗尽为budget_exhausted。V1同次返回多图只登记供应商顺序首个完整图为candidate，其他图只存raw审计，已知额外采样仍入budget。

统计定义冻结于config.common.stats_metric（display_stats_v1）：sRGB编码域Yprime使用0.2126/0.7152/0.0722；shadow<0.10、highlight>0.95；CIELAB D65从IEC sRGB逆变换；HSV saturation黑为0；ROI像素中心odd-even/half-open bbox；空ROI为unavailable。STATS是辅助显示观察，不作为传感器物理量或自动成功依据。M3测试必须核对这些精确值与参数缓存键。M5加入summarypass与细项fail/uncertain、空观察、无可比style观察拒收测试。
