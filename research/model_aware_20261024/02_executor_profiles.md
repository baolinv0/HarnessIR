# HarnessIR Executor Profiles：一手接口核验笔记

核验截止：2026-10-24。对象：Nano Banana 2、Qwen-Image-2.1（主要），Qwen-Image-Edit-2511（身份对照）；FLUX.2 Klein、FireRed（辅助）。本笔记未调用这些模型生成图像，未下载完整权重，也无原始运行日志；下文“可获取/支持”仅指已核验的官方发布与公开实现接口，不是本机端到端运行成功、性能或编辑质量结论。

## 1. 身份先于能力

| 名称 | 可核验精确身份 | 获取/运行渠道 | 不应合并的身份 |
|---|---|---|---|
| Nano Banana 2 | Google `gemini-3.1-flash-image`；稳定版 GA 发布 2026-05-28 | Gemini API / Google Cloud 托管 API，官方 AI Studio 入口；本轮未找到公开下载权重 | `gemini-3.1-flash-image-preview` 已于2026-06-25关闭；`gemini-nano-banana-2.1` 是2026-10-06另发的2.1，不应静默替换 |
| Qwen-Image-2.1 | `Qwen/Qwen-Image-2.1`，`QwenImage21Pipeline`，2026-09-20官方发布 | 官方 HF/ModelScope 权重、官方 HF Demo、Diffusers本地推理 | 不是 `Qwen-Image-Edit-2511` 的别名；`Qwen-Image-2.1-Turbo`、托管 Pro/Turbo API须另建身份 |
| Qwen-Image-Edit-2511 | `Qwen/Qwen-Image-Edit-2511`，`QwenImageEditPlusPipeline` | 官方 HF 权重、官方 Demo、Qwen Chat图像编辑入口 | 不能将它的默认CFG、RGB协议或图像预处理转用到2.1 |
| FLUX.2 Klein | 至少应写全 `black-forest-labs/FLUX.2-klein-4B`（本轮简要核验实例） | 官方 HF权重、BFL API、Diffusers；模型卡Apache-2.0 | 家族名不能指定4B/9B、base/distilled、KV等变体 |
| FireRed | `FireRedTeam/FireRed-Image-Edit-1.0` 与 `...-1.1`均有官方模型卡；1.1于2026-03-03发布 | 官方HF/ModelScope权重、官方仓库推理、官方Demo | 当前官方`inference.py`默认仍指1.0；不能因README宣传1.1而视为运行了1.1 |

Nano Banana 2状态需要单列：Gemini API官方changelog在2026-10-06宣布`gemini-3.1-flash-image` deprecated，但**尚未宣布shutdown日期**。Google Cloud专页仍列GA与退休不早于2027-05-28；这是服务渠道层面的不同生命周期信息，不能据此断言模型已不可调用，也不能保证新账号即时可用。[G1–G4]

**规划/评分器身份补充（B1）**：同一官方changelog的2026-10-08节与deprecations表写明，`gemini-3.7-flash`已不再供AI Studio选择，发往此字符串的API请求会**自动路由到`gemini-3.8-flash`**；`gemini-3.5-flash`同样自动路由到`gemini-3.6-flash`。因此，若HarnessIR规划器或评分器只保存`gemini-3.7-flash`配置字符串，当前重跑不能证明仍使用论文当时的规划/评分版本。需要原始响应的实际model version、时间与端点记录；缺失时应标身份未锁定，不能以同名配置充当复现。此项是官方路由事实及其研究记录含义，未推断新旧版本能力。[G3的2026-10-08节L97–99；G4的Gemini 3 models表L101、L104]

Qwen 2.1身份有权重文件级证据：HF revision `840b4adb1e2c21c7d77967203188b55b678c535f`（2026-09-19）实际更新两片transformer safetensors；当前已核验完整repo revision为`d26bb61231c349cf6b7896fa83353113880e1ba3`（2026-09-30，后续文档修改）。模型卡license为`qwen-research`，不要继承2511的Apache-2.0标签。[Q1–Q4]

## 2. Nano Banana 2 Profile

