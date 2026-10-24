"""Offline deployment inventories and no-inference preflight checks."""
from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from ..models import file_sha256, now
from ..storage import atomic_write, read_json, write_json
from .common import model_identity, package_versions, require
from .contracts import CATALOG, validate_config


def lock_checkpoint(path: Path, model_id: str, revision: str, output: Path) -> dict:
    path, output = Path(path).expanduser().resolve(), Path(output).resolve()
    require(path.is_dir(), "local_weights_missing", "Checkpoint directory does not exist")
    require(re.fullmatch(r"[0-9a-fA-F]{40}", revision), "revision_required", "Supply the actual checkpoint commit")
    require(model_id in {row["model_id"] for row in CATALOG.values()} | {
        "Qwen/Qwen-Image-2.1-PE-I2I", "black-forest-labs/flux-3-image-klein-pup"},
        "model_identity_mismatch", "Unknown four-model or native compiler checkpoint")
    require(not output.exists(), "manifest_exists", "Deployment manifests are immutable; choose a new output path")
    records = []
    for component in sorted(path.rglob("*")):
        if not component.is_file() or component.resolve() == output or any(part in {".git", ".cache"} for part in component.relative_to(path).parts):
            continue
        before = component.stat()
        digest = file_sha256(component)
        after = component.stat()
        require((before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns),
                "checkpoint_changed", "A checkpoint file changed during inventory")
        records.append({"path": component.relative_to(path).as_posix(), "size": after.st_size,
                        "mtime_ns": after.st_mtime_ns, "sha256": digest})
    require(records, "local_weights_missing", "Checkpoint has no files")
    manifest = {"schema_version": "hre_deployment_v3", "model_id": model_id, "revision": revision.lower(),
                "local_path": str(path), "files": records, "created_at": now(),
                "upstream_authenticity": "operator_declared_revision_local_bytes_frozen"}
    write_json(output, manifest)
    return {"path": str(output), "sha256": file_sha256(output), "files": len(records),
            "bytes": sum(record["size"] for record in records), "identity": model_id,
            "note": "Local bytes are frozen; this inventory does not independently authenticate their upstream origin."}


def _endpoint(config: dict):
    parsed = urlsplit(config.get("base_url", ""))
    require(parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password,
            "endpoint_required", "Set an explicit local/intranet base_url")
    require(isinstance(config.get("model"), str) and config["model"], "endpoint_required", "Set the deployed model name")


