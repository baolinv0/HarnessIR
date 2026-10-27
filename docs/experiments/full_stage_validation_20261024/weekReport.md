按原模板保留英文正文，重点收敛到**模型选择、主要瓶颈和下周方向**。

:chatgpt-content-reference{index="0"}[下载 Markdown 周报](sandbox:/workspace/scratch/9ec665b45e7b/Tone_Mapping_Weekly_Report_20261027.md)

# Tone Mapping

## Description:

This week, we evaluated the reference-guided tone-mapping pipeline across four open-source image editors and three VLM configurations. The focus was to identify a suitable executor and understand the remaining limitations in matching reference tone and color while preserving input content.

1. **Executor comparison:** Compared Qwen, FLUX, Fibo, and FireRed on four paired scenes.
2. **Human-calibrated assessment:** Reviewed 32 outputs to assess editing quality, workflow effectiveness, and the reliability of VLM judgments.

## Results:

Human-reviewed subset: four development scenes, direct and model-aware strategies; eight outputs per editor.

| Editor | Overall improved | Content preservation passed |
|---|---:|---:|
| **Qwen** | **7/8** | **8/8** |
| FLUX | 7/8 | 6/8 |
| Fibo | 5/8 | 5/8 |
| FireRed | 1/8 | 4/8 |

“Improved” indicates relative improvement; it does not mean all reference-matching targets were achieved.

## Analyze:

- **Qwen is the preferred executor for the next stage.** It matched FLUX in overall improvement and preserved content more consistently in this subset. Fibo showed mixed results. FireRed frequently changed content or missed the reference appearance, making its current configuration unsuitable as the main executor.

- **Regional tone and color control remain the main bottleneck.** Qwen repeatedly applies broad brightness changes while leaving skin tone, foreground/background balance, or highlights inaccurate. Model-aware planning showed no aggregate improvement-rate gain over the direct baseline in the reviewed subset. These recurring issues suggest a weakness in the current instruction-to-execution chain; the contribution of prompt generation, rewriting, and model execution remains unresolved.

- **VLM evaluation still requires human calibration.** 27B matched human ratings best overall; 32B was overly permissive, while 8B both rejected improvements and accepted failures. On the Qwen subset, 27B showed no agreement advantage over 32B. Current evidence therefore does not establish one VLM as the best choice for the Qwen pipeline.

## 一句话本周工作总结：

Identified Qwen as the preferred executor for further development, with regional tone/color control and VLM evaluation reliability remaining the key limitations.

## 下周工作计划：

1. Fix Qwen as the executor and compare VLMs on regional difference analysis and planning, using final image quality and human review to guide selection.
2. Explore explicit region masks for more precise subject/background tone control, while separating instruction/workflow limitations from execution limitations and preserving input content.

