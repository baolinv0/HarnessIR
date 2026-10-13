# HarnessRefEnhance 状态机与文件协议

版本：`ref_enhance_v1`，2026-10-13。权威公共决议见 [00_SHARED_CONTRACT.md](00_SHARED_CONTRACT.md)。本文件定义可实现的 V1 文件管线与静态合同，尚未实现 Controller、桌面自动操作或模型调用。旧 restoration 状态、轮次和字段不得混入新管线。

## 1. 唯一状态源与职责

每个 case revision 只有一个 Controller 写入 `state.json`、任务、已接受响应、证据快照和终态选择。Streamlit 页面发送事件给该 Controller；Worker、桌面桥和人工导入只写各自任务的 submission 或 evidence job 输出。Watcher 只提示“存在新文件”，不能直接推进状态。单机单用户不需要消息队列、数据库、多写者选主或网络协调服务。

`case_revision` 标识冻结 A/B、ROI 和正式配置的输入版本；`state.revision` 从 0 开始，是每次 Controller 提交事务递增的审计版本。替换参考图、A、ROI 或正式配置必须建立新的 case revision 并重新诊断，原版本任务与结果仍保留。新版本预算从其冻结实验配置重新开始；成本报告保留各版本真实账目，不以换版本抹去成本。

操作系统文件锁保护单个 revision 的所有 Controller 写入：Windows 用 `msvcrt`，POSIX 用 `fcntl`；持有打开的锁文件描述符，程序退出由 OS 释放。锁文件的 PID/时间只供显示，不以文件年龄擅自夺锁。第二个 Controller 只能只读；UI 多标签仍调用同一服务实例。锁内进行短事务，不在持锁期间等待模型或运行大型工具。

## 2. 目录与路径边界

实际 revision 根可为 `cases/<case_id>/rev_0000/`，下文称 `case_root`；所有 schema 的 `path` 都相对此根。revision 根和既有 Data/cases 的接入路径由适配配置显式登记，不假定用户 Windows 的真实盘符。

| 相对位置 | 内容与写入者 |
|---|---|
| `input/original/` | A/B 原文件，导入器复制后只读 |
| `input/canonical/` | 独立尺寸的 A、B SDR sRGB PNG，Controller 注册后冻结 |
| `input/roi_manifest.json` | 冻结手工 ROI 配对及可比性说明 |
| `config.json` | 冻结配置；不得运行中改阈值 |
| `state.json` | Controller 唯一当前快照 |
| `transactions/000001_<tx_id>.json` | Controller 原子提交的恢复凭据 |
| `tasks/<task_id>/attempts/000/` | 不可变 `request.json`、`prompt.txt`、派发 manifest |
| `tasks/<task_id>/submissions/<submission_id>/pending/` | 适配器写 raw、图像、response、最后 done |
| `tasks/<task_id>/accepted/` | Controller 接受的首份有效结果，仅一份正式值 |
| `evidence/records/` | 当前 case 绑定的已校验证据，不链接外部可变文件 |
| `evidence/snapshots/` | 不可变 `snapshot_<sha256>.json` |
| `rounds/r000/` | 该轮 candidate manifest、geometry 报告、验证引用 |
| `quarantine/<submission_id>/` | 拒收/过期/冲突文件、原因与原始文本 |
| `final/selection.json` | 被选资产引用、success/fallback/review_required、原因；不覆盖 raw |
| `events.jsonl` | 从事务再生的审计投影 |

只接受 `/` 分隔的相对路径；拒绝绝对路径、盘符、反斜杠、`..`、空路径段、`.` 段、URI、Windows ADS、设备保留名和尾部点/空格。Schema 做第一层格式约束；文件桥还须逐段校验、`resolve` 后确认仍在 `case_root`，拒绝 symlink/junction/reparse point 越界。不由模型给任意路径；任务输出目录、submission ID 和最终文件名由本地桥生成。Downloads 文件只能经用户对当前任务明确导入，不能按“最新图片”自动匹配 case。

## 3. 状态字段与不变量

`schemas/state.schema.json` 是严格快照合同。`workflow_state` 仅允许 `CREATED, WAIT_DIAGNOSIS, WAIT_EVIDENCE, WAIT_COMPOSITION, WAIT_EXECUTION, WAIT_VERIFICATION, WAIT_REFINEMENT, PAUSED, COMPLETED, FAILED, CANCELLED`。暂停用真正的 `PAUSED` 和 `resume_state`，不叠加另一套 operation_status。

