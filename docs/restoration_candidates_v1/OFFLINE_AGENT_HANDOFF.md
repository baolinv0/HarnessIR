# Debug the transferred candidates code

You are debugging the approved restoration candidates implementation on an offline GPU computer. Preserve frozen requests, original LQ provenance, strict native geometry, call budgets and evidence-based qualification. Fix software defects without claiming restoration quality from fixtures.

## Start with evidence

1. Read `RUNBOOK.md`, `BUILD_PLAN.md` and the failure's structured CLI output.
2. Verify the ZIP with `python tools/build_candidates_bundle.py --verify ARCHIVE.zip`.
3. Set `PYTHONPATH=engine/src`, run the CPU fixture, then `python -m pytest engine/tests -q -k candidates`.
4. Run real preflight against the actual local configuration. Record Python/package versions, GPU visibility, deployment revision and failed checks without printing API keys.
5. Reproduce the smallest failure in a new case. Preserve the failing case and operation receipts.

## Repair one owned domain at a time

| Domain | Files | Verification |
|---|---|---|
| Input/config/freeze | `contracts.py` | contracts tests; unknown fields and changed hashes rejected |
| Requests, native geometry, old stage bridge | `bridge.py` | bridge tests; odd x1/x4 and zero calls on manifest mutation |
| HTTP model boundary | `transport.py` | transport tests; no hidden retries, no credential persistence |
| Operation recovery | `journal.py` | journal tests; completed/failed replay and unknown reconciliation |
| Issue, IR, rewrite, audit, fallback | `planner.py` | planner tests; F/T/FT dependencies, protected requirements and seeds |
| Source/candidate/ROI evidence | `evidence.py` | evidence tests; hashes, fixed coordinates, anonymous transport artifacts |
| Package coverage and qualification | `judge.py` | judge tests; required unknown/missing cannot become eligible |
| Workflow and CLI | `runtime.py`, `cli.py` | runtime tests and actual fixture create/run/resume/report |
| Offline labels and metrics | `report.py`, `study.py`, `analysis.py` | runtime/study/analysis tests; GT cannot alter online selection |
| Transfer artifacts | `tools/build_candidates_bundle.py` | bundle tests; manifest hashes and forbidden file checks |

Application files are below `engine/src/hre/candidates/`. Do not change legacy `harness/`, `hre/sr/`, v3 spatial delivery or legacy selectors to repair the new workflow. Escalate a required legacy behavior change as a separate issue.

## Recognize expected failures

- `blocked` preflight usually requires correcting an actual deployment path, revision, source manifest, missing dependency or endpoint. Do not substitute a different model.
- `execution_manifest_mismatch`, `freeze_modified`, `source_modified` or `output_modified` means frozen identity changed. Preserve the record and locate the mutation. Do not reseal altered inputs to silence the check.
- `external_config_modified` means a deployment or source-identity manifest changed after F0. All candidates must share the same frozen deployment. Prepare a fresh case after intentionally changing deployment; never accept different per-slot deployment hashes.
- `operation_unknown` means a remote call may have executed. Reconcile using provider or worker proof. Never retry it automatically.
- `confirmed_not_executed` remains a recorded failure and does not restore a spent image-call allowance.
- `unresolved` selection is a supported outcome. Do not choose the highest sharpness score or relax verified-content requirements to force a result.
- Real mode cannot fall back to fixture mode. An explicit fixture run is only a separate software diagnostic.
- A wrong native x4 size is not fixed by resizing. Check padding, requested canvas and native adapter capability.
- No internet means no implicit weight download. Preload dependencies and checkpoints and retain offline flags.

## Make the smallest reviewable fix

Add a failing regression test for the observed defect. Change only its owning module. Run that module's tests, then all `test_candidates_*.py`, then repeat the real failing operation in a fresh case when a new request is needed. A legitimate repair operation inside an existing case must follow its frozen budget and attempt rules.

If a local dependency import fails, fix the environment before editing the algorithm. If the local VLM cannot follow a large JSON contract, preserve the raw response and diagnose token/image capacity. Do not remove required checks, GT isolation, protected attributes, semantic audit or hash validation.

## Return this repair record

- Error code, minimal input conditions, exact command and case ID.
- Python/package/GPU versions and checkpoint revision.
- Changed file diff and added regression test.
- Test summary and real smoke result, with separate labels for CPU fixture and real model observations.
- Bound request/response/receipt hashes, unresolved operations and costs that remain unknown.
- Any unsupported canvas or VLM contract behavior that requires a research decision rather than a software patch.

Do not include API key values, private input images or model weights in the source ZIP. Keep those on the execution computer and reference local hashes in the repair record.
