import json

import pytest
from PIL import Image

from hir_manual.service import Controller
from hir_manual.storage import CasePaths, read_json, sha256_file, write_json
from hir_manual.transport import image_observations, import_image, import_payload, scan_ready


@pytest.fixture
def pending(tmp_path, photo):
    ctl = Controller(tmp_path)
    state = ctl.new(photo, "restore")
    return ctl, CasePaths(state.case_id, tmp_path), ctl.current_task(state.case_id)


def execution(pending, fixture_json):
    ctl, case, request = pending
    diagnosis = fixture_json("diagnosis")
    diagnosis["tool_plan"] = []
    assert ctl.import_json(case.case_id, request.task_id, diagnosis, "fixture").accepted
    request = ctl.current_task(case.case_id)
    assert ctl.import_json(case.case_id, request.task_id, fixture_json("composition"), "fixture").accepted
    return ctl, case, ctl.current_task(case.case_id)


def test_payload_only_archive_and_done_do_not_write_state(pending, fixture_json):
    ctl, case, request = pending
    before = case.path("state.json").read_bytes()
    raw = "```json\n" + json.dumps(fixture_json("diagnosis")) + "\n```"
    result = import_payload(case, request.task_id, raw, ctl.provenance("fixture", "file", "local_work"))
    assert result.accepted
    assert case.path("state.json").read_bytes() == before
    response = read_json(case.path(request.response_file))
    assert response["provenance"]["writer"] == "manual_import"
    assert response["provenance"]["transport_mode"] == "clipboard_import"
    assert next(case.path(f"tasks/{request.task_id}/raw").glob("*" )).read_text(encoding="utf-8") == raw
    done = read_json(case.path(request.ready_marker))
    assert done["response_sha256"] == sha256_file(case.path(request.response_file))
    assert done["artifact_hashes"] == []


@pytest.mark.parametrize("raw", ['{"x":1,"x":2}', '{"x":NaN}', 'prefix {}', '{"x":true}', '{"x":"true"}'])
def test_bad_json_preserved_without_done(pending, raw):
    ctl, case, request = pending
    with pytest.raises(ValueError):
        import_payload(case, request.task_id, raw, ctl.provenance("fixture"))
    assert len(list(case.path(f"tasks/{request.task_id}/raw").glob("*"))) == 1
    assert not case.path(request.ready_marker).exists()


def test_full_envelope_preserves_file_provenance_and_identity(pending, fixture_json):
    ctl, case, request = pending
    envelope = {key: getattr(request, key) for key in ("protocol_version", "task_id", "case_id", "role", "round", "expected_state_revision", "input_sha256")}
    envelope.update(status="ok", payload=fixture_json("diagnosis"), error=None, provenance=ctl.provenance("file fixture", "file", "local_work"))
    import_payload(case, request.task_id, json.dumps(envelope), ctl.provenance("ignored"))
    assert read_json(case.path(request.response_file))["provenance"] == envelope["provenance"]
    envelope["expected_state_revision"] += 1
    with pytest.raises(ValueError, match="identity"):
        import_payload(case, request.task_id, json.dumps(envelope), ctl.provenance("fixture"))


def test_provenance_time_order_rejected(pending, fixture_json):
    ctl, case, request = pending
    provenance = ctl.provenance("fixture")
    provenance["completed_at"] = "2020-01-01T00:00:00Z"
    with pytest.raises(ValueError, match="times"):
        import_payload(case, request.task_id, json.dumps(fixture_json("diagnosis")), provenance)


def test_accepted_official_response_cannot_be_overwritten(pending, fixture_json):
    ctl, case, request = pending
    import_payload(case, request.task_id, json.dumps(fixture_json("diagnosis")), ctl.provenance("fixture"))
    before = case.path(request.response_file).read_bytes()
    write_json(case.path(f"tasks/{request.task_id}/accepted/official.json"), read_json(case.path(request.response_file)))
    with pytest.raises(ValueError, match="accepted"):
        import_payload(case, request.task_id, json.dumps(fixture_json("diagnosis")), ctl.provenance("other"))
    assert case.path(request.response_file).read_bytes() == before


def test_scan_only_exact_task_done_markers(pending):
    _, case, request = pending
    for path in (request.ready_marker + ".part", request.ready_marker + ".tmp", "input/done.json", "tasks/extra/nested/done.json"):
        write_json(case.path(path), {})
    assert scan_ready(case.root) == []
    write_json(case.path(request.ready_marker), {})
    assert scan_ready(case.root) == [case.path(request.ready_marker)]


