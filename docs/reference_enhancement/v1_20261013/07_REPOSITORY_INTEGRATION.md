# 仓库适配与迁移说明

本轮为文档设计交付。以下是 2026-10-13 读取当前仓库源码后的工程判断，不代表用户 Windows 本地代码已具备对应能力。

## 1. 已核查的源文件

| 仓库文件 | 当前行为 | 新系统处理 |
|---|---|---|
| `harness/pipeline.py` | 单个 LQ，退化类型选评价；默认无 redo 时不跑 Verifier；各轮可执行原图颜色回拉 | 独立 `hre` 工作流；A/B 双图；每个候选验证；禁用颜色回拉 |
| `harness/stages/execute.py` | `mfm.edit([send_path], prompt)`，只传一图；可 pad 为方图，自动 resize 输出 | 新适配器声明并验证两图角色；保留 raw output；尺寸不符需明确派生规则 |
| `harness/types.py` | 根据 restoration 类别允许或锁定色彩 | 新任务明确允许 rendering 变化；不用退化类别推断色彩权限 |
| `harness/stages/compose.py` | 从退化需求与工具证据组装恢复指令 | 使用本包的新 Compose 合同；可借鉴视觉包组织方式 |
| `harness/stages/verify.py` | 与 LQ 的灰度 SSIM / chroma drift 门禁；`needs_redo` 驱动接受 | 新三态 style/content 观察；几何硬门禁与外观观察分离；Controller 决定停止 |
| `harness/selection.py` | 全部门禁失败仍选择生成图，NR 分数用于部分兜底排序 | 不得照搬；只从合格候选选图，无合格图回退 A 并标失败 |
| `configs/default.json` | `square1024=true, color_adjust=true, workers=4`；FR 指标开启 | 独立配置，默认无强制方图、无色彩回拉，工具串行；不对非对齐 B 算 FR 质量 |
| `QWEN_ADAPTATION.md` | 指向本 fork 的 Qwen 文档记录 | 本改造单独归档；后续新增 Executor 时固定 Prompt 与模型版本 |

源码 blob SHA：pipeline `5d844da47a05b9c1ff7590385ea7272e0ccdd1df`；
execute `9e04c0f8a77abfb757f44c666067c8c7c274736f`；
types `5d86b8c32593ece5ded8b8eb8e9586355151890d`；
compose `9d6b96208f0720c7d05905e188c7874d8a3d4c9a`；
verify `4b481d3c87a2a780c012cf942b0e1694677013b0`；
selection `8bee269ba75610fb42ea5d46724a3aa5b5614802`；
default config `5588a77f26af16af61d1da371e51213ed036f9b0`；
color_adjust `0c4f2ee25c30b2855f144ece39b2f587f6e7fe70`。
以上是文件对象哈希，不是版本号或新实现的 commit。

## 2. 旧 Manual 方案与新需求的关系

已读取 2026-10-12 的 Manual v1.1 设计：本地文件交接、Controller 唯一推进、离线证据缓存、T1–T4、CPU/GPU profile 分离、原图重试、模型不可用明确记录。这些作为迁移依据保留。

但本次应新建 `task_type=reference_guided_enhancement`：

- 单输入 case → prediction + reference 两个独立资产。
- degradation diagnosis → rendering gap + comparability diagnosis。
- 原恢复工具需求 → 基础统计 + 可比较 ROI + 按需 T1/T2/T3/T4。
- 原色彩保留规则 → 允许外观调整、限制结构与身份改变。
- 两图 input/result 验证 → A/B/C 三图验证。
- 退化移除 D-Score → 固定参考外观偏好与 A 内容保真双轴。
- 旧 Schema 不能被新 payload 静默覆盖；保留旧 case 的版本号和解析器。

本次查到的仓库根 `AGENTS.md`、`START_HERE.md` 返回不存在。此结论仅限读取的仓库分支，不能据此忽略工程师本地可能存在的规则或目录级要求。

## 3. 工程师本地迁移前检查

