# Experiment file handoff

These commands use real local files and never call an image model. Freezing
creates a plan; generation and independent ratings remain separate operations.
All paths in a dataset case are relative to its `case_root`, which is relative
to the manifest's directory. All outcome/contract paths are relative to the
frozen run. The small JSON examples below show field shapes; full asset records
come from validated files, not manually invented hashes.

## Prepare and freeze a pilot

Install and prepare one actual A/B pair:

```bash
python -m pip install -e ./engine
python - <<'PY'
from pathlib import Path
from hre.storage import write_json
write_json(Path('case_identity.json'), {'case_id': 'capture_001', 'case_revision': 0})
PY
hre case create --prediction originals/prediction.png --reference originals/reference.png --manifest case_identity.json --case-root prepared/capture_001 --profile direct_ref --reference-usable usable
```

Use `usable` only after a real pre-output comparability annotation. Otherwise
retain `unknown`; the Controller will pause. Untagged images require an explicit
frozen color assumption or explained sRGB conversion. A and B may have different
dimensions. They are independent images; B is never pixel ground truth.

The run manifest envelope and case metadata have this shape:

```json
{
  "schema_version": "ref_enhance_v1",
  "manifest_kind": "pilot",
  "allow_unverified": true,
  "reference_is_pixel_ground_truth": false,
  "run_linkage": {"selected_profile_ids": ["baseline", "direct_ref", "agent_single"]},
  "cases": [{
    "case_id": "capture_001",
    "case_revision": 0,
    "scene_group_id": "capture_group_001",
    "case_root": "prepared/capture_001",
    "split": "validation",
    "comparability": {"reference_usable": "usable"},
    "content_preservation_annotations": {
      "status": "not_observed", "source_anchor": "prediction",
      "protected_face_regions": [], "protected_text_regions": [],
      "protected_geometry_landmarks": [], "protected_object_regions": [],
      "critical_content_rules_version": "content_preservation_v1",
      "notes": "Annotate protected A content before enrollment; do not invent observations."
    }
  }]
}
```

Structured protection annotations retain their `status`, A `source_anchor`
(`prediction`), rule version, notes and all four protected-region arrays.
Use `status: observed` only for actual pre-output annotations. Face, text and
object regions have `{region_id, coordinate_system: "canonical_norm", bbox:
[x0,y0,x1,y1], instruction}`; geometry landmarks have `{landmark_id,
coordinate_system: "canonical_norm", point: [x,y], instruction}`. All coordinates
refer to the canonical prediction A, with normalized half-open boxes and
independent B coordinates. Optional region `text`, `identity` and `notes` are
retained. For example, an actually observed text region could be:

```json
{"region_id":"sign_01","coordinate_system":"canonical_norm",
 "bbox":[0.1,0.2,0.4,0.3],"instruction":"Preserve exact existing text.",
 "text":"OPEN","notes":"A sign; do not copy B text."}
```

These are field-shape examples, not observations. Missing annotations normalize
to `[]`; supported lists contain nonempty instruction strings or validated
composition protection records. Invalid objects, region records, coordinates or
list elements reject admission before a generation can be submitted. Verify
receives the lossless object as `protected_content.annotations`, alongside
`protected_content.rubric`; list form retains the existing rubric-plus-list
context. No region is discarded or converted to an opaque string.

The required `cases[].assets` field is an array containing the complete
prediction/reference asset dictionaries: `asset_id,path,sha256,role,width,height,
color_space,pixel_sha256,source_file,canonicalization`. Populate it from the real
case and preserve actual case identity with this executable assembly step:

```bash
python - <<'PY'
from pathlib import Path
from hre.storage import CaseStore, read_json, write_json
root = Path('prepared/capture_001')
state = CaseStore(root).load()
config = read_json(root / 'config.json')
case = {
    'case_id': state['case_id'], 'case_revision': state['case_revision'],
    'scene_group_id': 'capture_group_001', 'case_root': root.as_posix(),
    'split': 'validation', 'assets': state['inputs'],
    'comparability': {'reference_usable': config['reference_usable']},
    'content_preservation_annotations': config['protected_content']
}
write_json(Path('run_manifest.json'), {
    'schema_version': 'ref_enhance_v1', 'manifest_kind': 'pilot',
    'allow_unverified': True, 'reference_is_pixel_ground_truth': False,
    'run_linkage': {'selected_profile_ids': ['baseline', 'direct_ref', 'agent_single']},
    'cases': [case]
})
PY
hre run freeze --manifest run_manifest.json --profile docs/reference_enhancement/v1_20261013/config/experiment_profiles.json --out runs/pilot_001
```

