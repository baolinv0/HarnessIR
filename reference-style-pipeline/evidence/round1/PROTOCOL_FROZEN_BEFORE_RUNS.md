# A01 diagnosis-spec attribution protocol — frozen before six runs

2026-11-01. Authorized diagnosis-only trial; no new image generation and no source modifications.

## Contrast
D0: reconstructed baseline, original fixed AB instruction plus compact neutral numeric evidence.
D1: same baseline and exactly identical evidence, with a generic sequence: reference-B state → A difference → change/keep/unknown → reference appearance/endpoint and preserved attributes → whole-region relationships and uncertainty.
No case-specific color correction or prior output lesson is inserted in D1. The seven region labels are neutral location/material identities shared by both arms. D1 has more instruction text; this experiment concerns the complete diagnosis specification, not a token-length-matched placebo.

This is NOT an exact replay of the old historical long context. The earlier session consumed summary/partial JSON and had accumulated conversation context; that context is not reconstructibly controlled. This experiment estimates differences in fresh-context diagnosis on one fixed pair under the two explicit instructions only. It does not attribute the historical generated C to a single cause.

## Fixed inputs / procedure
- Exact same current canonical A/B files, ordered A then B, original full-resolution, no new resize or color conversion by runners.
- Same compact AB q50 values: 40 region/metric medians plus seven signed relations, from the original verified numeric report. No asymmetric quantiles, masks, extra tool outputs or evidence budget. Full-precision numbers are in shared_evidence_exact.json; both actual prompt bodies contain the same shared_evidence.md rendered to five decimals.
- Both prompts use the same fixed A-preservation and diagnosis-only instructions. No C, user feedback, prior diagnostic prose/targets/results, old run outcomes, or final reports.
- Old mask images/localization guides are not supplied because not restored. No fictitious tool evidence. Numeric support limitations are stated identically in both arms.
- Parent runs six independent current-model sessions with fork_turns=none, three per arm. Repetitions use the same arm prompt; no inherited outputs or inter-run exchanges.
- Actual model sampling, seed and exact version may be uncontrollable. Record available identity honestly; no seed-equivalence or stochastic-independence claim. Three repetitions are descriptive, not statistical significance.
- Fixed balanced run order is in private/six_run_assignments.json; it is not claimed randomized. Runners receive only neutral packet filenames, A/B paths and the identical wrapper below. The parent retains the private arm mapping.
- A run is actual only after the model has inspected both images and the exact prompt and produced its output. Record prompt/image hashes, actual viewed scope and any tool failures. No placeholder output or receipt counts as a run.

## Identical runner wrapper
Read the assigned instruction file completely. Use tools.view_image to inspect the given A image followed by B image. Diagnose solely from these inputs. Do not read any other files, previous conversations, historical outputs, code or reviews; do not call other models or generate/edit images. Return the requested Chinese Markdown diagnosis. State if either image or any supplied text was not actually accessible. Save the output only to the assigned neutral run output path and return that path. Do not invent receipts or execution metadata.

The parent substitutes only instruction path, two fixed image paths and output path. Do not append a case-specific correction or expected answer.

## Predeclared evaluation
Parent arranges an independent A/B expectation reference before reading outputs. Evaluators see exact A/B, common evidence and neutral output IDs, but not arm mapping, prompt variant, history or C. They may infer instruction structure from answers: this is **label-blind**, not assured full blinding.

Five axes, scored 0/1/2 (unsupported/wrong or absent; partly correct/incomplete; specific and well supported), with concrete supporting/counterexamples:
1. Reference-description fidelity: accurately characterizes B, not merely a generic desirable look.
2. Action correctness: chooses supported change/keep/unknown and direction/strength for relevant whole regions; not every region needs the same change.
3. Reference endpoint and preserved attributes: specifies the desired B-like appearance and what must remain, rather than unlimited one-direction adjustments or copying B content.
4. Regional relationships: preserves and reasons about whole-frame relative appearance/ordering, including background; no intra-face tonal subdivisions.
5. Evidence/uncertainty: distinguishes visual observations, numeric descriptors and hypotheses, recognizes support/lighting/alignment limits and does not fabricate certainty.

Assess substantive correctness, not mere headings/field completeness. Keep critical wrong directions/content-change instructions visible rather than hiding them in an aggregate. Summarize each arm's three individual results and spread; no significance claim. Parent decides whether further generation is useful after results; this protocol authorizes none.

## Artifact boundary
Packets and hash manifest are frozen before runs. Private reconstruction provenance and assignments are not runner/evaluator input. Exact current source was restored and verified but not changed or executed for inference. Canonical input recovery is independently recorded by the asset agent.
