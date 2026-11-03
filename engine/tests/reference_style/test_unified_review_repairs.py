"""File-bound style regressions for round-one review blockers B2/B3."""
from copy import deepcopy
from hre.reference_core import evaluation
from hre.reference_style import unified
from test_unified import UnifiedStyleTest


class UnifiedReviewRepairTest(UnifiedStyleTest):
    def configured(self,detail=False,conflict_stage=None):
        f=self.f;original=f.draft
        def draft():
            original();spec=self.semantic_spec(prepare=False)
            spec["semantics"]["delivery_requirements"]["require_detail_pass"]=detail
            unified.freeze_semantics(f.case,spec);unified.record_preflight(f.case,dict(semantic_version="u1",planned_size=None,capability_known=False))
            return f.st.compile_targets(f.case,"v1")
        f.draft=draft;f.configured_evaluation()
        images=[dict(role=role,path=str(f.case/a["derivative_path"]),sha256=a["derivative_file_hash"]) for role,a in zip(("A","B"),f.audit)]
        a=f.evaluation["payload"]["selected_artifact"];images.append(dict(role="C",path=str(f.case/a["path"]),sha256=a["file_hash"]))
        axis=dict(reference_status="achieved",relation="closer",direction="fixture",magnitude="slight",confidence="high",evidence="Synthetic file-bound fixture only")
        self.holistic=[]
        for n,stage in enumerate(evaluation.STAGES):
            spec=dict(schema_version="hre_holistic_review_v1",review_id="r"+str(n+1),sample_id=f.evaluation["sample_id"],stage=stage,
                predecessor_hash=None if not self.holistic else self.holistic[-1]["content_hash"],images=images,
                display=dict(method="side_by_side",scale="native full frame",color_basis="sRGB fixture",note="Synthetic fixture"),
                reviewer=dict(reviewer_id="reviewer",independence="independent",prior_exposure="Synthetic fixture only"),
                whole_image={a:deepcopy(axis) for a in evaluation.AXES} if n==0 else None,
                preservation={k:dict(status="pass",confidence="high",evidence="Synthetic fixture") for k in evaluation.PROTECTIONS} if n==0 else None,
                regions=[],metrics=[],conflicts=["Unresolved whole/region interpretation"] if stage==conflict_stage else [])
            self.holistic.append(unified.import_holistic(f.case,spec))
        self.facts=f.review.freeze_facts(f.case,f.facts_spec());return f

    def resolution(self,status="resolved"):
        original=next(r for r in self.holistic if r["payload"]["conflicts"])
        return dict(schema_version="hre_holistic_resolution_v1",resolution_id="res1",sample_id=self.f.evaluation["sample_id"],
            predecessor_hash=self.holistic[-1]["content_hash"],review_hashes=[r["content_hash"] for r in self.holistic],
            images=deepcopy(original["payload"]["images"]),display=deepcopy(original["payload"]["display"]),reviewer=deepcopy(original["payload"]["reviewer"]),
            resolutions=[dict(review_hash=original["content_hash"],conflict_index=0,conflict=original["payload"]["conflicts"][0],
                status=status,confidence="high",evidence="Actual same-candidate synthetic re-review resolves this named discrepancy")])

    def test_all_stage_conflicts_block_acceptance_and_bound_resolution_restores(self):
        for stage in evaluation.STAGES:
            with self.subTest(stage=stage):
                if stage!=evaluation.STAGES[0]:self.doCleanups();self.setUp()
                f=self.configured(conflict_stage=stage)
                before={r["payload"]["review_id"]:(f.case/"unified/holistic"/self.holistic[0]["payload"]["images"][2]["sha256"]/"holistic"/(r["payload"]["review_id"]+".json")).read_bytes() for r in self.holistic}
                first=f.decision(self.facts)
                self.assertEqual(first["payload"]["status"],"needs_user_review")
                self.assertTrue(first["payload"]["unified_holistic_assessment"]["unresolved_conflicts"])
                unified.resolve_holistic(f.case,self.resolution())
                later=f.decision(self.facts,decision_id="z2",predecessor=dict(decision_id="z1",hash=first["content_hash"]))
                self.assertEqual(later["payload"]["status"],"accepted")
                for r in self.holistic:self.assertEqual(before[r["payload"]["review_id"]],(f.case/"unified/holistic"/r["payload"]["images"][2]["sha256"]/"holistic"/(r["payload"]["review_id"]+".json")).read_bytes())

    def test_unknown_rejected_or_unbound_resolutions_never_clear_conflict(self):
        f=self.configured(conflict_stage="whole_image")
        for field in ("predecessor_hash","review_hashes","images","resolutions","schema_version"):
            bad=self.resolution()
            if field=="predecessor_hash":bad[field]="0"*64
            elif field=="review_hashes":bad[field]=[]
            elif field=="images":bad[field][2]["sha256"]="0"*64
            elif field=="schema_version":bad[field]="legacy_review"
            else:bad[field][0]["conflict"]="Never recorded conflict"
            with self.assertRaises(ValueError):unified.resolve_holistic(f.case,bad)
        first=unified.resolve_holistic(f.case,self.resolution("uncertain"))
        self.assertEqual(unified.holistic_for_evaluation(f.case,f.evaluation)["status"],"needs_user_review")
        next_spec=self.resolution("rejected");next_spec.update(resolution_id="res2",predecessor_hash=first["content_hash"])
        unified.resolve_holistic(f.case,next_spec)
        self.assertEqual(unified.holistic_for_evaluation(f.case,f.evaluation)["status"],"needs_user_review")

    def detail_spec(self,status="pass"):
        f=self.f;e=f.evaluation["payload"];d=f.derived["payload"]
        detail=dict(schema_version="hre_native_detail_review_v1",review_id="nd1",source_sha256=f.audit[0]["source_file_hash"],
            native_sha256=e["raw_candidate_hash"],native_size=d["audit"]["native_size"],result_hash=e["response_hash"],evaluation_hash=f.evaluation["content_hash"],
            selected_sha256=e["selected_artifact"]["file_hash"],reviewer=dict(reviewer_id="native_reviewer",independence="independent",prior_exposure="Synthetic fixture only"),
            display=dict(method="native_pixels_1_to_1",note="Actual raw native C inspected against frozen A"),status=status,confidence="high",observation="Synthetic native-detail observation")
        return dict(evaluation_id=e["evaluation_id"],predecessor_hash=None,resolves_hashes=[],detail=detail)

    def test_bound_native_detail_pass_completes_delivery_while_fail_unknown_do_not(self):
        for status,expected in (("pass","accepted"),("fail","delivery_not_met"),("unknown","delivery_not_met")):
            with self.subTest(status=status):
                if status!="pass":self.doCleanups();self.setUp()
                f=self.configured(detail=True)
                self.assertEqual(f.decision(self.facts)["payload"]["status"],"delivery_not_met")
                unified.import_detail(f.case,self.detail_spec(status))
                previous=f.verifier._decisions(f.case,f.verifier.co._status(f.case),"j1")[-1]
                decision=f.decision(self.facts,decision_id="z2",predecessor=dict(decision_id="z1",hash=previous["content_hash"]))
                self.assertEqual(decision["payload"]["status"],expected)

    def test_detail_wrong_native_evaluation_selected_or_result_is_rejected(self):
        f=self.configured(detail=True)
        for key in ("native_sha256","evaluation_hash","result_hash","selected_sha256","source_sha256"):
            bad=self.detail_spec();bad["detail"][key]="0"*64
            with self.assertRaises(ValueError):unified.import_detail(f.case,bad)

    def test_detail_unknown_can_complete_by_append_and_conflicting_reviews_need_explicit_resolution(self):
        f=self.configured(detail=True);first=unified.import_detail(f.case,self.detail_spec("unknown"))
        original=(f.case/"unified/detail/j1/nd1.json").read_bytes()
        later=self.detail_spec("pass");later["detail"]["review_id"]="nd2";later["predecessor_hash"]=first["content_hash"]
        passed=unified.import_detail(f.case,later)
        self.assertTrue(unified.delivery_for_evaluation(f.case,f.verifier.co._status(f.case),f.evaluation)["pass"])
        failed=self.detail_spec("fail");failed["detail"]["review_id"]="nd3";failed["predecessor_hash"]=passed["content_hash"]
        rejected=unified.import_detail(f.case,failed)
        self.assertEqual(unified.delivery_for_evaluation(f.case,f.verifier.co._status(f.case),f.evaluation)["detail_preservation"],"uncertain")
        stale=self.detail_spec("pass");stale["detail"]["review_id"]="stale";stale["predecessor_hash"]=first["content_hash"]
        with self.assertRaises(ValueError):unified.import_detail(f.case,stale)
        uncertain=self.detail_spec("unknown");uncertain["detail"]["review_id"]="nd4";uncertain["predecessor_hash"]=rejected["content_hash"]
        uncertain["resolves_hashes"]=[first["content_hash"],passed["content_hash"],rejected["content_hash"]]
        pending=unified.import_detail(f.case,uncertain)
        self.assertFalse(unified.delivery_for_evaluation(f.case,f.verifier.co._status(f.case),f.evaluation)["pass"])
        resolving=self.detail_spec("pass");resolving["detail"]["review_id"]="nd5";resolving["predecessor_hash"]=pending["content_hash"]
        resolving["resolves_hashes"]=[first["content_hash"],passed["content_hash"],rejected["content_hash"],pending["content_hash"]]
        unified.import_detail(f.case,resolving)
        self.assertTrue(unified.delivery_for_evaluation(f.case,f.verifier.co._status(f.case),f.evaluation)["pass"])
        self.assertEqual(original,(f.case/"unified/detail/j1/nd1.json").read_bytes())

    def test_unknown_later_resolution_requires_new_decision_and_cannot_reuse_old_accept(self):
        f=self.configured(conflict_stage="whole_image");resolution=unified.resolve_holistic(f.case,self.resolution())
        accepted=f.decision(self.facts)
        self.assertEqual(accepted["payload"]["status"],"accepted")
        later=self.resolution("uncertain");later.update(resolution_id="res2",predecessor_hash=resolution["content_hash"])
        unified.resolve_holistic(f.case,later)
        with self.assertRaises(ValueError):f.verifier.select(f.case,dict(selection_id="sel1",version="q1",decision_ids=["z1"],rule_version="first_accepted_generation_order_v1"))
        next_decision=f.decision(self.facts,decision_id="z2",predecessor=dict(decision_id="z1",hash=accepted["content_hash"]))
        self.assertEqual(next_decision["payload"]["status"],"needs_user_review")
