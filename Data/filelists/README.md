# 数据调用 file list

当前实际输入164：基础84、新增80（人像40、长焦/真实光学跨焦段40）。此目录清单只调用已存在文件；280仍是目标。

| 子集 | 输入数 | 每行一个绝对路径的TXT | HarnessIR兼容JSON |
|---|---:|---|---|
| 全部 |164|file_list_all.txt|harness_all.json|
| 基础 |84|file_list_base.txt|harness_base.json|
| 新增HardCases |80|file_list_hardcases.txt|harness_hardcases.json|
| 人像 |40|file_list_portrait.txt|harness_portrait.json|
| 长焦/真实光学跨焦段 |40|file_list_telephoto.txt|harness_telephoto.json|

这些分组相互包含：all=base+hardcases；hardcases=portrait+telephoto。不要把五份列表拼接，否则会重复调用。

所有TXT为UTF-8、无表头、无引号、每行一个输入路径，只含输入图，不含GT、Mask或缩略图。全部绝对路径指向 `C:\Users\Lenovo\Desktop\HarnessIR_Manual\Data`。后缀 `_relative.txt` 是相对于这个Data根目录的可搬迁版本。

## Python读取

```python
from pathlib import Path

data_root = Path(r"C:\Users\Lenovo\Desktop\HarnessIR_Manual\Data")
list_path = data_root / "filelists" / "file_list_all.txt"
image_paths = [Path(line) for line in list_path.read_text(encoding="utf-8").splitlines() if line.strip()]
assert len(image_paths) == 164
assert all(path.is_file() for path in image_paths)

for image_path in image_paths:
    # 在这里把单张输入路径交给你的恢复接口。
    print(image_path)
```

只换 `file_list_portrait.txt` 即调用40张人像。若Data被移动，使用相对列表并修改data_root：

```python
image_paths = [data_root / line for line in
    (data_root / "filelists" / "file_list_all_relative.txt").read_text(encoding="utf-8").splitlines()
    if line.strip()]
```

## HarnessIR输入

`harness_all.json` 与当前已导出的官方格式一致，每条仅有 `lq`（绝对图像路径）和 `prompt`。将选中的JSON作为HarnessIR的manifest读取；具体命令参数按你本地HarnessIR入口，清单不猜测入口脚本或参数名。

```python
import json
items = json.loads((data_root / "filelists" / "harness_portrait.json").read_text(encoding="utf-8"))
for item in items:
    image_path, request = item["lq"], item["prompt"]
    # 把image_path、request交给HarnessIR或同执行器直接调用。
```

## 评测参考单独读取

`sample_index.csv` 关联样本ID、来源、类别、输入路径和SHA256。`evaluation_references.jsonl` 包含74条有参考文件的记录，只供评测，禁止把它作为模型输入。

74条参考含基础44、RAIM设计师闪光风格目标15、COZ跨焦段HR15；并非74条可直接算保真PSNR的配对。RAIM参考不是自然皮肤/身份真值，COZ的尺度与配准须先核实。该文件明确保留reference_role、几何状态及Mask。完整限制见Data/HardCases/README.md与专项协议。

LICAM/RealMCVSR原定配额存在临时替换；22张WildDark的独立事件待核查。file list验证路径存在和计数，不证明照片许可、独立事件或模型效果。此次仅导出调用清单，没有运行恢复模型。
