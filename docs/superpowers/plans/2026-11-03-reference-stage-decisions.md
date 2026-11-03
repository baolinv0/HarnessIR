# Reference stage decisions implementation plan

Goal. Reduce single-request bookkeeping while preserving visual decisions and final validation.

Architecture. Add an opt-in task field `stage_adapter=reference_decisions_v1`. Freeze the adapted schema in each actual stage request. Compile decisions into existing v1/v2 documents and run the original validators. Legacy tasks continue their original request protocol.

Files. `v3/stage_adapter.py` owns compact schemas and deterministic assembly. `v3/stages.py` invokes it on the normal production path. `v3/contracts.py` validates the option. `v3/runner.py` binds the option into requests. `v3/common.py` passes explicit reasoning settings. Tests exercise the production `run_stage` entry point.

- [x] A. Validate explicit reasoning settings and classify completed length truncation with raw response retained. Test captured HTTP requests.
- [x] B1. Diagnose uses eight keyed dimensions containing profile, deltas and coverage state/reason. Program assigns finding/delta IDs and coverage links. Test round trips, unknown evidence, conflicting status and missing dimensions.
- [x] B2. Compose inherits diagnosed facts, evidence, limitations and protections. Model supplies ordered decisions, mandatory flags, criteria and relationship plans. Test no-edit, more than three targets and unsupported references.
- [x] B3. Evidence review explicitly confirms or replaces each section and each dimension. Omission fails. Program assembles the effective diagnosis and hashes. Audit/verify fixed identities are derived from the displayed request. Test conflict and missing checks.
- [x] C. Run existing reference and runtime regressions, then broader CPU suite. Document four-dev qualification procedure and unresolved live validation.

Review focus. Old frozen identities, multi-delta ordering, unsupported evidence, conditional correspondence limits, incomplete review. Production model/service and four-dev images are unavailable in this workspace. Live qualification must be recorded separately.

Decision. This implementation uses an explicit opt-in until dev qualification. Bounded repair remains a later opt-in after A/B evidence, as agreed in the design.

## Enabling the implementation

Create a fresh task with the following field alongside its existing workflow contract.

```json
{
  "workflow_contract": "reference_retouch_v2",
  "stage_adapter": "reference_decisions_v1"
}
```

`reference_retouch_v1` accepts the same adapter option. The adapter is explicitly opt-in. Existing task/config files are hash-bound, so changing an existing frozen task requires creating a fresh case. Adapted stage templates include the adapter version and the exact request-specific schema in their request hash. The controller archives the original model text, compact decision payload and assembled full payload. Each operation retains its normal receipt and actual call charge.

| Stage | Model decision | Deterministic assembly |
|---|---|---|
| Diagnose | All eight reference profiles, A/B deltas, coverage status/reason, whole-image findings, protections and uncertainty | Finding/delta IDs, attributes from dimension keys, coverage links |
| Compose | Ordered target selection, instruction, region, mandatory flag, criterion, extra evidence, new protections, relationships, coverage status/reason | Frozen diagnosed facts/evidence/limitations, existing protections, IDs, priorities, revision identity, coverage links |
| Evidence review | Explicit confirm or complete replacement for every general section and each dimension, resolution and reason | Effective diagnosis, regenerated diagnostic IDs/links, exact input hashes |
| Verify | Every target, preservation and artifact judgment, issues, verdict and all other visual fields | Fixed identities, exact whole-frame review hash and its previously validated overall_style |
| Condition audit | Every target's actual instruction coverage, protections, exclusions and reason | Fixed target identities and exact condition/contract hashes |

Diagnostic records are emitted in sorted dimension order. Within one dimension, model delta order is preserved. Diagnostic IDs may be regenerated before goal freezing. Compose target list order defines execution priority. Reference texture/noise boundaries, global relationships, conditional correspondence limits and uncertainty continue through the original semantic validator. A missing dimension, missing review/check, unknown reference, or contradictory model status fails validation.

The adapter keeps the full stage input images and context. It accepts open-ended observations and target counts. Existing protections are inherited from the validated diagnosis. The model can add protections, while replacements in evidence review remain subject to the original protection-superset check.

## Runtime configuration

The following is a configuration example for a server confirmed to support these options. Token values are starting settings for qualification, not measured optima. The base stage endpoint and deployed model name must be supplied in the existing configuration.

```json
{
  "stage": {
    "response_format": "json_schema",
    "settings": {"temperature": 0.1, "max_tokens": 16000},
    "stage_overrides": {
      "diagnose": {"settings": {"thinking_token_budget": 6000}},
      "compose": {"settings": {"thinking_token_budget": 6000}},
      "evidence_review": {"settings": {"thinking_token_budget": 6000}}
    }
  }
}
```