| 项 | 已核验协议 | 边界/未知 |
|---|---|---|
| 输入 | 文本与图片parts；`generateContent`请求包含`contents[].parts[]`，图片可`inline_data`（base64＋MIME）；SDK可接PIL；较大文件使用Files/GCS等指定渠道 | 闭源服务内部resize、tile、颜色管理及权重不可观测；不要把通用Gemini image-understanding的3600张上限覆盖该模型14张限制 |
| 多图 | 模型专页给出每prompt最多14图；图片MIME为PNG/JPEG/WEBP/HEIC/HEIF | `14`是请求接口上限，不证明14对象都保持准确；“10对象/4人物”是官方产品能力描述，不是本研究实测结果 |
| 尺寸 | `image_config.aspect_ratio`与`image_config.image_size`（GenerateContent SDK）；1K默认，另有512px/0.5K、2K、4K；非任意width/height接口 | `image_size`的实际字面量应随SDK/端点版本核验；当前文档有`512px`与0.5K文字表述，不能自行发明`width`/`height`原生字段 |
| 比例 | 官方枚举：1:1、1:4、1:8、2:3、3:2、3:4、4:1、4:3、4:5、5:4、8:1、9:16、16:9、21:9 | 示例：1:1在1K/2K/4K为1024²/2048²/4096²；16:9为1376×768/2752×1536/5504×3072 |
| prompt | 自然语言；单轮与多轮会话编辑；可启用Google Search/Image Search grounding；minimal/high thinking，默认minimal | 工具开关、思考档、会话历史与返回thought signatures必须入运行记录；不能只记录最终用户prompt |
| 局部编辑 | 官方称“semantic masking”：用自然语言指定修改部分 | 已核验图像生成接口未见独立像素级`mask_image`参数；语义局部编辑不是硬mask合成，也不保证未编辑区逐像素不变 |
| 原生参数 | Google Cloud专页列temperature范围0–2、默认1；topP范围0–1、默认0.95；candidateCount=1。API层有response modalities、image config、thinking config、tools等 | 无已核验的diffusion steps、CFG、strength、scheduler、裁剪矩形、颜色匹配参数；不得把Harness字段直接标成原生支持 |
| seed | 通用`GenerationConfig` schema存在`seed`，定义为decoding seed | 未获得此图像模型专属seed确定性承诺或同seed重复调用原始证据。只能登记“API schema字段存在；图像重现行为未知”，不能写“固定seed可完全复现” |
| 输出/颜色 | 返回图像与文本；官方规定生成图包含SynthID | 本轮未找到原生LUT、ICC、直方图匹配、颜色恢复、背景硬合成开关。任何此类处理均须显式列为Harness后处理；透明RGBA的模型专属支持未知 |

来源分工：[G1]身份/令牌/入口；[G2]当前渠道、输入上限、格式、原生采样参数；[G3–G4]生命周期；[G5]GenerateContent编辑与图像配置、语义mask；[G6]精确输出尺寸与thinking表；[G7]通用seed schema。现行通用图像指南默认示例多使用2.1，引用时必须同时写明目标模型ID。

## 3. Qwen-Image-2.1 Profile（原始checkpoint）

实现锁定：Diffusers commit `da1d3829cf08d4f329b526d89e17cc035c049d8d`（2026-10-05，sampling sigmas变更）；`pipeline_qwenimage21.py`文件blob SHA `7cb519cde4a2e79a0bfc97abefc892490bde137e`。首次支持合并commit `6256aa7666cedd47443adc8f82da9a10e110b09c`（2026-09-18）。[Q5–Q7]

