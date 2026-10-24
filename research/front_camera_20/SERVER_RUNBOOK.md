# 服务器执行与回传

以下命令从 HarnessIR 仓库根目录执行。先完成 [DATA_REQUIREMENTS.md](DATA_REQUIREMENTS.md)，再冻结计划。部署四模型、权重锁和原生 helper 的完整步骤沿用 [四模型运行手册](../../docs/four_model_v3/RUNBOOK.md)。本手册不自动下载或启动模型。**最终只复制粘贴一份 EXPERIMENT_REPORT.md；其他文件均供服务器使用，不作为回传附件。**

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

## 6. 生成唯一回传文档

在服务器执行：

```bash
python3 research/front_camera_20/scripts/export_text_report.py \
  --study-root /data/front20/study-v1
```

默认只生成一个文件：`/data/front20/study-v1/EXPERIMENT_REPORT.md`。脚本从现有计划与实际 report.json 读取数据，不调用模型，也不修改原始图像/运行记录。它不会凭 verifier 的 accepted/confidence 填人工画质分。

- `manifests/` 与 `manifests-extended/` 只存在一个时自动选用；两者都存在时必须加 `--manifest-dir /data/front20/study-v1/manifests-extended` 指定本次计划。
- 已有人工汇总表时，可加 `--results /data/front20/study-v1/per_pair_results.csv` 在服务器读取；该 CSV 不需要回传。主参考与无参考组必须用完整 case_root 或含 task_mode 的键对应；model 填 profile ID（如 qwen21），不能只靠重名的 aware_single 关联。usable_final 是按冻结投票/裁决得到的最终结果，不能由平均分推断；报告中注明分数是单人分、均分还是中位数。
- 默认目标文件已存在时拒绝覆盖，以免抹掉人工填写。再次导出用 `--out /data/front20/study-v1/EXPERIMENT_REPORT_v2.md`；最后只复制粘贴选定的一个完整版本。
- 不使用脚本时，直接复制仓库内 [EXPERIMENT_REPORT.md](EXPERIMENT_REPORT.md) 模板，填写同一份文件即可。

### 只需补写的人工内容

1. 确认颜色出口、工作尺寸、目标优先级、评审人数/显示条件等尚缺信息，直接写在文档里。
2. 填逐 pair/model/seed 的外观、保真、自然度与最终人评。20 对四模型共 80 行，同一格保留所有 seed；不需手动抄 320/960 行宽 CSV。
3. 写清关键失败、争议裁决、实际设置偏离与3–5个具体观察。
4. 如果直接在 Markdown 中补评分，汇总表人工评分列可标为“待按明细复算”，由接收方依据逐例记录重算；不要保留已过时的汇总数当最终结果。

然后**从 BEGIN_OF_REPORT 到 END_OF_REPORT 完整复制粘贴**。若消息长度受限，可以按顺序分段粘贴同一个文件，并标注第1/2段；不拆成多种附件。开头的报告 ID、预期行数与末尾标记用于检查是否截断。

### 必须内联、仅在服务器留存

| 写在唯一 Markdown 里 | 留在服务器，无需回传 |
|---|---|
| 实验身份、实际模型/公共VLM版本、关键参数、GPU | 完整环境/配置 JSON、权重 |
| A/B颜色与尺寸定义、baseline身份、pair→group/subject关系 | 原始 linear、prediction、iPhone原图、逐文件完整hash |
| 计划分母、技术状态、逐pair/seed评分、失败与缺失 | 原始 report.json、comparisons.csv、匿名映射与原始人评 |
| 调用成本摘要、关键异常代码、协议偏离、人工观察 | 图片/HTML、完整stack trace、condition/VGL、journal/receipt |

回传文档应当能够独立阅读，不写“结果见附件”“评分见CSV”或仅给服务器路径。完整证据继续在服务器保存；后续需要定位问题时，仍由服务器补充相关文字摘录。

**证据边界**：接收者可以核对计划、分母、配置、配对趋势和已报告人评分数；未收到图片，不能独立复核像素、肤色和人物变化。若仅回传最终裁决而没有原始评审投票，不能据此重新计算评审间一致性。实验尚未完成的部分仍写未运行/待评，不补造结论。
