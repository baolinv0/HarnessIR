# HarnessIR Manual Wizard v1.1

2026-10-15 增量：用户已授权新增独立 [Gemini API 可选通路](GEMINI_API.md)，新建 case 时显式选择，默认 ChatGPT 桌面通路及旧 case 不变。已验收的 SAM3.1 替代证据按 [独立标准缓存接入说明](SAM31_NORMALIZATION.md) 导入；不计原 SAM3 正式评测。

在项目根目录 PowerShell 执行。Controller 环境只承担文件协议、状态机、UI和资源监控；模型位于 preprocessing/environments 下的独立环境。正式推理不安装、不下载、不换模型。

```powershell
.\engine\start.ps1
# UI: http://127.0.0.1:8501
# 无 UI 时运行文件接收与自动证据调度；不要同时运行多个 watch
.\engine\.venv\Scripts\python.exe -m hir_manual watch
```

部署准备可联网，按 T2、T1、T3、T4 顺序：

```powershell
.\engine\.venv\Scripts\python.exe preprocessing/prepare_models.py --tool T2_FACE
.\engine\.venv\Scripts\python.exe preprocessing/prepare_models.py --tool T1_OCR
.\engine\.venv\Scripts\python.exe preprocessing/prepare_models.py --tool T3_DEPTH
.\engine\.venv\Scripts\python.exe preprocessing/prepare_models.py --tool T4_SEGMENTATION
```

下载/安装成功只表示部署准备完成。ready 只有真实 warm-up 通过才写入；T4 文本 embedding 的准备也受到内存、进程和超时保护。安装与 embedding 日志在 preprocessing/environments 和 runtime/preparation_logs。低内存时保留已下载资产，释放内存后重试同一命令；不要降低冻结配置的保护值。

真实验收命令：

```powershell
# M1: T2 三张真实照片，随后 T1 三张；遇失败或资源等待停止
.\engine\.venv\Scripts\python.exe engine/scripts/run_real_acceptance.py --stage M1
# M1 通过后 M2: T3 Small / YOLOE 各一张真实照片
.\engine\.venv\Scripts\python.exe engine/scripts/run_real_acceptance.py --stage M2
# 单张强制推理 warm-up（不以缓存命中代替推理）
.\engine\.venv\Scripts\python.exe -m hir_manual doctor-tools --profile cpu_probe_v1 --tool T2_FACE --input "<原图绝对路径>"
# 当前 case 的按需计划
.\engine\.venv\Scripts\python.exe -m hir_manual tools run --case "<case_id>"
```

CPU gate：启动可用 RAM≥2048 MiB，运行中可用 RAM≥512 MiB，工具进程树 RSS≤3072 MiB。T2/T1/T3/T4 预算120/600/600/900秒，含加载。日志位于 runtime/tool_jobs/<job_id>/logs；RSS 是采样峰值。run_real_acceptance 输出在 runtime/acceptance_v11；查看证据图和原生数据后才判断内容质量。模型无法运行与未检出对象分别记录。

新建 case 会冻结 profile、模型 bundle、后端、参数、类别顺序与环境锁。升级后新建 case；旧 case 的快照保持原绑定。已有 case 若冻结了未准备的模型，之后部署成功仍应新建 case，不原地改合同。

```powershell
.\engine\.venv\Scripts\python.exe -m hir_manual new --input "<原图>" --intent "<恢复目标>"
# 保留完全人工工具通道
.\engine\.venv\Scripts\python.exe -m hir_manual new --input "<原图>" --intent "<恢复目标>" --manual-tools
.\engine\.venv\Scripts\python.exe -m hir_manual evidence --case "<case_id>" --file "<证据目录/evidence.json>"
```

证据包中的路径须相对证据目录，所有引用资产必须列入 assets 并带 SHA。手工 v1.1 证据与冻结 case 的合同必须一致；legacy 1.0 导入保留。Composer 接收原图、真实证据图、图例与 unavailable 列表；Executor 只接收原图与编辑文字。Verifier 独立看原图及输出。每次重试从 canonical 开始，最多三次生成。

ChatGPT 桌面没有已验证的自动派发/下载桥时：从 UI 复制任务，上传 allowed_assets 中全部图像，导入角色 JSON；编辑阶段在 ChatGPT 桌面保存完整原始生成图，使用 UI 或 import-image 导入。当前 Work 的本地文件能力不等于桌面图像编辑会话具备相同能力。不要用外部模型 API 替代。

GPU 转移必须先准备目标 Base/SAM3 权重、真实 CUDA 后端和环境锁到 gpu_full_v1 registry。当前主机未部署 GPU，因此导出会明确列出 unresolved，不能构造假权重 SHA。

```powershell
.\engine\.venv\Scripts\python.exe -m hir_manual tools export-missing --manifest Data/manifest.json --profile gpu_full_v1 --out runtime/exports/gpu_jobs.zip
.\engine\.venv\Scripts\python.exe -m hir_manual tools import-cache --bundle "<GPU结果ZIP>"
```

export ZIP 内 bundle.json 为 missing_jobs，保留输入 canonical 与完整 contract；本地 runtime/offline_exports/<bundle_id>/expected.json 是不可替换的导入依据。计算机另一端以同一输入和合同计算，将 bundle_kind 改为 cache_results，各 entry 增加 evidence_dir，放入原格式 evidence.json、全部 raw/map/overlay 资产和同一 input_path，打包ZIP。导回会先全包校验，拒绝重复/越界路径、错图SHA、不同合同、漏文件和坏哈希；只登记缓存，不改完成 case。仍需少量 GPU 复验后再处理完整 manifest。

```powershell
.\engine\.venv\Scripts\python.exe -m pytest engine/tests -q
.\engine\.venv\Scripts\python.exe engine/scripts/check_existing_assets.py
```

当前阶段与限制见 IMPLEMENTATION_REPORT_v1_1.md。合成夹具只验证工程协议，不能代替真实模型验收、恢复效果或总体算法增益。
