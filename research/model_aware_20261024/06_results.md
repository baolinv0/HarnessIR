# 6. Experimental Results：已运行与未运行分开

**本轮NB2/Qwen图像模型调用次数=0。E0–E6的画质、泛化、种子稳定性结果全部NOT_RUN。以下不得引用为Model-Aware画质提升。**

## 本轮实际执行的检查

| 检查 | 结果 | 证据 | 能证明什么 |
|---|---|---|---|
| 原始代码对照 | 40/40相关文件原始字节一致 | results/source_comparison.json | 用户分支原始harness/prompts/config/四入口未变化 |
| 单图engine契约probe | 拒绝single-image；四profile全部declared_not_measured | results/branch_contract_probe.txt | 当前Model-Aware入口不是原始单图复原 |
| S5多类型 | 修复前NameError；修复后双checklist组装正常 | regression_red/green.txt | 已定位并修复确定性执行错误 |
| Direct/Harness原生输出存档 | 控制编辑器80×60输出与40×30交付均保留 | tests/test_restoration_audit.py；green日志 | 可区分decoded native端点与Harness几何处理；非真实模型测试 |
| 配对分析工具 | scene级平均、缺对/错误拒绝、差中差受控输入测试通过 | tests/test_paired_analysis.py | 不把重复seed当独立样本；不证明任何数据来源/实际收益 |
| 新增测试 | 10 passed | results/regression_green.txt | 指定软件合同通过 |
| 原有engine完整回归 | 469 passed / 4 warnings / exit 0（原engine459+本轮10） | results/engine_pytest.txt | 原有工程回归；不证明真实模型可运行 |
| 旧adapter完整包身份 | SHA256=af5ba6862bd256d68a62150c2cccdc96e8588ae49019d5b56cd5ff1c52c7adfa，与仓库相符 | 原包与docs/qwen_adaptation/evidence/artifacts.json | 历史compiler来源可追；无图像实验 |
| night_0043原始LQ | 已获取并目视；NoGT；要求正常亮度 | evidence/night0043_source.json、caseboard | 可研究可见失败现象，不能给高频真值结论 |

回归红/绿记录均为真实输出。Red中S5是自然触发的NameError，其余为缺存档合同的断言失败；不是预设图像质量实验。日志临时目录只反映测试fixture路径。

## 论文作者报告（仅E2，不是本轮复现）

来源：[v3 §4.4 Tables4–5，p10](https://arxiv.org/html/2610.10133v3#S4.SS4)，Real-Paired-200 / NB2。

| 设置 | MFM候选预算 | PSNR dB | DF | 本轮解释 |
|---|---|---:|---:|---|
| Direct简短请求 | 1 | 23.94 | 52.9 | 弱通用基线 |
| 更详细请求 | 1 | 24.75 | 54.5 | 仅改善通用请求已有效，必须设置强统一对照 |
| 单VLM instruction | 1 | 25.49 | 56.6 | 图像特定组织bundle |
| 双VLM＋tools视觉 | 1 | 25.62 | 57.8 | 两个变量一起变，工具贡献不可独立识别 |
| 双VLM＋tools文字 | 1 | 26.01 | 59.6 | 与visual相比支持证据传递方式重要，但不说明Qwen收益 |
| in-place | 多轮，按作者设置 | 25.64 | 57.2 | 把失败输出继续输入可能积累偏差 |
| 从LQ Redo | 最多3，平均1.45 | 26.63 | 62.0 | 相对single +0.62dB/+2.4DF，仍混合反馈/额外采样/选优 |

作者主表在两个闭源Executor上报告系统收益；同时NB2 MiO的D略降、SSIM并非所有旧方法都优，不能概括为所有维度全面获胜。完整作者数字与限制见`evidence/paper_audit_notes.md`，不从这些表计算不存在的CI。

作者成本§4.5/Table7为NB2/Real-Paired-200：direct14.7s/$0.070、final64.3s/$0.129；平均3.90 VLM/1.45 MFM/2.40 local tools。这是特定历史价格/设备与排除开销后的估算，不是当前端点费用、端侧结果或本轮测量。复现时需重新测真实端到端时延/重试/账单。

## 质量结果登记表

| Arm | NB2真实运行 | Qwen真实运行 | 配对CI | 冻结测试 | 独立盲评 |
|---|---|---|---|---|---|
| Direct/E0 | NOT_RUN | NOT_RUN | 无 | 无 | 无 |
| E1/E1-fixed | NOT_RUN | NOT_RUN | 无 | 无 | 无 |
| E2/S3 | NOT_RUN | NOT_RUN | 无 | 无 | 无 |
| E3/Evidence | NOT_RUN | NOT_RUN | 无 | 无 | 无 |
| E4/Execution | NOT_RUN | NOT_RUN | 无 | 无 | 无 |
| E5/Refinement | NOT_RUN | NOT_RUN | 无 | 无 | 无 |
| E6/组合 | 不准入，等待单项通过 | 不准入，等待单项通过 | 无 | 无 | 无 |

当前没有可绘制的质量胜负图、seed箱线图或模型×策略效果图。保留NOT_RUN比填零或以软件单测数代替质量结果更准确。统计程序单测中的人工构造数值只证明计算，不会进入本表。
