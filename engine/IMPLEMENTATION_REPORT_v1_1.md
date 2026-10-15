# HarnessIR Manual Wizard v1.1 实施与验收记录

记录日期：2026-10-13（Asia/Shanghai）。工程增量已实现并通过回归；真实实验停在 M1 的内存门槛，M1–M5 尚未完成。未调用外部模型 API，也未用其他图像模型代替 ChatGPT 桌面 Executor。

## 已实现、已验证、待完成

已沿用原 engine 的状态机、角色任务、独立 Verifier、原图重试、事务恢复和手动图片导入。新增自动证据调度、隔离 worker、资源监控、严格 1.1 证据校验、合同缓存、immutable case binding、证据图/图例 pack、手工 1.1 导入、离线作业导出及结果导回。

实际验证：196 项测试通过，耗时105.95秒；JUnit 为 engine/validation/v11_tests.xml。其中合成证据只用于协议、缓存和几何验证。Windows Job Object 的真实子进程测试覆盖即时退出父进程的遗留子进程、超时孙进程、分配失败前停止和无法确认释放时的 false 状态。已有 Data 的238个 input/GT文件与现有 manifest SHA全部一致。当前 manifest 实际164张，不将用户所述约280张视为已存在或已处理。

待完成：四工具真实照片验收、真实证据图交付 Composer、ChatGPT 桌面编辑保存、独立验证和重试、10图完整pilot，以及GPU Base/SAM3正式评测。

## 阶段交付

| 阶段 | 工程流程证据 | 实际恢复效果 | 实验支持的结论 / 阻塞 |
|---|---|---|---|
| M0 | 当前本地 Work 读取真实256×256低光人像，返回诊断JSON；Controller接受并进入WAIT_EVIDENCE。向导随后自动记录冻结模型尚无warm-up为unavailable，按CPU partial policy进入WAIT_COMPOSITION，并标记deviated | 未编辑，未验证 | 最小诊断交接与状态推进通过；不代表桌面Executor已验证 |
| M1 | T2/T1适配器与隔离环境准备；实际M1启动检查记录resource_wait，PID=null，没有调用模型。3张T2+3张T1真实照片计划已固定 | 尚无推理证据 | 实测证明低内存时不启动模型；不能支持检测/OCR质量或实际内存结论。M1未通过 |
| M2 | DA-V2 Small已准备；YOLOE权重/依赖已准备，文本embedding准备被resource_wait阻止。浮点深度、Mask关联、union/overlap、palette、图例和坐标的合成协议测试通过 | 尚无推理证据 | M1未通过，因此未提前开展真实M2；CPU工具仅作为接口验证 |
| M3 | 原有完整状态机与≤3次生成预算、从canonical重试继续通过；桌面手工导入通道保留 | Direct首轮0张、Harness首轮0张、最终0张 | 本会话没有可操作ChatGPT桌面表面或已验证派发/保存桥；完整真实闭环未完成，首轮和最终效果均未知 |
| M4 | 准备10张真实照片的pilot清单；缓存命中、中断恢复、失败/空检测分离、旧快照不变的协议测试通过 | 未运行真实10图闭环 | 待M1–M3完成；人工操作次数不能由合成夹具替代 |
| M5 | 目标模型/后端锁定检查，拒绝CPU Small/YOLOE冒充GPU Base/SAM3；离线bundle合同/原图/资产哈希/重复和路径安全测试通过 | 未进行GPU评测 | 无已部署并验证的GPU环境；本地manifest164张，完整约280张manifest尚未确认 |

## 本机能力实测

| 能力 | 结果 | 实测范围 |
|---|---|---|
| 本地JSON读写 | supported | 当前Work会话读取随机nonce与图片并在指定本地路径写回JSON，重新校验时间与nonce |
| 会话派发 | unsupported | 对原有待执行任务调用派发入口，返回unsupported；UI自动化inventory只有Codex浏览器，没有原生ChatGPT桌面表面 |
| 图片本地保存 | 现有PNG复制/哈希 supported | 不等于ChatGPT生成图保存；保存原始生成图仍需桌面实际操作后导入 |
| ChatGPT图像编辑及自动保存 | untested | 没有生成图片，未将Work文件权限或子代理视为桌面能力 |

证据：runtime/v11_m0/minimal_chain.json、runtime/v11_m0/capability_check.json、runtime/probes/0711f6a696e06b38。M0 case为case_59b9a98f07434ad1，诊断diagnose_4d91ef1e208e4831。canonical SHA为882cae04a775483d6885b6f0da1a5fdc67077b04d51f0a9da1be54a14fcd1a98。真实图像是Data/HardCases/Portrait/LowLight/HC_WildDark_124/input.png；没有向角色提供GT。

