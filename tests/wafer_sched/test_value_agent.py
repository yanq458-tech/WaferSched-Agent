from types import SimpleNamespace

import pytest

from wafer_sched.recovery.feedback import learned_query, value_query
from wafer_sched.recovery.feedback.local_outcomes import compress, estimator, planner


def test_evidence_rewards_distinguish_first_witness_from_one_tick_upper():
    assert value_query.gains(-1, 100, 100) == (3, 0.01)
    assert value_query.gains(-1, 100, 0) == (1, 2)
    assert value_query.gains(50, 100, 51) == (0.02, 2)
    with pytest.raises(ValueError):
        value_query.gains(50, 100, 50)


def test_repeated_snapshot_not_extra_votes():
    row=dict(case="a",goal="find_witness",x=[0]*9,outcome=1,receipts=["WITNESS"])
    other={**row,"case":"b","receipts":["INFEASIBLE"]}
    p1=estimator(compress([row,other]),3)("find_witness",row["x"])
    p2=estimator(compress([row]*30+[other]),3)("find_witness",row["x"])
    assert p1==pytest.approx(p2)
    assert sum(p1)==pytest.approx(1)


def test_real_evidence_changes_query_with_both_actions_available(monkeypatch):
    domain=([SimpleNamespace(choices=[("F",8)])],1,1,1)
    forecasts={"find_witness":[0.65,0.02,0.33],"tighten_upper":[0.35,0.50,0.15]}
    monkeypatch.setattr(planner,"estimator",lambda *_:lambda g,x:forecasts[g])
    pick=planner.selector({"table":[],"neighbors":1})
    q1,e1=pick(domain,"F",-1,100,8,False,set(),[],100)
    q2,e2=pick(domain,"F",15,100,8,False,{0},[],100)
    assert (q1,q2)==(0,100)
    assert len(e1["candidates"])==len(e2["candidates"])==2
    assert e1["objective"]!=e2["objective"]


def test_archive_label_requires_valid_consistent_receipt():
    conflicting=dict(outcome=1,receipts=["WITNESS","INFEASIBLE"],x=[0]*len(learned_query.FEATURES))
    with pytest.raises(ValueError,match="Contradictory"):
        value_query.train([conflicting])
