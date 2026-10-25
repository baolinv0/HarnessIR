# 参考 Retouch：独立验证模板
接收者：视觉语言模型，独立调用。
输入：A、B、候选 C、生成前冻结的 TransferContract、可信 ROI/属性证据、A→C 已声明几何变换。不给模型名称、编辑 prompt、生成者评价和候选策略标签。

独立完成三项判断：
1. 内容保持：对 A/C 检查身份、五官/表情、姿态、对象数量、结构、构图、可读文字、可信纹理与物理光向。允许合同要求的颜色/亮度改变。不得用 A/C 原始 RGB 差异直接判定内容损坏。
2. 参考属性达成：逐个 target_id 检查 C 是否达到预先标准。分别记录 A→C 变化、C 与 B 在可信对应区域的差距、achieved / partial / unmet / uncertain、证据和副作用。仅更好看、锐利或更亮不能证明参考跟随。B 非像素 GT。
3. 自然度与污染：检查剪裁/溢出、色阶断裂、光晕、过饱和、塑料肤质、B 对象/纹理渗入及局部接缝。目标内达成也不能抵消身份或文字损伤。

返回 JSON：
- target_results：每个冻结目标恰好一条，使用同一 target_id，附 status、evidence_refs、observation、remaining_gap、suggested_correction。
- preservation_checks：每项 pass / fail / uncertain 与具体区域；A 原本不可读文字保留 unreadable，不能按新生成文本的清晰度评分。
- artifact_checks：pass / fail / uncertain，重大程度与证据。
- global_status：accept / revise / reject / uncertain / already_satisfied。
- actionable_issues：只给可观察、可修正的问题；每项关联目标或保护项。
- evaluator_coverage：说明未看清、缺少工具或不可比较的部分。

accept 必须全部 mandatory targets 为 achieved，且 mandatory preservation/artifact checks 通过。出现 mandatory partial/unmet/uncertain 时绝不能 accept。already_satisfied 只适用于生成前合同已确认无须编辑并交付原始 A 的路径。uncertain 不能以高自评置信度抵消。不要修改目标、删除困难目标或调低阈值；不要以“模型能力上限”解释失败。
