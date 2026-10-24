# 分阶段模型测试台实施清单

目标：D/P/C/E/J 每阶段能独立调用多个模型、保存结果、并排可视化，并选用已保存结果继续下一阶段。

依据：本会话已确认的 Model-Aware 分阶段调试方案；用户要求直接实现功能。

实现：在现有 Python engine 中增加独立 `hre lab` 入口和 Streamlit 测试台；结果使用普通 JSON 与图像文件，原 v2 流程继续可用。

- [x] 核心：案例、模型配置、阶段输入构造、批量运行、结果导入导出、阶段结果复用。
- [x] 接口：OpenAI-compatible、Gemini、外部命令与离线导入；附四模型可选原生 worker。
- [x] 界面：A/B 输入、阶段选择、多模型运行、上游结果选择、图像/文本/JSON并排、运行时间与输出指标。
- [x] 报告：独立 HTML，比对结果可离线打开，提供筛选、文本差异、图像对照与原始数据。
- [x] 集成：CLI、模型配置示例、CPU 演示、运行说明。
- [x] 验证：真实本地 HTTP/命令协议测试、阶段复用与独立运行、UI 烟测、旧 engine 回归、代码审阅。

接口约定：`stage_lab.core` 提供 init_lab/add_case/list_cases/list_runs/run_stage/import_output/export_request。provider 接收阶段 request 并返回 text/data/images/usage/metadata；每次运行独立保存，错误不会阻止同批其他模型。

重点检查：执行阶段传递编译输出；Judge 默认不读取规划理由；不同 case 不混用上游图；原始输出不 resize；缺少模型服务时报明确错误；demo 始终标明模拟输出。

交付到独立分支 `feat/stage-model-lab-20261022`。原生权重推理需用户的模型环境，离线测试不代替模型效果验证。

验证记录：engine 全量回归 391 项通过；审阅修复后新增功能定向测试 35 项通过（覆盖新增回归场景）。CLI 合成演示跑完 12 次运行，Streamlit AppTest 跑完五阶段，原生接口使用 mock 验证，未运行真实模型权重。
