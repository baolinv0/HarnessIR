"""Create synthetic CLI inputs. These are not model or image-quality results."""
from argparse import ArgumentParser
import json
from pathlib import Path

from PIL import Image


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = args.out.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    paths = [root / name for name in ("source.png", "task.json", "config.json")]
    if any(path.exists() for path in paths):
        parser.error("Use a fresh directory; an existing fixture will not be overwritten")
    image = Image.new("RGB", (256, 256))
    image.putdata([(x, y, (x * 3 + y * 5) % 256) for y in range(256) for x in range(256)])
    image.save(paths[0])
    task = {
        "schema_version": "hre_sr_v02", "case_id": "synthetic_contract_fixture",
        "source": {"path": str(paths[0])}, "scale": 4, "seed": 42,
        "rois": [{"id": "detail", "box": [32, 32, 224, 224]}],
    }
    config = {
        "mode": "fixture", "fixture_marker": "SR_TEST_FIXTURE_NOT_MODEL_QUALITY",
        "fixture": {"candidates": {key: "ok" for key in ("C0", "C1", "C2", "C3")},
                    "judge": {"content": {key: "pass" for key in ("C0", "C1", "C2", "C3")},
                              "improved": ["C1"], "ranking": ["C1", "C2", "C3"]}},
    }
    for path, value in zip(paths[1:], (task, config)):
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"fixture_only": True, "task": str(paths[1]), "config": str(paths[2]),
                      "quality_evidence": "none; scripted decisions and synthetic outputs"}, indent=2))


if __name__ == "__main__":
    main()
