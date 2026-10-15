"""Freeze the explicitly authorized alternative without changing SAM3 cases."""
import copy
import json
from pathlib import Path

from hir_manual.storage import now, read_json, write_json, sha256_file
from hir_manual.tool_registry import load_profile

ROOT = Path(__file__).resolve().parents[2]


def prepare(root=ROOT):
    root = Path(root)
    original = load_profile("gpu_full_v1", root)
    profile = original.model_copy(deep=True)
    profile.evidence_profile_id = "gpu_yoloe26l_v1"
    profile.configuration_status = "authorized_alternative_not_deployed"
    profile.formal_eligible = False
    tool = profile.tools["T4_SEGMENTATION"]
    tool.update(model="YOLOE-26l-seg", checkpoint_generation="YOLOE-26", implementation="ultralytics_yoloe_text", input_size=1024)
    registry = read_json(root / "preprocessing/registry/gpu_full_v1.json")
    # T4 stays absent until its own real deployment creates a locked entry.
    registry["tools"] = {k: copy.deepcopy(v) for k, v in registry["tools"].items() if k != "T4_SEGMENTATION"}
    registry["registry_status"] = "alternative_t4_deployment_required"
    config = root / "preprocessing/configs/gpu_yoloe26l.json"
    registry_path = root / "preprocessing/registry/gpu_yoloe26l_v1.json"
    for path, value in ((config, profile.model_dump()), (registry_path, registry)):
        if path.exists():
            if read_json(path) != value:
                raise ValueError("Alternative already changed/deployed; preserve it and use a new version")
        else:
            write_json(path, value)
    write_json(root / "runtime/alternatives/yoloe26l/authorization.json", {
        "recorded_at": now(), "human_instruction": "我没有，可以采取替代方案",
        "selected_model": "YOLOE-26l-seg", "profile_id": profile.evidence_profile_id,
        "original_sam3_protocol_eligible": False, "model_inference_completed": False,
        "profile_sha256": sha256_file(config), "original_profile_sha256": sha256_file(root / "preprocessing/configs/gpu_full.json"),
        "new_server_window_authorized": False,
        "reason": "Public text-prompted instance segmentation; GPU Large chosen for quality-first pilot; 31 original class prompts retained."
    })
    return profile


if __name__ == "__main__":
    profile = prepare()
    print(json.dumps({"profile": profile.evidence_profile_id, "model": profile.tools["T4_SEGMENTATION"]["model"], "deployed": False, "inference_completed": False}))
