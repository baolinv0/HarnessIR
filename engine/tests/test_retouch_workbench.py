import base64
import copy
import io
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from PIL import Image
try:
    from hre.retouch.contracts import RetouchError, validate_contract, decide_verification, compile_prompt
    from hre.retouch.evidence import measure
    from hre.retouch.workflow import Workbench
except ModuleNotFoundError:
    Workbench = None

def picture(color=(90,100,110), size=(96,128)):
    b=io.BytesIO(); Image.new("RGB",size,color).save(b,format="PNG")
    return "data:image/png;base64,"+base64.b64encode(b.getvalue()).decode()

def analysis():
    dims=['neutral_balance','chroma_by_hue','skin_rendering','shadow_midtone_highlight','highlight_transition','local_contrast','subject_background_balance','texture_and_noise_observation']
    return {"source_diagnosis":{"source_degradation":[],"source_appearance":["脸部中间调较暗"],"protected_facts":["眼镜与脸型"],"unreadable_text_regions":[]},
            "reference_profile":[{"attribute":d,"status":"observed" if d=='skin_rendering' else 'uncertain',"observation":"参考肤色更明亮" if d=='skin_rendering' else '当前测试未提供该维度的可靠依据',"region":"face","evidence_refs":["B"]} for d in dims],
            "correspondence":[],"candidate_deltas":[
                {"id":"d_face_brightness","attribute":"brightness","source_region":"face","reference_region":"face",
                 "source_observation":"较暗","reference_observation":"更明亮","desired_change":"提亮脸部中间调",
                 "comparability":"comparable","uncertainty":"","evidence_refs":["A","B"]},
                {"id":"d_skin_color","attribute":"color","source_region":"face","reference_region":"face",
                 "source_observation":"偏灰","reference_observation":"较暖","desired_change":"借鉴参考自然暖肤色",
                 "comparability":"comparable","uncertainty":"","evidence_refs":["A","B"]}],
            "coverage":[{"attribute":d,"status":"targeted" if d=='skin_rendering' else 'uncertain',
                         "reason":"本软件样例记录该维度的依据或不确定性"} for d in dims],"analysis_status":"transfer_supported","evidence_requests":[]}

def contract():
    return {"targets":[{"target_id":"face_brightness","delta_id":"d_face_brightness","attribute":"brightness","source_region":"face","reference_region":"face","source_observation":"较暗","reference_observation":"更明亮","desired_change":"提亮脸部中间调","mandatory":True,"acceptance_criterion":"脸部曝光接近参考但保持高光层次","evidence_refs":["A","B"],"comparability":"comparable","uncertainty":""},
                       {"target_id":"skin_color","delta_id":"d_skin_color","attribute":"color","source_region":"face","reference_region":"face","source_observation":"偏灰","reference_observation":"较暖","desired_change":"借鉴参考自然暖肤色","mandatory":True,"acceptance_criterion":"无额外青灰偏色且不改变身份","evidence_refs":["A","B"],"comparability":"comparable","uncertainty":""}],
            "protected_facts":["眼镜与脸型"],"excluded_reference_traits":["背景几何与文字"],"coverage":[{"attribute":p['attribute'],"status":"targeted" if p['attribute']=='skin_rendering' else 'uncertain',"target_ids":["face_brightness","skin_color"] if p['attribute']=='skin_rendering' else [],"reason":"通过目标表达" if p['attribute']=='skin_rendering' else '当前样例无可靠依据'} for p in analysis()['reference_profile']],"overall_status":"ready_to_edit","acceptance_rule":"全部必需项通过"}

def verification(status="achieved"):
    return {"target_results":[{"target_id":"face_brightness","status":"achieved","observation":"提亮达标","evidence_refs":["A","B","C"],"remaining_gap":"","suggested_correction":""},
                              {"target_id":"skin_color","status":status,"observation":"检查肤色","evidence_refs":["A","B","C"],"remaining_gap":"肤色未达标" if status!="achieved" else "","suggested_correction":"修正肤色" if status=="unmet" else ""}],
            "preservation_checks":[{"item":"眼镜与脸型","status":"pass","observation":"保持","evidence_refs":["A","C"]}],
            "artifact_checks":[{"item":"naturalness","status":"pass","observation":"软件样例中未记录重大伪影","evidence_refs":["A","C"]},
                               {"item":"reference_content_leakage","status":"pass","observation":"软件样例中未记录参考内容污染","evidence_refs":["B","C"]},
                               {"item":"unsupported_detail","status":"pass","observation":"软件样例中未记录无依据细节","evidence_refs":["A","C"]}],
            "global_status":"accept","actionable_issues":[],"evaluator_coverage":[]}

