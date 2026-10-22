# Model-Aware HarnessIR: run and inspect stages in parallel

Two entry points share one implementation:

| Entry point | Purpose | Case progression |
|---|---|---|
| `hre v2 run` | Diagnose → Compose → model condition → Execute → Verify | Uses the existing Controller and generation budget |
| `hre v2 stage-export`, `stage-run`, `stage-compare` | Inspect one frozen stage and compare its outputs side by side | Does not advance the case; does not call an image editor |

The complete workflow does **not** wait for stage experiments to pass. Export a
pending stage when you want an independent check, or run the full case directly.

## Installation and a runnable smoke demonstration

From the repository root:

```bash
python -m pip install -e './engine[test]'
python engine/examples/model_aware_demo.py --out /tmp/hre-model-aware-demo
```

The demonstration uses real subprocess handoffs and the complete Controller, but
its images and judgments are explicitly synthetic. It must finish with
`workflow_state=COMPLETED`, one charged generation and a separate stage check.
It makes no image-model call and provides no evidence of model quality.

## Enable a new case

Add this field to your existing v2 case specification before `hre v2 create`:

```json
"model_aware": {
  "profile_id": "qwen21",
  "strategy": "model_aware",
  "compiler": "direct"
}
```

| Profile | Condition | Built-in compiler | Native compiler worker |
|---|---|---|---|
| `flux3_klein` | Full-scene caption | None | Actual FLUX PUP |
| `fibo2_dev` | Native VGL JSON with `edit_instruction` | None | Actual Bria VGL |
| `qwen21` | Concise semantic instruction | `direct` | Official PE-I2I |
| `firered11` | Coherent full-frame edit instruction | `direct` | Actual Recaption |

Use `compiler="native"` to invoke your deployed native compiler worker. Generic
VLM rewriting is not substituted for PUP, VGL, PE-I2I or Recaption. All profiles
currently use full-frame A+B. Profile capabilities are declared, not established
by real HarnessIR image tests; Mask/BBox/ROI fusion is not enabled here.

G0 requires `strategy="native"`; G1 accepts `shared` or `model_aware`. Existing G2
is a different paired mask experiment and does not accept this opt-in. A direct
Qwen/FireRed baseline is explicitly the direct path, not a claim of the best
possible upstream pipeline. Freeze the same compiler choice in compared arms.

Compose can plan up to three supported `region_relations` between distinct frozen
ROI IDs. These are preserved in the compiler request with the independent A/B
coordinates, statistics, comparability and content constraints. An empty relation
list means none was supported, not that the regions are independent.

## Full execution

Create `workers.json` with installed commands, not shell command strings:

```json
{
  "schema_version": "hre_workers_v1",
  "timeout_seconds": 900,
  "workers": {
    "stage": ["python", "-m", "hre.model_workers"],
    "execute": ["python", "-m", "hre.native_editor"]
  }
}
```

The built-in stage worker supports an OpenAI-compatible vision
`/chat/completions` endpoint:

```bash
export HRE_VLM_BASE_URL='http://localhost:8000/v1'
export HRE_VLM_MODEL='your-deployed-vision-model'
# Set HRE_VLM_API_KEY only when the endpoint requires it.
hre v2 create --prediction A.png --reference B.png --spec spec.json --case-root runs/case-01
hre v2 run --case-root runs/case-01 --workers workers.json
```

`HRE_VLM_TIMEOUT` defaults to 120 seconds. The non-secret endpoint/model settings
are frozen for the case. Credentials remain in the environment. Successful API
responses retain requested/returned model identity, usage when supplied, and
elapsed time. A stage-specific command such as `verify` overrides `stage`.

The local native editor supports Qwen-Image-2.1 and FireRed-Image-Edit-1.1 with
already deployed model weights. Install compatible `torch`, `diffusers` and model
dependencies in that worker's environment. It uses `local_files_only=True`, one
pipeline call, A then B, and explicit A width/height. It does not resize an invalid
canvas or repair an output silently. Configure the frozen v2 `executor` with:

