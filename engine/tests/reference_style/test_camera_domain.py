"""Synthetic domain/lineage contracts only; no actual scene or model execution."""
import copy,json,unittest
import numpy as np
import test_coordinator as fixture
from hre.models import file_sha256
from hre.storage import read_json
from hre.reference_style import coordinator as co,s4_budget,s4_verify


class CameraDomainTest(unittest.TestCase):
    setUp=fixture.CoordinatorTest.setUp

    def camera(self):
        config=copy.deepcopy(self.config)
        for item in config['inputs']:item.update(source_kind='camera_rgb',base_model_version=None)
        return config

    def test_camera_kind_null_base_is_truthful_audit_state_and_report(self):
        config=self.camera();state=co.create_sample(config,self.out);audit=read_json(self.out/'input_audit.json')
        self.assertEqual(state['payload']['input_domain'],'camera_rgb')
        self.assertEqual(audit['payload']['input_domain'],'camera_rgb')
        for item in audit['payload']['images']:
            self.assertEqual(item['source_kind'],'camera_rgb');self.assertIsNone(item['base_model_version'])
            self.assertEqual(item['base_provenance'],'not_applicable_camera_rgb')
        report=self.root/'report.md';s4_verify.export_report(self.out,report);text=report.read_text(encoding='utf-8')
        self.assertIn('camera_rgb_workflow_only',text);self.assertNotIn('A is caller-declared Base output',text)
        self.assertEqual(state['payload']['attempts'],[])

    def test_legacy_missing_kind_stays_base_and_explicit_base_matches_pixels(self):
        a=co.create_sample(self.config,self.out);explicit=copy.deepcopy(self.config)
        explicit['inputs'][0]['source_kind']='base_model_output';explicit['inputs'][1]['source_kind']='camera_rgb'
        second=self.root/'explicit';b=co.create_sample(explicit,second)
        camera=self.root/'camera';co.create_sample(self.camera(),camera)
        self.assertEqual(a['payload']['input_domain'],b['payload']['input_domain']);self.assertEqual(a['payload']['input_domain'],'base_model_output')
        left=read_json(self.out/'input_audit.json')['payload']['images'];right=read_json(second/'input_audit.json')['payload']['images']
        for x,y in zip(left,right):
            self.assertEqual(x['source_file_hash'],y['source_file_hash']);self.assertEqual(x['derivative_pixel_hash'],y['derivative_pixel_hash'])
            with np.load(self.out/x['analysis_path'],allow_pickle=False) as A,np.load(second/y['analysis_path'],allow_pickle=False) as B:
                for key in A.files:np.testing.assert_array_equal(A[key],B[key])
            with np.load(self.out/x['analysis_path'],allow_pickle=False) as A,np.load(camera/y['analysis_path'],allow_pickle=False) as C:
                for key in A.files:np.testing.assert_array_equal(A[key],C[key])

    def test_camera_cannot_carry_fake_base_version(self):
        config=self.camera();config['inputs'][0]['base_model_version']='pretend-Base'
        with self.assertRaises(ValueError):co.create_sample(config,self.out)
        self.assertFalse(self.out.exists())

    def test_base_missing_or_invalid_version_still_rejects(self):
        for v in (None,'',False,42):
            config=copy.deepcopy(self.config);config['inputs'][0].update(source_kind='base_model_output',base_model_version=v)
            with self.subTest(version=v),self.assertRaises(ValueError):co.create_sample(config,self.out)

    def test_source_kind_rejects_unknown_and_nonstrings(self):
        for kind in ('RAW','unknown','phone',None,False,[],{}):
            config=self.camera();config['inputs'][0]['source_kind']=kind
            with self.subTest(kind=kind),self.assertRaises(ValueError):co.create_sample(config,self.out)

    def test_B_cannot_be_base_or_direct_P3(self):
        for change in ({'source_kind':'base_model_output'},{'encoding':'display_p3'},{'base_model_version':'fake'}):
            config=self.camera();config['inputs'][1].update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):co.create_sample(config,self.out)

    def test_unknown_A_remains_display_only(self):
        config=self.camera();config['inputs'][0].update(encoding='unknown',display_assumption='srgb')
        co.create_sample(config,self.out);a=read_json(self.out/'input_audit.json')['payload']['images'][0]
        self.assertEqual(a['numeric_status'],'blocked_unknown_encoding');self.assertIsNone(a['analysis_path'])

    def test_real_camera_gate_has_zero_requests_and_requires_explicit_budget(self):
        config=self.camera();config['purpose']='reference_style';co.create_sample(config,self.out)
        with self.assertRaises(ValueError):co.export_request(self.out,'ab_diagnosis',self.context)
        s4_budget.configure_budget(self.out,dict(version='b1',edit_attempts=0,diagnostics=0,feedback_rounds=0,total=0))
        state=co.status(self.out);self.assertEqual(state['payload']['budget']['used']['total'],0);self.assertEqual(state['payload']['attempts'],[])
        with self.assertRaises(ValueError):co.export_request(self.out,'ab_diagnosis',self.context)

    def test_lineage_snapshot_binds_archival_bytes_not_prompt_instructions(self):
        manifest=self.root/'original_to_canonical.json';sentinel='Tiny geometry changes are fine after B style achieved'
        manifest.write_text(json.dumps({'observational_note':sentinel,'original_hash':'a'*64,'canonical_hash':file_sha256(self.config['inputs'][0]['path'])}), encoding='utf-8', newline='')
        config=self.camera();config['input_lineage']=dict(path=str(manifest),sha256=file_sha256(manifest))
        state=co.create_sample(config,self.out);ref=state['payload']['input_lineage']
        self.assertEqual((self.out/ref['path']).read_bytes(),manifest.read_bytes());self.assertEqual(ref['sha256'],file_sha256(manifest))
        audit=read_json(self.out/'input_audit.json');self.assertEqual(audit['payload']['images'][0]['source_file_hash'],file_sha256(config['inputs'][0]['path']))
        self.assertEqual(audit['payload']['input_lineage'],ref)
        request=co.export_request(self.out,'ab_diagnosis',self.context);self.assertNotIn(sentinel,request['payload']['prompt'])
        report=self.root/'report.md';s4_verify.export_report(self.out,report);text=report.read_text(encoding='utf-8')
        self.assertIn(ref['sha256'],text);self.assertIn('supplied input',text);self.assertIn('upstream',text)
        (self.out/ref['path']).write_bytes(b'corrupt')
        with self.assertRaises(ValueError):co.status(self.out)

    def test_bad_lineage_rejects_before_creating_sample(self):
        path=self.root/'lineage.json';path.write_text('{}', encoding='utf-8', newline='')
        for ref in (dict(path=str(path),sha256='0'*64),dict(path=str(path),sha256=file_sha256(path),permission='allowed')):
            config=self.camera();config['input_lineage']=ref
            with self.assertRaises(ValueError):co.create_sample(config,self.out)
            self.assertFalse(self.out.exists())
        path.write_text('not JSON', encoding='utf-8', newline='');config=self.camera();config['input_lineage']=dict(path=str(path),sha256=file_sha256(path))
        with self.assertRaises(ValueError):co.create_sample(config,self.out)
        self.assertFalse(self.out.exists())

    def test_camera_cannot_silently_become_base_state(self):
        state=co.create_sample(self.camera(),self.out);state['payload']['input_domain']='base_model_output'
        co._save_state(self.out,state['sample_id'],state['payload'])
        with self.assertRaises(ValueError):co.status(self.out)

    def test_selected_label_keeps_camera_domain_and_C_is_not_a_base_audit(self):
        import test_s4 as stages
        test=stages.S4Test();test.setUp()
        try:
            config=copy.deepcopy(test.config)
            for i in config['inputs']:i.update(source_kind='camera_rgb',base_model_version=None)
            test.case=test.root/'camera_case';co.create_sample(config,test.case);test.config=config
            test.audit=read_json(test.case/'input_audit.json')['payload']['images']
            test.configured_evaluation();facts=test.review.freeze_facts(test.case,test.facts_spec());test.decision(facts)
            label=test.verifier.select(test.case,dict(selection_id='sel1',version='q1',decision_ids=['z1'],rule_version='first_accepted_generation_order_v1'))['payload']['label_manifest']
            self.assertEqual(label['input_domain'],'camera_rgb');self.assertEqual(label['validation_scope'],'camera_rgb_workflow_only')
            for key in ('source_kind','base_model_version','base_provenance'):self.assertNotIn(key,test.derived['payload']['audit'])
        finally:test.doCleanups()


if __name__=='__main__':unittest.main()
