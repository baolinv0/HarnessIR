# S4 r2 — explicit offline ABC review, private verification and bounded feedback

**Runnable file protocol, not an automatic model runner. No model/API/Qwen calls occur.**
The S4 code gate and an actual scene/effect gate are separate. All supplied tests and
smoke outputs are synthetic. Current verified A/Base, B/sRGB, real evidence, actual
ChatGPT outputs, user-approved calibration/anchors and real run-budget values are
still pending. Never use synthetic receipts to satisfy a real sample.

See [r2 exact-artifact and public-target amendment](REFERENCE_STYLE_S4_R2.md) for
the selected-C representation contract, legacy factual-record migration and test oracle changes.

## Start / migration / complete command sequence

Run from `source/engine` with `PYTHONPATH=src python -m hre reference-style`.
Commands emit JSON records with IDs/content hashes; save those exact identities.
See [S0/S1](REFERENCE_STYLE_S01.md), [S2](REFERENCE_STYLE_S2.md) and
[S3](REFERENCE_STYLE_S3.md) for their manifest/input fields. Their historical envelope
names are superseded by **`reference_style_s4_v6`** in this copy. Old records are not
rewritten or relabelled: create a fresh sample with this code and explicitly import
actual evidence. Existing native stage-lab records are not these reference-style records.

1. `run --config INPUTS.json --out CASE`: audit original A/B, freeze role/color evidence.
2. **Before the first request:** `budget-configure --root CASE --spec BUDGET.json`.
3. `evidence-import --root CASE --manifest EVIDENCE.json [--asset ACTUAL_ASSET]` for
   available/unavailable/uncertain AB segmentation, face, relative depth and OCR.
4. `supports-freeze --root CASE --spec AB_SUPPORTS.json`; then
   `measure-ab --root CASE --snapshot-id s1`.
5. `ab-export --root CASE --report-id ACTUAL_REPORT_ID`; parent performs actual AB
   visual diagnosis outside this code; `import --root CASE --receipt AB_RECEIPT.json
   --output ACTUAL_AB_TEXT`. S2's AB receipt binds actual A/B/evidence/report; it
   retains the existing S2 receipt shape, not S3's separate submission-record format.
6. `targets-freeze --root CASE --spec TYPED_TARGETS.json`;
   `targets-compile --root CASE --version v1`.
7. `edit-export --root CASE --compiled-id ACTUAL_COMPILED_ID`; parent actually submits
   exported A/B images, localization guides and prompt in ChatGPT. Then
   `submission-record --root CASE --manifest ACTUAL_SUBMISSION.json --prompt-file ACTUAL_PROMPT.txt`;
   `import --root CASE --receipt EDIT_RECEIPT.json --output ACTUAL_RAW_C`.
8. `candidate-derive --root CASE --response-id ACTUAL_RESPONSE_ID --spec C_COLOR.json`.
   Raw bytes never change. Unknown encoding blocks exact analysis; assumed display
   is separately flagged. No silent resize/crop/geometry normalization to A.
9. `evaluation-version --root CASE --spec Q1.json`;
   `candidate-supports --root CASE --spec C_SUPPORTS.json`;
   `evaluate-candidate --root CASE --spec EVALUATE.json`.
10. `abc-export --root CASE --evaluation-id j1 --view image_first`. An independent
    reviewer first sees actual A/B/C with fixed roles and preservation goals, not
    method names, prior verdicts or numeric achievement. Record actual submission
    and import real text using the same commands as step 7 (response_type text).
11. `abc-export --root CASE --evaluation-id j1 --view evidence`. Record actual
    submission and import real evidence-assisted text. This view adds genuine
    bounded role guides and typed numeric/support evidence, never private policy.
12. `facts-freeze --root CASE --spec FACTS.json`: explicitly map actual diagnosis into
    closed factual fields; raw narrative remains archival, never executable edits.
