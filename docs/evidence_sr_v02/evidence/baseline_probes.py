"""CPU-only reproductions against HarnessIR baseline 90283e5189160c4c6e3429ddfa48f04d5bc27dfd.

No image model or network is invoked. Synthetic images live in temporary directories.
Run with the baseline engine/src on PYTHONPATH, not a revised SR implementation.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import json

from PIL import Image

from hre.models import file_sha256
from hre.v3 import stages
from hre.v3.contracts import create_case
from hre.v3.dispatch import seal_generation
from hre.v3.runner import _finish, run_case
from hre.v3.runner_journal import Journal
from hre.v3.spatial import deliver_outputs, prepare_request


def geometry_and_selection_probe():
    with TemporaryDirectory() as directory:
        root = Path(directory)

        def asset(name, size):
            path = root / name
            Image.new("RGB", size).save(path)
            return {"path": str(path), "sha256": file_sha256(path),
                    "width": size[0], "height": size[1], "mode": "RGB", "role": "source"}

        source = asset("source.png", (256, 256))
        spec = {"task_mode": "restoration", "brief": "Restore detail",
                "geometry": {"policy": "resize", "grid": 32, "width": 1024, "height": 1024},
                "spatial": {"mode": "full_frame"}, "alpha_policy": "require_opaque"}
        request = {"inputs": [source], "canvas": {"width": 256, "height": 256},
                   "spatial": {"mode": "full_frame"}}
        prepared = prepare_request(request, spec, root / "probe")
        native = asset("native_hr.png", (1024, 1024))
        delivered = deliver_outputs({"outputs": [native]}, prepared, spec, root / "delivered")["deliveries"][0]
        observed = {"prepared_size": [prepared["canvas"]["width"], prepared["canvas"]["height"]],
                    "delivered_size": [delivered["width"], delivered["height"]]}
        print("resize_delivery", json.dumps(observed))
        assert observed == {"prepared_size": [1024, 1024], "delivered_size": [256, 256]}

        candidate = {"candidate_id": "bad", "native": source, "delivered": source,
                     "geometry_valid": True, "delivery_status": "valid",
                     "verification": {"verdict": "reject", "preservation": "fail",
                                      "task_progress": "worse", "confidence": .9},
                     "round": 0, "provider_order": 0}
        state = {"case_id": "probe", "freeze_sha256": "fixture", "inputs": [source],
                 "canvas": {"width": 256, "height": 256}, "candidates": [candidate]}
        final = _finish(Journal(root, state), spec, "budget_complete")
        observed = {key: final[key] for key in
                    ("selected_kind", "selected_candidate_id", "success", "quality_status")}
        print("finish_bad_candidate", json.dumps(observed))
        assert observed == {"selected_kind": "candidate_unaccepted", "selected_candidate_id": "bad",
                            "success": False, "quality_status": "quality_not_met"}


def serialized_judge_probe():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "in.png"
        Image.new("RGB", (256, 256)).save(source)
        spec = {"profile_id": "qwen21", "task_mode": "restoration", "strategy": "native",
                "brief": "Restore image", "source": {"path": str(source)},
                "geometry": {"policy": "pad"}, "policy": {"mode": "single"},
                "regions": [{"id": "roi", "description": "center", "source_box": [.25, .25, .75, .75]}]}
        config = {"stage": {}, "models": {"qwen21": {"compiler": {"backend": "direct"},
                  "editor": {"model_id": "Qwen/Qwen-Image-2.1"}}}}
        case_root = root / "case"
        create_case(case_root, spec, config)
        captures = []

        def chat_spy(endpoint, messages, response_schema=None):
            captures.append(messages)
            payload = {"verdict": "reject", "preservation": "fail", "task_progress": "worse",
                       "confidence": .9, "summary": "Software probe", "issues": []}
            return {"text": json.dumps(payload), "calls_attempted": 1, "calls_completed": 1,
                    "fixture_only": True}

        def judge(request):
            return stages.run_stage(request, {})

        def execute(request, condition, model_config, output_dir):
            output_dir.mkdir(parents=True)
            path = output_dir / "x.png"
            size = (request["canvas"]["width"], request["canvas"]["height"])
            Image.new("RGB", size).save(path)
            result = {"outputs": [{"path": str(path), "sha256": file_sha256(path),
                                   "width": size[0], "height": size[1], "mode": "RGB"}],
                      "observation": {"image_calls_attempted": 1, "image_calls_completed": 1,
                                      "actual_generation_count": 1, "fixture_only": True}}
            return seal_generation(request, condition, model_config, result, output_dir=output_dir)

        original_chat = stages.chat
        try:
            stages.chat = chat_spy
            final = run_case(case_root, stage_fn=judge, execute_fn=execute)
        finally:
            stages.chat = original_chat
        assert len(captures) == 1
        context = json.loads(captures[0][1]["content"][0]["text"])["context"]
        print("actual_serialized_judge_context", json.dumps(context))
        print("selected_after_content_fail", final["selected_kind"], final["selected_candidate_id"])
        assert set(context) == {"evaluation", "regions", "geometry_valid", "available_evidence_refs"}
        assert context["available_evidence_refs"] == ["source", "candidate"]
        assert "evidence" not in context
        assert final["selected_kind"] == "candidate_unaccepted"
        assert final["selected_candidate_id"] == "r000-p000"


if __name__ == "__main__":
    geometry_and_selection_probe()
    serialized_judge_probe()
