# 当前对话的真实视觉回执协议

本接口不调用新服务。操作者将实际请求及其像素视图送入当前对话，由当前模型观察后提供结构化回执。`provider=current_chat_offline` 是来源标签，不是模型版本证明、Qwen 服务部署或真实性认证；不得把测试 payload 当真实视觉判断。当前对话可能已看到规划上下文，不能因此声称评审者具有独立盲法；应另记该局限。

## 配置与恢复

在新配置中将 `automatic_diagnosis.provider`、`planner`、`reviewer` 三处均设为：

```json
{"mode":"files","provider":"current_chat_offline"}
```

旧 `{"mode":"files"}` 仍可用且请求哈希不变。不能修改已有冻结运行的配置来切换 provider，应建立新 out。自动诊断尚需真实分割；当前 SAM3 不可用时，只能完成前置 discover_regions 请求，不能跳过真实 mask 伪造对应。

```bash
PYTHONPATH=engine/src python -m hre tool-retouch run --config /absolute/case/config.json --out /absolute/new-run
```

原图/配置满足前提时，程序导出请求并以 `waiting_for_response` 暂停（CLI exit 2），不是失败验收。请求位于 `semantic_vlm/NN-stage-hash/request.json`、`planner/.../request.json` 或 `reviewer/.../request.json`。在同目录保存 response.json，再原样重复上述命令。每次从初始阶段重放已绑定回执，调用序号及输入相同；已完成渲染恢复有独立调用缓存。若修改图像、mask、合同、配置，应新建 run，不覆写旧证据。

## 精确请求与回执外壳

请求字段集合（current_chat 模式）：

```text
{
 stage: discover_regions | correspond_regions | diagnose | contract | plan | verify,
 instruction: string,
 context: object（下表指定的实际上下文）,
 images: [{type:"text",text:string}, {type:"image_url",image_url:{url:"data:image/png;base64,..."}}, ...],
 model: "current_chat_offline",
 provider: "current_chat_offline"
}
```

images 按“名称、PNG”交替。整图和区域视图最长边 1024；原生裁剪通常 512×512，不缩放。均为已转换工作域的 RGB8 显示副本，不是原图字节或高精度测量输入。

回执必须恰好包含以下三字段：

```text
{
 request_sha256: string（完整 request 经 canonical 编码的 SHA256）,
 observer: "current_chat_offline",
 payload: object（相应 stage 的下述字段）
}
```

canonical = UTF-8 JSON，sort_keys=True、separators=(',',':')、ensure_ascii=False、allow_nan=False。目录后缀只是前12位，不能作为完整 SHA。不得凭图像文件名填 source/reference/candidate_sha256：verify 使用 context 中的像素数组哈希，discover_regions context 使用原文件哈希，两者不同。必须直接沿袭请求提供的值。

下面脚本将一个已导出的请求转换为可实际查看的 PNG + 保留全部上下文的审阅文件，既不修改原 request，也不生成回复。out 必须为新目录。操作者须实际打开这些图，而不是仅阅读文件名或 base64。

```bash
PYTHONPATH=engine/src python - /absolute/request.json /absolute/new-review-bundle <<'PY'
import sys,json,base64
from pathlib import Path
from hre.tool_retouch.contracts import canonical
from hre.tool_retouch.color import digest_bytes
p=Path(sys.argv[1]);out=Path(sys.argv[2]);out.mkdir(exist_ok=False)
r=json.loads(p.read_text());entries=[];parts=r['images']
assert len(parts)%2==0
for i in range(0,len(parts),2):
    assert parts[i]['type']=='text' and parts[i+1]['type']=='image_url'
    u=parts[i+1]['image_url']['url'];prefix='data:image/png;base64,';assert u.startswith(prefix)
    data=base64.b64decode(u[len(prefix):],validate=True);assert data.startswith(b'\x89PNG\r\n\x1a\n')
    name=f'{i//2:03d}.png';(out/name).write_bytes(data)
    entries.append({'label':parts[i]['text'],'file':name,'sha256':digest_bytes(data)})
review={k:v for k,v in r.items() if k!='images'}
review.update(request_sha256=digest_bytes(canonical(r).encode()),image_files=entries)
(out/'review-request.json').write_text(json.dumps(review,ensure_ascii=False,indent=2))
print(out/'review-request.json')
PY
```

## Stage payload：字段必须齐全，不添加未定义字段

记号：S=非空字符串，S[]=字符串数组（部分字段可为空），ID=请求中存在的引用，null=JSON null。实际校验为 diagnosis.py、contracts.py、planner.py、verifier.py 中对应函数；以下是当前实现字段与枚举，不是另创一套协议。

### discover_regions

```text
{labels:S[1..12 unique], source_observations:S[], reference_observations:S[],
 protected_properties:S[至少1], uncertainties:S[]}
```

