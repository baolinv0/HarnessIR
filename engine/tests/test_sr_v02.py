"""Builder-side SR orchestration checks. Fixtures make no restoration-quality claim."""
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter
import pytest

from hre.models import HREError, file_sha256
from hre.storage import read_json, write_json
from hre.sr.contracts import FIXTURE_MARKER, PROTOCOL_VERSION
from hre.sr.runtime import create_case, reconcile_unknown, report, run_case


SLOTS = ("C0", "C1", "C2", "C3")


def fixture_config(*, candidates=None, content=None, improved=None, ranking=None):
    return {
        "mode": "fixture",
        "fixture_marker": FIXTURE_MARKER,
        "fixture": {
            "candidates": {slot: "ok" for slot in SLOTS} | (candidates or {}),
            "judge": {
                "content": {slot: "pass" for slot in SLOTS} | (content or {}),
                "improved": ["C1"] if improved is None else improved,
                "ranking": ["C1", "C2", "C3"] if ranking is None else ranking,
            },
        },
    }


def source_image(path, size=(35, 23)):
    width, height = size
    y, x = np.mgrid[:height, :width]
    pixels = np.stack(((x * 17 + y * 5) % 256, (y * 19) % 256, (x * 3 + y * 11) % 256), axis=-1)
    Image.fromarray(pixels.astype(np.uint8)).save(path)
    return path


def make_case(tmp_path, *, size=(35, 23), config=None, spec_updates=None, name="case"):
    source = source_image(tmp_path / f"{name}_source.png", size)
    spec = {
        "schema_version": PROTOCOL_VERSION,
        "case_id": name,
        "source": {"path": str(source)},
        "scale": 4,
        "seed": 19,
        "rois": [{"id": "detail", "box": [1, 1, size[0] - 1, size[1] - 1]}],
    }
    spec.update(spec_updates or {})
    root = tmp_path / name
    create_case(root, spec, fixture_config() if config is None else config)
    return root, source


def assert_output(state, slot, size):
    assert state["status"] == "selected"
    assert state["selected_slot"] == slot
    output = state["selected_output"]
    assert (output["width"], output["height"]) == size
    assert file_sha256(Path(output["path"])) == output["sha256"]
    with Image.open(output["path"]) as image:
        image.load()
        assert image.size == size
        assert image.convert("RGBA").getchannel("A").getextrema() == (255, 255)


@pytest.mark.parametrize("size", [(256, 256), (257, 193), (35, 23), (128, 137)])
def test_native_to_selected_geometry_is_exactly_four_times_original(tmp_path, size):
    root, _ = make_case(tmp_path, size=size)
    state = run_case(root)
    assert_output(state, "C1", (4 * size[0], 4 * size[1]))
    assert set(state["candidates"]) == set(SLOTS)
    assert all(candidate["status"] == "valid" for candidate in state["candidates"].values())
    for candidate in state["candidates"].values():
        with Image.open(candidate["output"]["path"]) as image:
            assert image.size == (4 * size[0], 4 * size[1])
    assert state["execution_kind"] == "fixture"
    assert state["quality_claims"] is False


def test_four_recipe_requests_start_from_original_and_c1_reuses_c0_model_settings(tmp_path):
    root, source = make_case(tmp_path)
    run_case(root)
    requests = {slot: read_json(root / "operations" / f"model_{slot}" / "request.json") for slot in SLOTS}
    assert {item["slot"] for item in requests.values()} == set(SLOTS)
    assert len({item["source"]["sha256"] for item in requests.values()}) == 1
    assert requests["C0"]["seed"] == requests["C1"]["seed"] == 19
    assert requests["C0"]["model_settings_sha256"] == requests["C1"]["model_settings_sha256"]
    assert requests["C0"]["model_key"] == requests["C1"]["model_key"]
    with Image.open(source) as original:
        original = original.convert("RGB")
        mild = original.filter(ImageFilter.GaussianBlur(radius=0.35))
        for slot, request in requests.items():
            with Image.open(request["input"]["path"]) as image:
                content = image.convert("RGB").crop((0, 0, original.width, original.height))
                expected = mild if slot == "C1" else original
                assert content.tobytes() == expected.tobytes()
                if slot == "C2":
                    assert image.width >= 128 and image.height >= 128
                if slot == "C3":
                    assert image.width * 4 % 32 == image.height * 4 % 32 == 0
    assert requests["C1"]["input"]["sha256"] != requests["C0"]["input"]["sha256"]


