# Evidence-driven SR v0.2 — reviewed implementation scope

Status: plan reviewed; implementation authorized; final independent code review is pending.

## Grounding and scope

The requested branch `codex/reference-unified-20261101` was fetched on 2026-11-11. Its observed head equals the review baseline `90283e5189160c4c6e3429ddfa48f04d5bc27dfd`. Work starts on the isolated branch `codex/evidence-sr-v02-20261111`, not `main`. No existing local changes were present in the new worktree. The private ChatGPT conversation could not be retrieved; this implementation uses the six explicit requirements in the current request. It does not claim to have recovered the full prior SR v0.2 transcript.

Existing boundaries inspected: `v3/contracts.py` canonicalizes and hashes immutable source bytes; `v3/spatial.py` prepares model canvases and returns delivered images to source dimensions; `v3/runner.py::_finish` can publish an unaccepted candidate or source baseline; restoration verification excludes candidate-bound measured evidence; `v3/runner_journal.py` provides recoverable append-only state; `v3/qwen.py::generate` accepts an LR conditioning image and a distinct output canvas.

The baseline counterexamples are executable in [evidence/baseline_probes.py](evidence/baseline_probes.py), with actual output in [evidence/baseline_probes_output.txt](evidence/baseline_probes_output.txt). A second run by the coordinating context against a separate detached baseline checkout reproduced the same four output lines, exit 0. These probes demonstrate software behavior using synthetic inputs and an actual Judge serializer with a local chat spy.

## Decision and alternatives

Two shapes were considered. Extending the existing v3 runner would spread SR branching through task normalization, profile selection, preparation, delivery, verification and terminal selection. A separate opt-in `hre sr` entrypoint owns the SR contract and fixed candidate experiment while reusing the existing canonical asset importer, locks, journal, hash utilities, chat transport and native Qwen adapter. The latter is selected to preserve existing x1 behavior and keep one owner of the SR invariants. This is an integration module, not a replacement agent framework.

Public operations should cover create, run/resume, show/report and frozen-study preparation. Native model and Judge calls must be explicit; import and help must make no model calls. The builder may choose a similarly small CLI surface if all acceptance cases below remain runnable.

## Frozen domain contract

An SR task freezes: contract version, original/canonical source identity, positive integer scale (initial real-model profile x4), LR width/height, target HR width/height, model-specific right/bottom padding, exact inverse crop, alpha policy, original-coordinate ROIs and mapping, ordered recipe table, seeds, model/runtime identities, Judge settings and soft-evidence profile. An unsupported scale or geometry fails explicitly. Output resizing cannot conceal a native model geometry failure. A 256x256 source at x4 must be 1024x1024 in native content, delivery and final selection. Non-square and odd inputs retain their exact scaled content dimensions after declared padding is removed. Reject unsupported nonopaque alpha explicitly rather than silently flattening it.

The four recipe slots are C0 reconstruction Y0, C1 a fixed mild prefilter followed by the exact C0 reconstruction model/settings/seed, C2 SeeSR, and C3 direct Qwen LR-to-HR. Every recipe begins with the immutable original source; C1 has its own recorded derivative. No candidate consumes another candidate. A missing deployment is `blocked`; a failed invocation, unknown submission, contract failure and content failure are separate outcomes. Test adapters must be clearly marked fixtures and cannot produce real-study quality results.

