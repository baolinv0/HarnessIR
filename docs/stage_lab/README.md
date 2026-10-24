# 分阶段模型测试台

服务器 VLM 校准实验：[完整实验计划](../experiments/vlm_stage_calibration_20261024/EXPERIMENT_PLAN.md) · [报告模板](../experiments/vlm_stage_calibration_20261024/REPORT_TEMPLATE.md) · [配置与记录表](../experiments/vlm_stage_calibration_20261024/README.md)。测试对象为本分支；先对比 27B/32B/8B 的 D/P/J，再按需验证 C/E。

`hre lab` 把参考增强拆成五个可独立运行、保存和比较的阶段。每次只选择要测试的阶段、模型和输入；已有结果可以继续交给任意下一阶段。CLI、Streamlit 界面和离线 HTML 报告共用同一份实验数据。

| 阶段 | 要测试什么 | 输入 | 输出与对比 |
| --- | --- | --- | --- |
| 1 · `diagnose` | 模型看到了什么语义差异 | 原图 A、参考图 B、任务 | 观察、区域关系、可比性、不确定性；并排文本 / JSON |
| 2 · `plan` | 如何把差异转成 action | A/B、选定观察或手写上下文 | actions、采纳 / 拒绝理由、编辑指令；动作与来源对照 |
| 3 · `compile` | 如何表达给特定编辑模型 | A/B、同一 action、模型 profile | PUP Caption / VGL / PE-I2I / Recaption 等实际条件 |
| 4 · `execute` | 编辑器是否执行了条件 | A/B、选定编译结果或直接指令 | 原始生成图、A/C 滑块、尺寸与像素变化描述 |
| 5 · `judge` | 判别模型如何评价同一结果 | A/B、候选 C | 参考跟随、内容保真、区域协调、缺陷与不确定性 |

`diagnose`、`plan`、`judge` 使用具备图像理解能力的 VLM。FLUX、Fibo、Qwen-Image 和 FireRed 在此接入的是原生条件处理 / 图像执行能力，不能直接当作这三个阶段的判别模型。模型名相近也不代表它们是同一个运行组件。

## 先运行演示

在仓库根目录执行：

```bash
python -m pip install -e ./engine
hre lab demo --root Data/stage_lab_demo
hre lab ui --root Data/stage_lab_demo
```

演示会完成五阶段、写入不同模型配置的结果并生成 `Data/stage_lab_demo/comparison.html`。可直接打开 HTML，也可在界面中按阶段筛选、并排查看、比较文本差异和图像变化。没有 `hre` 命令时，用 `python -m hre` 替代。

**demo 是带明确标记的合成样例，不调用真实模型，也不能用于模型性能结论。**

## 配置真实模型与案例

复制 [models.example.json](models.example.json)，仅保留需要的配置，填好实际模型 ID、接口、原生仓库和权重路径。`YOUR_*` 和 `/absolute/path/to/*` 都需要替换。

```bash
cp docs/stage_lab/models.example.json models.local.json
# 编辑 models.local.json 后，按其中的 api_key_env 在当前环境设置密钥。
hre lab init --root Data/stage_lab --models models.local.json
hre lab add-case --root Data/stage_lab --case-id backlit \
  --prediction /path/to/A.png --reference /path/to/B.png \
  --task '借鉴 B 的影调和颜色，适度显露人物衣服已有细节，保留 A 的内容与逆光关系'
hre lab ui --root Data/stage_lab
```

A 是被编辑的内容来源；B 是外观参考，允许构图和内容不同，不作为逐像素真值。案例保存原始输入及 SHA256，生成图保留原始字节和尺寸。运行期间出错的模型会留下错误记录，同批其他模型继续执行。

修改配置后，使用 `hre lab models --root Data/stage_lab --file models.local.json` 更新；仅加 `--root` 可查看当前模型。配置键是实验中的模型 ID，同一服务可注册成多个 ID 来比较 prompt、参数或编译方式。

