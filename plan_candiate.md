HarnessIR 多候选生成完整方案 v1.1
基于 baolinv0/HarnessIR 的 IMPLEMENTATION_PLAN.md v1.0，重点细化 Candidate Generation，不重新设计已经确定的 Judge。以下将原方案规定与建议补充的工程规则合并成可实施规格。
一、核心设计结论
多候选生成的目标不是让 Qwen 随机产生多张图，也不是简单地设置保守、中等、激进三种生成强度。

目标是：发现 C0 的实际恢复缺陷，针对不同缺陷提出有依据的替代策略，并验证这些策略能否产生更好的恢复结果。

核心流程：
#chatgpt-mermaid-_r_6n1_{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:16px;fill:rgb(237, 237, 237);}@keyframes edge-animation-frame{from{stroke-dashoffset:0;}}@keyframes dash{to{stroke-dashoffset:0;}}#chatgpt-mermaid-_r_6n1_ .edge-animation-slow{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 50s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-_r_6n1_ .edge-animation-fast{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 20s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-_r_6n1_ .error-icon{fill:rgb(48, 48, 48);}#chatgpt-mermaid-_r_6n1_ .error-text{fill:rgb(237, 237, 237);stroke:rgb(237, 237, 237);}#chatgpt-mermaid-_r_6n1_ .edge-thickness-normal{stroke-width:1px;}#chatgpt-mermaid-_r_6n1_ .edge-thickness-thick{stroke-width:3.5px;}#chatgpt-mermaid-_r_6n1_ .edge-pattern-solid{stroke-dasharray:0;}#chatgpt-mermaid-_r_6n1_ .edge-thickness-invisible{stroke-width:0;fill:none;}#chatgpt-mermaid-_r_6n1_ .edge-pattern-dashed{stroke-dasharray:3;}#chatgpt-mermaid-_r_6n1_ .edge-pattern-dotted{stroke-dasharray:2;}#chatgpt-mermaid-_r_6n1_ .marker{fill:rgb(175, 175, 175);stroke:rgb(175, 175, 175);}#chatgpt-mermaid-_r_6n1_ .marker.cross{stroke:rgb(175, 175, 175);}#chatgpt-mermaid-_r_6n1_ svg{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:16px;}#chatgpt-mermaid-_r_6n1_ p{margin:0;}#chatgpt-mermaid-_r_6n1_ .label{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";color:rgb(237, 237, 237);}#chatgpt-mermaid-_r_6n1_ .cluster-label text{fill:rgb(237, 237, 237);}#chatgpt-mermaid-_r_6n1_ .cluster-label span{color:rgb(237, 237, 237);}#chatgpt-mermaid-_r_6n1_ .cluster-label span p{background-color:transparent;}#chatgpt-mermaid-_r_6n1_ .label text,#chatgpt-mermaid-_r_6n1_ span{fill:rgb(237, 237, 237);color:rgb(237, 237, 237);}#chatgpt-mermaid-_r_6n1_ .node rect,#chatgpt-mermaid-_r_6n1_ .node circle,#chatgpt-mermaid-_r_6n1_ .node ellipse,#chatgpt-mermaid-_r_6n1_ .node polygon,#chatgpt-mermaid-_r_6n1_ .node path{fill:rgb(19, 33, 54);stroke:rgb(31, 78, 148);stroke-width:1px;}#chatgpt-mermaid-_r_6n1_ .rough-node .label text,#chatgpt-mermaid-_r_6n1_ .node .label text,#chatgpt-mermaid-_r_6n1_ .image-shape .label,#chatgpt-mermaid-_r_6n1_ .icon-shape .label{text-anchor:middle;}#chatgpt-mermaid-_r_6n1_ .node .katex path{fill:#000;stroke:#000;stroke-width:1px;}#chatgpt-mermaid-_r_6n1_ .rough-node .label,#chatgpt-mermaid-_r_6n1_ .node .label,#chatgpt-mermaid-_r_6n1_ .image-shape .label,#chatgpt-mermaid-_r_6n1_ .icon-shape .label{text-align:center;}#chatgpt-mermaid-_r_6n1_ .node.clickable{cursor:pointer;}#chatgpt-mermaid-_r_6n1_ .root .anchor path{fill:rgb(175, 175, 175)!important;stroke-width:0;stroke:rgb(175, 175, 175);}#chatgpt-mermaid-_r_6n1_ .arrowheadPath{fill:rgb(175, 175, 175);}#chatgpt-mermaid-_r_6n1_ .edgePath .path{stroke:rgb(175, 175, 175);stroke-width:1px;}#chatgpt-mermaid-_r_6n1_ .flowchart-link{stroke:rgb(175, 175, 175);fill:none;}#chatgpt-mermaid-_r_6n1_ .edgeLabel{background-color:rgb(14, 14, 14);text-align:center;}#chatgpt-mermaid-_r_6n1_ .edgeLabel p{background-color:rgb(14, 14, 14);}#chatgpt-mermaid-_r_6n1_ .edgeLabel rect{opacity:0.5;background-color:rgb(14, 14, 14);fill:rgb(14, 14, 14);}#chatgpt-mermaid-_r_6n1_ .labelBkg{background-color:rgba(14, 14, 14, 0.5);}#chatgpt-mermaid-_r_6n1_ .cluster rect{fill:rgb(48, 48, 48);stroke:rgba(255, 255, 255, 0.15);stroke-width:1px;}#chatgpt-mermaid-_r_6n1_ .cluster text{fill:rgb(237, 237, 237);}#chatgpt-mermaid-_r_6n1_ .cluster span{color:rgb(237, 237, 237);}#chatgpt-mermaid-_r_6n1_ div.mermaidTooltip{position:absolute;text-align:center;max-width:200px;padding:2px;font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:12px;background:rgb(48, 48, 48);border:1px solid rgba(255, 255, 255, 0.15);border-radius:2px;pointer-events:none;z-index:100;}#chatgpt-mermaid-_r_6n1_ .flowchartTitleText{text-anchor:middle;font-size:18px;fill:rgb(237, 237, 237);}#chatgpt-mermaid-_r_6n1_ rect.text{fill:none;stroke-width:0;}#chatgpt-mermaid-_r_6n1_ .icon-shape,#chatgpt-mermaid-_r_6n1_ .image-shape{background-color:rgb(14, 14, 14);text-align:center;}#chatgpt-mermaid-_r_6n1_ .icon-shape p,#chatgpt-mermaid-_r_6n1_ .image-shape p{background-color:rgb(14, 14, 14);padding:2px;}#chatgpt-mermaid-_r_6n1_ .icon-shape .label rect,#chatgpt-mermaid-_r_6n1_ .image-shape .label rect{opacity:0.5;background-color:rgb(14, 14, 14);fill:rgb(14, 14, 14);}#chatgpt-mermaid-_r_6n1_ .label-icon{display:inline-block;height:1em;overflow:visible;vertical-align:-0.125em;}#chatgpt-mermaid-_r_6n1_ .node .label-icon path{fill:currentColor;stroke:revert;stroke-width:revert;}#chatgpt-mermaid-_r_6n1_ .node .neo-node{stroke:rgb(31, 78, 148);}#chatgpt-mermaid-_r_6n1_ [data-look="neo"].node rect,#chatgpt-mermaid-_r_6n1_ [data-look="neo"].cluster rect,#chatgpt-mermaid-_r_6n1_ [data-look="neo"].node polygon{stroke:url(#chatgpt-mermaid-_r_6n1_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-_r_6n1_ [data-look="neo"].swimlane.cluster rect{filter:none;}#chatgpt-mermaid-_r_6n1_ [data-look="neo"].node path{stroke:url(#chatgpt-mermaid-_r_6n1_-gradient);stroke-width:1px;}#chatgpt-mermaid-_r_6n1_ [data-look="neo"].node .outer-path{filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-_r_6n1_ [data-look="neo"].node .neo-line path{stroke:rgb(31, 78, 148);filter:none;}#chatgpt-mermaid-_r_6n1_ [data-look="neo"].node circle{stroke:url(#chatgpt-mermaid-_r_6n1_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-_r_6n1_ [data-look="neo"].node circle .state-start{fill:#000000;}#chatgpt-mermaid-_r_6n1_ [data-look="neo"].icon-shape .icon{fill:url(#chatgpt-mermaid-_r_6n1_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-_r_6n1_ [data-look="neo"].icon-shape .icon-neo path{stroke:url(#chatgpt-mermaid-_r_6n1_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-_r_6n1_ .node text{font-size:14px;font-weight:600;letter-spacing:normal;fill:rgb(153, 206, 255);}#chatgpt-mermaid-_r_6n1_ .edgeLabels text{font-size:13px;font-weight:600;letter-spacing:-0.08px;fill:rgb(153, 206, 255);}#chatgpt-mermaid-_r_6n1_ .node tspan[font-weight="normal"],#chatgpt-mermaid-_r_6n1_ .edgeLabels tspan[font-weight="normal"]{font-weight:600;}#chatgpt-mermaid-_r_6n1_ .edgeLabel .label rect{opacity:1;rx:13px;ry:13px;fill:rgb(0, 14, 26);stroke:rgb(26, 62, 95);stroke-width:1px;}#chatgpt-mermaid-_r_6n1_ .node rect,#chatgpt-mermaid-_r_6n1_ .node circle,#chatgpt-mermaid-_r_6n1_ .node ellipse,#chatgpt-mermaid-_r_6n1_ .node polygon,#chatgpt-mermaid-_r_6n1_ .node path{fill:rgb(0, 40, 77);stroke:rgba(255, 255, 255, 0.1);stroke-width:1px;}#chatgpt-mermaid-_r_6n1_ .node rect{rx:16px;ry:16px;}#chatgpt-mermaid-_r_6n1_ .mermaid-decision .label-container{fill:rgb(0, 14, 26);stroke:rgb(26, 62, 95);stroke-dasharray:2,2;}#chatgpt-mermaid-_r_6n1_ .edgePaths .flowchart-link{stroke:rgb(175, 175, 175);stroke-width:1px;stroke-linecap:round;stroke-linejoin:round;}#chatgpt-mermaid-_r_6n1_ .marker{fill:rgb(175, 175, 175);stroke:rgb(175, 175, 175);}#chatgpt-mermaid-_r_6n1_ :root{--mermaid-font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";}输入低质量图像 LQHarnessIR 原始 Diagnosis +Tools + Composition冻结原始 Prompt P0生成基线 C0比较 LQ /C0：找出欠恢复、过恢复、内容错误确定关键问题及对应 ROICandidate Planner人物替代策略 F文字替代策略 TPrompt Rewriter + Audit冻结 PF / PT / PFT同一 LQ + 同一 Qwen 执行器CF / CT / CFT统一候选池Evidence + Judge





