# Unified reference independent review — round 2

Verdict: **PASS_TO_NEXT_STAGE**

Reviewed candidate: `7eaec58e97ac03bbe4a117d4692a0863e758e49a`. Initial implementation: `a836944463e3ba7246da058da8c592fd0ab6a770`. Engineering base: `9073086bd86cff3062eab65bcbc32da6e4fd2114`.

Reviewer: fresh read-only agent `/root/unified_reviewer_round2`, not an implementer. Source was not edited, committed or pushed by this reviewer. The probe and this report are written in the repository's parent workspace. The review uses the frozen `docs/reference_unified/CONTRACT.md`, the implementation plan and the original independent `reviews/ROUND1.md`; no product requirements were added.

## Requirement compliance before correctness

This round reads the contract/plan, implementation/executor/validation/runbook/review records and the entire production repair diff. It carries forward the first review's inspection of unchanged implementation paths, and independently checks the repaired boundaries and their interactions. It does not claim a fresh execution of every historical suite.

| Requirement | Re-review result |
|---|---|
| R1 historical versions | Repair adds explicit optional native-detail evidence and explicit resolution records. Historical ratings remain readable; historical schemas/templates are not silently migrated by this diff. Old v3 scheduling is changed only within the versioned review-import boundary. No blocker found. |
| R2 imported evidence | No imported historical color/encoding/support behavior is rewritten by repairs; style changes are the explicit unified extension and its verification/report gates. Parent's 177 imported tests and capability skip are recorded accurately. No blocker found. |
| R3 semantics/audit | Existing exact eight-dimension and final-condition audits remain unchanged. Repair does not widen edit authority or expose private tolerance. No blocker found. |
| R4 effective evidence | Existing diagnosis/effective-evidence/freeze boundaries remain unchanged. Resolution is an appended observation, not a mutation of the original holistic facts or task goals. No blocker found. |
| R5 whole-image first | B2 fixed: all stages' conflicts gate success; explicit all-stage/same-image resolutions are required; low-confidence/non-independent/unknown/rejected resolutions do not grant acceptance; old bytes remain. No unresolved blocker. |
| R6 no-op/delivery | B3 fixed: native-detail evidence has a bound executable path in study and style; actual delivery consumes the qualified conclusion; missing/unknown does not pass, fail prevents success. Source/native/result/evaluation/selected identities and native dimensions are checked. No unresolved blocker. |
| R7 scoped feedback | B4 fix keeps a historical candidate's feedback local while preserving current scheduling, selection and budgets. Current-candidate actionable review still recovers its own workflow. No unresolved blocker. |
| R8 append-only review | Resolution/detail chains validate exact predecessor, preserve observations and invalidate reuse of stale acceptance decisions on selection. Historical candidate records append without generating. No unresolved blocker. |
| R9 study/report | B1 fixed: full decision projection includes relative-to-A, target/protection/artifact states, six axes, confidence, independence and native detail. Any disagreement remains unknown until all-rating adjudication. Selected rating/adjudication identities and conflicts are exposed. All planned rows and denominators remain. No unresolved blocker. |
| R10 real boundaries | New CLI commands route to the same production functions and runbook supplies actual import paths. Review used only local synthetic files and fixture controllers, with no real model, paid or GPU call. No new boundary blocker. |
| R11 validation | Independently executed repair/CLI checks and minimal probes below. Parent's broader focused, style, package/JS evidence was read, not relabeled as reviewer-executed. Full CPU suite was already running from the initial candidate and is not claimed green here. Known unchanged Windows symlink privilege/deadline failures are not repair regressions. |
| R12 iterative review/publication | Four original blockers are re-verified as repaired. No new reproducible in-scope blocker found. This passes the independent review gate to finish truthful validation/publication; it does not assert remote publication or CI completion. |

## Repair correctness and inspected locations

