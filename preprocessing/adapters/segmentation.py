import hashlib
from pathlib import Path

import numpy as np
from PIL import Image,ImageDraw

from .common import asset,bbox_to_canonical,canonical_json,save_image,score,write_json


def write_segmentation(records,prompt_set,out,view,source_size,mask_threshold=.5):
    labels=prompt_set["labels"]
    if prompt_set.get("unknown_id")!=0 or len(labels)!=len(set(labels)) or not labels:
        raise ValueError("invalid frozen prompt set")
    height,width=view["grid_shape"]
    unions=[np.zeros((height,width),dtype=bool) for _ in labels]
    masks=[]
    assets=[]
    ids=set()
    native=[]
    for index,record in enumerate(records):
        prompt_index=record["prompt_index"]
        if not isinstance(prompt_index,int) or not 0<=prompt_index<len(labels) or labels[prompt_index]!=record["label"] or record["id"] in ids:
            raise ValueError("native mask/label/prompt association mismatch")
        ids.add(record["id"])
        original=np.asarray(record["mask"])
        if original.ndim!=2 or original.shape!=(height,width) or not np.isfinite(original).all():
            raise ValueError("native mask shape or values invalid")
        raw_path=f"raw/mask_{index:04d}.npy"
        (Path(out)/"raw").mkdir(parents=True,exist_ok=True)
        np.save(Path(out)/raw_path,original,allow_pickle=False)
        binary=original>=mask_threshold
        path=f"masks/mask_{index:04d}.png"
        save_image(out,path,Image.fromarray(binary.astype(np.uint8)*255))
        unions[prompt_index]|=binary
        masks.append((record,binary))
        item={"id":record["id"],"label":labels[prompt_index],"prompt_index":prompt_index,"score":score(record.get("score")),
              "bbox_norm":bbox_to_canonical(record["bbox"],view),"mask_path":path,"grid_shape":[height,width],"view_id":view["id"]}
        native.append({**item,"native_mask_path":raw_path,"native_bbox":np.asarray(record["bbox"]).tolist(),"area_pixels":int(binary.sum())})
        assets.extend([asset(out,path,"map",(height,width)),asset(out,raw_path,"raw_data",(height,width))])
    regions=[]
    for index,label in enumerate(labels):
        path=f"masks/class_{index+1:03d}_union.png"
        save_image(out,path,Image.fromarray(unions[index].astype(np.uint8)*255))
        assets.append(asset(out,path,"map",(height,width)))
        regions.append({"class_id":index+1,"label":label,"prompt_index":index,"union_path":path,"union_area_pixels":int(unions[index].sum()),"union_area_ratio":float(unions[index].mean()),"instance_ids":[item["id"] for item in native if item["prompt_index"]==index]})
    display=np.zeros((height,width),dtype=np.uint16)
    for record,binary in sorted(masks,key=lambda pair:(-(pair[0].get("score") or 0),pair[0]["prompt_index"],pair[0]["id"])):
        display[binary & (display==0)]=record["prompt_index"]+1
    save_image(out,"maps/labels.png",Image.fromarray(display))
    palette=[{"class_id":0,"label":"unassigned/unknown","rgb":[0,0,0]}]
    for index,label in enumerate(labels):
        seed=hashlib.sha256(f"{prompt_set.get('palette_seed',0)}:{label}".encode()).digest()
        palette.append({"class_id":index+1,"label":label,"rgb":[64+(value%192) for value in seed[:3]]})
    colours=np.asarray([item["rgb"] for item in palette],dtype=np.uint8)
    save_image(out,"maps/semantic.png",Image.fromarray(colours[display]))
    write_json(out,"maps/palette.json",{"unknown_id":0,"classes":palette,"colour_algorithm":"sha256(seed:label),64+byte%192","display_overlap_rule":"score_desc_then_prompt_index_then_instance_id"})
    legend=Image.new("RGB",(480,30+24*len(palette)),(25,25,25))
    draw=ImageDraw.Draw(legend)
    draw.text((8,5),"Prompt masks; overlap retained in native masks",fill="white")
    for i,item in enumerate(palette):
        y=30+i*24
        draw.rectangle((8,y,28,y+16),fill=tuple(item["rgb"]))
        draw.text((38,y),f"{item['class_id']}: {item['label']}",fill="white")
    save_image(out,"maps/segmentation_legend.png",legend)
    overlap_count=np.sum([binary for _,binary in masks],axis=0) if masks else np.zeros((height,width))
    save_image(out,"maps/overlap.png",Image.fromarray((overlap_count>1).astype(np.uint8)*255))
    write_json(out,"raw/seg.json",{"instances":native,"regions":regions,"mask_threshold":mask_threshold,"overlap_pixels":int((overlap_count>1).sum()),"overlap_path":"maps/overlap.png","legend_path":"maps/segmentation_legend.png","grid_shape":[height,width],"view_id":view["id"]})
    assets.extend([asset(out,path,kind,shape) for path,kind,shape in [("maps/labels.png","map",(height,width)),("maps/semantic.png","map",(height,width)),("maps/palette.json","json",None),("maps/segmentation_legend.png","map",(legend.height,legend.width)),("maps/overlap.png","map",(height,width)),("raw/seg.json","json",None)]])
    data={"prompt_set_id":prompt_set["prompt_set_id"],"prompt_set_sha256":hashlib.sha256(canonical_json(prompt_set)).hexdigest(),"label_names":labels,
          "native_masks":[{key:value for key,value in item.items() if key not in ("native_mask_path","native_bbox","area_pixels")} for item in native],"unknown_id":0,"native_masks_may_overlap":True,
          "display_label_path":"maps/labels.png","preview_path":"maps/semantic.png","palette_path":"maps/palette.json",
          "display_overlap_rule":"score_desc_then_prompt_index_then_instance_id","unassigned_ratio":float((display==0).mean()),"native_result_path":"raw/seg.json"}
    return data,assets,["prompt_masks_do_not_guarantee_full_image_coverage"]
