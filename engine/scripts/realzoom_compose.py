"""Compose only issued roles that do not require missing auxiliary evidence."""
import json
from realzoom_flow import ROOT,BATCH,prepare,scan
from realzoom_visual_diagnoses import OBS
from hir_manual.service import Controller
from hir_manual.storage import read_json,write_json,now

ctl=Controller(ROOT);rows=prepare()['images'];review=[]
for row in rows:
    cid=row['cases']['harness'];req=ctl.current_task(cid)
    if not req or req.role!='compose':continue
    # Read actual issued task context before composing. A missing planned tool
    # cannot be waived by this helper to make an experiment look completed.
    if req.context.get('unavailable_tools') or req.context.get('evidence'):raise ValueError('Additional actual evidence review required')
    diagnostic=req.context['diagnosis'];o=OBS[row['sample_id'].rsplit('_',1)[1]]
    assert diagnostic['content']==o[0] and not diagnostic['tool_plan']
    instruction=('Restore this original photograph conservatively. '+o[0]+' '+o[1]+' '+o[4]+' '
        'Apply only mild source-supported cleanup to visible noise or softness. Retain real material texture, lighting, colour and photographic character. '
        'Do not hallucinate high-frequency detail, replace patterns, guess semantic identity, change geometry, add/remove objects, or introduce halos and plastic surfaces. '
        'Return exactly one photograph with the same full field of view, framing and aspect ratio.')
    payload=dict(task_type='conservative_source_supported_long_focal_length_restoration',treat=[o[1]],preserve=[o[4]],region_notes=[dict(region=o[2],anchor='visual',issue=o[1],action='protect',directive=o[4])],evidence_used=['Original visually inspected in current Work; no auxiliary tool was justified by this individual diagnosis; T4 excluded by user'],instruction=instruction)
    out=BATCH/'compositions'/f"{row['sample_id']}.json";write_json(out,payload)
    model='GPT-6.1 Sol 轻度（当前本地 Work 实际看图）'
    result=ctl.import_json(cid,req.task_id,json.dumps(payload,ensure_ascii=False),model,ctl.provenance(model,'file','local_work','01a1307e-d7af-7ec1-948d-239bfd73fa89'))
    if not result.accepted:raise ValueError(result.message)
    review.append(dict(sample_id=row['sample_id'],case_id=cid,composer_task_id=req.task_id,actual_view_scope='current Work individually observed original; no model evidence required',reviewed_at=now()))
    write_json(BATCH/'composition_reviews.json',review)
    print(row['sample_id']+' Composer validated',flush=True)
scan()
