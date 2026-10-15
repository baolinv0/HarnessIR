import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def test_native_landmark_order_and_tile_transform():
    from preprocessing.adapters.face import normalize_faces
    view = {"id": "tile", "grid_shape": [100, 100], "view_to_canonical": [[.001,0,.4],[0,.002,.2],[0,0,1]], "kind": "tile"}
    points = [[10,20],[30,20],[20,30],[12,40],[28,40]]
    result = normalize_faces([{"id":"f", "bbox":[0,10,50,60],"score":.9,"landmarks5":points}], view, (1000,500))
    assert result[0]["bbox_norm"] == pytest.approx([.4,.22,.45,.32])
    assert result[0]["landmarks5_norm"][0] == pytest.approx([.41,.24])
    assert result[0]["landmarks5_norm"][1] == pytest.approx([.43,.24])
    assert result[0]["landmark_order"] == "eye_0,eye_1,nose,mouth_0,mouth_1 (native SCRFD order)"
    assert result[0]["source_face_pixels"] == [50,50]


def test_missing_landmarks_are_explicit_null_and_empty_success():
    from preprocessing.adapters.face import normalize_faces
    view = {"id":"full","grid_shape":[100,100],"view_to_canonical":[[.01,0,0],[0,.01,0],[0,0,1]],"kind":"full_frame"}
    assert normalize_faces([],view,(100,100)) == []
    assert normalize_faces([{"id":"f","bbox":[1,2,10,20],"score":.5,"landmarks5":None}],view,(100,100))[0]["landmarks5_norm"] is None
    with pytest.raises(ValueError,match="five"):
        normalize_faces([{"id":"f","bbox":[1,2,10,20],"score":.5,"landmarks5":[[1,2]]}],view,(100,100))
