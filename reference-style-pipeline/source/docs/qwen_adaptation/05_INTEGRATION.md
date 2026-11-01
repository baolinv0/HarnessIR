# 05 · 基于真实仓库的接入建议

返回：[总览](README.md)。核查 SHA：`3c48c206bb15027366dd9326e8e1fa552c6e6542`。
**本章所有新增接口与路径都是建议；本提交没有修改这些源文件。**

## 1. 现有代码落点

| 已核查路径 | 当前职责 | 建议变化／注意点 |
|---|---|---|
| harness/settings.py | 现有 NB2/GPT Executor 名称和 Gemini 协议设置 | 图像模型客户端适配与 Prompt 适配分离；不能仅换 model 字符串就认为支持 Qwen |
| harness/stages/compose.py | diagnosis/evidence/request → Composition.prompt | 引入结构化意图出口或独立转换，保留原 Composition 兼容路径 |
| prompts/compose_blocks.txt | haze/lowlight/rain/snow/mix 任务块 | 原块只作历史基线，不能直接把 10 个 adapter 操作写成这些 type |
| harness/types.py | 任务块和颜色冲突规则 | 评估标签保持独立；多类型 verify 的静态疑点见问题台账 |
| harness/pipeline.py | plan.prompt → run_execute；日志、后处理、可选 redo | 可选编译点位于执行前；保存原 Prompt、意图、最终文本、hash、版本 |
| harness/stages/execute.py | mfm.edit([send_path], prompt)、padding/crop/resize | 只发原图与最终文本；模型实际返回图在几何处理前另存；SR 单独处理 |
| harness/color_adjust.py | pure mix 用 AdaIN，其余具名类型 copy | 保留日志并隔离后处理，不覆盖唯一 raw 输出 |

建议新增的模块可放 `harness/prompt_adapters/`，具体文件布局由接入实现决定；目前该目录未创建为运行组件。独立包应先按资产 SHA256 确认，再决定复制或 import，不从聊天示例重新手写另一套接口。

## 2. 类型映射不是简单字符串替换

| 原任务语义 | 候选操作 | 额外条件 |
|---|---|---|
| lowlight | low_light | 不自动加 denoise，除非用户目标／诊断确有需要 |
| haze | dehaze | 无须修改评估标签 |
| rain | derain | 原任务若还要求雨雾、模糊等，应显式加入所需操作；只映射雨丝会丢任务 |
| snow | desnow | 区分空中雪粒、雾幕与积雪，不能误删积雪 |
| mix | **无唯一映射** | 根据实际目标和诊断拆解，不能默认所有增强全开 |

新操作 color_cast/highlight_recovery/super_resolution 等需要独立的评估定义与尺寸策略。不要把 `type` 改成不受原 build_system 支持的值，也不要将所有任务悄悄压为 mix 来绕开验证。

## 3. 宿主契约

先检查 `action`：bypass 必须直接交付输入，不调用 Executor。编译错误作为明确失败记录，不静默返回原 Prompt 或换模型。成功时仅取 positive_prompt，图像另传，negative_prompt 按已冻结后端协议处理。

保存 adapter_version/template_hash、原始用户目标、诊断、语义提取器身份、归一化意图、原／最终 Prompt、真实 model ID/revision、最终图像输入、seed、输出和错误。凭据只在环境／本地安全配置中，不进入记录。

旧自由文本入口需要宿主提供语义提取器；v0.1 并未自带一个能理解任意 Prompt 的模型。官方 PE 的 `parse_ok=false` 不得继续把 raw answer 当编辑指令使用。

## 4. 可执行边界与顺序

现有仓库没有本方案的新 CLI 参数，文档不提供伪装成已经可运行的 `--prompt-profile` 命令。

第一步接入单次执行：同 Executor 条件下切换原 Prompt 和模板；默认 NB 路径不变。第二步补齐场景／混合任务与尺寸。第三步才接 redo：每轮重新校验／编译，仍从原 LQ 而非上轮输出出发。

NB 回归、bypass、invalid intent、最终请求一致性、任务标签、postprocess、SR 尺寸与 refine 再编译应各有测试。集成通过与真实图像收益分开验收。
