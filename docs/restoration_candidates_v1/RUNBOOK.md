# Run candidates on CPU and an offline GPU computer

Use [EXPERIMENT_PLAN.md](EXPERIMENT_PLAN.md) for the full research protocol and [EXPERIMENT_TRACKER.md](EXPERIMENT_TRACKER.md) for execution status. Review the current statistical acceptance gate before freezing Pilot or final experiment reports.

The source package is developed and tested on CPU. Fixture images are synthetic interpolation and scripted responses. They validate software contracts, not restoration quality. Real Qwen execution, visual improvement and VLM accuracy require separate GPU observations.

## Verify and unpack the delivery

Copy the ZIP and its `.zip.sha256` file to the execution computer. Verify the outer SHA-256 before extracting. The archive contains a `HarnessIR/` directory and no Git metadata, local runtime configuration, credentials, weights, CUDA libraries or dependency wheelhouse.

From the unpacked directory, verify every packaged file with the standard-library verifier:

```bash
python tools/build_candidates_bundle.py --verify /path/to/restoration-candidates-SNAPSHOT.zip
```

`MANIFEST.json` records the locked baseline, current Git commit when available, dirty-source flag and each packaged file's size and SHA-256. `SOURCE_IDENTITY.json` binds the unchanged baseline `harness/` and `prompts/` bytes for offline preflight. A source bundle can be tested through `PYTHONPATH=engine/src`; it does not require a wheel to import the new code.

## Prepare dependencies before disconnecting

Use Python 3.12 where possible. The engine supports Python >=3.10, but the native image environment requires >=3.11. The supplied engine lock was generated for Python 3.12 on Linux x86_64. Do not install a Windows dependency set on Linux or assume it matches a different Python ABI.

On an online machine, prepare a wheelhouse matching the target OS, architecture, Python version and ABI. For a Linux target, pip download on Windows must explicitly use that target's actual tags:

```bash
python -m pip download --only-binary=:all: --platform TARGET_PLATFORM --python-version TARGET_PYTHON --implementation cp --abi TARGET_ABI --dest wheelhouse -r engine/requirements-lock.txt
```

Replace all TARGET values before running. If a dependency has no compatible wheel, prepare that dependency on a matching online build environment. Transfer the resulting wheelhouse separately. The bundle builder does not invent or fetch GPU dependencies.

On the offline execution computer, install from local files only:

```bash
python -m pip install --no-index --find-links /srv/wheelhouse -r engine/requirements-lock.txt
export PYTHONPATH="$PWD/engine/src"
```

The core dependencies needed for fixture tests include Pillow, NumPy, Pydantic, jsonschema, referencing, Jinja2 and pytest. The full engine metadata also includes Streamlit for existing UI entrypoints. If a pure Python package wheel is included under `wheels/`, install it only after dependencies are present:

```bash
python -m pip install --no-index --no-deps --force-reinstall wheels/harness_ref_enhance-VERSION-py3-none-any.whl
```

Use the actual wheel filename. `--force-reinstall` avoids silently retaining an installed baseline wheel with the same package version. Installed wheel mode still needs the unpacked repository for `harness_source_root` and original prompts.

Native execution additionally requires target-compatible torch/torchvision with CUDA, the exact Diffusers source pinned in `engine/requirements-native-image.txt`, Transformers and the required local tool dependencies from the root requirements. Prepare these on the online side and transfer them. Do not run the `git+https` dependency line on the offline computer. Do not replace the pinned Diffusers implementation with a similarly named pipeline merely because it imports.

## Run the synthetic CPU smoke case

From the unpacked repository root:

```bash
export PYTHONPATH="$PWD/engine/src"
python -m hre candidates fixture --out /srv/runs/cpu-smoke
python -m hre candidates run --case-root /srv/runs/cpu-smoke/case
python -m hre candidates judge --case-root /srv/runs/cpu-smoke/case --variant J0
python -m hre candidates resume --case-root /srv/runs/cpu-smoke/case
python -m hre candidates report --case-root /srv/runs/cpu-smoke/case
python -m pytest engine/tests -q -k candidates
```

