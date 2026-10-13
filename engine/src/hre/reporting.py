"""Transparent reports from retained case files and actual selected asset."""
from pathlib import Path
from .assets import validate_asset
from .models import file_sha256
from .paths import safe_path
from .selection import selected_candidate_asset
from .storage import CaseStore, atomic_write, read_json, write_json


def _events(root: Path) -> list[dict]:
    records = []
    seen = set()
    for path in sorted((root / "transactions").glob("*.json")):
        transaction = read_json(path)
        event = dict(transaction.get("event", {}), event_id=transaction.get("event_id", str(path)))
        identity = event["event_id"]
        if identity not in seen:
            seen.add(identity)
            records.append(event)
    return records


def cost_summary(state: dict, events: list[dict]) -> dict:
    budget = state["budget"]
    ledger = budget["ledger"]
    confirmed = sum(1 for entry in ledger if entry.get("charged_count", 0) > 0)
    known_extra = sum(max(0, entry.get("charged_count", 0) - 1) for entry in ledger)
    intents = {event.get("payload", event).get("generation_id") for event in events if event.get("type", event.get("event")) in {"execution_intent", "submission_intent"}}
    uncertain = sum(1 for entry in ledger if entry.get("status") == "reserved" and (entry.get("generation_id") in intents or entry.get("outcome") == "unknown"))
    observations = [event.get("payload", event) for event in events]
    known_status = [o["backend_regeneration_count_status"] for o in observations if "backend_regeneration_count_status" in o]
    bills = [o for o in observations if isinstance(o.get("observed_billed_cost"), (float, int))]
    currencies = {o.get("currency") for o in bills}
    billed = sum(o["observed_billed_cost"] for o in bills) if bills and len(currencies) == 1 else None
    responses = [event for event in events if event.get("type") == "response_accepted" and event.get("payload", {}).get("stage") in {"diagnose", "compose", "verify", "refine"}]
    return {"generation_cap": budget["max_generations"], "observed_generation_submissions": confirmed,
            "known_backend_regenerations": known_extra, "uncertain_submission_reservations": uncertain,
            "accounted_generations": budget["consumed"] + uncertain, "consumed": budget["consumed"],
            "reserved": budget["reserved"], "held_budget": budget["consumed"] + budget["reserved"],
            "backend_regeneration_count_status": "known" if confirmed and len(known_status) >= confirmed and all(s == "known" for s in known_status) else "unknown",
            "text_or_vision_stage_calls": len(responses), "stage_call_count_scope": "accepted responses only; unobserved calls remain unknown",
            "format_repairs": sum(event.get("type") == "format_repair" for event in events),
            "failures_and_regenerations": [o for o in observations if o.get("status") == "error" or o.get("error_type") or o.get("extra_count")],
            "wall_seconds": next((o["wall_seconds"] for o in reversed(observations) if "wall_seconds" in o), None),
            "manual_active_minutes": sum(o["manual_active_minutes"] for o in observations if isinstance(o.get("manual_active_minutes"), (float, int))) if any("manual_active_minutes" in o for o in observations) else None,
            "observed_billed_cost": billed, "currency": next(iter(currencies)) if billed is not None else None,
            "subscription_cost_allocation_method": next((o["subscription_cost_allocation_method"] for o in reversed(observations) if "subscription_cost_allocation_method" in o), None),
            "cost_unknown_fraction": None if not observations else sum("observed_billed_cost" not in o or o["observed_billed_cost"] is None for o in observations) / len(observations)}


def resolve_selected_asset(state: dict) -> dict | None:
    selection = state.get("selection")
    if selection is None:
        return None
    if selection["kind"] == "baseline":
        assets = [a for a in state["inputs"] if a["role"] == "prediction"]
    else:
        candidates = [c for c in state["candidates"] if c["candidate_id"] == selection["candidate_id"] and c["round"] == selection["selected_round"]]
        assets = [selected_candidate_asset(c) for c in candidates]
    matches = [asset for asset in assets if asset["asset_id"] == selection["asset_id"]]
    if len(matches) != 1:
        raise ValueError("selection does not map to one actual delivered asset")
    return matches[0]


