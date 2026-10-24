#!/usr/bin/env python3
"""Build frozen front-camera experiment manifests; never run or edit images.

Requires only Python's standard library. This checks declared metadata and,
optionally, file bytes. It cannot establish that pixels really are SDR sRGB.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys


MODELS = ["qwen21", "firered11", "flux3_klein", "fibo2_dev"]
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
PLACEHOLDER = re.compile(r"REPLACE_[A-Z0-9_]+|PLACEHOLDER|\bTODO\b|\bTBD\b|\bUNKNOWN\b|待填写|待补充|待确认", re.I)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def real_text(value: object, label: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), f"{label}: provide a nonempty string")
    require(not PLACEHOLDER.search(value), f"{label}: replace the template placeholder")
    return value.strip()


def sha256(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def image_path(value: object, label: str, base: Path) -> str:
    text = real_text(value, label)
    path = Path(text).expanduser()
    return str((base / path).resolve() if not path.is_absolute() else path.resolve())


def regions(value: object, label: str) -> list[dict]:
    require(isinstance(value, list), f"{label}: regions must be a list")
    result, seen = [], set()
    for index, region in enumerate(value):
        location = f"{label}[{index}]"
        require(isinstance(region, dict), f"{location}: expected an object")
        require(set(region) <= {"id", "description", "source_box", "reference_box"},
                f"{location}: only id, description, source_box and reference_box are supported")
        rid = real_text(region.get("id"), location + ".id")
        require(re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", rid) and rid not in seen,
                f"{location}: use a unique, runtime-compatible region id")
        seen.add(rid)
        description = real_text(region.get("description"), location + ".description")
        require("source_box" in region, f"{location}: source_box is required")
        item = {"id": rid, "description": description}
        for key in ("source_box", "reference_box"):
            if key not in region:
                continue
            box = region[key]
            require(isinstance(box, list) and len(box) == 4
                    and all(type(x) in {int, float} and math.isfinite(x) and 0 <= x <= 1 for x in box)
                    and box[0] < box[2] and box[1] < box[3],
                    f"{location}.{key}: normalized [xmin, ymin, xmax, ymax] is required")
            item[key] = list(box)
        result.append(item)
    return result


def validate_dataset(dataset: dict, base: Path, check_files: bool) -> tuple[dict, list[dict]]:
    require(isinstance(dataset, dict) and dataset.get("schema_version") == "front_camera_dataset_v1",
            "Expected schema_version=front_camera_dataset_v1")
    meta = dataset.get("meta")
    require(isinstance(meta, dict), "meta must be an object")
    for flag in ("data_count_confirmed", "color_contract_confirmed", "group_contract_confirmed"):
        require(meta.get(flag) is True, f"meta.{flag} must be true after actual confirmation")
    for key in ("source_encoding", "reference_encoding"):
        require(meta.get(key) == "srgb_sdr_8bit", f"meta.{key} must be srgb_sdr_8bit")
    for key in ("baseline_id", "baseline_revision", "source_export_recipe", "reference_export_recipe",
                "brief_reference", "brief_source_only"):
        real_text(meta.get(key), "meta." + key)
    # The A-only arm must not contain instructions derived from the appearance reference.
    require(not re.search(r"\biPhone\b|\breference\b|参考图|参考照片", meta["brief_source_only"], re.I),
            "brief_source_only must describe source-only goals without iPhone/reference instructions")
    cases = dataset.get("cases")
    require(isinstance(cases, list) and cases, "Supply at least one paired case")
    require(type(meta.get("paired_count")) is int and meta["paired_count"] == len(cases),
            "meta.paired_count must equal the actual number of paired cases")
    normalized, files = [], []
    ids, paths, group_splits = set(), set(), {}
    for index, case in enumerate(cases):
        location = f"cases[{index}]"
        require(isinstance(case, dict), f"{location}: expected an object")
        pair = real_text(case.get("pair_id"), location + ".pair_id")
        require(ID.fullmatch(pair) and pair not in ids, f"{location}: pair_id must be unique and safe")
        ids.add(pair)
        split = case.get("split")
        require(split in {"dev", "test"}, f"{pair}: split must be dev or test")
        group = real_text(case.get("group_id"), pair + ".group_id")
        require(group_splits.get(group, split) == split,
                f"{pair}: scene/capture-session/burst group {group!r} crosses dev/test")
        group_splits[group] = split
        item = {"pair_id": pair, "split": split, "group_id": group,
                "regions": regions(case.get("regions", []), pair + ".regions")}
        if case.get("subject_id"):
            item["subject_id"] = ("unknown" if case["subject_id"] == "unknown" else
                                  real_text(case["subject_id"], pair + ".subject_id"))
        for role in ("source", "reference"):
            path = image_path(case.get(role), pair + "." + role, base)
            require(path not in paths, f"{pair}: repeated source/reference path: {path}")
            paths.add(path)
            item[role] = path
            record = {"pair_id": pair, "role": role, "path": path, "status": "unchecked"}
            if check_files:
                require(Path(path).is_file(), f"{pair}: missing {role} file: {path}")
                record.update(status="bytes_checked", sha256=sha256(Path(path)), size_bytes=Path(path).stat().st_size)
            files.append(record)
        normalized.append(item)
    require(any(item["split"] == "test" for item in normalized), "At least one test case is required")
    return {"schema_version": dataset["schema_version"], "meta": deepcopy(meta), "cases": normalized}, files


def arm(name: str, strategy: str, policy: str = "single") -> dict:
    multiple = policy != "single"
    return {"name": name, "strategy": strategy, "policy": policy,
            "max_generations": 3 if multiple else 1,
            "max_stage_calls": 9 if multiple else 5,
            "max_compiler_calls": 3 if policy == "feedback" else 1}


def case_spec(case: dict, meta: dict, *, reference: bool) -> dict:
    brief = meta["brief_reference" if reference else "brief_source_only"]
    result = {"id": case["pair_id"],
              "task_mode": "reference_enhance" if reference else "restoration",
              "source": {"path": case["source"]}, "brief": brief,
              "geometry": {"policy": "pad", "grid": 32},
              "spatial": {"mode": "full_frame"}, "alpha_policy": "require_opaque",
              "colour_policy": "assume_srgb", "regions": deepcopy(case["regions"]),
              "evaluation": {
                  "task_goal": brief, "preserve_identity_text_geometry": True,
                  "reference_content_transfer_allowed": False,
                  "protected_content": ["source identity", "source expression and gaze", "eye and tooth geometry",
                                        "hair and clothing structure", "readable source text", "source viewpoint and composition"],
                  "forbidden_changes": ["face reshaping", "invented pores or lettering", "unrequested beauty retouching",
                                        "replacement of source people or objects"],
              }}
    if reference:
        result["reference"] = {"path": case["reference"]}
    else:
        for region in result["regions"]:
            region.pop("reference_box", None)
    return result


def batch(cases: list[dict], meta: dict, arms: list[dict], seeds: list[int], *, reference: bool) -> dict:
    return {"schema_version": "hre_batch_v3", "models": MODELS, "arms": arms,
            "seeds": seeds, "share_planning": True,
            "cases": [case_spec(case, meta, reference=reference) for case in cases]}


def budget(manifest: dict) -> dict:
    repetitions = len(manifest["cases"]) * len(MODELS) * len(manifest["seeds"])
    arms = manifest["arms"]
    return {"paired_cases": len(manifest["cases"]), "seed_starts": manifest["seeds"],
            "planned_case_runs": repetitions * len(arms),
            "max_image_generations": repetitions * sum(row["max_generations"] for row in arms),
            "max_case_stage_calls": repetitions * sum(row["max_stage_calls"] for row in arms),
            "max_compiler_calls": repetitions * sum(row["max_compiler_calls"] for row in arms),
            "additional_shared_planning_cases": len(manifest["cases"])}


def build(dataset_path: Path, out: Path, seeds: list[int], include_feedback: bool, check_files: bool) -> dict:
    require(not out.exists(), "Output path already exists; choose a new directory to preserve the frozen plan")
    require(seeds and all(type(seed) is int and 0 <= seed < 2**63 - 100 for seed in seeds),
            "Seeds must be nonnegative integers below 2**63 - 100")
    ordered = sorted(seeds)
    require(all(right - left >= 3 for left, right in zip(ordered, ordered[1:])),
            "Seed starts must be unique and at least 3 apart, e.g. 42 1042 2042")
    original_bytes = dataset_path.read_bytes()
    original = json.loads(original_bytes)
    dataset, files = validate_dataset(original, dataset_path.parent, check_files)
    meta, cases = dataset["meta"], dataset["cases"]
    dev = [case for case in cases if case["split"] == "dev"]
    test = [case for case in cases if case["split"] == "test"]
    main_arms = [arm("native_single", "native"), arm("shared_single", "shared"), arm("aware_single", "model_aware")]
    if include_feedback:
        main_arms.extend([arm("aware_resample3", "model_aware", "resample"),
                          arm("aware_feedback3", "model_aware", "feedback")])
    manifests = {
        "main_reference.json": batch(test, meta, main_arms, seeds, reference=True),
        "source_only.json": batch(test, meta, [arm("aware_single", "model_aware")], seeds, reference=False),
    }
    if dev:
        manifests = {"pilot.json": batch(dev, meta, [arm("aware_single", "model_aware")], [42], reference=True), **manifests}
    warnings = [
        "Declared SDR sRGB metadata is not pixel-level colour validation. Do not pass linear/RAW/HDR images.",
        "Source-only region descriptions and brief must be written from A alone; their semantics cannot be proved by this tool.",
        "No time/GPU-hour estimate is inferred from image counts; measure actual calls and elapsed time on the server.",
        "Shared planning is scoped to each batch. The source-only batch deliberately plans without B.",
        "Feedback/resample arms share an initial intent, not a guaranteed identical compiled condition; compare recorded condition hashes.",
        "Feedback may stop early; counts are maximum generation budgets, not equal actual compute.",
    ]
    if not check_files:
        warnings.append("Input files are unchecked. Rebuild with --check-files on the server before running.")
    if not dev:
        warnings.append("No dev/pilot pairs: pilot.json is omitted. Use an external deployment pilot or freeze all test settings beforehand.")
    details = {name: budget(manifest) for name, manifest in manifests.items()}
    planned = {"schema_version": "front_camera_planned_budget_v1", "status": "planned_not_executed",
               "dev_pairs": len(dev), "test_pairs": len(test), "pilot_missing": not bool(dev),
               "file_checks": "bytes_checked" if check_files else "unchecked", "include_feedback": include_feedback,
               "batches": details,
               "total_planned_case_runs": sum(value["planned_case_runs"] for value in details.values()),
               "total_max_image_generations": sum(value["max_image_generations"] for value in details.values()),
               "gpu_hours": None, "warnings": warnings}
    lock = {"schema_version": "front_camera_dataset_lock_v1", "created_at": datetime.now(timezone.utc).isoformat(),
            "dataset_path": str(dataset_path), "dataset_sha256": hashlib.sha256(original_bytes).hexdigest(),
            "generator_sha256": sha256(Path(__file__).resolve()), "dataset_original": original,
            "dataset_normalized": dataset, "input_files": files, "warnings": warnings}
    output = {**manifests, "dataset.lock.json": lock, "planned_budget.json": planned}
    serialized = {name: json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n" for name, value in output.items()}
    out.mkdir(parents=True, exist_ok=False)
    for name, content in serialized.items():
        (out / name).write_text(content, encoding="utf-8")
    return planned


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True, help="Completed dataset JSON; relative images resolve beside it")
    parser.add_argument("--out", type=Path, required=True, help="New output directory; existing directories are never overwritten")
    parser.add_argument("--seeds", type=int, nargs="+", default=[42], help="Nonoverlapping seed starts, e.g. 42 1042 2042")
    parser.add_argument("--include-feedback", action="store_true", help="Add capped resample and feedback arms to the SAME main batch")
    parser.add_argument("--check-files", action="store_true", help="Verify input files exist and record their SHA-256; does not validate colour")
    args = parser.parse_args()
    try:
        result = build(args.dataset.expanduser().resolve(), args.out.expanduser().resolve(),
                       args.seeds, args.include_feedback, args.check_files)
    except (ValueError, OSError) as exc:
        print(f"Manifest preparation failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
