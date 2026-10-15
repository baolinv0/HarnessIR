# 离线工具、图像与证据

## 工具计划

支持 `T1_OCR`、`T2_FACE`、`T3_DEPTH`、`T4_SEGMENTATION`。由 VLM 对当前照片给出 tool_plan 和理由，控制器校验 ID、去重保持次序，不用场景类别写死工具。工具选择为空是正常情况。

## metadata 统一格式

每个工具文件夹有 `evidence.json`（符合 `evidence.schema.json`），包含 canonical input_sha256、tool_id、status、实际模型名称 / checkpoint SHA、source width/height、坐标变换、原始结果与资产哈希。status 为 ok / error；零检测是 ok、detections=[]。可选模型权重 SHA 暴露时记录，未知 null。

坐标统一 canonical EXIF 方向后的图像：左上原点，x 右向、y 下向，所有 bbox 使用 [x0,y0,x1,y1]，归一化 0–1；非法 bbox 拒收。若工具输入有 resize / padding，必须记录 source_to_tool 的 3×3 仿射矩阵和 tool width/height，并由适配器反映射回 canonical 坐标；最终 detections 坐标必须为 canonical_norm。缺失变换不准用经验目测补齐。

| 工具 | 原始输出 | Composer 可见资产 | 特别注意 |
|---|---|---|---|
| OCR | 带 bbox、文字、confidence 的 JSON | 原图框选图、结构化文本 | OCR 不是 GT；不清楚的字符保持 ambiguous=true，不强迫模型猜字 |
| Face | 带 bbox/confidence 的 JSON | 人脸框选图及可选原图裁片 | 检测不到不能认定没有人脸；不生成“身份描述”作虚构监督 |
| Depth | float32 `.npy` + 可视化 `.png` + metadata | 伪彩色地图及说明 | 标明 relative/inverse/metric 深度，invalid mask、near/far 图例；不能假装单目相对深度有米制尺度 |
| Segmentation | 离散标签 PNG/NPY + label 表 | 分割地图及图例 | labels 与像素 ID 一致，背景/ignore ID 明确；缩放标签仅 nearest |

`.npy` 加载必须 allow_pickle=False，验证 shape、dtype 和有限数值。Depth 允许 metadata 标记的 invalid 区域；至少一个有效像素。标签图片不是普通照片，不通过 JPEG 保存。

工具地图由 Composer 用于区域推断，再译成原图里的自然语言位置。Executor 永远只收 canonical 与文字，不能附 depth / seg / boxes。地图输入 Composer 是官方流程的重要部分，不能只保存地图却不展示给模型。

## 图像处理与几何

保留原始 bytes 与 metadata；canonical 的 EXIF 方向与已知 ICC 转 sRGB 操作写记录。不做自动曝光、降噪、白平衡、缩放或锐化。8bit 显示域是第一阶段默认；DNG/RAW/HEIC 先在独立统一步骤导出，原 bytes 留存，不能把导出当真实 RAW 恢复。

返回图分辨率与色彩信息真实记录；无 ICC 时按本实验默认 sRGB 解释，声明这个假设。将带 alpha 的生成图片用于评价前采用固定白底处理，并同时保存原图；默认要求生成 RGB 无透明。宽高比误差超 2% → 几何不合规；不静默拉伸 / 裁切。尺寸变化在适配版允许，官方 exact size gate 差异明确记入报告。

## 静态检查与质量检查分离

文件不可解码、损坏或未知类型属于传输失败，不推进 verifier。图像可解码但场景替换、重复原图或几何改变属于算法输出，必须记入结果，不能以“文件失败”重试掩盖。

input/output 的结构 SSIM、平均亮度、颜色漂移可以作为观察量；不使用与 LQ 的 PSNR / SSIM 排序恢复质量。场景很暗时自然提亮会降低与 LQ 相似度，不能据此否定恢复。文本核对只在原图或工具证据明确可读区域执行；退化图无法知道的字符不可把生成“更清晰”当正确。

## 后续本地工具 runner 接口

`run_tool(tool_id: str, canonical: Path, out_dir: Path, config: ToolConfig) -> EvidenceManifest`。第一阶段可以只有上传适配器。将来通过固定 executable 与 argv 列表配置离线模型；禁止执行模型返回的任意 shell 字符串。工具成功文件先写临时再提交，runner 不能改 case state。
