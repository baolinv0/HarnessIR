"""Independent bilateral masks and deterministic, explicitly labelled measurements."""
import numpy as np
from .color import require, linearize, lab, digest_bytes,luminance,resolve_domain

MATERIAL_REGION_PROTOCOL='manual_material_v1'

COMPARABILITY={'comparable':1.,'partially_comparable':.25,'not_comparable':0.}

def array_hash(a):
    a=np.ascontiguousarray(a)
    return digest_bytes(str((a.shape,a.dtype.str)).encode()+a.tobytes())

def mask_valid(mask,shape):
    require(isinstance(mask,np.ndarray) and mask.shape==shape and np.isfinite(mask).all() and mask.min()>=0 and mask.max()<=1,'mask shape/range invalid')

def erode(mask,radius):
    require(type(radius) is int and 0<=radius<=32,'erosion radius')
    out=mask.copy()
    for _ in range(radius):
        p=np.pad(out,1,constant_values=False)
        out=np.logical_and.reduce([p[y:y+out.shape[0],x:x+out.shape[1]] for y in range(3) for x in range(3)])
    return out

def build_pairs(a,b,specs,masks,*,edge=1,min_pixels=32,min_coverage=.4,max_regions=6):
    require(type(max_regions) is int and max_regions in (6,9),'region cap must be exactly 6 or 9')
    require(1<=len(specs)<=max_regions,f'need 1..{max_regions} bilateral regions')
    result=[];seen=set()
    for p in specs:
        require(set(p)=={'id','a_mask','b_mask','semantic','comparability','reasons','provenance'},'region fields')
        require(isinstance(p['id'],str) and p['id'] and p['id'] not in seen,'duplicate/empty region');seen.add(p['id'])
        require(p['comparability'] in COMPARABILITY and p['reasons'] and p['provenance'] in ('automatic','manual_diagnostic'),'comparability needs evidence/provenance')
        row=dict(p);supports={};counts={};coverage={}
        for role,image in [('a',a),('b',b)]:
            mask=masks[p[role+'_mask']];mask_valid(mask,image.shape[:2])
            binary=mask>=.5;support=erode(binary,edge)
            # Freeze clipping exclusions ON INPUT; C is measured on identical support.
            support &= (image.min(-1)>1/65535)&(image.max(-1)<65534/65535)
            supports[role]=support;counts[role]=int(support.sum())
            coverage[role]=float(support.sum()/max(1,binary.sum()))
        if min(counts.values())<min_pixels or min(coverage.values())<min_coverage:
            row['comparability']='not_comparable';row['reasons']=list(row['reasons'])+['insufficient frozen interior support']
        row.update(supports=supports,counts=counts,coverage=coverage,exclusion_rule=dict(edge=edge,clip=(1/65535,65534/65535),min_pixels=min_pixels,min_coverage=min_coverage))
        result.append(row)
    return result

def measure(rgb,support,domain=None):
    domain=resolve_domain(domain)
    require(support.shape==rgb.shape[:2] and support.dtype==bool and support.any(),'empty/invalid evaluation support')
    x=rgb[support];y=luminance(x,domain);l=lab(x,domain);chroma=np.linalg.norm(l[:,1:],axis=1)
    out={'pixels':int(len(x)),'clip.low':float((x.min(1)<=1/65535).mean()),'clip.high':float((x.max(1)>=65534/65535).mean())}
    for name,v in [('Y_linear',y),('Lab_D65.L',l[:,0]),('Lab_D65.a',l[:,1]),('Lab_D65.b',l[:,2]),('Lab_D65.C',chroma)]:
        for q,value in zip((10,25,50,75,90),np.quantile(v,[.1,.25,.5,.75,.9])):out[f'{name}.P{q}']=float(value)
        out[name+'.IQR']=float(np.quantile(v,.75)-np.quantile(v,.25))
    # Fixed luminance strata, never move bins to improve an output score.
    for name,lo,hi in [('shadow',0,.1),('midtone',.1,.6),('highlight',.6,1.00001)]:
        s=(y>=lo)&(y<hi);out[name+'.pixels']=int(s.sum())
        if s.any():
            for i,c in enumerate('Lab'):out[name+'.Lab_D65.'+c]=float(np.median(l[s,i]))
    return out

def extract(a,b,pairs,domain_a=None,domain_b=None):
    observations={};domains={'a':resolve_domain(domain_a),'b':resolve_domain(domain_b)}
    for role,image in [('a',a),('b',b)]:
        for p in pairs:
            if p['comparability']=='not_comparable':continue
            for metric,value in measure(image,p['supports'][role],domains[role]).items():
                if metric=='pixels' or metric.endswith('.pixels'):continue
                key=f'{role}:{p["id"]}:{metric}'
                observations[key]=dict(region=p['id'],role=role,metric=metric,value=value,domain='sRGB SDR / linear Y / Lab D65' if domains[role].id=='srgb' else 'display_p3 nominal SDR / linear Y / Lab D65',support_hash=array_hash(p['supports'][role]))
    return observations

def pair_manifest(pairs):
    return [{**{k:v for k,v in p.items() if k!='supports'},'support_hashes':{k:array_hash(v) for k,v in p['supports'].items()}} for p in pairs]
