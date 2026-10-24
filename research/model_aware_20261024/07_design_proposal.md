# 7. Model-Aware Design Proposal

## 当前设计决策

保留原始复原五阶段骨架；不将参考增强engine的A+B contract强行移植，也不借助复制LQ为B来绕过接口。先做可复现性修复，真实画质实验通过后才选择最少必要Stage。

| 层 | 本轮动作 | 依据 | 收益界限 |
|---|---|---|---|
| 原始S5规范 | 修正 `_colour_clause_judge`→`_colour_clause_verify` | 自然触发NameError＋红/绿回归 | 验证分支可以执行；不声称画质提升 |
| 原始S4与Direct | 同一`archive_native_output`保存客户端返回图、SHA、native尺寸、executor输入、是否发生尺寸归一 | 原实现丢端点，控制例可复现 | 增强审计可辨识性；交付像素处理算法不变；增加存储与IO；存档失败保留可交付图并标native_archive_complete=false、archive_error |
| 统计 | scene级配对bootstrap/模型×policy差中差脚本 | 受控fixture＋缺失拒绝测试 | 只接受真实CSV，不替代评价/独立验证 |
| Prompt/Evidence/路由 | 不部署候选策略 | 目前没有单阶段或冻结收益 | 避免给未经检验规则赋予永久系统行为 |

补丁中的raw是**decoded native image**：原始Gemini client已解码并转RGB；既不是HTTP响应字节，也不保留转RGB前alpha/EXIF/ICC。几何后的图仍可能被颜色对齐覆盖；为了完成E4三端点评估，还需另存geometry-only与final输出hash、transport metadata、实际参数。此项保留在计划中，不假称完整trace已实现。新增存档失败不再丢弃本可交付的候选，但显式标记native_archive_complete=false及archive_error；这样的运行不能冒称端点证据齐全。后续写交付图失败仍保留已经成功存档的raw回执。

## 单图模型接口的最小后续适配（尚未实现，质量收益未知）

S1→S2→S3仍共享；只在S3与S4间加`RestorationCondition`，含source_LQ哈希、frozen task/region/protection IDs、最终prompt、原生参数、executor identity。**只需单一源图**；无reference_targets或appearance A/B字段。接口描述必须能返回unsupported，不由模型名补造mask、bbox或strength。

NB2调用器只编译经核验端点支持的image/text/aspect/imageSize/采样字段，记录requested/returned model、服务别名和不可控随机性。不能静默用NB2.1替代NB2或用3.8 VLM冒称3.7。

Qwen单图调用器使用精确`QwenImage21Pipeline`和已部署本地revision；显式W/H、output_resolution、steps、CFG/negative_prompt、cache/dtype/attention、generator。该适配器本身先做原生Direct parity验证；后续E2/E3都用同一调用器，避免把adapter实现差异当策略增益。当前原始`MFMClient`未接Qwen，本地用户替换版本必须提供actual code后才审计其行为。

## 质量改动条件准入

- 若只有E2在两个模型上都改善且无交互：采用更好的共享S3，不命名为Model-Aware成果。
- 若交叉prompt证明仅某模型特定表达有效，且长度/信息/尝试数配平：只为该模型加入S3 renderer。
- 若正确证据与打乱/去除证据有差，并且信息消费链可追：加入该证据编码；无贡献工具删除。
- 若E5定向动作超重采样＋同selector，且原因分类可靠：只加入已证实的failure→action；classifier允许unknown。若收益主要来自选优，改善共享selector即可。
- 若E4配置修正解释主要收益：修adapter/profile，报告为工程配置修复，不称新Harness策略。
- 若E6复杂度不能超等预算强共享，或在冻结测试保真退步：回退共享；保留负结果。

最终方案按“stage数更少→额外调用更少→端点更可审计”的顺序作simplicity比较，而不是按模型数量或配置条数评估完成度。没有数据支持自动strategy_router，因此本轮不加入。

## 研究交付与远端状态

本轮在源分支的隔离本地研究分支创建补丁和报告；未改动`engine/`的参考增强功能。当前没有合并或发布画质策略，也没有启动模型调用或外部算力。原始commit可作为E1；修复版另有patch，保持比较可复查。