def probe_runtime(profile_id: str, kind: str, config: dict) -> dict:
    """Inspect files/packages only. Never construct a model or send a VLM call."""
    result = {"profile_id": profile_id, "kind": kind, "checks": [], "issues": [], "warnings": [],
              "packages": package_versions(), "inference_calls": 0}
    def check(name, fn):
        try:
            detail = fn()
            result["checks"].append({"name": name, "ok": True, "detail": detail})
        except Exception as exc:
            result["issues"].append({"name": name, "code": getattr(exc, "code", type(exc).__name__), "message": str(exc)})

    backend = config.get("backend")
    needs_diffusers = kind == "editor" or backend in {"flux3_pup_local", "flux3_external_vlm_local"}
    required_packages = (["torch", "diffusers", "transformers"] if kind == "editor" else
                         ["torch", "transformers"] if backend in {"qwen_pe_i2i", "flux3_pup_local"} else [])
    if needs_diffusers and "diffusers" not in required_packages:
        required_packages.append("diffusers")
    for package in required_packages:
        def available(package=package):
            require(result["packages"].get(package) is not None, "dependency_missing", f"Install {package} in this worker environment")
            return result["packages"][package]
        check(package, available)
    if kind == "editor":
        check("checkpoint", lambda: model_identity(config, CATALOG[profile_id]["model_id"]))
        def pipeline_version():
            require(config.get("pipeline_version") and config["pipeline_version"] == result["packages"].get("diffusers"),
                    "pipeline_version_mismatch", "Set pipeline_version to the explicitly deployed Diffusers version")
            return config["pipeline_version"]
        check("pipeline_version", pipeline_version)
        index = Path(config.get("local_path", "")) / "model_index.json"
        if profile_id in {"qwen21", "firered11", "fibo2_dev"}:
            def pipeline_identity():
                data = read_json(index)
                require(data.get("_class_name") == CATALOG[profile_id]["pipeline"], "pipeline_class_mismatch",
                        "Local model_index.json belongs to another pipeline class")
                return data["_class_name"]
            check("pipeline_class", pipeline_identity)
    elif backend in {"qwen_pe_i2i", "flux3_pup_local"}:
        expected = "Qwen/Qwen-Image-2.1-PE-I2I" if backend == "qwen_pe_i2i" else "black-forest-labs/flux-3-image-klein-pup"
        check("checkpoint", lambda: model_identity(config, expected))
    if config.get("local_path") and not config.get("deployment_manifest"):
        result["warnings"].append("Checkpoint revision is operator-declared; use models lock to freeze local component hashes.")
    if backend in {"firered_recaption", "flux3_external_vlm_local", "fibo2_thales_local_openai"}:
        check("endpoint", lambda: _endpoint(config.get("endpoint", {})))
    if backend in {"qwen_pe_i2i", "firered_recaption", "fibo2_thales_local_openai"}:
        from .official_checkout import verified_checkout
        files = {"qwen_pe_i2i": ("prompt_rewrite/pe_core.py", "prompt_rewrite/run_transformers.py"),
                 "firered_recaption": ("agent/recaption.py", "agent/config.py"),
                 "fibo2_thales_local_openai": ("src/bria_vgl",)}[backend]
        check("upstream_checkout", lambda: verified_checkout(config, files)[1])
    if backend == "qwen_pe_i2i":
        check("pe_system_prompt", lambda: file_sha256(Path(config.get("system_prompt_path") or Path(config.get("local_path", "")) / "system_prompt.txt")))
    if backend == "fibo2_thales_local_openai":
        for package in ("litellm", "openai", "boltons"):
            check(package, lambda package=package: require(importlib.util.find_spec(package) is not None,
                                                         "dependency_missing", "Install the pinned VGL checkout dependencies: " + package))
    if needs_diffusers and result["packages"].get("diffusers"):
        from .native_sources import DIFFUSERS_BLOBS, verify_source_file
        module = importlib.util.find_spec("diffusers")
        package_root = Path(next(iter(module.submodule_search_locations)))
        if profile_id == "flux3_klein":
            names = [name for name in DIFFUSERS_BLOBS if "flux3" in name or name == "modular_pipelines/modular_pipeline.py"]
        elif profile_id == "fibo2_dev":
            names = [name for name in DIFFUSERS_BLOBS if "bria_fibo2" in name]
        elif profile_id == "qwen21":
            names = [name for name in DIFFUSERS_BLOBS if "qwenimage21" in name]
        else:
            names = [name for name in DIFFUSERS_BLOBS if "qwenimage" in name and "edit_plus" in name]
        for name in names:
            check("source:" + name, lambda name=name: verify_source_file(package_root / name, name))
    result["ready"] = not result["issues"]
    return result


def doctor(config: dict, profiles: list[str] | None = None) -> dict:
    profiles = profiles or list(CATALOG)
    checks = []
    issues = []
    try:
        _endpoint(config.get("stage", {}))
    except Exception as exc:
        issues.append({"name": "shared_stage_endpoint", "message": str(exc)})
    for profile_id in profiles:
        try:
            validate_config(config, profile_id)
        except Exception as exc:
            issues.append({"name": profile_id, "message": str(exc)})
            continue
        for kind in ("compiler", "editor"):
            runtime = config["models"][profile_id][kind]
            if runtime.get("worker"):
                from .worker import probe_worker
                try:
                    checks.append(probe_worker(runtime["worker"], profile_id, kind, runtime))
                except Exception as exc:
                    checks.append({"profile_id": profile_id, "kind": kind, "ready": False,
                                   "issues": [{"message": str(exc)}]})
            else:
                checks.append(probe_runtime(profile_id, kind, runtime))
    return {"schema_version": "hre_preflight_v3", "ready": not issues and all(row["ready"] for row in checks),
            "checks": checks, "issues": issues, "model_calls": 0,
            "scope": "Local files, package identities and configuration; server inference is not executed."}


