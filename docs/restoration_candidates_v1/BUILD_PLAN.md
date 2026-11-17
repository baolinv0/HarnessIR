# CPU development and offline GPU delivery

The approved system specification is IMPLEMENTATION_PLAN_V1_1.md. Build working Python code now on CPU. Model quality and native GPU execution remain separate verification gates, not prerequisites for writing or testing orchestration.

## Synthesis decision

Use the domain-first candidate design. One CandidateCase orchestrates immutable JSON snapshots and pure domain functions. Reuse hre.storage.case_lock and atomic JSON writes for one operation journal. This fits existing repository conventions and gives the offline code agent readable artifacts. Reject SQLite as an additional state authority. Adopt the workflow design's operation identity including partition, variant, package, candidate and attempt. All real calls pass one journal boundary. Failed operations replay failure, completed replay response, submitted becomes unknown after crash. Unknown never retries.

The design candidates are saved in the development workspace under artifacts/design. Available models are from one vendor, so there is no independent cross-vendor design verdict. The parent compared source grounding, failure recovery, public API size, CPU testability and offline maintainability.

## Throughput checkpoint

- Blocking first steps. Acquire pinned baseline, find CPU Python, install test-only dependencies, freeze common interfaces and run baseline tests before feature integration.
- Independent workstreams. Bridge/journal, planner/evidence and judge/study own disjoint files. The parent owns contracts, runtime, reports, CLI and packaging.
- Shared mutable state. Agents edit separate files. Runtime serializes mutations through the existing case lock; all external operation state has one journal authority.
- Smallest safe decomposition. Three bounded implementation workers plus parent integration; no nested delegation.

## Shared interfaces

All domain records are validated JSON dictionaries, copied at boundaries and sealed with canonical hashes. contracts.py exports VERSION, require(condition, code, message), digest(value), text_hash(text), parse_task(value), parse_config(value), candidate_spec(slot_id, strategy_id, sample_index, seed, full_prompt, source_hash, issue_refs=None, expected_effect=None, evaluation_axis_id=None), seal(value), verify_seal(value). Errors use hre.models.HREError. Source refs always contain path, sha256, canonical_source_sha256, width, height. Paths in internal records are absolute; anonymous model-facing records never contain candidate strategy paths.

Journal(root: Path, limits: dict) owns operations.json. invoke(operation_id: str, kind: str, request: dict, callback: Callable[[], dict], *, group: str | None = None) -> dict. snapshot() -> dict. reconcile(operation_id: str, resolution: dict) -> dict. limits keys are stage names, image_generation, and judge_J0_primary/aggregate/dispute/format_repair with judge_J0_total, similarly J1/J2. Missing limit must reject, not imply unlimited. root runtime holds case_lock for each public mutation.

bridge.py exports canonicalize_source(path, directory), prepare_source(source, task, directory), build_execution(spec, prepared, editor), execute_image(manifest, root, journal, config, partition='E1'), compose_baseline(root, task, config, journal, source), preflight(config). Prepared source contains source, path, sha256, prepared_source_sha256, geometry, geometry_sha256. Manifest contains spec, request, editor, prepared and execution_manifest_sha256. Artifact contains candidate_id, status, native_image, delivered_image, native_sha256, sha256, width, height, receipt, manifest_sha256. Failed artifacts may have null images.

transport.py exports call_json(root, config, journal, operation_id, kind, prompt, images, *, system='', group=None, fixture_response=None). Image paths are resolved before request persistence and hashed. In fixture mode fixture_response is required. In real mode use config.stages[kind] or config.stages.judge for judge kinds. Stages use OpenAI-compatible local HTTP chat/completions, zero transport retries. No API secret values in records.

planner.py exports build_plan(root, task, config, baseline, source, journal) -> sealed dict with plan_origin, issues, roi_registry, shared_requirements, candidate_specs, fallbacks, requirements_ir. Source-only C0 is supplied in baseline and never execution input for alternatives. baseline includes P0 and C0 artifact. Specs preserve slot_id, planned_strategy_id, effective_strategy_id, evaluation_axis_id. Main contract full_prompt is canonical, prompt_path is only an execution artifact.

