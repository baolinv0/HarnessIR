"""Software-only orchestration contracts; fixtures never call an image model."""
from copy import deepcopy
from pathlib import Path

from PIL import Image
import pytest

from hre.models import HREError, file_sha256
from hre.storage import read_json, write_json
from hre.v3.common import digest
from hre.v3.contracts import create_case
from hre.v3.dispatch import seal_condition, seal_generation
from hre.v3.runner import reconcile, run_case


def make_case(tmp_path, *, mode="restoration", strategy="model_aware", policy="feedback", name="case", shared=None,
              policy_overrides=None, regions=None, compiler_backend="direct"):
    source = tmp_path / "source.png"
    reference = tmp_path / "reference.png"
    if not source.exists():
        Image.new("RGB", (31, 23), (40, 50, 60)).save(source)
        Image.new("RGB", (28, 20), (70, 75, 80)).save(reference)
    spec = {"schema_version": "hre_task_v3", "case_id": name, "task_mode": mode,
            "profile_id": "qwen21", "strategy": strategy, "brief": "Reduce visible blur while preserving the scene.",
            "source": {"path": str(source)}, "geometry": {"policy": "pad"},
            "spatial": {"mode": "full_frame"},
            "policy": {"mode": policy, "max_generations": 1 if policy == "single" else 2}}
    if mode == "reference_enhance":
        spec["reference"] = {"path": str(reference)}
    if shared:
        spec["shared_intent"] = str(shared)
    if policy_overrides:
        spec["policy"].update(policy_overrides)
    if regions is not None:
        spec["regions"] = regions
    config = {"stage": {}, "models": {"qwen21": {"compiler": {"backend": compiler_backend},
              "editor": {"model_id": "Qwen/Qwen-Image-2.1"}}}}
    root = tmp_path / name
    create_case(root, spec, config)
    return root


def intent(mode):
    return {"schema_version": "hre_edit_intent_v3", "task_mode": mode, "revision": 0,
            "targets": [{"id": "t1", "region": "source vehicle", "instruction": "Reduce supported blurred contours.",
                         "priority": 1, "evidence_refs": ["source"]}],
            "region_relations": [], "protected_content": ["Preserve source lettering and geometry."],
            "uncertainties": ["Unresolved plate letters remain unresolved."], "summary": "One supported target.",
            "parent_intent_hash": None, "feedback_refs": []}


class Workers:
    def __init__(self, *, accept_after=2):
        self.stages = []
        self.compiles = []
        self.executions = []
        self.accept_after = accept_after
        self.last_execution = None

    def stage(self, request):
        self.stages.append(request["stage"])
        stage = request["stage"]
        if stage == "diagnose":
            payload = {"schema_version": "hre_diagnosis_v3", "task_mode": request["task_mode"],
                       "findings": [{"id": "f1", "region": "vehicle", "kind": "blur",
                                     "observation": "A visible contour is blurred.", "confidence": .9,
                                     "evidence_refs": ["source"]}], "protected_content": ["Preserve source contents."],
                       "uncertainties": [], "tool_requests": ["basic_statistics"], "summary": "Visible blur."}
        elif stage == "compose":
            payload = intent(request["task_mode"])
        elif stage == "verify":
            accepted = len(self.executions) >= self.accept_after
            payload = {"verdict": "accept" if accepted else "revise", "preservation": "pass",
                       "task_progress": "improved" if accepted else "unchanged", "confidence": .9,
                       "summary": "Synthetic fixture judgment; no visual quality claim.",
                       "issues": [] if accepted else [{"id": "i1", "kind": "residual_degradation", "region": "vehicle",
                                                       "observation": "A residual blur remains in this software fixture.",
                                                       "evidence_refs": ["source", "candidate"],
                                                       "suggested_change": "Emphasize the supported main contour."}]}
        else:
            previous = request["context"]["previous_intent"]
            revised = deepcopy(previous)
            revised["revision"] += 1
            revised["parent_intent_hash"] = digest(previous)
            revised["feedback_refs"] = request["context"]["actionable_feedback_refs"]
            revised["targets"][0]["instruction"] = "Reduce the supported main contour blur more clearly."
            revised["targets"][0]["evidence_refs"] = revised["feedback_refs"]
            payload = {"action": "revise", "reason": "Respond to the observed residual.", "intent": revised}
        return {"payload": payload, "observation": {"calls_attempted": 1, "calls_completed": 1, "fixture_only": True,
                "stage_request_id": request["request_id"], "stage_request_sha256": digest(request)}}

    def compile(self, request, config):
        self.compiles.append(deepcopy(request))
        result = {"text": request["brief"] if request["intent"] is None else request["intent"]["targets"][0]["instruction"],
                "condition_kind": "semantic_instruction", "native_output": {}, "warnings": [],
                "observation": {"compiler_id": "fixture-direct", "calls_attempted": 0, "calls_completed": 0, "fixture_only": True}}
        return seal_condition(request, config, result)

    def execute(self, request, condition, config, outdir):
        self.executions.append(deepcopy(request))
        outdir.mkdir(parents=True, exist_ok=True)
        path = outdir / "fixture.png"
        Image.new("RGB", (request["canvas"]["width"], request["canvas"]["height"]),
                  (80 + len(self.executions), 70, 60)).save(path)
        result = {"outputs": [{"path": str(path), "sha256": file_sha256(path),
                               "width": request["canvas"]["width"], "height": request["canvas"]["height"], "mode": "RGB"}],
                  "observation": {"image_calls_attempted": 1, "image_calls_completed": 1,
                                  "actual_generation_count": 1, "fixture_only": True}}
        result = seal_generation(request, condition, config, result, output_dir=outdir)
        self.last_execution = result
        return result


