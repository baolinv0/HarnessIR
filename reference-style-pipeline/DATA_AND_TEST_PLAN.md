# 可利用的数据与测试计划（私人数据不随 Git 发布）

## 1. 数据在哪里、哪些真的跑过

用户指定私有 Google Drive 的 **10.29 / Camera0717**，S26 与 Iphone17/iP17 两组手机 RGB。公开仓库不含 Drive ID、token、私有下载链接，也不包含照片、生成候选图或 mask。请在自己的授权 Drive 中按下列文件名查找，手动下载到被 `.gitignore` 排除的 `private_data/Camera0717/`；归档相对文件夹名为 `S26/`、`iP17/`，实际 Drive 显示名称可能不同，**以文件名和 SHA256 为准**。

|角色|归档相对文件名|新版实际试验状态|
|---|---|---|
|A01|`S26/20260625_165113_AI_PHOTO_FRONT_DAY_HDR.jpg`|已做输入审计、实际证据、对话生成及三轮归因|
|B01|`iP17/1.jpg`|A01 的未配准参照，同上|
|A07|`S26/20260625_170358_AI_PHOTO_FRONT_DAY_HDR.jpg`|文件字节/元数据本次复核，**未跑新版试验**|
|B07|`iP17/7.jpg`|同上，可作为候选留出，不已有结论|
|A19|`S26/20260625_185324_AI_PHOTO_FRONT_LOWLIGHT_HDR.jpg`|文件字节/元数据本次复核，**未跑新版试验**|
|B19|`iP17/19.jpg`|同上，低照候选留出，未已有结论|

六个原始 SHA256、大小、格式、ICC、方向和实际验证状态见 `examples/available_camera0717_data.json`。本次确实在现有私有恢复文件上重新计算六个原始文件哈希，与历史清单一致；只是读取字节/元数据，没有新生成/归一化/推理。不要被旧历史文件里的 `local_materialized:false`（早期尚未恢复）误导；它是历史而非当前状态。

这些 A 是 **camera_rgb**，Base version 必须 null；并非当前生产 Base 输出。iP17 是用户指定文件夹来源，B 原图 EXIF 不提供完整拍摄机型/时间证明，不能编造设备或同时刻证据。图对同场景，但不同姿态/视角/可见范围，不视为对齐、同像素对应或训练真值。未来验证生产目标需要另取有真实 Base lineage 的 A，不替换或伪标这组数据。

## 2. 原始编码与正确入口

- 三张 S26 A：RGB JPEG，3056×2296 原始栅格，EXIF orientation **8**，嵌入 `DCI-P3 D65 Gamut with sRGB Transfer`。先解方向，输出为2296×3056。
- B01/B07：RGB **MPO**，各8帧；B19为2帧。主帧2316×3088，orientation1，嵌入 Display P3。扩展名`.jpg`不代表单帧/sRGB。
- 当前入口要求 **B 是已知 sRGB**；不能把 P3 文件改标签直接喂入。先独立选择 primary SDR frame0，按EXIF方向，真实源ICC→sRGB RGB8，记录工具/版本/profile/intent/flags/精度、无 resize/crop。不会合成额外MPO/HDR帧。本实验是受控较窄色域sRGB8流程，不是完整P3/HDR保真证明。
- A01已用 Pillow13.0.0/LittleCMS2.19，intent0 PERCEPTUAL、flags0、无黑点补偿；这是历史兼容选择，不声称最优gamut mapping。源不变，保存 full-res PNG/目标ICC、不带未应用EXIF。

### A01 已用 canonical 的可核验身份

|文件|尺寸|SHA256|
|---|---|---|
|`A01/A_srgb8.png`|2296×3056|`45fde436c1dded521d1bd7e3fccd48b413fbae9ea5eb03ca1573a36e990f0568`|
|`A01/B_srgb8.png`|2316×3088|`9e7d4adec9ada04f100314598500583ae24ffb72c148f91ad69296e49cf1f374`|

目标 ICC 是无照片信息的标准 profile，随包 `examples/profiles/target_srgb.icc`，SHA `ce307a089eca5a63e415744432365a0a4593fd49e282abd1cf69a239078f6b19`。完整公开技术摘要在 `examples/A01_CANONICAL_REFERENCE.json`。

恢复同一 canonical 时必须**载入已序列化的目标 ICC 文件**；历史直接使用内存 `createProfile('sRGB')` 路径与 serialize/reload 路径在约0.5%像素有最大1代码级差异。虽然很小，也使旧 mask 的 exact input 绑定失效；我们后来在当前 canonical 上真实重新分割。不能只看尺寸一致就复用历史缓存。

重建步骤：用现有图片工具打开原图→seek(0)→EXIF transpose→读取原嵌入ICC并使用上述已序列化目标ICC做 `profileToProfile(..., outputMode='RGB', renderingIntent=0, flags=0)`→清理导出EXIF→PNG `compress_level=6` 且嵌入目标ICC。具体保存与解码库版本影响字节，**必须比对哈希/像素，不承诺其他机器自动byte-exact**。若不一致，保存新明确身份/转换清单并重建其支持，不改写旧记录冒充相同输入。

禁止把端点0/255占比直接当精确裁剪率。RGB8→高精度数组不能恢复被量化或裁掉的色彩信息。

## 3. 现有证据/工具可用性

A01实际用过 isolated MediaPipe0.10.21 CPU，6类 person segmentation；hair、body skin、face skin、clothes 是当前图真实 native category 支持，face 含眼/唇/镜片、clothes 含肩带，并非纯材料。柜体/顶板/主灯箱是明标的 model-authored coarse manual_annotation，不冒称MediaPipe或人工GT。深度、OCR没有实际缓存，明确unavailable。没有发布任何模型或mask；在新环境需要官方包/可信模型来源、重新核对hash和许可，再真实运行；不能伪造历史cache。

生成 C 没有ICC/sRGB颜色声明，仍 unknown；探索数字明确假设sRGB而非正式验收。未来实际模型若提供可靠编码契约，另行记录依据；不把RGB模式当sRGB证明。

## 4. 下一测试顺序

1. **纯代码**：按 START_HERE 跑175项与CLI。实现新的整体优先评价合同后加专项测试，不只复跑旧套件就宣布新评价通过。
2. **整体评价优先**：现有A01候选可用于反馈知情开发/回归；先看整体B接近度、影调/光照自然度/材质关系，A保留另列，再关键整区域与局部数字解释。历史看过/被用户纠偏的图不能叫独立盲验证。
3. **候选留出**：A07/B07、A19/B19目前只确认文件/元数据，需重新审计归一化、支持、可见度，再制定独立评价与有限调用计划；不要声称已经跑过或保证同一策略稳定。
4. **真正生产域**：另取真实Base输出A与合规B，记录Base版本和来源，独立建样本。Camera RGB结果不能外推成Base域结果。
5. 需要探查参考响应时可另提B=A no-op/不同参考对照；当前没跑，也不是比改进评价更优先的自动下一步。

每次真实试验先冻结输入/目标/预算、保留原始输出与真实提交记录；未知调用先解决现有回执，不重复出图凑数量。代码可控的是本地导出请求数量，不是费用或provider内部随机性。
