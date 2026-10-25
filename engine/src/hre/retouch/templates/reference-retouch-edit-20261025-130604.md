# GPT Image 2：参考外观编辑模板
接收者：GPT Image 2 图像编辑器。
实际输入顺序必须为 image 1=A 原始源图，image 2=B 外观参考图。以下花括号必须由已冻结合同填充；不得将未填模板发送生图。本文件不包含任何真实图像观察。

Edit image 1 using image 2 as an appearance reference.

Image 1 is the source photograph and defines the people, identity, expression, objects, readable text, geometry, viewpoint, framing and authentic visible detail. Image 2 defines only the selected photographic appearance described below.

Produce the same photograph as image 1 with these supported changes, in priority order:
{rendered_targets_with_source_region_reference_region_and_criteria}

Coordinate these regional relationships:
{rendered_supported_region_relations_or_omit_section}

Retain the source facts and details:
{rendered_source_protected_facts}

Use image 2 only for:
{rendered_allowed_reference_attributes}

Keep these reference traits out of the result:
{rendered_excluded_reference_traits}

{rendered_feedback_correction_if_this_is_a_revision}

Keep the source lighting direction and scene arrangement. Preserve natural texture already visible in image 1 while applying the requested tonal and color changes. Leave unreadable source text and genuinely missing detail unresolved. Return one photorealistic edited photograph, with the source composition and the declared canvas. Include no captions, labels, borders, before/after panels or additional objects.

## 填充规则

由具体观察生成 targets，不默认任何图必需暖色、提亮或柔化高光。保护身份/纹理与改变渲染肤色分开表述。already_satisfied 目标只列保护要求。新一轮仍使用原始 A+B，保留完整目标状态，并仅增加可证实的修正要求。传输时只有最终英文段落；标题、接收者说明和填充规则不是图像提示。

## 模型参数边界

精确目标为 gpt-image-2（可用时固定其日期快照）；不替换其他图像模型。官方 Images API 可传 A/B 文件列表。GPT Image 2 省略 input_fidelity；不虚构 seed/CFG/steps。n=1，quality 和输出尺寸在真实运行前明确。若宿主工具不能指定/确认模型，只记录实际可见工具身份，不宣称已验证 GPT Image 2。
