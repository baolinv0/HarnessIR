"""Builder-side evidence tests using real chat serialization and synthetic pixels."""
import base64
from copy import deepcopy
import io
import json

import numpy as np
from PIL import Image
import pytest

from hre.models import canonical_json, sha256_bytes
from hre.storage import read_json
from hre.sr import evidence
from hre.sr.contracts import FIXTURE_MARKER
from hre.sr.runtime import create_case, run_case
from hre.v3 import common


@pytest.fixture
def completed(tmp_path):
    y, x = np.mgrid[:23, :35]
    pixels = np.stack(((x * 7 + y * 3) % 256, (y * 17) % 256, (x * 11) % 256,
                       np.full_like(x, 255)), axis=-1).astype(np.uint8)
    source = tmp_path / "source.png"
    Image.fromarray(pixels).save(source)
    config = {"mode": "fixture", "fixture_marker": FIXTURE_MARKER,
              "fixture": {"judge": {"improved": ["C1"], "ranking": ["C1", "C2", "C3"]}}}
    spec = {"case_id": "evidence_case", "source": {"path": str(source)}, "seed": 7,
            "rois": [{"id": "letters", "box": [1, 2, 10, 11]},
                     {"id": "edge", "box": [20, 5, 33, 20]}]}
    root = tmp_path / "case"
    create_case(root, spec, config)
    state = run_case(root)
    case = read_json(root / "case.json")
    bundle = read_json(root / "judge" / "bundle.json")
    records = {slot: read_json(root / "evidence" / (slot + ".json")) for slot in state["candidates"]}
    return root, case, state, records, bundle


def assessment(bundle):
    aliases = list(bundle["aliases"])
    target = next(alias for alias, slot in bundle["aliases"].items() if slot == "C1")
    return {"baseline_content": "pass", "candidates": [
        {"id": alias, "content": "pass", "improvement": "improved" if alias == target else "no_improvement",
         "confidence": 0.8} for alias in aliases], "ranking": aliases,
        "best_candidate": target, "reason": "Synthetic transport response used to test the contract"}


def real_judge_case(case, response_format="json_object"):
    result = deepcopy(case)
    result["config"]["mode"] = "real"
    result["config"]["judge"] = {
        "base_url": "https://judge.invalid/v1", "model": "deployed-judge",
        "settings": {"temperature": 0, "seed": 21, "max_tokens": 2048},
        "timeout_seconds": 20, "response_format": response_format,
    }
    return result