13. Only with actual approved source artifacts, `policy-install`,
    `verification-rule-install`, optional `adjudication-install`, then
    `verify-candidate`, each `--root CASE --spec FILE.json`. Without suitable approved
    basis the result remains pending/insufficient; do not manufacture approval.
14. Optional explicit next round: `feedback-freeze --root CASE --spec FEEDBACK.json`;
    `feedback-compile --root CASE --compiled-id ORIGINAL_TARGET_DRAFT_ID --feedback-id fb1`;
    `edit-export` the new compiled ID. This starts again from **original A and B**,
    not old C. It does not modify StyleTargets, old receipts or tolerated geometry.
15. `label-select --root CASE --spec SELECTION.json`;
    `run-report --root CASE --out RUN_REPORT.md`.

Every command is explicit. No implicit stage advance/retry, budget increase, auto
feedback, model call, final acceptance or fallback-A success occurs. `status --root
CASE` validates ledger/assets. Generic old `export` is legacy protocol scaffolding,
not a replacement for measured `ab-export` / `edit-export` / `abc-export`.

### Budget contract and failures

`BUDGET.json` has exactly `version` (`bN`), `edit_attempts`, `diagnostics`,
`feedback_rounds`, `total`; counts are explicit nonnegative integers. Real runs
require user/operator-chosen limits before any attempt. This document gives **no
real default**. Only purpose `protocol_fixture` supports labeled finite synthetic
compatibility limits (1000/category and total), not real operating recommendations.

Exports reserve category+total before dispatchable artifacts. AB and each ABC view
consume diagnostics; edits consume edit_attempts; frozen feedback consumes
feedback_rounds. Unknown, failed and partially failed exports never refund. External
chat actions not made through these exports are outside enforcement.

`unknown --root CASE --attempt-id ID --reason TEXT` pauses the same attempt. A missing
or uncertain response cannot free a reservation or authorize another request.
An explicit terminal error can use `attempt-failed --root CASE --spec ERROR.json`:
`attempt_id`, `request_hash`, `reason_code:terminal_provider_error`, `artifact_path`,
`artifact_sha256`, `origin:actual_current_chat`, `tool_call_ref`. The actual artifact
is retained and locally hashed; this is caller attestation, not error authentication.
Timeout/unknown is not a terminal error code. After terminal failure a new explicitly
requested attempt costs a new reservation. Exhaustion prevents new exports but does
not prevent resolving/replaying an already reserved receipt. Partial artifacts are
never overwritten; unresolved discrepancies require inspection, not fabricated success.

## Factual evaluation identity (public, independent of private tolerance)

`Q1.json`:
```json
{"version":"q1","target_version":"v1","predecessor":null,"reason_code":"initial",
 "coordinate_rule_version":"whole_semantic_C_v1","numeric_rule_version":"ABC_signed_residual_v1"}
```

Default evaluation uses C's generation target. Sequential q2/q3 revisions require
`predecessor:{version,hash}` and reason `target_revision`, `corrected_evidence` or
`diagnosis_correction`. A changed target must be the explicit next S2 target revision.
Evaluation under revised targets requires a prior evaluation for that candidate;
never silently relabel an old generation receipt. One candidate/qN evaluation and
one facts record per evaluation are immutable. Corrections create a new version.

`EVALUATE.json` fields: `evaluation_id:jN`, `version:qN`, `candidate_record_id`,
`derived_record_id`, `support_id:kN|null`, `reevaluation:null` (initial) or
`{previous_evaluation_id,previous_hash,reason_code}` matching the profile predecessor.
Records bind raw C/selected derived C, generation and evaluation targets, AB report,
snapshot, support and numeric/coordinate rules. **No policy, calibration, verdict or
private rule reference is a field of the factual evaluation/profile.** Policy-only
change re-verifies the same facts in a new private decision, not new ABC evidence.

### Genuine C supports and comparability

