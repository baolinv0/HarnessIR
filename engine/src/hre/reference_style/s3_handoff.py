"""Measured edit handoff and separate caller-attested actual submission receipts."""
from copy import deepcopy
from io import BytesIO
import numpy as np
from PIL import Image, ImageDraw
from hre.models import sha256_bytes, file_sha256, canonical_json
from hre.storage import case_lock
from .contracts import exact, require, digest, content_hash, PRESERVATION, transition
from . import coordinator as co, s2_store as store, s2_stage as stage
from .s2_public import diagnostic_view
from .s2_evidence import code, load_array

NOTICE=('Generate one complete-frame C from original A using B only as the style reference. '
        'The first attachments are A content and B style. All additional labeled PNGs are '
        'localization-only aids, not hard masks, style targets, candidate outputs or permission '
        'to alter structure. They have a separate label/padding canvas; use the original A/B '
        'for appearance. Missing aids mean missing support, not a fabricated region. '
        'Return C without annotation labels, contours or padding. '+PRESERVATION)
ITEM_KEYS=('attachment_id','ordinal','role','purpose','sha256')


def _chain(root,state,compiled_id):
    compiled=store.get(root,state,'compiled',compiled_id);p=compiled['payload']
    from .unified import check_compiled
    check_compiled(root,compiled)
    require(compiled['kind']=='compiled_request' and p['execution_status']=='draft_not_dispatched','not a saved draft')
    versions=store.registry(state)['targets'];latest=max(versions,key=lambda v:int(v[1:]))
    require(p['target_version']==latest,'superseded target draft; compile current targets explicitly')
    target=store.get(root,state,'targets',latest);t=target['payload']
    require(p['target_hash']==p['target_record_hash']==target['content_hash'],'compiled target binding mismatch')
    report=store.get(root,state,'reports',t['report_id']);r=report['payload']
    require(report['content_hash']==t['report_hash'],'target/report binding mismatch')
    snapshot=store.get(root,state,'snapshots',t['snapshot_id'])
    require(t['snapshot_hash']==r['snapshot_hash']==snapshot['content_hash'] and t['snapshot_id']==r['snapshot_id'],'snapshot binding mismatch')
    diagnosis=stage._diagnosis(root,state,t['diagnosis_record_id'],report)
    require(diagnosis['content_hash']==t['diagnosis_hash'],'diagnosis binding mismatch')
    audit=co._load(root,'input_audit.json');public=diagnostic_view(r)
    require(p['input_audit_hash']==r['input_audit_hash']==audit['content_hash'],'compiled input binding mismatch')
    require(p['prompt_hash']==sha256_bytes(p['prompt'].encode('utf-8')) and p['prompt_version'] in ('measured_whole_region_v1','measured_whole_region_feedback_v1','diagnosis_backed_visual_goals_v1','diagnosis_backed_visual_goals_feedback_v1','faithful_diagnosis_goals_v1','faithful_diagnosis_goals_feedback_v1'),'compiled prompt identity mismatch')
    if p['prompt_version'] in ('measured_whole_region_feedback_v1','diagnosis_backed_visual_goals_feedback_v1','faithful_diagnosis_goals_feedback_v1'):
        from .s4_feedback import validate_binding
        validate_binding(root,state,compiled)
    require(p['region_context']==public['regions'] and p['evidence_assets']==r['assets'],'compiled evidence mismatch')
    require(p['covered_target_ids']==[x['target_id'] for x in t['targets']] and p['unsupported_target_ids']==[],'incomplete draft coverage')
    require(p['preservation_requirements']==PRESERVATION and t['preservation_requirements']==PRESERVATION,'preservation mismatch')
    for planned,actual in zip(p['images'],audit['payload']['images']):
        require(all(planned[k]==actual[k] for k in planned),'compiled A/B image binding mismatch')
    require([i['role'] for i in p['images']]==['A','B'],'compiled A/B roles missing or duplicate')
    return compiled,target,report,audit,public


