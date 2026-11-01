import pytest


def test_budget_reservation_submission_idempotence_and_known_extras():
    from hre.budget import reserve, submit, validate_budget, release
    b = dict(max_generations=3,reserved=0,consumed=0,ledger=[])
    g = reserve(b,'task_1',0)
    assert (b['reserved'],b['consumed']) == (1,0)
    assert submit(b,'task_1',1) == g
    submit(b,'task_1',1)
    assert (b['reserved'],b['consumed']) == (0,1)
    submit(b,'task_1',3)
    assert b['consumed']==3
    validate_budget(b)
    with pytest.raises(Exception): reserve(b,'task_2',1)
    g = reserve(dict(max_generations=1,reserved=0,consumed=0,ledger=[]),'task_x',0)
    assert g.startswith('generation_')


def test_release_keeps_audit_and_budget_sum_rejects_corruption():
    from hre.budget import reserve, release, validate_budget
    b = dict(max_generations=1,reserved=0,consumed=0,ledger=[])
    reserve(b,'t',0)
    release(b,'t')
    assert b['ledger'][0]['status']=='released_unsubmitted'
    assert b['reserved']==0
    b['consumed']=1
    with pytest.raises(Exception): validate_budget(b)
