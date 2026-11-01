import copy
from pathlib import Path
import pytest
from PIL import Image, ImageCms
from hre.assets import canonicalize_image, create_case, validate_asset, AssetRegistry
from hre.paths import safe_path
from hre.models import HREError, file_sha256


def image(path, size=(4,3), color=(24,80,190), **kwargs):
    Image.new('RGB',size,color).save(path, **kwargs)
    return path


def test_case_freezes_different_size_sources(tmp_path):
    a=image(tmp_path/'same.png'); before=file_sha256(a)
    b=image(tmp_path/'b.png',(7,5),(200,70,40))
    root=tmp_path/'case'
    s=create_case(a,b,{}, {'assume_srgb':True},root)
    assert [(i['width'],i['height']) for i in s['inputs']]==[(4,3),(7,5)]
    assert s['budget']['max_generations']==3 and s['revision']==0
    assert before==file_sha256(a)
    for asset in s['inputs']:validate_asset(asset,root)
    assert (root/'config.json').exists() and (root/'manifest.json').exists()


def test_missing_profile_requires_explicit_assumption(tmp_path):
    a=image(tmp_path/'a.png')
    with pytest.raises(HREError): canonicalize_image(a,tmp_path/'out.png','prediction',{})


def test_exif_rotates_and_icc_is_converted(tmp_path):
    exif=Image.Exif();exif[274]=6
    src=image(tmp_path/'a.jpg',(8,5),exif=exif,icc_profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes())
    asset=canonicalize_image(src,tmp_path/'out.png','prediction',{})
    assert (asset['width'],asset['height'])==(5,8)
    assert asset['canonicalization']['icc_converted']
    assert asset['canonicalization']['orientation_applied']
    with Image.open(tmp_path/'out.png') as im:assert im.mode=='RGB' and im.info['icc_profile']


@pytest.mark.parametrize('path',['../x','/x','a//b','a/./b','a\\b','https://x','x:ads','CON.png','a/aux','a./x','a /x'])
def test_paths_reject_unsafe(tmp_path,path):
    with pytest.raises(HREError):safe_path(tmp_path,path)


def test_paths_reject_symlink(tmp_path):
    (tmp_path/'out').mkdir();(tmp_path/'link').symlink_to(tmp_path/'out',target_is_directory=True)
    with pytest.raises(HREError):safe_path(tmp_path,'link/a.png')


def test_unknown_hdr_and_alpha_rejected(tmp_path):
    Image.new('I',(2,2),5000).save(tmp_path/'hdr.tiff')
    with pytest.raises(HREError):canonicalize_image(tmp_path/'hdr.tiff',tmp_path/'out.png','prediction',{'assume_srgb':True})
    Image.new('RGBA',(2,2),(0,0,0,0)).save(tmp_path/'alpha.png')
    with pytest.raises(HREError):canonicalize_image(tmp_path/'alpha.png',tmp_path/'out.png','prediction',{'assume_srgb':True})


def test_asset_bytes_and_original_tampering_rejected(tmp_path):
    root=tmp_path/'case';src=image(tmp_path/'a.png')
    asset=AssetRegistry(root).import_asset(src,'prediction','A',{'assume_srgb':True})
    validate_asset(asset,root)
    (root/asset['source_file']['path']).write_bytes(b'tamper')
    with pytest.raises(HREError):validate_asset(asset,root)


def test_same_filename_different_bytes_isolated(tmp_path):
    root=tmp_path/'case';(tmp_path/'one').mkdir();(tmp_path/'two').mkdir()
    a=image(tmp_path/'one'/'same.png');b=image(tmp_path/'two'/'same.png',color=(1,2,3))
    reg=AssetRegistry(root)
    aa=reg.import_asset(a,'prediction','A',{'assume_srgb':True});bb=reg.import_asset(b,'reference','B',{'assume_srgb':True})
    assert aa['source_file']['path']!=bb['source_file']['path']
    assert aa['sha256']!=bb['sha256']


def test_hdr_rgb16_tiff_rejected_without_silent_downconversion(tmp_path):
    import struct
    source=tmp_path/'rgb16.tiff'
    entries=[(256,4,1,4),(257,4,1,3),(258,3,3,122),(259,3,1,1),(262,3,1,2),(273,4,1,128),(277,3,1,3),(278,4,1,3),(279,4,1,72)]
    raw=b'II'+struct.pack('<HIH',42,8,len(entries))+b''.join(struct.pack('<HHII',*entry) for entry in entries)+struct.pack('<I',0)+struct.pack('<HHH',16,16,16)+struct.pack('<H',10000)*36
    source.write_bytes(raw)
    with pytest.raises(HREError):canonicalize_image(source,tmp_path/'c.png','prediction',{'assume_srgb':True})


def test_canonicalization_flags_cannot_lie(tmp_path):
    source=image(tmp_path/'a.png');root=tmp_path/'case'
    asset=AssetRegistry(root).import_asset(source,'prediction','A',{'assume_srgb':True})
    asset['canonicalization']['icc_converted']=True
    with pytest.raises(HREError):validate_asset(asset,root)


