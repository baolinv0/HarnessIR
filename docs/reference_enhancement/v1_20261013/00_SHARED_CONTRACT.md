# 公共合同与设计决议

版本 `ref_enhance_v1`，2026-10-13。四个并行设计共用本合同，汇总后以本文件与 JSON Schema 为准。

## 用户目标与交付范围

编辑对象 A 是冻结的 Modular Neural ISP prediction；B 是同场景、非像素对齐的 iPhone 17 外观参考；C 是增强输出。目标是改善可比较的亮度、色彩、层次与局部 rendering，同时保持 A 的内容、构图、人物身份及文字。B 不是像素 GT，不复制其几何、物体或纹理；本系统名称 HarnessRefEnhance。本轮仅交付设计、合同、模板、配置、夹具和校验器，不实现运行 Controller 或调用图像模型。

## 工程边界

新增独立 `engine/src/hre/`，不直接改造现有 restoration `harness/`。本地已建的 `engine/`、`Data/`、`cases/` 要先盘点再增量接入，保留现有资产；仓库当前不代表用户 Windows 工程。Python 3.10+、Streamlit 本地单用户页面、Pydantic v2、Jinja2、jsonschema、Pillow。文件与 JSON 是可信状态源，仅 Controller 推进状态。无 API 的第一阶段使用 ChatGPT 桌面端；文件读写、会话派发、两图编辑、输出落盘均为独立 capability probe，未经实测不可宣称自动化。手动导入走同一校验链。

## 图像与证据

先 EXIF 定向、ICC 转换为冻结的 SDR sRGB canonical PNG；保留原文件。无法解释的 HDR/HEIC 不静默裁剪或忽略 profile；先阻止正式入组并导出可解释的 SDR。A/B 独立尺寸与坐标系。原文件 SHA 与 canonical SHA 均记录。Executor 每轮只能收到冻结 A + B + 编辑文字，无工具色彩图或上轮输出；每次重试从 A 开始。生成原始图必须保留，禁止官方 colour adjustment 把输出拉回 A。geometry 检查与亮度/色彩观察分开，不硬复用 chroma drift / raw SSIM 阈值。

T1=OCR、T2=FACE、T3=DEPTH、T4=SEGMENTATION 保持旧编号；新增 STATS/ROI_COMPARE 独立名称。缓存按图像 canonical SHA、角色、工具模型权重、预处理、参数、backend/profile 绑定；双图/输出不能串证据。允许离线全量预生成、运行时仅消费计划内证据。统计不依赖 GPU；manual ROI 是 V1 的可信起点，不要求新 matcher 模型。遮挡、时间、照明、视角、语义区域组成差异必须能标成不可比较。

## 通用字段（下游必须一致）

资产 `asset_id,path,sha256,role,width,height,color_space`；path 是 case 根下的相对路径，role=`prediction|reference|candidate|evidence`，照片 color_space=`sRGB`。JSON/npy 证据 color_space=null、不可用宽高为null，并使用evidence_format记录kind/dtype/value_range/coordinate_asset_id；可视化证据sRGB。SHA256 为 64 位小写十六进制。

任务 envelope：`schema_version,case_id,case_revision,state_revision_issued,task_id,stage,round,attempt,request_sha256,config_sha256,input_assets,prompt_version,payload`。stage=`diagnose|compose|execute|verify|refine`；round 从 0 开始，attempt 是同阶段传输重发编号。case_revision 绑定冻结输入；state_revision_issued 绑定发任务的事务版本。request_sha256 是规范请求正文（排除此字段）canonical JSON 的 SHA256，config_sha256 同法计算。response echo 相同身份字段并包含 `status,model_observed,session_id,payload`；status=`ok|error`，session_id 不可观测时 null。响应 payload 与 stage schema 匹配。

配置默认 `max_generations=3`（含第一轮；失败提交和可知后台重生成也记账），`format_repair_limit=1`（仅修 JSON，不能替看图），`single_pass` 与 `adaptive` 实验分开。模型内部 seed/精确版本不可见则 unknown，记录 UI 名称、时间、会话、人工步骤；不得编造 model ID。

