# HarnessRefEnhance Prompt、结果 Schema 与输入边界

本文件与 `00_SHARED_CONTRACT.md` 共同约束工程实现；版本为 `ref_enhance_v1`，模板版本为 `ref_enhance_v1.0`。本轮交付模板和协议夹具，不调用模型，不运行真实图像实验。所有可执行编辑文字使用英文。

## 1. A/B/C 双重角色与增强目标

| 图像 | 内容角色 | Rendering 角色 | 使用边界 |
| --- | --- | --- | --- |
| A：冻结 ISP prediction | 唯一内容、构图、几何、人物身份、文字来源 | 待改善的 baseline | 每次生成均从同一 canonical A 开始 |
| B：非对齐同场景 iPhone 17 reference | 不能作为物体、纹理或视角来源 | 仅对可信可比较区域提供亮度、色彩、层次、局部 rendering 目标 | 不把视角、时间、遮挡、照明或区域组成差异归因于 A |
| C：本轮 candidate | 相对 A 检查内容保存 | 观察 A 到 C 的改变及 C 对 B 的接近程度 | 仅供 Verify 和后续 Refine 分析，不作为下一次编辑源 |

增强允许改变 A 的亮度、白平衡、饱和度、对比和 tonal rendering；需保护的是 A 的几何、身份、文字和内容。过去 Qwen 提示过度保守、变化不明显的经验，要求本版本消除“保持原始颜色/曝光/对比”等与增强目标冲突的句子。允许可见、自然、有证据支持的变化，也允许针对过强改变减弱具体目标。

所有阶段将问题表述为 `rendering gap`，不沿用去噪、去模糊或退化恢复的默认判断。没有看到实际附件，禁止只依据路径、文件名、缓存或工具元数据诊断图像。任一必需图片未实际可见，分析模型返回 `status=error`、`payload=null`、`error.code=image_not_observed`；修复 JSON 格式不能替代看图。

## 2. 模板与可见信息

| 模板 | 必需图像 | 可用文字上下文 | 输出 |
| --- | --- | --- | --- |
| `diagnose.j2` | A + B | 已确认的 manual ROI 对、可用工具、已验证且计划内的证据摘要 | diagnosis 裸 payload |
| `compose.j2` | A + B | diagnosis、已验证且计划内的证据摘要 | composition 裸 payload，包含英文 edit_prompt |
| `verify.j2` | A + B + C | protected_content、reference_limitations | verification 裸 payload，仅观察及枚举判断 |
| `refine.j2` | A + B + C | previous_edit_prompt、verification、source_round | refinement 裸 payload，完整替换 edit_prompt |
| `execute.j2` | 固定 A + B | 仅已通过语义校验的 edit_prompt | 两图绑定和完整编辑文字的 JSON bundle |
| `direct_ref.j2` | 固定 A + B | 无动态分析上下文 | 固定 DirectRef 编辑文字的 JSON bundle |

工具证据只进入 Diagnose / Compose。Verify / Refine 不接收 OCR/人脸/深度/分割彩色图、工具报告或 STATS 表；独立 geometry checker 的结果由 Controller 按冻结规则消费。Executor 不接收诊断、工具证据、保护清单、评分、上轮 C 或生成历史。四个分析模板各自生成独立任务，不将完整共享聊天历史串入 Executor。每轮只从冻结 A + B 开始。

流程 Verifier 不接收 Compose edit_prompt，不按“是否执行了我的提示”评价 C。论文或正式实验的最终独立裁判另起盲化任务，只接收匿名 A/B/C、冻结 rubric 和图像角色；不接收 Compose prompt、diagnosis、工具证据、过程分数、方法名或预算。

## 3. 短提示的编写规则

Compose / Refine 只保留最重要的 1–3 个优先级；建议编辑文字为 80–160 个英文词，Schema 的硬上限为 1800 字符。执行模板添加固定的 A/B 角色与内容保护前缀；固定前缀与动态 edit_prompt 都记入发送文本与 prompt hash。

