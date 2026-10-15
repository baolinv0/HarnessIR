import json
import math
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

BASE_DESIGN_DIR = Path(__file__).resolve().parents[3] / "Design_v1_20261012"
DESIGN_DIR = Path(__file__).resolve().parents[3] / "Design_v1_1_20261012"
SCHEMA_DIR = DESIGN_DIR / "schemas"
ROLE_SCHEMAS = {"diagnose": "diagnosis.schema.json", "compose": "composition.schema.json", "refine": "composition.schema.json", "execute": "execution.schema.json", "verify": "verification.schema.json"}


def strict_loads(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        match = re.fullmatch(r"```(?:json)?\s*\n([\s\S]*)\n```", raw)
        if not match:
            raise ValueError("Only a single complete JSON fence is accepted")
        raw = match.group(1)
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    def constant(value):
        raise ValueError(f"Non-finite JSON number: {value}")
    def finite(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("Non-finite JSON number")
        return result
    data = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant, parse_float=finite)
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    return data


@lru_cache(maxsize=512)
def schema_validator(name: str, directory: Path = SCHEMA_DIR):
    if not re.fullmatch(r"[a-z_]+\.schema\.json", name):
        raise ValueError("Unknown local schema")
    resources = []
    schemas = {}
    for path in directory.glob("*.schema.json"):
        data = strict_loads(path.read_text(encoding="utf-8"))
        if directory.resolve() == SCHEMA_DIR.resolve() and path.name == "evidence_local.schema.json":
            # Engine-owned increment: preserve the delivered design and all
            # historical case snapshots. Only the authorized alternative is
            # added, and it cannot claim original SAM3 protocol eligibility.
            data["properties"]["evidence_profile_id"]["enum"].extend(["gpu_yoloe26l_v1", "gpu_sam31_v5"])
            data.setdefault("allOf", []).append({"if": {"properties": {"evidence_profile_id": {"enum": ["gpu_yoloe26l_v1", "gpu_sam31_v5"]}}, "required": ["evidence_profile_id"]}, "then": {"properties": {"formal_eligible": {"const": False}}}})
        schemas[path.name] = data
        resources.append((data["$id"], Resource.from_contents(data)))
    checker = FormatChecker()
    if "date-time" not in checker.checkers or checker.conforms("not-a-date", "date-time"):
        raise RuntimeError("date-time validator unavailable; install rfc3339-validator")
    if name not in schemas:
        raise ValueError("Unknown local schema")
    return Draft202012Validator(schemas[name], registry=Registry().with_resources(resources), format_checker=checker)


def validate_schema(name: str, data: dict, directory: Path = SCHEMA_DIR):
    errors = sorted(schema_validator(name, directory).iter_errors(data), key=lambda e: str(list(e.path)))
    if errors:
        error = errors[0]
        raise ValueError(f"{name} {list(error.path)}: {error.message}")


def check_bboxes(data: dict):
    for key in ("detections", "defects"):
        for item in data.get(key, []):
            x0, y0, x1, y1 = item["bbox_norm"]
            if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
                raise ValueError("bbox_norm must have increasing canonical coordinates")


def validate_payload(role: str, payload: dict, directory: Path = SCHEMA_DIR):
    validate_schema(ROLE_SCHEMAS[role], payload, directory)
    check_bboxes(payload)


def parse_time(value: str):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Timestamp requires timezone")
    return stamp


def validate_response(request, response, case):
    from .storage import sha256_file
    validate_schema("response.schema.json", response.model_dump(), case.path("snapshot/schemas"))
    for key in ("protocol_version", "task_id", "case_id", "role", "round", "expected_state_revision", "input_sha256"):
        if getattr(request, key) != getattr(response, key):
            raise ValueError(f"Response identity mismatch: {key}")
    if request.attempt_index != request.round - 1 or ROLE_SCHEMAS[request.role] != request.payload_schema:
        raise ValueError("Invalid attempt/schema mapping")
    if sha256_file(case.path("input/canonical.png")) != request.input_sha256:
        raise ValueError("Canonical changed")
    for asset in request.allowed_assets:
        validate_asset(case, asset.model_dump())
    provenance = response.provenance
    if parse_time(provenance["completed_at"]) < parse_time(provenance["started_at"]):
        raise ValueError("Provenance times out of order")
    if provenance["model_version_source"] == "not_exposed" and provenance["model_version"] is not None:
        raise ValueError("Unexposed backend version must be null")
    if response.status == "ok":
        validate_payload(response.role, response.payload, case.path("snapshot/schemas"))


def validate_asset(case, asset: dict):
    from PIL import Image
    from .storage import sha256_file
    validate_schema("asset.schema.json", asset, case.path("snapshot/schemas"))
    path = case.path(asset["path"])
    if path.suffix in (".tmp", ".part") or sha256_file(path) != asset["sha256"]:
        raise ValueError("Asset hash mismatch or incomplete file")
    if asset["kind"] in ("photo", "map", "overlay"):
        with Image.open(path) as im:
            im.load()
            if im.size != (asset["width"], asset["height"]):
                raise ValueError("Declared image dimensions mismatch")
    elif asset["width"] is not None or asset["height"] is not None:
        raise ValueError("Non-image dimensions must be null")
