# Unified reference implementation evidence

Contract: [CONTRACT.md](CONTRACT.md). Plan: [implementation plan](../superpowers/plans/2026-11-01-unified-reference-implementation.md).

Status: implementation and two independent review rounds complete at local code candidate `7eaec58e97ac03bbe4a117d4692a0863e758e49a`; all four first-round blockers were repaired and independently re-verified. No unresolved in-scope blocker remains. Published code `bd25c7a` passed Linux/Windows focused CI and Linux full-engine CI. [PR #12](https://github.com/baolinv0/HarnessIR/pull/12) is open, attached and unmerged. Actual local failures and remote successes remain separate in [VALIDATION.md](VALIDATION.md). No real image/GPU/paid model experiment has been performed for this change.

## Requirement traceability

| Requirement | Implementation | Relevant evidence |
|---|---|---|
| R1 version/history | v3/reference_selector, separate reference_retouch_v2; workbench UnifiedWorkbenchMixin | old v3 template/request and delivery tests; explicit new-version tests |
| R2 audited evidence | installed reference_style package and pure color; POSIX asset paths; exact UTF-8/LF fixtures; major-damage precedence | imported 175 plus 2 portable regressions, 177 tests green, one OS-capability skip |
| R3 coverage/limits | reference_core/contracts + rendering; v2 contract; final-condition semantic_audit; style semantic-freeze | missing/duplicate dimensions, unsupported targets, conditional limits, native audit hash/spans and thin-audit rejection |
| R4 effective evidence | runner evidence_review phase and effective diagnosis; workbench evidence review; immutable style revisions | resolved/unresolved evidence and actual request bindings |
| R5 holistic evaluation | reference_core/holistic and evaluation; independent whole_image_review phase; style holistic-import/gate | six axes, A protection, order, display identities, no hidden aggregation; whole-image-before-local negative controls |
| R6 no-op/delivery | shared delivery preflight/assessment; v3/workbench new routes; style no-edit/preflight | zero-call production no-change example; native-size failure despite enlarged preview |
| R7 normalized feedback | reference_core/feedback and v2 runner/workbench; original A/B | per-target suggestion without duplicate issues; pending and delivery-stop ordering; frozen goals |
| R8 re-review | v3 candidate/planning review imports; workbench appended review; style evaluation/decision chain | previous observations retained; no generation during review; missing calibration cannot hide major damage |
| R9 study/report | reference_core/study + CLI | six actual v3 task arms; true A-only runtime projection; all planned P rows; native gate; S/B distinction; bound neutral ratings; conflict adjudication; appended P resolution |
| R10 real boundaries | existing configurable VLM/GPT Image API and native adapters; new UI/version/CLI routing | actual loopback multipart assertions; one installed hre path; no remote quality claim |
| R11 validation | Linux/Windows reference-unified CI plus existing complete-engine CI | focused CPU tests, imported unittest, CLI/help, JavaScript syntax and wheel content checks |
| R12 review/publication | independent read-only review then blocker repair/re-verification | final review record and verified remote commit/PR are added only after completion |

## Actual local checks before independent review

- Previous clean-base compatibility: 95 focused tests passed.
- Imported evidence after portability repair: 177 unittest tests, one skip for Windows symbolic-link privilege; all remaining passed. This includes two regressions added after reproducing the failure on unmodified code.
- New shared/evaluation/study/entrypoint checks passed; exact final combined count is recorded after the implementation agent freezes its tests.
- New style semantic/no-op/preflight/holistic gate: six tests passed.
- Production `engine/examples/reference_unified/check_no_change.py` on actual temporary synthetic 64x48 PNG: source pixels unchanged, already_satisfied; generations=0, stage_calls=0, compiler_calls=0. The observation is from exact A=A pixel identity, not an invented VLM opinion.
- Editable installation succeeds as harness-ref-enhance 0.4.0; installed hre resolves this repository's engine/src/hre. New CLI help resolves from the same package.
- JavaScript syntax and diff whitespace checks passed before final freeze.
- Initial wheel build succeeded; final package is rebuilt after final code changes.
- Full CPU suite launched with `python -m pytest engine/tests -q --durations=12 -o faulthandler_timeout=120`; no complete-suite pass is claimed until it exits.

## Independent review and repairs

See REVIEW.md for the actual reviewer verdict, reproducible blockers, repair commits and verification. A self-check or old release review is not substituted for this review.

## Real-world evidence boundary

The implementation includes executable configuration, transport and study/report protocols. It does not certify a checkpoint, interpret an unknown backend as a named model, create training labels, establish Base-domain quality, rank four executors or prove stable style transfer. Actual inference, private inputs and approved experiment budgets are required to populate real quality results; study rows remain P/unknown until observations are imported.
