"""Import only already completed, independently frozen SAM3.1 native evidence."""
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine/src"))
from hir_manual.sam31_evidence import import_image, RAW_CONTRACT, RUN_ID
from hir_manual.storage import read_json

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--delivery", type=Path)
    parser.add_argument("--image-id", action="append", help="Repeat for bounded selections; omit to import all frozen20")
    args = parser.parse_args()
    delivery = args.delivery or args.root / "Data/annotations/cache/alternatives/SAM31" / RAW_CONTRACT / RUN_ID
    rows = read_json(delivery / "inputs.json")["images"]
    ids = args.image_id or [r["image_id"] for r in rows]
    for image_id in ids:
        print(json.dumps(import_image(args.root, delivery, image_id), ensure_ascii=False), flush=True)