- 活跃/暂停状态的 `success,terminal_reason,selection` 为 null；终态三者必填，`success` 是布尔值。`COMPLETED` 可 `success=false`；`FAILED`、`CANCELLED` 永远 false。
- `CREATED`、`WAIT_EVIDENCE` 没有 ChatGPT pending task；其余 WAIT 状态有匹配 stage 的唯一 pending task。工具子 job 不占这个槽。
- `pending_task` 保存 `task_id,stage,round,attempt,request_sha256,state_revision_issued,request_path`。响应与发出时任务身份比较，不能把其 `state_revision_issued` 与记账后的最新 revision 直接比较。
- 输入严格为一个 prediction A 和一个 reference B；参考入组须已通过共同冻结人工可比性门禁，Agent还须diagnosis判usable；角色、asset ID、canonical SHA、原始 SHA、尺寸、颜色处理均冻结。A/B 不共用坐标系；不同尺寸无需对齐或 resize。
- round 从 0 开始，表示一次有意的生成任务。diagnose/compose 初始 round=0；verify 与候选同 round；refine 的 `source_round` 是失败候选 round，而其 envelope round 是准备生成的下一 round。没有图像的失败提交也占一个 round。
- 同 case task ID 唯一；同 task 可有多个传输 attempt 和多份无效 submission；只有首个合法 accepted response 成为正式值。预算、candidate 和任务不能凭文件名猜关联。
- 状态只是合法形状。hash、账本求和、角色数量、候选门禁、证据计划覆盖、路径实物和时间顺序必须通过语义校验。

## 4. 主状态转移表

表中“接受”包括 done、身份、Schema、文件 SHA、附件角色、case revision 和语义校验。每行变更均由一个 Controller 事务完成。无合法事件时原状态保持；超时不等于成功或已失败。

| 当前状态 | 事件 | guard / Controller 原子动作 | 下一状态 |
|---|---|---|---|
| CREATED | `start`，AgentSingle/Adaptive | A/B canonical 可解释、config/ROI/probes冻结；发 diagnose | WAIT_DIAGNOSIS |
| CREATED | `start`，DirectRef/BestOfK（profile_id=direct_best_of_3） | A/B合法；冻结固定 direct prompt、空证据快照；预留生成槽并发 execute | WAIT_EXECUTION |
| CREATED | `start`，Baseline | 仅登记 A；不调用诊断、工具、编辑或流程 Verifier；终结为 baseline_only | COMPLETED，success=false |
| WAIT_DIAGNOSIS | `response_ready` | diagnosis合法且 reference_usable=usable；工具名、角色、ROI合法；冻结计划并建立计划内 jobs | WAIT_EVIDENCE，或计划为空时直接发 compose |
| WAIT_DIAGNOSIS | `response_ready` | reference_usable=unusable/unknown，或所有目标范围不可比较；保存并接受诊断、关闭该task（pending=null）、不生成编辑 | PAUSED，resume_state=WAIT_DIAGNOSIS |
| WAIT_EVIDENCE | `evidence_ready` | 校验/复用准确缓存；所有required=ok，所有optional已ok或明确error/unavailable；冻结snapshot并发compose | WAIT_COMPOSITION |
| WAIT_EVIDENCE | `evidence_failed` | required证据缺失/失败；保留全部结果与原因 | PAUSED，resume_state=WAIT_EVIDENCE |
| WAIT_COMPOSITION | `response_ready` | composition合法、引用证据在冻结snapshot中；编辑文字非空，未要求复制B内容；预算可预留；发execute | WAIT_EXECUTION |
| WAIT_EXECUTION | `execution_submitted` | generation_id首次提交；账本预留转已消费；记录真实UI操作与时间 | WAIT_EXECUTION |
| WAIT_EXECUTION | `response_ready` | execution envelope、图像/角色/源绑定合法；保存raw与canonical；未duplicate；登记candidate并执行冻结geometry检查、发verify | WAIT_VERIFICATION |
| WAIT_EXECUTION | `response_ready` | 与先前输出相同raw bytes（或相同canonical，含A） | COMPLETED，duplicate_output/canonical_duplicate_output，立即停止 |
| WAIT_EXECUTION | `response_ready`，status=error | 已提交的失败仍记预算；无candidate不能verify；记录generation_error | PAUSED，resume_state=WAIT_EXECUTION |
| WAIT_VERIFICATION | `response_ready` | geometry pass；style improved；content pass；critical_defects空；confidence>=.7；Single/Adaptive/DirectRef首次accepted | COMPLETED，accepted，success=true |
| WAIT_VERIFICATION | `response_ready` | BestOfK consumed+reserved<K，无重复/异常且仍有预算 | 同固定prompt预留下一round并发execute；WAIT_EXECUTION |
| WAIT_VERIFICATION | `response_ready` | BestOfK consumed达到冻结K（即使formal candidate不足K） | COMPLETED，fixed_k_complete；运行固定selector |
| WAIT_VERIFICATION | `response_ready` | AgentSingle/DirectRef未accepted | COMPLETED，single_pass_complete，success=false |
| WAIT_VERIFICATION | `response_ready` | Adaptive未accepted、还有预算、可比性成立且retry_focus可执行；发refine，envelope round=当前+1 | WAIT_REFINEMENT |
| WAIT_VERIFICATION | `response_ready` | Adaptive未accepted且预算不足 | COMPLETED，budget_exhausted，success=false |
| WAIT_VERIFICATION | `response_ready` | 仅Adaptive尚有预算，且不可比较/低置信缺关键观察、没有可执行retry_focus | PAUSED，已接收task关闭；补观察后新task_id重做同candidate/round的verify，或显式停止 |
| WAIT_REFINEMENT | `response_ready` | source_round及反馈绑定正确；编辑文字有实质变化；预算可预留；仅把新文字与A+B发execute | WAIT_EXECUTION，round更新 |
| WAIT_REFINEMENT | `response_ready` | edit_prompt与上一有效文字精确相同（去首尾空白后） | COMPLETED，no_prompt_change，success=false |
| 任意分析WAIT状态 | `response_ready`，status=error | diagnose/compose/verify/refine默认接受合法error、关闭task（pending=null）并暂停；retryable只表示可考虑恢复，不自动重试 | PAUSED，resume_state=当前WAIT |
| WAIT_REFINEMENT | error.code=no_supported_refinement | 不再生成；保存错误并运行冻结selector；已有usable为review_required/success=false，否则fallback A | COMPLETED，no_supported_refinement，success=false |
| 任意活跃状态 | `pause_requested` | 保存原workflow为resume_state，保留pending任务和预算 | PAUSED |
| PAUSED | `resume_requested` | 阻塞原因已消除或明确有效重试动作；未接收任务保留身份，已接收分析任务原子issue新task，不自动再次生成 | 恢复resume_state，再处理已完成pending submission |
| 任意非终态 | `cancel_requested` | 清除pending正式接收资格；不尝试抹去已提交模型操作；固定selector并标取消 | CANCELLED，success=false |
| 任意非终态 | `fatal_integrity_error` | 冻结原状态和可追溯失败；停止派发；选择已知可用候选或A | FAILED，success=false |
| PAUSED | `stop_requested` | 不继续执行；终止reason记录明确原因，例如unusable_reference/generation_error/evidence_unavailable | FAILED，success=false |
| 任意终态 | 任意新的workflow事件 | 返回terminal_noop；不再派发或替换选择。晚到费用单独登记而不改变success/selection | 原终态 |

