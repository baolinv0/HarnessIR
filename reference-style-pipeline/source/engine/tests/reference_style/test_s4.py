"""S4 synthetic contracts, actual local numbers and no external model execution."""
import copy,importlib,json,unittest
import numpy as np
from PIL import Image
import test_s3 as fixture
from hre.models import file_sha256
from hre.storage import read_json
from hre.reference_style import coordinator as co


class S4Test(unittest.TestCase):
    manifest=fixture.S3Test.manifest
    import_array=fixture.S3Test.import_array
    import_json=fixture.S3Test.import_json
    supports=fixture.S3Test.supports
    report=fixture.S3Test.report
    receipt=fixture.S3Test.receipt
    diagnose=fixture.S3Test.diagnose
    target_spec=fixture.S3Test.target_spec
    draft=fixture.S3Test.draft
    submission=fixture.S3Test.submission
    candidate=fixture.S3Test.candidate
    color=fixture.S3Test.color

    def setUp(self):
        fixture.S3Test.setUp(self)
        for name in ('s4_budget','s4_evaluate'):
            self.assertIsNotNone(importlib.util.find_spec('hre.reference_style.'+name),'missing '+name)
        self.budget=importlib.import_module('hre.reference_style.s4_budget')
        self.evaluate=importlib.import_module('hre.reference_style.s4_evaluate')

    def prepare(self,unknown=False):
        self.compiled=self.draft();req=self.handoff.export_edit(self.case,self.compiled['record_id'])
        p=self.root/'perfect_synthetic_C.png'
        Image.open(self.config['inputs'][1]['path']).save(p)
        self.response,_,_=self.candidate(req,p)
        self.derived=self.candidates.derive_candidate(self.case,self.response['record_id'],self.color('unknown','srgb') if unknown else self.color())
        return self.response,self.derived

    def version_spec(self,version='q1'):
        return dict(version=version,target_version='v1',predecessor=None,reason_code='initial',
                    coordinate_rule_version='whole_semantic_C_v1',numeric_rule_version='ABC_signed_residual_v1')

    def support_spec(self,version='q1',sid='k1'):
        proof=self.root/'review.json';proof.write_text(json.dumps({'synthetic_fixture':True,'whole_regions':['r1','r2']}))
        regions=[]
        for rid,mask in [('r1',[[1]*4,[0]*4]),('r2',[[0]*4,[1]*4])]:
            path=self.root/(sid+rid+'.npy');np.save(path,np.array(mask,dtype=bool),allow_pickle=False)
            regions.append(dict(region_id=rid,mode='actual_mask',asset_path=str(path),asset_sha256=file_sha256(path),mapping=None,
                correspondence='confirmed',coverage='complete_comparable',occlusion='none_observed'))
        return dict(support_id=sid,version=version,candidate_record_id=self.response['record_id'],derived_record_id=self.derived['record_id'],
            candidate_hash=self.response['payload']['candidate_hash'],coordinate_image_hash=self.derived['payload']['audit']['derivative_file_hash'],
            coordinate_frame='oriented_C',size=[4,2],global_comparability='comparable',
            review=dict(path=str(proof),sha256=file_sha256(proof),source=dict(tool='synthetic',version='1',origin='synthetic_fixture')),
            regions=regions)

    def evaluated(self,unknown=False):
        self.prepare(unknown);self.profile=self.evaluate.freeze_version(self.case,self.version_spec())
        self.support=self.evaluate.freeze_supports(self.case,self.support_spec())
        self.evaluation=self.evaluate.evaluate(self.case,dict(evaluation_id='j1',version='q1',candidate_record_id=self.response['record_id'],
            derived_record_id=self.derived['record_id'],support_id='k1',reevaluation=None))
        return self.evaluation

    def test_residuals_are_actual_ABC_signed_values_and_absolute_improvement(self):
        ev=self.evaluated();rows=ev['payload']['measurements']
        for subject in ('r1','r2','l1'):
            row=next(m for m in rows if m['subject_id']==subject and m['metric']=='linear_Y' and m['statistic']=='q50')
            self.assertAlmostEqual(row['C_minus_B'],0);self.assertGreater(row['absolute_improvement'],0)
            self.assertAlmostEqual(row['absolute_improvement'],abs(row['B']-row['A']))
            self.assertEqual(row['numeric_achievement'],'uncalibrated')
        relation=next(m for m in rows if m['subject_id']=='l1')
        self.assertGreater(relation['C'],0);self.assertLess(relation['A'],0)
        self.assertEqual(ev['payload']['generation_target_hash'],self.target['content_hash'])
        self.assertEqual(ev['payload']['raw_candidate_hash'],self.response['payload']['candidate_hash'])

    def test_unknown_C_never_becomes_numeric_achievement(self):
        ev=self.evaluated(True)
        self.assertTrue(all(m['C'] is None for m in ev['payload']['measurements']))
        self.assertTrue(all(m['eligibility']!='numeric_eligible' for m in ev['payload']['measurements']))

    def test_same_size_does_not_authorize_A_mask_mapping(self):
        self.prepare();self.evaluate.freeze_version(self.case,self.version_spec());spec=self.support_spec()
        r=spec['regions'][0];r.update(mode='checked_A_mapping',asset_path=None,asset_sha256=None,
            mapping=dict(kind='identity',offset=[0,0],source_size=[4,2],target_size=[4,2],checked_against_C=False))
        with self.assertRaises(ValueError):self.evaluate.freeze_supports(self.case,spec)
        r['mapping']['checked_against_C']=True
        support=self.evaluate.freeze_supports(self.case,spec)
        self.assertEqual(support['payload']['regions']['r1']['mode'],'checked_A_mapping')

    def test_missing_mixed_occluded_or_unmatched_support_is_not_numeric(self):
        self.prepare();self.evaluate.freeze_version(self.case,self.version_spec());spec=self.support_spec()
        spec['regions'][0]['occlusion']='partial';spec['regions'][1].update(mode='unavailable',asset_path=None,asset_sha256=None,
            correspondence='unmatched',coverage='unknown',occlusion='unknown')
        support=self.evaluate.freeze_supports(self.case,spec)
        self.assertNotEqual(support['payload']['regions']['r1']['eligibility'],'numeric_eligible')
        self.assertEqual(support['payload']['regions']['r2']['coverage_pixels'],0)

    def test_support_rejects_wrong_raw_derived_hash_and_favorable_subset(self):
        self.prepare();self.evaluate.freeze_version(self.case,self.version_spec());spec=self.support_spec()
        for field,value in [('candidate_hash','0'*64),('coordinate_image_hash','0'*64),('coordinate_frame','oriented_A'),('size',[8,4]),('regions',spec['regions'][:1])]:
            bad=copy.deepcopy(spec);bad[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):self.evaluate.freeze_supports(self.case,bad)
        self.evaluate.freeze_supports(self.case,spec);spec['support_id']='k2'
        with self.assertRaises(ValueError):self.evaluate.freeze_supports(self.case,spec)

    def test_evaluation_and_profile_identity_cannot_be_overwritten(self):
        ev=self.evaluated();before=(self.case/'state.json').read_bytes()
        with self.assertRaises(ValueError):self.evaluate.freeze_version(self.case,self.version_spec())
        with self.assertRaises(ValueError):self.evaluate.evaluate(self.case,dict(evaluation_id='j2',version='q1',candidate_record_id=self.response['record_id'],
            derived_record_id=self.derived['record_id'],support_id='k1',reevaluation=None))
        self.assertEqual((self.case/'state.json').read_bytes(),before)

    def test_finite_budget_reserves_unknown_requests_and_allows_old_resolution(self):
        self.budget.configure_budget(self.case,dict(version='b1',edit_attempts=1,diagnostics=1,feedback_rounds=0,total=2))
        draft=self.draft();request=self.handoff.export_edit(self.case,draft['record_id'])
        co.mark_unknown(self.case,request['payload']['attempt_id'],'Unknown synthetic result')
        self.assertEqual(co.status(self.case)['payload']['budget']['used']['total'],2)
        response,receipt,out=self.candidate(request)
        self.assertEqual(co.import_response(self.case,receipt,out),response)
        with self.assertRaises(ValueError):self.handoff.export_edit(self.case,draft['record_id'])
        self.assertEqual(co.status(self.case)['payload']['budget']['used']['total'],2)

    def test_budget_cannot_expand_after_reservations_or_use_negative_limits(self):
        bad=dict(version='b1',edit_attempts=-1,diagnostics=1,feedback_rounds=1,total=3)
        with self.assertRaises(ValueError):self.budget.configure_budget(self.case,bad)
        self.draft()
        with self.assertRaises(ValueError):self.budget.configure_budget(self.case,{**bad,'edit_attempts':100})

    def review_modules(self):
        for name in ('s4_review','s4_verify'):
            self.assertIsNotNone(importlib.util.find_spec('hre.reference_style.'+name),'missing '+name)
        self.review=importlib.import_module('hre.reference_style.s4_review');self.verifier=importlib.import_module('hre.reference_style.s4_verify')

    def configured_evaluation(self,calibrated=True):
        self.review_modules();self.prepare();proof=self.root/'approved_fixture.txt';proof.write_text('EXPLICIT SYNTHETIC CALIBRATION FIXTURE, NOT USER APPROVAL')
        source=dict(origin='synthetic_fixture',path=str(proof),sha256=file_sha256(proof))
        policy=self.verifier.install_policy(self.case,dict(policy_id='p1',version='v1',allow_minor_incidental=True,source=source))
        rule=self.verifier.install_rule(self.case,dict(rule_id='rv1',version='v1',target_hash=self.target['content_hash'],policy_hash=policy['content_hash'],source=source,
            global_anchors=['tone','color','brightness'] if calibrated else [],visual_target_ids=['t1','t2','t3'] if calibrated else [],
            numeric_tolerances=[dict(target_id=t,max_abs_residual=0.00001) for t in ('t1','t2','t3')] if calibrated else [],
            critical_preservation=['identity','ocr','naturalness'],required_confidence='high',review_basis='independent_image_first'))
        ref=dict(policy_id='p1',policy_version='v1',policy_hash=policy['content_hash'],rule_id='rv1',rule_version='v1',rule_hash=rule['content_hash'])
        self.policy,self.rule,self.verification_ref=policy,rule,ref;self.profile=self.evaluate.freeze_version(self.case,self.version_spec())
        self.evaluate.freeze_supports(self.case,self.support_spec())
        self.evaluation=self.evaluate.evaluate(self.case,dict(evaluation_id='j1',version='q1',candidate_record_id=self.response['record_id'],derived_record_id=self.derived['record_id'],support_id='k1',reevaluation=None))
        return self.evaluation

    def abc_response(self,view):
        req=self.review.export_abc(self.case,'j1',view);manifest,prompt=self.submission(req)
        sub=self.handoff.record_submission(self.case,manifest,prompt);out=self.root/(view+'.txt');out.write_text('Synthetic factual review. RAW_POLICY_PROSE_NOT_EXECUTABLE')
        receipt=self.receipt(req,out);receipt.update(submission_record_id=sub['record_id'],submission_hash=sub['content_hash'])
        return req,co.import_response(self.case,receipt,out)

    def facts_spec(self):
        self.first_request,first=self.abc_response('image_first');self.evidence_request,evidence=self.abc_response('evidence')
        return dict(facts_id='f1',evaluation_id='j1',evidence_response_id=evidence['record_id'],image_first_response_id=first['record_id'],
            reviewer=dict(reviewer_id='fixture_reviewer',independence='independent'),
            overall_style={k:dict(status='achieved',confidence='high') for k in ('tone','color','brightness')},
            targets=[dict(target_id=t,status='achieved',confidence='high',residual_code='none_observed') for t in ('t1','t2','t3')],
            content_spatial={k:dict(severity='none_observed',confidence='high') for k in ('identity','layout','geometry','texture','ocr','naturalness')},spillover=[])

    def decision(self,facts,**kwargs):
        spec=dict(decision_id='z1',evaluation_id='j1',facts_id=facts['payload']['facts_id'],predecessor=None,adjudication_id=None,verification_ref=getattr(self,'verification_ref',None));spec.update(kwargs)
        return self.verifier.verify(self.case,spec)

    def test_ABC_actual_images_submission_and_image_first_no_policy_or_numbers(self):
        self.configured_evaluation();spec=self.facts_spec();facts=self.review.freeze_facts(self.case,spec)
        self.assertEqual([i['role'] for i in self.first_request['payload']['images']],['A','B','C'])
        self.assertNotIn('C_minus_B',self.first_request['payload']['prompt'])
        self.assertIn('C_minus_B',self.evidence_request['payload']['prompt'])
        for request in (self.first_request,self.evidence_request):
            self.assertNotIn('allow_minor_incidental',str(request));self.assertNotIn('RAW_POLICY_PROSE',str(request))
            self.assertNotIn('posthoc_principles',str(request))
        self.assertEqual(facts['payload']['evaluation_hash'],self.evaluation['content_hash'])

    def test_minor_incidental_deviation_can_be_conditionally_accepted_not_rewritten(self):
        self.configured_evaluation();spec=self.facts_spec();spec['content_spatial']['geometry']['severity']='minor_local_incidental'
        facts=self.review.freeze_facts(self.case,spec);before=(self.case/co.status(self.case)['payload']['s2']['facts']['f1']['path']).read_bytes()
        result=self.decision(facts)['payload'];self.assertEqual(result['status'],'accepted')
        self.assertEqual(result['acceptance_basis'],'incidental_deviation_tolerated')
        self.assertEqual(result['content_facts']['geometry']['severity'],'minor_local_incidental')
        self.assertEqual((self.case/co.status(self.case)['payload']['s2']['facts']['f1']['path']).read_bytes(),before)

    def test_selected_targets_pass_cannot_hide_weak_whole_color(self):
        self.configured_evaluation();spec=self.facts_spec();spec['overall_style']['color']['status']='unmet'
        spec['content_spatial']['geometry']['severity']='minor_local_incidental'
        result=self.decision(self.review.freeze_facts(self.case,spec))['payload']
        self.assertEqual(result['status'],'revise');self.assertIsNone(result['acceptance_basis'])

    def test_uncalibrated_rules_remain_user_review_not_achievement(self):
        self.configured_evaluation(False);facts=self.review.freeze_facts(self.case,self.facts_spec())
        self.assertEqual(self.decision(facts)['payload']['status'],'needs_user_review')

    def test_major_unknown_and_critical_preservation_not_automatically_minor(self):
        import shutil
        self.configured_evaluation();spec=self.facts_spec()
        for n,(dimension,severity,expected) in enumerate((('geometry','major','rejected'),('geometry','unknown','insufficient_evidence'),('ocr','minor_local_incidental','revise'))):
            old=self.case;case=self.root/f'verdict{n}';shutil.copytree(old,case);self.case=case
            try:
                s=copy.deepcopy(spec);s['content_spatial'][dimension]['severity']=severity
                self.assertEqual(self.decision(self.review.freeze_facts(case,s))['payload']['status'],expected)
            finally:self.case=old

    def test_mixed_numeric_visual_conflict_retained_and_not_averaged(self):
        self.configured_evaluation();spec=self.facts_spec();spec['targets'][0]['status']='unmet'
        facts=self.review.freeze_facts(self.case,spec);result=self.decision(facts)['payload']
        self.assertEqual(result['status'],'needs_user_review');self.assertEqual(result['conflicts'][0]['target_id'],'t1')
        self.assertEqual(result['target_statuses'][0]['numeric'],'achieved')
        self.assertEqual(result['target_statuses'][0]['visual'],'unmet')

    def test_factual_projection_rejects_prose_missing_global_or_candidate_mismatch(self):
        self.configured_evaluation();spec=self.facts_spec()
        bad=copy.deepcopy(spec);bad['content_spatial']['geometry']['severity']='Minor changes are allowed'
        with self.assertRaises(ValueError):self.review.freeze_facts(self.case,bad)
        bad=copy.deepcopy(spec);del bad['overall_style']['brightness']
        with self.assertRaises(ValueError):self.review.freeze_facts(self.case,bad)
        bad=copy.deepcopy(spec);bad['evidence_response_id']=self.response['record_id']
        with self.assertRaises(ValueError):self.review.freeze_facts(self.case,bad)
        self.review.freeze_facts(self.case,spec);spec['facts_id']='f2'
        with self.assertRaises(ValueError):self.review.freeze_facts(self.case,spec)

    def feedback_module(self):
        self.assertIsNotNone(importlib.util.find_spec('hre.reference_style.s4_feedback'),'missing factual feedback interface')
        return importlib.import_module('hre.reference_style.s4_feedback')

    def test_feedback_restores_original_A_and_never_retains_tolerated_drift(self):
        feedback=self.feedback_module();self.configured_evaluation();spec=self.facts_spec();spec['content_spatial']['geometry']['severity']='minor_local_incidental'
        facts=self.review.freeze_facts(self.case,spec);self.decision(facts)
        fb=feedback.freeze_feedback(self.case,dict(feedback_id='fb1',evaluation_id='j1',facts_id='f1',current_target_version='v1',target_ids=['t1','t2','t3'],include_global_residuals=True))
        compiled=feedback.compile_feedback(self.case,self.compiled['record_id'],'fb1')
        self.assertEqual(compiled['payload']['target_hash'],self.target['content_hash']);self.assertEqual(compiled['payload']['feedback_hash'],fb['content_hash'])
        self.assertIn('restore_original_A_consistency',compiled['payload']['prompt']);self.assertNotIn('incidental_deviation_tolerated',str(compiled))
        request=self.handoff.export_edit(self.case,compiled['record_id']);self.assertEqual([i['role'] for i in request['payload']['images']],['A','B'])
        self.assertEqual(request['payload']['images'][0]['source_file_hash'],self.audit[0]['source_file_hash'])
        self.assertNotIn('allow_minor_incidental',str(request));self.assertNotIn('accepted',request['payload']['prompt'])

    def test_reevaluation_keeps_generation_target_and_requires_explicit_lineage(self):
        ev=self.evaluated();state=co.status(self.case);report=read_json(self.case/state['payload']['s2']['reports'][self.target['payload']['report_id']]['path'])
        targets=self.target_spec(report,{'record_id':self.target['payload']['diagnosis_record_id']});targets.update(version='v2',revision=dict(predecessor_version='v1',predecessor_hash=self.target['content_hash'],reason_code='mapping_correction',rationale='Synthetic revision audit'))
        revised=self.st.freeze_targets(self.case,targets);profile=self.version_spec('q2');profile.update(target_version='v2',predecessor=dict(version='q1',hash=self.profile['content_hash']),reason_code='target_revision')
        self.evaluate.freeze_version(self.case,profile);self.evaluate.freeze_supports(self.case,self.support_spec('q2','k2'))
        spec=dict(evaluation_id='j2',version='q2',candidate_record_id=self.response['record_id'],derived_record_id=self.derived['record_id'],support_id='k2',reevaluation=None)
        with self.assertRaises(ValueError):self.evaluate.evaluate(self.case,spec)
        spec['reevaluation']=dict(previous_evaluation_id='j1',previous_hash=ev['content_hash'],reason_code='target_revision')
        later=self.evaluate.evaluate(self.case,spec)['payload'];self.assertEqual(later['generation_target_hash'],self.target['content_hash'])
        self.assertEqual(later['evaluation_target_hash'],revised['content_hash'])

    def test_feedback_budget_zero_blocks_new_round_but_not_prior_receipts(self):
        feedback=self.feedback_module();self.budget.configure_budget(self.case,dict(version='b1',edit_attempts=2,diagnostics=4,feedback_rounds=0,total=10))
        self.configured_evaluation();facts=self.review.freeze_facts(self.case,self.facts_spec())
        with self.assertRaises(ValueError):feedback.freeze_feedback(self.case,dict(feedback_id='fb1',evaluation_id='j1',facts_id='f1',current_target_version='v1',target_ids=['t1'],include_global_residuals=True))

    def test_selection_preserves_conditional_facts_and_never_certifies_pixel_label(self):
        self.configured_evaluation();spec=self.facts_spec();spec['content_spatial']['geometry']['severity']='minor_local_incidental'
        facts=self.review.freeze_facts(self.case,spec);decision=self.decision(facts)
        self.assertTrue(hasattr(self.verifier,'select'),'selection is missing')
        result=self.verifier.select(self.case,dict(selection_id='sel1',version='q1',decision_ids=['z1'],rule_version='first_accepted_generation_order_v1'))['payload']
        self.assertEqual(result['status'],'selected');self.assertEqual(result['label_manifest']['raw_candidate_hash'],self.response['payload']['candidate_hash'])
        self.assertEqual(result['label_manifest']['derived_file_hash'],self.derived['payload']['audit']['derivative_file_hash'])
        self.assertEqual(result['label_manifest']['acceptance_basis'],'incidental_deviation_tolerated')
        self.assertNotEqual(result['label_manifest']['pixel_supervision_screening_status'],'certified')

    def test_pending_review_selection_is_pending_not_fallback_A(self):
        self.configured_evaluation(False);facts=self.review.freeze_facts(self.case,self.facts_spec());self.decision(facts)
        self.assertTrue(hasattr(self.verifier,'select'),'selection is missing')
        result=self.verifier.select(self.case,dict(selection_id='sel1',version='q1',decision_ids=['z1'],rule_version='first_accepted_generation_order_v1'))['payload']
        self.assertEqual(result['status'],'pending_review');self.assertIsNone(result['label_manifest'])

    def test_single_markdown_report_contains_actual_hashes_and_not_run_limits(self):
        self.configured_evaluation();self.review.freeze_facts(self.case,self.facts_spec())
        self.assertTrue(hasattr(self.verifier,'export_report'),'Markdown run report missing')
        path=self.root/'RUN_REPORT.md';self.verifier.export_report(self.case,path);text=path.read_text()
        self.assertIn(self.response['payload']['candidate_hash'],text);self.assertIn('NOT RUN',text)
        self.assertIn('C_minus_B',text);self.assertIn('budget',text.lower());self.assertIn('Qwen',text)

    def test_explicit_adjudication_preserves_old_conclusion_and_conflict(self):
        self.configured_evaluation();spec=self.facts_spec();spec['targets'][0]['status']='unmet'
        facts=self.review.freeze_facts(self.case,spec);first=self.decision(facts)
        source=self.rule['payload']['source'];adjudication=self.verifier.install_adjudication(self.case,dict(adjudication_id='adj1',evaluation_id='j1',evaluation_hash=self.evaluation['content_hash'],
            facts_hash=facts['content_hash'],rule_hash=self.rule['content_hash'],resolutions=[dict(target_id='t1',resolution='confirm_unmet')],source=source))
        with self.assertRaises(ValueError):self.decision(facts,decision_id='z2',adjudication_id='adj1')
        second=self.decision(facts,decision_id='z2',predecessor=dict(decision_id='z1',hash=first['content_hash']),adjudication_id='adj1')
        self.assertEqual(second['payload']['status'],'revise');self.assertEqual(second['payload']['conflicts'][0]['resolution'],'confirm_unmet')
        self.assertEqual(read_json(self.case/'private_verification/s4/decisions/z1.json'),first)

    def test_unevaluated_generated_candidate_stays_pending_selection(self):
        self.configured_evaluation();facts=self.review.freeze_facts(self.case,self.facts_spec());self.decision(facts)
        req=self.handoff.export_edit(self.case,self.compiled['record_id']);self.candidate(req)
        result=self.verifier.select(self.case,dict(selection_id='sel1',version='q1',decision_ids=['z1'],rule_version='first_accepted_generation_order_v1'))['payload']
        self.assertEqual(result['status'],'pending_review');self.assertIsNone(result['label_manifest'])
        self.assertTrue(result['unevaluated_candidate_ids'])

    def test_selection_cannot_mix_rule_versions_or_superseded_decisions(self):
        self.configured_evaluation();facts=self.review.freeze_facts(self.case,self.facts_spec());first=self.decision(facts)
        self.decision(facts,decision_id='z2',predecessor=dict(decision_id='z1',hash=first['content_hash']))
        with self.assertRaises(ValueError):self.verifier.select(self.case,dict(selection_id='sel1',version='q1',decision_ids=['z1'],rule_version='first_accepted_generation_order_v1'))
        profile=self.version_spec('q2');profile.update(predecessor=dict(version='q1',hash=self.profile['content_hash']),reason_code='diagnosis_correction')
        self.evaluate.freeze_version(self.case,profile)
        with self.assertRaises(ValueError):self.verifier.select(self.case,dict(selection_id='sel1',version='q2',decision_ids=['z2'],rule_version='first_accepted_generation_order_v1'))

    def test_cli_explicit_budget_and_single_report_commands(self):
        import io
        from contextlib import redirect_stdout
        from hre.reference_style.cli import main
        path=self.root/'budget.json';path.write_text(json.dumps(dict(version='b1',edit_attempts=2,diagnostics=3,feedback_rounds=1,total=6)))
        buffer=io.StringIO()
        with redirect_stdout(buffer):rc=main(['budget-configure','--root',str(self.case),'--spec',str(path)])
        self.assertEqual(rc,0);self.assertEqual(json.loads(buffer.getvalue())['payload']['budget']['used']['total'],0)
        report=self.root/'run.md';buffer=io.StringIO()
        with redirect_stdout(buffer):rc=main(['run-report','--root',str(self.case),'--out',str(report)])
        self.assertEqual(rc,0);self.assertIn('NOT RUN',report.read_text())

    def test_real_purpose_needs_explicit_budget_not_fixture_default(self):
        config=copy.deepcopy(self.config);config['purpose']='reference_style';real=self.root/'real_contract_fixture';co.create_sample(config,real)
        context=dict(target_version='v1',targets=[],evidence=[],feedback=[])
        with self.assertRaises(ValueError):co.export_request(real,'ab_diagnosis',context)
        self.assertIsNone(co.status(real)['payload'].get('budget'))
        self.budget.configure_budget(real,dict(version='b1',edit_attempts=0,diagnostics=1,feedback_rounds=0,total=1))
        co.export_request(real,'ab_diagnosis',context)
        self.assertEqual(co.status(real)['payload']['budget']['basis'],'explicit_local_export_limits')

    def test_policy_only_revision_reverifies_same_immutable_factual_evaluation(self):
        self.configured_evaluation();spec=self.facts_spec();spec['content_spatial']['geometry']['severity']='minor_local_incidental'
        facts=self.review.freeze_facts(self.case,spec);first=self.decision(facts)
        before=(self.case/co.status(self.case)['payload']['s2']['evaluations']['j1']['path']).read_bytes()
        policy=self.verifier.install_policy(self.case,dict(policy_id='p2',version='v2',allow_minor_incidental=False,source=self.policy['payload']['source']))
        rule_spec={k:v for k,v in self.rule['payload'].items() if k not in ('assets','approved_basis','semantics')};rule_spec.update(rule_id='rv2',version='v2',policy_hash=policy['content_hash'])
        rule=self.verifier.install_rule(self.case,rule_spec)
        reference=dict(policy_id='p2',policy_version='v2',policy_hash=policy['content_hash'],rule_id='rv2',rule_version='v2',rule_hash=rule['content_hash'])
        second=self.verifier.verify(self.case,dict(decision_id='z2',evaluation_id='j1',facts_id='f1',predecessor=dict(decision_id='z1',hash=first['content_hash']),adjudication_id=None,verification_ref=reference))
        self.assertEqual(second['payload']['status'],'needs_user_review')
        self.assertEqual((self.case/co.status(self.case)['payload']['s2']['evaluations']['j1']['path']).read_bytes(),before)
        self.assertEqual(len(co.status(self.case)['payload']['s2']['evaluation_versions']),1)

    def test_private_policy_refs_are_not_fields_of_factual_version(self):
        self.prepare();spec=self.version_spec();spec['verification_ref']=dict(policy_id='p1',policy_version='v1',policy_hash='0'*64,rule_id='rv1',rule_version='v1',rule_hash='1'*64)
        with self.assertRaises(ValueError):self.evaluate.freeze_version(self.case,spec)

    def test_explicit_terminal_failure_never_refunds_budget_or_consumes_new_attempt(self):
        self.assertTrue(hasattr(self.budget,'record_failure'),'terminal failure receipt interface missing')
        self.budget.configure_budget(self.case,dict(version='b1',edit_attempts=0,diagnostics=2,feedback_rounds=0,total=2))
        context=dict(target_version='v1',targets=[],evidence=[],feedback=[]);request=co.export_request(self.case,'ab_diagnosis',context)
        error=self.root/'terminal_error.txt';error.write_text('Explicit synthetic terminal provider error, not timeout/unknown')
        spec=dict(attempt_id=request['payload']['attempt_id'],request_hash=request['content_hash'],reason_code='terminal_provider_error',
            artifact_path=str(error),artifact_sha256=file_sha256(error),origin='synthetic_fixture',tool_call_ref='synthetic_error_call')
        bad={**spec,'reason_code':'unknown_timeout'}
        with self.assertRaises(ValueError):self.budget.record_failure(self.case,bad)
        first=self.budget.record_failure(self.case,spec)
        self.assertEqual(co.status(self.case)['payload']['budget']['used']['total'],1)
        new=co.export_request(self.case,'ab_diagnosis',context);state=(self.case/'state.json').read_bytes()
        self.assertEqual(self.budget.record_failure(self.case,spec),first);self.assertEqual((self.case/'state.json').read_bytes(),state)
        self.assertEqual(co.status(self.case)['payload']['active_attempt']['attempt_id'],new['payload']['attempt_id'])
        self.assertEqual(co.status(self.case)['payload']['budget']['used']['total'],2)

    def test_checked_translation_records_lost_coverage_without_numeric_pass(self):
        self.prepare();self.evaluate.freeze_version(self.case,self.version_spec());spec=self.support_spec()
        for item in spec['regions']:
            item.update(mode='checked_A_mapping',asset_path=None,asset_sha256=None,
                mapping=dict(kind='integer_translation',offset=[1,0],source_size=[4,2],target_size=[4,2],checked_against_C=True))
        support=self.evaluate.freeze_supports(self.case,spec)['payload']
        for region in support['regions'].values():
            self.assertEqual(region['mapped_outside_pixels'],1)
            self.assertEqual(region['coverage_pixels'],3)
            self.assertEqual(region['coverage_fraction'],3/8)
            self.assertNotEqual(region['eligibility'],'numeric_eligible')

    def test_policy_installation_cannot_change_ABC_prompt(self):
        import shutil
        self.configured_evaluation();original=self.case;clone=self.root/'isolated_policy_change';shutil.copytree(original,clone)
        rule=self.verifier.install_policy(clone,dict(policy_id='p2',version='v2',allow_minor_incidental=False,source=self.policy['payload']['source']))
        a=self.review.export_abc(original,'j1','image_first');b=self.review.export_abc(clone,'j1','image_first')
        self.assertEqual(a['payload']['prompt'],b['payload']['prompt'])
        self.assertEqual(a['payload']['context'],b['payload']['context'])
        self.assertEqual([i['sha256'] for i in a['payload']['planned_attachments']],[i['sha256'] for i in b['payload']['planned_attachments']])
        self.assertNotIn(rule['content_hash'],str(b))
        # This request is intentionally left pending; independent fixture teardown only.

    def test_run_report_has_support_evaluation_and_submission_detail_not_just_counts(self):
        self.configured_evaluation();facts=self.review.freeze_facts(self.case,self.facts_spec());self.decision(facts)
        report=self.root/'complete.md';self.verifier.export_report(self.case,report);text=report.read_text()
        for term in ('SYNTHETIC PROTOCOL FIXTURE','candidate_supports: 1','evaluations: 1','submitted_prompt_hash','raw_candidate_hash','baseline_absolute_residual','rule_hash','derivative_file_hash','derivative_pixel_hash'):
            self.assertIn(term,text)
        self.assertIn(self.evaluation['content_hash'],text)

    def test_private_policy_change_cannot_change_feedback_compiled_prompt(self):
        import shutil
        from hre.reference_style import s4_feedback as fb
        self.configured_evaluation();spec=self.facts_spec();spec['content_spatial']['geometry']['severity']='minor_local_incidental'
        self.review.freeze_facts(self.case,spec);clone=self.root/'private_feedback_change';shutil.copytree(self.case,clone)
        self.verifier.install_policy(clone,dict(policy_id='p2',version='v2',allow_minor_incidental=False,source=self.policy['payload']['source']))
        prompts=[]
        for root in (self.case,clone):
            fb.freeze_feedback(root,dict(feedback_id='fb1',evaluation_id='j1',facts_id='f1',current_target_version='v1',target_ids=['t1','t2','t3'],include_global_residuals=True))
            prompts.append(fb.compile_feedback(root,self.compiled['record_id'],'fb1')['payload']['prompt'])
        self.assertEqual(prompts[0],prompts[1]);self.assertIn('restore_original_A_consistency',prompts[0])
        self.assertNotIn('incidental_deviation_tolerated',prompts[0]);self.assertNotIn('allow_minor_incidental',prompts[0])

    def test_same_factual_version_different_private_rules_cannot_be_selected_together(self):
        self.configured_evaluation();spec=self.facts_spec();facts=self.review.freeze_facts(self.case,spec);self.decision(facts)
        req=self.handoff.export_edit(self.case,self.compiled['record_id']);self.response,_,_=self.candidate(req,self.root/'perfect_synthetic_C.png')
        self.derived=self.candidates.derive_candidate(self.case,self.response['record_id'],self.color())
        self.evaluate.freeze_supports(self.case,self.support_spec(sid='k2'))
        self.evaluate.evaluate(self.case,dict(evaluation_id='j2',version='q1',candidate_record_id=self.response['record_id'],derived_record_id=self.derived['record_id'],support_id='k2',reevaluation=None))
        ids=[]
        for view in ('image_first','evidence'):
            req=self.review.export_abc(self.case,'j2',view);manifest,prompt=self.submission(req);sub=self.handoff.record_submission(self.case,manifest,prompt)
            output=self.root/('second_'+view+'.txt');output.write_text('Synthetic second candidate ABC observation')
            receipt=self.receipt(req,output);receipt.update(submission_record_id=sub['record_id'],submission_hash=sub['content_hash'])
            ids.append(co.import_response(self.case,receipt,output)['record_id'])
        spec.update(facts_id='f2',evaluation_id='j2',image_first_response_id=ids[0],evidence_response_id=ids[1]);self.review.freeze_facts(self.case,spec)
        policy=self.verifier.install_policy(self.case,dict(policy_id='p2',version='v2',allow_minor_incidental=False,source=self.policy['payload']['source']))
        rule_spec={k:v for k,v in self.rule['payload'].items() if k not in ('assets','approved_basis','semantics')};rule_spec.update(rule_id='rv2',version='v2',policy_hash=policy['content_hash'])
        rule=self.verifier.install_rule(self.case,rule_spec)
        ref=dict(policy_id='p2',policy_version='v2',policy_hash=policy['content_hash'],rule_id='rv2',rule_version='v2',rule_hash=rule['content_hash'])
        self.verifier.verify(self.case,dict(decision_id='z2',evaluation_id='j2',facts_id='f2',predecessor=None,adjudication_id=None,verification_ref=ref))
        with self.assertRaises(ValueError):self.verifier.select(self.case,dict(selection_id='sel1',version='q1',decision_ids=['z1','z2'],rule_version='first_accepted_generation_order_v1'))


if __name__=='__main__':unittest.main()