@pytest.mark.parametrize("mode", ["restoration", "reference_enhance"])
def test_feedback_compiles_each_new_intent_and_reuses_original_source(tmp_path, mode):
    root = make_case(tmp_path, mode=mode)
    workers = Workers()
    state = run_case(root, stage_fn=workers.stage, compile_fn=workers.compile, execute_fn=workers.execute)
    assert state["status"] == "completed" and state["success"] is True
    assert len(workers.executions) == len(workers.compiles) == 2
    assert state["intent"]["revision"] == 1
    assert workers.compiles[0]["intent"]["targets"] != workers.compiles[1]["intent"]["targets"]
    assert workers.executions[0]["inputs"][0]["sha256"] == workers.executions[1]["inputs"][0]["sha256"]
    assert all(request["original_input_sha256"]["source"] == state["inputs"][0]["sha256"] for request in workers.executions)
    assert all(len(request["inputs"]) == (1 if mode == "restoration" else 2) for request in workers.executions)
    assert state["selected_output"]["width"] == 31 and state["selected_output"]["height"] == 23
    assert state["budget"]["generations"] == 2
    assert (root / "artifacts/shared_intent.json").is_file()
    second = run_case(root, stage_fn=workers.stage, compile_fn=workers.compile, execute_fn=workers.execute)
    assert second == state and len(workers.executions) == 2


def test_native_resample_keeps_compiler_output_and_does_not_acquire_intent(tmp_path):
    root = make_case(tmp_path, strategy="native", policy="resample")
    workers = Workers(accept_after=20)
    state = run_case(root, stage_fn=workers.stage, compile_fn=workers.compile, execute_fn=workers.execute)
    assert len(workers.compiles) == 1 and len(workers.executions) == 2
    assert workers.stages == ["verify", "verify"]
    assert all(request["intent"] is None for request in workers.executions)
    assert [request["seed"] for request in workers.executions] == [0, 1]
    assert state["selected_kind"] == "candidate_unaccepted" and not state["success"]
    assert len(state["candidates"]) == 2
    cached = read_json(root / state["rounds"][1]["condition"]["path"])
    assert cached["observation"]["calls_attempted"] == 0 and cached["cache_origin"]["round"] == 0


def test_unknown_generation_is_not_repeated_and_actual_result_can_be_reconciled(tmp_path):
    root = make_case(tmp_path, policy="single")
    workers = Workers(accept_after=1)

    def lose_response(*args):
        workers.execute(*args)
        raise RuntimeError("Simulated connection loss after image generation")

    state = run_case(root, stage_fn=workers.stage, compile_fn=workers.compile, execute_fn=lose_response)
    assert state["status"] == "paused" and state["pause_reason"] == "submission_unknown"
    assert state["budget"]["generations"] == 1 and len(workers.executions) == 1
    run_case(root, stage_fn=workers.stage, compile_fn=workers.compile, execute_fn=lose_response)
    assert len(workers.executions) == 1
    response = tmp_path / "actual_response.json"
    write_json(response, workers.last_execution)
    reconcile(root, "confirmed_result", result_path=response, evidence="The fixture worker returned this exact persisted response.")
    recovered = run_case(root, stage_fn=workers.stage, compile_fn=workers.compile, execute_fn=lose_response)
    assert recovered["success"] is True and len(workers.executions) == 1
    assert recovered["budget"]["generations"] == 1


