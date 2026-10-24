# 目标分支 engine Model-Aware 只读审计

审计时间：2026-10-24。目标 `/workspace/scratch/7d29333b7554/HarnessIR`，HEAD `e1b610ef034d467c8c9172e530d38a930956a3bb`；官方 `/workspace/scratch/7d29333b7554/HarnessIR-official`，指定 HEAD `773f19654d2d4d9a3b0ce20f80508a4dd0788aff`。本笔记只审计现状，未修改 engine，也未把用户原始单图复原任务转成参考图迁移任务。

## 结论

**这份 Model-Aware 代码是另外的、明确 opt-in 的 A+B 参考外观增强 engine，不是原始单图复原入口的模型适配层。当前不能直接用于用户单图任务。** `model_aware._bindings` 强制恰好两图 A/B（`engine/src/hre/model_aware.py:59-77`），compiler task 将 B 定义成 appearance only（`:80-86`），内置 editor 再强制两图 prediction/reference（`native_editor.py:53-64`）。`hre v2 create` CLI 的 `--reference` 必填（`reference_cli.py:8`）。没有“不传参考图的 Model-Aware 模式”。本地真实函数 probe 已报 `condition_inputs: This version requires exactly A and B, without editor masks`。

原始 `run_harness.py`→`harness.pipeline.run_sample`→`harness.stages.execute.run_execute` 调用链没有 `hre`/`model_aware`/`model_runner`/`native_editor` 接线。审计开始时 branch 与 official 的 `run_harness.py` SHA256 均为 `5beebfaf56c43d1065b4b789cb0cedf0da0e72303181cd0042abd93fc3b5ab22`；`harness/pipeline.py` 均为 `a531e9df6a06a0328cd82edcf09b6747d15c4d8c4ded2b47eb0f2e523e3c1b0a`。官方没有 `engine/` 目录。注意：根 agent 随后已开始用户授权的原始单图路径修复，以上哈希描述的是本轮初始审计时的分支状态。

`engine/pyproject.toml:6-10` 将新包命名为 `harness-ref-enhance`，说明为 “Audited offline reference enhancement controller”，独立 CLI 是 `hre`（`:15-16`）。Model-Aware 主要实现固定模型 profile、条件格式及哈希绑定、外部 worker 调度和生成记账。它**没有建立四模型真实复原质量提升**；没有实现自动模型路由、自动寻找参数、硬像素保护、局部裁切回拼、模型空间控制或正常 v2 流程中的反馈再生成。

## 对照原始五阶段：实际改变了什么

这里沿用官方五阶段：S1 诊断，S2 按需工具，S3 prompt 编排，S4 图像执行，S5 验证与迭代。原路径没有被 Model-Aware 改写；下表将新 engine 的职责对齐到这五阶段，不代表原路径已接入这些机制。Model-Aware 的新增 condition 编译位于 S3/S4 之间，不是新增一个复原算法。

