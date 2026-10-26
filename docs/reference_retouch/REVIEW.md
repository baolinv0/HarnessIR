# Reference Retouch 工程审查

日期：2026-10-26。审查基线：`7ecc32cebd54503f2924f9062a5a1c708f37deba`；发布分支：`codex/reference-retouch-contract-20261026`。

结论：**PASS**。初审发现的三项 P2 均已通过独立复现脚本复核关闭；本次修复及相关兼容范围内未发现新的 P1/P2 阻断。

| 初审问题 | 修复复核结果 |
|---|---|
| 工作台 compose 可绕过不足诊断、丢失差异来源，或误报 already_satisfied | 新案例逐目标绑定 delta ID、A/B 事实、区域、可比性与证据；不足诊断进入编辑被拒绝，误报已满足被拒绝；拒绝导入前后 state 文件字节及预算不变。 |
| 工作台任意一项伪影 pass 可以替代全部必需检查 | 新案例精确要求 naturalness、reference_content_leakage、unsupported_detail；任意项、遗漏与重复项均拒绝，并检查角色证据；拒绝导入不改变等待验证状态。 |
| v3 already_satisfied 绕过冻结交付尺寸 | 源图 32×32、最小原生尺寸 64×64 的原样交付得到 success=false、delivery_requirements_not_met，并保存独立交付 assessment；编译与图像生成次数均为 0。 |

聚焦验证命令：

```powershell
$env:PYTHONPATH='engine/src'
& .venv/Scripts/python.exe -m pytest engine/tests/test_retouch_delivery.py engine/tests/test_v3_reference_runner.py engine/tests/test_v3_reference_contract.py -q
```

结果：**95 passed in 14.60s**。同时检查了旧 v3 模板身份、旧 intent validator 拒绝新版本 schema、新旧 shared planning 版本隔离、历史工作台合同继续运行和只读查看不改写案例。未重复执行完整测试套件。

本次审查与合成 fixture 仅验证工程约束、拒绝路径和兼容行为；没有调用真实图像生成或模型 API，也不证明参考迁移质量、模型身份、四模型效果、跨场景泛化或高频细节真实性。真实案例观察及其限制另见 [CASE_EXPERIMENT.md](CASE_EXPERIMENT.md)。