| 配置 | 连接方式 |
| --- | --- |
| `vlm_openai` | OpenAI-compatible `/chat/completions`，A/B/C 按角色作为多图输入；填写可用的视觉语言模型 ID |
| `vlm_gemini` | Gemini `generateContent`，读取 `GEMINI_API_KEY` |
| `image_openai` | `mode: image-edit` 调用 `/images/edits`，multipart 上传 A/B；接口需支持多图编辑 |
| `image_gemini` | Gemini 图像模型，返回文本和图像；与 VLM 分开配置 |
| `flux3` / `fibo2` / `qwen_pe` / `qwen21` / `firered11` | 调用本地原生 worker，见下方运行环境说明 |
| `manual` | 导出请求，到外部服务运行，再导入真实输出 |
| `demo` | 仅用于检查功能和界面 |

API 密钥通过环境变量读取，不写进配置。`base_url` 可改为兼容服务；也支持 `base_url_env`。OpenAI-compatible 的 `parameters` 原样传入请求，Gemini 的 `parameters` 对应 `generationConfig`。不同服务支持的参数由其实际接口决定。

## 逐阶段运行与比较

以下命令中的 `DIAGNOSE_RUN`、`PLAN_RUN`、`COMPILE_RUN`、`EXECUTE_RUN` 替换为上一步返回的 `id`。也可运行 `hre lab runs --root Data/stage_lab --case-id backlit --stage diagnose` 查询。每次 `run` 都会保存一份新结果并刷新 HTML 报告。

### 1. 对同一 A/B 比较各模型的差异描述

```bash
hre lab run --root Data/stage_lab --case-id backlit \
  --stage diagnose --models vlm_openai vlm_gemini
```

先在界面查看每个模型实际观察到的属性、区域关系、证据和不确定性。文本 diff 用于定位措辞与结构变化；语义差异仍需结合图像和输出内容查看，不把字面相似度当作正确性。

### 2. 固定同一份观察，比较 action 规划

```bash
hre lab run --root Data/stage_lab --case-id backlit \
  --stage plan --models vlm_openai vlm_gemini \
  --from-run DIAGNOSE_RUN --profile qwen21
```

这样各规划模型读到同一份观察和同一编辑器 profile。如果同时选择两个 `--from-run` 和两个模型，默认得到 **2 × 2 = 4 次运行**，分别观察上游差异是否影响规划。若希望各模型同时参考两份观察，加 `--combine-sources`，这时得到两次运行。

### 3. 固定同一 action，比较各自原生条件处理

```bash
hre lab run --root Data/stage_lab --case-id backlit \
  --stage compile --models flux3 fibo2 qwen_pe firered11 \
  --from-run PLAN_RUN
```

这里不传统一 `--profile`，使用各配置的 `flux3_klein` / `fibo2` / `qwen21` / `firered11`。输出分别记录真实 Caption、VGL、重写指令或 Recaption；可以查看编译是否遗漏、修改或新增了 action 含义。

也可以选 `vlm_openai --profile fibo2` 来测试通用 VLM 的条件规划，但该输出是建议 / brief；真正的 Fibo VGL 由 `fibo2` 的原生 `bria-vgl` 编译器生成。

### 4. 把各编译结果交给对应编辑器

```bash
hre lab run --root Data/stage_lab --case-id backlit \
  --stage execute --models qwen21 --from-run COMPILE_RUN
```

此处的 `COMPILE_RUN` 应是 `qwen_pe` 的结果。FLUX、Fibo 和 FireRed 同理，分别选择对应编译运行。已有编译结果会传入实际执行条件；不会为了方便比较而把原生结构都改写成同一段通用文本。

如果要比较同一通用编辑指令下的多个图像服务，可使用 `--models image_openai image_gemini --prompt-file edit.txt`。如果比较 Native 与 Harness，请将两种条件保存为不同运行、保持同一编辑器设置；PUP、VGL 等原生步骤的收益不能全部归因于新增规划。

### 5. 固定候选图，比较判别模型

```bash
hre lab run --root Data/stage_lab --case-id backlit \
  --stage judge --models vlm_openai vlm_gemini --from-run EXECUTE_RUN
```

默认 judge 只读取原始任务与 A/B/C，不传上游模型名称、诊断、规划理由或补充上下文。也可直接传 `--candidate /path/to/C1.png /path/to/C2.png`；默认每张候选分别交给每个判别模型。同时选择执行结果和外部候选时，各自独立判别。要让模型同时看多个候选，使用 `--combine-sources` 并提供明确的 `--prompt-file`，说明 C、C2 的比较方式。

