"""Frozen display-attribute diagnostics; no pixel alignment of B or quality selection."""
from pathlib import Path
import numpy as np
from PIL import Image
from .models import HREError
from .roi import _box_mask
from .masks import checked_file, validate_mask, require

EVALUATOR_VERSION='reference_attributes_v2_20261015_r2'
NEAR_ZERO=1e-4
DIMENSIONS={'brightness','color','tone','saturation'}


def region_mask(shape, region, root):
    require(isinstance(region,dict),'invalid_roi','Explicit independent region required')
    kind=region.get('kind')
    if kind=='box':
        require(set(region)=={'kind','box'},'invalid_roi','Unknown box fields')
        return _box_mask(shape,region['box'])
    if kind=='polygon':
        require(set(region)=={'kind','points'},'invalid_roi','Unknown polygon fields')
        points=region['points'];require(isinstance(points,list) and len(points)>=3,'invalid_roi','Polygon needs 3 vertices')
        for p in points:
            require(isinstance(p,list) and len(p)==2 and all(type(v) in (int,float) and np.isfinite(v) and 0<=v<=1 for v in p),'invalid_roi','Normalized polygon coordinates required')
        # Pixel-centre ray crossing; matches half-open box sampling semantics.
        h,w=shape[:2];inside=np.zeros((h,w),dtype=bool)
        for start in range(0,h,128):
            stop=min(h,start+128);x,y=np.meshgrid((np.arange(w)+.5)/w,(np.arange(start,stop)+.5)/h)
            for p,q in zip(points,points[1:]+points[:1]):
                if p[1]!=q[1]:inside[start:stop]^=((p[1]>y)!=(q[1]>y)) & (x < (q[0]-p[0])*(y-p[1])/(q[1]-p[1])+p[0])
        return inside
    if kind=='mask':
        require(set(region)=={'kind','path','sha256'},'invalid_roi','Unknown mask region fields')
        values=np.load(checked_file(root,{k:region[k] for k in ('path','sha256')}),allow_pickle=False)
        require(values.dtype==np.uint8 and values.shape==tuple(shape[:2]) and set(np.unique(values))<={0,1},'invalid_roi','ROI mask must be binary and source sized')
        return values.astype(bool)
    raise HREError('invalid_roi','Use independent box/polygon/mask regions')


def _rgb8(asset,root):
    from .assets import validate_asset
    from .paths import safe_path
    validate_asset(asset,Path(root))
    require(asset['color_space']=='sRGB','invalid_color_space','Canonical sRGB required')
    with Image.open(safe_path(Path(root),asset['path'],must_exist=True)) as image:
        require(image.mode=='RGB','invalid_image_mode','Canonical RGB8 required')
        return np.asarray(image,dtype=np.uint8)


def _unit(values):
    x=np.asarray(values,dtype=np.float64)
    if np.asarray(values).dtype==np.uint8:x/=255
    require(np.isfinite(x).all() and x.min()>=0 and x.max()<=1,'invalid_pixels','RGB8 or finite normalized display pixels required')
    return x


def _lab(rgb):
    lin=np.where(rgb<=.04045,rgb/12.92,((rgb+.055)/1.055)**2.4)
    xyz=lin @ np.array([[.4124564,.3575761,.1804375],[.2126729,.7151522,.0721750],[.0193339,.1191920,.9503041]]).T
    t=xyz/np.array([.95047,1.,1.08883]);d=6/29;f=np.where(t>d**3,np.cbrt(t),t/(3*d*d)+4/29)
    return np.stack([116*f[...,1]-16,500*(f[...,0]-f[...,1]),200*(f[...,1]-f[...,2])],axis=-1)


def display_attributes(rgb):
    """Bounded conversion; retain only 1D float32 L*/Y-prime quantile samples.

    All frozen pixels are used, without resizing or sampling. Sums accumulate in
    float64; quantiles interpolate the full float32 display-statistic arrays.
    """
    pixels=np.asarray(rgb)
    require(pixels.ndim>=2 and pixels.shape[-1]==3 and pixels.size>0,'empty_roi','Nonempty RGB ROI required')
    pixels=pixels.reshape(-1,3);n=len(pixels);lightness=np.empty(n,dtype=np.float32);luma=np.empty(n,dtype=np.float32)
    total_L=0.;total_ab=np.zeros(2);total_sat=0.;channel_low=channel_high=luma_low=luma_high=0
    for start in range(0,n,65536):
        stop=min(n,start+65536);p=_unit(pixels[start:stop]);lab=_lab(p)
        yp=p @ np.array([.2126,.7152,.0722]);lightness[start:stop]=lab[:,0];luma[start:stop]=yp
        total_L+=float(lab[:,0].sum());total_ab+=lab[:,1:].sum(axis=0)
        hi,lo=p.max(axis=1),p.min(axis=1)
        total_sat+=float(np.divide(hi-lo,hi,out=np.zeros_like(hi),where=hi!=0).sum())
        channel_low+=int((lo<=1/255).sum());channel_high+=int((hi>=254/255).sum())
        luma_low+=int((yp<=1/255).sum());luma_high+=int((yp>=254/255).sum())
    quantiles=np.quantile(lightness,[.1,.5,.9]).tolist()
    return dict(L_mean=total_L/n,L_median=quantiles[1],L_quantiles=quantiles,ab_mean=(total_ab/n).tolist(),
                Yprime_quantiles=np.quantile(luma,[.1,.5,.9]).tolist(),saturation_mean=total_sat/n,
                channel_any_low_endpoint_fraction=channel_low/n,channel_any_high_endpoint_fraction=channel_high/n,
                display_luma_low_endpoint_fraction=luma_low/n,display_luma_high_endpoint_fraction=luma_high/n)


