# Unified reference independent review — round 1

Verdict: **REVISE_BLOCKERS_ONLY**

Reviewer was a fresh read-only agent. Frozen baseline: `9073086bd86cff3062eab65bcbc32da6e4fd2114`. Reviewed candidate: `a836944463e3ba7246da058da8c592fd0ab6a770`, branch `codex/reference-unified-20261101`. Repository source remained unchanged; `git status --short` was empty after inspection. This review follows `docs/reference_unified/CONTRACT.md` (FROZEN) and the checked implementation plan, with the contract taking precedence over the skill's one-cycle limit.

## Requirement compliance before correctness review

| Requirement | Inspection and result |
|---|---|
| R1 historical versions | Inspected selector, stage/schema/template routing, shared planning import identity, contract validation, CLI, report and workbench mixin boundaries. Old routes are explicitly separate; no independent compatibility blocker found. Parent's already-run baseline/legacy evidence was reviewed, not rerun. |
| R2 imported evidence | Inspected imported package layout, selected/native identity handling, narrow Windows portability fixes and damage-before-calibration precedence. No independent blocker found in the imported historical path. |
| R3 complete semantics and audit | Inspected eight-dimension validation, exact target coverage, conditional limitations, actual deterministic text spans, native condition identity and full audit revalidation. No independent blocker found. |
| R4 evidence review | Inspected diagnosis/fresh-evidence hashes, separately bound effective diagnosis, compose gate, freeze and manual review append. No independent blocker found. |
| R5 whole-image first | Stage input projection, actual display hashes, six axes, A preservation and numerical ordering exist. **BLOCKER B2:** unified style acceptance ignores unresolved holistic conflicts. |
| R6 no-op/delivery | Inspected source result gate, zero compiler/image checks, original/native identity, geometry preflight and prepared native-size delivery checks. **BLOCKER B3:** required detail cannot be supplied through study/style verification paths. |
| R7 normalized feedback | Inspected exact candidate/round/verification binding, delivery stop precedence, mandatory review precedence, per-target corrections and frozen factual projection. No separate blocker; historical review scheduling is B4. |
| R8 same-candidate re-review | Existing bytes are retained and new observations are versioned. **BLOCKER B4:** importing a historical candidate observation unconditionally changes the current case scheduler and can turn an accepted case into failure. B2 repair must also preserve prior holistic observation bytes. |
| R9 frozen study/report | Inspected six runnable task arms, common offline evaluation separation, A-only brief/regions/reference stripping, frozen planned rows, baseline denominators, pending-result append, blind packet mapping, complete report and result/rating identities. **BLOCKER B1:** conflict detection compares only collapsed task success and silently chooses an effective-edit conclusion. B3 also affects study delivery. |
| R10 real boundaries/runbook | Read runbook/examples and CLI routing; inspected request preparation, final native condition audit, workbench ordered two-image submission and manual imports. No additional real/GPU/paid invocation was made. Real quality remains NOT_RUN and is not an engineering blocker. |
| R11 validation/CI | Read Linux/Windows focused CI, package/version changes and parent validation evidence. Full CPU suite was already running in parent; this reviewer did not duplicate it or claim it passed. |
| R12 independent review | This report and reproducible probes provide the first independent review. Publication should wait for blocker repairs, independent re-verification and the existing completion bar. |

## Reproduction