class ContractTests(unittest.TestCase):
    def setUp(self): self.assertIsNotNone(Workbench,"Reference retouch implementation is missing")
    def test_partial_style_is_not_accepted(self):
        self.assertEqual(decide_verification(contract(),verification("unmet")),"revise")
    def test_unknown_mandatory_blocks_success(self):
        self.assertEqual(decide_verification(contract(),verification("uncertain")),"uncertain")
    def test_content_damage_rejects(self):
        v=verification();v["preservation_checks"][0]["status"]="fail"
        self.assertEqual(decide_verification(contract(),v),"reject")
    def test_missing_target_is_invalid(self):
        v=verification();v["target_results"].pop()
        with self.assertRaises(RetouchError): decide_verification(contract(),v)
    def test_prompt_preserves_target_coverage(self):
        p=compile_prompt(contract())
        self.assertIn("face_brightness",p);self.assertIn("skin_color",p)
        self.assertIn("image 1",p);self.assertIn("image 2",p)
    def test_incomparable_mandatory_target_rejected(self):
        c=contract();c["targets"][0]["comparability"]="incomparable"
        with self.assertRaises(RetouchError): validate_contract(c)

    def test_contract_cannot_omit_reference_coverage(self):
        c=contract();c['coverage']=[]
        with self.assertRaises(RetouchError):validate_contract(c)

    def test_contract_coverage_cannot_point_to_dropped_target(self):
        c=contract();c['targets'].pop()
        with self.assertRaises(RetouchError):validate_contract(c)

    def test_all_source_protections_must_be_verified(self):
        v=verification();v['preservation_checks'][0]['item']='unrelated background'
        with self.assertRaises(RetouchError):decide_verification(contract(),v)

    def test_target_status_requires_observed_evidence(self):
        v=verification();v['target_results'][0]['evidence_refs']=[]
        with self.assertRaises(RetouchError):decide_verification(contract(),v)

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(Workbench,"Reference retouch implementation is missing")
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.w=Workbench(Path(self.tmp.name))
        self.c=self.w.create({"source_data":picture(),"reference_data":picture((160,150,120)),
                             "source_name":"A.png","reference_name":"B.png","brief":"参考肤色与影调"})
    def test_real_measurements_without_provider(self):
        c=self.w.step(self.c["id"],"evidence")
        self.assertAlmostEqual(c["evidence"]["source"]["mean_rgb"][0],90,places=4)
        self.assertAlmostEqual(c["evidence"]["reference"]["mean_rgb"][0],160,places=4)
        self.assertEqual(c["calls"]["images"],0)
    def test_missing_provider_is_visible_not_simulated(self):
        c=self.w.step(self.c["id"],"diagnose")
        self.assertIsNone(c["analysis"]);self.assertEqual(c["calls"]["analysis"],0)
        self.assertEqual(next(s for s in c["stages"] if s["id"]=="diagnose")["status"],"needs_input")
    def test_no_degradation_does_not_skip_style(self):
        c=self.w.import_stage(self.c["id"],"diagnose",analysis(),"manual_agent")
        self.assertEqual(c["phase"],"evidence")
        self.w.step(c["id"],"evidence")
        c=self.w.import_stage(c["id"],"compose",contract(),"manual_agent")
        self.assertEqual(c["phase"],"edit");self.assertIsNotNone(c["contract"])
    def test_already_satisfied_does_not_call_editor(self):
        a=analysis();a.update(analysis_status="already_close",candidate_deltas=[])
        for row in a['coverage']:row.update(status='already_satisfied')
        self.w.import_stage(self.c["id"],"diagnose",a,"manual_agent")
        c=contract();c["targets"]=[];c["overall_status"]="already_satisfied"
        for row in c['coverage']:row.update(status='already_satisfied',target_ids=[])
        s=self.w.import_stage(self.c["id"],"compose",c,"human")
        self.assertEqual(s["status"],"already_satisfied");self.assertEqual(s["calls"]["images"],0)
    def test_regions_cannot_change_after_freezing(self):
        self.w.import_stage(self.c["id"],"diagnose",analysis(),"manual_agent")
        self.w.import_stage(self.c["id"],"compose",contract(),"manual_agent")
        with self.assertRaises(RetouchError): self.w.regions(self.c["id"],[])
    def test_invalid_box_rejected(self):
        with self.assertRaises(RetouchError):
            self.w.regions(self.c["id"],[{"id":"face","description":"face","source_box":[.8,0,.2,1],"reference_box":[0,0,1,1]}])
    def test_editor_export_keeps_original_pair(self):
        self.w.import_stage(self.c["id"],"diagnose",analysis(),"manual_agent")
        self.w.import_stage(self.c["id"],"compose",contract(),"manual_agent")
        req=self.w.export(self.c["id"],"edit")
        self.assertEqual([x["role"] for x in req["images"]],["source","appearance_reference"])
        self.assertNotIn("seed",req["settings"]);self.assertNotIn("input_fidelity",req["settings"])
    def test_frozen_contract_cannot_be_reimported(self):
        self.w.import_stage(self.c["id"],"diagnose",analysis(),"manual_agent")
        self.w.import_stage(self.c["id"],"compose",contract(),"manual_agent")
        with self.assertRaises(RetouchError):
            self.w.import_stage(self.c["id"],"compose",contract(),"human")

    def test_analysis_cannot_omit_reference_dimensions(self):
        a=analysis();a['reference_profile'].pop()
        with self.assertRaises(RetouchError): self.w.import_stage(self.c['id'],'diagnose',a,'manual_agent')

    def test_feedback_must_cite_actual_unmet_observation(self):
        self.w.import_stage(self.c['id'],'diagnose',analysis(),'manual_agent')
        self.w.import_stage(self.c['id'],'compose',contract(),'manual_agent')
        self.w.candidate(self.c['id'],picture(),'gpt-image-2')
        self.w.import_stage(self.c['id'],'verify',verification('unmet'),'manual_agent')
        with self.assertRaises(RetouchError):
            self.w.import_stage(self.c['id'],'refine',{'action':'revise','correction':'修正肤色','changed_target_ids':['skin_color'],'feedback_refs':['invented_issue']},'manual_agent')

    def test_feedback_retains_complete_goals_and_original_images(self):
        self.w.import_stage(self.c['id'],'diagnose',analysis(),'manual_agent')
        self.w.import_stage(self.c['id'],'compose',contract(),'manual_agent')
        initial=self.w.export(self.c['id'],'edit')
        self.w.candidate(self.c['id'],picture(),'gpt-image-2')
        self.w.import_stage(self.c['id'],'verify',verification('unmet'),'manual_agent')
        self.w.import_stage(self.c['id'],'refine',{'action':'revise','correction':'修正肤色','changed_target_ids':['skin_color'],'feedback_refs':['verification:skin_color']},'manual_agent')
        revised=self.w.export(self.c['id'],'edit')
        self.assertEqual(initial['images'],revised['images'])
        self.assertIn('face_brightness',revised['prompt']);self.assertIn('skin_color',revised['prompt'])

    def test_last_unknown_attempt_resolves_without_second_charge(self):
        self.w.import_stage(self.c['id'],'diagnose',analysis(),'manual_agent')
        self.w.import_stage(self.c['id'],'compose',contract(),'manual_agent')
        c=self.w._load(self.c['id']);c['calls']['images']=3;c['status']='submission_unknown';c['pending_image']={'attempt_id':'attempt3'};self.w._save(c)
        c=self.w.candidate(c['id'],picture(),'gpt-image-2',pending_attempt_id='attempt3')
        self.assertEqual(c['calls']['images'],3);self.assertIsNone(c['pending_image'])

    def test_candidate_cannot_bypass_feedback(self):
        self.w.import_stage(self.c['id'],'diagnose',analysis(),'manual_agent')
        self.w.import_stage(self.c['id'],'compose',contract(),'manual_agent')
        self.w.candidate(self.c['id'],picture(),'gpt-image-2')
        self.w.import_stage(self.c['id'],'verify',verification('unmet'),'manual_agent')
        with self.assertRaises(RetouchError):self.w.candidate(self.c['id'],picture(),'gpt-image-2')

    def test_verify_receives_real_evidence_and_geometry(self):
        self.w.import_stage(self.c['id'],'diagnose',analysis(),'manual_agent');self.w.step(self.c['id'],'evidence')
        self.w.import_stage(self.c['id'],'compose',contract(),'manual_agent');self.w.candidate(self.c['id'],picture(),'gpt-image-2')
        req=self.w.export(self.c['id'],'verify')
        self.assertIn('evidence',req['context']);self.assertIn('geometry',req['context'])
        self.assertNotIn('prompt',req['context'])

    def test_frozen_compose_does_not_spend_another_call(self):
        self.w.import_stage(self.c['id'],'diagnose',analysis(),'manual_agent');self.w.import_stage(self.c['id'],'compose',contract(),'manual_agent')
        with patch('hre.retouch.providers.settings',return_value={'analysis_configured':True,'image_configured':False,'image_model':'gpt-image-2'}),patch('hre.retouch.providers.analyze',side_effect=AssertionError('must not call')):
            with self.assertRaises(RetouchError):self.w.step(self.c['id'],'compose')
        self.assertEqual(self.w.get(self.c['id'])['calls']['analysis'],0)

    def test_eight_analysis_calls_are_a_hard_limit(self):
        c=self.w._load(self.c['id']);c['calls']['analysis']=8;self.w._save(c)
        with patch('hre.retouch.providers.settings',return_value={'analysis_configured':True,'image_configured':False,'image_model':'gpt-image-2'}),patch('hre.retouch.providers.analyze',side_effect=AssertionError('must not call')):
            with self.assertRaises(RetouchError):self.w.step(c['id'],'diagnose')

    def test_draft_does_not_freeze_inputs(self):
        self.w.import_stage(self.c['id'],'diagnose',analysis(),'manual_agent')
        c=contract();c['overall_status']='insufficient_evidence'
        result=self.w.import_stage(self.c['id'],'compose',c,'manual_agent')
        self.assertIsNone(result['contract']);self.assertIsNotNone(result['contract_draft'])
        self.w.regions(self.c['id'],[])

    def test_protected_source_facts_cannot_disappear(self):
        self.w.import_stage(self.c['id'],'diagnose',analysis(),'manual_agent')
        c=contract();c['protected_facts']=['unrelated background']
        with self.assertRaises(RetouchError):self.w.import_stage(self.c['id'],'compose',c,'manual_agent')

    def test_unknown_evidence_cannot_be_used_for_goal(self):
        self.w.import_stage(self.c['id'],'diagnose',analysis(),'manual_agent')
        c=contract();c['targets'][0]['evidence_refs']=['evidence:never_observed']
        with self.assertRaises(RetouchError):self.w.import_stage(self.c['id'],'compose',c,'manual_agent')

    def test_stale_verification_cannot_resolve_unknown_edit(self):
        self.w.import_stage(self.c['id'],'diagnose',analysis(),'manual_agent');self.w.import_stage(self.c['id'],'compose',contract(),'manual_agent')
        self.w.candidate(self.c['id'],picture(),'gpt-image-2');self.w.import_stage(self.c['id'],'verify',verification('unmet'),'manual_agent')
        c=self.w._load(self.c['id']);c['phase']='edit';c['status']='submission_unknown';c['pending_image']={'attempt_id':'next_attempt'};self.w._save(c)
        with self.assertRaises(RetouchError):self.w.import_stage(c['id'],'verify',verification(),'manual_agent')

    def test_verification_cannot_claim_nonexistent_tool(self):
        self.w.import_stage(self.c['id'],'diagnose',analysis(),'manual_agent');self.w.import_stage(self.c['id'],'compose',contract(),'manual_agent')
        self.w.candidate(self.c['id'],picture(),'gpt-image-2')
        v=verification();v['preservation_checks'][0]['evidence_refs']=['invented_ocr_service']
        with self.assertRaises(RetouchError):self.w.import_stage(self.c['id'],'verify',v,'manual_agent')

if __name__=="__main__": unittest.main()
