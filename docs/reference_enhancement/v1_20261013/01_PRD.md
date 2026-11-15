# HarnessRefEnhance 产品需求文档

版本：`ref_enhance_v1`；日期：2026-10-13；用途：交给工程师实施的 V1 产品定义。
本文件遵循 `00_SHARED_CONTRACT.md`；状态、Schema、Prompt 与实验细节分别见 02、03、04。
本次交付设计与协议材料，没有运行 Controller、Windows 应用或图像模型的实施结果。

## 1. 目标、对象与范围

用户希望把 Modular Neural ISP 已生成的 prediction A，借助同场景 iPhone 17 reference B，生成增强候选 C。
改善项包括可比较的亮度、白平衡、色彩倾向、明暗层次和局部 rendering；保留 A 的内容与构图。
A 是冻结的编辑底图；B 是外观参考，可能来自不同拍摄位置、时刻、曝光及镜头，不能当作像素 GT。
产品名称为 HarnessRefEnhance；原 restoration HarnessIR 的去噪、去模糊任务不是本任务的默认意图。
V1 面向本地单用户研究工作流：Python 3.10+、Streamlit、文件交接、ChatGPT 桌面图像编辑。
无外部模型 API；本地 Controller 自动处理确定性的协议、文件、证据缓存、预算和状态。
ChatGPT 会话承担 Diagnosis、Compose、Execute、Verify、Refine；模型回复是候选事实，需经 Controller 校验。
本地工具可提前离线算完；运行阶段只消费 diagnosis 计划内、校验合格、与图像绑定的证据。
V1 不训练 Neural ISP、不建立新图像匹配模型、不实现全自动登录，也不承诺桌面端后台无人值守。
成功不是“生成了一张更漂亮的图”；必须同时满足参考外观改善和 A 的内容保真。

## 2. 三种实现方案与选择

| 方案 | 可获得的能力 | 代价或限制 | V1 决策 |
|---|---|---|---|
| 纯手动 ChatGPT，多角色复制粘贴 | 最快验证 A/B 两图编辑；人工观察结果 | 易串图、漏证据、重试计数错误；难恢复与审计 | 保留为传输降级，不作为流程状态源 |
| 桌面 UI 脚本包办发送、下载与重试 | 在具体版本实测后可能减少点击 | 窗口、焦点、控件与保存位置易变；可见成功不等于正确任务完成 | 不设为 V1 前置条件；后续仅接经过探测的适配器 |
| 本地文件 Controller + Streamlit + 能力分级会话适配器 | 可审计、可恢复、缓存自动消费；手动与自动走同一协议 | 首期可能仍需人工发送、导入 JSON、保存图片 | **选择本方案** |

选择理由：用户已具备本地 engine/Data 思路，且希望离线工具自动消费；可信文件能隔离模型会话与流程控制。
Controller 不通过 ChatGPT 私有接口或抓取历史取得结果；后续自动派发只能由受支持、实测的机制提供。
模型 API 架构不进入 V1；未来如需替换 transport，业务状态与 evidence 合同仍保持独立。

## 3. 用户旅程与关键体验

1. 工程师先连接已有工作目录，查看盘点报告；用户选择 A、B，填写场景说明及可选敏感区域。
2. 预览明确标注“编辑底图 A”和“外观参考 B”，分别展示尺寸、色彩处理、SHA 与拍摄差异。
3. 用户确认 canonical 预览和可比较性；不支持的 HDR/HEIC 先处理为可解释 SDR，再正式入组。
4. 用户新建 case；Controller 冻结资产、配置、Prompt 版本和预算，生成 Diagnose 任务。
5. Diagnose 说明可比较区域、差距与保护项；Controller 自动查缓存，仅收取计划内证据。
6. 缓存缺失时 UI 列出缺项；用户导入离线包或导出预计算清单，完成后自动续到 Compose。
7. Compose 把证据变为执行文字；用户按当前能力模式发送冻结 A、B 与编辑文字，请求一张 C。
8. C 原始文件导入后完成格式、hash、geometry 等检查；Verify 分别比较 C 对 B 的外观与 C 对 A 的内容。
9. Controller 接受合格候选，或在预算内 Refine 后重新从 A 编辑；用户可暂停、恢复或取消。
10. 结果页显示最终选图、成功与否、停止原因、成本及候选历史；用户导出完整 case 或训练候选包。

用户不需要手工上传每种工具地图；证据包渲染、计划选择和快照绑定由 Controller 完成。
UI 不允许用“人工确认成功”覆盖保真失败；人工改变指令、ROI 或参考必须形成可追溯的新 revision/分支。

