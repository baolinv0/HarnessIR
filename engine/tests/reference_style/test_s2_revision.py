"""S2 r2 regression fixtures: no model, all data explicitly synthetic."""
import copy
import importlib
import unittest
import test_s2 as fixture
from hre.reference_style import coordinator as co
from hre.storage import read_json


class S2RevisionTest(unittest.TestCase):
    setUp = fixture.S2Test.setUp
    manifest = fixture.S2Test.manifest
    import_array = fixture.S2Test.import_array
    import_json = fixture.S2Test.import_json
    supports = fixture.S2Test.supports
    report = fixture.S2Test.report
    receipt = fixture.S2Test.receipt
    diagnose = fixture.S2Test.diagnose
    target_spec = fixture.S2Test.target_spec

    def missing_spec(self, kind='segmentation', status='unavailable', index=None, offset=0):
        ids=[f'e{offset+1}',f'e{offset+2}']
        for eid,role in zip(ids,('A','B')):
            self.ev.import_evidence(self.case,self.manifest(eid,role,kind,status))
        return dict(snapshot_id='s1',evidence_ids=ids,global_comparability='unknown',
            regions=[dict(region_id='r1',semantic_class='face',
                A=dict(evidence_id=ids[0],entry_index=index),B=dict(evidence_id=ids[1],entry_index=index),
                match_status='uncertain',composition='unknown',illumination='unknown',
                parent_id=None,usage='independent')],relations=[],trusted_ocr=[])

    def revision(self, previous, reason='mapping_correction', rationale=None):
        return dict(predecessor_version=previous['payload']['version'],
                    predecessor_hash=previous['content_hash'],reason_code=reason,rationale=rationale)

    def test_assetless_mask_reference_indices_reject_before_availability_branch(self):
        # Removing pre-branch validation would turn these scalars/containers into prompt prose.
        for n,status in enumerate(('unavailable','uncertain')):
            spec=self.missing_spec(status=status,offset=2*n)
            for j,bad in enumerate(('POLICY_SENTINEL_KEEP_FACE_SHIFTS',{'permission':'yes'},True,0,1,-1,1.0,[])):
                with self.subTest(status=status,index=bad):
                    badspec=copy.deepcopy(spec);badspec['regions'][0]['A']['entry_index']=bad
                    badspec['snapshot_id']=f's{n*10+j+1}'
                    with self.assertRaises(ValueError):self.ev.freeze_supports(self.case,badspec)

    def test_assetless_bbox_reference_indices_are_nullable_bounded_integers(self):
        for n,(kind,status) in enumerate((('face','unavailable'),('ocr','uncertain'))):
            spec=self.missing_spec(kind,status,offset=2*n)
            for j,bad in enumerate(('POLICY_SENTINEL',{'index':0},False,-1,1_000_000,0.5)):
                with self.subTest(kind=kind,index=bad):
                    candidate=copy.deepcopy(spec);candidate['regions'][0]['A']['entry_index']=bad
                    candidate['snapshot_id']=f's{n*10+j+1}'
                    with self.assertRaises(ValueError):self.ev.freeze_supports(self.case,candidate)

    def test_unavailable_depth_cannot_masquerade_as_support(self):
        for n,status in enumerate(('unavailable','uncertain')):
            spec=self.missing_spec('depth',status,offset=2*n)
            spec['snapshot_id']=f's{n+1}'
            with self.subTest(status=status),self.assertRaises(ValueError):
                self.ev.freeze_supports(self.case,spec)

    def test_valid_missing_mask_and_bbox_references_still_prepare_visual_AB(self):
        for n,(kind,index) in enumerate((('segmentation',None),('face',None),('face',0),('ocr',0))):
            spec=self.missing_spec(kind,'uncertain',index,offset=2*n);spec['snapshot_id']=f's{n+1}'
            self.ev.freeze_supports(self.case,spec);report=self.me.measure_ab(self.case,spec['snapshot_id'])
            req,diag=self.diagnose(report,'POLICY_SENTINEL_ARCHIVE_ONLY')
            self.assertEqual(req['payload']['context']['regions']['r1']['eligibility'],'insufficient_evidence')
            self.assertEqual(req['payload']['context']['regions']['r1']['A']['entry_index'],index)
        visual=dict(version='v1',report_id=report['record_id'],diagnosis_record_id=diag['record_id'],targets=[
            dict(target_id='t1',measurement_id=None,visual_region_id='r1',visual_dimension='tone',
                 visual_direction='match_B',judge_type='visual',priority='critical')])
        self.st.freeze_targets(self.case,visual)
        self.assertNotIn('POLICY_SENTINEL',str(self.st.compile_targets(self.case,'v1')))

    def test_typed_transform_dimensions_not_python_numeric_equality(self):
        for n,dims in enumerate(([4.0,2],[4,2.0])):
            m=self.manifest(f'e{n+1}','A','face','unavailable');m['transform']['target_size']=dims
            with self.subTest(dims=dims),self.assertRaises(ValueError):self.ev.import_evidence(self.case,m)

    def test_final_diagnostic_projection_rejects_untyped_nested_fields(self):
        self.assertIsNotNone(importlib.util.find_spec('hre.reference_style.s2_public'),
                             'final diagnostic projection schema is missing')
        public=importlib.import_module('hre.reference_style.s2_public');report=self.report()
        good=public.diagnostic_view(report['payload'])
        self.assertEqual(good['regions']['r1']['A']['entry_index'],None)
        paths=[('regions','r1','A','entry_index'),('regions','r1','coverage','A','pixels'),
               ('regions','r1','support_paths','A'),('evidence',0,'observations','pixels'),
               ('measurements',0,'A'),('source_color_audit','A','numeric_status')]
        for path in paths:
            p=copy.deepcopy(report['payload']);node=p
            for key in path[:-1]:node=node[key]
            node[path[-1]]='POLICY_SENTINEL'
            with self.subTest(path=path),self.assertRaises(ValueError):public.diagnostic_view(p)
        for field in ('source','history','rationale'):
            p=copy.deepcopy(report['payload']);p['regions']['r1'][field]='POLICY_SENTINEL'
            with self.subTest(field=field),self.assertRaises(ValueError):public.diagnostic_view(p)

    def test_attachment_refs_and_revision_text_length_are_also_bounded(self):
        public=importlib.import_module('hre.reference_style.s2_public');report=self.report()
        for change in ({'path':'POLICY_SENTINEL'}, {'sha256':'POLICY_SENTINEL'}, {'metadata':'POLICY_SENTINEL'}):
            candidate=copy.deepcopy(report['payload']);candidate['assets'][0].update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):public.diagnostic_view(candidate)
        _,diag=self.diagnose(report);spec=self.target_spec(report,diag)
        first=self.st.freeze_targets(self.case,spec);spec['version']='v2'
        spec['revision']=self.revision(first,rationale='x'+' '*10001)
        with self.assertRaises(ValueError):self.st.freeze_targets(self.case,spec)

    def test_new_target_version_without_revision_cannot_drop_objectives(self):
        report=self.report();_,diag=self.diagnose(report);spec=self.target_spec(report,diag)
        self.st.freeze_targets(self.case,spec);spec['version']='v2';spec['targets']=spec['targets'][1:2]
        with self.assertRaises(ValueError):self.st.freeze_targets(self.case,spec)

    def test_reasoned_revision_records_exact_before_after_and_excludes_prose(self):
        report=self.report();req,diag=self.diagnose(report);spec=self.target_spec(report,diag)
        first=self.st.freeze_targets(self.case,spec)
        before=(self.case/'s2/targets/v1.json').read_bytes()
        spec['version']='v2';spec['revision']=self.revision(first,rationale='Small facial shifts are fine; keep those shifts.')
        spec['targets'][0]['priority']='secondary';spec['targets'].pop()
        new=copy.deepcopy(spec['targets'][0]);new.update(target_id='t4',measurement_id='m37');spec['targets'].append(new)
        second=self.st.freeze_targets(self.case,spec);rev=second['payload']['revision']
        self.assertEqual(rev['predecessor_hash'],first['content_hash'])
        self.assertEqual(rev['predecessor_record_id'],first['record_id'])
        self.assertEqual(rev['reason_code'],'mapping_correction')
        for category,wanted in [('retained',['t2']),('added',['t4']),('changed',['t1']),('removed',['t3'])]:
            self.assertEqual([x['target_id'] for x in rev['changes'][category]],wanted)
        change=rev['changes']['changed'][0]
        self.assertEqual(change['before']['priority'],'critical');self.assertEqual(change['after']['priority'],'secondary')
        self.assertEqual((self.case/'s2/targets/v1.json').read_bytes(),before)
        compiled=self.st.compile_targets(self.case,'v2')
        self.assertNotIn(spec['revision']['rationale'],str(compiled));self.assertNotIn('rationale',str(compiled))
        self.assertEqual(compiled['payload']['target_hash'],second['content_hash'])
        self.assertNotIn(spec['revision']['rationale'],req['payload']['prompt'])
        later=self.st.export_ab_diagnosis(self.case,report['record_id'])
        self.assertNotIn(spec['revision']['rationale'],str(later))

    def test_wrong_stale_skipped_and_malformed_revisions_reject_without_writes(self):
        report=self.report();_,diag=self.diagnose(report);spec=self.target_spec(report,diag)
        first=self.st.freeze_targets(self.case,spec)
        base=copy.deepcopy(spec);base.update(version='v2',revision=self.revision(first))
        baseline=(self.case/'state.json').read_bytes()
        for field,value in [('predecessor_version','v9'),('predecessor_hash','0'*64),
                            ('reason_code','accept_content_change'),('rationale',{'instruction':'keep shifts'})]:
            candidate=copy.deepcopy(base);candidate['revision'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):self.st.freeze_targets(self.case,candidate)
            self.assertEqual((self.case/'state.json').read_bytes(),baseline)
        candidate=copy.deepcopy(base);candidate['version']='v3'
        with self.assertRaises(ValueError):self.st.freeze_targets(self.case,candidate)
        self.st.freeze_targets(self.case,base)
        candidate=copy.deepcopy(base);candidate['version']='v3'
        with self.assertRaises(ValueError):self.st.freeze_targets(self.case,candidate)

    def test_changed_report_revision_requires_its_own_diagnosis_and_reason(self):
        report=self.report();_,diag=self.diagnose(report)
        first=self.st.freeze_targets(self.case,self.target_spec(report,diag))
        later=self.me.measure_ab(self.case,'s1');bad=self.target_spec(later,diag)
        bad.update(version='v2',revision=self.revision(first,'evidence_update'))
        with self.assertRaises(ValueError):self.st.freeze_targets(self.case,bad)
        _,newdiag=self.diagnose(later);spec=self.target_spec(later,newdiag)
        spec.update(version='v2',revision=self.revision(first))
        with self.assertRaises(ValueError):self.st.freeze_targets(self.case,spec)
        spec['revision']['reason_code']='evidence_update'
        second=self.st.freeze_targets(self.case,spec)
        self.assertEqual(second['payload']['report_hash'],later['content_hash'])
        self.assertEqual(second['payload']['diagnosis_hash'],newdiag['content_hash'])


if __name__=='__main__':unittest.main()