这里有五条必须遵守的原则：
1. 问题驱动，而不是强度驱动：人物蜡感需要恢复自然质感，人物假纹理需要减少生成；两者策略方向可能完全相反。
2. 候选间保持正交：CF 主要改变人物策略，CT 主要改变文字策略，CFT 组合两种修改，以便观察独立收益和相互干扰。
3. 共同任务不变：输入、模型、分辨率、色彩处理、执行参数、验收要求一致，仅候选策略和预先安排的 seed 存在差异。
4. 候选独立生成：C0 用于诊断；CF/CT/CFT 均从原始 LQ 出发，不把 C0 当作下一轮生成图像。
5. 不预设局部编辑成功：Qwen 首轮没有硬 Mask 控制，局部 Prompt 也可能改变整图；必须用实际输出验证。
二、候选的定义及数量
当人物和文字均存在值得处理的问题时，采用固定四槽位：
C0

Baseline

人物：原始策略

文字：原始策略

回答：原始 HarnessIR 恢复水平如何？


CF

Face Alternative

人物：替代策略 F

文字：原始策略

回答：人物修改有无收益及副作用？


CT

Text Alternative

人物：原始策略

文字：替代策略 T

回答：文字修改有无收益及副作用？


CFT

Joint Alternative

人物：替代策略 F

