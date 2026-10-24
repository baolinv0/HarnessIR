"""Independent software probes; no learned model is imported or invoked."""
import csv
import importlib.util
import json
import subprocess
import sys
import tempfile
import types
from itertools import combinations
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from harness.stages.execute import run_execute
from harness.stages.verify import build_verify_system
from run_baseline import _run_one

BASE = 'e1b610ef034d467c8c9172e530d38a930956a3bb'


class Editor:
    def edit(self, images, prompt):
        im = Image.new('RGB', (87, 71))
        im.putdata([((x*17+y*3) % 256, (x*5+y*23) % 256, (x*31+y*7) % 256)
                    for y in range(71) for x in range(87)])
        return im


def load_base(path, name, package=None):
    source = subprocess.check_output(['git', 'show', f'{BASE}:{path}'], cwd=ROOT, text=True)
    mod = types.ModuleType(name)
    mod.__file__ = str(ROOT / path)
    if package:
        mod.__package__ = package
    exec(compile(source, f'<base:{path}>', 'exec'), mod.__dict__)
    return mod


old_execute = load_base('harness/stages/execute.py', 'harness.stages.execute_base', 'harness.stages')
old_baseline = load_base('run_baseline.py', 'run_baseline_base')
with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    lq = root / 'lq.png'
    source = Image.new('RGB', (40, 30))
    source.putdata([((x*3+y*2) % 256, (x*7+y*3) % 256, (x*11+y*2) % 256)
                    for y in range(30) for x in range(40)])
    source.save(lq)
    for crop in [None, ((40, 30), 1024 / 40)]:
        a = old_execute.run_execute(Editor(), lq, 'restore', root / f'old_execute_{bool(crop)}', crop_back=crop)
        b = run_execute(Editor(), lq, 'restore', root / f'new_execute_{bool(crop)}', crop_back=crop)
        with Image.open(a['path']) as ia, Image.open(b['path']) as ib:
            assert ia.tobytes() == ib.tobytes()
            print(json.dumps(dict(probe='execute_pixel_equivalence', crop=bool(crop), equal=True, size=ib.size)))
    for square in [False, True]:
        for color in [False, True]:
            opts = dict(square1024=square, color_adjust=color, resume=False)
            a = old_baseline._run_one(Editor(), 'case', dict(lq=str(lq), type='mix'),
                                     root / f'old_{square}_{color}', root / f'del_old_{square}_{color}', **opts)
            b = _run_one(Editor(), 'case', dict(lq=str(lq), type='mix'),
                         root / f'new_{square}_{color}', root / f'del_new_{square}_{color}', **opts)
            with Image.open(a['output']) as ia, Image.open(b['output']) as ib:
                assert ia.tobytes() == ib.tobytes()
                print(json.dumps(dict(probe='baseline_pixel_equivalence', square=square, color=color,
                                      equal=True, size=ib.size)))
    out = root / 'blocked_archive'
    out.mkdir()
    (out / 'raw_outputs').write_text('file prevents archive directory creation')
    rec = run_execute(Editor(), lq, 'restore', out)
    assert rec['path'] and rec['error'] is None and rec['archive_error'] and not rec['native_archive_complete']
    print(json.dumps(dict(probe='archive_failure_keeps_delivery', passed=True, archive_error=rec['archive_error'])))
    out = root / 'blocked_delivery'
    out.mkdir()
    (out / 'output.png').mkdir()
    rec = run_execute(Editor(), lq, 'restore', out)
    assert rec['path'] is None and rec['error'] and Path(rec['raw_path']).is_file() and rec['raw_sha256']
    print(json.dumps(dict(probe='downstream_failure_keeps_native_receipt', passed=True)))

count = 0
for n in range(1, 6):
    for combo in combinations(['haze', 'rain', 'snow', 'lowlight', 'mix'], n):
        build_verify_system(list(combo))
        count += 1
print(json.dumps(dict(probe='valid_verifier_type_combinations', count=count)))

spec = importlib.util.spec_from_file_location('paired', ROOT / 'research/model_aware_20261024/scripts/analyze_pairs.py')
paired = importlib.util.module_from_spec(spec)
spec.loader.exec_module(paired)
rows = []
for scene in ['a', 'b']:
    for model, delta in [('qwen', 3), ('nb2', 1)]:
        for arm, value in [('shared', 10), ('aware', 10+delta)]:
            rows.append(dict(scene_id=scene, sample_id=scene, replicate='0', model=model,
                             arm=arm, metric='PSNR', value=str(value), status='ok'))
result = paired.interaction(rows, 'qwen', 'nb2', 'shared', 'aware', 'PSNR', 1,
                            expected=[('a', 'a', '0'), ('b', 'b', '0')], draws=100)
assert result['effect'] == 2 and result['cohort_bound']
print(json.dumps(dict(probe='synthetic_interaction_arithmetic_only', effect=result['effect'], cohort_bound=True)))
try:
    paired.compare(rows, 'qwen', 'shared', 'aware', 'PSNR', 1,
                   expected=[('a', 'a', '0'), ('b', 'b', '0'), ('c', 'c', '0')], draws=100)
except ValueError:
    print(json.dumps(dict(probe='two_arms_missing_same_scene_rejected', passed=True)))
else:
    raise AssertionError('Both arms omitted a frozen scene without rejection')
try:
    paired.interaction(rows+[dict(r, model='different', sample_id='different_'+r['sample_id'])
                             for r in rows if r['model']=='qwen'],
                       'qwen', 'different', 'shared', 'aware', 'PSNR', 1, draws=100)
except ValueError:
    print(json.dumps(dict(probe='cross_model_image_cohort_mismatch_rejected', passed=True)))
else:
    raise AssertionError('Different cross-model image identities accepted')
print('ALL SOFTWARE PROBES PASSED; NO MODEL QUALITY EXPERIMENT WAS RUN')
