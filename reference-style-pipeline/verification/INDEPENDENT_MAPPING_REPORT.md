# 固定诊断映射模块：独立功能核验

## 结论
**PASS：8项独立针对性测试、175项参考风格模块回归均通过。** 实际历史诊断配对文本通过独立重建检查。未调用图像模型、未生成新图、未验证是否减少过冲。

## 验证范围
冻结源码：reference_style_faithful_mapping_20261101/source，364个文件与清单逐一一致。
源码清单 SHA256：15936f3e0300b6b61578242c93f8f03b105382f227bad8f9095fbab22ac3278e。

独立计划和测试在读取本次新实现前准备。先按拟定API在旧源码运行，出现预期缺少faithful_mapping的6项错误，旧强度路径1项通过。契约随后显式增加strength_basis后，测试按其公开规格调整为8项；不是根据失败放宽断言。新实现8/8通过。

1. 映射结果深拷贝，只将已声明为mapping-added的补充strength置null，其他目标内容不变。
2. 诊断原句中的substantially/moderately/gentle等实际强度表达保持原样；新模式不渲染strength=标签，也不渲染None/null标签。
3. 同一句多个目标只显示一次，所有ID、维度和方向仍可见；不同原句不会被合并。
4. 七个完整区域、关系端点和A保真要求保留。
5. 编译→编辑导出→两种ABC视图均保留原目标含义，ABC仍逐目标评价。
6. 旧版全非null强度保持旧版本及输出；混合模式不悄悄运行。
7. strength_basis必须明确为mapping_added_labels；未知/structured_diagnosis来源不被静默删除。此模式不是通用诊断强度解析器。

## 实际固定诊断配对
- 诊断Markdown原字节未变，SHA df1bff1910bdae9fca2620ab3eb7b03a66b58661e87ea8ebb8fcd89538131619。
- 生产纯渲染器重建基线6696字节，与历史精确提示逐字一致：c82adf7f5b510c8ccb25b7e70abbe262fa991ab2906d368c42781633693cfa4a。
- 处理后预览6238字节：e728f79723f4542a16ca8515529c8f978bfcca7a089be1e0336f50426a2f7b74。
- 18条目标记录对应15句不同诊断原文。每句处理后出现一次，各原有目标ID/subject/dimension/direction及关系有向端点完整保留。
- 两种ABC投影相对旧版本仅补充strength字段变null，原句、区域和关系不变。
- 实际对照是离线生产渲染预览，未建立新执行请求/回执；历史四张提交附件尚未全部恢复，不能声称重放原图像执行。

## 证据与边界
本目录保存TEST_PLAN.md、test_mapping_fidelity.py、baseline.log、amended.log、check_actual_pair.py、actual_pair.log、actual_pair_verified.json、regression.log。回归实际耗时36.132秒；未运行整个旧项目pytest套件。

这是删除补充强度标签与去重的**联合映射干预**。强度标签删除不等于删除诊断原文本来具有的强度。当前PASS只证明该变换忠实且程序路径可用，不证明两个因素各自的因果贡献，不证明执行器一定遵循目标，更不证明B风格匹配或训练标签合格。

## Actual two-image screening follow-up — 2026-11-01

Report ID: `mapping-screening-r1-independent-numeric-check`.
Evidence root: `${SHARED_ROOT}/reference_style_mapping_20261101/screening_r1`.
Independent checker: `check_screening.py`; machine result: `screening_check.json` in this report's directory.

**PASS arithmetic and associations, not efficacy.** Independently recalculated assumed-sRGB transfer, XYZ/Lab, luminance/chroma, all 40 regional distributions (7 statistics each) and all 287 comparisons/relations per output without calling author's calculation helpers. Absolute agreement within 1e-10. Original A/B measurement fields preserved except explicitly downgraded eligibility. Own-native category masks match category IDs exactly; material masks exclude classified foreground. Raw hashes, support hashes and source receipts agree. Both arms used identical ordered four input attachments, verified from actual preserved files and call ledger; actual tool argument reporting remains caller attestation.

- `result_58` = baseline, raw 1087×1446, metric report SHA256 `a83b20488ab472c17d5bc23b831d8a30e09783c5b1ea00da0963977fec4a542a`.
- `result_23` = faithful mapping, raw 1087×1447, metric report SHA256 `4cc87e96849218cbd01683e6f27c1d6499087606693d0b1dc6f904e4915ead18`.
- Both raw files match generated originals; baseline/treatment prompt hashes remain c82adf7f… / e728f797… respectively. Reference B is 2316×3088. No resizing/alignment is used by the numeric procedure.

Both frozen visual reviews concluded tie/uncertain, not equivalence. Exploratory numbers also show tradeoffs, not uniform improvement: whole-face median L* B=53.784, baseline=59.910, faithful=60.156; neck B=51.584, baseline=58.324, faithful=62.471; ceiling median chroma B=22.213, baseline=27.206, faithful=23.654. These are per-mask distributions, not pixelwise errors or calibrated style scores.

Important limitations: C metadata has no color declaration, so assumed sRGB is explicitly unverified and formal numeric eligibility remains blocked. Fresh C masks vary with image content; A/B/C are unregistered and differ in pose, scene coverage and resolution. Coarse class masks include mixed semantic materials. Manual material support annotator knew condition; a glasses-hole contamination correction was applied symmetrically before statistics, with draft retained. This history is transparent, not blinded or ground-truth localization. One case and one stochastic generation per arm cannot establish effect size, equivalence, efficacy, or batch/training-label suitability. The combined mapping intervention cannot distinguish strength-label from duplicate-instruction effects. No further generation or code regression was run by this reviewer in this follow-up.