1. 读取实际工程根及上级适用的 AGENTS/START_HERE；执行 `git status`，记录当前 branch/head 与未提交文件，先备份 case 元数据。
2. 盘点 `engine/` 的实际入口、类型、case 根、Watcher、缓存注册器与 UI。按接口逐项确认可复用模块，不能把“以前交付过设计”当成“代码已实现”。
3. 新建 `engine/src/hre/`；已存在的 `hir_manual` 与 `Data` 保留。通过小适配器复用可信 IO/缓存，而不是把旧状态与新状态混写。
4. 新 case 根使用配置 `case_root`；建议 `Data/ref_enhance_cases/`。缓存根仍可配置为既有 `Data/annotations/cache/`，但只有匹配合同的证据可复用。
5. 新 reference 以新 case/revision 入组；旧 diagnosis/verification 不自动搬成新结果。原工具证据可以按冻结 asset/hash/profile 重新绑定。
6. 首先在合成夹具中验证幂等与状态，再用用户提供的一对 A/B 验证真正看图、写 JSON、两图编辑及保存。只有四项能力分别通过，才打开对应自动化开关。

## 4. 两图编辑能力探测

本包不对当前桌面 App 支持能力作未经实测的断言。工程师需保存每次探测的截图/日志/实际文件哈希：

| 探测 | 通过条件 | 失败后的可运行路径 |
|---|---|---|
| 读取任务与图片 | 同时识别 A、B 文件与身份；写回正确 task/request hash | 上传 A/B + 当前任务包 |
| JSON 落盘 | 用户指定根下实际出现可解析响应与完成标记 | 下载/粘贴 JSON 由导入器原子落盘 |
| 会话派发 | 下一阶段被支持接口送到正确、独立角色会话 | UI 显示任务包与复制/下载操作 |
| 两图编辑 | 编辑结果保持 A 场景，B 仅外观参考；反转上传顺序仍按标签正确 | 显式上传两图并标 A/B；若仍不能保角色则停止正式实验 |
| 图像保存 | 对应 task 的结果可保存至指定 inbox，Controller 能核验 hash | 用户保存一次图片再登记；不可按最新下载文件猜 task |

文件读写能力不能推出会话派发能力。图像生成完成也不能推出能写到 Windows 指定目录。可用缓存自动读取也不能推出 ChatGPT 会自动接收下一任务。

## 5. 输出几何与训练用途

V1 正式运行要求候选与 canonical A 的构图一致。若图像模型仅改变输出分辨率，可在预冻结配置 `geometry_policy=aspect_preserving_resize` 下派生评审图；raw 图不覆盖，记录原始宽高、scale、插值与派生 SHA。宽高比差异 0.5% 是拒绝初筛上界，不是允许拉伸的容忍度：V1派生到A尺寸还须 `raw_width * A_height == raw_height * A_width`，即单一scale精确匹配宽高。即使偏差小于0.5%，不满足等比例仍拒绝；不通过resize到A尺寸引入轻微非均匀warp。尺寸相同也仍需内容审查。不自动对生成图做注册、warp 或裁剪去掩盖移动。

默认 `geometry_policy=strict`，尺寸不同则拒绝正式候选。R1 能力探测后如改策略，应新配置哈希并重跑各臂相同处理。

输出只能称 reference-guided enhancement candidate。若将其用于训练，需单独核验 A/C 对齐、文字/身份、生成幻觉与数据许可，并把 scene group 与 test reference 隔离；通过本流程不自动获得 GT 资格。

## 6. 结论与归属

本系统借鉴 HarnessIR 的诊断—证据—Compose—执行—反馈结构，变更了任务、条件、Executor 和评价标准。它属于本 fork 的 reference-guided enhancement 设计，不能称原论文同模型指标复现。第一轮需要检验的假设是：在同一 ChatGPT 编辑能力与可比生成预算下，流程是否提高外观贴近度并控制内容破坏。是否有增益、能否推广到目标相机风格，均需要实验。