def test_reconciliation_rejects_a_sealed_generation_from_another_source(tmp_path):
    first_dir, second_dir = tmp_path / "a", tmp_path / "b"
    first_dir.mkdir(); second_dir.mkdir()
    Image.new("RGB", (31, 23), "red").save(first_dir / "source.png")
    Image.new("RGB", (31, 23), "blue").save(second_dir / "source.png")
    first = make_case(first_dir, strategy="native", policy="single")
    second = make_case(second_dir, strategy="native", policy="single")
    a, b = Workers(accept_after=1), Workers(accept_after=1)
    assert run_case(first, stage_fn=a.stage, compile_fn=a.compile, execute_fn=a.execute)["success"]

    def lose_b(*args):
        b.execute(*args)
        raise RuntimeError("Lost B response after generation")

    paused = run_case(second, stage_fn=b.stage, compile_fn=b.compile, execute_fn=lose_b)
    assert paused["status"] == "paused"
    response = tmp_path / "foreign_response.json"
    write_json(response, a.last_execution)
    with pytest.raises(HREError, match="reconciliation_binding"):
        reconcile(second, "confirmed_result", result_path=response,
                  evidence="An operator accidentally selected another completed case response.")
    after = run_case(second, stage_fn=b.stage, compile_fn=b.compile, execute_fn=lose_b)
    assert after["status"] == "paused" and after["pending"] == paused["pending"]
    assert after["budget"] == paused["budget"] and after["candidates"] == [] and len(b.executions) == 1
    write_json(response, b.last_execution)
    reconcile(second, "confirmed_result", result_path=response, evidence="This is the exact saved B response.")
    recovered = run_case(second, stage_fn=b.stage, compile_fn=b.compile, execute_fn=lose_b)
    assert recovered["success"] and len(b.executions) == 1
    assert Path(recovered["candidates"][0]["native"]["path"]).is_relative_to(second)


def test_reconciliation_binds_the_actual_seed_even_when_semantic_binding_matches(tmp_path):
    from hre.v3.dispatch import request_binding
    root = make_case(tmp_path, strategy="native", policy="single")
    workers = Workers(accept_after=1)
    submitted = []

    def wrong_seed(request, condition, config, outdir):
        submitted.append(deepcopy(request))
        different = deepcopy(request)
        different["seed"] += 1
        assert request_binding(different) == request_binding(request)
        workers.execute(different, condition, config, outdir)
        raise RuntimeError("A response exists, but its actual request used a different seed")

    state = run_case(root, stage_fn=workers.stage, compile_fn=workers.compile, execute_fn=wrong_seed)
    assert state["status"] == "paused"
    response = tmp_path / "different_seed.json"
    write_json(response, workers.last_execution)
    with pytest.raises(HREError, match="execution_request_sha256"):
        reconcile(root, "confirmed_result", result_path=response, evidence="The saved worker result is being checked.")
    assert workers.last_execution["observation"]["execution_request_sha256"] != digest(submitted[0])
    assert run_case(root)["status"] == "paused"


@pytest.mark.parametrize("mismatch", ["unbound", "condition", "configuration", "output_directory", "output_path"])
def test_reconciliation_requires_a_complete_receipt_bound_to_the_pending_execution(tmp_path, mismatch):
    root = make_case(tmp_path, strategy="native", policy="single")
    workers = Workers(accept_after=1)

    def lose_response(*args):
        workers.execute(*args)
        raise RuntimeError("Response lost after the fixture wrote its image")

    paused = run_case(root, stage_fn=workers.stage, compile_fn=workers.compile, execute_fn=lose_response)
    result = deepcopy(workers.last_execution)
    if mismatch == "unbound":
        result["observation"] = {key: result["observation"][key] for key in
                                 ("image_calls_attempted", "image_calls_completed", "actual_generation_count")}
    elif mismatch == "condition":
        result["observation"]["condition_sha256"] = digest({"text": "An earlier accepted condition"})
    elif mismatch == "configuration":
        result["observation"]["editor_config_sha256"] = digest({"model_id": "another-runtime"})
    elif mismatch == "output_directory":
        result["observation"]["output_directory"] = str(root / "another_attempt")
    else:
        path = tmp_path / "foreign_native.png"
        path.write_bytes(Path(result["outputs"][0]["path"]).read_bytes())
        result["outputs"][0]["path"] = str(path)
    response = tmp_path / "mismatched_receipt.json"
    write_json(response, result)
    with pytest.raises(HREError, match="reconciliation_binding"):
        reconcile(root, "confirmed_result", result_path=response, evidence="A saved result is available for inspection.")
    current = run_case(root)
    assert current["status"] == "paused" and current["pending"] == paused["pending"]
    assert current["budget"] == paused["budget"] and len(workers.executions) == 1


