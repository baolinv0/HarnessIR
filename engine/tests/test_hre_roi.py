import pytest
from hre.roi import compare_rois
from test_hre_stats import asset


def test_independent_halfopen_boxes(tmp_path):
    a=asset(tmp_path,'A',[[[255,0,0],[0,0,0]]]); b=asset(tmp_path,'B',[[[0,0,0],[255,0,0]]]); b['role']='reference'
    pair=dict(roi_pair_id='material',prediction=[0,0,.5,1],reference=[.5,0,1,1],coordinate_system='canonical_norm',comparability='comparable',reason='same material')
    r=compare_rois(a,b,[pair],case_root=tmp_path)['roi_pairs'][0]
    assert r['metric_delta']['mean_luma']==0 and r['metric_delta']['lab_distance']==0
    pair['comparability']='not_comparable'
    r=compare_rois(a,b,[pair],case_root=tmp_path)['roi_pairs'][0]
    assert r['metric_delta']=={} and r['status']=='not_comparable'


def test_invalid_empty_roi_not_zero(tmp_path):
    a=asset(tmp_path); b=dict(a,asset_id='B',role='reference')
    p=dict(roi_pair_id='empty',prediction=[0,0,.01,.01],reference=[0,0,1,1],coordinate_system='canonical_norm',comparability='comparable',reason='same')
    r=compare_rois(a,b,[p],case_root=tmp_path)['roi_pairs'][0]
    assert r['status']=='unknown' and r['metric_delta']=={}
    p['prediction']=[-.1,0,1,1]
    with pytest.raises(Exception): compare_rois(a,b,[p],case_root=tmp_path)
