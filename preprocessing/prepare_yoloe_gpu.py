"""Explicit, isolated deployment of the human-authorized YOLOE alternative.

Never run by an inference worker. Requires verified local official assets.
Installation and text-embedding preparation are not image-pilot acceptance.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from preprocessing.prepare_models import isolated_python, install_requirements, file_components, make_entry, source_components, sha256, CLIP_REVISION
from preprocessing.prepare_gpu_models import probe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--base-python", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--asset-receipt", type=Path, required=True)
    parser.add_argument("--text-encoder", type=Path, required=True)
    parser.add_argument("--clip-source", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform == "win32":
        raise ValueError("YOLOE-26l GPU deployment requires an explicitly authorized Linux run window")
    root = args.root.resolve()
    sys.path.insert(0, str(root / "engine/src"))
    from hir_manual.tool_registry import load_profile
    from hir_manual.resource_monitor import monitor_process
    from hir_manual.storage import write_json
    from filelock import FileLock
    profile = load_profile("gpu_yoloe26l_v1", root)
    receipt = json.loads(args.asset_receipt.read_text(encoding="utf-8"))
    if receipt.get("repository") != "ultralytics/assets" or receipt.get("model") != "YOLOE-26l-seg" or args.checkpoint.name != "yoloe-26l-seg.pt" or sha256(args.checkpoint) != receipt["sha256"] or args.checkpoint.stat().st_size != receipt["bytes"]:
        raise ValueError("Exact official Large text checkpoint source/size/SHA256 mismatch")
    if sha256(args.text_encoder) != "35d7f213e4d75f38514e4656ad3cb91158bd33e3805d8ac349f23b186f66982f":
        raise ValueError("Official MobileCLIP2 text encoder SHA256 differs")
    if args.clip_source.name != "CLIP-" + CLIP_REVISION or not (args.clip_source / "clip/bpe_simple_vocab_16e6.txt.gz").is_file():
        raise ValueError("Exact prepared CLIP source/tokenizer is required")
    environment = root / "preprocessing/environments/venv_t4_yoloe26l_gpu"
    python = isolated_python(environment, args.base_python)
    if Path(probe(python, "import sys; print(sys.prefix)")).absolute() != environment.absolute():
        raise ValueError("Tool environment isolation failed")
    lock = environment.parent / "t4_yoloe26l_gpu.freeze.txt"
    install_requirements(python, ["--index-url", "https://download.pytorch.org/whl/cu128", "torch==2.10.0", "torchvision==0.25.0"], lock)
    install_requirements(python, ["ultralytics==8.4.175", "numpy==2.3.5", "Pillow==12.1.0", str(args.clip_source.resolve())], lock)
    directory = root / "models/yoloe_26l_seg"
    directory.mkdir(parents=True, exist_ok=True)
    prompt = directory / "harness_scene_v1.json"
    write_json(prompt, profile.tools["T4_SEGMENTATION"]["prompt_set"])
    embeddings = directory / "harness_scene_v1_embeddings.npz"
    temporary = directory / "harness_scene_v1_embeddings.preparing.npz"
    code = "from preprocessing.workers.common import enforce_offline; enforce_offline(2); import json,sys,torch,numpy as np; from ultralytics import YOLOE; from ultralytics.nn.text_model import MobileCLIPTS; torch.set_num_threads(2); torch.set_num_interop_threads(1); torch.backends.cuda.matmul.allow_tf32=False; torch.backends.cudnn.allow_tf32=False; assert torch.cuda.is_available(); m=YOLOE(sys.argv[1]); m.to('cuda:0'); labels=json.load(open(sys.argv[2],encoding='utf-8'))['labels']; m.model.clip_model=MobileCLIPTS(device=torch.device('cuda:0'),weight=sys.argv[3]); pe=m.model.get_text_pe(labels,cache_clip_model=True); m.set_classes(labels,pe); m.save_prompt_embeddings(sys.argv[4]); z=np.load(sys.argv[4],allow_pickle=False); assert z['names'].tolist()==labels and str(z['model'].item())=='yoloe-26l'; assert z['embeddings'].dtype==np.float32 and z['embeddings'].shape[:2]==(1,len(labels)) and np.isfinite(z['embeddings']).all()"
    profile.tools["_active"] = {"timeout_seconds": profile.tools["T4_SEGMENTATION"]["timeout_seconds"]}
    log_dir = root / "runtime/preparation_logs/yoloe26l_text_embeddings"
    measured = monitor_process([str(python), "-c", code, str(args.checkpoint.resolve()), str(prompt), str(args.text_encoder.resolve()), str(temporary)], root, profile, log_dir)
    write_json(log_dir / "worker_result.json", measured)
    if measured.status != "completed" or measured.process_released is not True:
        raise ValueError("Text-embedding preparation failed/waiting; preserve logs and do not mark model ready")
    temporary.replace(embeddings)
    # Freeze actual installed versions after successful preparation.
    import subprocess
    lock.write_bytes(subprocess.run([str(python), "-m", "pip", "freeze", "--all"], check=True, capture_output=True).stdout)
    paths = {"checkpoint": args.checkpoint.resolve(), "text_embeddings": embeddings, "prompt_set": prompt, "text_encoder": args.text_encoder.resolve()}
    components = file_components([*paths.items(), ("tokenizer_vocabulary", args.clip_source / "clip/bpe_simple_vocab_16e6.txt.gz"), *source_components(args.clip_source, "clip_source")])
    revision = "ultralytics-8.4.175_clip-" + CLIP_REVISION
    entry = make_entry("YOLOE-26l-seg", python, paths, components, revision, "torch", probe(python, "import torch; print(torch.__version__)"), "ultralytics_yoloe_text", sha256(lock))
    entry["backend"]["device"] = "cuda:0"
    entry["environment_lock_file"] = str(lock.resolve())
    registry_path = root / "preprocessing/registry/gpu_yoloe26l_v1.json"
    with FileLock(str(registry_path) + ".lock"):
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        registry["tools"]["T4_SEGMENTATION"] = entry
        registry["registry_status"] = "alternative_t4_warmup_required"
        write_json(registry_path, registry)
    profile.tools.pop("_active")
    profile.configuration_status = "deployed_authorized_yoloe26l_alternative"
    write_json(root / "preprocessing/configs/gpu_yoloe26l.json", profile)
    write_json(directory / "deployment_receipt.json", {"model": entry["model_name"], "bundle_sha256": entry["model_bundle_sha256"], "environment_lock_sha256": entry["environment_lock_sha256"], "text_embedding_preparation": measured.model_dump(), "image_inference_completed": False, "ready": False, "original_sam3_protocol_eligible": False})
    print(json.dumps({"prepared": True, "ready": False, "profile": profile.evidence_profile_id, "image_inference_completed": False, "framework": entry["backend"]["framework_version"]}))


if __name__ == "__main__":
    main()
