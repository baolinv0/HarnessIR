# HarnessRefEnhance local engine

This isolated engine freezes editing base A and appearance reference B, validates manual task handoffs, and keeps generation budgets, evidence, candidate checks and selection on disk. B is nonaligned appearance guidance, never pixel ground truth. It does not call a model API or automate the ChatGPT desktop application.

From the repository root:

```bash
python -m pip install -r engine/requirements-lock.txt
python -m pip install --no-deps -e ./engine
hre --help
python -m hre --help
python -m streamlit run engine/src/hre/ui.py
```

The lock records the tested Python 3.12.14 Linux dependency closure, including test extras; regenerate it for another platform. The general dependency install remains `python -m pip install -e ./engine`.

If the installer reports a scripts directory outside PATH, use `python -m hre` or add that reported directory to PATH.

Set `HRE_DATA_ROOT` to choose the UI collection directory (default `Data/ref_enhance_cases`). The six UI regions show cases, separate A/B previews and comparability, current task and evidence, candidate history, audit history, and exports with independent capability labels. The UI shows actions derived from the persisted WAIT/PAUSED/terminal state; it uses the same Controller and import validator as the CLI.

`--case-root` always names **one frozen revision directory containing `state.json`**. `--data-root` names a collection searched read-only, including incompatible historical states. Existing revisions cannot be overwritten. Changing A/B, ROI, Prompt or policy requires a fresh revision and preserves the old one.

Create a revision from real files and explicit input policy:

```bash
hre case create --prediction A.png --reference B.png \
  --manifest source_manifest.json --config runtime_config.json \
  --case-root Data/ref_enhance_cases/my_case/rev1
hre case list --data-root Data/ref_enhance_cases
hre case show --case-root Data/ref_enhance_cases/my_case/rev1
hre case start --case-root Data/ref_enhance_cases/my_case/rev1
```

`source_manifest.json` may contain `case_id` and `case_revision` plus observed provenance. A minimal runtime configuration is:

```json
{
  "profile_id": "agent_adaptive",
  "max_generations": 3,
  "assume_srgb": true,
  "reference_usable": "usable",
  "reference_limitations": ["Operator confirmed comparable wall regions; moving people excluded."],
  "geometry_policy": {"mode": "strict"},
  "roi_manifest": [],
  "cache_root": "Data/ref_enhance_cache"
}
```

Only set `assume_srgb=true` for explicitly understood untagged SDR images. The default is false. `reference_usable` defaults to `unknown`; that case pauses until a new revision has a usable frozen annotation. CLI overrides are `--profile`, `--assume-srgb`, and `--reference-usable usable|unknown|unusable`. The UI requires confirmed comparability and written scope/limitations before allowing a usable annotation.

Export the pending task, manually send its images/text to the indicated role, and import the observed stage payload:

```bash
hre task export --case-root Data/ref_enhance_cases/my_case/rev1 --out exchange
hre response import --case-root Data/ref_enhance_cases/my_case/rev1 --payload diagnosis.json
hre response import --case-root Data/ref_enhance_cases/my_case/rev1 \
  --response response.json --done done.json
```

A stage payload is JSON for the current stage schema only. `TaskWriter` wraps it with current request identity and a hash-checked done marker, then `Controller.consume_done` validates it. Full envelopes use `--response` plus `--done`; an existing case-local marker may be passed with `--done` alone. Optional `--metadata` supplies truthful schema-compatible model observation, for example `transport=desktop_manual`, display name `unknown`, null exact version/seed and observed operator steps. No missing observation is invented.

An execution bundle has a separate `editor/` folder containing exactly frozen `A.png`, `B.png`, and `edit_prompt.txt`. Audit JSON and other stage inputs stay outside that folder. Candidate metadata must state `actual_generation_count` and `provider_order`; the formal image is the first complete output in provider order. If the observed count exceeds the frozen cap, downloaded raw C/extras and metadata are archived under immutable `external_observations/` before the ledger records failure; they are not promoted to formal candidates. Extra raw outputs must have explicit observed order and completion in `extras` records `{"source":"download.png","provider_order":1,"complete":true}` and must be counted. Bare paths are rejected. They remain audit artifacts, not extra ranked candidates; filenames, upload selection and directory order never establish provider order.

```bash
hre candidate import --case-root Data/ref_enhance_cases/my_case/rev1 \
  --task-id task_CURRENT --image downloaded_C.png --metadata candidate_metadata.json \
  --submission submitted
```

For example, a complete candidate at observed provider order 1 needs the earlier output explicitly recorded incomplete:

```json
{
  "actual_generation_count": 3,
  "provider_order": 1,
  "extras": [
    {"source": "partial_0.bin", "provider_order": 0, "complete": false},
    {"source": "extra_2.png", "provider_order": 2, "complete": true}
  ]
}
```