分支判定优先级：先协议/语义拒收，再独立费用与duplicate；合法error先匹配no_supported_refinement专属终结，否则默认暂停；合法verification先按profile执行Single/DirectRef一次结束、BestOfK已记账上限/下一生成，再处理Adaptive的accepted、预算耗尽、可执行refine或缺观察暂停。因此低置信暂停只适用于Adaptive有预算且无法执行有效反馈，不覆盖一次组/固定K组已冻结终结规则。

`PAUSED` 时可扫描并保存submission，但不能接受后推进；已确认实际生成的成本仍须立即登记。替换参考不是对同一pending任务resume，而是建立新revision。若工具/参考永久不可用，操作员可记录失败；不能降级成无参考success。正式profile不允许“跳过required工具继续”；探索profile例外须预先配置并记录deviation，不能进入正式统计。

image_not_observed必须实际补齐附件/观察；若合法error已被接受，resume原子发新task_id（不是只attempt++），不能用format repair替代。no_supported_target暂停以补真实比较限制或明确停止失败，不能直接生成；其他retryable分析错误若已正式接受则resume新task_id，不扣图片预算；只对未接收的传输/格式拒收任务允许按attempt规则重传。正常工作流不会自动重跑失败图片。暂停后的 `retry_generation` 只在真实剩余预算允许时发新的 generation_id、task_id、round；沿用最近已冻结有效文字和 A+B，不用失败C。`retry_transport` 只交接既有结果或纠正格式，不再次点编辑器生成。缺少原提交事实时保留预留，明确核对后恢复，不以超时自行释放。

## 5. 接受、停机与选图

Controller 从candidate本身的geometry和对应verification计算，不相信模型自报的“success”。

```python
usable = (geometry.status == "pass"
          and verification.content_preservation == "pass"
          and not verification.critical_defects
          and verification.confidence >= 0.7)
accepted = usable and verification.style_alignment == "improved"
```

Geometry `fail/uncertain`、content `fail/uncertain`、有critical defect或confidence<.7，均不能作为可交付增强候选。style `unchanged/worse/uncertain` 即使usable也只是待人工复核，不能成功。低置信不因“看起来比较好”绕过门禁。Verifier是流程反馈，不代替正式盲评。

verification的summary content=pass必须有composition、geometry、identity、text、scene_content五类preservation_observations且全部status=pass；无脸/无文字需明确absent说明，也记对应pass。summary pass与细项fail/uncertain或非空critical_defects矛盾时合同拒收，不能进入selector。style improved至少有一条comparable/partly_comparable的style_observation；不能凭summary绕过可比性。schema作结构约束，Controller还需检查每一类覆盖、重复/缺失、逐项矛盾与其真实附件。

冻结selector：先取最早round的accepted；无accepted时取最早round的usable，`review_required=true,success=false`；无usable取A，`fallback=true,review_required=true,success=false`。同round异常多输出只按provider明确顺序选第一完整图片，其他永久保留为extras并如实记预算；不挑“最好”一张。provider顺序不可确定则暂停，不能由人工替系统择优。同round不应有多个正式candidate，冲突交由协议拒收。

