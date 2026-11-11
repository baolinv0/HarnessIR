# Independent review handoff

**Status: independent code review has not run.** The builder and coordinating context completed implementation tests and integration checks. They are not the reviewer requested by the user. No merge or review request has been issued.

## Exact scope

- Repository: `baolinv0/HarnessIR`.
- Required base branch: `codex/reference-unified-20261101`.
- Reviewed and observed base commit: `90283e5189160c4c6e3429ddfa48f04d5bc27dfd`.
- Implementation branch: `codex/evidence-sr-v02-20261111`.
- Fixed published runtime/tests commit: `22dd603b7f661608bb78b33df2f6a9043ec3a950`.
- Locally executed runtime/tests commit: `f94dfcda6ced7bcc819b936843949e23a48436ab`. Both commits have exactly the same complete Git tree, `fae71799792a378536d6f4e0cfec2f788df0d85b`; only commit metadata differs. The connected GitHub application published the verified tree after shell Git lacked credentials.
- The accompanying delivery commit adds only documentation, examples and verification evidence. Record its exact SHA from the delivery response and `git rev-parse HEAD`; runtime/tests must still match the implementation commit.
- Pstack source: `backnotprop/pstack@08547969e1dffaa6457ea65141cc62c1d9a2eef1`.

Use a fresh conversation/context and a separate clean checkout. Read [PLAN_REVIEW.md](PLAN_REVIEW.md), [RUNBOOK.md](RUNBOOK.md) and [VALIDATION.md](VALIDATION.md). The private conversation linked by the user was unavailable; the six explicit requirements recorded in the plan are the accessible acceptance scope. `main` is not the review baseline.

```bash
git rev-parse HEAD
git diff --exit-code 22dd603b7f661608bb78b33df2f6a9043ec3a950 HEAD -- engine/src engine/tests
git diff --stat 90283e5189160c4c6e3429ddfa48f04d5bc27dfd HEAD
python -m pytest engine/tests -q --durations=15 -o faulthandler_timeout=120
python docs/evidence_sr_v02/evidence/verify_cli.py --out /tmp/sr-review-cli.json
```

A branch may move later; use the fixed delivery SHA supplied in the handoff response rather than silently trusting its name.

## Review priorities

| Requirement | Observable behavior to challenge |
| --- | --- |
| Opt-in SR contract | 256x256 must remain 1024x1024 from native content through delivery and formal selection. Odd/non-square inputs, declared padding/crop, unsupported scales, alpha and source mutation must behave explicitly. |
| Formal result | Hard-invalid or content-failed candidates never become the formal output. With no accepted improvement, only qualified Y0 may be used; otherwise output is null and unresolved. |
| Bound evidence | Actual Judge transport includes source/candidate/Y0/ROI/method identities. Missing, failed, stale and modified evidence cannot pass. Proxies do not certify authentic high-frequency detail. |
| Four real recipes | C0 RealESRNet; C1 original-source prefilter plus the exact same reconstruction settings/seed; C2 actual SeeSR; C3 native Qwen LR-to-HR. Missing deployment and actual failure stay distinct. No fixture impersonates model success. |
| Paired Judge | Anonymous candidates, common Y0 and frozen original-coordinate ROIs. Exact image bytes, order and layout are shared; only evidence text changes. GT, local paths and candidate model identities stay out of online requests. |
| Experiment and cost | Real dev8 is required before an anchored condition freeze and disjoint test16. Pool availability, independent oracle coverage, selection error, fallback, unresolved, failures, submissions and observed costs are separate. |
| Recovery | Unknown submitted calls never repeat automatically. Check crashes around marker/journal/receipt writes, completion recovery and explicit abandonment. Artifact changes during Judge evaluation must block final selection. |
| Compatibility | Existing x1 contracts remain unchanged. The only modification to their entrypoint is the explicit SR dispatch. |

The original x1 `_finish` still has its historical unaccepted-output behavior. This version isolates SR from that path instead of changing the requested compatibility contract. Flag a defect if the new SR path exposes that behavior, rather than demanding an unrequested migration of old x1 records.

## Pstack review approach

Read the specified `how`, `interrogate`, `architect`, feature and shipping files at the fixed pstack commit. Apply their relevant ideas under the user's permissions and repository rules. For each claimed defect, retain a runnable test/probe, exact command, actual output, required output and affected code location. Re-run findings against the fixed reviewed commit. Distinguish a verified failure from an unexecuted risk and from an already-declared environmental limitation.

Do not call same-model parallelism a multi-model review. No full pstack installation, arena comparison or Cursor cloud verification is claimed. An approving test result from the author is not an independent shipping verdict.

## Known limits to preserve in the review

- No real GPU inference, deployed Judge call, real dev8/test16 quality result or later x1 experiment was produced.
- The actual local model adapters and official argv/pipeline guards have software tests; their success with real checkpoints remains to be established on the user's GPU deployment.
- Initial proxies and the C1 prefilter are provisional development choices.
- The profile is x4 only and requires opaque SDR inputs/outputs.
- Offline oracle labels are optional and human-supplied. GT is metadata-only; automatic GT metrics and annotation are outside this implementation.
- The local regression environment is recorded explicitly and does not claim to reproduce the repository dependency-lock environment or Windows/GPU CI.

Return a verdict tied to the exact commit and the reproducible findings. Do not merge, upload private images, run paid external inference or change runtime code as part of this read-only review unless the user authorizes the next step.
