# v1.1：T1–T4 本地模型接入规格

本文是本次接入的权威增量规格，与原版 docs/01–09 配套。用户已提供硬件：i5-7200U、2 核 4 线程、7.9 GB RAM。模型选型沿用用户方案；推理速度 / 内存峰值必须在本机实测。本包没有安装或运行这些模型。

## 1. 要改的核心边界

将原来的“用户上传证据”改成“Controller 按诊断计划自动取得证据”。新增 EvidenceService、隔离工具进程、工具任务队列和持久缓存。手动导入保留为同一验证通道。Diagnoser / Composer / Executor / Verifier 的模型与文件交接不因工具本地化自动变得无人值守。

**在线流程**：Diagnosis.tool_plan → ToolResolver 查匹配缓存 → 没有则发本地 ToolJob → 校验原始输出并统一适配 → 固定 case 证据快照 → Composer。全局 workflow 仍在 WAIT_EVIDENCE 等待；UI 自动显示 queued / running / cache_hit / resource_wait / completed / failed。Worker 不写 case.state，只有 Controller 接收通过校验的证据后推进。

**离线流程**：manifest 中的冻结 canonical 图 → 显式预计算作业（可四种全算）→ 同一缓存 → case 按 tool_plan 只读取所需项。预先算过全部工具不能导致 Compose 自动看见全部证据；运行时仍保持按需策略。用掉缓存也不是零计算成本，应报告预处理成本与运行时 cache-hit。

## 2. 模型 profile

| 工具 | cpu_probe_v1 | gpu_full_v1 | 适配器记录 |
|---|---|---|---|
| T1_OCR | PP-OCRv6 Medium det+rec；CPU Paddle | 同模型，GPU Paddle（或明确保留 CPU） | det/rec 各组件哈希、OCR 过滤与尺寸配置 |
| T2_FACE | SCRFD det_10g.onnx，ORT CPU EP | 同模型，实际可用的 ORT GPU EP | bbox、置信度、五点、实际 provider |
| T3_DEPTH | DA-V2 Small/vits，作者 PyTorch API | DA-V2 Base/vitb，同一 API | encoder、权重、预处理、相对深度方向 |
| T4_SEGMENTATION | YOLOE-26n-seg，文本提示实例 Mask | SAM 3，默认 Meta 图像 API，提示 Mask | checkpoint 与语言组件、实现后端、类别表、Mask 阈值 |

cpu_probe_v1 用于接口验证，T3/T4 是替代工具；gpu_full_v1 用原规模工具做正式本系统评测。两者分别锁定，不混入同一实验配置。不自动切换 Small/Tiny、不悄悄将 SAM 3 换成 SAM 3.1；目标模型不可运行时明确报 unavailable。

**原模型名称不等于原工具实现。** 锁定 HarnessIR 的 T3 经 Transformers depth pipeline，T4 经 Ultralytics SAM3SemanticPredictor；本次采用 DA 作者 API / Meta SAM3 API，需要记录实现与预处理差异。若要再接原 HarnessIR 工具路径，建立独立 `gpu_harness_tools_v1` profile 并逐项核对源码、阈值、色彩图与输出，不将本 profile 命名“严格复现”。Executor 仍是 ChatGPT 时，即便工具全部一致，也不是同模型论文复现。

## 3. CPU 资源调度

Controller 环境只放流程、Schema、文件与 UI 依赖，不能 import Paddle / torch / InsightFace。使用配置好的 Python executable 启动独立工具进程，argv 为固定白名单列表，不执行模型输出的命令。

本机默认：max_active_workers=1，batch_size=1，CPU 线程 2；一个 worker 一张图一种工具，用完退出。初次 T2→T1→T3 Small→T4 YOLOE；实际 case 仅执行计划中的工具。不得四模型驻留，也不为“独立任务”并行启动。PyTorch/ORT/OpenMP/MKL 的线程在进程启动前 / SDK 初始化时统一设置，记录实际值。

初始保护配置为工程预算而非运行保证：启动前 available RAM ≥2048 MiB；worker RSS 上限 3072 MiB；运行中 available RAM <512 MiB 则中止 worker 并保留日志；每 200 ms 采样 worker 及子进程 RSS（是采样峰值，不能声称精确峰值）。没有内存余量时 resource_wait，UI 提示关闭占用程序或导出 GPU 作业，不反复重启。