## 4. P0 可验收需求

| ID | 需求 | 验收标准 |
|---|---|---|
| P0-01 | 双图角色与内容边界 | 每个任务明确 A/B；把 B 设为编辑底图、交换角色或引用 B 几何的任务被拒绝或阻止执行 |
| P0-02 | 冻结资产 | 保留原文件与 canonical PNG；记录二者 SHA、尺寸、颜色处理；运行中修改文件触发失效而非继续 |
| P0-03 | 可比较性 | 记录全局/局部可比较、不可比较原因和 manual ROI；reference 不可用不会进入无参考成功路径 |
| P0-04 | 严格任务协议 | 请求/响应身份、Schema、SHA、版本与阶段均验证；旧回复、错 case、重复导入不能推进新状态 |
| P0-05 | 文件为状态源 | UI 重启后状态与磁盘一致；只有 Controller 写 state；模型与工具写产物不等于自动通过 |
| P0-06 | 离线缓存自动消费 | 命中缓存后无需上传工具图；仅绑定 tool_plan 项；同名不同图、不同权重/参数/backend 均不错误命中 |
| P0-07 | A/B/C 证据隔离 | 每条证据标角色与 canonical SHA；A 的 OCR/Face、B 的区域统计、C 的核查证据不能互换 |
| P0-08 | 两图执行最小输入 | Execute 每轮只收到冻结 A+B+edit_prompt；没有工具色彩图、诊断 JSON、上轮 C 或历史会话依赖 |
| P0-09 | 保留真实输出 | 原始生成 bytes 不覆盖；没有官方 colour adjustment 拉回 A；任何展示 derivative 另记变换 |
| P0-10 | 保真与外观分离 | Verify 分别输出 style_alignment、content_preservation、critical_defects 与 confidence；geometry 独立检查 |
| P0-11 | 冻结接受与选图 | 接受条件遵循公共合同；最早 accepted 优先，无 accepted 取最早 usable 且 review_required；不按 NR 或最后一轮选成功 |
| P0-12 | 有限重试 | 默认最多 3 次生成，失败提交与可知后台重生成记账；重试总是从 A 开始；JSON 修复最多 1 次 |
| P0-13 | 真实能力标注 | 四项 capability 独立显示 supported/unsupported/untested，保存探测记录；untested 不启用自动化 |
| P0-14 | 一致手动导入 | JSON、图像、缓存导入与自动返回使用同一验证链；错图、坏包、外部绝对路径或穿越路径拒收 |
| P0-15 | 中断与恢复 | 暂停、超时、退出后能恢复 pending task；不能把重发等同重生成；未知执行结果暂停核对预算 |
| P0-16 | 可解释交付 | 成功、终止原因、最终选图来源分开；预算耗尽 success=false；无可用候选时 baseline A 明示 fallback |
| P0-17 | 本地目录保留 | 接入前盘点 engine/Data/cases；默认增量新目录；已有资产不覆盖、旧 case 不静默升级 |
| P0-18 | 实验可复现记录 | 记录配置/Prompt/evidence hashes、实际 UI 模型名、时间、人工步骤、生成数；不可观测信息标 unknown |
| P0-19 | 导出与成本 | 导出含相对路径、状态、原始候选与证据快照；分开记录预计算和在线耗时、cache-hit、人工操作与实际成本 |
| P0-20 | 训练用途分界 | 训练候选包有 selected/fallback/success、内容核查与来源；不会自动写入训练集或把 B/C 宣称像素真值 |

## 5. P1 需求与延期项

| ID | 需求 | 验收或进入条件 |
|---|---|---|
| P1-01 | 经验证的会话派发/落盘适配器 | 独立 probe 通过后启用；升级桌面版本重新探测；失败回到文件导入 |
| P1-02 | 数据集离线队列与缓存包 | 使用同一键和校验器批量导出/导入；部分失败报告具体项，不能把失败注册为空结果 |
| P1-03 | 多样本进度与耗时总览 | 单 case 失败不终止其余 case；每个 case 独立预算，队列操作留审计 |
| P1-04 | 细粒度内容复核界面 | 提供 A/C 对应文字、人脸裁片与核查列表；自动工具漏检/低置信不显示为通过 |
| P1-05 | 固定 ROI 协议与工程辅助 | 对同类区域提供独立 A/B ROI 编辑和覆盖率预览；更改 ROI 形成新配置/分支 |

暂不做：精确跨相机配准、自动语义匹配训练、HDR 外观迁移、视频时序增强、模型微调或商业多用户服务。
新增 CPU/GPU 模型 profile 是部署任务；缓存服务不得为消除缺项而静默换模型、在线下载或临时降分辨率。

