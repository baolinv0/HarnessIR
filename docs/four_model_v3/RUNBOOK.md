# 四模型服务器部署与运行

这份运行手册对应 `hre models` / `hre_task_v3`。完整设计见 [DESIGN_AND_COMPLETION.md](DESIGN_AND_COMPLETION.md)。命令从仓库根目录执行；代码本身不下载权重、不猜测模型 revision、不在失败时换模型。

## 1. 部署环境

建议将 Qwen PE 与图像模型分成两个 Python 环境：官方 PE 使用 Transformers 5.4.0，而 Qwen 2.1 图像说明要求至少 5.17。默认示例已为 compiler/editor 配置仓库自带的常驻 worker，不需要另写模型脚本。

| 环境 | 用途 | 固定/候选版本 |
|---|---|---|
| `/srv/venvs/hre-pe` | Qwen 官方 PE-I2I | Transformers 5.4.0；其余见 `requirements-native-pe.txt` |
| `/srv/venvs/hre-edit` | 四个 editor、FLUX PUP、FireRed 文本 Recaption、FIBO 本地 Thales compiler | Diffusers 固定 commit `aaf57d03a3edfbd9de457d2872417a92f149a91d` / `0.42.0.dev0`，Transformers 5.17.0 |
| 已部署本地 VLM endpoint | S1/S3/S5、FireRed 文本改写、FIBO VGL | 明确 `base_url`、实际服务 model 名称和采样配置 |

图像 worker 使用 Python 3.11 或以上。以下 CUDA 12.8 / Torch 2.10.0 命令是依据上游接口选择的部署组合，尚未在本交付环境进行 GPU 整栈验证；服务器可按自己的 CUDA 环境选择匹配的 Torch 构建并记录最终环境。

```bash
python3.11 -m venv /srv/venvs/hre-edit
/srv/venvs/hre-edit/bin/python -m pip install --upgrade pip
/srv/venvs/hre-edit/bin/python -m pip install torch==2.10.0 torchvision==0.25.0 --index-url https://download.pytorch.org/whl/cu128
/srv/venvs/hre-edit/bin/python -m pip install -e ./engine -r engine/requirements-native-image.txt

python3.11 -m venv /srv/venvs/hre-pe
/srv/venvs/hre-pe/bin/python -m pip install --upgrade pip
/srv/venvs/hre-pe/bin/python -m pip install torch==2.10.0 torchvision==0.25.0 --index-url https://download.pytorch.org/whl/cu128
/srv/venvs/hre-pe/bin/python -m pip install -e ./engine -r engine/requirements-native-pe.txt
```

PE 实际走 Transformers，不需 vLLM。FireRed 的本地文本编译器不需 Gemini SDK。FIBO 的官方包导入依赖仍需要安装，但运行 transport 不进入其 gateway。

### 锁定上游 helper

以下 checkout 用于原生消息、模板、schema 和 parser，不承担图像模型下载。

```bash
git clone https://github.com/QwenLM/Qwen-Image-2.1.git /srv/upstream/qwen21
git -C /srv/upstream/qwen21 checkout ab96caa944157ca28a4f36b695c3047549f48f98

git clone https://github.com/FireRedTeam/FireRed-Image-Edit.git /srv/upstream/firered11
git -C /srv/upstream/firered11 checkout 456d010bd3f9bd727f1ab7fe60838caf6ee479e6

git clone https://github.com/Bria-AI/vgl.git /srv/upstream/fibo2_dev
git -C /srv/upstream/fibo2_dev checkout 8211c2cdbc4c1a2bd78b51e40ffbc8e6c751f6f8
/srv/venvs/hre-edit/bin/python -m pip install -e /srv/upstream/fibo2_dev
```

实现会验证 checkout HEAD、所用 tracked files 和实际 hash。部署后不要在这些 helper 文件中临时修改模板；需要变化时显式形成新的 adapter/runtime 身份。

### 部署本地权重

| 路径示例 | checkpoint 身份 |
|---|---|
| `/srv/models/qwen21` | `Qwen/Qwen-Image-2.1` |
| `/srv/models/qwen21_compiler` | `Qwen/Qwen-Image-2.1-PE-I2I`，含 `system_prompt.txt` |
| `/srv/models/firered11` | `FireRedTeam/FireRed-Image-Edit-1.1` |
| `/srv/models/flux3_klein` | `black-forest-labs/flux-3-image-klein`，distilled |
| `/srv/models/flux3_klein_compiler` | `black-forest-labs/flux-3-image-klein-pup` |
| `/srv/models/fibo2_dev` | `briaai/Fibo-2.0-dev` |

