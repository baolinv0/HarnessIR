# 06 · 证据、来源与缺口

返回：[总览](README.md)。本次整理于 2026-10-13；所有外部网页都可能继续更新。

## 证据等级

REPO_VERIFIED=本次读取仓库代码；USER_REPORTED=用户提供实验摘要，未从图像重算；LOCAL_TESTED=本次运行离线程序测试；PROPOSED=设计建议。上述标签不自动等价于 IMAGE_VALIDATED；本次没有新增任何真实图像性能验证。

## 仓库证据（固定 SHA）

基线提交：[3c48c206](https://github.com/baolinv0/HarnessIR/commit/3c48c206bb15027366dd9326e8e1fa552c6e6542)。

| ID | 固定来源 | 支持的事实 |
|---|---|---|
| R1 | [settings.py](https://github.com/baolinv0/HarnessIR/blob/3c48c206bb15027366dd9326e8e1fa552c6e6542/harness/settings.py) | 当前 Executor 注册和协议设置；不是 Qwen 本地运行证据 |
| R2 | [pipeline.py](https://github.com/baolinv0/HarnessIR/blob/3c48c206bb15027366dd9326e8e1fa552c6e6542/harness/pipeline.py) | Compose→Execute、颜色处理、redo、日志位置 |
| R3 | [compose.py](https://github.com/baolinv0/HarnessIR/blob/3c48c206bb15027366dd9326e8e1fa552c6e6542/harness/stages/compose.py) | DEFAULT_SPEC 已允许必要亮度／颜色变化；instruction→prompt |
| R4 | [compose_blocks.txt](https://github.com/baolinv0/HarnessIR/blob/3c48c206bb15027366dd9326e8e1fa552c6e6542/prompts/compose_blocks.txt) | 原五类任务、夜感保持与阴影恢复并存；源码注释实验不作本次实测 |
| R5 | [execute.py](https://github.com/baolinv0/HarnessIR/blob/3c48c206bb15027366dd9326e8e1fa552c6e6542/harness/stages/execute.py) | 图像／文本调用及 resize/crop；SR 风险 |
| R6 | [color_adjust.py](https://github.com/baolinv0/HarnessIR/blob/3c48c206bb15027366dd9326e8e1fa552c6e6542/harness/color_adjust.py) | pure mix→AdaIN，具名类型→copy |
| R7 | [types.py](https://github.com/baolinv0/HarnessIR/blob/3c48c206bb15027366dd9326e8e1fa552c6e6542/harness/types.py) | 类型冲突规则与多类型 verify 静态疑点 |
| R8 | [README.md](https://github.com/baolinv0/HarnessIR/blob/3c48c206bb15027366dd9326e8e1fa552c6e6542/README.md) | 原五阶段定位、评分与运行说明 |

## 用户报告（不可冒充仓库原始实验）

U1：2026-10-09～10 会话中的 Qwen-Image-Edit 实际调用摘要和 night_0001 三个均值，随后确认 Edit-2511。原图、请求原文、运行日志、revision 未随本次请求提供。

U2：2026-10-13 用户引用 §6 A/B/C/D、§7.1 seed、§7.2 smoke 和跨 Qwen-Image-Edit/FLUX/Qwen21 复现。章节全文与逐组数据缺失；本记录仅保存该报告，不构造不存在的链接或数字。

U3：本次会话中 Qwen-Image-2.1 三图固定区域表及 4381 字 Compose Prompt 的摘要；数值在 [CSV](evidence/night_roi_reported.csv)。没有完整 4381 字文本、图像、ROI 坐标、亮度公式、测量脚本、seed、配置和原始输出，所以不做“已独立复现”声明。

用户原判断为保守措辞导致变差；归档后的审慎判断为主要候选原因，需机制隔离。直接更亮、road_std 更高，尚不足以证明 Direct 总体恢复质量更好。

## 资产与复测

A1：先前会话提供的 qwen21_prompt_adapter_v0.1.zip。ZIP 和源码文件指纹见 [artifacts.json](evidence/artifacts.json)。本次在未修改的解压资产上重新运行 36 项单测，见 [日志](evidence/adapter_v0.1_reverification.txt)。仅模板 JSON 被复制为文档快照；可执行源码与完整 ZIP 未包含在本提交。

## 官方资料（2026-10-13 重新核对）

O1：[Qwen 编辑改写 System Prompt](https://github.com/QwenLM/Qwen-Image-2.1/blob/main/prompt_rewrite/prompts/system_prompt_edit.txt)：图像依据、目标属性与非目标保持、正向指令、单段改写。它不是本项目恢复模板的性能认证。

O2：[Qwen Prompt Enhancer README](https://github.com/QwenLM/Qwen-Image-2.1/blob/main/prompt_rewrite/README.md)：edit 需要图像与文本；原始回答和工具记录字段不同；检查 parse_ok。未下载或部署 PE。

O3：[Google Cloud Nano Banana Prompting Guide](https://cloud.google.com/blog/products/ai-machine-learning/ultimate-prompting-guide-for-nano-banana)：编辑目标与保持内容的官方指导。不能从文档推出 NB2 必然白昼化，或 Qwen 必然更保守。

## 待补材料

按 [实验模板](templates/EXPERIMENT_RECORD.json) 补齐 local commit、model revision、input/ROI/prompt/config/output 哈希、逐 seed 指标及失败图。无法公开的图像可用受控资产 ID 与访问说明代替，但不能把缺失材料伪装为公开可复现。禁止上传 API Key、访问令牌或未经许可的人像原图。
