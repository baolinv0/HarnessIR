"""End-to-end file handoffs with no paid calls or checkpoints."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from PIL import Image
import pytest

from hre.models import HREError
from hre.search import review, study
from hre.search.texture import assess, measure
from hre.storage import read_json, write_json
from hre.v3.dispatch import compile_condition, seal_generation
from hre.v3.common import save_outputs
from test_hre_v3_runner import Workers

THRESHOLDS = {"luma_p95": 8, "chroma_p95": 8, "new_clipping_fraction": 0.005}
GOOD = {"preservation": "no_visible_conflict", "texture": "improved",
        "artifact": "none", "evidence": "Existing fabric weave is clearer."}


def config_files(tmp_path):
    samples = []
    for index, split in enumerate(study.SPLITS):
        path = tmp_path / f"{split}.png"
        Image.new("RGB", (32, 32), (60 + index,) * 3).save(path)
        samples.append({"id": split, "scene": split, "split": split, "source": path.name,
                        "regions": [{"id": "cloth", "role": "target", "source_box": [0, 0, 0.5, 1]}]})
    manifest = tmp_path / "manifest.json"
    write_json(manifest, {"profiles": ["minimax_h3", "qwen21"], "seeds": [7, 20], "samples": samples,
                          "thresholds": THRESHOLDS, "calibration_note": "Software-only fixture"})
    config = tmp_path / "runtime.json"
    write_json(config, {"stage": {}, "models": {
        "minimax_h3": {"compiler": {"backend": "direct"}, "editor": {"model_id": "MiniMaxAI/MiniMax-H3-Image"}},
        "qwen21": {"compiler": {"backend": "direct"}, "editor": {"model_id": "Qwen/Qwen-Image-2.1"}},
    }})
    return manifest, config


class TextureFixture(Workers):
    def execute(self, request, condition, config, outdir):
        self.executions.append(deepcopy(request))
        with Image.open(Path(request["inputs"][0]["path"])) as opened:
            image = opened.convert("RGB")
        if "Fine weave only" in condition["text"]:
            low = image.getpixel((0, 0))[0]
            image.putdata([(low + (8 if (x + y) % 2 else -8),) * 3
                           for y in range(image.height) for x in range(image.width)])
        result = save_outputs([image], outdir, {"image_calls_attempted": 1, "image_calls_completed": 1})
        return seal_generation(request, condition, config, result, output_dir=outdir)


def rating_packet(root, tmp_path, split, profile, names):
    out = tmp_path / f"review-{split}-{profile}"
    receipt = review.make_review(root, split, profile, names, out)
    ratings = read_json(out / "ratings.template.json")
    ratings.update(reviewer="independent fixture", ratings=dict.fromkeys(ratings["ratings"], GOOD))
    return receipt, ratings, out


def test_manual_loop_uses_same_budget_unverified_images_and_frozen_holdout(tmp_path):
    manifest, config = config_files(tmp_path)
    root = tmp_path / "private"
    study.initialize(root, manifest, config)
    proposal = {"id": "weave", "parent": "baseline", "hypothesis": "Constrain H3 to existing texture.",
                "model_overrides": {"minimax_h3": {"instruction": "Fine weave only."}}}
    record = study.register(root, proposal)
    assert record == study.register(root, proposal)
    assert record["policies"]["qwen21"]["instruction"] == ""
    assert record["policies"]["minimax_h3"]["instruction"] == "Fine weave only."
    with pytest.raises(HREError, match="test_locked"):
        study.run(root, "test", "minimax_h3", "baseline")

    model = TextureFixture(accept_after=1)
    workers = {"execute_fn": model.execute, "stage_fn": model.stage, "compile_fn": compile_condition}
    for split in ("dev", "selection"):
        for name in ("baseline", "weave"):
            first = study.run(root, split, "minimax_h3", name, **workers)
            assert first["accepted"]
            calls = len(model.executions)
            assert study.run(root, split, "minimax_h3", name, **workers) == first
            assert len(model.executions) == calls
            assert first["cases"][0]["budget"]["generations"] == 2
        assert [row["seed"] for row in model.executions[-4:]] == [7, 20, 7, 20]
        assert len({row["original_input_sha256"]["source"] for row in model.executions[-4:]}) == 1
        receipt, ratings, out = rating_packet(root, tmp_path, split, "minimax_h3", ["baseline", "weave"])
        assert set(read_json(out / "review.json")) == {"packet", "cases"}
        report = review.score(root, ratings)
        assert report["versions"]["baseline"]["selected_improved_rate"] == 0
        assert report["versions"]["weave"]["eligible_pool_rate"] == 1
        assert report["versions"]["weave"]["selected_improved_rate"] == 1
        if split == "dev":
            with pytest.raises(HREError, match="promotion_requires_selection"):
                review.promote(root, "minimax_h3", "weave", receipt["packet"], "Software test")
            feedback = tmp_path / "feedback"
            review.export_feedback(root, receipt["packet"], feedback)
            exported = read_json(feedback / "feedback.json")
            assert exported["traces"]["weave"]["dev"]["conditions"]
            assert all((feedback / row["native"]).is_file() for row in exported["images"].values())
            assert all("offline_reference" not in row for row in exported["cases"].values())
        else:
            with pytest.raises(HREError, match="feedback_dev_only"):
                review.export_feedback(root, receipt["packet"], tmp_path / "forbidden")
            review.promote(root, "minimax_h3", "weave", receipt["packet"], "Qualified gains")
    locked = study.freeze_final(root, "Finish the search")
    assert locked["active"] == {"minimax_h3": "weave", "qwen21": "baseline"}
    assert study.run(root, "test", "minimax_h3", "weave", **workers)["accepted"]
    with pytest.raises(HREError, match="test_locked"):
        study.run(root, "test", "qwen21", "weave", **workers)
    with pytest.raises(HREError, match="search_frozen"):
        study.register(root, {**proposal, "id": "after-freeze"})


def test_scene_split_cannot_reuse_a_scene_or_edit_study_artifacts(tmp_path):
    manifest, config = config_files(tmp_path)
    value = read_json(manifest)
    value["samples"][2]["scene"] = value["samples"][0]["scene"]
    write_json(manifest, value)
    with pytest.raises(HREError, match="study_split_leak"):
        study.initialize(tmp_path / "private", manifest, config)


def test_texture_roi_detects_balanced_tone_shift_and_does_not_reward_copy(tmp_path):
    lq = tmp_path / "lq.png"
    output = tmp_path / "result.png"
    original = Image.new("RGB", (64, 64), (60, 60, 60))
    original.save(lq)
    altered = Image.new("RGB", (64, 64), (120, 120, 120))
    altered.paste((0, 0, 0), (0, 0, 32, 64))
    altered.save(output)
    regions = [{"id": "shadow", "source_box": [0, 0, 0.5, 1]}]
    observed = measure(lq, output, regions, THRESHOLDS)
    assert {row["check"] for row in observed["violations"] if row["region"] == "shadow"} == {
        "luma_p95", "new_clipping_fraction",
    }
    assert assess(observed, GOOD, False)["severe"]
    assert not assess(measure(lq, lq, regions, THRESHOLDS), GOOD, False)["eligible"]


def test_positive_selection_cannot_compensate_for_severe_regression(tmp_path):
    manifest, config = config_files(tmp_path)
    root = tmp_path / "private"
    study.initialize(root, manifest, config)
    study.register(root, {"id": "bad", "parent": "baseline", "hypothesis": "Synthetic severe error",
                          "policy": {"instruction": "Fine weave only."}})
    worker = TextureFixture(accept_after=1)
    for name in ("baseline", "bad"):
        study.run(root, "selection", "minimax_h3", name, execute_fn=worker.execute, stage_fn=worker.stage)
    receipt, ratings, _ = rating_packet(root, tmp_path, "selection", "minimax_h3", ["baseline", "bad"])
    binding = read_json(root / "reviews" / receipt["packet"] / "binding.json")
    for alias, row in binding["entries"].items():
        if row["version"] == "bad":
            ratings["ratings"][alias] = {**GOOD, "preservation": "conflict", "evidence": "A legible marking changed."}
    report = review.score(root, ratings)
    assert report["versions"]["bad"]["severe_rate"] == 1
    assert report["versions"]["bad"]["unresolved_rate"] == 1
    with pytest.raises(HREError, match="promotion_criteria_failed"):
        review.promote(root, "minimax_h3", "bad", receipt["packet"], "Invalid try")