Adaptive/Single/DirectRef接受立即停止，最后一个预算槽刚好accepted仍为accepted/success=true。未accepted的耗尽才是budget_exhausted/success=false。BestOfK原则用满冻结generation预算K、不refine；consumed==K时使用fixed_k_complete，已有accepted可success=true。若可知后台额外采样令consumed==3但正式candidate不足3，也按fixed_k_complete停，不再派发，分别报告正式candidate数与实际已记账生成数；consumed>K一律FAILED/extra_sampling。BestOfK遇duplicate提前停时，若之前已有accepted可保留success=true并记录duplicate原因；否则false。FAILED/CANCELLED一律false，即使保留先前候选也标review_required，不能把失败/取消报告成成功。失败候选、不完整文件和全部历史verification保留。

Baseline臂的A本来就是指定输出，reason=baseline_only、success=false、fallback=false、review_required=false；管线失败而交付A才是fallback。流程终止原因、增强成功、是否需要复核和baseline回退是独立字段。

## 6. 预算与 generation 账本

`max_generations`默认3，生成profile可取1到3；Baseline为0，reserved/consumed为0、ledger为空。`profile_id`严格使用baseline/direct_ref/agent_single/agent_adaptive/direct_best_of_3，BestOfK在V1的K固定为3，不另用direct_best_of_k。`budget.consumed`包括失败提交和可知后台重生成，不能只计成功图片。`reserved`是已派发但尚未确认是否提交的槽数；派发guard为 `consumed + reserved < max_generations`。round、transport attempt、格式修复次数和生成次数不可互相代替。

1. 发execute事务先新增ledger `{generation_id,task_id,round,status:reserved,charged_count:0}`，reserved+1。
2. 在实际点击/发送编辑器前，适配器写本地submission intent；只有确认已经提交时通知Controller `execution_submitted`。ledger变submitted、charged_count=1、consumed+1、reserved-1；即使输出错误、超时、拒绝或丢失，已知提交也占一槽。不能排除已提交或提交中断且事实不明时，仅保存durable intent并PAUSED，reservation继续占用，不能转submitted/consumed；核对确已提交才execution_submitted，确未提交才release_unsubmitted，不能自动重发。
3. 明确从未提交时才允许 `release_unsubmitted`，ledger为released_unsubmitted；保留原因/证据，不计生成。状态error自身不是释放凭据。
4. 同generation_id重复submitted事件幂等，不加成本。后台额外可知生成用同entry新增charged_count，按实际数量更新consumed；extras也计数。若consumed超过冻结上限，记录extra_sampling偏离、停止派发并FAILED；不能把计数截断至3。
5. 再次点“重新生成”是新采样，必须预留新槽、登记新generation_id与round；不能包装成attempt重传。传输attempt+1时只重传已有结果或格式纠正，generation_id保持同一值。

Schema允许consumed大于3以记录已发生违规；guard保证正常派发最多3。ledger求和必须等于consumed，reserved等于状态reserved entry数，同一generation_id不得重复。人工方式若未能看到后台次数，明确记录unknown/观察局限；不得编造模型内部调用数或费用。预算耗尽后仍可接受已经提交任务的合法结果并verify，不能新增图片生成。

报告counter是从不可变ledger+事务事件派生的审计投影，不能在state里随手加另一个独立计数器。每个execution intent/submitted/extra observation事件记录generation_id、事实来源、可观测状态和count，并持久化在事务event正文；归并按event_id去重。

| 报告字段 | 来源与定义 |
|---|---|
| observed_generation_submissions | 唯一generation_id的确认提交事件数；失败确认提交也计，不把未确认intent当已观测提交 |
| known_backend_regenerations | provider额外生成观测事件count求和；人工另点重新生成是新确认submission，不能又重复计在此项 |
| uncertain_submission_reservations | ledger reserved且存在durable intent、提交事实未确认的entry数；普通尚未点击的预留不属于uncertain |
| accounted_generations | budget.consumed + uncertain_submission_reservations；同时另列reserved和held_budget=consumed+reserved用于派发guard，防止报告把预留误写实际费用 |
| backend_regeneration_count_status | 所有提交的provider内部数量确实可知才known；任一不可观察则unknown，即使known额外次数为0也不能假装后台总次数已知 |

文本/看图阶段调用和repair按task提交事件统计，transport重发与纯本地格式修改分别标注；wall time、操作员active minutes与实际账单/币种从观测事件和原账单派生。response的精确版本/seed=null在实验报告导出为unknown。成本未知保持null，不由图片张数推算美元。

## 7. 请求、响应与 canonical hash

请求和响应必需公共字段：`schema_version,case_id,case_revision,state_revision_issued,task_id,stage,round,attempt,request_sha256,config_sha256,input_assets,prompt_version,payload`。response额外为 `status,model_observed,session_id,error`。`input_assets`和prompt_version也原样echo。所有身份/hash/资产字段由Controller/本地桥给模型，模型不能计算、猜测或修改SHA。模型只填写对应stage结果；人工仅payload导入时由桥补envelope并明确provenance。

`schemas/request.schema.json`按stage校验输入payload：diagnose冻结工具profile和ROI引用；compose引用合法diagnosis与证据snapshot；execute绑定generation_id、A/B与编辑文字；verify绑定candidate、geometry报告与rubric；refine绑定source_round和对应verification。`schemas/response.schema.json`对ok严格引用四份Agent3 stage schema；execute结果合同在 `$defs/execution_payload`。status=error必须 `payload=null` 且结构化error非null；ok必须error=null且有效payload，不能用空对象冒充结果。

