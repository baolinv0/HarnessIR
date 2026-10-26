# 参考 Retouch：运行、验收与实验边界

日期：2026-10-26。依据：[最初目标](GOALS.md)、[已同意的完整设计](DESIGN.md)、[实际单案例实验](CASE_EXPERIMENT.md)。

## 1. 本次整合了什么

保留原 v3 参考闭环和模型适配器，新增显式 `workflow_contract="reference_retouch_v1"`。未设置该字段的任务仍使用原有 schema、模板和请求身份。新旧共享规划不能混用；历史案例不迁移。

- 八维参考覆盖、独立 A/B 观察、差异 ID、证据引用和属性级可比性。
- 目标不限三条；每项明确必需/可选、成功标准、源/参考区域与对应差异。
- 编译输入包含源图事实、参考事实、修改指令、成功标准和排除项；原生编译结果完整保存。
- 生成前冻结 `artifacts/reference_contract.json`。验证器接收该合同、A/B/C/原生 C、证据与几何，不接收模型名称和执行提示。
- 每个目标、保护项和固定伪影类别必须恰好检查一次。必需项未知或未完成不能通过，副目标残差仍显示。
- 反馈可改执行表达，不能修改源/参考事实、目标集、证据、必需性或成功标准；每轮仍从原 A+B 执行。
- 正确的 already-close 诊断与已满足合同返回原图，图像与编译调用均为零。参考不足是独立的未完成结果。
- 原生分辨率和可选细节门槛独立验收；插值不能使原生门槛通过。图像工具后端 unknown 不转写成已确认模型。

这条 opt-in 集成用现有四模型执行接口表达同一合同，不表示已经验证四个真实权重的风格跟随效果。

## 2. 先使用 GPT Image 可视化工作台

在仓库根目录创建环境并按 `engine/pyproject.toml` 安装依赖后：

```sh
python -m pip install -e ./engine
hre-retouch --serve --port 8766 --runs runs/retouch
```

也可以设置 `PYTHONPATH=engine/src`，运行 `python -m hre.retouch --serve --port 8766 --runs runs/retouch`。Windows 可运行 `./start-retouch.ps1 -Python <python路径>`。浏览器打开 http://127.0.0.1:8766/ 。

按页面顺序操作：创建 A/B 案例 → 参考诊断 → 证据与独立区域 → 目标/提示 → 编辑 → 逐目标验证 → 有支持的反馈或报告。各阶段可导出任务和导入实际 Agent 观察；配置接口后可直接运行。未配置接口时不提供模拟成功结果。

配置变量、真实双图传输、外部候选导入和未知提交恢复见 [工作台手册](../../RETOUCH_WORKBENCH.md)。工作台的新交付验收版本与原 v3 opt-in 合同分别标记；二者的历史数据不被相互转换。工作台与 v3 阶段 schema 分开版本化，不直接互换 JSON。

GPT Image 2 输出编辑图像；诊断/验证使用实际配置的 VLM 或 Agent。仓库不包含用户照片、运行目录或密钥。`/experiments` 在本地 `runs/retouch_experiments/` 存在真实记录时才显示实验数据，空目录不伪造样例。

## 3. 使用原始 hre models 入口

任务示例：[`engine/examples/reference_retouch/reference.example.json`](../../engine/examples/reference_retouch/reference.example.json)。修改源图、参考图和 brief 路径。使用已有的四模型 runtime 配置、部署检查和本地权重，见 [四模型运行手册](../four_model_v3/RUNBOOK.md)。

```sh
hre models create --case-root runs/retouch-v3-001 --spec engine/examples/reference_retouch/reference.example.json --config server-config/runtime.example.json
hre models prepare --case-root runs/retouch-v3-001 --through compose
hre models show --case-root runs/retouch-v3-001
hre models run --case-root runs/retouch-v3-001
hre models report --run runs/retouch-v3-001 --out runs/retouch-v3-report
```

`prepare --through compose` 不编译、不生图。若源图已经满足目标，它可以直接以 `already_satisfied` 完成；若参考不足则明确未成功。对正常编辑任务，报告显示分析/证据/冻结合同/实际条件、逐目标结果、原生与交付图像。命令执行完成与 `state.success` 的质量判断分别读取。

可用真实照片运行一个无需接口的严格自参考机制检查：

```sh
python engine/examples/reference_retouch/check_no_change.py --source /path/to/source-A.png --out runs/no-change-control
```

此检查专门使用像素相同的 A+A 和“只匹配已有参考外观”的明确任务，依靠像素一致性产生诊断证据，经生产运行器返回 A。它不证明 VLM 对任意 A/B 的诊断准确，也不加载示例配置中的模型权重。

新任务的 `delivery_requirements` 支持：

```json
{"require_native_source_resolution": true, "minimum_native_size": [1024, 1024], "require_detail_pass": false}
```

省略时要求原生宽高至少为源图宽高；提供 `minimum_native_size` 时取更严格的下限。`require_detail_pass=true` 还要求验证明确报告 `detail_preservation=pass`，缺失或 uncertain 均不通过。该观察仍非逐像素真实性认证。预先规划了缩小工作画布或局部编辑时，应明确设置适合任务的原生下限，不能运行失败后临时放宽。

批量案例透传 `workflow_contract` 和 `delivery_requirements`；此合同使用 shared/model_aware 臂。原 native 基线保持旧协议，单独运行并用同一离线合同评价，避免把直接编辑强制送入诊断流程。

## 4. 实验得到的经验与剩余边界

本地已保留六次真实宿主工具输出、五组主对照、一次 A+A 自参考，以及两个原样图像控制。带 B 的条件在柜板上更接近 B，但完整流程并未在所有属性上优于普通修图。A+A 仍提亮暖化、原生尺寸不达要求，是本次强化零编辑分支与交付验收的直接依据。

本轮软件负例和真实照片机制检查验证规则与链路，不自动证明分析 VLM 能正确诊断。宿主后端身份未知；当前没有新增已确认 GPT Image 2 的质量结论、四模型排名、跨场景稳定性或源高频细节真实性保证。

继续实验时先固定身份可核对的后端和真实输入来源，再做已知变换、属性替换、困难验证器反例和独立场景；只有确有残差和可支持改法时再比较等预算反馈。全部候选、失败及未评结果保留，不用新增采样次数冒充闭环收益。