def test_stage_reconciliation_requires_the_full_original_request_and_recovers_once(tmp_path):
    root = make_case(tmp_path, policy="single")
    workers = Workers(accept_after=1)
    responses = []

    def lost_stage(request):
        responses.append(workers.stage(request))
        raise RuntimeError("Stage completed but response was lost")

    paused = run_case(root, stage_fn=lost_stage, compile_fn=workers.compile, execute_fn=workers.execute)
    assert paused["pending"]["kind"] == "stage"
    response = tmp_path / "stage_response.json"
    altered = deepcopy(responses[0])
    altered["observation"]["stage_request_sha256"] = digest({"context": "A different image or diagnostic context"})
    write_json(response, altered)
    with pytest.raises(HREError, match="stage_request_sha256"):
        reconcile(root, "confirmed_result", result_path=response, evidence="Stage response under review.")
    write_json(response, responses[0])
    reconcile(root, "confirmed_result", result_path=response, evidence="The real original stage request receipt.")
    recovered = run_case(root, stage_fn=workers.stage, compile_fn=workers.compile, execute_fn=workers.execute)
    assert recovered["success"] and workers.stages.count("diagnose") == 1


def test_compiler_reconciliation_rejects_another_attempt_even_with_the_same_intent(tmp_path):
    root = make_case(tmp_path, strategy="native", policy="single")
    workers = Workers(accept_after=1)
    responses = []

    def lost_compile(request, config):
        responses.append(workers.compile(request, config))
        raise RuntimeError("Compiler response lost")

    paused = run_case(root, stage_fn=workers.stage, compile_fn=lost_compile, execute_fn=workers.execute)
    assert paused["pending"]["kind"] == "compile"
    response = tmp_path / "compiler_response.json"
    another_attempt = deepcopy(workers.compiles[0])
    another_attempt["execution_attempt"] += 1
    altered = deepcopy(responses[0])
    altered["compilation_request_sha256"] = digest(another_attempt)
    write_json(response, altered)
    with pytest.raises(HREError, match="compilation_request_sha256"):
        reconcile(root, "confirmed_result", result_path=response, evidence="A previous compiler receipt is available.")
    write_json(response, responses[0])
    reconcile(root, "confirmed_result", result_path=response, evidence="The pending compiler attempt's actual receipt.")
    recovered = run_case(root, stage_fn=workers.stage, compile_fn=lost_compile, execute_fn=workers.execute)
    assert recovered["success"] and len(workers.compiles) == 1


def test_shared_intent_reuses_planning_but_still_verifies_new_output(tmp_path):
    first = make_case(tmp_path, policy="single", name="first", strategy="shared")
    workers = Workers(accept_after=1)
    run_case(first, stage_fn=workers.stage, compile_fn=workers.compile, execute_fn=workers.execute)
    second = make_case(tmp_path, policy="single", name="second", shared=first / "artifacts/shared_intent.json")
    other = Workers(accept_after=1)
    state = run_case(second, stage_fn=other.stage, compile_fn=other.compile, execute_fn=other.execute)
    assert state["success"] and other.stages == ["verify"]
    assert other.compiles[0]["intent"] == workers.compiles[0]["intent"]


def test_journal_corruption_is_not_accepted_as_a_resume(tmp_path):
    root = make_case(tmp_path, policy="single")
    workers = Workers(accept_after=1)
    run_case(root, stage_fn=workers.stage, compile_fn=workers.compile, execute_fn=workers.execute)
    last = sorted((root / "journal").glob("*.json"))[-1]
    value = read_json(last)
    value["state"]["success"] = False
    write_json(last, value)
    with pytest.raises(HREError, match="journal_modified"):
        run_case(root, stage_fn=workers.stage, compile_fn=workers.compile, execute_fn=workers.execute)


