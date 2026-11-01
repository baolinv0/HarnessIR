import numpy as np
import pytest
from hre.tool_retouch.color import encode_png16, read_png16, linearize, encode_srgb
from hre.tool_retouch.evidence import build_pairs, measure
from hre.tool_retouch.contracts import FrozenContract
from hre.tool_retouch.planner import validate_plan


def test_png16_roundtrip(tmp_path):
    x=np.linspace(0,1,120*3).reshape(10,12,3)
    p=tmp_path/'x.png'; encode_png16(p,x)
    y,meta=read_png16(p)
    assert y.shape==x.shape and meta['bit_depth']==16 and meta['icc_sha256']
    assert np.max(np.abs(y-x))<=.5/65535+1e-8


def test_transfer_roundtrip():
    x=np.linspace(0,1,1001)
    assert np.max(abs(encode_srgb(linearize(x))-x))<1e-12


def test_measure_is_linear_and_deterministic():
    x=np.full((12,12,3),.5)
    m=measure(x,np.ones((12,12),bool))
    assert m['Y_linear.P50']==pytest.approx(.21404114)
    assert m==measure(x,np.ones((12,12),bool))


def test_plan_rejects_commands():
    with pytest.raises(ValueError): validate_plan({'commands':['file.open']}, {'targets':[]}, {})


def test_contract_detects_mutation():
    c=FrozenContract.freeze({'targets':[], 'roi':{'a':[1]}})
    d=c.data;d['roi']['a'][0]=2
    assert c.data['roi']['a']==[1]
    with pytest.raises(ValueError): FrozenContract(c.payload+' ', c.sha256).verify()
