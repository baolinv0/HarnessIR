import csv
import io
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from hre.models import file_sha256
from hre.storage import atomic_write, read_json, write_json
from .contracts import VERSION, digest, require, verify_seal
from .evidence import pool_contract_sets


def _ratio(numerator, denominator, missing=0):
    return {'numerator': numerator, 'denominator': denominator,
            'value': numerator / denominator if denominator else None,
            'missing_count': missing}


def _csv(path, columns, rows):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(rows)
    atomic_write(path, stream.getvalue().encode('utf-8'))


def write_report(root):
    root = Path(root).resolve()
    f0, state = read_json(root / 'f0.json'), read_json(root / 'case.json')
    verify_seal(f0)
    pools = read_json(root / 'artifacts.json') if (root / 'artifacts.json').exists() else {}
    selections = []
    for search_root, pool in [(root, 'B'), (root / 'pools' / 'A', 'A')]:
        for variant in ('J0', 'J1', 'J2'):
            path = search_root / 'judge' / variant / 'selection.json'
            if path.is_file():
                selection = read_json(path)
                selections.append({'pool': pool, 'variant': variant, 'status': selection['status'],
                                   'best_candidate': selection.get('best_candidate'),
                                   'eligible_count': len(selection.get('eligible_ids', []))})
    operations = []
    for journal_path in [root / 'operations.json', root / 'pools' / 'A' / 'operations.json']:
        if journal_path.exists():
            journal = read_json(journal_path)
            entries = journal.get('operations', {})
            operations.extend(entries.values() if isinstance(entries, dict) else entries)
    rows = []
    for pool, artifacts in pools.items():
        for item in artifacts:
            rows.append({'pool': pool, 'candidate_id': item['candidate_id'], 'status': item['status'],
                         'pixel_sha256': item.get('pixel_sha256'), 'duplicate_of': item.get('duplicate_of'),
                         'sha256': item.get('sha256'), 'width': item.get('width'), 'height': item.get('height'),
                         'delivered_image': item.get('delivered_image')})
    _csv(root / 'per_candidate.csv', ['pool', 'candidate_id', 'status', 'sha256', 'pixel_sha256', 'duplicate_of', 'width', 'height', 'delivered_image'], rows)
    _csv(root / 'judge_comparison.csv', ['pool', 'variant', 'status', 'best_candidate', 'eligible_count'], selections)
    _csv(root / 'per_case.csv', ['case_id', 'mode', 'status', 'selected_output'], [{'case_id': state['case_id'], 'mode': f0['config']['mode'], 'status': state['phase'], 'selected_output': state.get('selected_output')}])
    images = [('LQ', f0['source']['path'])]
    seen = set()
    for row in rows:
        if row['candidate_id'] not in seen and row.get('delivered_image'):
            seen.add(row['candidate_id'])
            images.append((row['candidate_id'], row['delivered_image']))
    sheet = Image.new('RGB', (320 * 4, 280 * math.ceil(len(images) / 4)), 'white')
    draw = ImageDraw.Draw(sheet)
    for index, (title, path) in enumerate(images):
        with Image.open(path) as image:
            image = image.convert('RGB')
            image.thumbnail((300, 240))
            left, top = index % 4 * 320, index // 4 * 280
            sheet.paste(image, (left + 10, top + 30))
            draw.text((left + 5, top + 5), title[:46], fill='black')
    sheet.save(root / 'contact_sheet.png')
    lines = ['# Restoration candidates report', '',
             f"Case `{state['case_id']}`. Mode `{f0['config']['mode']}`. State `{state['phase']}`.", '',
             'Fixture outputs are synthetic software checks and cannot establish restoration quality.' if f0['config']['mode'] == 'fixture' else 'Real outputs require independent offline content and quality evaluation.', '',
             '## Configuration', '', f"Task `{f0['task']['task_mode']}`. Policy `{f0['task']['usage_policy']}`. F0 `{f0['freeze_hash']}`.", '',
             '## Coverage', '', f"B pool has {len(pools.get('B', []))} recorded slots; A pool has {len(pools.get('A', []))} recorded slots.",
             'See per_candidate.csv for produced, failed and missing outputs.', '',
             '## Judge selection', '', '| Pool | Judge | Status | Selected | Eligible |', '|---|---|---|---|---|']
    lines.extend(f"| {x['pool']} | {x['variant']} | {x['status']} | {x['best_candidate']} | {x['eligible_count']} |" for x in selections)
    if not any(x['variant'] == 'J2' for x in selections):
        lines.extend(['', 'J2 = not_run.'])
    lines.extend(['', '## Content errors', '', 'Per-attribute online assessments remain under judge/. Independent GT evaluation belongs only in offline/.', '',
                  '## Prompt effect', '', 'See plan/plan.json for exact prompts, preserved requirements, axis mapping and fallback reasons. Same-seed causal claims require preregistered E2 observations.', '',
                  '## Cost', '', f"Recorded operations: {len(operations)}. Actual fees are unknown unless supplied by bound provider receipts.", '',
                  '## Failure cases', '', str(state.get('error') or 'No terminal case error recorded. Individual candidate and measurement failures remain in their own records.'), '',
                  '## Decision', '', f"Selected output: {state.get('selected_output') or 'null'}.", '',
                  '## Next experiment', '', 'Complete independent Oracle annotation. Preserve failed cases and frozen denominators. Never feed GT or Oracle labels back into online decisions.', '',
                  '![Full-frame contact sheet](contact_sheet.png)', ''])
    path = root / 'report.md'
    atomic_write(path, '\n'.join(lines).encode('utf-8'))
    return path


