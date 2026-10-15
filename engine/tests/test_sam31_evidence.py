"""Storage/protocol tests, not synthetic model inference or accuracy claims."""
import copy
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from hir_manual.sam31_evidence import normalize_masks, iter_masks, validate_import_configuration, PROFILE
from hir_manual.tool_registry import load_profile, load_registry, make_contract, check_entry, gpu_evidence_origin_matches
from hir_manual.protocol import validate_schema
from hir_manual.storage import read_json, write_json

ROOT = Path(__file__).resolve().parents[2]


def fixture_native(tmp_path, empty=False):
    masks = np.zeros((0 if empty else 2, 2, 3), dtype=bool)
    if not empty:
        masks[0, 0, :2] = True
        masks[1, 0, 1:] = True
    path = tmp_path / "native.npz"
    np.savez_compressed(path, masks=masks)
    instances = [] if empty else [dict(id="a", array_index=0, label="person", prompt_index=0, score=.6,
        bbox_xyxy=[0,0,2,2],native_bbox_xyxy=[-1,0,2,2],area_pixels=2),
        dict(id="b",array_index=1,label="sky",prompt_index=1,score=.9,bbox_xyxy=[1,0,3,2],native_bbox_xyxy=[1,0,4,2],area_pixels=2)]
    metadata = dict(width=3,height=2,instances=instances)
    prompt = dict(prompt_set_id="fixture",labels=["person","sky"],unknown_id=0,fixed_order=True,palette_seed=0)
    return path,metadata,prompt


@pytest.mark.parametrize("empty", [False, True])
def test_stream_masks_empty_overlap_coordinates_and_composer_assets(tmp_path, empty):
    path, metadata, prompt = fixture_native(tmp_path, empty)
    data, assets = normalize_masks(path, metadata, prompt, tmp_path / "normalized")
    validate_schema("tool_payload_segmentation.schema.json", data)
    out = tmp_path / "normalized"
    assert len(data["native_masks"]) == (0 if empty else 2)
    assert {a["path"] for a in assets if a["kind"] == "map"} == {"maps/semantic.png", "maps/segmentation_legend.png"}
    # Retain overlap and lossless originals while visual winners use confidence.
    display = np.asarray(Image.open(out / data["display_label_path"]))
    assert display.tolist() == ([[0,0,0],[0,0,0]] if empty else [[1,2,2],[0,0,0]])
    native = read_json(out / "raw/seg.json")
    assert native["overlap_pixels"] == (0 if empty else 1)
    assert data["unassigned_ratio"] == (1 if empty else .5)
    if not empty:
        assert native["instances"][0]["native_bbox"][0] == -1
        assert data["native_masks"][0]["bbox_norm"] == [0,0,2/3,1]
        assert native["regions"][0]["union_area_pixels"] == 2
        assert native['instances'][0]['native_mask_path']==native['instances'][0]['mask_path']
        assert np.array_equal(np.asarray(Image.open(out / native['instances'][0]['native_mask_path'])) >= .5,np.array([[1,1,0],[0,0,0]],dtype=bool))
        assert not list(out.glob('raw/mask_*.npy'))


@pytest.mark.parametrize("field,value", [("label","car"),("area_pixels",3),("bbox_xyxy",[0,0,1,2])])
def test_stream_associations_reject_forgery(tmp_path, field, value):
    path,metadata,prompt=fixture_native(tmp_path)
    metadata["instances"][0][field]=value
    with pytest.raises(ValueError):
        normalize_masks(path,metadata,prompt,tmp_path/'output')


def test_stream_rejects_dense_float_or_wrong_dimensions(tmp_path):
    path=tmp_path/'bad.npz'
    np.savez_compressed(path,masks=np.zeros((2,2,3),dtype=np.float32))
    with pytest.raises(ValueError,match='dtype'):
        list(iter_masks(path,2,2,3))


