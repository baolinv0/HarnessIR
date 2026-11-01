# S3: measured edit handoff, actual submission and raw C derivation

**Offline file bridge only. No tool/model/API is invoked.** Synthetic protocol tests
are not actual ChatGPT judgments or generated photographic results. Real execution
waits for verified current A/Base, B/sRGB, actual S2 evidence and parent approval.

## Schema and lifecycle

This stage uses `reference_style_s3_v5`. Create a new sample and follow the S2
evidence/diagnosis/target flow using this code. Earlier v4 or other stage samples are
not rewritten/relabelled; this version refuses old envelopes. S2 initial mapping and
explicit revision contracts remain unchanged. Existing S0/S1 generic `export` stays
legacy scaffolding, **not** the measured S3 path.

Commands below are under `PYTHONPATH=src python -m hre reference-style` from
`source/engine`:

1. `edit-export --root CASE --compiled-id compiled_request_ACTUAL_ID`
2. Outside this software, the parent attaches the planned files in the actual ChatGPT
   dialogue and submits the exact exported prompt. No execution is presumed here.
3. `submission-record --root CASE --manifest ACTUAL_SUBMISSION.json --prompt-file ACTUAL_PROMPT.txt`
4. `import --root CASE --receipt ACTUAL_RECEIPT.json --output ACTUAL_RAW_C`
5. Optional: `candidate-derive --root CASE --response-id response_ACTUAL_ID --spec COLOR.json`

### Exported request

`export_edit` reads the **saved compiled record**, not a reconstructed generic control
context. It checks sample/audit, latest target version/hash, report, imported diagnosis,
snapshot, coverage, original A/B bindings and compiled prompt hash. Superseded/foreign
or modified drafts reject. It retains the complete measured regional/signed-relationship
instructions and appends only fixed generation/localization/preservation instructions.
The request binds `compiled_record_id`, `compiled_record_hash`, `compiled_prompt_hash`
and its final prompt hash/version `s3_measured_whole_region_localization_v1`.

`planned_attachments` is exact and ordered:

- a1: unchanged audited A RGB derivative, purpose content_image.
- a2: unchanged audited B RGB derivative, purpose style_reference.
- If genuine nonempty support exists, at most one composite A guide and one B guide,
  purpose localization_only. No empty/missing support is invented.

Guide contours come from each role's own frozen masks or bbox-derived support arrays.
Typed rN/semantic labels, contour colors, bbox coordinates, support paths/hashes and
canvas geometry are recorded. The image appears at offset [0,24] with no resize/crop;
header and right-side legend are separate padding. A/B themselves are never annotated.
Guides are **not hard masks, style examples, target images or output C**; the prompt
asks for no labels/contours/padding in C. This does not claim model mask capability or
prove that a model interpreted a guide correctly. Large numbers of regions can make
the composite dense; actual visibility remains a later visual check.

### Record what was actually submitted

The actual submission manifest is independent of the plan:

```json
{
  "attempt_id":"attempt_ACTUAL_ID", "request_hash":"ACTUAL_REQUEST_CONTENT_HASH",
  "prompt_sha256":"HASH_OF_ACTUAL_SUBMITTED_PROMPT_FILE",
  "attachments":[
    {"attachment_id":"a1","ordinal":1,"role":"A","purpose":"content_image",
     "path":"LOCAL_FILE_ACTUALLY_ATTACHED","sha256":"ACTUAL_FILE_HASH"}
  ],
  "provenance":{"origin":"actual_current_chat","provider":"chatgpt",
                "conversation_ref":"ACTUAL_DIALOG_REF","tool_call_ref":"ACTUAL_TOOL_REF"}
}
```

This partial example is **not a valid matching package**: list every actually attached
file, in actual order, with IDs/ordinals copied from the plan only when they match.
The software reads/hashes the supplied files and prompt and preserves their actual
bytes separately. It does not fill in missing attachments or infer that planned
assets were seen. IDs and ordinals must be unique; missing/extra/reordered/swapped-role
or changed but structurally valid packages are archived as `differs_from_plan`, set
the attempt to response_unknown, and block importing C as the original request.
False file hashes or malformed structure reject. Manual reconciliation is required;
no silent prompt mutation, replay, automatic retry or new tool call follows.

Only `matches_plan` submissions can bind C. Exact submission replay is read-only;
changed submission facts cannot overwrite the original. In all cases provenance is
`caller_attested_not_remote_authenticated` and remote input visibility is unknown.
Internal dialogue/model resizing or encoding is not observed or certified.

### S3 response receipt additions

Keep the existing receipt fields/role bindings and add `submission_record_id` and
`submission_hash` from the actual submission record. Its origin, provider,
conversation_ref and tool_call_ref must match that record; request/target/final
prompt identities must match too. Missing/mismatched fields reject before import.
Legacy non-S3 receipts retain their old exact shape.

Existing immutable raw import, partial-transaction refusal, unknown-result pause and
exact replay behavior remain. A committed old receipt can be replayed read-only while
a newer attempt waits; it cannot consume or replace the newer attempt. `candidate_hash`
always hashes the **raw returned bytes**, never a derivative or metadata-restored file.
S3 deliberately archives even an unsupported/unreadable image return as raw transport
evidence; protocol_status validated is **not** image validity, color validity or quality.

## Candidate color/geometry derivative

```json
{"derivation_id":"d1","encoding":"auto","encoding_basis":"embedded_metadata",
 "display_assumption":null}
```

- auto accepts recognized supported embedded sRGB/Display-P3 ICC or an actual PNG
  sRGB tag, then validates container/profile consistency through the existing audit.
  RGB mode alone establishes no encoding. Untagged auto output is blocked_unknown_encoding.
- Explicit srgb/display_p3 uses encoding_basis explicit_output_declaration, with
  display_assumption null. This is a caller output declaration, not remote proof;
  conflicting/unsupported ICC/container metadata still rejects derivation.
- Unknown uses encoding_basis unknown. With display_assumption null exact
  standardization is blocked. With explicit srgb display assumption the result is
  assumed_display_only: no numerical analysis is created. Auto may also use this
  assumption only if no known encoding can be established.

A successful separate candidate_derivative record includes raw response/hash binding,
native dimensions, EXIF orientation, native bit depth and pixel hash, ICC/color
evidence, conversion chain, RGB8 derivative hashes, unclipped full-precision analysis
when eligible, and explicit clipping/quantization information. RGB16 is read by the
existing exact decoder, not Pillow's downcast. Unsupported RGB16 orientation is refused
rather than silently normalized. A failed/blocked derivation has no claimed usable audit;
raw bytes remain, and partial derivative artifacts are retained but not called usable.
Use a new dN for an explicitly revised derivation; the same ID cannot be relabeled.

There is **no resize/crop to A** or geometric normalization beyond declared supported
EXIF orientation. Same dimensions only set size_matches_A; spatial_correspondence is
always unverified and true C-coordinate evidence is required for later region measures.
Style is not_evaluated, numeric support remains uncertain, and no ABC score, acceptance,
selection, training label or feedback update is performed. Private AcceptancePolicy,
source metadata prose, raw diagnosis and revision rationale never enter edit instructions.
