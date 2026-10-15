"""Read app diagnostic logs only; save narrowly filtered, redacted evidence."""
import os
import re
import sys
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'engine/src'))
from hir_manual.storage import write_json,atomic_write,now

logs=Path(os.environ['LOCALAPPDATA'])/'Codex/Logs/2026/10'
session='01a1307e-d7af-7ec1-948d-239bfd73fa89'
matches=[];counts=Counter();lasts={}
for day in ['13','14']:
    for p in sorted((logs/day).glob('*.log')):
        with p.open(encoding='utf-8',errors='replace') as f:
            for lineno,line in enumerate(f,1):
                if session not in line:continue
                category=None
                if 'No ChatGPT browser route is available' in line:category='no_browser_route'
                elif 'browser_use_iab_backend_startup_ready' in line:category='iab_backend_ready'
                elif 'browser_use_iab_backend_startup_started' in line:category='iab_backend_start'
                elif 'browser-use-iab-api' in line and ('failed' in line or 'received' in line):category='iab_api_failed' if 'failed' in line else 'iab_api_received'
                if not category:continue
                counts[category]+=1
                error=re.search(r'errorMessage="([^"\n]*)"',line)
                request=re.search(r'\brequest=([^\s]+)',line)
                record=dict(category=category,time_utc=line[:24],file=str(p),line=lineno)
                if error:record['message']=error.group(1)
                if request:record['request']=request.group(1)
                # Never include raw log lines, credentials, pipe addresses,
                # page content, other tasks' histories or call payloads.
                lasts[category]=record
                if len([m for m in matches if m['category']==category])<3:matches.append(record)
report=dict(recorded_at=now(),session_id=session,scope='Application process metadata and narrowly filtered logs; no browser source or private page data read',counts=dict(counts),first_examples=matches,last_examples=lasts,confirmed=['This task has explicit No ChatGPT browser route errors in app logs','Native capture of ChatGPT and Explorer failed with FrameArrived timeout','Main ChatGPT.exe PID21044 started 2026-10-12 11:30 Beijing; computer-use PID6364 started 2026-10-13 23:45 Beijing'],uncertain=['Whether the historical route error explains every later timeout','Underlying Windows graphics frame failure cause','Whether app main-process exit/relaunch will repair both channels'],excluded_claims=['Not established to be a Gemini/ChatGPT website refusal','No evidence that CompPkgSrv is the cause','Durable WebSocket errors are observed separately and not attributed as the cause'])
out=ROOT/'runtime/computer_use_diagnosis_20261014';write_json(out/'evidence.json',report)
lines=['# Computer Use 故障定位','',f'记录时间：{report["recorded_at"]}','', '## 已确认的线索','', '1. 本会话浏览器路由报错：`No ChatGPT browser route is available for browser session ...`。这是应用内部会话到浏览器路由失败，不是网站登录拒绝。历史日志有明确证据，但不把它等同于所有后续超时的唯一原因。', '2. 原生Windows截图另有故障：ChatGPT和Explorer均`FrameArrived timed out`，不能断言只影响ChatGPT。', '3. 主进程PID21044仍从10月12日11:30运行，辅助进程PID6364从10月13日23:45运行。只有部分renderer近期新建，完整控制服务重启尚未实测。','', '## 路由错误统计与最后记录','',f'次数：{counts["no_browser_route"]}。',str(lasts.get('no_browser_route')),'','## 下一次验证','', '先保存其他正在运行的工作，通过应用的“退出”彻底结束主进程，再重新启动。仅关窗口/重载网页不会保证退出后台主进程。退出会中断当前及其他运行任务，因此本次没有强杀。重新打开同一聊天与浏览器，再测试页面读取及普通窗口截图。若仍失败，应将本报告提供给应用支持排查会话路由/原生捕获两条故障。','', '不清除浏览器登录数据，不改安全设置，不重新安装模型或把未完成实验标为通过。']
atomic_write(out/'README.md','\n'.join(lines).encode('utf-8'))
print(dict(counts=dict(counts),last_route=lasts.get('no_browser_route'),last_ready=lasts.get('iab_backend_ready')))

if __name__=='__main__':pass