Concrete upstream boundaries were inspected locally and through the GitHub connector: [Real-ESRGAN at a4abfb2979a7bbff3f69f58f58ae324608821e27](https://github.com/xinntao/Real-ESRGAN/tree/a4abfb2979a7bbff3f69f58f58ae324608821e27) and [SeeSR at b13b8ac3bbcc6b9a6baa970ee5349628070877ee](https://github.com/cswry/SeeSR/tree/b13b8ac3bbcc6b9a6baa970ee5349628070877ee). C0 selects the official `RealESRNet_x4plus` MSE-trained model, rather than assuming that the similarly named adversarial model is a reconstruction control. This concrete baseline is an implementation choice because the original conversation was unavailable. Checkpoint bytes and GPU outputs were not supplied or verified. SeeSR must use its separately configured environment; its dependencies conflict with the existing HarnessIR/Qwen environment. Padding removes its hidden small-image and multiple-of-eight resizing from the intended geometry path. Missing RAM, DAPE, SD2, SeeSR or tokenizer resources remain explicit blockers.

## Evidence and decision contract

Hard checks validate identity, decode, dimensions, padding, scale and alpha. They establish delivery eligibility, not faithful recovered detail. Soft measurements are versioned proxies (for example downsample consistency, clipping and edge change), reported with limitations and no quality-pass assertion. Semantic/content preservation and perceptual progress remain explicit visual/learned decisions. Missing, failed, stale or mismatched evidence cannot pass or support an accepted improvement. First-round soft evidence is provisional until selected from documented development failures.

Freeze ROI locations before candidates. Bind each measurement to source, Y0, candidate, ROI definition, geometry and method versions/hashes. Build the source/Y0/anonymized candidate full-frame and ROI attachments once. The visual control and evidence arm must share exact attachment bytes, order and layout, and a single explicit evidence-text field is their only experimental difference. Do not expose recipe/model names, local paths, or GT in online requests. Use a strict allow-list when projecting offline records to Judge input. Archive actual request manifests and observed responses, including failures and costs.

The official selection uses the frozen evidence-arm policy. Only contract-valid, content-preserving, explicitly improved accepted candidates can replace Y0. Otherwise select Y0 only if its hard contract and content assessment pass. If Y0 is missing, invalid, failed or uncertain, the outcome is `unresolved` with no formal output. Never return LR or a content-failed artifact as the formal SR result. Audit artifacts remain available separately.

## Implementation and verification sequence

1. Establish the unchanged baseline suite and executable probes for the observed size/selection gaps.
2. Delegate the code to a separate builder context with exclusive ownership of new runtime files. Keep the SR record/receipt state under one owner; parallel read-only source research is safe.
3. Add behavior tests for size propagation (256->1024, non-square, odd, padding, scale rejection, alpha, modified input), each recipe and failures, acceptance/Y0/unresolved, stale evidence, anonymization/GT exclusion, paired actual Judge transport snapshots, resume and no repeat of unknown calls.
4. Run an end-to-end synthetic CLI fixture, all existing engine regressions and package/CLI checks. Fixtures prove implementation behavior, not restoration quality.
5. Publish a fixed implementation version with exact checks and blockers, then stop for the user's independent code-review window. Author/integration checks do not count as that review; do not merge.

Experiment accounting must separately record produced/valid/accepted pool coverage, selection, incorrect selection only where an offline oracle exists, fallback/unresolved, failures, call/latency/token/cost observations. Unknown quality and cost values remain unknown. Complete 8 development cases, document observed failures and select soft evidence, then freeze conditions before a disjoint 16-case test. If data, GPU, weights or Judge are unavailable, leave these phases pending. x1 restoration experiments follow SR.

## Pstack use and adaptations

Read from `backnotprop/pstack@08547969e1dffaa6457ea65141cc62c1d9a2eef1`: `skills/how/SKILL.md` and explorer/explainer references; `skills/interrogate/SKILL.md`; `skills/architect/SKILL.md`, runner/rationale/red-flag references; `skills/poteto-mode/SKILL.md`; feature and shipping playbooks.

Applied: trace the existing runtime before placement (`how`), compare two structural alternatives and decide ownership before implementation (`architect`), delegate implementation and verify observable behavior (`feature`), demand runnable counterexamples for defect claims (`interrogate`), tie final checks to a fixed patch and reserve shipping for independent review (`shipping`). The plan audit is separate from the builder but uses the available model family. No full pstack installation, arena multi-model comparison, Cursor cloud review, independent final review, or shipping/merge is claimed. User permissions and repository rules override external skill autonomy and publication instructions.

Throughput checkpoint: baseline/interface decisions precede implementation; read-only adapter research and plan audit are independent; only the builder writes coupled SR runtime state; one runtime owner is the smallest safe decomposition because geometry, evidence and selection share a frozen case. Review evidence and runbook can be produced separately after interfaces stabilize.
