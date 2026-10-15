from .common import WorkerFailure,assert_framework_version,require_artifact


def run(image,entry,parameters,out):
    import importlib.util
    import cv2
    import numpy as np
    import onnxruntime as ort
    from preprocessing.adapters.common import asset,detection_overlay,full_view,write_json
    from preprocessing.adapters.face import normalize_faces
    checkpoint=require_artifact(entry,"checkpoint")
    if checkpoint.name!="det_10g.onnx" or entry["model_name"]!="SCRFD_det_10g":
        raise WorkerFailure("unavailable","the locked detector is SCRFD det_10g.onnx")
    source=require_artifact(entry,"scrfd_source")
    assert_framework_version(ort.__version__,entry)
    provider=parameters["provider"]
    if provider == "CUDAExecutionProvider" and hasattr(ort, "preload_dlls"):
        # Explicitly prepared NVIDIA wheels, not runtime downloads or torch.
        ort.preload_dlls(directory="")
    if provider not in ort.get_available_providers():
        raise WorkerFailure("unavailable",f"frozen ORT provider unavailable: {provider}")
    cv2.setNumThreads(parameters["cpu_threads"])
    options=ort.SessionOptions()
    options.intra_op_num_threads=parameters["cpu_threads"]
    options.inter_op_num_threads=1
    session=ort.InferenceSession(str(checkpoint),sess_options=options,providers=[provider])
    actual=session.get_providers()
    if actual[0]!=provider:
        raise WorkerFailure("unavailable","ORT provider differs from frozen backend")
    spec=importlib.util.spec_from_file_location("locked_scrfd_detector",source)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    detector=module.SCRFD(model_file=str(checkpoint),session=session)
    detector.prepare(-1 if provider=="CPUExecutionProvider" else 0,input_size=tuple(parameters["input_size"]),det_thresh=parameters["det_threshold"],nms_thresh=parameters["nms_threshold"])
    bgr=np.ascontiguousarray(np.asarray(image.convert("RGB"))[:,:,::-1])
    boxes,landmarks=detector.detect(bgr,input_size=tuple(parameters["input_size"]),max_num=0)
    if landmarks is not None and len(boxes)!=len(landmarks):
        raise ValueError("SCRFD native bbox/landmark association mismatch")
    records=[{"id":f"face_{index:04d}","bbox":boxes[index,:4].tolist(),"score":float(boxes[index,4]),"landmarks5":None if landmarks is None else landmarks[index].tolist()} for index in range(len(boxes))]
    view=full_view(image.width,image.height)
    faces=normalize_faces(records,view,image.size)
    width,height=parameters["input_size"]
    if image.height/image.width>height/width:
        resized_h=height;resized_w=int(resized_h/(image.height/image.width))
    else:
        resized_w=width;resized_h=int(resized_w*(image.height/image.width))
    scale=resized_h/image.height
    sdk_view={"id":"sdk_letterbox","grid_shape":[height,width],"view_to_canonical":[[1/(scale*image.width),0,0],[0,1/(scale*image.height),0],[0,0,1]],"kind":"full_frame"}
    write_json(out,"raw/faces.json",{"records":records,"coordinate_space":"canonical_pixels_after_SCRFD_inverse_scale","providers":session.get_providers(),"model_input_size":[height,width],"resize_size":[resized_h,resized_w],"letterbox_padding":"bottom_right_black","threads":{"ort_intra":options.intra_op_num_threads,"ort_inter":options.inter_op_num_threads,"opencv":cv2.getNumThreads()},"recognition_loaded":False})
    assets=[asset(out,"raw/faces.json","json")]+detection_overlay(image,faces,out,"overlays/faces.png",keypoints=True)
    detections=[{"bbox_norm":item["bbox_norm"],"label":"face","text":None,"confidence":item["confidence"],"ambiguous":False} for item in faces]
    return {"data":{"faces":faces,"native_result_path":"raw/faces.json"},"assets":assets,"detections":detections,"views":[view,sdk_view],"tool_size":(width,height),"source_to_tool":[[scale,0,0],[0,scale,0],[0,0,1]],"warnings":[]}