输入 context：user_goal、source_sha256、reference_sha256；images：实际 A/B。当前 labels 为 SAM3 开放文本标签；轻量固定类后端选定后必须提供实际支持词表约束，不能把模型想出的任意名词当可分割类别。

### correspond_regions

```text
{regions:[{id:S,a_mask:ID,b_mask:ID,semantic:S,
 comparability:"comparable"|"partially_comparable"|"not_comparable",reasons:S[至少1]}]（1..6）, uncertainties:S[]}
```

输入：user_goal、discovery、catalog（side/label/mask_id）、restriction；images 为 A/B、每个实际 mask 的覆盖暗化图及真实像素区域裁剪。A/B mask ID 必须属于各自侧；不创建像素mask，不把同类别/同名字当相同物体、光照或可比较证据。后续 build_pairs 可因实际内部支持不足降级。

### diagnose

```text
{deltas:[{id:S,dimension:D,regions:ID[至少1],evidence_ids:ID[至少1],
 interpretation:S,transfer:"target"|"preserve"|"exclude"|"uncertain",uncertainty:string}]（最多32）,
 coverage:[{dimension:D,status:"targeted"|"preserve"|"excluded"|"uncertain"|"not_applicable",delta_ids:ID[],reason:S}]（恰好8）,
 protected_properties:S[至少1],uncertainties:S[],summary:S}
```

D 为 neutral_balance、chroma_by_hue、skin_rendering、shadow_midtone_highlight、highlight_transition、local_contrast、subject_background_balance、texture_and_noise_observation。八维各出现一次；所有 delta 必须被同维度 coverage 引用，targeted 不能为空。每个 delta 引用存在且属于所列区域的 A/B 双侧统计；弱可比区域必须保留非空 uncertainty；沿袭发现阶段保护项。

输入：observations、regions、policy、user_goal、discovery、dimensions；images 为 A/B 总览、每区范围、原生中心裁剪。统计由程序实际像素测量，不能由当前模型猜测替代；不把内容、光照、视角差直接当作应迁移风格。

### contract

```text
{targets:[{id:S,kind:"interval"|"direction"|"relation"|"perceptual"|"protection",
 regions:ID[至少1],metric:string|null,evidence_ids:ID[至少1],tolerance_id:string|null,
 mandatory:boolean,direction:"increase"|"decrease"|null,description:S,delta_id:ID}]（1..32）,
 protected_properties:S[至少1],exclusions:S[],uncertainties:S[]}
```

自动诊断路线必须有 delta_id；兼容的非诊断路线反而不允许该额外字段。delta 必须 transfer=target 或 preserve，regions 相同，证据不少于原 delta；所有 transfer=target 必须被覆盖，诊断保护项/uncertainties 不可丢。至少一 mandatory。

perceptual/protection 的 metric、tolerance_id、direction 必须全 null。其余数值目标：interval/direction 为1区，relation 为2区；metric 与 tolerance_id 只能引用 observations 和 policy.tolerances；双侧该metric证据必须完整。部分可比只允许 direction，不可比禁止数值目标。方向需与实际差值一致；interval/relation 的 direction=null。禁止自行写 lower/upper/value/scale 等目标数值，程序负责解析冻结。

输入在 diagnose 基础上增加 measured_diagnosis；图像同 diagnose。

### plan

```text
{operations:[{id:S,tool:"exposure"|"curve"|"balance"|"saturation",
 target_ids:ID[至少1],mask_id:ID|null,
 parameters:{参数名:{lower:number,upper:number,suggested:number,min_step:number}},
 expected_effect:S,protect_target_ids:ID[]}],reason:S,feedback_ids:ID[]}
```

输入：contract、tools、edit_mask_ids、feedback；图像 A/B 总览、区域/原生裁剪。参数以 tools 为准：ev [-1,1] identity0/min_step≥.015625；mid [96,160] identity128/≥.5；red/blue [-10,10] identity0/≥.15625；amount [-20,20] identity0/≥.3125。上下界须覆盖 identity、非退化；suggested 在范围内，min_step 不超宽度。最多3全局+3局部、12参数。第一轮 feedback_ids 可以空；修订必须引用实际当前反馈。不能改合同/验收ROI，不能添加shell、任意命令或新mask路径。

### verify

```text
{contract_sha256:S,source_sha256:S,reference_sha256:S,candidate_sha256:S,
 observer:"current_chat_offline",target_results:[{id:ID,status:"achieved"|"partial"|"unmet"|"uncertain",observation:S}],
 content:"pass"|"fail"|"uncertain",naturalness:"pass"|"fail"|"uncertain",reference_match:"pass"|"fail"|"uncertain",
 native_inspected:boolean,notes:string,
 preservation_checks:[{item:ID,status:"pass"|"fail"|"uncertain",observation:S}]}
```

