from .common import WorkerFailure,assert_framework_version,require_artifact,require_torch_device,source_view


def locked_variant(entry, parameters):
    allowed = {"YOLOE-26n-seg": "yoloe-26n", "YOLOE-26l-seg": "yoloe-26l"}
    name = entry.get("model_name")
    if name not in allowed or parameters.get("model") != name:
        raise WorkerFailure("unavailable", "YOLOE model differs from explicit frozen variant")
    return allowed[name]


def run(image,entry,parameters,out):
    import json
    import numpy as np
    import torch
    from ultralytics import YOLOE
    from preprocessing.adapters.common import full_view,write_json,asset
    from preprocessing.adapters.segmentation import write_segmentation
    embedding_model = locked_variant(entry, parameters)
    assert_framework_version(torch.__version__,entry)
    require_torch_device(torch,parameters)
    checkpoint=require_artifact(entry,"checkpoint")
    embedding_path=require_artifact(entry,"text_embeddings")
    prompt_set=parameters["prompt_set"]
    if json.loads(require_artifact(entry,"prompt_set").read_text("utf-8"))!=prompt_set:
        raise WorkerFailure("unavailable","frozen prompt set differs from deployed embeddings")
    with np.load(embedding_path,allow_pickle=False) as bundle:
        if bundle["names"].tolist()!=prompt_set["labels"] or str(bundle["model"].item())!=embedding_model:
            raise WorkerFailure("unavailable","YOLOE prompt embedding identity mismatch")
        embeddings=bundle["embeddings"].copy()
    if embeddings.dtype!=np.float32 or embeddings.ndim!=3 or embeddings.shape[:2]!=(1,len(prompt_set["labels"])) or not np.isfinite(embeddings).all():
        raise ValueError("invalid frozen text embeddings")
    model=YOLOE(str(checkpoint))
    model.set_classes(prompt_set["labels"],torch.from_numpy(embeddings))
    view_image=source_view(image,parameters)
    results=model.predict(source=view_image,imgsz=parameters["input_size"],device=parameters["device"],conf=parameters["score_threshold"],retina_masks=True,half=False,batch=1,verbose=False,save=False,stream=False,rect=False)
    if len(results)!=1:
        raise ValueError("YOLOE must return one image result")
    result=results[0]
    boxes=result.boxes
    count=len(boxes) if boxes is not None else 0
    if count and (result.masks is None or len(result.masks.data)!=count):
        raise ValueError("YOLOE native box/mask association mismatch")
    records=[]
    for i in range(count):
        # Index the SDK Results object once; all fields retain its native row.
        instance=result[i]
        prompt_index=int(instance.boxes.cls[0].item())
        if not 0<=prompt_index<len(prompt_set["labels"]):
            raise ValueError("YOLOE unknown prompt association")
        records.append({"id":f"mask_{i:04d}","label":prompt_set["labels"][prompt_index],"prompt_index":prompt_index,
                        "score":float(instance.boxes.conf[0].item()),"bbox":instance.boxes.xyxy[0].detach().cpu().numpy().tolist(),
                        "mask":instance.masks.data[0].detach().cpu().numpy()})
    view=full_view(view_image.width,view_image.height,"source_view")
    data,assets,warnings=write_segmentation(records,prompt_set,out,view,image.size,parameters["mask_threshold"])
    size=parameters["input_size"]
    scale=min(size/view_image.width,size/view_image.height)
    resized=(round(view_image.width*scale),round(view_image.height*scale))
    padx=round((size-resized[0])/2-.1);pady=round((size-resized[1])/2-.1)
    scale_x=resized[0]/view_image.width;scale_y=resized[1]/view_image.height
    sdk_view={"id":"sdk_letterbox","grid_shape":[size,size],"view_to_canonical":[[1/resized[0],0,-padx/resized[0]],[0,1/resized[1],-pady/resized[1]],[0,0,1]],"kind":"full_frame"}
    write_json(out,"raw/model_input.json",{"model_input_shape":[size,size],"source_view_shape":[view_image.height,view_image.width],"letterbox_resize_shape":[resized[1],resized[0]],"letterbox_left_top":[padx,pady],"text_embeddings_precomputed":True,"mask_scaling":"ultralytics_retina_masks_to_original_shape","native_mask_threshold":parameters["mask_threshold"],"display_labels_are_not_native_instance_masks":True,"torch_threads":torch.get_num_threads(),"precision":"fp32"})
    assets.append(asset(out,"raw/model_input.json","json"))
    detections=[{"bbox_norm":record["bbox_norm"],"label":record["label"],"text":None,"confidence":record["score"],"ambiguous":False} for record in data["native_masks"]]
    return {"data":data,"assets":assets,"detections":detections,"views":[view,sdk_view],"tool_size":(size,size),"source_to_tool":[[scale_x*view_image.width/image.width,0,padx],[0,scale_y*view_image.height/image.height,pady],[0,0,1]],"warnings":warnings}
