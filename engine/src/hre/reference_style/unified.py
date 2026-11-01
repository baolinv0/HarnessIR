"""Explicit semantic/delivery extensions around immutable historical style records."""
from copy import deepcopy
import json
from pathlib import Path

from hre.models import canonical_json, file_sha256, sha256_bytes
from hre.storage import case_lock
from hre.reference_core.contracts import validate_semantics
from hre.reference_core.rendering import render_target_limits
from hre.reference_core.delivery import preflight, assess_delivery
from .contracts import require, exact, record, validate_record
from .s2_evidence import code
from . import coordinator as co, s2_store as store


def _write(root, relative, sample_id, kind, payload):
    path = co._path(root, relative)
    if path.exists():
        previous = co._load(root, relative)
        require(previous['kind'] == kind and previous['payload'] == payload, 'Unified record is immutable')
        return previous
    result = record(sample_id, kind, payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    co._immutable_bytes(root, relative, canonical_json(result))
    return result


def active(root, target_version=None):
    directory = co._path(root, 'unified/contracts')
    if not directory.exists(): return None
    records = []
    for path in directory.glob('u*.json'):
        item = co._load(root, path.relative_to(root).as_posix())
        records.append(item)
    records.sort(key=lambda x: int(x['payload']['version'][1:]))
    if records:
        state = co._load(root, 'state.json')
        audit = co._load(root, 'input_audit.json')
    for n, item in enumerate(records):
        p = item['payload']; validate_semantics(p['semantics'])
        require(item['sample_id'] == state['sample_id'] and p['input_audit_hash'] == audit['content_hash'],
                'Unified semantics belong to different frozen inputs')
        require(p['version'] == 'u' + str(n + 1) and p['predecessor_hash'] == (None if not n else records[n - 1]['content_hash']),
                'Unified semantic revision chain changed')
    matches = records if target_version is None else [r for r in records if r['payload']['target_version'] == target_version]
    return matches[-1] if matches else None


def freeze_semantics(root, spec):
    optional = ('basis',) if spec.get('outcome') == 'already_satisfied' else ()
    exact(spec, ('version', 'outcome', 'target_version', 'semantics') + optional)
    code(spec['version'], 'u')
    require(spec['outcome'] in ('edit', 'already_satisfied'), 'Explicit edit/no-edit outcome required')
    semantics = validate_semantics(spec['semantics'])
    with case_lock(root):
        state = co._status(root); require(state['payload']['active_attempt'] is None, 'Resolve the pending observation first')
        old = active(root)
        require(spec['version'] == ('u1' if old is None else 'u' + str(int(old['payload']['version'][1:]) + 1)), 'Extend the semantic version chain')
        audit = co._load(root, 'input_audit.json')
        if spec['outcome'] == 'edit':
            code(spec['target_version'], 'v')
            target = store.get(root, state, 'targets', spec['target_version'])
            require([t['target_id'] for t in semantics['targets']] == [t['target_id'] for t in target['payload']['targets']],
                    'Semantic inventory must cover exactly the frozen execution targets')
            require(old is None or old['payload']['target_hash'] != target['content_hash'],
                    'Changed semantic criteria require an explicit target revision')
            if old is None:
                require(not any(a['stage_id'] == 'edit' for a in state['payload']['attempts']), 'Freeze task criteria before first generation')
            target_hash = target['content_hash']; basis = None
        else:
            require(old is None and spec['target_version'] is None and not semantics['targets'], 'No-edit needs a new closed, target-free contract')
            require(all(c['status'] in ('preserve', 'already_satisfied', 'not_applicable', 'excluded') for c in semantics['coverage']),
                    'No-edit cannot hide an unresolved dimension')
            require(not any(a['stage_id'] == 'edit' for a in state['payload']['attempts']), 'No-edit success cannot follow a generation')
            basis = spec['basis']; exact(basis, ('report_id', 'diagnosis_record_id', 'requested_operation', 'observation'))
            require(basis['requested_operation'] == 'match_reference_appearance_only' and isinstance(basis['observation'], str) and basis['observation'].strip(),
                    'No-edit must address an explicit appearance-only request')
            from .s2_stage import _diagnosis
            report = store.get(root, state, 'reports', basis['report_id'])
            diagnosis = _diagnosis(root, state, basis['diagnosis_record_id'], report)
            basis = dict(deepcopy(basis), report_hash=report['content_hash'], diagnosis_hash=diagnosis['content_hash'],
                         truth_basis='operator_projection_of_actual_imported_AB_review_not_automatic_visual_truth')
            target_hash = None
        payload = dict(version=spec['version'], outcome=spec['outcome'], target_version=spec['target_version'], target_hash=target_hash,
                       semantics=semantics, basis=basis, input_audit_hash=audit['content_hash'],
                       predecessor_hash=None if old is None else old['content_hash'], semantic_schema='reference_unified_semantics_v1')
        return _write(root, 'unified/contracts/' + spec['version'] + '.json', state['sample_id'], 'unified_semantics', payload)


def extend_prompt(root, target, prompt):
    frozen = active(root, target['payload']['version'])
    if frozen is None: return prompt, None
    require(frozen['payload']['outcome'] == 'edit' and frozen['payload']['target_hash'] == target['content_hash'], 'Semantic target binding changed')
    limits = '\n'.join(render_target_limits(t) for t in frozen['payload']['semantics']['targets'])
    return prompt + '\nUnified frozen reference facts, limits and completion criteria:\n' + limits, frozen


def public_semantics(root, target):
    frozen = active(root, target['payload']['version'])
    if frozen is None: return None
    require(frozen['payload']['target_hash'] == target['content_hash'], 'Unified public target changed')
    keys = ('target_id', 'attribute', 'source_observation', 'reference_observation', 'comparability',
            'uncertainty', 'mandatory', 'acceptance_criterion', 'source_region', 'reference_region')
    return dict(version=frozen['payload']['version'], hash=frozen['content_hash'],
                coverage=deepcopy(frozen['payload']['semantics']['coverage']),
                targets=[{k: deepcopy(t[k]) for k in keys if k in t} for t in frozen['payload']['semantics']['targets']])


def record_preflight(root, spec):
    exact(spec, ('semantic_version', 'planned_size', 'capability_known')); code(spec['semantic_version'], 'u')
    with case_lock(root):
        state = co._status(root); frozen = active(root)
        require(frozen is not None and frozen['payload']['version'] == spec['semantic_version'] and frozen['payload']['outcome'] == 'edit', 'Current edit semantics required')
        audit = co._load(root, 'input_audit.json'); source = audit['payload']['images'][0]
        assessment = preflight(source['oriented_size'], spec['planned_size'], frozen['payload']['semantics']['delivery_requirements'], capability_known=spec['capability_known'])
        return _write(root, 'unified/preflight/' + spec['semantic_version'] + '.json', state['sample_id'], 'unified_preflight',
                      dict(semantic_hash=frozen['content_hash'], plan=deepcopy(spec), assessment=assessment,
                           basis='explicit_declared_backend_content_size_not_remote_capability_authentication'))


def check_compiled(root, compiled):
    p = compiled['payload']; frozen = active(root, p['target_version'])
    if frozen is None: return
    require(p.get('unified_semantics_hash') == frozen['content_hash'] and p.get('unified_semantic_version') == frozen['payload']['version'],
            'Recompile against frozen unified semantics')
    require(not co._path(root, 'unified/no_edit.json').exists(), 'Case completed without editing')
    assessment = co._load(root, 'unified/preflight/' + frozen['payload']['version'] + '.json')
    require(assessment['payload']['semantic_hash'] == frozen['content_hash'] and assessment['payload']['assessment']['status'] != 'infeasible',
            'Known-infeasible delivery must stop before image reservation')


def guard_export(root, stage_id, extra):
    frozen = active(root)
    if frozen is None or stage_id != 'edit': return
    require(frozen['payload']['outcome'] == 'edit' and not co._path(root, 'unified/no_edit.json').exists(), 'Successful no-edit is terminal')
    require(isinstance(extra, dict) and extra.get('binding_kind') == 'compiled_edit', 'Unified edits require measured compiled-export path')


def _detail_binding(root,state,evaluation):
    from .s4_selected import require_selected
    e=evaluation['payload'];derived=require_selected(root,state,evaluation);d=derived['payload'];audit=d['audit']
    require(audit is not None and e['selected_artifact'] is not None,'Native-detail review requires a usable native C and selected display')
    source=co._load(root,'input_audit.json')['payload']['images'][0]
    require(file_sha256(co._path(root,d['raw_output_path'],True))==e['raw_candidate_hash'],'Native candidate bytes changed')
    require(file_sha256(co._path(root,source['source_path'],True))==source['source_file_hash'],'Native source bytes changed')
    return dict(source_sha256=source['source_file_hash'],native_sha256=e['raw_candidate_hash'],native_size=audit['native_size'],
                result_hash=e['response_hash'],evaluation_hash=evaluation['content_hash'],selected_sha256=e['selected_artifact']['file_hash'])


def detail_request(root,evaluation_id):
    """Actual native artifacts for an independent review; this makes no judgement."""
    from hre.reference_core.native_detail import KEYS
    with case_lock(root):
        state=co._status(root);ev=store.get(root,state,'evaluations',evaluation_id);binding=_detail_binding(root,state,ev)
        require(active(root,ev['payload']['evaluation_target_version']) is not None,'Detail extension requires explicit unified semantics')
        source=co._load(root,'input_audit.json')['payload']['images'][0]
        derived=store.by_id(root,state,'candidate_derivatives',ev['payload']['derived_record_id'])
        prior=_detail_records(root,state,ev)
        return dict(evaluation_id=evaluation_id,binding=binding,review_schema='hre_native_detail_review_v1',required_fields=list(KEYS),
            predecessor_hash=None if not prior else prior[-1]['content_hash'],review_hashes=[r['content_hash'] for r in prior],
            images=[dict(role='source_native',path=str(co._path(root,source['source_path'],True)),sha256=binding['source_sha256']),
                    dict(role='candidate_native',path=str(co._path(root,derived['payload']['raw_output_path'],True)),sha256=binding['native_sha256'])],
            instruction='Inspect exact native C against frozen native A at 1:1 or native zoom. Declare detail pass/fail/unknown, confidence, independence and exposure. An enlarged selected preview cannot prove source-detail preservation.')


def _detail_records(root,state,evaluation):
    from hre.reference_core.native_detail import validate_detail
    directory=co._path(root,'unified/detail/'+evaluation['payload']['evaluation_id'])
    if not directory.exists():return []
    binding=_detail_binding(root,state,evaluation);records=[co._load(root,p.relative_to(root).as_posix()) for p in directory.glob('*.json')]
    records.sort(key=lambda r:r['payload']['sequence'])
    previous=None
    for n,r in enumerate(records):
        p=r['payload'];exact(p,('evaluation_id','predecessor_hash','resolves_hashes','detail','sequence'))
        require(r['sample_id']==state['sample_id'] and r['kind']=='unified_native_detail' and p['evaluation_id']==evaluation['payload']['evaluation_id'], 'Detail review sample/evaluation mismatch')
        require(p['sequence']==n+1 and p['predecessor_hash']==previous,'Broken native-detail predecessor/sequence')
        require(isinstance(p['resolves_hashes'],list) and (not p['resolves_hashes'] or p['resolves_hashes']==[prior['content_hash'] for prior in records[:n]]),
                'Detail resolution must explicitly bind all previous review records')
        validate_detail(p['detail'],binding);previous=r['content_hash']
    return records


def import_detail(root,spec):
    from hre.reference_core.native_detail import validate_detail
    exact(spec,('evaluation_id','predecessor_hash','resolves_hashes','detail'));code(spec['evaluation_id'],'j')
    with case_lock(root):
        state=co._status(root);ev=store.get(root,state,'evaluations',spec['evaluation_id'])
        require(active(root,ev['payload']['evaluation_target_version']) is not None,'Detail extension requires explicit unified semantics')
        validate_detail(spec['detail'],_detail_binding(root,state,ev));prior=_detail_records(root,state,ev)
        replay=[r for r in prior if r['payload']['detail']['review_id']==spec['detail']['review_id']]
        if replay:
            require({k:replay[0]['payload'][k] for k in spec}==spec,'Conflicting detail review replay');return replay[0]
        require(spec['predecessor_hash']==(None if not prior else prior[-1]['content_hash']),'Detail review must bind the exact current predecessor')
        require(isinstance(spec['resolves_hashes'],list) and (not spec['resolves_hashes'] or spec['resolves_hashes']==[r['content_hash'] for r in prior]),
                'A detail adjudication must explicitly cite all earlier observations')
        return _write(root,'unified/detail/'+spec['evaluation_id']+'/'+spec['detail']['review_id']+'.json',state['sample_id'],'unified_native_detail',
            dict(**deepcopy(spec),sequence=len(prior)+1))


def detail_for_evaluation(root,state,evaluation):
    from hre.reference_core.native_detail import detail_status
    records=_detail_records(root,state,evaluation)
    if not records:return dict(status='uncertain',review_hashes=[],unresolved_conflict=False)
    latest=records[-1];effective=detail_status(latest['payload']['detail'])
    last_resolution=next((n for n in range(len(records)-1,-1,-1) if records[n]['payload']['resolves_hashes'] and detail_status(records[n]['payload']['detail'])!='uncertain'),0)
    known={detail_status(r['payload']['detail']) for r in records[last_resolution:]};known.discard('uncertain')
    conflict=len(known)>1
    return dict(status='uncertain' if conflict else effective,review_hashes=[r['content_hash'] for r in records],
        latest_review_hash=latest['content_hash'],unresolved_conflict=conflict)


def delivery_for_evaluation(root, state, evaluation, detail=None):
    e = evaluation['payload']; frozen = active(root, e['evaluation_target_version'])
    if frozen is None: return None
    require(detail is None,'Import a bound native-detail observation; an unbound detail status is not evidence')
    require(frozen['payload']['target_hash'] == e['evaluation_target_hash'], 'Delivery semantic target changed')
    from .s4_selected import require_selected
    derived = require_selected(root, state, evaluation); audit = derived['payload']['audit']
    source = co._load(root, 'input_audit.json')['payload']['images'][0]
    native = None if audit is None else audit['oriented_size']
    detail_evidence=detail_for_evaluation(root,state,evaluation)
    return dict(**assess_delivery(source['oriented_size'], native, frozen['payload']['semantics']['delivery_requirements'], detail=detail_evidence['status'],
                           geometry_valid=audit is not None),native_detail_evidence=detail_evidence)


def complete_no_edit(root):
    with case_lock(root):
        state = co._status(root); frozen = active(root)
        require(frozen is not None and frozen['payload']['outcome'] == 'already_satisfied', 'Closed reviewed no-edit contract required')
        require(state['payload']['active_attempt'] is None and not any(a['stage_id'] == 'edit' for a in state['payload']['attempts']), 'No-edit needs zero image attempts')
        source = co._load(root, 'input_audit.json')['payload']['images'][0]
        delivery = assess_delivery(source['oriented_size'], source['oriented_size'], frozen['payload']['semantics']['delivery_requirements'], detail='pass')
        return _write(root, 'unified/no_edit.json', state['sample_id'], 'unified_no_edit',
                      dict(status='already_satisfied' if delivery['pass'] else 'delivery_not_met', semantic_hash=frozen['content_hash'],
                           source_path=source['derivative_path'], source_hash=source['derivative_file_hash'], delivery=delivery,
                           image_calls=0, compiler_calls=0, selected_kind='source_already_satisfied', training_label_status='not_certified'))


def import_holistic(root, spec):
    from hre.reference_core.evaluation import append_review
    with case_lock(root):
        state = co._status(root); require(active(root) is not None, 'Freeze unified semantics before reviewing')
        require(spec.get('sample_id') == state['sample_id'], 'Holistic review sample mismatch')
        images = spec.get('images', [])
        require(isinstance(images, list) and len(images) == 3 and [i.get('role') for i in images] == ['A', 'B', 'C'], 'Holistic review needs A/B/C')
        audit = co._load(root, 'input_audit.json')['payload']['images']
        require(all(images[n]['sha256'] == audit[n]['derivative_file_hash'] for n in (0, 1)), 'Review original frozen A/B displays')
        candidates = [store.get(root, state, 'candidate_derivatives', key) for key in store.registry(state)['candidate_derivatives']]
        require(any(c['payload']['audit'] is not None and c['payload']['audit']['derivative_file_hash'] == images[2]['sha256'] for c in candidates),
                'Review an actual imported selected C, not an unrelated image')
        return append_review(co._path(root, 'unified/holistic/' + images[2]['sha256']), spec)


def holistic_report(root, candidate_hash):
    from .contracts import digest
    from hre.reference_core.evaluation import render_report
    digest(candidate_hash); co.status(root)
    return render_report(co._path(root, 'unified/holistic/' + candidate_hash))


def resolve_holistic(root,spec):
    from hre.reference_core.evaluation import append_resolution
    with case_lock(root):
        state=co._status(root);require(active(root) is not None and spec.get('sample_id')==state['sample_id'],'Frozen unified sample required')
        images=spec.get('images',[])
        require(isinstance(images,list) and len(images)==3 and [i.get('role') for i in images]==['A','B','C'],'Resolution requires exact A/B/C images')
        audit=co._load(root,'input_audit.json')['payload']['images']
        require(all(images[n]['sha256']==audit[n]['derivative_file_hash'] for n in (0,1)),'Resolve against frozen A/B displays')
        candidates=[store.get(root,state,'candidate_derivatives',key) for key in store.registry(state)['candidate_derivatives']]
        require(any(c['payload']['audit'] is not None and c['payload']['audit']['derivative_file_hash']==images[2]['sha256'] for c in candidates),
                'Resolution must bind an actual selected C')
        return append_resolution(co._path(root,'unified/holistic/'+images[2]['sha256']),spec)


def holistic_for_evaluation(root, evaluation):
    from hre.reference_core.evaluation import read_reviews, STAGES,conflict_state
    e = evaluation['payload']; frozen = active(root, e['evaluation_target_version'])
    if frozen is None: return None
    artifact = e.get('selected_artifact')
    if artifact is None: return {'status': 'needs_user_review', 'reason': 'No usable selected display'}
    reviews = read_reviews(co._path(root, 'unified/holistic/' + artifact['file_hash']))
    if not reviews: return {'status': 'needs_user_review', 'reason': 'Whole-image-first review not imported'}
    facts = reviews[0]['payload']; whole = facts['whole_image']; preservation = facts['preservation']
    conflict=conflict_state(co._path(root,'unified/holistic/'+artifact['file_hash']))
    if any(x['status'] == 'fail' for x in preservation.values()): status = 'rejected'
    elif conflict['unresolved_conflicts']:status='needs_user_review'
    elif any(x['reference_status'] in ('unmet', 'partial') for x in whole.values()): status = 'revise'
    elif len(reviews) != len(STAGES) or facts['reviewer']['independence'] != 'independent': status = 'needs_user_review'
    elif any(x['reference_status'] == 'uncertain' or x['confidence'] != 'high' for x in whole.values()) or any(
            x['status'] == 'uncertain' or x['confidence'] != 'high' for x in preservation.values()): status = 'needs_user_review'
    else: status = 'accepted'
    return dict(status=status, whole_image_hash=reviews[0]['content_hash'], last_review_hash=reviews[-1]['content_hash'], aggregation='none',**conflict)


def check_decision_current(root,state,evaluation,decision):
    """A later observation requires a new decision, never reuse an older pass."""
    if active(root,evaluation['payload']['evaluation_target_version']) is None:return
    require(decision['payload'].get('unified_holistic_assessment')==holistic_for_evaluation(root,evaluation),
            'Holistic evidence changed; append a new exact-predecessor verification decision before selection')
    delivery=decision['payload'].get('unified_delivery_assessment')
    require(delivery is not None and delivery.get('native_detail_evidence')==detail_for_evaluation(root,state,evaluation),
            'Native-detail evidence changed; append a new exact-predecessor verification decision before selection')
