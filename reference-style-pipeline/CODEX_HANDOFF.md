# Codex 完整交接：目的、实现与边界

## 1. 不可丢失的产品目标

- 生产 A 是共同 Base 模型已经输出的 RGB；B 是同时拍摄同一场景的另一部手机 sRGB，可能不对齐。入口只有 A/B，不接 RAW X。此次 Camera0717 S26/iPhone17 是**另一个明确授权的 camera_rgb 流程试验域**，不能用 dataset 字符串伪造 Base lineage；真实 Base 域尚待验证。
- C 尽量贴近 B 的整体影调、色彩、亮度、全物体/材料及相对关系，同时最大保留 A 的场景、人物身份、表情/姿态、布局、几何、文字和纹理。目标是参考忠实度，不是泛化美化或只把人脸变亮。
- 所有区域作为整物体/整材料单元联合编辑一整帧。整脸、可见皮肤、头发、衣服可用；禁止把脸拆成高光/阴影/额头/脸颊局部影调编辑单元。定位图不是硬 mask，也不是像素对应关系或目标图。
- AB 阶段融合真实数值和 VLM 视觉差异；ABC 阶段分别检查 A–C 内容一致、B–C 风格残差与相对初始 A 的进展。分割、相对深度、OCR、既有人脸证据可用时接入，不可用就降级为 unavailable/uncertain；不能制造缓存或假结果。深度只在每张图内相对解释，不是“深处必暗”的亮度定律。
- preservation_requirements 在诊断/目标/提示/反馈都存在；**AcceptancePolicy 仅 verifier/selection 可读**。用户只允许在总体 B 风格及关键要求已满足后，事后容忍实际发生的轻微局部结构偏差；不能预先在提示中允许换脸、改纹理/几何，也不能把 accepted/tolerated 历史带入下一次编辑。
- 直接生成的 C 是有效候选，不要求强制投影回某个确定性调色器。下一轮始终从原始 A+B 出发，不能保留/累积被容忍的 C 几何漂移。

## 2. 已实现的实际模块

源码主包：`source/engine/src/hre/reference_style/`，当前 envelope `reference_style_s4_v6`。共 175 项 scoped 测试位于 `source/engine/tests/reference_style/`。

|范围|模块|现有功能|仍需人工/外部真实证据|
|---|---|---|---|
|S0/S1|contracts, audit, coordinator, cli|角色顺序/来源域、颜色/ICC/精度、明确 RGB8 派生、状态/attempt/hash、不可变导入|确认实际来源和 profile，独立图像检查|
|S2 证据/数值|s2_evidence, s2_measure, s2_public, s2_store|真实资产导入、原生坐标/变换、整区域支持/匹配、覆盖和层级、Y/Lab/C* 分布、带符号关系|实际分割/深度/OCR；mask 质量/语义对应由工具/操作者承担|
|S2 诊断/目标|s2_stage, visual_goals|AB 文件桥、诊断与证据先冻结、后目标版本链；具体区域视觉摘录/关系及数值控制编译|当前 ChatGPT 实际诊断；操作者选取受绑定的风格摘录，不是自动读全部 prose|
|S3|s3_handoff, s3_candidate|保存 compiled draft → edit-export；A/B 及 bounded guides；真实提交声明；raw C 导入和派生|外部真实 imagegen 调用、实际附件/提示记录、未知 model/seed 保留未知|
|S4 事实|s4_evaluate, s4_selected, s4_targets, s4_review|事实版本独立于 policy；有效 C 支持；选定导出像素的准确分析；ABC image-first/evidence；事实冻结|实际 A/B/C 视觉复核，未配准的对应/遮挡审核|
|S4 决策/预算|s4_verify, verification_store, s4_budget|私有 policy/rule/adjudication，条件容忍、有限预算、同版本选择、Markdown run report|真实校准/认可锚点/判断依据；没有则 pending，不强行绿灯|
|S4 反馈|s4_feedback|候选/评估/目标绑定的 residual 反馈，保持原始 A+B 与目标版本|实际下一次调用与人工确认；非自动优化器|

faithful_mapping 是后加的小范围功能：仅当调用者明确知道 `strength_basis='mapping_added_labels'`，去掉映射附加强度标签，保留原诊断中的“明显/适度/温和”；重复摘录渲染一次，但全部18目标、15段文本与关系端点保留。它不判断未来结构化强度的来源、不自动改诊断。旧编译版本可逐字重现。

颜色要点：A 支持已声明 sRGB/P3/unknown 的既定受限 SDR 路径；B 仍要求已知 sRGB。遇 PNG tRNS、冲突 cHRM/cICP、坏 iCCP 不会静默当 absent。RGB16 路径单独解码，不能信 Pillow `mode=RGB` 就说保留16位。原始/原生精度诊断与**最终选定 RGB8 派生像素的评价**分开；unknown C 派生显示加 sRGB 标签不意味着源编码已验证。未知颜色可有清楚标注的假设 sRGB 探索数字，不能据此验收。

## 3. 真正可运行的路径与非自动边界

`current_chat_offline` 是文件交接：每条 CLI 命令显式执行，不会自动跑模型。当前正式的 staged commands 顺序在 `source/docs/REFERENCE_STYLE_S4.md`；schema 字段以具体源码/测试为准。不要使用早期 generic `export` 替代 measured `ab-export` / `edit-export` / `abc-export`。