- `executor_id`: `hre-native-diffusers`; `transport`: `api`.
- `adapter_version`: `hre.native_editor.v1`.
- `model_display_name`: the profile's display name; `model_exact_version`: the pinned model revision.
- `pipeline_version`: the installed `diffusers.__version__`.
- `settings`: `model_id`, `revision`, `seed`, `num_inference_steps`,
  `true_cfg_scale`, `negative_prompt`, `device`, `torch_dtype`; Qwen additionally
  requires `output_resolution` and `use_kv_cache`. Optional
  `num_images_per_prompt` must be 1.

See `native_editor.py` for the validated runtime settings. Different models need
different inference settings; do not force a common CFG or step count.

For FLUX/Fibo, or a hosted editor, set `execute` to your real adapter command.
For any native compiler, also set `condition` to its adapter command. Missing
deployments produce a clear error; the runtime never fabricates native output.

## Independent stage testing and comparison

Start or run a case to the desired pending stage, then export its frozen inputs:

```bash
hre start --case-root runs/case-01
hre v2 stage-export --case-root runs/case-01 --out checks/qwen-diagnose-input
hre v2 stage-run --request checks/qwen-diagnose-input/worker_request.json \
  --workers workers.json --out checks/qwen-diagnose
hre v2 stage-compare --checks checks/qwen-diagnose checks/firered-diagnose \
  --out checks/diagnose-comparison.html
```

Repeat with other worker configurations or model-condition requests. The portable
HTML shows attached A/B/C images where present, final instructions, structured
outputs and observed call metadata. It flags different A/B bytes. It does not
invent a quality ranking. Stage checks validate schemas and condition bindings;
their judgments still need content/visual evaluation.

Use `--max-steps 1` on `v2 run` to advance one orchestration step at a time. At the
condition boundary the case is `PAUSED/condition_compilation_required`; this is
the existing Controller's external compilation wait, not an experiment gate.
The full runner compiles it automatically when configured. For manual compilers:

```bash
hre v2 condition-export --case-root runs/case-01 --out compiler-input
# Run the actual compiler using A.png, B.png and condition_request.json.
hre v2 condition-import --case-root runs/case-01 --result compiler-result.json
```

## Worker protocol and audit

Every external command receives `--request PATH --response PATH` and runs once
without a shell. The input envelope contains `kind`, frozen `request`, `prompt`,
ordered `attachments`, `executor`, `output_dir` and `bundle_path`.

| Kind | Response |
|---|---|
| `stage` | `{"payload": {...}}`, or `{"payload": null, "error": {"code": "...", "message": "...", "retryable": false}}`; optional actual `provenance`/`worker_observation` |
| `condition` | `model_condition_result_v1`: matching request/profile IDs, status, final `edit_prompt`, A canvas, actual `compiler_observation`, and native output needed by that profile |
| `execute` | `{"image_path": "/absolute/C.png", "metadata": {...}}` using the existing observed execution receipt, provider order and actual generation count |

Fibo `edit_prompt` is a serialized native JSON object with a nonempty
`edit_instruction`. Qwen native output must parse, follow `<image1>`/`image1`,
have no ratio override, and have the exact final `positive_prompt`. These are
structural checks, not a semantic guarantee that a caption preserves A.

Compiler calls are separately recorded and do not consume image-generation
slots. The generation slot is reserved only after condition acceptance. Final
native text reaches the editor unchanged. Unknown submissions pause for explicit
reconciliation; rerunning the runner does not make another image. Stdout/stderr,
invocation status, frozen request files and accepted outputs remain available.

## Comparing strategies

Run native, shared and model-aware as separate frozen case revisions. For a
compiler-only shared/model-aware comparison, reuse the exact accepted diagnosis
and composition payloads and verify identical intent bytes; rerunning planning
confounds the comparison. Keep source images, executor version/settings and
compiler choice fixed within a model. Report content preservation, reference
attribute following, region coordination and cost separately. The existing
independent R1/R2 evaluation remains the source of quality claims.

No GPU inference or four-model quality experiment is established by the bundled
software tests or synthetic example. Native PUP/VGL/PE/Recaption deployment and
semantic caption auditing are explicit remaining integration/evaluation work.
