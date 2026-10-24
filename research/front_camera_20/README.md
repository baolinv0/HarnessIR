# 前置实拍 S26 prediction / iPhone 参考：四模型实验包

**状态：实验方案与报告模板已准备；真实图像、GPU 推理、人工评分和质量结论均为 `NOT_RUN`。**

**回传方式：只复制粘贴一份 [EXPERIMENT_REPORT.md](EXPERIMENT_REPORT.md)。** 本文档内联必要配置、汇总和逐样本结果；其他文件仅供服务器执行和留存，不要求上传附件。

本轮只比较 Qwen / FireRed / FLUX / FIBO。源 A 是 S26 linear 经冻结 baseline 处理后的 prediction 的明确显示版本；B 是同场景、未像素对齐的 iPhone 外观参考。人物、内容、表情、几何和构图由 A 决定。

代码接口依据 `86284d5d190614369c4e6c47c5ad8ed021c93a35` 的 `hre models` / `hre_task_v3`。本目录的新脚本仅准备实验清单和匿名评审材料，不修改推理框架、权重或照片，也不运行模型。

## 文件入口

| 文件 | 用途 |
|---|---|
| [DATA_REQUIREMENTS.md](DATA_REQUIREMENTS.md) | 需要补充的数据、颜色定义和可直接回复的信息表 |
| [refine-logs/EXPERIMENT_PLAN.md](refine-logs/EXPERIMENT_PLAN.md) | 假设、矩阵、预算、评价、统计和停止条件 |
| [refine-logs/EXPERIMENT_TRACKER.md](refine-logs/EXPERIMENT_TRACKER.md) | 部署与实验执行记录 |
| [EXPERIMENT_REPORT.md](EXPERIMENT_REPORT.md) | 唯一回传文档；配置、汇总、逐图结果、失败与人工观察全部写在其中 |
| [SERVER_RUNBOOK.md](SERVER_RUNBOOK.md) | 服务器实际操作顺序和结果返回清单 |
| [dataset.example.json](dataset.example.json) | 20 对占位配对表；必须填实际信息后才能生成运行清单 |
| [metadata.csv](metadata.csv) | 场景、人物、拍摄和预处理记录表 |
| [environment.example.json](environment.example.json) | 服务器、模型、编译器和公共 VLM 身份记录 |
| [scripts/build_manifests.py](scripts/build_manifests.py) | 生成与现有 batch 接口一致的实验清单和预算 |
| [scripts/prepare_blind_review.py](scripts/prepare_blind_review.py) | 从运行报告生成隐藏模型身份的离线评审页和评分表 |
| [scripts/export_text_report.py](scripts/export_text_report.py) | 在服务器把计划与运行结果汇总成一份可粘贴的 Markdown |

## 默认决策

- “共 20 张”尚未确认是 **20 对（40 张 A/B）**还是 **10 对（20 张 A/B）**；全部预算以正式配对数 `N` 计算，模板的 20 个 ID 不是已经收到的数据。
- 首先做四模型 × 三种 strategy 的参考实验，加四模型的 A-only 消融。单 seed 为 `16N` 次计划图像生成，`N=20` 时为 **320**，`N=10` 时为 **160**。原始 A 是零生成调用的基线。
- 建议另备 2–4 对开发样本。若只能使用现有 20 对且会根据样例修改提示词/参数，先按场景组分成约 4 对开发、16 对正式；核心生成数为 **256**。若只检查安装与协议，且所有画质相关设置在看结果前冻结，可记录这一事实后评估全部 20 对。
- `native/shared/model_aware` 都保留各模型自己的原生 compiler；这轮测的是完整系统和表达指导的增益。
- 参考外观改善和人物保真分别判断。未对齐 iPhone 不作为整图 PSNR、SSIM、LPIPS 的像素真值。
- 输入统一为经明确转换的 SDR、sRGB、8-bit 显示图。不会猜测 linear prediction 的色域、传递函数或 HDR 映射。
- 主实验固定 `full_frame`，统一测试画布生成规则。不得单独给 OOM 的模型降分辨率后混入同一排名。

## 结果返回

运行后用 `export_text_report.py --study-root /data/front20/study-v1` 生成一个 Markdown，人工补充评分/观察后复制粘贴全部正文即可。图片、JSON、CSV、原始日志和完整 run 目录保留在服务器。本文所有质量结论需标为服务器评审报告；接收方未看图片，不能声称独立完成视觉复核。详细命令见 [SERVER_RUNBOOK.md](SERVER_RUNBOOK.md)。
