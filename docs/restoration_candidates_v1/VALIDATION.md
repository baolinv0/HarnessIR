# CPU implementation validation

The current implementation includes the second-review fixes described in FIX_REVIEW_V2.md. CPU verification covers orchestration, contracts, failure recovery, selection, offline analysis and packaging. Native GPU execution and model quality remain unverified. Earlier passing tests did not cover R1 through R4; the new regressions and evidence below supersede the earlier unconditional handoff assessment.

## Recorded results

Validation ran on Windows with Python 3.12.13 on 2026-11-17. `validation/cpu_results.json` records test counts and artifact hashes.

| Check | Result | Evidence in the development workspace |
| --- | --- | --- |
| Candidate-related tests after R1-R4 fixes | 145 passed, 1 skipped, no failures or errors | `artifacts/final-publish/candidates-tests.xml` |
| Targeted legacy tests | 121 passed, 4 platform failures | `artifacts/legacy-targeted-tests.xml` |
| The same four tests on the unchanged pinned baseline | All four failures reproduced | `artifacts/baseline-platform-tests.xml` |
| Final wheel installed into a separate directory | Public CLI fixture, run, J0, J2, report and resume passed | `artifacts/delivery/installed_smoke.json` |
| Installed package identity | Installed `hre/` files match the final wheel bytes | `validation/installed_smoke.json` |
| A/B execution and strict geometry | Seven unique generation records; 65 by 49 input delivered as 260 by 196 | `validation/installed_smoke.json` |
| Resume | Operation journal bytes unchanged; no new operations | `validation/installed_smoke.json` |
| Modified selected anonymous image | Installed CLI rejects resume with output_modified; no new operations | `validation/installed_smoke.json` |

The skipped candidate test needs Windows symlink creation permission. Two legacy failures have the same permission limitation. The other two compare normalized Windows paths against POSIX path strings. These four failures reproduce on baseline `d44d40fa209a9978d37ce38efa9a6ef89abe7432`. They do not demonstrate a new candidate regression. A full legacy suite run was interrupted and is not reported as completed.

The workspace test helper supplies test-only dependencies and adjusts restrictive temporary-directory creation within this Windows sandbox. Production code does not carry that workaround. Fixture generation uses synthetic interpolation and transforms. Fixture reviews are synthetic responses. Neither provides model-quality evidence.

## Independent code review and accepted repairs

The second review identified four additional defects despite the earlier green suite. R1 fixed E2 registered denominators. R2 validates all referenced completed files before reuse. R3 requires actual hard-contract success in both Oracle report paths. R4 preserves legal other-domain observations and explicit target applicability. See FIX_REVIEW_V2.md and the RED/GREEN records in `validation/cpu_results.json`.

Two fresh agents reviewed separate code areas. They used the available model family. This was not a cross-vendor review.

| Finding | Implemented correction | Regression coverage |
| --- | --- | --- |
| Final aggregate assessments could fail to affect eligibility | Aggregate coverage and verdicts now participate in mandatory qualification | `test_candidates_judge.py` aggregate and missing-assessment tests |
| J2 roles were insufficiently explicit | Each request contains its person, text, technical or normal-viewing responsibility | `test_expert_role_instructions_are_explicit_in_requests` |
| Optional repair reserves could block a sufficient primary-only budget | Reserve only remaining optional capacity | `test_primary_only_budget_can_complete_without_optional_repair` |
| Exact duplicate outputs were not recorded | Preserve every slot and call; add pixel identity and duplicate metadata | `test_candidates_runtime.py` workflow coverage |
| Re-sealing modified F0 could bypass an internal seal | Compare against the original case anchor before journal access and execution | `test_reopened_case_rejects_resealed_f0_against_original_anchor` |
| A deployment manifest could change between candidates | Freeze external manifest bytes at F0; check before each execution; freeze all alternative requests before submission | `test_deployment_file_change_after_c0_prevents_alternative_submission` |
| Reconciliation could leave a recovered Judge run stuck | Reopen only a resolved unknown workflow; replay saved operations; support both pools | `test_reconciled_judge_result_is_consumed_by_resume_without_new_calls` |
| An old wheel could be packaged beside newer source | Build and verification compare exact package file lists and bytes | `test_candidates_bundle.py` stale-wheel regression |

## Reproduce the checks

On a compatible Python environment with dependencies installed, use the source tree from the archive:

```bash
export PYTHONPATH="$PWD/engine/src"
python -m pytest engine/tests -q -k candidates
python -m hre candidates fixture --out /srv/runs/new-cpu-fixture
python -m hre candidates run --case-root /srv/runs/new-cpu-fixture/case
python -m hre candidates judge --case-root /srv/runs/new-cpu-fixture/case --variant J2
python -m hre candidates resume --case-root /srv/runs/new-cpu-fixture/case
python -m hre candidates report --case-root /srv/runs/new-cpu-fixture/case
```

Run `python tools/build_candidates_bundle.py --verify PATH_TO_ARCHIVE` to verify the archive manifest, every file hash, source identity and wheel/source agreement. Its adjacent `.zip.sha256` binds the archive bytes. The archive carries source and the pure Python application wheel. Platform dependency wheels, CUDA libraries and model weights are not included.

## Remaining execution gates

Follow RUNBOOK.md on the GPU computer. Supply target-compatible offline dependencies, local checkpoints, exact revisions and actual local VLM endpoints. Run real preflight, then separate x1 and odd-size x4 smoke cases. Confirm native canvas support, frozen prompts, source hashes, receipts and VLM image/JSON capacity before any experiment.

Pilot and held-out experiments, human Oracle labels, same-seed E2 effect annotations, and scientific improvement claims remain pending. Optional OCR, landmarks or quality metrics remain explicitly missing when unavailable. Required content verification can legitimately leave selection unresolved. Do not relax it to obtain a winner.

## Final publication validation

The remaining Best-in-pool annotation-availability defect is fixed. Both single and batch paths report null with a missing annotation when raw best labels conflict with accepted outputs. Oracle Pass and Selected Pass are retained. The new regression matrix ran RED before the repair, and an independent reviewer ran 38 tests successfully. The complete candidate suite has 145 passed and 1 Windows symlink-permission skip. See validation/final_review.md and cpu_results.json. Installed CLI evidence records a fresh wheel and includes modified-output rejection without another call. Public evidence replaces local workspace paths with $WORKSPACE; original artifact hashes are retained. Real GPU execution and experiment quality remain unverified.
