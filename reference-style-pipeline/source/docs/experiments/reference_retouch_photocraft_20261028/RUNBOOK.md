# 摄影师式工具路线运行说明

## 当前交付边界

新增 `hre tool-retouch` 显式入口。原 `hre lab`、v1/v2 生成路线不变。本实现不是 PhotoCraft UI，也不承诺 Photoshop 数值等价。真实后端需先完成下面的批准构建与 M0 probe；没有二进制、模型或掩膜时失败关闭，不自动替换为 NumPy 修图或伪造观察。

源代码：`engine/src/hre/tool_retouch/`；真实 PhotoCraft 封装：`engine/photocraft_worker/`；测试替身仅位于 `engine/tests/tool_retouch/helpers.py`。

## 1 环境与测试

使用仓库既有 Python 依赖。此环境额外测试依赖在 `/tmp/harness-test-deps`，不修改系统安装：

```bash
PYTHONPATH=engine/src:/tmp/harness-test-deps python -m pytest engine/tests/tool_retouch -q
PYTHONPATH=engine/src:/tmp/harness-test-deps python -m pytest engine/tests -q
PYTHONPATH=engine/src python -m hre tool-retouch --help
```

若迁移环境，按 `engine/pyproject.toml` 安装项目与 test extra；当前测试还需要 Jinja2（既有依赖）。

## 2 PhotoCraft 构建（本环境已获批准并完成）

拟使用官方 rustup：`https://sh.rustup.rs`；工具链源 `https://static.rust-lang.org`。固定 Rust 1.95.0，minimal profile，`RUSTUP_HOME=/workspace/toolchains/rustup`，`CARGO_HOME=/workspace/toolchains/cargo`。不使用管理员权限，不更改系统 PATH 配置或账户凭据。下载依赖、构建脚本及第三方源程序执行属于需确认范围。

批准安装后，构建命令为：

```bash
CARGO_HOME=/workspace/toolchains/cargo RUSTUP_HOME=/workspace/toolchains/rustup /workspace/toolchains/cargo/bin/cargo +1.95.0 build --locked --release --manifest-path engine/photocraft_worker/Cargo.toml
sha256sum engine/photocraft_worker/target/release/harnessir-photocraft-worker
```

Cargo.toml 中两个直接 PhotoCraft crate 均固定提交 `b1794c6e0608ccfc887213dcf58398977c5cb75e`。第一次解析后保存 Cargo.lock；后续构建加 `--locked`。本环境已保存 Cargo.lock 与依赖树，并完成 release 构建；复现应使用 `--locked`。

获得实际二进制路径和 SHA 后：

```bash
PYTHONPATH=engine/src python -m hre tool-retouch capabilities --executable /absolute/path/to/harnessir-photocraft-worker --sha256 ACTUAL_SHA256
PYTHONPATH=engine/src python -m hre tool-retouch probe --executable /absolute/path/to/harnessir-photocraft-worker --sha256 ACTUAL_SHA256 --out /new/probe-directory
```

`probe.json` 检查空计划、每种操作 identity、曝光方向、全零/全一/局部 mask、原生 16 位导出、重放。探针通过仅证明所列合成用例，不证明所有真实照片有效。`capabilities` 的状态仍是 code_verified；运行证据另由 probe 绑定二进制哈希记录。

封装直接构造 PhotoCraft `Document/Adjustment/Surface/LayerMask`，使用 `compose::render` 的原生浮点缓冲。没有 `mask.import` 或任意 `command_run`；不使用 `trusted_local` 通用命令入口。CPU 单线程固定，文档 RGB U16 sRGB，输出 raw float32，再由 HarnessIR 导出带 ICC 的 RGB16 PNG。不是 8 位 preview 放大。

## 3 样例与真实输入配置

生成可运行的合成输入和完整配置，明确不是正式摄影样本：

```bash
PYTHONPATH=engine/src python engine/examples/tool_retouch/make_synthetic_inputs.py --out /new/synthetic-inputs
PYTHONPATH=engine/src python -m hre tool-retouch audit --config /new/synthetic-inputs/config.json --out /new/audit-run
```

`audit` 不运行 PhotoCraft/VLM。`run` 前在 config 中填实际二进制路径、哈希；冻结后的配置不可修改，修改须创建新 out。相对路径以配置目录为基准。

