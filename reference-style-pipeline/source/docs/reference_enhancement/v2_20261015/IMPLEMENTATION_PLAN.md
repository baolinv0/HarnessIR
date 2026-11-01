# Generative reference enhancement v2 implementation plan

> **For agentic workers:** use superpowers:executing-plans; implement in this session, then obtain a fresh code review before submission.

**Goal:** execute G0/G1 and capability-gated G2 using the existing audited Controller, and measure frozen independent A/B/C regions without treating B as pixel GT.

**Architecture:** an explicit `ref_enhance_v2` configuration extension and transport manifest compose with the unchanged v1 task/state schemas. CaseStore remains the only workflow state. Metrics and independent experiment review remain offline projections, never automatic retry inputs.

**Tech stack:** Python, existing Pillow/NumPy/JSON Schema/Jinja/Streamlit; no external model API or new inference dependencies.

**Spec:** DESIGN.md, EXPERIMENT_PLAN.md, IMPLEMENTATION_CHECKLIST.md in this directory.

## Global constraints

- G0/G1 editor inputs: exactly A.png, B.png, edit_prompt.txt.
- G0/G1/G2: one generation per case and arm; preserve original raw outputs.
- G2 uses the same executor/settings and exact rendered G1 prompt, with a verified mask transport.
- Separate native mask parameter from separate image soft guidance; no colored overlays.
- Independent A/B coordinates, frozen annotations, no warp/crop or color rollback.
- No real R1/R2 or mask capability claim without actual input/output and delivery evidence.
- User requested review before submission: collect changes locally; commit/push only after review and checks.

## Review focus

- Changed executor/version/settings invalidate a mask probe or paired G1 comparison.
- Wrong A/B roles, inverse mask semantics, malformed or empty arrays fail closed.
- Changed frozen files and resumed/duplicate imports retain the existing integrity and budget rules.
- Failed/unknown content or geometry yields no interpretable ROI improvement.
- Missing candidates, missing/disagreeing independent reviews stay in ITT and cannot become successes.

### Task 1: explicit contracts, masks and frozen capability proof

Files: reference_contracts.py, masks.py; opt-in hooks in assets.py/storage.py/capabilities.py/evidence.py.

Interfaces: `prepare_reference_config(root, config, inputs)`, `validate_mask(root, contract, asset)`, `validate_mask_probe(root, proof, executor)`.

- [x] Write failing tests for mask encoding/source/shape, strict contracts and executor drift.
- [x] Implement binary allow_edit masks, explicit adapter encoding and provenance, three observed probe cases and their real artifacts.
- [x] Verify targeted tests and v1 regressions.

### Task 2: frozen ROI evaluator

Files: reference_evaluator.py, additive stats/roi helpers.

Interface: `evaluate_reference(A,B,C,roi_pairs,case_root,geometry_status,content_status,eval_mask,task_scope)` returns per-ROI attributes and spill.

- [x] Write tests for three RGB fixtures, independent geometry, empty/unreliable regions and near-zero distance.
- [x] Implement L*/a*/b*, display quantiles/clipping, before/after/delta, and matched G1/G2 spill.
- [x] Verify targeted tests; no cross-attribute aggregate or automatic selection.

### Task 3: integrate prompts, delivery and Controller

Files: workflow.py/prompts.py/desktop.py plus v2 resources and CLI.

Interfaces: `capture_g1_prompt(root)`, v2 execute delivery manifest, `validate_mask_delivery(root,request,metadata)`.

- [x] Write integration failures for unsupported G2, mismatched G1 text, changed settings, missing delivery proof and over-budget output.
- [x] Implement v2 template snapshots, concise supported targets, paired G1 snapshot, G2 export/import gate without a second state store.
- [x] Run synthetic end-to-end G0/G1 and conditional fixture-only G2; mark all fixtures non-model evidence.

### Task 4: experiments, UI and operational handoff

Files: reference_experiments.py, CLI/UI, packaged v2 profiles/schemas, runbook/examples.

Interfaces: `freeze_reference_run`, `export_reference_blind`, `summarize_reference_run`.

- [x] Write tests for planned/skipped rows, immutable inputs, neutral anonymous exports, unresolved reviews and paired executor identity.
- [x] Implement frozen randomized one-shot arms, ITT/win-tie-loss/reasons/costs and conservative GO/PROBE/STOP recommendations.
- [x] Verify CLI/UI, installed wheel and old design contracts; write honest implementation/real-experiment status.

### Task 5: review, repairs and submission

- [x] Run full suite, compile and packaging checks, and review the complete diff against v2 requirements.
- [x] Obtain independent reviewer findings; fix blocking issues with regression tests.
- [x] Commit and publish an implementation PR based on PR #3, without merging main or overwriting its divergent engine.

## Execution record

All implementation tasks and independent-review repairs are complete. Final verification: 348 tests passed (50 new), 181 static design checks passed, installed wheel and synthetic end-to-end smoke passed. No real R0/R1/R2/R3 or production Mask capability was established. See REVIEW_AND_VALIDATION.md for findings and measured limits. Submission targets a new implementation branch based on PR #3; no main merge is included.

Source snapshot: PR #3 `c94a4001e5250fd257e8954b56b72ca9c4725409`. GitHub connector recovered exact text files because direct git access was unavailable; remote submission will reuse the original tree so binary assets remain untouched.

Local implementation and test fixtures are not real image model experiments. R1/R2 require the user's actual A/B pairs and externally observed editor outputs.
