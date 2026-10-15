# Isolated local model workers (evidence protocol 1.1)

The controller starts a separate Python executable for one image and one tool:

```text
<isolated-python> preprocessing/worker_main.py --job <absolute-job.json> --out <result-directory>
```

`job.json` follows `Design_v1_1_20261012/schemas/tool_job.schema.json`. Its directory also contains immutable `input/canonical.png` and `runner_config.json`:

```json
{
  "registry_entry": {
    "model_name": "SCRFD_det_10g",
    "python_executable": "<local-isolated-python>",
    "components": [{"name": "detector", "path": "<local-file>", "sha256": "<sha256>"}],
    "model_bundle_sha256": "<ordered-component-bundle-sha256>",
    "backend": {"implementation": "insightface_scrfd_detector_only", "source_revision": "<revision>", "framework": "onnxruntime", "framework_version": "<version>", "device": "cpu", "precision": "fp32", "environment_lock_sha256": "<sha256>"},
    "artifact_paths": {"checkpoint": "<det_10g.onnx>", "scrfd_source": "<locked-scrfd.py>"}
  },
  "profile": {"cpu_threads": 2, "formal_eligible": false, "offline": true, "auto_download": false, "auto_install": false},
  "original_sha256": "<source-file-sha256>",
  "source_width": 1024,
  "source_height": 768
}
```

The example illustrates runner configuration only; placeholder values are not inference evidence. Parameters come from the job's frozen cache contract. The registry's model bundle and backend must match it exactly.

Success writes `evidence.json`, every listed artifact, then `worker_done.json`. The completion marker has `evidence_sha256` and an ordered `artifact_hashes` array of `{path, sha256}`. Failure writes `error.json`, `worker_error.json`, and `worker_traceback.log`, exits nonzero, and never writes a completion marker. Error codes distinguish `model_missing`, `import_error`, `oom`, `timeout`, and `unavailable`.

No worker imports the controller package. Heavy SDK imports happen inside each tool's `run()` function. Offline environment flags, Python socket audit events, and package-install subprocess checks are enforced before SDK initialization. The controller is responsible for resource sampling, timeout, termination, schema validation, cache publication, and readiness after actual warm-up.

## Required artifacts

| Tool | Registry artifact paths | Runtime API |
|---|---|---|
| T1 | `detection_model_dir`, `recognition_model_dir` | PaddleOCR `TextDetection` + `TextRecognition`, with native PaddleX `CropByPolys`; PP-OCRv6 Medium only |
| T2 | `checkpoint`, `scrfd_source` | Locked official SCRFD detector source and ORT session; no recognition model |
| T3 | `checkpoint`, `source_dir` | Author `DepthAnythingV2.infer_image`; vits Small CPU or vitb Base GPU |
| CPU T4 | `checkpoint`, `text_embeddings`, `prompt_set`, `text_encoder` | Ultralytics YOLOE-26n-seg with precomputed fixed text embeddings |
| GPU T4 | `checkpoint`, `source_dir`, `tokenizer` | Meta `build_sam3_image_model(load_from_HF=False)` and `Sam3Processor`; SAM 3 only |

`prepare_models.py --tool <tool-id> --registry preprocessing/registry/cpu_probe_v1.json` explicitly downloads the CPU artifacts and installs their separate environments. It records source download hashes, model component hashes, exact dependencies in a freeze file, and pip installation reports. A registry remains `ready=false` until a genuine warm-up is validated. Repeating preparation validates existing artifacts against the stored download receipts. Runtime never calls preparation.

All evidence asset paths are relative to the output directory; component paths are stripped from the evidence manifest. `raw_data`, `json`, and `text` assets have null image dimensions. Depth remains float32 with a separate valid mask. Each segmentation instance retains its native mask and association; class union files, overlap pixels, and region summaries appear in `raw/seg.json`. The display raster's class zero means unassigned/unknown, and its palette is stable across images.

## Official source references checked for this implementation

- PP-OCRv6 and local Paddle models: https://www.paddleocr.ai/main/en/version3.x/pipeline_usage/OCR.html
- Native Paddle recognition outputs: https://www.paddleocr.ai/main/en/version3.x/module_usage/text_recognition.html
- SCRFD detector API: https://github.com/deepinsight/insightface/blob/v0.7/python-package/insightface/model_zoo/scrfd.py
- Author DA-V2 API and configs: https://github.com/DepthAnything/Depth-Anything-V2
- YOLOE text encoder downloads and offline embeddings: https://docs.ultralytics.com/models/yoloe/
- Meta SAM 3 image API and requirements: https://github.com/facebookresearch/sam3

Pinned CPU preparations use PaddleOCR 3.7.0 / PaddlePaddle 3.3.1; ORT 1.23.2 and InsightFace source commit `3e6486942a1be2da0e5b475fac375ea73264bd21`; author DA source `a561b849ebae10a6f5ef49e26c83cbbcd36c71bf` and Small weight revision `03876f8651c73a60fe4c2c48294e09fcb6838fcf`; PyTorch 2.10.0 CPU / torchvision 0.25.0; Ultralytics 8.4.175 and tokenizer source `7ffa84b3bfa40c42ecc1c77147a855e69cb2dd40`. Actual framework version strings and environment locks are read back after installation. These version choices are deployment locks, not measured speed or memory guarantees.

The official SAM 3 setup requires Python 3.12+, PyTorch 2.7+, and CUDA 12.6+ hardware. GPU weights and tokenizer must already exist locally; an absent backend/artifact produces an explicit failure. No model substitution is implemented. CPU probe and GPU full results have different frozen contracts.
