"""Blind offline review, scored results and manual promotion for texture search."""
from __future__ import annotations

from collections import Counter
import io
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps

from ..models import file_sha256, sha256_bytes
from ..storage import atomic_write, case_lock, read_json, write_json
from ..v3.common import digest, require
from ..v3.runner_journal import immutable_json
from .study import (
    asset_path, case_path, case_state, check_id, fields, gate_split, incumbents, load_study, version,
)
from .texture import assess, measure


def _copy(path: Path, expected_hash: str, target: Path) -> None:
    data = path.read_bytes()
    require(sha256_bytes(data) == expected_hash, "study_asset_changed", "An output no longer matches its receipt")
    atomic_write(target, data)


def _reference_png(source: Path, target: Path) -> None:
    with Image.open(source) as image:
        buffer = io.BytesIO()
        ImageOps.exif_transpose(image).convert("RGB").save(buffer, format="PNG")
    atomic_write(target, buffer.getvalue())


def _collect(root: Path, study: dict, split: str, profile: str, versions: list[str]) -> list[dict]:
    rows = []
    for name in versions:
        gate_split(root, study, split, name, profile)
        version_hash = version(root, study, name)["version_sha256"]
        for sample in study["samples"]:
            if sample["split"] != split:
                continue
            path = case_path(root, split, profile, name, sample)
            require((path / "freeze.json").is_file(), "review_run_missing", f"Finish {name} on {sample['id']} first")
            _, record = case_state(path)
            require(record["status"] in {"completed", "failed"}, "review_run_pending",
                    f"Resolve {name} on {sample['id']} before review")
            require(record["inputs"][0]["original_sha256"] == sample["source"]["sha256"],
                    "review_source_mismatch", "Run did not consume the frozen source")
            budget = record.get("budget", {})
            rows.append({"sample": sample["id"], "version": name, "version_sha256": version_hash,
                         "source": record["inputs"][0], "state_sha256": digest(record), "budget": budget,
                         "status": record["status"], "terminal_reason": record.get("terminal_reason"),
                         "selected": record.get("selected_candidate_id"),
                         "selected_kind": record.get("selected_kind"),
                         "outputs": record.get("candidates", []),
                         "over_budget": budget.get("generations", 0) > len(study["seeds"])})
    return rows


def make_review(root: Path, split: str, profile: str, candidates: list[str], out: Path) -> dict:
    root, out = root.resolve(), out.resolve()
    require(not out.is_relative_to(root) and not root.is_relative_to(out),
            "review_path_invalid", "Put exports outside the private study directory")
    require(candidates and len(candidates) == len(set(candidates)), "review_versions_invalid", "Supply distinct versions")
    with case_lock(root):
        study = load_study(root)
        runs = _collect(root, study, split, profile, sorted(candidates))
        with case_lock(out.parent / ".hre-search-export"):
            require(not out.exists() or not any(out.iterdir()), "review_path_exists", "Use a new export directory")
            packet_id = uuid4().hex
            samples = {row["id"]: row for row in study["samples"] if row["split"] == split}
            alias_by_sample = {sid: uuid4().hex[:16] for sid in samples}
            entries = {}
            public = {}
            for run in runs:
                sid, src = run["sample"], run["source"]
                sample = samples[sid]
                sample_alias = alias_by_sample[sid]
                source_path = f"images/{sample_alias}/source.png"
                if sample_alias not in public:
                    _copy(Path(src["path"]), src["sha256"], out / source_path)
                    public[sample_alias] = {"source": source_path, "source_sha256": src["sha256"],
                                            "task": sample["brief"], "regions": sample["regions"], "outputs": {}}
                    if "gt" in sample:
                        gt_path = f"images/{sample_alias}/reference.png"
                        _reference_png(asset_path(root, sample["gt"]), out / gt_path)
                        public[sample_alias]["offline_reference"] = gt_path
                        public[sample_alias]["offline_reference_sha256"] = file_sha256(out / gt_path)
                for candidate in run["outputs"]:
                    alias = uuid4().hex[:16]
                    image = f"images/{sample_alias}/{alias}.png"
                    output = candidate["delivered"]
                    _copy(Path(output["path"]), output["sha256"], out / image)
                    entries[alias] = {"sample_alias": sample_alias, "sample": sid, "version": run["version"],
                                      "candidate": candidate["candidate_id"], "native": candidate["native"],
                                      "geometry_valid": candidate["geometry_valid"], "image": image,
                                      "sha256": output["sha256"]}
                    public[sample_alias]["outputs"][alias] = {"image": image, "sha256": output["sha256"]}
            packet = {"packet": packet_id, "cases": public}
            packet_hash = digest(packet)
            write_json(out / "review.json", packet)
            write_json(out / "ratings.template.json", {
                "packet": packet_id, "review_sha256": packet_hash, "reviewer": "",
                "ratings": {alias: {"preservation": "", "texture": "", "artifact": "", "evidence": ""}
                            for alias in sorted(entries)},
            })
            immutable_json(root / "reviews" / packet_id / "binding.json", {
                "packet": packet_id, "review_sha256": packet_hash, "split": split, "profile": profile,
                "study_sha256": study["study_sha256"], "entries": entries, "runs": runs, "public": packet,
                "export": str(out),
            })
            return {"packet": packet_id, "directory": str(out), "images": len(entries)}


