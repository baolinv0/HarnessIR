"""Measurements from actual pixels; never infer semantic correspondence."""
from pathlib import Path
import math
import numpy as np
from PIL import Image
from .contracts import require

def lab(rgb):
    lin=np.where(rgb<=.04045,rgb/12.92,((rgb+.055)/1.055)**2.4)
    xyz=lin@np.array([[.4124564,.3575761,.1804375],[.2126729,.7151522,.0721750],[.0193339,.1191920,.9503041]]).T
    t=xyz/np.array([.95047,1.,1.08883]);d=6/29
    f=np.where(t>d**3,np.cbrt(t),t/(3*d*d)+4/29)
    return np.stack([116*f[...,1]-16,500*(f[...,0]-f[...,1]),200*(f[...,1]-f[...,2])],axis=-1)

def measure(path,box=None):
    with Image.open(path) as im:
        im=im.convert("RGB");w,h=im.size
        if box:
            im=im.crop((math.floor(box[0]*w),math.floor(box[1]*h),math.ceil(box[2]*w),math.ceil(box[3]*h)))
        im.thumbnail((1200,1200))
        a=np.asarray(im,dtype=np.float64)/255
        flat=a.reshape(-1,3);require(len(flat)>0,"empty_region","区域没有像素")
        y=flat@np.array([.2126,.7152,.0722]);l=lab(flat)
        hi,lo=flat.max(1),flat.min(1)
        sat=np.divide(hi-lo,hi,out=np.zeros_like(hi),where=hi>0)
        histogram=np.histogram(y,bins=32,range=(0,1))[0].tolist()
        pal=im.quantize(colors=6,method=Image.Quantize.MEDIANCUT)
        colors=sorted(pal.getcolors() or [],reverse=True);p=pal.getpalette()
        palette=[{"hex":"#%02x%02x%02x"%tuple(p[n*3:n*3+3]),"weight":count/len(flat)} for count,n in colors]
        grid=a@np.array([.2126,.7152,.0722])
        local=float((np.abs(np.diff(grid,axis=0)).mean() if len(grid)>1 else 0)+(np.abs(np.diff(grid,axis=1)).mean() if grid.shape[1]>1 else 0))
        return {"width":w,"height":h,"pixels":len(flat),"mean_rgb":(flat.mean(0)*255).tolist(),
                "lab_mean":l.mean(0).tolist(),"luma_quantiles":np.quantile(y,[.01,.1,.5,.9,.99]).tolist(),
                "histogram":histogram,"palette":palette,"clipping":{"black":float((y<=1/255).mean()),"white":float((y>=254/255).mean())},
                "saturation":float(sat.mean()),"local_contrast":local,
                "L_quantiles":np.quantile(l[:,0],[.1,.5,.9]).tolist(),"sampling":"aspect-preserving thumbnail, maximum 1200 per edge"}

def collect(source,reference,regions):
    rows=[]
    for r in regions:
        rows.append({**r,"source":measure(source,r["source_box"]),"reference":measure(reference,r["reference_box"])})
    return {"source":measure(source),"reference":measure(reference),"regions":rows,
            "domain":"sRGB display attributes; B is unaligned appearance reference, not pixel GT; measurements do not establish semantic correspondence"}

def candidate_deltas(source,reference,candidate,regions):
    rows=[]
    for r in regions:
        if r.get("comparability") not in ("comparable","conditional"): continue
        a,b,c=measure(source,r["source_box"]),measure(reference,r["reference_box"]),measure(candidate,r["source_box"])
        for dim in r.get("attributes",[]):
            if dim=="brightness": before,after=abs(a["lab_mean"][0]-b["lab_mean"][0]),abs(c["lab_mean"][0]-b["lab_mean"][0])
            elif dim=="color": before,after=float(np.linalg.norm(np.array(a["lab_mean"][1:])-b["lab_mean"][1:])),float(np.linalg.norm(np.array(c["lab_mean"][1:])-b["lab_mean"][1:]))
            elif dim=="tone": before,after=float(np.abs(np.array(a["L_quantiles"])-b["L_quantiles"]).mean()),float(np.abs(np.array(c["L_quantiles"])-b["L_quantiles"]).mean())
            else: before,after=abs(a["saturation"]-b["saturation"]),abs(c["saturation"]-b["saturation"])
            rows.append({"region_id":r["id"],"attribute":dim,"before":before,"after":after,"delta":before-after,"interpretation":"descriptive only; content/geometry must be independently checked"})
    return rows
