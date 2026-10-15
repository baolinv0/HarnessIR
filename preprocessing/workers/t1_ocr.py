from .common import WorkerFailure,assert_framework_version,require_artifact,result_dict,serializable


def run(image,entry,parameters,out):
    import cv2
    import numpy as np
    import paddle
    from paddleocr import TextDetection,TextRecognition
    from paddlex.inference.pipelines.components import CropByPolys
    from paddlex.inference.models.text_detection.processors import DetResizeForTest
    from PIL import Image
    from preprocessing.adapters.common import asset,detection_overlay,full_view,write_json,save_image
    from preprocessing.adapters.ocr import normalize_ocr,paddle_detection_records
    if entry["model_name"]!="PP-OCRv6_medium_det+rec":
        raise WorkerFailure("unavailable","locked OCR requires PP-OCRv6 Medium det and rec")
    assert_framework_version(paddle.__version__,entry)
    det_dir=require_artifact(entry,"detection_model_dir",directory=True)
    rec_dir=require_artifact(entry,"recognition_model_dir",directory=True)
    cv2.setNumThreads(parameters["cpu_threads"])
    device="cpu" if parameters["device"]=="cpu" else parameters["device"].replace("cuda","gpu")
    if device!="cpu" and not paddle.is_compiled_with_cuda():
        raise WorkerFailure("unavailable","frozen Paddle GPU backend unavailable")
    kwargs={"device":device,"engine":"paddle_static","cpu_threads":parameters["cpu_threads"],"enable_mkldnn":False,"enable_hpi":False}
    detector=TextDetection(model_name="PP-OCRv6_medium_det",model_dir=str(det_dir),**kwargs)
    recognizer=TextRecognition(model_name="PP-OCRv6_medium_rec",model_dir=str(rec_dir),**kwargs)
    bgr=np.ascontiguousarray(np.asarray(image.convert("RGB"))[:,:,::-1])
    resize=DetResizeForTest(limit_side_len=parameters["det_limit_side_len"],limit_type=parameters["det_limit_type"])
    resized_images,resize_metadata=resize([bgr])
    model_height,model_width=resized_images[0].shape[:2]
    del resized_images
    det_results=list(detector.predict(input=bgr,batch_size=1,limit_side_len=parameters["det_limit_side_len"],limit_type=parameters["det_limit_type"]))
    if len(det_results)!=1:
        raise ValueError("OCR detector must return one native image result")
    raw_det=result_dict(det_results[0])
    records=paddle_detection_records(raw_det)
    cropper=CropByPolys(det_box_type="quad")
    native_rec=[]
    recognizer_assets=[]
    # One crop per call keeps a stable association even if the recognizer sorts
    # internally by aspect ratio. Use the SDK's own perspective crop operation.
    for record in records:
        crops=list(cropper(bgr,[np.asarray(record["polygon"],dtype=np.float32)]))
        if len(crops)!=1 or crops[0].size==0:
            raise ValueError("OCR native crop association invalid")
        results=list(recognizer.predict(input=crops[0],batch_size=1))
        if len(results)!=1:
            raise ValueError("OCR native recognition association invalid")
        rec=result_dict(results[0])
        record["text"]=rec["rec_text"]
        record["rec_score"]=float(rec["rec_score"])
        crop_path=f"crops/recognizer_{len(native_rec):04d}.png"
        save_image(out,crop_path,Image.fromarray(np.ascontiguousarray(crops[0][:,:,::-1])))
        recognizer_assets.append(asset(out,crop_path,"photo",crops[0].shape[:2]))
        native_rec.append({"detection_id":record["id"],"crop_path":crop_path,"result":serializable(rec)})
    view=full_view(image.width,image.height)
    items=normalize_ocr(records,view)
    write_json(out,"raw/ocr.json",{"records":records,"native_detection":serializable(raw_det),"native_recognition":native_rec,"detector_model_input_shape":[model_height,model_width],"detector_resize_metadata":serializable(resize_metadata),"pipeline_mode":"paddle_static_modules_with_native_CropByPolys","model_names":["PP-OCRv6_medium_det","PP-OCRv6_medium_rec"],"doc_orientation":False,"doc_unwarp":False,"textline_orientation":False,"cpu_threads":parameters["cpu_threads"],"opencv_threads":cv2.getNumThreads()})
    assets=[asset(out,"raw/ocr.json","json")]+recognizer_assets+detection_overlay(image,items,out,"overlays/ocr.png",polygon_key="polygon_norm",crops=True)
    detections=[{"bbox_norm":item["bbox_norm"],"label":"text","text":item["text"],"confidence":item["recognition_confidence"],"ambiguous":item["ambiguous"]} for item in items]
    return {"data":{"items":items,"native_result_path":"raw/ocr.json"},"assets":assets,"detections":detections,"views":[view,full_view(model_width,model_height,"sdk_detection_input")],"tool_size":(model_width,model_height),"source_to_tool":[[model_width/image.width,0,0],[0,model_height/image.height,0],[0,0,1]],"warnings":["OCR_output_is_unverified_recognition"]}