def _read_binding(root: Path, study: dict, packet_id: str) -> dict:
    binding = read_json(root / "reviews" / check_id(packet_id) / "binding.json")
    require(binding["packet"] == packet_id and binding["study_sha256"] == study["study_sha256"]
            and digest(binding["public"]) == binding["review_sha256"], "review_binding_mismatch", "Review binding changed")
    return binding


def _validate_grade(grade: dict, has_gt: bool) -> None:
    fields(grade, {"preservation", "texture", "artifact", "evidence"}, "rating")
    require(grade.get("preservation") in {"verified", "no_visible_conflict", "conflict", "unverifiable"}
            and grade.get("texture") in {"improved", "unchanged", "worse", "uncertain"}
            and grade.get("artifact") in {"none", "minor", "major", "uncertain"}
            and isinstance(grade.get("evidence"), str) and bool(grade["evidence"].strip()),
            "review_grade_invalid", "Each rating needs a verdict and a concrete evidence note")
    require(has_gt or grade["preservation"] != "verified", "review_unverified_detail",
            "Use no_visible_conflict or unverifiable when there is no offline reference")


def _summarize(runs: list[dict], results: dict, binding: dict) -> dict:
    by_run = {}
    for alias, row in binding["entries"].items():
        by_run.setdefault((row["version"], row["sample"]), {})[row["candidate"]] = alias
    versions = {}
    for run in runs:
        aliases = by_run.get((run["version"], run["sample"]), {})
        selected_alias = aliases.get(run["selected"])
        selected = results.get(selected_alias, {})
        valid_run = run["status"] == "completed" and not run["over_budget"]
        improved = bool(valid_run and run["selected_kind"] == "candidate_accepted" and selected.get("eligible"))
        retained = run["selected_kind"] == "source_baseline" or selected.get("measurements", {}).get("unchanged")
        delivered = binding["entries"][selected_alias]["image"] if improved else None
        row = {"sample": run["sample"], "produced": bool(aliases), "severe": bool(selected.get("severe")),
               "oracle_pass": valid_run and any(results[alias]["eligible"] for alias in aliases.values()),
               "improved": improved, "selected_alias": selected_alias, "delivered": delivered,
               "delivery": "accepted" if improved else "source_retained" if retained else "unresolved", "budget": run["budget"], "runtime_status": run["status"],
               "terminal_reason": run["terminal_reason"], "over_budget": run["over_budget"]}
        versions.setdefault(run["version"], []).append(row)
    report = {}
    for name, rows in versions.items():
        counts = Counter()
        for row in rows:
            counts.update(row["budget"])
        count = len(rows)
        eligible_pool = sum(row["oracle_pass"] for row in rows)
        success = sum(row["improved"] for row in rows)
        report[name] = {
            "total": count, "produced_rate": sum(row["produced"] for row in rows) / count,
            "eligible_pool_rate": eligible_pool / count, "selected_improved_rate": success / count,
            "conditional_selection_success": success / eligible_pool if eligible_pool else None,
            "severe_rate": sum(row["severe"] for row in rows) / count,
            "source_retained_rate": sum(row["delivery"] == "source_retained" for row in rows) / count,
            "unresolved_rate": sum(row["delivery"] == "unresolved" for row in rows) / count,
            "budget": dict(counts), "cases": rows,
        }
    return report