文字：替代策略 T

回答：两个方向能否兼得？




对应完整生成指令：
\[
\begin{aligned}
P_F &= \operatorname{Rewrite}(P_0,\Delta_F)\\
P_T &= \operatorname{Rewrite}(P_0,\Delta_T)\\
P_{FT} &= \operatorname{Rewrite}(P_0,\Delta_F,\Delta_T)
\end{aligned}
\]

其中 \(\Delta_F\) 和 \(\Delta_T\) 是基于 C0 缺陷确定的语义策略修改，不是直接修改像素，也不是统一的生成强度参数。

四候选是首轮的固定预算设计，不意味着所有场景都必须具备人物和文字。若没有相应问题，就按实际诊断重新分配槽位。
三、Candidate Planner：怎样决定应该生成哪些版本？
Planner 是多候选生成中最关键的新增模块。

其职责不是“生成三个不同的 Prompt”，而是完成：

观察缺陷 → 判断缺陷类型 → 确定修改方向 → 定义候选之间的差异。
3.1 Planner 输入
输入	内容	用途
LQ	原始退化图像	判断已有可见内容
C0	原版 HarnessIR 恢复结果	发现实际恢复缺陷
P0	原始 Composer 完整指令	了解已有恢复策略
Diagnosis	原始诊断结果	继承退化类型和区域问题
ToolEvidence	OCR、Face、Segmentation 等	提供区域和内容依据
EvaluationContract	任务目标、保护属性、用途政策	规定哪些修改可接受
TaskSpec	x1/x4、输出尺寸、执行参数	确保候选任务一致

特别重要的是：Planner 既看 LQ，也看 C0，还要看 P0。

原因是，仅看 C0 不能区分以下情况：
- C0 皮肤太平滑，是原 Prompt 过于保守，还是 Qwen 自身的去噪偏好？
- C0 招牌仍然模糊，是 Prompt 缺少明确恢复目标，还是原始图像根本没有足够字符信息？
- C0 出现假细节，是 Prompt 过度强调清晰度，还是模型即使使用保守指令也会补出虚构纹理？
Planner 不要求一次回答全部因果原因，但必须区分观察到的现象和尚未验证的原因假设。
3.2 第一步：建立问题清单
建议先生成结构化的 IssueRecord，而不是直接进入 Prompt Rewrite。
字段	说明	示例
issue_id	唯一 ID	F01
region_id	对应 ROI	person_01_face
problem_type	缺陷类别	waxy_skin
observation	可观察现象	面部肤质明显平滑
source_evidence	LQ/C0 对照与工具依据	face ROI、局部图像
cause_hypothesis	可能原因	原策略偏向平滑
alternative_explanation	替代解释	执行器固有生成偏好
desired_change	期望变化	恢复自然低对比肤质
preserve	保护属性	可见五官、表情、姿态、肤色
support_status	证据状态	supported / ambiguous / unavailable
expected_effect	可检验预期	蜡感降低且人物结构不恶化

其中 support_status 表示证据充分程度，不应使用 VLM 自报的 0.95 作为已校准概率。
3.3 第二步：选择真正需要干预的问题
不是 C0 所有细节都要产生替代策略。

建议按照以下顺序选问题：
01

影响可接受性的严重缺陷

如脸型改变、明显蜡感、错误字符、主要主体欠恢复、显著生成伪影。


02

有观察证据且存在可执行的替代策略

例如能明确提出减少面部过度平滑，而不是笼统要求画质更好。


03

预期策略差异有实际意义

PF 和 P0 必须代表不同的恢复决策，而非仅把 improve details 改成 enhance details。


04

改进具备可观察的验收条件

必须能判断目标区域是否改善，以及整图是否出现明显代价。



第一版最多选择两个策略轴，每个轴必须有明确目标和证据。不能因为候选预算有四个槽位，就强行编造两个修改方向。

