# Explicit input domain: camera RGB versus Base output

This additive `source_kind_v1` contract extends delivered S4 r2. It does not change
color math, precision, ICC restrictions, preservation, private acceptance policy,
model receipts, targets or budget semantics. The envelope remains
`reference_style_s4_v6`; existing configs and frozen records retain their legacy
Base-A meaning. Never relabel an existing run. Create a new sample for a new domain.

## Input contract

Each A/B input retains the six existing fields `role`, `path`, `encoding`,
`encoding_basis`, `base_model_version`, `display_assumption` and may explicitly add
`source_kind`. The only values are `base_model_output` and `camera_rgb`.

| Role/domain | Base model version | Encoding |
| --- | --- | --- |
| A / base_model_output | nonempty actual caller-declared version | existing sRGB/P3/unknown rules |
| A / camera_rgb | null | existing sRGB/P3/unknown rules |
| B / camera_rgb | null | known sRGB only, as before |

Omitted source_kind defaults to Base for A and camera RGB for B (legacy behavior).
B cannot be Base. Unknown A remains explicitly display-assumed and numerically
blocked. A nonempty Base version is a declaration, **not authentication**; do not use
a dataset name or fake version to pretend camera RGB came from a Base model.

Audits carry source_kind; camera audits mark base_provenance
`not_applicable_camera_rgb`. Audit/state bind A's input_domain. Human reports and
selected label metadata distinguish `camera_rgb_workflow_only` from
`base_model_output_domain_only`. Camera results are not Base-model validation or
training-label certification. Shared raw-C audit does not inherit A's source_kind
or Base provenance. No source-domain or lineage prose is forwarded into prompts.

## Original-to-supplied lineage

An optional config field `input_lineage: {"path": ".../manifest.json", "sha256":
"64 lowercase hex characters"}` captures a UTF-8 JSON object byte-for-byte as
`input_lineage.json`. Its hash/ref is bound to audit/state and integrity checked by
status; the human report and selected label retain the reference. Extra keys in
this reference reject. This is an **archival external attestation**, not automatic
verification of its claims, conversion script, original assets or mapping.
Independent input review must check those against actual files. Arbitrary narrative
inside it is archival only, never executable text or a model attachment.

`source_file_hash` always identifies the **supplied** A/B file. If supplied files
are normalized sRGB derivatives, that hash is not the camera-original hash. Keep
both original and canonical bytes/hashes in the independently checked lineage.
Direct P3 B still rejects; perform any controlled source conversion separately,
record ICC, frame, orientation, intent, flags, precision and absence of resizing.
The Camera0717 first gate is controlled reduced-gamut sRGB8 workflow validation,
not full-P3 fidelity proof. Endpoint fractions are not exact measured clipping.

## First gate only (after independent code approval)

Create a new run from canonical images with explicit camera_rgb/null Base fields
and the bound lineage manifest. Do not use protocol_fixture for actual inputs.
The CLI `run` audits and stops; it never automatically advances or calls a model:

```sh
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$IMPLEMENTATION/source/engine/src"
python -m hre reference-style run --config "$CONFIG" --out "$CASE"
python -m hre reference-style budget-configure --root "$CASE" --spec "$BUDGET"
python -m hre reference-style status --root "$CASE"
python -m hre reference-style run-report --root "$CASE" --out "$REPORT"
```

For the authorized A01 single-pass ceiling, BUDGET is
`{"version":"b1","edit_attempts":1,"diagnostics":3,"feedback_rounds":0,"total":4}`.
It is a finite **local export-count cap**, not a cost budget, actual call commitment
or authority to advance stages. Freeze before any export; no silent expansion.
At this gate all used counts, attempts and results must be zero. Do not export any
AB/edit/ABC request yet. Later stages, genuine receipts, masks/depth/OCR, style,
acceptance, spatial alignment and label certification remain NOT RUN/unverified.

Current runnable provider is current_chat_offline. Future native Qwen mapping is
unchanged and not automatically compatible with the new receipts; see S3/S4 docs.
