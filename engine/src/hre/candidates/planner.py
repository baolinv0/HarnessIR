from __future__ import annotations

from copy import deepcopy
from importlib.resources import files
import io
import json
from pathlib import Path
import re

from jsonschema import Draft202012Validator
from PIL import Image

from hre.models import HREError, file_sha256
from hre.storage import atomic_write, write_json
from .contracts import VERSION, candidate_spec, digest, require, seal, text_hash
from .transport import call_json


_CRITICALITY = {'high': 0, 'medium': 1, 'low': 2}
_SEVERITY = {'major': 0, 'minor': 1}
_STRATEGY_PREFIX = {'person': 'face', 'text': 'text', 'building': 'building', 'grass': 'grass', 'other': 'other'}
_CATALOG = {
    'person': {'under_restored_features', 'waxy_skin', 'over_generated_detail',
               'over_sharpened', 'structural_inconsistency', 'body_hand_incorrect'},
    'text': {'merged_strokes', 'broken_strokes', 'invented_or_wrong_text', 'unreadable_source'},
}


def _scope_domain(scope):
    prefix = scope.split('.', 1)[0].lower()
    for domain, words in {'person': ('person', 'face', 'body', 'hand', 'hair', 'skin'),
                          'text': ('text', 'sign', 'number', 'character'),
                          'building': ('building', 'architecture'), 'grass': ('grass', 'vegetation')}.items():
        if any(prefix == word or prefix.startswith(word + '_') for word in words):
            return domain
    return prefix if prefix in {'global', 'other'} else 'other'


def requirements_from_prompt(prompt):
    require(isinstance(prompt, str) and bool(prompt.strip()), 'prompt_empty', 'P0 must be a nonempty string')
    result = []
    for index, match in enumerate(re.finditer(r'[^.!?\n]+[.!?]?', prompt)):
        text = match.group()
        lowered = text.lower()
        protected = bool(re.search(r'\b(preserve|retain|keep)\b.*\b(identity|expression|pose|layout|color|colour|character)\b', lowered))
        domain = 'global'
        for value, words in [('person', r'face|facial|person|skin|hair|hand|body'),
                             ('text', r'text|stroke|sign|character|number'),
                             ('building', r'building|architecture'), ('grass', r'grass|vegetation')]:
            if re.search(r'\b(' + words + r')\b', lowered):
                domain = value
                break
        kind = 'protection' if protected else ('restoration_strategy' if domain != 'global' else 'global')
        result.append({'requirement_id': f'REQ_{index:03d}', 'source_span': text,
                       'start': match.start(), 'end': match.end(), 'scope': [domain + '.*'],
                       'kind': kind, 'mutable_by': [] if kind != 'restoration_strategy' else [domain],
                       'protected_links': []})
    return result


def _normalize_ir(prompt, requirements):
    require(isinstance(requirements, list), 'requirements_invalid', 'requirements_ir must be a list')
    result, identifiers, intervals = [], set(), []
    for raw in requirements:
        require(isinstance(raw, dict), 'requirements_invalid', 'Each requirement must be an object')
        require(set(raw) <= {'requirement_id', 'source_span', 'start', 'end', 'scope', 'kind', 'mutable_by', 'protected_links', 'original_text_hash'},
                'requirements_invalid', 'Unknown requirement fields')
        identifier, span = raw.get('requirement_id'), raw.get('source_span')
        require(isinstance(identifier, str) and identifier and identifier not in identifiers,
                'requirements_invalid', 'Requirement IDs must be unique nonempty strings')
        require(isinstance(span, str) and bool(span), 'requirements_invalid', 'Requirement source_span must be nonempty')
        start, end = raw.get('start'), raw.get('end')
        if start is None and end is None:
            positions = [match.start() for match in re.finditer(re.escape(span), prompt)]
            require(len(positions) == 1, 'requirements_invalid', 'A source span without offsets must be unique in P0')
            start, end = positions[0], positions[0] + len(span)
        require(type(start) is int and type(end) is int and 0 <= start < end <= len(prompt)
                and prompt[start:end] == span, 'requirements_invalid', 'Requirement span does not match original P0')
        scope = raw.get('scope')
        require(isinstance(scope, list) and scope and all(isinstance(item, str) and item for item in scope)
                and len(scope) == len(set(scope)), 'requirements_invalid', 'Requirement scope must be a unique string list')
        kind = raw.get('kind')
        require(kind in {'restoration_strategy', 'protection', 'global', 'other'}, 'requirements_invalid', 'Unknown requirement kind')
        mutable, links = raw.get('mutable_by', []), raw.get('protected_links', [])
        require(isinstance(mutable, list) and all(isinstance(item, str) for item in mutable)
                and isinstance(links, list) and all(isinstance(item, str) for item in links),
                'requirements_invalid', 'Requirement references must be lists')
        result.append({**deepcopy(raw), 'start': start, 'end': end, 'mutable_by': mutable, 'protected_links': links})
        identifiers.add(identifier)
        intervals.append((start, end))
    for item in result:
        require(set(item['protected_links']) <= identifiers, 'requirements_invalid', 'Dangling protected requirement reference')
    intervals.sort()
    require(all(right[0] >= left[1] for left, right in zip(intervals, intervals[1:])),
            'requirements_invalid', 'Overlapping spans cannot be rewritten safely')
    return result


