import uuid
from PIL import Image
from .models import Artifact, Request
from .prompts import encoded, render_prompt
from .protocol import ROLE_SCHEMAS, validate_schema
from .storage import atomic_write, read_json, sha256_file, write_json


def asset_for(case, relative: str, kind="photo") -> Artifact:
    width = height = None
    if kind in ("photo", "map", "overlay"):
        with Image.open(case.path(relative)) as im:
            width, height = im.size
    return Artifact(path=relative, sha256=sha256_file(case.path(relative)), kind=kind, width=width, height=height)


def issue_task(case, state, role: str, context: dict) -> Request:
    """Prepare immutable files; caller commits their hashes before exposing task."""
    task_id = role + "_" + uuid.uuid4().hex[:16]
    prefix = f"tasks/{task_id}"
    config = read_json(case.path("case_config.json"))
    original_path = "input/canonical.png"
    upload = None
    if role in ("execute", "verify") and config.get("desktop_original_rgb_equivalent_upload") is True:
        # Explicit transport policy: upload existing original bytes, never resize
        # or recompress. Canonical identity remains the internal cache identity.
        from .transport import image_observations
        metadata = read_json(case.path("input/metadata.json"))
        original_path = metadata["original_path"]
        if case.path(original_path).stat().st_size > 20_000_000:
            raise ValueError("Original exceeds the declared desktop upload budget")
        canonical = image_observations(case.path("input/canonical.png"), case.path("input/canonical.png"), config)
        native = image_observations(case.path(original_path), case.path("input/canonical.png"), config)
        if metadata["operations"] or native["pixel_sha256"] != canonical["pixel_sha256"] or (native["width"], native["height"]) != (canonical["width"], canonical["height"]):
            raise ValueError("Original upload is not a verified pixel-identical canonical equivalent")
        upload = {"policy": "original_rgb_equivalent_v1", "file_sha256": metadata["original_sha256"],
                  "canonical_sha256": state.input_sha256, "pixel_sha256": native["pixel_sha256"],
                  "reencoded": False, "resized": False}
    assets = [asset_for(case, original_path)]
    if role in ("compose", "refine"):
        for manifest in context.get("evidence", []):
            assets.extend(Artifact.model_validate(a) for a in manifest["assets"] if a["kind"] in ("map", "overlay", "photo"))
    if role in ("verify", "refine"):
        assets.extend(Artifact.model_validate(a["output_asset"]) for a in context.get("attempts", []))
    schema_name = ROLE_SCHEMAS[role]
    schema = read_json(case.path(f"snapshot/schemas/{schema_name}"))
    # Role contexts are constructed separately, never copy an unrestricted context.
    attachments = []
    for i, asset in enumerate(assets):
        entry = asset.model_dump() | {"picture_number": i + 1, "label": "original" if i == 0 else asset.kind}
        attempt = next((a for a in context.get("attempts", []) if a["output_asset"]["path"] == asset.path), None)
        if attempt:
            entry.update(label=f"attempt {attempt['index']} (round {attempt['round']})", attempt_index=attempt["index"], round=attempt["round"], task_id=attempt["task_id"])
        for evidence in context.get("evidence", []):
            if any(a["path"] == asset.path for a in evidence["assets"]):
                entry.update(tool_id=evidence["tool_id"], legend=evidence["data"])
        attachments.append(entry)
    common = {"intent": config["intent"], "payload_schema_json": encoded(schema), "attachment_manifest_json": encoded(attachments)}
    if role == "diagnose":
        role_context = {"statistics_json": encoded(context.get("statistics", {}))}
        request_context = {"intent": config["intent"], "statistics": context.get("statistics", {})}
    elif role in ("compose", "refine"):
        evidence_context = {"available": context.get("evidence", []), "unavailable": context.get("unavailable_tools", {}),
                            "excluded": context.get("excluded_tools", {}),
                            "partial_evidence": bool(context.get("unavailable_tools") or context.get("excluded_tools"))}
        role_context = {"diagnosis_json": encoded(context["diagnosis"]), "evidence_json": encoded(evidence_context)}
        request_context = {"intent": config["intent"], "diagnosis": context["diagnosis"], "evidence": context.get("evidence", []),
                           "unavailable_tools": context.get("unavailable_tools", {}), "excluded_tools": context.get("excluded_tools", {}),
                           "attempts": context.get("attempts", [])}
        if role == "refine":
            role_context.update(previous_instruction=context["previous_instruction"], verification_json=encoded(context["verification"]))
            request_context.update(previous_instruction=context["previous_instruction"], verification=context["verification"])
    elif role == "execute":
        role_context = {"instruction": context["instruction"]}
        common = {}
        request_context = {"instruction": context["instruction"], "instruction_sha256": context["instruction_sha256"], "request_one_image": True, "new_session_required": True}
    else:
        role_context = {"task_types_json": encoded(context.get("task_types", [])), "measurements_json": encoded(context.get("measurements", {}))}
        request_context = {"intent": config["intent"], "checklist": config["checklist"], "attempts": context["attempts"], "task_types": context.get("task_types", []), "measurements": context.get("measurements", {}), "independent_session_required": True}
    if upload is not None:
        request_context["original_upload_transport"] = upload
    rendered = render_prompt(role, common | role_context, case.path("snapshot"))
    request = Request(task_id=task_id, case_id=state.case_id, role=role, round=state.round, attempt_index=state.round - 1, expected_state_revision=state.revision + 1, input_sha256=state.input_sha256, template_sha256=sha256_file(case.path(f"snapshot/prompts/{role}.j2")), prompt_file=f"{prefix}/prompt.txt", payload_schema=schema_name, allowed_assets=assets, context=request_context, response_file=f"{prefix}/response.json", ready_marker=f"{prefix}/done.json")
    validate_schema("request.schema.json", request.model_dump(), case.path("snapshot/schemas"))
    atomic_write(case.path(request.prompt_file), rendered.encode("utf-8"))
    write_json(case.path(f"{prefix}/request.json"), request)
    if role != "execute":
        adapter = "\n\nLOCAL WORK FILE HANDOFF: Inspect every allowed image with an image viewer. Read request.json. Return the role payload; use the local file bridge to calculate hashes and write response.json and done.json last. Do not modify state.json. If file access is unavailable, return only payload JSON for manual import.\n"
        atomic_write(case.path(f"{prefix}/work_task.txt"), (rendered + adapter + f"Request absolute path: {case.path(f'{prefix}/request.json')}\n" + "Allowed assets:\n" + "\n".join(str(case.path(a.path)) for a in assets)).encode("utf-8"))
    return request