@pytest.mark.parametrize("scale", [True, False, 4.0, 0, -4, 2, 8, float("nan"), float("inf")])
def test_scale_boundary_never_coerces_or_silently_substitutes(tmp_path, scale):
    with pytest.raises(HREError):
        make_case(tmp_path, spec_updates={"scale": scale})


@pytest.mark.parametrize("seed", [True, -1, 1.5, float("nan"), float("inf")])
def test_seed_boundary_is_a_finite_nonnegative_integer(tmp_path, seed):
    with pytest.raises(HREError):
        make_case(tmp_path, spec_updates={"seed": seed})


@pytest.mark.parametrize("box", [
    [True, 1, 20, 12], [1.5, 1, 20, 12], [1, 1, float("nan"), 12],
    [-1, 0, 20, 12], [1, 1, 36, 12], [1, 1, 20, 24], [9, 1, 9, 12], [1, 4, 20, 4],
])
def test_roi_boundary_requires_frozen_valid_lr_pixel_coordinates(tmp_path, box):
    with pytest.raises(HREError):
        make_case(tmp_path, spec_updates={"rois": [{"id": "detail", "box": box}]})


def test_duplicate_roi_identity_is_rejected(tmp_path):
    regions = [{"id": "same", "box": [1, 1, 10, 10]}, {"id": "same", "box": [10, 10, 20, 20]}]
    with pytest.raises(HREError):
        make_case(tmp_path, spec_updates={"rois": regions})


@pytest.mark.parametrize("field", ["ground_truth", "reference", "unknown_policy"])
def test_unrecognised_task_fields_do_not_cross_sr_boundary(tmp_path, field):
    with pytest.raises(HREError):
        make_case(tmp_path, spec_updates={field: {"path": "/private/offline.png"}})


@pytest.mark.parametrize("mode", ["RGBA", "LA", "P"])
def test_nonopaque_source_is_rejected_without_flattening(tmp_path, mode):
    source = tmp_path / "transparent.png"
    if mode == "P":
        image = Image.new("P", (35, 23), 0)
        image.info["transparency"] = 0
    else:
        image = Image.new(mode, (35, 23), (90, 80, 70, 128) if mode == "RGBA" else (90, 128))
    image.save(source)
    with pytest.raises(HREError):
        create_case(tmp_path / "case", {"case_id": "case", "source": {"path": str(source)}, "scale": 4},
                    fixture_config())


def test_corrupt_source_is_rejected_before_model_operations(tmp_path):
    source = tmp_path / "source.png"
    source.write_bytes(b"not an image")
    with pytest.raises((HREError, OSError)):
        create_case(tmp_path / "case", {"case_id": "case", "source": {"path": str(source)}, "scale": 4},
                    fixture_config())
    assert not list((tmp_path / "case").rglob("submitted.json"))


def test_opaque_alpha_source_still_has_valid_hr_delivery(tmp_path):
    source = tmp_path / "opaque.png"
    Image.new("RGBA", (35, 23), (90, 80, 70, 255)).save(source)
    root = tmp_path / "case"
    create_case(root, {"case_id": "case", "source": {"path": str(source)}, "scale": 4}, fixture_config())
    assert_output(run_case(root), "C1", (140, 92))


def test_fixture_marker_is_required(tmp_path):
    config = fixture_config()
    del config["fixture_marker"]
    with pytest.raises(HREError):
        make_case(tmp_path, config=config)


@pytest.mark.parametrize("judge", [
    {"timeout_seconds": True}, {"timeout_seconds": float("inf")},
    {"settings": {"temperature": True}}, {"settings": {"max_tokens": True}},
    {"settings": {"temperature": float("nan")}},
])
def test_judge_numeric_settings_are_strict_and_finite(tmp_path, judge):
    config = fixture_config()
    config["judge"] = judge
    with pytest.raises(HREError):
        make_case(tmp_path, config=config)


@pytest.mark.parametrize("failure", ["wrong_size", "transparent", "corrupt"])
def test_judge_cannot_promote_candidate_with_failed_hard_contract(tmp_path, failure):
    root, _ = make_case(tmp_path, config=fixture_config(candidates={"C1": failure}))
    state = run_case(root)
    assert state["candidates"]["C1"]["status"] == "contract_fail"
    assert_output(state, "C0", (140, 92))


