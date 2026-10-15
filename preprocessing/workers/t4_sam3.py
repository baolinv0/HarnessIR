from .common import WorkerFailure,assert_framework_version,require_artifact,require_torch_device,source_view


def run(image,entry,parameters,out):
    import sys
    import torch
    from preprocessing.adapters.common import full_view,asset,write_json
    from preprocessing.adapters.segmentation import write_segmentation
    if entry["model_name"]!="SAM3" or parameters.get("checkpoint_generation")!="SAM3-not-SAM3.1":
        raise WorkerFailure("unavailable","this profile requires Meta SAM 3 image API; SAM 3.1 is not a substitute")
    assert_framework_version(torch.__version__,entry)
    device=require_torch_device(torch,parameters)
    if not device.startswith("cuda"):
        raise WorkerFailure("unavailable","gpu_full_v1 SAM3 requires the frozen CUDA backend")
    checkpoint=require_artifact(entry,"checkpoint")
    tokenizer=require_artifact(entry,"tokenizer")
    source=require_artifact(entry,"source_dir",directory=True)
    sys.path.insert(0,str(source))
    from sam3.model_builder import build_sam3_image_model
    from sam3.model.sam3_image_processor import Sam3Processor
    model=build_sam3_image_model(checkpoint_path=str(checkpoint),bpe_path=str(tokenizer),load_from_HF=False,device="cuda",eval_mode=True,enable_inst_interactivity=False,compile=False)
    model=model.to(device).eval()
    torch.backends.cuda.matmul.allow_tf32=False
    torch.backends.cudnn.allow_tf32=False
    processor=Sam3Processor(model,resolution=parameters["input_size"],device=device,confidence_threshold=parameters["score_threshold"])
    view_image=source_view(image,parameters)
    prompt_set=parameters["prompt_set"]
    records=[]
    with torch.inference_mode():
        state=processor.set_image(view_image)
        for prompt_index,label in enumerate(prompt_set["labels"]):
            processor.reset_all_prompts(state)
            output=processor.set_text_prompt(state=state,prompt=label)
            boxes,scores=output["boxes"],output["scores"]
            masks=output.get("masks_logits",output["masks"])
            if not len(boxes)==len(scores)==len(masks):
                raise ValueError("SAM3 native mask/box/score association mismatch")
            for i in range(len(boxes)):
                records.append({"id":f"prompt_{prompt_index:03d}_mask_{i:04d}","label":label,"prompt_index":prompt_index,"score":float(scores[i].item()),"bbox":boxes[i].detach().cpu().numpy().tolist(),"mask":masks[i].squeeze(0).detach().cpu().numpy()})
    view=full_view(view_image.width,view_image.height,"source_view")
    data,assets,warnings=write_segmentation(records,prompt_set,out,view,image.size,parameters["mask_threshold"])
    size=parameters["input_size"]
    write_json(out,"raw/model_input.json",{"model_input_shape":[size,size],"source_view_shape":[view_image.height,view_image.width],"api":"Meta_Sam3Processor_image","checkpoint_generation":"SAM3","download_allowed":False,"mask_scaling":"Meta_bilinear_align_corners_false_sigmoid","precision":"fp32","torch_threads":torch.get_num_threads()})
    assets.append(asset(out,"raw/model_input.json","json"))
    detections=[{"bbox_norm":record["bbox_norm"],"label":record["label"],"text":None,"confidence":record["score"],"ambiguous":False} for record in data["native_masks"]]
    return {"data":data,"assets":assets,"detections":detections,"views":[view,full_view(size,size,"sdk_input")],"tool_size":(size,size),"source_to_tool":[[size/image.width,0,0],[0,size/image.height,0],[0,0,1]],"warnings":warnings}
