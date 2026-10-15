from hir_manual.service import Controller
from hir_manual.cache import EvidenceCache
from hir_manual.tool_registry import load_profile, make_contract
from hir_manual.tool_service import ToolService
from hir_manual.storage import read_json,write_json,sha256_file
from local_fixtures import synthetic_registry,face_evidence


def test_planned_cache_auto_composes_and_map_is_not_sent_to_editor(tmp_path,photo,fixture_json):
    entry = synthetic_registry(tmp_path)
    ctl = Controller(tmp_path)
    state = ctl.new(photo,"restore",{"auto_local_tools":True})
    version = read_json(ctl.case(state.case_id).path("input/metadata.json")).get("canonicalizer_version", "hir_rgb8_exif_icc_v1")
    contract = make_contract(state.input_sha256,"T2_FACE",load_profile(),entry, canonicalizer_version=version)
    source = tmp_path/"computed"
    face_evidence(source,contract)
    cache = EvidenceCache(tmp_path/"Data/annotations/cache")
    with cache.lock("T2_FACE",__import__('hir_manual.cache',fromlist=['make_cache_key']).make_cache_key(contract)):
        cache.publish(contract,source)
    diagnosis = fixture_json("diagnosis")
    diagnosis["tool_plan"] = [{"tool":"T2_FACE","reason":"test fixture"}]
    assert ctl.import_json(state.case_id,state.pending_task_id,diagnosis,"fixture").accepted
    ToolService(tmp_path).run_case(state.case_id)
    state = ctl.inspect(state.case_id)
    assert state.workflow_status == "WAIT_COMPOSITION"
    req = ctl.current_task(state.case_id)
    assert any(a.kind == "overlay" for a in req.allowed_assets)
    snapshot = ctl.case(state.case_id).path("tools/evidence_snapshot.json")
    before = sha256_file(snapshot)
    assert ctl.import_json(state.case_id,req.task_id,fixture_json("composition"),"fixture").accepted
    req = ctl.current_task(state.case_id)
    assert [a.path for a in req.allowed_assets] == ["input/canonical.png"]
    assert sha256_file(snapshot) == before


def test_partial_policy_records_unavailable_not_empty(tmp_path,photo,fixture_json):
    ctl = Controller(tmp_path)
    state = ctl.new(photo,"restore",{"auto_local_tools":True})
    diagnosis = fixture_json("diagnosis")
    diagnosis["tool_plan"] = [{"tool":"T2_FACE","reason":"fixture"}]
    ctl.import_json(state.case_id,state.pending_task_id,diagnosis,"fixture")
    ctl.record_tool_unavailable(state.case_id,"T2_FACE","import_error","test SDK failure")
    state = ctl.inspect(state.case_id)
    assert state.workflow_status == "WAIT_COMPOSITION" and state.deviated
    assert state.received_tools == []
    assert ctl.current_task(state.case_id).context["unavailable_tools"]["T2_FACE"]["code"] == "import_error"


def test_strict_policy_blocks_without_silent_downgrade(tmp_path,photo,fixture_json):
    ctl = Controller(tmp_path)
    profile = load_profile().model_dump()
    profile["evidence_failure_policy"] = "all_planned_tools_required"
    state = ctl.new(photo,"restore",{"auto_local_tools":True,"evidence_profile":profile})
    diagnosis = fixture_json("diagnosis")
    diagnosis["tool_plan"] = [{"tool":"T2_FACE","reason":"fixture"}]
    ctl.import_json(state.case_id,state.pending_task_id,diagnosis,"fixture")
    state = ctl.record_tool_unavailable(state.case_id,"T2_FACE","oom","test allocation failure")
    assert state.workflow_status == "WAIT_EVIDENCE" and state.operation_status == "blocked"


def test_manual_v11_uses_same_validation_and_binding(tmp_path,photo,fixture_json):
    entry = synthetic_registry(tmp_path)
    ctl = Controller(tmp_path)
    state = ctl.new(photo,"restore")
    diagnosis = fixture_json("diagnosis")
    diagnosis["tool_plan"] = [{"tool":"T2_FACE","reason":"fixture"}]
    ctl.import_json(state.case_id,state.pending_task_id,diagnosis,"fixture")
    version = read_json(ctl.case(state.case_id).path("input/metadata.json")).get("canonicalizer_version", "hir_rgb8_exif_icc_v1")
    contract = make_contract(state.input_sha256,"T2_FACE",load_profile(),entry, canonicalizer_version=version)
    face_evidence(tmp_path/"manual",contract)
    state = ctl.register_evidence(state.case_id,tmp_path/"manual/evidence.json")
    assert state.workflow_status == "WAIT_COMPOSITION"
    assert ctl.current_task(state.case_id).context["evidence"][0]["cache_key"] == __import__('hir_manual.cache',fromlist=['make_cache_key']).make_cache_key(contract)