| 阶段 | engine 的真实实现 | 与用户单图任务的边界、未接线内容 |
|---|---|---|
| S1 诊断 | Controller 冻结诊断请求（`workflow.py:109-119`），通过通用 stage worker 发送图片与 prompt；v2 对 Diagnose/Compose 增添 ROI、A/B 的 display statistics 与 `model_aware_planning` 布尔量（`prompts.py:464-474`）。 | `resources/v2/prompts/diagnose.j2:2` 明确 A 是 Neural ISP prediction、B 是同场景 iPhone 17 rendering reference，诊断的是亮度、颜色、色调分离等差距，而非官方 degradation restoration 诊断。该 stage 不按四个图像模型切换诊断算法；model profile 不进入诊断上下文，只有 opt-in 布尔量。 |
| S2 工具 | `run_case` 在 WAIT_EVIDENCE 调用现有 Controller.collect_evidence（`model_runner.py:157-158`）。EvidenceService 可运行 STATS 和 ROI_COMPARE（`evidence.py:425-440`），其他 T1–T4 只导入验证过的离线 bundle/cache（文件说明 `:1-4`；missing job export `:582-611`）。required evidence 缺失则暂停（`workflow.py:450-457`）。 | 没有将官方 `harness/perception` 的 OCR/face/depth/segmentation 在线推理接进此 runner。`create_reference_case` 默认 available_tools 为 STATS/ROI_COMPARE（`reference_contracts.py:189-195`）；不能把“有 T1–T4 evidence schema”说成此流程会自动跑 T1–T4。 |
| S3 编排与条件编译 | Compose 在已有 diagnosis/evidence 上约束 1–3 targets、160 英语词（`workflow.py:277-301`）；允许最多三对 distinct frozen ROI 的 `region_relations`（`:278-285`；`composition.schema.json:9-20`）。接受 Compose 后冻结 condition request 并 PAUSED（`workflow.py:338-342`）。`condition_handoff.py:31-49` 收集 edit_prompt、reference_targets、protected_content、limitations、ROI、relations、统计；`:54-78` 冻结并反复校验 source binding。 | 编排仍然是参考外观意图。直接编译只是确定性字符串渲染（`model_aware.py:303-348`），Qwen 有一段关系协调指导，FireRed 有另一段整幅编辑指导；没有训练过的 model-aware planner。四模型 native 编译器只声明外部接口，未内置 PUP/VGL/PE-I2I/Recaption 的执行器。 |
| S4 执行 | condition 接受后才发普通 execute 并 reserve generation（`workflow.py:215-225`，`:121-159`）；compiled native 文本在 execute 模板中原样透传，不追加旧通用 preamble（`resources/v2/prompts/execute.j2:7`）。`desktop.py:50-59` 输出 editor/A.png、B.png、edit_prompt.txt、condition.json。内置 `native_editor` 对 Qwen/FireRed 载本地 pinned Diffusers weights，显式 A 宽高，一次 pipe 调用（`:73-89`）。 | A+B 整幅、软文字控制。`native_editor.py:31` 只支持 qwen21/firered11；FLUX/Fibo 需要实际外部 execute worker。`active_spatial_controls` 在四 profiles 中全为空；没有 ROI tensor、mask、bbox/layout、blend/fusion。native editor 调用 kwargs 只有 image、prompt、canvas、generator、steps、CFG、negative prompt 和 Qwen 两个额外参数（`:84-88`）。 |
| S5 验证与迭代 | 输出走原有 candidate import/geometry/verify（`model_runner.py:188-207`；`workflow.py:344-366`）。Verify 是 A/B/C 外观及内容保持评估（`resources/v2/prompts/verify.j2:2-3`），选择器用 geometry pass、5类 content pass、无 critical defects、confidence≥.7、style improved（`selection.py:9-38`）。 | **正常 model-aware v2 不做反馈迭代。** G0→direct_ref，G1→agent_single，均 max_generations=1（`reference_contracts.py:5-16`、`:89-93`、`:192-195`；`resources/v2/profiles.json:4-18`）。`decide_after_verify` 对 direct_ref/agent_single 无论接受与否都结束（`workflow.py:25-30`）；只有旧 adaptive profile 才能走 refine。`resources/v2/profiles.json:31-33` 明写 adaptive_retry_enabled=false。已有 Refine 模板/worker 类型不等于 v2 已接闭环。 |

补充：现存 `_apply(refine)` 会直接 `_prepare(execute)`（`workflow.py:367-369`），而开启 model_aware 的 `_prepare(execute)` 总是优先取冻结 `compiled_` manifest（`:121-124`），没有重新编译新 Refine prompt 的路径。因此如果未来要支持 model-aware 多轮，必须同时设计新意图/编译 source 与预算流程。此为当前准入之外的潜在扩展边界，不当作已触发 bug。

## 四模型接口完成度

