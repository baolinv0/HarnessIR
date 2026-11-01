# Qualitative visual-goal compiler: independent functional report

2026-11-01 UTC. **PASS for functional propagation of diagnosis-backed goals.**

## Frozen source and tests
- Root `${SCRATCH_ROOT}/reference_style_visual_goals_20261101`.
- Manifest SHA256 `47ee6a2fb67d8fca764ef1ff9bfbf795841c25944225d657157f86da7a6aed60`; all362 source files verified.
- Five focused independent functional tests PASS (2.656s). Written from announced public contract before inspecting patch or author tests. Baseline had three expected missing-feature errors; old visual target still passed.
- Previous33 independent camera-domain probes PASS (0.796s).
- Scoped reference-style regression170/170 PASS (35.866s), including author tests. Full inherited project suite NOT RUN.

Focused checks cover seven separate whole-region appearance/strength goals and two qualitative relationships through freeze→compile→edit export; same selected meaning in both ABC views; relationship-only localization of both endpoints; actual bound diagnosis excerpt requirement; legacy targets unchanged. No broad adversarial expansion.

## Actual A01 artifact check
Actual files under `${SHARED_ROOT}/reference_style_validation_20261101/A01_B01/pipeline_s2/edit_handoff/`.

- All18 targets preserved:3 global goals,7 whole-region goals,8 relationship goals.
- Every selected instruction is an exact substring of the imported bound diagnosis and appears unchanged in compiled output and exact edit request. Qualitative strengths survive.
- Both saved ABC projections equal freshly computed public views; relationship endpoints remain explicit.
- Mandatory A content/spatial preservation remains present. Targets stay visual with null numeric measurement/tolerance; no fabricated numeric calibration.
- First attachments remain original A content and B style; actual hashed localization aids cover all seven whole regions per image.
- `EDIT_PROMPT_EXACT.txt` equals stored request prompt byte-for-byte. SHA256 `c82adf7f5b510c8ccb25b7e70abbe262fa991ab2906d368c42781633693cfa4a`,6696 UTF-8 bytes.
- Compiled version `diagnosis_backed_visual_goals_v1`.
- Diagnosis ID `response_5fd0965a3ce74953b5250ff9b548b46a`, content hash `d1dd7d3f37312c171a76d0450a9a5dbcf9cd99c0776b264ef4a11b0d1c68faa8`.
- No hand-authored replacement prompt hid a compiler failure: exact exported request contains the compiler output and notice.

## Scope
This establishes correct functional transport, not semantic correctness or image quality. Actual parent diagnosis was honestly recorded as summary-based rather than claiming full raw-prompt consumption. Separate reviewer assesses selected wording against images. No image generation, source edits, model calls or dependency installations by this tester.

## Evidence
`test_visual_goals_functional.py`, `visual_goals_baseline.log`, `visual_goals_r1.log`, `visual_goals_regression_r1.log`, `camera_domain_on_visual_goals.log`, `check_actual_visual_goals.py`, `actual_visual_goals_verified.json`, alongside this report.
