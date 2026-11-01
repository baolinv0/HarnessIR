# Unified Reference Implementation Plan

> **For agentic workers:** Use subagent-driven-development. Execute the checked tasks against docs/reference_unified/CONTRACT.md. The user has authorized design synthesis, implementation, independent review/repair and GitHub publication; proceed without another design approval round.

**Goal:** Integrate the strongest contracts and evidence mechanisms from both reviewed branches into one executable, reviewable engine.

**Architecture:** Keep v3 and workbench state machines with explicit v2/v3 routes. Add shared pure reference_core rules, the audited reference_style package, holistic evaluation and frozen studies. Preserve all historical schemas and input identities.

**Tech Stack:** Python 3.10+, existing Pillow/NumPy/jsonschema, stdlib HTTP/CLI, existing JS UI, pytest/unittest, setuptools, GitHub Actions.

## Ownership and sequence

Root owns reference_style port/extensions, holistic evaluator, study/report protocol, CLI dispatch, CI, docs and publication. Execution Agent owns reference_core pure rules, v3 v2 route/runner/audits/evidence review/feedback/review, workbench delivery_v3/API/UI integration and their tests. Do not edit the other owner's files without coordination. Both work in the same checkout; never revert another agent's changes. A fresh read-only reviewer evaluates frozen contract compliance first, then implementation quality. Repairs are limited to reported in-scope failures and re-reviewed.

## Shared API (implement these exact signatures)

Package engine/src/hre/reference_core/. All functions raise ValueError or HREError on malformed input, reject bool-as-int sizes and nonfinite data, and do not perform model/network calls.

```python
DIMENSIONS = frozenset({"neutral_balance", "chroma_by_hue", "skin_rendering",
    "shadow_midtone_highlight", "highlight_transition", "local_contrast",
    "subject_background_balance", "texture_and_noise_observation"})

# contracts.py: canonical operator/model semantics, not automatic visual truth.
def validate_semantics(spec: dict) -> dict: ...
# spec: {coverage:[{attribute,status,reason,target_ids}], targets:[
# {target_id,attribute,source_observation,reference_observation,comparability,
# uncertainty,mandatory,acceptance_criterion}], delivery_requirements:dict}
# Extra binding identifiers may live in enclosing records, not spec.
# Coverage states: targeted/preserve/already_satisfied/uncertain/not_applicable/excluded.
# Preserve/excluded/unknown rows have no target IDs. Targeted rows exactly cover targets
# with matching attributes. Only comparable/conditional targets are executable.

# rendering.py: deterministic text preserving limits, with no private policy.
def render_target_limits(target: dict) -> str: ...
# Accept target_id or legacy id, and attribute/comparability/uncertainty/mandatory/
# acceptance_criterion. Render all supplied source/reference facts and restrictions.

# delivery.py: final and pre-execution native-content checks, never scaled previews.
def assess_delivery(source_size, native_size, requirements, *, detail="uncertain",
                    geometry_valid=True) -> dict: ...
def preflight(source_size, planned_size, requirements, *, capability_known=True) -> dict: ...
# Results include status, minimum_native_size and pass; preflight status is
# feasible/infeasible/unknown. require_native_source_resolution defaults true,
# require_detail_pass defaults false. minimum_native_size is optional [w,h].
```

The execution Agent may add focused helpers/modules. Root depends only on these frozen APIs. It must not introduce imports from reference_style into historical validators at module import time.

## Task 1 — Reproducible base and imported evidence

