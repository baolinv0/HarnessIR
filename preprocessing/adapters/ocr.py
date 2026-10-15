import numpy as np

from .common import points_to_canonical, score


def normalize_ocr(records,view,ambiguous_below=.5):
    result=[]
    ids=set()
    for record in records:
        if record["id"] in ids:
            raise ValueError("duplicate native OCR id")
        ids.add(record["id"])
        if len(record["polygon"])<3:
            raise ValueError("OCR polygon needs at least three points")
        polygon=points_to_canonical(record["polygon"],view)
        array=np.asarray(polygon)
        box=[*array.min(axis=0),*array.max(axis=0)]
        if box[2]<=box[0] or box[3]<=box[1]:
            raise ValueError("degenerate OCR polygon")
        det,rec=score(record.get("det_score")),score(record.get("rec_score"))
        text=record.get("text")
        if text is not None and not isinstance(text,str):
            raise ValueError("OCR text must be string or null")
        result.append({"id":record["id"],"polygon_norm":polygon,"bbox_norm":[float(v) for v in box],"text":text,
                       "detection_confidence":det,"recognition_confidence":rec,
                       "ambiguous":bool(record.get("ambiguous",False) or not text or rec is None or rec<ambiguous_below),"view_id":view["id"]})
    return result


def paddle_detection_records(result):
    polygons=result.get("dt_polys",[])
    scores=result.get("dt_scores",[])
    if len(polygons)!=len(scores):
        raise ValueError("Paddle detection polygon/score association mismatch")
    return [{"id":f"text_{i:04d}","polygon":np.asarray(polygons[i]).tolist(),"det_score":score(scores[i]),"text":None,"rec_score":None} for i in range(len(polygons))]
