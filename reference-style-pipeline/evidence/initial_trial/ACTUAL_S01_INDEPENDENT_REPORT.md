# Actual A01/B01 S0/S1 independent gate

Date: 2026-11-01 UTC. **PASS, narrowly for input/color/provenance preparation. Stop before S2.**

Run: `${SHARED_ROOT}/reference_style_validation_20261101/A01_B01/pipeline_s01/case`

## Independently verified
- Viewed both actual canonical images. Their framing differs; no pixel alignment claimed.
- Original A/B hashes match archived lineage; neither original mutated.
- Independently reread original primary frame 0, applied EXIF orientation, then regenerated using each embedded ICC to the saved target sRGB ICC, LittleCMS perceptual intent 0 / flags 0. Both output pixel arrays exactly equal supplied canonical PNGs.
- Canonical RGB8, captured pipeline source and output derivative pixels are exactly equal, with no resize/crop. Full resolutions A 2296×3056 and B 2316×3088. File bytes differ legitimately due to metadata/profile serialization and are separately hash-bound.
- Independently computed piecewise sRGB linearization equals stored `linear_srgb` exactly. All stored analysis arrays finite; native shapes preserved. Numeric eligibility applies to supplied sRGB8 only.
- Source domain is explicitly camera_rgb, Base versions null, Base provenance not applicable. Purpose reference_style, not synthetic fixture.
- Original-to-canonical lineage exact SHA256 `5e9a4667dc87dda365a50937065d8ef095d819f991dee39f045809e365319e34` snapshotted/bound.
- Budget edit1 / diagnostics3 / feedback0 / total4; all used counters zero, no reservations, attempts, results or active request. No S2 state. No model invocation by this tester.
- All 12 case-manifest files pass bytes/SHA256 checks. Case manifest SHA256 `629b6150218653a8b92cb758d361590165c55a74cea4edf63836b6db485567ff`.
- Source-manifest copy SHA256 `805e60742da554421c4f2f7be6d1587bd87045ef688746b9a396488b8560e686` matches code-tested snapshot.
- Author run report SHA256 `50c07df6c9681bffe43845b0f1862138cba32da946ef529883e5c81f601ffad8` inspected; its claims and NOT RUN boundaries match actual artifacts.

## Boundaries
This is a controlled reduced-gamut sRGB8 workflow gate, not full-P3/HDR fidelity, achieved style, alignment, image-quality improvement, pixel-label certification, training utility or Base-output-domain evidence. ICC conversion endpoint counts do not establish exact gamut-clipping rates. No masks/depth/OCR are certified by this gate. Historical cached masks do not automatically bind to the new canonical images. Later diagnosis/edit/ABC validation remains NOT RUN.

## Reproduction and evidence
Independent script `check_actual_s01.py`; result `actual_s01_verified.json`; source-only reconversion `actual_input_reconversion.json`, all alongside this report. Script reads originals and run assets, performs in-memory independent conversion and checks; it does not alter originals/case/source. Normal status checking may touch ordinary lock infrastructure. No implementation edits, dependency installs or model calls.
