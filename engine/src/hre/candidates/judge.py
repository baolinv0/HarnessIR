from copy import deepcopy
import json
from pathlib import Path

from hre.models import HREError, file_sha256
from hre.storage import read_json, write_json
from .contracts import digest, require, seal, verify_seal

ROLE_INSTRUCTIONS = {
    'J-P': 'Focus on people: expression, visible identity cues, pose, face/hair/body/hand geometry, waxy texture and invented pores. Natural appearance alone cannot verify identity.',
    'J-T': 'Focus on text: source-supported characters and strokes, spacing, layout, readability and invented content. Candidate OCR and language plausibility are not ground truth.',
    'J-G': 'Focus on technical restoration: background detail, residual noise/blur/compression, ringing, major artifacts, color and global geometry. Sharpness cannot compensate for a confirmed content error.',
    'J-U': 'Use normal viewing size to assess whether the image is natural, coherent and usable in daily viewing. Then inspect required evidence. This is a viewing perspective, not a statistical user survey.',
    'aggregate': 'Verify every required assessment and the original image evidence. Resolve substantive conflict from evidence; do not average expert scores or substitute votes for content verification.',
}


def _passed(candidate):
    gate = candidate.get('hard_gate')
    return gate == 'passed' or isinstance(gate, dict) and gate.get('status') == 'passed'


def _roi_id(roi):
    return roi.get('id', roi.get('region_id'))


