"""v2 transport/evaluation projections, backed by the existing case journal."""
from pathlib import Path
import json
from .models import file_sha256,sha256_bytes,now
from .storage import CaseStore,read_json,write_json,atomic_write
from .paths import safe_path
from .masks import require,checked_file,validate_mask_probe,encode_edit_mask


def mask_transport(root,request):
    """Build the explicit opt-in transport binding; never dispatches a model."""
    root=Path(root);config=read_json(root/'config.json');spec=config.get('reference_v2',{})
    if spec.get('arm_id')!='G2':return None
    from .prompts import build_context,render_stage
    context=build_context(root,request)
    prompt=json.loads(render_stage('execute',context,case_root=root))['edit_prompt']
    require(prompt==spec['paired_g1']['rendered_prompt'],'paired_g1_mismatch','G1/G2 editor text must match byte for byte')
    proof=validate_mask_probe(root,spec['mask_probe'],spec['executor'],allow_fixture=spec['simulation_only'])
    target=safe_path(root,f'tasks/{request["task_id"]}/attempts/{request["attempt"]:03d}/v2_transport/M.png')
    encode_edit_mask(root,spec['edit_mask'],request['input_assets'][0],proof['mask_encoder'],target)
    return dict(schema_version='mask_transport_v2',request_sha256=request['request_sha256'],executor=spec['executor'],
                input_order=['A','B','M'],input_sha256={'A':request['input_assets'][0]['sha256'],'B':request['input_assets'][1]['sha256'],'M':file_sha256(target)},
                mask_mode=proof['mask_mode'],mask_encoder=proof['mask_encoder'],mask_applies_to='A',
                mask_path=target.relative_to(root).as_posix(),internal_mask_sha256=spec['edit_mask']['sha256'],
                prompt_sha256=sha256_bytes(prompt.encode()),guidance='soft; pixel boundaries are not guaranteed',
                probe_sha256=spec['mask_probe']['sha256'],simulation_only=spec['simulation_only'])


def validate_mask_delivery(root,request,metadata,image_path=None):
    contract=mask_transport(root,request)
    if contract is None:return []
    receipt_ref=metadata.get('mask_delivery')
    require(receipt_ref is not None,'mask_delivery_missing','G2 needs observed exact A/B/mask delivery and raw transport response')
    path=checked_file(root,receipt_ref);receipt=read_json(path)
    req,resp=validate_delivery_receipt(root,contract,receipt,metadata.get('actual_generation_count'),file_sha256(Path(image_path)) if image_path else None)
    from .evidence import _immutable
    from .reference_execution import AUDIT_KIND
    mask=safe_path(Path(root),contract['mask_path'],must_exist=True)
    audit=safe_path(Path(root),f'tasks/{request["task_id"]}/attempts/{request["attempt"]:03d}/mask_delivery_v2.json')
    _immutable(audit,dict(kind=AUDIT_KIND,contract=contract,receipt_ref=receipt_ref,
                        artifacts=[receipt_ref,receipt['transport_request'],receipt['transport_response'],
                                   dict(path=contract['mask_path'],sha256=file_sha256(mask))]))
    return [path,req,resp,mask,audit]


def validate_delivery_receipt(root,contract,receipt,count,output_sha256):
    keys={'schema_version','request_sha256','executor','mask_mode','mask_encoder','input_order','delivered_input_sha256',
          'prompt_sha256','delivered','observer','observed_at','transport_request','transport_response'}
    require(set(receipt)==keys and receipt['schema_version']=='mask_delivery_v2' and receipt['delivered'] is True
            and receipt['observer'],'mask_delivery_invalid','An attributed actual transport receipt is required')
    from datetime import datetime
    try:stamp=datetime.fromisoformat(receipt['observed_at'].replace('Z','+00:00'))
    except (ValueError,TypeError) as exc:
        from .models import HREError
        raise HREError('mask_delivery_invalid','Invalid zoned delivery timestamp') from exc
    require(stamp.tzinfo is not None,'mask_delivery_invalid','Zoned delivery timestamp required')
    for key in ('request_sha256','executor','mask_mode','mask_encoder','input_order','prompt_sha256'):
        require(receipt[key]==contract[key],'mask_delivery_invalid','Delivery changed '+key)
    require(receipt['delivered_input_sha256']==contract['input_sha256'],'mask_delivery_invalid','Delivery image/mask roles or bytes differ')
    req=checked_file(root,receipt['transport_request']);resp=checked_file(root,receipt['transport_response'])
    observed=read_json(req);response=read_json(resp)
    require(all(observed.get(k)==contract[k] for k in ('request_sha256','executor','input_order','input_sha256','mask_mode','mask_encoder','mask_applies_to','prompt_sha256')),
            'mask_delivery_invalid','Actual request differs from the frozen transport contract')
    require(response.get('transport_request_sha256')==file_sha256(req)
            and response.get('actual_generation_count')==count, 'mask_delivery_invalid','Actual response/request/generation count mismatch')
    if output_sha256 is not None:
        require(response.get('output_sha256')==output_sha256,'mask_delivery_invalid','Raw response output differs from downloaded image')
    return req,resp


def evaluate_reference_case(root):
    from .reference_evaluator import evaluate_reference
    root=Path(root);state=CaseStore(root).load();config=read_json(root/'config.json');spec=config.get('reference_v2')
    require(spec is not None,'v2_schema','Select a v2 case')
    candidate=state['candidates'][0] if state['candidates'] else None
    verification=candidate.get('verification') if candidate else None
    geometry=candidate['geometry']['status'] if candidate else 'unknown'
    content=verification['content_preservation'] if verification else 'unknown'
    result=evaluate_reference(*state['inputs'],candidate['asset'] if candidate else None,spec['roi_pairs'],case_root=root,
                              geometry_status=geometry,content_status=content,eval_mask=spec['eval_mask'],task_scope=spec['task_scope'])
    result.update(case_id=state['case_id'],arm_id=spec['arm_id'],state_revision=state['revision'],
                  source_assets=spec['source_assets'],candidate_sha256=candidate['asset']['sha256'] if candidate else None,
                  content_observation_source='workflow verifier; independent blind review still required',
                  workflow_success=state['success'],simulation_only=spec['simulation_only'],real_effect_validated=False)
    from .evidence import _immutable
    path=root/f'evaluation/reference_attributes_v2_rev{state["revision"]}.json';_immutable(path,result)
    write_json(root/'evaluation/reference_attributes_v2.json',dict(path=path.relative_to(root).as_posix(),sha256=file_sha256(path)))
    return result


def v2_status(root):
    root=Path(root);state=CaseStore(root).load();spec=read_json(root/'config.json').get('reference_v2')
    require(spec is not None,'v2_schema','Select a v2 case')
    capability='untested';mode=None;reason=None
    if spec['mask_probe']:
        try:
            proof=validate_mask_probe(root,spec['mask_probe'],spec['executor'],allow_fixture=spec['simulation_only'])
            capability='fixture_only' if proof['probe_env']=='fixture' else 'observed_supported';mode=proof['mask_mode']
        except Exception as exc:capability='invalid';reason=str(exc)
    from .reference_contracts import mask_roi_binding
    return dict(schema_version='reference_status_v2',arm_id=spec['arm_id'],executor=spec['executor'],task_scope=spec['task_scope'],
                mask_roi_binding=mask_roi_binding(root,spec,state['inputs'][0]),
                capability=capability,mask_mode=mode,capability_reason=reason,guidance='soft; no hard pixel guarantee',
                local_mask_eligible=spec['local_mask_eligible'],budget=state['budget'],simulation_only=spec['simulation_only'])