`C_SUPPORTS.json` fields:
- `support_id:kN`, `version:qN`, `candidate_record_id`, `derived_record_id`,
  `candidate_hash` (raw C), `coordinate_image_hash` (selected derivative),
  `coordinate_frame:oriented_C`, `size:[width,height]`.
- `global_comparability:comparable|mixed|unknown`.
- `review:{path,sha256,source:{tool,version,origin}}` links actual supporting review
  bytes; origin `actual_tool|manual_review|synthetic_fixture` (last is fixture-only).
- `regions`: exactly every frozen AB semantic rN, no favorable subset/new partitions.
  Each has `region_id`, `mode`, `asset_path`, `asset_sha256`, `mapping`,
  `correspondence:confirmed|uncertain|unmatched`,
  `coverage:complete_comparable|mixed|unknown`, `occlusion:none_observed|partial|unknown`.

`actual_mask` requires an actual binary 2-D C-grid NPY, matching hash, no mapping.
`checked_A_mapping` requires no mask asset and explicit
`mapping:{kind:identity|integer_translation,offset:[dx,dy],source_size:[w,h],
target_size:[w,h],checked_against_C:true}`. The frozen A support is mapped to C only
under that recorded review. Equal image sizes alone never authorize reuse.
`unavailable` requires null asset/hash/mapping. Only identity/integer translations
are supported initially; arbitrary warps do not silently resample.

One immutable set per candidate/qN; parent-child subset and independent-region
nonoverlap enforced. Coverage/denominator, A/B fractions, bbox, lost mapped pixels,
coordinates and assets are frozen. Partial occlusion, uncertain/unmatched/empty
coverage, lost mapping pixels or unknown color cannot be numerical achievement.
Whole face/exposed_skin are valid; intraface tone units are not. These checks bind
provided evidence; semantic completeness and mapping correctness remain explicit
caller attestations requiring actual visual evidence, not automatically proven truth.

### Measurements

Frozen A/B full-precision source-reference analysis remains unchanged. Primary **C**
measurements now decode the **exact selected/exported RGB8 sRGB PNG bytes**, using
float64 arithmetic on their actual 8-bit values. The immutable selected-analysis
snapshot binds file hash, pixel hash, encoding, bit depth and analysis source/file
hashes. This is not restored RGB16 precision. S3 native/raw C analysis remains
unchanged and is retained separately as `native_C_diagnostics`; it cannot satisfy
final-artifact numeric gates. Unknown-encoding assumed-display C remains nonnumeric
regardless of its display PNG's sRGB tag.

Global/whole-region quantiles q05/q25/q50/q75/q95, mean and q95−q05 span; signed
region relationships are left minus right within each image. C−B, C−A, |A−B|,
|C−B| and absolute improvement `|A−B|−|C−B|` use selected C and frozen A/B references,
including negative improvement. Invalid comparability may retain observations but
not numeric eligibility. Empty/unknown is null, never zero. Numeric rows remain
`uncalibrated`, not achieved; S2 tolerance remains null. Selection and diagnosis
validate the same selected-artifact identity; no native-only pass transfers to a
different quantized/clipped output.

## Actual ABC bridge and closed facts

ABC exports reuse request/attempt locks, actual submission manifests and immutable
receipts. Planned images are A/content_image, B/style_reference, C/candidate_observation
in that order; evidence view may add one composite localization-only guide per role.
No guide is a hard mask or desired output. The original image derivatives are untouched.
Actual submitted attachment hashes/order/roles and prompt hash are recorded separately;
changed/missing/reordered payload is not treated as the planned request. Receipt binds
request, prompt version, candidate, evaluation, target and submission IDs/hashes.
Model internal resizing and whether it truly attended to attachments remain unknown.

