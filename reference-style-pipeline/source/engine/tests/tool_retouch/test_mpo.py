"""Primary SDR frame only; auxiliary MPO frames must not become HDR/linear inputs."""
import hashlib
import numpy as np
import pytest
from PIL import Image,ImageOps
from hre.tool_retouch.color import ColorContext,srgb_profile

@pytest.mark.parametrize('count',[2,8])
def test_mpo_primary_orientation_profile_and_auxiliary_isolation(tmp_path,count,monkeypatch):
    p=tmp_path/'iphone.jpg';primary=Image.new('RGB',(20,12),(80,130,180));aux=Image.new('RGB',(20,12),(255,0,0))
    exif=Image.Exif();exif[274]=8
    primary.save(p,format='MPO',save_all=True,append_images=[aux]*(count-1),icc_profile=srgb_profile(),exif=exif,quality=100,subsampling=0)
    original=p.read_bytes();im=Image.open(p);assert im.format=='MPO' and im.n_frames==count
    visits=[];seek=im.seek
    def tracked(index):visits.append(index);return seek(index)
    im.seek=tracked;monkeypatch.setattr(Image,'open',lambda *args,**kwargs:im)
    pixels,context=ColorContext.load(p)
    assert context.source_format=='MPO' and context.frame_count==count and context.frame_index==0
    assert context.orientation==8 and context.native_size==(12,20) and pixels.shape==(20,12,3)
    assert context.source_icc_sha256==hashlib.sha256(srgb_profile()).hexdigest()
    assert context.source_hash==hashlib.sha256(original).hexdigest() and p.read_bytes()==original
    assert context.frame_policy=='primary_frame_0_SDR_no_HDR_composition'
    assert not any(i!=0 for i in visits) and pixels[...,2].mean()>pixels[...,0].mean()

def test_mpo_oversized_frame_directory_rejected(tmp_path):
    p=tmp_path/'too-many.jpg';im=Image.new('RGB',(4,4))
    im.save(p,format='MPO',save_all=True,append_images=[im]*64,icc_profile=srgb_profile())
    with pytest.raises(ValueError,match='MPO frame count'):ColorContext.load(p)

def test_mpo_non_rgb_primary_rejected(tmp_path):
    p=tmp_path/'cmyk.jpg';im=Image.new('CMYK',(8,8))
    im.save(p,format='MPO',save_all=True,append_images=[im])
    with pytest.raises(ValueError,match='opaque RGB|malformed MPO'):ColorContext.load(p,assume_srgb=True)


def test_malformed_mpo_is_not_silently_treated_as_jpeg(tmp_path):
    p=tmp_path/'broken.jpg';im=Image.new('RGB',(8,8))
    im.save(p,format='MPO',save_all=True,append_images=[im],icc_profile=srgb_profile())
    raw=p.read_bytes();assert b'MPF\0II*\0' in raw
    p.write_bytes(raw.replace(b'MPF\0II*\0',b'MPF\0XX*\0',1))
    with pytest.raises((ValueError,SyntaxError,OSError)):ColorContext.load(p)
