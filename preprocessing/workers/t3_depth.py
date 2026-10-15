from .common import WorkerFailure,assert_framework_version,require_artifact,require_torch_device,source_view


def run(image,entry,parameters,out):
    import sys
    import cv2
    import numpy as np
    import torch
    from preprocessing.adapters.common import full_view,write_json,asset
    from preprocessing.adapters.depth import rgb_to_author_bgr,write_depth
    expected={"vits":"Depth-Anything-V2-Small","vitb":"Depth-Anything-V2-Base"}
    encoder=parameters["encoder"]
    if encoder not in expected or entry["model_name"]!=expected[encoder]:
        raise WorkerFailure("unavailable","frozen DA-V2 encoder and checkpoint disagree")
    assert_framework_version(torch.__version__,entry)
    device=require_torch_device(torch,parameters)
    checkpoint=require_artifact(entry,"checkpoint")
    source=require_artifact(entry,"source_dir",directory=True)
    sys.path.insert(0,str(source))
    from depth_anything_v2.dpt import DepthAnythingV2
    configs={"vits":{"encoder":"vits","features":64,"out_channels":[48,96,192,384]},"vitb":{"encoder":"vitb","features":128,"out_channels":[96,192,384,768]}}
    cv2.setNumThreads(parameters["cpu_threads"])
    model=DepthAnythingV2(**configs[encoder])
    model.load_state_dict(torch.load(checkpoint,map_location="cpu",weights_only=True),strict=True)
    model=model.to(device).eval()
    view_image=source_view(image,parameters)
    bgr=rgb_to_author_bgr(np.asarray(view_image.convert("RGB")))
    with torch.inference_mode():
        tensor,_=model.image2tensor(bgr,parameters["sdk_input_size"])
        model_height,model_width=tensor.shape[-2:]
        del tensor
        depth=model.infer_image(bgr,input_size=parameters["sdk_input_size"])
    view=full_view(view_image.width,view_image.height,"source_view")
    data,assets,warnings=write_depth(depth,out,view["id"],parameters["larger_is"])
    # Author infer_image bilinearly returns the source-view grid, not an image
    # pretending to contain additional detail at canonical resolution.
    write_json(out,"raw/model_input.json",{"model_input_shape":[int(model_height),int(model_width)],"source_view_shape":[view_image.height,view_image.width],"api":"DepthAnythingV2.infer_image","api_colour":"OpenCV_BGR","channel_swap_count":1,"encoder":encoder,"threads":{"torch":torch.get_num_threads(),"torch_interop":torch.get_num_interop_threads(),"opencv":cv2.getNumThreads()},"depth_interpolation":"author_API_bilinear_align_corners_true"})
    assets.append(asset(out,"raw/model_input.json","json"))
    if view_image.size!=image.size:
        warnings.append("source_view_resized_no_added_detail")
    sdk_view=full_view(int(model_width),int(model_height),"sdk_input")
    return {"data":data,"assets":assets,"detections":[],"views":[view,sdk_view],"tool_size":(int(model_width),int(model_height)),"source_to_tool":[[model_width/image.width,0,0],[0,model_height/image.height,0],[0,0,1]],"warnings":warnings}
