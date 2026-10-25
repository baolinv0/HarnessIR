# 参考 Retouch：反馈修订模板
接收者：视觉语言模型。
输入：原始 A+B、冻结 TransferContract、上一轮 edit_plan、候选 C、独立验证结果、剩余生成预算。下一次编辑输入仍为原始 A+B。

仅根据有证据的残余差距或副作用修改编辑计划。返回 action=revise / stop / needs_review，以及目标完整覆盖的 revised_plan、changed_target_ids、feedback_refs、reason。

保持评价合同的目标与保护要求不变。对于已达成项，在新的完整期望状态中保留；对未达成项给更清楚且可执行的方向。不能为了修复肤色而静默取消高光目标，也不能将“亮度已改善”当作所有参考目标完成。禁止将候选 C 作为新 source，以免累积重绘。

内容损伤优先修正或停止；参考不合适/目标冲突应 needs_review，不能强行加大编辑。没有新的可支持改法或预算耗尽时 stop，交付状态为 task_not_met 或 uncertain。可以保留未通过候选供审阅，但不得重标 accepted。若交付原始 A，标记 source_fallback，不混为成功编辑。

新计划由固定模板重新编译为完整编辑 prompt；只保存本轮实际变化，避免堆叠互相冲突的历轮指令。