Use a new fixture directory. The fixture source is 65×49 and its strict x4 delivered images must be 260×196. A/B share C0, producing seven recorded image operations. Inspect `operations.json`, `artifacts.json`, `selection.json`, `report.md` and `contact_sheet.png`. Resume must not add completed model operations or replace frozen images. Fixture mode remains explicitly labeled and cannot satisfy research acceptance.

In PowerShell, replace the export command with `$env:PYTHONPATH="$PWD/engine/src"`. The fixture helper at `engine/examples/restoration_candidates_v1/make_fixture.py --out PATH` invokes the same public fixture implementation.

## Configure the real execution computer

Copy `engine/examples/restoration_candidates_v1/runtime.real.example.json` outside the source tree. Replace every deployment placeholder. Copy `task.example.json` and replace its image path and ROI annotations using LQ only. Do not reuse the example boxes for an unrelated image.

Keep `mode=real`, model ID `Qwen/Qwen-Image-2.1`, a real 40-hex checkpoint revision, exact installed Diffusers version, local weight path, deployment manifest and explicit editor settings. This workflow seals the Composer output directly and does not run a PE compiler.

All six stage entries use an OpenAI-compatible local `/v1/chat/completions` endpoint. They may point to the same deployed VLM, but the deployment must actually accept the required image count and JSON responses. Freeze actual provider image capacity in `review.max_images_per_call`. An image-capacity or required-coverage failure must return unresolved; never drop ROI images to make a request fit.

Set the credential only in the execution environment if the endpoint requires it:

```bash
export LOCAL_VLM_API_KEY='LOCAL_VALUE_NOT_STORED_IN_CONFIG'
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
python -m hre candidates preflight --config /srv/config/runtime.local.json
```

If the local server needs no authentication, remove `api_key_env` from each endpoint. The untouched example deliberately fails preflight. Preflight checks source identity, local weights, deployment manifest, packages, pipeline source and CUDA; it does not prove quality or canvas support.

## Run the first real GPU smoke case

First run a `restoration_x1` task in its own fresh case. Then run the example `sr_x4` task on an actual 257×193 LQ image. Keep its ROI boxes inside that image and annotate them before generation.

```bash
python -m hre candidates create --case-root /srv/runs/gpu-odd-x4 --spec /srv/config/task.odd-x4.json --config /srv/config/runtime.local.json
python -m hre candidates run --case-root /srv/runs/gpu-odd-x4
python -m hre candidates judge --case-root /srv/runs/gpu-odd-x4 --variant J0
python -m hre candidates report --case-root /srv/runs/gpu-odd-x4
```

For 257×193, x4 preparation pads the LQ to 264×200, requests a native 1056×800 canvas and crops to exactly 1028×772. Native geometry mismatch is a contract failure. Never insert a resize to make it pass. x1 uses a separate 32-grid preparation and returns exactly the original content dimensions.

Check that all alternatives use the same canonical and prepared LQ hashes, C0 is only a planning input, frozen prompts equal actual `condition.text`, seeds and effective editor settings match their manifests, and outputs retain native and delivered receipts. Judge qualification may legitimately return unresolved. A naturally looking face or legible character does not prove identity or text authenticity.

## Recover without repeating uncertain calls

```bash
python -m hre candidates resume --case-root /srv/runs/gpu-odd-x4
```

Completed operations replay their saved responses. Failed operations replay their saved failure. Unknown operations consume their reserved quota and require bound evidence. Do not delete `operations.json`, edit F0/F1, change seeds, or manually mark an operation completed.

Place reconciliation evidence below `case/reconciliation/` and prepare a resolution file with `schema_version=hre_candidates_v1`, `record_type=reconciliation`, operation ID, original request hash, decision, operator, reason and evidence refs. confirmed_completed also needs response_path and receipt_path. The receipt binds operation_id, request_sha256, response_sha256 and the execution manifest hash when applicable. confirmed_not_executed requires request-bound provider or worker nonexecution proof. still_unknown preserves the state and budget. A PNG alone proves neither execution completion nor cost.

