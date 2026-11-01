# 服务器执行说明

本文为当前 stage_lab 的命令模板；把大写 RUN/SELECTED 等占位符替换为实际 ID。所有执行在 `feat/stage-model-lab-20261022` 工作树，记录 SHA 与本地差异。不要覆盖本地已调好的模型环境。

## 1. 准备

```bash
python -m pip install -e ./engine
hre lab --help
# 无 GPU 的工具检查，可使用已有测试环境
PYTHONPATH=engine/src python -m pytest engine/tests/test_stage_lab_core.py engine/tests/test_stage_lab_cli.py engine/tests/test_stage_lab_providers.py engine/tests/test_stage_lab_native_workers.py engine/tests/test_stage_lab_report.py -q
hre lab demo --root Data/full_stage_demo
```

这些测试不运行真实权重，不计模型效果。UI 检查用 `hre lab ui --root Data/full_stage_demo`。

复制 docs/stage_lab/models.example.json 为 models.full.local.json，按已部署环境配置 native_repo、checkpoint、command 的 Python 绝对路径和 compiler 服务。主环境无需装全部模型依赖；每个模型自己的环境安装相同 engine。VLM 配置从旧校准包复制已选项，并添加一个 provider=manual 的 `manual` 条目用于导入人工输入/外部输出。

建立以下别名，减少 C/E 误配。下例生成脚本不启动模型，先读取你已填好的原配置：

```bash
python - <<'PYCODE'
import json
from pathlib import Path
from copy import deepcopy
src=json.loads(Path('models.full.local.json').read_text())
out={k:deepcopy(v) for k,v in src.items() if k not in ['flux3','fibo2','qwen_pe','qwen21','firered11']}
for editor,compiler in [('flux3','flux3'),('fibo2','fibo2'),('qwen21','qwen_pe'),('firered11','firered11')]:
    c=deepcopy(src[compiler]);c['stages']=['compile'];out['c_'+editor]=c
    for seed in (42,43):
        e=deepcopy(src[editor]);e['stages']=['execute'];e.setdefault('parameters',{})['seed']=seed
        if editor=='flux3':
            e['parameters']['use_pup']=False
            # FLUX 的 inference.seed 若已设置，会优先于顶层 seed；必须同步。
            e['parameters'].setdefault('inference',{})['seed']=seed
        out[f'e_{editor}_s{seed}']=e
Path('models.full.aliases.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
PYCODE
hre lab init --root Data/full_stage --models models.full.aliases.json
```

各模型原生尺寸、steps、CFG 等放在 parameters.inference，Qwen 必须同时显式设置 width/height。这些值由服务器 smoke 确认，不能把旧示例值当“最优”。对于不同 case 的 A 画布，先写一份 case-specific 配置，更新模型注册，再执行该 case，保存每次实际 request；同 case 所有臂与两 seed画布一致。不要只改 width 或只改 height。

Fibo bria-vgl/FireRed Recaption 的 LLM 服务也要可用。无外网时使用官方支持的已部署服务/本地后端或可追踪的手动交接；未跑原生 C 不标通过。不运行不存在的 ROI/Mask 接口。

## 2. 注册四对 A/B，制作人工 I 与 N

```bash
hre lab add-case --root Data/full_stage --case-id c01   --prediction /absolute/path/A.png --reference /absolute/path/B.png   --task '借鉴 B 可比区域的亮度、颜色和影调，改善 A，同时保持 A 的内容、构图及合理的前背景关系'
```

c02–04 同理。N 的 instruction 只用同一简洁任务和明确角色，不能偷偷加入从模型结果反推的操作。保存在 `inputs/c01/N.json`：

```json
{"instruction":"以图 A 为编辑基底，借鉴图 B 可比区域的亮度、颜色与影调，保持 A 的内容和构图；不要复制 B 的物体。"}
```

I 文件使用下列字段（内容须针对真实图片人工填写）：

```json
{
  "instruction": "完整可执行 edit_prompt；准确涵盖下面 actions 的区域、方向、关系与保留要求",
  "actions": [{"id":"i1","region":"真实目标区域","attribute":"brightness","direction":"increase","relation":"应保持的前背景关系","preserve":["文字与物体形状"]}],
  "expected_canvas":"A",
  "roi_evidence":"人工证据文件路径"
}
```

worker 主要读取 instruction，actions 是审计依据；保证二者一致。该 I 可通过 --context 直接 C，不必先 import P。

## 3. D 与 P

按旧校准计划使用三个已选 VLM，seed17/29 分别注册别名或更新模型配置，保存结果。不要修改七套配置后却仍沿用旧 arm 名称。

```bash
hre lab run --root Data/full_stage --case-id c01 --stage diagnose --models VLM27 VLM32 VLM8
# D_shared.json = 选定 D 的 observations/relations/uncertainties；无模型名与自评分
hre lab run --root Data/full_stage --case-id c01 --stage plan   --models VLM27 VLM32 VLM8 --profile generic --context inputs/c01/D_shared.json
# 选定 planner 后，依次用四种 profile；示例为 FLUX
hre lab run --root Data/full_stage --case-id c01 --stage plan   --models FIXED_PLANNER --profile flux3_klein --context inputs/c01/D_shared.json
```

