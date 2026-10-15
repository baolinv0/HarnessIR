"""A separate real-photo SAM3.1 alternative study, with manual desktop handoff.

No inference, image editing, or verifier response is fabricated by this helper.
Only strictly matching normalized caches can satisfy the diagnostic tool plan.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'engine/src'))
from hir_manual.service import Controller, history
from hir_manual.storage import read_json, write_json, sha256_file, atomic_write, now
from hir_manual.tool_service import ToolService

STUDY = ROOT / 'runtime/sam31_flow/commons_001'
PROFILE = 'gpu_sam31_v5'
DIRECT = ('Restore this photograph conservatively. Reduce visible noise and blur where the original supports an improvement, '
          'and improve visibility without changing the scene or its lighting character. Preserve the original framing, perspective, '
          'objects, people, facial identity, text, colours, and natural texture. Do not invent missing details, replace unreadable text, '
          'beautify faces, add or remove objects, or introduce sharpening halos. Return one restored photograph with the same aspect ratio.')


def prepare():
    if (STUDY / 'study.json').exists():
        return read_json(STUDY / 'study.json')
    batch = ROOT / 'runtime/quality20/pilot20_20261013_stable_v2'
    row = next(r for r in read_json(batch / 'manifest.json')['images'] if r['sample_id'] == 'commons_001')
    source = Path(row['input_path'])
    if sha256_file(source) != row['original_sha256']:
        raise ValueError('Original differs from frozen input')
    ctl = Controller(ROOT)
    config = dict(evidence_profile_id=PROFILE, auto_local_tools=False, branch_type='manual_variant',
                  experiment_condition='SAM31_independent_alternative', formal_experiment_eligible=False,
                  desktop_original_rgb_equivalent_upload=False, executor='chatgpt_desktop_image')
    intent = 'Conservatively improve the noisy, motion-softened night photograph while preserving its scene, geometry, text, and night lighting.'
    arms = {}
    for arm, limit in [('harness', 3), ('direct', 1)]:
        state = ctl.new(source, intent, {**config, 'max_generations': limit, 'experiment_arm': arm})
        if state.input_sha256 != row['canonical_sha256']:
            ctl.operate(state.case_id, 'pause')
            raise ValueError('New canonical differs from frozen source; new case paused')
        arms[arm + '_case_id'] = state.case_id
    study = dict(image_id='commons_001', created_at=now(), formal_eligible=False,
                 original_sha256=row['original_sha256'], canonical_sha256=row['canonical_sha256'],
                 evidence_profile_id=PROFILE, executor='ChatGPT desktop original + text only',
                 verifier='independent fresh session, no editor instructions', **arms)
    write_json(STUDY / 'study.json', study)
    return study


def submit_payload(role, file, model, arm='harness', session=None, writer='local_work'):
    study = prepare(); ctl = Controller(ROOT); case_id = study[arm + '_case_id']
    req = ctl.current_task(case_id)
    if not req or req.role != role:
        raise ValueError('Current task is not ' + role)
    result = ctl.import_json(case_id, req.task_id, json.dumps(read_json(file), ensure_ascii=False), model,
                             ctl.provenance(model, 'file', writer, session))
    if not result.accepted:
        raise ValueError(result.message)
    return ctl.inspect(case_id).model_dump()


def diagnose(file, model, session=None):
    study = prepare(); ctl = Controller(ROOT)
    for arm in ('harness', 'direct'):
        req = ctl.current_task(study[arm + '_case_id'])
        if req and req.role == 'diagnose':
            submit_payload('diagnose', file, model, arm, session)
    # A declared fixed Direct baseline consumes no auxiliary evidence.
    state = ctl.inspect(study['direct_case_id'])
    if state.workflow_status == 'WAIT_EVIDENCE':
        for tool in state.required_tools:
            if tool not in state.received_tools and tool not in ctl.excluded_tools(state.case_id):
                ctl.operate(state.case_id, 'skip_tool', tool + ':Declared fixed Direct baseline excludes auxiliary evidence')
    return handoff()


def evidence():
    study = prepare(); ctl = Controller(ROOT)
    state = ctl.inspect(study['harness_case_id'])
    if state.workflow_status == 'WAIT_EVIDENCE':
        # ToolService resolves exact frozen contracts. Cache-only SAM3.1 missing
        # records are unavailable, never sent to another segmentation model.
        state = ToolService(ROOT).run_case(state.case_id)
    return handoff()


def direct():
    study = prepare(); ctl = Controller(ROOT); req = ctl.current_task(study['direct_case_id'])
    if not req or req.role != 'compose':
        return handoff()
    payload = dict(task_type='conservative_restoration', treat=['visible degradations conservatively'],
                   preserve=['scene, framing, text, natural texture, lighting'], region_notes=[], evidence_used=[], instruction=DIRECT)
    result = ctl.import_json(req.case_id, req.task_id, json.dumps(payload), 'Fixed Direct preset (not model inference)',
                             ctl.provenance('Fixed Direct preset (not model inference)', 'clipboard_import', 'manual_import'))
    if not result.accepted:
        raise ValueError(result.message)
    return handoff()


def import_edit(arm, file, model, session=None, extras=()):
    study = prepare(); ctl = Controller(ROOT); case_id = study[arm + '_case_id']
    req = ctl.current_task(case_id)
    if not req or req.role != 'execute':
        raise ValueError('Arm is not waiting for actual editor output')
    from hir_manual.transport import image_observations
    case = ctl.case(case_id); canonical = case.path('input/canonical.png'); config = read_json(case.path('case_config.json'))
    source_pixels = image_observations(canonical, canonical, config)['pixel_sha256']
    for generated in [file, *extras]:
        if image_observations(Path(generated), canonical, config)['pixel_sha256'] == source_pixels:
            raise ValueError('An unchanged source copy is not a generated editor output')
    result = ctl.import_image(case_id, req.task_id, Path(file), model,
                              ctl.provenance(model, 'file', 'manual_import', session),
                              extras=[Path(p) for p in extras], actual_generations=1 + len(extras))
    if not result.accepted:
        raise ValueError(result.message)
    return handoff()


def handoff():
    study = prepare(); ctl = Controller(ROOT); status = dict(recorded_at=now(), formal_eligible=False, arms={})
    for arm in ('harness', 'direct'):
        case_id = study[arm + '_case_id']; state = ctl.inspect(case_id); case = ctl.case(case_id)
        req = ctl.current_task(case_id); rounds = history(case)['rounds']
        status['arms'][arm] = dict(case_id=case_id, workflow_status=state.workflow_status,
            operation_status=state.operation_status, consumed=state.budget.consumed, restoration_success=state.restoration_success,
            first_round=next((r for r in rounds if r['round'] == 1 and r.get('output_asset')), None),
            final_round=next((r for r in rounds if r['round'] == state.selected_round and r.get('output_asset')), None),
            independent_verifications=sum('verification' in r for r in rounds))
        if req:
            directory = STUDY / 'handoff' / arm / req.task_id
            atomic_write(directory / 'prompt.txt', case.path(req.prompt_file).read_bytes())
            write_json(directory / 'request.json', req)
            write_json(directory / 'attachments.json', {'assets': [{**a.model_dump(), 'absolute_path': str(case.path(a.path))} for a in req.allowed_assets]})
            if req.role == 'execute':
                if [a.path for a in req.allowed_assets] != ['input/canonical.png'] or 'evidence' in req.context:
                    raise ValueError('Executor isolation violated')
            if req.role == 'verify' and any(k in req.context for k in ('instruction', 'evidence', 'diagnosis')):
                raise ValueError('Independent verifier isolation violated')
    status['full_real_flow_passed'] = all(ctl.inspect(v['case_id']).workflow_completed and v['consumed'] > 0 and v['independent_verifications'] > 0 for v in status['arms'].values())
    status['desktop_actual_generations'] = sum(v['consumed'] for v in status['arms'].values())
    write_json(STUDY / 'current_status.json', status)
    return status


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['prepare', 'diagnose', 'evidence', 'direct', 'compose', 'refine', 'handoff', 'import-edit', 'import-verification'])
    p.add_argument('--file', type=Path); p.add_argument('--model'); p.add_argument('--session')
    p.add_argument('--arm', choices=['harness', 'direct'], default='harness'); p.add_argument('--extra', type=Path, action='append', default=[])
    a = p.parse_args()
    if a.action == 'diagnose': value = diagnose(a.file, a.model, a.session)
    elif a.action in ('compose', 'refine'): value = submit_payload(a.action, a.file, a.model, a.arm, a.session)
    elif a.action == 'import-verification': value = submit_payload('verify', a.file, a.model, a.arm, a.session, 'manual_import')
    elif a.action == 'import-edit': value = import_edit(a.arm, a.file, a.model, a.session, a.extra)
    else: value = globals()[a.action]()
    print(json.dumps(value, ensure_ascii=False, indent=2))
