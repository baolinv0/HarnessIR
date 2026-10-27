Tone Mapping
Description: 
This week, we improved the tone-mapping data-generation pipeline in two areas and evaluated the updated version on the full 21-pair test set.
1. Evidence-guided prompt composition: Added depth and semantic information as structured inputs to the compose stage, allowing the pipeline to generate more accurate, region-aware tone-mapping instructions.
2. Refine from original: Changed the refinement process to start each iteration from the original image rather than the previous output. This avoids accumulating artifacts across iterations and helps preserve input fidelity.
3. Evaluation protocol: Introduced region-sim-tone v2, which measures region-level brightness and color distribution similarity to the reference using EMD, alongside SSIM for structural fidelity. Input and reference regions are matched using their respective ROI boxes. The previous VLM-based evaluation was removed because its fidelity scores saturated at 100 across all 126 outputs, making it unsuitable for ranking.

Results:
The comparison includes five outputs:
Input | Reference (GT) | Redraw (Soft-ISP) | Previous | Current
 

Analyze: 
–	Comparable overall performance, better color transfer. The current pipeline scores 78.1 vs. 78.7 previously, but improves b* chrominance matching (EMD: 5.58 vs. 6.11) and reference-aligned regions (38/66 vs. 36/66).
–	Regional brightness remains the main limitation. Subject tone improves, but background brightness and contrast remain inaccurate. Only 20/51 ROIs show brightness improvement, indicating limited regional control.
–	Fidelity gap remains. Tone similarity approaches redraw (79.3 vs. 80.3), but structural fidelity remains lower (≈78 vs. 92.2).

一句话本周工作总结：
Depth/semantic evidence and refine-from-original improve color transfer while maintaining comparable overall quality. Regional luminance control and structural fidelity remain the main bottlenecks.

下周工作计划：
(1)	Improve subject/background-independent tone control with region-specific luminance targets, while preserving high-frequency details and minimizing full-frame resampling.
