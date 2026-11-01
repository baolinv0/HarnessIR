# Independent Codex Handoff Review — 2026-11-01

## Decision

**PASS for publishing the reviewed handoff on an isolated branch/subdirectory, subject to the publisher verifying its final archive hash and remote commit.** This review does not authorize new image generation, certify image quality, approve merging, or claim full upstream test coverage.

## Verified locally

1. The initial copied source matched all **364** files in the original frozen manifest. The final public source matches all **364** entries of `verification/source_manifest_public.json`. Differences from the original are limited to two historical documentation/metadata files with private service identifiers removed; functional Python/config/template files are unchanged.
2. All **68** entries in `verification/PUBLIC_REDACTIONS.json` match their declared public SHA256 values. Historical hashes are explicitly source provenance, not claims that sanitized receipts can be imported as originals.
3. Independently executed `PYTHONPATH=engine/src python -m unittest discover -s engine/tests/reference_style -p 'test_*.py' -v` from the handoff `source/`: **175 tests passed in 37.353 seconds**. CLI `python -m hre reference-style --help` also passed. No image model was called. Generated Python caches were excluded from the final tree.
4. Independently checked original bytes and metadata for **A01/B01, A07/B07, A19/B19** against the public data inventory: all six matched file SHA256, byte size, format, native dimensions, frame count, orientation and ICC hash. Reading existing bytes is not a new image experiment. A07/A19 remain unrun in the new pipeline.
5. The reviewed tree contained no photograph/crop PNG/JPEG/WebP, NPY/NPZ masks, model weights, TFLite models, PEM credentials or Python caches. Targeted checks found no live Library/Drive identifiers or common credential patterns after redaction. ICC profile binaries are intentionally present and are not photos. This is a scoped inspection, not a general DLP guarantee.
6. Startup commands are coherent with CLI behavior: run from `source/`, because relative input paths resolve from the working directory, not the config file directory. The example explicitly requires replacement with real verified conversion provenance and private inputs.

## Requirements and evidence review

- Entry documents distinguish implemented S0–S4 and faithful mapping from the manual current-chat diagnosis/imagegen bridge; they do not claim an automatic end-to-end generator or turnkey Qwen/server integration.
- Camera RGB validation is explicitly separate from the future Base-output production domain. Unaligned paired photos are not pixel-aligned ground truth. P3 source profiles, S26 orientation 8, B MPO frame0 policy, explicit sRGB conversion and native-grid support identity are explained.
- Three experiment rounds, single-sample/repetition limitations, unknown generated-C color encoding, same-family reviewers and unknown seed/context remain visible. Round3's old tie is not presented as equivalence or absence of visible gain. Full's observed yellow/chroma improvement and the user's overall naturalness preference are retained without claiming stable method superiority.
- The latest priority is **whole-image B style/tone first, key whole regions and relationships second, local metrics for explanation last**. The new evaluator is clearly unimplemented. Appended section 17 explicitly supersedes the region-first interpretation of historical section 16.4 without rewriting frozen observations.
- Preservation is the prompt objective; tolerated incidental structural deviations remain posthoc acceptance policy, not advance permission to alter content.
- Current plan, code map, data inventory, private acquisition instructions, test commands, next-step acceptance and original/public provenance are sufficient for a new Codex worker to continue without guessing the experiment state.

## Issues found and addressed

- Historical metadata contained six real Drive IDs plus Library IDs: public copies now remove them and record derived hashes.
- A historical design identifier was initially truncated while labeled SHA: corrected to the stated full historical identifier, while the original design document's absence remains disclosed. The unavailable original design itself was not independently hash-verified by this reviewer.
- Broad inherited tool-retouch tests retain historical fixture paths. The handoff now explicitly limits portability/test claims to the documented reference-style path rather than claiming all upstream tests passed.

## Remaining limits

The public package intentionally excludes private A/B/C pixels, masks and models, so image-dependent reruns require private asset recovery and fresh valid supports. No new holistic evaluation was run. No Base-domain, batch, held-out, Qwen, training or server experiment was performed by this review. Git remote upload, archive transfer integrity and the final published commit remain the publisher's responsibility.
