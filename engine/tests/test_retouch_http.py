import base64
import copy
from http.server import BaseHTTPRequestHandler,HTTPServer
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import urlopen,Request
from urllib.error import HTTPError
from PIL import Image
from hre.retouch.providers import edit
from hre.retouch.workflow import Workbench
from hre.retouch.server import make_server
from hre.retouch.contracts import RetouchError
from test_retouch_workbench import analysis,contract,picture

class HTTPTests(unittest.TestCase):
    def test_invalid_analysis_json_retains_raw_receipt(self):
        class BadReply(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                raw=json.dumps({'choices':[{'message':{'content':'not valid analysis JSON'}}]}).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        server=HTTPServer(('127.0.0.1',0),BadReply);threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                w=Workbench(Path(tmp));c=w.create({'source_data':picture(),'reference_data':picture(),'brief':'reference tone'})
                with patch.dict(os.environ,{'HRE_RETOUCH_VLM_BASE_URL':f'http://127.0.0.1:{server.server_port}/v1','HRE_RETOUCH_VLM_MODEL':'test-vlm','HRE_RETOUCH_VLM_API_KEY':'test-key'}):
                    with self.assertRaises(RetouchError):w.step(c['id'],'diagnose')
                receipts=list((Path(tmp)/c['id']/'receipts').glob('*.json'))
                self.assertEqual(len(receipts),1);self.assertIn('not valid analysis JSON',receipts[0].read_text())
                self.assertEqual(w.get(c['id'])['calls']['analysis'],1);self.assertIsNone(w.get(c['id'])['analysis'])
        finally:server.shutdown();server.server_close()

    def test_extra_provider_outputs_are_retained_and_counted(self):
        class ExtraReply(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                raw=json.dumps({'data':[{'b64_json':'Zmlyc3Q='},{'b64_json':'c2Vjb25k'}]}).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        server=HTTPServer(('127.0.0.1',0),ExtraReply);threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                w=Workbench(Path(tmp));c=w.create({'source_data':picture(),'reference_data':picture(),'brief':'reference tone'})
                w.import_stage(c['id'],'diagnose',analysis(),'manual_agent');w.import_stage(c['id'],'compose',contract(),'manual_agent')
                with patch.dict(os.environ,{'OPENAI_BASE_URL':f'http://127.0.0.1:{server.server_port}/v1','OPENAI_API_KEY':'test-key'}):
                    with self.assertRaises(RetouchError):w.step(c['id'],'edit')
                s=w.get(c['id']);self.assertEqual(s['calls']['images'],2);self.assertEqual(s['status'],'task_not_met')
                raw=json.loads(next((Path(tmp)/c['id']/'receipts').glob('*.json')).read_text())
                self.assertEqual(len(json.loads(raw['raw_response'])['data']),2)
        finally:server.shutdown();server.server_close()

    def test_real_multipart_request_has_two_ordered_images_and_no_seed(self):
        seen={}
        class Recorder(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                seen["path"]=self.path
                seen["body"]=self.rfile.read(int(self.headers["Content-Length"]))
                seen["type"]=self.headers["Content-Type"]
                data=json.dumps({"data":[{"b64_json":base64.b64encode(b"test-output").decode()}]}).encode()
                self.send_response(200);self.send_header("Content-Length",str(len(data)));self.end_headers();self.wfile.write(data)
        server=HTTPServer(("127.0.0.1",0),Recorder)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                a,b=Path(tmp)/"a.png",Path(tmp)/"b.png";a.write_bytes(b"actual-A-bytes");b.write_bytes(b"actual-B-bytes")
                req={"prompt":"Edit image 1 using image 2","images":[{"role":"source","path":str(a)},{"role":"appearance_reference","path":str(b)}],
                     "settings":{"model":"gpt-image-2","n":1,"size":"1024x1024","quality":"high","output_format":"png"}}
                with patch.dict(os.environ,{"OPENAI_API_KEY":"test-key","OPENAI_BASE_URL":f"http://127.0.0.1:{server.server_port}/v1"}):
                    data,obs=edit(req)
                self.assertEqual(data,b"test-output");self.assertEqual(seen["path"],"/v1/images/edits")
                self.assertEqual(seen["body"].count(b'name="image[]"'),2)
                self.assertLess(seen["body"].index(b"actual-A-bytes"),seen["body"].index(b"actual-B-bytes"))
                for bad in (b'name="seed"',b'name="input_fidelity"',b'name="steps"',b'name="cfg"'):self.assertNotIn(bad,seen["body"])
        finally:server.shutdown();server.server_close()
    def test_http_case_roundtrip_and_no_secret_in_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            server=make_server(Workbench(Path(tmp)),0);threading.Thread(target=server.serve_forever,daemon=True).start()
            base=f"http://127.0.0.1:{server.server_port}"
            try:
                config=json.load(urlopen(base+"/api/config"))
                self.assertNotIn("api_key",config)
                b=io.BytesIO();Image.new("RGB",(100,120)).save(b,format="PNG")
                pic="data:image/png;base64,"+base64.b64encode(b.getvalue()).decode()
                req=Request(base+"/api/cases",data=json.dumps({"source_data":pic,"reference_data":pic,"brief":"参考影调"}).encode(),headers={"Content-Type":"application/json"},method="POST")
                c=json.load(urlopen(req));self.assertEqual(len(c["stages"]),8)
                fake=Request(base+'/api/cases/'+c['id']+'/import',data=json.dumps({'stage':'diagnose','payload':analysis(),'provenance':'vlm_api'}).encode(),headers={'Content-Type':'application/json'},method='POST')
                with self.assertRaises(HTTPError):urlopen(fake)
                self.assertIsNone(json.load(urlopen(base+'/api/cases/'+c['id']))['analysis'])
                self.assertEqual(json.load(urlopen(base+"/api/cases"))["cases"][0]["id"],c["id"])
                self.assertEqual(urlopen(base+c["images"]["source"]["url"]).headers["Content-Type"],"image/png")
            finally:server.shutdown();server.server_close()
if __name__=="__main__":unittest.main()