def test_completed_compiler_parse_failure_retains_native_evidence_without_image_call(tmp_path):
    root = make_case(tmp_path, policy="single")
    workers = Workers()

    def invalid_native(request, config):
        error = HREError("fixture_parse_failed", "Invalid native compiler result")
        error.observation = {"compiler_id": "fixture", "calls_attempted": 1, "calls_completed": 1}
        error.native_output = {"raw": "unparseable output"}
        raise error

    state = run_case(root, stage_fn=workers.stage, compile_fn=invalid_native, execute_fn=workers.execute)
    assert state["status"] == "failed" and state["terminal_reason"] == "compiler_error"
    assert workers.executions == [] and state["budget"]["compiler_calls"] == 1
    result = read_json(next((root / "operations").glob("compile-*/result.json")))
    assert result["native_output"]["raw"] == "unparseable output"


@pytest.mark.parametrize("cutoff,expected_compiles", [("compose", 0), ("condition", 1)])
def test_prepare_cutoff_never_generates_and_resumes_without_replanning(tmp_path, cutoff, expected_compiles):
    root = make_case(tmp_path, policy="single")
    workers = Workers(accept_after=1)
    prepared = run_case(root, stage_fn=workers.stage, compile_fn=workers.compile,
                        execute_fn=workers.execute, stop_after=cutoff)
    assert prepared["status"] == "ready" and workers.executions == []
    assert len(workers.compiles) == expected_compiles
    artifact = read_json(root / "artifacts/shared_intent.json")
    assert artifact["planning"]["diagnosis"]["findings"]
    assert artifact["planning"]["evidence"]["records"]
    done = run_case(root, stage_fn=workers.stage, compile_fn=workers.compile, execute_fn=workers.execute)
    assert done["success"] and len(workers.compiles) == 1 and len(workers.executions) == 1
    assert workers.stages == ["diagnose", "compose", "verify"]


def test_direct_compiler_needs_no_model_call_budget(tmp_path):
    root = make_case(tmp_path, policy="single", policy_overrides={"max_compiler_calls": 0})
    workers = Workers(accept_after=1)
    state = run_case(root, stage_fn=workers.stage, compile_fn=workers.compile, execute_fn=workers.execute)
    assert state["success"] and state["budget"]["compiler_calls"] == 0


def test_stage_overbudget_is_stopped_before_compilation_or_generation(tmp_path):
    root = make_case(tmp_path, policy="single", policy_overrides={"max_stage_calls": 1})
    workers = Workers()

    def overbudget(request):
        result = workers.stage(request)
        result["observation"].update(calls_attempted=2, calls_completed=2)
        return result

    state = run_case(root, stage_fn=overbudget, compile_fn=workers.compile, execute_fn=workers.execute)
    assert state["status"] == "failed" and state["terminal_reason"] == "stage_budget_exceeded"
    assert state["budget"]["stage_calls"] == 2 and workers.compiles == workers.executions == []


def test_region_evidence_uses_each_images_independent_coordinate_system(tmp_path):
    from hre.v3.stages import collect_basic_evidence
    source = Image.new("RGB", (20, 10), "black")
    source.paste(Image.new("RGB", (10, 10), "white"), (10, 0))
    reference = Image.new("RGB", (40, 20), "white")
    reference.paste(Image.new("RGB", (20, 20), "black"), (20, 0))
    assets = []
    for role, image in (("source", source), ("appearance_reference", reference)):
        path = tmp_path / (role + ".png")
        image.save(path)
        assets.append({"path": str(path), "sha256": file_sha256(path), "width": image.width,
                       "height": image.height, "mode": "RGB", "role": role})
    regions = [{"id": "dark", "description": "Independently selected dark appearances.",
                "source_box": [0, 0, .5, 1], "reference_box": [.5, 0, 1, 1]}]
    evidence = collect_basic_evidence(assets, regions=regions)
    rois = [record for record in evidence["records"] if record.get("region_id") == "dark"]
    assert len(rois) == 2
    assert all(record["rgb_mean"] == [0.0, 0.0, 0.0] for record in rois)
    assert rois[0]["pixel_box_xyxy"] == [0, 0, 10, 10]
    assert rois[1]["pixel_box_xyxy"] == [20, 0, 40, 20]
    assert rois[0]["evidence_id"] == "evidence:source:region:dark"
    assert "not pixel-aligned" in rois[0]["cross_image_correspondence"]


def test_frozen_prepared_request_cannot_change_before_execution(tmp_path):
    root = make_case(tmp_path, policy="single")
    workers = Workers(accept_after=1)
    prepared = run_case(root, stage_fn=workers.stage, compile_fn=workers.compile,
                        execute_fn=workers.execute, stop_after="condition")
    path = root / prepared["rounds"][0]["request"]["path"]
    value = read_json(path)
    value["seed"] += 123
    write_json(path, value)
    state = run_case(root, stage_fn=workers.stage, compile_fn=workers.compile, execute_fn=workers.execute)
    assert state["status"] == "failed" and state["terminal_reason"] == "artifact_changed"
    assert workers.executions == []


