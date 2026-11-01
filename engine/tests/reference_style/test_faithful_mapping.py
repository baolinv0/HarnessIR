"""Mapping-only tests; fixture diagnoses are synthetic, never actual model calls."""
import copy,hashlib,unittest
import test_visual_goals as f
from hre.reference_style import visual_goals as vg
from hre.reference_style.s4_targets import target_view
from hre.reference_style.contracts import PRESERVATION

class FaithfulMappingTest(unittest.TestCase):
    setUp=f.VisualGoalsTest.setUp
    manifest=f.VisualGoalsTest.manifest;import_array=f.VisualGoalsTest.import_array;import_json=f.VisualGoalsTest.import_json
    supports=f.VisualGoalsTest.supports;report=f.VisualGoalsTest.report;receipt=f.VisualGoalsTest.receipt;diagnose=f.VisualGoalsTest.diagnose
    setup_goals=f.VisualGoalsTest.setup_goals
    def convert(self,spec):
        self.assertTrue(callable(getattr(vg,'faithful_mapping',None)),'faithful_mapping production helper is missing')
        return vg.faithful_mapping(spec,strength_basis='mapping_added_labels')
    def duplicated(self):
        report,diag,spec=self.setup_goals()
        extra=copy.deepcopy(spec['targets'][0]);extra.update(target_id='t3',visual_dimension='color',visual_direction='match_B');spec['targets'].append(extra)
        edge=copy.deepcopy(spec['targets'][1]);edge['target_id']='t4';edge['visual_goal']['relation']=dict(relation_id='l8',left_region_id='r2',right_region_id='r1');spec['targets'].append(edge)
        return report,diag,spec
    def test_helper_only_strips_explicitly_mapping_added_labels_without_mutating(self):
        _,_,spec=self.setup_goals();before=copy.deepcopy(spec);new=self.convert(spec)
        self.assertEqual(spec,before)
        for old,t in zip(spec['targets'],new['targets']):
            self.assertIsNone(t['visual_goal']['strength']);expected=copy.deepcopy(old);expected['visual_goal']['strength']=None;self.assertEqual(t,expected)
            self.assertEqual(t['visual_goal']['instruction'],old['visual_goal']['instruction'])
        with self.assertRaises(ValueError):vg.faithful_mapping(spec,strength_basis='diagnosis_structured')
        with self.assertRaises(TypeError):vg.faithful_mapping(spec)
    def test_null_strength_freezes_compiles_exports_and_projects_all_associations(self):
        report,diag,spec=self.duplicated()
        for t in spec['targets']:t['visual_goal']['strength']=None
        try:target=self.st.freeze_targets(self.case,spec)
        except ValueError as e:self.fail('null means no supplemental intensity label and must be supported: '+str(e))
        draft=self.st.compile_targets(self.case,'v1');p=draft['payload'];req=self.handoff.export_edit(self.case,draft['record_id'])
        self.assertEqual(p['prompt_version'],'faithful_diagnosis_goals_v1');self.assertEqual(req['payload']['prompt_version'],'s3_faithful_diagnosis_goals_v1')
        self.assertNotIn('strength=',p['prompt']);self.assertIn('strong tonal lift',p['prompt']);self.assertIn(PRESERVATION,p['prompt'])
        for sentence in {t['visual_goal']['instruction'] for t in spec['targets']}:self.assertEqual(p['prompt'].count(sentence),1)
        for tid in ('t1','t2','t3','t4'):self.assertIn(tid,p['prompt'])
        self.assertIn('l9: r1 -> r2',p['prompt']);self.assertIn('l8: r2 -> r1',p['prompt']);self.assertIn('color',p['prompt']);self.assertIn('brightness',p['prompt'])
        self.assertEqual(p['covered_target_ids'],['t1','t2','t3','t4'])
        for numbers in (False,True):
            view=target_view(target,report,numbers);self.assertEqual(len(view),4)
            self.assertTrue(all(t['visual_goal']['strength'] is None for t in view));self.assertEqual(view[1]['left_region_id'],'r1');self.assertEqual(view[3]['left_region_id'],'r2')
        self.assertNotIn('ARCHIVAL_NOTE_NOT_SELECTED',req['payload']['prompt'])
    def test_mixed_label_modes_rejected_not_silently_merged(self):
        _,_,spec=self.setup_goals();spec['targets'][0]['visual_goal']['strength']=None
        try:self.st.freeze_targets(self.case,spec)
        except ValueError as e:self.fail('nullable goal contract not implemented before mixed render check: '+str(e))
        with self.assertRaises(ValueError):self.st.compile_targets(self.case,'v1')
    def test_legacy_prompt_bytes_unchanged(self):
        _,_,spec=self.setup_goals();self.st.freeze_targets(self.case,spec);draft=self.st.compile_targets(self.case,'v1')
        self.assertEqual(hashlib.sha256(draft['payload']['prompt'].encode()).hexdigest(),'927303e4c81b48f637ab168dd859304b917d24238cde41f489a6bef6796fea78')
        self.assertEqual(draft['payload']['prompt_version'],'diagnosis_backed_visual_goals_v1')
    def test_pure_renderer_is_same_production_path_and_quote_binding_survives(self):
        report,diag,spec=self.setup_goals();spec=self.convert(spec);target=self.st.freeze_targets(self.case,spec);draft=self.st.compile_targets(self.case,'v1')
        from hre.reference_style.s2_public import diagnostic_view
        renderer=getattr(self.st,'render_target_prompt',None);self.assertTrue(callable(renderer),'shared renderer required')
        text='Warm peach face with strong tonal lift. Keep the wall less bright than the face. ARCHIVAL_NOTE_NOT_SELECTED'
        prompt,version=renderer(target['payload'],diagnostic_view(report['payload']),diag,text)
        self.assertEqual(prompt,draft['payload']['prompt']);self.assertEqual(version,draft['payload']['prompt_version'])
        with self.assertRaises(ValueError):renderer(target['payload'],diagnostic_view(report['payload']),diag,'different diagnosis')

if __name__=='__main__':unittest.main()
