import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def test_ocr_retains_text_polygon_and_separate_confidences():
    from preprocessing.adapters.ocr import normalize_ocr
    view = {"id":"full","grid_shape":[50,100],"view_to_canonical":[[.01,0,0],[0,.02,0],[0,0,1]],"kind":"full_frame"}
    result = normalize_ocr([{"id":"a","polygon":[[10,10],[30,10],[30,20],[10,20]],"text":"错识也保留","det_score":.92,"rec_score":.3}],view)
    assert result[0]["text"] == "错识也保留"
    assert result[0]["bbox_norm"] == pytest.approx([.1,.2,.3,.4])
    assert result[0]["detection_confidence"] == .92
    assert result[0]["recognition_confidence"] == .3
    assert result[0]["ambiguous"] is True


def test_sdk_array_association_rejects_inconsistent_lengths():
    from preprocessing.adapters.ocr import paddle_detection_records
    with pytest.raises(ValueError, match="association"):
        paddle_detection_records({"dt_polys":[[[0,0],[1,0],[1,1]]],"dt_scores":[]})
    assert paddle_detection_records({"dt_polys":[],"dt_scores":[]}) == []
