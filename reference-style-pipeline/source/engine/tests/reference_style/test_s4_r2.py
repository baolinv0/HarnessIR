"""Selected-artifact and factual ABC regressions; synthetic fixtures only."""
import copy,json,unittest
import numpy as np
from PIL import Image
import test_s4 as fixture
from hre.models import file_sha256
from hre.storage import read_json
from hre.reference_style import coordinator as co,s4_evaluate as ev,s4_review as review,s4_verify as verify
from hre.tool_retouch.color import encode_png16


class S4R2Test(unittest.TestCase):
    for name in ('setUp','manifest','import_array','import_json','supports','report','receipt','diagnose','target_spec','draft','submission','candidate','color',
                 'prepare','version_spec','support_spec','evaluated','review_modules','abc_response','facts_spec','decision'):
        locals()[name]=getattr(fixture.S4Test,name)

    def real_bytes(self,p3=False):
        self.review_modules()
        levels=np.full((2,4,3),.5155 if p3 else 10001/65535,dtype=float)
        b=self.root/'B16.png';encode_png16(b,levels)
        config=copy.deepcopy(self.config);config['inputs'][1]['path']=str(b);self.case=self.root/'case16';self.config=config
        co.create_sample(config,self.case);self.audit=read_json(self.case/'input_audit.json')['payload']['images']
        before=(self.case/'input_audit.json').read_bytes();self.compiled=self.draft();request=self.handoff.export_edit(self.case,self.compiled['record_id'])
        raw=b
        if p3:raw=self.root/'rawP3.png';Image.new('RGB',(4,2),(255,0,0)).save(raw)
        self.response,_,_=self.candidate(request,raw);self.derived=self.candidates.derive_candidate(self.case,self.response['record_id'],self.color('display_p3' if p3 else 'auto'))
        self.profile=ev.freeze_version(self.case,self.version_spec());ev.freeze_supports(self.case,self.support_spec())
        self.evaluation=ev.evaluate(self.case,dict(evaluation_id='j1',version='q1',candidate_record_id=self.response['record_id'],derived_record_id=self.derived['record_id'],support_id='k1',reevaluation=None))
        self.assertEqual((self.case/'input_audit.json').read_bytes(),before)
        return self.evaluation

    def row(self,evaluation,rid='r1'):
        return next(r for r in evaluation['payload']['measurements'] if r['subject_id']==rid and r['metric']=='linear_Y' and r['statistic']=='q50')

    def selected_Y(self):
        pixels=np.asarray(Image.open(self.case/self.derived['payload']['audit']['derivative_path']),float)/255
        linear=np.where(pixels<=.04045,pixels/12.92,((pixels+.055)/1.055)**2.4)
        return float(np.median(linear[0]@np.array([.2126,.7152,.0722])))

    def calibrated_decision(self,tolerance):
        proof=self.root/'fixture_calibration.txt';proof.write_text('SYNTHETIC fixture rule, not user calibration')
        source=dict(origin='synthetic_fixture',path=str(proof),sha256=file_sha256(proof))
        policy=verify.install_policy(self.case,dict(policy_id='p1',version='v1',allow_minor_incidental=True,source=source))
        rule=verify.install_rule(self.case,dict(rule_id='rv1',version='v1',target_hash=self.target['content_hash'],policy_hash=policy['content_hash'],source=source,
            global_anchors=['tone','color','brightness'],visual_target_ids=['t1','t2','t3'],numeric_tolerances=[dict(target_id=t,max_abs_residual=tolerance) for t in ('t1','t2','t3')],
            critical_preservation=['identity','ocr','naturalness'],required_confidence='high',review_basis='independent_image_first'))
        self.verification_ref=dict(policy_id='p1',policy_version='v1',policy_hash=policy['content_hash'],rule_id='rv1',rule_version='v1',rule_hash=rule['content_hash'])
        facts=review.freeze_facts(self.case,self.facts_spec());return self.decision(facts)

    def test_RGB16_primary_residual_is_exact_selected_RGB8_not_native(self):
        e=self.real_bytes();m=self.row(e);expected=self.selected_Y()
        self.assertAlmostEqual(m['C'],expected,places=14)
        self.assertGreater(m['candidate_absolute_residual'],1e-6)
        native=e['payload']['native_C_diagnostics']['distributions']['r1']['linear_Y']['values']['q50']
        self.assertAlmostEqual(native,m['B'],places=14);self.assertNotAlmostEqual(native,expected,places=6)
        binding=e['payload']['selected_artifact'];audit=self.derived['payload']['audit']
        self.assertEqual(binding['file_hash'],audit['derivative_file_hash']);self.assertEqual(binding['analysis_source_file_hash'],binding['file_hash'])
        self.assertEqual(binding['pixel_hash'],audit['derivative_pixel_hash']);self.assertEqual(binding['bit_depth'],8)
        self.assertEqual(file_sha256(self.case/binding['analysis_path']),binding['analysis_file_hash'])
        self.assertEqual(e['payload']['raw_candidate_hash'],self.response['payload']['candidate_hash'])

    def test_quantization_cannot_accept_or_select_using_zero_native_residual(self):
        self.real_bytes();decision=self.calibrated_decision(0.)
        self.assertNotEqual(decision['payload']['status'],'accepted')
        selected=verify.select(self.case,dict(selection_id='sel1',version='q1',decision_ids=['z1'],rule_version='first_accepted_generation_order_v1'))
        self.assertIsNone(selected['payload']['label_manifest'])

    def test_P3_clipping_primary_is_selected_pixels_and_tight_predicate_changes(self):
        e=self.real_bytes(p3=True);m=self.row(e);self.assertAlmostEqual(m['C'],self.selected_Y(),places=14)
        self.assertGreater(self.derived['payload']['audit']['gamut_clipped_pixel_fraction'],0)
        native=e['payload']['native_C_diagnostics']['distributions']['r1']['linear_Y']['values']['q50']
        self.assertLess(abs(native-m['B']),.001);self.assertGreater(m['candidate_absolute_residual'],.01)
        self.assertNotEqual(self.calibrated_decision(.001)['payload']['status'],'accepted')

    def test_unknown_tagged_display_never_becomes_numeric(self):
        e=self.evaluated(unknown=True)
        self.assertTrue(all(r['C'] is None for r in e['payload']['measurements']))
        self.assertIsNone(e['payload']['selected_artifact']['analysis_path'])
        self.assertEqual(e['payload']['selected_artifact']['numeric_status'],'blocked_unknown_encoding')

    def test_ABC_both_views_have_closed_target_identities_only_evidence_has_values(self):
        self.review_modules();self.evaluated();first,_=self.abc_response('image_first');evidence,_=self.abc_response('evidence')
        for request in (first,evidence):
            self.assertIn('targets',request['payload']['context'])
            goals=request['payload']['context']['targets'];self.assertEqual([t['target_id'] for t in goals],['t1','t2','t3'])
            self.assertEqual(goals[0]['subject_id'],'r1');self.assertEqual(goals[0]['metric'],'linear_Y');self.assertEqual(goals[0]['statistic'],'q50')
            self.assertEqual(goals[0]['direction'],'increase_toward_B');self.assertEqual(goals[1]['direction'],'decrease_toward_B')
            self.assertEqual(goals[2]['left_region_id'],'r1');self.assertEqual(goals[2]['right_region_id'],'r2')
            self.assertIn('"target_id":"t1"',request['payload']['prompt'])
            for bad in ('tolerance','rationale','allow_minor_incidental','posthoc_principles','RAW_POLICY_PROSE'):
                self.assertNotIn(bad,request['payload']['prompt'])
        self.assertNotIn('measurements',first['payload']['context']);self.assertIsNone(first['payload']['context']['targets'][0]['reference_measurement'])
        self.assertEqual(evidence['payload']['context']['targets'][0]['reference_measurement']['A'],self.row(self.evaluation)['A'])

    def test_C_localization_is_genuine_bounded_and_missing_is_explicit(self):
        self.review_modules();self.evaluated();request,_=self.abc_response('evidence');items=request['payload']['planned_attachments']
        self.assertEqual([(x['role'],x['purpose']) for x in items[:3]],[('A','content_image'),('B','style_reference'),('C','candidate_observation')])
        guides=[i for i in items if i['purpose']=='localization_only'];self.assertEqual([i['role'] for i in guides],['A','B','C'])
        c=guides[-1];pixels=np.asarray(Image.open(self.case/c['path']));np.testing.assert_array_equal(pixels[24,:4],np.array([[255,220,0]]*4))
        self.assertEqual(request['payload']['context']['localization_guides']['C'],'provided')
        self.assertEqual(items[2]['sha256'],self.derived['payload']['audit']['derivative_file_hash'])
        for region in c['regions']:self.assertEqual(file_sha256(self.case/region['support_path']),region['support_sha256'])

    def test_missing_C_support_has_no_fabricated_guide(self):
        self.review_modules();self.prepare();ev.freeze_version(self.case,self.version_spec())
        ev.evaluate(self.case,dict(evaluation_id='j1',version='q1',candidate_record_id=self.response['record_id'],derived_record_id=self.derived['record_id'],support_id=None,reevaluation=None))
        request=review.export_abc(self.case,'j1','evidence')
        self.assertNotIn('C',[i['role'] for i in request['payload']['planned_attachments'] if i['purpose']=='localization_only'])
        self.assertEqual(request['payload']['context']['localization_guides']['C'],'unavailable_no_nonempty_selected_support')

    def test_legacy_feedback_compilation_cannot_bypass_selected_artifact_upgrade(self):
        from hre.reference_style import s4_feedback as feedback,contracts as ct
        self.review_modules();self.evaluated();facts=review.freeze_facts(self.case,self.facts_spec())
        f=feedback.freeze_feedback(self.case,dict(feedback_id='fb1',evaluation_id='j1',facts_id='f1',current_target_version='v1',target_ids=['t1'],include_global_residuals=True))
        compiled=feedback.compile_feedback(self.case,self.compiled['record_id'],'fb1')
        # Explicit local legacy-producer fixture, not a mutation API in production.
        def legacy_record(group,key,change):
            state=co.status(self.case);entry=state['payload']['s2'][group][key];path=self.case/entry['path'];value=read_json(path)
            change(value['payload']);value['content_hash']=ct.content_hash({k:v for k,v in value.items() if k!='content_hash'})
            path.write_text(json.dumps(value));state['payload']['s2'][group][key]['hash']=value['content_hash'];co._save_state(self.case,state['sample_id'],state['payload']);return value
        old=legacy_record('evaluations','j1',lambda p:p.pop('candidate_measurement_basis'))
        facts=legacy_record('facts','f1',lambda p:p.update(evaluation_hash=old['content_hash']))
        f=legacy_record('feedback','fb1',lambda p:p.update(evaluation_hash=old['content_hash'],facts_hash=facts['content_hash']))
        compiled=legacy_record('compiled',compiled['record_id'],lambda p:p.update(feedback_hash=f['content_hash']))
        before=(self.case/'state.json').read_bytes()
        with self.assertRaises(ValueError):self.handoff.export_edit(self.case,compiled['record_id'])
        with self.assertRaises(ValueError):feedback.compile_feedback(self.case,self.compiled['record_id'],'fb1')
        self.assertEqual((self.case/'state.json').read_bytes(),before)
        with self.assertRaises(ValueError):review.export_abc(self.case,'j1','image_first')
        with self.assertRaises(ValueError):verify.select(self.case,dict(selection_id='sel1',version='q1',decision_ids=[],rule_version='first_accepted_generation_order_v1'))

    def test_target_projection_is_closed_visual_goal_meaning_and_no_archival_prose(self):
        from hre.reference_style.s4_targets import target_view
        self.review_modules();self.evaluated();target=copy.deepcopy(self.target)
        state=co.status(self.case);report=read_json(self.case/state['payload']['s2']['reports'][target['payload']['report_id']]['path'])
        sentinel='Slight facial geometry changes are fine once B style reached'
        target['payload']['revision']['rationale']=sentinel
        t=target['payload']['targets'][0];t.update(measurement_binding=None,judge_type='visual',dimension='brightness',direction='increase_toward_B')
        goals=target_view(target,report,False);self.assertIsNone(goals[0]['metric']);self.assertEqual(goals[0]['dimension'],'brightness');self.assertNotIn(sentinel,str(goals))
        for key in ('direction','semantic_class','priority'):
            bad=copy.deepcopy(target);bad['payload']['targets'][0][key]=sentinel
            with self.subTest(field=key),self.assertRaises(ValueError):target_view(bad,report,True)
        bad=copy.deepcopy(target);bad['payload']['targets'][0]['history']=sentinel
        with self.assertRaises(ValueError):target_view(bad,report,False)

    def test_selected_analysis_tampering_and_report_identity_are_visible(self):
        self.real_bytes();path=self.root/'representation_report.md';verify.export_report(self.case,path)
        self.assertIn('candidate_measurement_basis',path.read_text());self.assertIn('analysis_source_file_hash',path.read_text())
        selected=self.evaluation['payload']['selected_artifact'];(self.case/selected['analysis_path']).write_bytes(b'corrupt exact-artifact analysis')
        with self.assertRaises(ValueError):review.export_abc(self.case,'j1','evidence')


if __name__=='__main__':unittest.main()
