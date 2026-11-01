"""Native-coordinate mask preparation, independent of frozen evaluation support."""
import numpy as np
from .color import require,linearize,luminance,resolve_domain
from .evidence import mask_valid,array_hash

def prepare_mask(raw,source,*,feather_native=0.,density=1.,luminance_range=None,domain=None):
    domain=resolve_domain(domain)
    mask_valid(raw,source.shape[:2])
    require(type(feather_native) in (int,float) and np.isfinite(feather_native) and 0<=feather_native<=128,'feather range')
    require(type(density) in (int,float) and np.isfinite(density) and 0<=density<=1,'density range')
    # HarnessIR extension: feather once in native pixels, then resize exact effective mask.
    # density means effect coverage strength here; does not map to PhotoCraft's mask density slider.
    out=raw.astype(float).copy()
    if feather_native:
        radius=max(1,int(np.ceil(3*feather_native)));x=np.arange(-radius,radius+1)
        kernel=np.exp(-.5*(x/feather_native)**2);kernel/=kernel.sum()
        for axis in (0,1):
            pad=[(0,0),(0,0)];pad[axis]=(radius,radius)
            padded=np.pad(out,pad,mode='edge');out=np.apply_along_axis(lambda row:np.convolve(row,kernel,mode='valid'),axis,padded)
    if luminance_range is not None:
        require(isinstance(luminance_range,list) and len(luminance_range)==4 and all(type(v) in (int,float) and np.isfinite(v) for v in luminance_range),'luminance window')
        lo,full_lo,full_hi,hi=luminance_range;require(0<=lo<full_lo<=full_hi<hi<=1,'ordered luminance window')
        y=luminance(source,domain)
        out*=np.minimum(np.clip((y-lo)/(full_lo-lo),0,1),np.clip((hi-y)/(hi-full_hi),0,1))
    out*=density
    return out,dict(raw_hash=array_hash(raw),effective_hash=array_hash(out),feather_native=feather_native,density=density,luminance_range=luminance_range,implementation='HarnessIR coverage extension; PhotoCraft mask density=1 feather=0',**({'color_domain':domain.identity} if domain.id!='srgb' else {}))