工作流状态：`CREATED,WAIT_DIAGNOSIS,WAIT_EVIDENCE,WAIT_COMPOSITION,WAIT_EXECUTION,WAIT_VERIFICATION,WAIT_REFINEMENT,PAUSED,COMPLETED,FAILED,CANCELLED`。终止原因与成功分开。Verifier 是流程反馈，不是论文最终独立裁判；Controller 根据冻结规则做接受、停止与选图。

## 阶段 payload 最小合同（由 Agent 3 扩展为 schema）

diagnosis：`reference_usable,comparability,global_gaps,local_gaps,style_targets,preservation_constraints,tool_plan,uncertainties`。
composition：`edit_prompt,edit_targets,protected_content,evidence_ids,reference_limitations`。
verification：`style_alignment` (`improved|unchanged|worse|uncertain`), `content_preservation` (`pass|fail|uncertain`), `critical_defects`, `remaining_issues`, `retry_focus`, `confidence` [0,1]。
refinement：`edit_prompt,changes,retry_focus,source_round`；仍编辑 A，不编辑 C。

V1 接受仅当冻结入组可比较性为usable（Agent还须诊断reference_usable=usable）、可比较目标已有支持，且有效 geometry + style_alignment=improved + content_preservation=pass + critical_defects 为空 + confidence>=0.7。低置信/不可比较不自动判成功；不可用参考暂停以便替换（替换须新 case revision）或记录失败，不能降级成无参考成功。相同 bytes 输出立即停止 `duplicate_output`。可用候选需有效 geometry + content_preservation=pass + critical_defects 空 + confidence>=0.7；选最早 accepted，若无 accepted 则最早 usable 标 `review_required,success=false`，无 usable 回退 A 并标 fallback。confidence 不作质量排序，禁止按 NR 排序。DirectBestOf3 原则跑完K再用相同selector；Adaptive在最早accepted时停止。

停止原因与success互不混写：最后一次正好accepted仍可成功；未accepted耗尽才记budget_exhausted并successfalse。固定K正常结束记fixed_k_complete，可交付此前accepted；duplicate如已有accepted可选其并successtrue。FAILED/CANCELLED始终successfalse。Baseline对照是baseline_only/successfalse/fallbackfalse，失败回退A才fallbacktrue。

Geometry默认strict，宽高与canonical A完全相同；aspect_preserving_resize须预冻结，各臂一致，宽高比相对偏差<=0.005为初筛上界，且raw_w*A_h==raw_h*A_w才允许单一scale派生；raw留存，不允许crop/warp掩盖几何变化。

## 对照原则

Baseline=A；DirectRef=A+B+固定 prompt；AgentSingle=A+B+诊断/按需证据/Compose，一次生成；AgentAdaptive=同流程+反馈重试（至多3）；DirectBestOfK=固定 direct prompt 独立生成3次，同一流程 selector。1次对1次、K预算对K预算分别报告；调用次数与实际成本均报告，不把 3 次 agent 同 1 次 direct 当策略增益。最终评价盲化、冻结 rubric、对所有方法相同；style 对 B、content 对 A；禁止对非对齐 B 直接 PSNR/SSIM/LPIPS 后称质量。流程选择和最终评审分离。先协议测试，再一图真实链，再12对 pilot，再冻结正式分组；无真实数据不声称实验完成。

## 并行文件所有权

Agent 1：01_PRD.md；Agent 2：02_STATE_AND_PROTOCOL.md + schemas/{asset,request,response,state,evidence}.schema.json；Agent 3：03_PROMPTS.md + prompts/ + schemas/{diagnosis,composition,verification,refinement}.schema.json；Agent 4：04_EXPERIMENTS.md + config/experiment_profiles.json + examples/dataset_manifest.example.json。主 Agent：汇总入口、实施计划、验收、仓库适配、公共样例、静态校验与独立审查记录。
