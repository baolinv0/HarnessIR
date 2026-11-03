# Source and compatibility provenance

- Engineering base: `9073086bd86cff3062eab65bcbc32da6e4fd2114`, reference-retouch branch. Its implemented code is the same as `16dee77487e4e13f76963f48bc4611d046bd0afe`; the later change is the 1247-line modification plan.
- Imported evidence source: `6adfd0ba7054d453662df7e91c93f547a85e6fdc`, only `reference_style/*.py`, its public Python tests and required pure color implementation. Original commit bytes and per-file import hashes are in IMPORTED_SOURCES.json.
- `color.py` is relocated into reference_style to avoid installing the unrelated tool-retouch application. Audit imports are updated accordingly.
- Exact-byte UTF-8/LF fixture writes, POSIX stored asset paths, narrowly capability-skipped Windows symlink creation, and major-damage precedence repair are intentional changes after import.
- Existing project MIT license and upstream HarnessIR academic attribution remain in place. No private photos, masks, historical C pixels, model weights, credentials or raw user runs were copied into source.
- Old `hre` modules/templates are retained. New behavior is selected explicitly by reference_retouch_v2, reference_retouch_delivery_v3 or separate unified semantic records; historical schema strings are not silently relabelled.
