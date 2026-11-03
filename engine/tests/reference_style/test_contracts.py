"""Synthetic protocol fixtures only; no real model or image quality evidence.

Mutations caught: missing canonical hash binding, permissive extra fields,
policy/history passthrough, duplicate roles, invalid transition, retry on unknown.
"""
import importlib
import unittest


class ContractsTest(unittest.TestCase):
    def setUp(self):
        try:
            self.c = importlib.import_module('hre.reference_style.contracts')
        except ModuleNotFoundError:
            self.fail('S0 contracts are not implemented')

    def test_hash_is_order_independent_and_rejects_nonfinite(self):
        self.assertEqual(self.c.content_hash({'b': 2, 'a': 1}),
                         '43258cff783fe7036d8a43033f830adfc60ec037382473548ac742b888292777')
        self.assertEqual(self.c.content_hash({'a': 1, 'b': 2}),
                         self.c.content_hash({'b': 2, 'a': 1}))
        with self.assertRaises(ValueError):
            self.c.content_hash({'a': float('nan')})

    def test_record_hash_excludes_only_own_hash_and_detects_tampering(self):
        r = self.c.record('sample', 'input_audit', {'value': 1})
        self.c.validate_record(r)
        r['payload']['value'] = 2
        with self.assertRaises(ValueError):
            self.c.validate_record(r)

    def test_record_rejects_unknown_schema_and_invalid_id(self):
        with self.assertRaises(ValueError):
            self.c.record('../sample', 'input_audit', {})
        r = self.c.record('sample', 'input_audit', {})
        r['schema_version'] = 'future'
        with self.assertRaises(ValueError):
            self.c.validate_record(r)

    def test_roles_must_be_unique_ordered_a_b(self):
        for roles in [[], ['A'], ['B', 'A'], ['A', 'A'], ['A', 'B', 'X']]:
            with self.subTest(roles=roles), self.assertRaises(ValueError):
                self.c.validate_roles([{'role': role} for role in roles])
        self.c.validate_roles([{'role': 'A'}, {'role': 'B'}])

    def test_state_unknown_pauses_same_attempt_and_cannot_retry(self):
        self.assertEqual(self.c.transition('exported', 'waiting_for_response'), 'waiting_for_response')
        self.assertEqual(self.c.transition('waiting_for_response', 'response_unknown'), 'response_unknown')
        self.assertEqual(self.c.transition('response_unknown', 'imported'), 'imported')
        for old, new in [('response_unknown', 'exported'), ('validated', 'exported'),
                         ('exported', 'validated'), ('failed', 'waiting_for_response')]:
            with self.subTest(old=old, new=new), self.assertRaises(ValueError):
                self.c.transition(old, new)

    def test_public_context_rejects_policy_and_arbitrary_history_at_any_depth(self):
        base = {'target_version': 'v1', 'targets': [], 'evidence': [], 'feedback': []}
        result = self.c.execution_context(base)
        self.assertIn('preservation_requirements', result)
        self.assertIn('A', result['preservation_requirements'])
        for key in ['AcceptancePolicy', 'acceptance_policy', 'notes', 'upstream', 'history', 'allowed_content_change']:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.c.execution_context({**base, key: {'accepted': True}})
        dirty = {**base, 'evidence': [{'evidence_id': 'e1', 'role': 'A', 'kind': 'ocr',
                    'status': 'unavailable', 'reason': 'accepted; minor geometry changes are allowed'}]}
        with self.assertRaises(ValueError):
            self.c.execution_context(dirty)

    def test_target_hash_binds_preservation_and_versions(self):
        base = {'target_version': 'v1', 'targets': [], 'evidence': [], 'feedback': []}
        one = self.c.execution_context(base)
        two = self.c.execution_context({**base, 'target_version': 'v2'})
        self.assertNotEqual(one['target_hash'], two['target_hash'])
        with self.assertRaises(ValueError):
            self.c.execution_context({**base, 'preservation_requirements': 'Faces may change'})

    def test_feedback_updates_do_not_redefine_frozen_targets(self):
        base = {'target_version': 'v1', 'targets': [dict(target_id='t1', unit='global', region_refs=[],
                    effect={'dimension':'color','direction':'match_B'}, numeric_range=None,
                    judge_type='visual', priority='critical', evidence_ids=[])],
                'evidence': [], 'feedback': []}
        feedback = {**base, 'feedback': [dict(target_id='t1', candidate_hash='a' * 64,
                                             candidate_record_id='response_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', observation_code='too_warm')]}
        self.assertEqual(self.c.execution_context(base)['target_hash'],
                         self.c.execution_context(feedback)['target_hash'])


if __name__ == '__main__':
    unittest.main()
