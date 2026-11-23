from time import perf_counter

import pytest
from ortools.sat.python import cp_model
from wafer_sched.recovery.feedback import slot_query
from wafer_sched.recovery.feedback.checked_replay import CheckedIncident
from wafer_sched.recovery.continuation import Continuation
from wafer_sched.recovery.conflict_evidence import best_bound
from wafer_sched.recovery.dispatch import replay_incident
from wafer_sched.recovery.replay import replay_recovery
from wafer_sched.recovery.study_data import terminal_case
from wafer_sched.recovery.terminal_exact import build, terminal_domain
from wafer_sched.verification import validate_state


@pytest.mark.parametrize("size,seed",[(2,2),(3,2),(3,4),(3,6),(4,2),(4,4),(5,4)])
def test_partition_completeness_and_witness(size,seed):
    case=terminal_case(size,seed)
    p,h=case.prepare()
    domain=terminal_domain(p)
    cap=best_bound(p)["upper_tick"]
    full=build(p,domain,cap)
    s=cp_model.CpSolver()
    s.parameters.num_search_workers=1
    st=s.solve(full.model)
    assert st in (cp_model.OPTIMAL,cp_model.INFEASIBLE)
    optimum=s.value(full.repair_variable) if st==cp_model.OPTIMAL else -1
    for q in {0,max(optimum,0),optimum+1}:
        status,plan,trace=slot_query.query(p,domain,q,perf_counter()+15)
        assert (status=="FEASIBLE")==bool(plan)
        if q>optimum:
            assert status=="INFEASIBLE"
            assert [t["last"] for t in trace]==list(slot_query.ranks(domain))
        else:
            assert status=="FEASIBLE"
            for kind in (Continuation,CheckedIncident):
                inc=kind(**{k:getattr(case,k) for k in Continuation.__dataclass_fields__})
                suffix,h=inc.prepare()
                v=replay_recovery(suffix,q/suffix.scale,plan)
                assert v["valid"],v["errors"]
                report=dict(witness_repair_delay_seconds=h["offset"]+q/suffix.scale,
                            makespan_seconds=h["offset"]+plan["makespan_tick"]/suffix.scale)
                replay_incident(inc,h,report,dict(verification=v))
                assert len(report["completed_at"])==size


def test_no_partition_completed_is_unknown():
    case=terminal_case(3,4)
    p,_=case.prepare()
    assert slot_query.query(p,terminal_domain(p),0,perf_counter()-1)==("UNKNOWN",None,[])


def test_past_record_and_resource_corruption_are_detected_with_cache():
    sim=terminal_case(3,4).at_fault()
    state=sim.state
    cache={}
    assert validate_state(state,sim.config,wafer_cache=cache)
    wafer=next(w for w in state.wafers.values() if w.transfer_records)
    wafer.transfer_records[0]["end"]=state.time+1
    result=validate_state(state,sim.config,wafer_cache=cache)
    assert not result and result==validate_state(state,sim.config)
    wafer.transfer_records[0]["end"]=0
    state.chambers[wafer.location].wafer_id=None
    assert not validate_state(state,sim.config,wafer_cache=cache)