Use this only when those facts were actually observed. Unknown order/completion rejects intake; no default order is assigned. An auxiliary `hre_output_order_v1` manifest binds the declared order/completion to task/request/generation and actual raw file hashes, and Controller validates it with the response. Instead of metadata extras, the CLI accepts repeated paired `--extra PATH --extra-order INTEGER --extra-complete true|false`. Every extra path needs both explicit flags; CLI pairs the declarations without deriving provider positions. In the UI, upload multiple extra raw files and fill the order/completion JSON table with their exact filenames as `source`; only `source` is replaced by a controlled temporary path before validation. Other observed metadata remains unchanged.

`--submission submitted` records explicit observed submission before intake. `already_recorded` requires an existing submitted ledger entry and reconciles the later observed cumulative count. For either confirmed route, over-budget raw files are archived before any image decoding/canonicalization, then the full observed count records terminal failure even if downloads are undecodable. When no image has downloaded, `hre task unknown --case-root REVISION --task-id CURRENT` records the same uncertainty without requiring an image. `unknown` holds the reserved budget and pauses without guessing count or resubmitting. `not_submitted` releases the reservation only with explicit operator confirmation. Reconcile unknown status with `hre task submitted --case-root ... --task-id ... --count 1`, then resume; the task identity stays the same. A downloaded image does not by itself prove a submitted generation count.

```bash
hre case pause --case-root Data/ref_enhance_cases/my_case/rev1 --reason "operator break"
hre case resume --case-root Data/ref_enhance_cases/my_case/rev1
hre case retry-transport --case-root Data/ref_enhance_cases/my_case/rev1
hre watch --case-root Data/ref_enhance_cases/my_case/rev1 --max-polls 10 --interval 1
hre report --case-root Data/ref_enhance_cases/my_case/rev1
```

Watch is bounded, can be stopped with Ctrl-C, and consumes only original `tasks/*/submissions/*/pending/done.json` inbox markers and planned evidence without generating images. It excludes quarantine/export copies. Derived `watch_receipts.json` fingerprints actual marker/dependency bytes and relevant submission facts, so unchanged rejected transfers are not quarantined again on every poll; repaired dependencies or new submissions are revalidated. Transport retry is format/transport repair of the same task with a new attempt, subject to the frozen repair limit; it does not create a new generation. After a confirmed execution failure or confirmed never-submitted release, use `hre case resume --case-root REVISION --action retry_generation` or the UI's explicit **Retry generation (new task and reserved budget)** button. It creates a distinct task/generation reservation, subject to remaining budget; it is separate from transport repair and never retries unknown submissions. `COMPLETED` and `success=true` are separate. A final report binds the selected actual asset and hash; a fallback can deliver A with `success=false`.

Offline evidence handoff is actionable:

```bash
hre tools export-missing --case-root Data/ref_enhance_cases/my_case/rev1 --out offline_jobs
hre tools precompute --case-root Data/ref_enhance_cases/my_case/rev1 --out builtin_bundle
hre tools import-cache --bundle offline_bundle --cache-root Data/ref_enhance_cache
hre evidence collect --case-root Data/ref_enhance_cases/my_case/rev1
```

`tool_jobs.json` exports full frozen image/cache contracts and required model profiles for missing planned evidence. `tools precompute` exports a validated builtin bundle from the current plan (or `--plan plan.json` containing a `plan` list), without advancing state or running T1–T4. Builtin STATS/ROI can run on CPU; T1–T4 need real external offline workers/weights and hash-valid bundles. Missing required evidence is shown as missing and waits; it is never filled with fake detections. `evidence import` is an alias for cache registration. Cache originals are not modified.

```bash
hre capabilities probe --case-root Data/ref_enhance_cases/my_case/rev1
hre capabilities probe --case-root Data/ref_enhance_cases/my_case/rev1 \
  --name two_image_edit --evidence actual_probe.json
hre run freeze --manifest real_dataset_manifest.json \
  --profile docs/reference_enhancement/v1_20261013/config/experiment_profiles.json --out runs/my_run
hre evaluation export --run runs/my_run --out review/my_blind_package
hre evaluation analyze --run runs/my_run --ratings frozen_independent_ratings.json
```

Each desktop capability remains independently `untested` until actual supporting evidence is imported. A local filesystem probe proves only controller I/O. Formal run freeze requires real provenance, group/split audits and enrolled inputs; design examples are rejected. An explicitly unverified pilot must declare `manifest_kind=pilot` and `allow_unverified=true` and cannot be formal/test. Blind reviewer exports exclude Prompt/method/Verifier data; mapping is private outside the reviewer package. Analysis retains planned failures and uses paired scene groups.

The self-contained synthetic protocol demonstration is:

```bash
python engine/examples/demo.py --out /fresh/path/synthetic_demo
python -m pytest engine/tests -q
```

It creates deterministic color patches, labels every response synthetic, calls no model, and exercises DirectRef, AgentSingle and an adaptive refine/retry path. It is not real R1, a desktop capability probe, a 12-pair pilot, or evidence that enhancement works. Those require real A/B, actual generated C, external tool artifacts and independent ratings. See `docs/reference_enhancement/IMPLEMENTATION_RUNBOOK.md` for handoff and recovery details, and [Experiment file handoff](../docs/reference_enhancement/EXPERIMENT_HANDOFF.md) for dataset, outcome/contract and blinded evaluation file formats.