def _distance(x,y,dimension):
    if dimension=='brightness':return abs(x['L_mean']-y['L_mean'])
    if dimension=='color':return float(np.linalg.norm(np.asarray(x['ab_mean'])-y['ab_mean']))
    if dimension=='tone':return float(np.mean(np.abs(np.asarray(x['L_quantiles'])-y['L_quantiles'])))
    return abs(x['saturation_mean']-y['saturation_mean'])


def _spill(a,c,target):
    target=np.asarray(target,dtype=bool);outside_count=int(target.size-np.count_nonzero(target))
    if not outside_count:return dict(status='not_assessable',reason='No non-target pixels')
    L_sum=ab_sum=boundary_sum=0.;boundary_count=0;h=a.shape[0]
    for start in range(0,h,128):
        stop=min(h,start+128);end=min(h,stop+1);height=stop-start
        la,lc=_lab(_unit(a[start:end])),_lab(_unit(c[start:end]));mask=target[start:end];outside=~mask[:height]
        L_sum+=float(np.abs(lc[:height,:,0]-la[:height,:,0])[outside].sum())
        ab_sum+=float(np.linalg.norm(lc[:height,:,1:]-la[:height,:,1:],axis=2)[outside].sum())
        for axis in (0,1):
            ma=mask if axis==0 else mask[:height];aa=la[:,:,0] if axis==0 else la[:height,:,0];cc=lc[:,:,0] if axis==0 else lc[:height,:,0]
            cross=np.diff(ma.astype(np.int8),axis=axis)!=0
            delta=np.abs(np.abs(np.diff(cc,axis=axis))-np.abs(np.diff(aa,axis=axis)))
            boundary_sum+=float(delta[cross].sum());boundary_count+=int(cross.sum())
    return dict(status='measured',outside_area=outside_count,outside_L_mean_absolute_change=L_sum/outside_count,
                outside_ab_mean_distance=ab_sum/outside_count,
                boundary_L_change_proxy=boundary_sum/boundary_count if boundary_count else None,
                interpretation='Descriptive spatial change only; neither hallucination detector nor automatic rejection')


def evaluate_reference(prediction,reference,candidate,roi_pairs,*,case_root,geometry_status,content_status,
                       eval_mask=None,task_scope='global'):
    root=Path(case_root);a=_rgb8(prediction,root);b=_rgb8(reference,root)
    c=_rgb8(candidate,root) if candidate else None
    valid=geometry_status=='pass' and content_status=='pass' and c is not None and c.shape==a.shape
    rows=[];seen=set()
    for p in roi_pairs:
        pid=p['roi_pair_id'];require(pid not in seen,'duplicate_roi','Duplicate frozen ROI');seen.add(pid)
        dims=p['dimensions'];require(dims and set(dims)<=DIMENSIONS and len(set(dims))==len(dims),'invalid_roi','Unknown or repeated target attribute')
        ma=region_mask(a.shape,p['prediction'],root);mb=region_mask(b.shape,p['reference'],root)
        row=dict(roi_pair_id=pid,status='not_assessable',reasons=list(p['reasons']),areas={'A':int(ma.sum()),'B':int(mb.sum()),'C':int(ma.sum()) if valid else None},stats=None,attributes=None)
        if not valid:row['reasons'].append('A/C geometry or content unverified/failed, or candidate missing')
        elif p['comparability']!='comparable':row['reasons'].append('ROI comparability is not fully established')
        elif not ma.any() or not mb.any():row['reasons'].append('empty ROI')
        else:
            aa,bb,cc=display_attributes(a[ma]),display_attributes(b[mb]),display_attributes(c[ma]);attrs={}
            for dim in dims:
                before,after=_distance(aa,bb,dim),_distance(cc,bb,dim)
                attrs[dim]=dict(before=before,after=after,delta=before-after,relative_improvement=(before-after)/before if before>NEAR_ZERO else None,
                                status='near_zero_baseline' if before<=NEAR_ZERO else 'measured')
            row.update(status='measured',stats={'A':aa,'B':bb,'C':cc},attributes=attrs)
        rows.append(row)
    spill=None
    if task_scope=='local' and eval_mask is not None and valid:
        require(eval_mask['purpose']=='EVAL_MASK','mask_binding','Spill requires independently named EVAL_MASK')
        spill=_spill(a,c,validate_mask(root,eval_mask,prediction))
    return dict(schema_version='reference_evaluation_v2',evaluator_version=EVALUATOR_VERSION,near_zero=NEAR_ZERO,
                per_roi=rows,spill=spill,geometry_status=geometry_status,content_status=content_status,
                n_evaluable=sum(r['status']=='measured' for r in rows),aggregate_score=None,
                limitations=['B is not pixel ground truth. Region mean chromaticity is not pixelwise DeltaE00.',
                             'Attribute changes do not establish joint success or absence of invented content.'])
