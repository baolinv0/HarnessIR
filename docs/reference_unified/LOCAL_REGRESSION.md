# Local complete CPU regression audit

Status: **COMPLETED — local broad suite is not green**. Printed result: **15 failed, 905 passed, 3 skipped, 178 subtests passed in 3039.74 s (50:39)**. This document audits the existing Windows run without rerunning it, polling its owner session, terminating it or changing production/test source. Root owns CI and other validation reports.

## Invocation and snapshot boundary

Working directory: `C:\Users\Lenovo\Documents\ChatGPT\RefHarnessIR\upstream-HarnessIR`.

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONDONTWRITEBYTECODE='1'
& .venv/Scripts/python.exe -m pytest engine/tests -q --durations=12 -o faulthandler_timeout=120
```

Output was redirected to `C:\Users\Lenovo\Documents\ChatGPT\RefHarnessIR\unified_full_engine_tests.txt`. Root owns executor session `28725`; the observed Python PID is `18344`, started **2026-11-01 23:20:00.907 +08:00**.

This is the initial integration candidate run (reported as `a836944463e3ba7246da058da8c592fd0ab6a770`; that snapshot was committed at 23:22:40 after the process started). Tests collected/imported the initial sources. First-review repairs were frozen later as `7eaec58e97ac03bbe4a117d4692a0863e758e49a` at 23:50:38; documentation commit `32f1fa3fc9102a275e8149b50dead3cbdb7a148d` followed at 23:58:50. Files and editable installation changed while this long process remained active. Consequently, this summary is broad evidence from that time interval, **not a clean immutable-final-snapshot run**. In particular, Python modules already imported may retain initial code while subsequent child processes or file reads can see later files. Final repair validation and independent re-review are recorded separately; they do not erase a local broad failure.

The regression comparison base is `9073086bd86cff3062eab65bcbc32da6e4fd2114`. An unchanged path alone does not prove an environment issue: each final failure must be classified using its real assertion/stack, relevant dependency path and available independent reproduction.

The audit interpreter resolves `hre.__file__` to this checkout's `engine/src/hre/__init__.py`. Read-only environment inspection reports Python **3.12.14** (MSC v.1944, AMD64), pytest **9.1.1**, jsonschema **4.26.0**, referencing **0.37.0**, pydantic **2.14.1**, Pillow **12.3.0**, NumPy **2.3.5**. These are the inspected local environment versions, not a reconstructed historical base environment.

## Observations before the final summary

At **2026-11-02 00:08:29 +08:00**, the log's last progress line was **67%**. It had no final summary or failure traceback section. The process was alive/responding, cumulative CPU **2224.203125 s**, up from **2172.375 s** during the preceding inspection. No failure count is inferred from progress `F` characters.

The log contains a 120-second faulthandler watchdog dump while `test_hre_reference_feedback.py::test_first_pair_review_can_continue_same_cohort_then_receive_fresh_final_reviews` was inside `reference_experiments.summarize_reference_run` → `reference_run_status` → `reference_runtime.evaluate_reference_case` → `storage.load/_frozen/_validate_state` → `models.validate_schema` → installed `jsonschema` property/reference/item validation. Later progress and increasing CPU show that this dump did not terminate the suite. It is evidence of a slow validation interval, not itself a pytest failure or proof of a dead process. Those named legacy source/test paths are unchanged between base and initial candidate; performance causality beyond this observed stack is not established by that fact.

## Independently observed failure mechanisms

These observations were supplied by root's already-completed focused reproductions. This audit did not repeat them.

| Observation | Actual evidence and limit | Classification before full trace |
|---|---|---|
| Legacy `test_hre_assets.py::test_paths_reject_symlink` | The test tries to create its fixture link before calling `safe_path`; the separate local run raised Windows `WinError 1314` for unavailable symlink privilege. Production path assertion was not reached. Base/candidate test path is unchanged. | Host capability limitation for that reproduction. Match the final full traceback before attributing its row. |
| Legacy `test_hre_model_workers.py::test_failed_worker_records_one_attempt` | `unified_worker_timing_probe.txt`: **4 failed, 1 passed** in 2.43 s with the existing five parameters and `timeout=0.2`. Failures include `worker_timeout` instead of missing/invalid-response codes, and the timeout parameter's `attempts.txt` not being created. `run_worker` starts a real subprocess and counts the timeout across startup; it kills/waits on expiry and records the invocation. Both implementation and test are unchanged from base. | Reproduced local startup/deadline sensitivity; does not prove every full-suite worker failure has the same mechanism. The 200 ms fixture deadline is insufficient in the observed host conditions. |

No complete historical baseline suite was rerun by this audit. No numerical/model-quality result is inferred from synthetic transport or image fixtures.

## Final result and per-failure classification

The log reached 100% and wrote its final summary at **2026-11-02 00:10:41 +08:00**. The next inspection at 00:11:09 found the summary and no live PID 18344. The printed counts are **15 failed, 905 passed, 3 skipped, 178 subtests passed**, duration **3039.74 s**. The non-subtest outcomes sum to **923**; the quiet log does not print a separate collection total or skipped IDs, so neither is reconstructed as an additional observed pytest header.

| # | Failed test ID (under `engine/tests/`) | Actual failure in the full log | Classification |
|---|---|---|---|
| 1 | `test_hre_assets.py::test_paths_reject_symlink` | `pathlib.symlink_to` → `os.symlink`: `WinError 1314`, before the `safe_path` rejection assertion. | Host lacks fixture symlink privilege; not evidence that the path protection accepted a symlink. |
| 2 | `test_hre_evidence.py::test_bad_arrays_labels_and_bundle_paths_rejected` | Same `WinError 1314` creating `bundle/link.json` at line 138, after earlier array-label/path rejection checks. | Host fixture capability. The remaining symlink rejection cannot be evaluated by this run. |
| 3 | `test_hre_model_workers.py::test_failed_worker_records_one_attempt[print('failed',file=sys.stderr);sys.exit(7)\n-worker_exit_error]` | Expected `worker_exit_error`; observed `worker_timeout` at line 63, with `timeout=0.2`. | Existing fixture deadline/host startup interaction; independently reproduced mechanism, not a newly changed worker branch. |
| 4 | `test_hre_model_workers.py::test_failed_worker_records_one_attempt[pass\n-worker_response_missing]` | Expected missing response; observed timeout at line 63. | Same deadline mechanism. |
| 5 | `test_hre_model_workers.py::test_failed_worker_records_one_attempt[pathlib.Path(a.response).write_text('not json')\n-worker_response_invalid]` | Expected invalid JSON response; observed timeout at line 63. | Same deadline mechanism. |
| 6 | `test_hre_model_workers.py::test_failed_worker_records_one_attempt[pathlib.Path(a.response).write_text('[]')\n-worker_response_invalid]` | Expected invalid-object response; observed timeout at line 63. | Same deadline mechanism. |
| 7 | `test_hre_model_workers.py::test_failed_worker_records_one_attempt[time.sleep(5)\n-worker_timeout]` | Timeout code matched, but `attempts.txt` was absent at line 64. The child did not reach the fixture's initial marker write before being killed. | Same short-deadline fixture assumption; actual timeout handling occurred, but the marker expectation failed. |
| 8 | `test_hre_protocol.py::test_partial_response_and_symlink_done_do_not_advance` | Same `WinError 1314` at `done.symlink_to(part)`, line 92; earlier partial-response and pending-task assertions ran. | Host fixture capability; symlink-specific assertion was not reached. |
| 9 | `test_hre_protocol.py::test_quarantine_does_not_follow_rejected_submission_parent_symlink` | Same `WinError 1314` creating the external-parent fixture link at line 109. | Host fixture capability; quarantine link behavior was not exercised. |
| 10 | `test_hre_reference_ui.py::test_v2_panel_shows_unprobed_mask_without_enabling_control` | `ModuleNotFoundError: No module named 'streamlit'`, importing `streamlit.testing.v1.AppTest` at line 8. | Incomplete local dependency environment, before the UI was run. |
| 11 | `test_hre_ui.py::test_streamlit_renders_real_case_and_pause_resume` | Same missing import at line 17. | Same dependency gap. |
| 12 | `test_hre_ui.py::test_streamlit_analysis_displays_task_without_candidate_controls` | Same missing import at line 49. | Same dependency gap. |
| 13 | `test_hre_ui.py::test_streamlit_execution_exposes_extra_uploads_and_explicit_order_table` | Same missing import at line 76. | Same dependency gap. |
| 14 | `test_hre_ui.py::test_streamlit_explicit_new_generation_retry_after_failure_or_confirmed_release[True]` | Same missing import at line 87. | Same dependency gap. |
| 15 | `test_hre_ui.py::test_streamlit_explicit_new_generation_retry_after_failure_or_confirmed_release[False]` | Same missing import at line 87. | Same dependency gap. |

Totals by observed mechanism: **4 symlink-fixture privilege failures + 5 subprocess-deadline failures + 6 missing-Streamlit failures = 15**. No new unified reference/core/style/v3 functionality assertion appears in this run's failed-test list. This is a classification of the actual local failures, not a claim that the final source is fully tested or that the original complete suite passed elsewhere.

### Source and dependency comparison supporting those classifications

Read-only `git diff --exit-code 9073086 REF -- <listed paths>` returned exit 0 for each of `a836944`, `7eaec58`, and `32f1fa3`; blob identities were also inspected with `git rev-parse REF:PATH`. All six failed test files have identical Git blobs across these four snapshots:

| Test file | Identical blob |
|---|---|
| `test_hre_assets.py` | `67f53d247a02f5aada6abbd7e5fee38a754a04ed` |
| `test_hre_evidence.py` | `12d4d723077a358bbce3f2c7134295ad16dc99f0` |
| `test_hre_model_workers.py` | `8016360904c42bcc89c3ee6427078773e5cd2e3c` |
| `test_hre_protocol.py` | `9f06c4cdadce1e573b32c5044742566ba99f5a9b` |
| `test_hre_reference_ui.py` | `d0343d82d2f3dece08d14c470e8c2453d5b51784` |
| `test_hre_ui.py` | `cf592e5bbf38538f5b4ad35eef05b7a3d2a1c4e1` |

The relevant production files `model_workers.py`, `models.py`, `paths.py`, `assets.py`, `evidence.py`, `protocol.py`, `workflow.py`, and `ui.py` also have identical blobs across these snapshots. This identity is corroborating evidence; the classifications principally follow the actual failing operation:

- All four symlink failures originate in the test fixture's Windows `os.symlink` call, not a changed production rejection path.
- Worker fixtures launch the same Python executable with a temporary script whose imports are `argparse,json,pathlib,sys,time`; its 200 ms allowance includes process startup. The production timeout path kills/waits and reports `worker_timeout`. The standalone old test's 4-fail/1-pass result, compared with this broad run's 5 failures, shows timing variability in the observed host environment. A controlled historical-environment run was not performed, so no claim is made that these tests universally failed before this change.
- Streamlit was already a required dependency (`streamlit>=1.30`) in base `engine/pyproject.toml`; the base-to-current metadata diff changes version 0.3.0 to 0.4.0, not that dependency. The inspected installed engine is 0.4.0, while `importlib.util.find_spec('streamlit')` returns `None`. Six tests fail at that import before any application execution. This is an environment gap, not evidence about whether the Streamlit UI itself behaves correctly once installed. The audit did not install packages or rerun those tests.

The watchdog's legacy `reference_runtime.py`, `reference_experiments.py`, `storage.py`, `models.py`, and `test_hre_reference_feedback.py` likewise have identical blobs. Its named test is absent from the failure list and is printed as the slowest call at **133.73 s**. Other printed long calls include 91.49 s and 89.80 s in that legacy feedback suite. The trace establishes slow schema validation during this run; it does not isolate a new performance regression, a historical package-version effect, or a general runtime bound.

### Local evidence identities

- Complete run log: `C:\Users\Lenovo\Documents\ChatGPT\RefHarnessIR\unified_full_engine_tests.txt`, **31,668 bytes**, SHA256 `df7dffd510a16e075545bab9253d80ad01318fed3e649aa23d433e9e6d82a76b`.
- Standalone old-worker timing probe: `C:\Users\Lenovo\Documents\ChatGPT\RefHarnessIR\unified_worker_timing_probe.txt`, SHA256 `b92cd2e65c2e630e637d1c85aaa82b81a3bf772b50ccd0b458b9f74dde5ad039`.
- Source equality can be reproduced read-only with `git rev-parse 9073086:engine/tests/test_hre_model_workers.py` (and each listed path/ref); inspect the full log's traceback section and `--durations=12` output for actual assertions and timings.

This agent changed only this document, made no commit/push, did not rerun any test or terminate any process, and did not perform model/API/GPU work. Synthetic transport/image fixtures are software evidence only. Remote CI and final-snapshot repair checks must be reported independently by their owner; neither can turn the recorded local result into a full green result.

## Post-run environment follow-up (root-owned)

After the broad run completed, root installed lock-file-declared `streamlit==1.65.0` successfully (log `C:\Users\Lenovo\Documents\ChatGPT\RefHarnessIR\unified_streamlit_install.txt`). The separate command below covers the affected UI file plus the reference-panel test, including additional non-Streamlit checks:

```powershell
& .venv/Scripts/python.exe -m pytest engine/tests/test_hre_ui.py engine/tests/test_hre_reference_ui.py::test_v2_panel_shows_unprobed_mask_without_enabling_control -q
```

Actual post-install result: **10 passed, 3 failed in 59.70 s**. The missing imports were resolved. All three failures now show `RuntimeError: AppTest script run timed out after 3(s)` in the unchanged tests' default AppTest window; they are pause/resume and the two retry variants. This result is separate from the original full run, and is not relabeled as green.

Root then ran the archived [UI host-timing probe](reviews/probe_ui_host_timeout.py), using the public `AppTest.run(timeout=30)` argument on every real UI interaction, no runtime production patches. Actual temporary synthetic case state and budget assertions passed for pause/resume, submitted-failure retry, and confirmed-never-submitted retry. All three scenarios passed, exit 0; [JSON output](reviews/probe_ui_host_timeout_output.json). This demonstrates those state transitions under the explicit host window, not three-second responsiveness or model quality. Production and legacy test source stayed unchanged.

The final source's Linux complete CI and Linux/Windows focused CI all passed on published code commit `bd25c7a853c73945b17cfa75a569a8e6d45f0eb8`; see [VALIDATION.md](VALIDATION.md). Those clean remote results do not rewrite the original **15 failed / 905 passed** local result.
