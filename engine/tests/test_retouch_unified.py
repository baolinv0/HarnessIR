"""delivery_v3 synthetic software controls; no real visual/model claims."""
from copy import deepcopy
import base64
import io
import json
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
import pytest
from PIL import Image,ImageCms
from hre.retouch.contracts import RetouchError
from hre.retouch.workflow import Workbench,read_json
from hre.retouch.unified_workflow import VERSION,digest
from test_retouch_workbench import picture,analysis,contract,verification
from unified_fixtures import whole_fixture


def verify(w,id,value):
    c=w._load(id)
    if c["phase"]=="whole_image_review":w.import_stage(id,"whole_image_review",whole_fixture(w.export(id,"whole_image_review")["context"]["image_sha256"]))
    c=w._load(id);whole=c["rounds"][-1]["whole_image_review"]
    value={**deepcopy(value),"overall_style":deepcopy(whole["overall_style"]),"whole_image_review_sha256":digest(whole)}
    return w.import_stage(id,"verify",value)


def inputs(size=(96,128),known=False):
    def image(color):
        out=io.BytesIO();Image.new("RGB",size,color).save(out,format="PNG",**({"icc_profile":ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()} if known else {}))
        return "data:image/png;base64,"+base64.b64encode(out.getvalue()).decode()
    return dict(source_data=image((90,100,110)),reference_data=image((140,130,120)),brief="Match supported B appearance",acceptance_version=VERSION)


def new_analysis(close=False):
    value=analysis()
    for delta in value["candidate_deltas"]:
        delta["attribute"]="shadow_midtone_highlight" if delta["attribute"]=="brightness" else "skin_rendering"
    if close:
        value.update(candidate_deltas=[],analysis_status="already_close")
        for row in value["coverage"]:row["status"]="already_satisfied"
    return value


def new_contract(close=False):
    value=contract()
    for target in value["targets"]:
        target["attribute"]="shadow_midtone_highlight" if target["attribute"]=="brightness" else "skin_rendering"
    for row in value["coverage"]:
        refs=[t["target_id"] for t in value["targets"] if t["attribute"]==row["attribute"]]
        row.update(target_ids=refs,status="targeted" if refs else "preserve")
    if close:
        value.update(targets=[],overall_status="already_satisfied")
        for row in value["coverage"]:row.update(status="already_satisfied",target_ids=[])
    return value


def setup(tmp_path,*,close=False,request=None):
    w=Workbench(tmp_path/"cases");c=w.create(request or inputs());id=c["id"]
    w.import_stage(id,"diagnose",new_analysis(close));c=w.step(id,"evidence")
    review=dict(initial_diagnosis_sha256=digest(c["initial_diagnosis"]),evidence_sha256=digest(c["evidence"]),
        resolution="resolved",reason="Synthetic actual review fixture",effective_diagnosis=new_analysis(close))
    w.import_stage(id,"evidence_review",review);return w,id


def prepared(tmp_path,**kwargs):
    w,id=setup(tmp_path,**kwargs);w.import_stage(id,"compose",new_contract());return w,id


def test_noop_preserves_original_before_canvas_and_skips_backend_aspect_limit(tmp_path):
    w,id=setup(tmp_path,close=True,request=inputs((800,40)))
    c=w.import_stage(id,"compose",new_contract(close=True))
    assert c["status"]=="already_satisfied" and c["result_url"]==c["images"]["source"]["url"]
    assert c["calls"]==dict(analysis=0,images=0)
    assert c["geometry"]["policy"]=="not_prepared"
    assert not (w._dir(id)/"assets/source_work.png").exists()


