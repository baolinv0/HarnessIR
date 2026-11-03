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

## Completed broad regression and independent re-review

The full local Windows run finished: **905 passed, 15 failed, 3 skipped, 178 subtests passed in 3039.74 seconds**. Its initial-source/mixed-time boundary and all 15 actual tracebacks are classified in [LOCAL_REGRESSION.md](LOCAL_REGRESSION.md): four symlink fixture privilege failures, five existing 0.2-second subprocess deadline failures, six missing-Streamlit imports. No unified functionality assertion appears in its failed-test list. This is not an immutable final-snapshot green result.

After installing declared `streamlit==1.65.0`, the affected UI set produced **10 passed, 3 failed**; remaining failures were the unchanged three-second AppTest deadline. A separate actual UI probe using the public explicit 30-second timeout passed all three pause/resume/retry scenarios. Its script/output are archived, with no production monkeypatches. These observations do not alter the original full-run counts or establish three-second responsiveness.

The fresh second reviewer passed the independent gate on `7eaec58`; its full [ROUND2 report](reviews/ROUND2.md) distinguishes reviewer executions from parent evidence.

## Completed remote CI and publication

Published code commit: `bd25c7a853c73945b17cfa75a569a8e6d45f0eb8`. Its full Git tree `89e41384d1d22b2ba6820cdb1b1c37354c201c1c` was verified identical to local source/documentation commit `32f1fa3fc9102a275e8149b50dead3cbdb7a148d`. Production code and workflow files are unchanged from independent review candidate `7eaec58`. Git transport repeatedly reset, so publication used the connected GitHub Git-data API; differing commit metadata did not change the verified bytes.

Actual GitHub Actions checks on that published code all completed **success**:

| Required check | Actual result |
|---|---|
| [Linux focused contracts/evidence/compatibility/CLI/JS/package](https://github.com/baolinv0/HarnessIR/actions/runs/41324443399/job/124901327506) | success |
| [Windows focused contracts/evidence/compatibility/CLI/JS/package](https://github.com/baolinv0/HarnessIR/actions/runs/41324443399/job/124901327641) | success |
| [Linux complete engine CPU and JavaScript](https://github.com/baolinv0/HarnessIR/actions/runs/41324443404/job/124901327265) | success |

The duplicate push-triggered Linux/Windows focused jobs also succeeded; duplicate jobs are not counted as extra coverage. [PR #12](https://github.com/baolinv0/HarnessIR/pull/12) targets `codex/reference-retouch-contract-20261026` from `codex/reference-unified-20261101`, remains open/unmerged, and is attached to the chat. Initial remote ref, tree and all 97 initial changed paths were verified through GitHub readbacks.

Final documentation-only commits append this completed evidence, the local audit and the executed diagnostic probe. They do not change the reviewed engine/workflows. Their commit message uses `[skip ci]` to avoid repeating successful code checks for a documentation-only update; the green check links above refer explicitly to the code commit. The final head/tree/path readback is recorded in the PR description and delivery response.