@pytest.mark.parametrize('mutation',['mask','association','provenance'])
def test_normalized_output_cannot_self_validate_against_forged_maps(tmp_path,mutation):
    import shutil
    from hir_manual.sam31_evidence import verify_normalized_native,RAW_CONTRACT,RESULT_ZIP_SHA,INPUT_ZIP_SHA
    from hir_manual.storage import sha256_file
    path,metadata,prompt=fixture_native(tmp_path)
    metadata['npz_sha256']=sha256_file(path)
    out=tmp_path/'normalized';data,_=normalize_masks(path,metadata,prompt,out)
    shutil.copyfile(path,out/'raw/native.npz')
    write_json(out/'raw/native_metadata.json',metadata)
    write_json(out/'raw/provenance.json',dict(raw_contract_sha256=RAW_CONTRACT,received_result_archive_sha256=RESULT_ZIP_SHA,frozen_input_archive_sha256=INPUT_ZIP_SHA))
    write_json(out/'evidence.json',dict(data=data))
    verify_normalized_native(out,metadata)
    if mutation=='mask':Image.new('L',(3,2)).save(out/data['native_masks'][0]['mask_path'])
    if mutation=='association':
        data['native_masks'][0]['score']=.8;write_json(out/'evidence.json',dict(data=data))
    if mutation=='provenance':
        value=read_json(out/'raw/provenance.json');value['received_result_archive_sha256']='0'*64
        write_json(out/'raw/provenance.json',value)
    with pytest.raises(ValueError):verify_normalized_native(out,metadata)


def test_profile_preserves_all_three_gpu_contracts_and_provenance():
    full=load_profile('gpu_full_v1',ROOT)
    alt=load_profile(PROFILE,ROOT)
    fullreg=load_registry(ROOT,'gpu_full_v1')
    altreg=load_registry(ROOT,PROFILE)
    validate_import_configuration(alt,altreg.tools['T4_SEGMENTATION'])
    for tool in ('T1_OCR','T2_FACE','T3_DEPTH'):
        assert full.tools[tool]==alt.tools[tool]
        assert fullreg.tools[tool]==altreg.tools[tool]
        assert make_contract('1'*64,tool,full,fullreg.tools[tool])==make_contract('1'*64,tool,alt,altreg.tools[tool])
        assert gpu_evidence_origin_matches(PROFILE,tool,'gpu_full_v1',True)
    assert not gpu_evidence_origin_matches('gpu_full_v1','T4_SEGMENTATION',PROFILE,False)
    assert not gpu_evidence_origin_matches(PROFILE,'T4_SEGMENTATION','gpu_full_v1',True)
    assert gpu_evidence_origin_matches(PROFILE,'T4_SEGMENTATION',PROFILE,False)
    entry=altreg.tools['T4_SEGMENTATION']
    current=make_contract('1'*64,'T4_SEGMENTATION',alt,entry)
    legacy=copy.deepcopy(alt)
    legacy.tools['T4_SEGMENTATION']['normalization_version']='sam31_stream_lossless_v1'
    old=make_contract('1'*64,'T4_SEGMENTATION',legacy,entry)
    from hir_manual.cache import make_cache_key
    assert make_cache_key(current)!=make_cache_key(old)


@pytest.mark.parametrize("mutation", ['model','weight','backend','params'])
def test_independent_import_locks_reject_self_selected_expected_model(mutation):
    profile=load_profile(PROFILE,ROOT)
    entry=copy.deepcopy(load_registry(ROOT,PROFILE).tools['T4_SEGMENTATION'])
    if mutation=='model':entry['model_name']='SAM3'
    if mutation=='weight':entry['components'][0]['sha256']='0'*64
    if mutation=='backend':entry['backend']['framework_version']='another'
    if mutation=='params':profile.tools['T4_SEGMENTATION']['score_threshold']=.15
    with pytest.raises(ValueError):validate_import_configuration(profile,entry)


