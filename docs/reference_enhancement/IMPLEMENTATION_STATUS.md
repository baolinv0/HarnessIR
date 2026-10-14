# HarnessRefEnhance 实现与验证记录

实现日期：2026-10-13。代码位于 `engine/src/hre/`，独立于原有 restoration harness。设计依据保留在 `v1_20261013/`；设计包内“拟实现”的表述记录当时的规划，实际运行接口以 [engine README](../../engine/README.md) 和 [运行手册](IMPLEMENTATION_RUNBOOK.md) 为准。

## 已提供的工程能力

| 模块 | 实现 |
|---|---|
| 图像与事务 | EXIF/ICC 规范化、未知 HDR 拒绝、原始文件与实际像素的派生证明、SHA 绑定、安全路径、跨进程锁、原子事务与恢复 |
| 状态与预算 | 五个冻结 profile、Diagnose→证据→Compose→Execute→Verify→Refine、提交预留、未知提交暂停、失败与额外采样计费、幂等、显式重试、终止后仅补记费用 |
| 离线证据 | 计划内缓存消费、原子缓存发布、模型/坐标/内容绑定、递归人工注释证明、CPU STATS 与独立 A/B ROI、缺失工作包导出 |
| 提示与桌面交接 | 六个严格模板、手动任务包、编辑附件仅 A+B、真实 C/request 绑定、首个完整供应商输出校验、全部额外 raw 审计、独立能力探测记录 |
| 验证与实验 | 冻结接受规则、最早 accepted/usable/fallback、实际选图与报告、run 冻结、分组泄漏检查、盲评、独立评审、ITT、配对场景组 bootstrap、协议偏离保留成本且成功为零 |
| 使用入口 | `hre` 与 `python -m hre`、六区 Streamlit 界面、真实 Controller 共用路径、限定 inbox 监控、导入、恢复和导出 |

[实验文件交接](EXPERIMENT_HANDOFF.md) 提供真实文件组装步骤、outcomes/execution contract/ratings 字段和可运行命令。依赖锁定文件是 `engine/requirements-lock.txt`，记录本轮 Linux/Python 3.12 的实际环境；其他平台需重新解析平台依赖。

## 验证边界

本轮通过真实本地文件、哈希、事务、CLI 子进程和 Streamlit AppTest 验证软件行为。合成演示使用确定性色块与明确标注的 synthetic 角色响应，未调用图像模型。合成 `success=true` 仅表示模拟输入满足软件接受规则。

真实 A/B、桌面会话和 T1–T4 模型权重未提供。因此真实 R1、12 对 pilot、正式模型效果、OCR/face/depth/segmentation 推理、真实生成成本和最终独立评审均为 **not_run**。这些流程有可执行的文件交接入口，不能用合成演示替代其证据。无模型 API 或桌面自动化能力被假定通过。

实际 Streamlit HTTP 服务启动被自动审批拒绝：启动尝试访问 `checkip.amazonaws.com`。没有重试或绕过；界面交互用本地 AppTest 验证，HTTP 服务启动保持 **unverified**。

## 实现取舍

1. 使用新的隔离 checkout 实现，保留此前设计目录；无需修改用户已有 checkout。若隔离布局不合适，需要重新应用分支。
2. 持久化对象使用严格 Schema 校验的字典，内部标量结果使用 Pydantic；避免复制整套大型 Schema 类型。若需要更强静态类型，需要后续类型层重构，磁盘协议不变。
3. 缺少真实桌面与图像时完成手动文件通道，保留未测试能力状态，并使用明确的合成流程验证；实际模型验证仍需外部输入。
4. 供应商输出顺序证明使用 `done.artifacts` 中的 `hre_output_order_v1` 辅助 JSON，保留批准的响应 Schema。若后续供应商协议无法表达所需事实，需要新协议版本。
5. PAUSED 的实际阻塞原因映射到现有终止枚举，并在审计事件保留原始原因。若分类不适合后续分析，可调整映射，原始证据仍在。

## 最终验证

最终工作树的本地验证结果：

| 验证 | 命令或方法 | 结果 |
|---|---|---|
| 完整运行测试 | `python -m pytest engine/tests -q` | **298 passed，185.25 秒**；包含 CLI 子进程、真实文件协议、恢复、缓存、实验及 AppTest |
| 编译 | `python -m compileall -q engine/src/hre engine/examples` | 通过 |
| 设计合同静态检查 | `python docs/reference_enhancement/v1_20261013/scripts/validate_package.py` | **PASS，181 checks**；范围仅设计合同 |
| Wheel 构建 | `python -m pip wheel ./engine --no-deps --no-build-isolation` | 通过；0.1.0 |
| 独立安装测试 | 新目录安装 wheel，确认导入来自该目录，初始化 case、渲染并导出诊断任务、运行 `python -m hre --help` | 通过；包内 9 个 Schema、6 个模板、1 个配置 |
| 合成闭环 | `python engine/examples/demo.py --out EMPTY_DESTINATION` | DirectRef/Single 各消费 1 次，Adaptive 消费 2 次并接受；明确 `synthetic=true,actual_model_called=false,real_R1=not_run` |

六个实现模块均经过独立合规与质量审查；审查发现的图像/费用/状态/顺序/缓存/盲评/前端问题均有失败复现与回归修复，并通过对应复核。整体分支审查的两项集成问题已通过一次集中修复与独立复核：实际模板字节在 case 初始化时冻结并绑定配置与执行记录；结构化保护注释在入组前校验并完整保留到验证上下文。19 项新增回归覆盖模板漂移、历史源证明、外部真实协议记录及注释类型；全部包含于上述 298 项最终测试。整体合规与质量复核通过，无剩余阻塞项。没有真实模型效果的通过声明。