`model_observed`为 `{ui_model_name,exact_model_version,seed,observed_at,transport,operator_steps}`；UI名称不知填unknown，精确后端版本和seed不可观测填null，session_id不可观测填null。保存实际UI名称、操作时间和人工步骤，不假装已使用某个API model ID。`transport=fixture`只用于静态测试，不算真实模型实验。

所有JSON为UTF-8；拒绝重复键、NaN、Infinity、BOM和类型错误。可接受最外层单个完整JSON markdown fence，保留原始文本后由桥生成规范response；不得从散文中捞片段。日期为真实带时区RFC3339，启动时确认jsonschema `FormatChecker`启用，另检查时间先后。

规范算法命名 `hre_cj_v1`：在Python3.10+对JSON值调用 `json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")`。按Unicode codepoint排序键，不作NFC/NFKC重写；整数/浮点的表示遵从此冻结Python序列化合同，不声称RFC8785兼容。各模块只调用同一canonical_json函数，前端不能另算“等价hash”。

```python
request_sha256 = sha256(canonical_json({k: v for k, v in request.items()
                                      if k != "request_sha256"})).hexdigest()
config_sha256 = sha256(canonical_json({k: v for k, v in config.items()
                                     if k != "config_sha256"})).hexdigest()
```

只排除顶层自身hash字段，不删除nested hash或状态身份。保存前本地生成request hash，消费时重新计算。`done.response_sha256`、asset.sha256、snapshot.sha256则是实际文件bytes SHA，不是解析后JSON hash；二者语义不能混用。payload文本和input_assets都被request hash覆盖，prompt.txt是其确定性渲染，派发manifest记录prompt bytes SHA并验证。

## 8. 图片角色、candidate绑定与 geometry

| stage | 可见图像/数据 | 禁止混淆 |
|---|---|---|
| diagnose | 冻结A=prediction、B=reference；ROI和能力清单 | B不当pixel GT，不含C |
| compose | A+B、合法diagnosis、计划内冻结证据 | 证据图的坐标必须标所属A或B |
| execute | 仅冻结A+B和当前edit_prompt | 不传工具色彩图、C、上轮图或geometry图；每轮编辑A |
| verify | A+B+本轮C、所有臂共用冻结rubric、protected_content/reference_limitations | content对A，style对B；不把B的几何/人物作为保真标准 |
| refine | A+B+失败C、对应verification、原编辑文字及共同保护/参考限制 | 输出只调整下一轮文字；仍编辑A |

DirectRef/BestOfK无需Compose：Controller创建不可变固定prompt artifact，source ID为 `direct_prompt_<case_id>_rev_<case_revision>`，execute.prompt_source_task_id指向该本地artifact manifest而非模型任务；该manifest记录prompt文本/版本/SHA和config绑定，evidence_snapshot_sha256指向已冻结空snapshot。所有方法Verify的protected_content/reference_limitations来自同一预注册manual ROI/comparability和公共rubric，不依赖Compose的措辞。

实际两图附件必须映射asset_id、role和SHA，附件顺序显示“图1=A编辑对象；图2=B外观参考”。仅有路径/JSON不代表模型看到了图。两图编辑、图像读取、文件读写、会话派发、输出保存是独立capability probe；缺少任一必需能力则暂停，人工导入链仍可运行，不能提前宣称全自动。

candidate资产的 `candidate_binding` 必填case_id/case_revision/task_id/round/generation_id/prediction_sha256/reference_sha256；同时保留raw source_file与canonicalization记录。asset_id即候选主ID，state的candidate_id必须与之相等。同candidate的geometry、verification、ROI证据均通过candidate_id、generation_id和canonical SHA绑定，不能把上一轮verification套在本轮。

verify/refine模型不接收工具报告、STATS、geometry图或数值；request中的geometry_report/snapshot字段仅供Controller审计绑定，不能作为模型消息input_context。模型只收到上表图像和统一冻结文字/反馈，Controller独立执行geometry门禁。compose可读取其计划内证据；execute不接收。

输出raw先原样保存。随后仅做冻结的EXIF定向和ICC→SDR sRGB canonical PNG；不调用把C拉回A的官方colour adjustment，不作自动曲线、白平衡、去饱和或局部纠正。无法解释的HDR/HEIC/profile暂停正式入组，先做可追溯SDR导出。无ICC只可在预冻结、明确记录的sRGB假设下处理，不能静默假装有profile。

geometry默认strict，raw定向后的宽高必须与A相同，且冻结结构/构图/人物/文字检查通过；像素尺寸符合不能单独证明内容保真。可预冻结aspect_preserving_resize例外：宽高比相对偏差<=0.005只是初筛，且必须满足 `raw_W * A_H == raw_H * A_W` 精确等比例，才能对C做记录完整的纯scale派生显示/检查图，raw和原canonical均保留。只在精确等比例时可用同一scale因子映射到A；即使宽高比差小于.5%，不精确等比例也必须geometry fail，不能直接resize(A.size)产生轻微warp。V1不做integer rounding、pad或额外匹配方案。不能crop、pad、warp、mask或靠对齐藏掉结构改变；插值方法、尺寸、变换矩阵和派生SHA入报告。所有实验臂使用同政策。严格模式Verify观察master canonical C；纯scale例外Verify观察geometry.derived_asset，selection.asset_id必须等于该次Verify实际观察的C asset ID，selection.candidate_id仍指master候选ID。同generation/candidate_binding使其可追溯，不能Verify原图却交付另一个派生图；raw、master、derived全部保留。geometry与亮度/色彩观察分开，不以raw SSIM或chroma drift当保真硬门禁。

