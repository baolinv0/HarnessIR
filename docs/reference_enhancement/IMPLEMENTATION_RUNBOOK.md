# HarnessRefEnhance implementation runbook

The executable engine is `engine/src/hre/`, separate from the restoration `harness/`. Start from the repository root with `python -m pip install -e ./engine`; both `hre` and `python -m hre` call the same entry point. Launch the interface with `python -m streamlit run engine/src/hre/ui.py`. The exact commands, metadata fields and input configuration are in `engine/README.md`. Reproduce the tested Python 3.12.14 Linux runtime with `python -m pip install -r engine/requirements-lock.txt`, then `python -m pip install --no-deps -e ./engine`; regenerate the platform-specific lock for another platform. Dataset/outcome execution contracts and evaluation handoff formats are documented in [Experiment file handoff](EXPERIMENT_HANDOFF.md).

## Paths and preservation

A case revision is one immutable input/config namespace with `state.json`, `config.json`, `manifest.json`, role-bound images, tasks, responses, audit transactions and reports. Pass that directory as `--case-root`. A parent holding many cases/revisions is a collection passed only as `--data-root` for discovery or `HRE_DATA_ROOT` for the UI. Existing revision destinations are rejected. Legacy schema files remain visible in the list and untouched; they are not loaded as new controller states. Create a fresh revision for any changed reference, ROI, Prompt, geometry or tool profile.

The UI separates six regions: case list/new revision, A/B canonical previews and comparability, pending task/evidence, candidate comparison and selection, budget/audit history, and exports/capability evidence. PAUSED retains its suspended stage; terminal states retain complete history and exports.

## Manual stage chain

1. Import real A and B with truthful source provenance. Untagged SDR requires explicit sRGB assumption; unsupported HDR/ICC needs a controlled SDR export. Annotate usable reference only after checking comparable regions and describing limitations. B remains appearance guidance, never source content or aligned ground truth.
2. Start the exact revision. Agent profiles issue Diagnose; DirectRef issues Execute. Export the current task bundle. Analysis roles receive indicated real images and strict JSON schema. Execute receives only `editor/A.png`, `editor/B.png`, `editor/edit_prompt.txt`.
3. Import current stage JSON with `hre response import --case-root REVISION --payload FILE`. Full response/done pairs use `--response FILE --done FILE`. Both pass the same strict TaskWriter/Controller protocol; malformed JSON, wrong identity, stale revision or mismatched hashes are rejected. UI pasted JSON and uploaded JSON take this identical path.
4. For WAIT_EVIDENCE, export missing jobs with `hre tools export-missing --case-root REVISION --out JOBS`. This packages frozen images, binding/cache contracts and requirements. Produce required external T1–T4 evidence in an existing worker environment, or precompute CPU STATS/ROI. Register a validated directory bundle with `hre tools import-cache --bundle BUNDLE --cache-root CACHE`; retry evidence collection. No fake detector output is supplied and only planned evidence is consumed.
5. After a real external edit, state the observed submission count and provider order in candidate metadata. Import raw C with `hre candidate import --case-root REVISION --task-id CURRENT --image C --metadata METADATA --submission submitted`. Use `already_recorded` if submission was explicitly recorded before download. Preserve extra raw outputs and observed total count in metadata. Verify evaluates C versus B for appearance and C versus A for content; dimensions alone do not establish preservation.
6. Import Verify, then Refine if requested. Refinement uses original frozen A+B again. The selector chooses earliest accepted, else earliest usable for review, else baseline A. Report success, selected hash/round and terminal reason together; stopping is not automatic success.

## Observed output order and extra raw files

The formal image must be the first complete provider output, not the operator's preferred image. Metadata extras are structured records with explicit `source`, integer `provider_order`, and boolean `complete`. Bare paths and unknown order/completion are rejected. Provider order must be less than `actual_generation_count`, unique across outputs, and every earlier order before the formal image must be explicitly recorded incomplete. The auxiliary typed order manifest binds those declarations to real raw hashes and the current task; completion is an operator observation, not inferred from upload order or filenames.

Example for a formal complete image observed at order 1:

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

CLI declarations can instead use `--extra partial_0.bin --extra-order 0 --extra-complete false --extra extra_2.png --extra-order 2 --extra-complete true` with the observed count/formal order in metadata. The UI supports multiple extra uploads and a JSON table using each exact uploaded filename in `source`; it binds filenames to controlled temporary paths while keeping explicit order/completion unchanged. Do not invent an order when it was not observed: retain raw downloads externally and reconcile the observation before candidate intake.