| profile | 条件类型 | 内置 compiler | 内置图像 editor | 当前事实 |
|---|---|---|---|---|
| flux3_klein | full_scene_caption | 无；native 外部 PUP | 无 | `resources/model_profiles/flux3_klein.json:9-17` 声明 A+B、PUP 或明确记录的 VLM+官方 i2i system prompt；没有本地 PUP 集成。 |
| fibo2_dev | vgl_edit | 无；native 外部 Bria VGL | 无 | `fibo2_dev.json:9-17` 声明真实 Thales/EditImages 路径；`model_aware.py:212-219` 只校验 JSON object 与非空 edit_instruction，未验证 target caption 的完整 native schema，也没有语义审计。 |
| qwen21 | semantic_instruction | direct 零模型调用；native 外部 PE-I2I | 有，QwenImage21Pipeline | `qwen21.json:9-17`；`:18-23` 没有 active spatial controls。native PE 结果必须 parse_ok、follow A、无 ratio override、positive_prompt 精确等于 edit_prompt（`model_aware.py:220-230`）。 |
| firered11 | edit_instruction | direct 零模型调用；native 外部 Recaption | 有，QwenImageEditPlusPipeline | `firered11.json:9-17`；Recaption 被定义成文本改写而非 A/B 图像诊断；真实 Recaption 未接入内置 worker。 |

所有 profiles 都是 `capability_status=declared_not_measured`、`validated_capabilities=[]`、`model_revision=null`（每个 JSON 的 `:6-9`）。这些是作者接口声明，不是能力测量，也不是运行时已安装或通过真实模型验证的证明。built-in editor 另外强制用户 executor settings 中 40 hex revision，不能混淆 profile 中 null 与 editor 实际需要的 pinned revision。

`validate_model_config`（`model_aware.py:45-56`）只接受固定的 profile_id/strategy/compiler，明确 “There is no automatic router”。策略 `native/shared/model_aware` 是手工预先指定的实验分支，不依据图像退化自动挑选模型。G0 限 native，G1 限 shared/model_aware，G2 不允许 model_aware（`reference_contracts.py:37-43`）。

## 参数、seed、调用与输出流程

1. `model_runner.export_worker_request`（`:48-81`）依据 Controller 当前状态导出 stage 或 condition；其 envelope 含 request、prompt、ordered attachments、executor、output_dir、bundle_path，另存请求和 bundle 文件哈希。
2. 通用 stage worker 仅接受 kind=stage（`model_workers.py:115-118`），真实请求 body 仅 model/messages/response_format=json_object（`:157-158`），**没有显式 seed、temperature、max_tokens**。HRE_VLM_BASE_URL、MODEL、TIMEOUT 由环境提供（`:122-133`）；runner 冻结该内置 worker 的非秘密 runtime（`model_runner.py:32-45`、`:150-154`），不会保存 API key。模型返回 metadata 记录 requested/returned model、usage、elapsed；不是采样确定性保证（`model_workers.py:175-196`）。
3. condition=direct 在本地 `compile_direct_condition`，compiler calls=0（`model_runner.py:100-106`；`model_aware.py:340-347`）。它**不是原生 PE/Recaption**，也不会偷换 native 为 direct。native 编译要配置 `workers.condition`，否则 `worker_not_configured`（`model_runner.py:107-111`）。普通 stage worker 不能替代 condition；给它 kind=condition 会拒绝。
4. compiler observation 必须包含 id/version/settings/calls，但观察不到时 id/version/calls 可 null；native success 只禁止可观测 calls=0（`model_aware.py:167-182`）。未知版本可能保留下来，因此仅有 schema 通过不保证完整可复现或执行的是 profile 所列原生 compiler。代码不比对 compiler_id 与 profile.native_compiler.compiler_id。
5. built-in native settings 逐项显式冻结：model_id/revision/seed/num_inference_steps/true_cfg_scale/negative_prompt/device/torch_dtype；Qwen 另需 output_resolution/use_kv_cache；num_images_per_prompt 只能 1（`native_editor.py:32-49`）。不同模型没有被强行使用共同 steps/CFG，runtime 也不自动搜索这些值。固定 seed 经 `torch.Generator(device).manual_seed(seed)` 传入（`:84-88`），receipt 记录 seed（`:103-106`）。没有“跨模型相同 seed 代表相同采样”的保证。
6. editor 校验执行 prompt=冻结 native text、A/B 文件 hash、尺寸、canvas（`native_editor.py:50-64`）；检查 executor 整个对象精确等于实际 profile 名、revision、diffusers version、adapter version、settings（`:70-72`）。以 `local_files_only=True` 载 weights（`:78-79`）；torch/diffusers 缺失或类不存在直接报错（`:65-75`）。没有自动下载。
7. 若 A 宽高不是 `vae_scale_factor*2` 的倍数则报 `native_canvas_unsupported`（`:80-83`），不缩放或 padding 修复。执行时显式 width/height=A。保存所有返回 PIL images 为 candidate_000.png、candidate_001.png…，保 provider order，正式返回第一张并在 extras 记录其余，actual_generation_count=实际返回张数（`:90-107`）。这只是一次 pipeline 调用的输出计数，不能据此断言 provider 内部 sampling。
8. `import_candidate_manual` 对超预算保留所有下载 raw outputs，计费后拒绝 formal candidate（`cli.py:98-102`）；candidate 导入后做 byte/canonical duplicate 检查（`workflow.py:350-352`）、geometry gate（`:353-356`）后进 verify。v2 冻结 strict geometry（`reference_contracts.py:92-93`），geometry 不是内容复原质量证明（`geometry.py:57-62`）。
9. 最终结果由 `selection.select_final` 选最早 accepted，否则最早 usable/review required，否则 fallback 原 A（`selection.py:46-59`）。`workflow._final_projection` 只写 `final/selection.json`（`workflow.py:435-436`）；全 runner 返回 state/budget/success，不产生一个新的“增强后 final.png”拷贝（`model_runner.py:215-217`）。原始用户单图链有其独立 results/<id>.png 输出逻辑，此处不是同一条链。

