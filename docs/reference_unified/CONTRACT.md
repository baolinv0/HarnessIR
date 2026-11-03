# Unified reference implementation contract

status: FROZEN
date: 2026-11-01
base: 9073086bd86cff3062eab65bcbc32da6e4fd2114
evidence_source: 6adfd0ba7054d453662df7e91c93f547a85e6fdc
branch: codex/reference-unified-20261101

## Outcome

Deliver one installable HarnessIR engine combining the retouch product contract with the audited reference-style evidence path. The existing workbench and native-model entry points remain usable; the new reference-style commands resolve the same installed hre package. Implement the seven documented engineering gaps, whole-image-first evaluation, and an executable study/report protocol. Publish reviewed source and tests to a new GitHub branch and PR.

## Scope

R1. Preserve old v3, reference_retouch_v1, and reference_retouch_delivery_v2 payloads, template/request identities, and historical files. New semantics use reference_retouch_v2 / reference_retouch_delivery_v3. Do not silently upgrade old records.

R2. Import the 21 reference-style modules and their tests into engine/src/hre/reference_style and engine/tests/reference_style, plus the required pure color implementation. Preserve raw/derived/selected file identities, unknown encoding, native-grid A/B/C supports and genuine evidence restrictions. Fix Windows relative-path, UTF-8/LF test, and known-major-damage precedence defects. No entire second checkout or private evidence is vendored.

R3. New unified tasks cover exactly eight appearance dimensions. Every target binds A/B facts, attribute, supported comparability, limitations, mandatory flag and observable acceptance criterion. Every actionable target is covered once; an unknown/incomparable difference cannot authorize an edit. Entire face/object/material units remain the edit units. A supplied visual quote proves provenance only. All requirements and limitations must reach the actual compiled condition; native rewrites require a bound semantic audit and block missing/contradictory/uncertain critical coverage.

R4. Evidence review is executable before target freeze: initial diagnosis and fresh evidence remain archived; effective diagnosis is separately bound. needs_evidence or new conflicting evidence cannot fall through compose without a resolved review. Frozen goals cannot be changed by feedback; contradicting new evidence requires explicit revision.

R5. Whole-image-first review has a closed contract: actual display/file bindings; whole-frame B fidelity for tone, color, brightness, lighting naturalness, material relationships and processing appearance; A preservation separately; subsequent whole-region review and explanatory metrics. Record direction/ranking, magnitude, confidence, exposure and uncertainty. A numerical/local preference cannot silently cancel whole-image observations. No default weighted aggregate or posthoc tie. Unknown is not failure or achievement.

R6. A supported already-satisfied outcome returns frozen A with zero compiler/image calls and independent delivery check. Failed source fallback is distinct. Freeze native-content-size/detail requirements and run delivery feasibility preflight before image calls; padding/upsampling do not satisfy native resolution. Retain original A/B and native C; explicit declared-working-size is a distinct task mode, never a retroactive threshold change.

R7. One normalized feedback record drives target/preservation/artifact/delivery action: revise_prompt, gather_evidence, manual_review, stop. Bind exact candidate/round/verification. Pending mandatory review blocks refinement; known delivery infeasibility stops; actionable per-target corrections must not depend on duplicate legacy issue fields. Refinement changes execution expressions only and restarts from A+B. Unknown submissions do not refund or authorize retries.

R8. Same-candidate re-review appends a versioned observation/decision without generation or rewriting old verdicts. Private tolerance never enters diagnosis, edit or feedback. Known major damage is reported rejected even when calibration is unavailable; incomplete calibration still blocks success.

R9. A frozen study builder supports legacy_native_ab, legacy_shared_ab, legacy_aware_ab, retouch_shared_ab, retouch_aware_ab, legacy_aware_a. It freezes common offline evaluation and baseline status before results, binds planned run identities, and resolves new arms to actual runnable new contracts. A-only inputs, brief, regions, caches and runtime verification exclude B-derived data; offline evaluation is stored separately. Retain all planned runs, failures and pending results. Provide independent rating import and explicit adjudication, transparent task_success/effective_edit_success with unknowns and denominators, and a single complete Markdown report.

R10. Existing configurable VLM/GPT Image and four native executors remain real execution boundaries. Add explicit command/runbook/example paths for the integrated workflow. Validate transport and requests with local HTTP/fake protocol fixtures, never invent real model outputs. GPU checkpoints, private photos and credentials are not required for offline software completion and are never published.

R11. Windows and Linux CPU CI exercise imported reference-style tests, new unified contracts/evaluator/study tests, old focused v3/workbench compatibility, CLI and wheel contents. Any unrelated existing failures must be recorded accurately, with no blanket green claim.

R12. Each implemented requirement has code/test evidence in IMPLEMENTATION_REPORT.md and independent REVIEW.md. Reproducible in-scope reviewer blockers are repaired and re-reviewed until no blockers remain. The human explicitly requested iterative completion, overriding any skill's arbitrary one-cycle cap. Publish only after this bar passes; do not merge the PR automatically.

## Frozen Design

Use the 10/26 repository as the engineering base. Keep its two state machines; share small pure reference_core rules rather than merge histories. Import the 11/1 evidence package into the existing engine, preserving historical style records. New style semantic/delivery extensions are explicit records, never edits to an old frozen target. Whole-image evaluation and study are provider-neutral. Shared semantic-rule API is defined in PLAN.md. Each native rewrite is inspected against the same actual condition that generation consumes.

## Non-goals

No new model training, no fabricated visual judgement or remote identity, no unapproved paid image/GPU experiments, no assertion of stable quality improvement or training-label certification. Real Base-domain/held-out/feedback-effect experiments are executable protocols and explicitly NOT_RUN until genuine inputs, configured backends and budgets are available. Preserve newest whole-face/material scope; do not restore older intraface editing examples.

## Robustness Envelope

Opaque SDR PNG/JPEG and the explicitly supported color/precision paths; separate coordinate grids; missing/conditional evidence; failed/unknown calls; restart/replay; finite budgets; same-candidate review; old/new-version rejection; native/deployed file distinction. Color metadata conflicts and malformed/nonfinite data fail closed. Unsupported provider/capability remains unavailable, not a synthetic success.

## Required Evidence

Failing-to-passing regressions for each fixed bug; negative coverage and audit cases; no-op counters/pixels; preflight zero-call rejection; independent holistic observations and conflicts; A-only leakage negatives; planned-run denominator examples; actual local HTTP multipart and complete candidate identity; legacy/new template identity checks; CLI help, wheel, JS, focused test logs and CPU CI. Synthetic fixtures are labelled as such.

## Completion Bar

R1-R12 implemented and traceable; required new/focused tests green, imported style suite green apart from explicitly capability-skipped symlink tests, no unresolved in-scope review blocker; source clean and no private assets; new branch/PR visible at the verified commit. Real quality is NOT_RUN, never a software completion gate masquerading as measured success.

## Blocker Definition

A reproducible violation of R1-R12 or the robustness envelope that causes wrong success, lost/falsified binding, inability to run the documented supported path, privacy leakage, incompatible history, broken core tests, or a missing promised function. Preferences, unrelated cleanup and unmeasured possible model gains are follow-ups. A reviewer may not expand scope by opinion.