## 实际版本、资源与来源

Controller：Python3.12.14，hir-manual1.1.0，psutil7.2.2；依赖闭包已更新到engine/requirements.lock.txt。CPU单worker、单图、2线程，运行后退出；Windows在启动前将挂起进程分配至kill-on-close Job Object。模型SDK不导入Controller。

| 工具 | 本机准备的指定模型与环境 | readiness |
|---|---|---|
| T2 | SCRFD det_10g.onnx，ORT1.23.2 CPUExecutionProvider，InsightFace源码3e6486942a1be2da0e5b475fac375ea73264bd21，只提取检测权重 | false，缺真实warm-up |
| T1 | PP-OCRv6 medium det+rec，Paddle3.3.1、PaddleOCR3.7.0、PaddleX3.7.2 | false，缺真实warm-up |
| T3 | DA-V2 Small，作者源码a561b849ebae10a6f5ef49e26c83cbbcd36c71bf，权重revision03876f8651c73a60fe4c2c48294e09fcb6838fcf，Torch2.10.0+cpu/Torchvision0.25.0+cpu | false，缺真实warm-up |
| T4 | YOLOE-26n-seg与MobileCLIP官方v8.4.0资产；Ultralytics8.4.175、CLIP1.0锁定源码7ffa84b3bfa40c42ecc1c77147a855e69cb2dd40，Torch2.10.0+cpu，NumPy2.5.2、OpenCV5.0.0.93 | false，文本embedding准备和warm-up待完成 |

完整bundle SHA、后端、组件和依赖锁见preprocessing/registry/cpu_probe_v1.json及engine/validation/deployment_v11.json。T4未生成完整可用bundle，未伪造model_bundle_sha256。下载来源/文件哈希在各models/*/source_lock.json；安装pip报告/freeze在preprocessing/environments。CLIP官方源码包中CLAUDE.md符号链接跳过并记录，未读取为指令。

本机物理RAM约8048MiB，2物理/4逻辑CPU。启动要求可用2048MiB，运行中abort floor512MiB，worker树RSS上限3072MiB，采样200ms。M1尝试时实际可用1235.12MiB；T4文本embedding准备时1497.71MiB，均没有启动子进程。elapsed_ms=0、peak_rss_mb=0表示尚未启动，不能当作模型性能测量。最后部署汇总检查可用1333.5MiB。未关闭其他应用、未降低保护阈值、未换模型。GPU硬件WMI读取被系统拒绝，未据此宣称已检测到或未检测到CUDA设备；目标GPU环境未部署是确定事实。

日志：runtime/tool_jobs/tool_d9025100f94f4442becacdd448a92d78/logs/resource_guard.json与result.json；runtime/preparation_logs/t4_text_embeddings；runtime/acceptance_v11/M1.json、M2.json。工具模型尚未实际运行，因此没有真实模型耗时/峰值RSS、空检测率或恢复分数可报告。

## 启动与下一步

在项目根目录PowerShell：

```powershell
.\engine\start.ps1
# http://127.0.0.1:8501
.\engine\.venv\Scripts\python.exe engine/scripts/run_real_acceptance.py --stage M1
.\engine\.venv\Scripts\python.exe preprocessing/prepare_models.py --tool T4_SEGMENTATION
.\engine\.venv\Scripts\python.exe engine/scripts/run_real_acceptance.py --stage M2
```

先释放内存使可用RAM达到2048MiB，再依次完成T2三图、T1三图，检查实际坐标和内容；之后补齐T4 embedding准备，运行M2并看深度方向/Mask/图例。真实warm-up通过后新建case，避免修改已冻结未准备模型的旧case。在ChatGPT桌面手动完成一张Direct和一张Harness首轮，保存原始输出，经独立Verifier判断，必要时从原图重试，≤3次；首轮与最终分别记录。随后才运行runtime/acceptance_v11/pilot10.json的10图完整pilot，CPU工具结果标为接口验证。

GPU迁移需准备真实Base/SAM3、SDK/CUDA/driver及锁定后端，先少量复验，再导出缺失作业并导回严格匹配的缓存，重新创建正式case。详细CLI、手工JSON/图片和ZIP协议见README_v1_1.md。当前结论只支持工程流程与低内存保护，不能支持恢复效果或Harness优于Direct。