初始 timeout：T2 120 秒、T1 600 秒、T3 600 秒、T4 900 秒，含模型加载；探测后按测得耗时另冻结配置。timeout / oom / import_error / model_missing 分开记录。同配置瞬时 I/O 可重试一次；OOM 不自动降分辨率或换模型。降低尺寸必须形成新 profile / 参数哈希。

GPU 批量阶段可一工具进程串行处理多图以摊薄加载，但仍禁止不同框架同时抢同一 GPU；GPU 总队列默认单 worker。未来并发需要单独资源测试，不是 280 张的前置条件。

## 4. 环境和离线准备

Windows 建议 3 个环境：venv_controller、venv_t12_cpu（Paddle+ORT）、venv_t34_cpu（torch+YOLOE）。若 T1/T2 依赖冲突再分开，不把所有依赖倒入 Controller。Linux 用独立 t12_gpu / t34_gpu；SAM 3 相关环境按官方兼容要求和实际锁定版本搭建。部署准备与恢复运行分开。

model_registry.example.json 中的未安装路径 / SHA 为 null、ready=false；工程师完成下载、组件清单哈希、SDK 导入、设备后端和一张 warm-up 后才生成本机可用 registry。记录 Python / SDK / torch / Paddle / ORT / CUDA / driver 的版本与源码 commit。不能把“包 import 成功”当作模型推理通过。

运行默认 offline=true，auto_download=false，auto_install=false。YOLOE 文本路径要预备文本编码器 / tokenizer / 词表，首次 set_classes 的安装下载工作放在部署阶段；固定类别时可预生成 prompt embedding 或静态导出，导出后类别不可动态变更，要另记产物哈希。SAM 3 checkpoint 访问由用户 / 工程师在准备阶段完成，运行不修复认证、不输出凭据。

## 5. 输出适配

evidence_local.schema.json 使用独立 evidence protocol 1.1；ChatGPT 的 request/response 外层保持 1.0，prompt profile 保持 chatgpt_adapted_v1。不能用 schema 1.0 校验新证据后静默丢字段。旧 evidence.schema.json 只用于 legacy 导入。

每条包含原始图片 SHA、固定 canonical SHA、image_id、evidence_profile_id、model_name、model_bundle_sha256、checkpoint/语言组件清单、实现后端与实际设备、参数哈希、模型输入尺寸、输出网格、坐标变换、quality_warnings、elapsed_ms 与采样 RSS。model_bundle_sha256 从 components 的有序名称+文件 SHA 构造，不能仅靠一个文件名标版本。多组件 OCR 顶层旧 checkpoint_sha256 可 null，但新 bundle 必须有效。

| 任务 | 必须保留 | 给 Composer 的材料 |
|---|---|---|
| OCR | 原始检测多边形、det 与 rec 分别的置信度、原始识别文本、ambiguous、原生 JSON | 框 / 多边形预览、文字与对应原图裁片；不将 OCR 当 GT |
| Face | bbox、score、5 个关键点（缺失明确 null）、原图脸宽高像素、原生 JSON | 人脸位置、像素大小、框图；不用识别 embedding、属性或修复图 |
| Depth | float32 相对深度与 valid mask、输出方向/范围、可视化规则 | grayscale + legend / false-colour 明示，真实相对尺度；不编米制距离 |
| Seg | 每实例 / 提示 Mask、label/prompt ID、score、原生关联关系、重叠区、unassigned | 固定图例的类别预览 + 结构化区域摘要；避免给 editor 地图 |

T4 是提示 / 开放词汇实例证据，不保证覆盖全图。label=0 必须表示 unassigned/unknown，不直接叫背景。原始 Mask 可重叠；每类 union 保留独立文件。可额外生成 display label raster，但它的冲突处理只是显示规则，不能替代 native masks。保留 stable class_id 和 palette；不能按检测返回顺序给每张图随机配色。

默认 T4 类别固定于 profile；CPU 小类别集与 GPU 官方类集分别提供配置。诊断可以决定是否需要 T4，不能偷偷改变类别表。对“发丝”“头发”的专门验证用单独冻结的人像 prompt set；它不等于可靠头发 alpha matting，低分辨率 Mask 不能证明发丝保真。

## 6. 图像与变换

input_sha256 始终指 Executor 使用的 canonical bytes，而不是 worker 临时 resize 图。raw source bytes SHA 另存；工具与模型原始结果都不得回写 / 提亮 canonical。缓存复用依赖 canonical SHA 和 preprocessing version，不能只靠 manifest 的同名 filename。

