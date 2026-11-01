# S2: real evidence transport, A/B measurement and postdiagnosis targets

**Code/protocol stage only. No actual ChatGPT call is made.** The real-evidence
gate requires verified current A/Base and B/sRGB, genuinely produced tool assets,
an actual ChatGPT visual judgment plus receipts, and independent review. Local
synthetic test records cannot satisfy that gate. Old A01 assets are not substituted.

## Lifecycle and commands

New records use `reference_style_s2_v4` (S2 r2). Create a **new** sample with the existing
`run` command; no S0/S1 or S2 r1 record is mutated or silently migrated. The v4 reader
rejects earlier envelope versions; v3 evidence must be reimported into a new sample,
not relabeled in place. Initial v1 mapping shape is unchanged. All commands are under
`PYTHONPATH=src python -m hre reference-style` from `source/engine`:

1. `evidence-import --root CASE --manifest EVIDENCE.json [--asset ACTUAL_FILE]`
2. `supports-freeze --root CASE --spec SUPPORTS.json`
3. `measure-ab --root CASE --snapshot-id s1`
4. `ab-export --root CASE --report-id ab_report_UUID`
5. Actual current-chat visual processing occurs outside this code. Import with
   existing `import --root CASE --receipt RECEIPT.json --output ACTUAL_DIAGNOSIS`.
6. `targets-freeze --root CASE --spec TARGET_MAPPING.json`
7. `targets-compile --root CASE --version v1`

Step 4 binds the A/B images, immutable evidence snapshot and numeric report. Its
receipt has `target_version: null` and `target_hash: null`: **targets do not exist
yet**. The request hash binds evidence/report identities. Step 6 requires the
actual imported AB response tied to that exact report and snapshot, then freezes
the target version. A later report cannot borrow the earlier diagnosis even if
its values happen to be identical. Raw narrative is archived, never executed.

`targets-compile` emits `execution_status=draft_not_dispatched`, prompt/hash,
original A/B roles and derivative identities, concrete regional controls,
coordinates and evidence references. It does not allocate a generation attempt,
generate/import C, evaluate quality, apply AcceptancePolicy or certify a label.
The older generic `export` route remains compatibility scaffolding; **use ab-export
for S2's evidence-before-target lifecycle**, not a generic target-bound AB request.

## Evidence manifest and parser

```json
{
  "evidence_id":"e1", "role":"A", "kind":"segmentation", "status":"available",
  "input_file_hash":"ACTUAL_A_SOURCE_SHA256", "input_pixel_hash":"ACTUAL_A_PIXEL_SHA256",
  "source":{"tool":"ACTUAL_TOOL_NAME", "version":"ACTUAL_VERSION_OR_NULL", "origin":"actual_tool"},
  "asset_sha256":"ACTUAL_ASSET_SHA256", "coordinate_frame":"oriented_input_grid",
  "asset_size":[WIDTH,HEIGHT], "transform":{"method":"identity","target_size":[WIDTH,HEIGHT]},
  "value_semantics":"binary_support", "missing_reason":null
}
```

This is a template, not usable evidence. Source hashes come from the immutable
input audit, not an arbitrary same-size image. A/B roles are unique and C is not
admitted. `source.origin` is actual_tool, manual_annotation or synthetic_fixture;
synthetic origin is rejected for purpose reference_style. Tool/version strings
are archival metadata, not executable prompt fields. Provenance is caller-attested,
not remote-authenticated; code cannot prove a declared tool actually ran.

- Segmentation: one actual binary 2D NPY support per whole region, bool or 0/1.
- Depth: actual numeric 2D NPY; finite observations required; semantics
  near_is_small or near_is_large. Missing cells are retained, not fabricated.
- OCR: JSON `{"entries":[{"text":"scene text","bbox":[x,y,w,h],"confidence":0.9}]}`.
- Face: JSON `{"entries":[{"bbox":[x,y,w,h],"confidence":0.9}]}`.
- Every NPY uses `np.load(..., allow_pickle=False)`; object arrays/NPZ, malformed
  JSON, duplicate keys, invalid bounds/confidence and false hashes reject.
