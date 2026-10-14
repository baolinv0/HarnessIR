"""Actual pixel geometry gate. Content preservation requires later VLM review."""
from copy import deepcopy
from pathlib import Path
from PIL import Image
from .assets import validate_asset
from .models import canonical_json, file_sha256, sha256_bytes
from .paths import safe_path
from .storage import atomic_write, write_json


def check_geometry(prediction: dict, candidate: dict, policy: dict, *, case_root: Path) -> dict:
    case_root = Path(case_root)
    asset = candidate.get("asset", candidate)
    validate_asset(prediction, case_root)
    validate_asset(asset, case_root)
    width, height = prediction["width"], prediction["height"]
    mode = policy.get("mode", "strict")
    error_limit = policy.get("max_aspect_ratio_error", 0 if mode == "strict" else .005)
    if mode not in {"strict", "aspect_preserving_resize"} or not 0 <= error_limit <= .005:
        raise ValueError("invalid frozen geometry policy")
    if mode == "strict" and error_limit != 0:
        raise ValueError("strict geometry forbids aspect error")
    if policy.get("target_width", width) != width or policy.get("target_height", height) != height:
        raise ValueError("geometry target differs from frozen prediction")
    frozen = {"mode": mode, "target_width": width, "target_height": height, "max_aspect_ratio_error": error_limit}
    raw_w, raw_h = asset["width"], asset["height"]
    aspect_error = abs(raw_w * height / (raw_h * width) - 1)
    exact_aspect = raw_w * height == raw_h * width
    exact_size = (raw_w, raw_h) == (width, height)
    status = "pass" if exact_size or (mode == "aspect_preserving_resize" and exact_aspect and aspect_error <= error_limit) else "fail"
    derived = None
    output_dir = safe_path(case_root, "rounds/geometry")
    output_dir.mkdir(parents=True, exist_ok=True)
    identity = sha256_bytes(canonical_json({"asset_sha256": asset["sha256"], "policy": frozen}))
    if status == "pass" and not exact_size:
        destination = output_dir / ("scaled_" + identity + ".png")
        with Image.open(safe_path(case_root, asset["path"], must_exist=True)) as image:
            resized = image.resize((width, height), Image.Resampling.LANCZOS)
            import io
            buffer = io.BytesIO()
            resized.save(buffer, "PNG", icc_profile=image.info.get("icc_profile"))
            pixels = resized.tobytes()
        data = buffer.getvalue()
        if destination.exists() and destination.read_bytes() != data:
            raise ValueError("immutable derived asset collision")
        atomic_write(destination, data)
        derived = deepcopy(asset)
        derived.update(asset_id=asset["asset_id"] + "_scaled_" + identity[:12], path=destination.relative_to(case_root).as_posix(),
                       sha256=sha256_bytes(data), pixel_sha256=sha256_bytes(b"HRE-RGB8-v1\0" + width.to_bytes(4, "big") + height.to_bytes(4, "big") + pixels), width=width, height=height)
        scale_policy = {"mode": "aspect_preserving_resize", "target_width": width, "target_height": height,
                        "interpolation": "LANCZOS", "source_sha256": asset["source_file"]["sha256"],
                        "source_pixel_sha256": asset["pixel_sha256"]}
        derived["canonicalization"].update(canonicalizer_version="hre_rgb8_uniform_scale_v1",
                                            conversion_policy_sha256=sha256_bytes(canonical_json(scale_policy)))
        # Preserve the original generated master and its conversion provenance.
        validate_asset(derived, case_root)
    report = {"status": status, "policy": frozen, "raw_asset_id": asset["asset_id"], "raw_sha256": asset["sha256"],
              "source_file": asset.get("source_file"), "raw_dimensions": [raw_w, raw_h], "exact_aspect": exact_aspect,
              "relative_aspect_error": aspect_error, "selected_asset_id": (derived or asset)["asset_id"],
              "selected_sha256": (derived or asset)["sha256"], "derived_asset": derived,
              "pixel_gate_only": True, "content_preservation": "not_established; later VLM preservation observations required",
              "operations": ["exact_aspect_uniform_scale"] if derived else []}
    report_path = output_dir / ("geometry_" + identity + ".json")
    if report_path.exists() and report_path.read_bytes() != canonical_json(report):
        raise ValueError("immutable geometry report collision")
    write_json(report_path, report)
    return {"status": status, "policy": frozen, "report_path": report_path.relative_to(case_root).as_posix(),
            "report_sha256": file_sha256(report_path), "derived_asset": derived}