| 项 | 已核验实现 | Harness含义 |
|---|---|---|
| 原生入口 | `QwenImage21Pipeline(prompt=..., image=...)`同时用于T2I和编辑。`image`为PIL/np.ndarray或其**扁平列表**；同一图集共享给该batch内所有prompt | 不是每prompt一组的嵌套list；源码会拒绝嵌套list及把latent冒充图片（607–628行） |
| 多图 | 官方README/模型卡最多10张参考图；代码以顺序`<image1>`、`<image2>`…建立视觉前缀；每张图分别经VLM与VAE（240–291、657–672行） | 顺序是协议变量。README上限与Python签名是不同证据，未实测第10张/超过上限的服务行为 |
| prompt协议 | 原始模板是system `Comprehend and analyze the provided prompt.`、user指令与图像标记；直接传processor，非任意chat template（212–231、252–291行）。空prompt替为单空格 | Harness若加入角色名、翻译、长prompt扩写、目标列表或约束序列，属于适配；需保存最终编译prompt与原始prompt |
| 尺寸 | 输出W/H显式可传；源码取整到32倍数（638–642）；未传W/H时，按**最后一张条件图**比例和`output_resolution²`面积推导（630–636）；每张条件图也按自身比例调到该面积，计算尺寸四舍五入至32倍数（148–156、665–671） | 必须保存原尺寸、实际resize尺寸、输出尺寸、图序和`output_resolution`。多图最后一张可影响默认输出比例 |
| 默认冲突 | 官方README“Default Parameters”称2048×2048/2K；已核验Diffusers `__call__`的`output_resolution=1024`（533行），HF `model_index.json`没有覆盖该参数 | 这两项确实不一致，不能笼统写“2.1默认2K”。实验应显式传W/H及`output_resolution`，不依赖隐式默认 |
| 原生采样 | `num_inference_steps=40`、`true_cfg_scale=1.0`、`num_images_per_prompt=1`、`use_kv_cache=True`；可传`sigmas`、`generator`、`latents`、prompt embeddings、callbacks（511–535） | CFG仅在`true_cfg_scale>1`且negative prompt/embedding存在时启用；没有负prompt时仅设置CFG无效。此处没有`guidance_scale`/`strength`原生参数 |
| seed/重现 | `torch.Generator`或generator列表；输出噪声latent也可直接输入。官方代码明确KV缓存开关在低精度下可产生可见不同结果（590–598） | 固定seed还必须固定cache、dtype、后端/attention实现、硬件与版本；本轮未验证跨硬件/跨软件逐像素重现 |
| 颜色/透明 | 条件图先转RGBA（661–663）；RGBA的VLM副本在白底合成，VAE仍读4通道（270–277）。HF processor配置RGB、rescale/normalize、mean/std各0.5；VAE输出原生4通道 | alpha处理不是“颜色匹配”；不能无记录地把条件RGBA转RGB黑底。返回PIL保留4通道能力不代表每个prompt都会生成有意义的alpha |
| 局部/Mask | 官方README宣称可用圈、涂画标注或单独mask表达局部修改；但已核验`__call__`签名**没有空间mask参数**。`prompt_embeds_mask`是token有效位mask，不是编辑区域mask | 若传原图＋圈图/单独mask图，实际编译方式及提示词需要Harness明确定义；不能报告为“原生硬mask/inpainting接口”或自动保证ROI外不变 |
| 输出后处理 | 2.1源码853–854行仅VAE decode→`VaeImageProcessor.postprocess`；后者反归一化/截断至[0,1]并转换PIL/np/pt；PIL经×255取整uint8 | 未见原生色彩直方图/LUT/ICC恢复/颜色校正开关。裁剪再放回、alpha blend、背景恢复、颜色匹配均应计入Harness适配器 |

官方可运行方案包括BF16 Diffusers；HF文件树可见text_encoder/transformer/vae safetensors，约33.1GB整体仓库。此处仅核验发布文件与代码，不能作为已下载/已成功执行证据。Qwen发布的`PE-T2I`/`PE-I2I`为**另外的Qwen3.5-VL 9B prompt rewriting checkpoint与代码**，不属于2.1图像模型内部的默认改写；若启用，需在Adapter/系统级实验身份中单列。[Q1,Q3,Q8]

Turbo须独立：`Qwen/Qwen-Image-2.1-Turbo`是2026-10-09发布的8步checkpoint；保存的`sample_sigmas`优先于`num_inference_steps`，只更改steps数不能覆盖保存调度。原始2.1与Turbo不得放在同一profile仅改“步数”而省略checkpoint身份。[Q9]

## 4. Qwen-Image-Edit-2511：防止版本混用的对照

精确权重为`Qwen/Qwen-Image-Edit-2511`；官方模型卡使用`QwenImageEditPlusPipeline`（不是2.1的类）。卡上示例为两图列表、`true_cfg_scale=4.0`、`negative_prompt=" "`、40步、`guidance_scale=1.0`、seed 0。**这是官方示例参数，不是库所有默认值**。[E1]