def score(root: Path, ratings: dict) -> dict:
    root = root.resolve()
    fields(ratings, {"packet", "review_sha256", "reviewer", "ratings"}, "ratings")
    with case_lock(root):
        study = load_study(root)
        binding = _read_binding(root, study, ratings["packet"])
        require(isinstance(ratings.get("reviewer"), str) and bool(ratings["reviewer"].strip())
                and ratings.get("review_sha256") == binding["review_sha256"],
                "review_binding_mismatch", "Ratings need a reviewer and the original review hash")
        require(isinstance(ratings.get("ratings"), dict) and set(ratings["ratings"]) == set(binding["entries"]),
                "review_incomplete", "Rate every output in the frozen packet exactly once")
        out = Path(binding["export"])
        require(out.is_dir() and read_json(out / "review.json") == binding["public"],
                "review_binding_mismatch", "The exported review manifest changed")
        samples = {row["id"]: row for row in study["samples"]}
        for row in binding["public"]["cases"].values():
            asset_path(out, {"path": row["source"], "sha256": row["source_sha256"]})
            if "offline_reference" in row:
                asset_path(out, {"path": row["offline_reference"], "sha256": row["offline_reference_sha256"]})
        rows = {}
        seen_verdicts = {}
        for alias, row in binding["entries"].items():
            sample = samples[row["sample"]]
            public_case = binding["public"]["cases"][row["sample_alias"]]
            lq = out / public_case["source"]
            output = asset_path(out, {"path": row["image"], "sha256": row["sha256"]})
            grade = ratings["ratings"][alias]
            _validate_grade(grade, "gt" in sample)
            key = (row["sample"], row["sha256"])
            verdict = {name: grade[name] for name in ("preservation", "texture", "artifact")}
            require(seen_verdicts.setdefault(key, verdict) == verdict, "review_duplicate_disagreement",
                    "Identical images for the same sample require the same judgments")
            measurements = measure(lq, output, sample["regions"], study["thresholds"])
            if not row["geometry_valid"]:
                measurements["violations"].append({"region": "full_frame", "check": "native_geometry"})
            rows[alias] = {**assess(measurements, grade, sample["requires_verified_content"]),
                           "measurements": measurements}
        report = {"packet": binding["packet"], "split": binding["split"], "profile": binding["profile"],
                  "study_sha256": study["study_sha256"], "reviewer": ratings["reviewer"],
                  "ratings_sha256": digest(ratings), "results": rows,
                  "versions": _summarize(binding["runs"], rows, binding)}
        return immutable_json(root / "reviews" / binding["packet"] / "score.json",
                              {**report, "score_sha256": digest(report)})


def _read_score(root: Path, binding: dict) -> dict:
    report = read_json(root / "reviews" / binding["packet"] / "score.json")
    require(report["packet"] == binding["packet"] and report["study_sha256"] == binding["study_sha256"]
            and report["score_sha256"] == digest({k: v for k, v in report.items() if k != "score_sha256"}),
            "review_score_changed", "Independent score no longer matches its receipt")
    return report


