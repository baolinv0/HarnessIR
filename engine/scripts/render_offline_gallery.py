"""Render the saved batch, without running models or altering Controller state."""
import argparse
from datetime import datetime
from pathlib import Path

from hir_manual.offline_gallery import render_gallery
from hir_manual.storage import read_json


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--batch", type=Path, default=root / "runtime/quality20/pilot20_20261013_stable_v2")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--offline-status", type=Path)
    options = parser.parse_args()
    output = options.out or options.root / "runtime/reports/offline20" / datetime.now().strftime("%Y%m%d_%H%M%S")
    status = read_json(options.offline_status) if options.offline_status else None
    print(render_gallery(options.root, options.batch, output, status))


if __name__ == "__main__":
    main()
