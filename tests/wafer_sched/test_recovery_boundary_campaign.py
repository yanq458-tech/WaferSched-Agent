from itertools import permutations, product
from time import perf_counter

import pytest

from wafer_sched.recovery.feedback import boundary_campaign as campaign
from wafer_sched.recovery.feedback.frontier_witness import lift
from wafer_sched.recovery.feedback.route_resume import choices
from wafer_sched.recovery.replay import replay_recovery
from wafer_sched.recovery.study_data import terminal_case
from wafer_sched.recovery.terminal_exact import terminal_domain


@pytest.mark.parametrize("seed", [2,4,6])
def test_maximum_per_rank_matches_enumerated_timetables(seed,tmp_path):
    p,_=terminal_case(3,seed).prepare()
    domain=terminal_domain(p)
    n=len(domain[0])
    cap=173
    maxima={}
    for seq in permutations(range(2*n)):
        if any(seq.index(2*j)>seq.index(2*j+1) for j in range(n)):
            continue
        k=max(seq.index(2*j) for j in range(n))
        for cs in product(*[[c for c,_ in j.choices] for j in domain[0]]):
            hit=lift(p,domain,seq,cs,0,cap)
            if hit:
                maxima[k]=max(maxima.get(k,-1),hit[0])
    for k in campaign.slot_query.ranks(domain):
        row,plan=campaign.optimize(p,domain,campaign.node(k,cap),-1,perf_counter()+5,tmp_path)
        assert row["status"] in ("OPTIMAL","INFEASIBLE")
        assert row["branch_upper"]==maxima.get(k,-1)
        if plan:
            assert replay_recovery(p,row["attained"]/p.scale,plan)["valid"]


def test_timeout_and_split_preserve_every_branch(tmp_path):
    p,_=terminal_case(3,4).prepare()
    domain=terminal_domain(p)
    rank=next(iter(campaign.slot_query.ranks(domain)))
    part=campaign.node(rank,100)
    row,plan=campaign.optimize(p,domain,part,0,perf_counter()-1,tmp_path)
    assert row["status"]=="UNKNOWN" and row["branch_upper"]==100 and plan is None
    children=campaign.split(part,domain)
    assert [c["job"] for c in children]==list(range(len(domain[0])))
    for child in children:
        branches=campaign.split(child,domain)
        job=branches[0]["route"][0][0]
        assert {tuple(choices(domain,b["route"])[0][job].choices) for b in branches}=={
            ((c,t),) for c,t in domain[0][job].choices}
        assert all(b["upper"]==100 for b in branches)