像素hash可用 `SHA256(b"HRE-RGB8-v1\0" + W.to_bytes(4,"big") + H.to_bytes(4,"big") + RGB_bytes)`，作用于定向、ICC转换后的RGB8，版本入canonicalizer合同。candidate raw bytes与已有raw相同即duplicate_output立即停止，不再refine；canonical与已有C或A相同则canonical_duplicate_output停止，避免metadata变化绕过重复检查。

## 9. done提交与三种接收区

适配器只写当前task的唯一submission目录。所有临时文件与最终目标同一卷，同目录rename；write→flush→fsync→close→replace，完成后才写done。Windows sharing violation短退避100/200/400/800/1600ms，仍失败则保留pending并暂停，不能先写done冒充完成。具备目录fsync的平台对rename后的父目录同步。

提交顺序：raw图/附件 `.part`→最终文件；本地测SHA/尺寸/色彩元数据；`response.json.tmp`→response.json；最后 `done.json.tmp`→done.json。done合同在 `response.schema.json#/$defs/done_manifest`，字段严格为 `schema_version,case_id,case_revision,task_id,request_sha256,response_file,response_sha256,artifacts,completed_at,writer`，artifacts逐文件列path/bytes SHA/kind。done里的路径仍为case-root相对路径，必须落在本submission的授权目录；错误响应可artifacts=[]。模型不得写想象done hash。

- **pending**：文件尚不完整，或done已齐尚未校验/等待resume；只有完成done才进入候选消费。`.tmp/.part`永不推进。
- **accepted**：Controller逐项校验通过并在事务中登记后，首份正式response及引用资产成为不可变正式值。
- **quarantine**：坏JSON/Schema/hash、错误case/stage/role/revision、缺图、路径越界、旧task/attempt、同任务内容冲突、已取消/终态晚到响应。保留raw与机器可读拒收原因；不将隔离文件自动修成有效候选。

消费done先校验manifest→response bytes SHA→严格JSON/envelope→所有identity与request逐字段等值→request/config重新hash→对应stage payload→资产文件hash/解码→候选/证据/ROI/预算语义。任何失败都不推进、不改pending；写拒收事件。最外层envelope错误不由阶段模型自由补身份。生成费用独立审计，即使响应被隔离也不能抹掉已知提交成本。

## 10. 原子状态事务与恢复

提交步骤：取得case锁；加载最新state并验证revision；准备/校验next_state、next任务文件和事件；将事务写 `.tmp`、fsync、rename为最终 `transactions/<next_revision>_<tx_id>.json`；该rename是唯一commit point；再原子替换state.json；最后更新events和accepted投影。未经事务引用的任务目录不派发。

事务必需 `tx_id,event_id,previous_revision,next_revision,case_revision,previous_state_sha256,next_state,event,accepted_submission,next_task,committed_at`；其中next_state是完整已通过Schema/语义检查快照，accepted_submission和next_task可null。next_task含不可变request_path/request_sha256/prompt_sha256。revision严格+1；Controller事务对最新revision做compare-and-swap，不对request发出旧revision做当前值相等要求。事务能重建状态，events与accepted目录只是可重建投影，不承担另一个commit点。

启动恢复顺序：取得锁→校验冻结config/A/B→扫描连续且完整事务→确认state与最后事务一致或按事务重放→按event_id重建去重日志→重建accepted引用→派发已提交但未执行的新任务→扫描pending done。崩溃于任务准备但事务尚未commit：任务为orphan，不派发；commit后state尚未更新：重放next_state；state完成但accepted目录未整理：从事务补投影。事务缺号、previous hash不匹配、两个同revision不同事务或引用文件损坏均PAUSED/FAILED protocol_integrity_error，不猜哪个“更新”。

模型提交不是文件事务可回滚的动作。恢复有未确认submission intent时暂停核对，不能自动再次生成。重启不会增加round或重复消费预算。accepted之前就先持久化accepted_submission身份，恢复可以认出已消费done。

## 11. 幂等、attempt与格式修复

收件幂等键为 `(case_id,case_revision,task_id,attempt,request_sha256,response_sha256)`；所有response身份还须匹配config与state_revision_issued。重复same key返回already_processed，状态/round/预算不变。已接受同task的不同内容是conflict，隔离且不择优。合法diagnosis unknown/unusable、低置信verification或分析error一旦被接受，该task也已完成且首合法值冻结。PAUSED补真实观察后必须Controller原子发新task_id，verify保持同candidate_id/source_round/round且图片预算不变；旧task/旧attempt迟到输出隔离，不覆盖原合法值。只有尚未接受任何合法response的task可格式修复/attempt重传。尚未接受的无效response可在同task下另建submission纠正，原文保留。