def _aids(root,compiled,target,audit,public,roles=('A','B')):
    require(roles in (('A','B'),('A','B','C')),'unsupported localization roles')
    selected=set()
    for t in target['payload']['targets']:
        m=t['measurement_binding']
        visual=t.get('visual_goal');relation=None if visual is None else visual['relation']
        if relation is not None:selected.update((relation['left_region_id'],relation['right_region_id']))
        elif m is not None and m['kind']=='relation':selected.update((m['left_region_id'],m['right_region_id']))
        elif t['subject_id']!='g0':selected.add(t['subject_id'])
    images={i['role']:i for i in audit['payload']['images']};result=[]
    prefix='s3/localization/'+compiled['record_id'];co._path(root,prefix).mkdir(parents=True,exist_ok=True)
    palette=([255,220,0],[0,220,255],[255,80,180],[80,255,80],[255,130,40],[160,130,255])
    for role in roles:
        require(role in images,'missing localization image role')
        with Image.open(co._path(root,images[role]['derivative_path'],True)) as source:rgb=np.asarray(source).copy()
        regions=[]
        for rid in sorted(selected,key=lambda x:int(x[1:])):
            region=public['regions'][rid]
            if role not in region['support_paths']:continue
            support=region['support_paths'][role];mask=load_array(root,support)
            require(mask.dtype==np.bool_ and list(mask.shape[::-1])==images[role]['oriented_size'],'localization support geometry mismatch')
            if not mask.any():continue
            padded=np.pad(mask,1);interior=mask.copy()
            for dy,dx in ((0,1),(2,1),(1,0),(1,2)):
                interior &= padded[dy:dy+mask.shape[0],dx:dx+mask.shape[1]]
            color=palette[(int(rid[1:])-1)%len(palette)];rgb[mask & ~interior]=color
            regions.append(dict(region_id=rid,semantic_class=region['semantic_class'],contour_rgb=color,
                bbox=region['coverage'][role]['bbox'],support_path=support,support_sha256=file_sha256(co._path(root,support,True))))
        if not regions:continue
        labels=[f'{r["region_id"]} {r["semantic_class"]} bbox={r["bbox"]}' for r in regions]
        legend_width=max(len(label)*7+28 for label in labels)
        canvas=Image.new('RGB',(max(rgb.shape[1]+legend_width,280),max(rgb.shape[0],len(regions)*20)+24),'white')
        canvas.paste(Image.fromarray(rgb),(0,24));draw=ImageDraw.Draw(canvas)
        draw.text((4,5),role+' | LOCALIZATION ONLY - NOT AN OUTPUT',fill='black')
        for n,(region,label) in enumerate(zip(regions,labels)):
            x,y=rgb.shape[1]+6,24+n*20
            draw.rectangle((x,y+2,x+8,y+10),fill=tuple(region['contour_rgb']));draw.text((x+14,y),label,fill='black')
            bx,by,bw,bh=region['bbox']
            if bw>=40 and bh>=16:draw.text((bx+2,by+25),region['region_id'],fill='black',stroke_width=1,stroke_fill='white')
        stream=BytesIO();canvas.save(stream,format='PNG');data=stream.getvalue();path=prefix+'/'+role+'_guide.png'
        destination=co._path(root,path)
        if destination.exists():require(destination.read_bytes()==data,'localization artifact already differs; never overwrite')
        else:co._immutable_bytes(root,path,data)
        result.append(dict(role=role,purpose='localization_only',path=path,sha256=sha256_bytes(data),mime_type='image/png',regions=regions,
            geometry=dict(image_size=images[role]['oriented_size'],canvas_size=list(canvas.size),image_offset=[0,24],resize=None,crop=None)))
    return result


def export_edit(root,compiled_id):
    with case_lock(root):
        state=co._status(root);require(state['payload']['active_attempt'] is None,'pending/unknown attempt must resolve; no retry')
        compiled,target,report,audit,public=_chain(root,state,compiled_id);c=compiled['payload'];t=target['payload']
        aids=_aids(root,compiled,target,audit,public)
        context={k:t[k] for k in ('report_id','report_hash','diagnosis_record_id','diagnosis_hash','snapshot_id','snapshot_hash')}
        context.update(target_version=t['version'],target_hash=target['content_hash'],preservation_requirements=PRESERVATION)
        return co._export_prepared(root,state,audit,context,'edit',prompt=c['prompt']+'\n'+NOTICE,bind_targets=False,
            prompt_version={'measured_whole_region_feedback_v1':'s4_measured_feedback_localization_v1','measured_whole_region_v1':'s3_measured_whole_region_localization_v1',
                            'diagnosis_backed_visual_goals_v1':'s3_diagnosis_backed_visual_goals_v1','diagnosis_backed_visual_goals_feedback_v1':'s4_diagnosis_backed_visual_goals_feedback_v1',
                            'faithful_diagnosis_goals_v1':'s3_faithful_diagnosis_goals_v1','faithful_diagnosis_goals_feedback_v1':'s4_faithful_diagnosis_goals_feedback_v1'}[c['prompt_version']],attachment_aids=aids,
            extra=dict(binding_kind='compiled_edit',compiled_record_id=compiled_id,compiled_record_hash=compiled['content_hash'],
                       compiled_prompt_hash=c['prompt_hash'],submission_status='planned_not_attested'))


