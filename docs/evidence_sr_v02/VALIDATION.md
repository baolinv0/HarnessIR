# SR v0.2 implementation validation

## Version and review status

- Repository: `baolinv0/HarnessIR`.
- Required base: `codex/reference-unified-20261101` at `90283e5189160c4c6e3429ddfa48f04d5bc27dfd`. The fetched branch head matched this reviewed base; `main` was not used.
- Isolated implementation branch: `codex/evidence-sr-v02-20261111`.
- Fixed published runtime and tests: `22dd603b7f661608bb78b33df2f6a9043ec3a950`.
- Locally executed runtime and tests: `f94dfcda6ced7bcc819b936843949e23a48436ab`. Both commits have the identical complete tree `fae71799792a378536d6f4e0cfec2f788df0d85b`; the different commit IDs reflect publication metadata, not different file contents.
- The final delivery commit adds documentation, examples and these verification records. Its full SHA is supplied in the delivery response. The runtime and tests remain byte-identical to the fixed implementation commit.
- Pstack reference: `08547969e1dffaa6457ea65141cc62c1d9a2eef1`.

The implementation was delegated to a fresh builder context after plan review. The coordinating context performed baseline probes, integration checks and the recorded regression runs. **The user's separate independent code review has not run.** The code is handed off for that step, without merging the reference branch or `main`.

## Observed checks

All results below are software checks on synthetic inputs or unavailable-deployment paths. They are not measurements of real restoration quality.

| Check | Observed result | Evidence |
| --- | --- | --- |
| Unchanged baseline suite at `90283e5` | 1015 passed, 186 subtests passed, 4 warnings; 579.97 seconds | [baseline_pytest.txt](evidence/baseline_pytest.txt) |
| New SR behavior suite at `f94dfcd` | 190 passed; 23.50 seconds | [sr_targeted_pytest.txt](evidence/sr_targeted_pytest.txt) |
| Complete implementation regression at `f94dfcd` | 1205 passed, 186 subtests passed, 4 warnings; 515.09 seconds | [implementation_pytest.txt](evidence/implementation_pytest.txt) |
| Public CLI synthetic end-to-end case | 256x256 source; C0–C3 contract-valid; scripted C1 selection is 1024x1024; resume leaves state and journal unchanged | [cli_verification.json](evidence/cli_verification.json) |
| Public CLI with real mode and no deployment | Preflight and run exit 2; all four candidates blocked; unresolved/null result; zero submitted operations and zero real model calls | [cli_verification.json](evidence/cli_verification.json) |
| Editable install and installed `hre sr --help` | Exit 0 | [package_verification.json](evidence/package_verification.json) |
| Wheel build and source-content check | Exit 0; all eight SR modules included, including the official-runtime launcher; their bytes match source | [package_verification.json](evidence/package_verification.json) |
| Original behavior counterexamples | Reproduced at the fixed base using a local Judge transport spy and synthetic images | [baseline_probes_output.txt](evidence/baseline_probes_output.txt) |

The baseline warnings concern the existing fork/multithreading test path. The local environment is Python 3.12.14 on Linux; exact package versions and the absence of Torch are recorded in [environment.json](evidence/environment.json). The repository dependency lock was not edited. These runs do not claim to reproduce the lock environment, Windows CI or GPU CI.

### Publication and identity

The shell `git push` failed before authentication with `fatal: could not read Username for 'https://github.com': No such device or address`. A subsequent remote-ref read confirmed that the new branch had not been created and the reference branch still pointed to `90283e5`. The connected GitHub application then reported repository `push` permission. Its Git data API created the verified code tree with exactly the expected tree SHA and a commit with the same parent/base. The resulting published runtime commit is `22dd603`; the executed local snapshot remains `f94dfcd` in the raw test/CLI/package evidence. [publication_identity.json](evidence/publication_identity.json) records this correspondence. No test result is attributed to different source contents, and no branch was force-updated.

### Commands actually used

The following full suite command ran separately from the detached baseline worktree and the isolated implementation worktree, with the same local interpreter:

```bash
PYTHONPATH=engine/src /workspace/scratch/5a405e7cb038/.venv/bin/python \
  -m pytest engine/tests -q --durations=15 -o faulthandler_timeout=120
```

The new behavior suite was also recorded separately:

```bash
PYTHONPATH=engine/src /workspace/scratch/5a405e7cb038/.venv/bin/python \
  -m pytest \
  engine/tests/test_sr_v02.py \
  engine/tests/test_sr_adapters.py \
  engine/tests/test_sr_evidence.py \
  engine/tests/test_sr_study.py \
  engine/tests/test_sr_receipts_oracle.py -q
```

The CLI verification script starts the public CLI in subprocesses, uses temporary synthetic files, checks the selected artifact dimensions and compares the state/journal before and after resume. Its recorded commands and individual exit codes are in the JSON result:

```bash
/workspace/scratch/5a405e7cb038/.venv/bin/python \
  docs/evidence_sr_v02/evidence/verify_cli.py \
  --out docs/evidence_sr_v02/evidence/cli_verification.json

uv pip install --python /workspace/scratch/5a405e7cb038/.venv/bin/python \
  --no-deps -e ./engine

uv build --wheel --out-dir /workspace/scratch/5a405e7cb038/sr-wheel ./engine
```

The wheel was inspected as a ZIP and all `hre/sr/*.py` entries were compared byte-for-byte with the implementation worktree. The package metadata version remains the repository's existing `0.4.0`; identify this implementation by the commit and `hre_sr_v02` schema, not by that package number alone. The wheel is not a published package release.

