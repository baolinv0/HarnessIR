# S4 r2 amendment — coherent selected C, explicit ABC goals and C localization

This bounded correction follows the independent S4 r1 REVISE reports. The r1 source,
records, verdicts and evidence remain untouched. No model/API/Qwen or real-scene
execution occurred. All fixture tolerances here are contract probes, not recommended
production calibration.

## Exact representation used for numeric C achievement

The S3 candidate audit retains its original meaning: native/raw RGB16 or P3 decoded
before final RGB8 endpoint clipping and quantization. A/B source analysis is also
unchanged. `s4_selected.analyze_selected(root,derived,evaluation_id)` now separately
reuses the unchanged strict color audit on the **actual selected derivative bytes**.
It validates source-file/pixel hashes, sRGB encoding, RGB8 bit depth and no extra
orientation/geometry; stores an immutable `s4/selected_analysis/jN/` snapshot with
analysis NPZ, captured exact source and audit output assets. The extra audit output
is not a newly selected C; the selected path/hash remains the original S3 derivative.

New factual profile/evaluation field:
`candidate_measurement_basis: selected_C_artifact_v1`.
Evaluation `selected_artifact` records:
- `path`, `file_hash`, `pixel_hash`, `encoding`, `bit_depth`, `numeric_status`;
- `analysis_path`, `analysis_file_hash`, `analysis_source_file_hash`;
- fixed precision statement: exact selected RGB8 values computed in float64, **not
  restored native precision**.

Primary `measurements`/`C_distributions`, residuals, feedback directions and private
numeric predicates use this analysis. `native_C_diagnostics` separately retains
raw candidate hash, original analysis path/hash and native distributions, labeled
raw-before-clipping/quantization and **not acceptance evidence for the selected file**.
The original S3 candidate audit and raw bytes are never rewritten/rebound. Labels
retain both identities and add `evaluated_artifact` and the representation basis.

If original C encoding was unknown and S3 only assumed sRGB for display, r2 never
upgrades it based on the newly tagged PNG. `selected_artifact.numeric_status` remains
blocked_unknown_encoding; analysis paths/numbers remain null. Failed/no-display C
stays unusable for ABC images. Color/support uncertainty is not relaxed.

## Versioned migration, not silent relabeling

Envelope remains `reference_style_s4_v6` so existing A/B/evidence/raw-C records remain
readable. New selected-representation marker is mandatory for factual evaluation,
ABC export, private verification, selection and feedback execution. An old v6 r1
evaluation/profile lacks it; it cannot inherit current acceptance or feed new editing
instructions. Archived reports can be read but explicitly show the legacy basis.

For an existing r1 sample, preserve q1/j1 and decisions. Explicitly freeze next qN
with predecessor hash and reason `corrected_evidence`, re-freeze C support for that
version, and evaluate with the prior candidate evaluation/hash/reason reference.
Perform new image-first/evidence requests and facts; then new private verification.
Do not mutate old conclusions, targets, raw receipts or set a marker by hand.
A fresh sample can use q1 with the new producer. Private policy-only revisions still
reverify the same factual evaluation without changing ABC/feedback prompts.

ABC prompt versions are now `s4_ABC_image_first_selected_goals_v2` and
`s4_ABC_evidence_selected_goals_v2`. The generic residual formula rule remains
`ABC_signed_residual_v1`; the new explicit representation basis distinguishes its
C operand. Receipts continue binding exact request/prompt/evaluation hashes.

## Closed public goals in both ABC phases

`s4_targets.target_view(target,report,include_numbers)` validates a typed allowlist
against the actual frozen AB report and emits `context.targets`:
`target_id`, `subject_id`, `semantic_class`, `dimension`, `direction`, `judge_type`,
`priority`, `measurement_id`, `metric`, `statistic`, `left_region_id`,
`right_region_id`, `left_semantic_class`, `right_semantic_class`,
`reference_measurement`.

Image-first has null reference_measurement (no numeric findings), but intelligible
original goal identities and relation endpoints. Evidence includes the validated
frozen reference measurement (A/B/statistic/delta/operand/support refs) and the
selected C residual rows. Visual-only goals retain typed dimension/direction with
null metric/statistic/binding. Field types/enums/references are validated; arbitrary
labels or permission prose reject. Top-level target revision rationale, source
metadata, private calibration/tolerances, acceptance decisions/history and raw VLM
narratives are not serialized as goals. This is not keyword filtering.

## C localization, without changing edit inputs

The reused guide helper now takes an explicit roles tuple. Its edit default remains
`('A','B')`. ABC evidence explicitly asks for `('A','B','C')`; each actual C mask comes
from the hash-bound frozen C support set on the exact selected C grid, not a copied
B mask or size-only A assumption. At most one composite per role. Original A/B/C
images are first and unchanged; guides are localization-only, not hard masks, target
images, desired outputs, or claimed model mask capability.

`context.localization_guides` reports each role as `provided` or
`unavailable_no_nonempty_selected_support`. Missing/empty support is not fabricated.
The image-first view keeps only the three original images. Feedback edit exports
still contain original A+B, never old C or C guides.

## Test oracle migration (frozen independent tests not edited)

The original 39-test independent S4 source is rerun byte-for-byte in a separate
output directory to preserve its prior failure artifacts. Its original must-fix
selected-file and missing-target tests now pass. Three old methods still encode
native16-C expectations for primary C fields:

1. `test_fullprecision_residuals_independent_oracle_all_regions_and_relation`
   (four regional/global/relation subtest failures): keep A/B raw16 oracles; compute
   primary C from exact selected RGB8 bytes. Test raw16 C separately against
   `native_C_diagnostics.distributions`, including relationship endpoint differences.
2. `test_integer_translation_different_C_grid_explicit_and_lost_pixels_reported`:
   keep coordinate/bbox/lost-pixel assertions; mapped C that originally equals raw16
   B can have nonzero selected-file residual after quantization.
3. `test_saturation_and_critical_region_spillover_not_dropped`: keep spillover/count
   assertions; the untouched region's final RGB8 residual need not be zero against
   full-precision B. Assert its independently decoded selected-pixel residual.

These are representation-oracle migrations, not reasons to loosen calibrated
acceptance or alter input A/B semantics. Zero/tight thresholds remain valid synthetic
contract probes: if the actual selected file fails them, no accepted label is emitted.
Prior S01's one missing mandatory-budget precondition migration remains separately
documented; its synthetic-provenance rejection assertion must not be weakened.
