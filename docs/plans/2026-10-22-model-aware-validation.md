# Validation record — 2026-10-22

Base: `25112d624b161dd3960b410d11f8c1bd4563f9e9`, branch
`feat/reference-enhance-generative-v2-20261015`.

## Completed checks

- Existing engine regression plus new core/handoff/runner/worker tests:
  **448 passed, 1 failed**. The failure reproduced subprocess timeout leaving a
  child process alive. It was fixed by terminating the POSIX worker process group.
- After that fix, the complete affected/new module set
  (`test_hre_native_editor`, `test_hre_model_workers`, `test_hre_model_aware`,
  `test_hre_model_runner`) passed: **85 passed**. This includes the failed
  child-process regression, real local HTTP/subprocess transport, and the new
  native executor contract tests. The full suite was not rerun after this focused
  verification; the other 448 checks were already green.
- `model_aware_demo.py` ran through real subprocesses: independent stage check
  succeeded; full case reached `COMPLETED`; one generation charged; no learned
  model called. The `stage-compare` CLI produced a self-contained HTML comparison.
- `git diff --check` passed.
- Wheel build passed; inspection confirmed all four profile JSON resources and
  the native executor module are included in the distribution.

## Review fixes included

- Use a valid API provenance transport when importing stage results.
- Reject G0/shared and G1/native arm/strategy combinations at admission.
- Bind Qwen PE `positive_prompt` exactly to the executed instruction.
- Reject replay of responses from unsuccessful worker invocations.
- Freeze built-in VLM endpoint/model/timeout without persisting credentials;
  record actual returned model/usage when available.
- Terminate subprocess groups on timeout instead of leaving child inference jobs.
- Account for and archive an editor response arriving after cancellation or pause.
- Keep numeric evidence and workflow bookkeeping out of direct edit instructions.

## Evidence limits

The native editor tests inject fake Torch/Diffusers dependencies to verify call
arguments and receipts. Torch, Diffusers, Transformers and model weights were not
installed in the execution environment. No real Qwen, FireRed, FLUX, Fibo,
PUP/VGL/PE/Recaption inference or image-quality comparison was run. The built-in
local native executor covers Qwen/FireRed; other real compilers/editors use the
documented external worker interface. Profile capabilities remain unmeasured.
