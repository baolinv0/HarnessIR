# Diagnosis-backed qualitative goals (additive v6 extension)

For actual visual-only supports, the earlier numeric-relation mapping could not
express appearance or unequal adjustment strength. This extension is deliberately
small: an explicit operator can select a style excerpt from the **bound AB diagnosis**
and attach it to a whole region or a qualitative relationship. Whole narrative,
source metadata, revision rationale and private AcceptancePolicy are not forwarded.

Existing visual target fields stay unchanged. Optional new field:

```json
"visual_goal": {
  "instruction": "Exact nonempty style excerpt selected from the imported AB text",
  "strength": "strong",
  "relation": null
}
```

For a region, use existing visual_region_id g0/rN. For a relationship set that field
to null and supply relation `{relation_id:"lN",left_region_id:"rN",right_region_id:"rN"}`.
Both distinct endpoints must exist in the frozen support report; an existing relation
ID cannot acquire different endpoints. Strength is strong/moderate/gentle/preserve/
relative, not a numeric gain or calibrated tolerance. judge_type must be visual,
measurement_id null; primary visual dimension/direction and priority retain their
existing enums. A visual instruction may describe appearance across tone and color;
the dimension names its primary review axis, not a restriction to one color channel.

The operator is explicitly authoring an execution goal, not asking the program to
interpret every VLM observation automatically. `instruction` must be an exact
substring (1–2000 characters) of that actual diagnosis. Freeze stores instruction
SHA256, diagnosis record hash and selection_basis. Compilation rechecks the source.
This proves textual provenance, **not semantic correctness** or an automatic safety
guarantee: independent semantic review must check the selected goal against actual
images and preservation. No keyword list or invented global color vocabulary is
claimed to solve semantic judgment. The canonical A-preservation instruction governs
all selected STYLE-ONLY goals; no content/geometry-change permission is introduced.

New compiled prompt version is diagnosis_backed_visual_goals_v1; rich edit exports
use s3_diagnosis_backed_visual_goals_v1. They contain concrete selected instructions,
qualitative strengths and concise actual region locations instead of a large
redundant context dump. Saved typed region_context/assets remain fully bound. Relation
endpoints contribute genuine localization guides. Old target/compiled records and
old prompt versions continue unchanged; never rewrite a previous target.

ABC target_view exposes the same selected meaning, strength, source binding and
endpoint semantics in both image-first and evidence views. It does not turn a visual
goal into a numeric target or create a threshold. Feedback starts from original A/B
and the original rich draft, not C geometry or accepted-history; corresponding rich
feedback prompt versions are supported. No model provider/automatic runner is added.
