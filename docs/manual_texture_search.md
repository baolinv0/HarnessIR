# 手动迭代 texture-only 恢复

`hre search` 在现有 v3 单图恢复之外运行。操作员通过文件将开发集反馈交给 VS Code Chat，并登记模型或人工撰写的 JSON 提案。Python 运行恢复、归档结果并计算独立验收。操作员依据选优集决定是否晋级。作为图像编辑器使用的 MiniMax、Qwen 和 FLUX 与负责提案的聊天模型是独立角色。

## 准备运行环境

在仓库根目录安装 `python -m pip install -e "./engine[test]"`。运行 `hre models catalog --all` 查看新增配置。`hre models init --out ./model-config` 可生成现有 Qwen 和 FLUX 3 的配置样例。`stage` 使用已部署的 v3 VLM 端点作诊断、指令组装和内部验证。聊天提案走文件，操作者通过正常的 VS Code 界面使用可访问的模型。

- `minimax_h3` 使用本地或授权的 SGLang 服务。配置 `compiler: {"backend":"direct"}`。`editor` 使用 `model_id: "MiniMaxAI/MiniMax-H3-Image"`，填入 `revision`、`base_url`（例如 `http://127.0.0.1:30000`）和可选的 `api_key_env`。`settings.min_generation_area` 默认为 4194304，亲自核对实际部署版本和计划的画布。revision 来自操作者的部署记录。 [MiniMax H3 原生接口](https://huggingface.co/MiniMaxAI/MiniMax-H3-Image)
- `qwen21` 与 `flux3_klein` 使用已有 v3 适配器。给 Qwen 的同一组对照固定 direct 或 PE-I2I，FLUX 3 固定原生 PUP 或明确配置的外部编译器。 [v3 部署说明](four_model_v3/RUNBOOK.md)
- `flux2_klein` 使用 `compiler: {"backend":"direct"}`，`editor.model_id` 为 `black-forest-labs/FLUX.2-klein-4B`。填入 `local_path`、`revision`、`pipeline_version`、`device` 和 `torch_dtype`，`settings` 用空对象。使用本地 Diffusers `Flux2KleinPipeline` 的四步蒸馏路径。 [FLUX.2 Klein 4B 模型卡](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B)

用 `hre models doctor --config runtime.json --profile minimax_h3` 检查指定配置。每个模型先独立跑一例；doctor 只检查配置或本地文件，不测模型能力。

## 冻结任务与评价

在独立的校准样本上准备原图与可接受、不可接受的候选。使用以下命令查看整图与 ROI 的统计，再选定阈值。校准对照图应使用同一几何、方向和 SDR sRGB 色彩空间。`rois.json` 的 `regions` 数组沿用下例的 `id` 和 `source_box`。

```powershell
hre search measure --source calibration/original.png --output calibration/candidate.png --regions calibration/rois.json
```

亮度使用 Y 通道经半径 2 和 8 像素高斯滤波后的绝对差第 95 百分位，取二者最大。色度使用 Cb、Cr 每通道绝对差第 95 百分位的最大值。新增截断检查原图中尚未截断、交付图中落到 Y ≤ 2 或 Y ≥ 253 的像素比例。盲评同时判断实质纹理改善、内容冲突和伪影。无 GT 的结果可以判为与可见证据一致。有离线参考时，可以使用 `verified`。原图像素副本始终没有恢复收益。

```json
{
  "profiles": ["minimax_h3", "qwen21"],
  "seeds": [21, 42],
  "geometry": {"policy": "pad", "grid": 32},
  "maximum_proposals": 6,
  "minimum_gain": 0.05,
  "thresholds": {"luma_p95": 8, "chroma_p95": 8, "new_clipping_fraction": 0.005},
  "calibration_note": "Replace illustrative thresholds with a separate calibration record.",
  "samples": [
    {
      "id": "study-01", "scene": "scene-01", "split": "dev", "source": "photos/01.png",
      "brief": "Recover existing weave on the jacket.",
      "regions": [
        {"id": "jacket", "role": "target", "source_box": [0.15, 0.45, 0.65, 0.85]},
        {"id": "face", "role": "protected", "source_box": [0.20, 0.10, 0.60, 0.44]}
      ]
    },
    {"id": "study-02", "scene": "scene-02", "split": "selection", "source": "photos/02.png"},
    {"id": "study-03", "scene": "scene-03", "split": "test", "source": "photos/03.png", "gt": "paired/03.png"}
  ]
}
```

表中的阈值和三个样本只示范格式。用场景分组准备独立样本和校准证据。`gt` 可选，仅进入离线盲评包。需要核实关键内容时，设置 `requires_verified_content: true` 并提供离线参考。将私有 study 和选优、测试评审包放在提案模型无法读取的位置。只把 `feedback` 生成的开发包交给聊天模型。

## 跑一轮

```powershell
$studyRoot = 'C:/experiments/texture/private-study'
$reviewRoot = 'C:/experiments/texture/review-exports'
hre search init --study $studyRoot --manifest study.json --config runtime.json
hre search run --study $studyRoot --split dev --profile minimax_h3 --candidate direct
hre search run --study $studyRoot --split dev --profile minimax_h3 --candidate baseline
hre search review --study $studyRoot --split dev --profile minimax_h3 --candidate direct --candidate baseline --out "$reviewRoot/dev-01"
```

`direct` 使用原生基线，`baseline` 使用现有 model-aware 工作流。同一组比较固定模型、编译路线、seed 序列、几何和生成上限。`review.json` 是匿名图像索引，评级人填写 `ratings.template.json` 的副本。每张候选填写一项保真结论、一项纹理结论、一项伪影结论和具体证据。

| 字段 | 允许值 |
| --- | --- |
| `preservation` | `verified`, `no_visible_conflict`, `conflict`, `unverifiable` |
| `texture` | `improved`, `unchanged`, `worse`, `uncertain` |
| `artifact` | `none`, `minor`, `major`, `uncertain` |
| `evidence` | 观察到的区域、可见变化及依据 |

```powershell
hre search score --study $studyRoot --ratings "$reviewRoot/dev-01/ratings.json"
hre search feedback --study $studyRoot --packet PACKET_ID --out "$reviewRoot/feedback-01"
```

把开发包交给提案者。下面的 JSON 展示提案格式。

```json
{
  "id": "weave-only",
  "parent": "baseline",
  "hypothesis": "Targeted wording increases usable fabric detail and reduces tone drift.",
  "policy": {"evidence": "target"},
  "model_overrides": {
    "minimax_h3": {"instruction": "Sharpen only the weave already visible in the jacket. Preserve shadow density."}
  }
}
```

提案可调整 `instruction`、`strategy`（`shared`、`model_aware`）和 `evidence`（`all`、`target`、`protected`、`none`）。每个模型可以覆盖共享策略。模型、标签、评测器、数据分组和预算在 study 中冻结。可以用同一提案在另一个模型的独立配置下作迁移对照。

```powershell
hre search propose --study $studyRoot --proposal proposal.json
hre search run --study $studyRoot --split dev --profile minimax_h3 --candidate weave-only
hre search run --study $studyRoot --split selection --profile minimax_h3 --candidate baseline
hre search run --study $studyRoot --split selection --profile minimax_h3 --candidate weave-only
hre search review --study $studyRoot --split selection --profile minimax_h3 --candidate baseline --candidate weave-only --out "$reviewRoot/selection-01"
hre search score --study $studyRoot --ratings "$reviewRoot/selection-01/ratings.json"
hre search promote --study $studyRoot --profile minimax_h3 --candidate weave-only --packet PACKET_ID --reason "Qualified gains on selection"
```

继续迭代时以该模型当前生效版本为父版本。外层报告记录候选池合格率、最终合格改善率、严重违例率、回退率与实际图像、编译和 VLM 调用数。`severe_rate` 统计经内层选择的输出在外层独立验收中出现严重问题的比例。外层的 `delivered` 只有在有改善且通过内外两层验收时才指向正式图像，候选仍保留作审计。晋级要求同一独立评审包的改善率增长达到门槛、严重违例率无上升、生成预算未越界。

当结果准备好时，运行 `hre search freeze --study $studyRoot --reason "End of proposals"`。之后可对 `direct`、`baseline` 和各模型自己的最终版本执行 `--split test`，用相同的盲评流程出最终报告。提交状态未知的 v3 case 使用 `hre models reconcile` 核对证据，再恢复。

## 验证

```powershell
python -m pytest -q engine/tests/test_texture_search.py engine/tests/test_v3_h3_flux2.py
```

测试覆盖合成图、H3 本地模拟服务和模拟 Diffusers 管道。真实模型的画质、模型间迁移和 H3 的可部署性需要用实际权重和数据测量。
