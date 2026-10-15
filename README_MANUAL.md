# HarnessIR Manual Wizard v1.1

文件驱动的图像恢复 Controller，包含诊断、按需证据、Composer、编辑、独立 Verifier 和从原图重试。默认执行器是 ChatGPT 桌面人工交接；可显式选择 Gemini API 替代通路。

本目录与上游 `harness/` 并行，不改变上游启动命令。现有 Qwen 适配保留在 `docs/qwen_adaptation/`。原项目许可证见 [LICENSE](LICENSE)；模型权重和数据另遵循各自许可与授权要求。

## Windows 启动

需要 Git、Python 3.11+（当前实测 Python 3.12.14）、PowerShell。完整克隆仓库，保留两个 Design 目录；源码当前通过相对位置加载 schema 和提示模板，不能只复制 engine 或安装孤立 wheel。

```powershell
git clone https://github.com/baolinv0/HarnessIR.git
Set-Location HarnessIR
py -3 -m venv engine/.venv
.\engine\setup.ps1
.\engine\start.ps1
```

访问 http://127.0.0.1:8501 。关闭启动终端或 Ctrl+C 停止 UI。

setup 仅准备 Controller；不会下载 T1–T4 权重。依赖由 `engine/requirements.lock.txt` 约束。上游根目录 requirements 与 Controller 环境分别安装。

## 流程与约束

```text
原始低质量输入 → canonical原图 → 诊断JSON → 严格校验
                                      ↓
                            按需T1–T4 / 同合同缓存
                                      ↓
                         Composer（原图+证据图+图例）
                                      ↓
                          Executor（仅原图+编辑文字）
                                      ↓
                         独立Verifier（原图+真实输出）
                                      ↓
                      接受 / Refiner → 从同一原图重试
```

所有角色禁止使用 GT、参考增强图作输入。最多3次编辑；首轮与最终结果分别保留。Verifier 通过是模型判断，不能代替 GT 或证明普遍质量提升。正式推理禁止自动安装、下载或替换模型。

## Gemini API 可选执行器

仅新建的显式 Gemini case 调用 API，默认桌面通路和已有 case 不自动改变。不需要 computer use。密钥放在仓库外的本地文件，或由运行进程读取 `GEMINI_API_KEY`；不要提交 `.env`、授权缓存或密钥文件。

```powershell
# 只验证认证与模型列表，不生成图片
& engine/.venv/Scripts/python.exe engine/scripts/gemini_route.py models --key-file C:/private/gemini-key.txt

# 显式冻结模型和证据 profile；大图采用 Files API 原始字节上传
& engine/.venv/Scripts/python.exe engine/scripts/gemini_route.py new --input C:/photos/original.jpg --intent "Conservative restoration; preserve identity and geometry" --image-model gemini-3-pro-image --text-model gemini-3.1-pro-preview --evidence-profile gpu_sam31_v5 --media-transport files_api_v1

# 每次执行当前角色；CASE_ID 使用 new 返回的实际值
& engine/.venv/Scripts/python.exe engine/scripts/gemini_route.py run --case CASE_ID --key-file C:/private/gemini-key.txt

# WAIT_EVIDENCE 按实际诊断计划严格查缓存或运行已部署工具
& engine/.venv/Scripts/python.exe -m hir_manual tools run --case CASE_ID
```

以上是本次实测的模型 ID，不保证所有账号均可调用；列表可见不等于 generateContent 可用。没有自动回退模型。API 调用可能收费，图片生成提交状态未知时不自动重发。

`gpu_sam31_v5` 的 T4 为 **cache_only**，必须先按其独立合同导入真实 SAM3.1 证据；空克隆不自带这些缓存。没有证据会明确阻塞。Files 通路为显式配置；旧 inline case 超过20 MB会停止，不缩图、不丢证据。详见 [Gemini 通路](engine/GEMINI_API.md)。

## 工具与数据部署

| 工具 | GPU目标 / 独立替代 | 输出 |
|---|---|---|
| T1 OCR | PP-OCRv6 Medium，检测+识别 | 原图坐标多边形、文字、置信度 |
| T2 人脸 | SCRFD det_10g | 人脸框、五点、置信度 |
| T3 深度 | Depth Anything V2 Base | 原图大小 float32 相对深度及图例 |
| T4 分割 | 原版 SAM3；已授权独立替代 SAM3.1 | 实例 Mask、类别、置信度、提示词及图例 |

CPU Small/YOLOE 配置仅用于相应接口验证，不冒充 Base/SAM3 正式结果。部署前核对官方模型版本、依赖、权重访问条件及实际后端。GPU 远程主机和 Colab 需要用户自行配置授权与可用计算窗口；本仓库不会提供账号或计算资源。

依次阅读 [本地工具说明](engine/README_v1_1.md)、[v1.1接入规格](Design_v1_1_20261012/docs/10_Local_Tools_Integration_v1_1.md)、[实施计划](Design_v1_1_20261012/docs/11_Local_Tools_Implementation_Plan.md) 和 [SAM3.1标准缓存接入](engine/SAM31_NORMALIZATION.md)。

SSH/Colab 客户端的独立安装、固定 source revision 与授权前提见 [远程环境部署](docs/manual_wizard/DEPLOYMENT.md)。

源码 snapshot 中 registry 保留实际部署的来源/权重/后端锁及相对路径，供合同校验；`ready` 记录不表示新机器存在对应权重。新机器必须部署、warm-up并核实资源。旧 case 的模型合同保持不变，升级配置后新建 case。

数据保持在本地 `Data/`，缓存生产协议为：

```text
Data/annotations/cache/<TOOL_ID>/<cache_key>/
  evidence.json
  ...原生数据、证据图和图例...
```

缓存 key 绑定 canonical SHA、权重、配置、类别和实际后端。缓存导入使用独立冻结 export ledger；不能只复制同名 JSON、用模拟结果补齐或从结果反推预期合同。数据布局见 [Data说明](Data/README.md) 和 [filelists说明](Data/filelists/README.md)。filelists、原图、manifest、GT 与模型文件未随源码发布，路径存在性检查须在放入数据后执行。

## 验证

```powershell
# 从仓库根目录运行，只执行工程测试，不调用付费 API 或加载真实模型
& engine/.venv/Scripts/python.exe -m pytest engine/tests -q
```

发布副本的实际检查结果见 [源码发布记录](docs/manual_wizard/SOURCE_RELEASE.md)。测试使用合成图与假传输验证协议，不能代替真实推理验收。历史实现/实验报告按其原始阶段保留；其中的本机路径、runtime链接和原始报告可能仅在原工作区可用。

留存实测：SAM3.1 的20张证据已完成（18非空、2合法空）；一张人像的 Gemini Harness 完整闭环在第二轮获独立 Verifier 接受，夜景 Direct 有失败记录。**20张完整恢复验收尚未完成**，不据此报告通用效果提升或原版 SAM3 正式结论。大图上传和批量 runner 的工程测试与真实模型恢复结果分别记录。

## 源码范围

包含完整 Controller 模块、状态机与传输层、UI/CLI、工具部署/适配/worker、缓存验证、离线导出导入、Colab handoff、报告脚本、工程测试、两版设计规格及模板。少数历史批次脚本依赖原工作区的 manifest、case、冻结作业账本或外部输入；不会用虚构数据替代缺失运行资产。

`.gitignore` 排除运行目录、原图、权重、venv、缓存、密钥和授权文件。所有原始本地资产在发布时保留；notebook 的输出和执行序号已清空。
