# Validation evidence

All image fixtures below are explicitly synthetic. No paid model, remote image generation or GPU inference was run. This record establishes engineering behavior, not style-transfer quality.

Environment: Windows, Python 3.12 bundled runtime in the repository virtual environment, `PYTHONUTF8=1`, `PYTHONDONTWRITEBYTECODE=1`, installed editable `harness-ref-enhance==0.4.0` resolving this repository's `engine/src/hre`.

## Recorded checks

| Check | Actual result |
|---|---|
| Original focused compatibility before changes | 95 passed |
| Imported style suite after portability repair | 177 unittest tests, OK, one capability skip for Windows symlink privilege |
| New style semantic/no-op/preflight gate before review | 6 passed |
| First independent review | Four reproducible blockers; see [ROUND1](reviews/ROUND1.md) |
| First repair counterexamples against unfixed behavior | 28 failed / 19 passed, including subtests; used as failing-to-passing evidence, not release validation |
| First repaired targeted set | 58 passed, 6 subtests passed in 173.65 seconds |
| Final repaired core/study/CLI/scheduling and compatibility set | 132 passed in 79.23 seconds |
| Final repaired style conflict/detail/version boundaries | 18 passed, 6 subtests passed in 228.79 seconds |
| Fresh second independent review | PASS_TO_NEXT_STAGE; 47 repair/CLI tests, one three-stage test plus three subtests, original and supplemental probes passed |
| JavaScript syntax | `node --check` passed for both `app.js` and `experiments.js` |
| Whitespace | `git diff --check` passed |
| Installed commands | `reference-style`, `reference-evaluate`, `reference-study` help all exit 0; new review-resolution/detail commands present |
| Wheel after repairs | Built successfully; 145 members, eight required integration paths checked including `reference_core/native_detail.py` |

Wheel SHA256 at the repaired-code freeze: `d866aaa99e43936c3aa449a450a2ad14ebe4fc87fc984bf22e8a3cbac7cd7fc7`. Wheel bytes are a local build artifact, not committed source. Rebuilding can change archive metadata.

The production no-change example used actual temporary synthetic 64x48 A=A PNGs: returned original A pixels, `already_satisfied`, `generations=0`, `stage_calls=0`, `compiler_calls=0`.

## Broad regression and independent re-review

The full engine CPU run was launched before repair, using `python -m pytest engine/tests -q --durations=12 -o faulthandler_timeout=120`. It remains in progress at initial publication. A complete-suite green result is not claimed. The unchanged original `test_hre_assets.py::test_paths_reject_symlink` was separately confirmed to fail with Windows `WinError 1314` before reaching its assertion because this machine cannot create symbolic links. The unchanged `test_hre_model_workers.py::test_failed_worker_records_one_attempt` was separately rerun: four failed, one passed, because its 0.2-second deadline expires before fixture execution in this machine's current conditions. Production `model_workers.py`, `models.py` and that test are byte-unchanged relative to the base. These are recorded separately from repair validation. Final broad counts and any other failures will be added after completion.

The fresh second reviewer passed the independent gate on `7eaec58`; its full [ROUND2 report](reviews/ROUND2.md) distinguishes reviewer executions from parent evidence and explicitly leaves broad/remote status unclaimed.

The final source also runs in the committed Linux/Windows focused CI matrix; the existing Linux full-engine job remains enabled. CI status is reported from actual GitHub results after publication, never inferred from these local checks.
