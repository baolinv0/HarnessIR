# HarnessIR Manual · 第一阶段工程交付包

版本：v1.1，2026-10-12。目标目录：`C:\Users\Lenovo\Desktop\HarnessIR_Manual`。

**本包是完整设计与工程实施依据；控制器应用尚待工程师实现。** Executor 已固定为 ChatGPT 桌面端图像编辑。无需先购买 API。目标是让用户只提供当前缺失的输入，系统自动形成下一任务、接收结果、校验并推进状态。

## 放到 Windows 指定目录

1. 下载并解压整个 ZIP；保留内部文件夹结构。
2. 双击解压文件夹中的 `INSTALL_TO_WINDOWS.cmd`。
3. 方案安装到 `C:\Users\Lenovo\Desktop\HarnessIR_Manual\Design_v1_1_20261012`。脚本保留已有 `Data`、`cases` 和其他文件；若同名方案目录已存在，停止并提示，不覆盖。
4. 打开安装目录中的 `index.html` 阅读完整方案，或从下表依次阅读 Markdown。

脚本仅整理本包与创建空的运行目录，不安装软件、不启动应用、不调用模型。若本机禁止脚本，手动把本文件夹复制为目标目录下的 `Design_v1_1_20261012` 即可。当前云端交付没有验证你的 Windows 目录或桌面 App 能力。

## 工程师阅读顺序

| 文件 | 用途 |
|---|---|
| [工程规格](docs/01_Engineering_Spec.md) | 产品范围、架构、数据流与约束 |
| [状态机](docs/02_State_Machine.md) | 完整状态、异常恢复、停止与选图规则 |
| [文件协议](docs/03_File_Protocol.md) | 任务、回写、完成标记、事务与幂等 |
| [ChatGPT 操作](docs/04_ChatGPT_Operation.md) | 本地能力探测、三个角色会话、编辑器与降级操作 |
| [工具和图像](docs/05_Tools_and_Images.md) | 离线工具证据、坐标、图像与保真边界 |
| [实施计划](docs/06_Implementation_Plan.md) | 文件职责、接口、分任务实现与验证命令 |
| [验收标准](docs/07_Acceptance.md) | P0/P1 验收、失败测试、真实一图 R0 |
| [实验协议](docs/08_Experiment_Protocol.md) | Direct 对照、生成预算、真实照片评价与结论边界 |
| [来源与差异](docs/09_Source_and_Deviations.md) | 官方版本证据、ChatGPT 适配差异 |
| `prompts/`、`schemas/`、`examples/` | 可直接使用的模板、JSON Schema 和合成协议示例 |
| `config/`、`templates/` | 配置、空目录模板、报告模板 |

## 第一个里程碑

工程师先完成 **Controller 发任务 → 本地 Work 读图与任务 → JSON 原子回写 → Controller 自动切到下一状态**。先测试读写权限，再测试图像编辑结果能否保存到任务目录。能力不足时转为“复制当前任务 / 导入 JSON / 保存一次图片”，状态机保持一致。

模型必须看过图像才可诊断；模板渲染不是模型推理；文件出现不是任务成功；停止重试也不代表恢复成功。

## 交付验证

本包可用 `python scripts/validate_package.py` 校验（依赖见 `scripts/requirements-validation.txt`）。详见 `VALIDATION_REPORT.md`。示例均为协议夹具，不是跑过的真实图像实验。

## 本次新增：本地T1–T4

从 [修改清单](CHANGELOG_v1_1.md) 开始，优先读 [接入规格](docs/10_Local_Tools_Integration_v1_1.md) 和 [实施增量](docs/11_Local_Tools_Implementation_Plan.md)。本包新增模型registry / cpu与gpu配置、tool job / cache /四类payload Schema及合成夹具；这些是工程实现依据，没有安装权重或提供已部署工具。

正常流程在WAIT_EVIDENCE自动运行所需本地模型或复用匹配缓存；CPU单进程单图，GPU升级保留原case；Executor仍用ChatGPT原图+文字。Controller与预处理环境分开安装，CPU probe与GPU full正式数据不混用。
