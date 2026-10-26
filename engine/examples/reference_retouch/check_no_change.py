"""Run the actual v3 no-edit control on a real photo, with no remote calls.

This deliberately narrow control uses the SAME source as its reference and an
appearance-only brief. Pixel identity supplies the diagnostic evidence. It does
not test a VLM's diagnostic accuracy or a generator's image quality.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path

from hre.v3.common import digest
from hre.v3.contracts import create_case
from hre.v3.reference_retouch import REFERENCE_DIMENSIONS, VERSION
from hre.v3.runner import run_case


def check(source: Path, output: Path) -> dict:
    source, output = source.resolve(), output.resolve()
    spec = {"schema_version": "hre_task_v3", "workflow_contract": VERSION,
        "case_id": "pixel-identity-no-change", "profile_id": "qwen21", "strategy": "shared",
        "task_mode": "reference_enhance", "brief": "Match B's existing photographic appearance only. No other enhancement is requested.",
        "source": {"path": str(source)}, "reference": {"path": str(source)},
        "policy": {"mode": "single", "max_generations": 1}}
    # This required native profile is never loaded or invoked in the control.
    config = {"models": {"qwen21": {"compiler": {"backend": "direct"},
        "editor": {"model_id": "Qwen/Qwen-Image-2.1"}}}}
    state = create_case(output, spec, config)
    assert state["inputs"][0]["pixel_sha256"] == state["inputs"][1]["pixel_sha256"]
    proof = "A and B are pixel-identical after canonicalization; the requested reference appearance is already present."
    protected = ["Preserve every source pixel and all source content, text, identity, expression and geometry."]
    diagnosis = {"schema_version": "hre_reference_diagnosis_v1", "task_mode": "reference_enhance",
        "findings": [], "protected_content": protected, "uncertainties": [], "tool_requests": ["basic_statistics"],
        "summary": proof, "analysis_status": "already_close", "candidate_deltas": [],
        "reference_profile": [{"attribute": a, "status": "observed", "observation": proof,
            "region": "whole image", "evidence_refs": ["source", "appearance_reference"]} for a in sorted(REFERENCE_DIMENSIONS)],
        "coverage": [{"attribute": a, "status": "already_satisfied", "reason": proof, "delta_ids": []}
            for a in sorted(REFERENCE_DIMENSIONS)]}
    intent = {"schema_version": "hre_reference_intent_v1", "task_mode": "reference_enhance", "revision": 0,
        "targets": [], "region_relations": [], "protected_content": protected, "uncertainties": [], "summary": proof,
        "parent_intent_hash": None, "feedback_refs": [], "overall_status": "already_satisfied", "excluded_reference_traits": [],
        "coverage": [{"attribute": a, "status": "already_satisfied", "reason": proof, "target_ids": []}
            for a in sorted(REFERENCE_DIMENSIONS)]}

    def stage(request):
        assert request["stage"] in {"diagnose", "compose"}
        return {"payload": deepcopy(diagnosis if request["stage"] == "diagnose" else intent),
            "observation": {"calls_attempted": 0, "calls_completed": 0, "kind": "deterministic_pixel_identity_control",
                "stage_request_id": request["request_id"], "stage_request_sha256": digest(request)}}

    def forbidden(*args, **kwargs):
        raise AssertionError("An already-satisfied control must never invoke a compiler or generator")

    state = run_case(output, stage_fn=stage, compile_fn=forbidden, execute_fn=forbidden)
    assert state["success"] and state["terminal_reason"] == "already_satisfied"
    assert state["selected_output"]["pixel_sha256"] == state["inputs"][0]["pixel_sha256"]
    assert state["budget"] == {"generations": 0, "stage_calls": 0, "compiler_calls": 0}
    return {"status": state["quality_status"], "source_pixels_unchanged": True,
        "source_size": [state["canvas"]["width"], state["canvas"]["height"]], "budget": state["budget"],
        "source_pixel_sha256": state["inputs"][0]["pixel_sha256"], "case_root": str(output),
        "scope": "Exact-image appearance-only control; no automatic VLM or image-model quality claim."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="Fresh case directory; existing data is never overwritten")
    args = parser.parse_args()
    print(json.dumps(check(args.source, args.out), ensure_ascii=False, indent=2))
