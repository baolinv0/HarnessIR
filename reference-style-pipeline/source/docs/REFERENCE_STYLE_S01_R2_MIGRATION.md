# S0/S1 r2 controlled-context migration

`schema_version` is now **reference_style_s01_v2**. R1 archives and their manifest
remain immutable; there is no silent migration of an existing sample directory.
Use a new sample directory and explicit v2 context. Unchanged r1 tests using free
text contexts are intentionally incompatible; they must not be relabeled passing.

## Why the break is necessary

Exact field allowlists plus keyword filtering did not prevent posthoc tolerance
prose in descriptions, evidence reasons or feedback. V2 rejects those fields,
not just specific paraphrases. There is no generic string-to-instruction bridge.
All executable controls use typed enums/numbers/references. No unconstrained
region label, reference description, upstream metadata or raw diagnosis is copied.
Private AcceptancePolicy changes cannot modify this projection.

Narrative remains valuable: imported VLM text/JSON is preserved verbatim as the
raw response artifact with request/receipt identity. It remains non-executable
observation material. A later explicit S2 workflow may review it and construct
typed controls; S0/S1 does not silently extract, summarize or forward it.

## Valid context example

```json
{
  "target_version": "v1",
  "targets": [{
    "target_id": "t1", "unit": "global", "region_refs": [],
    "effect": {"dimension": "tone", "direction": "match_B"},
    "numeric_range": null, "judge_type": "visual", "priority": "critical",
    "evidence_ids": ["e1"]
  }],
  "evidence": [{"evidence_id": "e1", "role": "B", "kind": "visual",
                "status": "available", "reason_code": "observed"}],
  "feedback": []
}
```

IDs are bounded positive numeric codes: target `t1`, evidence `e1`, version `v1`
(up to six digits); they cannot be a hidden prose channel. Region refs contain
only `role`, `semantic_class`, `instance_index` (integer 1..10000). Global targets
have no refs; object/material targets have A then B; relationships have A,A,B,B
for the respective pair of endpoints. These are reference slots, not proof of
instance matching, pixel correspondence or valid measurement support.

Semantic classes: person, face, exposed_skin, hair, clothing, sign, wall, sky, foliage, ground,
building, vehicle, water, food, furniture, metal, wood, glass, fabric,
other_whole_object, other_whole_material. `face` means the complete semantic face;
`exposed_skin` means the complete exposed-skin/material region. Both are valid
whole-region color/tone targets, never facial reconstruction permissions. No
custom labels, face-shadow/highlight or landmark/part-specific subdivisions.

Effects for non-relations: tone, color, brightness, contrast, chroma, warmth.
Relation effects: relative_brightness, relative_warmth, relative_chroma. Directions:
match_B, increase_toward_B, decrease_toward_B. Fixed preservation always requires
A's content/spatial consistency and jointly edited complete frame.

`numeric_range` is null or `{metric, lower, upper}` with finite ordered numbers;
requires numeric/mixed judge. Metrics and supported ranges: linear_Y [0,1],
L_star [0,100], a_star/b_star [-200,200], chroma [0,300]. This transports a frozen
style range but does not implement S2 support validation or assert achievement.
Unknown A still blocks numeric/mixed execution preparation.

Evidence `reason_code`: observed, not_installed, not_collected,
coverage_insufficient, correspondence_uncertain, encoding_unknown. Evidence kind
and status enums are unchanged. Missing tools remain unavailable/uncertain,
not a fabricated tool result or automatic rejection of coarse visual preparation.

Feedback: `{target_id, candidate_record_id, candidate_hash, observation_code}`.
Use the actual imported response's top-level `record_id` (response_ plus 32 hex
digits) and payload `candidate_hash`. The record must be a validated edit in this
sample with exactly the same target version/hash and intact raw/receipt artifacts.
Unknown, foreign, stale or tampered references reject. Re-evaluation after target
revision is not implemented, so old-target feedback is explicitly unavailable.

Observation codes: too_bright, too_dark, too_warm, too_cool, too_saturated,
too_muted, tone_residual, relationship_residual, content_spatial_deviation,
spillover, uncertain. The fixed instruction for content_spatial_deviation is to
restore consistency with original A, never to retain or reproduce that deviation.
There is no tolerance/permission/accepted-deviation code.

## Transport/format corrections

- Exact committed receipt/output replay is an idempotent read; a newer active
  attempt is left unchanged. Different attestation/output for the old request
  rejects. Incomplete raw_response.bin, receipt.json or response.json is immutable
  and blocks import for explicit same-attempt reconciliation.
- PNG8/PNG16 tRNS rejects under opaque-only contract. cHRM must match declared or
  explicitly assumed primaries. cICP only supports consistent full-range RGB SDR
  sRGB/P3; HDR/limited-range/unknown coding rejects. mDCV/cLLI and animation reject.
  Applicable metadata is recorded rather than silently ignored.
- R3 refinement: present iCCP must decompress completely to a supported, valid
  ICC payload before any audit output is written. Empty/truncated/malformed data
  or inconsistent decoder metadata rejects as an input error, never as absent ICC.
- R1 independent test sources are untouched. Their context helper needs the above
  v2 schema, plus feedback references from actual imported response records.
  Old malicious prose tests should continue asserting rejection of old fields;
  migrated positive tests should assert useful typed controls and actual payloads.