## 6. Reference 可比较性与非内容复制

比较的是相近语义表面/区域的 rendering，而非 B 上某像素的目标值或某物体的目标位置。
Manual ROI 是 V1 的可信起点：A、B 各用自身坐标系，标同类区域、面积、遮挡与采样说明，不要求一一像素对应。
全局可比较须检查主要区域组成、视角、照明及拍摄时刻；存在明显差异时降为局部可比较或不可比较。
例如 B 多出大片天空时，不能根据全图均值要求 A 整体变亮；人物姿势变化时，不用 B 的脸形替换 A。
对白墙、天空、肤色、植被、阴影等区域，可观察亮度分位数、色彩倾向与高光/阴影占比，并记录可信范围。
统计结果仅提供诊断证据，不自动推出“B 更真实”；色差可能来自材料、光源和相机位置，而非 ISP 缺陷。
允许增强 A 已存在的层次和质感；不从 B 复制文字、纹理、人物五官、物体、灯光位置、边缘或景深几何。
对 A 原本不可读的文字或细节，不要求补造；对人脸不做美化、身份变化和表情重建。
被遮挡、动态变化、光照变化或语义区域组成不同的区域必须可标 `not_comparable` 并排除迁移目标。
“局部可比较”只对标出的区域提出目标；不能把局部参考推演为全图 tone/style 必须相同。
不可用 reference 的 case 进入 PAUSED，允许换 B 后新建 revision，或结束为失败；不能偷偷变成无参考增强。

## 7. UI 状态、操作与结果呈现

页面结构：case 列表、A/B 预览与可比较性、当前任务与证据、候选对照、日志与导出。
每页顶部显示当前状态、round/attempt、已耗生成预算、能力模式及下一步操作；界面显示由 state 派生。

| 状态 | 用户看到什么 | 允许操作 |
|---|---|---|
| CREATED | 资产预览、canonical 报告、配置摘要 | 启动、另建 revision、取消 |
| WAIT_DIAGNOSIS | 当前 Diagnose 包与角色说明 | 复制任务、导入回复、暂停、取消 |
| WAIT_EVIDENCE | planned/hit/missing/rejected 项与原因 | 导出离线清单、导入缓存、重试校验、暂停、取消 |
| WAIT_COMPOSITION | 已锁定证据快照、Compose 包 | 复制任务、导入回复、暂停、取消 |
| WAIT_EXECUTION | A/B 角色顺序、edit_prompt、预算 | 打开待发送包、提交原始 C、声明执行失败、暂停、取消 |
| WAIT_VERIFICATION | 原始 C、geometry 结果、A/B/C 核查包 | 复制 Verify 任务、导入回复、暂停、取消 |
| WAIT_REFINEMENT | 未通过项、余量、Refine 包 | 复制任务、导入回复、暂停、取消 |
| PAUSED | 暂停原因、挂起阶段、未决外部任务 | 继续核对/修复、另建 revision、取消 |
| COMPLETED | selected output、success、stop_reason、fallback | 下载选图、查看全部候选、导出 case/训练候选包 |
| FAILED | 技术/业务失败、可用产物、恢复说明 | 查看日志、导出、从冻结输入新建分支 |
| CANCELLED | 已取消原因及保留产物 | 查看、导出、另建分支 |

COMPLETED 表示流程终止并完成交付登记；并不保证 success=true。
暂停不撤回已发送的 ChatGPT 任务；收到晚到结果先校验身份与挂起记录，取消后不得自动重开。
按钮“重发任务”只用于传输恢复；“重新生成”会新增计费/预算事件，两者在界面上分开。
敏感动作如换 B、改 Prompt、改证据 profile，在确认后创建新分支，旧 case 继续只读保存。

## 8. 模块输入输出与职责

