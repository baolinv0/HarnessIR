# HarnessIR Manual Wizard

当前版本 **1.1**，基础依据 `../Design_v1_20261012`，本地工具依据 `../Design_v1_1_20261012`。Controller 不调用模型 API。Data、GT 与实验原始资产保持原目录；新缓存写入 Data/annotations/cache。

2026-10-13 的 [20图质量优先 pilot](QUALITY20_REPORT_20261013.md) 已完成真实Work诊断交接20/20与中断恢复，14张等待证据、6张等待Composer，尚未产生恢复图片。用 `.\engine\start-quality20.ps1` 在8502查看该独立批次。工程回归207项通过；本地模型首图仍因内存不足未启动，不能据此宣称恢复效果。

在项目根目录 PowerShell 启动（本机依赖已安装）：

```powershell
.\engine\start.ps1
```

浏览器打开 http://127.0.0.1:8501 。关闭启动终端或按 Ctrl+C 停止服务。向导内每秒接收 done，不需另开 watch。首次安装或另换电脑：

```powershell
.\engine\setup.ps1
```

也可按实施计划从 engine 目录运行：

```powershell
.\.venv\Scripts\python.exe -m streamlit run src/hir_manual/ui.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

## 最短人工交接

1. 新建 case，固定原图与恢复 intent。
2. 在独立 Diagnoser 会话上传 canonical 原图，复制当前完整任务。导入返回 JSON；无工具计划时立即出现 Composer。
3. 如有工具，自动查缓存并串行运行已部署且通过 warm-up 的工具。CPU 配置只有一个进程、单图、2线程，用完退出。内存不足进入 resource_wait；失败与空检测分别记录。也可导入 v1.1 evidence.json，走相同合同、内容和哈希验证。CPU允许明确记录 unavailable 后进入 Composer，并将 case 标为偏离；正式 GPU 配置要求所有计划工具成功。
4. Composer 看原图和所有证据地图，生成 composition JSON。导入后，当前任务只含原图和编辑 instruction。
5. 新建 ChatGPT 桌面图像编辑会话，上传 canonical，并发送 instruction 原文。可记录“已提交”；保存第一张完整原始生成图，连同额外生成图按提供顺序导入。此动作将图片记入预算，然后自动发出 Verifier。
6. 独立 Verifier 看原图和所有输出，不看编辑指令。导入 verification JSON；成功早停，失败按预算 refine 或以 incomplete 终止。所有重试仍用同一 canonical。

图像编辑功能是否可用、生成与下载是否成功均以实际 ChatGPT 桌面操作为准。没有桥接时本地程序不会唤醒角色会话。当前能力证据在 `../runtime/capabilities.json`；Work 本地文件能力不等于图像编辑模式的文件能力。

## CLI

以下从项目根目录运行；`--root` 可放在子命令前后。所有 CLI 和向导使用同一服务。

```powershell
.\engine\.venv\Scripts\python.exe -m hir_manual new --input 'C:\path\photo.png' --intent 'Restore conservatively'
.\engine\.venv\Scripts\python.exe -m hir_manual inspect --case CASE_ID
.\engine\.venv\Scripts\python.exe -m hir_manual import-json --case CASE_ID --task TASK_ID --file payload.json --model '界面实际显示名'
.\engine\.venv\Scripts\python.exe -m hir_manual import-image --case CASE_ID --task TASK_ID --file result.png --model '界面实际显示名'
.\engine\.venv\Scripts\python.exe -m hir_manual evidence --case CASE_ID --file evidence.json
.\engine\.venv\Scripts\python.exe -m hir_manual submitted --case CASE_ID
.\engine\.venv\Scripts\python.exe -m hir_manual pause --case CASE_ID
.\engine\.venv\Scripts\python.exe -m hir_manual resume --case CASE_ID
.\engine\.venv\Scripts\python.exe -m hir_manual export --case CASE_ID --out runtime/exports/audit.zip
```

`import-image --extra other.png` 可重复，用于如实登记同一次请求的全部输出。不要按美观挑图。导出不覆盖已有 ZIP。

本地 Work 写回时使用仅写文件的桥，随后 Controller watcher 接收：

```powershell
.\engine\.venv\Scripts\python.exe -m hir_manual write-response --case CASE_ID --task TASK_ID --file payload.json --model '实际显示名' --session '实际会话 ID'
.\engine\.venv\Scripts\python.exe -m hir_manual watch --once
```

`write-response` 不写 state。payload-only 与完整 response envelope 都通过严格 JSON / Schema / 身份检查，done 最后提交。持续 `watch` 每秒扫描并持有根目录单写锁；此时其他 Controller/UI 写操作会被拒绝。通常只用向导内的扫描；纯文件模式才单独启动持续 watch。

## 工具文件

所有规范路径都相对于 case。也支持外部 evidence bundle：manifest 的 assets 路径相对于 bundle 目录。路径不能含绝对路径、反斜杠、冒号、`..` 或逃逸 junction。登记器把资产复制为 `tools/<tool>/assets/<sha>.<ext>`，原始源文件不改。具体 Depth/Segmentation metadata 约定见 `src/hir_manual/evidence.py` 的模块说明。

JSON 修复保留同一 task，最多两次；失败 raw 入 quarantine，任务目录产生 `format_repair.txt`。暂停/阻塞不丢 pending；不自动重新采样。用户更改策略应创建 manual_variant；skip_tool 要求理由并标记 deviated。

## 验证

```powershell
Set-Location engine
.\.venv\Scripts\python.exe -m pytest -q
```

测试临时目录使用 engine/.test-runs 内新 UUID，不写 Data。锁定环境包版本见 `requirements.lock.txt`；实现与本机实测结果见 `IMPLEMENTATION_REPORT.md`。协议夹具、UI 渲染测试和实际照片诊断均不能代替 ChatGPT 桌面真实生成或证明恢复质量增益。
