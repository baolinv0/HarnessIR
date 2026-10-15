"""Small bounded public dependency transfer probe, no model or credentials."""
import json
import time
import urllib.request
from pathlib import Path
url='https://files.pythonhosted.org/packages/b6/23/2a1b231b8ff672b4c450dac27164a8b2ca7d9b7144f9c02d2396518352eb/numpy-2.3.5-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl'
started=time.monotonic()
try:
    with urllib.request.urlopen(url,timeout=20) as r:data=r.read(1048576)
    elapsed=time.monotonic()-started
    result={'url':url,'status':'reachable','bytes_read':len(data),'elapsed_seconds':elapsed,'mib_per_second':len(data)/1048576/elapsed}
except Exception as e:result={'url':url,'status':'failed','error_type':type(e).__name__,'message':str(e),'elapsed_seconds':time.monotonic()-started}
out=Path(__file__).resolve().parents[2]/'runtime/alternatives/yoloe26l/local_package_transfer_probe.json'
out.write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