结果判别和 action 完成度是不同问题。若要测后者，创建上下文文件：

```json
{
  "judge_mode": "action",
  "action": "仅适度提亮衣服中已有的暗部细节，保持人物仍处于逆光阴影"
}
```

通过 `--context judge-action.json` 运行，输出会额外要求 `action_completion`，仍保留参考跟随与内容保真的判断。人为编辑的候选、未改动的 A、已知损坏的候选也都可直接作为 C 输入，用于检查判别模型是否能识别这些差别；测试台不自动把任何模型的评价当作真值。

## 跳过前面阶段，直接调试某一阶段

所有阶段都可独立运行。需要自己指定输入时，使用 `--context` 提供 JSON，或 `--prompt-file` / `--prompt` 完整替换阶段 prompt。例如 `action.json`：

```json
{
  "instruction": "图 A 是编辑基底，图 B 仅提供影调参考。适度显露图 A 人物衣服已有的暗部细节，同时保留逆光轮廓、背景亮度关系与场景内容。"
}
```

```bash
hre lab run --root Data/stage_lab --case-id backlit \
  --stage compile --models qwen_pe --context action.json
hre lab run --root Data/stage_lab --case-id backlit \
  --stage execute --models qwen21 --context action.json
hre lab run --root Data/stage_lab --case-id backlit \
  --stage judge --models vlm_gemini --candidate /path/to/external_C.png
```

第二条直接执行手写指令，没有先运行 PE-I2I。编辑器原生条件也可通过 `context.condition` 传给原生 worker。`--prompt-file` 会完整替换默认 prompt，因此应自己写清 A/B/C 角色和需要的输出格式。

## 原生模型运行环境

主测试台使用 CPU 即可运行；真实权重推理由各模型自己的环境承担。在已按对应官方说明安装好的环境中执行 `python -m pip install --no-deps -e /absolute/path/to/HarnessIR/engine`，然后将模型配置的 `command[0]` 改为该环境 Python 的绝对路径。无需把四套 Torch / Diffusers / vLLM 依赖塞进同一环境。

统一命令协议是：

```bash
python -m hre.stage_lab.native_workers qwen21 \
  --request /path/to/request.json --output /path/to/response.json
```

| Worker | 实际条件处理 / 执行路径 | 需要配置 |
| --- | --- | --- |
| `flux3` | 官方 `flux3.pup.Upsampler`；`flux3.generate` / `Models` | `native_repo`、完整官方权重布局的 `weights_dir`；可设 `model_variant`、`quant`、`pup_checkpoint`、`boxes` |
| `fibo` | `bria_vgl.modify`；`BriaFibo2Pipeline` | `bria-vgl` 与支持该 Pipeline 的 Diffusers；`checkpoint`、`compiler`、可选 `fonts` |
| `qwen_pe` | 官方 PE-I2I `prompt_rewrite` 实现 | `native_repo`、`Qwen/Qwen-Image-2.1-PE-I2I` 权重，及对应 Transformers 环境 |
| `qwen21` | `QwenImage21Pipeline` | 支持该 Pipeline 的 Diffusers、`Qwen/Qwen-Image-2.1` 权重 |
| `firered` | 官方 `agent.recaption`；`QwenImageEditPlusPipeline` | compile 时需 `native_repo` 与 Recaption 服务配置；执行需对应 Diffusers 和权重 |

编译器自身可能还会调用 VLM：Fibo 的 `compiler.llm` 可指定 `bria-vgl` 支持的服务，默认编译环境需 `GEMINI_API_KEY` 或 `GOOGLE_API_KEY`；FireRed 按官方 `RECAPTION_PROVIDER`、模型和接口环境变量配置。这些编译器与 D/P/J 阶段注册的 VLM 是独立组件，真实使用的编译模型记录在运行 metadata 中。

原生参数放在模型配置的 `parameters` 中：`seed`、`device`、`dtype`、`checkpoint`，`load` 对应权重加载选项，`inference` 对应原生推理选项。FLUX 的步数参数是 `steps`；其他 Pipeline 使用 `num_inference_steps`。示例提供起始配置，可按各模型的实际环境调整并保存；不同模型不必强行统一 CFG 和 steps。

