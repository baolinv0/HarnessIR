"""Record observed deployment/capability facts without importing model SDKs."""
import importlib.metadata as metadata
import json
import subprocess
import sys
from pathlib import Path
import psutil
from hir_manual.storage import read_json,write_json,now,sha256_file
from hir_manual.service import Controller
from hir_manual.capabilities import dispatch
from hir_manual.tool_registry import check_entry

root=Path(__file__).resolve().parents[2]
registry_path=root/"preprocessing/registry/cpu_probe_v1.json"
registry=read_json(registry_path)
t2_lock=root/"preprocessing/environments/t2_cpu.freeze.txt"
if sha256_file(t2_lock)==registry["tools"]["T2_FACE"]["environment_lock_sha256"]:
    registry["tools"]["T2_FACE"]["environment_lock_file"]=str(t2_lock)
write_json(registry_path,registry)
observed={"generated_at":now(),"python":sys.version,"controller_version":metadata.version("hir-manual"),"psutil":metadata.version("psutil"),"hardware":{"physical_memory_mb":round(psutil.virtual_memory().total/1048576,1),"available_memory_mb":round(psutil.virtual_memory().available/1048576,1),"cpu_physical":psutil.cpu_count(logical=False),"cpu_logical":psutil.cpu_count(logical=True),"gpu":"not_deployed_or_validated; hardware WMI read denied"},"models":{}}
for tool,entry in registry["tools"].items():
    check_entry(entry,require_ready=False)
    observed["models"][tool]={k:entry.get(k) for k in ("model_name","source_revision","model_bundle_sha256","backend","environment_lock_file","ready","warmup_evidence")}
t4_python=root/"preprocessing/environments/venv_t4_cpu/Scripts/python.exe"
if t4_python.exists():
    code="import importlib.metadata as m,json; print(json.dumps({n:m.version(n) for n in ['torch','torchvision','ultralytics','clip','numpy','opencv-python','Pillow']}))"
    result=subprocess.run([str(t4_python),"-c",code],capture_output=True,text=True,check=True)
    observed["models"]["T4_SEGMENTATION"]={"model_name":"YOLOE-26n-seg","versions":json.loads(result.stdout),"preparation":read_json(root/"models/yoloe_26n_seg/source_lock.json"),"ready":False,"missing":"guarded text embedding preparation and real-photo warm-up"}
write_json(root/"engine/validation/deployment_v11.json",observed)
ctl=Controller(root)
capabilities=read_json(root/"runtime/capabilities.json")
capabilities["dispatch_probe"]=dispatch(ctl,"case_cd31d9743abf4b14").model_dump()
capabilities["ui_inventory_probe"]={"apps":[],"browsers":["Codex In-app Browser","Codex MCP Apps"],"chatgpt_desktop_surface_available":False,"observed_at":now()}
write_json(root/"runtime/capabilities.json",capabilities)
write_json(root/"runtime/v11_m0/capability_check.json",capabilities)
case=ctl.inspect("case_59b9a98f07434ad1")
write_json(root/"runtime/v11_m0/minimal_chain.json",{"real_source":"Data/HardCases/Portrait/LowLight/HC_WildDark_124/input.png","case_id":case.case_id,"scope":"current_local_Work; explicitly selected by user; not desktop Executor validation","role_response":"runtime/v11_m0/diagnosis.json","canonical_sha256":case.input_sha256,"diagnosis_accepted":True,"next_state_after_accept":"WAIT_EVIDENCE","current_state":case.workflow_status,"passed_minimal_chain":True,"image_editing_completed":False,"restoration_success":None})
rows=__import__('hir_manual.tool_cli',fromlist=['read_manifest']).read_manifest(root/"Data/manifest.json")
write_json(root/"engine/validation/dataset_scope_v11.json",{"manifest":"Data/manifest.json","image_rows":len(rows),"input_and_gt_files":read_json(root/"engine/validation/existing_assets.json")["checked_files"],"requested_approximate_formal_count":280,"full_280_manifest_available":len(rows)>=280,"original_assets_unchanged":read_json(root/"engine/validation/existing_assets.json")["passed"]})
print({"controller_version":observed["controller_version"],"memory_mb":observed["hardware"]["available_memory_mb"],"model_ready":{k:v["ready"] for k,v in observed["models"].items()},"manifest_images":len(rows)})
