# GPT Image 2 参考 Retouch 工作台

这是已确认设计的可运行实现。入口独立于旧四模型路径，图像执行器固定为 GPT Image 2。

## 启动

在 HarnessIR 根目录运行（Python 3.10+；需要 NumPy 与 Pillow）：

```powershell
$env:PYTHONPATH = (Resolve-Path engine/src).Path
python -m hre.retouch --serve --port 8766 --runs runs/retouch
```

Windows 也可运行 `./start-retouch.ps1`，脚本优先使用项目 `.venv`，也可通过 `-Python` 指定 Python、`-Runs` 指定运行目录。浏览器打开 [本地工作台](http://127.0.0.1:8766/)。

如果使用项目安装环境，可以运行 `hre-retouch --serve`。

## 能看到什么

- A/B 原图和独立坐标的区域框，支持新案例分别拖动圈选。
- 源图问题、八类参考外观、可迁移差异与不可比较/不确定项。
- 实际像素色板、亮度直方图、影调分位数和区域 Lab 数据。
- 每个参考维度的处理方式、目标 ID、引用证据、编辑方向和完成标准。
- 点击目标或证据查看参考区域→源图区域→目标→完整提示→验证的使用链。
- 编辑请求、实际模型身份、全部候选、A/C 对比滑块、逐目标验证和反馈记录。
- 每一步单独执行、导出请求、导入 Agent 观察或实际候选。接口未配置时不生成伪造结果。

结果来源清楚区分：Agent 观察导入、人工观察、像素实测、真实接口调用。分析接口调用数为零不代表没有人工/Agent 读图观察。

## 配置真实接口

诊断、编译、验证、反馈使用能看图并返回 JSON 的视觉语言模型。环境变量：

- `HRE_RETOUCH_VLM_BASE_URL`：OpenAI-compatible 根地址，通常以 /v1 结尾。
- `HRE_RETOUCH_VLM_MODEL`：实际部署的视觉语言模型。
- `HRE_RETOUCH_VLM_API_KEY`：该分析接口的本机密钥；本地无鉴权服务可不设置。
- `OPENAI_API_KEY`：图像接口密钥。
- `OPENAI_BASE_URL`：默认为 https://api.openai.com/v1。
- `HRE_RETOUCH_IMAGE_MODEL`：gpt-image-2 或 gpt-image-2-2026-04-21；不接受其他图像模型。

在启动服务前设置；不要把密钥粘贴进阶段 JSON 或浏览器表单。界面只显示配置是否可用，不显示密钥。服务只监听 127.0.0.1。

图像请求以 A、B 顺序发送两个 image[] 文件，一次请求一张，quality=high，PNG，显式合法画布。省略 input_fidelity，不发送 seed/CFG/steps。真实 HTTP 回执在解析/验证前保存，返回多图时保留完整回执并按实际数量计数，不挑选最佳图冒充单次生成。

## 没有接口时

每一阶段可以导出含 instruction、context、实际附件路径和目标字段的请求。让实际能看见 A/B 的 Agent 完成诊断；把真实 JSON 导入工作台。图像编辑导出会给出原始 A/B 的准备图和最终 prompt。只导入实际 GPT Image 2 输出，并记录可观察身份；仅声明模型名称会被标注为 user_declared，不冒充服务端确认。

GPT Image 2 本身输出图像，不承担文本诊断或 JSON 验证。宿主图像工具若无法确认型号，不能宣称完成指定型号实验。

### 接入宿主或外部生成的真实结果

在「GPT Image 2 编辑」点击「导入编辑结果 C」。若宿主不公开后端型号，填写 `unknown` 并说明来源；它作为型号未确认的外部候选继续验证，不会冒充 GPT Image 2 接口回执。可粘贴本轮实际执行的提示词，单独记录在候选轮次中，不覆盖冻结的目标合同。

外部结果分辨率不同时，只有确认保留了源图完整构图，才勾选完整画幅缩放。程序检查长宽比仅有像素取整范围内的误差，保留原生图片，并显式记录缩放到源图尺寸的对比图与几何变换。缩放不增加真实细节，也不证明几何保真；明显不同的画幅会拒绝导入。原生结果下载入口和尺寸说明在候选对比上方。

导入后进入「逐目标验证」。未配置分析接口时仍可导出验证请求，由实际读图的独立 Agent 查看 A/B/C 与冻结目标，再导入其 JSON 观察。必需项或保护项不确定时进入复核；反馈页会展示本轮决定与复核事项，不自动追加生成。

## 合同与反馈

新案例还要求诊断 `candidate_deltas` 包含唯一 ID、独立 A/B 观察、区域、属性、可比性、方向及双图证据；每个目标用 `delta_id` 引用对应差异并保留其事实。`already_satisfied` 仅接受无未决差异、八维覆盖闭合的 `already_close` 诊断；参考不足不能进入编辑或成功。新验收固定检查 `naturalness`、`reference_content_leakage`、`unsupported_detail` 三类，并要求各项引用相应的 A/B/C 证据。新阶段导出已给出这些结构；历史案例保留原结构。

诊断必须覆盖八类参考外观，允许明确 uncertain/N/A。目标合同逐项映射到编辑目标或保留/排除/不确定理由；所有引用必须属于当前 A/B 或已声明区域。源图已明确的保护事实不能在编译时丢失。

必需目标 partial/unmet/uncertain 不算成功。每项源图保护事实都需要单独检查；合法颜色变化不直接当内容损伤。验证只读取冻结目标、A/B/C、真实证据和几何变换，不读取生成提示或编辑模型名称。

反馈只响应真实未达成/损伤观察，仍从原始 A+B 生成，保留完整目标。最多三次图像调用、八次分析接口调用，无隐式重试。若图像请求结果未知，界面会阻止再次提交；导入同一请求结果时必须勾选关联确认，不重复计数。第三次未知请求也能核对恢复。

## 新案例的外观与交付验收

2026-10-26 起新建案例固定 `acceptance_version=reference_retouch_delivery_v2`。创建时冻结独立的 `delivery_requirements`，默认要求原生结果至少达到源图宽高；细节真实性没有足够证据时不作认证。

通过 `POST /api/cases` 可以在创建请求中明确修改交付范围，例如：

```json
{
  "delivery_requirements": {
    "require_native_source_resolution": true,
    "require_detail_pass": false,
    "minimum_native_size": [1024, 1024]
  }
}
```

`minimum_native_size` 可省略；宽高必须是正整数，两个开关必须是真正的布尔值。需要预览级交付时，可在新案例创建前显式设置 `require_native_source_resolution=false` 和较小的原生尺寸下限。运行后不能通过反馈降低已冻结要求。

工作台分别保存 `appearance_status` 和 `delivery_assessment`，并展示实际原生文件、交付/对比图及要求尺寸。尺寸检查读取真实原生 PNG；插值后的对比图不满足原生分辨率证明。若外观通过但原生交付失败或不确定，案例以 `delivery_not_met` 停止并保留结果，不能显示整体通过，也不为了碰运气自动追加重绘。

启用 `require_detail_pass=true` 时，独立验证必须明确给出 `detail_preservation=pass`，否则交付不通过。验证请求包含 `candidate_native` 原生图、冻结交付要求和尺寸记录；无法确认原有高频细节时应填写 `uncertain`。自然度、身份检查或颜色更接近参考，不能替代原有细节的真实性检查。源图无需修改而直接交付 A 时，保留原图像素。

历史案例没有这个验收版本时，保留其原有状态与验收语义。查看报告只显示“历史未冻结独立交付门槛”及可读到的原生/交付尺寸，不修改历史 state，也不按新门槛追溯降级。

## 本地案例与公开代码

用户的输入图、候选、文件名、原始采集信息、完整测量和回执留在本地运行目录，不随代码公开。新环境从创建 A/B 案例开始；工作台只展示实际存在的本地记录。

## 已执行的 V2 实验对照

从侧栏「实验对照」进入 `/experiments`。它只读取本地真实保存的实验记录，不发起模型调用。开发验证包括五次主对照、一次独立的 A+A 自参考干预、两个原样图像验证器检查，以及零生成的控制器分支检查。历史 case 不改写。

界面分别显示必需外观/内容判断、含可选项的目标达成数、原生尺寸及规格、后端身份、全部实际提示和候选。已有宿主工具实验的后端为 unknown；结构化流程由 Agent 辅助，未运行已配置 API 的自动编排。公开的脱敏发现与边界见 [实验摘要](docs/reference_retouch/CASE_EXPERIMENT.md)。

## 检查命令

```powershell
$env:PYTHONPATH = (Resolve-Path engine/src).Path
python -m unittest discover -s engine/tests -p 'test_retouch_*.py'
node --check engine/src/hre/retouch/static/app.js
```

新测试覆盖参考维度/目标/源图保护覆盖、部分达成拒绝、未知状态、原始 A/B 反馈、预算与请求核对、真实本地 multipart HTTP、失败回执保留及额外输出计数。它们验证软件规则，不证明图像增强有效。旧四模型未在本次做 GPU 推理或质量比较。

## 文件

- `engine/src/hre/retouch/`：独立的合同、证据、阶段控制、接口、HTTP 与浏览器界面。
- `engine/src/hre/retouch/templates/`：六阶段提示词。
- `engine/tests/test_retouch_workbench.py`、`test_retouch_http.py`：软件与本地请求验证。
- `engine/tests/test_retouch_delivery.py`：新交付门槛、历史只读兼容及原生尺寸检查。