attempt表示显式传输重发编号。每个attempt有独立不可变request文件和新request_sha；Controller事务替换pending attempt后，旧attempt响应隔离。单纯重复扫描/复制同一done不升attempt。execute的attempt重传只能登记已有生成结果，不能触发再次生成；UI桥必须检查generation账本。

格式修复上限默认1，作用仅限结构/JSON错误。使用原任务、同一观察上下文，请原角色修正或人工修正；不让另一模型“替看图”，不重做图像编辑。修复次数作为事件/任务manifest记录，不能用attempt无限循环逃过format_repair_limit。缺图、证据不足、错误candidate/源SHA和可比性问题不是格式错误；必须补真实观察或暂停。超过限额进PAUSED，明确停止时FAILED。

## 12. 证据、离线缓存与freeze

T1_OCR/T2_FACE/T3_DEPTH/T4_SEGMENTATION维持旧编号；STATS、ROI_COMPARE独立。diagnosis计划仅A/B；候选工具仅由冻结verification policy预先定义，不能临时“看见差异就补一个工具”。refinement没有新tool_plan，V1禁止refine新增工具或扩大证据集合；只能使用诊断原计划和冻结verification policy内已有证据。运行时可只消费离线已全量生成证据，但只向当前角色暴露计划内记录，不因缓存齐全而扩大工具计划。

`schemas/evidence.schema.json`严格记录 `binding.inputs` 的asset_id、role、canonical SHA、原坐标尺寸和candidate_id。bbox采用所属源图 `canonical_norm`，每个输入独立source_to_tool矩阵，禁止A的框直接套B。需要交叉ROI比较时用人工roi_pair_id分别绑定A/B区域；reference遮挡/照明/视角/时间/语义组成不同可明确not_comparable/unknown，不补造匹配。

缓存key=`SHA256(canonical_json(cache_contract))`；cache_contract包括有序 `(role,canonical_sha256,width,height)` 输入，tool ID/版本、canonicalizer、模型名称/源码revision、权重SHA及多组件列表、preprocess版本/配置SHA、参数、backend实现/版本/device/precision/environment/profile、ROI manifest SHA及prompt-set SHA。输入与组件顺序冻结，排序规则由工具合同规定。CPU STATS无权重时weights_sha256=null且算法版本明确；未知ROI配置hash=null只代表不使用ROI，计划要求ROI时缺失必须暂停。不是任何未知值都可随意null。

共享cache为只读payload与content-addressed artifact存储；命中须完整校验合同和输出文件hash。复制/硬链接可控不可变文件到case根后，materialize必须按hash+role+尺寸/几何建立旧ID到当前ID的严格映射，重写payload及metadata内全部资产引用（coordinate_frames.asset_id、detections.source_asset_id、STATS.regions.source_asset_id、ROI_COMPARE两图asset_id、数组/伪彩图关联、assets.evidence_format.coordinate_asset_id），再为当前case/revision/plan item/candidate重建binding wrapper并生成新record bytes SHA。共享cache原artifact不改；任何引用无唯一合法映射都拒绝复用，不把别的case wrapper或旧payload ID原封拿来。相同C canonical bytes可复用同role工具payload，但仍关联当前candidate ID；prediction/reference/candidate role不互用。没有检测到对象是ok空detections，未运行是unavailable，工具出错是error。

证据图/数组也用asset合同：visualization须sRGB和真实尺寸；JSON/npy `color_space=null`，width/height不可用时null，`evidence_format`标kind/dtype/value_range/coordinate_asset_id，避免把depth float32误标成彩色图。depth/segmentation原数组与用于看的伪彩图分开资产并记录范围；伪彩图不送Executor。T3/T4的工具data需分别提供数组asset_id、depth_kind或class registry；旧工具返回值经适配器转换，不能把新深度/分割数据截断为通用bbox。

当计划所有required可用、optional均有明确结果时冻结snapshot；合同在 `evidence.schema.json#/$defs/snapshot`。snapshot含case/config/plan hash、scope、candidate绑定、证据记录bytes SHA/cache key和明确不可用项，自身bytes SHA写入state/request。空计划也生成空snapshot。DirectRef/BestOfK的snapshot diagnosis_task_id=null；Agent路径必须为当前已接受diagnosis任务ID，语义校验器不允许Agent以null跳过诊断。Controller为compose、verification、refinement各绑定不可变snapshot，供复现与审计；仅Compose将计划内报告提供给模型，verify/refine仅携带Controller绑定，不给模型工具/geometry报告。验证C时创建新的candidate专属snapshot，不能覆盖composition snapshot。补证据生成新snapshot并新发相关任务或新case revision，不能悄悄替换旧证据。snapshot freeze后所有记录/资产不可变。

## 13. manual import与桌面桥同一管道

人工粘贴payload：UI要求选当前task，保留raw文本，按stage schema验证payload，使用不可变request补echo，再让操作者登记实际UI模型名/时间/session/步骤，生成response和done。自动桥收到envelope也走完全相同校验；人工不能因“知道是对的”绕过hash/geometry/候选门禁。

