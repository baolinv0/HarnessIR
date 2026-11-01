# 历史传输层静态检查（非新执行实验）

只读取精确恢复的原诊断、人工映射脚本、目标记录与真实发送编辑指令；没有重新编译或生成。

- `compile_actual_targets.py` 为 r1 全脸、r3 颈部、r5 柜体显式填入 `strength=strong`，实际编辑指令 t4/t5/t8 保留了这个分类。原诊断引用文字确实逐字存在；但离散强度标签来自映射脚本，不是引用哈希自动证明、数值标定或编译器从诊断自动解析的结果。脸的原文有“明显”，颈/柜原文没有同等显式离散强度字段。
- 原全局 g0 段落被 tone/color/brightness 三个目标逐字重复，真实编辑指令中出现三次；不是三条各自独立的具体全局目标。
- 这说明传输层除了转述诊断，也有操作者强度编码和重复。它们**可能**影响强调程度，但静态记录不能证明造成历史候选的任何偏差，也不应据此直接分配因果比例。
- 原提示仍有 B 参照终点及 A 内容/结构保留条款；不能把上述发现歪写成完全没有终点/保留要求。
- 本次 D0/D1 只测新干净上下文下诊断规范差异；没有测试“去 strong”“去三重复”、图像执行器或旧长上下文。若以后要归因传输/执行，需要单独固定其余输入的实验，本轮未做。

证据文件 SHA、目标字段和原样引用见同名 JSON。此审计不发送给本轮 label-blind 评分者。

## 实际源代码逐字摘录

文件 `actual_run/pipeline_s2/compile_actual_targets.py`，SHA256 `fee18974bf2cda834cbbf6c9465c1088b7d77d187f6cd9c4d4335cd8a2f40a00`。

第 16 行：
```python
for dimension in ('tone','color','brightness'):add('g0',dimension,'match_B','moderate',lines['g0'])
```

第 17 行：
```python
for rid,dim,direction,strength in [('r1','tone','increase_toward_B','strong'),('r3','tone','increase_toward_B','strong'),('r2','color','match_B','moderate'),('r4','tone','match_B','gentle'),('r5','color','match_B','strong'),('r6','color','match_B','moderate'),('r7','tone','match_B','gentle')]:add(rid,dim,direction,strength,lines[rid])
```

这两行分别创建三个同引用的全局目标，并人为分配各区域的离散强度。编译器 `s2_stage.py` 随后把 `strength` 原值渲染进 `Style goal [...]`；并非诊断模型自动输出的可靠标定强度。