当前接入范围：

- FLUX 无编译输入时默认启用 PUP，有编译输入时默认直接使用已有 Caption；BBox 是原生条件，不是硬 Mask。
- Fibo 无编译输入时会运行原生 VGL 编译；已有 VGL 则直接执行。当前 Mask 路径支持单图，A/B 多图加 Mask 没有在此 worker 中组合实现。
- Qwen 的 PE-I2I 是显式 compile 阶段，execute 不自动叠加重写。`ratio_follow` / `wh_ratio` 会进入画布设置；可在 `inference.width` / `height` 显式指定尺寸，并在结果检查 `size_matches_A`。
- FireRed 的 compile 是文本 Recaption；execute 使用选定编译结果。当前处理最多三张图，尚未接入多图裁切拼接或单图 ROI 裁切再融合策略。

本测试台已包含可调用的原生 worker；真实模型可用性和生成效果需在配置好权重、GPU 与原生依赖的环境中运行验证。协议测试与 demo 不代表四个模型的实测效果。

## 外部服务、手动导入与自定义 worker

没有可用 API 也可以完成每阶段比较。导出包含 prompt、JSON 请求与输入图片的目录：

```bash
hre lab export --root Data/stage_lab --case-id backlit \
  --stage diagnose --model manual
```

导出的 `request.json` 使用相对包目录的图片路径，并标记 `image_path_base: request_directory`，整个目录可复制到模型所在机器；原生 worker 会相对 request 文件解析这些路径。将目录里的图像和 prompt 交给外部模型，保存实际响应后导入：

```bash
hre lab import --root Data/stage_lab --case-id backlit \
  --stage diagnose --model manual --json diagnosis.json
hre lab import --root Data/stage_lab --case-id backlit \
  --stage plan --model manual --text-file plan.txt --from-run DIAGNOSE_RUN
hre lab import --root Data/stage_lab --case-id backlit \
  --stage execute --model manual --image C.png --from-run COMPILE_RUN
```

`--json` 导入该阶段的输出数据本身；`--text-file` 保存原文；`--image` 可提供多张图，三种方式可组合。`--from-run` 记录来源，导入后同样可以被下一阶段复用。为了区分外部模型，可在配置中复制 `manual` 条目并修改 ID / `model`。

自定义本地 / 远程调用脚本用 `provider: command`，`command` 是 argv 数组，支持 `{request}`、`{output}`、`{output_dir}` 占位符，不经过 shell。脚本读取 request JSON，写出：

```json
{
  "text": "实际模型输出原文",
  "data": {"native_prompt": "实际可执行条件"},
  "images": ["C.png"],
  "usage": {},
  "metadata": {"checkpoint": "实际使用的权重版本"}
}
```

`images` 使用绝对路径，或相对输出目录的路径；文字阶段留空数组。执行阶段必须返回至少一张图片。脚本的 stdout / stderr 保存到各运行目录，便于检查原生环境错误。

## 输出、可视化与解释

```bash
hre lab report --root Data/stage_lab
hre lab report --root Data/stage_lab --case-id backlit --stage execute \
  --out Data/stage_lab/execute-report.html
```

HTML 报告自包含，可离线打开，支持案例 / 阶段 / 模型 / 状态筛选、文本差异、JSON、原图 / 候选图查看和 A/C 滑块。Streamlit 界面还支持选择上游结果继续运行、上传候选、编辑 prompt 与上下文、导入导出。

数据位置：`lab.json` 保存模型配置；`cases/<case-id>/` 保存 A/B 与任务；`runs/<run-id>/` 保存 request、result、原始输出、判别候选快照与日志；`exports/` 保存外部交接包；`comparison.html` 是当前全量报告。

耗时、provider 返回的 usage 和推理参数用于查看执行成本。`mean_luma`、暗 / 亮像素比例、相对 A 的 RGB 变化和尺寸一致性只是**描述性指标**，不等于参考匹配、语义正确性或图像质量分数。当前没有自动把各阶段结果折成单一排行榜；判断应保留逐阶段证据，必要时结合人工已知标签与独立盲评。
