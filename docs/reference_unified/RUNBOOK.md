# 统一参考迁移：安装、执行与验收

本路径以 10/26 工程为基础，将 11/1 的公开参考证据代码接入同一个 `hre` 包。新合同显式启用，历史 v3、reference_retouch_v1、reference_retouch_delivery_v2 不被迁移或改分。

这是已实现的软件路径。本文不把测试、导入的人工判断或接口配置成功当作真实风格增益；Base 域、留出、GPU 和训练标签实验仍需真实执行证据。

## 1. 一个安装包，三个互补入口

```text
python -m pip install -e "./engine[test]"
python -m hre models --help
python -m hre reference-style --help
python -m hre reference-study --help
python -m hre reference-evaluate --help
python -m hre.retouch --serve --port 8766 --runs runs/retouch
```

Windows 源码运行可设置 `PYTHONPATH=engine/src`、`PYTHONUTF8=1`。应从本仓库根目录启动；不要把另一份 reference-style-pipeline/source 放到 PYTHONPATH 前面。查看 `import hre; print(hre.__file__)` 可确认实际安装路径。

- `hre models`：真实四模型运行器，新任务选择 `workflow_contract=reference_retouch_v2`。仍需安装实际模型/编译器和配置运行端。
- Web 工作台：建案例时选择 `reference_retouch_delivery_v3`。未显式选择的新旧 API 调用继续使用旧 delivery_v2，历史案例保持原样。
- `hre reference-style`：审计来源、颜色/精度、独立区域、数值与实际提交的文件桥。新增语义记录把这条证据链接到覆盖、限制、no-op、交付和整体评价。

独立观察与 study 不会自动调用模型；使用已有真实 API 入口才会产生请求。未知后端保持 unknown，不能标成指定模型的质量实验。

## 2. 先做零调用机制检查

```text
python engine/examples/reference_unified/check_no_change.py --source /absolute/source.png --out runs/unified-no-change
```

这是明确的 A=A、仅匹配已有参考外观任务。程序用规范化像素一致性作依据，经生产新 v2 路径得到 `already_satisfied`；编译、图像与远端分析调用均为 0。它只证明这一窄机制，不证明 VLM 能识别任意“已经接近”。输出目录必须全新。

## 3. 原生运行器新路径

编辑 `engine/examples/reference_unified/task.example.json` 的真实 A/B 路径与任务要求；使用实际 runtime 配置：

```text
python -m hre models create --case-root runs/unified-001 --spec engine/examples/reference_unified/task.example.json --config /absolute/runtime.json
python -m hre models prepare --case-root runs/unified-001 --through compose
python -m hre models show --case-root runs/unified-001
python -m hre models run --case-root runs/unified-001
python -m hre models report --run runs/unified-001 --out runs/unified-001-report
```

状态顺序包含：初始诊断 → 实际证据 → evidence_review → effective diagnosis → 目标冻结 → 交付预检 → 实际条件/审计 → 生成 → **whole_image_review** → 逐目标验证 → 有依据的反馈或结束。

evidence_review 不是重命名旧诊断；旧诊断与新证据均归档。缺乏依据时保持待复核，不能让 needs_evidence 自动流入 compose。

直接确定性渲染记录真实文本 span；原生 PE/Recaption/PUP/VGL 重写需要针对最终 text/native-output hash 的语义审计。缺失、矛盾或不确定关键覆盖会停在审查，生成不能使用另一份未审计条件。

同一候选复核或待决规划审计可以导入实际观察：

```text
python -m hre models evidence-review-import --help
python -m hre models condition-audit-import --help
python -m hre models review-import --help
```

导入需要当前请求/合同/候选及前驱身份；新观察追加保存。复核不新增图像调用，也不抹掉原 unknown/失败记录。超时或结果未知仍按原操作核对，不以重试释放预算。

## 4. 工作台 delivery_v3

浏览器打开 `http://127.0.0.1:8766/`，新建时选择新合同与 `source_native` 或 `declared_working_size`。原文件和方向/颜色处理记录先保存；只有确定需要编辑，才准备编辑画布。

