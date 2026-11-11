# Evidence-driven SR v0.2

This opt-in path runs a fixed four-candidate SR experiment and compares a visual Judge with the same Judge given bound numerical evidence. The existing x1 restoration/reference commands retain their contracts. The implementation is prepared for independent review; software fixtures are not restoration-quality evidence.

## Runtime and entrypoint

From the repository root, install the engine in an isolated environment:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r engine/requirements-lock.txt
python -m pip install --no-deps -e ./engine
python -m hre sr --help
```

The real profile supports **x4 only**, eight-bit SDR input and opaque alpha. A different scale is rejected. Nonopaque source or native output is rejected rather than silently flattened. Original and canonical input bytes are retained and hashed. ROI boxes use original LR integer pixels in `[x0, y0, x1, y1]` order; the last edge is exclusive. Their HR coordinates are exactly four times these values.

For a 256x256 source, native content and delivered output must remain 1024x1024. For a 257x193 source they must remain 1028x772. Each model may have declared right/bottom edge padding; delivery removes that padding at HR scale. A wrong native size is a contract failure, not an invitation to resize the result into compliance.

## Run a CPU-only end-to-end fixture

The helper creates synthetic pixels and a configuration whose model and Judge responses are explicitly scripted. It uses a fresh directory and does not overwrite existing fixtures.

```bash
python engine/examples/evidence_sr_v02/make_fixture.py --out .work/sr-smoke-input
python -m hre sr create \
  --case-root .work/sr-smoke-case \
  --spec .work/sr-smoke-input/task.json \
  --config .work/sr-smoke-input/config.json
python -m hre sr run --case-root .work/sr-smoke-case
python -m hre sr show --case-root .work/sr-smoke-case
python -m hre sr report --case-root .work/sr-smoke-case
python -m hre sr resume --case-root .work/sr-smoke-case
```

Inspect the actual selected image dimensions, the four recipe records, request snapshots and journal. The expected scripted selection is C1 with a 1024x1024 output. The final resume must reuse observations and make no new model/Judge call. The configuration contains `SR_TEST_FIXTURE_NOT_MODEL_QUALITY`; fixture cases cannot satisfy the real development-study gate.

Useful failure scenarios can be exercised in a new fixture configuration before creating a new case: candidate `wrong_size`, `transparent`, `corrupt`, `fail`, `blocked` or `crash`; Judge content `fail` or `uncertain`; Judge `invalid`, `truncated`, `unavailable` or `crash`. Do not edit an existing case's frozen configuration.

## Configure the actual four candidates

Copy [the runtime example](../../engine/examples/evidence_sr_v02/runtime.example.json) to a local configuration and replace its paths and deployment identifiers. Empty Qwen revision/pipeline values are intentional placeholders and remain blocked. The example Judge model is also a placeholder; configure the deployed VLM rather than assuming a model name from a paper or conversation.

| Slot | Actual execution | Frozen distinction |
| --- | --- | --- |
| C0 / Y0 | Official `RealESRNet_x4plus` inference | Reconstruction baseline, native x4, fp32 |
| C1 | Original LR → Gaussian blur radius 0.35 → the same RealESRNet inference | The prefilter is the only change to the SR recipe; same model, settings and seed |
| C2 | Official SeeSR `test_seesr.py` | Independent input, fixed prompts, seed, steps and settings |
| C3 | Existing native Qwen-Image-2.1 adapter | Direct LR conditioning with an explicit padded HR output canvas |

The blur radius and soft proxy set are initial development choices, not validated optima. Every candidate starts from the immutable original LR. C1's derivative is retained with its transformation and hash. Candidate outputs are never chained into another recipe.

### Reconstruction deployment

Use [Real-ESRGAN source at a4abfb2979a7bbff3f69f58f58ae324608821e27](https://github.com/xinntao/Real-ESRGAN/tree/a4abfb2979a7bbff3f69f58f58ae324608821e27), its own configured Python and a local `RealESRNet_x4plus.pth` checkpoint. The [official model zoo](https://github.com/xinntao/Real-ESRGAN/blob/a4abfb2979a7bbff3f69f58f58ae324608821e27/docs/model_zoo.md) identifies this as the MSE-trained model. Its similarly named RealESRGAN counterpart is a different baseline.

The adapter calls the actual official CLI, with `--model_path`, native `--outscale 4`, one source and a fresh output directory. It does not enable GFPGAN. A zero exit status without the expected image is a failure. The upstream CLI can catch a CUDA error and still exit zero, so process status alone is insufficient.

### SeeSR deployment

Use [SeeSR source at b13b8ac3bbcc6b9a6baa970ee5349628070877ee](https://github.com/cswry/SeeSR/tree/b13b8ac3bbcc6b9a6baa970ee5349628070877ee) in a separate environment. Its upstream Torch/Diffusers/Pydantic versions conflict with the HarnessIR/Qwen environment.

Required local resources are the SD2 base, SeeSR UNet/ControlNet, DAPE checkpoint, a local BERT tokenizer and the RAM base checkpoint at `preset/models/ram_swin_large_14m.pth` under the SeeSR checkout. Preflight checks the configured Python, imports and CUDA. The execution launcher uses local resources and disables network loading. A missing prerequisite is reported; no substitute model is run.

At process_size512 and scale4, preparation pads LR edges to at least128 and to an even size, so the model's HR canvas is divisible by8. This avoids SeeSR's internal small-image enlargement and multiple-of-eight rounding. The launcher also checks pipeline output **before** the official script's color alignment and final resize. Delivery then crops only the declared HR padding.

### Qwen and Judge

Deploy the existing Qwen-Image-2.1 runtime and source requirements described by the repository's v3 adapter. Record the checkpoint revision, matching Diffusers pipeline version and deployment manifest. The SR wrapper retains the existing checks. C3 pads LR to a multiple of8 so its x4 HR canvas is divisible by32, then invokes the real adapter with separate conditioning and output sizes.

The Judge uses the existing OpenAI-compatible chat transport. Configure the exact endpoint, model, settings and optional environment-variable name for its credential. Credentials are not stored in the task JSON. These settings are frozen into the case; both arms share them.

```bash
python -m hre sr preflight --config /path/to/sr-runtime.local.json
python -m hre sr create \
  --case-root /data/sr-runs/dev01 \
  --spec /path/to/dev01-task.local.json \
  --config /path/to/sr-runtime.local.json
