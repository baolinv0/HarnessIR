# Reference-style S0/S1 r3 — offline protocol foundation

This is an opt-in new path, not the old A01/P3 workflow. It does not invoke any
model, GPU, HTTP endpoint, renderer, perception tool, or raw X. `run` audits A/B
and stops. Later stage names in the bridge are transport contracts only; S2
targets/diagnosis and quality/acceptance are not implemented.

## Commands

Run from `source/engine` with `PYTHONPATH=src`:

```sh
python -m hre reference-style run --config config.json --out NEW_OUTPUT
python -m hre reference-style status --root NEW_OUTPUT
python -m hre reference-style export --root NEW_OUTPUT --stage ab_diagnosis --context context.json
python -m hre reference-style unknown --root NEW_OUTPUT --attempt-id ATTEMPT_ID --reason 'Outcome not established'
python -m hre reference-style import --root NEW_OUTPUT --receipt receipt.json --output ACTUAL_OUTPUT
```

`export` also supports `edit` (nonempty targets required) or `abc_diagnosis`
(`--candidate-hash` must match imported C with the same targets). There is no
automatic advance. Synthetic fixtures cannot demonstrate real style quality.

## Configuration template — not an actual sample

```json
{
  "sample_id": "sample01", "provider": "current_chat_offline", "purpose": "reference_style",
  "inputs": [
    {"role": "A", "path": "/actual/A.png", "encoding": "srgb",
     "encoding_basis": "actual Base output documentation", "base_model_version": "actual-version",
     "display_assumption": null},
    {"role": "B", "path": "/actual/B.png", "encoding": "srgb",
     "encoding_basis": "actual phone export metadata", "base_model_version": null,
     "display_assumption": null}
  ]
}
```

A supports declared `srgb`, `display_p3`, or `unknown`. Unknown requires explicit
`display_assumption: "srgb"` and blocks precise numeric color targets. B must be
known sRGB. Base version/encoding basis are caller declarations, not provenance
proof. Historical P3 cases with unverified Base origin must not substitute A/B.

Supported inputs: opaque RGB8 SDR JPEG/PNG; noninterlaced RGB16 PNG with orientation
1. The exact baseline RGB16 decoder is reused because Pillow may expose RGB16 as
RGB8. Unsupported ICC/profile conversions, alpha, RAW, TIFF, HDR composition and
animated images fail closed. RGB8 EXIF orientation is applied and recorded; no
resize/crop. Original bytes and native pixel hashes remain. Analysis is unclipped
float64 XYZ/D65, linear sRGB, Y, Lab/D65 and chroma. Model derivatives are explicitly
clipped and quantized RGB8 sRGB PNG with canonical ICC. Critical colors affected
by clipping require later review. There is no silent source-color restoration.

## Public execution context

```json
{"target_version": "v1", "targets": [], "evidence": [], "feedback": []}
```

- Targets: exactly `target_id`, `unit`, `region_refs`, `effect`, `numeric_range`,
  `judge_type`, `priority`, `evidence_ids`. Units: `global`, `whole_semantic_object`,
  `whole_material`, `relation`. Effects/regions are controlled enums, not prose.
- Evidence: exactly `evidence_id`, `role`, `kind`, `status`, `reason_code`.
- Feedback: exactly `target_id`, `candidate_record_id`, `candidate_hash`,
  `observation_code`; never arbitrary facts or acceptance labels. Each reference
  must resolve to an intact, validated local image with the exact target hash/version.
  Feedback changes request identity, not frozen target hash.
- Fixed preservation requirements are inserted into every prompt. Arbitrary
  config/upstream/history/notes/policy fields are rejected, not forwarded.
- Private policy has only explicit `verification_store.store_policy` and
  `read_policy_for_verifier` APIs under `private_verification/`. The coordinator
  neither imports this module nor enumerates the directory. No acceptance engine
  exists. Executable target/evidence/feedback strings use finite vocabularies and
  typed references; no arbitrary prose/labels are forwarded. This is not semantic
  classification. Raw VLM narrative remains in imported response artifacts for
  later human/VLM analysis; it is not automatically promoted into instructions.

See `REFERENCE_STYLE_S01_R2_MIGRATION.md` for the intentionally incompatible v2
schema, accepted enums and examples. S2 full measurement/diagnosis semantics remain
unimplemented; typed numeric ranges are recorded, not verified as achieved.

## Receipt contract

Requests bind sample/stage/attempt, original and derivative A/B file/pixel hashes,
conversion/geometry metadata, target version/hash and actual compiled prompt hash.
Ordered roles are exactly A then B. C is a separately hash-bound ABC attachment.

Receipt keys: `schema_version`, `sample_id`, `attempt_id`, `stage_id`, `request_hash`,
`target_version`, `target_hash`, `prompt_hash`, `role_bindings`, `response_type`,
`output_sha256`, `provenance`. Identity values must match the exported request.
Provenance keys: `origin` (`actual_current_chat`), `provider` (`chatgpt`),
`conversation_ref`, `tool_call_ref`, `model_version` (null if unknown),
`transcription_note`, `input_visibility`
(`audited_files_attached_internal_transforms_unknown`). For unit fixtures only,
purpose `protocol_fixture` requires origin `synthetic_fixture`.

Import preserves raw output bytes and receipt. Image size, ICC and container depth
are recorded; spatial correspondence is unverified even at the same dimensions.
Different dimensions are recorded, never silently resized. Numeric support stays
uncertain. `validated` means identity/transport checks, not style acceptance.
The sample is not marked style-complete. Local hashes cannot authenticate a remote
call: `caller_attested_not_remote_authenticated` is recorded and
`real_execution_evidence` remains false in S0/S1 even for claimed actual receipts.
Actual conversation/tool evidence requires independent review. No model version,
seed, cost, duration or internal preprocessing is invented.

Unknown results preserve the same attempt and block new export. Immutable state
snapshots distinguish exported/waiting/unknown/imported/validated. Orphan export
directories or partial imports require explicit same-attempt reconciliation,
never automatic replay. SHA256 record canonicalization uses sorted UTF-8 JSON,
finite numbers and only excludes its own hash. Pixel hashes include shape/dtype.
An exactly committed receipt/output replay returns the same result without state
mutation, even when a newer attempt is pending. Conflicting replay rejects. Any
preexisting partial raw/receipt/response artifact blocks; it is never overwritten.
PNG tRNS transparency keys, conflicting cHRM/cICP and unsupported HDR metadata
reject before derivatives; supported SDR metadata is recorded in the audit.
Present PNG iCCP must decompress to a valid supported profile and match decoder
metadata before output creation; malformed profile presence is never treated as
absent. Whole `face` and `exposed_skin` semantic regions are supported, while
face-shadow/highlight and facial-part subdivisions remain unsupported.

## Verification and limits

```sh
PYTHONPATH=src python -m unittest discover -s tests/reference_style -v
PYTHONPATH=src python -m pytest -q
```

Own suite: 48 synthetic protocol/color tests, including real CLI subprocesses.
Inherited pytest suite: unavailable because pytest is not installed; Jinja2 and
Streamlit are also absent. No package installation performed. Historical
balance100 tests also require `V6_WORKER` and fixed archive-runtime paths.

This is not full baseline regression coverage, real style/Qwen validation,
independent test/review approval, or training-label validity. No S2 perception,
full target/diagnosis semantics, acceptance/selection, budget scheduling or label
export is implemented. Stop at the S0/S1 gate pending independent verification.