def compile_prompt(prompt, requirements, replacements, allowed_domains):
    entries = _normalize_ir(prompt, requirements)
    require(isinstance(replacements, dict), 'rewrite_invalid', 'Replacements must map requirement IDs to full text')
    indexed = {item['requirement_id']: item for item in entries}
    require(set(replacements) <= indexed.keys(), 'rewrite_invalid', 'A replacement references an unknown requirement')
    for identifier, text in replacements.items():
        item = indexed[identifier]
        require(isinstance(text, str) and bool(text.strip()), 'rewrite_invalid', 'Replacement text must be nonempty')
        domains = {_scope_domain(scope) for scope in item['scope']}
        require(item['kind'] == 'restoration_strategy' and domains <= set(allowed_domains)
                and bool(item['mutable_by']), 'protected_requirement_modified', 'Only declared target restoration strategies are mutable')
        if item.get('original_text_hash'):
            require(item['original_text_hash'] == text_hash(item['source_span']),
                    'requirements_invalid', 'Requirement source text hash mismatch')
    output, position = [], 0
    for entry in sorted(entries, key=lambda value: value['start']):
        output.append(prompt[position:entry['start']])
        replacement = replacements.get(entry['requirement_id'], entry['source_span'])
        leading = re.match(r'\s*', entry['source_span']).group()
        output.append(leading + replacement.lstrip() if entry['requirement_id'] in replacements else replacement)
        position = entry['end']
    output.append(prompt[position:])
    return ''.join(output)


def _rois(task, proposed, source):
    original = task.get('rois', [])
    original_by_id = {item['id']: item for item in original}
    require(isinstance(proposed, list), 'roi_registry_invalid', 'ROI registry must be a list')
    result, seen = [], set()
    for raw in proposed:
        require(isinstance(raw, dict) and isinstance(raw.get('id'), str) and raw['id'] not in seen,
                'roi_registry_invalid', 'ROI IDs must be unique strings')
        identifier, box = raw['id'], raw.get('box')
        require(re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', identifier) is not None,
                'roi_registry_invalid', 'ROI ID must be portable')
        require(isinstance(box, list) and len(box) == 4 and all(type(value) is int for value in box)
                and 0 <= box[0] < box[2] <= source['width'] and 0 <= box[1] < box[3] <= source['height'],
                'roi_registry_invalid', 'ROI must be inside canonical LQ coordinates')
        require(raw.get('semantic_type') in _STRATEGY_PREFIX, 'roi_registry_invalid', 'Unknown ROI semantic type')
        if identifier in original_by_id:
            old = original_by_id[identifier]
            require(box == old['box'] and raw['semantic_type'] == old['semantic_type'],
                    'roi_registry_modified', 'Planner cannot move or reinterpret a frozen LQ ROI')
            item = deepcopy(old)
        else:
            require(raw.get('provenance') == 'planner_lq', 'roi_registry_invalid', 'New ROIs must declare planner_lq provenance')
            item = deepcopy(raw)
        item['canonical_source_sha256'] = source['canonical_source_sha256']
        result.append(item)
        seen.add(identifier)
    require(set(original_by_id) <= seen, 'roi_registry_modified', 'Planner cannot remove a frozen LQ ROI')
    return result


