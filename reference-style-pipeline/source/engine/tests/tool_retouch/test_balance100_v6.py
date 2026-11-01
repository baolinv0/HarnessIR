"""Small actual-worker balance100 capability tests, not photo quality claims."""
import hashlib,json,os,subprocess,tempfile
from pathlib import Path
import numpy as np
import pytest
from hre.tool_retouch.backend import PhotoCraftAdapter,PROTOCOL
from hre.tool_retouch.planner import TOOLS
from hre.tool_retouch.color import display_p3_domain

ROOT=Path('/workspace/shared/retouch_rgb_runtime')
WORKER=Path(os.environ['V6_WORKER'])
OLD_WORKER=ROOT/'p3_controller_v5/target/release/harnessir-photocraft-worker'
PROFILE=(ROOT/'p3_material_controller_v6/source/engine/photocraft_worker/profiles/d77bd8c4008f1813dca5e67762872667734f796a188b52123db65fd5fda262a9.icc').read_bytes()
V6_PROTOCOL='harnessir_photocraft_channels_v6'
VERSION='p3-material-controller-v6'


def render(red=0.,blue=0.,mask=None,worker=WORKER,protocol=V6_PROTOCOL,tool='balance',values=None):
 source=np.repeat(np.repeat(np.linspace(0,1,129)[None,:,None],3,axis=2),5,axis=0)
 q=np.rint(source*65535).astype('<u2')
 with tempfile.TemporaryDirectory(prefix='balance100-v6-test-') as directory:
  root=Path(directory);q.tofile(root/'source.u16');(root/'working.icc').write_bytes(PROFILE)
  if mask is not None:np.asarray(mask,dtype='<f4').tofile(root/'mask0.f32')
  req={'protocol':protocol,'width':129,'height':5,'domain_id':'display_p3','working_icc_sha256':hashlib.sha256(PROFILE).hexdigest(),'operations':[{'tool':tool,'mask':mask is not None,'values':values if values is not None else {'red':red,'blue':blue}}]}
  (root/'request.json').write_text(json.dumps(req))
  p=subprocess.run([str(worker)],cwd=root,capture_output=True,text=True,timeout=30,env={'RAYON_NUM_THREADS':'1','LC_ALL':'C'})
  out=np.fromfile(root/'output.u16','<u2').reshape(q.shape) if (root/'output.u16').exists() else None
  return p,out,q


def test_registry_changes_only_balance_bounds():
 assert TOOLS['balance']=={'red':(-100.,100.,0.,.15625),'blue':(-100.,100.,0.,.15625)}
 assert PROTOCOL==V6_PROTOCOL


def test_worker_capability_and_adapter_identity_v6():
 p=subprocess.run([str(WORKER),'--capabilities'],capture_output=True,text=True,check=True);caps=json.loads(p.stdout)
 assert caps['protocol']==V6_PROTOCOL and caps['adapter_version']==VERSION
 assert caps['balance_parameter_range']==[-100,100]
 assert set(caps['tools'])=={'balance','exposure','curve','gamma','saturation','brightness_contrast'}
 b=PhotoCraftAdapter(WORKER,hashlib.sha256(WORKER.read_bytes()).hexdigest(),domain=display_p3_domain(PROFILE))
 assert b.identity['protocol']==V6_PROTOCOL and b.identity['adapter_version']==VERSION


@pytest.mark.parametrize('red,blue',[(0.,0.),(100.,0.),(-100.,0.),(0.,100.),(0.,-100.),(100.,-100.),(-100.,100.),(100.,100.),(-100.,-100.)])
def test_identity_boundaries_monotonic_range_clipping(red,blue):
 p,out,q=render(red,blue);assert p.returncode==0,p.stderr
 assert np.isfinite(out).all() and out.dtype==np.uint16
 assert np.min(np.diff(out.astype(int),axis=1))>=-2
 assert np.all(out[:,0]==0) and np.all(out[:,-1]==65535)
 # Interior ramp values must not silently become clipped at the legal extremes.
 assert np.all((out[:,1:-1]>0)&(out[:,1:-1]<65535))
 if red==blue==0:assert np.max(abs(out.astype(int)-q.astype(int)))<=2
 if red>blue:assert out[0,64,0]>out[0,64,2]
 if red<blue:assert out[0,64,0]<out[0,64,2]
 receipt=json.loads(p.stdout);assert receipt['protocol']==V6_PROTOCOL and receipt['adapter_version']==VERSION


@pytest.mark.parametrize('axis',['red','blue'])
def test_slider_direction_is_monotonic_at_fixed_midpoint(axis):
 measured=[]
 for value in (-100.,-50.,0.,50.,100.):
  p,out,_=render(**{axis:value});assert p.returncode==0,p.stderr
  measured.append(int(out[0,64,0 if axis=='red' else 2]))
 assert all(a<b for a,b in zip(measured,measured[1:]))


@pytest.mark.parametrize('red,blue',[(100.001,0.),(-100.001,0.),(0.,100.001),(0.,-100.001)])
def test_outside_legal_range_rejected_not_silently_clamped(red,blue):
 p,out,_=render(red,blue)
 assert p.returncode==2 and out is None and 'parameter bounds' in p.stderr


def test_extreme_balance_actual_mask_locality_and_soft_interpolation():
 zero=np.zeros((5,129));one=np.ones((5,129));local=zero.copy();local[:,32:96]=1
 soft=np.tile(np.linspace(0,1,129),(5,1));outs=[]
 for mask in (zero,one,local,soft):
  p,out,q=render(100.,-100.,mask);assert p.returncode==0,p.stderr;outs.append(out.astype(float))
 z,o,l,s=outs
 assert np.max(abs(z-q))<=2
 assert np.max(abs(l[local==0]-q[local==0]))<=2
 assert np.max(abs(l[local==1]-o[local==1]))<=2
 assert np.max(abs(s-(z+(o-z)*soft[...,None])))<=4


@pytest.mark.parametrize('tool,values',[('exposure',{'ev':.25}),('curve',{'mid':144.}),('balance',{'red':40.,'blue':-40.}),('gamma',{'gamma':1.3}),('saturation',{'amount':15.}),('brightness_contrast',{'brightness':15.,'contrast':10.})])
def test_old_legal_operations_byte_identical_to_frozen_v5(tool,values):
 p,old,_=render(worker=OLD_WORKER,protocol='harnessir_photocraft_channels_v5',tool=tool,values=values);assert p.returncode==0,p.stderr
 p,new,_=render(tool=tool,values=values);assert p.returncode==0,p.stderr
 assert np.array_equal(old,new)