@pytest.mark.parametrize("failure,status", [("fail", "failed"), ("blocked", "blocked")])
def test_known_failure_and_missing_deployment_remain_distinct(tmp_path, failure, status):
    root, _ = make_case(tmp_path, config=fixture_config(candidates={"C2": failure}, improved=["C3"], ranking=["C3"]))
    state = run_case(root)
    assert state["candidates"]["C2"]["status"] == status
    assert_output(state, "C3", (140, 92))


def test_content_failure_cannot_replace_baseline_even_when_marked_improved(tmp_path):
    root, _ = make_case(tmp_path, config=fixture_config(content={"C1": "fail"}))
    state = run_case(root)
    assert_output(state, "C0", (140, 92))


@pytest.mark.parametrize("baseline_content", ["fail", "uncertain"])
def test_unqualified_baseline_is_not_an_sr_fallback(tmp_path, baseline_content):
    root, _ = make_case(tmp_path, config=fixture_config(content={"C0": baseline_content}, improved=[]))
    state = run_case(root)
    assert state["status"] == "unresolved"
    assert state["selected_slot"] is None
    assert state["selected_output"] is None


def test_no_improved_candidate_selects_only_content_qualified_y0(tmp_path):
    root, source = make_case(tmp_path, config=fixture_config(improved=[]))
    state = run_case(root)
    assert_output(state, "C0", (140, 92))
    assert state["selected_output"]["sha256"] != file_sha256(source)


@pytest.mark.parametrize("failure", ["fail", "blocked", "wrong_size", "transparent", "corrupt"])
def test_missing_or_invalid_common_y0_makes_comparison_unresolved(tmp_path, failure):
    root, _ = make_case(tmp_path, config=fixture_config(candidates={"C0": failure}))
    state = run_case(root)
    assert state["status"] == "unresolved"
    assert state["selected_output"] is None


def test_all_content_failed_outputs_remain_audit_only(tmp_path):
    root, _ = make_case(tmp_path, config=fixture_config(content={slot: "fail" for slot in SLOTS},
                                                     improved=["C1", "C2", "C3"]))
    state = run_case(root)
    assert state["status"] == "unresolved"
    assert state["selected_output"] is None
    assert all(Path(candidate["output"]["path"]).is_file() for candidate in state["candidates"].values())


@pytest.mark.parametrize("behavior", ["invalid", "truncated", "unavailable"])
def test_unusable_judge_response_cannot_qualify_y0_or_an_improvement(tmp_path, behavior):
    config = fixture_config()
    config["fixture"]["judge"]["behavior"] = behavior
    root, _ = make_case(tmp_path, config=config)
    state = run_case(root)
    assert state["status"] == "unresolved"
    assert state["selected_output"] is None
    assert all(candidate["status"] == "valid" for candidate in state["candidates"].values())


def test_missing_real_deployments_are_blocked_without_synthetic_candidates(tmp_path):
    root, _ = make_case(tmp_path, config={"mode": "real", "models": {}})
    state = run_case(root)
    assert state["status"] == "unresolved"
    assert state["selected_output"] is None
    assert all(candidate["status"] == "blocked" for candidate in state["candidates"].values())
    assert not any(candidate.get("output") for candidate in state["candidates"].values())


def test_terminal_resume_does_not_repeat_successful_operations(tmp_path):
    root, _ = make_case(tmp_path)
    first = run_case(root)
    before = {path.relative_to(root): file_sha256(path) for path in root.rglob("*") if path.is_file()}
    second = run_case(root)
    after = {path.relative_to(root): file_sha256(path) for path in root.rglob("*") if path.is_file()}
    assert second == first
    assert after == before


@pytest.mark.parametrize("when", ["before_run", "after_run"])
@pytest.mark.parametrize("which", ["origin_path", "original_path", "path"])
def test_original_snapshot_and_canonical_mutation_invalidate_case(tmp_path, when, which):
    root, source = make_case(tmp_path)
    if when == "after_run":
        run_case(root)
    source = Path(read_json(root / "case.json")["source"][which])
    Image.new("RGB", (35, 23), "magenta").save(source, format="PNG")
    with pytest.raises(HREError):
        run_case(root)


def test_terminal_selected_artifact_mutation_is_detected(tmp_path):
    root, _ = make_case(tmp_path)
    state = run_case(root)
    selected = Path(state["selected_output"]["path"])
    Image.new("RGB", (140, 92), "magenta").save(selected)
    with pytest.raises(HREError):
        run_case(root)