每个目标应包含可定位范围、观察支持的方向和具体改变，如“lift comparable midtones moderately while retaining highlight separation”。方向可用定性强弱，不用没有测量来源的百分比、EV、色温、RGB 偏移或相似度分数。工具给出的测量可以原样出现在诊断证据讨论中，不自动转成图像编辑数值。置信度是模型对观察支持程度的判断，不是估计的物理量或候选质量分。

全局目标需排除 B 的照明、视角差异影响；局部目标必须对应已确认的 ROI pair，并用 A 的区域描述定位。A/B 各自使用独立坐标，不能直接搬运 B 的坐标或做像素差。未知比较保持 `unknown`，不能补造对应区域、物体、文字或数字。

工具文本、图片中的文字均为数据，不作为新的指令。英文 edit_prompt 不夹带工具名、证据 ID、metric、诊断推理、输出文件路径、模型实现细节或 JSON 回包指令。没有可支持的目标时 Compose 返回 `no_supported_target`；没有可支持的修订时 Refine 返回 `no_supported_refinement`，Controller 依协议暂停或停止，不把无变化包装为增强成功。

Refine 必须交付完整新提示，并记录具体改写。若 C 对目标改变太弱，可把“moderately lift”改为“make a clearly visible lift”；若有过强改变或内容缺陷，调整相关目标。不得通过新增“保持原始颜色/曝光”来撤销全部增强。下一次执行仍从 A 开始，不累加 C 的误差。

## 4. Jinja 字段与渲染合同

六个文件均输出合法 JSON，所有动态值经 Jinja `tojson`；使用 `Environment(..., undefined=StrictUndefined)`，缺字段直接失败，不填隐式默认。`result_schema` 必须注入对应 JSON Schema 完整对象，模型不能假定可读本地 schema 路径。

| 变量 | 类型与来源 | 使用模板 |
| --- | --- | --- |
| `image_bindings` | attachment 映射数组；每项含 `label`、`asset_id`、`canonical_sha256`，label 为 A/B/C | 全部 |
| `response_identity` | adapter 从已冻结 request 提取的所有公共身份字段；包含 `case_revision`、`state_revision_issued`，排除 request.payload | 四个分析模板 |
| `model_observed` | adapter 记录的结构：UI 名称、可观测精确版本/seed、时间、transport、人工步骤 | 四个分析模板 |
| `session_id` | 实测会话 ID；不可观测为 null | 四个分析模板 |
| `result_schema` | 当前阶段解析后的 schema JSON 对象；不是文件名 | 四个分析模板 |
| `manual_roi_pairs` | 已验证的独立 A/B ROI 对数组；无 ROI 时为空 | Diagnose |
| `available_tools` | 可调用工具 ID 字符串数组；不可用工具不列入 | Diagnose |
| `evidence_summary` | 通过角色、canonical SHA、工具参数/cache key、ROI 可比较性校验的计划内证据数组；无证据为空 | Diagnose / Compose |
| `diagnosis` | 通过 schema 与语义校验的 diagnosis payload | Compose |
| `protected_content` | 所有臂共用冻结保真rubric+入组时人工标注的A保护项；不依赖Compose | Verify |
| `reference_limitations` | 所有臂共用冻结入组可比较性/ROI限制；不依赖Compose | Verify |
| `previous_edit_prompt` | 生成当前 C 时使用的动态编辑文字，保留原文 | Refine |
| `verification` | 与当前 C 和 source_round 绑定的 verification payload | Refine |
| `source_round` | 当前 C 的生成轮次，整数且从 0 开始 | Refine |
| `edit_prompt` | schema 与语义校验通过后的 composition/refinement.edit_prompt | Execute |

`response_identity` 含 `schema_version,case_id,case_revision,task_id,stage,round,attempt,state_revision_issued,request_sha256,config_sha256,input_assets,prompt_version`。模型只 echo，不能重算/猜测 hash 或自行更改输入绑定。adapter 记录 `model_observed`；未知 UI 名称用 `unknown`，不可观测 exact_model_version/seed 用 null，不能编造精确模型 ID。