| 模块 | 输入 | 输出与职责边界 |
|---|---|---|
| AssetService/Canonicalizer | A/B 原文件、冻结转换配置 | EXIF 定向、ICC 转 SDR sRGB PNG；原文件、hash/尺寸/转换记录保留，不修复内容 |
| Controller | case 配置、有效回包、工具事件、操作事件 | 唯一 state 写入、request、预算账本、选择结果、终止原因；不替模型看图 |
| CaseStore/FileBroker | 相对路径任务与产物、内容 hashes | 持久状态、临时文件到完成标记、幂等导入与隔离；不根据文件名猜任务 |
| CapabilityService/DesktopAdapter | 当前主机/应用、probe 记录、待发送任务 | 四项能力状态、传输记录；未知能力要求手动动作 |
| Diagnoser | 冻结 A+B、意图、比较限制 | diagnosis payload 与 tool_plan；不编辑图像，不调用未授权工具 |
| EvidenceService | tool_plan、资产角色、profile/模型/预处理/参数 | 合法缓存条目、case 证据快照、缺项清单；只读取已规划证据 |
| STATS/ROI_COMPARE | canonical 图、独立 ROI、比较性说明 | CPU 可算的区域统计、覆盖率与限制；不产生配准 GT |
| Composer/Refiner | A/B、诊断、计划内证据、必要反馈 | composition/refinement payload 与 edit_prompt；把地图依据转成照片可定位的文字 |
| ExecutorAdapter | 冻结 A+B+edit_prompt | 原始生成 C、可观测模型/会话/操作 metadata；不接收辅助地图 |
| GeometryChecker/Verifier | A/B/C、固定保真与比较规则 | geometry 报告和 verification payload；不写 success，也不是最终论文评审 |
| Selector/Exporter | 全候选、核查、冻结选择规则 | selected candidate 或 baseline fallback、完整审计包、训练候选清单 |

T1=OCR、T2=FACE、T3=DEPTH、T4=SEGMENTATION 延续旧编号；STATS/ROI_COMPARE 单独命名。
T1/T2 主要提供内容保护提示，T3/T4 可辅助区域理解；OCR 识别不等于文字 GT，Face 检测不等于身份保证。
服务只接受约定 Schema 和固定工具名称；不能执行模型回复中的 shell、路径或下载建议。

## 9. 自动化能力的实际边界

| 能力 | 探测成功证据 | 未通过时行为 |
|---|---|---|
| local_file_io | 当前桌面会话可读带随机 nonce 的任务并按规定路径写匹配回复 | 复制任务、手动导入 JSON |
| role_dispatch | Controller 经受支持机制启动/继续指定角色，并收到匹配 task_id 的回复 | 用户点击并发送对应角色任务 |
| two_image_edit | 真实 A/B 编辑任务确认以 A 为底图，得到 C；角色关系无歧义 | PAUSED；能手动两图编辑则记录人工步骤后继续 |
| image_save | 生成原始图保存到规定 task 路径，bytes/hash 可由 Controller 验证 | 用户下载原始图并提交 |

四项互不推定：文件能读写不代表能派发，会返回图片不代表能写入用户磁盘，能编辑单图不代表支持 A/B 角色。
首次默认全部 untested；每项记录应用版本/显示模型名、时间、操作方式、结果与可验证产物。
运行前必须确认 two_image_edit；模型显示名、精确版本/seed 不可观测时分别记录 UI 名称与 unknown。
在任何能力模式下，本地缓存查找、计划筛选、Schema/hash 校验、Prompt 渲染、状态推进均由 Controller 自动完成。
人工发送与保存计入成本，不能把桌面订阅称零成本，也不能将受人工操作的流程标成无人值守。

## 10. 默认策略与异常处理

默认 adaptive 最多 3 次生成；single_pass 独立配置只生成一次，但同样核查与记录，不冒充已接受输出。
默认 format_repair_limit=1，只补 JSON 格式；需重看图、改判断或改指令时必须新阶段任务并留下记录。
正式 profile 要求计划内证据齐全；cache miss 保持 WAIT_EVIDENCE，失败工具不注册成 empty 检测结果。
离线预计算可全量覆盖，但 Compose 只看计划内证据；预处理费用和实际消费集合分别报告。
接受规则：geometry 有效、style_alignment=improved、content_preservation=pass、无 critical_defects、confidence≥0.7。
不以 A/C 原始像素 SSIM 或 chroma drift 的 restoration 阈值阻止合法亮度/色彩增强；结构风险另行核查。
相同 bytes 的候选立即停止为 duplicate_output；停止、选图与 success 分开记，不再浪费下一次生成。
可用候选须 geometry 有效、content_preservation=pass、无 critical_defects 且 confidence≥0.7；接受还须 improved。
有 accepted 取最早 accepted；否则取最早 usable，标 review_required、success=false；没有可用候选交付 A 并显式 fallback。
confidence 不作质量排序，禁止 NR 排序；Adaptive 最早 accepted 停止，DirectBestOfK 跑完 K 后用同一 selector。
JSON 不合法/缺字段：拒收并一次格式修复；错 task/hash/角色：隔离产物并提示原因为何，状态不推进。
损坏文件、断写、未完成标记：不消费；读到完成标记仍验证真实资产，不用“文件存在”判定成功。
HDR/HEIC 或 ICC 无法解释：阻止正式入组，提供明确的 SDR 导出要求，不静默 clip 或忽略 profile。
geometry 默认 strict，C 的方向和尺寸与 canonical A 一致；不满足则失败，保留原始 C。
可预冻结 aspect_preserving_resize 允许纯缩放、宽高比偏差≤0.5%；记录评审 derivative 的缩放/插值/SHA，禁止裁切/补边/warp。
能力探测后若改 geometry 策略，生成新配置哈希并让各实验臂同样重跑；不能见到失败后临时换策略。
内容变化或局部保真不确定：不给自动成功；预算内反馈重试，余量不足保留核查记录并停止。
模型超时/限流/拒绝/无法下载：记录不同原因；未知是否已生成时 PAUSED 核对，不盲目再次提交。
磁盘不足/文件被占用：停止写入并保留可恢复临时产物；不覆盖旧候选或丢失预算账本。

