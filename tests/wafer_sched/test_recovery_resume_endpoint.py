from time import perf_counter
from itertools import permutations, product

import pytest

from wafer_sched.recovery.feedback.frontier_witness import timing
from wafer_sched.recovery.feedback.resume_endpoint import age_proof, leaf, query
from wafer_sched.recovery.replay import replay_recovery
from wafer_sched.recovery.study_data import terminal_case
from wafer_sched.recovery.terminal_exact import terminal_domain


@pytest.mark.parametrize("n,seed,q", [(2,2,0),(3,4,15),(3,6,30),(3,4,200)])
def test_scoped_cuts_against_all_orders(n,seed,q):
    problem,_=terminal_case(n,seed).prepare()
    domain=terminal_domain(problem)
    jobs,P,L,d=domain
    valid=set()
    for sequence in permutations(range(2*n)):
        if any(sequence.index(i*2)>sequence.index(i*2+1) for i in range(n)):
            continue
        k=max(sequence.index(i*2) for i in range(n))
        for chambers in product(*[[c for c,_ in job.choices] for job in jobs]):
            if timing(problem,domain,sequence,chambers,q) is not None:
                valid.add((k,sequence[k]//2))
    from wafer_sched.recovery.feedback.slot_query import ranks
    for k in ranks(domain):
        for i in range(n):
            row,plan=leaf(problem,domain,q,k,i,perf_counter()+4)
            assert row["status"]!="UNKNOWN"
            assert (plan is not None)==((k,i) in valid)
            if plan:
                assert replay_recovery(problem,q/problem.scale,plan)["valid"]
                proof=age_proof(problem,domain,q,k,i,P+L+2*d,perf_counter()+5)
                assert proof["status"]!="INFEASIBLE"


def test_exclusions_only_reused_for_later_repair():
    p,_=terminal_case(3,4).prepare()
    domain=terminal_domain(p)
    scope=dict(floor_tick=10,remaining=[[4,1]])
    with pytest.raises(ValueError):
        query(p,domain,9,scope,perf_counter()+1)
    assert query(p,domain,10,scope,perf_counter()-1)==("UNKNOWN",None,[])