python -m hre sr run --case-root /data/sr-runs/dev01
python -m hre sr report --case-root /data/sr-runs/dev01
```

Use [the task example](../../engine/examples/evidence_sr_v02/task.example.json), adjusting ROI bounds to the actual LR image. Preflight and source-code inspection are not evidence that a model has run. The current delivery includes no real GPU or VLM quality results.

## What the Judge receives

The online request includes the source, common Y0, anonymized candidates and frozen full-frame/ROI attachments. Image data is serialized once, and both arms reuse identical transmitted bytes, labels, order and layout. Actual transport-image hashes are retained in addition to original/canonical/candidate file hashes. The only experimental input difference is the designated evidence text.

The local alias mapping keeps model/recipe identity out of the online request. GT is not an allowed online input. The frozen geometry describes the source-to-HR mapping; images are not presented as if LR and HR shared the same pixel grid.

| Evidence layer | What it can establish | Authority |
| --- | --- | --- |
| Hard contract | Decode, file identity, exact size, padding/crop, alpha and binding integrity | A failure makes the candidate ineligible |
| `lr_consistency_v1` | Low-resolution consistency under the declared downsampler | A soft proxy; does not establish authentic high-frequency detail |
| `clipping_v1` | Display-domain clipping changes | A soft cue for saturation/overcorrection |
| `edge_energy_v1` | Relative edge energy/texture change | A soft cue; sharpness can also increase through artifacts |
| Visual assessment | Visible content preservation and perceptual progress against Y0 | A bound judgment, including explicit uncertainty |

Measurements bind source, candidate, Y0, ROI, geometry and method identities. Missing, failed or stale records do not become passes. These initial proxies are provisional until documented development failures justify a selected set. No proxy threshold certifies recovered detail.

## Formal result and recovery

The evidence arm drives the formal result under the frozen policy. A candidate needs a valid hard contract, explicit content-preservation pass and explicit improvement over Y0. If none qualifies, a contract-valid and content-qualified Y0 can be returned. If Y0 fails or its content is uncertain/unassessed, the case is `unresolved` and `selected_output` is null. LR input and content-failed candidates remain audit artifacts, never formal SR outputs.

Each side effect has a durable submission marker and bound completion receipt. Completed observations are reused on resume. An interrupted operation without a reliable receipt is unknown, and resume must not resend it. Inspect the journal and operation artifacts. The conservative reconciliation command abandons a specifically identified unknown operation using an operator note; it does not regenerate it:

```bash
python -m hre sr reconcile \
  --case-root /data/sr-runs/dev01 \
  --operation model_C1 \
  --note 'Confirmed operator decision to abandon this unknown attempt; no resubmission'
