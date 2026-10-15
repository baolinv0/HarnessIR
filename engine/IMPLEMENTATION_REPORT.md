# HarnessIR Manual Wizard 实现与验收记录

日期：2026-10-12，用户本机 Windows / Asia/Shanghai。

已实现 Design_v1_20261012 的本地 Controller、文件桥、手动导入向导、CLI 和审计导出。最小链已用真实照片与实际本地 Work 视觉推理跑通。**ChatGPT 桌面真实编辑、生成图保存、Direct-1 / Harness-1 R0 尚未完成；不能宣称整个第一阶段或恢复质量验收通过。**

## 交付与启动

代码在 `engine/src/hir_manual/`，按实施计划划分 models/storage/protocol/cases/workflow/prompts/tasks/service/evidence/transport/reports/ui/CLI。Python 3.12.14；环境为 `engine/.venv`，实际依赖闭包的 48 个包版本锁在 `requirements.lock.txt`。当前没有 Git 仓库，未创建提交或工作树。

项目根目录启动：

```powershell
.\engine\start.ps1
```

地址 `http://127.0.0.1:8501`。向导内每秒接收 done，无需另开 watch。启动器禁用 Streamlit 的目录源文件监控和使用统计。CLI 见 README；其他 Controller 对同一根目录的并发写入会被拒绝，CLI 导入/导出应先停止向导，或直接使用向导按钮。

## 最终测试

```powershell
Set-Location engine
.\.venv\Scripts\python.exe -m pytest -q --junitxml=validation/pytest.xml
```

**149 passed in 188.75s**。文本见 `validation/test-output.txt`，机器结果见 `validation/pytest.xml`。

覆盖严格 JSON / Schema / 时间；路径 traversal 和 Windows junction；不可变输入、EXIF canonical、超限拒绝；两个写进程；原子文件与事务各崩溃边界；无工具 / 证据等待；角色资产和 instruction 隔离；身份、哈希、done-last、重复与冲突；工具坐标、安全 NPY、Depth/Segmentation；正常闭环、三次预算、固定原图重试、矛盾修复、成功与不成功终止、选图、报告 ZIP 和向导渲染。

独立复核后补充了四条边界回归：取消后的晚到图像成本、已接受任务的额外生成成本与正式输出保护、Refine 接收到派发之间崩溃后暂停/继续、透明输出不得成功。详见 REVIEW.md。

只读对照既有 Data/manifest.json：**128 个输入/GT 文件全部 SHA-256 一致，0 个不匹配**。证据在 `validation/existing_assets.json`。没有改写、重编码或覆盖 Data 和实验原始文件。

## 本机能力探测

| 能力 | 结果 | 实测范围 |
|---|---|---|
| local_read_write | supported | 当前本地 Work/Codex 实际读 probe.json 和小图，识别红方块/蓝圆形，按随机 nonce 回写指定本机目录；不是图像编辑模式权限证明 |
| role_dispatch | unsupported | Controller dispatch 实测返回 unsupported，没有验证过的 ChatGPT 桌面角色派发桥 |
| image_edit | untested | 未执行真正 ChatGPT 桌面编辑，不调用外部 API 或其他生成工具替代 |
| image_save | untested | 未验证生成图直接写指定 task 目录，仍需手动下载后导入 |
| local_image_copy | supported | 原始 PNG bytes 复制、解码 160×120、SHA 校验通过，不冒充生成图自动保存 |

完整记录在 `../runtime/capabilities.json`；nonce、图片、响应与本地保存证据在 `../runtime/probes/ab9e7f5973deeac9/`。没有把协作 agent 当作桌面派发桥，也没有把 imagegen 当作用户指定 Executor。

## 真实照片最小链

case 为 `case_cd31d9743abf4b14`，输入取自既有 `Data/inputs/LOL_v2_Real/lolv2_00695.png`；角色推理没有读取 GT 图像。canonical 固定 600×400，SHA 为 `f3a2388af41219938cebbabd8dd75d8db02a309b0aa9b532a64df3cca14e1606`。

1. Controller 生成诊断 request 和完整 Prompt。
2. 当前本地 Work 模型实际查看 canonical，产出严重低光诊断，tool_plan=[]。
3. response/done 交接经身份、Schema、哈希校验后，自动进入 Composer。
4. 独立本地 Work Composer 查看同一原图，产出实际 230 词 instruction，并通过 local_work/file 回写。
5. Controller 自动保留一个生成槽并发出 `execute_eafe37297b114abf`。现为 WAIT_EXECUTION，round=1，consumed=0，reserved=1，workflow_completed=false，restoration_success=null。

实际角色的界面型号未采集，provenance 明确写为未捕获，后端版本为 null。Composer session 字段是本地协作任务身份，不是 ChatGPT 编辑会话 ID。本例是工程 smoke，不是完成的图像恢复实验。

已退出并用新 Controller 进程重读同一 pending task。原图、Prompt、raw、事务与报告导出为 `../runtime/exports/live_smoke_20261012.zip`；其中没有生成图片或 verifier 质量结论。

## P0 矩阵

| ID | 工程证据 | 真实桌面部分 |
|---|---|---|
| A01 | 输入/快照/重启测试通过，真实照片 case 已登记 | 本地完成 |
| A02 | 无工具自动 compose，实际读图 smoke 通过 | Work-only |
| A03 | OCR+Face 缺失不推进，完整证据自动 compose | 协议测试，未跑真实工具 |
| A04 | 独立 Composer JSON/instruction/哈希已保存 | Work-only，型号未采集 |
| A05 | 图片导入、预算、verifier 派发测试通过 | 待真实桌面生成/下载 |
| A06 | 原图重试、新 instruction、round 2 测试通过 | 待真实失败与 refine |
| A07 | accepted 与 incorrect/no-redo 不误判 | 待真实独立 Verifier |
| A08 | 三次上限、无第 4 个 execute、额外成本如实记录 | 协议测试 |
| A09 | commit/state/events 与 Refine 中断恢复通过 | 本地 pending 重启已验证 |
| A10 | clipboard/file 共用验证器和状态转移 | 文件桥已实用 |
| A11 | 全任务/失败/干预入 JSON/Markdown/HTML/ZIP | 未完成真实 case 已导出 |
| A12 | supported/unsupported/untested 分项证据已保存 | 编辑与保存待实测 |

Task 1–5 的本地实现和协议验证完成；Task 6 部分完成。单图 smoke、协议测试和 UI 运行均不支持总体算法增益结论。

## 下一步

在新 ChatGPT 桌面图像编辑会话，仅上传当前 case 的 `input/canonical.png`，发送当前 execute 的 `prompt.txt` 原文。保存第一张完整原始生成图，通过向导“提交图片并自动进入验证”导入，填写实际模型显示名；若同一次返回多图，按提供顺序全部登记。随后在独立 Verifier 会话执行自动形成的任务，导入 JSON。

完整 R0 还需同 canonical/intent 的 Direct-1 固定 baseline、Harness-1 实际生成与保存、独立核查；不能用 GT 编辑或人工挑图。当前 reservation 只代表待确认槽位，并非已生成或已成功。
