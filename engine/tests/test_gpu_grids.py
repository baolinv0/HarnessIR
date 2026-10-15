"""Synthetic bounded-file checks; not real model acceptance."""
import tempfile
from pathlib import Path
import numpy as np
import pytest
from hir_manual.local_evidence import _grid


def test_original_size_float32_above_old_50mib_limit(tmp_path):
    path=tmp_path/'depth.npy'
    mmap=np.lib.format.open_memmap(path, mode='w+', dtype='float32', shape=(4000,4000))
    mmap[0,0]=1.25
    mmap.flush()
    del mmap
    result=_grid(tmp_path,'depth.npy')
    assert isinstance(result,np.memmap) and result.shape==(4000,4000)
    assert result[0,0]==1.25
    del result


@pytest.mark.parametrize('dtype',['object','complex64','S100'])
def test_prohibited_grid_dtypes(tmp_path,dtype):
    np.save(tmp_path/'bad.npy',np.zeros((2,2),dtype=dtype))
    with pytest.raises(ValueError):_grid(tmp_path,'bad.npy')


def test_native_numeric_float64_remains_readable(tmp_path):
    np.save(tmp_path/'native.npy',np.zeros((2,2),dtype='float64'))
    assert _grid(tmp_path,'native.npy').dtype==np.float64


def test_truncated_grid_rejected_before_mapping(tmp_path):
    path=tmp_path/'bad.npy'
    np.save(path,np.zeros((2,2),dtype='float32'))
    path.write_bytes(path.read_bytes()[:-1])
    with pytest.raises(ValueError):_grid(tmp_path,'bad.npy')