## 错误、暂停与回退

- 外部命令为 argv array，shell=False；每次仅一次，无自动重试。stdout/stderr/invocation sidecar 留存（`model_workers.py:43-105`）。timeout 会终止 POSIX 进程组（`:81-89`）。HTTP/network error 同样不重试（`:167-174`）。
- `validate_compiled_condition` 遇 status=error 抛 `condition_compile_failed`，canvas mismatch/空 prompt/native format invalid 都不能接受（`model_aware.py:185-234`）。condition 失败后仍停在原 `PAUSED/condition_compilation_required`，没有换模型、换 compiler、降级 direct 或生成图像；code 中未实现这种 fallback。
- stage 明确 error 响应会按现有 Controller 暂停（`workflow.py:321-327`）；unusable/no target diagnosis 也暂停（`:328-337`）。required evidence 缺失暂停；不会用空测量继续。
- runner 先写 started/submission_intent 再调 editor（`model_runner.py:170-178`），已有 run_dir 没有 response 或 invocation 未 succeeded 时抛 `worker_call_uncertain`，不会重跑（`:179-184`）。执行 exception 且 reservation 尚 reserved 则 mark_submission_unknown（`:209-214`）。这里“失败”不等于“无提交、可无条件重试”。
- 迟到 editor 输出（case 已暂停/取消）保留、计数但不提升成 formal candidate（`model_runner.py:196-200`）。
- 只有完成选择时、无 usable candidate 的 fallback 才是原 A（`selection.py:57-59`）；该回退不是另调一种图像模型，也不表示复原成功。`COMPLETED` 与 `success=True` 不等价（`workflow.py:87-95`）。

## 现有软件测试能够证明什么

`engine/tests/test_hre_native_editor.py:1` 明示 fake dependencies，fixture 向 `sys.modules` 注入 fake Torch/Diffusers（`:43-72`）。测试可以验证传参、单次调用、seed/尺寸/receipt/count 等契约；不能验证真实 checkpoint 可装载、pipeline 与模型兼容、编辑质量、内容保持，不能证明 model-aware 优于 shared/native。

`MODEL_AWARE.md:22-25` 明示 smoke demo 的图片与判断是 synthetic、没有 image-model call；`docs/plans/2026-10-22-model-aware-validation.md:36-43` 明示当时未装 Torch/Diffusers/Transformers/weights、没有四模型或原生 compiler inference。本轮实际 `find_spec` 也显示 torch/diffusers/transformers=False。

