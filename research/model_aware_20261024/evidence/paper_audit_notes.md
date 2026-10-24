# HarnessIR 原始论文与官方数据审计（中间证据笔记）

审阅日期：2026-10-24。范围：原始图像复原的 diagnosis、tools、composition、execution、verification/redos；未运行论文的复原实验，不把作者结果或代码阅读称为复现。E2=已检查作者原始论文/表/代码，不能自动升级为独立验证。

## 固定身份与来源

- 论文固定版：[arXiv:2610.10133v3](https://arxiv.org/abs/2610.10133v3)，2026-10-19，26页；[PDF](https://arxiv.org/pdf/2610.10133v3)、[HTML](https://arxiv.org/html/2610.10133v3)。v1提交于2026-10-07，v2=10-08。作者为 Xiangtao Kong、Shuaizheng Liu、Rongyuan Wu、Lingchen Sun、Zhengqiang Zhang、Jixin Zhao、Yuhui Wu、Lei Zhang，PolyU/OPPO。
- 官方身份链：论文p1直接链接 https://github.com/PolyU-VCLab/HarnessIR；[项目页](https://polyu-vclab.github.io/HarnessIR/)同名同作者且链接该仓库和数据。仓库 main 在本次审阅时固定到 [773f19654d2d4d9a3b0ce20f80508a4dd0788aff](https://github.com/PolyU-VCLab/HarnessIR/tree/773f19654d2d4d9a3b0ce20f80508a4dd0788aff)，提交时间2026-10-16 14:20 UTC（Update index.html）。仓库版本早于v3论文，差异需显式核对。
- 官方HF由README顶部链接到 [VCLab-PolyU/HarnessIR](https://huggingface.co/datasets/VCLab-PolyU/HarnessIR)。固定HF revision=d64b3fc51d30944b6750326f3aeadecd2006ed8d，lastModified=2026-10-07T10:16:05Z。
- 下列代码链接的统一固定前缀：https://github.com/PolyU-VCLab/HarnessIR/blob/773f19654d2d4d9a3b0ce20f80508a4dd0788aff/ 。

## 最强可支持结论（E2，作者报告）

相同执行器下，具体图像分析、较详细且带保真要求的提示组织能改进原论文所测数据的指标，已有一次执行控制。整套系统加verification/redo与选优进一步提高均值；这是有价值的系统证据。现有研究没有充分隔离五个阶段各自的因果贡献，也未证明统一Harness独立于执行器能力、预算、评估模型偏好而普遍有效。对传统agent的比较同时更换执行器，不能将全部优势归于Harness。

## 五阶段：论文机制与代码定位

| 阶段 | 原始论文位置 | 机制/范围 | 固定代码路径与行 |
|---|---|---|---|
| Diagnosis | §3.1 p4、§3.2 pp4-5 | 同一冻结VLM的诊断brief读LQ+请求，输出内容/退化/辅助工具计划；不是安排复原模型次序 | harness/stages/diagnosis.py L113-154；pipeline.py L159-166 |
| Tools | §3.2 pp4-5 | OCR文本与置信度/框、人脸框、depth图、seg图；结果交composer，不交最终executor；按需，可为空 | harness/stages/tools.py；harness/perception/{ocr,faces,depth,segment}.py；pipeline.py L168-196 |
| Composition | §3.3 p5 | VLM结合LQ+诊断+工具结构/视觉证据，筛选domain requirements，生成一段图像特定文本；可不采纳不可靠工具证据 | harness/stages/compose.py；prompts/compose.txt、compose_blocks.txt；pipeline.py L197-205 |
| Execution | §3.1 Eq1 p4、§3.3 p5 | executor仅接原始LQ+文本；工具不是复原网络；每轮为完整候选 | harness/stages/execute.py L34-148；clients.py L179-238；pipeline.py L212-235 |
| Verification / redo | §3.4 p5 | 同型VLM另brief看LQ与候选及统计，不看executor instruction；失败才从同一LQ以新prompt重做；最多3轮，保留更好候选 | harness/stages/verify.py L443-504；refine.py；pipeline.py L263-320；selection.py L132-215 |

论文§3.4将SSIM/color等描述为诊断证据而非固定接受阈值；实际settings.py设置STRUCTURE_SSIM_MIN=.30和CHROMA_DRIFT_MAX=.10，selection.py L169-177先排除gates_failed候选（全失败时回退）。需由主代码审计核对实际gate策略；不能只按正文复述。

## 模型身份、参数与运行条件

- 论文§4.1 pp5-6：diagnoser/composer/verifier均为Gemini-3.7-Flash，同冻结VLM三种brief；执行器NB2或GPT-Image-2.5-Sunburst；无训练/微调。
- 代码settings.py L58-88：VLM模型字串gemini-3.7-flash；temperature=.2，max_output_tokens=16384；NB2实际endpoint别名gemini-3.1-flash-image-preview；GPT为gpt-image-2.5-sunburst；MFM output size=1K。未见固定权重hash/API snapshot或返回模型版本证明，不能视为永久可重现身份。
- 已进一步访问官方vendor文档：[Gemini3.7Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.7-flash)页面（2026-10-12更新）明确该模型deprecated，`gemini-3.7-flash` API请求自动转发`gemini-3.8-flash`。因此今日按同字串调用不能声称exact replication，也无法在无作者返回元数据下确定原评测实际服务版本。[NB2模型页](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-image)当前stable code为`gemini-3.1-flash-image`（2026-10-09更新），页面未列仓库所用preview后缀，需核验兼容别名。[GPT图像模型页](https://developers.openai.com/api/docs/models/gpt-image-2.5-sunburst)列出了可固定的`gpt-image-2.5-sunburst-2026-09-08`，但仓库用undated alias且采用Gemini格式代理路由；官方模型存在不等于作者运行身份证明。
- 四工具：PP-OCRv6、InsightFace、Depth-Anything-V2、SAM3（§4.1 p6）。settings.py列本地checkpoint路径；闭源MFM/VLM参数量、服务硬件、精度、能耗/峰值内存没有报告，不能推断端侧可部署。
- configs/default.json：enable_tools=true、enable_redo=false、max_rounds=3、square1024=true、color_adjust=true。默认命令跑single-pass，需显式启用redo才能对应论文final系统。
- 编码图像/RGB管线；代码execute.py对长边等比缩放1024，executor前居中黑填充1024²，后裁掉边；对偏离目标尺寸的MFM结果先LANCZOS重采样。原始测试集制作的resize/crop另见AppB。
- color_adjust.py在纯mix标签时用AdaIN把LQ每通道均值/标准差转移给输出；named weather/lowlight为copy。pipeline.py L243-252在评分/验证前覆盖输出；run_baseline.py L97-104也默认做同样处理。论文正文/附录未见AdaIN的明确描述或消融；原始executor输出与后处理结果须分开，且需作者运行记录才能确认表格到底采用何设置。

## 主要作者报告结果（E2；未独立重跑）

### Tables 1-3，pp7-8

| 数据 | 模型 | PSNR dB↑ | LPIPS↓ | D↑ | F↑ | DF↑ |
|---|---|---:|---:|---:|---:|---:|
| MiO100，组平均，Tab1 p7 | NB2 direct |20.81|.24|76.7|44.9|55.87|
| | HarnessIR-NB2 |22.21|.21|75.2|51.7|59.94|
| | GPT direct |17.95|.36|48.8|20.9|30.38|
| | HarnessIR-GPT |19.70|.30|67.5|37.7|48.44|
| Real-Paired-200，Tab2 p7 | NB2 direct |23.94|.309|67.9|47.8|52.9|
| | HarnessIR-NB2 |26.63|.246|75.2|63.6|62.0|
| | GPT direct |20.87|.361|69.0|27.5|40.1|
| | HarnessIR-GPT |23.74|.286|82.7|50.4|60.2|
| Real-NoGT-200，Tab3 p8 | NB2 direct |—|—|65.1|34.4|47.3|
| | HarnessIR-NB2 |—|—|71.3|64.1|62.9|
| | GPT direct |—|—|59.3|16.9|29.6|
| | HarnessIR-GPT |—|—|76.4|36.0|49.3|

- MiO100 NB2的D从76.7降到75.2，不能说所有指标/去退化均提升。HarnessIR-GPT MiO PSNR19.70低于LQ19.86；Real-Paired PSNR23.74低于LQ25.27。指标体现取舍，不等于逐像素恢复总是更好。
- MiO100最强旧方法OPERA PSNR21.78、SSIM.69；HarnessIR-NB2为22.21/.65。不能把“多数指标领先”扩写成每项SOTA。
- 旧方法含6 all-in-one + 6 agentic；§4.1 p6称公开代码权重用官方实现，未公开的仅引用原论文MiO结果。Tab1存在不少缺失列；真实集只有可运行子集。不同执行器/代际工具造成大混杂。

## 消融能隔离与不能隔离什么

### Tab4 p10，§4.4.1：全部一次MFM、无verification/redo

| NB2 executor输入 | PSNR | DF | 可读结论 |
|---|---:|---:|---|
| direct简短用户请求 |23.94|52.9|基线|
| Detailed User Request |24.75|54.5|更具体的通用请求本身有益|
| Single-VLM Instruction |25.49|56.6|图像特定诊断+生成prompt组合有益|
| Two VLMs+Tools (Visual Evidence) |25.62|57.8|工具与第二次VLM同时加入，无法单独归因tools|
| Two VLMs+Tools (Text Evidence) |26.01|59.6|在相同大组合下文字化证据优于视觉输入，最强一次执行|

没有逐工具/无工具双VLM等factorial控制，没有随机或错误证据的负对照，没有诊断准确率、工具选择正确性与质量收益的逐图因果分析。最后两行D=74.4→73.0而F=55.3→58.5；文字优势主要不该泛化为所有维度同时改善。作者对visual artifacts给出例子，但还不是系统归因。

### Tab5 p10，§4.4.2

single-pass26.01/59.6；in-place refinement25.64/57.2；redo from LQ26.63/62.0（PSNR/DF）。支持该实现下从LQ重做优于累积失败图。没有equal-call固定prompt重复采样+同selector、Best-of-N、仅选择/无反馈控制，故无法将+0.62dB/+2.4DF纯归因“验证反馈”。redo集合是verifier选择的困难样本，不能拿其均值推广到所有图。

### Tab6 p11，§4.4.3

同NB2；只换diagnoser+composer，关闭verification/redo。Qwen3-VL-32B25.68/57.5；GPT-5.6-Sol26.18/60.5；GPT-5.6-Luna26.05/59.1；Gemini-3.7-Flash26.01/59.6。支持单轮前段对几种较强VLM有一定稳健性，不能证明verifier、redo、整套统一Harness跨模型均成立。

## 数据集与预处理（AppB，TabB.1 p22、文字p23）

Real-Paired-200：LR=DRealSR20+RealSR20；haze=I-HAZE20+NH-HAZE20；rain=RealRain-1k-H20+RainDS-real20；blur=RealBlur20；noise=SIDD20+PolyU20；wild mixed=RAIM20。没有paired低光或paired雪，所谓真实mixed paired仅20张。

Real-NoGT-200：mixed100（RealDeg classic film25+old photo25+social media25，ImageNet-worst25）；haze25（ACDC7/JarvisIR6/RESIDE-RTTS6/NightHaze6）；rain25（ACDC7/HQ-NightRain6/JarvisIR6/NTURain6）；snow25（ACDC9/JarvisIR8/Snow100K-realistic8）；lowlight25（ExDark9/ACDC-night8/JarvisIR-night8）。

作者称从各源随机抽取；未见抽样seed、来源原始文件映射/采集时间、闭源预训练去重/污染检测。长边<1024则等比放到1024；>1024则沿长维中心裁至1024且短维不变；paired GT同步操作保持对齐。MiO100 A/B各2种退化，C三种；TabD.3 pp24-25分别给组结果。自建真实集的规模/来源有限，且来源公开并不能证明对闭源MFM为训练外数据。

## 指标、评估独立性与人类验证

- §4.2 pp6-7：Y-channel PSNR/SSIM；LPIPS/DISTS；NR=MANIQA、CLIP-IQA、MUSIQ、TOPIQ、AFINE-NR。GT存在时用|NR(output)-NR(GT)|；没有GT时灰化NR列，强调DF。绝对NR差接近不证明内容正确，多个错误图可同分；应作为互补指标。
- DF=每图sqrt(D*F)，再平均；不能由表中平均D和平均F开方重算。DF的F比较LQ而非不可观察GT，因此无法证明细节是真实恢复、无法判断LQ中本来不可辨认的文字/人脸。
- 主DF评估模型从AppC推知是Gemini-3.7-Flash，与控制器同型号；“independent evaluator”是不同角色/调用，不能写成不同模型或独立机构验证。compute_df.py默认同settings VLM，默认repeats=1（L66-73）；未见主表重复采样方差/统计置信区间。
- AppC pp23-24：300个Real-NoGT pair、8方法均匀随机选两者、左右顺序随机、隐去方法/分数，30 annotators，majority，平票丢弃；作者报DF与人类一致87%，NR=50.8%-67.1%。未给最终有效pairs数、标注原始数据、同图重复pair相关性处理或CI，87%不是全部任务准确率。
- 同AppC TabC.2：400真实图输出，GPT-5.6-Sol相对Gemini的D/F/DF PLCC=.85/.87/.94；Claude-Opus-5=.87/.89/.92。支持分值相关；未给各模型方法排名/胜负稳定性、rank correlation、系统差值CI。也不能排除共享审美/提示rubric偏好。
- §4.6 pp12-13 Fig5：200图（paired100+noGT100），每图8候选、随机排列盲方法，25人每人全标200，共5000票；NB2 Harness48.3%、GPT Harness28.1%、合计76.4%。作者组织的人类偏好研究是多模态指标之外的支持，但非独立复现；两Harness加总是8选1中两个候选的票份额，不能当“76.4%图优于baseline”的paired win rate。

## 成本与边界

Tab7 p11，§4.5 pp11-12，均Real-Paired-200/NB2：direct14.7s/$0.070/1MFM；1VLM27.2s/$0.077；2VLM+tools41.8s/$0.085；final64.3s/$0.129，平均3.90 VLM/1.45 MFM/2.40 local tools。29%一次redo、8%两次、共37%需要redo，平均.45新增轮。相较direct约4.37倍时长/1.84倍估算成本，不能称无额外推理开销。

价格依据2026-09公开API价、A100三云平均$2.671/GPU小时，按实测token和local runtime折算，明确排除并行等待、部署、环境开销（§4.5）。它是作者的理想化参考估算，不是用户端账单/SLA、网络延迟或端侧实测。

§5 p13自述限制：依赖在线VLM/MFM API；Harness只能调控/引出executor已有能力，不能提高其上限。未报告privacy/on-device/能耗证据；不要外推到移动ISP/RAW复原。AppA.2 pp18-22展示单个bird案例，验证检测虚构左爪并重做改善；属于选例而非总体失败率。

## 公共数据可用性（继续补充指定night_0043样本）

HF固定索引只含4文件：.gitattributes2504B、README83B、dataset.zip660,918,954B、visual_results.zip4,517,500,116B；压缩包合计5,178,419,070B，约5.18GB（十进制）。metadata已实读，保存在harnessir_hf_meta.json、harnessir_hf_index.json。

大文件支持HTTP Range，已实际读到dataset.zip尾65557B，206 Content-Range bytes660853397-660918953/660918954。使用固定revision读取zip central directory和单个night_0043；没有整包下载。两包central directory已保存为dataset_archive_index.json、visual_results_archive_index.json。

压缩包实际内容（排除目录）：dataset.zip=603文件，其中paired LQ200+GT200、noGT LQ200、3个manifest；没有MiO LQ/GT，仅MiO manifest。visual_results.zip=3680文件：MiO NB2/HarnessIR-NB2各1440、paired各200、noGT各200；只有这两个模型图像，没有GPT/HarnessIR-GPT输出，也无JSON/TXT/CSV/LOG逐图执行日志。

指定样本：dataset/Real-NoGT-200/LQ/Low-Light/night_0043_acdc-night.png，689392B，已实际从Range解压，路径=/workspace/scratch/7d29333b7554/harnessir_author_samples/dataset/Real-NoGT-200/LQ/Low-Light/night_0043_acdc-night.png。该图在noGT子集，因此没有paired GT。

作者输出索引中存在visual_results/Real-NoGT-200/NB2/Low-Light/night_0043_acdc-night.png（1519032B）和visual_results/Real-NoGT-200/HarnessIR-NB2/Low-Light/night_0043_acdc-night.png（1439521B）。但下载具体条目的Range请求被环境网络策略阻止：`Network access to https://us.aws.cdn.hf.co:443 was blocked by policy`。因此只确认索引存在，不声称已取得或查看这两张输出，不对其质量下结论。

3个小manifest均已成功取得（第二次dataset Range总传输157399B，含重复读取的central directory；三个manifest压缩总15134B），保存在上述harnessir_author_samples/dataset/{MiO,Real-NoGT-200,Real-Paired-200}/manifest.json。MiO=1440条且LQ/GT为`/MIO100/...`外部绝对路径；dataset.zip未附这些MiO输入。真实paired/noGT各200条。它们属于输入清单，不是逐阶段/逐轮日志。

night_0043对应manifest完整对象：`{"lq":"LQ/Low-Light/night_0043_acdc-night.png","prompt":"Restore this low-quality image to a clear, clean and natural state and recover its normal brightness.","type":["lowlight"]}`。没有gt字段，没有keep night mood之类额外用户要求；对它评价“夜间氛围是否保持”须区分原请求明确要求恢复正常亮度与后加的scope约束。

## 仍缺失且会改变判断的证据

1. 固定API快照、执行器seed/repeats、生成超参和最终运行manifest；closed model内容/训练重叠不可查。
2. 作者所有逐图stage日志、raw MFM输出、后处理前后图、逐轮prompt/verdict/选择记录，才能查验复原保真与评估流程。
3. tools vs第二VLM、prompt长度/domain知识、type标签、后处理、verification与重采样/选择的独立因果控制。
4. 全局/逐类失败分布、特别是text identity与极暗/截断/严重模糊下不可恢复细节的负例与不确定性。
5. 多seed/运行的统计区间；按图/源数据聚类的人类评估不确定性；独立团队同预算复现。

审计产生的是E2论文/源码核对与公开数据访问证据，未执行云复原或复现任何作者分数。
