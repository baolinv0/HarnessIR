# 第一阶段工程规格

## 1. 目标与已确定的设计

用户要在 Windows 笔记本上，通过 ChatGPT 的诊断、提示词编写、图像编辑、验证能力和离线视觉工具，连续完成单图恢复。用户不再重复说明各阶段上下文；系统显示下一动作、所需文件和当前完整任务。

采用 **Python 本地控制器 + 共享文件夹 + Streamlit 向导 + ChatGPT 角色会话**。已有讨论已确定文件交接与 ChatGPT Executor；本轮将它固化为工程规范。控制器不调用外部模型 API，不抓取 ChatGPT 历史，不安装或调用 cline，不自动登录或修复认证。外部模型在用户选定的 ChatGPT 会话中工作。

本地工具可以使用预先配置的本机模型服务或固定离线命令，第一阶段默认仅接收文件。用户的其他 Naive/ARIS 本机调用约束不被本方案改变。控制器、图像编辑器与联网 ChatGPT 的职责不能混同。

## 2. 范围与成功标准

P0：创建 case；绑定不可变输入；发出 diagnoser 任务；接收严格 JSON；按诊断中的工具计划等待证据；发出 composer 任务并接收实际模型生成的 `instruction`；执行图像编辑；校验输出；独立 verifier 判定；必要时 refine；终止并导出审计报告。自动部分包括任务生成、缺失项检查、文件接收、状态迁移与报告。

自动启动外部会话、自动保存图片、自动跑工具是独立能力，需要本机探测通过才启用。不能把“用户保存了图片”记为“系统自动生成并写盘”。第一阶段不承诺跨回合永久后台无人值守。

完成条件分开记录：`workflow_completed` 表示闭环已终止；`restoration_success` 表示选定图像被 verifier 判为正确且图像约束通过。工程验收通过不代表算法有增益。

## 3. 架构与职责

| 模块 | 输入 | 输出 / 职责 |
|---|---|---|
| CaseStore | 原图、case ID、配置 | 原子文件写入、不可变输入、case 配置快照 |
| WorkflowEngine | 当前状态、已校验响应、证据清单 | 唯一有权改变 `state.json` 的组件 |
| TaskBroker | 状态与完整上下文 | 不可变 request、Prompt、任务文件夹 |
| FileTransport | response、done 标记、图片 | 校验身份、哈希、Schema，封装有效响应 |
| PromptRenderer | Jinja2 模板和已知数据 | 完整角色任务；不替代 Composer 生成编辑策略 |
| EvidenceRegistry | 工具 metadata 与原始文件 | 配准 / 坐标校验、证据包、缺失项 |
| ChatGPT Adapter | 当前任务、实际可用会话 | 角色推理与回写；不能改状态 |
| Image Adapter | 标准原图 + `instruction` | 原始生成图片、输出 metadata |
| ReportBuilder | 所有事件、轮次、终止判定 | Markdown、JSON、可浏览报告与 case ZIP |
| UI / CLI | 用户上传、粘贴、继续与导出 | 调用统一服务接口，不自建另一套状态机 |

数据顺序：输入 → Diagnose → Evidence → Compose → Execute → Verify → Finish / Refine。Refine 读取失败输出与反馈，下一次 Execute 仍只接收同一原图和新的 instruction。Verifier 接收原图、全部有效历史输出、固定 intent 与 checklist，不接收 composer instruction 或模型自评。

## 4. 用户可见交互

首页列出 case / 状态 / 阻塞原因。详情页只突出一个“下一步”：需要上传什么，在哪个已指定角色会话执行，是否可自动回写。含原图、当前 Prompt 复制、任务目录打开、JSON 导入、结果图上传、工具缺失清单和历史。

按钮：新建、复制当前任务、导入 JSON、登记工具证据、提交编辑结果、暂停、继续、导出。停止时用户可取消 case，但不能人工把失败改为成功。人工改 Prompt 必须复制为 `manual_variant` 新分支，完整记录父 case，不能混入预注册 benchmark 主组。

## 5. 文件布局

目标根目录下：`Data/` 为已有数据；`Design_v1_20261012/` 为本包；`cases/<case_id>/` 存单图；`runtime/capabilities.json` 存本机探测；`logs/` 存操作日志。所有 case 内路径使用 `/` 分隔的相对路径，控制器用 pathlib 映射 Windows 路径。

每 case：`input/original.*`、`input/canonical.png`、`case_config.json`、`state.json`、`events.jsonl`、`transactions/`、`tasks/<task_id>/request.json` 与 `prompt.txt`、`tools/<tool_id>/`、`rounds/round_001/`、`final/`、`quarantine/`。

Canonical 是统一用于所有角色与两组编辑器的、仅做 EXIF 方向 / 已知色彩空间处理的照片；与 original bytes 都保留。禁止按组分别缩放或调亮。工具也对 canonical 运行。研究中的“从原图重试”指该固定 canonical，而不是上轮生成图。

## 6. 默认配置与限制

- Python 3.11+，Streamlit、Pydantic 2、Jinja2、jsonschema、Pillow、filelock；watchdog 可选，默认每 1 秒扫描 done 标记。
- 一进程一根目录写锁；多 case 管理，外部 ChatGPT 队列默认一次只派发一个任务。
- 主 profile：`chatgpt_adapted_v1`；模板 / 配置 / intent 创建 case 时锁定。
- 默认每 case 最多 3 次图像生成（初次 1 + 重试 2）；每次请求一张；默认第一完整返回图。响应格式修复最多 2 次，不重新生成图片。
- 默认图像最大 50 MiB、最大 40 MP；更大输入须显式创建另一个统一预处理配置，不能静默压缩。
- 分辨率变化记录。默认宽高比相对误差 ≤ 0.02、全图构图保持；尺寸不等本身不直接判错。超过误差标记为几何不合规；不能自动裁切修复。
- 默认无色彩回对齐、自动白平衡或锐化等后处理。原始输出始终保留。
- 诊断 / 编写 / 验证各角色的会话明确分开；编辑器每轮用新会话或受支持的隔离调用，防止隐式连续编辑。

## 7. 能力等级

| 等级 | 前提 | 可自动化 | 人工操作 |
|---|---|---|---|
| A：文件权限已通过 | Work 能读指定本地图片、写指定 JSON | 已发起任务的分析与回写、状态推进 | 无派发桥时仍需启动 / 继续会话；图片不能回写时保存一次 |
| B：仅能上传下载 | 普通 ChatGPT 对话可看图 / 编辑 | 本地解析、推进、生成下一任务与报告 | 上传当前任务资产、导入返回 JSON、保存生成图 |
| C：受支持派发桥 | 工程师验证一个可用官方机制和权限 | 在记录的能力范围内派发与回写 | 确认该机制需要的授权；不得拿未验证接口充数 |

文件 watcher 不承担唤醒任务。A 与 C 必须分别验收。普通聊天与能运行本地工具的 Work / Codex 会话是不同能力；不能只因为 App 已安装就记录等级 A。

## 8. 交付边界

这份规格含工程实施与验证设计，不含已经完成的向导程序，不含真实照片的恢复结果。官方代码快照仅为参考；运行向导不得 import 它的 API client。第一张图完成后才进入批量；对 ChatGPT 的结论只适用于实际 UI、账户、模型标识和测试时间。
