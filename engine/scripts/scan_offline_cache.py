"""Read-only strict GPU evidence inspection; no imports or case transitions."""
import argparse
import json
from pathlib import Path

from hir_manual.offline_monitor import scan_offline_cache


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--dataset", type=Path, default=root / "runtime/offline_gpu/prepared_20261013")
    parser.add_argument("--batch", type=Path)
    parser.add_argument("--out", type=Path, default=root / "runtime/offline_monitor/status.json")
    parser.add_argument("--profile", choices=("gpu_full_v1", "gpu_yoloe26l_v1"), default="gpu_full_v1")
    args = parser.parse_args()
    status = scan_offline_cache(args.root, args.dataset, args.out, args.batch, args.profile)
    print(json.dumps({"complete": status["complete"], "prepared_images": status["prepared_image_count"], "unsupported_inputs": len(status["unsupported_original_inputs"]), "accepted_gpu_results": status["accepted_gpu_results"], "expected_tool_results": status["expected_tool_results"], "status": str(args.out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