新路径展示证据复核、全图优先评价、原生交付和反馈。全图六轴为影调、颜色、亮度、光照自然度、材质关系与处理感；A 内容保护单列。后续局部检查必须引用这份整体观察，不能把整体 unmet/uncertain 隐藏成 accept。

VLM 与图像配置沿用 `RETOUCH_WORKBENCH.md`。没有接口时导出实际任务，由能看到对应图像的 Agent/人工完成后导入；导入来源不会改标成真实 API。真实 API 使用 A、B 顺序的双图 multipart，保留原始响应，不隐式多图择优或重试。

新编码路径区分已知源编码和仅供显示的 sRGB 假设；未知源编码不产生正式数值通过。未提供真实 C 支持或明确审核映射时，C 区域指标为 unavailable。尺寸相同不代表配准。

`source_native` 按原生有效内容检查；`declared_working_size` 是事前声明的另一任务范围。已知计划无法满足冻结要求时，在图像调用前停止；padding、放大预览和重复采样不能满足原生门槛。

## 5. 将审计证据链用于新统一语义

原有 reference-style 文件命令仍可用于历史观察。新统一任务在 `targets-freeze` 后、任何编辑尝试前增加：

```text
python -m hre reference-style semantic-freeze --root CASE --spec SEMANTICS.json
python -m hre reference-style targets-compile --root CASE --version v1
python -m hre reference-style delivery-preflight --root CASE --spec PREFLIGHT.json
python -m hre reference-style edit-export --root CASE --compiled-id ACTUAL_COMPILED_ID
```

SEMANTICS 的结构为 `version:u1`、`outcome:edit`、`target_version:v1` 与 `semantics`。后者有精确八维 coverage、与现有 targets 顺序和 ID 一致的逐目标语义，以及 delivery_requirements。每目标必含 attribute、A/B 独立观察、comparability、uncertainty、mandatory、acceptance_criterion。unknown/incomparable 不能编辑；conditional 限制必进实际提示。成功标准不是私有容忍政策。

PREFLIGHT 示例：

```json
{"semantic_version":"u1","planned_size":null,"capability_known":false}
```

未知能力明确保留 unknown，最终依真实原生文件检查；已知不足则阻止编辑导出，不消耗新的图像预约。

零编辑合同使用 `outcome:already_satisfied`、`target_version:null`、空 targets 与闭合八维覆盖；basis 绑定实际已导入 AB 诊断/报告，并明确请求只有匹配已有参考外观。然后：

```text
python -m hre reference-style complete-no-edit --root CASE
```

返回冻结 A，并单独检查交付。代码核对引用与结构，不伪称自动证明文字中的视觉判断。

新统一 C 需导入完整全图优先观察后才可通过：

```text
python -m hre reference-style holistic-import --root CASE --spec WHOLE_IMAGE.json
python -m hre reference-style holistic-import --root CASE --spec WHOLE_REGIONS.json
python -m hre reference-style holistic-import --root CASE --spec EXPLANATIONS.json
python -m hre reference-style holistic-report --root CASE --candidate-hash SELECTED_DISPLAY_SHA256 --out REVIEW.md
```

三份记录显式绑定同一 A/B/C 显示文件、实际观看条件、观察者暴露/独立性和前驱 hash。全图六轴分别保存 reference_status、相对变化方向、幅度、置信度及依据。局部数字仅解释；冲突原样保留，无默认加权、主观相抵或统计等价推断。

任一阶段的 `conflicts` 非空都阻止 accepted。需要真实同候选复核来消解时，追加记录：

```text
python -m hre reference-style holistic-resolve --root CASE --spec RESOLUTION.json
python -m hre reference-style holistic-report --root CASE --candidate-hash SELECTED_DISPLAY_SHA256 --out REVIEW-v2.md
```