def test_new_case_job_uses_metadata_version_without_running_worker(tmp_path, photo, fixture_json):
    synthetic_registry(tmp_path)
    ctl = Controller(tmp_path)
    state = ctl.new(photo, "restore")
    diagnosis = fixture_json("diagnosis")
    diagnosis["tool_plan"] = [{"tool": "T2_FACE", "reason": "fixture"}]
    ctl.import_json(state.case_id, state.pending_task_id, diagnosis, "fixture")
    job = ToolService(tmp_path).resolve_or_enqueue(ctl.case(state.case_id), "T2_FACE")
    assert job.cache_contract["canonicalizer_version"] == "hir_rgb8_exif_icc_v2_stablepng"
    assert ctl.inspect(state.case_id).received_tools == []


def test_unversioned_case_keeps_v1_jobs_and_evidence(tmp_path, photo, fixture_json, monkeypatch):
    import hir_manual.cases as cases
    save = cases.write_json
    def legacy_metadata(path, value):
        if path.name == "metadata.json":
            value = {k: v for k, v in value.items() if k != "canonicalizer_version"}
        return save(path, value)
    monkeypatch.setattr(cases, "write_json", legacy_metadata)
    entry = synthetic_registry(tmp_path)
    ctl = Controller(tmp_path)
    state = ctl.new(photo, "restore")
    case = ctl.case(state.case_id)
    before = case.path("input/metadata.json").read_bytes()
    diagnosis = fixture_json("diagnosis")
    diagnosis["tool_plan"] = [{"tool": "T2_FACE", "reason": "fixture"}]
    ctl.import_json(state.case_id, state.pending_task_id, diagnosis, "fixture")
    job = ToolService(tmp_path).resolve_or_enqueue(case, "T2_FACE")
    assert job.cache_contract["canonicalizer_version"] == "hir_rgb8_exif_icc_v1"
    contract = make_contract(state.input_sha256, "T2_FACE", load_profile(), entry)
    face_evidence(tmp_path / "legacy_manual", contract)
    state = ctl.register_evidence(state.case_id, tmp_path / "legacy_manual/evidence.json")
    assert state.workflow_status == "WAIT_COMPOSITION"
    assert case.path("input/metadata.json").read_bytes() == before


def test_new_case_rejects_legacy_cache_even_with_same_pixel_png(tmp_path, photo, fixture_json):
    import pytest
    entry = synthetic_registry(tmp_path)
    ctl = Controller(tmp_path)
    state = ctl.new(photo, "restore")
    diagnosis = fixture_json("diagnosis")
    diagnosis["tool_plan"] = [{"tool": "T2_FACE", "reason": "fixture"}]
    ctl.import_json(state.case_id, state.pending_task_id, diagnosis, "fixture")
    legacy = make_contract(state.input_sha256, "T2_FACE", load_profile(), entry)
    source = tmp_path / "legacy_result"
    face_evidence(source, legacy)
    published = EvidenceCache(tmp_path / "Data/annotations/cache").publish(legacy, source)
    with pytest.raises(ValueError, match="Cache differs"):
        ctl.accept_local_evidence(state.case_id, published)
    with pytest.raises(ValueError):
        ctl.register_evidence(state.case_id, source / "evidence.json")
    assert ctl.inspect(state.case_id).received_tools == []


def test_prepare_job_reads_actual_source_metadata_for_offline_cli(tmp_path, photo):
    from hir_manual.tool_jobs import prepare_job
    from hir_manual.tool_registry import load_registry
    synthetic_registry(tmp_path)
    ctl = Controller(tmp_path)
    state = ctl.new(photo, "restore")
    case = ctl.case(state.case_id)
    metadata = read_json(case.path("input/metadata.json"))
    job, _ = prepare_job(tmp_path, case.path("input/canonical.png"), metadata["original_sha256"],
                         "fixture", "T2_FACE", load_profile(), load_registry(tmp_path))
    assert job.cache_contract["canonicalizer_version"] == "hir_rgb8_exif_icc_v2_stablepng"


def test_prepare_job_cannot_relabel_a_versioned_case(tmp_path, photo):
    import pytest
    from hir_manual.tool_jobs import prepare_job
    from hir_manual.tool_registry import load_registry
    synthetic_registry(tmp_path)
    ctl = Controller(tmp_path)
    state = ctl.new(photo, "restore")
    case = ctl.case(state.case_id)
    before = case.path("input/metadata.json").read_bytes()
    metadata = read_json(case.path("input/metadata.json"))
    with pytest.raises(ValueError, match="differs from source metadata"):
        prepare_job(tmp_path, case.path("input/canonical.png"), metadata["original_sha256"],
                    "fixture", "T2_FACE", load_profile(), load_registry(tmp_path),
                    canonicalizer_version="hir_rgb8_exif_icc_v1")
    assert case.path("input/metadata.json").read_bytes() == before
    assert not (tmp_path / "runtime/tool_jobs").exists()
