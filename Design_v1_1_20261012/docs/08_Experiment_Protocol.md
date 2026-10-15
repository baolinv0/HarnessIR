# 实验协议：先验证架构，再检验增益

## 研究问题与结论边界

问题：在同一 ChatGPT 图像编辑功能下，诊断 + 按需工具 + Prompt 编写 + 验证反馈能否比直接编辑获得更好的退化去除，同时保持内容？本地 UI 流程通过只证明交接可用。后端模型不可锁定时，结论是“所记录 ChatGPT UI 条件下的表现”，不能宣称严格复现论文 API 数值。

官方仓库同时提供 NB2 和 GPT-image-2.5 路径；本方案与它仍有 VLM、交互方式、Prompt、工具实现、几何、停止与后处理差异。不可因为同属 OpenAI 图像编辑就把桌面输出等同某个 API 模型。

## 对照矩阵

| 组 | 诊断 / 工具 / Compose | 编辑次数 | 验证与选图 |
|---|---|---|---|
| Direct-1 | 无；固定 baseline Prompt + 相同 intent | 1 | 第一完整图；只做盲评 |
| Harness-1 | 完整前三阶段 | 1 | 同一盲评，无 retry |
| Direct-repeat-3 | 固定 baseline Prompt，不反馈改写 | 最多 3 | 保留三次，预定第一图为实际交付；另报告盲评 best-of-3 作采样分析 |
| Harness-loop-3 | 完整流程 + verifier / refine | 最多 3，成功早停 | 固定内部选择规则；记录实际次数 |

P0 第一个 case：Direct-1 与 Harness-1 各一张。若 Harness 因验证失败重试，retry 另记为 Harness-loop，不能把它与只生成一次 Direct 的差值称为“同预算增益”。同预算结论优先看 Direct-1 vs Harness-1；循环 vs 重复采样需报告 budget、选图规则与实际使用次数。不要把所有差异归因于单个模块。

两组使用同一 canonical bytes、固定 intent、UI 功能 / 显示名、尺寸选项和输出设置，创建时间尽量相近，交错组别执行；默认新会话。seed 未暴露时记录 seed_control=false；不声称确定性。服务端可能更新权重，持续记录测试时间。

## 数据与评价

R0 一张真实拍摄图仅验证端到端与失败记录。后续 pilot 建议 12 张分层照片（低光 / 噪声、模糊、雨雾、文字、人脸、混合退化各有覆盖，可跨标签），验证工程与评测是否有分歧；若看算法趋势，预注册至少 30 张独立真实拍摄图，分层、全部纳入结果。这个样本数是实施建议，不是功效保证。开发图不能混进冻结测试集。

有可信对齐 GT：PSNR/SSIM/LPIPS/DISTS，统一几何与色彩预处理并记录；GT 不用于在线 Prompt / verifier / 选图。没 GT：原图对比盲评、可读文字一致性、人脸 / 结构漂移、退化残留、逐区域失败率。无参考 IQA 作为辅助，不能单独证明保真。

独立最终评测不能复用闭环 verifier 的 verdict 作主指标。人盲评推荐随机 A/B 左右、隐藏组名，分“去退化”“内容保真”“可用性”三项；记录平局与不可判断。以图为统计单位，重复生成属于同图内相关采样。报告 paired differences、胜/平/负、95% bootstrap CI 和灾难性改动比例；不同类别单列。

官方 DF 为逐图 sqrt(D*F) 后平均，D/F 为 0–100；本地 verifier 的 0–10 scores 不可改名为官方 DF。本包保留 DF Prompt 快照供工程师后续严格装配；使用新模型 / 修改 Prompt 的 DF 必须命名 adapted_DF。工程 R0 不要求装全量 IQA 工具。

## 防止取样与人工偏差

图像清单、intent、baseline Prompt、profile、最大生成数、内部选择规则在开始前冻结。所有任务与失败样本都保留；不能只把成功图纳入平均。人工改 Prompt / 增工具 / 选图变成 manual_variant 单列。不可恢复 / 额度耗尽仍进入分母。方法内部 best_round 与最终独立评测分开。

## 如何决定下一步

- Direct 和 Harness 都改变脸 / 字：先检验 executor 保真上限，不继续加复杂 Prompt。
- Harness-1 比 Direct-1 差但 loop 好：拆开 Prompt 初次收益与多次采样收益。
- 图片格式错误多：修文件桥后重新跑冻结 case，不改变算法标准。
- 只有单张好看：保留案例观察，不外推真实数据总体恢复能力。
- 无工具组与有工具组接近：再做按需工具消融；P0 不提前堆砌全部消融。

## v1.1 工具实验轨道

cpu_probe与gpu_full单列，model/backend/preprocessing/labels均锁定。按需消费cached证据相当于同配置工具执行的复用，但缓存来源、预计算成本和外部设备信息完整记录。Small或YOLOE结果不得标为Base/SAM3；正式工具仍不等于原论文完整复现。
