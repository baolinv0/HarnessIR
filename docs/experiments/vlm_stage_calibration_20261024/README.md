# HarnessIR VLM 调用与分阶段能力实验包

日期：2026-10-24；版本：1.0；状态：计划与空白模板，未在服务器执行。

目的：为 Qwen3.8-27B、Qwen3-VL-32B-Instruct、Qwen3-VL-8B-Instruct 选择合理调用方式，分别测诊断 D、规划 P、判别 J；可选用固定 Qwen-Image-2.1 做 C/E 验证。不是四种图像编辑器的横向 benchmark。

1. 按 [实验计划](EXPERIMENT_PLAN.md) 的 S0→S4 执行，每一步都可单独返回结果。
2. 复制 [模型配置](models.example.json) 到服务器，修改模型 ID/端口，生成两个 seed 配置。
3. 按 [执行清单](EXPERIMENT_TRACKER.md) 标记完成，逐次填 [运行记录](runs.csv) 与 [观察审核](observations.csv)。
4. 复制 [报告模板](REPORT_TEMPLATE.md) 为自己的 REPORT.md，填实测值并附原始结果、对比 HTML。

**本次唯一测试对象：`feat/stage-model-lab-20261022` 分支的五阶段测试台。** 文档与配置已同步到该分支，核对过的运行代码 SHA：8636e25ad68dcb309961241bb9da454ed7ef0347。此前 main 上的文档属于初始归档；执行时以本分支文档和你的服务器实际 SHA 为准，不混用 model-aware-parallel 分支的 Controller/worker 协议。

服务器已有该分支时，先保留本地修改，再 `git pull --ff-only`；若有分叉不要强制 reset。新检出可用：

```bash
git clone --branch feat/stage-model-lab-20261022 --single-branch https://github.com/baolinv0/HarnessIR.git HarnessIR-stage-lab
cd HarnessIR-stage-lab
python -m pip install -e ./engine
hre lab --help
```

本轮是该项目的 VLM 校准与 D/P/J 分阶段实验，可选固定 Qwen 执行器检查 C/E；四个图像执行器的完整横向对比属于后续实验，不能用本轮 VLM 结果替代。

本包不修改运行代码、不安装服务、不运行 GPU。既有“27B 有 10 条观察”等为用户先导报告，不作为本实验已验证结果。优先沿用该分支上已有的服务器环境。