四、人物恢复：详细策略库
人物策略应覆盖 Face、Hair、Body、Hands，而不是只优化人脸。

建议将人物问题分成四类，而不是统一映射为“增强人物细节”。
问题类别	C0 的实际表现	替代策略 F	风险与保护要求
F1 欠恢复	眼眉、嘴唇、头发等仍模糊	增强已有边界和纹理连续性	避免补出错误五官和头发
F2 过度平滑	皮肤蜡感、头发成片、衣料无纹理	减少过度平滑，恢复自然微纹理	避免人工毛孔、过强纹理
F3 过度生成	假毛孔、假皱纹、边缘光晕	减少伪高频，降低不可靠细节生成	避免重新过度模糊
F4 结构错误	五官不对称、手指异常、姿态改变	优先遵循原始可见结构	不引入身份和表情变化

4.1 F1：人物欠恢复
假设原始图像中眉毛、眼睛、头发存在一些可见结构，但 C0 仍然很模糊。

替代要求：
Target:
Improve the reconstruction of visible facial and hair structures.

Strategy:
Recover continuity of existing eyebrow, eye and lip boundaries.
Restore plausible fine texture only where supported by visible cues.
Maintain the original facial geometry and expression.

Avoid:
Inventing new facial features or changing the apparent identity.


预期效果：已有边界更加连续、细节更加清楚，但人物结构不应明显改变。
4.2 F2：皮肤蜡感
C0 可能消除了噪声，却同时抹除了自然皮肤的微小亮度变化。

替代要求：
Target:
Reduce the waxy and plastic appearance of the skin.

Strategy:
Restore subtle, irregular and low-contrast skin texture.
Maintain smooth large-scale skin tone and shading.
Avoid excessive smoothing without creating dense artificial pores.

Preserve:
Visible facial geometry, expression and natural skin color.


这里的重要区别是：自然肤质不等于尽可能多的高频纹理。

人物专家需要判断纹理是否自然，而不是简单偏好更大的高频能量。
4.3 F3：过度锐化和假纹理
如果 C0 已经出现假毛孔、过强皱纹和边缘光晕，替代策略应该反向处理：
Target:
Reduce artificial facial high-frequency details.

Strategy:
Soften unsupported pore-like patterns and oversharpening halos.
Keep genuine visible facial boundaries recognizable.
Maintain natural transitions between skin, hair and background.


这个候选可能在某些锐度指标上低于 C0，却具备更好的视觉质量。
4.4 F4：五官、手部和姿态异常
这一类不应该仅靠“生成更真实的人物”处理。

优先提出：
Target:
Correct visible structural inconsistencies in the restored person.

Strategy:
Follow the facial and body structures supported by the source image.
Keep the apparent expression, pose, silhouette and limb configuration.
Do not introduce unsupported fingers, facial landmarks or accessories.


如果原始 LQ 已经严重退化，无法确认身份或手指数量，Planner 必须记录 unverifiable，不能以“看起来合理”冒充与真实人物一致。
4.5 多人物场景
假设画面中有三个人：
人物	C0 问题	处理
Person 1：前景主体	肤质过平滑	重点修改
Person 2：侧面人物	恢复基本正常	保留原策略
Person 3：远景人物	严重模糊，身份无法确认	不强行生成人脸细节

CF 可以针对 Person 1 提出区域语义指令，但需要同时检查 Person 2、Person 3 是否受到影响。

如果多个重要人物需要相反的恢复策略，且模型无法可靠区分目标区域，Planner 应标记 spatial_control_risk，而不是继续叠加大量互相冲突的局部指令。

五、文字恢复：详细策略库
文字恢复要将两个目标分开：
- Visual Restoration：恢复笔画边缘、间距、对比度和可读性。
- Content Fidelity：是否保留原有的字符、数字和符号。
前者改善不代表后者正确。
5.1 首先确定原始文字信息等级
LQ 文字区域 → 原始信息可确认性判断

T1 可确认

笔画和字符有足够依据

加强笔画恢复


T2 部分确认

部分字符可信，部分不确定

局部恢复，未知不补词


T3 不可确认

无法从 LQ 确认字符

不主动生成确定文字




5.2 四类文字缺陷及策略
缺陷	CT 的策略变化
字符存在但笔画粘连	增加笔画分离、边缘恢复和间距恢复
已有笔画断裂	优先恢复有视觉证据支持的笔画连续性
C0 生成清晰错字	减少依赖语言先验的字符生成，回到 LQ 可见笔画
原始文字完全不可辨认	仅改善区域视觉结构和可见性，不要求生成完整单词

5.3 示例：文字可确认，但 C0 欠恢复
Target:
Improve the legibility of the existing shop sign.

Strategy:
Restore visible character boundaries and separated strokes.
Improve contrast between characters and the sign background.
Preserve the original character shapes, arrangement and spacing.

Do not:
Insert additional characters or replace the original text
with a plausible word based only on surrounding context.


5.4 示例：C0 产生了清晰错字
Target:
Remove unsupported reconstructed text details.

Strategy:
Prioritize visible stroke evidence from the source image.
Reduce invented character structures inconsistent with the source.
Preserve confirmed characters and text layout.

Do not:
Treat OCR recognition of the generated output as ground truth.


5.5 文字很模糊时怎么办？
如果 LQ 中某个招牌完全无法辨认，CT 不应该强行要求生成可读文字。

