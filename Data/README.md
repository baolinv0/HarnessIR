# HarnessIR 真实拍摄测试集：当前实际 164 个输入

基础 84 个输入 + 新增 Hard Cases 80 个输入（人像40、真实长焦/光学跨焦段40），已合并在同一个 Data 目录。目标280，基础部分仍差116；不能把目标数量当已下载。新增原定 LICAM/RealMCVSR 来源配额尚未兑现，实际替换记录见 [HardCases/README.md](HardCases/README.md)。未运行 HarnessIR。

主清单有164条，74个参考文件（基础44 + 设计师闪光风格目标15 + 光学跨焦段HR15），另15个人物Mask。包含4条基础补充记录的实际图片文件总数259。不同参考类型不能混作保真GT。22张 WildDark 的独立拍摄事件待核查，164是输入数量，不是164个已严格证明统计独立的事件。

| 来源 | 实际主输入 |
|---|---:|
|Wikimedia Commons|8|
|DPDD|8|
|LIVE Challenge|16|
|LOL-v2 Real|10|
|RealBlur|10|
|RealSR|8|
|RELLISUR|8|
|SPAQ|16|
|COZ|15|
|Wikimedia Commons portrait fallback|3|
|RAIM2026 AI Flash Portrait|15|
|ReWiTe|25|
|WildDark-Face|22|

从 [index.html](index.html) 浏览实际基础与新增图片；[manifest.csv](manifest.csv) / JSON / JSONL 是合并清单；[harness_manifest_no_gt.json](harness_manifest_no_gt.json) 是164条官方兼容输入清单，不含GT/Mask/ROI。新增80条输入单独见 [HardCases/harness_manifest_no_gt.json](HardCases/harness_manifest_no_gt.json)。

新增样本说明、粗ROI、采样和专项评审见 [HardCases/README.md](HardCases/README.md)、[HardCases/roi_manifest.json](HardCases/roi_manifest.json)、[HardCases/TEST_PROTOCOL.md](HardCases/TEST_PROTOCOL.md)。原84样本字节未改，合并前清单和说明保存在 `versions/base84_before_hardcases/`。

以下是基础84子集的来源说明，其中数字仅指基础部分；根目录运行清单现在为164输入。

# 基础84子集来源说明

整理日期：2026-10-12（Asia/Shanghai）。本目录含 **84 个去重主场景、44 个参考 GT，共 128 张主集图片文件**。这是已经落盘的代表性子集，不是上一轮计划的 200 场景全集，也没有运行 HarnessIR 或生成性能结论。

| 来源 | 实际主场景 | 实际 GT |
|---|---:|---:|
| DPDD | 8 | 8 |
| LIVE Challenge | 16 | 0 |
| LOL-v2 Real | 10 | 10 |
| RELLISUR | 8 | 8 |
| RealBlur | 10 | 10 |
| RealSR | 8 | 8 |
| SPAQ | 16 | 0 |
| Wikimedia Commons | 8 | 0 |

## 开始使用

1. 用浏览器打开 `index.html`，按来源和属性查看实际输入、参考 GT、许可、尺寸和证据限制。
2. `manifest.csv`（UTF-8 BOM）适合 Excel；`manifest.jsonl` / `manifest.json` 适合程序。路径均相对于本目录，可搬迁。只统计这三个文件中的主集记录。
3. `harness_manifest_no_gt.json` 是当前官方 HarnessIR 可直接读取的 `lq/prompt` 格式，使用本机目标目录绝对路径，不含 GT 或退化真值标签。搬迁后用 `scripts/export_harness.py` 重导出。`run_queue.jsonl` 含每场景输入路径、固定通用请求和目标输出尺寸；没有 GT 路径，避免评测参考进入恢复系统。
4. `protocols/SAMPLING.md` 说明抽样、去重、来源缺口；`protocols/TEST_PROTOCOL.md` 说明公平比较、预处理、GT 使用和统计。
5. `templates/run_log.csv` / `templates/review.csv` 是空白评测表，不能视为实测结果。`scripts/validate_dataset.py` 可重新检查路径、哈希、图片解码和尺寸。

## 真实性与分辨率边界

本次没有人为加噪、模糊、雾、JPEG 重压缩或合成低光。受控数据的退化由拍摄曝光、镜头散焦或光学倍率形成；公开发布前的裁剪、配准、相机 ISP 和转换另列在 `preprocessing`。`capture_evidence` 是证据说明，不等于证明所有文件未经编辑。

