"""Serial, per-image normalized-cache imports with sampled memory/cost logs."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import psutil
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'engine/src'))
from hir_manual.sam31_evidence import RAW_CONTRACT, RUN_ID
from hir_manual.storage import read_json, write_json, now

def main():
    directory = ROOT / 'runtime/sam31_normalization/batch_png_v2'
    directory.mkdir(parents=True, exist_ok=True)
    native = ROOT / 'Data/annotations/cache/alternatives/SAM31' / RAW_CONTRACT / RUN_ID
    rows = read_json(native / 'inputs.json')['images']
    config = dict(policy='normalization_only_v1', model_inference=False, workers=1, cpu_threads=2,
                  min_available_mib=768, abort_available_mib=256, max_rss_mib=768,
                  timeout_seconds=1800, memory_sample_seconds=.2)
    write_json(directory / 'configuration.json', config)
    records = []
    for row in rows:
        image_id = row['image_id']; started = time.monotonic()
        if psutil.virtual_memory().available / 2**20 < config['min_available_mib']:
            records.append(dict(image_id=image_id, status='resource_wait', at=now(), inference=False))
            write_json(directory / 'summary.json', dict(records=records, completed=False)); break
        env = dict(os.environ, OMP_NUM_THREADS='2', MKL_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2', NUMEXPR_NUM_THREADS='2')
        process = subprocess.Popen([sys.executable, str(ROOT / 'engine/scripts/import_sam31_evidence.py'), '--image-id', image_id],
            cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        peak = 0.; error = None
        while process.poll() is None:
            try:
                worker = psutil.Process(process.pid)
                rss = sum(p.memory_info().rss for p in [worker, *worker.children(recursive=True)] if p.is_running()) / 2**20
                peak = max(peak, rss)
            except psutil.Error:
                pass
            if peak > config['max_rss_mib']: error = 'normalization_rss_limit'
            elif psutil.virtual_memory().available / 2**20 < config['abort_available_mib']: error = 'normalization_memory_pressure'
            elif time.monotonic() - started > config['timeout_seconds']: error = 'normalization_timeout'
            if error:
                process.terminate(); break
            time.sleep(config['memory_sample_seconds'])
        stdout, stderr = process.communicate(timeout=30)
        record = dict(image_id=image_id, at=now(), elapsed_seconds=time.monotonic()-started,
                      peak_rss_mib_sampled=peak, returncode=process.returncode, process_released=not psutil.pid_exists(process.pid),
                      inference=False, error=error)
        (directory / (image_id + '.stdout.log')).write_bytes(stdout)
        (directory / (image_id + '.stderr.log')).write_bytes(stderr)
        if process.returncode == 0 and not error:
            record.update(json.loads(stdout.decode('utf-8')))
        else:
            record['status'] = 'failed'
        records.append(record)
        write_json(directory / 'summary.json', dict(configuration=config, records=records, completed=len(records)==len(rows)))
        print(json.dumps(record, ensure_ascii=False), flush=True)
    return 0 if len(records) == len(rows) and all(r['status'] in ('imported', 'existing') for r in records) else 2

if __name__ == '__main__': raise SystemExit(main())