可以要求改善招牌轮廓、局部对比和已有可见痕迹；但不能把模型补出的词语当作真实内容。

这并不意味着严格禁止所有未知细节：日常摄影用途可以允许合理的视觉性补全，但要记录其真实性不可验证。涉及证件、号码、关键文字时，应采用更严格的内容政策。

六、Prompt Rewriter：如何保证真正只改变指定策略？
我建议采用结构化需求 → 定向替换 → 完整 Prompt 编译 → 独立审计，而不是让模型自由重新编写四份 Prompt。
6.1 将原始 P0 解析为可审计的需求集合
P0 原始完整 Prompt

G：任务、退化恢复、全局颜色与几何

F0：人物相关要求

T0：文字相关要求

O：其他区域恢复要求

R：全局保护要求

按允许修改的作用域替换

PF = G + F1 + T0 + O + R

F0 → F1


PT = G + F0 + T1 + O + R

T0 → T1



PFT = G + F1 + T1 + O + R

两个修改方向组合，但不重新定义全局任务


上面的 G/F/T/O/R 是推荐的中间表示，不要求原始 Composer 已经天然具备这些字段。

如果原始 P0 是连续自然语言，可先做一次需求解析。解析失败或存在明显歧义时，不得以解析结果取代原文；应保留原始 P0，重新审查允许修改的句子。
6.2 哪些内容允许变化？
Prompt 组成	CF	CT	CFT
任务目标	不变	不变	不变
输出尺寸和 scale	不变	不变	不变
人物恢复策略	修改	不变	修改
文字恢复策略	不变	修改	修改
建筑、草地等其他要求	不变	不变	不变
内容与几何保护要求	保留	保留	保留
全局色彩、亮度要求	不变	不变	不变

这里允许在目标作用域内修正与恢复目标矛盾的旧约束。例如原 P0 的“绝不重建任何皮肤细节”可能需要调整，但不能因此取消可见五官、表情的保护要求。
6.3 Rewriter 输出必须包含什么？
建议一次调用生成三份完整 Prompt，输出：
{
  "strategy_id": "face_alt",
  "base_prompt_id": "P0",
  "issue_refs": ["F01"],
  "changed_requirements": [
    {
      "scope": "person_01_face.texture",
      "old": "avoid recovering facial microtexture",
      "new": "recover subtle natural texture without artificial pores"
    }
  ],
  "retained_requirements": [
    "task",
    "scale",
    "geometry",
    "text_content",
    "global_color",
    "background_structure"
  ],
  "expected_effect": [
    "reduced waxy appearance",
    "no major facial structural change"
  ],
  "full_prompt": "..."
}


真实实现应将完整 Prompt 写入文件，记录文本哈希、需求差异及引用证据。以上只是接口示例，不代表仓库已实现。
6.4 独立语义审计
Rewriter 完成后，需要独立检查：
1. PF 是否只改变了允许的人物恢复要求。
2. PT 是否只改变了允许的文字恢复要求。
3. PFT 是否同时保留 F 和 T 两种预先确定的策略。
4. 是否遗漏任务目标、尺寸、关键保护要求。
5. 是否把 OCR 猜测误写为真实字符。
6. 是否引入互相矛盾的要求。
允许最多一次语义修复。仍无法通过的槽位按冻结的规则转为 baseline resample，并显式记录 plan_fallback；不应把失败的策略改写伪装为正常执行。

注意：审计通过仅说明 Prompt 符合规划，不代表 Qwen 会准确执行。
七、候选槽位如何自适应分配？
CF/CT 只是典型混合场景的命名。真实恢复场景并不总有一张人脸和一个招牌。

建议将候选规划抽象成两个问题轴 A/B，再根据场景决定是否使用人物和文字策略。
场景	C0	候选 1	候选 2	候选 3
人物 + 文字	原版	人物替代	文字替代	人物+文字
只有人物，存在两个不同策略方向	原版	人物策略 A	人物策略 B	原版追加采样
只有文字，存在两个不同策略方向	原版	文字策略 A	文字策略 B	原版追加采样
建筑 + 草地	原版	建筑替代	草地替代	两者联合
仅一个有依据的修改方向	原版	修改方向 A	原版追加采样	原版追加采样
没有明确问题	原版	P0 追加采样	P0 追加采样	P0 追加采样

注意：如果只有一个问题，不能自动构造“弱修复”和“强修复”。必须能解释两种策略为何在恢复机制上不同。否则采用原版追加采样更加合理。
多个相同类型目标怎么办？
例如画面中有三个人、两块招牌。

这不是五个独立候选轴，而是一个人物策略轴和一个文字策略轴。每个轴包含多个需要关注的 ROI。

建议：
- 主 ROI 默认最多 6 个，人物 3 个、文字 3 个。
- ROI 超限时，拆评审包或标记 coverage_incomplete，不能静默忽略重要实例。
- 各人物可能需要不同处理方向，Planner 必须记录作用域和潜在冲突。
- 记录图片中哪些重要实例被策略覆盖，哪些没有覆盖。
候选预算仍是四次，但其语义覆盖必须完整。

