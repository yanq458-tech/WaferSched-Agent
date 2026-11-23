from itertools import permutations, product
import pytest
from ortools.sat.python import cp_model
from wafer_sched.recovery.feedback.gate_projection import build
from wafer_sched.recovery.feedback.frontier_witness import lift
from wafer_sched.recovery.terminal_exact import terminal_domain
from wafer_sched.recovery.study_data import terminal_case


@pytest.mark.parametrize("n,seed",[(2,2),(2,4),(3,2),(3,4),(3,6),(3,8)])
def test_relaxed_optimum_covers_all_legal_orders(n,seed):
    p,_=terminal_case(n,seed).prepare()
    domain=terminal_domain(p)
    cap=255
    attained=-1
    for seq in permutations(range(2*n)):
        if any(seq.index(2*i)>seq.index(2*i+1) for i in range(n)): continue
        for cs in product(*[[c for c,_ in j.choices] for j in domain[0]]):
            hit=lift(p,domain,seq,cs,0,cap)
            if hit: attained=max(attained,hit[0])
    model,q=build(p,domain,0,cap)
    model.maximize(q)
    solver=cp_model.CpSolver()
    solver.parameters.num_search_workers=1
    status=solver.solve(model)
    assert status in (cp_model.INFEASIBLE,cp_model.OPTIMAL)
    assert attained <= (solver.value(q) if status==cp_model.OPTIMAL else -1)


@pytest.mark.parametrize("seed",[2,4])
def test_compact_endpoint_matches_independent_rank_groups(seed):
    from wafer_sched.recovery.feedback.boundary_campaign import node
    from wafer_sched.recovery.feedback.slot_query import ranks
    from wafer_sched.recovery.feedback.upper_campaign import compact
    from wafer_sched.recovery.feedback.upper_review import projection_witness
    from wafer_sched.recovery.solver import read_witness
    p,_=terminal_case(3,seed).prepare()
    domain=terminal_domain(p)
    maxima={}
    hint=None
    for seq in permutations(range(6)):
        if any(seq.index(2*j)>seq.index(2*j+1) for j in range(3)): continue
        k=max(seq.index(i*2) for i in range(3))
        for cs in product(*[[c for c,_ in j.choices] for j in domain[0]]):
            hit=lift(p,domain,seq,cs,0,255)
            if hit:
                maxima[k]=max(maxima.get(k,-1),hit[0])
                hint=hit[1]
                projection_witness(p,domain,hint,hit[0])
    assert hint is not None
    for k in ranks(domain):
        for q in {max(0,maxima.get(k,-1)),maxima.get(k,-1)+1}:
            bundle=compact(p,domain,q,[node(k,256)],hint,3,False)
            solver=cp_model.CpSolver()
            solver.parameters.num_search_workers=1
            status=solver.solve(bundle.model)
            if q>maxima.get(k,-1):
                assert status==cp_model.INFEASIBLE
            else:
                assert status==cp_model.OPTIMAL
                _,check=read_witness(p,bundle,solver,q/p.scale)
                assert check["valid"]

