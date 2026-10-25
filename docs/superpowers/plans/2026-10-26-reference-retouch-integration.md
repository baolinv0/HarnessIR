# Reference Retouch Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Integrate the tested reference-retouch workflow into HarnessIR, enforce attributable per-target acceptance and a zero-generation already-satisfied path, and publish a reviewed GitHub branch/PR.

**Architecture:** Keep legacy v3 task/template/request semantics unchanged. An explicit `workflow_contract=reference_retouch_v1` selects strict reference diagnosis, target and verification contracts on the existing runner and native compiler boundaries. Include the previously implemented GPT Image workbench as a runnable, inspectable single-editor path; preserve unknown backend identities and independent native-delivery checks.

**Tech Stack:** Existing Python/Pillow/jsonschema/numpy, stdlib HTTP workbench, static JavaScript, pytest/unittest; no image generation dependency added to imports.

**Spec:** `docs/reference_retouch/GOALS.md`, `DESIGN.md`, and completed observations in `CASE_EXPERIMENT.md`. User authorized implementation and GitHub publication on 2026-10-26.

## Global Constraints

- A defines content, identity, text, geometry and framing. B supplies only supported photographic appearance.
- Every refinement uses the original A+B. No hidden retries or changed acceptance thresholds.
- Missing evidence is uncertainty, not a fabricated measurement. Native and delivered files are distinct.
- Opt-in only: preserve existing v3 schemas/templates and old request hashes. No migration of historical cases.
- Keep personal images, run directories, credentials and local configuration out of GitHub.
- Unknown tool backends do not count as identified GPT Image 2 or four-model quality experiments.

## Review Focus

- Self-reference already satisfied must return canonical A without compiler or image calls; unresolved evidence cannot take that success path.
- Duplicate/missing targets and incomplete content/artifact checks must not be accepted.
- Refinement and imported shared planning cannot change the frozen evaluation contract or cross workflow versions.
- Appearance acceptance cannot hide native-resolution or required-detail delivery failure.
- Old template/request identities and interrupted-submission recovery remain compatible.

### Task 1: Versioned reference contract

**Files:** Create `engine/src/hre/v3/reference_retouch.py`, `engine/tests/test_v3_reference_contract.py`.

**Interfaces:** `enabled`, `validate_spec`, `validate_intent`, `validate_payload`, `frozen_contract`, `stage_instruction`, `SCHEMAS`, `VERSION`, `TEMPLATE_VERSION`. Existing v3-like intent keys remain renderable; reference observations, deltas, comparability, coverage and success criteria are added in the new version only.

- [x] Write failing tests for evidence/goal traceability, all eight appearance dimensions, exact verifier coverage and immutable feedback goals.
- [x] Run focused tests, implement strict schemas and cross-field rules, rerun to green.

### Task 2: Existing runner and compiler integration

**Files:** Modify `v3/contracts.py`, `stages.py`, `runner.py`, `common.py`, `dispatch.py`, `batch.py`; create `engine/tests/test_v3_reference_runner.py`.

**Interfaces:** New tasks freeze a `reference_contract` artifact derived from composition; verification receives that contract and evidence, not the execution prompt/model. Requests and shared planning bind the new workflow version. Existing tasks omit every new field.

- [x] Add failing runner tests for already-satisfied, insufficient evidence, mandatory/optional outcomes, native-delivery failure, frozen feedback, cross-version shared import and unchanged old stage requests.
- [x] Route new stage templates/validation; persist the contract, correctly stop before compilation, add separate delivery checks and acceptance gates, and render all frozen attributes into compiler input.
- [x] Run focused new and existing v3 tests, resolving failures without changing old schemas.

### Task 3: Runnable workbench, visualization and revised scheme

**Files:** Add existing `engine/src/hre/retouch/`, existing `engine/tests/test_retouch*.py`, `RETOUCH_WORKBENCH.md`; modify `v3/report.py`, `README.md`, `REFERENCE_ENHANCEMENT.md`, `docs/four_model_v3/DESIGN_AND_COMPLETION.md`; add sanitized docs under `docs/reference_retouch/` and a runnable example task.

- [x] Package the existing workbench and preserve its full A/B/target/verification visualization and manual/API provenance.
- [x] Expose reference contract, diagnosis/evidence, actual compiled conditions, per-target verification and delivery status in the original v3 report.
- [x] Correct portable links and document commands, limits, experiment findings and the remaining actual-model/cross-scene validation boundary.
- [x] Run all engine tests and JS syntax checks; run a real-photo zero-generation/no-change case and negative verifier controls through the production contract/runner, explicitly marked Agent-assisted rather than automatic diagnosis.

### Task 4: Review and GitHub delivery

- [x] Review final diff for correctness, compatibility, secrets and accidental data inclusion; obtain a fresh read-only reviewer and repair reproducible blockers.
- [ ] Commit only code/tests/docs/example metadata; push `codex/reference-retouch-contract-20261026`, create a PR against `implementation/four-model-completion-20261024`, and attach the PR to this chat.
- [ ] Verify remote head and published PR contents; report exact validation, remaining quality limitations and usable links.

## Execution record

Baseline: `7ecc32cebd54503f2924f9062a5a1c708f37deba`. Complete repository cloned into the task workspace; existing source snapshot and historical runs are retained separately. Parallel ownership: contract module/tests by worker, integration/report/docs by root. The user has explicitly authorized completing all steps; no additional design approval is pending.