八、候选生成执行：实际怎样调用 Qwen？
8.1 固定模型执行条件
根据原方案，第一轮固定已有 Qwen 执行器：
项目	要求
执行器	现有 qwen21 profile
输入图像	同一规范化 LQ
推理参数	相同模型、权重、steps、CFG、dtype 等
输入条件	对应完整 Prompt
空间接口	full_frame
PE 改写	第一轮关闭
颜色额外调整	关闭
图像后处理	所有候选使用相同流程
随机性	明确记录预设 seed
生成链路	各候选独立从 LQ 生成

候选生成应该通过 engine/src/hre/v3/dispatch.py 已有的请求绑定能力连接执行器。文档建议 bridge 使用 seal_condition 与 generate，而非重走会给指令追加通用约束的 render_instruction。

必须验证生成器实际收到的 Prompt 与冻结的完整 Prompt 一致，包括共同的几何 wrapper。不要只比较 Planner 保存的文本，因为执行桥接有可能再次修改它。
8.2 x1 与 x4 的几何规则
这是容易被忽视但会影响全部实验有效性的部分。

设原始 LQ 大小为 \(W\times H\)。
模式	输入 padding	模型输出 canvas	最终交付
restoration x1	W/H 向上补齐至 32 倍数	padded W × padded H	W × H
SR x4	W/H 向上补齐至 8 倍数	4 × padded W/H	4W × 4H

padding 放在右侧和底部，记录精确范围，并按对应比例裁回。不能通过任意 resize 把错误尺寸的生成结果伪装成有效 x4 输出。

输入给 Composer 的仍然是未 padding 的 LQ；padding 只在执行桥接层发生。
8.3 生成任务的结构
建议每个候选都保存完全独立的执行记录：
{
  "candidate_id": "face_alt_s1_seed101",
  "strategy_id": "face_alt",
  "source_id": "case001",
  "source_sha256": "<original-LQ-hash>",
  "prompt_path": "plan/prompts/PF.txt",
  "prompt_sha256": "<frozen-prompt-hash>",
  "seed": 101,
  "executor_profile": "qwen21",
  "spatial_mode": "full_frame",
  "task_mode": "sr_x4",
  "scale": 4,
  "status": "pending"
}


每次执行后追加实际模型、请求哈希、原生输出尺寸、原生图像 Hash、交付图像 Hash、耗时、失败原因和回执。

这里的 101 是说明性 seed，不是必须采用的全局固定值。
8.4 实际调度顺序
1. 准备 C0
   
   执行原始 HarnessIR，归档 P0、C0 和原诊断证据。
2. 冻结候选计划
   
   得到 F/T 策略，完成 PF/PT/PFT 编译与审计，写入 plan.json。
3. 运行 CF
   
   Qwen 输入原始 LQ + PF，保存原生及交付图像。
4. 运行 CT
   
   Qwen 输入同一 LQ + PT，保存原生及交付图像。
5. 运行 CFT
   
   Qwen 输入同一 LQ + PFT。不能把 CF/CT 结果作为输入。
6. 完成候选池
   
   验证输出、记录缺失及重复情况，建立统一证据包，再移交 Judge。

默认单 GPU 串行运行，避免重复加载模型和 GPU 内存竞争。多 GPU 可以将已冻结的独立请求分发给不同 worker，但不允许 worker 自行重新规划策略。

九、失败和异常如何处理？
一个可交付的生成方案需要定义失败语义，而不是只描述正常流程。
情况	处理规则
C0 生成失败	标记 baseline_failed，不进行依赖 C0 的策略规划
Planner 找不到有依据的替代方向	使用预定的 P0 追加采样
PF/PT 无法通过语义审计	最多修复一次，仍失败则记录 fallback
生成请求明确失败	保存失败及原因，按预定重试政策处理
请求已提交但无回执	标记 unknown，先对账，不能自动重发
原生尺寸错误	contract_fail，不能 resize 后当作成功
两个候选图像完全相同	保留两次调用记录，报告重复
候选出现背景变化	保留结果，交给全图评审判断；不能假设局部保持成功
所有候选都有明显问题	不继续隐式生成新候选，交由 Judge 返回不合格或 unresolved

对重复图像，建议使用交付图像像素 Hash 做精确重复检测。不建议第一轮通过近似相似度自动去重，因为看似很小的变化可能刚好位于文字或表情上。
失败归因
每次候选生成后，都应该能区分四种失败：
失败环节	例子	后续研究方向
Diagnosis	没发现人物蜡感	改善缺陷识别
Planning	识别蜡感却选择更强锐化	改善策略映射
Rewriting	PF 遗漏文字保护要求	改善 Prompt 编译
Execution	PF 合理，但 Qwen 仍然产生蜡感	研究执行器可控性

这比仅记录“候选没变好”更有科研价值。

十、完整单图案例：人物、招牌、建筑、草地
假设输入一张夜景，存在人物、店铺招牌、建筑和草地。
10.1 C0 的观察结果
区域	C0 观察	问题等级
人脸	皮肤蜡感，面部自然纹理损失	关键问题
招牌	可确认字符的笔画仍然粘连	关键问题
建筑	主要边缘和结构基本合理	需保护
草地	已有一定恢复，局部仍模糊	次要问题