def _validate_issues(issues, rois, baseline):
    schema_path = files('hre').joinpath('resources/schemas/candidates_issue.schema.json')
    require(schema_path.is_file(), 'issue_schema_missing', 'Packaged candidates Issue schema is missing')
    validator = Draft202012Validator(json.loads(schema_path.read_text('utf-8')))
    require(isinstance(issues, list), 'issues_invalid', 'Planner issues must be a list')
    roi_ids = {item['id'] for item in rois}
    known_refs = {'source_full', 'lq_full', 'c0_full'}
    known_refs.update('source_' + value for value in roi_ids)
    known_refs.update('lq_roi_' + value for value in roi_ids)
    known_refs.update('c0_roi_' + value for value in roi_ids)
    tool_refs = baseline.get('tool_evidence_refs', [])
    if isinstance(tool_refs, dict):
        known_refs.update(tool_refs)
    elif isinstance(tool_refs, list):
        known_refs.update(value for value in tool_refs if isinstance(value, str))
    result, seen = [], set()
    for value in issues:
        errors = list(validator.iter_errors(value))
        require(not errors, 'issue_schema_invalid', errors[0].message if errors else '')
        require(value['issue_id'] not in seen, 'issue_duplicate', 'Duplicate issue ID')
        require(set(value['region_ids']) <= roi_ids and set(value['evidence_refs']) <= known_refs,
                'issue_reference_invalid', 'Issue contains dangling ROI or evidence references')
        result.append(deepcopy(value))
        seen.add(value['issue_id'])
    return result


def _planning_evidence(root, rois, source, baseline, scale):
    source_path, baseline_path = Path(source['path']), Path(baseline['C0']['delivered_image'])
    expected_baseline_hash = baseline['C0'].get('sha256')
    require(baseline_path.is_file(), 'baseline_failed', 'C0 delivered artifact is missing')
    baseline_hash = file_sha256(baseline_path)
    require(expected_baseline_hash is None or expected_baseline_hash == baseline_hash,
            'baseline_modified', 'C0 image bytes changed before planning')
    registry = {'source_full': {'path': str(source_path), 'sha256': source['canonical_source_sha256']},
                'lq_full': {'path': str(source_path), 'sha256': source['canonical_source_sha256']},
                'c0_full': {'path': str(baseline_path), 'sha256': baseline_hash}}
    with Image.open(source_path) as lq, Image.open(baseline_path) as c0:
        require(c0.size == (source['width'] * scale, source['height'] * scale),
                'baseline_failed', 'C0 dimensions do not match the task')
        for roi in rois:
            for prefix, image, factor in [('lq_roi_', lq, 1), ('c0_roi_', c0, scale)]:
                ref = prefix + roi['id']
                path = root / 'plan' / 'evidence' / (ref + '.png')
                buffer = io.BytesIO()
                image.convert('RGB').crop(tuple(value * factor for value in roi['box'])).save(buffer, format='PNG')
                atomic_write(path, buffer.getvalue())
                registry[ref] = {'path': str(path), 'sha256': file_sha256(path), 'region_id': roi['id']}
            registry['source_' + roi['id']] = deepcopy(registry['lq_roi_' + roi['id']])
    write_json(root / 'plan' / 'evidence_registry.json', registry)
    return registry


