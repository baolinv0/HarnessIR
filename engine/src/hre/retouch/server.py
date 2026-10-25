"""Loopback-only HTTP workbench, served without additional web dependencies."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from .contracts import RetouchError,require
from .workflow import Workbench
from . import providers,experiment_view

STATIC=Path(__file__).parent/"static"

def make_server(workbench,port=8766):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send_bytes(self,data,mime,status=200,download=None):
            self.send_response(status);self.send_header("Content-Type",mime)
            self.send_header("Content-Length",str(len(data)));self.send_header("Cache-Control","no-store")
            self.send_header("X-Content-Type-Options","nosniff")
            if download:self.send_header("Content-Disposition",'attachment; filename="'+download+'"')
            self.end_headers();self.wfile.write(data)
        def json(self,value,status=200,download=None):
            self.send_bytes(json.dumps(value,ensure_ascii=False,allow_nan=False).encode(),"application/json; charset=utf-8",status,download)
        def parts(self):
            return urlsplit(self.path),urlsplit(self.path).path.strip("/").split("/")
        def do_GET(self):
            try:
                parsed,parts=self.parts()
                if parsed.path in ("/","/index.html","/app.js","/style.css","/experiments","/experiments.html","/experiments.js"):
                    name="index.html" if parsed.path=="/" else "experiments.html" if parsed.path=="/experiments" else parsed.path.lstrip("/")
                    p=STATIC/name;require(p.is_file(),"static_missing","界面文件尚未安装")
                    self.send_bytes(p.read_bytes(),{"html":"text/html; charset=utf-8","js":"text/javascript; charset=utf-8","css":"text/css; charset=utf-8"}[p.suffix[1:]])
                elif parts==["api","config"]:self.json(providers.settings())
                elif parts==["api","experiments"]:self.json(experiment_view.listing(workbench))
                elif len(parts)==3 and parts[:2]==["api","experiments"]:self.json(experiment_view.detail(workbench,parts[2]))
                elif len(parts)==5 and parts[:2]==["api","experiments"] and parts[3]=="assets":
                    self.send_bytes(experiment_view.asset(workbench,parts[2],parts[4]).read_bytes(),"image/png")
                elif parts==["api","cases"]:self.json({"cases":workbench.list()})
                elif len(parts)>=3 and parts[:2]==["api","cases"]:
                    id=parts[2]
                    if len(parts)==3:self.json(workbench.get(id))
                    elif len(parts)==5 and parts[3]=="assets":
                        p=workbench._dir(id)/"assets"/parts[4]
                        require(p.name==parts[4] and p.suffix.lower()==".png" and p.is_file(),"asset_missing","图像不存在")
                        self.send_bytes(p.read_bytes(),"image/png")
                    elif parts[3:]==["export"]:
                        stage=parse_qs(parsed.query).get("stage",["diagnose"])[0]
                        self.json(workbench.export(id,stage),download=stage+"-request.json")
                    elif parts[3:]==["report"]:self.json(workbench.get(id),download=id+"-report.json")
                    else:self.json({"error":"not_found","message":"路径不存在"},404)
                else:self.json({"error":"not_found","message":"路径不存在"},404)
            except RetouchError as e:self.json({"error":e.code,"message":str(e)},400)
            except (OSError,ValueError,KeyError,TypeError):self.json({"error":"read_failed","message":"无法读取本地案例"},400)
        def do_POST(self):
            try:
                require(self.headers.get("Content-Type","").startswith("application/json"),"content_type","请求应使用 JSON")
                origin=self.headers.get("Origin")
                require(not origin or origin in ("http://"+self.headers.get("Host",""),),"origin_invalid","请从本地工作台提交")
                size=int(self.headers.get("Content-Length","0"))
                require(0<size<=140_000_000,"body_size","请求大小无效")
                req=json.loads(self.rfile.read(size));parsed,parts=self.parts()
                require(isinstance(req,dict),"body_invalid","请求必须是对象")
                if parts==["api","cases"]:value=workbench.create(req)
                else:
                    require(len(parts)==4 and parts[:2]==["api","cases"],"not_found","路径不存在")
                    id,action=parts[2:]
                    if action=="step":value=workbench.step(id,req["stage"])
                    elif action=="regions":value=workbench.regions(id,req["regions"])
                    elif action=="import":
                        provenance=req.get("provenance","manual_agent")
                        require(provenance in ("manual_agent","human"),"provenance_invalid","HTTP 导入只能标为 Agent 或人工观察，不能冒充真实接口调用")
                        value=workbench.import_stage(id,req["stage"],req["payload"],provenance)
                    elif action=="candidate":value=workbench.candidate(id,req["image_data"],req["model"],note=req.get("note",""),
                                                                       pending_attempt_id=req.get("pending_attempt_id"),
                                                                       submitted_prompt=req.get("submitted_prompt"),external_geometry=req.get("external_geometry"))
                    else:raise RetouchError("not_found","未知操作")
                self.json(value)
            except RetouchError as e:self.json({"error":e.code,"message":str(e)},400)
            except (OSError,ValueError,KeyError,TypeError):self.json({"error":"request_invalid","message":"请求无法处理；请核对 JSON 字段和本地文件"},400)
    return ThreadingHTTPServer(("127.0.0.1",port),Handler)