配置数据：

- source/reference：实际文件路径、SHA256、`assume_srgb` 布尔值。JPEG/PNG 等 RGB8 有 ICC 时经 LittleCMS 转换到 sRGB；未知编码无 ICC 要显式假设。RGB16 支持非交错 RGB PNG；只接受与规范 sRGB 色度/TRC 标签一致的 ICC、sRGB chunk 或显式无 ICC 假设。非 sRGB RGB16、RAW、16 位 TIFF、alpha 均明确拒绝，必须在上游完成可追溯的高精度转换。
- masks：`.npy` 二维 [0,1] coverage，`allow_pickle=False`，每个 mask 独立文件哈希、A/B side、生产者和版本。需要真实自动分割工具生成的掩膜；本实现不下载权重、不伪造自动分割。可导入人工 mask，但 `regions[].provenance=manual_diagnostic` 必须保留，不能混为全自动主成绩。
- regions：A/B 各自 mask ID、语义、comparable / partially_comparable / not_comparable、具体理由、provenance。A/B 可以尺寸不同，不能把 B mask 复制缩放当 A mask。
- support_policy：内部边缘剔除半径、最小像素和最小剩余覆盖率。截断剔除只在 A/B 初始阶段计算；输出沿用冻结支持，不重新剔除输出中的难像素。
- edit_masks：从 A mask 派生的可编辑覆盖、原生像素 feather、覆盖强度 density，可选 4 点线性 Y 窗口。这里 density 是 HarnessIR effect coverage，不是 PhotoCraft 同名 slider；实际后端固定 mask density=1 / feather=0，避免重复羽化。
- policy：实际开发集容差表、identity/区域外/截断/边缘/细节保护阈值、搜索预算；样例阈值只是合成工程示例，未经人审校准，不能直接称正式门槛。
- provenance：A/B 处理链、拍摄间隔（未知 null）、限制、development / held_out。

已有 `harness/perception/segment.py::run_segment` 的 seg_ids.png/seg_summary.json 可通过 `tool_retouch.segmentation.import_harness_segments` 导入，必须额外提供真实源图/生产版本/产物哈希回执；类名相同不证明同一对象。该导入器不执行 SAM3。

双侧自动分割调度已接入 `inputs`：参考 `engine/examples/tool_retouch/config.sam3.example.json`，配置 `segmentation` 并将顶层 masks/regions 留空。代码调用既有 `harness.perception.segment.run_segment`，A/B 顺序运行，不因 A/B 同标签就自动建立高置信对应。`segmentation.regions` 必须提供实际对应关系、可比等级和理由。自动语义标签/对应提案目前仍由配置提供，不把 VLM 猜测当像素 mask。

调度要求已经在本地提供的 checkpoint 与 SHA256、实际已安装的 ultralytics 版本、labels/conf/iou/imgsz/timeout。不会安装包或下载模型。生产 runner 在独立 Python 子进程中固定 CPU、禁用可见 GPU、设置 HuggingFace 离线模式，并拒绝 Python socket connect；这不是 OS 层网络沙箱。若 tokenizer 或其他本地资产缺失，明确失败而不下载。**本任务没有执行该真实模型路径。**

每侧缓存键绑定原始文件、色彩上下文、checkpoint、分割参数、版本、既有 SAM3 实现和调度 worker 源码；输出 label raster、summary、mask 均验证哈希和尺寸。成功缓存可恢复；失败/中断状态保留，不会因重复 run 自动重试。需要调查原因后显式建立新运行目录。A 成功而 B 失败时保存 A，不把半套双侧结果晋升为完整证据。

编辑 mask 可使用 `source_mask: "region:wall"` 绑定配置 region_id 对应的 A mask，避免依赖模型返回的数字 label id。分割只看到 canonical sRGB 的 RGB8副本；后续测量与修图仍使用原高精度数组。统计/评价支持继续在 A/B 独立 mask 上构建并冻结。

## 4 VLM 与离线交接

支持两种明确配置，规划者与评审者分别配置、上下文隔离：

```json
{"mode":"files"}
```

或已经在本机运行、由用户配置的 OpenAI 兼容服务：