实际单例路径使用过：输入归一化/审计 → 当前 A/B 真 MediaPipe 分割 + 明标粗材料注释 → AB 数值 → ChatGPT 真诊断 → 人工选择摘录/编译 → parent 真 imagegen → 原始 C 保全 → 当前 C 真分割 → image-first 视觉 → 假设颜色探索与证据诊断 → 保留观察。某些长 JSON 只以真实摘要交接，记录明确不是完整 payload 都被模型看过；不能把哈希绑定当远程证明。

第三轮比较是**2图简洁 Direct vs 4图 Full 系统包**，不是纯提示文本消融。传给执行器的完整文本留在 evidence；已结束预算不能在新环境重开当剩余额度。此次发布不授权新生成。

### Qwen / 老确定性方案

上游原生 Qwen、stage-lab 或 PhotoCraft/worker 仍保留在 source；它们不是新版 receipt/schema 的即插即用执行器。未来服务器需把实际请求/附件/提示哈希、真实 provider/model/tool 来源、原始响应与颜色元数据映射到新协议，显式版本迁移；不能把 Qwen 输出冒充 actual_current_chat/ChatGPT。`source/QWEN_ADAPTATION.md` 和 stage docs 是背景，不是 turnkey 支持声明。没有在本轮运行 Qwen/GPU/训练；同目标确定性 baseline 对比和批量稳定性也未验证。

## 4. 已知结论与容易重犯的误读

- 代码/协议门通过 ≠ 模型风格通过。摄像头 RGB 域通过 ≠ Base 域通过。支持哈希对上 ≠ 材料纯净或空间配准。
- 初始单例和后续两组新候选均保留观察，没有 training-ready 或接受标签。unknown C 色彩不能悄悄升级。
- Round1 六次诊断：D0 3次、D1 3次，同事实，reviewer1 9/9/9 vs10/10/10，reviewer2全10。表达/端点更明确，不是稳健视觉效果胜者，同家族偏差与粗量表天花板明显。
- Round2 固定原诊断、旧映射 vs faithful：清理强度标签和重复是整体映射/呈现干预；两盲评总体不确定/并列，数字有得有失，不能说清理无效，也不能只怪执行器。
- Round3 Direct 与 Full：旧自由描述的总体 tie 不证明等价。用户指出 Full 更自然、总体偏亮偏黄 Direct > Full > B；原评审已写出 Full 皮肤少黄，但没有预定权重地以灯箱差异抵消。原程序不够敏感。
- 既有假设sRGB数字：全图 b* B/Direct/Full=11.09/14.11/11.12；脸16.87/23.68/18.91；颈22.29/28.89/23.95。脸彩度22.79/31.41/25.72。全图L*65.17/70.80/69.98，但脸局部53.78/62.03/62.78反序。**黄/彩度改善存在，亮度不能逐区套同一顺序**；自然度是用户判断与视觉证据，不是某个单指标。

## 5. Codex 下一优先：评价，而非继续堆生成

**这一方案尚未实现。** 先写短计划/fixture/测试，再做独立审查；不要为流程增加不必要的通用框架或安全设施。

1. **整体先行**：同一显示条件下判断全图对 B 的影调、色温/色彩、整体亮感、光照自然度、材质关系与处理感；A 内容完整性单列。只允许“本样本可见差别”，不偷换方法统计效力。
2. **关键整区域复核**：整体结论有分歧/关键残差时检查整脸/皮肤、柜体、顶板等完整单元。比较偏黄/色相、红偏、彩度、亮度；给排序、幅度、置信度和 B 贴近程度。不是先拆成一堆局部平均数再拼“整体”。
3. **局部数值解释**：最后才用明确支持/颜色假设的分布和 signed relations 解释视觉差别。指标不能自动压过整体判断；揭示冲突而不是选择有利区域。
4. **聚合透明**：未预定权重时保留维度矩阵，不用“灯箱一票”抵消肤色；自然度和美化/纹理损失分开。不把轻微改善、未知、互有得失、不可辨别都压成 tie。
5. 用现有真实候选做评价方法的反馈知情回归可作为开发数据，不能重新包装成独立盲测。新的独立验证应留出或交换呈现并记录暴露情况；模型重复/新图实验必须另行明确预算和授权。

后续可讨论 B=A no-op 或对比参考敏感性，但**没有执行**。不提前给执行器硬上限定论、不以这些候选训练。

## 6. 可移植/公开交接约定

本目录新入口只依赖 CLI 参数/用户提供相对路径；不需要本次机器的绝对路径。source 中更早的旧 harness/worker/tests 可能保留历史绝对路径，属于未迁移旧功能；不承诺整个上游仓库可脱离模型/数据运行。

公开 evidence 是脱敏文字副本，可能与其内嵌历史 record hash 不再一致，**不能当原始回执直接 import**；只供理解实验和复现计划。原始来源 SHA 与公开副本 SHA 在 PUBLIC_REDACTIONS 中。不要用公共占位符创建假的真实运行。

私人照片、face crops、mask、模型、凭据、真实服务 ID 不在包里。公开数据说明提供文件名/哈希和私下获取步骤，不给 token/Drive IDs。不自动合并到上游主分支；先在独立子目录/新分支保留可运行源码，再在真实仓库比较祖先与 API 后决定是否整合。