独立 stage-run 明确返回 validation_scope=`schema_and_condition_contract_only`、case_advanced=False、actual_model_quality=`not_established`（`model_runner.py:127-140`）。它还拒绝 execute，强制图像生成走 Controller 记账（`:130-131`）。stage-compare 是人工查看界面而非图像质量 ranking；不能因为 HTML 能显示多模型列就声称做完多模型实验。

## 可复现证据与运行记录

本地 probe：`/workspace/scratch/7d29333b7554/branch_contract_probe.py`；输出：`/workspace/scratch/7d29333b7554/branch_contract_probe.txt`。命令：

```bash
cd /workspace/scratch/7d29333b7554/HarnessIR
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=/workspace/scratch/7d29333b7554/testdeps:/workspace/scratch/7d29333b7554/HarnessIR/engine/src \
python /workspace/scratch/7d29333b7554/branch_contract_probe.py
```

结果包括单图契约拒绝、四 profile 的 full_frame_A_B/declared_not_measured/empty validated capabilities、三项模型 runtime 依赖均未安装，以及 direct compiler 对 native 请求明确拒绝 `condition_compiler: The native compiler must run externally; no native output is synthesized`。

现有 engine 全回归命令（无新增测试、禁止 pytest cache/bytecode，不改仓库）：

```bash
cd /workspace/scratch/7d29333b7554/HarnessIR
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=/workspace/scratch/7d29333b7554/testdeps:/workspace/scratch/7d29333b7554/HarnessIR/engine/src \
python -m pytest -q -p no:cacheprovider engine/tests \
  > /workspace/scratch/7d29333b7554/branch_engine_pytest.txt 2>&1
```

完整结果：**452 passed, 7 failed in 260.13s (0:04:20)**；shell 退出码 **1**，另存 `/workspace/scratch/7d29333b7554/branch_engine_pytest_exitcode.txt`。测试共 459 项。最初一次过程输出不完整、没有 summary，不计作完成结果；此处为重启后从头到尾完成的一次。

失败已读取完整 traceback 与 worker stderr，均有明确环境依赖原因：

| 失败项目 | 证据与解释 |
|---|---|
| `test_hre_model_workers.py::test_builtin_cli_runs_through_transport` | 测试 `:206` 将 PYTHONPATH 改为单独 engine/src，故 `--target testdeps` 提供给主 pytest 的依赖不再出现在 child interpreter。worker stderr 实际是 `models.py:8` 导入 jsonschema 时 `ModuleNotFoundError: No module named 'jsonschema'`；invocation 显示 0.063957s 内 returncode=1，没有 VLM 请求。失败是依赖可见性，不是模型质量/HTTP/timeout 结论。 |
| `test_hre_reference_ui.py::test_v2_panel_shows_unprobed_mask_without_enabling_control` | `streamlit.testing.v1.AppTest` 导入即 `ModuleNotFoundError: No module named 'streamlit'`。 |
| `test_hre_ui.py::test_streamlit_renders_real_case_and_pause_resume` | 同上，缺 Streamlit。 |
| `test_hre_ui.py::test_streamlit_analysis_displays_task_without_candidate_controls` | 同上，缺 Streamlit。 |
| `test_hre_ui.py::test_streamlit_execution_exposes_extra_uploads_and_explicit_order_table` | 同上，缺 Streamlit。 |
| `test_hre_ui.py::test_streamlit_explicit_new_generation_retry_after_failure_or_confirmed_release[True/False]`（两项） | 同上，缺 Streamlit。 |

环境：Python 3.12.14；pytest 9.1.1、jsonschema 4.26.0、referencing 0.37.0、Jinja2 3.1.6、NumPy 2.5.4、Pillow 12.3.0。jsonschema 等轻依赖由根 agent 放在 scratch/testdeps；不是正常安装后的 engine 完整运行环境。`engine/pyproject.toml:10` 的正式依赖列表包含 Streamlit，因此这七项不能表述成已经证实的 engine 逻辑回归，也不能把本次受限环境结果报成全绿。