```json
{"mode":"local_openai","url":"http://127.0.0.1:8000/v1/chat/completions","model":"ACTUAL_LOCAL_MODEL_ID","timeout":120}
```

只允许字面 loopback 地址，不读 API 密钥，不走环境代理，不跟随重定向，不向新外部服务上传照片。真实服务未启动时应失败；没有内置生成替身。

```bash
PYTHONPATH=engine/src python -m hre tool-retouch run --config case/config.json --out /new/run
```

files 模式会写 `planner/NN-stage-hash/request.json` 或 `reviewer/.../request.json`，状态为 `waiting_for_response`。请求包含实际证据、合同/工具域及 A/B/C 规范预览、区域视图和原生裁剪（base64）。将模型实际 JSON 回包保存为同目录 `response.json`：

```json
{"request_sha256":"SHA256_OF_CANONICAL_REQUEST","observer":"实际模型或观察者","payload":{}}
```

请求 hash 即目录后缀对应完整 SHA：对请求 JSON 用 `hre.tool_retouch.contracts.canonical` 编码后 SHA256。payload 字段定义在 `providers.py` 的阶段说明、`contracts.compile_contract`、`planner.validate_plan`、`verifier.validate_visual`；不接受模型传入测量值、阈值、路径或命令。运行同一条 `run` 命令继续。已完成的请求和各次渲染按哈希重用；replay 使用独立 invocation，不会把一次缓存命中假称两次后端重放。

若调用已有提交标记但没有回执，标记结果不确定，不自动重发。需要先人工核对本地服务回执再导入绑定 response。错误终止后不可修改旧结果重跑；另建 run 保留失败。

## 5 输出与状态

保留原始文件、规范 RGB16 A/B、双侧冻结 ROI、实际编辑 mask、输入/配置快照、合同、完整 VLM 请求/回执、各次渲染、参数搜索日志、原生候选、重放、result.json 和单文件 REPORT.md。`result.output=original_A` 明确指向原图，不输出一个经过 identity 变换的假原图。CLI 失败/暂停 exit code=2，不能以进程有 JSON 输出当成功。

accepted 必须同时通过：所有 mandatory 数值目标、所有目标的独立视觉回执、每个保护项、自然性/参考匹配、原生检查和实际重放。感知目标不纳入伪造的数值总分；真实效果证据始终另记，自动 accepted 不会把 `real_effect_validated` 自动设 true。

预算最多 3 次计划、每轮 40 / 总 120 次预览、3 次原生候选和最多 3 次额外原生 replay 检查、8 次 VLM。replay 独立计数，成本不得藏入 3 次候选预算。未知/损坏服务会停止并回退 A。内环参数每轮重新从 identity 起步；局部/全局每次重算全部冻结 ROI 与关系。

## 6 G/T 实验入口

生成基线 G 继续用原来的 `hre lab` 或既有生成配置，冻结模型版本、prompt/config hash 和 seed，再导入实际输出；本入口不调用付费生成服务，不降低基线质量。T 使用本路线 run。

实验 manifest 结构见 `experiment.export_experiment`：protocol_id、split、seed、development_case_ids、baseline（model/version/prompt_sha256/seed/configuration_sha256）、original_user_goal、cases。每个 case 固定 A/B SHA，G 回执需绑定相同 A/B 和基线配置，tool_run 指向 T run。

```bash
PYTHONPATH=engine/src python -m hre tool-retouch experiment --manifest experiment.json --out /new/comparison
PYTHONPATH=engine/src python -m hre tool-retouch analyze --experiment /new/comparison --ratings observed-ratings.json
```

`review/` 为匿名随机 X/Y 包，原始完整用户目标先于合同评审；映射保留在包外。共同显示尺度不放大小图；单独提供各自原生图。G 尺寸不匹配 A 时记交付差异，不虚构逐像素对齐测量。所有计划图像对，包括失败与未运行，留在结果中；统计单位是图像对。ratings.template.json 必须由真实评审填写，未评填 unrated；单评审局限保留。当前分析不计算可靠性不足的自动“风格总分”或假设两路线等效。

## 7 自动诊断入口（本轮补齐）

使用 `config.automatic.example.json`，不要预填 labels、regions、masks、edit_masks。用户配置原始目标、本地分割资产与模型、颜色/预算/开发容差等技术政策。`automatic_diagnosis.provider` 与其他 provider 一样支持 files 或 literal-loopback local_openai。

