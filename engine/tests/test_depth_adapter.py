import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def test_float_depth_validity_direction_and_legend(tmp_path):
    from preprocessing.adapters.depth import write_depth
    original = np.array([[1,np.nan],[3,2]], dtype=np.float32)
    data, assets, warnings = write_depth(original,tmp_path,"full","near")
    loaded = np.load(tmp_path/data["depth_path"],allow_pickle=False)
    assert loaded.dtype == np.float32
    np.testing.assert_equal(loaded,original)
    valid = np.asarray(Image.open(tmp_path/data["valid_mask_path"]))
    assert valid.tolist() == [[255,0],[255,255]]
    preview = np.asarray(Image.open(tmp_path/data["preview_path"]))
    assert preview[0,0] == 0 and preview[1,0] == 255
    assert data["larger_is"] == "near"
    assert data["finite_value_range"] == [1.,3.]
    assert any(a["path"] == "maps/depth_legend.png" for a in assets)
    assert all((tmp_path/a["path"]).exists() for a in assets)
    raw_asset=next(a for a in assets if a["path"]==data["depth_path"])
    assert raw_asset["width"] is None and raw_asset["height"] is None
    assert "nonfinite_depth_values" in warnings
    from jsonschema import Draft202012Validator
    schema=json.loads((Path(__file__).resolve().parents[2]/"Design_v1_1_20261012/schemas/tool_payload_depth.schema.json").read_text("utf-8"))
    Draft202012Validator(schema).validate(data)


def test_all_invalid_depth_is_failure_not_empty(tmp_path):
    from preprocessing.adapters.depth import write_depth
    with pytest.raises(ValueError,match="finite"):
        write_depth(np.full((2,2),np.nan),tmp_path,"full","near")


def test_author_api_bgr_boundary_swaps_exactly_once():
    from preprocessing.adapters.depth import rgb_to_author_bgr
    rgb = np.array([[[255,10,30]]],dtype=np.uint8)
    assert rgb_to_author_bgr(rgb).tolist() == [[[30,10,255]]]
    assert rgb.tolist() == [[[255,10,30]]]
