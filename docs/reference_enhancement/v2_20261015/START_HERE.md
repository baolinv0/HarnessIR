> **当前下一步（v0.2.1）**：从完整 3–5 对真实 A/B 样本的预冻结开始，依次进行首对 G0/G1 → 完整 R1 → 独立盲评与 GO/PROBE/STOP 决策。详细可执行清单见 [NEXT_STEPS_R1.md](NEXT_STEPS_R1.md)。该计划尚未执行，真实 G0/G1 效果未验收；G2 暂不推进。

> 本文件保留 PR #3 的设计/预注册基线。实际实现、命令和验证边界见 [RUNBOOK.md](RUNBOOK.md) 与 [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)；真实 R1/R2 尚未运行。

# HarnessRefEnhance v2 — 生成式参考引导增强方案

**日期：2026-10-15** | **状态：工程设计与预注册实验草案；未运行真实 v2 实验** | **变更类型：文档增量，不修改运行代码**

## 1. 决策与范围

本版建立在 PR #2（feat/reference-enhancement-v1）的 hre 引擎上。保留原始 HarnessIR 的恢复实现与 v1 协议；不直接改 main，不把当前方案描述为已经实现。

**任务定义**：输入 A = Modular Neural ISP 的 RGB prediction（唯一内容与几何锚点）；输入 B = 同一场景、拍摄时间相隔约数秒的 iPhone 17 图像（仅提供亮度、颜色、白平衡、Global/Local Tone 等外观参考），输出 C = 在保留 A 内容前提下向 B 的可比外观靠近的生成式增强结果。A/B 不要求像素配准，B **不是**像素 GT。稳定照明与内容一致是本项目的采集前提，但仍应记录相机视角、RAW/JPEG/HDR、曝光和裁剪差异。

**本版明确不做**：
- 不增加确定性 ColorCurve / WB / Tone 参数优化器，不训练或反演 iPhone ISP；
- 不默认改变 3A、TM、Neural ISP 主干，也不声称输出 C 可自动充当 RAW 的像素 GT；
- 不把彩色分割可视化视为真实原生 mask，不未经验证地增加第三张辅助图；
- 不把设备/模型/API 的能力当作其他 Executor 的能力，不默认使用外部 API；
- 不为论文完整性先扩展成多 seed、多模型、多轮完整矩阵。

## 2. 核心研究命题

R1：在固定生成预算 1、同一 Executor 的情况下，参考引导生成能否将 A 的可比亮度、颜色与影调向 B 调整，并保持内容？

R2：将已验证的语义 / ROI / 统计证据编译为短文本 Prompt（G1），是否优于不带诊断的直接参考 Prompt（G0）？

R3：当同一 Executor 已证实支持指定的 mask 编辑模式时，G2 的空间条件能否比 G1 降低非目标区域漂移，并增加局部属性改善，而不引入边界与内容伪影？

R4：ROI 属性评价与独立盲评是否方向一致？能否识别过度保守、过度改动、幻觉与参考外观偏离？

不预设 G1 或 G2 必然优于 G0。若 DirectRef 已足够好，则不必强行保留更复杂的 Agent 链路。

## 3. 与 v1 的关键差异

| 项目 | v1 已有 | v2 要修改 |
|---|---|---|
| 比较对象 | 同场景非对齐 iPhone B | 进一步明确“数秒间隔、稳定照明/内容”作为采集条件；仅当记录证实条件失效时降低可比性 |
| 研究主线 | DirectRef、AgentSingle、Adaptive、BestOf3 | 首轮仅 G0/G1/G2 单次生成；多轮延后 |
| 语义输入 | OCR/Face/Depth/Segmentation 在分析链使用，Executor 仅 A+B | G1 仍用文本；G2 仅在特定 Executor 与 transport 真实支持 mask 时加入单独 mask 条件 |
| 分割可视化 | 文本证据 | 彩色可视化默认只用于人工诊断，不作为 Execute 额外普通参考图 |
| ROI | 主要比较 A/B | 同冻结 ROI 对计算 A/B/C 属性差，作为独立评价与下一轮失败类型归因 |
| 验证 | overall improved / content pass | 分亮度、颜色、Tone、局部变化、非目标漂移、内容真实性报告；定性与定量不可互相冒充 |
| 成功声明 | v1 严格流程闸门与盲评 | v2 仍需独立评审，新增参考方向和空间泄漏的证据；不更改 v1 已冻结的结果 |

## 4. 目录导航

1. [DESIGN.md](DESIGN.md)：体系架构、角色协议、语义/Mask 接入、ROI 闭环、接口和安全边界；
2. [EXPERIMENT_PLAN.md](EXPERIMENT_PLAN.md)：假设、G0/G1/G2、R0–R3、指标、预算、评价盲化、GO/PROBE/STOP；
3. [IMPLEMENTATION_CHECKLIST.md](IMPLEMENTATION_CHECKLIST.md)：具体代码文件、优先级、接口约束、测试、实施与交付验收。

## 5. 与已有工作连接

- 原始改造设计：docs/reference_enhancement/v1_20261013/START_HERE.md
- 当前实现与验证：docs/reference_enhancement/IMPLEMENTATION_STATUS.md
- 首个 R1 未完成说明：docs/reference_enhancement/R1_READINESS_AUDIT_20261014.md
- 代码：engine/src/hre/；旧恢复代码仍在 harness/。
- main 的 Qwen-Image-2.1 适配结果在 docs/qwen_adaptation/；该证据来自低光恢复，**只能作为 Prompt 风险提示，不作为本参考增强结论**。
- 新设计单独建立 v2 实验合同，不能悄悄覆盖 v1 预注册的 profiles、数据冻结和结果。

## 6. 外部证据与限制

1. HarnessIR 原论文：https://arxiv.org/abs/2610.10133 （原任务是 image restoration；直接送彩色可视化工具图和送文本证据是不同的输入组织，结论不能扩张到所有 mask 方式）。
2. Qwen-Image-2.1 官方仓库：https://github.com/QwenLM/Qwen-Image-2.1 （支持局部标注和以独立图片表达的 Mask 引导；需核实本地实际使用的 pipeline / serving 如何编码与提交）。
3. Qwen 官方说明：https://qwen.ai/blog?id=qwen-image-2.1 （展示原图与单独 Mask 两输入的局部编辑；并非保证硬像素锁定）。
4. OpenAI 图片编辑指南：https://developers.openai.com/api/docs/guides/image-generation/ （API Mask 属于 prompt-based guidance，不保证精确 mask 边界；不等于桌面客户端具备可调用 mask 参数）。

**证据等级**：外部文档证明接口/能力的一般范围；本项目是否支持、是否有画质收益，必须由固定运行环境真实实验验证。

## 7. 当前完成判定

- 已有：PR #2 的冻结、文件协议、CPU STATS/ROI、缓存、手动桌面交换、geometry gate、执行记账和实验导出。
- 本文新增：v2 设计和可执行实验计划。
- 未有：v2 mask adapter、A/B/C ROI 验证器、G2 独立能力证明、真实 G0/G1/G2 A/B/C 输出、独立视觉结果。
- 本次交付不声称 v2 代码/模型/真实 R1 已完成。