def test_wrong_canvas_native_output_remains_visible_but_is_not_a_deliverable(tmp_path):
    root = make_case(tmp_path, policy="single")
    workers = Workers(accept_after=1)

    def wrong_canvas(request, condition, config, outdir):
        result = workers.execute(request, condition, config, outdir)
        asset = result["outputs"][0]
        Image.new("RGB", (8, 8), "red").save(asset["path"])
        asset.update(width=8, height=8, sha256=file_sha256(Path(asset["path"])))
        return result

    state = run_case(root, stage_fn=workers.stage, compile_fn=workers.compile, execute_fn=wrong_canvas)
    assert state["status"] == "failed" and state["terminal_reason"] == "output_canvas_mismatch"
    assert len(state["candidates"]) == 1 and state["candidates"][0]["native"]["width"] == 8
    assert state["candidates"][0]["delivery_status"] == "invalid"
    assert state["selected_kind"] == "source_baseline" and not state["success"]
    assert state["selected_output"]["width"] == 31


def test_real_direct_dispatch_condition_binding_survives_fixed_prompt_resample(tmp_path):
    from hre.v3.dispatch import request_binding
    root = make_case(tmp_path, strategy="native", policy="resample",
                     policy_overrides={"max_compiler_calls": 0})
    workers = Workers(accept_after=1)
    texts = []

    def inspect_condition(request, condition, config, outdir):
        assert condition["request_binding_sha256"] == request_binding(request)
        texts.append(condition["text"])
        return workers.execute(request, condition, config, outdir)

    state = run_case(root, stage_fn=workers.stage, execute_fn=inspect_condition)
    assert state["success"] and len(workers.executions) == 2
    assert texts[0] == texts[1]
    assert state["selected_candidate_id"] == "r000-p000"
    assert state["budget"]["compiler_calls"] == 0


@pytest.mark.parametrize("operation", ["compile", "generate"])
def test_actual_persistent_worker_envelope_can_reconcile_without_manual_extraction(tmp_path, monkeypatch, operation):
    from hre.v3 import dispatch
    from hre.v3.worker import process_job
    root = make_case(tmp_path, policy="single", compiler_backend="qwen_pe_i2i" if operation == "compile" else "direct")
    workers = Workers(accept_after=1)
    monkeypatch.setattr(dispatch, "_compile_local", workers.compile)
    monkeypatch.setattr(dispatch, "_generate_local", workers.execute)
    response_files = []

    def lost_compile(request, config):
        envelope = {"schema_version": "hre_native_job_v3", "operation": "compile", "request": request,
                    "config": {key: value for key, value in config.items() if key != "worker"}}
        spool = tmp_path / "spool" / digest(envelope)
        envelope["job_dir"] = str(spool)
        process_job(envelope)
        response_files.append(spool / "result.json")
        raise RuntimeError("Lost response after persistent compiler worker finished")

    def lost_generate(request, condition, config, outdir):
        envelope = {"schema_version": "hre_native_job_v3", "operation": "generate", "request": request,
                    "config": {key: value for key, value in config.items() if key != "worker"},
                    "condition": condition, "output_dir": str(outdir)}
        spool = tmp_path / "spool" / digest(envelope)
        envelope["job_dir"] = str(spool)
        process_job(envelope)
        response_files.append(spool / "result.json")
        raise RuntimeError("Lost response after persistent image worker finished")

    compile_fn = lost_compile if operation == "compile" else None
    execute_fn = lost_generate if operation == "generate" else workers.execute
    state = run_case(root, stage_fn=workers.stage, compile_fn=compile_fn, execute_fn=execute_fn)
    assert state["status"] == "paused" and state["pending"]["kind"] == operation
    reconcile(root, "confirmed_result", result_path=response_files[0],
              evidence="The actual persistent fixture service committed this matching job response.")
    recovered = run_case(root, stage_fn=workers.stage, compile_fn=compile_fn, execute_fn=execute_fn)
    assert recovered["success"] and len(workers.executions) == 1
    assert recovered["reconciliations"][0]["worker_response"]["format"] == "verified_native_worker_envelope"
    condition = read_json(root / recovered["rounds"][0]["condition"]["path"])
    request = read_json(root / recovered["rounds"][0]["request"]["path"])
    assert condition["request_binding_sha256"] == dispatch.request_binding(request)