已核验Diffusers commit `c60830ee365d520ab52b110dda562dd26f7b4d7f`，文件blob `8b17f17c0e3e9ccbb502bb17ecdfcdf6a2af0ee3`：签名默认50步、CFG4、`guidance_scale=None`、`max_sequence_length=512`（528–552）；默认输出按最后条件图比例、约1024²面积，尺寸按VAE倍数向下取整（645–652）；代码对prompt batch>1直接报错（681–686）；条件图分别以VLM条件尺寸和VAE尺寸处理（697–706）。没有空间mask参数；默认解码后也调用通用postprocess（887–888）。不要把2.1的Qwen3-VL、RGBA或10图描述归给2511。关于2511精确多图上限，本轮只有官方双图示例，未单独核实硬上限，记未知。[E2]

## 5. 辅助模型（简要）

### FLUX.2 Klein

`black-forest-labs/FLUX.2-klein-4B`官方卡提供真实权重入口与`Flux2KleinPipeline`运行代码，示例1024×1024、4步、guidance1、seed0；不是全家族统一默认。[F1]

Diffusers commit `c60830ee365d520ab52b110dda562dd26f7b4d7f`的`pipeline_flux2_klein.py`（blob `50fd51e283f6d81099ffa7e39d3335d653dce49b`）签名默认50步、guidance4、max_seq512（616–637），再次说明“模型推荐”与“库默认”必须区分。输入图大于1024²面积时缩至该面积，宽高按VAE倍数取整并crop预处理，首个设定的图尺寸影响未显式指定的输出尺寸（762–787）；图片/列表、generator、latents受支持；该签名未见空间mask或色彩匹配字段。VAE decode后通用postprocess（916–922）。未运行性能/质量对比。[F2]

### FireRed

官方repo已发布1.0与1.1；本轮看见的`inference.py`默认模型ID为1.0（22行），原始图片转RGB（102），`true_cfg_scale`默认4（55）、步数40（61）、seed49（49），通过cuda Generator传入，negative_prompt为单空格（128–135）。锁定repo commit `456d010bd3f9bd727f1ab7fe60838caf6ee479e6`（2026-04-03），文件blob `eac7fa42f9de0c4c1cdfee55cdf4ce391723b88b`。[R1–R3]

**原生与官方Agent必须分开**：官方脚本检测输入图>3即触发`AgentPipeline`，其结果会替换images与prompt并强制enable_recaption（107–124）；README的“10+ elements”涉及Agent自动crop/stitch，不能写成底层checkpoint原生10+图保证。启用`optimized`还会换快速pipeline，不能忽略蒸馏LoRA、量化、缓存/编译差异。主接口为QwenImageEditPlusPipeline，未核实独立硬mask或颜色恢复参数；不据第三方服务参数补齐官方未知字段。

## 6. 对HarnessIR的可用约束（研究设计建议，不是模型能力结论）

1. 把`executor_id`定义为发布者＋checkpoint/model ID＋revision＋服务端点＋推理库commit；Adapter单独记录版本。Nano Banana 2不能通过“最新版”自动变成2.1，Qwen2.1不能用2511替代。
2. 原生参数以白名单编译；字段不存在写`unsupported_in_inspected_interface`，模型专属文档缺失写`unknown`。不要把“有自然语言局部编辑”压成`has_mask=true`。
3. 每次运行保存ordered input hashes、原尺寸/模式/alpha、resize/crop轨迹、最终prompt、负prompt、输出W/H、output_resolution、seed/generator类型、step/sigma、CFG、dtype、cache/attention、工具与会话状态。这样才能区分model-aware编译改变与底层随机差异。
4. 颜色恢复、ROI crop/stitch、未编辑区硬合成、多个mask的合成方式、LLM prompt rewriting均是可审计Adapter操作。即使操作由官方示例Agent提供，也不等于checkpoint原生接口。
5. 当前无运行原始证据，不能下结论“模型A更适合局部编辑/更保色/支持更强结构约束”，也不能声称当前Qwen Adapter已提升质量。Parent已告知v0.1仅有源文件、无原始日志；本笔记没有把这份代码包装成实验结果。