def example_files() -> dict[str, dict]:
    endpoint = {"base_url": "http://127.0.0.1:8000/v1", "model": "SET_LOCAL_VLM_DEPLOYMENT_NAME",
                "timeout_seconds": 600, "response_format": "json_object", "settings": {"temperature": 0, "max_tokens": 8192}}
    config = {"schema_version": "hre_runtime_config_v3", "stage": deepcopy(endpoint), "models": {}}
    commits = {"qwen21": "ab96caa944157ca28a4f36b695c3047549f48f98",
               "firered11": "456d010bd3f9bd727f1ab7fe60838caf6ee479e6",
               "fibo2_dev": "8211c2cdbc4c1a2bd78b51e40ffbc8e6c751f6f8"}
    for profile_id, catalog in CATALOG.items():
        compiler = {"backend": catalog["compiler"], "settings": {}}
        if profile_id in commits:
            compiler.update(upstream_path="/srv/upstream/" + profile_id, upstream_revision=commits[profile_id])
        if profile_id in {"qwen21", "flux3_klein"}:
            compiler.update(model_id="Qwen/Qwen-Image-2.1-PE-I2I" if profile_id == "qwen21" else "black-forest-labs/flux-3-image-klein-pup",
                            local_path="/srv/models/" + profile_id + "_compiler", revision="SET_ACTUAL_40_HEX_CHECKPOINT_REVISION",
                            device="cuda:0", torch_dtype="bfloat16")
        else:
            compiler["endpoint"] = deepcopy(endpoint)
        compiler["worker"] = {
            "command": ["/srv/venvs/hre-pe/bin/python" if profile_id == "qwen21" else "/srv/venvs/hre-edit/bin/python",
                        "-m", "hre.v3.worker", "--serve"],
            "timeout_seconds": 1800, "keep_other_workers": False,
        }
        editor = {"model_id": catalog["model_id"], "local_path": "/srv/models/" + profile_id,
                  "revision": "SET_ACTUAL_40_HEX_CHECKPOINT_REVISION", "device": "cuda:0", "torch_dtype": "bfloat16",
                  "pipeline_version": "0.42.0.dev0", "settings": deepcopy(catalog["settings"])}
        if profile_id == "fibo2_dev":
            editor["settings"].update(fonts=[], render_text_images=True)
        editor["worker"] = {"command": ["/srv/venvs/hre-edit/bin/python", "-m", "hre.v3.worker", "--serve"],
                            "timeout_seconds": 1800, "keep_other_workers": False}
        config["models"][profile_id] = {"compiler": compiler, "editor": editor}
    restoration = {"schema_version": "hre_task_v3", "case_id": "restoration_001", "task_mode": "restoration",
                   "profile_id": "qwen21", "strategy": "model_aware", "source": {"path": "/data/source.png"},
                   "brief": "Remove visible motion blur and noise while preserving identities, lettering, structure and composition. Do not invent unreadable text.",
                   "geometry": {"policy": "pad", "grid": 32}, "spatial": {"mode": "full_frame"},
                   "alpha_policy": "require_opaque", "policy": {"mode": "single", "max_generations": 1, "seed_schedule": [42]}}
    reference = {**deepcopy(restoration), "case_id": "reference_001", "task_mode": "reference_enhance",
                 "reference": {"path": "/data/reference.png"},
                 "brief": "Improve the source's brightness, colour balance and tonal relationships using the reference only as an appearance guide. Preserve source content, viewpoint, text and illumination geometry."}
    batch = {"schema_version": "hre_batch_v3", "models": list(CATALOG),
             "arms": [{"name": "native", "strategy": "native", "policy": "single"},
                      {"name": "shared", "strategy": "shared", "policy": "single"},
                      {"name": "model_aware", "strategy": "model_aware", "policy": "single"}],
             "seeds": [42], "share_planning": True,
             "cases": [{"id": "sample001", "task_mode": "restoration", "source": "/data/source.png",
                        "brief": restoration["brief"], "geometry": {"policy": "pad", "grid": 32}}]}
    return {"runtime.example.json": config, "restoration.example.json": restoration,
            "reference.example.json": reference, "batch.example.json": batch}


def write_examples(directory: Path) -> dict:
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    outputs = []
    for name, value in example_files().items():
        path = directory / name
        require(not path.exists(), "example_exists", "Do not overwrite an edited configuration: " + str(path))
        atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        outputs.append(str(path))
    return {"files": outputs, "note": "Replace explicit SET_* values and local paths; no weights or model responses are fabricated."}
