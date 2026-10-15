# Independent SAM3.1 evidence integration

`gpu_sam31_v5` keeps the actual remote inference v5 contract separate from
original SAM3 formal evaluation. `formal_eligible` is always false. The current
normalizer parameter is `sam31_stream_lossless_png_v2`; the earlier NPY-backed
v1 cache and case snapshots are preserved, and their cache keys differ.

From the project root, import two small validated native results first:

```powershell
& .\engine\.venv\Scripts\python.exe .\engine\scripts\import_sam31_evidence.py --image-id HC_RAIM_Phase1_011 --image-id commons_002
```

Then import the real paired-study photograph:

```powershell
& .\engine\.venv\Scripts\python.exe .\engine\scripts\import_sam31_evidence.py --image-id commons_001
```

After visual review, omitting `--image-id` imports all twenty frozen inputs;
repeat invocations independently verify the source and reuse complete matching
entries. No model runs, downloads, installation, endpoint changes, or image
edits occur. An imported-only cache miss is recorded as unavailable and blocks
the strict evidence plan; manual import remains available.

The importer verifies the independently frozen input ZIP and received result
ZIP hashes, official weight/source locks, environment freeze, exact raw run and
contract, source dimensions/hashes, strict detector load, worker release, and
full native mask content. The normalized PNG masks are compared pixel-for-pixel
against the unchanged original NPZ before publication and on reuse.

Normalized evidence enters `Data/annotations/cache/T4_SEGMENTATION/<cache_key>`
with the existing lock, asset validation, atomic publication, and ready marker.
The native NPZ and metadata are retained byte-for-byte as hashed raw assets.
Original unclipped boxes remain in native metadata and the normalized native
sidecar; canonical boxes are clipped and mapped to `[0,1]` coordinates.

One instance and one class union are processed at a time. Lossless 0/255 PNG
represents the native boolean masks exactly at threshold 0.5, avoiding duplicate
multi-GiB uncompressed per-instance arrays. Instance overlaps are retained;
display winners follow score, prompt index, then instance ID. Fixed class colours
and an actual PNG legend accompany the semantic map. Only the semantic map and
legend are Composer image assets; individual masks, class unions, label IDs,
overlap, provenance, and NPZ remain raw assets. Executor receives only the
original canonical photo and editing text. T1–T3 profiles, registries, cache
contracts, and approved original GPU provenance are unchanged.

Targeted checks:

```powershell
& .\engine\.venv\Scripts\python.exe -m pytest .\engine\tests\test_sam31_evidence.py .\engine\tests\test_yoloe_alternative.py .\engine\tests\test_local_tools_flow.py -q -p no:cacheprovider
```

These are protocol/storage tests, not model accuracy or restoration acceptance.
Real import/visual review, Composer, actual edited output, and independent
Verifier must be recorded separately by the study controller.