def evaluate_offline(root, labels, gt=None):
    root = Path(root).resolve()
    f0 = read_json(root / 'f0.json')
    verify_seal(f0)
    pools = read_json(root / 'artifacts.json')
    artifacts = {x['candidate_id']: x for group in pools.values() for x in group}
    for artifact in artifacts.values():
        if artifact.get('status') == 'completed':
            path = artifact.get('delivered_image')
            require(path and Path(path).is_file() and file_sha256(Path(path)) == artifact.get('sha256'),
                    'output_modified', 'Actual image bytes differ from the candidate bound to offline labels')
    items = labels.get('labels', [])
    require(isinstance(items, list), 'oracle_invalid', 'labels must be an independent annotation list')
    annotated, quality_acceptable, acceptable = set(), set(), set()
    for item in items:
        cid = item.get('candidate_id')
        require(cid in artifacts and cid not in annotated, 'oracle_invalid', 'Unknown or duplicate candidate label')
        require(item.get('candidate_hash') == artifacts[cid].get('sha256') and item.get('candidate_hash'), 'oracle_binding_mismatch', 'Labels must bind exact candidate bytes')
        require(type(item.get('acceptable')) is bool, 'oracle_invalid', 'acceptable must be boolean')
        annotated.add(cid)
        require(type(item.get('contract_valid', True)) is bool, 'oracle_invalid', 'contract_valid must be boolean when supplied')
        if item['acceptable']:
            quality_acceptable.add(cid)
        if item['acceptable'] and item.get('contract_valid', True):
            acceptable.add(cid)
    best_sets = labels.get('best_sets', {})
    require(isinstance(best_sets, dict), 'oracle_invalid', 'best_sets must be an object')
    best_value = best_sets.get('B', labels.get('best_set'))
    require(best_value is None or isinstance(best_value, list), 'oracle_invalid', 'Independent best set must be a list')
    best = set(best_value or [])
    b_ids = {x['candidate_id'] for x in pools['B']}
    require(best <= b_ids & quality_acceptable, 'oracle_invalid', 'Best set must belong to its independently quality-acceptable pool')
    selection = read_json(root / 'selection.json') if (root / 'selection.json').exists() else {}
    if selection:
        verify_seal(selection)
    selected = selection.get('best_candidate')
    produced_ids = {x['candidate_id'] for x in pools['B'] if x.get('status') == 'completed'}
    unaccounted_slots = {x['candidate_id'] for x in pools['B'] if x.get('status') not in {'completed', 'failed', 'contract_fail'}}
    complete = produced_ids <= annotated and not unaccounted_slots
    bundle_path = root / 'evidence' / 'bundle.json'
    contract = pool_contract_sets(read_json(bundle_path) if bundle_path.is_file() else {}, b_ids)
    valid = produced_ids & contract['passed']
    b_acceptable = b_ids & acceptable & valid
    best_available = bool(best) and best <= b_acceptable
    eligible = set(selection.get('eligible_ids', []))
    result = {'schema_version': VERSION, 'fixture_only': f0['config']['mode'] == 'fixture',
              'research_eligible': f0['config']['mode'] == 'real', 'oracle_complete': complete,
              'produced_coverage': _ratio(len(produced_ids), 4, len(unaccounted_slots)),
              'contract_valid_coverage': _ratio(len(valid), 4, 4 - len(contract['passed'] | contract['failed'])),
              'oracle_pass_at_4': _ratio(int(bool(b_acceptable)), 1, len(produced_ids - annotated) + len(unaccounted_slots)),
              'selected_pass': _ratio(int(complete and selected in b_acceptable), 1, int(not complete)),
              'conditional_selection_success': _ratio(int(complete and selected in b_acceptable), int(bool(b_acceptable))),
              'best_in_pool_agreement': _ratio(int(complete and best_available and selected in best),
                                              int(complete and bool(b_acceptable) and best_available),
                                              int(not complete or bool(b_acceptable) and not best_available)),
              'avoidable_unresolved': _ratio(int(selected is None and bool(b_acceptable)), int(bool(b_acceptable)), int(not complete)),
              'false_reject': _ratio(len(b_acceptable - eligible) if complete else 0, len(b_acceptable) if complete else 0, int(not complete)),
              'false_accept': _ratio(int(selected is not None and selected not in b_acceptable) if complete else 0, int(selected is not None) if complete else 0, int(not complete)),
              'eligible_false_accept': _ratio(len(eligible - b_acceptable) if complete else 0, len(eligible) if complete else 0, int(not complete)),
              'labels_hash': digest(labels), 'online_selection_hash': digest(selection), 'gt_metrics': {}}
    if gt:
        with Image.open(gt) as image:
            truth = np.asarray(image.convert('RGB'), dtype=np.float64)
        for cid, item in artifacts.items():
            if not item.get('delivered_image'):
                continue
            with Image.open(item['delivered_image']) as image:
                predicted = np.asarray(image.convert('RGB'), dtype=np.float64)
            require(predicted.shape == truth.shape, 'gt_geometry_mismatch', 'GT geometry must equal delivered output')
            mse = float(np.mean((predicted - truth) ** 2))
            result['gt_metrics'][cid] = {'mse': mse, 'psnr': 10 * math.log10(255**2 / mse) if mse else None, 'perfect_match': mse == 0}
        result['gt_sha256'] = file_sha256(Path(gt))
    write_json(root / 'offline' / 'oracle_labels.json', labels)
    write_json(root / 'offline' / 'metrics.json', result)
    return result
