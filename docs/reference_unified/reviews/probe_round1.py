"""Read-only source review probes; synthetic local artifacts, no model calls."""
from pathlib import Path
import sys, json, tempfile
REPO=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(REPO/'engine/src'),str(REPO/'engine/tests'),str(REPO/'engine/tests/reference_style')]
from copy import deepcopy
from hre.reference_core import study,evaluation
from test_reference_study import specification,result_spec,rating_spec

out={}
with tempfile.TemporaryDirectory(prefix='unified-review-') as tmp:
 p=Path(tmp);root=p/'study';spec=specification(p);plan=study.build_study(root,spec);run=plan['payload']['runs'][0]
 result=study.import_result(root,result_spec(plan,run,Path(spec['pairs'][0]['reference'])))
 study.import_rating(root,rating_spec(result,run))
 second=rating_spec(result,run,'rating2','reviewer2');second['relative_to_A']='worse';study.import_rating(root,second)
 out['conflicting_edit_ratings']=study.summarize(root)['runs'][0]
with tempfile.TemporaryDirectory(prefix='unified-review-detail-') as tmp:
 p=Path(tmp);root=p/'study';spec=specification(p);spec['pairs'][0]['evaluation']['semantics']['delivery_requirements']['require_detail_pass']=True
 plan=study.build_study(root,spec);run=plan['payload']['runs'][0]
 result=study.import_result(root,result_spec(plan,run,Path(spec['pairs'][0]['reference'])))
 study.import_rating(root,rating_spec(result,run));out['detail_required']=study.summarize(root)['runs'][0]

# Full style gate using the existing actual synthetic-file fixture.
from test_unified import UnifiedStyleTest
from hre.reference_style import unified
t=UnifiedStyleTest();t.setUp();f=t.f
try:
 original=f.draft
 def reviewed_draft():
  original();unified.freeze_semantics(f.case,t.semantic_spec(prepare=False))
  unified.record_preflight(f.case,dict(semantic_version='u1',planned_size=None,capability_known=False))
  return f.st.compile_targets(f.case,'v1')
 f.draft=reviewed_draft;f.configured_evaluation()
 images=[]
 for role,a in zip(('A','B'),f.audit): images.append(dict(role=role,path=str(f.case/a['derivative_path']),sha256=a['derivative_file_hash']))
 a=f.evaluation['payload']['selected_artifact'];images.append(dict(role='C',path=str(f.case/a['path']),sha256=a['file_hash']))
 axis=dict(reference_status='achieved',relation='closer',direction='synthetic',magnitude='slight',confidence='high',evidence='Synthetic file-bound fixture only.')
 spec=dict(schema_version='hre_holistic_review_v1',review_id='r1',sample_id=f.evaluation['sample_id'],stage='whole_image',predecessor_hash=None,
   images=images,display=dict(method='side_by_side',scale='full frame',color_basis='sRGB fixture',note='Synthetic reviewer probe'),
   reviewer=dict(reviewer_id='reviewer',independence='independent',prior_exposure='Synthetic fixture only.'),
   whole_image={a:deepcopy(axis) for a in evaluation.AXES},preservation={k:dict(status='pass',confidence='high',evidence='Synthetic fixture') for k in evaluation.PROTECTIONS},regions=[],metrics=[],
   conflicts=['Reference endpoint and whole-region interpretation remain unresolved.'])
 for n,stage in enumerate(evaluation.STAGES):
  spec['review_id']='r'+str(n+1);spec['stage']=stage
  record=unified.import_holistic(f.case,deepcopy(spec));spec['predecessor_hash']=record['content_hash'];spec['whole_image']=None;spec['preservation']=None;spec['conflicts']=[]
 facts=f.review.freeze_facts(f.case,f.facts_spec());out['style_unresolved_conflict']=f.decision(facts)['payload']
finally:t.doCleanups()
print(json.dumps(out,indent=2))
