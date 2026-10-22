# Model-aware integration and independent stage checks

The two tracks run in parallel. Stage experiments are not an admission gate for
the complete workflow. Both use the same frozen task inputs and condition compiler.

## Implementation

1. Extend the existing v2 spec with a model profile, strategy and compiler choice.
   Keep the current Controller, one-generation budget and accepted-artifact journal.
2. Freeze the appearance intent after Compose, including supported region
   relationships, independent A/B ROI coordinates, measured statistics and hashes.
3. Compile conditions through the selected model path. Qwen/FireRed have a built-in
   deterministic instruction compiler. Actual PUP/VGL/PE/Recaption services use
   external compiler workers; generic VLM calls cannot impersonate them.
4. Pass the accepted native condition unchanged to Execute. Do not prepend the
   old generic prompt to a caption or serialized native VGL object.
5. Add a full runner and stage export/run/compare commands. External workers use
   argument arrays and JSON files. Stage checks do not advance a case; the full
   runner uses the existing generation accounting and verification.
6. Provide a deployed-cache Diffusers worker for Qwen/FireRed, and preserve the
   existing manual handoff for other editors. No weight download during a run.
7. Exercise real subprocess/HTTP transport and a clearly labeled synthetic full
   workflow. Keep GPU quality experiments separate from software test evidence.

## Experimental interpretation

- G0/native: original brief + A/B through the chosen native or direct path.
- G1/shared: analysis-derived intent with model-neutral expression.
- G1/model_aware: the same class of intent with model-specific expression.
- For a clean shared-versus-model-aware ablation, reuse the exact frozen analysis
  and compare intent hashes. Independently rerunning diagnosis/Compose introduces
  an additional planning variation and is not a compiler-only ablation.
- Profiles declare interfaces, not measured success. This version enables only
  full-frame A+B; spatial masks, ROI fusion and automatic feedback retries remain
  separate experiments.

## Acceptance

Existing behavior remains opt-in compatible. Tests cover source binding, native
prompt preservation, Qwen canvas/PE checks, Fibo JSON handling, region contracts,
external calls, restart behavior, complete synthetic execution and CLI entry points.
Real model quality, cost, and native compiler availability are deployment results,
not conclusions from these tests.
