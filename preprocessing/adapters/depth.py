from pathlib import Path

import numpy as np
from PIL import Image,ImageDraw

from .common import asset,save_image,write_json


def rgb_to_author_bgr(rgb):
    rgb=np.asarray(rgb)
    if rgb.ndim!=3 or rgb.shape[2]!=3:
        raise ValueError("author API requires a three-channel image")
    return np.ascontiguousarray(rgb[:,:,::-1])


def write_depth(depth,out,view_id,larger_is):
    depth=np.asarray(depth,dtype=np.float32)
    if depth.ndim!=2 or min(depth.shape)<1:
        raise ValueError("depth grid must be two dimensional")
    if larger_is not in ("near","far"):
        raise ValueError("relative depth direction required")
    valid=np.isfinite(depth)
    if not valid.any():
        raise ValueError("depth grid has no finite values")
    minimum,maximum=float(depth[valid].min()),float(depth[valid].max())
    path=Path(out)/"maps/depth.npy"
    path.parent.mkdir(parents=True,exist_ok=True)
    np.save(path,depth,allow_pickle=False)
    save_image(out,"maps/valid.png",Image.fromarray(valid.astype(np.uint8)*255))
    normalized=np.zeros(depth.shape,dtype=np.float32)
    if maximum>minimum:
        normalized[valid]=(depth[valid]-minimum)/(maximum-minimum)
    preview=np.rint(normalized*255).astype(np.uint8)
    save_image(out,"maps/depth_vis.png",Image.fromarray(preview))
    legend=Image.new("RGB",(480,110),(25,25,25))
    draw=ImageDraw.Draw(legend)
    draw.text((10,8),f"Relative depth: larger = {larger_is}; no metric units",fill="white")
    draw.text((10,30),f"Black = {minimum:.5g}, white = {maximum:.5g}; invalid pixels black",fill="white")
    for x in range(460):
        value=round(x/459*255)
        draw.line((10+x,60,10+x,85),fill=(value,value,value))
    save_image(out,"maps/depth_legend.png",legend)
    data={"depth_path":"maps/depth.npy","valid_mask_path":"maps/valid.png","preview_path":"maps/depth_vis.png",
          "grid_shape":list(depth.shape),"dtype":"float32","representation":"relative_depth","larger_is":larger_is,
          "view_id":view_id,"finite_value_range":[minimum,maximum],
          "normalization":{"method":"minmax","parameters":{"min":minimum,"max":maximum,"invalid_display_value":0},
                           "near_colour":"white" if larger_is=="near" else "black","far_colour":"black" if larger_is=="near" else "white"}}
    write_json(out,"raw/depth.json",{"grid_shape":list(depth.shape),"dtype":"float32","larger_is":larger_is,"finite_value_range":[minimum,maximum],"invalid_count":int((~valid).sum()),"legend_path":"maps/depth_legend.png"})
    assets=[asset(out,path,kind,shape) for path,kind,shape in [("maps/depth.npy","raw_data",depth.shape),("maps/valid.png","map",depth.shape),("maps/depth_vis.png","map",depth.shape),("maps/depth_legend.png","map",(110,480)),("raw/depth.json","json",None)]]
    return data,assets,["nonfinite_depth_values"] if not valid.all() else []
