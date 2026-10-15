import io
import uuid
from pathlib import Path

from PIL import Image, ImageCms, ImageOps

from .models import Budget, NextAction, State
from .protocol import DESIGN_DIR, schema_validator
from .storage import CasePaths, atomic_write, commit, now, read_json, sha256_bytes, sha256_file, write_json, writer_lock


def create_case(root: Path, source: Path, intent: str, config: dict) -> State:
    with writer_lock(root):
        return create_case_locked(root, source, intent, config)


def create_case_locked(root: Path, source: Path, intent: str, config: dict) -> State:
    if not intent.strip():
        raise ValueError("Intent is required")
    defaults = read_json(DESIGN_DIR / "config/defaults.json")
    from .tool_registry import CANONICALIZER_VERSION, load_profile, load_registry
    profile_id = config.get("evidence_profile_id", "cpu_probe_v1")
    profile = load_profile(profile_id, root)
    defaults.update(auto_local_tools=False, evidence_profile_id=profile_id, evidence_profile=profile.model_dump(), tool_registry=load_registry(root, profile_id).model_dump(), engine_version="1.1.0")
    defaults.update(config)
    if defaults["read_chat_history"] or defaults["automatic_login"]:
        raise ValueError("Chat history access and automatic login prohibited")
    if defaults["executor"] == "gemini_api_image":
        from .gemini_api import validate_configuration
        validate_configuration(defaults)
        if defaults["max_generations"] > 3:
            raise ValueError("Gemini alternative permits at most three image generations")
        defaults["branch_type"] = "manual_variant"
    elif defaults["executor"] != "chatgpt_desktop_image" or defaults["external_api_calls"]:
        raise ValueError("Select ChatGPT desktop or the explicit Gemini API alternative")
    if not 1 <= defaults["max_generations"] <= 10:
        raise ValueError("Invalid generation budget")
    source = Path(source)
    if source.stat().st_size > defaults["max_input_bytes"]:
        raise ValueError("Image exceeds byte limit; use a separate explicit preprocessing profile")
    raw = source.read_bytes()
    operations = []
    with Image.open(io.BytesIO(raw)) as original:
        if original.width * original.height > defaults["max_input_pixels"]:
            raise ValueError("Image exceeds pixel limit; no silent resizing")
        if original.format not in ("PNG", "JPEG", "TIFF", "WEBP", "BMP") or getattr(original, "n_frames", 1) != 1:
            raise ValueError("Use one supported display-domain photograph")
        original.load()
        original_format = original.format
        orientation = original.getexif().get(274, 1)
        canonical = ImageOps.exif_transpose(original)
        if orientation != 1:
            operations.append("EXIF_orientation")
        icc = original.info.get("icc_profile")
        if icc:
            try:
                canonical = ImageCms.profileToProfile(canonical, ImageCms.ImageCmsProfile(io.BytesIO(icc)), ImageCms.createProfile("sRGB"), outputMode="RGB")
            except Exception as exc:
                raise ValueError("Cannot interpret embedded ICC; explicit preprocessing needed") from exc
            operations.append("ICC_to_sRGB")
        elif canonical.mode not in ("RGB", "L"):
            raise ValueError("Ambiguous/transparent colour mode; explicitly preprocess uniformly first")
        canonical = canonical.convert("RGB")
        # Pixels are now RGB8 in sRGB. Pillow retains the destination ICC in
        # info, including ImageCms's creation timestamp; never embed that or
        # source EXIF/ancillary metadata into the canonical PNG identity.
        canonical.info.clear()
        buffer = io.BytesIO()
        canonical.save(buffer, format="PNG")
        canonical_bytes = buffer.getvalue()
        width, height = canonical.size
    case = CasePaths("case_" + uuid.uuid4().hex[:16], Path(root))
    case.case_dir.mkdir(parents=True, exist_ok=False)
    for folder in ("input", "tasks", "tools", "rounds", "transactions", "final", "quarantine", "snapshot/prompts", "snapshot/schemas"):
        case.path(folder).mkdir(parents=True, exist_ok=True)
    extension = {"PNG": "png", "JPEG": "jpg", "TIFF": "tiff", "WEBP": "webp", "BMP": "bmp"}[original_format]
    original_path = f"input/original.{extension}"
    atomic_write(case.path(original_path), raw)
    atomic_write(case.path("input/canonical.png"), canonical_bytes)
    write_json(case.path("input/metadata.json"), {"original_path": original_path, "original_sha256": sha256_bytes(raw), "canonical_sha256": sha256_bytes(canonical_bytes), "canonicalizer_version": CANONICALIZER_VERSION, "canonical_storage": "metadata-free sRGB RGB8 PNG", "width": width, "height": height, "operations": operations, "source_format": original_format, "colour_assumption": "sRGB" if not icc else "converted embedded ICC", "display_domain": "RGB8"})
    snapshot_hashes = {"input/metadata.json": sha256_file(case.path("input/metadata.json"))}
    for folder, glob in (("prompts", "*.j2"), ("schemas", "*.json")):
        for path in (DESIGN_DIR / folder).glob(glob):
            relative = f"snapshot/{folder}/{path.name}"
            if profile_id in ("gpu_yoloe26l_v1", "gpu_sam31_v5") and folder == "schemas" and path.name == "evidence_local.schema.json":
                write_json(case.path(relative), schema_validator(path.name).schema)
            else:
                atomic_write(case.path(relative), path.read_bytes())
            snapshot_hashes[relative] = sha256_file(case.path(relative))
    checklist = read_json(DESIGN_DIR / "config/checklist.json")
    defaults.update({"intent": intent, "snapshot_hashes": snapshot_hashes, "checklist": checklist, "parent_case_id": config.get("parent_case_id"), "branch_type": "manual_variant" if defaults["executor"] == "gemini_api_image" else config.get("branch_type", "main")})
    write_json(case.path("case_config.json"), defaults)
    stamp = now()
    state = State(case_id=case.case_id, input_sha256=sha256_bytes(canonical_bytes), config_sha256=sha256_file(case.path("case_config.json")), budget=Budget(max_generations=defaults["max_generations"]), next_action=NextAction(code="initialize", message="准备诊断任务"), created_at=stamp, updated_at=stamp, deviated=defaults["branch_type"] != "main" or profile_id in ("gpu_yoloe26l_v1", "gpu_sam31_v5"))
    return commit(case, state, "case_created", {"original_sha256": sha256_bytes(raw), "canonical_sha256": state.input_sha256, "parent_case_id": defaults["parent_case_id"], "branch_type": defaults["branch_type"]})