An unverified pilot cannot contain test cases or support formal claims. For a
formal manifest remove the pilot override and provide the full approved source,
RAW, baseline checkpoint/command/environment, color, comparability, enrollment,
near-duplicate and leakage records described in
[the experiment protocol](v1_20261013/04_EXPERIMENTS.md). Source originals must
physically match A/B asset source files. The upstream RAW identity is separate
from the RGB prediction source. Every derivative of a RAW/capture group inherits
one split; changing a scene-group name cannot bypass observable RAW identity.

## Run planned Controller outcomes

Freezing writes `planned_outcomes.json` with schema `hre_outcomes_v1`:

```json
{
  "schema_version": "hre_outcomes_v1",
  "outcomes": [{
    "case_id": "capture_001", "case_revision": 0,
    "scene_group_id": "capture_group_001", "split": "validation",
    "arm_id": "direct_ref", "execution_order": 1, "status": "planned",
    "case_root": "records/capture_001/direct_ref",
    "input_case_root": "frozen_inputs/capture_001",
    "selected_asset": null, "selected_asset_root": null,
    "workflow_success": false
  }]
}
```

Keep every planned case/arm identity, including failures. The actual record and
input roots derive from frozen case/arm identity; mutable routing hints cannot
replace anchors. `execution_order` is generated by the freezer. Use its actual
case id rather than the illustrative id above. The copied per-case runtime
config contains the frozen ROI, restrictions, protected content and arm cap.

The run also freezes all six template SHA256 identities in
`runtime_configs/.../prompt_template_sha256`. At case initialization the actual
installed template bytes are copied into case `prompts/<stage>.j2`; the actual
six-stage SHA map enters the immutable case config and `config_sha256`.
`prompts/manifest.json` records stage/path/SHA identities; `freeze.json` hashes
that manifest and every source. Controller and task export render exclusively
from these case files. Each `dispatch.json` and committed `next_task` records
`template_source_proof` (stage/path/SHA), rendered `prompt_sha256` and the journal
additionally binds `dispatch_sha256`. Direct executions include both
`direct_ref` and `execute` source identities and hash-bound direct artifact
`manifest.json` plus exact rendered `prompt.txt`. Diagnose/Compose/Verify/Refine
carry their own source identities in the same journal contract.

Case initialization with an edited installed package records the actual changed
source map; export marks its mismatch against the run freeze as an ITT protocol
violation and preserves its actual costs. Installed-package changes after
initialization or completion cannot change case rendering or retroactively
invalidate matching historical proof. Do not overwrite frozen case templates.
Historical proof-free records remain unverified; no hashes are backfilled.

Initialize a planned record from its real copied assets:

```bash
python - <<'PY'
from pathlib import Path
from hre.assets import create_case
from hre.storage import read_json
run = Path('runs/pilot_001')
case = read_json(run / 'manifest.json')['cases'][0]
arm = 'direct_ref'
inputs = {a['role']: a for a in case['assets']}
source = run / 'frozen_inputs' / case['case_id']
create_case(source / inputs['prediction']['path'],
            source / inputs['reference']['path'], case,
            read_json(run / 'runtime_configs' / case['case_id'] / (arm + '.json')),
            run / 'records' / case['case_id'] / arm)
PY
hre case start --case-root runs/pilot_001/records/capture_001/direct_ref
hre task export --case-root runs/pilot_001/records/capture_001/direct_ref --out exchange/direct_ref
```

Replace the illustrative final two paths with the actual generated case id.
Continue with the [implementation runbook](IMPLEMENTATION_RUNBOOK.md) for
submission confirmation, candidate import, response import and recovery.
Controller states are consumed automatically during blind export; manually
rewriting their status, costs or selection is unnecessary. Actual executed
configuration and annotations must match the frozen run. Drift remains an ITT
`protocol_violation`, with its delivered files and observed costs retained.

## External candidate outcomes and execution contracts

For a separate file-based executor, update only its existing planned outcome.
`status` may be `planned/completed/failed/cancelled`. For a completed candidate,
`selected_asset` is the full validated candidate asset dictionary and
`selected_asset_root` contains that candidate's canonical and original files.
It must bind the exact case revision and frozen prediction/reference SHAs and
deliver A's dimensions. B cannot serve as C. A fallback is the exact registered
prediction asset and cannot be an improved output.

The external executor must save the effective configuration actually used,
including Controller-normalized geometry target dimensions, schema/canonicalizer,
stats metric and `config_sha256`. Save this execution-time record; do not invent
a matching configuration after observing output. The additional outcome field
has this shape:

```json
{
  "execution_contract": {
    "path": "external_records/capture_001/direct_ref/config.json",
    "sha256": "96e852194c90a2c7cfba2e41ff6f35a456e4f62eb4b866975598ab16d7d37f18",
    "execution_record_root": "external_records/capture_001/direct_ref",
    "selected_asset_id": "candidate_001",
    "selected_asset_sha256": "70c49278766b88fe7d9ce90a229479a544ef3f985c02c353b43dc0d52437ad91d"
  }
}
```

Those SHA strings illustrate the exact 64-character format; compute the actual
values from the executed config and selected file using `hre.models.file_sha256`.
`execution_contract.sha256` hashes file bytes; `config_sha256` inside the config
uses canonical JSON with its own top-level hash field excluded. Full config
equality and selected id/SHA are checked against the frozen arm and real asset.
`execution_record_root` must retain the actual Controller-compatible case
freeze, requests, exact rendered prompts, dispatch proofs and transaction journal
produced during execution. Its terminal status, case/revision, arm, A/B hashes,
config file identity and actual selected asset must bind this planned outcome.
The six frozen template identities and every issued role source are compared to
the run contract. Manual desktop imports through Controller already produce
this record. An external configuration alone cannot prove which templates ran;
it stays unverified with joint success zero. Authentic supplied journals retain
observed generation costs. Never fabricate an execution journal after output or
silently attach present-day package hashes to a historical candidate.

A missing file, bad contract SHA, unreadable contract JSON, absent contract or
policy mismatch marks that outcome `protocol_violation`; it stays in ITT with
joint success zero while other outcomes export normally. Unknown external costs
remain null. Corruption of the global frozen manifest, runtime, prompts,
provenance or input assets aborts export and requires repair/new revision.
Unsafe image/source records are never substituted into the reviewer package.

## Independent blind ratings

```bash
hre evaluation export --run runs/pilot_001 --out review/pilot_001
```

Give reviewers only `review/pilot_001`. Private method mapping stays under
`runs/pilot_001/private`; never send the run root. A/B roles stay explicit;
candidate codes and panel order are generated by the exporter. Copy codes and
the exact exported manifest SHA into ratings:

```json
{
  "frozen": true,
  "blind_manifest_sha256": "1a65bacdfe998aa47ba8e75716c2bd2603cff4fac0cfc8ba5951e7dba7b008620",
  "raters": [
    {"rater_id": "r1", "independent": true, "participated_cases": []},
    {"rater_id": "r2", "independent": true, "participated_cases": []},
    {"rater_id": "r3", "independent": true, "participated_cases": []}
  ],
  "ratings": [
    {"code": "item_2f1d75a3a6c88490193dfbeb", "rater_id": "r1",
     "comparability": "usable", "style_direction": "improved",
     "content_preservation": "pass", "critical_defects": []},
    {"code": "item_2f1d75a3a6c88490193dfbeb", "rater_id": "r2",
     "comparability": "unusable", "style_direction": "improved",
     "content_preservation": "pass", "critical_defects": []}
  ],
  "adjudications": [
    {"code": "item_2f1d75a3a6c88490193dfbeb", "rater_id": "r3",
     "comparability": "uncertain", "style_direction": "uncertain",
     "content_preservation": "pass", "critical_defects": []}
  ]
}
```

Use actual exporter codes/SHA and actual observations, not these illustrative
labels. Every rating/adjudication requires explicit comparability:
`usable/partial/unusable/uncertain`. Style labels are
`improved/unchanged/worse/uncertain/abstain/error`; content labels are
`pass/fail/uncertain/abstain/error`. Critical defects are a list; no defects is
`[]`. A rater who wrote prompts or selected this case's output is not independent
and must not rate it. Declare any participated case ids accurately.

Two independent raters must agree on comparability, style, content and presence
of critical defects. Disagreement needs an explicit third independent rater's
adjudication; otherwise it remains unresolved and zero joint success. Missing,
unusable or uncertain comparability cannot default to usable. Failure, missing
ratings, abstention, uncertainty and protocol violations stay in ITT. A-equal
delivery and baseline have joint success zero even with positive ratings.

After labels are final, freeze and analyze:

```bash
hre evaluation analyze --run runs/pilot_001 --ratings review/ratings.json
```

Analysis writes `analysis/summary.json`, privately freezes the exact ratings,
and uses scene-group paired estimates with 10,000 seeded cluster bootstrap
replicates. Labels cannot be replaced after unblinding in the same run. Changed
protocols, new labels or a second blind export require a new run revision.
