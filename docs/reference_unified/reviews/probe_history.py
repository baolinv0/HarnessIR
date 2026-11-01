"""Synthetic local same-candidate history probe; no model calls."""
from pathlib import Path
import sys,tempfile,json
from copy import deepcopy
R=Path(__file__).resolve().parents[3];sys.path[:0]=[str(R/'engine/src'),str(R/'engine/tests')]
from test_v3_reference_v2 import make,run
from hre.v3.runner import import_candidate_review
from hre.v3.common import digest
with tempfile.TemporaryDirectory() as tmp:
 root,w=make(Path(tmp),policy='feedback',generations=3)
 def residual(v,count):
  if count==1:
   v.update(verdict='revise',issues=[],task_progress='unchanged')
   v['target_results'][0].update(status='partial',suggested_correction='Reduce synthetic residual cast')
 w.mutate_verify=residual;state=run(root,w);c=state['candidates'][0]
 verification=deepcopy(c['verification']);verification.pop('whole_image_review',None)
 review=dict(candidate_id=c['candidate_id'],round=c['round'],native_sha256=c['native']['sha256'],delivered_sha256=c['delivered']['sha256'],
   predecessor_sha256=digest(c['verification_versions'][-1]),whole_image_review=deepcopy(c['whole_image_review']),verification=verification)
 changed=import_candidate_review(root,review)
 out=dict(before=dict(status=state['status'],success=state['success'],selected=state['selected_candidate_id'],round=state['round']),
   after=dict(status=changed['status'],success=changed['success'],selected=changed['selected_candidate_id'],round=changed['round'],phase=changed['phase']))
 final=run(root,w);out['resumed']=dict(status=final['status'],success=final['success'],terminal_reason=final.get('terminal_reason'),generations=final['budget']['generations'])
 print(json.dumps(out,indent=2))