## Pause, unknown submission and recovery

Pause and cancel have distinct audit effects. A paused response remains available for resume; cancel retains evidence without reopening the case. `case recover` loads committed transactions and validates file integrity. `watch --max-polls N --interval SECONDS` consumes complete markers and planned evidence in bounded polls and stops with Ctrl-C. It never submits a model generation. Discovery is limited to original task submission inboxes; quarantine and exports are excluded. A derived marker/dependency fingerprint cache suppresses unchanged repeated rejections while repaired bytes and new submissions trigger revalidation.

For unknown external submission use candidate import `--submission unknown`. Budget remains reserved, ledger records uncertainty, and the revision pauses. Reconcile actual submission using `task submitted --task-id CURRENT --count OBSERVED`; resume keeps the same pending identity. If the task was definitely never sent, use `task release-unsubmitted`; no later candidate can be silently assigned to that released generation. Unknown results do not cause automatic new generations. The UI exposes these explicit reconciliation controls while paused.

`case retry-transport` repairs the same task transport/JSON attempt under the frozen format-repair limit. It is not an instruction to generate again. Resume actions such as `retry_analysis` create fresh analysis identity when an accepted analysis was unusable; they cannot change frozen input policy. For a paused execution with no pending task after confirmed failure or confirmed never-submitted release, explicitly request `case resume --action retry_generation` or click **Retry generation (new task and reserved budget)**. Controller creates a distinct generation identity/reservation and enforces remaining budget; consumed count changes only with actual observed submission. This option is unavailable for unknown outcomes. Known oversampling on either submitted or already-recorded intake first archives downloaded raw C/extras and bound metadata as immutable external observations, then records cumulative actual count and terminal failure without decoding/canonicalizing or promoting a formal candidate, including malformed downloaded files. Later observed cumulative counts are reconciled even when an earlier submission count was already recorded. Budget exhaustion and failures keep raw artifacts and an explicit non-success outcome.

## Capability and experiment handoff

`capabilities probe` records local controller read/write separately from the four desktop capabilities. The four statuses are independent: `local_file_io`, `role_dispatch`, `two_image_edit`, `image_save`. No actual Windows/ChatGPT automation or real edit was available for implementation verification; unobserved desktop capability remains `untested`. A capability evidence file must record actual supported actions, application/model display information and verifiable artifacts. Unknown versions/seeds remain null/unknown.

Freeze an experiment with `run freeze`; formal enrollment validates real asset/source provenance, reference policy and group/split leakage audits. A genuine unverified pilot may opt into `allow_unverified=true` with `manifest_kind=pilot`; design fixtures remain rejected. Each planned arm/outcome stays in the intention-to-treat denominator even if generation or delivery fails. `evaluation export` creates the reviewer image package and keeps mapping outside it. Freeze independent ratings before `evaluation analyze`; scores from workflow Verify are not final independent ratings.

A headless HTTP server launch was blocked by automatic approval review because Streamlit's startup attempted its default external IP lookup. No service launch is claimed verified; actual Streamlit rendering and interaction were verified through AppTest.

Implementation verification uses deterministic synthetic patches only. `python engine/examples/demo.py --out EMPTY_DESTINATION` writes `SYNTHETIC_DEMO.json`, real patch bytes/hashes, stage envelopes/done, three completed synthetic cases, one two-generation refine path and reports. All observation payloads clearly identify synthetic construction and no model inference. This verifies protocol plumbing, not real R1 or image quality. Real R1, the 12-pair pilot, external OCR/face/depth/segmentation inference, real generation cost and independent evaluation remain `not_run` until the corresponding actual inputs are supplied and executed.

## Verification

Run `python -m pytest engine/tests -q` after editable install (or prefix with `PYTHONPATH=engine/src`). Frontend tests invoke the CLI in subprocesses, assert persisted assets/state/budget and strict rejected input, preserve unknown historical schema bytes, exercise bounded done-marker intake, and run Streamlit AppTest against a real revision with pause/resume. Integration tests execute the full explicitly synthetic DirectRef/AgentSingle/adaptive retry pipelines. [Implementation verification](IMPLEMENTATION_STATUS.md) records the final suite result, packaging checks and unresolved real-world work separately.
