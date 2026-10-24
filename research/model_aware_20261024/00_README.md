# HarnessIR Model-Aware 五阶段研究：审计、可证伪协议与可复现修复

2026-10-24｜研究状态：**尚未完成真实模型实验，不能宣称Model-Aware有效。**

当前可以下的结论：目标分支提供的是以A+B参考增强为契约的模型条件编译/执行基础设施；原始单图复原链路仍是官方实现。应先恢复可比较的单图路径，核验Executor原生行为，再检验策略差异。没有证据支持现在就给五个Stage全部添加模型专属逻辑。

原论文值得深读：价值在于把工具从复原算子改成证据源，以及把“去退化”和“保内容”同时纳入闭环。建议读§3、§4.4、App A/C。论文证明了特定已报告设置下的系统收益，没有证明Qwen适配、每个工具单独贡献、等预算反馈收益或五阶段都须模型专属。下文不进行领域趋势或新颖性判定。

## 交付导航

| 用户要求 | 文件 | 当前证据状态 |
|---|---|---|
| Original HarnessIR Audit | [01_original_audit.md](01_original_audit.md) | 论文+附录+固定commit源码已核验 |
| Executor Capability Profiles | [02_executor_profiles.md](02_executor_profiles.md) | 官方接口/参数已核验，行为实测阻塞 |
| Model × Stage Matrix | [03_model_stage_matrix.md](03_model_stage_matrix.md) | 事实与待测策略分列 |
| Hypothesis & Experiment Matrix | [04_experiment_plan.md](04_experiment_plan.md) | 可执行协议；非实验结果 |
| Failure Casebook | [05_failure_casebook.md](05_failure_casebook.md) | 作者公开图像观察、代码干预、缺失trace分列 |
| Experimental Results | [06_results.md](06_results.md) | 确定性软件检查已运行；质量结果未运行 |
| Model-Aware Design Proposal | [07_design_proposal.md](07_design_proposal.md) | 只纳入已验证的运行/审计修复；质量策略条件准入 |
| Independent Validation | [08_independent_validation.md](08_independent_validation.md) | 同家族独立审稿；人类盲评尚无 |
| Final Decision | [09_final_decision.md](09_final_decision.md) | 不通过最终科学完成门槛，列明采用/待测/放弃 |

## 身份与证据分级

- 论文：[arXiv:2610.10133v3](https://arxiv.org/html/2610.10133v3)，2026-10-19，26页，含附录。
- 官方源码：[PolyU-VCLab/HarnessIR@773f196](https://github.com/PolyU-VCLab/HarnessIR/tree/773f19654d2d4d9a3b0ce20f80508a4dd0788aff)。
- 用户分支：[baolinv0/HarnessIR@e1b610e](https://github.com/baolinv0/HarnessIR/tree/e1b610ef034d467c8c9172e530d38a930956a3bb)。审计行号指此原始快照；本轮修复另外标记。
- 作者数据：[VCLab-PolyU/HarnessIR@d64b3fc](https://huggingface.co/datasets/VCLab-PolyU/HarnessIR/tree/d64b3fc51d30944b6750326f3aeadecd2006ed8d)。

**事实/E2**=原始材料实际读到；**作者报告/E2**=检查了作者表格，未重跑；**复现/E4-software**=实际运行了指定软件行为，绝不外推为画质复现；**观察**=读到实际图像的可见现象；**假设**=需干预验证；**未知**=未取得材料。独立代理同家族审稿是流程独立，不是跨家族接受，也不是真实用户盲评。

## 可运行的交付

```bash
# 仓库根目录；基础图像依赖按原仓库准备
python -m unittest discover -s tests -v
# 完整原有engine回归依赖按engine/pyproject.toml准备
PYTHONPATH=engine/src python -m pytest engine/tests
# 统计输入须为真实、完整配对CSV，字段见04
python research/model_aware_20261024/scripts/analyze_pairs.py measured.csv \
  --cohort frozen_quality_cohort.csv --model qwen --control shared --treatment aware --metric PSNR --direction 1
```

本轮补丁修复S5多类型函数名，保留Direct/Harness两条路径的decoded native output；未部署新Prompt、工具路由或自动模型风险标签。`raw_outputs`位于客户端解码之后、Harness几何/颜色后处理之前；不包含HTTP原始字节。原始E1与修复后的E1-fixed必须分别登记。
