"""Independent image-coordinate ROI comparison; no matching or spatial transfer."""
from pathlib import Path
import numpy as np
from .stats import _pixels, _metrics, METRIC_VERSION


def _box_mask(shape: tuple, box: list) -> np.ndarray:
    from .models import HREError
    if len(box) != 4 or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not np.isfinite(x) for x in box):
        raise HREError('invalid_roi','ROI must contain four finite normalized numbers')
    x0,y0,x1,y1=box
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise HREError('invalid_roi','ROI must be an ordered normalized half-open box')
    h,w=shape[:2]
    x=(np.arange(w)+.5)/w; y=(np.arange(h)+.5)/h
    return ((y >= y0)&(y < y1))[:,None] & ((x >= x0)&(x < x1))[None,:]


def compare_rois(prediction: dict, reference: dict, roi_pairs: list[dict], *, case_root: Path) -> dict:
    from .models import HREError
    a=_pixels(prediction,case_root); b=_pixels(reference,case_root)
    pairs=[]; seen=set()
    for pair in roi_pairs:
        pid=pair['roi_pair_id']
        if pid in seen: raise HREError('duplicate_roi','ROI pair IDs must be unique')
        seen.add(pid)
        if pair.get('coordinate_system') != 'canonical_norm': raise HREError('invalid_roi','ROI coordinates must be canonical_norm')
        status=pair.get('comparability','unknown')
        if status not in ('comparable','partly_comparable','not_comparable','unknown'): raise HREError('invalid_roi','invalid comparability')
        ma=_box_mask(a.shape,pair['prediction']); mb=_box_mask(b.shape,pair['reference'])
        reason=pair.get('reason')
        reasons=[reason] if isinstance(reason,str) and reason else list(pair.get('reasons',[]))
        r=dict(roi_pair_id=pid,prediction_asset_id=prediction['asset_id'],reference_asset_id=reference['asset_id'],status=status,
               reasons=reasons,prediction_region_id=pid+'_prediction',reference_region_id=pid+'_reference',observations=[],metric_delta={})
        if not ma.any() or not mb.any():
            r['status']='unknown';r['reasons'].append('empty ROI is unavailable')
        elif status in ('comparable','partly_comparable'):
            aa=_metrics(a[ma]);bb=_metrics(b[mb])
            r['metric_delta']={k:bb[k]-aa[k] for k in aa if isinstance(aa[k],float)}
            for key in ('mean_rgb','mean_lab'):
                for suffix,av,bv in zip(('r','g','b') if key=='mean_rgb' else ('L','a','b'),aa[key],bb[key]):
                    r['metric_delta'][key+'_'+suffix]=bv-av
            r['metric_delta']['lab_distance']=float(np.linalg.norm(np.asarray(aa['mean_lab'])-bb['mean_lab']))
            r['observations']=[f"prediction sample_count={int(ma.sum())}",f"reference sample_count={int(mb.sum())}", 'metric_delta is reference minus prediction; descriptive display statistics']
        pairs.append(r)
    if not pairs: raise HREError('missing_roi','ROI_COMPARE requires at least one ROI pair')
    return dict(metric_version=METRIC_VERSION,roi_pairs=pairs)
