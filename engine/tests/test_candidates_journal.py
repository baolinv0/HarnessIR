import pytest

from hre.models import HREError
from hre.storage import read_json, write_json


def test_completed_replay_and_request_identity(tmp_path):
    from hre.candidates.journal import Journal
    journal = Journal(tmp_path, {"planner": 1})
    calls = []
    assert journal.invoke("E1/planner/0", "planner", {"a": 1}, lambda: calls.append(1) or {"value": 4}) == {"value": 4}
    assert journal.invoke("E1/planner/0", "planner", {"a": 1}, lambda: pytest.fail("replayed call")) == {"value": 4}
    assert calls == [1]
    with pytest.raises(HREError, match="request_replay_mismatch"):
        journal.invoke("E1/planner/0", "planner", {"a": 2}, lambda: {})


def test_failed_replays_error_and_keeps_budget(tmp_path):
    from hre.candidates.journal import Journal
    journal = Journal(tmp_path, {"planner": 1})
    def fail():
        raise HREError("invalid_model_reply", "bad result")
    with pytest.raises(HREError, match="invalid_model_reply"):
        journal.invoke("p", "planner", {}, fail)
    with pytest.raises(HREError, match="invalid_model_reply"):
        journal.invoke("p", "planner", {}, lambda: pytest.fail("failed operation was retried"))
    with pytest.raises(HREError, match="budget_exhausted"):
        journal.invoke("p2", "planner", {}, lambda: {})


def test_unknown_never_retries_and_reconcile_is_idempotent(tmp_path):
    from hre.candidates.journal import Journal
    journal = Journal(tmp_path, {"image_generation": 1})
    with pytest.raises(HREError, match="operation_unknown"):
        journal.invoke("image", "image_generation", {}, lambda: (_ for _ in ()).throw(TimeoutError("lost")))
    with pytest.raises(HREError, match="operation_unknown"):
        journal.invoke("image", "image_generation", {}, lambda: pytest.fail("unknown resent"))
    operation = journal.snapshot()["operations"]["image"]
    directory = tmp_path / "reconciliation"
    directory.mkdir()
    write_json(directory / "response.json", {"value": 1})
    from hre.candidates.contracts import digest
    write_json(directory / "receipt.json", {"operation_id": "image", "request_sha256": operation["request_sha256"], "response_sha256": digest({"value": 1})})
    resolution = {"schema_version": "hre_candidates_v1", "record_type": "reconciliation", "operation_id": "image", "request_sha256": operation["request_sha256"], "decision": "confirmed_completed", "operator": "tester", "reason": "worker receipt", "evidence_refs": ["reconciliation/receipt.json"], "response_path": "reconciliation/response.json", "receipt_path": "reconciliation/receipt.json"}
    result = journal.reconcile("image", resolution)
    assert result["state"] == "completed"
    assert journal.reconcile("image", resolution) == result
    assert journal.invoke("image", "image_generation", {}, lambda: pytest.fail("reconciled call resent")) == {"value": 1}


def test_orphaned_submitted_is_unknown(tmp_path):
    from hre.candidates.journal import Journal
    journal = Journal(tmp_path, {"planner": 2})
    journal.invoke("p", "planner", {}, lambda: {"ok": True})
    ledger = read_json(tmp_path / "operations.json")
    ledger["operations"]["p"]["state"] = "submitted"
    write_json(tmp_path / "operations.json", ledger)
    with pytest.raises(HREError, match="operation_unknown"):
        Journal(tmp_path, {"planner": 2}).invoke("p", "planner", {}, lambda: pytest.fail("orphan resent"))


def test_variant_total_covers_all_call_kinds(tmp_path):
    from hre.candidates.journal import Journal
    limits = {"judge_J1_primary": 2, "judge_J1_format_repair": 1, "judge_J1_total": 2}
    journal = Journal(tmp_path, limits)
    journal.invoke("primary1", "judge_J1_primary", {}, lambda: {}, group="J1")
    journal.invoke("primary2", "judge_J1_primary", {}, lambda: {}, group="J1")
    with pytest.raises(HREError, match="budget_exhausted"):
        journal.invoke("repair", "judge_J1_format_repair", {}, lambda: {}, group="J1")


def test_missing_limit_and_path_escape_rejected(tmp_path):
    from hre.candidates.journal import Journal
    journal = Journal(tmp_path, {})
    with pytest.raises(HREError, match="budget"):
        journal.invoke("p", "planner", {}, lambda: {})
    with pytest.raises(HREError):
        journal.invoke("../escape", "planner", {}, lambda: {})


def test_completed_response_tampering_rejected(tmp_path):
    from hre.candidates.journal import Journal
    journal = Journal(tmp_path, {"planner": 1})
    journal.invoke("p", "planner", {}, lambda: {"ok": True})
    operation = journal.snapshot()["operations"]["p"]
    write_json(tmp_path / operation["response_path"], {"ok": False})
    with pytest.raises(HREError, match="modified"):
        journal.invoke("p", "planner", {}, lambda: pytest.fail("tampered response resent"))


def test_base_exception_during_call_remains_unknown_on_same_journal(tmp_path):
    from hre.candidates.journal import Journal
    journal = Journal(tmp_path, {"planner": 1})
    def crash():
        raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        journal.invoke("p", "planner", {}, crash)
    with pytest.raises(HREError, match="operation_unknown"):
        journal.invoke("p", "planner", {}, lambda: pytest.fail("crashed request resent"))


def test_worker_lost_response_is_unknown(tmp_path):
    from hre.candidates.journal import Journal
    journal = Journal(tmp_path, {"image_generation": 1})
    def lost():
        raise HREError("worker_submission_unknown", "worker lost response")
    with pytest.raises(HREError, match="operation_unknown"):
        journal.invoke("p", "image_generation", {}, lost)
    assert journal.snapshot()["operations"]["p"]["state"] == "unknown"


def test_not_executed_proof_keeps_call_allowance_consumed(tmp_path):
    from hre.candidates.journal import Journal
    journal = Journal(tmp_path, {"planner": 1})
    with pytest.raises(HREError):
        journal.invoke("p", "planner", {}, lambda: (_ for _ in ()).throw(TimeoutError()))
    operation = journal.snapshot()["operations"]["p"]
    proof = tmp_path / 'reconciliation' / 'proof.json'
    write_json(proof, {"operation_id": "p", "request_sha256": operation['request_sha256'], "not_executed": True})
    resolution = {"schema_version": "hre_candidates_v1", "record_type": "reconciliation", "operation_id": "p", "request_sha256": operation['request_sha256'], "decision": "confirmed_not_executed", "operator": "tester", "reason": "worker did not accept", "evidence_refs": ['reconciliation/proof.json']}
    assert journal.reconcile('p', resolution)['state'] == 'failed'
    with pytest.raises(HREError, match='confirmed_not_executed'):
        journal.invoke('p', 'planner', {}, lambda: pytest.fail('nonexecution was retried'))
    with pytest.raises(HREError, match='budget_exhausted'):
        journal.invoke('p2', 'planner', {}, lambda: {})
