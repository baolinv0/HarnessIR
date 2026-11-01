# Independent Camera RGB contract test report

Date: 2026-11-01 UTC. Verdict: **PASS for the narrow source-domain and archival-lineage amendment.**

## Frozen implementation
- Root: `${SCRATCH_ROOT}/reference_style_camera_rgb_20261101`
- Manifest SHA256: `805e60742da554421c4f2f7be6d1587bd87045ef688746b9a396488b8560e686`
- All 359 source-file bytes and SHA256 values verified; no mismatches.
- Parent source manifest: `85c2344937d99c2675954d86af0a4eb6c448e35a5e4e0da11e48f46472c7907d`.
- Tester did not modify implementation source. Independent plan and initial 26 probes were written before amendment/test inspection. Six lineage probes were added from the public contract; one legacy frozen-record probe added afterward.

## Results
- Independent final probes: **33/33 PASS**, 0.759 seconds.
- Scoped reference-style unittest regression: **166/166 PASS**, 36.146 seconds (includes author tests; not an independent test count).
- Full inherited project test suite: **NOT RUN**.

Coverage: legacy/explicit Base config; camera RGB/null Base version; contradictions, malformed and unknown source kinds; B's unchanged sRGB constraint; external JSON lineage snapshots/hash/schema/tamper checks; archival text not copied into prompts; domain retained in audits/reports; original bytes and numeric/color results identical across domain labels; unknown encoding remains nonnumeric; explicit real budget required; no X input; unaligned flag; strict preservation text unchanged; persisted C audit carries no fabricated Base provenance; old frozen records load under new code without being relabeled or rewritten.

## Transparent test corrections
Original 32-probe execution had 31 passes and one failure: a probe examined the temporary private `_audit_rgb` C dictionary. The unchanged public `derive_candidate` path removes legacy Base fields before persistence. The assertion was corrected to inspect the persisted public candidate audit using the existing synthetic S4 fixture. Original script/log retained. This was a test-boundary error, not a demonstrated implementation regression; no implementation code changed to satisfy it.

The added frozen-record compatibility probe initially failed because ordinary read locking creates `case.lock`. It now excludes only this infrastructure file while comparing every other byte before/after status and report. Original log retained. All record and asset bytes remain equal.

## Evidence files
- `TEST_PLAN.md`
- `test_camera_domain_independent.py` (final 33 probes)
- `test_camera_domain_pre_boundary_correction.py` (original 32-probe script)
- `baseline.log` (old implementation expected feature failures)
- `amendment_r1.log` (original 32-probe result)
- `amendment_r1_boundary_corrected.log` (32/32 corrected public boundary)
- `legacy_lock_probe_original.log`
- `amendment_r1_final.log` (33/33)
- `scoped_regression_r1.log` (166/166)
- `manifest_verification.json`

## Limits
All probes use explicitly synthetic fixtures. No actual Camera0717 image was generated or judged by this tester. No ChatGPT/Qwen/API/GPU calls, fake real receipts, installs, server changes or source edits. Input lineage is a byte-bound external attestation, not proof of its claims. The narrow PASS permits the next independently reviewed input/color gate; it does not establish photographic quality, pixel alignment, label suitability or Base-output-domain generalization.