`hre tool-retouch run` 中的链路为：VLM discover_regions → 独立 A/B SAM3 → VLM correspond_regions（实际mask叠图/区域视图）→ 固定内部支持与测量 → VLM diagnose（八维差异及证据）→ VLM contract（delta_id继承）→ VLM plan → 确定性求解 → 原生独立验收。全部控制字段做结构和引用验证；VLM不能伪造mask或统计值。

初始语义调用保存到 semantic_vlm/，离线等待可重复同一命令恢复。预处理配置写 preprocess_binding.json；改配置需新run。前两次语义调用计入总VLM预算，典型首次闭环共6次，总上限仍8次。普通配置仍是“配置区域+VLM目标”模式，与新全自动语义模式通过audit.automatic_diagnosis区分。真实VLM/SAM3未在本任务运行，文件模式需要实际回包，不能把替身测试当真实诊断效果。

## 8 真实 CPU 验证记录（2026-10-29）

本环境真实 worker SHA256 为 `2c87bc8bfb9a5a69388afebbbb82ff1875e566b03ca8599768803f2b88ae0f74`。20 条 probe 检查通过，回执与构建信息在 verification/photocraft-runtime-probe.json、photocraft-build.json。包含四算子非零变化、软 mask 边缘、超过 2MP 原生往返。它不证明摄影风格质量。

```bash
HRE_TEST_PHOTOCRAFT_WORKER="$PWD/engine/photocraft_worker/target/release/harnessir-photocraft-worker" PYTHONPATH=engine/src:/tmp/harness-test-deps python -m pytest engine/tests/tool_retouch -q
```

未提供该显式变量时，4 项实际后端测试跳过，不能报告它们通过。真实后端 workflow 测试仍使用 planner/reviewer 替身，simulation=true；另测试真实进程 timeout 回退和 Rust 非法请求拒绝。

Camera0717 原始 JPEG 应只读保留：`ColorContext.load` 先按 EXIF 方向转正，再通过实际嵌入 ICC 和 LittleCMS `profileToProfile` 转为 sRGB，不能删 profile 或直接 assign。RGB8 P3→sRGB 存在目标色域限制与 8bit 量化，不可逆；RGB16 导出不会恢复原 P3 色域或增加输入信息。原文件 hash、原 ICC hash、方向及转正尺寸必须记录，不能把此相机 JPEG 对照称为 linear→prediction 正式集。

## 9 当前对话与逐阶段报告

当前聊天配置、精确回执与图像导出见 CURRENT_CHAT_PROTOCOL.md。支持 mode=files、provider=current_chat_offline；按真实请求逐阶段观察，不能把标签当作实际模型已响应。运行自动生成 trace/*.json 与展开的 REPORT.md，包含暂停/失败、来源、阶段变化、原生候选索引及参数/mask/目标差异。恢复时追加attempt记录；不是覆盖或假称重新实际执行缓存渲染。

## 10 审查后运行语义

感知目标有实际视觉未满足反馈时允许预算内候选验证，即便数值残差已经为零；安全、已满足mandatory数值目标和原生复核不放松。unsupported_targets必须显式报告。best_safe需要content/naturalness/所有保护pass且native_inspected=true。仅实际非identity局部mask进入接缝检查，记录实际checked_mask_ids。export、exported_native_acceptance、replay各自写trace，包括失败分支。

完整源码交接包snapshot/可直接作为仓库运行树，不需另取基线才有hre.storage；安装按engine/pyproject.toml与requirements进行，原生Rust依赖按Cargo.lock固定。MediaPipe父环境适配不要被此包覆盖：整合核心workflow/solver/verifier修复时保留父任务新后端文件。

## 11 MPO primary-frame输入

JPEG文件扩展名不等于单帧JPEG。MPO取primary frame0，记录source_format/frame_count/frame_index/frame_policy，保留原字节/ICC/hash并按原EXIF转正和ICC转换。1..64帧、RGB primary；损坏MP目录、非RGB primary拒绝。不会把辅助gain-map帧作为linear输入，也不自动HDR合成。ColorContext新字段会令旧冻结快照不匹配，使用新run。
