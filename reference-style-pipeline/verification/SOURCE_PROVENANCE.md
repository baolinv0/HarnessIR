# 源码来源、独立验证与发布差异

- 起点 `code-build-entry-001.tar.gz` 的完整 SHA256：`926157717c684e1e3d4fc4618d3b2d22423ad7106f81f6a2f7349f9f0f17e02e`；原成员 `workspace/shared/retouch_rgb_runtime/p3_material_controller_v6/source`。独立复制开发，从未拿未知 remote main 替代。
- 最新真实单例归档恢复基线：`ReferenceStyle_CameraRGB_A01_EndToEnd_20261101.tar.gz`，1,599,516 bytes，SHA256 `5b4600606219874b254e728653340958856fdc95f54ad62e958fe943e7bdde4c`。其中源码362文件的manifest SHA256 `47ee6a2fb67d8fca764ef1ff9bfbf795841c25944225d657157f86da7a6aed60`。
- 后加 faithful mapping 的冻结源码364文件，原manifest SHA256 `15936f3e0300b6b61578242c93f8f03b105382f227bad8f9095fbab22ac3278e`，完整原清单在source_manifest_original.json。
- 本交接再次核验364原文件；仅 `IMPLEMENTATION_REPORT.md` 与旧 `camera0717-pilot-inputs.json` 删除私有服务标识/机器路径。无运行代码变化；source_manifest_public.json 给公开树准确哈希，PUBLIC_REDACTIONS记录原件/公开副本差异。不要要求公开脱敏记录通过旧私有回执hash验证。
- 上游MIT许可及公开学术作者署名完整保留；标准ICC profile不是照片，保留用于正确颜色读取。

作者在本交接的独立新目录执行：
`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=engine/src python3 -m unittest discover -s engine/tests/reference_style -v`
（cwd=source）175 tests / 38.443s / OK，日志 handoff_reference_style_tests.log。
独立交接 reviewer 另跑同 scoped suite，175 / 37.353s / OK，CLI `hre reference-style --help`通过。具体review结论单独归档，不冒充整个上游pytest或真实风格效果通过。

其他历史证据：faithful mapping独立8项+语义14项及各175回归PASS；camera域、初始实际S0/S1/S2/C算术报告见evidence与verification。它们各自有清楚范围，不合并成一个“所有功能验证”标签。

旧源中其他harness/worker测试可能需要固定历史文件路径、模型或环境变量；没有迁移或全面验证。本新入口可从任意checkout路径按CLI传入自己的数据；建议作为独立子目录集成，不覆盖现有HarnessIR根。代码的Git祖先尚未在交接作者侧判定，不能称与remote main可直接无冲突覆盖。
