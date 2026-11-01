# Faithful excerpt mapping (mapping module only)

This additive mode does not change the AB diagnosis. It removes supplemental
mapping-added intensity labels and renders identical diagnosis excerpts once,
with all target associations. It is a joint intervention, not separate evidence
for the effect of strength versus repetition. No image-quality result is implied.

## Public contract

`visual_goals.faithful_mapping(spec, *, strength_basis)` returns a deep copy of a
normal S2 target mapping. The required keyword must be `mapping_added_labels`.
The caller must KNOW those labels were introduced by the mapping layer. The
helper does not infer provenance, parse natural language or reinterpret intensity.
It only handles the existing excerpt-backed `visual_goal` form; other strength
representations/extra goal fields are rejected, not silently discarded. Future
structured diagnosis with separately supported strength outside the excerpt is
out of scope; retain the legacy supported representation or design an explicit
migration rather than claiming this helper handles it.

The copied goals have `strength: null`, meaning "no supplemental label"—NOT
"no adjustment strength". The original `instruction` text is byte-identical:
words such as 明显, 适度, 温和 or strongly still instruct the executor. Target IDs,
subject/dimension/direction/priority and relationship operands are not removed.
The ordinary `freeze_targets` path still checks each exact excerpt against the
bound imported diagnosis. No additional arbitrary narrative is forwarded.

Use `s2_stage.freeze_targets(case, spec)` as before. On an existing case callers
must choose the next version and supply the required predecessor/revision audit;
the helper intentionally does not invent lineage, mutate old targets or rebind
old candidate receipts. New target hashes reflect null labels automatically.
The schema envelope remains v6 (additive nullable strength), with a distinct new
compiler version. Historical records remain immutable.

## Rendering / full flow

`render_target_prompt(target_payload, public_report, diagnosis_record, diagnosis_text)`
returns `(prompt, prompt_version)` without state, budget, dispatch or receipt.
The normal `compile_targets` now reuses this pure renderer. Full evidence/ledger
binding remains the surrounding coordinator's job; a standalone preview is NOT
a valid request or newly frozen target record. Every selected goal still undergoes
quote/hash validation against the provided diagnosis.

If any quoted goal is null-strength, all quoted goals in that plan must be null;
mixed faithful/legacy labels are rejected, never silently collapsed. Exact
identical `(diagnosis_hash, instruction)` is grouped; **all** corresponding target
IDs, subjects, dimensions and directions remain visible. Relation associations
explicitly include relation ID and directed endpoint IDs, even when two different
edges quote the same sentence. Different text is never paraphrased or merged;
conflicting directions, if present in caller targets, remain visibly distinct
rather than being silently resolved by the renderer. This is not a semantic
conflict adjudicator. Mandatory A preservation remains unchanged.

New versions:
- compiler: `faithful_diagnosis_goals_v1`
- current-chat edit export: `s3_faithful_diagnosis_goals_v1`
- feedback draft/export: `faithful_diagnosis_goals_feedback_v1` /
  `s4_faithful_diagnosis_goals_feedback_v1`

Legacy nonnull goals keep their old rendering and version byte-for-byte. Numeric
or plain typed controls are unchanged. ABC image-first/evidence projections still
contain one row per goal, including its original quote, null label and relation
operands: deduplication of edit prose does not delete evaluation goals.
Private acceptance policy is not read. Feedback still starts from original A/B,
not candidate geometry; this change does not authorize any new call.

## Actual historical fixture comparison

Author artifact `actual_pair/` (outside source) fixes the original actual AB
Markdown SHA df1bff1910bdae9fca2620ab3eb7b03a66b58661e87ea8ebb8fcd89538131619.
The same production renderer reproduces the original 6696-byte edit prompt SHA
c82adf7f5b510c8ccb25b7e70abbe262fa991ab2906d368c42781633693cfa4a.
Treatment keeps all 18 goals and renders 15 unique excerpts, with both t16/t17
relationship edges. It is an unregistered payload preview, not a new diagnosis,
request, execution, candidate or receipt. Attachment restoration is separate;
a text match alone does not claim the old four-image execution was reproduced.

Tests: from source, `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=engine/src python3 -m unittest discover -s engine/tests/reference_style -v`.
No model dependency/install is needed for these synthetic protocol tests.