python -m hre sr resume --case-root /data/sr-runs/dev01
```

Use the actual operation ID from the case, not the example ID when a different operation is pending. Keep model stdout, generated semantic prompts and image artifacts local; the source repository needs only code, examples and software-validation evidence.

## Development 8 → freeze → held-out test 16

[The study example](../../engine/examples/evidence_sr_v02/study.example.json) contains placeholder paths for eight development and sixteen test cases. Replace the paths and original-pixel ROI bounds with the actual dataset. Canonical source identity is used to reject overlap, including re-encoded duplicates. No real cases were supplied in this implementation session.

```bash
python -m hre sr study create \
  --root /data/sr-study-v02 \
  --manifest /path/to/sr-study.local.json \
  --config /path/to/sr-runtime.local.json
python -m hre sr study run --root /data/sr-study-v02 --phase dev
python -m hre sr study report --root /data/sr-study-v02
python -m hre sr study freeze \
  --root /data/sr-study-v02 \
  --selection /path/to/dev-proxy-selection.local.json
python -m hre sr study run --root /data/sr-study-v02 --phase test
python -m hre sr study report --root /data/sr-study-v02
```

The selection record names implemented methods and cites actual development failure artifacts with their hashes and the reason each method is useful. Copy identities from the recorded cases; do not use placeholder hashes or claim that successful fixture runs establish suitability. The test phase is held until this freeze succeeds. Recipes, model/runtime identities, seeds, Judge conditions, layout/mapping policy and selected methods stay frozen; per-case images and ROI locations are bound separately.

The complete input shape for `--selection` is below. `clipping_v1` illustrates one implemented method; select the methods justified by the actual development failures, from `lr_consistency_v1`, `clipping_v1` and `edge_energy_v1`. Replace all uppercase placeholders and add observations as needed. There is no `schema_version` field in this input:

```json
{
  "methods": ["clipping_v1"],
  "observations": [
    {
      "case_id": "ACTUAL_DEVELOPMENT_CASE_ID",
      "artifact_sha256": "ACTUAL_SHA256_FROM_THE_CASE_REPORT_ARTIFACTS_MAP",
      "failure": "DESCRIBE_THE_OBSERVED_DEVELOPMENT_FAILURE",
      "why_method": "EXPLAIN_WHY_THE_SELECTED_METHOD_ADDRESSES_THAT_FAILURE"
    }
  ]
}
```

Each completed development report is retained at `<study-root>/results/dev/<case_id>.json`. Its `artifacts` object maps case-relative artifact paths to their SHA-256 values. Inspect the corresponding artifact before citing its exact hash; `case_id` and `artifact_sha256` must match the same real development case. The freeze command re-reads all eight cases and verifies these bindings, their actual observed calls and their shared protocol. A syntactically valid placeholder file cannot open the test gate.

Reports distinguish produced/contract-valid/accepted candidate coverage, selected output, error, fallback, unresolved, blocked/failed/unknown operations and observed cost. Oracle coverage and selection error need offline labels; they stay unknown when labels are absent. Token or monetary costs remain unknown when the provider does not report them. A missing cost is not zero.

### Offline pool and selection labels

After independent annotation, supply a separate JSON to the report command. It is not part of the model or Judge request:

```bash
python -m hre sr report \
  --case-root /data/sr-runs/dev01 \
  --oracle /path/to/dev01-oracle.local.json
```

Use schema `hre_sr_oracle_v02`, the exact `case_id`, `source_sha256` and `source_pixel_sha256` from the case report, and a `method_version` naming the real labeling protocol. `candidates` must label every contract-valid slot, each with its exact delivered `sha256` and Boolean `content_preserved` and `improved_over_y0`. C0's `improved_over_y0` must be false. `best_slot` names a labeled eligible improvement, the qualified baseline when there is no improvement, or null when the pool has no suitable result. Failed products cannot qualify through labels.

For one case, `pool_oracle_quality_coverage` means that at least one valid candidate is independently labeled content-preserving and better than Y0. `selection_failure` means the selected result is outside the eligible pool; `selected_matches_best` separately checks the annotator's preferred result. `avoidable_fallback` and `avoidable_unresolved` expose cases where the pool contained a suitable result but the online selection did not use it. Across cases, aggregate these with their explicit denominators. The report retains the labeling method and label-file content hash. Labels do not change the online selection or its journal.

The study manifest may optionally contain `ground_truth: {"path": "/local/gt.png"}` per case. This is archived as offline metadata only and is excluded from each online task. This version does not implement GT metrics or generate oracle labels automatically.

After the real SR experiment is completed and reviewed, x1 restoration experiments can be designed separately. This version does not assert their results.

## Reproduce software verification

```bash
python -m pytest engine/tests -q --durations=15 -o faulthandler_timeout=120
PYTHONPATH=engine/src python docs/evidence_sr_v02/evidence/baseline_probes.py
git diff --check
```

The baseline probe intentionally demonstrates the old x1 behavior. It is not an SR passing-quality test. The validation report records the actual commands, environment, fixed implementation version and test results. The final independent code review remains a separate step.
