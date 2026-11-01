# 独立实现任务清单

固定起点 stage=9a42778537b675286341872253214977ad80789f；reference 比较=9073086bd86cff3062eab65bcbc32da6e4fd2114；环境原分支 work=0a0c048（完整 SHA 见最终报告）。不读取工程师实现、不推送。

1. `hre/tool_retouch/color.py`：显式 sRGB/ICC 审计、线性 Y/D65 Lab、等比预览、16 位 PNG 无损读取/导出；测试位深、往返、方向、未知 profile 拒绝。
2. `evidence.py`：双侧独立 mask、内部支持/剔除、可比等级降级、固定分位/色度/分层/关系；测试空区、不同尺寸、有效支持。
3. `contracts.py`：冻结输入/ROI/证据/目标/保护/预算、哈希验证、数值引用解析；`planner.py`：严格结构规划、操作白名单、参数边界与 identity；测试伪造证据/命令/NaN/合同篡改。
4. `backend.py` + `engine/photocraft_worker`：固定 CPU U16 sRGB 文档、源码对应 Adjustment/Surface/LayerMask 薄封装、浮点 compose 输出、显式高精度导出，外部 mask 为 HarnessIR 扩展；源码与运行验证分开。
5. `solver.py`：从 A 开始的确定性坐标搜索，固定扫描/尺度/缓存、组均衡损失、硬拒绝、跨轮预算；测试预算、同分、无安全改善、顺序及 mask 缓存隔离。
6. `workflow.py` / `verifier.py`：冻结合同、有限重规划、原生重渲染、逐目标/独立视觉检查、失败回退和状态；测试身份输出、原生失败、错误状态、必选目标遗漏。
7. `cli.py` / `experiment.py`：复用 hre CLI、冻结 JSON 配置、离线结构化 VLM 交接及本地兼容 API、审计/重放、G/T 同合同导入、匿名评审包和文本报告。
8. 运行新增测试及既有回归；独立第二遍代码审查、修复可复现问题；交付完整运行说明、证据日志与单文件 IMPLEMENTATION_REPORT.md，本地提交。

真实 VLM/真实照片效果依赖尚未提供的数据和服务。Rust 工具链未发现，不能将仅源码实现标为真实 PhotoCraft 通过。
