"""The complete built-in compiler/editor registry and optional process transport."""
from __future__ import annotations

from copy import deepcopy
import importlib
from pathlib import Path
import time

from ..models import HREError, file_sha256, sha256_bytes
from .common import digest, render_instruction, require
from .contracts import CATALOG, validate_request
from .spatial import prepare_request, deliver_outputs


_MODULES = {"qwen21": "qwen", "firered11": "firered", "flux3_klein": "flux", "fibo2_dev": "fibo"}


def request_binding(request: dict) -> str:
    spatial = {key: value for key, value in request.get("spatial", {}).items()
               if key not in {"mask_path"}}
    if request.get("spatial", {}).get("mask_path"):
        spatial["mask_sha256"] = file_sha256(Path(request["spatial"]["mask_path"]))
    binding = {"profile_id": request["profile_id"], "task_mode": request["task_mode"],
                   "strategy": request["strategy"], "brief": request["brief"], "intent": request.get("intent"),
                   "inputs": [{key: asset[key] for key in ("role", "sha256", "width", "height", "mode")}
                              for asset in request["inputs"]],
                   "canvas": request["canvas"], "spatial": spatial}
    if "workflow_contract" in request:
        binding.update(workflow_contract=request["workflow_contract"],
                       reference_contract_sha256=request.get("reference_contract_sha256"))
    return digest(binding)


def _module(profile_id: str):
    return importlib.import_module("hre.v3." + _MODULES[profile_id])


def _compile_local(request: dict, config: dict) -> dict:
    validate_request(request)
    backend = config.get("backend")
    require(backend in CATALOG[request["profile_id"]]["compilers"], "compiler_invalid", "Compiler/profile mismatch")
    if backend == "direct":
        return {"text": render_instruction(request),
                "condition_kind": "semantic_instruction" if request["profile_id"] == "qwen21" else "edit_instruction",
                "native_output": None, "observation": {"compiler_id": "hre-direct-v3",
                    "calls_attempted": 0, "calls_completed": 0, "fallback_used": False}, "warnings": []}
    return _module(request["profile_id"]).compile_condition(request, config)


def _generate_local(request: dict, condition: dict, config: dict, output_dir: Path) -> dict:
    return _module(request["profile_id"]).generate(request, condition, config, output_dir)


def compile_condition(request: dict, config: dict) -> dict:
    validate_request(request)
    started = time.monotonic()
    if config.get("worker") and config.get("backend") != "direct":
        from .worker import invoke_worker
        result = invoke_worker("compile", request, config)
    else:
        result = _compile_local(request, config)
    return seal_condition(request, config, result, elapsed_seconds=time.monotonic() - started)


def seal_condition(request: dict, config: dict, result: dict, *, elapsed_seconds: float | None = None) -> dict:
    """Bind a real compiler result, including a verified worker recovery result."""
    require(isinstance(result, dict) and isinstance(result.get("text"), str) and result["text"].strip(),
            "condition_empty", "Compiler did not return a final native condition")
    require(isinstance(result.get("observation"), dict), "compiler_observation_missing", "Compiler must report its actual calls")
    result = deepcopy(result)
    bindings = dict(schema_version="hre_condition_v3", profile_id=request["profile_id"],
                    request_binding_sha256=request_binding(request), text_sha256=sha256_bytes(result["text"].encode()),
                    compiler_config_sha256=digest(config), compilation_request_sha256=digest(request))
    for key, value in bindings.items():
        require(key not in result or result[key] == value, "condition_binding_mismatch", "Compiler result carries a conflicting " + key)
    result.update(bindings)
    if elapsed_seconds is not None:
        result["observation"]["total_elapsed_seconds"] = elapsed_seconds
    result.setdefault("warnings", [])
    # This sidecar describes inspectable intent bindings, not a semantic proof.
    result["intent_audit"] = {"mode": "structural_binding", "semantic_equivalence_proven": False,
                              "intent_sha256": digest(request["intent"]) if request.get("intent") else None,
                              "target_ids": [row["id"] for row in (request.get("intent") or {}).get("targets", [])],
                              "input_order": [row["role"] for row in request["inputs"]]}
    return result


def generate(request: dict, condition: dict, config: dict, output_dir: Path) -> dict:
    validate_request(request)
    require(condition.get("profile_id") == request["profile_id"] and
            condition.get("request_binding_sha256") == request_binding(request),
            "condition_binding_mismatch", "This condition was compiled for different inputs, geometry or intent")
    require(condition.get("text_sha256") == sha256_bytes(condition["text"].encode()),
            "condition_modified", "Accepted native condition text changed")
    require(config.get("model_id") == CATALOG[request["profile_id"]]["model_id"], "model_identity_mismatch", "Editor/profile mismatch")
    started = time.monotonic()
    if config.get("worker"):
        from .worker import invoke_worker
        result = invoke_worker("generate", request, config, condition=condition, output_dir=output_dir)
    else:
        result = _generate_local(request, condition, config, output_dir)
    return seal_generation(request, condition, config, result, output_dir=output_dir, elapsed_seconds=time.monotonic() - started)


def seal_generation(request: dict, condition: dict, config: dict, result: dict, *, output_dir: Path | None = None,
                    elapsed_seconds: float | None = None) -> dict:
    """Validate saved native outputs without invoking any model during recovery."""
    require(isinstance(result, dict) and isinstance(result.get("outputs"), list) and result["outputs"],
            "native_output_missing", "Editor did not return native output records")
    observation = result.get("observation")
    require(isinstance(observation, dict) and observation.get("actual_generation_count") == len(result["outputs"]),
            "generation_count_mismatch", "Retain and account for every returned image")
    for output in result["outputs"]:
        if output_dir is not None:
            require(Path(output["path"]).resolve().is_relative_to(Path(output_dir).resolve()),
                    "output_binding_mismatch", "Native output does not belong to this execution directory")
        require(file_sha256(Path(output["path"])) == output["sha256"], "output_modified", "Output bytes differ from the native receipt")
    bindings = dict(editor_config_sha256=digest(config), condition_text_sha256=condition["text_sha256"],
                    request_binding_sha256=request_binding(request), execution_request_sha256=digest(request),
                    condition_sha256=digest(condition))
    if output_dir is not None:
        bindings["output_directory"] = str(Path(output_dir).resolve())
    for key, value in bindings.items():
        require(key not in observation or observation[key] == value, "generation_binding_mismatch", "Native receipt carries a conflicting " + key)
    observation.update(bindings)
    if elapsed_seconds is not None:
        observation["total_elapsed_seconds"] = elapsed_seconds
    return result
