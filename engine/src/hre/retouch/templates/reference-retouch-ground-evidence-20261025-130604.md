# 参考 Retouch：证据复核模板
接收者：视觉语言模型。
输入：A、B、初始诊断、实际工具记录、独立 A/B 区域及工具可用状态。

将测量结果与视觉观察相互核对，输出更新后的 source_diagnosis、reference_profile、correspondence、candidate_deltas、coverage 和 analysis_status，并附 changed_observations。不得删除相互矛盾的证据。

只将提供的数值称为 measured；未执行工具、失败工具或图中估计不得标 measured。显示域亮度、Lab 与分位数不能解释为真实辐射或精确曝光补偿。分位数接近不证明影调曲线相同。对应区域的材质、光照或可见面积不同会限制比较；仅在可比属性上提出迁移。

B 的高光已裁切时，不能将其白色区域当作隐藏细节目标；A 的文字/纹理不可辨时不能用 B 的文字/纹理补全。B 某项风格不可观测时保留 unknown。遇到重要冲突，输出具体需人工确认的属性，而不是将所有目标平均化。

本步最多做一次必要的证据复核；已无歧义且无需新证据时可以跳过。
