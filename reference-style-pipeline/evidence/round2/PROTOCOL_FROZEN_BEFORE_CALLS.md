# A01 mapping/rendering package: two-call image screening

2026-11-01. Planned before either new image call. Independent code/semantic gates
must finish before parent execution. This file does not dispatch anything.

## Question and fixed contrast
Hold the original actual AB diagnosis fixed (SHA df1bff1910bdae9fca2620ab3eb7b03a66b58661e87ea8ebb8fcd89538131619).
Compare the legacy mapping/rendering package against the faithful excerpt package.
No diagnosis rewrite, user-feedback insertion, aesthetic correction or refinement.
Both preserve the same18 goal identities and original prose meaning.

- Baseline: exact old6696-byte prompt, SHA c82adf7f5b510c8ccb25b7e70abbe262fa991ab2906d368c42781633693cfa4a.
- Treatment:6238-byte prompt, SHA e728f79723f4542a16ca8515529c8f978bfcca7a089be1e0336f50426a2f7b74.
- Treatment removes mapping-added intensity labels, deduplicates15 excerpts with
  all18 associations, regroups headers and uses a new explanatory intro. This is
  a **joint mapping/rendering package**, not isolation of strong vsdup or wording.
- Original historical C is descriptive context only, not a fresh baseline repeat
  and not runner/evaluator input.

## Actual input/executor controls
Exact same FOUR ordered attachments for both new calls: historical A content PNG,
B reference PNG, A localization-only guide, B localization-only guide. All four
file hashes were restored byte-exact and independently checked. The same original
whole-region supports underpin both guides; no fabricated bbox masks or changed
localization evidence. No resize/crop/preprocessing by the caller.

Executor: builtin tools.image_gen__imagegen via the parent current dialog, with
`transparent_background=false` and the four exact absolute `referenced_image_paths`.
Use the complete stored prompt string, no added parent instructions or extra
conversation images. Do not use num_last_images_to_include. Exact model version,
seed, internal image processing and sampling settings are unknown/uncontrolled.
Even with identical tool arguments, internal/session equivalence is not guaranteed.

Fixed order: fresh baseline first, fresh treatment second, exactly one each. This
is not randomized and can be confounded by stochastic/order/internal state effects.
Record actual prompt/image hashes, tool-return reference, raw local path and any
known duration; do not invent unavailable model/version/seed/cost. The old closed
run budget is untouched: this is a NEW experiment ledger with2 image-call slots.

## Budget and stopping
Maximum2 image calls. Each planned arm has one reserved slot. A failed or unknown
call consumes its slot; unknown means pause and resolve, not repeat. No additional
candidate, best-of sampling, adaptive revision, post-processing retouch or fallback
A-as-success. Raw outputs are preserved byte-for-byte; display copies, if needed,
are separate with native dimensions/encoding/orientation recorded. No silent
sRGB assumption, geometry alignment, crop or pixel-scale matching.
This ceiling controls the parent's planned tool actions, not hidden provider
sampling, monetary spend or arbitrary external actions. Evaluation is not another
image generation. Stop after the paired screening record and its evaluation.

## Evaluation (distinct questions, not a single hidden aggregate)
1. **Reference-match/content review:** evaluator sees neutral output IDs plus the
   same A/B, not arm mapping, edit prompt, historical C or earlier result claims.
   Freeze image-first observations before numerical summaries. Evaluate actual B
   tone/color/brightness/material appearance, whole-region relationships, A
   identity/expression/layout/geometry/text/texture preservation and naturalness.
   Keep unknowns and trade-offs visible. This is label-blind; image appearance or
   reviewer/model-family bias can still reveal or influence conditions.
2. **Prompt compliance:** separately compare each output with the actual associated
   goal/prompt, including original diagnosed prose intensity. Determine whether
   the executor followed the instructions. This reviewer can see the relevant
   prompt, so cannot be claimed fully blind to condition. High compliance need
   not mean high B match; diagnose that distinction explicitly.
3. **Exploratory numbers:** only after image-first freeze. Record each raw C's real
   encoding. If unknown, an explicit sRGB-assumption analysis may be informative
   but is non-calibrated/noneligible, not exact color acceptance. Use actual native
   C supports (fresh real segmentation or clearly labeled coarse annotations),
   frozen without favorable-mask selection; never resize A/B masks onto C. Report
   support/visibility differences. Compare same metrics/directions for both arms,
   without selective ranges or fresh tolerances. Numbers do not overrule visible
   disagreement or establish spatial correspondence.

The fixed diagnosis may itself be imperfect. No key-error flag or AI preference
proves precise color truth or human acceptance, especially for subtle dark-yellow
material appearance. If prompt compliance improves while B match does not, do not
report the mapping as solving the reference problem.

## Inference limits and next decision
One pair, one fresh output perarm, unknown seed/model details, same model-family
AI evaluation and possible order effects: a positive result is provisional
screening, not causal certainty or stochastic confidence. No claim of Base-domain,
batch/training improvement or general superiority. Replication/held-out examples
may be proposed AFTER findings, not silently run now. Separating strength-label,
deduplication and header effects requires later one-at-a-time contrasts.

The parent executes after gates; author prepares only. Immutable protocol/prompts
and pre-call hashes are separate from actual receipts/results added afterward.
