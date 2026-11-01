"""Round-two read-only review: synthetic files, real production APIs, no network."""
from pathlib import Path
import json, sys, tempfile
from copy import deepcopy

REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(REPO / "engine/src"), str(REPO / "engine/tests"), str(REPO / "engine/tests/reference_style")]
from hre.reference_core import study
from hre.reference_style import unified
from hre.v3.runner import import_candidate_review
from hre.v3.common import digest
from test_reference_study import specification, result_spec, rating_spec
from test_unified_review_repairs import UnifiedReviewRepairTest
from test_v3_reference_v2 import make, run

out = {"candidate_sha": "7eaec58e97ac03bbe4a117d4692a0863e758e49a", "fixture_kind": "synthetic local protocol evidence only"}

for field in ("confidence", "independence"):
    with tempfile.TemporaryDirectory(prefix="review-round2-study-") as tmp:
        p = Path(tmp); spec = specification(p); root = p / "study"
        plan = study.build_study(root, spec); r = plan["payload"]["runs"][0]
        result = study.import_result(root, result_spec(plan, r, Path(spec["pairs"][0]["reference"])))
        first = study.import_rating(root, rating_spec(result, r)); other = rating_spec(result, r, "r2", "reviewer2")
        other[field] = "low" if field == "confidence" else "same_model"
        second = study.import_rating(root, other); row = study.summarize(root)["runs"][0]
        assert row["task_success"] is None and row["effective_edit_success"] is None
        assert row["rating_conflict_fields"] == [field]
        study.adjudicate(root, dict(adjudication_id="a1", run_id=r["run_id"], result_hash=result["content_hash"],
            rating_hashes=[first["content_hash"], second["content_hash"]], selected_rating_hash=first["content_hash"],
            reason="Explicit independent full-rating review fixture"))
        assert study.summarize(root)["runs"][0]["task_success"] is True
        out["study_" + field] = dict(before="unknown", conflict_fields=row["rating_conflict_fields"], after="true_after_explicit_adjudication")

t = UnifiedReviewRepairTest(); t.setUp()
try:
    f = t.configured(detail=True, conflict_stage="explanations")
    chain_root = f.case / "unified/holistic" / t.holistic[0]["payload"]["images"][2]["sha256"]
    old_bytes = {p: p.read_bytes() for p in (chain_root / "holistic").glob("*.json")}
    previous = None
    for n, mode in enumerate(("low_confidence", "same_model", "qualified"), 1):
        resolution = t.resolution()
        resolution["resolution_id"] = "resolution" + str(n)
        if previous: resolution["predecessor_hash"] = previous["content_hash"]
        if mode == "low_confidence": resolution["resolutions"][0]["confidence"] = "medium"
        if mode == "same_model": resolution["reviewer"]["independence"] = "same_model"
        previous = unified.resolve_holistic(f.case, resolution)
        actual = unified.holistic_for_evaluation(f.case, f.evaluation)["status"]
        assert actual == ("accepted" if mode == "qualified" else "needs_user_review")
        out["holistic_" + mode] = actual
    assert all(p.read_bytes() == b for p, b in old_bytes.items())
    req = unified.detail_request(f.case, "j1")
    assert req["binding"] == {k: t.detail_spec()["detail"][k] for k in req["binding"]}
    before = unified.delivery_for_evaluation(f.case, f.verifier.co._status(f.case), f.evaluation)
    assert before["status"] == "uncertain"
    first = unified.import_detail(f.case, t.detail_spec())
    passed = f.decision(t.facts)
    assert passed["payload"]["status"] == "accepted"
    newer = t.detail_spec("unknown"); newer["detail"]["review_id"] = "native_unknown"
    newer["predecessor_hash"] = first["content_hash"]
    unified.import_detail(f.case, newer)
    try:
        f.verifier.select(f.case, dict(selection_id="sel1", version="q1", decision_ids=["z1"], rule_version="first_accepted_generation_order_v1"))
    except ValueError as exc:
        out["stale_detail_selection"] = str(exc)
    else:
        raise AssertionError("old accepted decision reused after new unknown native-detail evidence")
    fresh = f.decision(t.facts, decision_id="z2", predecessor=dict(decision_id="z1", hash=passed["content_hash"]))
    assert fresh["payload"]["status"] == "delivery_not_met"
    out["style_detail"] = dict(missing=before["status"], qualified="accepted", newer_unknown=fresh["payload"]["status"], original_holistic_bytes_preserved=True)
finally:
    t.doCleanups()

with tempfile.TemporaryDirectory(prefix="review-round2-current-") as tmp:
    root, worker = make(Path(tmp), policy="feedback", generations=3)
    def pending(v, count):
        v.update(verdict="uncertain", issues=[])
        v["target_results"][0]["status"] = "uncertain"
    worker.mutate_verify = pending
    state = run(root, worker); candidate = state["candidates"][0]
    from test_v3_reference_contract import verification_fixture
    payload = verification_fixture(worker.intent)
    payload.update(overall_style=deepcopy(candidate["whole_image_review"]["overall_style"]), whole_image_review_sha256=digest(candidate["whole_image_review"]))
    reviewed = import_candidate_review(root, dict(candidate_id=candidate["candidate_id"], round=0,
        native_sha256=candidate["native"]["sha256"], delivered_sha256=candidate["delivered"]["sha256"],
        predecessor_sha256=digest(candidate["verification_versions"][-1]), whole_image_review=deepcopy(candidate["whole_image_review"]), verification=payload))
    assert reviewed["success"] and reviewed["budget"] == state["budget"] and len(worker.executions) == 1
    out["current_review_accept"] = dict(before=state["status"], after=reviewed["status"], success=reviewed["success"], image_calls=len(worker.executions), budgets_unchanged=True)

print(json.dumps(out, indent=2))
