"""Synthetic process-lifecycle reproduction, never a model acceptance test."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import psutil

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'engine/src'))
from hir_manual.resource_monitor import monitor_process
from hir_manual.tool_registry import load_profile
from hir_manual.storage import write_json
from hir_manual.windows_job import WindowsJob

records=[]
original_terminate=WindowsJob.terminate
original_close=WindowsJob.close
current=[]

def terminate(self):
    current.append({'at':time.monotonic(),'stage':'before_terminate','active':self.active_count(),'pids':self.process_ids()})
    return original_terminate(self)

def close(self):
    ids=list(dict.fromkeys(pid for row in current for pid in row.get('pids',[])))
    current.append({'at':time.monotonic(),'stage':'before_close','pid_exists':{pid:psutil.pid_exists(pid) for pid in ids}})
    value=original_close(self)
    current.append({'at':time.monotonic(),'stage':'after_close','pid_exists':{pid:psutil.pid_exists(pid) for pid in ids}})
    return value

WindowsJob.terminate=terminate
WindowsJob.close=close
base=ROOT/'runtime/remote_monitor/windows_release_probe'
base.mkdir(parents=True,exist_ok=True)
for index in range(12):
    current=[]
    profile=load_profile('cpu_probe_v1',ROOT)
    profile.min_available_memory_mb=0
    profile.abort_available_memory_mb=0
    profile.memory_sample_interval_ms=1000
    profile.tools['_active']={'timeout_seconds':5}
    folder=base/str(index);folder.mkdir(exist_ok=True)
    code="import subprocess,sys; p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']); open('child.pid','w').write(str(p.pid))"
    measured=monitor_process([sys.executable,'-c',code],folder,profile,folder/'logs')
    child=int((folder/'child.pid').read_text())
    present=psutil.pid_exists(child)
    delays=[]
    for delay in [0,.01,.02,.05,.1]:
        if delay:time.sleep(delay)
        details={'delay':delay,'pid_exists':psutil.pid_exists(child)}
        if details['pid_exists']:
            try:
                process=psutil.Process(child)
                details.update(status=process.status(),create_time=process.create_time(),running=process.is_running(),rss=process.memory_info().rss)
            except psutil.NoSuchProcess:details['gone_during_query']=True
        delays.append(details)
    record={'synthetic':True,'index':index,'worker':measured.model_dump(),'child_pid':child,'present_immediately':present,'stages':current,'delays':delays}
    records.append(record)
    write_json(base/'observations.json',records)
    print(json.dumps({'index':index,'present_immediately':present,'released':measured.process_released,'delays':delays}),flush=True)
