import copy,unittest
import test_s3 as f
from hre.reference_style.contracts import PRESERVATION
from hre.reference_style.s4_targets import target_view

class VisualGoalsTest(unittest.TestCase):
    setUp=f.S3Test.setUp
    manifest=f.S3Test.manifest;import_array=f.S3Test.import_array;import_json=f.S3Test.import_json
    supports=f.S3Test.supports;report=f.S3Test.report;receipt=f.S3Test.receipt;diagnose=f.S3Test.diagnose
    def setup_goals(self):
        report=self.report();quote='Warm peach face with strong tonal lift. Keep the wall less bright than the face.'
        _,diag=self.diagnose(report,quote+' ARCHIVAL_NOTE_NOT_SELECTED')
        def item(tid,rid,text,strength,relation=None):
            return dict(target_id=tid,measurement_id=None,visual_region_id=rid,visual_dimension='brightness',visual_direction='increase_toward_B' if rid else 'match_B',judge_type='visual',priority='critical',visual_goal=dict(instruction=text,strength=strength,relation=relation))
        spec=dict(version='v1',report_id=report['record_id'],diagnosis_record_id=diag['record_id'],targets=[item('t1','r1','Warm peach face with strong tonal lift.','strong'),item('t2',None,'Keep the wall less bright than the face.','relative',dict(relation_id='l9',left_region_id='r1',right_region_id='r2'))])
        return report,diag,spec
    def test_exact_appearance_strength_relation_survive_compile_edit_and_ABC(self):
        report,diag,spec=self.setup_goals();target=self.st.freeze_targets(self.case,spec);draft=self.st.compile_targets(self.case,'v1');req=self.handoff.export_edit(self.case,draft['record_id'])
        for text in ('Warm peach face with strong tonal lift.','Keep the wall less bright than the face.','strong','r1','r2',PRESERVATION):self.assertIn(text,req['payload']['prompt'])
        self.assertNotIn('ARCHIVAL_NOTE_NOT_SELECTED',req['payload']['prompt'])
        self.assertEqual(req['payload']['prompt_version'],'s3_diagnosis_backed_visual_goals_v1')
        self.assertEqual([r['region_id'] for r in req['payload']['planned_attachments'][2]['regions']],['r1','r2'])
        for numbers in (False,True):
            view=target_view(target,report,numbers);self.assertEqual(view[0]['visual_goal']['instruction'],spec['targets'][0]['visual_goal']['instruction']);self.assertEqual(view[1]['left_region_id'],'r1');self.assertEqual(view[1]['right_region_id'],'r2');self.assertIsNone(view[1]['reference_measurement'])
    def test_instruction_must_come_from_bound_diagnosis(self):
        report,diag,spec=self.setup_goals();spec['targets'][0]['visual_goal']['instruction']='Unseen claim'
        with self.assertRaises(ValueError):self.st.freeze_targets(self.case,spec)
    def test_relation_endpoints_must_exist_and_differ(self):
        report,diag,spec=self.setup_goals()
        for endpoint in ('r1','r99'):
            bad=copy.deepcopy(spec);bad['targets'][1]['visual_goal']['relation']['right_region_id']=endpoint
            with self.assertRaises(ValueError):self.st.freeze_targets(self.case,bad)
    def test_projection_does_not_erase_binding_or_accept_changed_quote(self):
        report,diag,spec=self.setup_goals();target=self.st.freeze_targets(self.case,spec)
        bad=copy.deepcopy(target);bad['payload']['targets'][0]['visual_goal']['instruction']='changed'
        with self.assertRaises(ValueError):target_view(bad,report,True)

if __name__=='__main__':unittest.main()