工具可使用独立缩放视图：cpu_probe 的 T3/T4 默认 full-frame source-view long edge≤1280，推理尺寸 DA 518 / YOLOE 640；T1 原图执行但 det max-side 初始960；T2 full-frame640。GPU full profile 的 source-view / SDK 参数另冻结，不能沿用低分辨率数据却仅将 model_name 改成 Base。

Depth Anything 作者 infer_image 接收 OpenCV BGR 并在内部转 RGB；若从 canonical PIL RGB 获取数组，要在该 API 边界转为 BGR 一次。不能因方案写“RGB”而在 SDK 前后重复交换通道；其他 SDK 按它们各自约定处理，Composer 看到的原图保持 RGB。

所有 OCR polygons、bbox、kps 最终为 canonical_norm。full-frame、crop、resize、letterbox 每个视图独立记录 view_to_canonical 3×3 矩阵；图像网格 shape 与 view ID 明列。Tiled OCR 不能用单个全局变换代替多个 tile。深度连续值双线性缩放，离散 labels 最近邻；native masks 使用锁定的插值 / 阈值规则；保留原始输出。不把上采样当新增细节。

## 7. 小文字和小人脸的两条路径

默认 full_frame_v1 不加任意人工 crop。人像/长焦 pilot 的质量审查记录漏检 / 错识别和 source pixels；high-confidence 也不能等同正确。

若全图缩放会吞掉小字 / 脸，另建 hardcase_roi_v1：固定网格切块（含重叠）或冻结的诊断 ROI → 局部执行 → 坐标反映射 → 固定去重。原图不可读细节依然不可验证。人工手选 ROI 必须标 manual_variant。ROI 政策、tile size / overlap / merge thresholds 纳入缓存键与实验配置，结果与 full_frame 分开报告。

## 8. 缓存与 case 快照

路径：Data/annotations/cache/<tool_id>/<cache_key>/，一个完成目录含 evidence.json、raw、map/overlay 和 ready.json。cache_contract.schema.json 规定 key 内容：canonical SHA、canonicalizer version、tool_id、tool implementation/revision、model bundle SHA、精确推理参数、precision/device/backend versions、prompt-set SHA、adapter version、ROI policy。序列化固定为 JSON(sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False) 的 UTF-8 bytes；SHA-256 后得 cache_key。prompt 顺序有语义，不排序类别列表。

只有内容与文件哈希均通过的 ok cache 可用；failure 只保留运行日志，不能当 empty 检测缓存。相同 cache_key 由一个进程计算，另一个等待，不重复运行。完成写临时目录→rename→ready 最后写入；断点续跑检查真实资产，不仅检查 evidence.json 存在。

绑定 case 时将所需资产复制到 case 的 immutable tools 目录（第一阶段默认复制，避免同步 / 用户修改污染），所有相对路径重写；保存 binding、cache key 和 evidence snapshot SHA。只给 Composer 计划内工具。升级模型会得到新 key 和新 case / 显式分支，不覆盖旧已完成 case 的证据与 instruction。只工具变动的假设也必须重跑 Compose→Execute→Verify。

## 9. 失败政策

延续 v1.0 formal 的 all_planned_tools_required：任一计划工具失败则 blocked / resource_wait，未到 Composer。CPU probe 可配置 continue_with_unavailable：明确错误原因、缺失工具与 partial_evidence，自动继续只为工程探索，deviated=true，不算完整证据主组。策略建 case 时冻结，不因为跑得慢临时换规则。

锁定官方 tools.py 本身允许 soft unavailable；因此 require-all 是我们更严的验收设计，不应声称它是官方必需规则。未检测到对象=工具运行 ok / empty；模型运行失败=unavailable，两者不同。缺图、OOM、坏 Mask、unknown label 分开记录。

工具不会修复原图。辅助工具失败不自动调用图像编辑模型来伪造证据。若 Composer 要额外工具，由诊断修订任务形成新已记录计划，不能绕过计划从缓存里自由挑图。

## 10. GPU 迁移与 280 张作业

Controller 不直连远程服务。导出冻结 canonical 文件、manifest、目标 profile、源码 / 权重清单、缺失 cache contracts 为 transfer 包；GPU 环境离线运行 batch worker；结果 import 包在本机重新验证原图 SHA、key、模型 / backend、资产哈希和相对路径，注册新缓存。CPU 与 GPU 的 absolute paths 不写入可移植结果。

