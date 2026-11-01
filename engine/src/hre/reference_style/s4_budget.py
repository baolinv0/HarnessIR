"""Finite local export reservations, not control over external chat actions."""
from copy import deepcopy
from hre.storage import case_lock
from .contracts import exact,require,digest,transition
from .s2_evidence import code
from . import coordinator as co

KINDS=('edit_attempts','diagnostics','feedback_rounds','total')


def configure_budget(root,spec):
    exact(spec,('version',*KINDS));code(spec['version'],'b')
    require(all(type(spec[k])is int and 0<=spec[k]<=1_000_000 for k in KINDS),'finite nonnegative integer budgets required')
    with case_lock(root):
        state=co._status(root);p=deepcopy(state['payload'])
        require(not p['attempts'] and p.get('budget') is None,'budget frozen before first reservation; no silent expansion')
        p['budget']={'config':deepcopy(spec),'basis':'explicit_local_export_limits','used':{k:0 for k in KINDS},'reservations':[]}
        return co._save_state(root,state['sample_id'],p)


def reserve(root,state,kind,reservation_id):
    """Caller holds lock. Persist reservation before any dispatchable artifacts."""
    require(kind in KINDS[:-1],'unsupported budget category');p=deepcopy(state['payload'])
    if p.get('budget') is None:
        require(p['purpose']=='protocol_fixture','real run budget unconfigured; explicit limits required')
        p['budget']={'config':{'version':'b1',**{k:1000 for k in KINDS}},
            'basis':'synthetic_protocol_fixture_only_v1','used':{k:0 for k in KINDS},'reservations':[]}
    b=p['budget'];require(all(r['reservation_id']!=reservation_id for r in b['reservations']),'budget identity already reserved')
    require(b['used'][kind]<b['config'][kind] and b['used']['total']<b['config']['total'],'budget_exhausted; old receipts may still resolve')
    b['used'][kind]+=1;b['used']['total']+=1
    b['reservations'].append({'reservation_id':reservation_id,'kind':kind,'ordinal':b['used']['total'],'refund':'never_automatic'})
    return co._save_state(root,state['sample_id'],p)


def record_failure(root,spec):
    """Explicit terminal provider evidence only; unknown/timeout is never inferred failed."""
    from hre.models import sha256_bytes
    from . import s2_store as store
    exact(spec,('attempt_id','request_hash','reason_code','artifact_path','artifact_sha256','origin','tool_call_ref'))
    digest(spec['request_hash']);digest(spec['artifact_sha256'])
    require(spec['reason_code']=='terminal_provider_error','unknown/timeout cannot be reclassified as terminal failure')
    require(isinstance(spec['tool_call_ref'],str) and spec['tool_call_ref'].strip(),'actual terminal tool reference required')
    raw=co._read_output(spec['artifact_path']);require(sha256_bytes(raw)==spec['artifact_sha256'],'terminal error artifact hash mismatch')
    with case_lock(root):
        state=co._status(root);attempt=next((a for a in state['payload']['attempts'] if a['attempt_id']==spec['attempt_id']),None)
        require(attempt is not None and attempt['request_hash']==spec['request_hash'],'terminal failure/request mismatch')
        require(spec['origin']==('synthetic_fixture' if state['payload']['purpose']=='protocol_fixture' else 'actual_current_chat'),'failure origin/purpose mismatch')
        if spec['attempt_id'] in store.registry(state)['failures']:
            result=store.get(root,state,'failures',spec['attempt_id']);require(result['payload']['receipt']==spec,'conflicting terminal failure replay')
            if attempt['status']=='failed':return result
        else:
            require(attempt['status'] in ('waiting_for_response','response_unknown') and state['payload']['active_attempt']['attempt_id']==spec['attempt_id'],'not a pending terminal error')
            prefix='s4/failures/'+spec['attempt_id'];co._path(root,prefix).mkdir(parents=True,exist_ok=False)
            path=prefix+'/terminal_error.bin';co._immutable_bytes(root,path,raw)
            result=store.put(root,state,'failures',spec['attempt_id'],'terminal_failure',dict(receipt=deepcopy(spec),assets=[{'path':path,'sha256':sha256_bytes(raw)}],provenance_verification='caller_attested_terminal_provider_artifact'))
            state=co._status(root)
        p=deepcopy(state['payload']);attempt=next(a for a in p['attempts'] if a['attempt_id']==spec['attempt_id'])
        require(p['active_attempt'] is not None and p['active_attempt']['attempt_id']==spec['attempt_id'],'failure reconciliation cannot consume another attempt')
        attempt['status']=transition(attempt['status'],'failed');attempt['terminal_failure_hash']=result['content_hash'];p['active_attempt']=None
        co._save_state(root,state['sample_id'],p);return result