def test_reject_unsafe_asset_id_before_creating_files(tmp_path):
    source=image(tmp_path/'a.png');root=tmp_path/'case'
    with pytest.raises(HREError):canonicalize_image(source,root/'c.png','prediction',{'assume_srgb':True},asset_id='../escape')
    assert not (root/'c.png').exists()


def test_baseline_zero_budget_and_invalid_configuration(tmp_path):
    source=image(tmp_path/'a.png');s=create_case(source,source,{}, {'assume_srgb':True,'profile_id':'baseline'},tmp_path/'base')
    assert s['budget']['max_generations']==0 and s['workflow_state']=='CREATED'
    with pytest.raises(HREError):create_case(source,source,{}, {'assume_srgb':True,'max_generations':4},tmp_path/'bad')


def test_evidence_arrays_validate_actual_dtype_geometry_range(tmp_path):
    import numpy as np
    from hre.models import file_sha256
    np.save(tmp_path/'a.npy',np.ones((3,4),dtype=np.float32))
    a={'asset_id':'depth','path':'a.npy','sha256':file_sha256(tmp_path/'a.npy'),'role':'evidence','width':4,'height':3,'color_space':None,'evidence_format':{'kind':'array','dtype':'float32','value_range':[0,1],'coordinate_asset_id':'A'}}
    validate_asset(a,tmp_path)
    a['evidence_format']['dtype']='float64'
    with pytest.raises(HREError):validate_asset(a,tmp_path)


def test_tagged_rec2020_pq_png_cannot_assume_srgb(tmp_path):
    import struct
    from PIL import PngImagePlugin
    info=PngImagePlugin.PngInfo();info.add(b'cICP',bytes([9,16,0,1]));info.add(b'cHRM',struct.pack('>8I',31270,32900,70800,29200,17000,79700,13100,4600))
    source=image(tmp_path/'pq.png',pnginfo=info)
    with pytest.raises(HREError):canonicalize_image(source,tmp_path/'out.png','prediction',{'assume_srgb':True})


def test_canonical_pixels_must_derive_from_raw_source(tmp_path):
    from hre.assets import pixel_hash
    source=image(tmp_path/'a.png');root=tmp_path/'case'
    asset=AssetRegistry(root).import_asset(source,'prediction','A',{'assume_srgb':True})
    with Image.open(root/asset['path']) as im:icc=im.info['icc_profile']
    fake=Image.new('RGB',(asset['width'],asset['height']),(255,0,0));fake.save(root/asset['path'],icc_profile=icc)
    asset.update(sha256=file_sha256(root/asset['path']),pixel_sha256=pixel_hash(fake))
    with pytest.raises(HREError):validate_asset(asset,root)


@pytest.mark.parametrize('cap',[1,2])
def test_direct_best_of_three_cannot_lower_fixed_k(tmp_path,cap):
    source=image(tmp_path/'a.png')
    with pytest.raises(HREError):create_case(source,source,{}, {'assume_srgb':True,'profile_id':'direct_best_of_3','max_generations':cap},tmp_path/'case')


def test_unknown_canonicalizer_cannot_claim_source_relation(tmp_path):
    source=image(tmp_path/'a.png');root=tmp_path/'case';asset=AssetRegistry(root).import_asset(source,'prediction','A',{'assume_srgb':True})
    asset['canonicalization']['canonicalizer_version']='unknown_v1'
    with pytest.raises(HREError):validate_asset(asset,root)


def test_uniform_scale_validates_raw_pixels_and_frozen_policy(tmp_path):
    from hre.assets import pixel_hash
    from hre.models import canonical_json,sha256_bytes
    source=image(tmp_path/'a.png',(8,6));root=tmp_path/'case';asset=AssetRegistry(root).import_asset(source,'prediction','A',{'assume_srgb':True})
    with Image.open(root/asset['path']) as im:
        scaled=im.resize((4,3),Image.Resampling.LANCZOS);scaled.save(root/'scaled.png',icc_profile=im.info['icc_profile'])
    policy={'mode':'aspect_preserving_resize','target_width':4,'target_height':3,'interpolation':'LANCZOS','source_sha256':asset['source_file']['sha256'],'source_pixel_sha256':asset['pixel_sha256']}
    derived=copy.deepcopy(asset);derived.update(asset_id='A_scaled',path='scaled.png',width=4,height=3,sha256=file_sha256(root/'scaled.png'),pixel_sha256=pixel_hash(scaled));derived['canonicalization'].update(canonicalizer_version='hre_rgb8_uniform_scale_v1',conversion_policy_sha256=sha256_bytes(canonical_json(policy)))
    validate_asset(derived,root)
    derived['canonicalization']['conversion_policy_sha256']='0'*64
    with pytest.raises(HREError):validate_asset(derived,root)