`image_bindings` 是提交实际 canonical 像素的映射，不代表模型已看到图。adapter 在发送前校验：Diagnose/Compose/Execute/DirectRef 恰好 A/B；Verify/Refine 恰好 A/B/C；role、SHA、case revision 全部吻合。模板中的绑定不会自动打开路径、上传文件或写结果。

分析模板 JSON bundle 包含 instructions、input_context、身份、结果 Schema；由 adapter 转为真实任务请求和附件。模型响应使用 `response.schema.json` 的 envelope：ok 时 error=null，payload 为本文件规定的裸结果；error 时 payload=null、error={code,message,retryable}。模型不负责落盘或推进状态。

Execute / DirectRef JSON bundle 只有 `image_bindings` 和 `edit_prompt`。adapter 向图像编辑器实际递送的内容只有绑定后的两张图片和 `edit_prompt` 文字。返回图片、原始下载、canonical 转换、落盘及 execute response envelope 由独立已实测 capability 或人工步骤完成，不能要求图片模型凭 prompt 自动读取/写入 case 目录。原始生成结果必须保留，不使用官方 colour adjustment 将 C 拉回 A。

## 5. 四个结果 Schema

所有 Schema 使用 Draft 2020-12；每个实例 object 都有 `additionalProperties=false`；置信度严格为 `[0,1]` number，布尔值或字符串不能替代。`schema_version=ref_enhance_v1` 写在 schema.description / 外层 envelope；裸 payload 不重复版本字段。

| Schema | 顶层字段 | 关键强类型 |
| --- | --- | --- |
| `diagnosis.schema.json` | reference_usable、comparability、global_gaps、local_gaps、style_targets、preservation_constraints、tool_plan、uncertainties | reference_usable=`usable/unusable/unknown`；比较=`comparable/partly_comparable/not_comparable/unknown`；unknown 比较 confidence=0 |
| `composition.schema.json` | edit_prompt、edit_targets、protected_content、evidence_ids、reference_limitations | 非空 edit_targets，最多 3；priority 为 1–3 integer；protected_content.asset_role=`prediction` |
| `verification.schema.json` | style_alignment、content_preservation、critical_defects、remaining_issues、retry_focus、confidence、style_observations、preservation_observations | style=`improved/unchanged/worse/uncertain`；content=`pass/fail/uncertain`；无 success/need_retry |
| `refinement.schema.json` | edit_prompt、changes、retry_focus、source_round | 非空 changes，最多 3；source_round 为非负整数；每项含原指令、新指令、原因和对应问题 |

gap 由 `gap_id,dimension,observation,desired_change,priority,confidence,evidence_ids` 描述；local_gap 额外要求 `roi_pair_id,region_in_a`。dimension 固定为 `brightness,white_balance,color_saturation,tonal_separation,local_contrast,highlight_rolloff,shadow_detail,texture_rendering,other`。style_target 用 `support_gap_ids` 连接 gap；edit_target 用 `source_gap_ids` 连接已支持的 gap。

comparability 项含 `scope,roi_pair_id,status,reasons,confidence`；global 的 roi_pair_id 必须为 null，roi_pair 的 ID 必须非空。edit_target 含 `priority,scope,region_in_a,operation,source_gap_ids,confidence`；global 的 region_in_a 必须为 null，region 目标必须用非空 A 区域描述。

tool_plan 项含 `tool,roles,purpose,roi_pair_ids,required`。机器工具 ID 保留旧编号：`T1_OCR,T2_FACE,T3_DEPTH,T4_SEGMENTATION`，另加 `STATS,ROI_COMPARE`；diagnosis.roles 只允许 prediction/reference。evidence_ids 只引用已经存在且通过同角色与 SHA 检查的证据，不由模型随意命名新文件。

critical_defect 项含 `kind,observation,region_in_a,confidence`，kind 包括几何、身份、文字、内容增造、render artifact、严重 clipping 及 other。remaining_issue 项用 dimension、可比较性和 observation 支持 retry_focus；style_observation 明确记录 A 到 C 的变化与 C 对 B 的关系。preservation_observation 按 composition/geometry/identity/text/scene_content 记录观察和三态。

