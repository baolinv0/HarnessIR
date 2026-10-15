from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(out, relative, value):
    path = Path(out) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json(value))
    return relative


def asset(out, relative, kind, shape=None):
    path = Path(out) / relative
    if kind not in ("photo","map","overlay"):
        shape=None
    return {"path":relative,"sha256":sha256(path),"kind":kind,
            "width":None if shape is None else int(shape[1]),"height":None if shape is None else int(shape[0])}


def score(value):
    if value is None:
        return None
    value = float(value)
    if not np.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("confidence must be finite and within [0,1]")
    return value


def points_to_canonical(points, view):
    points = np.asarray(points,dtype=np.float64)
    matrix = np.asarray(view["view_to_canonical"],dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all() or matrix.shape != (3,3) or not np.isfinite(matrix).all():
        raise ValueError("invalid coordinate geometry")
    transformed = np.c_[points,np.ones(len(points))] @ matrix.T
    if np.any(np.abs(transformed[:,2]) < 1e-12):
        raise ValueError("invalid homogeneous coordinate")
    # SDK detections may overshoot a border slightly; the native coordinates are
    # retained in raw JSON, while canonical overlays clip to the actual photo.
    return np.clip(transformed[:,:2] / transformed[:,2,None],0,1).tolist()


def bbox_to_canonical(bbox, view):
    bbox = np.asarray(bbox,dtype=np.float64)
    if bbox.shape != (4,) or not np.isfinite(bbox).all() or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
        raise ValueError("invalid bbox")
    points = np.asarray(points_to_canonical([[bbox[0],bbox[1]],[bbox[2],bbox[1]],[bbox[2],bbox[3]],[bbox[0],bbox[3]]],view))
    result = [*points.min(axis=0),*points.max(axis=0)]
    if result[2] <= result[0] or result[3] <= result[1]:
        raise ValueError("bbox outside canonical image")
    return [float(v) for v in result]


def full_view(width,height,view_id="full"):
    return {"id":view_id,"grid_shape":[int(height),int(width)],"view_to_canonical":[[1/width,0,0],[0,1/height,0],[0,0,1]],"kind":"full_frame"}


def save_image(out, relative, image):
    path = Path(out)/relative
    path.parent.mkdir(parents=True,exist_ok=True)
    image.save(path)
    return relative


def detection_overlay(image, items, out, relative, polygon_key=None, keypoints=False, crops=False):
    overlay = image.convert("RGB").copy()
    draw = ImageDraw.Draw(overlay)
    width,height = image.size
    assets=[]
    for index,item in enumerate(items):
        box=item["bbox_norm"]
        pixels = [box[0]*width,box[1]*height,box[2]*width,box[3]*height]
        draw.rectangle(pixels,outline=(255,190,0),width=2)
        if polygon_key:
            polygon=[(x*width,y*height) for x,y in item[polygon_key]]
            draw.line(polygon+[polygon[0]],fill=(0,255,160),width=2)
        if keypoints and item["landmarks5_norm"] is not None:
            for point_index,(x,y) in enumerate(item["landmarks5_norm"]):
                px,py=x*width,y*height
                draw.ellipse((px-2,py-2,px+2,py+2),fill=(255,60,60))
                draw.text((px+3,py),str(point_index),fill=(255,255,255))
        if crops:
            left,top,right,bottom = int(np.floor(pixels[0])),int(np.floor(pixels[1])),int(np.ceil(pixels[2])),int(np.ceil(pixels[3]))
            crop=image.crop((left,top,right,bottom))
            path=f"crops/item_{index:04d}.png"
            save_image(out,path,crop)
            assets.append(asset(out,path,"photo",(crop.height,crop.width)))
    save_image(out,relative,overlay)
    assets.append(asset(out,relative,"overlay",(height,width)))
    return assets


def normalize_result(job,raw_dir):
    """Read a normalized worker manifest without importing any model framework.

    Controller applies its independent schema and geometry validator afterward.
    This boundary refuses a different job or changed/missing worker artifacts.
    """
    directory=Path(raw_dir)
    manifest=json.loads((directory/"evidence.json").read_text("utf-8"))
    if not isinstance(job,dict):
        job=job.model_dump() if hasattr(job,"model_dump") else job.to_dict() if hasattr(job,"to_dict") else vars(job)
    for key in ("tool_id","image_id","cache_key","evidence_profile_id"):
        if manifest.get(key)!=job.get(key):
            raise ValueError(f"worker evidence mismatches {key}")
    contract=job["cache_contract"]
    if manifest["input_sha256"]!=contract["canonical_sha256"] or manifest["model_bundle_sha256"]!=contract["model_bundle_sha256"] or manifest["backend"]!=contract["backend"]:
        raise ValueError("worker evidence mismatches frozen cache contract")
    for item in manifest["assets"]:
        relative=item["path"]
        if not re.fullmatch(r"[A-Za-z0-9_./-]+",relative) or relative.startswith("/") or ".." in Path(relative).parts:
            raise ValueError("unsafe worker artifact path")
        path=(directory/relative).resolve()
        if not path.is_relative_to(directory.resolve()) or not path.is_file() or sha256(path)!=item["sha256"]:
            raise ValueError("worker artifact missing or changed")
    return manifest
