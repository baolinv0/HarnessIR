"""Linux preflight. Inspect shutdown first; never cancel or postpone a plan.

This script only runs after the user has authorized server access and shutdown.
It emits no environment credentials or process command lines.
"""
import datetime as dt
import json
import os
import pathlib
import shutil
import subprocess
import time


def run(argv, timeout=15):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return {"returncode": r.returncode, "stdout": r.stdout.strip(), "stderr": r.stderr.strip()}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"returncode": None, "error": type(e).__name__}


def utc(epoch):
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).isoformat()


def shutdown():
    start = time.time()
    scheduled = pathlib.Path('/run/systemd/shutdown/scheduled')
    def read_plan():
        if not scheduled.is_file():
            return None
        pairs = dict(line.split('=', 1) for line in scheduled.read_text().splitlines() if '=' in line)
        if pairs.get('USEC', '').isdigit():
            return {"verified": True, "deadline_utc": utc(int(pairs['USEC']) / 1_000_000),
                    "method": "systemd_shutdown", "verification": {"scheduled_file": str(scheduled), "mode": pairs.get('MODE')}}
        return {"verified": False, "status": "existing_plan_unreadable", "method": "systemd_shutdown"}
    existing = read_plan()
    if existing:
        existing.update(status="existing_plan_preserved", changed=False)
        return existing
    # Do not duplicate an existing cron/at shutdown, even when its date cannot
    # safely be resolved. Never output arbitrary scheduler contents.
    cron = run(['crontab', '-l'])
    lines = cron.get('stdout', '').splitlines()
    found = any(not l.lstrip().startswith('#') and any(x in l for x in ('shutdown', 'poweroff', 'halt')) for l in lines)
    atq = run(['atq'])
    for line in atq.get('stdout', '').splitlines():
        job = line.split()[0] if line.split() else ''
        if job.isdigit():
            body = run(['at', '-c', job]).get('stdout', '')
            found = found or any(any(x in l for x in ('shutdown ', 'poweroff', '/halt')) for l in body.splitlines())
    if found:
        return {"verified": False, "status": "existing_scheduler_plan_preserved", "changed": False,
                "method": "cron_or_at", "reason": "Existing shutdown detected; deadline requires inspection. No additional plan created."}
    pid1 = pathlib.Path('/proc/1/comm').read_text().strip()
    if pid1 != 'systemd' or not shutil.which('shutdown'):
        return {"verified": False, "status": "unsupported", "changed": False, "method": None,
                "reason": "System shutdown scheduling unavailable in this instance/container; no poweroff was scheduled.",
                "pid1": pid1, "compute_deadline_utc": utc(start + 120 * 60)}
    action = run(['shutdown', '-h', '+120', 'HarnessIR user-authorized 120 minute limit'])
    verified = read_plan()
    if action.get('returncode') == 0 and verified and verified['verified']:
        verified.update(status="scheduled_and_verified", changed=True)
        return verified
    return {"verified": False, "status": "schedule_not_verified", "changed": action.get('returncode') == 0,
            "method": "shutdown", "action": action, "reason": "A successful command alone does not prove a shutdown plan."}


def main():
    shutdown_record = shutdown()  # Must precede hardware, installation or jobs.
    result = {"checked_at_utc": utc(time.time()), "shutdown": shutdown_record,
              "gpu": run(['nvidia-smi', '--query-gpu=index,name,memory.total,memory.used,driver_version', '--format=csv,noheader,nounits']),
              "gpu_processes": run(['nvidia-smi', '--query-compute-apps=pid,process_name,used_gpu_memory', '--format=csv,noheader,nounits']),
              "python": run(['python3', '--version']), "system": run(['uname', '-a']),
              "memory": run(['free', '-m']), "disks": run(['df', '-h', '/root', '/tmp']),
              "cpu": run(['lscpu']), "network": {},
              "hf_token_present": any(bool(os.environ.get(k)) for k in ('HF_TOKEN', 'HUGGING_FACE_HUB_TOKEN')),
              "hf_cached_auth_present": any(p.is_file() for p in [pathlib.Path.home()/'.cache/huggingface/token', pathlib.Path.home()/'.huggingface/token'])}
    import urllib.request
    for host in ('https://pypi.org/simple/', 'https://huggingface.co', 'https://github.com'):
        begin = time.monotonic()
        try:
            with urllib.request.urlopen(host, timeout=10) as response:
                result['network'][host] = {"status": response.status, "elapsed_ms": round((time.monotonic()-begin)*1000)}
        except Exception as error:
            result['network'][host] = {"error": type(error).__name__}
    base = pathlib.Path('/root/autodl-tmp')
    result['existing_status_files'] = [str(p) for p in base.glob('*/processing_status.csv')] if base.is_dir() else []
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