外壳和 payload 各有 observer，均需如实标记。输入 context 只有冻结 contract 和四哈希；不提供候选计划或搜索叙事。图像必须实际查看 A/B/C 总览、区域与原生裁剪。每个目标/每条保护项恰好一条判断，不可漏项。原生中心裁剪仅代表局部，不自动证明全图文字、人脸、边缘无问题；不足时 native_inspected=false，相关状态 uncertain，不能填写通过。reference_match 评价外观迁移，不要求内容/视角复制。same-chat 非盲法局限写入 notes，并保留真实对话消息溯源于运行旁证，不给严格 payload 添加额外字段。

## 分割调度审查与最小改动（待选模型，尚未实施）

当前生产调度确实硬编码 SAM3，而不是已有通用可插拔后端：segmentation.schedule_bilateral 固定 checkpoint/labels/conf/iou/imgsz/version schema、ultralytics版本检查、segment.py/_models.py/sam3_worker.py 源码hash、固定 worker入口；import_harness_segments 固定 producer 名称，diagnosis 中提示和同实例限制也指向 SAM3。runner 注入仅供测试，不能用它把未安装轻量模型冒充生产路径。

选定模型后最小改动：

1. 加白名单 backend 描述和 capabilities（open_vocabulary 或 fixed_classes、实际类表及映射、CPU/runtime/model hash）；旧配置默认 sam3 保持兼容，不允许模型填写任意命令/模块路径。
2. 将 backend 特定版本/权重/参数校验、代码hash及 subprocess模块选择放到注册表；公共调度继续负责双侧输入、内容寻址缓存、超时、失败不重试及产物哈希。缓存键必须加入 backend/类别映射/预处理版本。
3. 统一原生尺寸 uint16 label图+类别表/可靠性/输入绑定回执的输出协议，适配不同忽略类和resize插值；producer记录实际后端，不能仍写SAM3。
4. discover_regions 请求增加所选后端能力；固定类模型只能选支持类别，不支持的对象标unsupported/uncertain。对应阶段仍看真实两侧mask和像素，不因类别相同提高可比性。
5. 增加双侧缓存隔离、标签缺失/固定类拒绝开放词、resize/边缘/空mask、版本失配、A成功B失败等测试；真实模型性能与分割质量另测。

固定类别分割通常无法表达任意招牌/展柜/材质语义，不等价于 SAM3 开放语义能力。模型未选定前，不下载权重、不装运行时、不修改当前生产分割路径。

## 剩余阻塞

协议和来源标签可独立准备，但真实请求必须以可读原图为前提。目前 Drive 和官方 Library ZIP 都未把原图送入执行环境；未重试被拒绝HTTP或改代理。轻量模型/本地权重与运行时尚未选定。当前对话视觉回执不依赖部署新VLM服务，但仍需父任务实际查看本次请求的像素并返回绑定证据，不能从先前场景文字描述代填。

## 已选轻量候选的接口草案（未安装、未实现生产后端）

父任务建议 MediaPipe SelfieMulticlass 256×256，float32 version 1，16,371,837 bytes；用户已授权必要安装/迁移，由父环境执行，本任务保持原环境。按父任务提供能力定义：固定类 0 background、1 hair、2 body-skin、3 face-skin、4 clothes、5 others/accessories。优先评估面部亮度/肤色与背景关系，不推断人物身份。face-skin 不保证已排除眼镜/牙齿；hair/others 用于候选保护，不声称精细五官分割。

拟新增配置（**当前CLI尚不接受，不可直接作为已实现样例运行**）：

```text
segmentation = {
 backend:"mediapipe_selfie_multiclass", checkpoint:<local_path>,checkpoint_sha256:<verified_hash>,
 producer_version:<actual_mediapipe_version>, model_version:"float32/1", timeout:<seconds>,
 requested_classes:["background","hair","body-skin","face-skin","clothes","others"],
 output_policy:{confidence_threshold:<frozen_development_threshold>,unknown_label:0}, regions:[]
}
```

模型接收规范RGB Image，由Tasks模型metadata负责预处理，不自行套ImageNet normalization。未测前不预设类别缺失必为背景；统一导出协议需区分真实 background 与 unknown（当前SAM3 importer忽略id0，适配器须将6个类别映射到正整数1..6，0专留unknown，并保存显式原类→输出ID表）。保存实际confidence masks及category mask；尺寸还原、置信阈值和插值策略均入cache key。实际API参数与输出布局需获准安装后核验，不能根据草案声称可运行。

统一输出回执草案：source_sha256、side、backend_id、runtime_version、model_sha256、model_version、class_mapping、preprocess_version、output_native_size、ids_sha256、summary_sha256、confidence_artifact_hashes、observer、status；类别表保留实际类名、像素数、置信统计及unsupported目标。原始来源不再写成SAM3。discover提示只可选择固定类及讨论其覆盖局限；不能把“眼镜”“招牌”直接新增为模型类别。

迁移实验需检查逆光/夜间皮肤、头发边缘、眼镜/accessories、衣服和背景，不用ADE20K整个人类别代替脸部控制。当前仅接口准备，尚未下载权重或安装MediaPipe。
