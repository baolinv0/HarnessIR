# Actual A01/B01 S2 functional check

2026-11-01 UTC. **PASS for evidence/measurement functionality; actual parent diagnosis and subsequent editing not assessed.**

- Fresh MediaPipe inputs bind to current canonical full-resolution A/B file and pixel hashes. Model/category labels, native mask shapes, exact binary class masks and finite normalized confidence maps verified. No historical-mask substitution.
- Viewed current segmentation and both adopted manual localization overlays. Whole face, hair, neck/exposed skin and clothes are sensible coarse supports. Cabinet, ceiling and main lightbox model-authored polygons are visually localized sufficiently for descriptive use. No intraface subdivision. Main signs/foreground and B auxiliary light excluded.
- All14 imported supports match their actual masks and frozen native-grid supports. Eight actual-tool and six uncertain manual-annotation provenance labels are truthful.
- Independently recomputed 80 distributions (8 regions including global ×2 roles ×5 metrics), all their seven statistics, and 287 A/B measurements including seven signed inter-region relations. Every value, count, operand and B-minus-A delta equals the independent oracle exactly.
- All measurements remain visual_direction_only. Missing depth/OCR/face-tool records are unavailable, not failed or fabricated. No depth-brightness inference.

## Useful observed differences (descriptive medians)

| Whole region | A L* | B L* |
|---|---:|---:|
| Face |33.37|53.78|
| Neck/body skin |32.12|51.58|
| Hair |21.81|30.95|
| Clothes including strap |24.24|26.11|
| Yellow cabinet |37.87|56.44|
| Cyan ceiling |66.31|77.49|
| Main lightbox |94.01|97.51|

The desired brightness change differs by region. Applying the face brightening amount globally would not follow these observations. These numbers are diagnostic evidence, not calibrated matching targets.

## Practical interpretation limits
Face class includes eyes/lips/lens interiors, not pure skin. Clothes includes a tan strap and different visible shirt proportions; hair boundaries are coarse. Background/others are mixed, not one material. Manual polygons are model-authored coarse supports, not human ground truth. A/B are independently framed and not aligned; illumination equivalence is unestablished. Minor localization boundary imperfections do not block this first region-level functional test.

## Evidence identity
- Case: `${SHARED_ROOT}/reference_style_validation_20261101/A01_B01/pipeline_s01/case`
- S2 artifacts: sibling `pipeline_s2/`
- Fresh segmentation batch SHA256: `1a54bdc500019238452114a0c3e4d846ccd47528e57fe0cfa836d91f47ecea6c`
- AB report ID: `ab_report_e665c65e38a340c59b16445c79a01c55`
- AB report content hash: `43ef76d1a045be4de189e31fb446cbf50fb206d9bc57f593fb3192955b45f020`
- Snapshot content hash: `e5730b2097dd12d42819c84de767e44ab4aab80f053c41fd59dcb06118daf25f`

Independent scripts/results alongside this report: `check_actual_s2_segmentation.py`, `actual_s2_segmentation_verified.json`, `compute_s2_oracle.py`, `actual_s2_oracle.json`, `check_s2_records.py`, `actual_s2_records_verified.json`.

No source edits, duplicated installs/inference or image generation by the tester. This checks functional numerical/evidence output, not achieved photographic style, label/training utility or generalization.
