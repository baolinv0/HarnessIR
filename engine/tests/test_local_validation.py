"""Adversarial synthetic evidence acceptance, not real model acceptance."""
import copy
import numpy as np
import pytest
from hir_manual.tool_registry import load_profile,make_contract
from hir_manual.local_evidence import validate_local_evidence
from hir_manual.storage import write_json
from local_fixtures import synthetic_registry,face_evidence
from preprocessing.adapters.common import full_view
from preprocessing.adapters.segmentation import write_segmentation


def segmentation(tmp_path):
    entry=synthetic_registry(tmp_path)
    entry["model_name"]="YOLOE-26n-seg"
    entry["backend"]["implementation"]="ultralytics_yoloe_text"
    profile=load_profile()
    contract=make_contract("a"*64,"T4_SEGMENTATION",profile,entry)
    directory=tmp_path/"result"
    base=face_evidence(directory,contract,width=64,height=48)
    view=full_view(64,48)
    labels=profile.tools["T4_SEGMENTATION"]["prompt_set"]["labels"]
    records=[{"id":"instance_0","prompt_index":0,"label":labels[0],"score":.9,"bbox":[0,0,32,48],"mask":np.tile(np.arange(64)<32,(48,1))},{"id":"instance_1","prompt_index":1,"label":labels[1],"score":.8,"bbox":[16,0,64,48],"mask":np.tile(np.arange(64)>=16,(48,1))}]
    data,assets,warnings=write_segmentation(records,profile.tools["T4_SEGMENTATION"]["prompt_set"],directory,view,(64,48))
    base.update(tool_id="T4_SEGMENTATION",model_name="YOLOE-26n-seg",data=data,assets=assets,quality_warnings=warnings)
    write_json(directory/"evidence.json",base)
    return directory,contract,base


def test_native_mask_label_swap_rejected(tmp_path):
    directory,contract,data=segmentation(tmp_path)
    validate_local_evidence(directory,contract)
    masks=data["data"]["native_masks"]
    masks[0]["mask_path"],masks[1]["mask_path"]=masks[1]["mask_path"],masks[0]["mask_path"]
    write_json(directory/"evidence.json",data)
    with pytest.raises(ValueError,match="association"):
        validate_local_evidence(directory,contract)


def test_view_shape_must_match_mask(tmp_path):
    directory,contract,data=segmentation(tmp_path)
    data["views"][0]["grid_shape"]=[96,128]
    write_json(directory/"evidence.json",data)
    with pytest.raises(ValueError,match="grid disagreement"):
        validate_local_evidence(directory,contract)


def test_gpu_profile_refuses_cpu_small_registry(tmp_path):
    entry=synthetic_registry(tmp_path)
    entry["model_name"]="Depth-Anything-V2-Small"
    entry["backend"]["implementation"]="depth_anything_author_api"
    with pytest.raises(ValueError,match="substitution"):
        make_contract("a"*64,"T3_DEPTH",load_profile("gpu_full_v1"),entry)


def test_prompt_order_is_frozen_in_profile(tmp_path,monkeypatch):
    entry=synthetic_registry(tmp_path)
    entry["model_name"]="YOLOE-26n-seg"
    entry["backend"]["implementation"]="ultralytics_yoloe_text"
    profile=load_profile()
    first=make_contract("a"*64,"T4_SEGMENTATION",profile,entry)
    monkeypatch.setattr("hir_manual.tool_registry.read_json",lambda *a: (_ for _ in ()).throw(AssertionError("must use frozen prompt")))
    assert make_contract("a"*64,"T4_SEGMENTATION",profile,entry)==first


def test_malformed_native_records_rejected_as_validation_error(tmp_path):
    from hir_manual.storage import read_json,sha256_file
    directory,contract,data=segmentation(tmp_path)
    raw=directory/data["data"]["native_result_path"]
    native=read_json(raw)
    native["instances"]=[123]
    write_json(raw,native)
    for asset in data["assets"]:
        if asset["path"]==data["data"]["native_result_path"]:
            asset["sha256"]=sha256_file(raw)
    write_json(directory/"evidence.json",data)
    with pytest.raises(ValueError,match="native instance"):
        validate_local_evidence(directory,contract)