def test_manual_and_file_transport_share_validation(pending, fixture_json):
    ctl, case, request = pending
    import_payload(case, request.task_id, json.dumps(fixture_json("diagnosis")), ctl.provenance("fixture"))
    marker = read_json(case.path(request.ready_marker))
    marker["response_sha256"] = "0" * 64
    write_json(case.path(request.ready_marker), marker)
    assert ctl.scan()[0].code == "validation_error"
    assert ctl.current_task(case.case_id).task_id == request.task_id


def test_image_bytes_actual_format_and_provider_order(pending, fixture_json, tmp_path):
    ctl, case, request = execution(pending, fixture_json)
    first = tmp_path / "wrong_extension.jpg"
    second = tmp_path / "extra.png"
    Image.new("RGB", (64, 48), "red").save(first, format="PNG")
    Image.new("RGB", (64, 48), "green").save(second)
    before = case.path("state.json").read_bytes()
    import_image(case, request.task_id, first, ctl.provenance("fixture"), actual_generations=2, extras=[second])
    response = read_json(case.path(request.response_file))
    payload = response["payload"]
    assert payload["output_asset"]["path"].endswith("/output.png")
    assert case.path(payload["output_asset"]["path"]).read_bytes() == first.read_bytes()
    assert payload["provider_sequence_index"] == 0
    assert payload["actual_generations"] == 2
    assert len(payload["extra_assets"]) == 1
    assert case.path(payload["extra_assets"][0]["path"]).read_bytes() == second.read_bytes()
    assert len(read_json(case.path(request.ready_marker))["artifact_hashes"]) == 2
    assert case.path("state.json").read_bytes() == before


def test_generation_count_must_include_extras(pending, fixture_json, photo):
    ctl, case, request = execution(pending, fixture_json)
    with pytest.raises(ValueError, match="count"):
        import_image(case, request.task_id, photo, ctl.provenance("fixture"), extras=[photo])
    assert not case.path(request.ready_marker).exists()


def test_corrupt_images_are_transport_failure(pending, fixture_json, tmp_path):
    ctl, case, request = execution(pending, fixture_json)
    corrupt = tmp_path / "bad.png"
    corrupt.write_bytes(b"not an image")
    with pytest.raises(ValueError):
        import_image(case, request.task_id, corrupt, ctl.provenance("fixture"))
    assert not case.path(request.ready_marker).exists()


def test_decodable_geometry_failure_enters_verification(pending, fixture_json, tmp_path):
    ctl, case, request = execution(pending, fixture_json)
    output = tmp_path / "wide.png"
    Image.new("RGB", (64, 20), "white").save(output)
    assert ctl.import_image(case.case_id, request.task_id, output, "fixture").accepted
    assert ctl.current_task(case.case_id).role == "verify"
    observations = image_observations(output, case.path("input/canonical.png"), {})
    assert not observations["valid_geometry"]
    assert observations["aspect_ratio_relative_error"] > .02


def test_alpha_is_observed_and_fixed_white_composite(tmp_path, photo):
    rgba = tmp_path / "rgba.png"
    white = tmp_path / "white.png"
    Image.new("RGBA", (64, 48), (0, 0, 0, 0)).save(rgba)
    Image.new("RGB", (64, 48), "white").save(white)
    observations = image_observations(rgba, photo, {})
    assert observations["has_alpha"] and observations["has_transparency"]
    assert observations["pixel_sha256"] == image_observations(white, photo, {})["pixel_sha256"]


def test_pixel_and_byte_limits_enforced(tmp_path, photo):
    with pytest.raises(ValueError, match="pixel"):
        image_observations(photo, photo, {"max_input_pixels": 100})
    with pytest.raises(ValueError, match="byte"):
        image_observations(photo, photo, {"max_input_bytes": 10})


def test_incomplete_copy_never_publishes_done(pending, fixture_json, photo, monkeypatch):
    import hir_manual.transport as transport

    ctl, case, request = execution(pending, fixture_json)
    original = transport.atomic_write
    def fail_copy(path, raw):
        if path.name == "output.png":
            raise OSError("simulated incomplete copy")
        return original(path, raw)
    monkeypatch.setattr(transport, "atomic_write", fail_copy)
    with pytest.raises(OSError):
        import_image(case, request.task_id, photo, ctl.provenance("fixture"))
    assert not case.path(request.ready_marker).exists()
    assert scan_ready(case.root) == [marker for marker in scan_ready(case.root) if marker.parent.name != request.task_id]