@pytest.mark.parametrize('mutation',['source','model','contract','asset'])
@pytest.mark.private_assets
def test_received_archive_bound_source_model_contract_and_hash_reject_forgery(tmp_path,mutation):
    from hir_manual.sam31_evidence import verify_native,RAW_CONTRACT,RUN_ID
    source=ROOT/'Data/annotations/cache/alternatives/SAM31'/RAW_CONTRACT/RUN_ID
    # A public source checkout deliberately excludes real photos, accepted
    # archives and local audit locks. Do not replace them with simulated runs.
    required=[source/name for name in ('run.json','inputs.json','prompt_set.json','images/commons_001.json')]
    required += [ROOT/'runtime/sam3_colab/uploads/847d740a9d1c0c47/harnessir_sam3_inputs20.zip',
                 ROOT/'runtime/alternatives/sam31/sam31_v5_selection20.zip']
    required += [ROOT/'runtime/alternatives/sam31'/name for name in
                 ('official_weight_lock.json','source_lock.json','tool_environment.freeze.txt')]
    if any(not path.is_file() for path in required):
        pytest.skip('Requires private accepted SAM3.1 cache, frozen input/result ZIPs and independent locks; no inference is simulated')
    for name in ('run.json','inputs.json','prompt_set.json','images/commons_001.json'):
        write_json(tmp_path/name,read_json(source/name))
    if mutation=='source':
        value=read_json(tmp_path/'inputs.json');value['images'][0]['canonical_sha256']='0'*64
        write_json(tmp_path/'inputs.json',value)
    if mutation=='model':
        value=read_json(tmp_path/'run.json');value['model']='SAM3';write_json(tmp_path/'run.json',value)
    if mutation=='contract':
        value=read_json(tmp_path/'run.json');value['contract']['parameters']['score_threshold']=.15
        write_json(tmp_path/'run.json',value)
    if mutation=='asset':
        value=read_json(tmp_path/'images/commons_001.json');value['npz_sha256']='0'*64
        write_json(tmp_path/'images/commons_001.json',value)
    with pytest.raises(ValueError):verify_native(ROOT,tmp_path,'commons_001')


def test_cache_only_worker_guard_even_if_ready_and_local_executable_exists():
    entry=load_registry(ROOT,PROFILE).tools['T4_SEGMENTATION']
    entry['ready']=True
    entry['python_executable']=str(ROOT/'engine/.venv/Scripts/python.exe')
    with pytest.raises(ValueError,match='cache-only'):check_entry(entry)


def test_tool_service_cache_miss_blocks_without_starting_any_worker(tmp_path,photo,fixture_json,monkeypatch):
    from hir_manual.service import Controller
    from hir_manual.tool_service import ToolService
    import hir_manual.tool_service as tools
    write_json(tmp_path/'preprocessing/configs/gpu_sam31_v5.json',load_profile(PROFILE,ROOT))
    registry=load_registry(ROOT,PROFILE)
    registry.tools['T4_SEGMENTATION']['ready']=True
    registry.tools['T4_SEGMENTATION']['python_executable']=str(ROOT/'engine/.venv/Scripts/python.exe')
    write_json(tmp_path/'preprocessing/registry/gpu_sam31_v5.json',registry)
    def prohibited(*args,**kwargs):raise AssertionError('No worker may start for imported-only SAM3.1')
    monkeypatch.setattr(tools,'run_worker',prohibited)
    ctl=Controller(tmp_path);state=ctl.new(photo,'fixture no local model',{'evidence_profile_id':PROFILE})
    diagnosis=fixture_json('diagnosis');diagnosis['tool_plan']=[{'tool':'T4_SEGMENTATION','reason':'cache miss fixture'}]
    assert ctl.import_json(state.case_id,state.pending_task_id,diagnosis,'fixture').accepted
    ToolService(tmp_path).run_case(state.case_id)
    state=ctl.inspect(state.case_id)
    assert state.operation_status=='blocked' and not state.received_tools
    assert ctl.unavailable_tools(state.case_id)['T4_SEGMENTATION']['code']=='model_missing'


