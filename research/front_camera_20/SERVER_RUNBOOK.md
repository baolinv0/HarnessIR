# 服务器执行与回传

以下命令从 HarnessIR 仓库根目录执行。先完成 [DATA_REQUIREMENTS.md](DATA_REQUIREMENTS.md)，再冻结计划。部署四模型、权重锁和原生 helper 的完整步骤沿用 [四模型运行手册](../../docs/four_model_v3/RUNBOOK.md)。本手册不自动下载或启动模型。

## 1. 准备目录、输入与配置

```bash
git fetch origin implementation/four-model-completion-20261024
git switch implementation/four-model-completion-20261024
git pull --ff-only origin implementation/four-model-completion-20261024
git rev-parse HEAD

mkdir -p /data/front20/study-v1
cp research/front_camera_20/dataset.example.json /data/front20/study-v1/dataset.json
cp research/front_camera_20/metadata.csv /data/front20/study-v1/metadata.csv
cp research/front_camera_20/environment.example.json /data/front20/study-v1/environment.json
cp research/front_camera_20/EXPERIMENT_REPORT.md /data/front20/study-v1/EXPERIMENT_REPORT.md
```

若尚无本地分支，使用 `git switch --track origin/implementation/four-model-completion-20261024`；有未提交工作时先自行保留，不强制 checkout/reset。

填 dataset.json 的实际样本数、路径、dev/test、group_id、baseline 与颜色出口。模板的 20 对并非已收到的数据，不直接把确认字段改 true 而保留占位。若增加外部 dev 样本，`paired_count` 改成 cases 总数（例如 20 test + 4 dev = 24）；正式 N 由 split=test 计算。

`metadata.csv` 保存采集/方向/格式/分辨率等额外说明；**运行以 dataset.json 为准**。二者 pair_id 必须对应。可额外保留源 linear 和 iPhone 原文件，不将它们直接作为未知 SDR 输入。

runtime.json 使用四模型部署生成的实际配置；记录 S1/S3/S5 的公共本地 VLM，所有 arm 固定。不要在本实验目录内硬编码凭据。

## 2. 生成正式矩阵（零模型调用）

核心单 seed：

```bash
python3 research/front_camera_20/scripts/build_manifests.py \
  --dataset /data/front20/study-v1/dataset.json \
  --out /data/front20/study-v1/manifests \
  --seeds 42 \
  --check-files
```

若事先决定三 seeds 和反馈，**用下面命令替代上面的命令**，且输出到新的目录：

```bash
python3 research/front_camera_20/scripts/build_manifests.py \
  --dataset /data/front20/study-v1/dataset.json \
  --out /data/front20/study-v1/manifests-extended \
  --seeds 42 1042 2042 \
  --include-feedback \
  --check-files
```

脚本输出 main_reference.json、source_only.json、dataset.lock.json、planned_budget.json。有 dev 时还输出 pilot.json。没有 dev 时不生成空 pilot；需使用额外部署样本，或明确只做技术验证、正式质量设置已冻结。

选择扩展计划时，下文**所有** `/manifests/` 路径（包括 pilot 命令）都改为 `/manifests-extended/`；只运行一套预先选定的正式计划。

该脚本只检查已声明合同与文件字节/hash，不能识别未知颜色空间、判断人脸配对或验证“这些照片确实互相独立”。照片解码、尺寸与 ICC 在正式 case import 也会检查，但未知 linear/HEIC/HDR 应在此前处理。文件内容若在 manifest 创建后改变，实际 batch 会冻结当时读取的文件；运行前需核对 dataset.lock 的输入 hash 与实际 batch.freeze/inputs hash。不要在生成清单之后覆盖准备图。

## 3. 部署检查与 pilot

```bash
/srv/venvs/hre-edit/bin/hre models doctor \
  --config /data/front20/runtime.json
```

有 dev 数据时：

```bash
/usr/bin/time -v -o /data/front20/study-v1/pilot.time.txt \
  /srv/venvs/hre-edit/bin/hre models batch \
  --manifest /data/front20/study-v1/manifests/pilot.json \
  --config /data/front20/runtime.json \
  --out /data/front20/study-v1/runs/pilot

/srv/venvs/hre-edit/bin/hre models report \
  --run /data/front20/study-v1/runs/pilot \
  --out /data/front20/study-v1/reports/pilot
```

检查原图/参考顺序、导出颜色、镜像/方向、画布与文件 hash、native compiler 是否真实执行、所有候选/账本保留。必要的部署修复或统一降分辨率在正式运行前完成并更新版本；不能单独对某模型或某困难 test 样本调参。

## 4. 正式实验

下列路径对应核心矩阵；扩展计划请将 manifest 路径统一换成 manifests-extended，不得同时把两套当一套跑。