- Arrays/bboxes live on the declared oriented input grid. The only supported
  mapping is identity or explicit nearest_grid scaling to the audited oriented
  image. Native/unrotated, crop/affine and guessed coordinate mappings reject.
  Both original evidence bytes and normalized array bytes/hashes are retained.
- Available always requires a readable matching asset. Unavailable has no asset;
  uncertain may carry one. Explicit reason: not_installed, not_collected,
  coverage_insufficient or uncertain_correspondence. No missing tool blocks the
  entire credible visual preparation path.

## Frozen whole-region support specification

```json
{
  "snapshot_id":"s1", "evidence_ids":["e1","e2"], "global_comparability":"unknown",
  "regions":[{
    "region_id":"r1", "semantic_class":"face",
    "A":{"evidence_id":"e1","entry_index":null},
    "B":{"evidence_id":"e2","entry_index":null},
    "match_status":"confirmed", "composition":"comparable", "illumination":"comparable",
    "parent_id":null, "usage":"independent"
  }], "relations":[], "trusted_ocr":[]
}
```

A/B evidence references must have their own source image role/hash. A B mask is
never copied into A. Region classes include complete face and exposed_skin and the
existing whole-object/material vocabulary; intra-face tonal/part units reject.
Use an actual OCR/face entry_index for a bounding-box support. Bounding boxes
remain visual-only because they can mix materials; they are not silently treated
as precise segmentation. A side can be null when support is genuinely missing.

Correspondence/composition/illumination are **explicit frozen operator assessments**,
not an automatically proven instance match. Match: confirmed/uncertain/unmatched;
composition: comparable/mixed/unknown; illumination: comparable/confounded/unknown.
Numeric eligibility requires both nonempty available segmentation supports, known
encodings and comparable frozen assessments. Mixed, uncertain or bbox supports
are visual_direction_only; empty/missing/unmatched supports retain
insufficient_evidence. Actual coverage denominators, fractions, bboxes and support
hashes are frozen. No minimum coverage threshold is invented.

Nested parents must be summary_only; child masks must be subsets. Overlap without
declared ancestry rejects. Summary parents cannot become duplicate numeric
objectives; no area-weighted regional total or double-counted aggregate exists.

Relations are explicit `{relation_id:"l1", left:"r1", right:"r2", metric:"linear_Y",
statistic:"q50"}`. Both endpoint IDs must exist and differ. `trusted_ocr` is an
explicit list of `{evidence_id, entry_index}` selecting actual available **A** OCR
entries. No confidence threshold is invented. Raw text is retained as data;
prompts contain only entry ID, bbox, confidence and text hash, plus fixed protection
instructions. Linked OCR assets are scene text, never executable instructions.

Every support reference is validated **before** checking whether an asset exists:
segmentation requires `entry_index: null`; face/OCR accept a null or integer index
0–999999 when unavailable/assetless uncertain. With parsed bbox evidence, an actual
in-range integer entry is required. Booleans/floats/prose/containers reject, and depth
is never a segmentation/bbox support. Null/missing supports remain insufficient,
not an obstacle to preparing credible global or visual-only AB judgment.

The final diagnostic view has a closed recursive schema: only finite numbers,
fixed enums, bounded indices, typed IDs/hashes and generated attachment paths enter
public reports/requests. Unknown nested fields reject. It is checked when a report
is produced, again on AB export, when targets freeze, and on compilation. Source
tool/version prose, original OCR strings and imported narrative remain archival,
not an alternate instruction channel. This is a typed projection, not a keyword
claim of semantic safety or evidence authenticity.

## Actual numerical observations

`measure_ab` reads the audited full-precision analysis.npz, not RGB8 derivatives.
It calculates global and whole-region linear_Y, L_star, a_star, b_star and chroma
distributions: q05/q25/q50/q75/q95, span95_05 and mean. Every row has A, B and signed
delta_B_minus_A, statistic, metric, region/relationship identity, frozen support
snapshot hash and eligibility. Invalid/empty support produces null, not zero or
invented achievement. Known B remains measurable when A encoding is unknown.
Endpoints are not removed; source endpoint/gamut statistics accompany the report.
There is no unaligned A/B pixelwise-error calculation.