def compile_review_plan(task, bundle, variant, config):
    require(variant in {'J0', 'J1', 'J2'}, 'judge_variant_invalid', 'Use J0, J1 or J2')
    settings = config.get('review', {})
    cap = settings.get('max_judge_calls', {}).get(variant, 7 if variant == 'J2' else 3)
    limits = config.get('budgets', {})
    cap = min(cap, limits.get('judge_'+variant+'_total', cap))
    max_images = settings.get('max_images_per_call', 64)
    max_rois = settings.get('max_rois_per_package', 6)
    output_cap = settings.get('max_output_tokens', 8192)
    endpoint_cap = config.get('stages', {}).get('judge', {}).get('settings', {}).get('max_tokens', output_cap)
    require(type(output_cap) is int and output_cap > 0 and type(endpoint_cap) is int and 0 < endpoint_cap <= output_cap,
            'review_token_budget_invalid', 'Judge endpoint output limit must fit the frozen ReviewPlan token cap')
    require(type(cap) is int and cap >= 0 and type(max_images) is int and max_images > 0 and type(max_rois) is int and max_rois > 0,
            'review_capacity_invalid', 'Positive image/ROI capacities and nonnegative call limit required')
    candidates = [c for c in bundle['candidates'] if _passed(c)]
    aliases = [c['alias'] for c in candidates]
    regions = [_roi_id(r) for r in bundle.get('roi_registry', [])]
    require(len(set(regions)) == len(regions), 'roi_registry_invalid', 'Duplicate region IDs')
    fixed_images = len(candidates) + 1
    per_package = min(max_rois, (max_images - fixed_images) // fixed_images)
    impossible = fixed_images > max_images or bool(regions) and per_package < 1
    chunks = [regions[i:i+per_package] for i in range(0, len(regions), per_package)] if regions and per_package > 0 else [[]]
    roles = ['J-P', 'J-T', 'J-G', 'J-U'] if variant == 'J2' else [variant]
    packages = []
    for role in roles:
        for region_chunk in chunks:
            package_id = f'{variant}_primary_{len(packages)}'
            checks = [x['check_id'] for x in bundle.get('critical_instances', []) if x.get('region_id') in region_chunk or x.get('region_id') in {'whole', '__full__', None}]
            image_hashes = [bundle['source']['sha256']] + [c['image_sha256'] for c in candidates]
            image_hashes.extend(crop['sha256'] for crop in bundle['source'].get('roi_images', []) if crop['region_id'] in region_chunk)
            image_hashes.extend(crop['sha256'] for c in candidates for crop in c.get('roi_images', []) if crop['region_id'] in region_chunk)
            packages.append({'package_id': package_id, 'role': role, 'candidate_ids': aliases,
                             'region_ids': region_chunk, 'required_check_ids': checks, 'image_hashes': image_hashes, 'kind': 'primary'})
    aggregate = variant == 'J2' or len(packages) > 1
    impossible |= aggregate and fixed_images * (1 + len(regions)) > max_images
    required_calls = len(packages) + int(aggregate)
    needed = required_calls
    repair_reserve = min(1, limits.get('judge_'+variant+'_format_repair', 1), max(0, cap - required_calls))
    dispute_reserve = min(1, limits.get('judge_'+variant+'_dispute', 1), max(0, cap - required_calls - repair_reserve))
    status = 'ready'
    reason = None
    if not candidates:
        status, reason = 'unresolved', 'no_contract_valid_candidates'
    elif impossible:
        status, reason = 'unresolved', 'review_capacity_insufficient'
    elif needed > cap or len(packages) > limits.get('judge_'+variant+'_primary', 4 if variant == 'J2' else 1) or int(aggregate) > limits.get('judge_'+variant+'_aggregate', 1):
        status, reason = 'unresolved', 'review_budget_insufficient'
    elif set(regions) - {x['region_id'] for x in bundle['source'].get('roi_images', [])} or any(set(regions) - {x['region_id'] for x in c.get('roi_images', [])} for c in candidates):
        status, reason = 'unresolved', 'review_coverage_insufficient'
    calls = [{'call_id': p['package_id'], 'kind': 'primary', 'package_ids': [p['package_id']], 'max_output_tokens': settings.get('max_output_tokens', 8192)} for p in packages]
    if aggregate:
        calls.append({'call_id': f'{variant}_aggregate', 'kind': 'aggregate', 'package_ids': [p['package_id'] for p in packages], 'max_output_tokens': settings.get('max_output_tokens', 8192)})
    return seal({'schema_version': 'hre_candidates_v1', 'variant': variant, 'pool_hash': bundle['pool_hash'],
                 'roi_registry_hash': digest(bundle.get('roi_registry', [])), 'required_checks': deepcopy(bundle.get('critical_instances', [])),
                 'candidate_ids': aliases, 'packages': packages, 'calls': calls, 'needs_aggregate': aggregate,
                 'budget': {'max_calls': cap, 'primary': len(packages), 'aggregate': int(aggregate), 'dispute': dispute_reserve, 'format_repair': repair_reserve},
                 'aggregation_rule': 'complete_required_checks_no_votes', 'status': status, 'reason': reason,
                 'tie_order': deepcopy(config.get('tie_order', []))})


def _refs(bundle, candidate, region_id=None):
    source = {'source_full'}
    own = {candidate['alias'] + '_full'}
    for item in bundle['source'].get('roi_images', []):
        if region_id is None or item.get('region_id') == region_id:
            source.add(item.get('ref_id', 'source_' + item['region_id']))
    for item in candidate.get('roi_images', []):
        if region_id is None or item.get('region_id') == region_id:
            own.add(item.get('ref_id', candidate['alias'] + '_' + item['region_id']))
    return source, own


def _bound_refs(bundle, candidate, refs, region_id=None):
    if not isinstance(refs, list) or not refs or not all(isinstance(x, str) for x in refs):
        return False
    source, own = _refs(bundle, candidate, region_id)
    return set(refs) <= source | own and bool(set(refs) & source) and bool(set(refs) & own)


def _groups_valid(groups, aliases):
    if not isinstance(groups, list) or any(not isinstance(g, list) or not g for g in groups):
        return False
    flat = [a for g in groups for a in g]
    return len(set(flat)) == len(flat) and set(flat) <= set(aliases)


def select(task, bundle, review_plan, reviews):
    verify_seal(review_plan)
    require(review_plan['pool_hash'] == bundle['pool_hash'] and review_plan['roi_registry_hash'] == digest(bundle.get('roi_registry', [])), 'review_binding_mismatch', 'Review pool or ROI registry changed')
    aliases = bundle['aliases']
    valid = [c for c in bundle['candidates'] if _passed(c)]
    required_packages = list(review_plan['packages'])
    if review_plan.get('needs_aggregate'):
        required_packages.append({'package_id': review_plan['variant'] + '_aggregate', 'kind': 'aggregate',
                                  'required_check_ids': [check['check_id'] for check in review_plan['required_checks']]})
    package_ids = {p['package_id'] for p in required_packages}
    received = {r.get('package_id') for r in reviews
                if any(r.get('package_id') == p['package_id'] and r.get('kind', 'primary') == p.get('kind', 'primary')
                       for p in required_packages)}
    complete_packages = package_ids <= received and review_plan['status'] == 'ready'
    disputed = _disputed_aliases(reviews)
    decisions = {}
    coverage = {}
    for candidate in bundle['candidates']:
        cid, alias = candidate['candidate_id'], candidate['alias']
        if not _passed(candidate):
            decisions[cid], coverage[cid] = 'ineligible', {'complete': False, 'reason': 'hard_contract_failed'}
            continue
        uncertain = not complete_packages
        rejected = False
        observations = []
        for package in required_packages:
            rows = [a for r in reviews if r.get('package_id') == package['package_id']
                    and r.get('kind', 'primary') == package.get('kind', 'primary')
                    for a in r.get('assessments', []) if a.get('candidate_id') == alias]
            if len(rows) != 1:
                uncertain = True
                continue
            row = rows[0]
            observations.append(row)
            uncertain |= not _bound_refs(bundle, candidate, row.get('evidence_refs'))
            uncertain |= row.get('content_state') == 'conflict' and not any(a.get('content_state') == 'conflict' for a in row.get('attribute_assessments', []))
            if row.get('restoration') not in {'adequate', 'strong', 'insufficient'} or row.get('artifact_severity') not in {'none', 'minor', 'major'}:
                uncertain = True
            if row.get('restoration') == 'insufficient' or row.get('artifact_severity') == 'major':
                if _bound_refs(bundle, candidate, row.get('evidence_refs')):
                    rejected = True
                else:
                    uncertain = True
            for check in review_plan['required_checks']:
                if check.get('required_for_acceptance', True) and check.get('available') is False:
                    uncertain = True
                if not check.get('required_for_acceptance', True) or check.get('check_id') not in package['required_check_ids']:
                    continue
                if check.get('attribute_id') in {'__restoration__', '__artifacts__'}:
                    continue
                attrs = [a for a in row.get('attribute_assessments', []) if a.get('attribute_id') == check['attribute_id'] and a.get('region_id') == check['region_id']]
                if len(attrs) != 1 or attrs[0].get('coverage') != 'complete':
                    uncertain = True
                    continue
                attr = attrs[0]
                state = attr.get('content_state')
                bound = _bound_refs(bundle, candidate, attr.get('evidence_refs'), check['region_id'])
                if state == 'conflict':
                    if bound:
                        rejected = True
                    else:
                        uncertain = True
                elif state == 'supported':
                    uncertain |= not bound
                elif state == 'no_visible_conflict':
                    uncertain |= check['verification_requirement'] == 'verified_content' or not bound
                elif state == 'unverifiable':
                    uncertain |= not (task['usage_policy'] == 'photo_restoration' and check.get('allow_unverifiable') and check['verification_requirement'] == 'visible_consistency' and bound)
                else:
                    uncertain = True
            for attr in row.get('attribute_assessments', []):
                if attr.get('content_state') == 'conflict' and attr.get('severity') in {'major', 'critical'}:
                    if _bound_refs(bundle, candidate, attr.get('evidence_refs'), attr.get('region_id')):
                        rejected = True
                    else:
                        uncertain = True
        if not observations:
            uncertain = True
        if alias in disputed:
            uncertain, rejected = True, False
        decisions[cid] = 'ineligible' if rejected else 'undetermined' if uncertain else 'eligible'
        coverage[cid] = {'complete': not uncertain, 'observed_packages': len(observations), 'required_packages': len(package_ids)}
    rank_reviews = [r for r in reviews if r.get('kind') == 'aggregate'] if review_plan['needs_aggregate'] else [r for r in reviews if r.get('package_id') in package_ids]
    groups = rank_reviews[-1].get('preference_groups', []) if rank_reviews else []
    if not _groups_valid(groups, review_plan['candidate_ids']):
        groups = []
    ranked = {a for group in groups for a in group}
    eligible = [cid for cid, state in decisions.items() if state == 'eligible']
    if any(c['alias'] not in ranked for c in valid if c['candidate_id'] in eligible):
        groups = []
    eligible_groups = [[aliases[a] for a in group if aliases[a] in eligible] for group in groups]
    eligible_groups = [g for g in eligible_groups if g]
    best = None
    if eligible_groups:
        first = eligible_groups[0]
        baseline = bundle.get('baseline_id')
        tie_order = review_plan.get('tie_order', [])
        tie_ids = [c['candidate_id'] for key in tie_order for c in valid if key in {c['candidate_id'], c.get('slot_id')}]
        best = baseline if baseline in first else next((x for x in tie_ids if x in first), sorted(first)[0])
    available = aliases[groups[0][0]] if groups and ranked == set(review_plan['candidate_ids']) else None
    output = next((c['image_path'] for c in valid if c['candidate_id'] == best), None)
    return {'schema_version': 'hre_candidates_v1', 'contract_valid_ids': [c['candidate_id'] for c in valid],
            'eligible_ids': eligible, 'eligibility_decisions': decisions, 'coverage': coverage,
            'review_plan_sha256': digest(review_plan), 'preference_groups': eligible_groups,
            'best_candidate': best, 'best_available_id': available, 'selected_output': output,
            'status': 'baseline_retained' if best and best == bundle.get('baseline_id') else 'selected' if best else 'unresolved',
            'content_verification': 'per_attribute_only', 'reason': review_plan.get('reason') or ('eligible_ranked' if best else 'no_complete_eligible_ranking')}


def _images(bundle, package):
    images = [bundle['source']['path']]
    refs = [{'ref_id': 'source_full', 'sha256': bundle['source']['sha256']}]
    for crop in bundle['source'].get('roi_images', []):
        if crop['region_id'] in package['region_ids']:
            images.append(crop['path'])
            refs.append({'ref_id': crop['ref_id'], 'sha256': crop['sha256']})
    ordered_candidates = sorted(bundle['candidates'], key=lambda c: package['candidate_ids'].index(c['alias']) if c['alias'] in package['candidate_ids'] else len(package['candidate_ids']))
    for candidate in ordered_candidates:
        if candidate['alias'] not in package['candidate_ids']:
            continue
        images.append(candidate['image_path'])
        refs.append({'ref_id': candidate['alias']+'_full', 'sha256': candidate['image_sha256']})
        for crop in candidate.get('roi_images', []):
            if crop['region_id'] in package['region_ids']:
                images.append(crop['path'])
                refs.append({'ref_id': crop['ref_id'], 'sha256': crop['sha256']})
    for path, ref in zip(images, refs):
        require(file_sha256(Path(path)) == ref['sha256'], 'judge_image_modified', 'Transmitted image bytes changed')
    return images, refs


def _fixture_review(config, bundle, package, variant):
    configured = config.get('fixture', {}).get('reviews', {})
    require(isinstance(configured, dict), 'fixture_review_invalid', 'Scripted reviews must be an object')
    if variant in configured:
        configured = configured[variant]
    require(isinstance(configured, dict), 'fixture_review_invalid', 'Variant review must be an object')
    if 'assessments' in configured:
        return deepcopy(configured)
    assessments = []
    for candidate in bundle['candidates']:
        alias = candidate['alias']
        if alias not in package['candidate_ids']:
            continue
        row = {'candidate_id': alias, 'content_state': 'supported', 'restoration': 'adequate', 'artifact_severity': 'none',
               'evidence_refs': ['source_full', alias+'_full'], 'attribute_assessments': [], 'limitations': ['synthetic fixture verdict; not model evidence']}
        for check in bundle.get('critical_instances', []):
            if check['check_id'] in package['required_check_ids']:
                row['attribute_assessments'].append({'attribute_id': check['attribute_id'], 'region_id': check['region_id'], 'coverage': 'complete', 'content_state': 'supported', 'evidence_refs': ['source_full', alias+'_full']})
        override = configured.get(alias, configured.get(candidate['candidate_id'], {}))
        row.update(deepcopy(override))
        row['candidate_id'] = alias
        assessments.append(row)
    return {'assessments': assessments, 'preference_groups': [package['candidate_ids']], 'fixture_only': True}


def _response_valid(value, aliases):
    if not isinstance(value, dict) or not isinstance(value.get('assessments'), list) or not _groups_valid(value.get('preference_groups'), aliases):
        return False
    ids = [a.get('candidate_id') for a in value['assessments'] if isinstance(a, dict)]
    if len(ids) != len(value['assessments']) or not all(isinstance(x, str) for x in ids) or len(set(ids)) != len(ids) or not set(ids) <= set(aliases):
        return False
    return all(isinstance(a.get('attribute_assessments', []), list) and all(isinstance(x, dict) for x in a.get('attribute_assessments', [])) for a in value['assessments'])


def _disputed_aliases(reviews):
    states = {}
    explicit = set()
    for review in reviews:
        if review.get('dispute_required') is True:
            explicit.update(a for group in review.get('preference_groups', [])[:2] for a in group)
        for row in review.get('assessments', []):
            alias = row['candidate_id']
            for attr in row.get('attribute_assessments', []):
                key = (alias, attr.get('attribute_id'), attr.get('region_id'))
                states.setdefault(key, set()).add(attr.get('content_state'))
    return explicit | {key[0] for key, values in states.items() if 'conflict' in values and bool(values & {'supported', 'no_visible_conflict'})}


def judge_pool(root, task, config, bundle, journal, variant):
    from .transport import call_json
    root = Path(root)
    directory = root / 'judge' / variant
    plan = compile_review_plan(task, bundle, variant, config)
    plan_path = directory / 'review_plan.json'
    if plan_path.exists():
        require(read_json(plan_path) == plan, 'review_plan_modified', 'Frozen ReviewPlan differs')
    else:
        write_json(plan_path, plan)
    if plan['status'] != 'ready':
        result = select(task, bundle, plan, [])
        write_json(directory / 'selection.json', result)
        return result
    reviews = []
    repair_used = False
    failure = None
    packages = list(plan['packages'])
    if plan['needs_aggregate']:
        packages.append({'package_id': variant+'_aggregate', 'role': 'aggregate', 'candidate_ids': plan['candidate_ids'],
                         'region_ids': [_roi_id(r) for r in bundle.get('roi_registry', [])],
                         'required_check_ids': [c['check_id'] for c in plan['required_checks']], 'kind': 'aggregate'})
    for package in packages:
        try:
            images, refs = _images(bundle, package)
            max_images = config.get('review', {}).get('max_images_per_call', 64)
            if len(images) > max_images:
                failure = 'aggregate_capacity_insufficient'
                break
            checks = [x for x in plan['required_checks'] if x['check_id'] in package['required_check_ids']]
            payload = {'usage_policy': task['usage_policy'], 'role': package['role'], 'candidates': package['candidate_ids'],
                       'role_instruction': ROLE_INSTRUCTIONS.get(package['role'], 'Assess source fidelity, restoration sufficiency, naturalness and artifacts across the whole image.'),
                       'required_checks': checks, 'image_refs': refs,
                       'output_contract': {'assessments': 'one per candidate with restoration, artifact_severity, evidence_refs and every required attribute assessment',
                                           'preference_groups': 'all candidates, best-first groups, ties allowed'},
                       'rules': 'Judge source-visible consistency, sufficient restoration and artifacts separately. Unsupported truth is unverifiable. Cite exact source and candidate image refs. No numeric soft threshold may veto a candidate.'}
            if variant != 'J0':
                payload['measurements'] = bundle.get('anonymous_measurements', bundle.get('measurements', []))
            if package['kind'] == 'aggregate':
                payload['independent_reviews'] = reviews
            prompt = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            fixture = _fixture_review(config, bundle, package, variant)
            try:
                value = call_json(root, config, journal, 'judge/'+bundle['pool_hash']+'/'+variant+'/'+package['package_id'], 'judge_'+variant+'_'+package['kind'], prompt, images,
                                  system='Return one JSON object. Evaluate the attached source and anonymous candidates. Follow the required per-attribute coverage contract.', group=variant, fixture_response=fixture)
            except HREError as exc:
                if exc.code != 'model_json_invalid':
                    raise
                value = {'format_error': exc.code}
            if not _response_valid(value, plan['candidate_ids']):
                if repair_used or plan['budget']['format_repair'] == 0:
                    failure = 'judge_failed'
                    break
                repair_used = True
                value = call_json(root, config, journal, 'judge/'+bundle['pool_hash']+'/'+variant+'/format_repair', 'judge_'+variant+'_format_repair',
                                  prompt+'\nRepair the prior response to the required JSON contract:\n'+json.dumps(value, ensure_ascii=False), images,
                                  system='Repair format without inventing unobserved assessments.', group=variant, fixture_response=fixture)
                if not _response_valid(value, plan['candidate_ids']):
                    failure = 'judge_failed'
                    break
            value = deepcopy(value)
            value['package_id'], value['kind'] = package['package_id'], package['kind']
            reviews.append(value)
            write_json(directory / (package['package_id']+'.json'), value)
        except (HREError, OSError, ValueError, TimeoutError) as exc:
            code = getattr(exc, 'code', type(exc).__name__)
            failure = 'judge_failed' if code == 'model_json_invalid' else code
            break
    disputed = _disputed_aliases(reviews)
    if not failure and disputed:
        ranked = [a for group in reviews[-1].get('preference_groups', []) for a in group]
        pair = ranked[:2]
        if plan['budget']['dispute'] == 0:
            failure = 'review_budget_insufficient_for_dispute'
        elif len(pair) != 2 or not disputed <= set(pair):
            failure = 'multiple_key_disputes_unresolved'
        else:
            package = {'package_id': variant+'_dispute', 'role': 'dispute', 'candidate_ids': list(reversed(pair)),
                       'region_ids': [_roi_id(r) for r in bundle.get('roi_registry', [])],
                       'required_check_ids': [c['check_id'] for c in plan['required_checks']]}
            try:
                images, refs = _images(bundle, package)
                prompt = json.dumps({'usage_policy': task['usage_policy'], 'candidate_ids': package['candidate_ids'],
                                     'required_checks': plan['required_checks'], 'image_refs': refs, 'prior_reviews': reviews,
                                     'instruction': 'Resolve the substantive disagreement from image evidence, not votes. Return complete assessments and best-first preference_groups for only these two candidates. Unresolved truth remains unverifiable.'}, ensure_ascii=False, sort_keys=True)
                resolved = call_json(root, config, journal, 'judge/'+bundle['pool_hash']+'/'+variant+'/dispute', 'judge_'+variant+'_dispute',
                                     prompt, images, system='Independent two-candidate evidence review. Display order is reversed.', group=variant,
                                     fixture_response=_fixture_review(config, bundle, package, variant))
                if not _response_valid(resolved, pair) or {a.get('candidate_id') for a in resolved['assessments']} != set(pair):
                    failure = 'dispute_response_invalid'
                else:
                    rows = {a['candidate_id']: a for a in resolved['assessments']}
                    for review in reviews:
                        review['assessments'] = [deepcopy(rows.get(a['candidate_id'], a)) for a in review['assessments']]
                    resolved_ranking = resolved['preference_groups'] + [[a] for a in ranked if a not in pair]
                    reviews[-1]['preference_groups'] = resolved_ranking
                    resolved['package_id'], resolved['kind'] = package['package_id'], 'dispute'
                    write_json(directory / 'dispute.json', resolved)
                    if _disputed_aliases([{'assessments': list(rows.values())}]):
                        failure = 'key_dispute_unresolved'
            except (HREError, OSError, ValueError, TimeoutError) as exc:
                failure = getattr(exc, 'code', type(exc).__name__)
    write_json(directory / 'attribute_assessments.json', {'reviews': reviews, 'failure': failure})
    result = select(task, bundle, plan, reviews)
    if failure:
        result.update(best_candidate=None, selected_output=None, status='judge_failed' if failure == 'judge_failed' else 'unresolved', reason=failure)
    result['fixture_only'] = config.get('mode') == 'fixture'
    write_json(directory / 'selection.json', result)
    return result
