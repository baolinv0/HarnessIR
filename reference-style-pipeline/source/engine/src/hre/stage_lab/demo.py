"""Synthetic inputs for exploring the interface without model credentials."""
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance

from .core import add_case, init_lab, list_cases, load_lab, run_stage, save_models
from .report import export_report


def run_demo(root: Path) -> dict:
    root = Path(root).resolve()
    init_lab(root)
    models = load_lab(root)['models']
    models.update({
        'demo_soft': {'provider': 'demo', 'model': 'demo-soft', 'parameters': {'gain': 1.12}},
        'demo_strong': {'provider': 'demo', 'model': 'demo-strong', 'parameters': {'gain': 1.45}},
    })
    save_models(root, models)
    names = ['demo_soft', 'demo_strong']
    case_id = 'demo'
    existing = {case['id'] for case in list_cases(root)}
    index = 1
    while case_id in existing:
        index += 1
        case_id = f'demo_{index}'
    with tempfile.TemporaryDirectory(prefix='hre-stage-demo-') as temporary:
        directory = Path(temporary)
        y, x = np.mgrid[0:320, 0:480]
        values = np.stack([25 + x / 12, 37 + y / 8, 60 + x / 12], axis=-1).astype('uint8')
        image = Image.fromarray(values)
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 225, 480, 320), fill=(36, 46, 45))
        draw.ellipse((174, 57, 278, 161), fill=(107, 85, 68))
        draw.rounded_rectangle((145, 150, 309, 310), radius=35, fill=(52, 72, 98))
        draw.rectangle((352, 35, 410, 125), fill=(200, 185, 132))
        draw.text((18, 286), 'SYNTHETIC DEMO', fill=(150, 160, 165))
        image.save(directory / 'A.png')
        ImageEnhance.Brightness(image).enhance(1.25).save(directory / 'B.png')
        add_case(root, directory / 'A.png', directory / 'B.png', case_id,
                 'Synthetic demonstration: explore stage output comparison; no real model inference.',
                 {'synthetic': True})
    diagnosed = run_stage(root, case_id, 'diagnose', names)
    planned = run_stage(root, case_id, 'plan', names, source_runs=[diagnosed[0]['id']])
    compiled = run_stage(root, case_id, 'compile', names, source_runs=[planned[0]['id']])
    executed = []
    for name, source in zip(names, compiled):
        executed.extend(run_stage(root, case_id, 'execute', [name], source_runs=[source['id']]))
    judged = []
    for source in executed:
        judged.extend(run_stage(root, case_id, 'judge', names, source_runs=[source['id']]))
    return {'synthetic': True, 'case_id': case_id,
            'runs': [row['id'] for row in diagnosed + planned + compiled + executed + judged],
            'report': str(export_report(root))}