def test_evidence_cannot_implicitly_resolve_needs_evidence(tmp_path):
    w=Workbench(tmp_path/"cases");id=w.create(inputs())["id"]
    a=new_analysis();a["analysis_status"]="needs_evidence"
    w.import_stage(id,"diagnose",a);c=w.step(id,"evidence")
    assert c["phase"]=="evidence_review" and c["effective_diagnosis"] is None
    with pytest.raises(RetouchError):w.import_stage(id,"compose",new_contract())
    review=dict(initial_diagnosis_sha256=digest(a),evidence_sha256=digest(c["evidence"]),resolution="resolved",reason="unsupported",effective_diagnosis=a)
    with pytest.raises(RetouchError):w.import_stage(id,"evidence_review",review)


def test_preflight_blocks_large_native_requirement_before_provider_and_budget(tmp_path):
    request=inputs();request["delivery_requirements"]={"minimum_native_size":[4000,4000]}
    w,id=prepared(tmp_path,request=request)
    with patch("hre.retouch.providers.edit",side_effect=AssertionError("must not call")):
        c=w.step(id,"edit")
    assert c["status"]=="delivery_not_met" and c["delivery_preflight"]["status"]=="infeasible"
    assert c["calls"]["images"]==0


def test_limitations_reach_actual_prompt_and_unknown_encoding_is_not_numeric(tmp_path):
    w,id=setup(tmp_path)
    c=w._load(id);effective=c["effective_diagnosis"]
    for delta in effective["candidate_deltas"]:delta.update(comparability="conditional",uncertainty="Preserve A illumination; B is a different light")
    review={**c["evidence_review"],"effective_diagnosis":effective}
    w.import_stage(id,"evidence_review",review)
    value=new_contract()
    for target in value["targets"]:target.update(comparability="conditional",uncertainty="Preserve A illumination; B is a different light")
    c=w.import_stage(id,"compose",value)
    assert "different light" in c["prompt"] and "Mandatory: true" in c["prompt"]
    assert c["prompt_audit"]["prompt_sha256"]
    assert not c["colour_policy"]["source"]["numeric_eligible"] and c["evidence"]["status"]=="unavailable"


def test_pending_review_blocks_refinement_and_same_candidate_review_appends(tmp_path):
    w,id=prepared(tmp_path);w.candidate(id,picture(),"unknown")
    value=verification("uncertain");c=verify(w,id,value)
    assert c["normalized_feedback"]["action"]=="manual_review"
    with pytest.raises(RetouchError):w.import_stage(id,"refine",dict(action="revise",correction="Unsupported",feedback_refs=["verification:target:skin_color"]))
    r=c["rounds"][-1];old=deepcopy(r["verification"])
    review=dict(candidate_id=r["candidate_id"],round=r["index"],native_sha256=r["native_sha256"],delivered_sha256=r["delivered_sha256"],
        predecessor_sha256=digest(r["verification_versions"][-1]),verification={**verification(),"overall_style":r["whole_image_review"]["overall_style"],
            "whole_image_review_sha256":digest(r["whole_image_review"])},whole_image_review=r["whole_image_review"])
    c=w.review_candidate(id,review)
    assert c["status"]=="accepted" and c["calls"]["images"]==1
    assert c["rounds"][-1]["verification"]==old and len(c["rounds"][-1]["verification_versions"])==2
    with pytest.raises(RetouchError):w.review_candidate(id,review)


def test_target_only_correction_uses_normalized_feedback_without_legacy_issues(tmp_path):
    w,id=prepared(tmp_path);w.candidate(id,picture(),"unknown")
    c=verify(w,id,verification("unmet"))
    assert c["phase"]=="refine" and c["normalized_feedback"]["action"]=="revise_prompt"
    c=w.import_stage(id,"refine",dict(action="revise",correction="Fix residual skin cast",feedback_refs=["verification:target:skin_color"]))
    assert c["phase"]=="edit" and "Fix residual skin cast" in c["prompt"]


def test_a_and_b_regions_do_not_assert_candidate_correspondence(tmp_path):
    w,id=prepared(tmp_path);c=w.candidate(id,picture(),"unknown")
    assert c["candidate_attribute_deltas"]==[] and c["candidate_measurement_status"]["status"]=="unavailable"
    r=c["rounds"][-1]
    assert r["raw_sha256"] and r["native_sha256"] and r["delivered_sha256"]


