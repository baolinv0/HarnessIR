# 本地工具接入 · 工程实施增量

规格依据：docs/10_Local_Tools_Integration_v1_1.md。在原 docs/06 Task4 接收证据模块上扩展；保留 state、JSON验证和独立模型角色。源代码路径是待实现接口，不是本包已经提供可运行工具。

## L1：任务与缓存骨架

创建 engine/src/hir_manual/tool_jobs.py、tool_registry.py、cache.py、tool_service.py；公共类型 ToolJob、EvidenceProfile、ModelRegistry、LocalEvidenceManifest、EvidenceBinding、VisualPack、WorkerResult、ImportSummary 对应增量规格。先写 tests/test_tool_jobs.py、test_cache.py：same contract同key；权重/类别/precision变化新key；empty不是error；并发同key只一进程；旧cache坏图不命中。验证命令 pytest tests/test_tool_jobs.py tests/test_cache.py -q，先失败，再最小实现通过。

## L2：隔离进程与资源监控

创建 resource_monitor.py 与 preprocessing/worker_main.py；实现 run_worker(job: ToolJob, registry: ModelRegistry) -> WorkerResult。不得 shell=True，不得 import torch/Paddle 到Controller；线程2，队列1，执行预算采用profile。tests/test_resource_monitor.py 测 worker子进程OOM/timeout、内存不足resource_wait、进程树终止、无auto-download。先使用可控stub进程测试资源与故障，再实测SDK；stub结果不算算法证据。

## L3：T2与T1真实接入

创建 preprocessing/workers/t2_face.py、t1_ocr.py 与 adapters/face.py、ocr.py。注册确定权重与后端，输出规范schema。tests/test_face_adapter.py 验kps顺序和坐标；test_ocr_adapter.py 验poly/rec文本关联、低置信与空结果。映射SDK原数组时先验证len与ID，不把不同过滤列表直接zip。部署阶段下载与推理阶段离线分开。然后本机3图 warm-up、采样RSS、检查工具卸载。

## L4：T3与T4真实接入

创建 workers/t3_depth.py、t4_yoloe.py、t4_sam3.py 和 adapters/depth.py、segmentation.py。test_depth_adapter.py 测BGR→RGB边界、方向、网格和无有效像素；test_segmentation_adapter.py 测原始label/mask关联、overlap、unknownID、class palette与显示冲突规则。文本embedding预准备，不在推理时触发安装。先CPU small/YOLOE少量图，SAM3留GPU对应环境。

## L5：Composer pack、UI与状态接入

创建 evidence_pack.py；Service接收diagnosis后按需调用resolve_or_enqueue；完成后bind_evidence并发composer；UI展示job状态、成本与模型profile。tests/test_local_tools_flow.py 测：计划空直接compose；仅OCR不自动读取其他缓存；partial policy明确deviation；地图在Composer资产中、执行器资产中没有；worker自身不能写state。profile锁定不可runtime切模型。

## L6：离线迁移与10图pilot

实现export_missing_jobs与import_cache_bundle；tests/test_bundle_import.py 校验原图SHA、缓存合同、relative路径和所有文件hash；bundle entry duplicates拒收。ten-image pilot测试重启、cache hit和模型升级旧case不变。完成后交付运行命令、真实registry、env locks、资源日志与完整case。GPU按目标配置重算，然后实际统计280图清单覆盖。

## 工程师应提供的CLI

- doctor-tools --profile cpu_probe_v1：import/backend/weights+单图warm-up，写真实readiness，不下载。
- tools run --case <id>：按当前冻结计划运行。
- tools precompute --manifest <file> --profile <id> --tool-ids <list>：明确离线全量预计算。
- tools export-missing --manifest <file> --profile gpu_full_v1 --out <bundle>。
- tools import-cache --bundle <file>：只注册缓存，不自动改变已完成case。

验收命令由实现工程提供；本包不含上述CLI。禁止把“协议夹具PASS”表述为“四模型部署成功”。