@pytest.mark.parametrize('empty',[False,True])
def test_normalized_full_validator_cache_reuse_and_composer_executor_boundary(tmp_path,fixture_json,empty):
    from hir_manual.storage import sha256_file,sha256_bytes
    from hir_manual.tool_registry import canonical_json
    from hir_manual.cache import EvidenceCache,make_cache_key
    from hir_manual.local_evidence import validate_local_evidence
    from hir_manual.service import Controller
    from hir_manual.tool_service import ToolService
    # Synthetic storage fixture. It is not published into real Data or inferred.
    path,metadata,prompt=fixture_native(tmp_path,empty)
    photo=tmp_path/'photo.png';Image.new('RGB',(3,2),'navy').save(photo)
    write_json(tmp_path/'preprocessing/configs/gpu_sam31_v5.json',load_profile(PROFILE,ROOT))
    write_json(tmp_path/'preprocessing/registry/gpu_sam31_v5.json',load_registry(ROOT,PROFILE))
    ctl=Controller(tmp_path)
    state=ctl.new(photo,'synthetic contract fixture only',{'evidence_profile_id':PROFILE})
    assert state.deviated
    case=ctl.case(state.case_id)
    assert PROFILE in read_json(case.path('snapshot/schemas/evidence_local.schema.json'))['properties']['evidence_profile_id']['enum']
    config=read_json(case.path('case_config.json'));profile=load_profile(PROFILE,tmp_path)
    # Fixture labels retain the exact frozen 31-label contract; two populated
    # classes person/sky use indices 0/4 rather than altering the profile.
    prompt=profile.tools['T4_SEGMENTATION']['prompt_set']
    if not empty:
        metadata['instances'][1]['prompt_index']=4
    entry=config['tool_registry']['tools']['T4_SEGMENTATION']
    contract=make_contract(state.input_sha256,'T4_SEGMENTATION',profile,entry,'hir_rgb8_exif_icc_v2_stablepng')
    out=tmp_path/'normalized';data,assets=normalize_masks(path,metadata,prompt,out)
    evidence=dict(protocol_version='1.1',tool_id='T4_SEGMENTATION',input_sha256=state.input_sha256,status='ok',model_name='SAM3.1',
        checkpoint_sha256=entry['components'][0]['sha256'],source_width=3,source_height=2,tool_width=3,tool_height=2,
        coordinates='canonical_norm',source_to_tool=[[1,0,0],[0,1,0],[0,0,1]],detections=[],assets=assets,data=data,error=None,
        image_id='fixture_only',original_sha256=sha256_file(photo),evidence_profile_id=PROFILE,model_bundle_sha256=entry['model_bundle_sha256'],
        components=[dict(name=c['name'],sha256=c['sha256']) for c in entry['components']],backend=entry['backend'],
        parameters_sha256=sha256_bytes(canonical_json(contract['parameters'])),cache_key=make_cache_key(contract),
        views=[dict(id='full',kind='full_frame',grid_shape=[2,3],view_to_canonical=[[1/3,0,0],[0,.5,0],[0,0,1]])],
        quality_warnings=['synthetic_storage_fixture_no_model_called'],elapsed_ms=0,peak_rss_mb=None,formal_eligible=False)
    write_json(out/'evidence.json',evidence)
    validate_local_evidence(out,contract)
    cache=EvidenceCache(tmp_path/'Data/annotations/cache')
    with cache.lock('T4_SEGMENTATION',make_cache_key(contract)):
        first=cache.publish(contract,out)
        second=cache.publish(contract,out)
    assert first==second==cache.lookup(contract)
    diagnosis=fixture_json('diagnosis');diagnosis['tool_plan']=[{'tool':'T4_SEGMENTATION','reason':'fixture protocol test'}]
    assert ctl.import_json(state.case_id,state.pending_task_id,diagnosis,'fixture').accepted
    ToolService(tmp_path).run_case(state.case_id)
    assert ctl.inspect(state.case_id).workflow_status=='WAIT_COMPOSITION'
    composer=ctl.current_task(state.case_id)
    assert len([a for a in composer.allowed_assets if a.kind=='map'])==2
    assert any(a.path.endswith('segmentation_legend.png') for a in composer.allowed_assets)
    assert not any('mask_' in a.path or 'native.npz' in a.path for a in composer.allowed_assets)
    assert ctl.import_json(state.case_id,composer.task_id,fixture_json('composition'),'fixture').accepted
    assert [a.path for a in ctl.current_task(state.case_id).allowed_assets]==['input/canonical.png']