RESOLUTION 使用显式 `schema_version:hre_holistic_resolution_v1`、新 `resolution_id`、原 `sample_id`、同一实际 `images`、实际 `display/reviewer`、按顺序列出的三个原始 `review_hashes`，以及精确当前 `predecessor_hash`（首次为最后一个阶段 hash，后续为上一消解记录 hash）。`resolutions` 精确覆盖所有已记录冲突；每项必须有原 `review_hash`、从零开始的 `conflict_index`、原样 `conflict` 文本、`status:resolved/uncertain/rejected`、`confidence` 和实际 `evidence`。只有独立且高置信的 resolved 才解除对应阻断；未知、拒绝、漏项、错候选、错前驱和不存在的冲突不会放行。原三个观察文件不会覆盖；消解不会重写原全图各轴或 A 损伤事实。独立评价目录对应命令为 `hre reference-evaluate resolve --root REVIEW_ROOT --spec RESOLUTION.json`。

消解后使用现有 `verify-candidate` 追加新的 `decision_id`，并在 `predecessor` 中写明上一 `decision_id/hash`；不覆盖旧判断。新观察或消解使旧通过结论过期，`label-select` 要求先完成新的精确前驱验证，不能重用过期 accepted。

若冻结 `require_detail_pass:true`，单有尺寸或整体/局部通过仍不够。导出实际原生文件及身份，再导入独立细节观察：

```text
python -m hre reference-style native-detail-request --root CASE --evaluation-id j1
python -m hre reference-style native-detail-import --root CASE --spec NATIVE_DETAIL.json
python -m hre reference-style verify-candidate --root CASE --spec NEXT_DECISION.json
```

NATIVE_DETAIL 的外层为 `evaluation_id`、精确 `predecessor_hash`（首次 null）、`resolves_hashes`（首次 []）和 `detail`。`detail` 使用 `schema_version:hre_native_detail_review_v1`、新 `review_id`，逐项复制导出 binding 的 `source_sha256/native_sha256/native_size/result_hash/evaluation_hash/selected_sha256`；另附实际 `reviewer:{reviewer_id,independence,prior_exposure}`、`display:{method:native_pixels_1_to_1 或 native_zoom,note}`、`status:pass/fail/unknown/uncertain`、`confidence:high/medium/low/unknown`、`observation`。必须实际查看绑定的原生 A/C；放大预览、自然度通过或无绑定 bool 不能替代该观察。缺失、非独立、低置信或未知保持 uncertain；独立高置信 fail 阻止交付，通过才可满足必需细节门槛。

后续细节复核也追加新 ID 与精确前驱。pass/fail 意见冲突保持 uncertain；如实际明确裁决，`resolves_hashes` 必须列出全部旧细节记录 hash，新的独立高置信观察说明裁决依据。旧观察字节保留，新证据之后必须追加新的验收决定。

也可独立使用 `hre reference-evaluate import/report` 评价其他真实候选；这不会自动赋予 style 案例的通过资格。

## 6. 六臂 study：先冻结，再运行，再盲评

完整字段示例：`engine/examples/reference_unified/study.example.json`。样例中的照片、Base 版本与观察文字必须替换为真实已核查内容；它不是既有实验结果。JSON 相对路径按配置文件所在目录解析。

```text
python -m hre reference-study build --root runs/study-v1 --spec /absolute/study.json
```

生成六臂：legacy_native_ab、legacy_shared_ab、legacy_aware_ab、retouch_shared_ab、retouch_aware_ab、legacy_aware_a。新臂确实携带 reference_retouch_v2；A-only 是 restoration，独立 brief/regions，不接收共同 B 派生评价或 baseline。运行命令保存为 `RUN_COMMANDS.md`；模型配置需实际可用。builder 本身不调用模型。

共同评价与 baseline 在任何输出之前冻结，保存在 study 中；不能从某方法生成后的执行目标复制一份当共同评价。输入域/版本、实际文件、配置、任务和计划行均有身份记录。独立 native/shared/aware 任务是包级系统比较；若要单独归因某模块，另冻共享规划或相应消融，不从主表偷推。