- **B1:** `engine/src/hre/reference_core/study.py:290` normalizes complete decision fields before boolean collapse; `:298` leaves conflicting task/edit conclusions unknown and records selected/adjudication identities. `:264` requires the exact complete rating set for adjudication. Independent original probe now reports `rating_conflict_fields=["relative_to_A"]`, both successes null and no selected rating. Independent reverse-order/differing-field regressions pass. Supplemental confidence/independence probes also remain unknown until explicit adjudication.
- **B2:** `engine/src/hre/reference_core/evaluation.py:189`, `:231`, `:246` validate all original stage hashes, exact image/sample identities, exact predecessor and every conflict identity/text. Only independent high-confidence resolved observations clear conflicts. `engine/src/hre/reference_style/unified.py:275` checks all-stage conflicts; `:295` and `s4_verify.py:193` block selecting stale acceptance. Original probe now yields `needs_user_review`. Supplemental low-confidence and same-model resolutions cannot clear an explanations-stage conflict; legitimate appended resolution can; original observation bytes remain equal.
- **B3:** `engine/src/hre/reference_core/native_detail.py:22` validates the closed versioned observation and exact binding; `:39` qualifies independence/confidence. Study `:239` validates optional observations and `:298` propagates their qualified detail status into actual delivery. Style `unified.py:183`, `:200`, `:212` validate append-only detail history, preserve contradictory pass/fail uncertainty until explicit all-prior resolution, and feed actual delivery. Supplemental actual request bindings match the current native artifacts. Missing detail is uncertain, bound pass allows acceptance, newer unknown prevents reuse of the old accepted decision and fresh verification does not pass.
- **B4:** `engine/src/hre/v3/runner.py:902` determines whether the exact reviewed candidate is the current scheduled candidate; historical imports commit candidate-local observation only. Original history probe preserves completed/true/r001 before and after review, and resumes with exactly two generations. Supplemental current uncertain-to-accept import completes successfully with one existing image execution and unchanged budgets. The independent repair suite also covers historical accept/revise/uncertain/reject and current revise/uncertain/reject.

No mandatory fixes remain from this review. No optional product expansion is proposed.

## Actual reviewer executions

Run from `upstream-HarnessIR` with `PYTHONPATH=engine/src`, `PYTHONUTF8=1`, `PYTHONDONTWRITEBYTECODE=1`, using the repository `.venv/Scripts/python.exe`:

```powershell
& .venv/Scripts/python.exe docs/reference_unified/reviews/probe_round1.py
& .venv/Scripts/python.exe docs/reference_unified/reviews/probe_history.py
& .venv/Scripts/python.exe -m pytest engine/tests/test_review_round1_repairs.py engine/tests/test_reference_entrypoints.py -q
& .venv/Scripts/python.exe docs/reference_unified/reviews/probe_round2.py
& .venv/Scripts/python.exe -m pytest engine/tests/reference_style/test_unified_review_repairs.py::UnifiedReviewRepairTest::test_all_stage_conflicts_block_acceptance_and_bound_resolution_restores -q
git diff --check
git status --porcelain
git rev-parse HEAD
```

Results:

- Both archived original probe programs completed with exit 0 and the repaired outcomes described above.
- Repair/CLI suite: **47 passed in 34.12 seconds**, exit 0.
- Supplemental reviewer probe: exit 0; full reproducible script `probe_round2.py` and historical JSON output `probe_round2_output.json` are archived beside this report. Only repository-root discovery was adjusted in the archived script. It asserts the supplemental study, holistic, native-detail freshness and current-candidate recovery scenarios above. These are explicitly synthetic protocol observations, not quality results.
- Three-stage style regression: **1 passed, 3 subtests passed in 37.01 seconds**, exit 0. Each original whole-image/whole-region/explanations conflict blocks success and can complete via a correctly bound appended resolution while preserving old observation bytes.
- `git diff --check` passed. Final `git status --porcelain` was empty and `git rev-parse HEAD` remained `7eaec58e97ac03bbe4a117d4692a0863e758e49a`.

## Completion boundary

The independent repair-review gate passes. Required final source/remote SHA verification, actual PR/CI state and the already-running broad CPU result remain the parent's publication tasks. This reviewer did not repeat the complete CPU suite, did not declare it green, and did not run real quality/GPU/paid experiments. Such experiments remain **NOT_RUN** under the frozen non-goals and are not software-completion blockers.