def _slots(issues):
    ranked = sorted(issues, key=lambda item: (_CRITICALITY[item['task_criticality']], _SEVERITY[item['severity']],
                                            tuple(item['region_ids']), item['issue_id']))
    usable, unhandled = [], []
    for item in ranked:
        reason = None
        if item['support'] != 'supported' or item['intervention_feasibility'] != 'plausible':
            reason = 'unsupported_or_not_executable'
        elif item['domain'] in _CATALOG and item['problem_type'] not in _CATALOG[item['domain']]:
            reason = 'problem_outside_frozen_catalog'
        if reason:
            unhandled.append({'issue_id': item['issue_id'], 'reason': reason})
        else:
            usable.append(item)
    domains = list(dict.fromkeys(item['domain'] for item in usable))[:2]
    if set(domains) == {'person', 'text'}:
        domains = ['person', 'text']
    for item in usable:
        if item['domain'] not in domains:
            unhandled.append({'issue_id': item['issue_id'], 'reason': 'two_axis_limit'})
    axes = []
    for domain in domains:
        same = [item for item in usable if item['domain'] == domain]
        opposite = {'waxy_skin', 'over_generated_detail', 'over_sharpened'} <= {item['problem_type'] for item in same}
        opposite = opposite or (any(item['problem_type'] == 'waxy_skin' for item in same)
                                and any(item['problem_type'] in {'over_generated_detail', 'over_sharpened'} for item in same))
        if opposite or any(item['spatial_control_risk'] == 'high' for item in same):
            for item in same[1:]:
                unhandled.append({'issue_id': item['issue_id'], 'reason': 'full_frame_spatial_control_limited'})
            same = same[:1]
        axes.append((domain, same))
    slots = [{'slot_id': 'C0', 'strategy_id': 'baseline', 'issues': [], 'domains': [], 'dependency_ids': []}]
    if len(axes) == 2:
        for slot, (domain, items) in zip(('CF', 'CT'), axes):
            slots.append({'slot_id': slot, 'strategy_id': _STRATEGY_PREFIX[domain] + '_alt',
                          'issues': items, 'domains': [domain], 'dependency_ids': []})
        slots.append({'slot_id': 'CFT', 'strategy_id': 'joint_alt', 'issues': axes[0][1] + axes[1][1],
                      'domains': [axis[0] for axis in axes], 'dependency_ids': ['CF', 'CT']})
    elif len(axes) == 1:
        domain, items = axes[0]
        mechanisms = list(dict.fromkeys(item['problem_type'] for item in items))
        directions = [[item for item in items if item['problem_type'] == mechanism] for mechanism in mechanisms[:2]]
        for index, direction in enumerate(directions):
            suffix = ('_A' if index == 0 else '_B') if len(directions) == 2 else ''
            slots.append({'slot_id': ('CF', 'CT')[index], 'strategy_id': _STRATEGY_PREFIX[domain] + '_alt' + suffix,
                          'issues': direction, 'domains': [domain], 'dependency_ids': []})
    for slot in ('CF', 'CT', 'CFT'):
        if not any(item['slot_id'] == slot for item in slots):
            slots.append({'slot_id': slot, 'strategy_id': 'baseline_resample', 'issues': [], 'domains': [], 'dependency_ids': []})
    return sorted(slots, key=lambda item: ['C0', 'CF', 'CT', 'CFT'].index(item['slot_id'])), unhandled


def _fixture_rewrites(prompt, slots):
    requirements = requirements_from_prompt(prompt)
    candidates = []
    for slot in slots:
        if not slot['domains']:
            continue
        replacements = []
        for domain in slot['domains']:
            entries = [item for item in requirements if item['kind'] == 'restoration_strategy'
                       and {_scope_domain(scope) for scope in item['scope']} == {domain}]
            if entries:
                changes = [item['desired_change'].rstrip('. ') for item in slot['issues'] if item['domain'] == domain]
                replacements.append({'requirement_id': entries[0]['requirement_id'], 'new_text': '; '.join(changes) + '.'})
        candidates.append({'slot_id': slot['slot_id'], 'replacements': replacements})
    return {'requirements_ir': requirements, 'candidates': candidates}


def _compile_rewrites(prompt, slots, response):
    require(isinstance(response, dict) and isinstance(response.get('candidates'), list), 'rewrite_invalid', 'Rewriter must return candidates')
    requirements = _normalize_ir(prompt, response.get('requirements_ir', []))
    entries, seen = {}, set()
    for item in response['candidates']:
        require(isinstance(item, dict) and set(item) <= {'slot_id', 'replacements', 'retained_requirements', 'expected_effect'},
                'rewrite_invalid', 'Unknown candidate rewrite fields')
        require(item.get('slot_id') in {'CF', 'CT', 'CFT'} and item['slot_id'] not in seen,
                'rewrite_invalid', 'Rewrite slot must be unique and known')
        entries[item['slot_id']] = item
        seen.add(item['slot_id'])
    prompts, replacements, failures = {}, {}, {}
    for slot in slots[1:]:
        slot_id = slot['slot_id']
        if not slot['domains']:
            prompts[slot_id], replacements[slot_id] = prompt, {}
            continue
        try:
            entry = entries.get(slot_id)
            require(entry is not None and isinstance(entry.get('replacements'), list), 'rewrite_missing', 'Missing required candidate rewrite')
            mapping = {}
            for replacement in entry['replacements']:
                require(isinstance(replacement, dict) and set(replacement) == {'requirement_id', 'new_text'},
                        'rewrite_invalid', 'Each replacement needs requirement_id and new_text')
                identifier = replacement['requirement_id']
                require(identifier not in mapping, 'rewrite_invalid', 'Duplicate requirement replacement')
                mapping[identifier] = replacement['new_text']
            compiled = compile_prompt(prompt, requirements, mapping, slot['domains'])
            changed_domains = {_scope_domain(scope) for item in requirements if item['requirement_id'] in mapping
                               and mapping[item['requirement_id']].strip() != item['source_span'].strip() for scope in item['scope']}
            require(set(slot['domains']) <= changed_domains and compiled != prompt,
                    'rewrite_no_intervention', 'Every target axis must have a real semantic-scope edit')
            prompts[slot_id], replacements[slot_id] = compiled, mapping
        except HREError as error:
            failures[slot_id] = {'failure_kind': 'compile_invalid', 'reason': str(error)}
            prompts[slot_id], replacements[slot_id] = prompt, {}
    joint = next((slot for slot in slots if slot['slot_id'] == 'CFT' and slot['dependency_ids']), None)
    if joint and 'CFT' not in failures:
        merged = {**replacements.get('CF', {}), **replacements.get('CT', {})}
        if replacements.get('CFT') != merged:
            failures['CFT'] = {'failure_kind': 'compile_invalid', 'reason': 'Joint replacements differ from the frozen single interventions'}
    return requirements, prompts, replacements, failures