将实际结果绑定到计划行，缺失行继续保留：

```text
python -m hre reference-study result --root runs/study-v1 --spec RESULT.json
python -m hre reference-study blind --root runs/study-v1 --out runs/study-v1-blind
python -m hre reference-study rate --root runs/study-v1 --blind-root runs/study-v1-blind --packet-id packet_0001 --spec NEUTRAL_RATING.json
python -m hre reference-study adjudicate --root runs/study-v1 --spec ADJUDICATION.json
python -m hre reference-study report --root runs/study-v1 --out runs/study-v1/EXPERIMENT_REPORT.md
```

盲包只给中性 A/B/C 文件与共同评价；`PRIVATE_MAPPING.json` 不交给评审。冻结后的中性评分由控制器映射回实际行。方法标签盲不等于观察者从未见过图像，必须披露暴露。

RESULT 的 role：G 真实生成交付；S 明确已满足返回 A；B 失败回退；X 无有效输出；P 未完成/待核对。S 必须对应冻结 A 的实际文件；它可为 task_success，永不算 effective_edit_success。原生尺寸不足，即使评分都通过仍交付失败。

P 可以用 `predecessor_hash` 追加实际结果解析；原记录不覆盖。评分精确覆盖目标、保护、伪影与全图六轴；不同观察有冲突则保留 unknown，须有引用全部旧评分的明确裁决。baseline 不因后续意见改变。报告包含所有计划行、原始评分/裁决、未知量与固定分母，可从一份 Markdown 复算。

冲突比较的是完整决策字段：逐目标、逐保护、逐伪影、六轴、相对 A 改善、独立性、置信度及绑定细节结论。两个意见即便折成相同 true/false，也不能当作一致；导入顺序不选择赢家。`rating_conflict_fields` 明确给出分歧，冲突下 task/edit 结果保留 unknown，直到现有 `adjudicate` 明确绑定全部 ratings 并选择实际意见。评审身份与说明文字不作为数值投票。

study 的 `rate` 可增加可选 `native_detail`，内容为上面的完整 `hre_native_detail_review_v1` 观察。直接评分从冻结 study/result 取精确身份；盲包 `review.json` 的 `native_detail_binding` 提供同一绑定而不暴露方法标签。使用盲包原生 A/C，不能用改尺寸的预览冒充 native 文件。旧评分无此字段仍可读，必需 detail 保持 uncertain；增加细节证据需新 rating ID，若与已有评分的完整决策字段有分歧，再显式裁决全部 ratings。S 返回 A 仍不算有效编辑，缺少所冻结的细节证据也不会自动认证通过。

v3 `models review-import` 对历史候选只追加该候选的观察，不改变当前 round、phase、已选结果或 terminal 状态；当前候选的真实复核仍可恢复对应的反馈/待复核流程。复核不生成图像、不退还调用预算，也不会把历史候选的反馈交给另一轮执行。

## 7. 验证与效果边界

```text
python -m pytest engine/tests/test_reference_core.py engine/tests/test_reference_evaluation.py engine/tests/test_reference_study.py engine/tests/test_reference_entrypoints.py engine/tests/test_review_round1_repairs.py engine/tests/test_v3_reference_v2.py engine/tests/test_retouch_unified.py -q
python -m unittest discover -s engine/tests/reference_style -v
python -m pytest engine/tests/test_retouch_delivery.py engine/tests/test_v3_reference_runner.py engine/tests/test_v3_reference_contract.py -q
node --check engine/src/hre/retouch/static/app.js
python -m pip wheel --no-deps --no-build-isolation --wheel-dir engine/dist ./engine
```

CPU 合同、临时合成像素和真实 loopback HTTP 验证规则与传输；没有新增付费生图或 GPU 调用。需真实模型回答的问题仍是：完整系统相对 Direct 的稳定增益、参考敏感性、Base 输出域、原尺度细节和反馈的等预算收益。按已冻结 study 执行并如实保留失败/未知后才能报告这些结论。