evidence.py exports collect_evidence(root, task, plan, artifacts, source, prepared, config) -> sealed bundle. Bundle keys: source, candidates (each candidate_id, alias, image_path, image_sha256, hard_gate, roi_images), roi_registry, measurements, critical_instances, aliases (alias->candidate_id), baseline_id, pool_hash. hard_gate is passed/failed/unknown. critical_instances has check_id, attribute_id, region_id, attribute, required_for_acceptance, verification_requirement, allow_unverifiable. Whole image restoration/artifact checks remain mandatory. Review requests use aliases and copied anonymous images, never internal IDs/strategy/seed/prompts/offline data.

judge.py exports compile_review_plan(task, bundle, variant, config) -> sealed plan; judge_pool(root, task, config, bundle, journal, variant) -> SelectionResult; select(task, bundle, review_plan, reviews) -> SelectionResult. Result keys use the main specification, including eligible_ids, eligibility_decisions, best_candidate, best_available_id, status and selected_output. Judge writes review_plan and raw/merged assessments under judge/<variant>. Candidates and instances must have complete checks before eligible. config.fixture.reviews optionally supplies scripted judgments; default fixture judgments are explicit synthetic responses and cannot satisfy research gates.

study.py exports preregister(dataset: dict, protocol: dict, split: str) -> dict. This freezes cases, strata, seeds and slots before E1 output. Seed-shuffled strata prevent fixed lexicographic first-stratum bias. Non-typical strategy effects are counted per slot/axis/effective strategy, never post-hoc best-of-A/B. Report eligibility and zero denominators explicitly.

## Configuration shape

Task keys: schema_version, case_id, source (path string or {path}), task_mode, scale, usage_policy, user_intent, critical_attributes, rois, task_types. ROI keys: id, semantic_type (person/text/building/grass/other), box, importance, provenance. CriticalAttribute keys follow the approved spec plus allow_unverifiable for the photo policy.

Runtime keys: schema_version, mode (fixture/real), harness_source_root, harness_sha, stages, editor, budgets, review, fixture, experiment, seed_schedule, tie_order. Fixture has baseline_prompt, issues, rewrites, audits, reviews, image_behaviors. Real editor is expanded Qwen v3 editor config; all effective defaults frozen. review keys: max_rois_per_package=6, max_images_per_call=64, max_judge_calls={J0:3,J1:3,J2:7}, max_output_tokens=8192. experiment keys: e1_ab=false, e2_manifest_path=null. seed_schedule defaults [0,1,2,3]. Fixture image generation is labeled interpolation/transforms only; never model-quality evidence.

## Execution checklist

- [x] Contracts and source/geometry/request identity tests.
- [x] Journal and real/fixture boundary tests, including crashes and failure replay.
- [x] Planner, semantic audit, fallback dependency and anonymous Evidence tests.
- [x] Judge, ReviewPlan, per-attribute qualification and preregistration tests.
- [x] Runtime/CLI fixture create/run/resume/reconcile/report/evaluate-offline and E1/E2 integration tests.
- [x] Targeted legacy regression and installed wheel verification. Four platform failures also reproduce on the unchanged baseline. Full legacy suite completion is not claimed.
- [x] Fresh code review, accepted fixes and CPU test report. See VALIDATION.md.
- [ ] Real GPU x1/x4 smoke, local VLM contract verification and research acceptance on the execution computer.

## Delivery rule

No placeholder production functions. Real mode cannot fall back to fixture. Missing real dependencies produce an explicit blocked result. Deliver source and wheel, platform-specific CPU dependency preparation instructions, fixtures, tests, runtime/task examples, hashes, offline runbook and a bounded debug-agent handoff. Do not package Windows binaries as Linux GPU dependencies or claim native GPU validation on CPU.