Planner 得到：
- F = 减少面部过度平滑，恢复自然纹理。
- T = 恢复可确认的笔画结构，减少粘连。
- 共同约束 = 保持场景几何、自然颜色和建筑布局，不引入无依据内容。
10.2 四个候选怎样产生？
C0	原始 P0，所有区域执行初始恢复策略。
CF	P0 中只替换人物恢复要求：减少蜡感、恢复自然肤质。文字和其他要求保持原策略。
CT	P0 中只替换文字恢复要求：分离可确认笔画、改善边界连续性。人物和其他要求保持原策略。
CFT	在 P0 中同时采用已冻结的 F/T 替代要求，完整重新生成一张图。


10.3 预期与可能的实际结果
版本	预期	可能失败
C0	原始基线	人物蜡感、文字粘连
CF	人物改善	文字不变，或非目标区域受干扰
CT	文字改善	人物仍蜡感，或文字生成错字
CFT	人物和文字均改善	两种指令互相干扰，导致局部或整图退化


CF + CT 的单独收益，并不保证 CFT 也能同时取得收益。

因为 Qwen 是条件整图生成模型，文字指令和人物指令可能竞争模型容量、注意力或生成倾向。CFT 必须作为独立的联合策略结果进行实测，而不是假设两种收益可以线性相加。

十一、如何验证候选生成策略真的有效？
这里建议将验证分成两层。不要把候选覆盖率实验与 Prompt 因果验证混在一起。
实验 1：策略候选是否比随机采样更有效？
比较相同四次图像生成预算：
Seed	Baseline A	Proposed B
s0	P0 → C0	P0 → C0
s1	P0 → C1	PF → CF
s2	P0 → C2	PT → CT
s3	P0 → C3	PFT → CFT

两组共享一次 C0，因此每张图共需七次实际生成。

这里回答的是：相同四张候选预算下，哪种方法更容易产生至少一张合格恢复图？

主要看 Oracle Pass@4，以及独立评审认定优于 C0 的候选覆盖率。

这是系统收益实验，但不能单靠它推断每个 Prompt 的因果效果，因为 P0、PF、PT、PFT 对应不同 seed。
实验 2：策略本身是否真正改变恢复结果？
针对少量有代表性的图像，补充固定 seed 的因子对照：
四种策略 × 两个 seed
	Seed A	Seed B
P0	P0-A	P0-B
PF	PF-A	PF-B
PT	PT-A	PT-B
PFT	PFT-A	PFT-B

同一 seed 下比较不同策略，再比较策略收益是否随 seed 改变。

建议重点测三个问题：
- Target Response：PF 是否改善目标人物？PT 是否改善目标文字？
- Off-target Damage：CF 是否损害招牌、建筑和草地？CT 是否损害人物和背景？
- Joint Compatibility：PFT 是否能同时保留 F/T 的改善，还是发生相互干扰？
在含 GT 的合成退化实验中，可以使用相同 ROI 的 PSNR、LPIPS、结构和人工内容验证；在无 GT 的真实图像中，只能分别评价视觉自然性、明确内容冲突和未确认真实性。

不建议把 PSNR 或锐度增加直接当作策略成功。
最小研究指标
指标	说明
Target Improvement Rate	目标区域相对原版出现有效改善的样本比例
Off-target Regression Rate	非目标重要区域出现明显退化的比例
Joint Success Rate	F/T 两方向同时改善且无重大内容错误的比例
Oracle Pass@4	四候选中至少一张合格的比例
Diversity Collapse Rate	多个策略产生相同或几乎无可区分效果的比例，需注明判定方法

这些指标建议同时按人物、文字和混合场景分层，而不是只汇总一个总分。

十二、工程结构和模块职责
保持现有 HarnessIR，新增独立模块：
engine/src/hre/candidates/
├── contracts.py    # TaskSpec / CandidatePlan / CandidateSpec
├── bridge.py       # HarnessIR + Qwen 执行接口
├── planner.py      # 缺陷分析、策略选择、Prompt Rewrite
├── evidence.py     # ROI / Code 证据 / 候选图像绑定
├── runtime.py      # 状态、冻结、seed、预算、异常恢复
├── judge.py        # 既定 Judge 方案
├── report.py       # 候选对照、问题归因、实验结果
└── cli.py          # 独立运行入口


这里最重要的是 planner.py 和 bridge.py 的边界：

Planner 只决定“生成什么”，Bridge 只负责“如何准确执行”。

不应让 Planner 直接访问 Qwen 私有执行器内部逻辑，也不应让 Bridge 自行修改生成指令。

建议 plan_candidates() 返回不可变的候选计划，execute_candidate() 只接受已冻结的候选规格。
12.1 推荐执行伪代码
def generate_candidate_pool(task, config):    # 1. 冻结输入和执行条件    freeze_task(task, config)    # 2. 复用原 HarnessIR    diagnosis = run_original_diagnosis(task.source)    tools = run_original_tools(diagnosis)    p0 = run_original_composition(diagnosis, tools)    # 3. 基线    c0 = execute(        source=task.source,        prompt=p0,        seed=task.seeds[0],    )    if not c0.contract_valid:        return baseline_failed(c0)    # 4. C0 反馈规划    plan = plan_candidates(        source=task.source,        baseline=c0,        original_prompt=p0,        diagnosis=diagnosis,        tool_evidence=tools,        evaluation_contract=task.evaluation_contract,    )    # 5. 一次性改写 + 审计 + 冻结    specs = rewrite_and_audit(plan, p0)    freeze_plan(specs)    # 6. 独立生成；每个 source 始终为原始 LQ    results = [c0]    for spec in specs:



以上是推荐的逻辑接口示意，不是当前仓库已经具备的业务实现。实际工程必须增加请求回执、超时处理、unknown 对账、幂等恢复与预算控制。
12.2 最小输出文件
每张图建议归档：
case001/
├── case.json
├── freeze.json
├── baseline/
│   ├── diagnosis.json
│   ├── tool_evidence.json
│   ├── P0.txt
│   └── C0.png
├── plan/
│   ├── issues.json
│   ├── roi_registry.json
│   ├── candidate_plan.json
│   ├── audit.json
│   └── prompts/
│       ├── PF.txt
│       ├── PT.txt
│       └── PFT.txt
├── candidates/
│   ├── face_alt/
│   ├── text_alt/
│   └── joint_alt/
├── evidence/
│   ├── measurements.json
│   └── roi_comparison/
├── judge/
├── selection.json
└── report.md


每个候选目录都包含 request.json、receipt.json、native.png 和 delivered.png（成功时），以及模型配置、输出 Hash 和失败记录。

不要仅保存最终获胜图像。后续研究最有价值的证据往往来自失败候选。

十三、工程实施顺序与验收
阶段	主要任务	完成标准
P0 基线核对	确认 d44d40f 或最新实际基线，检查服务器环境	不覆盖既有 HarnessIR 工作
P1 基线执行	完整 P0 直通 Qwen，生成并归档 C0	输出图像、Prompt 和请求 Hash 全部可追溯
P2 Planner	C0 对照诊断、IssueRecord、策略轴分配	可解释为何生成 CF/CT
P3 Rewrite	PF/PT/PFT 完整编译和语义审计	差异只涉及允许修改的要求
P4 生成引擎	四候选调度、几何、seed、执行回执	相同 LQ，符合 x1/x4 契约
P5 可视化	四候选整图/ROI、Prompt diff、目标和非目标变化	每张图可人工快速检查
P6 Pilot	10 图；原版四采样与策略四候选对照	发现失败、验证策略是否具有实际作用
P7 Held-out	冻结方案后运行 24 图	得到独立效果、内容错误和成本结论

必须执行的单元测试
尤其要覆盖：
- 相同输入、相同模型与参数；仅策略和预设 seed 变化。
- PF 的修改不丢失 P0 的文字要求，PT 不丢失人物要求。
- PFT 与两项替代策略一致，不会出现互相矛盾的指令。
- 不将 C0 作为后续候选的生成输入。
- 无人物、无文字、OCR 不可用、ROI 超限和策略规划失败。
- 严格 x4 尺寸检查；错误原生尺寸不被 resize 掩盖。
- 所有候选都有完整 Prompt Hash、图像 Hash、执行状态和实际开销。
- GT、人工真值和离线指标无法进入在线 Planner。
- 异常恢复不重复发起已完成或状态未知的生成请求。

十四、我建议额外加强的两个点
这部分是对原 v1.0 的建议补充，不是已经验证的实现效果。
14.1 将“策略是否实际生效”单独记录
当前设计很容易出现一种情况：PF、PT、PFT 的 Prompt 确实不同，但生成出来的图像几乎相同。

建议在报告中显式记录：
策略	Prompt 差异	目标区域变化	非目标区域变化	结论
PF	已确认	有 / 无	有 / 无	是否响应策略
PT	已确认	有 / 无	有 / 无	是否响应策略
PFT	已确认	有 / 无	有 / 无	是否组合成功

如果连续多张图出现 Prompt 不同、目标区域却没有方向性响应，就应优先研究 Qwen 的可控性，而不是继续人工优化大量 Prompt 模板。
14.2 不要让 Planner 变成新一轮自由 Prompt 搜索器
第一版 Planner 只应该在明确的缺陷类别中，选择有限、有依据的替代恢复方向。

例如：人物蜡感 → 减少平滑、恢复自然微纹理；假毛孔 → 减少无依据的伪高频。

不允许 Planner 在同一个 case 中先尝试 PF-A，观察结果后再生成 PF-B、PF-C，直到挑出满意的结果。那会改变实验预算，并且无法区分策略设计能力与大量试错收益。

后续如果研究自适应多轮搜索，应单独定义新实验和成本预算。

十五、最终判断
这套候选生成方案在工程上已经可以拆分任务实施。真正需要验证的核心不在于“四个版本是否足够多”，而在于：

基于 C0 缺陷的策略规划，能否让同一个 Qwen 执行器更稳定地产生不同且有价值的恢复结果？

我建议将首轮结果明确分成三类：
实验结果	应得出的研究结论
CF/CT 明显改善目标，且整体没有严重退化	候选策略具有实际价值，继续验证覆盖率和 Judge
目标改善，但非目标区域显著退化	主要瓶颈可能是缺乏可靠的局部空间控制
Prompt 已明显改变，结果却没有方向性改善	主要瓶颈可能是执行器对恢复策略的响应能力

这三种情况对应完全不同的下一步研究路线。

第一阶段不要引入局部融合、额外生成模型或更复杂的 Agent 反馈循环。 先把候选规划、完整 Prompt 编译、独立生成、可视化及固定 seed 对照跑通，才能明确这些新增能力是否真的必要。

方案来源：HarnessIR 多候选恢复与专家 Judge 工程实施方案 v1.0。上述 v1.1 是细化建议，尚未提交 GitHub，也没有真实模型运行结果。