使用实际模型仓库的 40 位 commit 下载完整快照。图像权重、PE/PUP 权重和代码 commit 是不同身份，不能互相代填。FLUX 必须把图像执行所需的组件放在明确本地目录，不能依靠另一个 Hub cache 的同名组件。

例如先设置真实的 `HRE_QWEN_IMAGE_REV`，再执行：

```bash
hf download Qwen/Qwen-Image-2.1 --revision "$HRE_QWEN_IMAGE_REV" --local-dir /srv/models/qwen21
```

这属于部署准备步骤；运行 worker 强制本地模型加载，缺文件直接报错。

## 2. 生成并编辑完整配置

```bash
/srv/venvs/hre-edit/bin/hre models init --out server-config
```

生成四个文件：

- `runtime.example.json`：四模型 compiler/editor、独立 worker 环境、共享 stage endpoint。
- `restoration.example.json`：仅 source 的单图复原。
- `reference.example.json`：A/B 外观参考增强。
- `batch.example.json`：四模型 × 三种策略的默认对比矩阵。

将 `SET_*` 替换为真实 checkpoint revision 和服务 model 名称，调整本地路径与 device。示例没有虚构 checkpoint revision；未修改时 doctor 会列出缺项。配置中的相对文件路径以配置文件目录为基准，运行时冻结为绝对路径。

Stage endpoint 示例：

```json
{
  "base_url": "http://127.0.0.1:8000/v1",
  "model": "实际部署的视觉模型名称",
  "timeout_seconds": 600,
  "response_format": "json_object",
  "settings": {"temperature": 0, "max_tokens": 8192}
}
```

如果服务需要认证，添加 `api_key_env` 指向已设置的环境变量。不要把密钥直接写进冻结 JSON。FireRed compiler 只会发送文本；FIBO 和各视觉阶段发送图像。未配置 endpoint 时不会使用厂商云服务默认值。

### 冻结本机权重清单

`models lock` 会读取实际文件，首次需要遍历权重。输出路径应放在 checkpoint 目录外，并在相应 runtime 增加 `deployment_manifest`。

```bash
/srv/venvs/hre-edit/bin/hre models lock \
  --path /srv/models/qwen21 \
  --model-id Qwen/Qwen-Image-2.1 \
  --revision "$HRE_QWEN_IMAGE_REV" \
  --out server-config/qwen21.deployment.json
```

其余五份图像/编译权重同理。清单绑定本机文件大小、mtime 和 SHA256；正常启动校验元数据，变动文件重新哈希。需要完整重哈希时在 runtime 设置 `verify_weight_hashes=true`。清单证明本机文件已冻结，不独立证明声称的上游来源。

### 无推理预检查

```bash
/srv/venvs/hre-edit/bin/hre models doctor --config server-config/runtime.example.json
```

可用 `--profile qwen21` 只检查一个模型。doctor 会在各自 worker Python 环境检查 package、checkpoint、upstream helper、关键 Diffusers 源文件、配置与 endpoint 格式，不加载权重也不发送模型请求。`ready=false` 时从 `issues` 找缺项；不要靠修改 version 字符串绕过源码不匹配。

## 3. 单图或 A/B 运行

先修改任务文件中的 source/reference 路径及 brief。引用增强 brief 应指向外观变化；单图复原则写明需要修复的退化。

```bash
/srv/venvs/hre-edit/bin/hre models create \
  --spec server-config/restoration.example.json \
  --config server-config/runtime.example.json \
  --case-root runs/qwen-restoration-001

/srv/venvs/hre-edit/bin/hre models dry-run --case-root runs/qwen-restoration-001
/srv/venvs/hre-edit/bin/hre models run --case-root runs/qwen-restoration-001
/srv/venvs/hre-edit/bin/hre models show --case-root runs/qwen-restoration-001
```

`dry-run` 是零模型调用的合同摘要。`prepare` 与之不同，会实际执行指定范围内的 VLM/原生编译，但不生成图像：

```bash
/srv/venvs/hre-edit/bin/hre models prepare --case-root runs/qwen-restoration-001 --through compose
```

`--through compose` 停在已冻结 intent；`--through condition` 还会调用原生 compiler。之后 `run`/`resume` 接续运行，不重复已完成阶段。