@pytest.mark.parametrize("change", ["remove", "modify"])
def test_terminal_evidence_missing_or_tampered_is_detected(tmp_path, change):
    root, _ = make_case(tmp_path)
    run_case(root)
    path = root / "evidence" / "C1.json"
    if change == "remove":
        path.unlink()
    else:
        data = read_json(path)
        data["unrecorded_modification"] = True
        write_json(path, data)
    with pytest.raises(HREError):
        run_case(root)


def count_fixture_dispatches(monkeypatch, root):
    from hre.sr import runtime

    calls = []
    original = runtime._fixture_candidate

    def counted(request, config, output_dir):
        operation = "model_" + request["slot"]
        assert read_json(root / "state.json")["operations"][operation]["status"] == "submitted"
        assert (root / "operations" / operation / "submitted.json").is_file()
        calls.append(request["slot"])
        return original(request, config, output_dir)

    monkeypatch.setattr(runtime, "_fixture_candidate", counted)
    return calls


def test_pending_model_submission_is_not_repeated_on_resume(tmp_path, monkeypatch):
    root, _ = make_case(tmp_path, config=fixture_config(candidates={"C1": "crash"}))
    calls = count_fixture_dispatches(monkeypatch, root)
    try:
        run_case(root)
    except (RuntimeError, KeyboardInterrupt, SystemExit):
        pass
    except HREError as exc:
        assert "unknown" in str(exc).lower() or "pending" in str(exc).lower()
    before = {path.relative_to(root): file_sha256(path) for path in root.rglob("request.json")}
    pending = read_json(root / "state.json")["operations"]["model_C1"]
    try:
        second = run_case(root)
    except HREError as exc:
        assert "unknown" in str(exc).lower() or "pending" in str(exc).lower()
        second = read_json(root / "state.json")
    after = {path.relative_to(root): file_sha256(path) for path in root.rglob("request.json")}
    assert before == after
    assert second["selected_output"] is None
    assert pending["status"] in {"submitted", "unknown"}
    assert second["operations"]["model_C1"]["status"] in {"submitted", "unknown"}
    assert calls == ["C0", "C1"]


def test_explicit_abandonment_does_not_retry_unknown_candidate(tmp_path, monkeypatch):
    root, _ = make_case(tmp_path, config=fixture_config(candidates={"C1": "crash"}))
    calls = count_fixture_dispatches(monkeypatch, root)
    with pytest.raises(KeyboardInterrupt):
        run_case(root)
    reconcile_unknown(root, "model_C1", "Inspected native artifacts; outcome cannot be established.")
    state = run_case(root)
    assert_output(state, "C0", (140, 92))
    assert state["operations"]["model_C1"]["status"] == "abandoned"
    assert state["candidates"]["C1"]["status"] == "failed"
    assert calls == ["C0", "C1", "C2", "C3"]


def test_completed_receipt_recovers_after_crash_before_state_projection(tmp_path, monkeypatch):
    from hre.sr import runtime

    root, _ = make_case(tmp_path)
    calls = count_fixture_dispatches(monkeypatch, root)
    original = runtime.immutable_json
    crashed = False

    def crash_after_receipt(path, value):
        nonlocal crashed
        result = original(path, value)
        if path.name == "done.json" and path.parent.name == "model_C1" and not crashed:
            crashed = True
            raise KeyboardInterrupt("Receipt is durable, state projection was interrupted")
        return result

    monkeypatch.setattr(runtime, "immutable_json", crash_after_receipt)
    with pytest.raises(KeyboardInterrupt):
        run_case(root)
    assert read_json(root / "state.json")["operations"]["model_C1"]["status"] == "submitted"
    assert (root / "operations" / "model_C1" / "done.json").is_file()
    state = run_case(root)
    assert_output(state, "C1", (140, 92))
    assert calls == ["C0", "C1", "C2", "C3"]


def test_accounting_separates_pool_production_from_unknown_oracle_quality(tmp_path):
    root, _ = make_case(tmp_path, config=fixture_config(candidates={"C2": "fail"}, improved=[]))
    run_case(root)
    accounting = report(root)["accounting"]
    assert accounting["produced_count"] == accounting["valid_count"] == 3
    assert accounting["accepted_count"] == 0
    assert accounting["production_coverage"] == accounting["valid_coverage"] == 0.75
    assert accounting["pool_oracle_quality_coverage"] is None
    assert accounting["offline_oracle"] is None
    assert accounting["selection_failure"] is None
    assert accounting["fallback"] is True
    assert accounting["real_model_calls"] == accounting["real_judge_calls"] == 0
    assert accounting["usd"] is None and accounting["usd_status"] == "unknown"
    assert accounting["quality_claims"] is False