Relationships keep A(left−right), B(left−right), all endpoint operands and the signed
change. Negative values are valid. Actual depth values influence within-image
ordering only; no A/B depth-scale subtraction and no near-means-brighter rule.
Available masks/face boxes/OCR entries have parsed numeric summaries in the public
report, not merely attached filenames. Evidence hashes and actual source assets
remain linked and immutable.

## Explicit diagnosis-to-control mapping

```json
{
  "version":"v1", "report_id":"ab_report_ACTUAL_UUID", "diagnosis_record_id":"response_ACTUAL_UUID",
  "targets":[{"target_id":"t1", "measurement_id":"m36", "visual_region_id":null,
    "visual_dimension":null, "visual_direction":null, "judge_type":"mixed", "priority":"critical"}]
}
```

IDs must come from actual report/response records. Numeric/mixed mappings select
an eligible measurement; they cannot override its operands, values, statistic or
direction. Positive delta yields increase_toward_B, negative delta yields
decrease_toward_B, zero yields match_B. Relationship operands remain signed. Two
regions can therefore compile opposite concrete adjustments in one frame.
No calibrated tolerance is guessed: frozen tolerance is null and the compiler
explicitly labels numerical values as observed reference directions, not an
acceptance range or proof of achievement.

A visual-only mapping uses measurement_id null, a declared visual_region_id
(including global g0), typed visual_dimension and visual_direction from the existing
vocabulary, judge_type visual and priority. It retains the support eligibility,
including insufficiency. The mapping is an explicit operator action informed by
the imported diagnosis, not automatic interpretation of arbitrary narrative.
Policy, acceptance history, source-tool prose and raw VLM/OCR strings are not copied
into concrete editing instructions. Preservation is fixed in every prompt.

## Explicit target revisions (v4)

The first S2 definition must be **v1**, with the four fields above and no revision
object. S2 cannot silently combine an older generic-export target lineage with its
own target chain. Additional versions must be sequential and add:

```json
"revision": {
  "predecessor_version":"v1",
  "predecessor_hash":"ACTUAL_FROZEN_V1_CONTENT_HASH",
  "reason_code":"mapping_correction",
  "rationale":"Optional archival explanation, or null; never an edit instruction."
}
```

This belongs beside `version`, `report_id`, `diagnosis_record_id`, `targets`; for
this example `version` is v2. The predecessor must be the **immediate latest** S2
version with the exact content hash. Gaps, branches, missing audit and wrong/stale
predecessors reject before writing. Allowed reasons: mapping_correction,
priority_reassessment, evidence_update, diagnosis_reassessment. A changed report
requires evidence_update **and its own bound imported diagnosis**; a new diagnosis
for the same report requires diagnosis_reassessment. These reasons are explicit
operator attestations, not proof that a revision is justified or improves style.

Every frozen target record carries `revision_contract: linked_target_revisions_v1`.
Its computed `revision` binds the predecessor version/hash/record ID, typed reason,
optional rationale (null or nonempty text, at most 10000 characters), and `changes`:
retained/added/changed/removed lists with target_id and full typed before/after
records (null for absent sides). IDs determine correspondence; IDs are not silently
renumbered. Initial v1 records all targets as added with reason initial_definition.
Previous target bytes never change. Rebinding the source measurement/diagnosis is
visible in the before/after record, even when the nominal style direction is equal.

Revision audit/rationale is **never included** in public diagnosis context, compiled
instructions or a later AB prompt. Only the new frozen record hash binds that audit
to the draft. Tolerant acceptance prose may be archived but is not a control; the
private AcceptancePolicy is still never read by any execution path.

## Gates / limits

Code tests use genuine local synthetic parsers, numbers, files and protocol steps.
That is not real model evidence. Stage evidence remains caller-attested and awaits
the parent's real A/B and actual ChatGPT judgment. No segmentation/depth/OCR model
is run or downloaded; this stage imports precomputed outputs. No C, final quality
decision, calibration, batching, weights, training or new server/API integration.
Full baseline pytest coverage remains unavailable in this executor as documented.