worker 失败的原始证据已另存 `/workspace/scratch/7d29333b7554/branch_worker_failure_stderr.log` 与 `branch_worker_failure_invocation.json`。最小复现（不发网络请求、不加载模型）：

```bash
cd /workspace/scratch/7d29333b7554/HarnessIR
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=/workspace/scratch/7d29333b7554/HarnessIR/engine/src \
python -m hre.model_workers --help
```

复现输出与退出码存 `branch_worker_failure_repro.txt`、`branch_worker_failure_repro_exitcode.txt`。本轮最后 `git status --short -- engine` 无输出；engine 没有修改。以上所有源码适配性结论独立于单测是否通过，也不把软件测试计为图像模型质量证据。

## 补齐环境后的联合回归（2026-10-24）

按根 agent 要求，在 scratch 建立独立 `/workspace/scratch/7d29333b7554/engine-test-venv`（`--system-site-packages`），在其 site-packages 新建 `audit-testdeps.pth` 指向 `/workspace/scratch/7d29333b7554/testdeps`，因此即使测试覆盖 PYTHONPATH，worker 子进程仍能找到 jsonschema。使用 venv pip 成功安装 Streamlit 1.66.1 及其依赖；安装日志和退出码分别为 `branch_testenv_install.txt`、`branch_testenv_install_exitcode.txt`。未安装 Torch、Diffusers、Transformers 或模型权重；venv 的实际导入/version 记录在 `branch_testenv_final.json`。

联合运行现有 engine/tests 与根 tests，保留上述初始受限环境失败日志，不改 engine 源码：

```bash
cd /workspace/scratch/7d29333b7554/HarnessIR
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=/workspace/scratch/7d29333b7554/HarnessIR/engine/src \
/workspace/scratch/7d29333b7554/engine-test-venv/bin/python \
  -m pytest -q -p no:cacheprovider engine/tests tests \
  > /workspace/scratch/7d29333b7554/branch_combined_pytest_final.txt 2>&1
```

第一轮联合回归：**466 passed, 2 failed, 4 warnings in 268.00s**（共 468=engine 459+当时根 tests 9），exit=1。engine 459 项全部通过；失败是根新增的两项 raw 输出归档错误回执测试。根 agent 已确认：本次测试启动后仍在修改 `harness/stages/execute.py` 并新增测试，pytest 进程持有旧 `run_execute`，测试文件却已是更新版，产生并行编辑的版本不一致。**这两项失败是同步快照不一致，不是环境依赖失败，也不计作冻结最终代码的结果。** 原始日志和退出码完整保留为 `branch_combined_pytest_snapshot_race.txt`、`branch_combined_pytest_snapshot_race_exitcode.txt`。

根 agent 随后声明冻结所有执行源码与 tests，新增 cohort 测试后重新从头运行完整联合回归。重跑之前保存相关 tracked 修改为 `branch_tested_final_diff.patch`；对 harness、tests、research、run_harness.py、run_baseline.py 共 **32 个 Python 文件**保存 SHA256 manifest 为 `branch_tested_final_source_sha256.txt`，结束后用 `sha256sum -c` 复核，**32 个全部 OK、退出码 0**，日志为 `branch_tested_final_source_verify.txt` 与 `branch_tested_final_source_verify_exitcode.txt`。

**最终稳定版本完整结果：469 passed, 4 warnings in 268.97s (0:04:28)，退出码 0。** 这是同一冻结源码上的 engine/tests 459 项与最终根 tests 10 项联合运行；没有修改 engine 源码。完整最终日志：`branch_combined_pytest_final.txt`；退出码：`branch_combined_pytest_final_exitcode.txt`。

四个 warning 均为 storage 进程锁测试在已启动线程的进程内调用 fork 时 Python 3.12 发出的 DeprecationWarning，没有测试失败。此结果证明本轮覆盖的软件契约/回归测试通过，不证明真实图像模型可部署或复原质量提升；Torch/Diffusers/Transformers/weights 仍未安装，也未调用任何学习模型。
