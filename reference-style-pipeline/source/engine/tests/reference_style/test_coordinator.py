"""Synthetic offline bridge fixtures. All receipts explicitly say synthetic_fixture."""
import copy
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image
from hre.models import file_sha256, HREError
from hre.storage import read_json


class CoordinatorTest(unittest.TestCase):
    def setUp(self):
        try:
            self.c = importlib.import_module('hre.reference_style.coordinator')
        except ModuleNotFoundError:
            self.fail('S1 offline coordinator is not implemented')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.out = self.root / 'sample'
        inputs = []
        for role, color in [('A', 'red'), ('B', 'blue')]:
            p = self.root / f'{role}.png'
            Image.new('RGB', (4, 3), color).save(p)
            inputs.append(dict(role=role, path=str(p), encoding='srgb', encoding_basis='synthetic',
                               base_model_version='fixture-base' if role == 'A' else None, display_assumption=None))
        self.config = dict(sample_id='fixture1', provider='current_chat_offline', purpose='protocol_fixture', inputs=inputs)
        self.context = dict(target_version='v1', targets=[], evidence=[], feedback=[])

    def create(self):
        return self.c.create_sample(self.config, self.out)

    def export(self, stage='ab_diagnosis', context=None):
        return self.c.export_request(self.out, stage, context or self.context)

    def receipt(self, request, output, **changes):
        p = request['payload']
        value = dict(schema_version='reference_style_s4_v6', sample_id='fixture1',
                     attempt_id=p['attempt_id'], stage_id=p['stage_id'], request_hash=request['content_hash'],
                     target_version=p['context']['target_version'], target_hash=p['context']['target_hash'],
                     prompt_hash=p['prompt_hash'], role_bindings=p['role_bindings'],
                     response_type=p['expected_response_type'], output_sha256=file_sha256(output),
                     provenance=dict(origin='synthetic_fixture', provider='chatgpt',
                         conversation_ref='synthetic://test', tool_call_ref='synthetic-test-call',
                         model_version=None, transcription_note='Synthetic protocol fixture, not actual model evidence',
                         input_visibility='audited_files_attached_internal_transforms_unknown'))
        value.update(changes)
        return value

    def test_create_audits_both_roles_preserves_original_and_refuses_reuse(self):
        state = self.create()
        self.assertEqual(state['payload']['sample_state'], 'input_audited')
        self.assertIsNone(state['payload']['active_attempt'])
        audit = read_json(self.out / 'input_audit.json')
        self.assertEqual([i['role'] for i in audit['payload']['images']], ['A', 'B'])
        self.assertEqual((self.out / 'assets/A/source.bin').read_bytes(), (self.root / 'A.png').read_bytes())
        with self.assertRaises((ValueError, FileExistsError)):
            self.create()

    def test_create_rejects_missing_duplicate_roles_and_x_before_read(self):
        for inputs in [self.config['inputs'][:1], [self.config['inputs'][0]] * 2]:
            with self.subTest(inputs=inputs), self.assertRaises(ValueError):
                self.c.create_sample({**self.config, 'inputs': inputs}, self.out)
            self.assertFalse(self.out.exists())
        with self.assertRaises(ValueError):
            self.c.create_sample({**self.config, 'X': '/do/not/read'}, self.out)
        self.assertFalse(self.out.exists())

    def test_export_waits_and_reexport_never_allocates_another_attempt(self):
        self.create()
        request = self.export()
        state = self.c.status(self.out)
        self.assertEqual(state['payload']['active_attempt']['status'], 'waiting_for_response')
        self.assertEqual(state['payload']['active_attempt']['attempt_id'], request['payload']['attempt_id'])
        with self.assertRaises(ValueError):
            self.export()
        self.assertEqual(len(list((self.out / 'attempts').iterdir())), 1)
        self.assertEqual([x['role'] for x in request['payload']['images']], ['A', 'B'])
        self.assertEqual(request['payload']['provider'], 'current_chat_offline')

    def test_unknown_pauses_same_identity_and_can_import_later(self):
        self.create()
        request = self.export()
        self.c.mark_unknown(self.out, request['payload']['attempt_id'], 'tool outcome not yet established')
        with self.assertRaises(ValueError):
            self.export()
        output = self.root / 'response.txt'
        output.write_text('Synthetic AB observation fixture')
        result = self.c.import_response(self.out, self.receipt(request, output), output)
        self.assertEqual(result['payload']['protocol_status'], 'validated')
        self.assertFalse(result['payload']['real_execution_evidence'])
        self.assertEqual(self.c.status(self.out)['payload']['attempts'][0]['status'], 'validated')

    def test_stale_missing_duplicate_role_or_hash_receipts_rejected_without_consuming_attempt(self):
        self.create()
        request = self.export()
        output = self.root / 'response.txt'
        output.write_text('Synthetic AB observation fixture')
        clean = self.receipt(request, output)
        variants = []
        for key in ['attempt_id', 'stage_id', 'sample_id', 'request_hash', 'target_version', 'target_hash', 'prompt_hash', 'output_sha256']:
            variants.append({**clean, key: 'stale'})
        variants += [{**clean, 'role_bindings': clean['role_bindings'][:1]},
                     {**clean, 'role_bindings': [clean['role_bindings'][0]] * 2}]
        missing = copy.deepcopy(clean)
        missing.pop('provenance')
        variants.append(missing)
        for receipt in variants:
            with self.subTest(receipt=receipt), self.assertRaises(ValueError):
                self.c.import_response(self.out, receipt, output)
            self.assertEqual(self.c.status(self.out)['payload']['active_attempt']['status'], 'waiting_for_response')
        imported = self.c.import_response(self.out, clean, output)
        self.assertEqual(self.c.import_response(self.out, clean, output), imported)

    def test_source_derivative_request_or_state_tamper_rejected(self):
        for relative in ['assets/A/source.bin', 'assets/B/input.png', 'input_audit.json', 'state.json']:
            with self.subTest(relative=relative):
                out = self.root / relative.replace('/', '_')
                self.c.create_sample(self.config, out)
                path = out / relative
                path.write_bytes(path.read_bytes() + b'x')
                with self.assertRaises((ValueError, HREError)):
                    self.c.export_request(out, 'ab_diagnosis', self.context)

    def test_private_policy_never_serialized_to_execution_even_as_notes(self):
        self.create()
        private = self.out / 'private_verification'
        private.mkdir()
        (private / 'policy.json').write_text('{"secret_policy": "SENTINEL_TOLERANCE"}')
        request = self.export()
        self.assertNotIn('SENTINEL_TOLERANCE', json.dumps(request))
        self.assertNotIn('private_verification', json.dumps(request))

    def test_edit_import_preserves_raw_and_records_geometry_mismatch_not_acceptance(self):
        self.create()
        context = {**self.context, 'targets': [dict(target_id='t1', unit='global', region_refs=[],
            effect={'dimension':'tone','direction':'match_B'}, numeric_range=None,
            judge_type='visual', priority='critical', evidence_ids=[])]}
        request = self.export('edit', context)
        output = self.root / 'candidate.png'
        Image.new('RGB', (6, 5), 'green').save(output)
        result = self.c.import_response(self.out, self.receipt(request, output), output)
        p = result['payload']
        self.assertEqual(p['candidate_hash'], file_sha256(output))
        self.assertEqual(p['geometry']['size_matches_A'], False)
        self.assertEqual(p['geometry']['spatial_correspondence'], 'unverified')
        self.assertEqual(p['geometry']['numeric_support_status'], 'uncertain')
        self.assertEqual(p['visual_style_status'], 'not_evaluated')
        self.assertEqual(p['pixel_supervision_screening_status'], 'undetermined')
        self.assertEqual((self.out / p['output_path']).read_bytes(), output.read_bytes())

    def test_real_sample_refuses_synthetic_provenance(self):
        self.config['purpose'] = 'reference_style'
        self.create()
        # v6: a real-purpose contract needs explicit limits even in this test fixture.
        from hre.reference_style.s4_budget import configure_budget
        configure_budget(self.out,dict(version='b1',edit_attempts=1,diagnostics=1,feedback_rounds=0,total=2))
        request = self.export()
        output = self.root / 'response.txt'
        output.write_text('fixture')
        with self.assertRaises(ValueError):
            self.c.import_response(self.out, self.receipt(request, output), output)

    def test_imported_raw_output_tamper_blocks_status_and_future_requests(self):
        self.create()
        request = self.export()
        output = self.root / 'response.txt'
        output.write_text('Synthetic diagnostic observation')
        result = self.c.import_response(self.out, self.receipt(request, output), output)
        (self.out / result['payload']['output_path']).write_text('modified')
        with self.assertRaises(ValueError):
            self.c.status(self.out)

    def test_orphan_export_directory_blocks_new_attempt_until_reconciled(self):
        self.create()
        (self.out / 'attempts/orphan').mkdir(parents=True)
        with self.assertRaises(ValueError):
            self.export()

    def test_unknown_a_blocks_numeric_and_mixed_targets_but_not_visual(self):
        self.config['inputs'][0].update(encoding='unknown', display_assumption='srgb')
        target = dict(target_id='t1', unit='global', region_refs=[],
                      effect={'dimension':'brightness','direction':'match_B'}, numeric_range=None,
                      judge_type='numeric', priority='critical', evidence_ids=[])
        for judge in ['numeric', 'mixed']:
            self.out = self.root / judge
            self.create()
            with self.subTest(judge=judge), self.assertRaises(ValueError):
                self.export('edit', {**self.context, 'targets': [{**target, 'judge_type': judge}]})
        self.out = self.root / 'visual'
        self.create()
        self.export('edit', {**self.context, 'targets': [{**target, 'judge_type': 'visual'}]})

    def test_abc_requires_candidate_hash_and_unchanged_target_binding(self):
        self.create()
        context = {**self.context, 'targets': [dict(target_id='t1', unit='global', region_refs=[],
            effect={'dimension':'tone','direction':'match_B'}, numeric_range=None,
            judge_type='visual', priority='critical', evidence_ids=[])]}
        request = self.export('edit', context)
        output = self.root / 'candidate.png'
        Image.new('RGB', (4, 3), 'green').save(output)
        self.c.import_response(self.out, self.receipt(request, output), output)
        with self.assertRaises(ValueError):
            self.c.export_request(self.out, 'abc_diagnosis', context, 'f' * 64)
        with self.assertRaises(ValueError):
            self.c.export_request(self.out, 'abc_diagnosis', {**context, 'target_version': 'v2'}, file_sha256(output))
        actual = self.c.export_request(self.out, 'abc_diagnosis', context, file_sha256(output))
        self.assertEqual(actual['payload']['candidate']['candidate_hash'], file_sha256(output))

    def test_private_policy_records_are_only_opened_by_explicit_verifier_reader(self):
        self.create()
        try:
            verifier = importlib.import_module('hre.reference_style.verification_store')
        except ModuleNotFoundError:
            self.fail('private verifier-only policy storage not implemented')
        policy = dict(policy_id='policy1', version='v1',
                      overall_style_achieved_required=True,
                      posthoc_principles=['SENTINEL_POLICY_minor_incidental_deviation'],
                      unknown_or_major_deviation='insufficient_evidence_or_reject')
        saved = verifier.store_policy(self.out, policy)
        self.assertEqual(verifier.read_policy_for_verifier(self.out, 'policy1')['content_hash'], saved['content_hash'])
        request = self.export()
        self.assertNotIn('SENTINEL_POLICY', json.dumps(request))
        with self.assertRaises((ValueError, FileExistsError)):
            verifier.store_policy(self.out, policy)

    def test_cli_run_and_status_work_without_legacy_optional_ui_dependencies(self):
        config = self.root / 'config.json'
        config.write_text(json.dumps(self.config))
        args = [sys.executable, '-m', 'hre', 'reference-style']
        run = subprocess.run(args + ['run', '--config', str(config), '--out', str(self.out)], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
        self.assertEqual(json.loads(run.stdout)['payload']['sample_state'], 'input_audited')
        status = subprocess.run(args + ['status', '--root', str(self.out)], capture_output=True, text=True)
        self.assertEqual(status.returncode, 0, status.stderr + status.stdout)
        self.assertEqual(json.loads(status.stdout)['sample_id'], 'fixture1')


if __name__ == '__main__':
    unittest.main()
