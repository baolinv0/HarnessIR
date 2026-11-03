"""S3 genuine local protocol fixtures only. No remote calls or real visual judgment."""
import copy
import importlib
from pathlib import Path
import unittest
import numpy as np
from PIL import Image, ImageCms
import test_s2 as fixture
from hre.models import file_sha256
from hre.reference_style import coordinator as co
from hre.storage import read_json


class S3Test(unittest.TestCase):
    manifest=fixture.S2Test.manifest
    import_array=fixture.S2Test.import_array
    import_json=fixture.S2Test.import_json
    supports=fixture.S2Test.supports
    report=fixture.S2Test.report
    receipt=fixture.S2Test.receipt
    diagnose=fixture.S2Test.diagnose
    target_spec=fixture.S2Test.target_spec

    def setUp(self):
        fixture.S2Test.setUp(self)
        for name in ('s3_handoff','s3_candidate'):
            self.assertIsNotNone(importlib.util.find_spec('hre.reference_style.'+name),'S3 interface missing: '+name)
        self.handoff=importlib.import_module('hre.reference_style.s3_handoff')
        self.candidates=importlib.import_module('hre.reference_style.s3_candidate')

    def draft(self):
        report=self.report();_,diag=self.diagnose(report,'SYNTHETIC_NARRATIVE_NOT_AN_INSTRUCTION')
        self.target=self.st.freeze_targets(self.case,self.target_spec(report,diag))
        return self.st.compile_targets(self.case,'v1')

    def submission(self,request,**updates):
        p=request['payload'];prompt=self.root/'submitted.txt';prompt.write_text(p['prompt'], encoding='utf-8', newline='')
        attachments=[{k:a[k] for k in ('attachment_id','ordinal','role','purpose','sha256')}|
                     {'path':str(self.case/a['path'])} for a in p['planned_attachments']]
        spec=dict(attempt_id=p['attempt_id'],request_hash=request['content_hash'],prompt_sha256=file_sha256(prompt),
                  attachments=attachments,provenance=dict(origin='synthetic_fixture',provider='chatgpt',
                  conversation_ref='synthetic',tool_call_ref='synthetic'))
        spec.update(updates)
        return spec,prompt

    def candidate(self,request,output=None):
        if output is None:
            output=self.root/'C.png';Image.new('RGB',(5,3),(40,70,90)).save(output)
        spec,prompt=self.submission(request);submitted=self.handoff.record_submission(self.case,spec,prompt)
        receipt=self.receipt(request,output);receipt['response_type']='image'
        receipt.update(submission_record_id=submitted['record_id'],submission_hash=submitted['content_hash'])
        return co.import_response(self.case,receipt,output),receipt,output

    def color(self,encoding='srgb',assumption=None,did='d1'):
        return dict(derivation_id=did,encoding=encoding,encoding_basis={'auto':'embedded_metadata','unknown':'unknown'}.get(encoding,'explicit_output_declaration'),display_assumption=assumption)

    def test_edit_preserves_measured_draft_and_exact_version_binding(self):
        draft=self.draft();request=self.handoff.export_edit(self.case,draft['record_id']);p=request['payload']
        self.assertIn(draft['payload']['prompt'],p['prompt'])
        self.assertIn('increase_toward_B',p['prompt']);self.assertIn('decrease_toward_B',p['prompt'])
        self.assertEqual(p['compiled_record_hash'],draft['content_hash'])
        self.assertEqual(p['compiled_prompt_hash'],draft['payload']['prompt_hash'])
        self.assertEqual(p['prompt_version'],'s3_measured_whole_region_localization_v1')
        self.assertEqual(p['context']['target_hash'],self.target['content_hash'])
        self.assertEqual([i['role'] for i in p['images']],['A','B'])

    def test_superseded_and_foreign_drafts_refuse_without_new_attempt(self):
        draft=self.draft();spec=dict(version='v2',report_id=self.target['payload']['report_id'],
            diagnosis_record_id=self.target['payload']['diagnosis_record_id'],targets=[])
        report=read_json(self.case/co.status(self.case)['payload']['s2']['reports'][spec['report_id']]['path'])
        diag={'record_id':spec['diagnosis_record_id']};spec=self.target_spec(report,diag)
        spec.update(version='v2',revision=dict(predecessor_version='v1',predecessor_hash=self.target['content_hash'],reason_code='mapping_correction',rationale=None))
        self.st.freeze_targets(self.case,spec);before=(self.case/'state.json').read_bytes()
        for identity in (draft['record_id'],'compiled_request_'+'0'*32):
            with self.subTest(identity=identity),self.assertRaises(ValueError):self.handoff.export_edit(self.case,identity)
            self.assertEqual((self.case/'state.json').read_bytes(),before)

    def test_localization_aids_come_from_exact_support_and_never_modify_AB(self):
        draft=self.draft();before=[file_sha256(self.case/i['derivative_path']) for i in self.audit]
        req=self.handoff.export_edit(self.case,draft['record_id']);a=req['payload']['planned_attachments']
        self.assertEqual([x['purpose'] for x in a[:2]],['content_image','style_reference'])
        self.assertEqual(len(a),4)  # Parent S3 refinement: at most one composite guide per role.
        for aid in a[2:]:
            self.assertEqual(aid['purpose'],'localization_only');self.assertEqual(file_sha256(self.case/aid['path']),aid['sha256'])
            self.assertEqual(aid['geometry']['resize'],None);self.assertEqual(aid['geometry']['image_offset'],[0,24])
            pixels=np.asarray(Image.open(self.case/aid['path']))
            self.assertEqual([r['region_id'] for r in aid['regions']],['r1','r2'])
            np.testing.assert_array_equal(pixels[24,:4],np.array([[255,220,0]]*4))
            np.testing.assert_array_equal(pixels[25,:4],np.array([[0,220,255]]*4))
        self.assertEqual(before,[file_sha256(self.case/i['derivative_path']) for i in self.audit])
        self.assertIn('not hard masks',req['payload']['prompt'])

    def test_missing_supports_do_not_invent_localization_images(self):
        report=self.report(dict(snapshot_id='s1',evidence_ids=[],global_comparability='unknown',regions=[],relations=[],trusted_ocr=[]))
        _,diag=self.diagnose(report);spec=dict(version='v1',report_id=report['record_id'],diagnosis_record_id=diag['record_id'],targets=[
            dict(target_id='t1',measurement_id=None,visual_region_id='g0',visual_dimension='tone',visual_direction='match_B',judge_type='visual',priority='critical')])
        self.st.freeze_targets(self.case,spec);draft=self.st.compile_targets(self.case,'v1')
        req=self.handoff.export_edit(self.case,draft['record_id'])
        self.assertEqual(len(req['payload']['planned_attachments']),2)

    def test_submission_hashes_actual_files_and_exact_replay_is_read_only(self):
        req=self.handoff.export_edit(self.case,self.draft()['record_id']);spec,prompt=self.submission(req)
        result=self.handoff.record_submission(self.case,spec,prompt);state=(self.case/'state.json').read_bytes()
        self.assertEqual(result['payload']['package_status'],'matches_plan')
        self.assertEqual(result['payload']['provenance_verification'],'caller_attested_not_remote_authenticated')
        self.assertEqual(self.handoff.record_submission(self.case,spec,prompt),result)
        self.assertEqual((self.case/'state.json').read_bytes(),state)

    def test_changed_prompt_is_archived_as_mismatch_and_blocks_import(self):
        req=self.handoff.export_edit(self.case,self.draft()['record_id']);spec,prompt=self.submission(req)
        prompt.write_text('ACTUAL_DIFFERENT_PROMPT', encoding='utf-8', newline='');spec['prompt_sha256']=file_sha256(prompt)
        result=self.handoff.record_submission(self.case,spec,prompt)
        self.assertEqual(result['payload']['package_status'],'differs_from_plan')
        out=self.root/'C.png';Image.new('RGB',(4,2)).save(out);receipt=self.receipt(req,out);receipt['response_type']='image'
        receipt.update(submission_record_id=result['record_id'],submission_hash=result['content_hash'])
        with self.assertRaises(ValueError):co.import_response(self.case,receipt,out)
        self.assertEqual(co.status(self.case)['payload']['active_attempt']['status'],'response_unknown')

    def test_changed_missing_reordered_and_role_swapped_attachments_not_same_plan(self):
        # One fixture per variant avoids a previous immutable submission masking a failure.
        draft=self.draft()
        for n,variant in enumerate(('missing','swapped_role','reordered','changed_bytes')):
            case=self.root/f'variant{n}';import shutil;shutil.copytree(self.case,case);old=self.case;self.case=case
            try:
                req=self.handoff.export_edit(case,draft['record_id']);spec,prompt=self.submission(req)
                if variant=='missing':spec['attachments'].pop()
                elif variant=='swapped_role':spec['attachments'][0]['role']='B'
                elif variant=='reordered':spec['attachments'].reverse()
                else:
                    p=self.root/'other.png';Image.new('RGB',(4,2),(1,2,3)).save(p)
                    spec['attachments'][0].update(path=str(p),sha256=file_sha256(p))
                self.assertEqual(self.handoff.record_submission(case,spec,prompt)['payload']['package_status'],'differs_from_plan')
            finally:self.case=old

    def test_duplicate_attachment_or_false_actual_hash_rejects_before_registration(self):
        req=self.handoff.export_edit(self.case,self.draft()['record_id']);spec,prompt=self.submission(req)
        for bad in ('duplicate','false_hash','wrong_request'):
            s=copy.deepcopy(spec)
            if bad=='duplicate':s['attachments'].append(s['attachments'][0])
            elif bad=='false_hash':s['attachments'][0]['sha256']='0'*64
            else:s['request_hash']='0'*64
            with self.subTest(bad=bad),self.assertRaises(ValueError):self.handoff.record_submission(self.case,s,prompt)

    def test_receipt_needs_actual_submission_and_matching_tool_reference(self):
        req=self.handoff.export_edit(self.case,self.draft()['record_id']);out=self.root/'C.png';Image.new('RGB',(4,2)).save(out)
        receipt=self.receipt(req,out);receipt['response_type']='image'
        with self.assertRaises(ValueError):co.import_response(self.case,receipt,out)
        spec,prompt=self.submission(req);sub=self.handoff.record_submission(self.case,spec,prompt)
        receipt.update(submission_record_id=sub['record_id'],submission_hash=sub['content_hash'])
        receipt['provenance']['tool_call_ref']='different'
        with self.assertRaises(ValueError):co.import_response(self.case,receipt,out)

    def test_unknown_pauses_and_old_C_replay_cannot_consume_new_attempt(self):
        draft=self.draft();req=self.handoff.export_edit(self.case,draft['record_id'])
        co.mark_unknown(self.case,req['payload']['attempt_id'],'Tool result unknown')
        with self.assertRaises(ValueError):self.handoff.export_edit(self.case,draft['record_id'])
        response,receipt,out=self.candidate(req)
        next_req=self.handoff.export_edit(self.case,draft['record_id']);state=(self.case/'state.json').read_bytes()
        self.assertEqual(co.import_response(self.case,receipt,out),response)
        self.assertEqual((self.case/'state.json').read_bytes(),state)
        self.assertEqual(co.status(self.case)['payload']['active_attempt']['attempt_id'],next_req['payload']['attempt_id'])

    def test_raw_C_hash_is_not_derivative_hash_and_never_resized_to_A(self):
        req=self.handoff.export_edit(self.case,self.draft()['record_id']);response,_,out=self.candidate(req)
        result=self.candidates.derive_candidate(self.case,response['record_id'],self.color());p=result['payload']
        self.assertEqual(p['status'],'standardized');self.assertEqual(p['raw_candidate_hash'],file_sha256(out))
        self.assertEqual(p['audit']['native_size'],[5,3]);self.assertEqual(p['audit']['oriented_size'],[5,3])
        self.assertEqual(p['geometry']['spatial_correspondence'],'unverified');self.assertIsNone(p['geometry']['resize'])
        self.assertEqual(p['visual_style_status'],'not_evaluated');self.assertFalse(p['geometry']['size_matches_A'])
        self.assertEqual(file_sha256(self.case/response['payload']['output_path']),file_sha256(out))

    def test_unknown_untagged_C_blocks_numeric_but_explicit_assumption_is_display_only(self):
        req=self.handoff.export_edit(self.case,self.draft()['record_id']);response,_,_=self.candidate(req)
        blocked=self.candidates.derive_candidate(self.case,response['record_id'],self.color('auto'))
        self.assertEqual(blocked['payload']['status'],'blocked_unknown_encoding');self.assertIsNone(blocked['payload']['audit'])
        assumed=self.candidates.derive_candidate(self.case,response['record_id'],self.color('unknown','srgb','d2'))
        self.assertEqual(assumed['payload']['status'],'assumed_display_only')
        self.assertIsNone(assumed['payload']['audit']['analysis_path'])

    def test_ICC_known_C_and_exif_orientation_are_explicit_not_alignment(self):
        req=self.handoff.export_edit(self.case,self.draft()['record_id']);p=self.root/'C.jpg'
        exif=Image.Exif();exif[274]=6;Image.new('RGB',(3,5),(25,75,100)).save(p,exif=exif,icc_profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes())
        response,_,_=self.candidate(req,p);r=self.candidates.derive_candidate(self.case,response['record_id'],self.color('auto'))['payload']
        self.assertEqual(r['status'],'standardized');self.assertEqual(r['audit']['orientation'],6)
        self.assertEqual(r['audit']['native_size'],[3,5]);self.assertEqual(r['audit']['oriented_size'],[5,3])
        self.assertEqual(r['geometry']['spatial_correspondence'],'unverified')

    def test_rgb16_precision_and_failed_derivation_preserve_raw(self):
        from hre.reference_style.color import encode_png16
        req=self.handoff.export_edit(self.case,self.draft()['record_id']);p=self.root/'C16.png'
        encode_png16(p,np.full((2,4,3),10001/65535));response,_,_=self.candidate(req,p)
        result=self.candidates.derive_candidate(self.case,response['record_id'],self.color())['payload']
        self.assertEqual(result['audit']['source_bit_depth'],16)
        with np.load(self.case/result['audit']['analysis_path'],allow_pickle=False) as arrays:
            self.assertAlmostEqual(float(arrays['Y'][0,0]),((10001/65535+0.055)/1.055)**2.4)

    def test_unsupported_candidate_is_retained_even_when_derivation_fails(self):
        req=self.handoff.export_edit(self.case,self.draft()['record_id']);p=self.root/'C.png'
        Image.new('RGBA',(4,2),(20,30,40,128)).save(p);response,_,_=self.candidate(req,p)
        result=self.candidates.derive_candidate(self.case,response['record_id'],self.color())
        self.assertEqual(result['payload']['status'],'failed')
        self.assertEqual(file_sha256(self.case/response['payload']['output_path']),file_sha256(p))
        self.assertIsNone(result['payload']['audit'])

    def test_derivation_replay_is_read_only_and_cannot_relabel_same_ID(self):
        req=self.handoff.export_edit(self.case,self.draft()['record_id']);response,_,_=self.candidate(req)
        spec=self.color();first=self.candidates.derive_candidate(self.case,response['record_id'],spec)
        state=(self.case/'state.json').read_bytes();self.assertEqual(self.candidates.derive_candidate(self.case,response['record_id'],spec),first)
        self.assertEqual((self.case/'state.json').read_bytes(),state)
        with self.assertRaises(ValueError):self.candidates.derive_candidate(self.case,response['record_id'],self.color('display_p3'))

    def test_malformed_provenance_is_contract_error_not_unhandled_exception(self):
        req=self.handoff.export_edit(self.case,self.draft()['record_id']);spec,prompt=self.submission(req)
        sub=self.handoff.record_submission(self.case,spec,prompt);out=self.root/'C.png';Image.new('RGB',(4,2)).save(out)
        receipt=self.receipt(req,out);receipt.update(response_type='image',submission_record_id=sub['record_id'],submission_hash=sub['content_hash'],provenance=[])
        with self.assertRaises(ValueError):co.import_response(self.case,receipt,out)

    def test_oversized_header_and_unreadable_outputs_still_preserve_raw_bytes(self):
        import struct,zlib,shutil
        draft=self.draft()
        for n,data in enumerate((b'not an image but actual returned bytes',None)):
            case=self.root/f'bad{n}';shutil.copytree(self.case,case);old=self.case;self.case=case
            try:
                req=self.handoff.export_edit(case,draft['record_id']);out=self.root/'C.bin'
                if data is None:
                    buffer=self.root/'base.png';Image.new('RGB',(4,2)).save(buffer);data=bytearray(buffer.read_bytes())
                    data[16:24]=struct.pack('>II',100000,100000);data[29:33]=struct.pack('>I',zlib.crc32(data[12:29])&0xffffffff)
                out.write_bytes(data);response,_,_=self.candidate(req,out)
                self.assertEqual(file_sha256(case/response['payload']['output_path']),file_sha256(out))
                derived=self.candidates.derive_candidate(case,response['record_id'],self.color())
                self.assertEqual(derived['payload']['status'],'failed')
            finally:self.case=old

    def test_profile_conflict_fails_derivation_but_declared_P3_converts_explicitly(self):
        import shutil
        draft=self.draft()
        for n,tagged in enumerate((False,True)):
            case=self.root/f'color{n}';shutil.copytree(self.case,case);old=self.case;self.case=case
            try:
                req=self.handoff.export_edit(case,draft['record_id']);out=self.root/'C.png'
                kwargs={'icc_profile':ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()} if tagged else {}
                Image.new('RGB',(4,2),(255,0,0)).save(out,**kwargs);response,_,_=self.candidate(req,out)
                result=self.candidates.derive_candidate(case,response['record_id'],self.color('display_p3'))['payload']
                self.assertEqual(result['status'],'failed' if tagged else 'standardized')
                if not tagged:
                    self.assertEqual(result['audit']['source_encoding'],'display_p3')
                    self.assertGreater(result['audit']['gamut_clipped_pixel_fraction'],0)
                self.assertEqual(file_sha256(case/response['payload']['output_path']),file_sha256(out))
            finally:self.case=old

    def test_draft_or_localization_tampering_blocks_export_and_import(self):
        draft=self.draft();req=self.handoff.export_edit(self.case,draft['record_id'])
        aid=req['payload']['planned_attachments'][2];p=self.case/aid['path'];raw=p.read_bytes();p.write_bytes(raw+b'tamper')
        with self.assertRaises(ValueError):co.status(self.case)
        p.write_bytes(raw)
        response,_,_=self.candidate(req);path=self.case/co.status(self.case)['payload']['s2']['compiled'][draft['record_id']]['path']
        value=read_json(path);value['payload']['prompt']='POLICY_SENTINEL';import json;path.write_text(json.dumps(value), encoding='utf-8', newline='')
        with self.assertRaises(ValueError):self.handoff.export_edit(self.case,draft['record_id'])

    def test_private_policy_and_source_narrative_never_enter_edit_or_labels(self):
        from hre.reference_style.verification_store import store_policy
        draft=self.draft();store_policy(self.case,dict(policy_id='p1',version='v1',overall_style_achieved_required=True,
            posthoc_principles=['POLICY_SENTINEL_FACE_SHIFTS_FINE'],unknown_or_major_deviation='insufficient_evidence_or_reject'))
        request=self.handoff.export_edit(self.case,draft['record_id'])
        self.assertNotIn('POLICY_SENTINEL',str(request));self.assertNotIn('SYNTHETIC_NARRATIVE',str(request))
        self.assertEqual(request['payload']['context']['preservation_requirements'],self.target['payload']['preservation_requirements'])

    def test_C_same_dimensions_are_not_spatial_alignment(self):
        req=self.handoff.export_edit(self.case,self.draft()['record_id']);out=self.root/'C.png';Image.new('RGB',(4,2)).save(out)
        response,_,_=self.candidate(req,out);p=self.candidates.derive_candidate(self.case,response['record_id'],self.color())['payload']
        self.assertTrue(p['geometry']['size_matches_A']);self.assertEqual(p['spatial_correspondence'],'unverified')
        self.assertEqual(p['numeric_region_support'],'requires_true_C_coordinate_evidence')

    def test_real_bbox_support_produces_visual_only_composite_guides(self):
        for eid,role in [('e1','A'),('e2','B')]:self.import_json(eid,role,'face',[dict(bbox=[0,0,2,1],confidence=0.7)])
        report=self.report(dict(snapshot_id='s1',evidence_ids=['e1','e2'],global_comparability='unknown',regions=[
            dict(region_id='r1',semantic_class='face',A=dict(evidence_id='e1',entry_index=0),B=dict(evidence_id='e2',entry_index=0),
                 match_status='confirmed',composition='comparable',illumination='comparable',parent_id=None,usage='independent')],relations=[],trusted_ocr=[]))
        _,diag=self.diagnose(report);spec=dict(version='v1',report_id=report['record_id'],diagnosis_record_id=diag['record_id'],targets=[
            dict(target_id='t1',measurement_id=None,visual_region_id='r1',visual_dimension='tone',visual_direction='match_B',judge_type='visual',priority='critical')])
        frozen=self.st.freeze_targets(self.case,spec);draft=self.st.compile_targets(self.case,'v1')
        request=self.handoff.export_edit(self.case,draft['record_id'])
        self.assertEqual(len(request['payload']['planned_attachments']),4)
        self.assertEqual(request['payload']['planned_attachments'][2]['regions'][0]['bbox'],[0,0,2,1])
        self.assertEqual(frozen['payload']['targets'][0]['evidence_eligibility'],'visual_direction_only')

    def test_cli_handoff_and_derivation_are_real_interfaces(self):
        import io,json
        from contextlib import redirect_stdout
        from hre.reference_style.cli import main
        draft=self.draft();buffer=io.StringIO()
        with redirect_stdout(buffer):rc=main(['edit-export','--root',str(self.case),'--compiled-id',draft['record_id']])
        self.assertEqual(rc,0);request=json.loads(buffer.getvalue());response,_,_=self.candidate(request)
        spec=self.root/'color.json';spec.write_text(json.dumps(self.color()), encoding='utf-8', newline='');buffer=io.StringIO()
        with redirect_stdout(buffer):rc=main(['candidate-derive','--root',str(self.case),'--response-id',response['record_id'],'--spec',str(spec)])
        self.assertEqual(rc,0);self.assertEqual(json.loads(buffer.getvalue())['payload']['status'],'standardized')


if __name__=='__main__':unittest.main()
