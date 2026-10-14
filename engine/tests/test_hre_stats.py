from pathlib import Path
import hashlib
import numpy as np
from PIL import Image, ImageCms
import pytest
from hre.stats import compute_stats


def asset(root, name='A', rgb=None):
    rgb = np.asarray(rgb if rgb is not None else [[[255,0,0],[0,255,0]],[[0,0,0],[255,255,255]]], dtype=np.uint8)
    from hre.assets import canonicalize_image
    source=root/(name+'_original.png')
    Image.fromarray(rgb).save(source,icc_profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes())
    return canonicalize_image(source,root/(name+'.png'),'prediction',{'case_root':root,'assume_srgb':False},asset_id=name)



def test_display_formula_and_lab(tmp_path):
    a=asset(tmp_path); r=compute_stats(a,case_root=tmp_path)['regions'][0]
    m=r['metrics']; assert r['sample_count']==4
    assert m['mean_luma']==pytest.approx((.2126+.7152+1)/4)
    assert m['p10_luma']==pytest.approx(.06378)
    assert m['p50_luma']==pytest.approx(.4639)
    assert m['p90_luma']==pytest.approx(.91456)
    assert m['shadow_fraction']==.25 and m['highlight_fraction']==.25
    assert m['mean_saturation']==.5
    assert m['mean_rgb']==[.5,.5,.25]
    red=compute_stats(asset(tmp_path,'red',[[[255,0,0]]]),case_root=tmp_path)['regions'][0]['metrics']
    assert red['mean_lab']==pytest.approx([53.2408,80.0925,67.2032],abs=.001)


def test_mask_count_empty_and_wrong_shape(tmp_path):
    a=asset(tmp_path); p=tmp_path/'mask.npy'; np.save(p, np.array([[1,0],[0,0]],dtype=bool))
    r=compute_stats(a,p,case_root=tmp_path)['regions'][0]
    assert r['sample_count']==1 and r['metrics']['mean_luma']==pytest.approx(.2126)
    np.save(p,np.zeros((2,2),dtype=bool))
    with pytest.raises(Exception,match='empty'): compute_stats(a,p,case_root=tmp_path)
    np.save(p,np.ones((1,2),dtype=bool))
    with pytest.raises(Exception,match='shape'): compute_stats(a,p,case_root=tmp_path)
