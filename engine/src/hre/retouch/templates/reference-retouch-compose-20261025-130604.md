# 参考 Retouch：目标合同与提示编译模板
接收者：视觉语言模型；输出由控制器检查后冻结。
输入：用户 brief、A/B、经证据支持的诊断、参考外观档案、属性级区域对应、实际证据与可用性、保护约束、明确的目标优先级。

生成 TransferContract 草案和供 GPT Image 2 使用的英文自然语言 edit_prompt。Contract 是评价目标；edit_prompt 是该目标的一种表达。两者不得互相替代。

Contract 包含：
- roles：A 提供内容，B 仅提供所选外观；本轮固定从原始 A 编辑。
- allowed_scope：允许的亮度/色彩/影调/局部对比范围；默认不改变光向、天气、身份、表情、对象、构图。
- targets：每项有稳定 target_id、attribute、独立 A/B 区域、source_observation、reference_observation、desired_change、mandatory、acceptance_criterion、evidence_refs、comparability、uncertainty。数值标准仅引用实测与预先认可阈值，否则用可判定的视觉标准。
- protected_facts：几何/身份/文字/材质与可信纹理等。允许目标要求的渲染颜色变化；不可同时写“保持所有像素/所有颜色不变”。
- excluded_reference_traits：B 中不应迁移的内容、纹理、反光/光向差异等。
- coverage：每项请求的外观维度映射到 target_id，或已有满足/不可比较/不适用的理由。
- overall_status：ready_to_edit / already_satisfied / insufficient_evidence / preference_conflict。
- acceptance_rule：所有 mandatory 目标达成，保护事实通过，且没有重大伪影/内容污染；uncertain 不算完成。

可以用少量主操作组织提示，但不得因操作数量限制而遗漏必需属性。没有明确目标时不能添加“商业大片/高级质感/电影感”等泛化美化词。已经满足的目标记 preserve/already_satisfied，不能为了“有改善”强行改变。

edit_prompt 应依次包含：输入角色；期望最终外观及优先级；可支持的局部关系；保护项；参考排除项；输出单张与 A 相同构图。指明对 A 的变化幅度，避免重述 B 的完整内容场景。不要给模型索要 JSON 分析、拼图、对比图或说明文字。

ready_to_edit 前若仍存在必需但无依据的目标，返回 insufficient_evidence；不能静默把 mandatory 降为 optional。
