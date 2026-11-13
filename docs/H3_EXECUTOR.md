# MiniMax H3-Image executor in HarnessIR

This branch switches the **classic HarnessIR executor** in `run_harness.py` and `run_baseline.py` to `minimax-h3-image`. Diagnosis, tool evidence, prompt composition, optional verify/refine, and output geometry are unchanged. The old `nb2` and `gpt-image-2.5` executors remain selectable for matched comparisons. No results from the original paper are relabeled as H3 results.

**Scope boundary:** the separate `engine/src/hre/v3` four-model research workflow and `engine/src/hre/sr` fixed C3 Qwen-Image-2.1 recipe are **not** modified in this change. Those have their own frozen model identities and would need a separate H3 experiment protocol, not a silent model-name substitution.

## Run a local SGLang server

Install SGLang with diffusion dependencies following the [official MiniMax instructions](https://github.com/MiniMax-AI/MiniMax-H3-Image). Example for a four-GPU deployment:

```bash
sglang serve --model-path MiniMaxAI/MiniMax-H3-Image \
  --host 127.0.0.1 --port 30000 --warmup-mode off \
  --num-gpus 4 --ulysses-degree 4
```

The model is large (33.1B DiT + 33.4B text encoder); prepare the checkpoint and serving environment before testing. The H3 editor adapter does **not** download or load weights itself.

```bash
export HARNESS_H3_BASE_URL=http://127.0.0.1:30000
export HARNESS_H3_SEED=1234
# Optional when the serving gateway requires authentication:
# export HARNESS_H3_API_KEY=...
# These still configure the separate diagnosis/composition VLM:
export HARNESS_API_BASE=https://YOUR_GEMINI_COMPATIBLE_ENDPOINT
export HARNESS_API_KEY=YOUR_VLM_KEY

# Harnessed restoration, retaining the existing output layout:
python run_harness.py --manifest /path/to/manifest.json \
    --lq-root /path/to/images --out runs/h3_harness --executor minimax-h3-image

# Fair direct-use baseline with the same H3 executable:
python run_baseline.py --manifest /path/to/manifest.json \
    --lq-root /path/to/images --out runs/h3_direct --executor minimax-h3-image
```

## Exact transport

- An image edit is one multipart `POST /v1/images/edits` with one or more `image` parts (in reference order); the first is `<Picture 1>`.
- Send `prompt`, `size=WIDTHxHEIGHT`, `seed`, `generator_device=cpu`, and `response_format=b64_json`. The server returns a PNG in `data[0].b64_json`.
- Existing `MFM_IMAGE_SIZE=1K` maps the incoming square 1024 canvas to a 1024x1024 response. Per the H3 server's default `min_generation_area`, inference internally uses at least 2048x2048 and may downsample. Consequently **this is an interface-parity experiment, not a measurement of H3's native 16MP capability**.
- No `guidance_scale`, `negative_prompt`, or arbitrary `num_inference_steps` is sent. H3 runs its distilled six-step schedule.
- H3 currently has **no native mask-inpainting interface**. Existing region masks in the diagnostic stage are not delivered to this model.
- H3 calls are not retried automatically. For non-idempotent image generation, a timeout is an unknown outcome rather than proof the model failed.
- A separate `HARNESS_H3_BASE_URL` prevents accidentally sending H3 requests to the Gemini-compatible VLM endpoint.

## Verification

```bash
python -m pytest -q tests/test_h3_executor.py
python run_harness.py --help
python run_baseline.py --help
```

Then run one image end-to-end using the actual H3 server. Confirm input/reference ordering, received output geometry, saved `raw_outputs/` image and final crop, and the verifier's structure-preservation result. For a model comparison, freeze prompts and source images, run the direct baseline and HarnessIR with the **same H3 server**, and compare content fidelity separately from visual restoration.

The tests above mock the server; they do not establish GPU deployment readiness or restoration quality.
