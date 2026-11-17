from copy import deepcopy
from pathlib import Path

from hre.models import HREError, canonical_json, file_sha256, sha256_bytes
from hre.storage import case_lock, read_json, write_json
from .contracts import VERSION, candidate_spec, digest, parse_config, parse_task, require, seal, verify_seal
from .journal import Journal


class CandidateCase:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.frozen = read_json(self.root / 'f0.json')
        verify_seal(self.frozen)
        state = read_json(self.root / 'case.json')
        require(state.get('f0_hash') == self.frozen['freeze_hash'], 'freeze_modified', 'F0 differs from its original case anchor')
        self.task = self.frozen['task']
        self.config = self.frozen['config']
        self.journal = Journal(self.root, self.config['budgets'])

    @classmethod
    def create(cls, root, task, config):
        from .bridge import canonicalize_source, prepare_source
        root = Path(root).resolve()
        require(not root.exists() or not any(root.iterdir()), 'case_exists', 'Create a fresh case directory')
        task, config = parse_task(task), parse_config(config)
        external_files = {}
        deployment = config['editor'].get('deployment_manifest')
        if deployment:
            path = Path(deployment).expanduser().absolute()
            require(path.is_file(), 'deployment_manifest_missing', 'Freeze an existing deployment manifest before creating a case')
            external_files['deployment_manifest'] = {'path': str(path), 'sha256': file_sha256(path)}
        if config.get('harness_source_root'):
            identity = Path(config['harness_source_root']).expanduser().absolute() / 'SOURCE_IDENTITY.json'
            external_files['harness_identity'] = {'path': str(identity), 'sha256': file_sha256(identity) if identity.is_file() else None}
        original = Path(task['source']['path']).expanduser().resolve()
        require(original.is_file(), 'source_missing', 'Original LQ does not exist')
        root.mkdir(parents=True, exist_ok=True)
        with case_lock(root):
            source = canonicalize_source(original, root / 'inputs')
            prepared = prepare_source(source, task, root / 'prepared')
            for roi in task['rois']:
                require(roi['box'][2] <= source['width'] and roi['box'][3] <= source['height'], 'roi_out_of_bounds', roi['id'])
            task['source'] = {'path': source['path']}
            registration = None
            manifest_path = config['experiment']['e2_manifest_path']
            if manifest_path:
                registration = read_json(Path(manifest_path))
                verify_seal(registration)
                require(registration.get('schema_version') == VERSION and registration.get('record_type') == 'e2_preregistration', 'preregistration_invalid', 'Use a frozen E2 preregistration record')
                seeds = registration.get('evaluation_seeds')
                require(isinstance(seeds, list) and len(seeds) == len(set(seeds)) == 2
                        and all(type(seed) is int and 0 <= seed < 2**63 for seed in seeds)
                        and not set(seeds) & set(config['seed_schedule']), 'seed_schedule_invalid', 'Register two evaluation seeds outside E1')
                case_ids = registration.get('case_ids')
                require(isinstance(case_ids, list) and all(isinstance(item, str) and item for item in case_ids)
                        and len(case_ids) == len(set(case_ids)), 'preregistration_invalid', 'Register unique case IDs')
                if task['case_id'] in case_ids:
                    require(config['budgets']['image_generation'] >= (15 if config['experiment']['e1_ab'] else 12),
                            'budget_exhausted', 'Freeze the full E1 plus E2 image budget before creating a registered case')
                require(config['mode'] == 'real', 'fixture_research_forbidden', 'Research preregistration cannot be attached to fixture cases')
                write_json(root / 'e2_manifest.json', registration)
            f0 = seal({'schema_version': VERSION, 'task': task, 'config': config,
                       'source': source, 'prepared': prepared, 'e2_registration': registration, 'external_files': external_files})
            write_json(root / 'f0.json', f0)
            write_json(root / 'case.json', {'schema_version': VERSION, 'case_id': task['case_id'],
                       'phase': 'created', 'mode': config['mode'], 'f0_hash': f0['freeze_hash'],
                       'selected_output': None, 'error': None})
        return cls(root)

    @classmethod
    def open(cls, root):
        return cls(root)

    def _check_image_file(self, path, expected_hash):
        require(isinstance(path, str) and isinstance(expected_hash, str) and bool(expected_hash),
                'output_modified', 'Completed image reference is incomplete')
        actual = Path(path).resolve()
        require(actual.is_relative_to(self.root) and actual.is_file() and file_sha256(actual) == expected_hash,
                'output_modified', 'Completed image path or bytes changed')

    def _check_artifact_files(self, artifact):
        if artifact.get('status') != 'completed':
            return
        receipt = artifact.get('receipt', {})
        for field, hash_key, receipt_key in [('native_image', 'native_sha256', 'native_sha256'),
                                              ('delivered_image', 'sha256', 'delivered_sha256')]:
            expected_hash = artifact.get(hash_key)
            require(receipt.get(receipt_key) == expected_hash, 'output_modified', 'Cached image differs from its receipt')
            self._check_image_file(artifact.get(field), expected_hash)

    def _check_evidence_files(self, pool_root):
        path = pool_root / 'evidence' / 'bundle.json'
        if not path.exists():
            return None
        bundle = read_json(path)
        verify_seal(bundle)
        source = bundle['source']
        self._check_image_file(source.get('path'), source.get('sha256'))
        for record in [source, *bundle['candidates']]:
            if 'candidate_id' in record and record.get('hard_gate') == 'passed':
                self._check_image_file(record.get('image_path'), record.get('image_sha256'))
            for crop in record.get('roi_images', []):
                self._check_image_file(crop.get('path'), crop.get('sha256'))
        return bundle

    def _check_frozen(self):
        current = read_json(self.root / 'f0.json')
        verify_seal(current)
        require(self.state().get('f0_hash') == current['freeze_hash'], 'freeze_modified', 'F0 differs from its original case anchor')
        require(current['freeze_hash'] == self.frozen['freeze_hash'], 'freeze_modified', 'F0 changed since case opened')
        for item in current.get('external_files', {}).values():
            path = Path(item['path'])
            actual = file_sha256(path) if path.is_file() else None
            require(actual == item['sha256'], 'external_config_modified', 'A deployment/source identity file changed after F0')
        source, prepared = current['source'], current['prepared']
        require(file_sha256(Path(source['path'])) == source['sha256'], 'source_modified', 'Canonical LQ changed')
        require(file_sha256(Path(prepared['path'])) == prepared['sha256'], 'source_modified', 'Prepared LQ changed')
        if (self.root / 'plan' / 'plan.json').exists():
            plan = read_json(self.root / 'plan' / 'plan.json')
            verify_seal(plan)
            recorded = self.state().get('f1_hash')
            require(recorded is None or plan['freeze_hash'] == recorded, 'freeze_modified', 'F1 differs from the recorded phase transition')
        if (self.root / 'artifacts.json').exists():
            for pool in read_json(self.root / 'artifacts.json').values():
                if not isinstance(pool, list):
                    continue
                for artifact in pool:
                    self._check_artifact_files(artifact)
        e2_path = self.root / 'e2' / 'results.json'
        if e2_path.exists():
            for record in read_json(e2_path).get('records', []):
                self._check_artifact_files(record['artifact'])
        bundle = self._check_evidence_files(self.root)
        self._check_evidence_files(self.root / 'pools' / 'A')
        selection_path = self.root / 'selection.json'
        if selection_path.exists():
            selection = read_json(selection_path)
            verify_seal(selection)
            selected = selection.get('best_candidate')
            output = selection.get('selected_output')
            if selected is not None:
                candidate = next((item for item in (bundle or {}).get('candidates', [])
                                  if item['candidate_id'] == selected and item['hard_gate'] == 'passed'), None)
                require(candidate is not None and output == candidate.get('image_path'),
                        'selection_binding_mismatch', 'Selected output must reference its reviewed candidate')
            else:
                require(output is None, 'selection_binding_mismatch', 'A selection without a candidate cannot deliver an image')
            state = self.state()
            if state['phase'] in {'selected', 'baseline_retained', 'unresolved', 'judge_failed'}:
                require(state.get('selected_output') == output, 'selection_binding_mismatch', 'Case delivery differs from frozen selection')

    def state(self):
        return read_json(self.root / 'case.json')

    def _phase(self, phase, **values):
        state = self.state()
        state.update(phase=phase, **values)
        write_json(self.root / 'case.json', state)
        return state

    def _execution_manifest(self, spec):
        from .bridge import build_execution
        self._check_frozen()
        manifest = build_execution(spec, self.frozen['prepared'], self.config['editor'])
        manifest_path = self.root / 'execution_manifests' / (spec['candidate_id'] + '.json')
        if manifest_path.exists():
            require(digest(read_json(manifest_path)) == digest(manifest), 'execution_manifest_mismatch', 'Frozen execution request changed')
        else:
            write_json(manifest_path, manifest)
        return manifest

    def _execute(self, spec, partition='E1'):
        from .bridge import execute_image
        manifest = self._execution_manifest(spec)
        destination = self.root / 'candidates' / spec['candidate_id']
        existing = destination / 'artifact.json'
        if existing.exists():
            artifact = read_json(existing)
            require(artifact.get('candidate_id') == spec['candidate_id'], 'output_modified', 'Cached artifact belongs to another candidate')
            self._check_artifact_files(artifact)
            return artifact
        artifact = execute_image(manifest, self.root, self.journal, self.config, partition=partition)
        write_json(existing, artifact)
        return artifact

    def _failed_artifact(self, spec, error):
        if 'unknown' in error.code or 'timeout' in error.code or error.code in {
                'output_modified', 'freeze_modified', 'source_modified', 'external_config_modified',
                'execution_manifest_mismatch', 'selection_binding_mismatch'}:
            raise error
        artifact = {'candidate_id': spec['candidate_id'], 'status': 'failed', 'native_image': None,
                    'delivered_image': None, 'sha256': None, 'error': {'code': error.code, 'message': str(error)}}
        write_json(self.root / 'candidates' / spec['candidate_id'] / 'artifact.json', artifact)
        return artifact

    def _record_duplicates(self, pools):
        from PIL import Image
        candidates, observed = {}, {}
        for pool in pools.values():
            for artifact in pool:
                identifier = artifact['candidate_id']
                if identifier in candidates or artifact.get('status') != 'completed':
                    continue
                candidates[identifier] = artifact
                with Image.open(artifact['delivered_image']) as image:
                    image = image.convert('RGB')
                    pixel_hash = sha256_bytes(canonical_json({'mode': image.mode, 'size': list(image.size)}) + image.tobytes())
                artifact['pixel_sha256'] = pixel_hash
                artifact['duplicate_of'] = observed.get(pixel_hash)
                observed.setdefault(pixel_hash, identifier)
                write_json(self.root / 'candidates' / identifier / 'artifact.json', artifact)

    def run(self):
        from .bridge import compose_baseline, preflight
        from .planner import build_plan
        from .evidence import collect_evidence
        with case_lock(self.root):
            self._check_frozen()
            state = self.state()
            if state['phase'] in {'selected', 'baseline_retained', 'unresolved', 'judge_failed'}:
                selected = read_json(self.root / 'selection.json')
                verify_seal(selected)
                return state
            if state['phase'] == 'failed' and state.get('error', {}).get('code') == 'baseline_failed':
                return state
            if self.config['mode'] == 'real':
                readiness = preflight(self.config)
                if readiness.get('status') == 'blocked' or readiness.get('accepted') is False or readiness.get('ready') is False:
                    return self._phase('blocked', error={'code': 'preflight_blocked', 'details': readiness})
            baseline_path = self.root / 'baseline' / 'context.json'
            try:
                if baseline_path.exists():
                    baseline = read_json(baseline_path)
                else:
                    baseline = compose_baseline(self.root, self.task, self.config, self.journal, self.frozen['source'])
                    write_json(baseline_path, baseline)
                c0spec = candidate_spec('C0', 'baseline', 0, self.config['seed_schedule'][0],
                                        baseline['P0'], self.frozen['source']['sha256'])
                c0 = self._execute(c0spec)
                self._check_frozen()
                require(c0.get('status') in {'completed', 'complete', 'produced'}, 'baseline_failed', 'C0 failed; no feedback planning is allowed')
                baseline['C0'] = c0
                self._phase('baseline_ready', error=None)
                plan_path = self.root / 'plan' / 'plan.json'
                if plan_path.exists():
                    plan = read_json(plan_path)
                    verify_seal(plan)
                else:
                    plan = build_plan(self.root, self.task, self.config, baseline, self.frozen['source'], self.journal)
                    if 'freeze_hash' not in plan:
                        plan = seal(plan)
                    write_json(plan_path, plan)
                require(self.config['mode'] != 'real' or plan['plan_origin'] != 'fixture', 'fixture_research_forbidden', 'Real cases require a real planner')
                a_specs = [c0spec]
                if self.config['experiment']['e1_ab']:
                    for index, seed in enumerate(self.config['seed_schedule'][1:], start=1):
                        spec = candidate_spec(f'A{index}', 'baseline_resample', index, seed, baseline['P0'], self.frozen['source']['sha256'])
                        spec['candidate_id'] = 'A_' + spec['candidate_id']
                        a_specs.append(spec)
                for spec in plan['candidate_specs'] + a_specs:
                    self._execution_manifest(spec)
                registration = self.frozen.get('e2_registration')
                if registration and self.task['case_id'] in registration['case_ids']:
                    for spec in self._e2_specs(plan, registration):
                        self._execution_manifest(spec)
                self._phase('plan_frozen', f1_hash=plan['freeze_hash'])
                b_pool = [c0]
                for spec in plan['candidate_specs']:
                    if spec['slot_id'] == 'C0' or spec['candidate_id'] == c0['candidate_id']:
                        continue
                    try:
                        b_pool.append(self._execute(spec))
                    except HREError as error:
                        b_pool.append(self._failed_artifact(spec, error))
                require(len(b_pool) == 4, 'pool_invalid', 'Exactly four terminal slots are required')
                pools = {'B': b_pool}
                if self.config['experiment']['e1_ab']:
                    a_pool = [c0]
                    for spec in a_specs[1:]:
                        try:
                            a_pool.append(self._execute(spec))
                        except HREError as error:
                            a_pool.append(self._failed_artifact(spec, error))
                    pools['A'] = a_pool
                self._record_duplicates(pools)
                write_json(self.root / 'artifacts.json', pools)
                self._phase('candidates_complete')
                evidence = collect_evidence(self.root, self.task, plan, b_pool, self.frozen['source'], self.frozen['prepared'], self.config)
                write_json(self.root / 'evidence' / 'bundle.json', evidence)
                if 'A' in pools:
                    pool_root = self.root / 'pools' / 'A'
                    a_plan = seal({**plan, 'candidate_specs': a_specs, 'issues': [], 'fallbacks': []})
                    write_json(pool_root / 'plan.json', a_plan)
                    a_evidence = collect_evidence(self.root, self.task, a_plan, pools['A'], self.frozen['source'], self.frozen['prepared'], self.config, output_root=pool_root)
                    write_json(pool_root / 'evidence' / 'bundle.json', a_evidence)
                self._phase('evidence_ready')
                result = self._judge('J1', 'B')
                if 'A' in pools:
                    self._judge('J1', 'A')
                return self._phase(result['status'], selected_output=result.get('selected_output'), error=None)
            except HREError as error:
                if 'unknown' in error.code or 'timeout' in error.code:
                    return self._phase('unknown', error={'code': error.code, 'message': str(error)})
                phase = self.state()['phase']
                code = 'baseline_failed' if phase in {'created', 'blocked'} else error.code
                self._phase('failed', error={'code': code, 'cause': error.code, 'message': str(error)})
                raise

    def _judge(self, variant, pool):
        from .judge import judge_pool
        require(variant in {'J0', 'J1', 'J2'}, 'variant_invalid', 'Unknown Judge variant')
        require(pool in {'A', 'B'}, 'pool_invalid', 'Use pool A or B')
        root = self.root if pool == 'B' else self.root / 'pools' / 'A'
        bundle_path = root / 'evidence' / 'bundle.json'
        require(bundle_path.is_file(), 'evidence_missing', 'Generate the frozen pool before judging')
        bundle = read_json(bundle_path)
        verify_seal(bundle)
        journal = self.journal if pool == 'B' else Journal(root, self.config['budgets'])
        result = judge_pool(root, self.task, self.config, bundle, journal, variant)
        result = seal({**result, 'variant': variant, 'pool': pool, 'fixture_only': self.config['mode'] == 'fixture'})
        write_json(root / 'judge' / variant / 'selection.json', result)
        if pool == 'B' and variant == 'J1':
            write_json(self.root / 'selection.json', result)
        return result

    def judge(self, variant, pool='B'):
        with case_lock(self.root):
            self._check_frozen()
            result = self._judge(variant, pool)
            if pool == 'B' and variant == 'J1':
                self._phase(result['status'], selected_output=result.get('selected_output'))
            return result

    def reconcile(self, operation_id, resolution, pool='B'):
        with case_lock(self.root):
            self._check_frozen()
            require(pool in {'A', 'B'}, 'pool_invalid', 'Use pool A or B')
            journal = self.journal if pool == 'B' else Journal(self.root / 'pools' / 'A', self.config['budgets'])
            prior_state = journal.snapshot()['operations'].get(operation_id, {}).get('state')
            result = journal.reconcile(operation_id, resolution)
            if prior_state == 'unknown' and resolution.get('decision') in {'confirmed_completed', 'confirmed_not_executed'}:
                previous_phase = self.state()['phase']
                self._phase('created', error=None, selected_output=None, resume_from_phase=previous_phase)
            return result

    def run_e2(self):
        from .bridge import preflight
        with case_lock(self.root):
            self._check_frozen()
            require(self.config['mode'] == 'real', 'fixture_research_forbidden', 'E2 requires real execution')
            manifest = self.frozen.get('e2_registration')
            require(manifest is not None, 'preregistration_missing', 'E2 registration must be frozen before E1')
            require((self.root / 'plan' / 'plan.json').is_file(), 'plan_missing', 'Freeze F1 before E2')
            cases = manifest.get('case_ids', manifest.get('cases', []))
            ids = [x if isinstance(x, str) else x['case_id'] for x in cases]
            require(self.task['case_id'] in ids, 'case_not_preregistered', 'Case is not in E2 registration')
            seeds = manifest.get('evaluation_seeds', manifest.get('seeds'))
            require(isinstance(seeds, list) and len(seeds) == 2 and not set(seeds) & set(self.config['seed_schedule']), 'seed_schedule_invalid', 'Freeze two new E2 seeds')
            require(len(set(seeds)) == 2 and all(type(seed) is int and 0 <= seed < 2**63 for seed in seeds), 'seed_schedule_invalid', 'E2 seeds must be distinct nonnegative integers')
            e1_budget = 7 if self.config['experiment']['e1_ab'] else 4
            require(self.config['budgets']['image_generation'] >= e1_budget + 8, 'budget_exhausted', 'Reserve the complete E1 plus E2 image budget before starting E2')
            readiness = preflight(self.config)
            require(readiness.get('status') == 'ready', 'preflight_blocked', 'Resolve real deployment prerequisites before E2 generation')
            plan = read_json(self.root / 'plan' / 'plan.json')
            records = []
            specs = self._e2_specs(plan, manifest)
            for spec in specs:
                self._execution_manifest(spec)
            for spec in specs:
                try:
                    artifact = self._execute(spec, partition='E2')
                except HREError as error:
                    artifact = self._failed_artifact(spec, error)
                records.append({'seed': spec['seed'], 'slot_id': spec['slot_id'], 'evaluation_axis_id': spec.get('evaluation_axis_id'), 'effective_strategy_id': spec['effective_strategy_id'], 'artifact': artifact})
            self._record_duplicates({'E2': [record['artifact'] for record in records]})
            result = {'schema_version': VERSION, 'case_id': self.task['case_id'], 'registration_hash': digest(manifest), 'records': records}
            write_json(self.root / 'e2' / 'results.json', result)
            return result

    def _e2_specs(self, plan, registration):
        originals = plan['candidate_specs']
        require(len(originals) == 4 and len({item['slot_id'] for item in originals}) == 4
                and any(item['slot_id'] == 'C0' for item in originals), 'pool_invalid', 'E2 requires four frozen F1 slots including C0')
        specs = []
        for seed in registration['evaluation_seeds']:
            for original in originals:
                spec = deepcopy(original)
                spec.update(seed=seed, candidate_id=f"E2_{original['effective_strategy_id']}_s{original['sample_index']}_seed{seed}")
                specs.append(spec)
        return specs

    def write_report(self):
        from .report import write_report
        with case_lock(self.root):
            self._check_frozen()
            return write_report(self.root)
