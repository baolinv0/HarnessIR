"""Synthetic handoff integrity tests, never real SAM3/GPU acceptance."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import zipfile

import numpy as np
from PIL import Image
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine/colab"))
import sam3_handoff as h


@pytest.fixture
def result(tmp_path):
    row = dict(image_id="fixture", canonical_sha256="1"*64, original_sha256="2"*64,
               canonicalizer_version="fixture_only", width=8, height=6)
    h.write(tmp_path / "prompt_set.json", dict(labels=["person", "text"]))
    masks = np.zeros((2,6,8), dtype=bool); masks[0,:4,:4] = True; masks[1,2:5,2:6] = True
    arrays = dict(masks=masks, boxes_xyxy=np.asarray([[0,0,4,4],[2,2,6,5]],dtype=np.float32),
                  scores=np.asarray([.9,.8],dtype=np.float32), prompt_indices=np.asarray([0,1],dtype=np.int32),
                  labels=np.asarray(["person","text"],dtype="U64"))
    (tmp_path / "images").mkdir()
    npz = tmp_path / "images/fixture.npz"
    np.savez_compressed(npz, **arrays)
    metadata = dict(**row, status="ok", contract_sha256="3"*64, coordinate_space="canonical_pixels",
                    process_released=True, npz_path="images/fixture.npz", npz_sha256=h.sha(npz), instances=[])
    for i in range(2):
        metadata["instances"].append(dict(id=str(i), array_index=i, label=str(arrays["labels"][i]),
            prompt_index=int(arrays["prompt_indices"][i]), score=float(arrays["scores"][i]), bbox_xyxy=arrays["boxes_xyxy"][i].tolist()))
    h.write(tmp_path / "images/fixture.json", metadata)
    return tmp_path,row,metadata,arrays


def test_overlapping_instances_survive_validation(result):
    output,row,metadata,arrays = result
    assert (arrays["masks"][0] & arrays["masks"][1]).any()
    assert len(h.validate_result(output,row,"3"*64)["instances"]) == 2


@pytest.mark.parametrize("change", ["source", "contract", "release", "label", "score", "bbox", "duplicate", "empty_status", "path"])
def test_rejects_invalid_binding_and_association(result, change):
    output,row,metadata,arrays = result
    if change == "source": metadata["canonical_sha256"] = "4"*64
    elif change == "contract": metadata["contract_sha256"] = "4"*64
    elif change == "release": metadata["process_released"] = False
    elif change == "label": metadata["instances"][1]["label"] = "person"
    elif change == "score": metadata["instances"][0]["score"] = .3
    elif change == "bbox": metadata["instances"][0]["bbox_xyxy"] = [0,0,8,6]
    elif change == "duplicate": metadata["instances"][1]["id"] = "0"
    elif change == "empty_status": metadata["status"] = "empty"
    elif change == "path": metadata["npz_path"] = "../../outside.npz"
    h.write(output / "images/fixture.json",metadata)
    with pytest.raises(ValueError): h.validate_result(output,row,"3"*64)


@pytest.mark.parametrize("kind", ["shape", "dtype", "object_labels", "unknown_prompt", "nan", "box_outside", "hash"])
def test_rejects_invalid_npz(result, kind):
    output,row,metadata,arrays = result
    if kind == "shape": arrays["masks"] = arrays["masks"][:,:,:4]
    elif kind == "dtype": arrays["masks"] = arrays["masks"].astype(np.float32)
    elif kind == "object_labels": arrays["labels"] = arrays["labels"].astype(object)
    elif kind == "unknown_prompt": arrays["prompt_indices"][0] = 99
    elif kind == "nan": arrays["scores"][0] = np.nan
    elif kind == "box_outside": arrays["boxes_xyxy"][0,2] = 100
    elif kind == "hash": arrays["masks"][0,0,0] = ~arrays["masks"][0,0,0]
    np.savez_compressed(output / metadata["npz_path"], **arrays)
    if kind != "hash": metadata["npz_sha256"] = h.sha(output / metadata["npz_path"])
    h.write(output / "images/fixture.json",metadata)
    with pytest.raises(ValueError): h.validate_result(output,row,"3"*64)


def test_valid_empty_and_failure_distinguished(result):
    output,row,metadata,arrays = result
    for key in arrays: arrays[key] = arrays[key][:0]
    np.savez_compressed(output / metadata["npz_path"], **arrays)
    metadata.update(status="empty", instances=[], npz_sha256=h.sha(output / metadata["npz_path"]))
    h.write(output / "images/fixture.json", metadata)
    assert h.validate_result(output,row,"3"*64)["status"] == "empty"
    metadata["status"] = "failed"; h.write(output / "images/fixture.json",metadata)
    with pytest.raises(ValueError): h.validate_result(output,row,"3"*64)


def test_pilot_review_bound_to_actual_assets(result):
    output,row,metadata,arrays = result
    h.write(output / "run.json",dict(run_id="synthetic",contract_sha256="3"*64))
    h.write(output / "inputs.json",dict(images=[row]))
    h.write(output / "pilot5.json",dict(image_ids=["fixture"]))
    h.write(output / "worker_lease.json",dict(pid=999999999))
    with pytest.raises(ValueError): h.accept_pilot(output, "")
    h.accept_pilot(output,"fixture-reviewer")
    original = h.read(output / "pilot_review.json")["pilot_digest"]
    metadata["elapsed_seconds"] = 1; h.write(output / "images/fixture.json",metadata)
    assert original != h.pilot_digest(output)


def test_scheduler_reuses_valid_result_and_rejects_env_change(result, monkeypatch):
    output,row,metadata,arrays=result
    h.write(output/"inputs.json",dict(images=[row]))
    for name in ("pilot5.json","selection20.json"):
        h.write(output/name,dict(image_ids=["fixture"]))
    freeze=b"synthetic-freeze-only"
    h.write(output/"run.json",dict(run_id="fixture",bundle=str(output),contract_sha256="3"*64,
        contract=dict(environment_lock_sha256=h.hashlib.sha256(freeze).hexdigest())))
    h.write(output/"deployment.json",dict(python_executable="fixture-python"))
    h.write(output/"worker_lease.json",dict(pid=999999999))
    monkeypatch.setattr(h,"verify_inputs",lambda _: None)
    monkeypatch.setattr(h.subprocess,"check_output",lambda *a,**k:freeze)
    actual=h._batch(output,"pilot")
    assert actual["complete"] and actual["ok"]==1
    monkeypatch.setattr(h.subprocess,"check_output",lambda *a,**k:b"different-env")
    with pytest.raises(ValueError,match="environment differs"):
        h._batch(output,"pilot")


def test_notebook_input_pack_excludes_unrelated_files_and_cells_compile(tmp_path):
    spec=importlib.util.spec_from_file_location("build_sam3_colab",ROOT/"engine/scripts/build_sam3_colab.py")
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    ds=tmp_path/"runtime/offline_gpu/prepared_20261013";ds.mkdir(parents=True)
    handoff=tmp_path/"runtime/sam3_handoff";handoff.mkdir(parents=True)
    rows=[]
    for i in range(20):
        name=f"fixture_{i:02d}"
        image=ds/(name+".png");Image.new("RGB",(8,6),"navy").save(image)
        rows.append(dict(image_id=name,canonical_path=image.name,original_path=image.name,
                         canonical_sha256=h.sha(image),original_sha256=h.sha(image),canonicalizer_version="fixture_only",width=8,height=6))
    h.write(ds/"manifest.json",dict(images=rows))
    h.write(handoff/"selection20.json",dict(image_ids=[r["image_id"] for r in rows]))
    h.write(handoff/"pilot5.json",dict(image_ids=[r["image_id"] for r in rows[:5]]))
    h.write(handoff/"prompt_set.json",dict(labels=[f"class{i}" for i in range(31)],unknown_id=0))
    (tmp_path/"engine/colab").mkdir(parents=True)
    (tmp_path/"engine/colab/sam3_handoff.py").write_bytes((ROOT/"engine/colab/sam3_handoff.py").read_bytes())
    (ds/"GT.png").write_bytes(b"not selected")
    output=module.build(tmp_path)
    nb=h.read(output/"HarnessIR_SAM3_Colab.ipynb")
    for cell in nb["cells"]:
        if cell["cell_type"]=="code": compile("".join(cell["source"]),"notebook-cell","exec")
    with zipfile.ZipFile(output/"harnessir_sam3_inputs20.zip") as z:
        assert len([n for n in z.namelist() if n.startswith("inputs/")]) == 20
        assert not any("GT" in n or "password" in n for n in z.namelist())
    h.extract_bundle(output/"harnessir_sam3_inputs20.zip",tmp_path/"extracted",h.sha(output/"harnessir_sam3_inputs20.zip"))
    assert h.read(output/"package_receipt.json")["model_inference_performed"] is False


def test_zip_traversal_rejected(tmp_path):
    archive=tmp_path/"bad.zip"
    with zipfile.ZipFile(archive,"w") as z: z.writestr("../escape","not allowed")
    with pytest.raises(ValueError): h.extract_bundle(archive,tmp_path/"out",h.sha(archive))


def test_raw_export_contains_gallery_logs_and_asset_ledger(result):
    output,row,metadata,arrays=result
    source=output/"canonical.png";Image.new("RGB",(8,6),"navy").save(source)
    row["canonical_path"]="canonical.png";row["canonical_sha256"]=h.sha(source)
    metadata["canonical_sha256"]=row["canonical_sha256"]
    h.write(output/"images/fixture.json",metadata)
    h.write(output/"inputs.json",dict(images=[row]))
    h.write(output/"selection20.json",dict(image_ids=["fixture"]))
    h.write(output/"run.json",dict(bundle=str(output),contract_sha256="3"*64))
    destination=output.parent/"raw.zip"
    exported=h.export_results(output,destination)
    assert exported["sha256"]==h.sha(destination)
    with zipfile.ZipFile(destination) as z:
        assert "evidence_gallery.html" in z.namelist()
        assert "images/fixture.npz" in z.namelist()
        ledger=json.loads(z.read("delivery_manifest.json"))
        assert ledger["kind"]=="sam3_raw_handoff_not_production_cache"
        for entry in ledger["files"]:
            assert h.hashlib.sha256(z.read(entry["path"])).hexdigest()==entry["sha256"]
    # Exporting a resumed batch must not hash the previous ledger as an asset.
    h.export_results(output,destination)
    with zipfile.ZipFile(destination) as z:
        ledger=json.loads(z.read("delivery_manifest.json"))
        assert "delivery_manifest.json" not in [e["path"] for e in ledger["files"]]
        for entry in ledger["files"]:
            assert h.hashlib.sha256(z.read(entry["path"])).hexdigest()==entry["sha256"]


def test_sam31_alternative_does_not_mutate_original_contract():
    before=(h.PROFILE,h.CHECKPOINT_SHA256,dict(h.PARAMETERS),h.worker,h.prepare)
    import sam31_handoff as alternative
    assert alternative.runner.PROFILE == "colab_sam31_tri_fp32_cpu_masks_1008_v4"
    assert alternative.runner.PARAMETERS["mask_storage"] == "disk_stream_v1"
    assert (h.PROFILE,h.CHECKPOINT_SHA256,h.PARAMETERS,h.worker,h.prepare)==before


@pytest.mark.parametrize("count,height,width", [(3,5,7),(0,5,7),(2,257,32771)])
def test_streamed_packed_storage_preserves_every_pixel_and_empty_shape(tmp_path,count,height,width):
    rng=np.random.default_rng(20261014)
    masks=rng.integers(0,2,size=(count,height,width),dtype=np.uint8).astype(bool)
    paths=[]
    for i,mask in enumerate(masks):
        path=tmp_path/f"{i}.npy";np.save(path,np.packbits(mask.reshape(-1)));paths.append(path)
    arrays=dict(scores=np.arange(count,dtype=np.float32),labels=np.asarray(["person"]*count,dtype="U64"))
    destination=tmp_path/"streamed.npz"
    h.write_disk_masks_npz(destination,paths,height,width,arrays)
    with np.load(destination,allow_pickle=False) as actual:
        assert actual['masks'].dtype==np.bool_
        assert actual['masks'].shape==masks.shape
        assert np.array_equal(actual['masks'],masks)
        for key,value in arrays.items():assert np.array_equal(actual[key],value)
