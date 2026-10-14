# Qwen-Image-2.1 本地配置核查（I-17）

核查日期：2026-10-14。级别：REPO_VERIFIED（本地 diffusers 0.41.0 源码 + 本仓库 settings/clients 静态读取，未重跑图像模型）。对应问题台账 I-17；本记录只确认“实际参数与运行分支”，不做质量归因。

## 1. 运行环境

| 项 | 值 |
|---|---|
| diffusers | 0.41.0 |
| transformers | 5.15.0 |
| torch | 2.11.0+cu130（CUDA 可用，8 卡） |
| Executor checkpoint | `pretrained_model/Qwen-Image-2.1` |

## 2. Pipeline 与组件身份

- `model_index.json`：`_class_name = QwenImage21Pipeline`；text_encoder=Qwen3VLForConditionalGeneration，transformer=QwenImage21Transformer2DModel，vae=AutoencoderKLQwenImage21。
- `model_index.json` 与 `model_index.json.bak` 无差异（未被本地改动）。
- 本地加载：`harness/clients.py` `MFMClient._build`，`kind=="qwen21"` 走 `QwenImage21Pipeline.from_pretrained(...)`。与官方推荐 pipeline 一致。

## 3. 采样参数（settings.py）

| 参数 | 值 | 来源 |
|---|---|---|
| num_inference_steps | 40 | `MFM_NUM_INFERENCE_STEPS`（默认 40，与官方一致） |
| true_cfg_scale | 4.0 | `MFM_TRUE_CFG_SCALE`（默认 4.0，可用 `HARNESS_MFM_TRUE_CFG` 覆盖） |
| negative_prompt | `" "`（单个空格） | `clients.py` qwen21 分支硬编码 |
| guidance_scale | 未传 | QwenImage21Pipeline 无 guidance_scale 形参 |
| scheduler | FlowMatchEulerDiscreteScheduler | `scheduler/scheduler_config.json`，use_dynamic_shifting=true，shift=1.0，与官方一致 |
| seed | 0 | `MFM_SEED` |

## 4. CFG 分支是否实际启用（关键）

diffusers 0.41.0 `pipeline_qwenimage21.py`：

- L677 `has_neg_prompt = negative_prompt is not None or negative_prompt_embeds is not None`
- L678 `do_true_cfg = true_cfg_scale > 1 and has_neg_prompt`
- L813 `noise_pred = neg_noise_pred + true_cfg_scale * (noise_pred - neg_noise_pred)`

本地 `negative_prompt=" "` → `has_neg_prompt=True`；`true_cfg_scale=4.0 > 1` → **`do_true_cfg=True`，CFG 分支确实启用**，每步多跑一次负向 transformer 前向。

官方文档字符串（同文件 L548-550）："true_cfg_scale (float, optional, defaults to 1.0): ... Qwen-Image 2.1 is meant to be sampled without guidance, hence the default of 1.0."

## 5. 判定

- **不能判定配错**：4.0 是合法可生效参数，pipeline/调度器/步数均正确，CFG 确实在跑；模型身份无误。
- **与官方默认不同**：官方推荐无引导（1.0）。本地为“4.0 + 空格负提示”——负提示语义为空，CFG 方向几乎完全由正 prompt 决定，属于边界配置；这与 H08 全部 Qwen 结果绑定，是潜在混杂变量。
- **必须补对照**：在固定诊断/prompt/seed 下，补 `true_cfg_scale=1.0`（官方默认）与当前 `4.0` 的配对小试；`HARNESS_MFM_TRUE_CFG=1.0` 即可切换，无需改代码。注意 1.0 时 `do_true_cfg=False`，负提示被忽略，单步走法不同，耗时约减半。
- H08 结果不得用改配置后的结果追溯替换；新旧配置分开报告。

## 6. 建议的最小对照协议（下一步 D+E 前置）

- 样本：分层 6 张开发图；每图 3 个配对 seed。
- 臂：{true_cfg 1.0, 4.0} × {simple, 原 Compose}，共 4 臂；其余参数冻结。
- 若 1.0 与 4.0 在简单 prompt 下差异可忽略，则后续 D 消融沿用 4.0 以保持与 H08 可比；若差异显著，则两条配置都要带入 D。
- 记录逐图输出、亮度/区域统计、NR-IQA；同时考察可见性、夜感、内容保持，不单看 shadow mean。
