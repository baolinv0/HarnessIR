import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))


def test_masks_overlap_class_union_and_stable_palette(tmp_path):
    from preprocessing.adapters.segmentation import write_segmentation
    prompt = {"prompt_set_id":"set","labels":["person","sky"],"unknown_id":0,"fixed_order":True,"palette_seed":0}
    view = {"id":"full","grid_shape":[2,3],"view_to_canonical":[[1/3,0,0],[0,.5,0],[0,0,1]],"kind":"full_frame"}
    records = [{"id":"a","label":"person","prompt_index":0,"score":.5,"bbox":[0,0,2,2],"mask":np.array([[1,1,0],[0,0,0]])},
               {"id":"b","label":"sky","prompt_index":1,"score":.9,"bbox":[1,0,3,2],"mask":np.array([[0,1,1],[0,0,0]])}]
    data,assets,warnings = write_segmentation(records,prompt,tmp_path,view,(3,2))
    assert data["unknown_id"] == 0
    assert data["native_masks_may_overlap"] is True
    assert np.asarray(Image.open(tmp_path/data["native_masks"][0]["mask_path"]))[0,1] == 255
    assert np.asarray(Image.open(tmp_path/data["native_masks"][1]["mask_path"]))[0,1] == 255
    raster = np.asarray(Image.open(tmp_path/data["display_label_path"]))
    assert raster.tolist() == [[1,2,2],[0,0,0]]
    assert data["unassigned_ratio"] == .5
    from jsonschema import Draft202012Validator
    schema=json.loads((Path(__file__).resolve().parents[2]/"Design_v1_1_20261012/schemas/tool_payload_segmentation.schema.json").read_text("utf-8"))
    Draft202012Validator(schema).validate(data)
    raw = json.loads((tmp_path/data["native_result_path"]).read_text("utf-8"))
    assert raw["regions"][0]["union_area_pixels"] == 2
    assert all((tmp_path/a["path"]).exists() for a in assets)
    data2,_,_ = write_segmentation(list(reversed(records)),prompt,tmp_path/"other",view,(3,2))
    assert json.loads((tmp_path/data["palette_path"]).read_text()) == json.loads((tmp_path/"other"/data2["palette_path"]).read_text())


def test_bad_label_mask_association_is_rejected(tmp_path):
    from preprocessing.adapters.segmentation import write_segmentation
    prompt={"prompt_set_id":"s","labels":["person"],"unknown_id":0,"fixed_order":True,"palette_seed":0}
    view={"id":"full","grid_shape":[2,2],"view_to_canonical":[[.5,0,0],[0,.5,0],[0,0,1]],"kind":"full_frame"}
    with pytest.raises(ValueError,match="association"):
        write_segmentation([{"id":"m","label":"sky","prompt_index":0,"score":.9,"bbox":[0,0,2,2],"mask":np.ones((2,2))}],prompt,tmp_path,view,(2,2))