## What changed and what was exercised

The only modification to an existing runtime file is the three-line explicit `sr` dispatch in `engine/src/hre/cli.py`. Eight new modules under `engine/src/hre/sr/` own the SR contract, real adapters, numerical evidence, request construction, selection, recovery, reporting and study gate. Five new test modules exercise their public behavior. No general agent framework or replacement x1 runner was introduced.

| Required behavior | Implementation and exercised boundaries |
| --- | --- |
| Independent opt-in LR→HR contract | Strict x4, source/origin/canonical identities, non-square and odd dimensions, per-model padding, exact HR crop, unsupported-scale rejection, opaque alpha policy and mutation detection. The end-to-end fixture verifies 256→1024 through formal selection. |
| Qualified final output | Accepted improvement requires hard-valid output, current evidence and explicit content/improvement decisions. Otherwise a qualified HR Y0 is used; failed, uncertain or missing Y0 produces unresolved/null. Content-failed artifacts and LR inputs cannot become formal SR outputs. |
| Candidate-bound evidence | Source, Y0, candidate, ROI, geometry and method versions/hashes are bound into the evidence. Missing, failed, stale and changed evidence is rejected. Hard checks, soft measurements and visual decisions are distinct. |
| Four real recipes | C0 official RealESRNet, C1 fixed light blur then the same SR/settings/seed, C2 official SeeSR, C3 the existing native Qwen adapter. Independent source preparation, recipe/seed/artifact recording, upstream arguments and output guards are exercised without asserting real model quality. |
| Controlled Judge comparison | Anonymous local alias mapping; shared Y0 and frozen mapped ROIs; byte-identical transmitted image attachments, ordering and layout across both arms; only evidence text differs. Tests inspect the actual common chat request body, not just a pre-serialization dictionary. GT/model identities/local paths are excluded. Invalid or inconsistent Judge responses are unavailable rather than accepted. |
| Recovery and immutable observations | Reuse existing canonical import, locks and Journal. Completed receipts resume without calls. Unknown submissions do not repeat. Marker-before-journal interruption is conservatively recoverable by explicit abandonment, not regeneration. Source, model identity and artifact changes are detected. |
| Study and separate accounting | Exactly eight development and sixteen disjoint test identities, including re-encoding/opaque-alpha duplicate detection. A test phase needs an anchored freeze bound to eight real development observations and the documented failures supporting selected methods. Fixtures, missing deployments and unknown observations cannot open the gate. |
| Offline oracle reporting | Optional independently supplied labels bind case/source/pixels/candidate hashes. Pool quality coverage, selection eligibility failure, matching the preferred candidate, avoidable fallback and avoidable unresolved are separate. No labels means unknown, and labels cannot change the online selection. |

The old x1 `_finish` behavior was demonstrated by the baseline probes and left unchanged to preserve the requested compatibility boundary. The new SR path never delegates its formal result to that function. Passing the x1 regression suite supports compatibility; it does not retroactively fix the historical x1 selection policy.

## Actual environment blockers and unfinished experiments

No actual model or Judge call was made. The executable unavailable-deployment check records these blockers:

- C0/C1: no configured inference Python, RealESRNet checkpoint or official source location in the tested deployment configuration.
- C2: no configured SeeSR Python/source, SD2 base, SeeSR checkpoint, DAPE, RAM or local BERT tokenizer.
- C3: no checkpoint directory, deployment manifest, revision or pipeline version; the local environment also lacks Torch, Diffusers, Transformers, Accelerate and CUDA.
- Judge: no deployed endpoint/model supplied for actual inference.
- Experiment: no real development/test dataset or independent oracle labels supplied.

The separate source checkouts used to inspect upstream behavior are not inference deployments. No checkpoint was downloaded, no GPU output was produced and no private image was uploaded.

Still to be established after independent code review:

1. Deploy the pinned source/weights/runtime identities and verify all four real inference paths and the actual VLM transport on the target GPU system.
2. Run eight real development cases. Select or revise the soft evidence using their recorded failure examples; the current LR consistency, clipping and edge-energy methods and C1 blur are provisional.
3. Freeze conditions and then run the sixteen disjoint test cases. Collect independent offline labels before reporting pool quality coverage or selection error. The study-level oracle aggregate remains unknown in this version; per-case labeled reports can be aggregated with explicit denominators.
4. Measure actual latency, token usage and monetary cost when those observations exist. Missing costs are not treated as zero.
5. Conduct subsequent x1 restoration experiments under a separately reviewed protocol.

This profile supports x4 opaque SDR only. Other scales, nonopaque alpha restoration and automatic GT metrics/annotation are not implemented. Optional GT references remain offline metadata and never enter online requests. No claim is made that the initial proxies validate authentic high-frequency reconstruction.

## Pstack application and handoff

[PLAN_REVIEW.md](PLAN_REVIEW.md) records the actual pinned pstack files read and the alternatives considered. `how` informed runtime tracing; `architect` informed the isolated SR boundary and shared invariant owner; `feature` informed separate implementation and behavior checks; `interrogate` informed executable defect probes; `shipping` informed frozen-version verification and the stop before independent review.

The available model family was used for plan/source analysis and implementation. Full pstack installation, different-model/arena review, Cursor review, final independent code review and merge/shipping are not claimed. External instructions did not alter user permissions, confidentiality or repository rules. See [REVIEW_HANDOFF.md](REVIEW_HANDOFF.md) for the fresh-context review scope and commands.