Files: engine/src/hre/reference_style/*.py, engine/tests/reference_style/*.py, engine/src/hre/cli.py, docs/reference_unified/PROVENANCE.md.

- [x] Copy only reference_style code/tests from 6adfd0b; put required pure color.py in that package and update its imports. Record original file hashes/attribution.
- [x] Reproduce Windows CRLF/default-encoding and str(relative_path) failures; persist paths with as_posix and test exact bytes with write_bytes or explicit UTF-8/newline. Capability-skip only Windows symlink creation when OS denies it.
- [x] Fix major-damage precedence while preserving unknown calibration as a separate blocked-success state. Add known-major-without-calibration regression.
- [x] Dispatch hre reference-style before old CLI parser; retain hre models and workbench entry points.
- [x] Run unittest discover -s engine/tests/reference_style -v and CLI help against the integrated installed package. No runtime monkeypatches in acceptance evidence.

## Task 2 — Shared semantics, limits and native delivery

Files: engine/src/hre/reference_core/{__init__,contracts,rendering,delivery}.py; engine/tests/test_reference_core.py.

- [x] Test complete eight-row semantics, missing/duplicate coverage, wrong attribute references, omitted success criterion, unknown/incomparable edit targets and conditional missing uncertainty.
- [x] Implement the exact shared API above. New state may reference these immutable records; old schema stays unchanged.
- [x] Test text contains the actual conditional limitation, mandatory flag, independent facts and success criterion. Verify private-policy text is never an input.
- [x] Test native 32x32 vs source64x64 fails despite preview64x64; no-op A checks its own size; planned32x32 preflight fails before any generation; capability unknown stays unknown.

## Task 3 — v3 reference_retouch_v2 execution

Files: new engine/src/hre/v3/reference_retouch_v2.py and focused review/audit helpers; modify contracts.py, stages.py, runner.py, common.py, dispatch.py, batch.py, cli.py/report.py only at versioned boundaries; tests/test_v3_reference_v2*.py.

- [x] Add one explicit version selector; route task validation, stage schema/template, validate_intent, frozen_contract, shared planning, native request rendering and compiler validation through it. Old v1 output/request hashes remain unchanged.
- [x] Implement evidence_review stage binding original diagnosis+fresh evidence. Compose reads effective diagnosis. A needs_evidence diagnosis cannot become ready merely because statistics were collected.
- [x] Render target limits with shared helper; save actual condition spans/JSON locations. Bind semantic audit to actual condition hash and block missing/contradictory/uncertain mandatory constraints. Deterministic direct rendering uses explicit structural audit; native rewrites require a real configured/injected audit judgement or pending review.
- [x] Use normalized scoped feedback rather than duplicated issues suggestions. Freeze factual goals. Enforce pending-review/stop-before-refine ordering; no-op and delivery preflight precede compiler/image calls.
- [x] Add CLI same-candidate review import with exact predecessor and immutable candidate binding; no generation on review. Preserve unknown-submission reconciliation.
- [x] Verify new batch arms activate v2 while old arms remain exact legacy. Add negative cross-version shared import tests.

## Task 4 — Workbench delivery_v3

Files: engine/src/hre/retouch/{contracts,workflow,prompts,server}.py and static/{app.js,style.css} as needed; tests/test_retouch_unified*.py.

- [x] New cases can explicitly choose delivery_v3; delivery_v2/historical cases retain their contracts. UI exposes version, declared working/native delivery mode and preflight result.
- [x] Add evidence review, effective diagnosis, shared limitation rendering, normalized feedback and explicit same-candidate re-review. Interface unavailability stays visible; exports/manual imports remain usable.
- [x] Preserve original input snapshots before optional work canvas; no-op skips editor canvas capability constraints. Preflight blocks known infeasible calls and preserves budget counters.
- [x] Use strict audited encoding for new cases, record raw and selected C identity, never treat assumed source encoding as formal numeric eligibility. Candidate regional measurements require genuine C support or explicit reviewed mapping; otherwise unavailable.
- [x] Keep real ordered two-image API multipart and no implicit retries; local HTTP tests inspect actual transmitted roles, prompt, legal settings, raw receipts and budget recovery.

## Task 5 — Unified style semantics and whole-image-first evaluator

Files: engine/src/hre/reference_style/unified.py; engine/src/hre/reference_core/evaluation.py; style CLI; tests/reference_style/test_unified.py and tests/test_reference_evaluation.py.

- [x] Add semantic-freeze (uN) record binding existing target hash and shared semantics. Exact target coverage mandatory; limits and endpoint state reach actual edit text. Existing v6 records remain readable without silent migration.
- [x] Add delivery preflight and supported no-edit terminal for new unified records. Verify successful A export has no image/compiler attempts; failed fallback never masquerades as no-op.
- [x] Evaluation stages are whole_image → whole_regions → explanations. Record immutable A/B/C/display hashes, size/viewing method, reviewer exposure and independence. Closed whole-image axes are tone/color/brightness/lighting_naturalness/material_relationships/processing_appearance; A preservation is independent.
- [x] Each observation records relation to B (closer/same/farther/uncertain), direction, magnitude (none/slight/moderate/large/unknown), confidence and evidence. Rank comparisons cannot force a winner or imply statistical equivalence.
- [x] Explanatory numbers cannot overwrite whole-image observations. Conflicts remain explicit; no weighted score or posthoc cancellation. Policy/tolerated-history is absent from edit material.

## Task 6 — Frozen study, ratings and one-file report

Files: engine/src/hre/reference_core/study.py plus CLI and tests/test_reference_study.py; engine/examples/reference_unified/.

- [x] Build six exact arms from versioned task specs. Use common frozen offline evaluation and baseline records outside runtime contexts. Distinguish source_native and declared_working_size with locked geometry.
- [x] Freeze each planned pair/model/arm/repeat identity and inputs/config/contract hashes. Emit runnable v3 task files for each arm; source-only arm strips reference/B-derived brief, regions/planning/cache/evaluator data before creation.
- [x] Import actual ratings by planned run/candidate/evaluation identities; require complete target/protection fields and disclosure. Adjudications append and bind prior conflicting ratings; not an override of old bytes.
- [x] Export all planned rows including not-run/pending/failed, G/S/B/X/P outcome roles, task and edit success true/false/unknown. An already-satisfied A is task success, not an effective edit; failed fallback never success. Denominators use pre-frozen baseline, unknowns stay unknown; report confirmed bounds without silently dropping rows.
- [x] CLI supports study-build, study-rate, study-adjudicate, study-report with --help/examples and relative config paths. Do not generate simulated quality results for real planned rows.

## Task 7 — Review, validation and publication

Files: docs/reference_unified/{RUNBOOK,IMPLEMENTATION_REPORT,REVIEW}.md; .github/workflows/; README links; package metadata/examples.

- [ ] Map R1-R12 to code/test commands and evidence. Run old95 focused tests, all new tests, imported175 style regressions, relevant runtime/batch/provider tests, JS syntax, CLI, wheel build/content checks and diff check. Run broader CPU tests once and record platform limitations separately.
- [x] CI matrix Linux/Windows with UTF-8, exact-byte fixtures and narrowly capability-skipped symlink creation. Include smoke import checks showing one hre package.
- [x] Assign fresh read-only reviewer frozen contract+diff+reports. First require requirement compliance; then request correctness/compatibility review. Implementer repairs listed blockers, reviewer verifies fixes; iterate until no in-scope blocker remains.
- [ ] Check scoped publication files exclude private images/masks/runs/credentials. Commit implementation and truthful reports; push codex/reference-unified-20261101; create PR against codex/reference-retouch-contract-20261026 and attach it to this chat. Verify remote SHA and PR file list; report real CI status without implying completion when pending.

## Local commands and evidence policy

Use existing .venv/Scripts/python.exe on Windows with PYTHONPATH=engine/src, PYTHONUTF8=1 and PYTHONDONTWRITEBYTECODE=1. Tests use actual temporary synthetic images and local HTTP, never real remote generation. Baseline old95 was green before edits; imported175 had known Windows issues to fix. Record those known baseline failures rather than requesting redundant permission to repair them.

```powershell
$env:PYTHONPATH=(Resolve-Path engine/src).Path
$env:PYTHONUTF8='1'
$env:PYTHONDONTWRITEBYTECODE='1'
& .venv/Scripts/python.exe -m pytest engine/tests/test_retouch_delivery.py engine/tests/test_v3_reference_runner.py engine/tests/test_v3_reference_contract.py -q
& .venv/Scripts/python.exe -m unittest discover -s engine/tests/reference_style -v
& .venv/Scripts/python.exe -m hre reference-style --help
& .venv/Scripts/python.exe -m hre models --help
```