更换模型时，为新 case 将 `profile_id` 改为 `firered11`、`flux3_klein` 或 `fibo2_dev`。已创建的 task/config 不原地修改；新的参数对应新的 case revision。

### 三种初始条件策略

| strategy | 输入给 compiler 的内容 |
|---|---|
| `native` | 原始 brief、任务角色和冻结输入，不取得 Harness intent |
| `shared` | 同一冻结 EditIntent 的公共表达 |
| `model_aware` | 同一冻结 EditIntent 加模型原生表达指导 |

默认四模型使用各自 native compiler。Qwen/FireRed 如需 direct 对照，将 compiler.backend 显式改为 `direct`；三种 strategy 对比时保持该 compiler 选择一致。FLUX/FIBO 不把没有执行原生编译的短提示伪装成 native condition。

## 4. 有限反馈与等预算采样

反馈策略例子：

```json
{
  "strategy": "model_aware",
  "policy": {
    "mode": "feedback",
    "max_generations": 3,
    "seed_schedule": [42, 43, 44],
    "max_stage_calls": 9,
    "max_compiler_calls": 3
  }
}
```

每次确有可支持的新指令时生成新 intent，再编译、再从原图执行。无有据反馈、结果合格或预算结束都会停止。若 mode 改为 `resample`，保持第一轮原生条件，只使用 seed schedule 继续采样。`native` 不允许 feedback，以免基线暗中获得 Harness 推理；它可以使用 resample。

重采样固定预算仍会逐次验证，完整保留候选；没有 adapter 内部的隐藏 best-of-N。

## 5. 区域证据与空间执行

### 两图独立区域统计

```json
{
  "regions": [
    {
      "id": "subject",
      "description": "主体面部及邻近衣物",
      "source_box": [0.2, 0.2, 0.6, 0.7],
      "reference_box": [0.3, 0.15, 0.65, 0.65]
    }
  ]
}
```

这里使用 `[x_min,y_min,x_max,y_max]`，各自归一化到对应图片。region 是证据对象，不自动变成局部执行 mask。S2 给出全局与每个 ROI 的显示亮度分位数、RGB 均值及裁切统计；B 未对齐，不计算无效的逐像素配对指标。

### 四模型通用 crop/fuse

```json
{
  "geometry": {"policy": "pad", "grid": 32},
  "spatial": {
    "mode": "crop_and_fuse",
    "mask_path": "/data/edit-mask.png",
    "context_pixels": 64,
    "feather_pixels": 8
  }
}
```

mask 必须与 canonical source 同尺寸，白色为可编辑区域，阈值 128。公共模块负责裁切、context、网格 padding、逆变换和融合，保留原生局部输出。feather 在 mask 内侧，二值 mask 外精确保留 canonical source。参考 B 使用自己的全图，不沿用 A 的裁切坐标。

### FLUX native bbox

```json
{
  "profile_id": "flux3_klein",
  "spatial": {
    "mode": "bbox",
    "boxes": [{
      "id": "subject", "desc": "the source subject", "from": "ref_image_0",
      "src_bbox": [0.2, 0.2, 0.7, 0.6],
      "tgt_bbox": [0.2, 0.2, 0.7, 0.6]
    }]
  }
}
```

FLUX 的原生顺序为 `[y_min,x_min,y_max,x_max]`，与上面的 ROI evidence 顺序不同；两个字段名和验证路径明确区分。源/目标框相同用于原位复原，框外不承诺硬像素保持。

### FIBO native mask

```json
{
  "profile_id": "fibo2_dev",
  "task_mode": "restoration",
  "spatial": {"mode": "native_mask", "mask_path": "/data/edit-mask.png"}
}
```

只能是单图，不能同时带 reference。它是 native 编码条件，不是输出域的逐像素锁；A+B 需要局部硬保护时使用公共 crop/fuse，并单独记录该执行策略。

## 6. 四模型批量比较与导出

编辑 `batch.example.json` 中 cases 的 source/reference/brief。默认主矩阵为：

```text
qwen21 / firered11 / flux3_klein / fibo2_dev
× native / shared / model_aware
× cases × seeds
```

这段只是矩阵表示，不是服务器 shell 命令。要运行：

```bash
/srv/venvs/hre-edit/bin/hre models batch \
  --manifest server-config/batch.example.json \
  --config server-config/runtime.example.json \
  --out runs/four-model-comparison

/srv/venvs/hre-edit/bin/hre models report \
  --run runs/four-model-comparison \
  --out reports/four-model-comparison
```