Per-stage overrides accept only `settings`, `response_format` and `timeout_seconds`. Settings merge onto base settings, so one stage's budget does not overwrite another's. `thinking_token_budget` and `chat_template_kwargs` are explicitly forwarded through the normal chat HTTP client. Server acceptance and actual enforcement must be checked on the deployed service. The local tests inspect the exact serialized request and prove forwarding. They do not establish the remote model's grammar or reasoning behavior.

A completed response with `finish_reason=length` returns `stage_output_truncated`, even if its JSON happens to be syntactically complete. Empty truncated responses retain raw response and completed-call accounting. Completed errors retain original observations. Transport errors keep the controller's existing unknown-submission reconciliation path.

## Four-dev qualification and performance check

1. Archive the current failed runs with their task/config/model/service versions and original raw responses. Keep the original four dev group IDs and existing Direct outputs. Create fresh case IDs with this adapter option. Use the existing model, images, executor/PE and generation limits.
2. Run stage qualification on these four dev groups through `hre models` or the existing reference controller. Review archived operation requests to confirm the adapted schema, model settings, allowed evidence and actual image roles. Check both valid and deliberately invalid structured-output examples on the deployed server to verify grammar enforcement. Capture completion reason, usage, elapsed time and raw response for each call.
3. Review Diagnose, Evidence Review and Compose for actual A/B skin hue/chroma differences, facial versus background directions, whole-frame tone relationships, comparability and uncertainty. Compare the archived decisions and assembled target contracts with old valid records and independent human observations. An increase in legal outputs accompanied by generic or missing judgments fails qualification.
4. Use archived Direct images for Verify checks and existing condition text for audits. This isolates textual protocol qualification from new image generation. Record expected check coverage and unresolved observations.
5. Once stages qualify, resume the existing three-arm quality protocol on the dev groups first. Report attempted cases, stage completion, image delivery, final effective delivery and image quality with their own denominators. Compare quality on shared successful cases and report all-case coverage separately. Four groups can reveal obvious regressions but cannot certify general zero quality loss.
6. Record a qualification decision before freezing formal D_test execution. The existing experiment's data split and generation budget govern formal execution.

Recovery batch C remains conditional on observed residual failures after A/B. This implementation performs exactly one VLM request per stage attempt and uses existing explicit operation recovery. A future protocol-repair option must declare its per-stage and per-case text-call limits in the frozen task, charge every attempt, preserve unknown-submission reconciliation, and retain frozen visual goals.

## Verification record

Tests use synthetic observations and image fixtures. Real VLM and image-model inference, the four dev image groups and deployed service enforcement remain pending in this environment. Current implementation is a candidate for dev qualification. Protocol completion and image-quality improvement require the qualification results above.

The stage-only qualification command stops after Compose and archives planning outputs.

```bash
python -m hre models create --case-root runs/dev_adapter_GXX --spec task_adapter.json --config runtime.json
python -m hre models prepare --case-root runs/dev_adapter_GXX --through compose
```

The existing `--through condition` cutoff additionally prepares/audits the final condition. Image generation follows the existing explicit `run` or `resume` command after qualification.

The adapted response schema includes an explicit error envelope so constrained generation can abstain when images were not observed. The deployed structured-output backend must support its `anyOf` alternatives and review-choice schemas. Adapted prompts use their own visual guidance and do not ask the model to output program-derived hashes or revision fields.

## Review fixes

A separate code reviewer inspected production entry points, legacy identities, multi-dimension replacement and frozen-goal boundaries. Five findings were reproduced and addressed with regression checks.

- Duplicate JSON keys could overwrite a contradictory target judgment. Adapted responses now reject duplicate keys at every nesting level before schema validation. Raw text remains archived.
- Empty additional target evidence was unnecessarily rejected. Compose accepts `evidence_refs=[]` and inherits previously validated delta evidence before the original full validator runs.
- Completed reasoning-only truncation with null/missing content lost its completed-call evidence. It now retains raw response, usage and actual call accounting while reporting truncation.
- Full-document instructions conflicted with compact output fields and lacked a grammar-valid abstention. Adapted visual guidance and a schema-valid error envelope resolve the conflict.
- Misspelled stage overrides could be ignored, and invalid budgets were discovered after reservation. Stage configuration is now validated at case creation and again before operation submission.

An additional range check preserves optional target-specific uncertainty for comparable deltas. Conditional correspondence limits are inherited exactly and conflicting replacements fail. The author verified fixes with regression tests after review.

Final CPU verification on 2026-11-03 passed `python -m pytest -q engine/tests` with **1015 tests and 186 subtests**, 4 existing multiprocessing fork deprecation warnings, in 385.42 seconds. The final focused controller/runtime regression passed 168 tests. The adapter-specific suite passed 35 tests. `git diff --check` and changed-source compilation passed. Live model/server and four-dev qualification remain pending.
