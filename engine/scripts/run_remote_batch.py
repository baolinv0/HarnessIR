"""Serial frozen GPU tools: pilot first, then explicitly reviewed full dataset."""
import argparse
import json
import signal
from pathlib import Path

from hir_manual.remote_batch import run_batch


def main():
    def interrupted(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--stage", choices=("pilot", "all"), required=True)
    parser.add_argument("--profile", choices=("gpu_full_v1", "gpu_yoloe26l_v1"), default="gpu_full_v1")
    parser.add_argument("--shutdown-deadline", help="UTC ISO8601; must match the verified saved shutdown receipt")
    parser.add_argument("--shutdown-record", type=Path, help="Defaults to ROOT/runtime/remote/shutdown_record.json")
    parser.add_argument("--pilot-review", type=Path, help="Required for all: accepted=true, reviewed_by, pilot_summary_sha256")
    parser.add_argument("--selection-file", type=Path, help="Optional JSON image_ids list for a reviewed subset; never counted as full dataset")
    parser.add_argument("--tool-ids", nargs="+", choices=("T1_OCR","T2_FACE","T3_DEPTH","T4_SEGMENTATION"), help="Reviewed per-tool work; full four-tool pilot gate still required")
    options = parser.parse_args()
    try:
        image_ids = None
        if options.selection_file is not None:
            image_ids = json.loads(options.selection_file.read_text(encoding="utf-8"))["image_ids"]
        summary = run_batch(options.root, options.dataset, options.stage, options.shutdown_deadline, options.pilot_review, options.shutdown_record, options.profile, image_ids, options.tool_ids)
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({"blocked": str(exc)}, ensure_ascii=False))
        return 3
    print(json.dumps({"stage": summary["stage"], "scope":summary["scope"], "complete": summary["complete"], "full_dataset_complete":summary["full_dataset_complete"], "selected_images":summary["selected_image_count"], "results": len(summary["results"]), "actual_inference_confirmed": summary["actual_inference_confirmed_count"], "stopped_reason": summary.get("stopped_reason"), "zip": summary["validated_results_zip"]}, ensure_ascii=False))
    return 0 if summary["complete"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
