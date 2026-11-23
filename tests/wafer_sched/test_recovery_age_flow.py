from dataclasses import replace
from time import perf_counter

import pytest
from ortools.sat.python import cp_model
from wafer_sched.recovery.feedback import age_flow, age_network, flow_price, slot_query
from wafer_sched.recovery.feedback.branch_probe import restrict
from wafer_sched.recovery.study_data import terminal_case
from wafer_sched.recovery.terminal_exact import terminal_domain
from wafer_sched.recovery.replay import replay_recovery


@pytest.mark.parametrize("size,seed",[(2,2),(3,4),(3,2),(4,4),(5,4)])
def test_flow_relaxes_original_fixed_query(size,seed):
    problem,_=terminal_case(size,seed).prepare()
    dom=terminal_domain(problem)
    for q in (0,6):
        original,_,_=slot_query.query(problem,dom,q,perf_counter()+10)
        enhanced,plan,_=slot_query.query(problem,dom,q,perf_counter()+10,enhanced=True)
        assert original==enhanced and original!="UNKNOWN"
        if plan:
            assert replay_recovery(problem,q/problem.scale,plan)["valid"]
        if q: continue
        model,_=age_flow.build(dom,6)
        bounds,table,_=age_network.matrix(dom,6)
        assert bounds==[(v.domain[0],v.domain[-1]) for v in model.proto.variables]
        normalize=lambda rows:[(sorted((i,c) for i,c in terms if c),a,b) for terms,a,b in rows]
        assert normalize(table)==normalize(flow_price.rows(model.proto))
        proof=flow_price.solve_table(bounds,table,perf_counter()+10)
        if original=="FEASIBLE":
            assert proof["status"]=="UNKNOWN"


def test_rational_certificate_and_bad_weights():
    model=cp_model.CpModel()
    x=model.new_int_var(0,2,"x")
    model.add(x==1)
    model.add(5*x<=4)
    proof=flow_price.price(model,perf_counter()+3)
    assert proof["status"]=="INFEASIBLE"
    assert flow_price.exact_lower(model.proto,proof["prices"],proof["denominator"])==proof["denominator"]
    assert flow_price.exact_lower(model.proto,[0],1)<=0
    with pytest.raises(ValueError):
        flow_price.exact_lower(model.proto,[1.5],1)


def test_restriction_does_not_modify_source_or_accept_an_unknown_route():
    problem,_=terminal_case(3,4).prepare()
    dom=terminal_domain(problem)
    job=next(j for j in dom[0] if len(j.choices)>1)
    c,t=job.choices[0]
    narrowed=restrict(dom,job.wafer,c)
    assert next(j for j in narrowed[0] if j.wafer==job.wafer)==replace(job,choices=((c,t),))
    assert len(job.choices)>1
    with pytest.raises(ValueError):
        restrict(dom,job.wafer,"missing")