## 7. 原始来源与定位

所有URL均为一手发布方、官方模型组织或官方链接指向的推理实现。行号为本轮读取的原始代码文件行号；网页采用节标题/网页行辅助定位。Git blob SHA不是commit SHA，下面明确区分。

- **G1** Google模型专页：[Gemini 3.1 Flash Image](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-image)，`gemini-3.1-flash-image`表、Versions；网页L107–118；Last updated 2026-10-09。
- **G2** Google Cloud模型专页：[3.1 Flash Image](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-1-flash-image)，Technical specifications / Parameter defaults / Versions，网页L549–669；Last updated 2026-10-22。其API支持表与Gemini Developer API不同，不能跨服务套用Interactions状态。
- **G3** [Gemini API changelog](https://ai.google.dev/gemini-api/docs/changelog)，2026-10-06节L106–111（2.1发布、2 deprecated）；2026-05-28节（GA）。
- **G4** [Gemini deprecations](https://ai.google.dev/gemini-api/docs/deprecations)，Nano Banana models表L168–179。
- **G5** [GenerateContent image generation](https://ai.google.dev/gemini-api/docs/generate-content/image-generation)，Image editing L322–327；Inpainting (semantic masking) L2634–2639；Aspect ratios and image size L2767–2818。
- **G6** [Image generation指南](https://ai.google.dev/gemini-api/docs/image-generation)，`Use up to 14 reference images`；`Controlling thinking levels`；`3.1 Flash Image`输出尺寸表L5423–5439。注意页面多处示例已变成2.1。
- **G7** [Generating content API reference](https://ai.google.dev/api/generate-content#v1beta.GenerationConfig)，GenerationConfig.seed L6160–6162；ImageConfig/response modalities相邻节。仅是通用schema证据。
- **Q1** 官方发布repo固定版：[QwenLM/Qwen-Image-2.1 README](https://github.com/QwenLM/Qwen-Image-2.1/blob/ab96caa944157ca28a4f36b695c3047549f48f98/README.md)，Introduction、News、Hosted APIs、Requirements、Multiple Reference Images、Default Parameters、Prompt Rewriting；原文对应行15–44、46–55、159–177、208–237、239–350（长prompt导致部分单行很长）。
- **Q2** [HF完整revision](https://huggingface.co/Qwen/Qwen-Image-2.1/tree/d26bb61231c349cf6b7896fa83353113880e1ba3)；[0919权重更新commit](https://huggingface.co/Qwen/Qwen-Image-2.1/commit/840b4adb1e2c21c7d77967203188b55b678c535f)，transformer两片实际LFS oid分别`9e6bc2d641e67bf277895ea8777141044a38f3edb7101bc469b2961dd7c36b4b`、`3aaf234dcbe128530479735854a346b5e3e66283b7c11db56f836bbd1c13ebaa`。
- **Q3** [官方HF模型卡](https://huggingface.co/Qwen/Qwen-Image-2.1)，Introduction/Quick Start/Supported Aspect Ratios/License；[模型卡固定revision](https://huggingface.co/Qwen/Qwen-Image-2.1/blob/d26bb61231c349cf6b7896fa83353113880e1ba3/README.md)。
- **Q4** [model_index.json固定revision](https://huggingface.co/Qwen/Qwen-Image-2.1/blob/d26bb61231c349cf6b7896fa83353113880e1ba3/model_index.json) L1–24；[processor/preprocessor_config.json](https://huggingface.co/Qwen/Qwen-Image-2.1/blob/d26bb61231c349cf6b7896fa83353113880e1ba3/processor/preprocessor_config.json) L1–39；[transformer/config.json](https://huggingface.co/Qwen/Qwen-Image-2.1/blob/d26bb61231c349cf6b7896fa83353113880e1ba3/transformer/config.json)；[vae/config.json](https://huggingface.co/Qwen/Qwen-Image-2.1/blob/d26bb61231c349cf6b7896fa83353113880e1ba3/vae/config.json)。
- **Q5** [Diffusers PR #14804](https://github.com/huggingface/diffusers/pull/14804)，Merged 2026-09-18；merge SHA `6256aa7666cedd47443adc8f82da9a10e110b09c`。
- **Q6** [pipeline_qwenimage21.py固定commit](https://github.com/huggingface/diffusers/blob/da1d3829cf08d4f329b526d89e17cc035c049d8d/src/diffusers/pipelines/qwenimage21/pipeline_qwenimage21.py)，尺寸函数L148–156；template L212–291；签名L511–535；说明L540–598；输入L607–642；RGBA/resize L657–678；decode L838–854。
- **Q7** [sampling schedule变更commit](https://github.com/huggingface/diffusers/commit/da1d3829cf08d4f329b526d89e17cc035c049d8d)，2026-10-05；[Diffusers Qwen2.1文档](https://github.com/huggingface/diffusers/blob/main/docs/source/en/api/pipelines/qwenimage21.md)，Defaults L19–20；Multiple condition images L37–46；Sampling sigmas L80–98（该文档本轮blob SHA `bf5c42ceafc02767c955d9e7e3d073b28b6f93df`）。
- **Q8** [官方prompt_rewrite代码目录](https://github.com/QwenLM/Qwen-Image-2.1/tree/ab96caa944157ca28a4f36b695c3047549f48f98/prompt_rewrite)，与README Prompt Rewriting节合看。此处未把PE执行当作已运行证据。
- **Q9** [官方Turbo模型卡](https://huggingface.co/Qwen/Qwen-Image-2.1-Turbo)，Introduction/Installation/Sampling；对应Diffusers PR [#14950](https://github.com/huggingface/diffusers/pull/14950)。
- **E1** [Qwen-Image-Edit-2511官方模型卡](https://huggingface.co/Qwen/Qwen-Image-Edit-2511)，Quick Start网页L112–140。
- **E2** [pipeline_qwenimage_edit_plus.py固定commit](https://github.com/huggingface/diffusers/blob/c60830ee365d520ab52b110dda562dd26f7b4d7f/src/diffusers/pipelines/qwenimage/pipeline_qwenimage_edit_plus.py)，签名L528–552；默认尺寸L645–652；batch限制L681–686；预处理L697–706；decode L887–888。
- **F1** [FLUX.2-klein-4B官方模型卡](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B)，Usage/API Endpoints/Using with Diffusers，网页L103–152。
- **F2** [pipeline_flux2_klein.py固定commit](https://github.com/huggingface/diffusers/blob/c60830ee365d520ab52b110dda562dd26f7b4d7f/src/diffusers/pipelines/flux2/pipeline_flux2_klein.py)，L616–637、762–787、916–922。官方reference仓库[black-forest-labs/flux2](https://github.com/black-forest-labs/flux2/tree/50fe5162777813d869182b139e83b10743caef15)，本轮未展开辅助模型benchmark。
- **R1** [FireRed README固定commit](https://github.com/FireRedTeam/FireRed-Image-Edit/blob/456d010bd3f9bd727f1ab7fe60838caf6ee479e6/README.md)，News、Model Zoo、Agent说明；[1.0官方卡](https://huggingface.co/FireRedTeam/FireRed-Image-Edit-1.0)、[1.1官方卡](https://huggingface.co/FireRedTeam/FireRed-Image-Edit-1.1)。
- **R2** [FireRed inference.py固定commit](https://github.com/FireRedTeam/FireRed-Image-Edit/blob/456d010bd3f9bd727f1ab7fe60838caf6ee479e6/inference.py)，模型默认L20–23；参数L47–62；RGB L101–103；Agent L107–124；运行参数L128–144。
- **R3** [FireRed技术报告](https://arxiv.org/abs/2602.13344)，仅作1.0身份/论文入口，不引用任何成绩。
- **P1** Diffusers通用[VaeImageProcessor当前源文件](https://github.com/huggingface/diffusers/blob/main/src/diffusers/image_processor.py)，本轮读取blob SHA `6dccc02dd5ef2910fb5694fa7ed7706064f2db53`；[固定blob API](https://api.github.com/repos/huggingface/diffusers/git/blobs/6dccc02dd5ef2910fb5694fa7ed7706064f2db53)，numpy_to_pil L129–150、denormalize L223–235、postprocess L739–787。通用类还有apply_overlay方法，但Qwen2.1/2511已核验主调用没有使用；不能因此归为模型原生mask合成。
