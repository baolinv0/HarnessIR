"""Typed observed execution and transitive proof in the accepted artifact journal."""
from pathlib import Path
import json
from datetime import datetime
from .models import file_sha256,sha256_bytes
from .storage import read_json,write_json
from .paths import safe_path,make_id
from .masks import require,checked_file

OBSERVATION_KIND='hre_executor_observation_v2'
AUDIT_KIND='hre_mask_delivery_audit_v2'
OBSERVATION_KEYS={'kind','schema_version','executor','request_sha256','prompt_sha256','input_sha256','output_sha256',
                  'actual_generation_count','observer','observed_at','steps'}


def validate_observation_shape(value):
    from .reference_contracts import validate_executor
    require(isinstance(value,dict) and set(value)==OBSERVATION_KEYS and value['kind']==OBSERVATION_KIND
            and value['schema_version']=='ref_enhance_v2','v2_execution_evidence_missing','Complete observed executor receipt required for every v2 arm')
    validate_executor(value['executor'])
    require(isinstance(value['observer'],str) and value['observer'].strip() and isinstance(value['steps'],list)
            and value['steps'] and all(isinstance(v,str) and v.strip() for v in value['steps']),
            'v2_execution_evidence_missing','Attributed actual execution observations required')
    try:stamp=datetime.fromisoformat(value['observed_at'].replace('Z','+00:00'))
    except (ValueError,TypeError) as exc:
        from .models import HREError
        raise HREError('v2_execution_evidence_missing','Zoned execution observation timestamp required') from exc
    require(stamp.tzinfo is not None,'v2_execution_evidence_missing','Zoned observation timestamp required')


def observation_files(root,request,metadata):
    config=read_json(Path(root)/'config.json')
    if 'reference_v2' not in config:return []
    value=metadata.get('executor_observation');validate_observation_shape(value)
    path=safe_path(Path(root),'assets/v2_observed_execution/'+make_id('observation')+'.json')
    write_json(path,value)
    return [path]


def remap_submission_proofs(root,artifacts,mapping):
    """Only audit projections are remapped. Raw provider request/response stay exact."""
    root=Path(root);receipts=[];audits=[]
    if 'reference_v2' not in read_json(root/'config.json'):return
    for item in artifacts:
        if item['kind']!='auxiliary' or not item['path'].endswith('.json'):continue
        try:value=read_json(safe_path(root,item['path'],must_exist=True))
        except Exception:continue  # Arbitrary raw provider logs are not typed proof projections.
        if value.get('schema_version')=='mask_delivery_v2':receipts.append((item,value))
        elif value.get('kind')==AUDIT_KIND:audits.append((item,value))
    def remap(ref):
        require(ref['path'] in mapping,'v2_execution_evidence_missing','Every proof dependency must be copied into the submission')
        path=mapping[ref['path']]
        return dict(path=path,sha256=file_sha256(safe_path(root,path,must_exist=True)))
    for item,receipt in receipts:
        for key in ('transport_request','transport_response'):receipt[key]=remap(receipt[key])
        write_json(root/item['path'],receipt);item['sha256']=file_sha256(root/item['path'])
    for item,audit in audits:
        audit['receipt_ref']=remap(audit['receipt_ref'])
        audit['artifacts']=[remap(ref) for ref in audit['artifacts']]
        old=audit['contract']['mask_path'];require(old in mapping,'v2_execution_evidence_missing','Actual encoded mask was not committed')
        audit['contract']['mask_path']=mapping[old]
        write_json(root/item['path'],audit);item['sha256']=file_sha256(root/item['path'])


def validate_committed_execution(root,request,response,artifacts):
    root=Path(root);spec=read_json(root/'config.json').get('reference_v2')
    if spec is None:return
    from .reference_runtime import mask_transport,validate_delivery_receipt
    from .prompts import build_context,render_stage
    transport=mask_transport(root,request)
    expected_inputs=transport['input_sha256'] if transport else {k:a['sha256'] for k,a in zip(['A','B'],request['input_assets'])}
    prompt=json.loads(render_stage('execute',build_context(root,request),case_root=root))['edit_prompt']
    typed={OBSERVATION_KIND:[],AUDIT_KIND:[]}
    for item in artifacts.values():
        if item['kind']=='auxiliary' and item['path'].endswith('.json'):
            try:value=read_json(root/item['path'])
            except Exception:continue
            if value.get('kind') in typed:typed[value['kind']].append((item,value))
    require(len(typed[OBSERVATION_KIND])==1,'v2_execution_evidence_missing','Exactly one committed observed executor receipt required')
    observation=typed[OBSERVATION_KIND][0][1];validate_observation_shape(observation);payload=response['payload']
    require(observation['executor']==spec['executor'],'executor_mismatch','Observed full executor/pipeline/adapter/settings differ from frozen control')
    visible=response['model_observed'];e=observation['executor']
    require(visible['ui_model_name']==e['model_display_name'] and visible['transport']==e['transport']
            and visible['exact_model_version']==e['model_exact_version'],'executor_mismatch','Visible model observation contradicts full executor receipt')
    require(observation['request_sha256']==request['request_sha256'] and observation['prompt_sha256']==sha256_bytes(prompt.encode())
            and observation['input_sha256']==expected_inputs and observation['output_sha256']==payload['candidate_asset']['source_file']['sha256']
            and type(observation['actual_generation_count']) is int and observation['actual_generation_count']==payload['actual_generation_count'],
            'executor_mismatch','Observed actual request/input/prompt/raw output/count binding differs')
    if transport is None:
        require(not typed[AUDIT_KIND],'mask_delivery_invalid','G0/G1 must not consume an EDIT_MASK')
        return
    require(len(typed[AUDIT_KIND])==1,'v2_execution_evidence_missing','G2 requires its transitive committed mask delivery graph')
    audit=typed[AUDIT_KIND][0][1]
    require(set(audit)=={'kind','contract','receipt_ref','artifacts'},'mask_delivery_invalid','Unknown delivery audit fields')
    actual_contract=audit['contract']
    require(set(actual_contract)==set(transport) and all(actual_contract[k]==transport[k] for k in transport if k!='mask_path'),
            'mask_delivery_invalid','Committed mask transport differs from frozen request')
    def committed(ref):
        require(ref['path'] in artifacts and artifacts[ref['path']]['sha256']==ref['sha256'],
                'v2_execution_evidence_missing','Every delivery proof dependency must be a committed artifact')
        return checked_file(root,ref)
    receipt=read_json(committed(audit['receipt_ref']))
    dependencies=[audit['receipt_ref'],receipt['transport_request'],receipt['transport_response'],
                  dict(path=actual_contract['mask_path'],sha256=transport['input_sha256']['M'])]
    require(audit['artifacts']==dependencies,'v2_execution_evidence_missing','Incomplete or substituted proof graph')
    for ref in dependencies:committed(ref)
    validate_delivery_receipt(root,transport,receipt,payload['actual_generation_count'],payload['candidate_asset']['source_file']['sha256'])
