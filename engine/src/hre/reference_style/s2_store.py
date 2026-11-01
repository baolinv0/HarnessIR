"""Small immutable S2 registry layered on the existing locked sample ledger."""
from copy import deepcopy
from hre.models import file_sha256, canonical_json
from .contracts import record, require
from . import coordinator as co

GROUPS=('evidence','snapshots','reports','targets','compiled','submissions','candidate_derivatives',
        'evaluation_versions','candidate_supports','evaluations','facts','feedback','selections','failures')


def registry(state):
    return state['payload'].get('s2', {g:{} for g in GROUPS})


def get(root,state,group,key):
    require(group in GROUPS and key in registry(state)[group], 'unknown S2 record identity')
    entry=registry(state)[group][key]
    value=co._load(root,entry['path'])
    require(value['sample_id']==state['sample_id'] and value['content_hash']==entry['hash'], 'S2 record binding mismatch')
    return value


def by_id(root,state,group,record_id):
    matches=[get(root,state,group,key) for key in registry(state)[group]]
    matches=[value for value in matches if value['record_id']==record_id]
    require(len(matches)==1,'unknown or nonunique registered record ID')
    return matches[0]


def verify(root,state):
    for group,entries in registry(state).items():
        require(group in GROUPS, 'unknown S2 registry group')
        for key in entries:
            value=get(root,state,group,key)
            for asset in value['payload'].get('assets',[]):
                require(file_sha256(co._path(root,asset['path'],True))==asset['sha256'], 'S2 immutable evidence/support asset modified')


def put(root,state,group,key,kind,payload):
    require(key not in registry(state)[group], 'S2 identity already frozen')
    value=record(state['sample_id'],kind,payload)
    if key is None:key=value['record_id']
    path='s2/'+group+'/'+key+'.json'
    co._path(root,path).parent.mkdir(parents=True,exist_ok=True)
    co._immutable_bytes(root,path,canonical_json(value))
    p=deepcopy(state['payload']);p.setdefault('s2',{g:{} for g in GROUPS})
    p['s2'][group][key]={'path':path,'hash':value['content_hash']}
    if group=='targets':p['target_versions'][key]=value['content_hash']
    co._save_state(root,state['sample_id'],p)
    return value
