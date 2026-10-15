"""Contract/provenance checks only: no image inference or accuracy acceptance."""
import copy
from pathlib import Path

import pytest
from PIL import Image

from hir_manual.cache import make_cache_key
from hir_manual.cases import create_case
from hir_manual.protocol import DESIGN_DIR, validate_schema
from hir_manual.storage import read_json, write_json, CasePaths
from hir_manual.tool_registry import load_profile, make_contract, gpu_evidence_origin_matches
from preprocessing.workers.t4_yoloe import locked_variant
from preprocessing.workers.common import WorkerFailure

ROOT = Path(__file__).resolve().parents[2]


def test_alternative_keeps_unchanged_contracts_and_original_files():
    original = load_profile("gpu_full_v1", ROOT)
    alternative = load_profile("gpu_yoloe26l_v1", ROOT)
    registry = read_json(ROOT / "preprocessing/registry/gpu_full_v1.json")
    assert not alternative.formal_eligible
    assert alternative.tools["T4_SEGMENTATION"]["model"] == "YOLOE-26l-seg"
    assert alternative.tools["T4_SEGMENTATION"]["prompt_set"] == original.tools["T4_SEGMENTATION"]["prompt_set"]
    for tool in ("T1_OCR", "T2_FACE", "T3_DEPTH"):
        entry = registry["tools"][tool]
        a = make_contract("1" * 64, tool, original, entry)
        b = make_contract("1" * 64, tool, alternative, entry)
        assert a == b and make_cache_key(a) == make_cache_key(b)
    assert original.tools["T4_SEGMENTATION"]["model"] == "SAM3"


@pytest.mark.parametrize("name,marker", [("YOLOE-26n-seg", "yoloe-26n"), ("YOLOE-26l-seg", "yoloe-26l")])
def test_worker_requires_exact_checkpoint_and_embedding_variant(name, marker):
    assert locked_variant({"model_name": name}, {"model": name}) == marker
    with pytest.raises(WorkerFailure):
        locked_variant({"model_name": name}, {"model": "SAM3"})
    with pytest.raises(WorkerFailure):
        locked_variant({"model_name": "YOLOE-27l-seg"}, {"model": "YOLOE-27l-seg"})


def test_alternative_provenance_cannot_claim_original_evaluation():
    assert gpu_evidence_origin_matches("gpu_yoloe26l_v1", "T1_OCR", "gpu_full_v1", True)
    assert gpu_evidence_origin_matches("gpu_yoloe26l_v1", "T4_SEGMENTATION", "gpu_yoloe26l_v1", False)
    assert not gpu_evidence_origin_matches("gpu_yoloe26l_v1", "T4_SEGMENTATION", "gpu_full_v1", True)
    assert not gpu_evidence_origin_matches("gpu_full_v1", "T4_SEGMENTATION", "gpu_yoloe26l_v1", False)
    assert not gpu_evidence_origin_matches("gpu_yoloe26l_v1", "T4_SEGMENTATION", "gpu_yoloe26l_v1", True)


def test_new_schema_snapshot_preserves_legacy_and_forbids_false_formal_claim(tmp_path):
    source = tmp_path / "input.png"
    Image.new("RGB", (12, 10), "navy").save(source)
    original = create_case(tmp_path, source, "fixture interface only", {})
    original_paths = CasePaths(original.case_id, tmp_path)
    original_bytes = original_paths.path("snapshot/schemas/evidence_local.schema.json").read_bytes()
    write_json(tmp_path / "preprocessing/configs/gpu_yoloe26l.json", load_profile("gpu_yoloe26l_v1", ROOT))
    alternate = create_case(tmp_path, source, "fixture alternative only", {"evidence_profile_id": "gpu_yoloe26l_v1"})
    assert alternate.deviated and not original.deviated
    assert original_paths.path("snapshot/schemas/evidence_local.schema.json").read_bytes() == original_bytes
    assert "gpu_yoloe26l_v1" not in read_json(original_paths.path("snapshot/schemas/evidence_local.schema.json"))["properties"]["evidence_profile_id"]["enum"]
    schema = read_json(CasePaths(alternate.case_id, tmp_path).path("snapshot/schemas/evidence_local.schema.json"))
    assert "gpu_yoloe26l_v1" in schema["properties"]["evidence_profile_id"]["enum"]
    conditional = schema["allOf"][-1]
    from jsonschema import Draft202012Validator
    validator = Draft202012Validator(conditional)
    assert not list(validator.iter_errors({"evidence_profile_id": "gpu_yoloe26l_v1", "formal_eligible": False}))
    assert list(validator.iter_errors({"evidence_profile_id": "gpu_yoloe26l_v1", "formal_eligible": True}))