def test_real_local_http_v3_multipart_preserves_order_prompt_receipt_and_count(tmp_path,monkeypatch):
    recorded=[];result=base64.b64decode(picture(size=(704,944)).split(",")[1])
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            recorded.append((self.path,self.headers["Content-Type"],self.rfile.read(int(self.headers["Content-Length"]))))
            body=json.dumps(dict(data=[dict(b64_json=base64.b64encode(result).decode())],created=1)).encode()
            self.send_response(200);self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
    server=ThreadingHTTPServer(("127.0.0.1",0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    monkeypatch.setenv("OPENAI_API_KEY","synthetic-local-fixture-key");monkeypatch.setenv("OPENAI_BASE_URL",f"http://127.0.0.1:{server.server_port}/v1")
    try:
        w,id=prepared(tmp_path)
        req=w.export(id,"edit")
        # Return the actual planned legal native canvas.
        out=io.BytesIO();Image.new("RGB",tuple(req["geometry"]["canvas_size"])).save(out,format="PNG");result=out.getvalue()
        c=w.step(id,"edit")
        assert c["calls"]["images"]==1 and c["pending_image"] is None
        path,mime,body=recorded[0]
        assert path=="/v1/images/edits" and "multipart/form-data" in mime
        assert body.index(b'filename="source.png"')<body.index(b'filename="reference.png"')
        assert req["prompt"].encode() in body and b'name="n"\r\n\r\n1' in body
        assert list((w._dir(id)/"receipts").glob("*.json"))
    finally:server.shutdown();server.server_close();thread.join(timeout=3)


@pytest.mark.parametrize("status,expected",[("unmet","task_not_met"),("uncertain","needs_review")])
def test_whole_frame_lighting_result_precedes_achieved_targets(tmp_path,status,expected):
    w,id=prepared(tmp_path);w.candidate(id,picture(),"unknown")
    whole=whole_fixture(w.export(id,"whole_image_review")["context"]["image_sha256"])
    whole["overall_style"]["lighting_naturalness"].update(reference_status=status,relation="uncertain" if status=="uncertain" else "farther",
        magnitude="unknown" if status=="uncertain" else "moderate")
    w.import_stage(id,"whole_image_review",whole)
    c=verify(w,id,verification())
    assert c["status"]==expected and c["appearance_status"]!="accept" and c["calls"]["images"]==1


def test_known_major_damage_is_rejected_with_uncertain_whole_color(tmp_path):
    w,id=prepared(tmp_path);w.candidate(id,picture(),"unknown")
    whole=whole_fixture(w.export(id,"whole_image_review")["context"]["image_sha256"])
    whole["preservation"]["identity"]["status"]="fail"
    whole["overall_style"]["color"].update(reference_status="uncertain",relation="uncertain",magnitude="unknown",confidence="unknown")
    w.import_stage(id,"whole_image_review",whole);c=verify(w,id,verification())
    assert c["appearance_status"]=="reject" and c["normalized_feedback"]["known_major_damage"]
    assert c["status"]=="task_not_met"


def test_known_icc_encoding_is_eligible_and_frozen_source_tampering_fails(tmp_path):
    w,id=setup(tmp_path,request=inputs(known=True))
    assert w.get(id)["colour_policy"]["source"]["numeric_eligible"]
    Image.new("RGB",(96,128),(1,2,3)).save(w._dir(id)/"assets/source.png")
    with pytest.raises(RetouchError):w.export(id,"compose")
    with pytest.raises(RetouchError):w.get(id)


def test_declared_working_size_cannot_stretch_portrait_to_square(tmp_path):
    request=inputs((96,128));request.update(delivery_mode="declared_working_size",working_size=[1024,1024])
    with pytest.raises(RetouchError):Workbench(tmp_path/"cases").create(request)
