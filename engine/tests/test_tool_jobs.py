import copy
import pytest
from hir_manual.cache import make_cache_key
from hir_manual.storage import read_json
from hir_manual.protocol import DESIGN_DIR


def test_same_contract_same_key():
    contract = read_json(DESIGN_DIR / "examples/local_tools/cache_contract.json")
    assert make_cache_key(contract) == make_cache_key(copy.deepcopy(contract))


@pytest.mark.parametrize("field,value", [("model_bundle_sha256", "0"*64), ("prompt_set_sha256", "1"*64), ("adapter_version", "another"), ("roi_policy_id", "tiles_v2")])
def test_changes_invalidate_cache(field, value):
    contract = read_json(DESIGN_DIR / "examples/local_tools/cache_contract.json")
    modified = copy.deepcopy(contract)
    modified[field] = value
    assert make_cache_key(contract) != make_cache_key(modified)


def test_precision_and_class_order_change_key():
    contract = read_json(DESIGN_DIR / "examples/local_tools/cache_contract.json")
    modified = copy.deepcopy(contract)
    modified["backend"]["precision"] = "fp16"
    assert make_cache_key(contract) != make_cache_key(modified)
    modified = copy.deepcopy(contract)
    modified["parameters"]["classes"] = ["face", "person"]
    alternative = copy.deepcopy(modified)
    alternative["parameters"]["classes"].reverse()
    assert make_cache_key(alternative) != make_cache_key(modified)