def capture_chat(monkeypatch, answer, *, finish_reason="stop"):
    captured = []

    def urlopen(request, timeout):
        captured.append({"bytes": request.data, "body": json.loads(request.data),
                         "url": request.full_url, "timeout": timeout})
        content = answer if isinstance(answer, str) else json.dumps(answer)
        raw = json.dumps({"id": "observed-response", "model": "deployed-judge",
                          "usage": {"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130},
                          "choices": [{"message": {"content": content}, "finish_reason": finish_reason}]}).encode()
        return io.BytesIO(raw)

    monkeypatch.setattr(common, "urlopen", urlopen)
    return captured


@pytest.mark.parametrize("response_format", ["json_object", "json_schema", "none"])
def test_actual_chat_pair_changes_only_designated_evidence_text(completed, monkeypatch, response_format):
    _, frozen, state, records, bundle = completed
    case = real_judge_case(frozen, response_format)
    requests = evidence.make_requests(case, state["candidates"], records, bundle)
    captured = capture_chat(monkeypatch, assessment(bundle))
    results = [evidence.invoke_judge(case, requests[arm], bundle) for arm in ("visual", "evidence")]

    assert all(result["status"] == "available" for result in results)
    assert len(captured) == 2
    for arm, result, actual in zip(("visual", "evidence"), results, captured):
        assert actual["body"] == requests[arm]["body"]
        assert actual["bytes"] == canonical_json(requests[arm]["body"])
        assert result["observation"]["request_sha256"] == sha256_bytes(actual["bytes"])
        assert result["observation"]["request_sha256"] == requests[arm]["body_sha256"]
        assert actual["url"] == "https://judge.invalid/v1/chat/completions"
        assert actual["timeout"] == 20
        assert result["observation"]["usage"]["total_tokens"] == 130
        assert result["observation"]["raw_response"]["id"] == "observed-response"

    visual, augmented = [deepcopy(item["body"]) for item in captured]
    control_payload = json.loads(visual["messages"][1]["content"][0]["text"])
    evidence_payload = json.loads(augmented["messages"][1]["content"][0]["text"])
    assert control_payload["evidence_text"] is None
    assert isinstance(evidence_payload["evidence_text"], str)
    projected = json.loads(evidence_payload["evidence_text"])
    assert projected["profile_selection"] == "provisional"
    assert "not verified high-frequency fidelity" in projected["limitations"]
    evidence_payload["evidence_text"] = None
    assert evidence_payload == control_payload
    augmented["messages"][1]["content"][0]["text"] = canonical_json(evidence_payload).decode()
    assert visual == augmented
    assert requests["visual"]["attachments_sha256"] == requests["evidence"]["attachments_sha256"]

    attachments = control_payload["attachments"]
    images = visual["messages"][1]["content"][1:]
    assert len(attachments) == len(images) == (2 + len(bundle["aliases"])) * 3
    for metadata, message in zip(attachments, images):
        encoded = message["image_url"]["url"].split(",", 1)[1]
        pixels = base64.b64decode(encoded, validate=True)
        assert sha256_bytes(pixels) == metadata["transport_png_sha256"]
        assert len(pixels) == metadata["transport_bytes"]
        with Image.open(io.BytesIO(pixels)) as image:
            assert image.mode == "RGB"
            assert image.size == (metadata["width"], metadata["height"])
    assert attachments[0]["transport_png_sha256"] != frozen["source"]["sha256"]
    assert control_payload["source"]["sha256"] == frozen["source"]["sha256"]
    assert control_payload["baseline"]["sha256"] == state["candidates"]["C0"]["output"]["sha256"]
    assert control_payload["methods"] == evidence.method_identity(frozen["task"]["evidence_profile"]["methods"])
    assert control_payload["rois"] == [
        {"id": "R01", "source_box": [1, 2, 10, 11], "hr_box": [4, 8, 40, 44]},
        {"id": "R02", "source_box": [20, 5, 33, 20], "hr_box": [80, 20, 132, 80]},
    ]
    for item in projected["measurements"]:
        assert item["status"] == "measured"
        assert set(item["binding"]) == {
            "source_sha256", "source_pixel_sha256", "baseline_sha256", "candidate_sha256",
            "roi_sha256", "geometry_sha256", "method_sha256",
        }
        assert item["method"]["version"] == evidence.METHOD_VERSION


def test_online_projection_excludes_offline_model_paths_and_ground_truth(completed, monkeypatch, tmp_path):
    _, frozen, state, records, _ = completed
    case, candidates, records = deepcopy(frozen), deepcopy(state["candidates"]), deepcopy(records)
    secret = {"ground_truth": "/private/GT.png", "model_id": "SeeSR_PRIVATE_MODEL", "path": "/private/checkpoint.pth"}
    case["ground_truth"] = secret
    case["source"]["offline_metadata"] = secret
    for region in case["rois"]:
        region["id"] = "PRIVATE_ROI_LABEL_" + region["id"]
    for slot, candidate in candidates.items():
        candidate.update(ground_truth=secret, recipe_name="RealESRNet_x4plus", model_id="Qwen-Image-2.1")
        candidate["output"]["offline_metadata"] = secret
        records[slot]["binding"] = evidence.binding(case, candidates, slot)
        records[slot]["offline_metadata"] = secret
        for measurement in records[slot]["measurements"].values():
            measurement["private"] = secret
            for region in measurement["regions"]:
                region["private"] = secret
    bundle_root = tmp_path / "projected_bundle"
    bundle_root.mkdir()
    bundle = evidence.build_bundle(bundle_root, case, candidates)
    local_map = read_json(bundle_root / "judge" / "alias_map.local.json")
    assert local_map["aliases"] == bundle["aliases"]
    assert set(local_map["aliases"].values()) == {"C1", "C2", "C3"}
    online_case = real_judge_case(case)
    requests = evidence.make_requests(online_case, candidates, records, bundle)
    captured = capture_chat(monkeypatch, assessment(bundle))
    evidence.invoke_judge(online_case, requests["evidence"], bundle)
    body = captured[0]["body"]
    text = body["messages"][1]["content"][0]["text"]
    for forbidden in ("/private", "ground_truth", "SeeSR", "RealESRNet", "Qwen", "PRIVATE_ROI_LABEL", '"C0"', '"C1"', '"C2"', '"C3"'):
        assert forbidden not in text
    payload = json.loads(text)
    assert [candidate["id"] for candidate in payload["candidates"]] == list(bundle["aliases"])
    assert all(set(candidate) == {"id", "sha256", "hard_contract", "geometry_sha256"} for candidate in payload["candidates"])
    assert set(payload["source"]) == {"id", "sha256", "pixel_sha256", "width", "height"}
    assert all(item["status"] == "measured" for item in json.loads(payload["evidence_text"])["measurements"])


@pytest.mark.parametrize("mutation", ["nan", "infinity", "bool_confidence", "unknown_alias", "duplicate_alias",
                                     "duplicate_rank", "content_failed_best", "unimproved_best", "extra_field",
                                     "missing_baseline", "invalid_json", "duplicate_json_key"])
def test_invalid_actual_judge_responses_are_unavailable_with_observation(completed, monkeypatch, mutation):
    _, frozen, state, records, bundle = completed
    case = real_judge_case(frozen)
    request = evidence.make_requests(case, state["candidates"], records, bundle)["evidence"]
    answer = assessment(bundle)
    target = next(item for item in answer["candidates"] if item["id"] == answer["best_candidate"])
    if mutation == "nan":
        target["confidence"] = float("nan")
    elif mutation == "infinity":
        target["confidence"] = float("inf")
    elif mutation == "bool_confidence":
        target["confidence"] = True
    elif mutation == "unknown_alias":
        target["id"] = "UNKNOWN"
    elif mutation == "duplicate_alias":
        answer["candidates"][1]["id"] = answer["candidates"][0]["id"]
    elif mutation == "duplicate_rank":
        answer["ranking"][1] = answer["ranking"][0]
    elif mutation == "content_failed_best":
        target["content"] = "fail"
    elif mutation == "unimproved_best":
        target["improvement"] = "no_improvement"
    elif mutation == "extra_field":
        answer["geometry_overrides_content"] = True
    elif mutation == "missing_baseline":
        del answer["baseline_content"]
    elif mutation == "invalid_json":
        answer = "{"
    elif mutation == "duplicate_json_key":
        answer = json.dumps(answer)[:-1] + ', "baseline_content": "fail"}'
    captured = capture_chat(monkeypatch, answer)
    result = evidence.invoke_judge(case, request, bundle)
    assert result["status"] == "unavailable"
    assert result["observation"]["raw_response"]["id"] == "observed-response"
    assert result["observation"]["request_sha256"] == sha256_bytes(captured[0]["bytes"])
    assert result["error"]["code"] in {"sr_judge_invalid", "sr_nonfinite"}
    selected = evidence.select(case, state["candidates"], records, bundle, result)
    assert selected["status"] == "unresolved"
    assert selected["selected_output"] is None


@pytest.mark.parametrize("finish_reason", ["length", "content_filter", "tool_calls", None])
def test_incomplete_actual_response_retains_observation_without_selection(completed, monkeypatch, finish_reason):
    _, frozen, state, records, bundle = completed
    case = real_judge_case(frozen)
    request = evidence.make_requests(case, state["candidates"], records, bundle)["evidence"]
    capture_chat(monkeypatch, assessment(bundle), finish_reason=finish_reason)
    result = evidence.invoke_judge(case, request, bundle)
    assert result["status"] == "unavailable"
    assert result["error"]["code"] == "sr_judge_incomplete"
    assert result["observation"]["finish_reason"] == finish_reason
    assert result["observation"]["text"]


@pytest.mark.parametrize("binding_key", ["source_sha256", "source_pixel_sha256", "baseline_sha256", "candidate_sha256",
                                        "roi_sha256", "geometry_sha256", "method_sha256"])
def test_every_bound_identity_is_required_for_measured_evidence(completed, binding_key):
    _, case, state, records, bundle = completed
    bad = deepcopy(records)
    bad["C1"]["binding"][binding_key] = "0" * 64
    assert evidence.evidence_status(records["C1"], case, state["candidates"], "C1") == "measured"
    assert evidence.evidence_status(bad["C1"], case, state["candidates"], "C1") == "stale"
    judgement = {"status": "available", "assessment": assessment(bundle)}
    decision = evidence.select(case, state["candidates"], bad, bundle, judgement)
    assert decision["selected_slot"] == "C0"
    assert decision["accepted_slots"] == []


@pytest.mark.parametrize("bad_status", ["missing", "failed", "stale"])
def test_unmeasured_proxy_cannot_support_accepted_improvement(completed, bad_status):
    _, case, state, records, bundle = completed
    changed = deepcopy(records)
    changed["C1"]["status"] = bad_status
    result = evidence.select(case, state["candidates"], changed, bundle,
                             {"status": "available", "assessment": assessment(bundle)})
    assert result["selected_slot"] == "C0"
    assert result["accepted_slots"] == []
    requests = evidence.make_requests(case, state["candidates"], changed, bundle)
    payload = json.loads(requests["evidence"]["body"]["messages"][1]["content"][0]["text"])
    projected = json.loads(payload["evidence_text"])
    alias = next(alias for alias, slot in bundle["aliases"].items() if slot == "C1")
    entry = next(item for item in projected["measurements"] if item["image_id"] == alias)
    assert entry["status"] == bad_status
    assert entry["measurements"] == {}


def test_missing_baseline_evidence_prevents_both_improvement_and_fallback(completed):
    _, case, state, records, bundle = completed
    records.pop("C0")
    result = evidence.select(case, state["candidates"], records, bundle,
                             {"status": "available", "assessment": assessment(bundle)})
    assert result["status"] == "unresolved"
    assert result["selected_slot"] is None
    assert result["selected_output"] is None


@pytest.mark.parametrize("mutation", ["method_version", "method_implementation", "method_missing", "region_missing",
                                     "region_swapped", "nan_metric", "bool_metric", "metric_failed"])
def test_measurement_schema_or_method_drift_never_remains_measured(completed, mutation):
    _, case, state, records, _ = completed
    record = deepcopy(records["C1"])
    measurement = record["measurements"]["lr_consistency_v1"]
    if mutation == "method_version":
        record["method"]["version"] = "unknown"
    elif mutation == "method_implementation":
        record["method"]["implementation_sha256"] = "0" * 64
    elif mutation == "method_missing":
        del record["measurements"]["clipping_v1"]
    elif mutation == "region_missing":
        measurement["regions"].pop()
    elif mutation == "region_swapped":
        measurement["regions"][1], measurement["regions"][2] = measurement["regions"][2], measurement["regions"][1]
    elif mutation == "nan_metric":
        measurement["regions"][0]["candidate"] = float("nan")
    elif mutation == "bool_metric":
        measurement["regions"][0]["candidate"] = True
    elif mutation == "metric_failed":
        measurement["status"] = "failed"
    assert evidence.evidence_status(record, case, state["candidates"], "C1") in {"failed", "stale"}


def test_actual_chat_body_hash_mismatch_cannot_be_available(completed, monkeypatch):
    _, frozen, state, records, bundle = completed
    case = real_judge_case(frozen)
    request = evidence.make_requests(case, state["candidates"], records, bundle)["evidence"]
    capture_chat(monkeypatch, assessment(bundle))
    request["body_sha256"] = "0" * 64
    result = evidence.invoke_judge(case, request, bundle)
    assert result["status"] == "unavailable"
    assert result["error"]["code"] == "sr_judge_request_mismatch"