Both ABC views include closed original tN goals: semantic subject, dimension,
direction, judge type/priority, metric/statistic and relationship endpoints. Image-first
omits measured values; evidence includes the frozen typed reference measurement
binding and actual selected-C residual rows. Neither includes target archival revision
prose, private tolerances or accepted history. Evidence guide status is explicit per
role; C gets an actual contour composite when selected nonempty C support exists.
The edit path remains original A/B only.

Image-first and evidence views may each be exported once per evaluation; correction
needs explicit reevaluation, not repeated diagnosis until a favorable answer appears.
`FACTS.json` fields:
- `facts_id:fN`, `evaluation_id:jN`, `evidence_response_id`, `image_first_response_id`
  (null is allowed but cannot meet the independent image-first verification basis).
- `reviewer:{reviewer_id,independence:independent|same_model|unknown}`.
- `overall_style`: exactly tone, color, brightness, each `{status,confidence}`.
- `targets`: exactly all frozen target IDs in order, each
  `{target_id,status,confidence,residual_code}`.
- `content_spatial`: exactly identity, layout, geometry, texture, ocr, naturalness,
  each `{severity,confidence}`.
- `spillover`: typed `{region_id,dimension,severity,confidence}` items.

Status is achieved|partial|unmet|uncertain; confidence high|medium|low|unknown;
severity none_observed|minor_local_incidental|major|unknown. Residual codes are
none_observed|too_bright|too_dark|too_warm|too_cool|too_saturated|too_muted|
tone_residual|relationship_residual|uncertain. Spillover dimensions:
tone|color|brightness|contrast|chroma|warmth. There is no arbitrary instruction,
region label, reason, history or permission field. Narratives/OCR are evidence/data,
not edit commands. Typed observation mapping and reviewer independence are attested,
not semantically certified by a parser.

## Private verifier, adjudication and selection

Private records/source snapshots live in `private_verification/s4/`, mode 0600.
Only verification/selection/human report code reads them. Execution payload builders
never read policy, accepted history or private decisions. The old S01 private policy
scaffold is not automatically a new S4 approved policy.

Source: `{origin:user_approved|synthetic_fixture|unapproved,path,sha256}`. Approved
sources require actual matching bytes. `unapproved` requires null path/hash and
cannot establish acceptance. Synthetic approval is forbidden for real-purpose samples.
No code can authenticate the user's approval from a caller's string alone.

Policy spec: `{policy_id,version,allow_minor_incidental,source}`.
Rule spec: `{rule_id,version,target_hash,policy_hash,source,global_anchors,
visual_target_ids,numeric_tolerances,critical_preservation,required_confidence,review_basis}`.
- global_anchors must explicitly cover tone,color,brightness for acceptance, even
  when selected StyleTargets omit global dimensions.
- numeric_tolerances are explicit approved `{target_id,max_abs_residual}`; none guessed.
- visual_target_ids require approved anchors/review basis.
- frozen current rule uses `critical_preservation:[identity,ocr,naturalness]`,
  `required_confidence:high`, `review_basis:independent_image_first`.

Verify spec: `{decision_id:zN,evaluation_id:jN,facts_id:fN,predecessor,adjudication_id,
verification_ref}`. verification_ref is null (uncalibrated) or
`{policy_id,policy_version,policy_hash,rule_id,rule_version,rule_hash}`.
A new decision for the same evaluation requires exact predecessor
`{decision_id,hash}`; old decisions stay intact. Policy-only revisions may change
this private decision, never the same ABC prompt, frozen facts or feedback payload.

Whole tone/color/brightness and critical applicable style targets must pass under
approved basis/high-confidence review. Numeric/visual conflicts remain explicit, not
averaged away. Unknown/unsupported/no basis never pass. Optional adjudication spec:
`{adjudication_id,evaluation_id,evaluation_hash,facts_hash,rule_hash,resolutions,source}`;
each resolution `{target_id,resolution:confirm_unmet|requires_re_evaluation|unresolved}`
addresses an actual bound conflict. There is no blanket override-to-achieved; corrected
facts require versioned reevaluation. Major content deviation rejects; unknown is
insufficient. Identity/OCR/naturalness deviations require revision. Only after whole
style/critical goals may actual minor incidental layout/geometry/texture deviation be
accepted when policy allows, flagged `incidental_deviation_tolerated`. Facts are never
rewritten as perfectly consistent. Weak style cannot be compensated by this tolerance.

