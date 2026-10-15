"""Short OS-locked transactions; immutable transaction rename is the commit point."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import json
import os
import tempfile
import threading
import time
from .models import HREError, canonical_json, config_hash, file_sha256, now, request_hash, sha256_bytes, validate_schema
from .paths import make_id, safe_path

_locks={}
_guard=threading.Lock()
_local=threading.local()

@contextmanager
def case_lock(case_root:Path):
    root=Path(case_root).absolute();root.mkdir(parents=True,exist_ok=True)
    lockpath=safe_path(root,'case.lock');key=str(root.resolve())
    with _guard:lock=_locks.setdefault(key,threading.RLock())
    with lock:
        held=getattr(_local,'held',{})
        if key in held:
            yield
            return
        with lockpath.open('a+b') as f:
            if os.name=='nt':
                import msvcrt
                f.seek(0,os.SEEK_END)
                if f.tell()==0:f.write(b'\0');f.flush()
                f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_LOCK,1)
            else:
                import fcntl
                fcntl.flock(f.fileno(),fcntl.LOCK_EX)
            held[key]=f;_local.held=held
            try:yield
            finally:
                del held[key]
                if os.name=='nt':
                    f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
                else:fcntl.flock(f.fileno(),fcntl.LOCK_UN)


def _fsync_dir(path):
    if os.name!='nt':
        fd=os.open(str(path),os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
        try:os.fsync(fd)
        finally:os.close(fd)


def atomic_write(path:Path,data:bytes)->None:
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    safe_path(path.parent,path.name)
    fd,tmp=tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        for i in range(6):
            try:os.replace(tmp,path);break
            except PermissionError:
                if os.name!='nt' or i==5:raise
                time.sleep(0.1*(2**i))
        _fsync_dir(path.parent)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def write_json(path:Path,data:dict)->None:
    atomic_write(path,canonical_json(data))


def read_json(path:Path)->dict:
    def pairs(items):
        d={}
        for k,v in items:
            if k in d:raise ValueError(f'Duplicate key {k}')
            d[k]=v
        return d
    def nonfinite(v):raise ValueError(f'Nonfinite JSON number {v}')
    try:
        raw=Path(path).read_bytes()
        if raw.startswith((b'\xef\xbb\xbf',b'\xff\xfe',b'\xfe\xff')):raise ValueError('JSON BOM is forbidden')
        d=json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,parse_constant=nonfinite)
        if not isinstance(d,dict):raise ValueError('JSON root must be an object')
        canonical_json(d)
        return d
    except (ValueError,UnicodeError) as e:raise HREError('invalid_json',f'{path}: {e}') from e


class CaseStore:
    def __init__(self,case_root:Path):self.case_root=Path(case_root).absolute()

    def _path(self,relative,exists=False):return safe_path(self.case_root,relative,exists)

    def _validate_state(self,state,initial=None):
        validate_schema('state',state)
        budget=state['budget'];ledger=budget['ledger']
        if budget['reserved']!=sum(x['status']=='reserved' for x in ledger) or budget['consumed']!=sum(x['charged_count'] for x in ledger):
            raise HREError('protocol_integrity_error','Budget ledger totals differ')
        if len({x['generation_id'] for x in ledger})!=len(ledger):raise HREError('protocol_integrity_error','Duplicate generation ID')
        if initial:
            for key in ('case_id','case_revision','inputs','config_sha256','profile_id','created_at'):
                if state[key]!=initial[key]:raise HREError('protocol_integrity_error',f'Frozen state field changed: {key}')
            if budget['max_generations']!=initial['budget']['max_generations']:raise HREError('protocol_integrity_error','Frozen generation cap changed')
        from .assets import validate_asset
        for asset in state['inputs']:validate_asset(asset,self.case_root)
        pending=state['pending_task']
        if pending:
            req=read_json(self._path(pending['request_path'],True));validate_schema('request',req)
            for key in ('task_id','stage','round','attempt','request_sha256','state_revision_issued'):
                if req[key]!=pending[key]:raise HREError('protocol_integrity_error',f'Pending task identity mismatch: {key}')
            for key in ('case_id','case_revision','config_sha256'):
                if req[key]!=state[key]:raise HREError('protocol_integrity_error',f'Pending task case mismatch: {key}')
            if req['request_sha256']!=request_hash(req):raise HREError('protocol_integrity_error','Pending request bytes/hash mismatch')
        candidates=state['candidates']
        if len({c['candidate_id'] for c in candidates})!=len(candidates):raise HREError('protocol_integrity_error','Duplicate candidate ID')
        for c in candidates:
            validate_asset(c['asset'],self.case_root)
            binding=c['asset']['candidate_binding']
            if c['candidate_id']!=c['asset']['asset_id'] or any(binding[k]!=state[k] for k in ('case_id','case_revision')) or binding['round']!=c['round'] or binding['generation_id']!=c['generation_id']:
                raise HREError('protocol_integrity_error','Candidate identity does not match asset binding')
            a,b=state['inputs']
            hashes={x['role']:x['sha256'] for x in state['inputs']}
            if binding['prediction_sha256']!=hashes['prediction'] or binding['reference_sha256']!=hashes['reference']:
                raise HREError('protocol_integrity_error','Candidate input hashes differ')
            geom=c['geometry']
            if geom['derived_asset']:validate_asset(geom['derived_asset'],self.case_root)
            if geom['report_path']:self._check_file(geom['report_path'],geom['report_sha256'])
        snapshot=state['evidence_snapshot']
        if snapshot:self._check_file(snapshot['path'],snapshot['sha256'])

    def _validate_transition(self,previous,next_state):
        old=previous['budget']['ledger'];new=next_state['budget']['ledger']
        indexed={e['generation_id']:e for e in new}
        if [e['generation_id'] for e in new[:len(old)]]!=[e['generation_id'] for e in old]:raise HREError('protocol_integrity_error','Generation ledger cannot remove or reorder committed entries')
        for entry in old:
            nxt=indexed.get(entry['generation_id'])
            if nxt is None or any(nxt[k]!=entry[k] for k in ('generation_id','task_id','round')):raise HREError('protocol_integrity_error','Generation identity cannot change')
            if entry['status']=='submitted':
                if nxt['status']!='submitted' or nxt['charged_count']<entry['charged_count'] or nxt['submitted_at']!=entry['submitted_at']:raise HREError('protocol_integrity_error','Submitted cost and timestamp are irreversible')
            elif entry['status']=='released_unsubmitted' and nxt['status']!='released_unsubmitted':raise HREError('protocol_integrity_error','Released generation cannot be reused')
            elif entry['status']=='reserved' and nxt['status'] not in ('reserved','submitted','released_unsubmitted'):raise HREError('protocol_integrity_error','Invalid reservation transition')

    def _check_file(self,path,sha):
        p=self._path(path,True)
        if file_sha256(p)!=sha:raise HREError('protocol_integrity_error',f'File hash mismatch: {path}')
        return p

    def _frozen(self):
        freeze=read_json(self._path('freeze.json',True))
        for path,sha in freeze['files'].items():self._check_file(path,sha)
        initial=read_json(self._path('initial_state.json',True))
        config=read_json(self._path('config.json',True))
        if config_hash(config)!=initial['config_sha256'] or config.get('config_sha256')!=initial['config_sha256']:
            raise HREError('protocol_integrity_error','Frozen configuration hash mismatch')
        self._validate_state(initial)
        return initial

    def initialize(self,state:dict)->None:
        with case_lock(self.case_root):
            if self._path('state.json').exists() or self._path('initial_state.json').exists():raise HREError('case_exists','Case already initialized')
            if state['revision']!=0:raise HREError('protocol_integrity_error','Initial revision must be zero')
            self._validate_state(state)
            config=read_json(self._path('config.json',True))
            if config_hash(config)!=state['config_sha256']:raise HREError('protocol_integrity_error','Configuration hash mismatch')
            write_json(self._path('initial_state.json'),state)
            names=['config.json','manifest.json','initial_state.json']
            if 'reference_v2' in config:
                from .reference_contracts import validate_artifacts
                names.extend(validate_artifacts(self.case_root,config['reference_v2']))
            if self._path('input/roi_manifest.json').exists():names.append('input/roi_manifest.json')
            if 'prompt_template_sha256' in config:
                names.append('prompts/manifest.json')
                names.extend('prompts/'+stage+'.j2' for stage in sorted(config['prompt_template_sha256']))
            write_json(self._path('freeze.json'),{'files':{p:file_sha256(self._path(p,True)) for p in names}})
            write_json(self._path('state.json'),state)
            atomic_write(self._path('events.jsonl'),b'')

    def _references(self,tx):
        nxt=tx['next_task']
        if nxt:
            req=read_json(self._path(nxt['request_path'],True));validate_schema('request',req)
            if request_hash(req)!=nxt['request_sha256'] or req['request_sha256']!=nxt['request_sha256']:
                raise HREError('protocol_integrity_error','Task request hash mismatch')
            self._check_file(str(Path(nxt['request_path']).with_name('prompt.txt')).replace('\\','/'),nxt['prompt_sha256'])
            if 'template_source_proof' in nxt:
                from .prompts import dispatch_sources
                if nxt['template_source_proof']!=dispatch_sources(self.case_root,req['stage'],req):raise HREError('protocol_integrity_error','Task template source proof mismatch')
                self._check_file(str(Path(nxt['request_path']).with_name('dispatch.json')).replace('\\','/'),nxt['dispatch_sha256'])
                for source in nxt['template_source_proof']['templates']+nxt['template_source_proof'].get('direct_prompt_files',[]):self._check_file(source['path'],source['sha256'])
            pending=tx['next_state']['pending_task']
            if not pending or pending['request_path']!=nxt['request_path'] or pending['request_sha256']!=nxt['request_sha256']:raise HREError('protocol_integrity_error','Committed task differs from pending task')
        accepted=tx['accepted_submission']
        if accepted:
            if 'reference_v2' in read_json(self._path('config.json',True)) and 'done_sha256' not in accepted:
                raise HREError('protocol_integrity_error','v2 acceptance requires the original done manifest digest')
            if 'done_sha256' in accepted:self._check_file(accepted['done_path'],accepted['done_sha256'])
            self._check_file(accepted['response_path'],accepted['response_sha256'])
            response=read_json(self._path(accepted['response_path'],True));validate_schema('response',response)
            done=read_json(self._path(accepted['done_path'],True));validate_schema('response',done,'#/$defs/done_manifest')
            for key in ('task_id','request_sha256','response_sha256'):
                if done[key]!=accepted[key]:raise HREError('protocol_integrity_error',f'Accepted submission mismatch: {key}')
            for key in ('task_id','attempt','request_sha256'):
                if response[key]!=accepted[key]:raise HREError('protocol_integrity_error',f'Accepted response identity mismatch: {key}')
            for key in ('case_id','case_revision','config_sha256'):
                if response[key]!=tx['next_state'][key]:raise HREError('protocol_integrity_error',f'Accepted response case mismatch: {key}')
            if done['response_file']!=accepted['response_path'] or any(done[key]!=response[key] for key in ('case_id','case_revision','task_id','request_sha256')):raise HREError('protocol_integrity_error','Done response binding mismatch')
            for artifact in done['artifacts']:self._check_file(artifact['path'],artifact['sha256'])

    def _transactions(self,initial):
        current=initial;transactions=[];event_ids=set()
        txdir=self._path('transactions');txdir.mkdir(exist_ok=True)
        paths=sorted(txdir.glob('*.json'))
        required={'tx_id','event_id','previous_revision','next_revision','case_revision','previous_state_sha256','next_state','event','accepted_submission','next_task','committed_at'}
        for path in paths:
            tx=read_json(safe_path(self.case_root,path.relative_to(self.case_root).as_posix(),True))
            if set(tx)!=required or tx['previous_revision']!=current['revision'] or tx['next_revision']!=current['revision']+1 or tx['case_revision']!=initial['case_revision'] or tx['previous_state_sha256']!=sha256_bytes(canonical_json(current)):
                raise HREError('protocol_integrity_error','Transaction gap, conflict, or previous hash mismatch')
            if path.name!=f"{tx['next_revision']:06d}_{tx['tx_id']}.json" or tx['event_id'] in event_ids:
                raise HREError('protocol_integrity_error','Transaction filename or event ID conflict')
            if tx['next_state']['revision']!=tx['next_revision']:raise HREError('protocol_integrity_error','Transaction revision mismatch')
            self._validate_state(tx['next_state'],initial);self._validate_transition(current,tx['next_state']);self._references(tx)
            current=tx['next_state'];transactions.append(tx);event_ids.add(tx['event_id'])
        return current,transactions

    def _project(self,transactions):
        rows=[]
        for tx in transactions:
            rows.append(canonical_json({'event_id':tx['event_id'],'tx_id':tx['tx_id'],'revision':tx['next_revision'],'committed_at':tx['committed_at'],'event':tx['event']}))
            accepted=tx['accepted_submission']
            if accepted:
                folder=f"tasks/{accepted['task_id']}/accepted"
                write_json(self._path(folder+'/submission.json'),accepted)
                atomic_write(self._path(folder+'/response.json'),self._path(accepted['response_path'],True).read_bytes())
        atomic_write(self._path('events.jsonl'),b''.join(row+b'\n' for row in rows))

    def recover(self)->dict:
        with case_lock(self.case_root):
            initial=self._frozen();latest,txs=self._transactions(initial)
            path=self._path('state.json')
            if path.exists():
                state=read_json(path)
                # A stale valid snapshot is permitted only if it exactly occurs on the chain.
                known=[initial]+[tx['next_state'] for tx in txs]
                if state not in known:raise HREError('protocol_integrity_error','State snapshot is outside committed transaction chain')
            write_json(path,latest);self._project(txs)
            return deepcopy(latest)

    def load(self)->dict:
        with case_lock(self.case_root):
            initial=self._frozen();latest,txs=self._transactions(initial)
            state=read_json(self._path('state.json',True))
            if state!=latest:raise HREError('recovery_required','State projection differs from committed transactions; recover required')
            return deepcopy(state)

    def commit(self,next_state:dict,event:dict,expected_revision:int,accepted_submission:dict|None=None,next_task:dict|None=None)->dict:
        with case_lock(self.case_root):
            current=self.load()
            if current['revision']!=expected_revision:raise HREError('revision_conflict',f'Expected {expected_revision}, actual {current["revision"]}')
            nxt=deepcopy(next_state);nxt['revision']=expected_revision+1;nxt['updated_at']=now()
            self._validate_state(nxt,self._frozen());self._validate_transition(current,nxt)
            tx={'tx_id':make_id('tx'),'event_id':make_id('event'),'previous_revision':expected_revision,'next_revision':expected_revision+1,'case_revision':current['case_revision'],'previous_state_sha256':sha256_bytes(canonical_json(current)),'next_state':nxt,'event':deepcopy(event),'accepted_submission':deepcopy(accepted_submission),'next_task':deepcopy(next_task),'committed_at':now()}
            canonical_json(tx);self._references(tx)
            txpath=self._path(f"transactions/{tx['next_revision']:06d}_{tx['tx_id']}.json")
            write_json(txpath,tx) # unique durable commit point
            write_json(self._path('state.json'),nxt)
            _,txs=self._transactions(self._frozen());self._project(txs)
            return deepcopy(nxt)