D_shared 的摘取保持事实原文，记录来源与摘取规则，不做人工增强而不说明。generic 的选定 P 是 G_RUN；各 profile 的 P 是对应 M_RUN。所有路径写入 lineage.csv。

## 4. 原生 C

```bash
# N 或 I：四个 compiler 用各自注册的 profile，不传统一 --profile
hre lab run --root Data/full_stage --case-id c01 --stage compile   --models c_flux3 c_fibo2 c_qwen21 c_firered11 --context inputs/c01/N.json
hre lab run --root Data/full_stage --case-id c01 --stage compile   --models c_flux3 c_fibo2 c_qwen21 c_firered11 --context inputs/c01/I.json
# G：同一 P 给四模型
hre lab run --root Data/full_stage --case-id c01 --stage compile   --models c_flux3 c_fibo2 c_qwen21 c_firered11 --from-run G_RUN
# M：逐个匹配；不能传四个 M_RUN × 四个 compiler
hre lab run --root Data/full_stage --case-id c01 --stage compile   --models c_flux3 --from-run M_FLUX_RUN
```

四 compiler 默认串行，每次单独记录返回 ID；每份只 C 一次。`request.prompt` 可能是外层 compile 任务，**真正 native instruction 用 native_workers.instruction(request) 提取**。保存它及对应 P.edit_prompt，避免审核错文本。

```bash
python - <<'PYCODE'
import json
from pathlib import Path
from hre.stage_lab.native_workers import instruction
path=Path('Data/full_stage/runs/C_RUN/request.json') # 替换 C_RUN
r=json.loads(path.read_text())
path.with_name('actual_compiler_instruction.txt').write_text(instruction(r))
PYCODE
```

## 5. E：一份 C 配两个 E seed

```bash
hre lab run --root Data/full_stage --case-id c01 --stage execute   --models e_flux3_s42 e_flux3_s43 --from-run C_FLUX_N_RUN
hre lab run --root Data/full_stage --case-id c01 --stage execute   --models e_fibo2_s42 e_fibo2_s43 --from-run C_FIBO_N_RUN
hre lab run --root Data/full_stage --case-id c01 --stage execute   --models e_qwen21_s42 e_qwen21_s43 --from-run C_QWEN_N_RUN
hre lab run --root Data/full_stage --case-id c01 --stage execute   --models e_firered11_s42 e_firered11_s43 --from-run C_FIRERED_N_RUN
```

同样执行 I/G/M 和其余案例。不要在已有 C 的 E 上加 --prompt-file，那会覆盖实际条件。核对 C SHA、E 实际条件、画布与输出 SHA；原生记录里没有的字段手工提取/记录，不伪造。

编译失败：E 标 upstream_failed，没有输出不算零画质。编译可执行但有语义错误：主臂保留，可继续观察 E并标注；重大错误需人工修复才能诊断 E 时新增 R，不覆盖主臂。

B2 检查另注册 c01_b2（A相同，B替换，任务字节相同）。不重新编译；从 c01-N 的结果中原样取 condition：

```bash
python - <<'PYCODE'
import json
from pathlib import Path
run=Path('Data/full_stage/runs/C_FLUX_N_RUN/result.json') # 替换为真实C ID
result=json.loads(run.read_text())
Path('condition.flux.b2.json').write_text(json.dumps({'condition':result['output']['data']},ensure_ascii=False))
PYCODE
hre lab run --root Data/full_stage --case-id c01_b2 --stage execute \
  --models e_flux3_s42 e_flux3_s43 --context condition.flux.b2.json
```

其余三个editor分别用自己的原生条件。不能跨case直接使用 --from-run；context.condition 保留原条件的角色位置A/B，图片仍按A/B顺序输入。lineage.csv填原source C ID和相同condition SHA。这里测E响应，不是重新编译后的全路径收益。

## 6. J 与报告

```bash
# 默认盲评；E_RUN 列表由预先定义子集提供
hre lab run --root Data/full_stage --case-id c01 --stage judge   --models VLM27 VLM32 VLM8 --from-run E_N_SEED42 E_M_SEED42
# 其余图只选 J_star
hre lab run --root Data/full_stage --case-id c01 --stage judge   --models J_STAR --from-run E_I_SEED43
hre lab report --root Data/full_stage --out Data/full_stage/comparison.html
hre lab report --root Data/full_stage --stage compile --out Data/full_stage/compile.html
hre lab report --root Data/full_stage --stage execute --out Data/full_stage/execute.html
```

三模型子集里的 J_star 结果直接复用，不再运行一次凑预算。J 的多个 E来源默认逐图×模型，正是本阶段需要的组合；不加 --combine-sources。action完成度由人工表填写；若额外用 action judge模式，单列额外调用，不能并入 blind J。

现有测试台不会自动 resume 去重、自动给语义评分或自动补本包CSV。先用 `hre lab runs` 检查已有run，根据执行清单补缺失。若工程人员另写批量脚本，保持这里的独立run、配对、冻结C和来源规则，脚本/参数快照随报告回传。