def _audit_response(slots, configured):
    return {'assessments': [{'slot_id': slot['slot_id'], 'passed': bool(configured.get(slot['slot_id'], True)),
                             'failure_kind': None if configured.get(slot['slot_id'], True) else 'compile_invalid',
                             'violations': [] if configured.get(slot['slot_id'], True) else ['scripted_fixture_rejection']}
                            for slot in slots[1:] if slot['domains']]}


def _merge_audit(slots, response, code_failures):
    require(isinstance(response, dict) and isinstance(response.get('assessments'), list), 'audit_invalid', 'Audit needs assessments')
    required = {slot['slot_id'] for slot in slots[1:] if slot['domains']}
    entries = {}
    for item in response['assessments']:
        require(isinstance(item, dict) and item.get('slot_id') in required and item['slot_id'] not in entries,
                'audit_invalid', 'Unknown or duplicate Audit slot')
        require(type(item.get('passed')) is bool and isinstance(item.get('violations', []), list),
                'audit_invalid', 'Audit passed flag must be boolean')
        require(item.get('failure_kind') in {None, 'compile_invalid', 'intervention_invalid'}, 'audit_invalid', 'Unknown audit failure kind')
        entries[item['slot_id']] = item
    failures = deepcopy(code_failures)
    for slot_id in required:
        item = entries.get(slot_id)
        if item is None or not item['passed'] or item.get('violations'):
            failures[slot_id] = {'failure_kind': (item or {}).get('failure_kind') or 'compile_invalid',
                                 'reason': '; '.join(str(value) for value in (item or {}).get('violations', ['missing_audit']))}
    return failures