## 11. 训练候选用途与数据治理

C 可以作为后续 Neural ISP 蒸馏或伪标签研究的候选；它是生成结果，不能仅因通过流程核查称为真实成像 GT。
入训练集需独立审核 A/C 的配准、裁切、文字/人脸保真、细节幻觉、色彩策略、授权及输入 RAW 关联。
本系统不自动关联 RAW 与 A，不自动创建损失函数；如研究需要，应使用冻结的 capture_id/ISP checkpoint/hash 建映射。
B 不与 RAW/A 建像素监督损失；非对齐参考不得直接用于 PSNR/SSIM/LPIPS 的“质量”结论。
候选包同时保留 A/B/C 来源、生成次数、selected_round、success、fallback、critical_defects 与审核状态。
默认训练审核状态 pending；FAILED、fallback、content fail/uncertain 不自动进入训练目标集。
未来训练/评审数据拆分须按场景与采集组进行，避免同场景或反复尝试的结果泄漏到测试集。

## 12. 现有工程迁移、拆分与成功标准

已核查仓库是 restoration harness：旧 pipeline 单图执行，且可原地 colour adjustment；旧 selector 全门禁失败仍可能选生成图。
这些行为不适用于参考增强；新增 `engine/src/hre/`，不直接覆写 `harness/` 的语义、门禁或颜色后处理。
旧 Manual 设计可借鉴文件 broker、独立工具进程和缓存，但它是设计资产，不能当作用户 Windows 上实现已完成的证据。
接入前工程师盘点实际 `engine/`、`Data/`、`cases/`、环境与模型 registry；仓库检查不替代现场盘点。
默认原 Data 只读，生成新的 case 与缓存命名空间；遇同名路径停止并报告冲突，不重建整目录。
旧 cache 仅在图像、角色、模型权重、预处理、参数、backend/profile 全部可验证一致时导入；缺字段则隔离待迁移。
旧 case 保留原协议/version；迁移产物写新分支与来源说明；可回滚到旧工程，已有图像与模型不移动或删除。

| 工程任务 | 先决依赖 | 完成证据 |
|---|---|---|
| E1 目录盘点、AssetService、CaseStore | 现场路径与 shared contract | 原资产保留报告；canonical/路径/hash 校验夹具通过 |
| E2 状态机、FileBroker、预算、Selector | E1 + 02 Schema | 幂等、错回包、中断恢复、失败回退的协议测试 |
| E3 EvidenceService、STATS/ROI_COMPARE | E1 + evidence schema/profile | 离线包导入、角色绑定、计划筛选、失效缓存测试 |
| E4 PromptRenderer、手动 transport、Streamlit | E2/E3 + 03 模板 | 完整手动任务可导入；UI 与磁盘状态一致 |
| E5 桌面 probes 与一图真实链 | E4 + 实际 ChatGPT 桌面能力 | A/B 两图编辑与 C 保存的真实产物、人工操作记录 |
| E6 12 对 pilot 与正式冻结 | E5 + 04 实验协议 | 问题清单、冻结 rubric/profile/分组，之后才运行正式对照 |

产品验收先检查协议与恢复，再完成一图真实链；不能用合成 JSON 夹具代替模型编辑效果验证。
工程成功：P0 全部通过、有可复现 case、零跨图证据污染、恢复不重复扣/漏记生成、无隐式内容复制与假成功。
效果成功由冻结盲评决定：外观对 B、内容对 A；1 次对 1 次、K 预算对 K 预算分别报告，不用更多调用包装策略优势。
pilot 只是检验链路、成本与风险；正式质量提升、训练收益及 Windows 性能需后续真实结果支持，本轮不声称已达成。
