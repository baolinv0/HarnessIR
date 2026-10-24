# HarnessIR VLM 调用与分阶段能力实验包

日期：2026-10-24；版本：1.0；状态：计划与空白模板，未在服务器执行。

目的：为 Qwen3.8-27B、Qwen3-VL-32B-Instruct、Qwen3-VL-8B-Instruct 选择合理调用方式，分别测诊断 D、规划 P、判别 J；可选用固定 Qwen-Image-2.1 做 C/E 验证。不是四种图像编辑器的横向 benchmark。

1. 按 [实验计划](EXPERIMENT_PLAN.md) 的 S0→S4 执行，每一步都可单独返回结果。
2. 复制 [模型配置](models.example.json) 到服务器，修改模型 ID/端口，生成两个 seed 配置。
3. 按 [执行清单](EXPERIMENT_TRACKER.md) 标记完成，逐次填 [运行记录](runs.csv) 与 [观察审核](observations.csv)。
4. 复制 [报告模板](REPORT_TEMPLATE.md) 为自己的 REPORT.md，填实测值并附原始结果、对比 HTML。

文档发布在 main；执行命令针对带 `hre lab` 的 [stage-model-lab 分支](https://github.com/baolinv0/HarnessIR/tree/feat/stage-model-lab-20261022)，核对过的实现 SHA：8636e25ad68dcb309961241bb9da454ed7ef0347。**main 上有本文档不代表 main 已合并该测试台**。优先在你已有服务器代码上执行，记录实际 SHA 与本地 diff；不要覆盖已有修改。

本包不修改运行代码、不安装服务、不运行 GPU。既有“27B 有 10 条观察”等为用户先导报告，不作为本实验已验证结果。下载文档后不必切换服务器工作分支。
