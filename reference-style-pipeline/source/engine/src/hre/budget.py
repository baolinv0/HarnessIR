"""Generation accounting. These helpers mutate a transaction's private state only."""
from .models import HREError, now
from .paths import make_id


def validate_budget(budget: dict) -> None:
    entries=budget['ledger']
    if len({e['generation_id'] for e in entries}) != len(entries):
        raise HREError('budget_integrity','Duplicate generation identity')
    if budget['reserved'] != sum(e['status']=='reserved' for e in entries):
        raise HREError('budget_integrity','Reservation count differs from ledger')
    if budget['consumed'] != sum(e['charged_count'] for e in entries):
        raise HREError('budget_integrity','Consumed count differs from ledger')
    for e in entries:
        if (e['status']=='submitted') != (e['charged_count']>=1):
            raise HREError('budget_integrity','Invalid charged entry')


def entry_for(budget: dict, task_id: str) -> dict:
    matches=[e for e in budget['ledger'] if e['task_id']==task_id]
    if len(matches)!=1: raise HREError('unknown_generation','Task has no unique generation reservation')
    return matches[0]


def reserve(budget: dict, task_id: str, round: int) -> str:
    validate_budget(budget)
    existing=[e for e in budget['ledger'] if e['task_id']==task_id]
    if existing:
        if existing[0]['status']=='released_unsubmitted': raise HREError('released_generation','Released task cannot dispatch')
        return existing[0]['generation_id']
    if budget['consumed']+budget['reserved']>=budget['max_generations']:
        raise HREError('budget_exhausted','No generation slot remains')
    gid=make_id('generation')
    budget['ledger'].append(dict(generation_id=gid,task_id=task_id,round=round,status='reserved',charged_count=0,submitted_at=None,outcome='pending'))
    budget['reserved']+=1
    return gid


def submit(budget: dict, task_id: str, count: int=1, submitted_at: str|None=None) -> str:
    """Count is the cumulative observed count for this generation, hence retry-safe."""
    if type(count) is not int or count<1: raise HREError('invalid_count','Generation count must be positive integer')
    validate_budget(budget); e=entry_for(budget,task_id)
    if e['status']=='released_unsubmitted': raise HREError('released_generation','Submission contradicts confirmed release')
    if e['status']=='reserved':
        budget['reserved']-=1; e['status']='submitted';e['submitted_at']=submitted_at or now()
    if count>e['charged_count']:
        budget['consumed']+=count-e['charged_count'];e['charged_count']=count
    validate_budget(budget)
    return e['generation_id']


def release(budget:dict,task_id:str)->None:
    validate_budget(budget);e=entry_for(budget,task_id)
    if e['status']=='submitted':raise HREError('already_submitted','Confirmed submission cannot be released')
    if e['status']=='reserved':budget['reserved']-=1;e['status']='released_unsubmitted';e['outcome']=None
    validate_budget(budget)