Use the repository virtual environment, from the repository root:

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONDONTWRITEBYTECODE='1'
& .venv/Scripts/python.exe docs/reference_unified/reviews/probe_round1.py
& .venv/Scripts/python.exe docs/reference_unified/reviews/probe_history.py
```

The probes use temporary, explicitly synthetic RGB PNGs and the existing fixture constructors. They call production study/style/controller code and do not replace production functions, fabricate remote model outputs, invoke network models, or edit repository source. Persisted historical outputs are `probe_round1_output.json` and `probe_history_output.json` beside this report. These record candidate `a836944`; run the probes against that candidate to reproduce the original findings. The archived copies differ only in repository-root discovery so they can run from this directory.

## BLOCKER B1 — Conflicting effective-edit ratings are counted as success

- Contract: R9 independent ratings, explicit adjudication and transparent effective_edit_success; unknowns must remain unknown.
- Location: `engine/src/hre/reference_core/study.py:304-309` (also `_rating_status` at 275).
- Trigger: import two independent, high-confidence ratings for the same planned run/result/evaluation. Both mark every mandatory target, protection, artifact and whole-image axis achieved/pass. The first says `relative_to_A='improved'`; the second says `'worse'`. Do not import an adjudication.
- Actual: `summarize()` collapses both to `_rating_status=True`, treats them as agreement, selects `observations[0]`, and reports `task_success=true`, **`effective_edit_success=true`**. Reverse import order changes the effective-edit result. Both rating hashes remain listed, so the report appears traceable while its conclusion silently chooses a rater.
- Expected: the affected effective-edit outcome must remain unknown until an explicit adjudication binds all conflicting ratings. Other decision-relevant target/protection/artifact/whole-image disagreements must also be detected at the observation level, rather than after boolean collapse. Uncontested task_success may be kept separately if the implementation explicitly distinguishes those outcomes.
- Minimum repair: compare the full decision-relevant independent conclusions (excluding identity/prose metadata) before choosing a rating; resolve conflicts only through the existing explicit all-ratings adjudication. Add reverse-order regression and differing-field regressions.
- Evidence: `review_probe_round1_output.json.conflicting_edit_ratings`: two rating hashes, no adjudication, effective_edit_success `true`.

## BLOCKER B2 — Unresolved whole-image conflicts still produce accepted style decisions

- Contract: R5 explicit conflicts and uncertainty, no silent cancellation; R8 immutable observations.
- Location: `engine/src/hre/reference_style/unified.py:186-201`, especially the acceptance ladder at 195-201. Integration gate is `engine/src/hre/reference_style/s4_verify.py:151-155`.
- Trigger: create an actual synthetic A/B/C style evaluation with frozen unified semantics and preflight. Import all three holistic stages in order, with exact display hashes. All axis/protection fields pass, but the first whole-image record explicitly contains an unresolved conflict. Import normal passing target facts and invoke production verification.
- Actual: `holistic_for_evaluation()` never examines `conflicts` from any stage. The full decision is **`status='accepted', acceptance_basis='consistent'`**, and the unified holistic assessment is also accepted.
- Expected: unresolved conflicts in any imported stage prevent acceptance and remain visible; numeric/local passing facts cannot erase them.
- Minimum repair: include unresolved holistic conflicts in the acceptance gate and carry their identity/details into the assessment/report. A later actual same-candidate review/resolution must append a bound version and preserve old bytes, rather than mutate or silently clear the original observations. Merely adding a permanent conflict rejection without a legal review-resolution route would leave the promised re-review path incomplete.
- Evidence: `review_probe_round1_output.json.style_unresolved_conflict`: real production decision accepted after the probe imported the unresolved whole-frame conflict.

## BLOCKER B3 — Frozen required-detail delivery has no executable evidence completion path

- Contract: R6 freeze native-content-size/detail requirements and independently assess actual delivery; R9 executable reporting for supported requirements; blocker definition includes a missing promised function or inability to run a supported path.
- Locations: study `engine/src/hre/reference_core/study.py:238-242,296`; style `engine/src/hre/reference_style/unified.py:139-146` and `engine/src/hre/reference_style/s4_verify.py:148`.
- Trigger: freeze valid semantics with `require_detail_pass=true`, import a full-native-size actual candidate and independent passing ratings/facts. The candidate can also be byte-identical A for a genuine S outcome in study.
- Actual: study always calls `assess_delivery()` with default `detail='uncertain'`; both result and rating schemas use exact fields and provide no detail field. Thus a legal import cannot ever establish required detail and task/edit success remain unknown. The style verifier likewise always calls `delivery_for_evaluation()` without its detail argument, so edited candidates under this valid requirement can never pass delivery even after a legitimate native-detail review.
- Expected: missing detail remains uncertain, actual independently reviewed native-detail pass can complete delivery, fail prevents success, and observations are tied to the current exact native candidate/result/evaluation identity.
- Minimum repair: add and validate a real bound detail-evidence input to the appropriate independent review records, propagate it to delivery assessment, and reject stale/unbound/uncertain evidence. Do not substitute an unchecked boolean or infer detail quality from enlarged display dimensions. Preserve compatible historical records and add pass/fail/unknown/wrong-candidate regressions for both supported paths.
- Evidence: `review_probe_round1_output.json.detail_required`: all required rating fields pass, 16x16 native equals frozen A size, delivery remains `uncertain` with no legal schema field to resolve it. Style missing propagation confirmed at the exact call site above.

## BLOCKER B4 — Historical candidate re-review corrupts current scheduling

- Contract: R8 same-candidate append-only observations with exact candidate/round binding; R7 feedback must drive the bound candidate, not a different round.
- Location: `engine/src/hre/v3/runner.py:864-909`, particularly unconditional `value.update(status='running',phase='refine')` at 901. The resume refinement branch at 764-765 selects the current `_get_round()` candidate, irrespective of the candidate just reviewed.
- Trigger: run a three-generation-budget feedback task where r0 receives a supported partial/revise and r1 is accepted. The case ends completed/success=true, selected r001. Append an exact predecessor-bound re-review of historical r0 with the same partial/revise conclusion. Resume the case.
- Actual: the append changes the accepted current case to running/refine while global round remains 1. Resume reads r1's stop feedback and terminates **failed, success=false, terminal_reason='feedback_not_actionable'**, with generation count still 2. A historical observation has invalidated an unrelated accepted candidate and made the documented resume path fail.
- Expected: historical re-review appends the observation and updates only consequences justified for that exact candidate. It must preserve unrelated current/terminal scheduling, or use an explicit correctly bound scheduling decision. It must never feed another round into refinement.
- Minimum repair: distinguish historical observations from current actionable reviews before changing global phase/status; retain current accepted state where appropriate, and bind any refinement scheduling to the reviewed candidate/round. Add historical/current review cases with accepted, revise, uncertain and stopped outcomes, asserting immutable previous records and no unintended generation.
- Evidence: `review_probe_history_output.json`: before completed/true selected r001; after running/refine round1; resumed failed/false feedback_not_actionable, generations2.

## Follow-ups and scope

No additional requirement is proposed. No model-quality assertion, broad redesign, private-input experiment, remote checkpoint or performance benchmark is required to repair these four engineering blockers. Other inspected areas have no separately reproduced blocker in this round; this does not substitute for the already-running full CPU result or the required targeted repair regressions.

Re-review should verify B1–B4 against the repaired candidate and inspect the repair diff for new in-scope regressions before assigning PASS_TO_NEXT_STAGE.