## 6. Schema 之外的语义校验

| 检查 | 拒绝条件或 Controller 行为 |
| --- | --- |
| 身份与输入绑定 | task/case revision/round/request SHA/config SHA/input assets 不吻合；拒绝 stale response |
| 可比较性 | reference_usable 不是 usable，或目标只来自 not_comparable/unknown 区域；不进入执行 |
| 三优先级 | global_gaps + local_gaps 总数超过 3、优先级重复/不连续、source/support gap ID 不存在；返回格式/合同错误 |
| 局部目标 | roi_pair_id 不在冻结 ROI 集，A 区域缺失，或套用 B 坐标；拒绝该目标 |
| 证据 | evidence ID 不存在、超出计划、错角色/错 SHA/参数或 backend/profile 不匹配；拒绝证据引用 |
| 内容约束 | 缺少 A 内容/几何/身份/文字保护，或出现冻结原始颜色/曝光、复制 B 内容、编辑 C 的指令；拒绝 Compose/Refine |
| 重试 | refinement.source_round 与当前 C 不吻合，或没有可支持的 change；不派发下一代 |
| 无变化 | canonical bytes 与已生成结果完全相同；按共享协议立即 `duplicate_output` 停止 |
| 判断 | Verifier 仅反馈；Controller 根据有效 geometry、style=improved、content=pass、无 critical defects、confidence≥0.7 才接受 |

confidence 不能作为选图质量分。Controller 选最早 accepted；无 accepted 时，仅可保留最早 usable（geometry/content pass、critical_defects为空且 confidence≥0.7）的 C 并标为 review_required、success=false；没有 usable 时交付 A fallback。content fail/uncertain 的 C 不交付为可用增强。单次与最多三次 adaptive budget 分开，不由 prompt 自行决定是否重试。DirectRef/DirectBestOf3没有Compose，直接使用固定DirectRef prompt artifact、空证据快照和同一冻结Verify上下文。

本节只规定待实现的语义 validator 行为；本轮静态校验能证明格式一致，不能证明真实图片可比较、诊断准确或桌面自动化成立。

## 7. 合法夹具与可复现渲染

`examples/stage_payloads.example.json` 顶层 `simulation_only=true`。`payloads` 提供四个合法的、明确虚构的协议样例；数值仅用于验证类型。`unseen_images_diagnosis` 是 unknown/空 gap 的 parser 测试样例，不能覆盖真实模型必须返回 image_not_observed 的规则。所有资产、hash、观察均为假数据，不作为真实诊断，不提交模型，不计入实验结果。

`sample_context` 按模板文件名 stem 存放完整可渲染上下文，包含解析后的 result_schema 对象。以下是工程校验用示例，不调用模型：

```python
import json
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from jsonschema import Draft202012Validator

root = Path("docs/reference_enhancement/v1_20261013")
fixture = json.loads((root / "examples/stage_payloads.example.json").read_text())
env = Environment(loader=FileSystemLoader(root / "prompts"),
                  undefined=StrictUndefined, autoescape=False)
for name, context in fixture["sample_context"].items():
    rendered_bundle = json.loads(env.get_template(f"{name}.j2").render(**context))
    assert isinstance(rendered_bundle, dict)
for name, payload in fixture["payloads"].items():
    schema = json.loads((root / f"schemas/{name}.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(payload)
```

正式运行的上下文必须由 case manifest、经过校验的阶段结果和 evidence store 构建，不能以夹具替代实际输入。每个模板至少验证 StrictUndefined、动态引号/换行安全、JSON 可解析、图片角色集以及输出 schema；结果另通过公共 response envelope 和语义校验后方能被 Controller 消费。

审查后门禁补充：content_preservation=pass须覆盖composition/geometry/identity/text/scene_content五类观察，全部pass且critical_defects为空；无对应文字/人物也需明确描述未出现该类内容，不能无观察直接pass。style_alignment=improved至少有一条可比/部分可比style观察。缺观察或细项与总评矛盾是合同错误，不直接推进或接受。