def promote(root: Path, profile: str, candidate: str, packet_id: str, reason: str) -> dict:
    root = root.resolve()
    require(isinstance(reason, str) and bool(reason.strip()), "search_reason_required", "Record the promotion rationale")
    with case_lock(root):
        study = load_study(root)
        binding = _read_binding(root, study, packet_id)
        report = _read_score(root, binding)
        require(not (root / "final.json").exists(), "search_frozen", "Final evaluation is frozen")
        require(binding["split"] == report["split"] == "selection" and binding["profile"] == report["profile"] == profile
                and report["packet"] == packet_id and report["study_sha256"] == study["study_sha256"],
                "promotion_requires_selection", "Use the frozen independent selection review for this profile")
        active = incumbents(root, study)
        current = active[profile]
        proposed = version(root, study, candidate)
        require(proposed["parent"] == current and current != candidate,
                "promotion_parent_mismatch", "Challenge the currently active version for this profile")
        require(proposed["policies"][profile] != version(root, study, current)["policies"][profile],
                "promotion_no_policy_change", "The challenger must change the policy for this profile")
        versions = report["versions"]
        require({candidate, current} <= set(versions), "promotion_comparison_missing", "Blind review must contain both versions")
        old, new = versions[current], versions[candidate]
        gain = new["selected_improved_rate"] - old["selected_improved_rate"]
        require(not any(row["over_budget"] for row in new["cases"] + old["cases"]),
                "promotion_budget_exceeded", "The compared runs breached the frozen generation budget")
        require(gain > 0 and gain + 1e-12 >= study["minimum_gain"] and new["severe_rate"] <= old["severe_rate"],
                "promotion_criteria_failed", "The challenger must improve the qualified rate without increasing serious violations")
        path = root / "incumbents.json"
        previous = read_json(path) if path.exists() else {}
        receipt = {"profile": profile, "from": current, "to": candidate, "packet": packet_id, "reason": reason,
                   "score_sha256": file_sha256(root / "reviews" / packet_id / "score.json"),
                   "version_sha256": proposed["version_sha256"], "improvement": gain}
        write_json(path, {"active": {**active, profile: candidate}, "history": [*previous.get("history", []), receipt]})
        # Keep feedback returned to the proposer free of selection metrics.
        return {key: receipt[key] for key in ("profile", "from", "to", "reason")}


def export_feedback(root: Path, packet_id: str, out: Path) -> dict:
    root, out = root.resolve(), out.resolve()
    require(not out.is_relative_to(root) and not root.is_relative_to(out),
            "review_path_invalid", "Put exports outside the private study directory")
    with case_lock(root):
        study = load_study(root)
        binding = _read_binding(root, study, packet_id)
        require(binding["split"] == "dev", "feedback_dev_only", "Proposer feedback is restricted to development runs")
        report = _read_score(root, binding)
        with case_lock(out.parent / ".hre-search-export"):
            require(not out.exists() or not any(out.iterdir()), "review_path_exists", "Use a new export directory")
            before = Path(binding["export"])
            for sample in binding["public"]["cases"].values():
                _copy(before / sample["source"], sample["source_sha256"], out / sample["source"])
            traces = {}
            for run in binding["runs"]:
                sample_dir = root / "runs" / "dev" / binding["profile"] / run["version"] / run["sample"]
                _, state = case_state(sample_dir)
                conditions = []
                for round_row in state.get("rounds", []):
                    condition = round_row.get("condition")
                    if condition:
                        resolved = asset_path(sample_dir, condition)
                        conditions.append({"round": round_row["round"], "text": read_json(resolved)["text"]})
                traces.setdefault(run["version"], {})[run["sample"]] = {
                    "conditions": conditions, "intent": state.get("intent"), "budget": run["budget"],
                    "terminal_reason": run["terminal_reason"],
                }
            localized = {}
            for alias, row in binding["entries"].items():
                native = row["native"]
                native_path = f"native/{alias}.png"
                _copy(before / row["image"], row["sha256"], out / row["image"])
                _copy(Path(native["path"]), native["sha256"], out / native_path)
                localized[alias] = {k: v for k, v in row.items() if k != "native"} | {"native": native_path}
            write_json(out / "feedback.json", {
                "packet": packet_id, "profile": binding["profile"],
                "cases": {alias: {key: value for key, value in row.items() if not key.startswith("offline_reference")}
                          for alias, row in binding["public"]["cases"].items()},
                "versions": {name: version(root, study, name) for name in report["versions"]},
                "assessment": report, "images": localized, "traces": traces,
                "proposal_template": {"id": "", "parent": "", "hypothesis": "", "policy": {},
                                      "model_overrides": {}},
            })
        return {"directory": str(out), "packet": packet_id}