- **LOL-v2 Real**：下载的输入及 GT 已与作者 `LOL-v2.zip/Real_captured/Test/Low|Normal` 对应成员逐字节核对一致；未选 Synthetic。原发布图约 600×400，不是相机 RAW。
- **LIVE Challenge**：官方 Box 压缩包 SHA1 匹配 `4a3dd319865de20f3ccf8ea94ff14db766015ff4`。按官方图像名关联 MOS 后剔除 7 张观察者练习图；主集 16 张来自正式 1162 图。发布图为 500×500，不能替代原尺寸传感器细节测试。
- **Commons**：8 张为网站原尺寸上传文件，逐文件核对 Commons 源 SHA1，保留作者和具体许可。桥梁图 commons_003 内含 MPO 辅助帧，保持原字节以 .jpg 命名，清单记录真实格式；模型需要时按固定规则导出主 RGB 帧。原尺寸上传文件不保证相机直出；手机 ISP、HDR、降噪和既有后期均可能存在。`commons_001` 的来源声明日期和 EXIF 日期冲突，两个日期都保留。
- **SPAQ**：16 张 JPG 来自仅涵盖城市/室内类别的社区未修改导出，文件哈希符合镜像 LFS，多数保留手机 EXIF。原作者 Google Drive 入口 404，因此与原作者文件逐字节核对仍待完成；没有 MOS、全部 66 机型的平衡抽样。另两个作者 PNG demo 放在补充清单，不计主集。
- **RELLISUR**：8 个独立序列，真实 Canon EOS 6D 拍摄；当前是公开 `Test_crop`，624×624 输入、2496×2496 GT 的光学 4×配对。不是原相机整幅照片。官方 8.86GB 原包 Range 请求 403，社区镜像哈希已核对，原档身份比对待补。
- **RealSR**：Canon/Nikon 各 4 个场景，只用 Test 的 4×尺度，保留 V3 发布的配准裁剪图。不能把同场景其他倍率或裁剪另计。官方原包逐字节核对待补。
- **DPDD**：8 个完整视野单张 combined RGB 输入，没有左右双像素视图；GT 按作者 `test_src.npy/test_trg.npy` 精确配对。社区 PNG 是 1680×1120、16 位，源论文相机整幅为 6720×4480；这里是缩小后的转换版本。镜像 SHA256 已核对，但不能作原尺寸 DPDD 复现。
- **RealBlur**：10 个不同 `sceneNNN`，只取真实模糊输入及同编号目标；没有 BSD-B、GoPro 或模型输出。社区 ZIP 成员 CRC 和图片解码已验证。镜像没有说明 R/J 变体，原作者版本身份尚待核对；报告为“RealBlur 镜像代表性子集”，不能直接冒称论文 RealBlur-J/R 基准。

**文件完整性与来源身份是不同检查。** SHA/CRC 通过说明收到的文件完整，不自动证明社区文件与原作者发布一致。50 个主场景的社区镜像原档身份还待确认；26 个 LOL/LIVE 场景有官方包身份核验，8 个 Commons 场景有网站原图校验。逐条状态在 `source_identity_status`。

## 许可与来源

逐条作者、来源页、下载 URL、许可和许可证据保存在 manifest；`ATTRIBUTION.md` 汇总引用。LIVE 完整原始版权声明保存在 `evidence/LIVE_LICENSE_and_README_original.txt`。RELLISUR/RealBlur 采用作者明确的数据 CC BY 4.0；Commons 各图单独许可。**SPAQ、LOL-v2、RealSR、DPDD 的照片数据权利未从作者资料中完整确认，不能把镜像或代码仓库的 MIT/Apache 标签当成照片许可。** 如需公开再分发，先解决这些逐条待核查的条款。

`source_status.csv` 和 `download_issues.json` 记录访问失败、访问方式替代和未完成核查。上轮 ZIP/index 的 sandbox 云附件未能从本机访问，本次沿用了可取回的 8 个优先 Commons 文件名并重新核验。未知的 9 个补充候选未臆造，也没有计作下载。

## 文件布局

```
inputs/<来源>/...          主集实际输入文件
gt/<来源>/...              主集实际参考文件
manifest.csv/json/jsonl    主集元数据，唯一计数入口
run_queue.jsonl            恢复输入与请求，不包含 GT
index.html + thumbnails/   本地浏览索引
supplementary/             两个官方 SPAQ demo、两个 LOL 重复候选
supplementary_manifest.*   已下载但不计主集
dedup_report.json          场景排除与哈希筛查记录
source_status.csv          每源已收到数量与限制
download_issues.json       失败入口及待核查项
evidence/                  来源、许可、官方映射等证据
protocols/ + templates/    抽样、测试及记录模板
scripts/                   路径及完整性验证脚本
verification_report.json  本机最终检查结果
```

推荐以“不处理 / 相同执行器直接恢复 / HarnessIR 单次 / HarnessIR 显式 redo”分组比较。当前数据可用于第一轮诊断，但不能据此宣称日常手机恢复全面领先；尤其社区身份待核、公开裁剪/缩放、场景覆盖缺口要单列。
