"""Small launcher executed by each upstream's independently deployed Python."""
from __future__ import annotations

import json
from pathlib import Path
import random
import runpy
import socket
import sys


def _offline(*args, **kwargs):
    raise RuntimeError("SR native invocation is offline; deploy all resources before running")


def guard_image(image, expected: tuple[int, int], directory: Path) -> None:
    image.save(directory / "native_before_color.png")
    alpha = image.convert("RGBA").getchannel("A").getextrema()
    valid = image.size == expected and alpha == (255, 255)
    report = {"status": "passed" if valid else "failed", "expected_size": list(expected),
              "native_size": list(image.size), "opaque": alpha == (255, 255),
              "stage": "pipeline_return_before_color_fix_or_output_resize"}
    (directory / "native_validation.json").write_text(json.dumps(report), encoding="utf-8")
    if not valid:
        raise RuntimeError("Native SeeSR output failed geometry/alpha contract before official output resize")


def main(argv: list[str]) -> None:
    kind, repo, seed, width, height, destination, bert, separator, *arguments = argv
    if separator != "--" or kind not in {"reconstruction", "seesr"}:
        raise ValueError("Invalid SR launcher arguments")
    socket.socket.connect = _offline
    socket.create_connection = _offline
    sys.path.insert(0, repo)
    import numpy as np
    import torch

    random.seed(int(seed))
    np.random.seed(int(seed) % (2**32))
    torch.manual_seed(int(seed))
    torch.cuda.manual_seed_all(int(seed))
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    script = "inference_realesrgan.py"
    if kind == "seesr":
        from transformers import BertTokenizer
        load_tokenizer = BertTokenizer.from_pretrained

        def from_local(name, *args, **kwargs):
            if name == "bert-base-uncased":
                name = bert
            return load_tokenizer(name, *args, **{**kwargs, "local_files_only": True})

        BertTokenizer.from_pretrained = from_local
        from pipelines.pipeline_seesr import StableDiffusionControlNetPipeline
        original_call = StableDiffusionControlNetPipeline.__call__

        def guarded_call(self, *args, **kwargs):
            result = original_call(self, *args, **kwargs)
            if len(result.images) != 1:
                raise RuntimeError("SeeSR must return exactly one native image")
            guard_image(result.images[0], (int(width), int(height)), Path(destination))
            return result

        StableDiffusionControlNetPipeline.__call__ = guarded_call
        script = "test_seesr.py"
    sys.argv = [str(Path(repo) / script), *arguments]
    runpy.run_path(sys.argv[0], run_name="__main__")


if __name__ == "__main__":
    main(sys.argv[1:])