def write_report(case_root: Path) -> Path:
    root = Path(case_root)
    state = CaseStore(root).load()
    config = read_json(root / "config.json")
    selected = resolve_selected_asset(state)
    assets = list(state["inputs"])
    for candidate in state["candidates"]:
        assets.append(candidate["asset"])
        if candidate["geometry"].get("derived_asset"):
            assets.append(candidate["geometry"]["derived_asset"])
        geometry = candidate["geometry"]
        if geometry.get("report_path"):
            if file_sha256(safe_path(root, geometry["report_path"], must_exist=True)) != geometry["report_sha256"]:
                raise ValueError("geometry report hash changed")
    for asset in assets:
        validate_asset(asset, root)
    if state.get("success") and (state["workflow_state"] != "COMPLETED" or not selected or state["selection"]["review_required"]):
        raise ValueError("inconsistent successful terminal selection")
    events = _events(root)
    accepted_responses = []
    for transaction_path in sorted((root / "transactions").glob("*.json")):
        accepted = read_json(transaction_path).get("accepted_submission")
        if accepted:
            path = safe_path(root, accepted["response_path"], must_exist=True)
            if file_sha256(path) != accepted["response_sha256"]:
                raise ValueError("accepted response hash changed")
            response = read_json(path)
            accepted_responses.append({"path": path.relative_to(root).as_posix(), "sha256": file_sha256(path), "response": response})
    provenance = [dict(r["response"].get("model_observed", {}), session_id=r["response"].get("session_id")) for r in accepted_responses]
    fields = {"ui_model_name": "ui_model_name", "model_version": "exact_model_version", "model_seed": "seed", "session_id": "session_id"}
    metadata = {key: next((p[source] for p in reversed(provenance) if p.get(source) is not None), "unknown" if key != "session_id" else None) for key, source in fields.items()}
    summary = {"schema_version": state["schema_version"], "case_id": state["case_id"], "case_revision": state["case_revision"],
               "state_revision": state["revision"], "profile_id": state["profile_id"], "workflow_state": state["workflow_state"],
               "success": state["success"], "terminal_reason": state["terminal_reason"], "selection": state["selection"],
               "selected_asset": selected, "selected_file_sha256": selected["sha256"] if selected else None,
               "inputs": state["inputs"], "candidates": state["candidates"], "config": config,
               "config_sha256": state["config_sha256"], "state_file_sha256": file_sha256(root / "state.json"),
               "accepted_responses": accepted_responses, "events": events, "costs": cost_summary(state, events),
               "model_metadata": metadata, "deviations": state.get("deviations", []),
               "limitations": ["0.7 confidence is an engineering heuristic, not a calibrated probability.", "Pixel geometry gate does not establish content preservation.", "Workflow verifier is not independent final evaluation.", "Unknown model versions, seeds and costs remain unknown; no inferred billing."]}
    final = root / "final"
    final.mkdir(parents=True, exist_ok=True)
    write_json(final / "summary.json", summary)
    write_json(final / "selection.json", {"selection": state["selection"], "success": state["success"], "terminal_reason": state["terminal_reason"], "selected_asset": selected})
    rows = ["# Reference enhancement case report", "", f"Case: {state['case_id']} revision {state['case_revision']}",
            f"Workflow: {state['workflow_state']}; success: {state['success']}; reason: {state['terminal_reason']}", "",
            f"Selected asset: {selected['asset_id'] if selected else 'pending'}",
            f"Actual selected SHA256: {selected['sha256'] if selected else 'pending'}", "", "All candidates and verification history are retained in summary.json.", "",
            "| Round | Candidate | Delivered SHA256 | Geometry | Usable | Accepted |", "|---|---|---|---|---|---|"]
    for c in state["candidates"]:
        rows.append(f"| {c['round']} | {c['candidate_id']} | {selected_candidate_asset(c)['sha256']} | {c['geometry']['status']} | {c.get('usable')} | {c.get('accepted')} |")
    rows += ["", "Costs and metadata", "", "```json", __import__("json").dumps({"costs": summary["costs"], "model_metadata": metadata}, indent=2), "```", ""]
    if selected:
        rows += ["", f"![Actual selected asset](../{selected['path']})", ""]
    rows += summary["limitations"]
    path = final / "report.md"
    atomic_write(path, ("\n".join(rows) + "\n").encode())
    return path
