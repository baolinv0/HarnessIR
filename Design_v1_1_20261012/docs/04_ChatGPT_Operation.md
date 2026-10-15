# ChatGPT 桌面端操作与能力探测

## 第零步：分别探测四项能力

工程师在你的 Windows 本机运行，不能用云端 scratch 成功写文件代替本机测试。

| 探测 | 操作 | 成功证据 |
|---|---|---|
| local_read_write | 创建 probe.json 与小图，在本地 Work 要求读图、回写新的 probe_response.json | 本机检查文件存在、随机 nonce 一致、图片描述有效 |
| role_dispatch | Controller 发新 request；验证受支持机制是否能启动 / 继续指定会话 | 无复制点击情况下的新会话任务记录；机制名称、官方出处和权限记录 |
| image_edit | 选中 ChatGPT 图像编辑，上传测试图与 Prompt | 真正生成了图片，不能用文字回复代替 |
| image_save | 保存该生成图到指定 task 目录 | 本机解码、哈希、宽高与 provider metadata 一致 |

四项分别记录 supported / unsupported / untested。只有探测成功才设 true。`role_dispatch=unsupported` 不妨碍等级 A 的文件回写，UI 提示“点击继续当前角色任务”。`image_save=unsupported` 时仅手动保存一次。随机 nonce 由工程师生成，不能照搬本包夹具 nonce。

## 固定角色会话

初次把 `prompts/00_operator_system.txt` 用作操作约定，并在界面选择模型显示名称。主控是本地程序，ChatGPT 不做隐藏状态控制。分别建立 Diagnoser、Composer/Refiner、Verifier 三个任务入口；编辑器用独立会话。每次完整任务自包含，不能依赖上一个 case 的记忆。

`prompts/01_session_bootstrap.txt` 用于具备本地读写能力的会话启动；会话读取当前 pending request，执行一项，然后回写并结束。本轮内若受支持机制允许继续，可再次读取新任务，但 verifier 独立会话要求不能被同一个会话读写循环替代。默认不在模型会话中无限轮询目录。

### Diagnose

输入 canonical 图和固定 intent；模型只观察退化和敏感区域，按图像需要规划工具。返回 `diagnosis.schema.json` 数据。不执行图像编辑，不因“照片有一点暗”自动认定需把夜景变白天。

### Compose

控制器按计划自动运行本地工具或命中缓存，收齐证据后派发。模型必须同时看到原图及工具地图 / 框 / OCR 文本；仅有 depth 文件路径不算已读深度。模型生成 `composition.schema.json`，其中 `instruction` 是实际用于编辑的文字。系统只渲染任务模板、校验与抽取，不用规则拼一段所谓“智能结果”。

### Execute

新建图像编辑会话。只发送 canonical 原图与 `instruction` 原文；不能把 task envelope、证据图、历史输出或诊断 JSON 一起附给编辑器。请求一张图片。返回后不在同一结果上继续改，保存原始生成图到该 task 的 output 文件，再登记完整 metadata。

真实生成图片的功能可能与本地 Work 文件写入在不同会话 / 模式；工程师必须测通，不通过就使用上传 / 保存通道。仅导出可下载链接不能证明已经写到 C 盘。

### Verify

独立验证入口读取原图与所有已登记输出；明确哪张是最新图。接收固定 intent 和 checklist，但不给编辑 Prompt / 模型名称 / 组名 / 自评。核查“退化处理”与“保真”分别是否满足。返回 fields 描述最新图，best_round 比较全部历史。

### Refine

Composer/Refiner 读取原始图、已有证据、上轮 instruction、失败输出和反馈，产出新的 composition。重试输入重新回到原图。此前已通过区域保留到新指令，不为了局部修复扩大改图范围。

## 实际人工操作预算

B 模式仍需要每次模型角色任务的一次发送与返回 JSON 的导入，工具失败时的处理和图片保存；正常本地工具执行无需手工上传。A 模式节省 JSON 搬运，但在没有受支持派发桥时仍要点击启动 / 继续角色任务。C 才能在探测范围内自动派发。报告统计操作次数和耗时，不能声称 A 是全自动。

自动 API 方案留到后续，只替换 adapter。普通 ChatGPT 历史抓取 / 私有接口 / 模拟网页登录均不作为 v1 的任务输入。