Small→Base、YOLOE→SAM3 必须重算；相同 T1/T2 名称也不能默认复用：只有所有 contract 字段相同才命中。改 device/precision/backend 默认会产生新 key。明确允许跨 backend 复用需要独立等价验证和 reuse exception 记录。

预计算可覆盖四工具，但运行时 consumed evidence 只包含按需集合。manifest 实际图数由扫描计算，约280不是硬编码。统计分别给 planned / precomputed / consumed / unavailable / empty / rejected coverage；不能要求所有照片检测到脸和文字。

磁盘按真实尺寸预算：单张12MP float32 深度约48MB，280张未压缩约13.44GB，尚不含多实例 Mask 和权重。本机 probe 存1280网格的真实浮点数据与低开销预览；GPU 输出配置另冻结。检查空间后再批量，别把 50GB 建议当保证。

## 11. 实现接口与文件

新增 engine/src/hir_manual/tool_jobs.py、tool_service.py、tool_registry.py、resource_monitor.py、cache.py、evidence_pack.py；新增 preprocessing/workers/t1_ocr.py、t2_face.py、t3_depth.py、t4_yoloe.py、t4_sam3.py 与 adapters/。Worker 的依赖各在隔离环境；统一 CLI 接收 --job 与 --out，返回完成标记，不能 import Controller。

公共接口：

- resolve_or_enqueue(case: CasePaths, tool_id: str, profile: EvidenceProfile) -> ToolJob
- make_cache_key(contract: dict) -> str
- run_worker(job: ToolJob, registry: ModelRegistry) -> WorkerResult
- normalize_result(job: ToolJob, raw_dir: Path) -> LocalEvidenceManifest
- bind_evidence(case: CasePaths, manifest: LocalEvidenceManifest) -> EvidenceBinding
- build_composer_pack(case: CasePaths, required_tools: list[str]) -> VisualPack
- export_missing_jobs(dataset_manifest: Path, profile: EvidenceProfile, output: Path) -> Path
- import_cache_bundle(bundle: Path, cache_root: Path) -> ImportSummary

WorkerResult 表示进程/文件结果，不等于模型证据有效；Controller 继续做 schema、坐标、数据 shape、hash、label association 校验。缓存和绑定完成后事件带来源(local_compute/cache_import/manual_import)与实际 worker成本；renderer 不替代看地图的模型推理。

## 12. 实施与验收顺序

1. 加工具服务 / 任务队列 / 缓存协议，先用合成协议文件验证幂等和 state 边界，不安装全部模型来测试协议。
2. 真正部署 T2，3 张单脸 / 多脸 / 远处小脸，检查 bbox/kps、内存和空检测。
3. 真正部署 T1，3 张白天 / 夜间 / 长焦招牌，检查 polygon、文本错识别、confidence 与裁片对应。
4. T3 Small 与 T4 YOLOE 各1–3张，检查方向、Mask类别、overlap、RSS与退出释放。
5. 10张完整 pilot，自动发现缓存、重启、资源等待和手动导入同协议；验证 Composer 实际看到地图。
6. GPU 重算缺失 / 目标模型不同项，导入缓存；重新建立正式 case，不改旧结果；之后才做完整数据集。

必须测：同名字不同 bytes 不命中；权重/阈值/类别/视图/precision改变不命中；空检测与进程error不同；两case共用cache不串图；CPU/GPU路径导入安全；实例Mask与label对不上时拒收；显示0为unknown；tile坐标精确反映射；低内存不并发；升级不改变旧快照；不读未计划工具；T4证据不泄漏到编辑器。

本包只定义上述模块和验证要求，未实现 worker / scheduler / models deployment。下一步交给工程师实施；本机的 7.9GB 是否足够每个实际 SDK，必须通过 warm-up 与采样日志回答。

## 数据校验补充

生产manifest的assets必须覆盖data指向的所有原始输出、depth/valid/preview、Mask/palette文件，逐项核验hash、shape、dtype和source geometry；fixture不提供真实文件不满足生产验收。Seg实例必须按SDK原始关联的mask/box/label/score构建，不能简单zip可能排序不同的数组。SCRFD五点保留native顺序，未经验证不推断人物解剖左右。缓存绑定后evidence_snapshot.json锁定实际消费项与不可用项，收到的新缓存不改变该快照。
