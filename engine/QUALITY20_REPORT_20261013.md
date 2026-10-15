# 20 图质量优先 pilot · 2026-10-13

当前交付是20张真实原图的诊断链验证，**不是20张恢复完成**。由164张现有输入有意分层取20张；夜景/低光、人像、长焦/小脸、小文字、复杂场景各4张，包含清晰控制。全部原图实际逐张观看，正式任务生成后再次观看并返回JSON；未把GT、参考图或人工标注提供给任何角色/模型。

- Controller接受20/20诊断：14 WAIT_EVIDENCE，6 WAIT_COMPOSITION。工具计划27项仍未推理；生成数、Verifier数均0，恢复成功保持null。
- 真实文件中断恢复：首张response/done发布后退出进程，下一进程接收；再次运行跳过20项，0新增case/接受。578份case JSON未变，编辑预算0。
- 修复同一ICC原图的动态sRGB配置时间造成canonical PNG哈希不稳定。新canonical为metadata-free sRGB RGB8 PNG，版本`hir_rgb8_exif_icc_v2_stablepng`；旧无version的case继续v1，不改旧文件或证据。缓存、作业、手工证据、导出导回按实际版本绑定。
- 工程回归207 passed，0 failures/errors，116.614秒；真实20图重放另有实际日志。协议夹具不代替SDK验收。
- 238份既有input/GT只读哈希核对全部一致。旧预检查批次、失败记录和实验资产均保留。

M1首个T2真实照片probe：`HC_RAIM_Phase1_011`，available=1410.855 MiB <2048，`resource_wait/insufficient_memory`。PID=null、worker elapsed/RSS=0，进程未启动；不是空检测、OOM或推理通过。T1/T3/T4未尝试，不静默降低配置或换模型。T4尚缺本地静态文本embedding与完整注册项。

Work本地JSON交接和PNG持久化已实测；自动ChatGPT桌面会话派发不受当前桥支持，桌面编辑/生成图保存没有本轮结果。JSON/图片手工导入通道保留。恢复质量、首轮Direct/Harness差异、最终结果均暂无结论。

完整材料：

- [逐图报告、环境和耗时](../runtime/quality20/pilot20_20261013_stable_v2/REPORT.md)
- [20图输入缩略图（不是恢复结果）](../runtime/quality20/pilot20_20261013_stable_v2/contact_sheet_inputs_only.png)
- [逐图CSV及case ID](../runtime/quality20/pilot20_20261013_stable_v2/sample_results.csv)
- [原图/请求/配置/模型版本锁](../runtime/quality20/pilot20_20261013_stable_v2/trial_contract.json)
- [中断恢复实测](../runtime/quality20/pilot20_20261013_stable_v2/resume_check.json)
- [核心工程回归](validation/quality20_core_tests.xml)

在项目根目录PowerShell启动此批次查看/审计（8502，独立根目录）：

```powershell
.\engine\start-quality20.ps1
```

普通向导仍用`.\engine\start.ps1`（8501）。本次批次冻结了尚未就绪的工具注册状态；工具完成真实验收后建立新批次或显式分支，保留这里的诊断与失败审计。不要把旧T4占位注册项升级为新的正式证据。

继续顺序：足够内存时先T2三图，再T1三图，再T3/T4各1–3图并逐图检查坐标/内容/空检测/图例/进程释放/缓存；单张realblur_scene094完整闭环，Direct和Harness先各一张，独立Verifier，Harness必要时从同原图重试最多3次；首轮与最终分开。通过后逐张完成余下19张。CPU结果标接口验证，GPU Base/SAM3锁定后另做正式评测。

可恢复命令及完整资源日志见逐图报告。不会调用外部模型API或用其他图像模型代替ChatGPT桌面Executor。