`share_planning=true` 会先对每个案例仅规划一次，再给所有 shared/aware 任务使用。同一 case 的源图、参考图和 mask 在 batch 初始化时复制并冻结；运行过程中原数据目录变化不会改变后续模型的输入。批次内副本变动则拒绝继续。

可增加两个 arm：

```json
[
  {"name": "aware_feedback3", "strategy": "model_aware", "policy": "feedback", "max_generations": 3},
  {"name": "aware_resample3", "strategy": "model_aware", "policy": "resample", "max_generations": 3}
]
```

若 seeds 为 `[42]`，三次生成使用 `[42,43,44]`。主矩阵建议统一 full-frame；bbox/mask/crop-fuse 放进显式单独的任务或批次，避免把执行控制差异藏进相同 arm 标签。单个 case 可用 `models` 限定模型子集，例如 FIBO native-mask 专项；默认仍是四模型。

报告输出：

- `index.html`：按案例、arm、seed 筛选；源图/参考/四模型交付图；点击原尺寸查看；全部轮次 native/delivered 图。
- `comparisons.csv`：模型和 compiler 身份、seed、预算、时长、选择类型和输出 hash。
- `report.json`：经 hash 检查的完整操作结果、原生编译响应、各轮 condition、运行配置和观察记录。

报告从已校验 journal 读取状态，不会把滞后的 `state.json` 当作最终事实。`candidate_unaccepted`、`source_baseline` 和正式通过的 candidate 会明确区别；没有计算的 PSNR/SSIM 或画质排名不会被填入。

## 7. 中断、异常与恢复

普通继续：

```bash
/srv/venvs/hre-edit/bin/hre models resume --case-root runs/qwen-restoration-001
```

批次继续用原 manifest/config 和 `--resume`。已完成 case 不重跑；未解决的未知提交会继续保持 paused，其他 case 可继续。

```bash
/srv/venvs/hre-edit/bin/hre models batch \
  --manifest server-config/batch.example.json \
  --config server-config/runtime.example.json \
  --out runs/four-model-comparison --resume
```

查看 `state.pending` 和 `operations/<operation_id>/last_error.json`。如果 worker 已将真实结果持久化，可直接导入对应 spool 的 `result.json`：

```bash
/srv/venvs/hre-edit/bin/hre models reconcile \
  --case-root runs/qwen-restoration-001 \
  --decision confirmed_result \
  --result /实际worker-job目录/result.json \
  --evidence "worker已保存该请求的真实结果，客户端响应丢失"

/srv/venvs/hre-edit/bin/hre models resume --case-root runs/qwen-restoration-001
```

实现会核验请求、condition、配置、seed/attempt 和输出目录绑定，不能把另一个 case 的图片作为该次成功结果导入。无 worker envelope 的 adapter 回执必须已有完整绑定，不能导入一张任意图片再伪造成功。

`not_submitted` 只用于有证据确认没有发生调用；`consumed_failed` 保留已消费预算并允许在剩余预算内产生新 attempt；`stop` 保留未知记录并终止。模型 OOM 不会触发隐藏缩图、降 dtype、改 checkpoint 或第二次自动生成。

## 8. 单卡与多卡进程生命周期

默认 worker 的 `keep_other_workers=false`：切换 compiler/editor 时释放其他 worker，避免一张卡上悄悄常驻多个大模型。同一个 worker 内按完整运行身份缓存一个模型，连续固定条件采样可以复用已加载 pipeline。

若 compiler 和 editor 分配到不同显卡，并且容量允许，可显式设置 `keep_other_workers=true`，让它们分别常驻。该选项意味着用户已经选择保留其他已启动 worker；大批次跨四模型时也可能保留多个进程，应据设备配置决定。此版本默认串行队列，不自动推断显存容量或迁移设备。

完成环境部署后保存实际依赖：

```bash
/srv/venvs/hre-edit/bin/python -m pip freeze > server-config/image-environment.lock.txt
/srv/venvs/hre-pe/bin/python -m pip freeze > server-config/pe-environment.lock.txt
```

## 9. 本次交付状态

四模型内置调用路径、两种任务、反馈重编译、空间控制、批次冻结和报告均已实现。仓库的 CPU 检查使用明确 fixture/mock，不伪造正式模型执行成功。服务器接手需要完成本地部署、实际推理验证以及用户计划的画质对比；这些结果应记录在新的 run 目录中，不回填为本次已有证据。
