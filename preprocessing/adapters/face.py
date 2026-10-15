from .common import bbox_to_canonical, points_to_canonical, score

LANDMARK_ORDER = "eye_0,eye_1,nose,mouth_0,mouth_1 (native SCRFD order)"


def normalize_faces(records,view,source_size):
    result=[]
    ids=set()
    for record in records:
        if record["id"] in ids:
            raise ValueError("duplicate native face id")
        ids.add(record["id"])
        box=bbox_to_canonical(record["bbox"],view)
        landmarks=record.get("landmarks5")
        if landmarks is not None and len(landmarks)!=5:
            raise ValueError("SCRFD landmarks must have five native points")
        result.append({"id":record["id"],"bbox_norm":box,"confidence":score(record.get("score")),
                       "landmarks5_norm":None if landmarks is None else points_to_canonical(landmarks,view),
                       "landmark_order":LANDMARK_ORDER,
                       "source_face_pixels":[max(1,round((box[2]-box[0])*source_size[0])),max(1,round((box[3]-box[1])*source_size[1]))],
                       "view_id":view["id"]})
    return result
