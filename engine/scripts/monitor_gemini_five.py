"""Read-only local RSS sampler. API server GPU/RSS are unavailable, not inferred."""
import json
import time
from datetime import datetime, timezone
from pathlib import Path
import psutil

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / 'runtime/gemini_api/five_complete_20261015/root_audit'
DIRECTORY.mkdir(parents=True, exist_ok=True)
deadline = time.monotonic() + 10800
with (DIRECTORY / 'controller_memory.jsonl').open('a', encoding='utf-8') as stream:
    while time.monotonic() < deadline:
        records = []
        for process in psutil.process_iter(['pid', 'name', 'cmdline', 'memory_info']):
            try:
                if 'run_gemini_five.py' in ' '.join(process.info['cmdline'] or []):
                    records.append(dict(pid=process.pid, rss_mib=process.memory_info().rss / 1048576))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        stream.write(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(), runner=records,
            available_mib=psutil.virtual_memory().available/1048576, api_server_memory='not_observable'))+'\n')
        stream.flush()
        if records:
            time.sleep(10)
        else:
            break