```bash
/usr/bin/time -v -o /data/front20/study-v1/main_reference.time.txt \
  /srv/venvs/hre-edit/bin/hre models batch \
  --manifest /data/front20/study-v1/manifests/main_reference.json \
  --config /data/front20/runtime.json \
  --out /data/front20/study-v1/runs/main_reference

/usr/bin/time -v -o /data/front20/study-v1/source_only.time.txt \
  /srv/venvs/hre-edit/bin/hre models batch \
  --manifest /data/front20/study-v1/manifests/source_only.json \
  --config /data/front20/runtime.json \
  --out /data/front20/study-v1/runs/source_only
```

可在单独终端记录 GPU 型号/驱动和显存使用：

```bash
nvidia-smi --query-gpu=name,uuid,driver_version,memory.total --format=csv
nvidia-smi --query-gpu=timestamp,index,memory.used,utilization.gpu,power.draw \
  --format=csv -l 1 > /data/front20/study-v1/gpu-samples.csv
```

第二条会持续记录，结束后在该终端停止。这是 1 秒采样，不是精确瞬时峰值；`/usr/bin/time` 只提供该命令的进程 wall/CPU/RSS 等，不提供 GPU 显存。

中断后按原 manifest、runtime、目录使用 `hre models batch ... --resume`。若出现 `submission_unknown`，先检查真实 worker/服务结果并按原运行手册 reconcile，不能当作未执行盲目重试。参数/输入变化必须新建实验版本，不能编辑已有冻结 case。完整失败/重试计入实际成本。

## 5. 导出机器报告与匿名人评包

```bash
/srv/venvs/hre-edit/bin/hre models report \
  --run /data/front20/study-v1/runs/main_reference \
  --out /data/front20/study-v1/reports/main_reference

/srv/venvs/hre-edit/bin/hre models report \
  --run /data/front20/study-v1/runs/source_only \
  --out /data/front20/study-v1/reports/source_only

python3 research/front_camera_20/scripts/prepare_blind_review.py \
  --report /data/front20/study-v1/reports/main_reference/report.json \
           /data/front20/study-v1/reports/source_only/report.json \
  --out /data/front20/study-v1/review \
  --seed 20261024
```

评审者只读取 `review/reviewer/`，包含离线 index.html、随机命名图像、ratings.csv 和说明。组织者保留目录外 private_mapping.json，正式评分和盲态争议裁决完成后才解盲。脚本只在评审端为 A-only 结果补同 pair 的 B；不会把 B 注入推理流程。

每位评审复制一份 ratings.csv，填写不同 rater_id；评分留空初始，usable 留给汇总规则。不能把自动报告的 accepted/confidence 复制成分数。同 pair 字节完全相同的模型结果可合并评分 trial，但映射保留所有 run；它们仍是不同计划运行，统计时也不能当独立场景。

原始图 baseline 每 pair 独立加入。技术失败但有有效选中交付图时仍可做人眼质量诊断，技术主终点保持失败。source_baseline 回退和无有效交付不伪装成模型结果。匿名工具只知道传入报告，**必须对照 planned_budget 与实际清单补齐完全没有报告的任务**。

注意：匿名工具需要每个可评 pair 的 B；若参考报告整体损坏/缺失，先修复导出或保留该 pair 为缺失，不拿另一场景 B 替代。

## 6. 填报告与回传

填写 EXPERIMENT_REPORT.md，补齐本目录提供的 `per_pair_results.csv`、`review_adjudication.csv` 和 `failures.csv`。这些表是人工汇总模板，脚本不会自动推断真实画质、bootstrap 置信区间或模型排名。

推荐回传以下内容：

| 内容 | 用途 |
|---|---|
| EXPERIMENT_REPORT.md、metadata.csv、environment.json | 理解实验事实和局限 |
| dataset.json、manifests/ 内所有 JSON、实际 runtime 身份 | 重建计划与输入，识别数量/颜色/配置变化 |
| reports/main_reference 与 reports/source_only 整个目录 | 含 report.json、comparisons.csv、index.html、images；离线复核结果 |
| 全部 ratings、private_mapping、裁决、逐例/失败表 | 重算人评汇总和完整分母 |
| 时间、GPU samples、错误日志 | 成本、部署与失败分析 |
| batch.freeze.json、batch.state.json、planning/ | 共享意图、配对与运行身份 |

完整 `runs/`、所有原生输出、condition、receipt、journal 及原始高精度输入继续保留在服务器。报告目录不包含全部日志；需要追查时可据 case_root 返回指定 run。不要只回传截图、最佳输出或填好百分比的汇总表。

在回传前处理实际 runtime 文件中的凭据值；保留字段和模型/参数/版本，凭据本身不需要用于结果分析。
