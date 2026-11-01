"""New semantic records do not reinterpret historical style targets."""
from copy import deepcopy
import unittest
import test_s4 as fixture
from hre.reference_core.contracts import DIMENSIONS
from hre.reference_style import unified, coordinator as co


class UnifiedStyleTest(unittest.TestCase):
    def setUp(self):
        self.f = fixture.S4Test(); self.f.setUp(); self.addCleanup(self.f.doCleanups)

    def semantic_spec(self, prepare=True):
        f = self.f
        if prepare: f.draft()
        targets = [dict(target_id=t['target_id'], attribute='shadow_midtone_highlight', source_observation='A state.',
                        reference_observation='B state.', comparability='conditional', uncertainty='Mixed illumination: direction only.',
                        mandatory=True, acceptance_criterion='Match supported whole-region appearance without over-brightening.')
                   for t in f.target['payload']['targets']]
        coverage = [dict(attribute=a, status='targeted' if a == 'shadow_midtone_highlight' else 'preserve', reason='Fixture observation.',
                         target_ids=[t['target_id'] for t in targets] if a == 'shadow_midtone_highlight' else []) for a in sorted(DIMENSIONS)]
        return dict(version='u1', outcome='edit', target_version='v1',
                    semantics=dict(coverage=coverage, targets=targets, delivery_requirements={}))

    def test_complete_semantics_enter_actual_prompt_and_preserve_target_hash(self):
        spec = self.semantic_spec(); before = deepcopy(self.f.target)
        frozen = unified.freeze_semantics(self.f.case, spec)
        draft = self.f.st.compile_targets(self.f.case, 'v1')
        self.assertIn('Mixed illumination: direction only.', draft['payload']['prompt'])
        self.assertIn('without over-brightening', draft['payload']['prompt'])
        self.assertEqual(self.f.target, before)
        self.assertEqual(draft['payload']['unified_semantics_hash'], frozen['content_hash'])

    def test_missing_requirement_or_foreign_target_cannot_freeze(self):
        spec = self.semantic_spec(); spec['semantics']['coverage'].pop()
        with self.assertRaises(ValueError): unified.freeze_semantics(self.f.case, spec)

    def test_known_infeasible_plan_blocks_export_without_spending_budget(self):
        spec = self.semantic_spec(); unified.freeze_semantics(self.f.case, spec)
        draft = self.f.st.compile_targets(self.f.case, 'v1')
        result = unified.record_preflight(self.f.case, dict(semantic_version='u1', planned_size=[2, 1], capability_known=True))
        self.assertEqual(result['payload']['assessment']['status'], 'infeasible')
        before = co.status(self.f.case)['payload']['budget']['used']['edit_attempts']
        with self.assertRaises(ValueError): self.f.handoff.export_edit(self.f.case, draft['record_id'])
        self.assertEqual(co.status(self.f.case)['payload']['budget']['used']['edit_attempts'], before)

    def test_unknown_backend_is_explicit_and_does_not_imply_delivery_pass(self):
        spec = self.semantic_spec(); unified.freeze_semantics(self.f.case, spec)
        result = unified.record_preflight(self.f.case, dict(semantic_version='u1', planned_size=None, capability_known=False))
        self.assertEqual(result['payload']['assessment']['status'], 'unknown')

    def test_no_edit_returns_original_A_without_editor_or_compiler_calls(self):
        f = self.f; report = f.report(); _, diagnosis = f.diagnose(report, 'Synthetic reviewed already-satisfied observation.')
        coverage = [dict(attribute=a, status='already_satisfied', reason='Reviewed fixture only.', target_ids=[]) for a in sorted(DIMENSIONS)]
        spec = dict(version='u1', outcome='already_satisfied', target_version=None,
                    semantics=dict(coverage=coverage, targets=[], delivery_requirements={}),
                    basis=dict(report_id=report['record_id'], diagnosis_record_id=diagnosis['record_id'],
                               requested_operation='match_reference_appearance_only', observation='Synthetic imported review says no supported edit remains.'))
        unified.freeze_semantics(f.case, spec)
        result = unified.complete_no_edit(f.case)
        self.assertEqual(result['payload']['status'], 'already_satisfied')
        self.assertEqual(result['payload']['image_calls'], 0)
        self.assertEqual(result['payload']['compiler_calls'], 0)
        self.assertEqual(result['payload']['source_hash'], f.audit[0]['derivative_file_hash'])

    def test_targets_alone_cannot_bypass_whole_image_review(self):
        f = self.f; original_draft = f.draft
        def reviewed_draft():
            original_draft()
            unified.freeze_semantics(f.case, self.semantic_spec(prepare=False))
            unified.record_preflight(f.case, dict(semantic_version='u1', planned_size=None, capability_known=False))
            return f.st.compile_targets(f.case, 'v1')
        f.draft = reviewed_draft
        f.configured_evaluation()
        facts = f.review.freeze_facts(f.case, f.facts_spec())
        decision = f.decision(facts)['payload']
        self.assertEqual(decision['status'], 'needs_user_review')
        self.assertIn('Whole-image-first', decision['unified_holistic_assessment']['reason'])


if __name__ == '__main__': unittest.main()
