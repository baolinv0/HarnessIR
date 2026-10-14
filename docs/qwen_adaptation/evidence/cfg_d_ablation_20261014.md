# H08 下一轮·第一步实测：CFG 配置 × D 消融 × 确定性基线

运行日期：2026-10-14。级别：IMAGE_VALIDATED（本地真跑 Qwen-Image-2.1，6 图 × 5 臂 × 3 seed × 2 配置 = 180 张生成 + 6 确定性基线 + 6 输入 = 192 张打分）。样本为分层开发集（exdark/jarvisir/acdc 各 2 张），不是泛化测试；seed 是图内重复，聚合先逐图平均再跨 6 图，不把 seed 当独立样本。

- 脚本：[compare/qwen21_cfg_d_ab.py](../../../../compare/qwen21_cfg_d_ab.py)、[compare/iqa_cfg_d.py](../../../../compare/iqa_cfg_d.py)
- 原始分：[iqa_raw.json](../../../../compare/qwen21_cfg_d/iqa_raw.json)；聚合：[aggregate.json](../../../../compare/qwen21_cfg_d/aggregate.json)；区域亮度：[cfg1p0/region_stats.json](../../../../compare/qwen21_cfg_d/cfg1p0/region_stats.json)、[cfg4p0/region_stats.json](../../../../compare/qwen21_cfg_d/cfg4p0/region_stats.json)

## 1. 三项 NR-IQA 组均值（n=6 图，先逐图对 3 seed 平均）

| 臂 | CLIPIQA | MUSIQ | TOPIQ |
|---|---:|---:|---:|
| Input LQ | 0.256 | 37.49 | 0.240 |
| baseline tone/gain（确定性，无模型） | 0.186 | 37.81 | 0.244 |
| **cfg1.0** simple | 0.355 | 59.88 | 0.445 |
| cfg1.0 compose（原框架） | 0.324 | 52.92 | 0.375 |
| cfg1.0 drop_guards | 0.326 | 53.26 | 0.379 |
| cfg1.0 compact | 0.358 | 60.01 | 0.438 |
| cfg1.0 region_target | 0.366 | 58.75 | 0.434 |
| **cfg4.0** simple | 0.399 | 68.07 | 0.548 |
| cfg4.0 compose（原框架） | 0.369 | 54.73 | 0.412 |
| cfg4.0 drop_guards | 0.370 | 55.41 | 0.418 |
| cfg4.0 compact | 0.433 | 69.93 | 0.553 |
| cfg4.0 region_target | 0.450 | 68.11 | 0.555 |

## 2. 三个可判定结论

**(a) CFG 是显著混杂变量，H08 与官方默认不可直接比。** 同一臂 cfg4.0−cfg1.0：simple +0.043/+8.19/+0.103，region_target +0.084/+9.36/+0.121。cfg4.0（H08 实际配置）系统性地更高也更亮（simple 臂 global 0.285 vs 0.199）。H08 的 Qwen 结果绑定 cfg=4.0，不能当作官方默认行为。pipeline/调度器/步数已核对与官方一致（见 [配置核查](qwen21_config_audit_20261014.md)）。

**(b) 框架臂负收益在两种配置下都复现。** compose−simple：cfg1.0 −0.031/−6.97/−0.070；cfg4.0 −0.030/−13.35/−0.135（CLIPIQA −0.030 与 H08 报告的 −0.030 完全一致）。负收益不是单一配置造成。

**(c) 机制线索：问题更像“冗余长度/结构”，不是“保守约束条款”。**
- drop_guards ≈ compose（cfg4.0: 0.370 vs 0.369 CLIPIQA）：**只删“保持夜感/不要变亮/不要改动”这类条款几乎无收益**。
- compact（同义压缩重写）与 region_target（压缩+正向区域目标）**反超 simple**：cfg4.0 compact +0.035、region_target +0.052 CLIPIQA；cfg1.0 也由负转正。
- 解释：原 Compose prompt 的长篇重复表达才是负收益主因；压缩重写消除冗余后恢复并超过 direct。这支持 I-01 的“长度/结构”分支，弱化“保守措辞”分支。但 drop_guards 同时缩短文本不多（3848→3090 字），compact 缩到 ~533 字，长度与语义压缩仍部分共变，需在更大样本和等长度对照上确认。

## 3. 不能下的结论

- 确定性 tone/gain 基线把图拉亮（global 0.275 vs 输入 0.194），但 CLIPIQA 反而更低（0.186）：**“更亮”不等于“更高质量分”**，该基线只作亮度参照，不作质量目标。
- region_target/compact 在 6 张开发图上领先，尚未在独立样本验收；region_target 加了区域目标但与 compact 共变，区域目标的独立贡献未分离。
- 本轮仍无 redo/闭环；所有臂都是单次生成。内容保真（身份、小物件）未独立盲评，NR-IQA 不验证保真。
- NB2 未在本轮重跑；cfg 对照只针对本地 Qwen。

## 4. 对下一步的直接输入

1. **配置**：D 类消融若要跟 H08 可比，沿用 cfg=4.0；若要对接官方默认，需全套重跑 cfg=1.0。两配置结果分开报告，不混用。
2. **Prompt**：把“压缩重写”作为独立臂推进；region_target 需在压缩基底上单独加减区域目标以分离其贡献；等长度近似改写作为残余混杂对照。
3. **B（等预算闭环）**：在 compact/region_target 这条已转正的单次路径上，再做 3 次反馈生成 vs 3 次无反馈采样＋同一选择器，分离反馈收益与额外计算。
4. 失败/逐图离群（如个别 seed CLIPIQA 跌到 0.23）需保留并查因，不得静默删除。