def record_submission(root,manifest,prompt_file):
    exact(manifest,('attempt_id','request_hash','prompt_sha256','attachments','provenance'))
    digest(manifest['request_hash']);digest(manifest['prompt_sha256'])
    prompt=co._read_output(prompt_file);require(sha256_bytes(prompt)==manifest['prompt_sha256'],'submitted prompt file hash mismatch')
    require(bool(prompt.decode('utf-8').strip()),'empty submitted prompt')
    require(isinstance(manifest['attachments'],list),'actual attachment list required')
    items=[];data=[];ids=set();ordinals=set()
    for item in manifest['attachments']:
        exact(item,(*ITEM_KEYS,'path'));code(item['attachment_id'],'a');digest(item['sha256'])
        require(type(item['ordinal'])is int and item['ordinal']>0 and item['ordinal'] not in ordinals and item['attachment_id'] not in ids,'duplicate/invalid actual attachment identity')
        require(item['role'] in ('A','B','C') and item['purpose'] in ('content_image','style_reference','candidate_observation','localization_only'),'invalid actual attachment role/purpose')
        raw=co._read_output(item['path']);require(sha256_bytes(raw)==item['sha256'],'actual attached file hash mismatch')
        items.append({k:item[k] for k in ITEM_KEYS});data.append(raw);ids.add(item['attachment_id']);ordinals.add(item['ordinal'])
    provenance=manifest['provenance'];exact(provenance,('origin','provider','conversation_ref','tool_call_ref'))
    require(provenance['provider']=='chatgpt','unsupported submission provider')
    require(all(isinstance(provenance[k],str) and 0<len(provenance[k].strip()) and len(provenance[k])<=10000 for k in ('conversation_ref','tool_call_ref')),'actual dialog/tool refs required')
    with case_lock(root):
        state=co._status(root);attempt=next((a for a in state['payload']['attempts'] if a['attempt_id']==manifest['attempt_id']),None)
        require(attempt is not None,'unknown submitted attempt');request=co._load(root,attempt['request_path'],'request');p=request['payload']
        require(request['content_hash']==manifest['request_hash'] and p.get('binding_kind') in ('compiled_edit','abc_evaluation'),'submission/request binding mismatch')
        require(provenance['origin']==('synthetic_fixture' if state['payload']['purpose']=='protocol_fixture' else 'actual_current_chat'),'submission purpose/origin mismatch')
        identity=dict(attempt_id=manifest['attempt_id'],request_hash=manifest['request_hash'],submitted_prompt_hash=manifest['prompt_sha256'],
                      submitted_attachments=items,provenance=deepcopy(provenance))
        if manifest['attempt_id'] in store.registry(state)['submissions']:
            prior=store.get(root,state,'submissions',manifest['attempt_id'])
            require(all(prior['payload'][k]==v for k,v in identity.items()),'conflicting actual submission replay; never overwrite')
            return prior
        require(state['payload']['active_attempt'] is not None and state['payload']['active_attempt']['attempt_id']==manifest['attempt_id'],'submission is not the active attempt')
        planned=[{k:i[k] for k in ITEM_KEYS} for i in p['planned_attachments']]
        matches=items==planned and manifest['prompt_sha256']==p['prompt_hash']
        prefix='s3/submitted/'+manifest['attempt_id'];co._path(root,prefix).mkdir(parents=True,exist_ok=False);assets=[]
        for name,raw in [('prompt.txt',prompt)]+[(f'attachment_{n}.bin',raw) for n,raw in enumerate(data,1)]:
            path=prefix+'/'+name;co._immutable_bytes(root,path,raw);assets.append({'path':path,'sha256':sha256_bytes(raw)})
        result=store.put(root,state,'submissions',manifest['attempt_id'],'dialog_submission',dict(**identity,assets=assets,
            planned_attachment_manifest_hash=p['planned_attachment_manifest_hash'],planned_prompt_hash=p['prompt_hash'],
            package_status='matches_plan' if matches else 'differs_from_plan',
            provenance_verification='caller_attested_not_remote_authenticated',remote_input_visibility='unknown'))
        if not matches:
            state=co._status(root);payload=deepcopy(state['payload'])
            active=next(a for a in payload['attempts'] if a['attempt_id']==manifest['attempt_id'])
            if active['status']!='response_unknown':active['status']=transition(active['status'],'response_unknown')
            active['unknown_reason']='Actual submitted package differs from planned request; manual reconciliation required.'
            payload['active_attempt']=deepcopy(active);co._save_state(root,state['sample_id'],payload)
        return result


def bound_submission(root,state,request,receipt):
    submission=store.get(root,state,'submissions',request['payload']['attempt_id']);p=submission['payload']
    require(submission['record_id']==receipt['submission_record_id'] and submission['content_hash']==receipt['submission_hash'],'receipt/submission identity mismatch')
    require(p['request_hash']==request['content_hash'] and p['package_status']=='matches_plan','actual package differs; cannot import as the planned request')
    require(all(receipt['provenance'].get(k)==v for k,v in p['provenance'].items()),'receipt/dialog tool attestation mismatch')
    return submission
