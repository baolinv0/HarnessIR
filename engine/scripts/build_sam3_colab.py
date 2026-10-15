"""Create a self-contained Colab Notebook and frozen 20-photo LQ input ZIP.

No model execution, uploads, secrets, GT or enhanced inputs are involved.
"""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine/colab"))
import sam3_handoff as runner


def build(root=ROOT):
    root = Path(root)
    output = root / "runtime/sam3_colab"
    output.mkdir(parents=True, exist_ok=True)
    dataset = root / "runtime/offline_gpu/prepared_20261013"
    handoff = root / "runtime/sam3_handoff"
    selected = runner.read(handoff / "selection20.json")["image_ids"]
    original = runner.read(dataset / "manifest.json")
    rows = {r["image_id"]: r for r in original["images"]}
    inputs = dict(handoff_version="sam3_raw_v1", dataset_kind="original_lq_canonical_only",
                  source_manifest_sha256=runner.sha(dataset / "manifest.json"), images=[])
    files = {}
    for image_id in selected:
        row = dict(rows[image_id])
        canonical = runner.under(dataset, row["canonical_path"])
        source = runner.under(dataset, row["original_path"])
        if runner.sha(canonical) != row["canonical_sha256"] or runner.sha(source) != row["original_sha256"]:
            raise ValueError("Prepared original/canonical hash changed")
        row["canonical_path"] = f"inputs/{image_id}.png"
        # The originals are hash-verified above but not copied into the ZIP.
        for key in ("input_path", "metadata_path", "original_path", "source_path"):
            row.pop(key, None)
        inputs["images"].append(row)
        files[row["canonical_path"]] = canonical
    archive = output / "harnessir_sam3_inputs20.zip"
    with zipfile.ZipFile(archive.with_suffix(".zip.tmp"), "w", zipfile.ZIP_STORED) as z:
        z.writestr("inputs.json", json.dumps(inputs, ensure_ascii=False, indent=2))
        for name in ("pilot5.json", "selection20.json", "prompt_set.json"):
            z.write(handoff / name, name)
        for name, path in files.items():
            z.write(path, name)
    archive.with_suffix(".zip.tmp").replace(archive)
    archive_sha = runner.sha(archive)
    native_weights = sorted((root / "models/sam3").glob("*.pt"))
    weight_sha = runner.sha(native_weights[0]) if len(native_weights) == 1 else runner.CHECKPOINT_SHA256
    if weight_sha != runner.CHECKPOINT_SHA256:
        raise ValueError("Local native checkpoint differs from the locked official SAM3 hash")
    cells = []
    def md(text):
        cells.append(dict(cell_type="markdown", metadata={}, source=text.splitlines(keepends=True)))
    def code(text):
        cells.append(dict(cell_type="code", metadata={}, source=text.splitlines(keepends=True), execution_count=None, outputs=[]))
    md("""# HarnessIR · SAM 3 Colab 五图验收与20图证据生成

这里只生成T4辅助证据，不生成图像编辑结果，也不算四工具完整验收。
使用你已下载的 **Meta原生SAM 3 `sam3.pt`**，不自动下载模型、不接受SAM3.1。
如果只有Hugging Face配置/tokenizer，或只有Transformers `model.safetensors`，请先取得原生官方 `sam3.pt`；不能直接改扩展名。

选择 **运行时 → 更改运行时类型 → GPU**。Python必须为3.12。部署会创建独立工具venv并安装锁定的Torch2.10/cu128；Colab内置Torch保持独立。

本Notebook配置 `colab_sam3_1008_v1`：使用官方1008输入、fp32、31类、阈值0.15/0.5、单图进程、2线程；与旧1024配置不同，标记formal_eligible=false，导回后建立新合同。
默认顺序：部署 → 5图 → 检查Mask/图例 → 明确填写reviewer → 20图 → 下载ZIP。

不需要Hugging Face令牌。推理进程禁网络/安装/下载。请将输入包与权重先上传Google Drive（推荐）或Colab `/content`；结果输出到Drive可避免运行时删除造成丢失。
官方源码固定：<https://github.com/facebookresearch/sam3/tree/0570b3a5be9c4e694f23d85232fb55f4a6f1f7fc>。
""")
    md("## 1. 配置文件路径\n输入ZIP仅包含冻结20张原始LQ的canonical PNG，不含GT、增强图或凭据。请根据实际上传路径修改下面三个路径。")
    code(f'''from pathlib import Path
import sys
assert sys.version_info[:2] == (3,12), "请使用Python3.12运行时；不会自动替换环境"
# 若使用Google Drive，取消下一行的注释并完成登录：
# from google.colab import drive; drive.mount('/content/drive')
INPUT_ZIP = Path('/content/harnessir_sam3_inputs20.zip')
CHECKPOINT = Path('/content/sam3.pt')
OUTPUT = Path('/content/drive/MyDrive/HarnessIR/sam3_colab_1008_v1')
DEPLOYMENT = Path('/content/harnessir_sam3_deployment')
BUNDLE = Path('/content/harnessir_sam3_inputs20')
INPUT_ZIP_SHA256 = '{archive_sha}'
CHECKPOINT_SHA256 = '{weight_sha}'  # 已由官方公开LFS元数据独立核对；上传后严格核验，不自动下载权重
CHECKPOINT_SOURCE_URL = 'https://huggingface.co/facebook/sam3/blob/{runner.WEIGHT_REVISION}/sam3.pt'
WALL_SECONDS = 7200  # 每次batch调用的上限；单图900秒，至少预留120秒保存
assert INPUT_ZIP.is_file(), '请先上传输入ZIP'
assert CHECKPOINT.is_file(), '请先上传原生sam3.pt权重'
assert len(CHECKPOINT_SHA256) == 64, '必须保留锁定的官方权重SHA256'
assert OUTPUT.parent.exists(), '输出到Drive时，请先挂载Drive；或改为/content下的目录'
''')
    md("## 2. 加载独立调度器、检查输入\n此单元不导入Torch，不运行模型。")
    text = (root / "engine/colab/sam3_handoff.py").read_text(encoding="utf-8")
    code("RUNNER_SOURCE = " + repr(text) + "\nRUNNER_PATH = Path('/content/sam3_handoff.py')\nRUNNER_PATH.write_text(RUNNER_SOURCE, encoding='utf-8')\nimport importlib.util\nspec = importlib.util.spec_from_file_location('sam3_handoff', RUNNER_PATH)\nhir = importlib.util.module_from_spec(spec); spec.loader.exec_module(hir)\nmanifest = hir.extract_bundle(INPUT_ZIP, BUNDLE, INPUT_ZIP_SHA256)\nprint('已核对输入', len(manifest['images']), '张；无模型推理')\n")
    md("## 3. 显式部署环境\n这是唯一允许安装依赖和下载官方源码的步骤。日志保存到 deployment.log。失败时查看日志，不能改用其他模型或精度。部署后执行真实CUDA计算检查；这不等于图片推理验收。")
    code("receipt = hir.prepare(DEPLOYMENT)\nprint(receipt['gpu_witness'])\nrun = hir.initialize(BUNDLE, DEPLOYMENT, CHECKPOINT, OUTPUT, CHECKPOINT_SHA256, CHECKPOINT_SOURCE_URL)\nprint('配置合同：', run['contract_sha256'])\n")
    md("## 4. 先跑五张真实图\n每张启动独立模型进程，用完退出。失败保留日志；无检测则生成合法空数组。中断会终止子进程并记录。")
    code("pilot = hir.batch(OUTPUT, 'pilot', wall_seconds=WALL_SECONDS)\nprint(pilot)\n")
    md("## 5. 检查证据与图例\n打开完整HTML查看原图/Mask叠加：重点检查人、文字、细小对象、边缘对齐和跨类别重叠。空检测不能证明不存在对象。显示pending的图尚未运行。")
    code("from IPython.display import display, HTML\ngallery_path = hir.gallery(OUTPUT)\ndisplay(HTML(gallery_path.read_text(encoding='utf-8')))\nprint('已保存：', gallery_path)\n")
    md("## 6. 五图全部通过后，手动确认\n只有真实五图输出可读、类别/坐标正确且你已看图，才填写自己的名称。这个review只覆盖T4，不能代替本地四工具验收。若不通过，先导出失败记录，不要继续20图。")
    code("REVIEWED_BY = ''  # 看过五图后填写你的名称；不要自动填充\nassert REVIEWED_BY.strip(), '先检查五图Mask，再填写审核人'\nhir.accept_pilot(OUTPUT, REVIEWED_BY)\nprint('T4五图已绑定审核，允许继续20图')\n")
    md("## 7. 继续20张\n复用严格一致的五图结果，只处理其他15张。已有失败默认保留；若原因已经修复，明确设置retry_failed=True，最多两次实际尝试。参数/权重/环境变化必须用新输出目录。")
    code("result20 = hir.batch(OUTPUT, 'selection20', wall_seconds=WALL_SECONDS, retry_failed=False)\nprint(result20)\n")
    md("## 8. 导出并下载\n未全部完成也可导出真实阶段结果；summary明确列出失败和pending，不宣称完成。ZIP含NPZ/JSON、实际环境锁、日志、资源记录与自包含HTML；不包含权重/令牌。")
    code("RESULT_ZIP = Path('/content/harnessir_sam3_results.zip')\nreceipt = hir.export_results(OUTPUT, RESULT_ZIP)\nprint(receipt)\nfrom google.colab import files\nfiles.download(str(RESULT_ZIP))\n")
    md("下载后将ZIP交回本地，待校验后解包到 `Data/annotations/incoming/t4_sam3/<run_id>/`。该ZIP是原始handoff，尚不是正式cache；我负责合同绑定、严格验证和正式缓存转换。\n\n恢复操作：重新挂载同一Drive、上传相同输入包与权重，运行1–3再运行4或7。完全一致结果才命中；受损结果会报错而不是被当作有效缓存。")
    notebook = dict(nbformat=4, nbformat_minor=5, metadata=dict(kernelspec=dict(display_name="Python 3", language="python", name="python3"),
                    language_info=dict(name="python", version="3.12"), colab=dict(name="HarnessIR_SAM3_Colab.ipynb"), accelerator="GPU"), cells=cells)
    # nbformat4.5 requires a unique stable cell ID.
    for i, cell in enumerate(cells): cell["id"] = f"hir-sam3-{i:02d}"
    runner.write(output / "HarnessIR_SAM3_Colab.ipynb", notebook)
    runner.write(output / "package_receipt.json", dict(inputs=20, pilot=5, contains_gt=False, contains_credentials=False,
                 archive_sha256=archive_sha, archive_bytes=archive.stat().st_size, notebook_sha256=runner.sha(output / "HarnessIR_SAM3_Colab.ipynb"),
                 runner_sha256=runner.sha(root / "engine/colab/sam3_handoff.py"), checkpoint_found=len(native_weights)==1,
                 checkpoint_sha256=weight_sha, official_weight_revision=runner.WEIGHT_REVISION,
                 official_weight_bytes=runner.CHECKPOINT_BYTES, source_revision=runner.REVISION, model_inference_performed=False))
    print(json.dumps(dict(output=str(output), input_zip_bytes=archive.stat().st_size, checkpoint_found=len(native_weights)==1)))
    return output


if __name__ == "__main__": build()