def build_plan(root, task, config, baseline, source, journal):
    root = Path(root)
    require(baseline.get('C0', {}).get('status') == 'completed', 'baseline_failed', 'C0 must succeed before feedback planning')
    prompt = baseline.get('P0')
    require(isinstance(prompt, str) and prompt.strip(), 'prompt_empty', 'Baseline full P0 is required')
    require(Path(source['path']).is_file() and file_sha256(Path(source['path'])) == source['canonical_source_sha256'],
            'source_modified', 'Canonical source changed before Planner submission')
    initial_rois = _rois(task, task.get('rois', []), source)
    evidence_registry = _planning_evidence(root, initial_rois, source, baseline, task['scale'])
    fixture = config.get('fixture', {})
    planner_fixture = {'issues': fixture.get('issues', []), 'roi_registry': fixture.get('roi_registry', task.get('rois', [])),
                       'plan_reason': 'Scripted CPU fixture; not a restoration quality result'}
    planning_input = {'task_mode': task['task_mode'], 'usage_policy': task['usage_policy'], 'P0': prompt,
                      'critical_attributes': task.get('critical_attributes', []), 'roi_registry': task.get('rois', []),
                      'available_evidence_refs': list(evidence_registry), 'tool_evidence': baseline.get('tool_evidence', {}),
                      'issue_schema': json.loads(files('hre').joinpath('resources/schemas/candidates_issue.schema.json').read_text('utf-8')),
                      'strategy_catalog': {domain: sorted(names) for domain, names in _CATALOG.items()}}
    diagnosis = call_json(root, config, journal, 'E1/planner/primary/0', 'planner', json.dumps(planning_input, ensure_ascii=False),
                          [source['path'], baseline['C0']['delivered_image']],
                          system=('Compare original LQ and C0. Return JSON {issues,roi_registry,plan_reason}. '
                                  'Issues must use hre_candidates_v1 Issue fields, source_full/c0_full or registered ROI evidence. '
                                  'Separate observation from cause hypothesis. Propose boxes only in original LQ coordinates with provenance planner_lq. '
                                  'Do not move existing boxes. Use only supported, plausible interventions from the frozen person/text catalog. '
                                  'Never invent known text, identity or GT. C0 is planning evidence, never a generator input.'),
                          fixture_response=planner_fixture)
    require(isinstance(diagnosis, dict) and set(diagnosis) <= {'issues', 'roi_registry', 'plan_reason'},
            'planner_invalid', 'Unknown Planner output fields')
    rois = _rois(task, diagnosis.get('roi_registry', task.get('rois', [])), source)
    evidence_registry = _planning_evidence(root, rois, source, baseline, task['scale'])
    issues = _validate_issues(diagnosis.get('issues'), rois, baseline)
    slots, unhandled = _slots(issues)
    active = any(slot['domains'] for slot in slots)
    requirements, prompts, replacements, failures = [], {}, {}, {}
    audit_refs = []
    if active:
        rewrite_fixture = _fixture_rewrites(prompt, slots)
        if 'rewrites' in fixture:
            supplied = fixture['rewrites']
            if isinstance(supplied, dict) and 'candidates' in supplied:
                rewrite_fixture = supplied
        rewrite_input = {'P0': prompt, 'slots': slots, 'roi_registry': rois, 'critical_attributes': task.get('critical_attributes', [])}
        instruction = ('Return JSON {requirements_ir,candidates}. Every requirement references an exact P0 source_span with start/end '
                       'character offsets, requirement_id, scope list, kind (restoration_strategy/protection/global/other), mutable_by and protected_links. '
                       'Each candidate has slot_id and replacements [{requirement_id,new_text}]. Only replace target restoration strategies. '
                       'Keep identity/expression/confirmed characters/layout/global/background protections. Keep literal unparsed P0 text. '
                       'Joint replacements must be exactly the union of both singles. Never append contradictory instructions or invent text.')
        rewritten = call_json(root, config, journal, 'E1/rewriter/primary/0', 'rewriter', json.dumps(rewrite_input, ensure_ascii=False),
                              [source['path'], baseline['C0']['delivered_image']], system=instruction, fixture_response=rewrite_fixture)
        try:
            requirements, prompts, replacements, failures = _compile_rewrites(prompt, slots, rewritten)
        except HREError as error:
            failures = {slot['slot_id']: {'failure_kind': 'compile_invalid', 'reason': str(error)} for slot in slots[1:] if slot['domains']}
            requirements, prompts, replacements = [], {slot['slot_id']: prompt for slot in slots[1:]}, {}
        audit_input = {'P0': prompt, 'requirements_ir': requirements, 'slots': slots,
                       'compiled_prompts': prompts, 'replacements': replacements, 'code_failures': failures}
        audit_instruction = ('Independently audit the compiled prompts against P0 and source evidence. Return JSON '
                             '{assessments:[{slot_id,passed:boolean,failure_kind:null|compile_invalid|intervention_invalid,violations:[]}]}. '
                             'Inspect every active slot. Reject missing protections, scope changes, false known text and unequal joint interventions. '
                             'Audit completion does not prove executor response. Do not inspect GT or future candidates.')
        configured_audits = fixture.get('audits', {})
        if not isinstance(configured_audits, dict):
            configured_audits = {}
        audited = call_json(root, config, journal, 'E1/audit/primary/0', 'audit', json.dumps(audit_input, ensure_ascii=False),
                            [source['path'], baseline['C0']['delivered_image']], system=audit_instruction,
                            fixture_response=_audit_response(slots, configured_audits))
        failures = _merge_audit(slots, audited, failures)
        audit_refs.append('E1/audit/primary/0')
        if failures:
            frozen_passes = {key: value for key, value in prompts.items() if key not in failures}
            repair_input = {**rewrite_input, 'prior_response': rewritten, 'failures': failures,
                            'frozen_passed_prompts': frozen_passes, 'instruction': 'Repair failed slots only; one batch, no new intervention direction.'}
            repaired = call_json(root, config, journal, 'E1/rewriter/repair/1', 'rewriter', json.dumps(repair_input, ensure_ascii=False),
                                 [source['path'], baseline['C0']['delivered_image']], system=instruction,
                                 fixture_response=fixture.get('repair_rewrites', rewritten))
            try:
                new_requirements, new_prompts, new_replacements, new_failures = _compile_rewrites(prompt, slots, repaired)
                require(all(new_prompts.get(key) == value for key, value in frozen_passes.items()),
                        'repair_modified_frozen_prompt', 'Repair cannot change a previously passed Prompt')
                requirements, prompts, replacements, failures = new_requirements, new_prompts, new_replacements, new_failures
            except HREError as error:
                for slot in slots[1:]:
                    if slot['slot_id'] not in frozen_passes and slot['domains']:
                        failures[slot['slot_id']] = {'failure_kind': 'compile_invalid', 'reason': str(error)}
            audit_input.update(requirements_ir=requirements, compiled_prompts=prompts, replacements=replacements, code_failures=failures)
            reaudited = call_json(root, config, journal, 'E1/audit/repair/1', 'audit', json.dumps(audit_input, ensure_ascii=False),
                                  [source['path'], baseline['C0']['delivered_image']], system=audit_instruction,
                                  fixture_response=_audit_response(slots, fixture.get('repair_audits', configured_audits)))
            failures = _merge_audit(slots, reaudited, failures)
            audit_refs.append('E1/audit/repair/1')
    specs, fallbacks = [], []
    for index, slot in enumerate(slots):
        slot_id = slot['slot_id']
        dependency_failure = any(dependency in failures for dependency in slot['dependency_ids'])
        failure = failures.get(slot_id)
        effective = slot['strategy_id']
        if failure or dependency_failure:
            effective = 'baseline_resample'
            fallbacks.append({'slot_id': slot_id, 'planned_strategy_id': slot['strategy_id'], 'effective_strategy_id': effective,
                              'dependency_ids': slot['dependency_ids'], 'failure_kind': (failure or {}).get('failure_kind', 'dependency_invalid'),
                              'fallback_reason': (failure or {}).get('reason', 'A required single-axis Prompt failed final audit'),
                              'audit_refs': audit_refs})
        full_prompt = prompt if not slot['domains'] or effective == 'baseline_resample' else prompts[slot_id]
        axis = slot['domains'][0] if len(slot['domains']) == 1 else ('joint' if slot['domains'] else None)
        spec = candidate_spec(slot_id, effective, index, config['seed_schedule'][index], full_prompt,
                              source['canonical_source_sha256'], issue_refs=[item['issue_id'] for item in slot['issues']],
                              expected_effect=[{'region_id': region, 'attribute': item['attribute'], 'direction': 'improve'}
                                               for item in slot['issues'] for region in item['region_ids']], evaluation_axis_id=axis)
        spec.update(planned_strategy_id=slot['strategy_id'], effective_strategy_id=effective,
                    dependency_ids=slot['dependency_ids'])
        specs.append(spec)
    plan = seal({'schema_version': VERSION, 'plan_origin': 'fixture' if config['mode'] == 'fixture' else 'planner',
                 'issues': issues, 'roi_registry': rois, 'shared_requirements': [item['requirement_id'] for item in requirements
                                                                             if item['kind'] != 'restoration_strategy'],
                 'candidate_specs': specs, 'requirements_ir': requirements, 'fallbacks': fallbacks,
                 'unhandled_issues': unhandled, 'audit_refs': audit_refs,
                 'evidence_registry': evidence_registry,
                 'joint_applicability': 'applicable' if len(slots[-1]['domains']) == 2 and not fallbacks else 'not_applicable',
                 'plan_reason': diagnosis.get('plan_reason', ''), 'source_hash': source['canonical_source_sha256'],
                 'baseline_prompt_hash': text_hash(prompt), 'fixture_only': config['mode'] == 'fixture'})
    write_json(root / 'plan' / 'candidate_plan.json', plan)
    write_json(root / 'plan' / 'audit.json', {'audit_refs': audit_refs, 'failures': failures, 'replacements': replacements})
    for spec in specs:
        path = root / 'plan' / 'prompts' / (spec['slot_id'] + '.txt')
        atomic_write(path, spec['full_prompt'].encode('utf-8'))
    return plan