Feedback spec: `{feedback_id:fbN,evaluation_id:jN,facts_id:fN,current_target_version:vN,
target_ids:[tN],include_global_residuals:boolean}`. It references measured residuals
and relation operands, and fixed restoration to original A for any observed deviation.
No private verdict or tolerant reason is forwarded. Current target must match eval;
old C requires explicit reevaluation first. `feedback-compile` starts from the original
measured target draft, not accumulated feedback; targets/old receipts do not change.

Selection spec: `{selection_id:selN,version:qN,decision_ids:[zN],
rule_version:first_accepted_generation_order_v1}`. All selected decisions must be
latest for their factual evaluation, same qN and compatible frozen policy/calibration
refs. Every generated candidate in the target lineage remains in the pool; omitted
or unevaluated candidates and unresolved reviews keep selection pending. Among a
resolved set, select the first accepted generation; transparent per-target/global
facts/conflicts remain visible, no opaque aggregate hides critical failure. No accepted
C means no_accepted_candidate, **never fallback A**. Manifest contains exact raw and
selected derivative hashes/paths/transforms and actual content facts. Visual acceptance
is **not pixel-label certification**: alignment/downstream suitability remain unchecked.

## One-document handoff

`run-report --root CASE --out RUN_REPORT.md` writes one immutable Markdown document:
input/output/record hashes, stage status, planned-vs-submitted details, actual
numeric/visual findings, versioned private decision summary, budget reservations,
unknowns and NOT RUN items. It is a **human audit report, not an edit prompt**; do not
feed acceptance history back into a composer. Use a new output filename after further
work, not overwrite an old report. All original local artifacts remain available.

## Future server Qwen: explicit integration work remains

Existing `engine/src/hre/stage_lab/native_workers.py` has `run_native`, `_qwen21`,
`compiled_condition`, `_images`, `_result`, with stage-lab request/result conventions.
It is **not automatically integrated** with reference-style v6 schemas/receipts.
No Qwen execution was performed or validated in these stages. In particular its
`_images` selects A/B and converts via Pillow; it does not implement the new C-view,
localization attachment manifest, full-precision audit, actual submission ledger or
factual-vs-private verification boundary.

A future authorized adapter must explicitly:
1. Map the frozen reference request's exact compiled prompt/version/hash (not an
   implicit PE rewrite), roles/order and every supported attachment into actual native
   inputs. Archive any rewrite/resize/unsupported-guide differences as a different
   request; never claim an unchanged package was seen.
2. Map attempt/sample/target/compiled/evaluation identities to native call/job IDs,
   checkpoint, seed, inference settings, actual submitted bytes and prompt hashes.
3. Add a distinct provider/origin and authenticated/attested receipt mapping in
   `contracts.py`, `coordinator.import_response`, `s3_handoff.record_submission` /
   `bound_submission`; current code intentionally requires ChatGPT current-chat
   provenance. Never spoof `provider:chatgpt` or `actual_current_chat` for Qwen.
4. Archive native raw outputs unchanged; only then use the candidate color/geometry
   audit. Preserve unknown/error budgets and idempotence. Separately implement a real
   AB/ABC VLM adapter; an image pipeline is not a diagnostic VLM.
5. Validate new adapter/schema migrations with independent tests and real server
   evidence before claims of support. No new provider framework is included here.

Same-goal deterministic-engine comparison, batch stability, real style efficacy,
actual tool-cache completeness, training utility and pixel-label certification are
**UNVERIFIED / NOT RUN**, not implied by synthetic protocol tests.
