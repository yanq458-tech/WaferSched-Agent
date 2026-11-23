from time import perf_counter

import pytest
from ortools.sat.python import cp_model

from wafer_sched.recovery.feedback import capacity, frontier_witness
from wafer_sched.recovery.feedback.exact import fixed_query
from wafer_sched.recovery.feedback.frontier_replay import FrontierIncident
from wafer_sched.recovery.continuation import Continuation
from wafer_sched.recovery.conflict_evidence import best_bound
from wafer_sched.recovery.dispatch import replay_incident
from wafer_sched.recovery.replay import replay_recovery
from wafer_sched.recovery.study_data import terminal_case
from wafer_sched.recovery.terminal_exact import build, terminal_domain


@pytest.mark.parametrize("n,seed",[(2,2),(3,4),(3,6),(4,2),(4,4),(5,4),(5,6),(6,2)])
def test_prefix_certificates_never_exclude_the_full_optimum(n,seed):
    incident=terminal_case(n,seed)
    p,_=incident.prepare()
    domain=terminal_domain(p)
    cap=best_bound(p)["upper_tick"]
    full=build(p,domain,cap)
    solver=cp_model.CpSolver()
    solver.parameters.num_search_workers=1
    solver.parameters.max_time_in_seconds=12
    st=solver.solve(full.model)
    assert st in (cp_model.OPTIMAL,cp_model.INFEASIBLE)
    opt=solver.value(full.repair_variable) if st==cp_model.OPTIMAL else -1
    for split in (False,True):
        upper,_=capacity.bound(p,domain,cap,perf_counter()+3,endpoints=True,prefix_split=split)
        assert opt<=upper<=cap
        if opt>=0:
            _,result=capacity.bound(p,domain,cap,perf_counter()+3,endpoints=True,prefix_split=split,threshold=opt)
            assert result["status"] in ("OPTIMAL","FEASIBLE")


def test_retimed_witness_survives_both_original_replays():
    incident=terminal_case(3,4)
    compact=FrontierIncident(**{k:getattr(incident,k) for k in Continuation.__dataclass_fields__})
    p,h=compact.prepare()
    domain=terminal_domain(p)
    cap=best_bound(p)["upper_tick"]
    _,plan,_,_=fixed_query(p,domain,0,perf_counter()+5)
    assert plan
    seq,choices=frontier_witness.unpack(domain,plan)
    q,new=frontier_witness.lift(p,domain,seq,choices,0,cap)
    for case in (compact,incident):
        p,h=case.prepare()
        v=replay_recovery(p,q/p.scale,new)
        assert v["valid"] and len(v["decisions"])>0
        replay_incident(case,h,dict(witness_repair_delay_seconds=h["offset"]+q/p.scale,
            makespan_seconds=h["offset"]+new["makespan_tick"]/p.scale),dict(verification=v))