```bash
python -m hre candidates reconcile --case-root /srv/runs/gpu-odd-x4 --operation-id ACTUAL_OPERATION_ID --resolution /srv/config/reconciliation.json
python -m hre candidates resume --case-root /srv/runs/gpu-odd-x4
```

## Keep experiments and GT separate

`experiment.e1_ab=true` enables the seven-image A/B comparison. Judge calls and costs for A and B are separately recorded. Both pools must use the same Judge variant when comparing system selection.

Run `preregister` from LQ metadata before creating any E1 case, and provide `experiment.e2_manifest_path` in that case's original runtime configuration. The manifest cannot be retrofitted after seeing C0. E2 requires two distinct evaluation seeds outside the E1 seed schedule and a separately frozen image budget. The E2 command uses frozen F1 prompts and never replans from its outputs.

```bash
python -m hre candidates preregister --dataset /srv/config/dataset.json --protocol docs/restoration_candidates_v1/examples/experiment_protocol.default.json --split pilot --out /srv/config/e2_manifest.json
python -m hre candidates e2 --case-root /srv/runs/gpu-odd-x4
python -m hre candidates evaluate-offline --case-root /srv/runs/gpu-odd-x4 --labels /srv/annotations/oracle.json --gt /srv/gt/truth.png
```

Only explicit offline commands read Oracle, GT or effect annotations. Labels bind exact candidate hashes and evaluation writes below `offline/`; it does not update online selection. Keep failed and unknown cases in their predeclared denominators. Optional J2 requires four independent role calls and aggregate; it is not a substitute for missing source evidence.

After independently labeling both pools, summarize all predeclared case directories, including missing or failed runs:

```bash
python -m hre candidates summarize-offline --cases /srv/runs/case01 /srv/runs/case02 --out /srv/reports/paired
python -m hre candidates effects-offline --registration /srv/config/e2_manifest.json --annotations /srv/annotations/effects.json --out /srv/reports/effects
```

Oracle JSON has `labels`, each with candidate_id, candidate_hash and boolean acceptable. An optional `best_sets` object holds independent `A` and `B` best-ID lists. `best_set` is the older B-only spelling. Missing labels remain missing; a recorded failed slot has no image to label and is a known non-acceptable result. E2 annotations use an `annotations` list with the exact hash-bound pair format documented at the top of `engine/src/hre/candidates/analysis.py`. Register evaluation_targets and case_root in each E2 case before E1. Do not select favorable targets or replace failed cases after generation.

Oracle acceptance also requires the candidate's actual Evidence hard gate to pass. An annotation cannot override a failed or missing hard gate. Both single-case and paired reports use this rule. Missing Evidence is unknown and must be reported, rather than assumed valid.

E2 registered evaluation assignments and actual interventions are distinct. Freeze `slot_axes` in each dataset case before preregistration for a nonstandard design, for example `{"CF":"person","CT":"person","CFT":null}` for two separate person alternatives. The fixed default is `{"CF":"person","CT":"text","CFT":"joint"}`. Registered targets determine denominators even if F1 later uses resampling, null or a different actual axis. A building, grass or other intervention remains an observed output and does not abort the report or automatically count as person/text improvement. A case without person/text targets has no applicable person/text comparison.

With A/B enabled, E1 uses up to seven image calls. An E2 case needs eight additional calls, so freeze `budgets.image_generation=15` before creating it. A four-image-only E1 case needs a total cap of 12 for E1 plus E2. The E2 command checks the complete budget before its first call. The runtime preserves slot/axis/strategy metadata and never compares different seed outputs as a same-seed effect.

For A-pool Judge reconciliation, pass `--pool A`; its evidence belongs under `case/pools/A/reconciliation/`. A confirmed resolution reopens the workflow for resume. Completed operations in either pool replay without a new provider call. True content uncertainty remains unresolved even after all external calls are accounted for.

Resume and report verify completed native/delivered files, anonymous Evidence images and saved E2 outputs. A changed or missing file returns `output_modified`; a case delivery path that differs from the reviewed selection returns `selection_binding_mismatch`. Preserve the existing operation and artifact records. Restore the exact recorded bytes from a trusted copy or investigate the corruption. Do not regenerate a completed slot to make the integrity check pass.