人工图片导入：选择当前execute任务与实际图片文件，复制原bytes到该task新submission目录；登记/核对generation提交事实；本地canonical化和资产测量；构造execution payload与done；Controller消费同一管道。导入器不修改图片颜色、替候选挑最优、搜索整个Downloads或把上轮图变成本轮。多个输出明确provider顺序和费用，顺序不明暂停。工具manual ROI的人工标注也存同evidence/ROI合同、记录producer=manual_roi与冻结配置，不能只留UI内存。

## 14. 实现接口与异常边界

以下为未来 `engine/src/hre/` 的接口签名设计，不是现已实现的API。

```python
class Controller:
    def start_case(self, case_root: Path, expected_revision: int) -> State: ...
    def handle_event(self, event: CaseEvent, expected_revision: int) -> State: ...
    def consume_done(self, done_path: Path) -> ConsumeResult: ...
    def pause(self, reason: str, expected_revision: int) -> State: ...
    def resume(self, action: ResumeAction, expected_revision: int) -> State: ...
    def cancel(self, reason: str, expected_revision: int) -> State: ...
    def recover(self, case_root: Path) -> State: ...
    def select_final(self, state: State, reason: str) -> Selection: ...

class TaskWriter:
    def issue(self, request: Request, rendered_prompt: bytes) -> PreparedTask: ...
    def commit_submission(self, request: Request, payload: dict | None,
                          raw_text: bytes, files: list[Path],
                          provenance: ModelObserved, error: Error | None) -> Path: ...

class AssetRegistry:
    def import_original(self, source: Path, role: ImageRole) -> SourceFile: ...
    def canonicalize(self, source: SourceFile, policy: ColorPolicy) -> Asset: ...
    def register_candidate(self, task: Request, source: SourceFile) -> Asset: ...
    def validate_asset(self, asset: Asset, case_root: Path) -> AssetCheck: ...

class EvidenceStore:
    def lookup(self, contract: CacheContract) -> CachedEvidence | None: ...
    def bind_to_case(self, record: CachedEvidence, binding: EvidenceBinding) -> Evidence: ...
    def freeze(self, plan: ToolPlan, records: list[Evidence],
               scope: str, candidate_id: str | None) -> EvidenceSnapshot: ...

class ProtocolValidator:
    def validate_request(self, request: dict, state: State) -> Request: ...
    def validate_submission(self, done: dict, request: Request,
                            state: State) -> ValidatedSubmission: ...
    def validate_state(self, state: State, previous: State | None) -> None: ...

def canonical_json(value: JsonValue) -> bytes: ...
def request_hash(request: dict) -> str: ...
def atomic_write(path: Path, data: bytes) -> None: ...
def check_geometry(prediction: Asset, candidate: Asset,
                   policy: GeometryPolicy) -> GeometryReport: ...
def import_manual(task_id: str, payload_text: str | None, image: Path | None,
                  provenance: ModelObserved) -> Path: ...
```

接口返回结构化错误，分为可修的protocol_rejection、需观察/操作的pause、不可恢复的integrity_failure；不在validator里调用模型。`expected_revision`不符返回stale_state，UI刷新后重试合法事件；不能覆盖新state。受控I/O失败进入PAUSED并给明确next action，不能用异常吞掉费用或假定完成。

## 15. 静态验证与实现前的必测情境

仅需标准库+jsonschema/Pillow/Pydantic等既定依赖；Schema使用Draft2020-12与同目录相对`$id/$ref`。resolver先加载全部本地schema并禁网络解析。response/evidence嵌入的done/snapshot合同无需额外协议文件。结构样例见 `examples/state_protocol.example.json`，hash占位的样例只验证形状，不代表存在真实图或通过语义验证。

实现验收必须覆盖：错A/B角色、缺任一图片、候选跨round、旧case/attempt响应、错request/config hash、error带payload/ok空payload、同done重复消费、同task不同合法内容冲突、文件越界与symlink、partial文件不推进、预算失败提交/后台重生成/未知提交、pause后late done、cancel后late费用、事务每个崩溃点恢复、required证据失败、不同role/cache配置未命中、snapshot改写拒绝、HDR未知不静默转换、尺寸不同strict拒绝及记录纯scale例外、重复图立即停、最后槽accepted、固定K与budget_exhausted区分、无usable回退A而baseline不是fallback。只做协议夹具测试，未经真实图片链路实测不声称模型/桌面能力或实验完成。


实施补充（最终集成修复）：case 初始化保存六个实际模板源文件及 stage/path/SHA manifest，实际模板 SHA 映射纳入冻结 config_sha256。freeze.json 哈希源文件；Controller 与桌面导出只从 case 源文件渲染。dispatch 与事务 next_task 保存 template_source_proof（Direct 两个源 direct_ref+execute）以及 exact rendered prompt SHA，事务另绑定 dispatch SHA；Direct artifact 同时保留完整渲染文本与源身份。后续安装包变化不改变历史 case。缺少实际执行证明的旧记录不可静默补写，最终评估记 unverified/protocol_violation。请求、响应与状态 schema 不变。
