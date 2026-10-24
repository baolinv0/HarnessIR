# 软件交付验证记录

## 执行结果

基线：`bffdb5243ac38e21b4498cde2205926256506362`。本次实现的定向检查在 CPU 环境执行，没有安装/加载正式图像权重，没有向模型 endpoint 发送真实请求。

```bash
PYTHONPATH=engine/src /tmp/hre-v3-check/bin/python -m pytest -q \
  engine/tests/test_hre_v3_delivery.py \
  engine/tests/test_hre_v3_runner.py \
  engine/tests/test_hre_v3_qwen_firered.py \
  engine/tests/test_hre_v3_runtime_boundaries.py \
  engine/tests/test_v3_flux_fibo.py \
  engine/tests/test_hre_cli.py
```

实际结果：**102 passed in 33.01s**。

临时解释器路径仅记录本次检查环境；服务器可使用自己已安装 `engine[test]` 的解释器运行相同文件列表。

另完成 `python -m compileall -q engine/src/hre/v3` 和 `git diff --check`。旧 CLI 的定向回归包含创建、导入、watch、预算、外部结果和恢复路径；没有宣称运行了整个仓库的全部历史测试。

## 检查覆盖

| 范围 | 检查的实际合同 |
|---|---|
| Qwen / FireRed | pipeline 类、权重身份、参数传递、PE raw/normalized 解析、文本 Recaption、单次调用、RGBA、额外返回、源码/输出冲突 |
| FLUX / FIBO | PUP 拆分、图像执行期 PUP 为零、bbox 条件、完整官方 VGL schema、输入引用、mask 互斥、原始失败证据、全部返回图像 |
| 五阶段 | source-only 与 A/B、有限反馈、每轮新 intent/condition、固定原 source、resample 不重编译、shared planning 导入 |
| 几何与融合 | Qwen 32 网格、声明的 padding/inverse、mask 外硬复制、透明策略、推理期间源图/mask/prepared 图变化被拒绝 |
| 恢复与预算 | 未知提交不重发、零调用 direct、超额调用、journal 篡改、worker spool、不同 source/seed/attempt/condition 的错误回执拒绝 |
| 批次与导出 | 四模型三臂共用一次规划、输入快照、原文件中途变化/删除、resume 不重复、完整回执与条件导出、只读 journal 状态 |

测试中的模型、VLM、Torch/Pipeline 边界均使用明确的 fixture/mock；它们验证代码调用与协议，不模拟已经完成正式 GPU 推理。

## 独立交叉审阅与修复

实际发现并修复的问题包括：

1. Qwen 工作画布误用 16 网格；统一准备为实际需要的 32 网格。
2. 长时间执行后原 source/mask 变化可能污染融合；交付前重新核对全部冻结输入及 geometry 摘要。
3. worker 非法 timeout 在启动进程后才报错；移至启动之前验证。
4. 批次开始后原数据文件变化可能让各模型读到不同输入；改为一次冻结 source/reference/mask 快照。
5. 人工恢复可串用其他案例或种子的 adapter 回执；现在验证完整 request、condition、config、seed/attempt 和输出目录。
6. 报告读取落后的 state 投影；改为只读校验 journal 最新状态。
7. 报告遗漏原生条件；完整 JSON 现在包含真实 operation result 与所有轮次 condition。

独立复核明确验证：错误恢复不改变 pending、预算或 paused 状态；随后真实匹配回执可恢复一次，生成计数仍为 1。输入快照测试在原数据文件被修改、删除后仍保持同一源哈希，resume 不增加生成。

## 服务器阶段

待用户服务器执行：本地权重加载、实际 compiler 与 image pipeline、CUDA/显存、长图和真实文字条件、四模型画质比较。默认依赖组合来自上游 API 与源码核验，没有被标记为整栈 GPU 实测通过。

可直接使用 [RUNBOOK.md](RUNBOOK.md) 的部署、doctor、单案例、batch 与 report 命令。实际运行结果应由真实模型回执生成，不能用本文件的软件通过状态替代。
