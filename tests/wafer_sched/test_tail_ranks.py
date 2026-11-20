from time import perf_counter

import pytest

from wafer_sched.recovery.conflict_evidence import propagated_bounds, verify_bound
from wafer_sched.recovery.continuation import Continuation
from wafer_sched.recovery.milp_reference import reference_incident
from wafer_sched.recovery.replay import replay_recovery
from wafer_sched.recovery.study_data import concurrent_case, terminal_case
from wafer_sched.recovery.tail_ranks import pending_pairs, rank_bound, solve_rank
from wafer_sched.recovery.terminal_exact import terminal_domain


@pytest.mark.parametrize("seed,forced,two_cap", [(2, {"W6", "W11"}, 445), (8, {"W2", "W6"}, 445)])
def test_single_pending_impossible(seed, forced, two_cap):
    p, _ = terminal_case(12, seed).prepare()
    domain = terminal_domain(p)
    cert = rank_bound(p, domain)
    one, two, *rest = cert["branches"]
    assert set(one["forced_pending"]) == forced and one["excluded"]
    assert two["upper_tick"] == two_cap == cert["upper_tick"]
    assert all(b.get("upper_tick", -1) < two_cap for b in rest)
    assert len(pending_pairs(p, domain, cert, two_cap)) >= 2
    assert not pending_pairs(p, domain, cert, two_cap + 1)


def test_joint_four_phase_matching():
    p, _ = terminal_case(8, 4).prepare()
    cert = rank_bound(p, terminal_domain(p))
    (four,) = cert["branches"]
    assert four["pending"] == 4
    assert four["average_upper"] == 218 and cert["upper_tick"] == 210


@pytest.mark.parametrize("count,seed,q", [(2, 2, 0), (2, 2, 97), (3, 4, 0), (3, 4, 101), (3, 6, 0)])
def test_full_rank_partition_matches_independent_scip(count, seed, q):
    case = terminal_case(count, seed)
    p, _ = case.prepare()
    domain = terminal_domain(p)
    plans = []
    for r in range(count - 1, 2 * count - 1):
        plan, row = solve_rank(p, domain, r, q, q, perf_counter() + 10, fixed=True, minimize=True)
        assert row["status"] in {"OPTIMAL", "INFEASIBLE"}
        if plan:
            assert replay_recovery(p, q / p.scale, plan)["valid"]
            plans.append(plan["makespan_tick"] / p.scale)
    ref = reference_incident(case, q / p.scale, seconds=15)
    if plans:
        assert ref["status"] == "OPTIMAL" and min(plans) == ref["makespan_seconds"]
    else:
        assert ref["status"] == "INFEASIBLE"


def test_timeout_is_not_exclusion():
    p, _ = terminal_case(8, 4).prepare()
    plan, row = solve_rank(p, terminal_domain(p), 10, 83, 83, perf_counter() - 1, fixed=True)
    assert plan is None and row["status"] == "UNKNOWN"


def test_propagated_upper_uses_all_required_windows():
    case = concurrent_case(22)
    p, _ = case.prepare()
    cert = min(propagated_bounds(p), key=lambda x: x["upper_tick"])
    assert cert["upper_tick"] / p.scale == 1361.375 and verify_bound(p, cert)
    assert not verify_bound(p, {**cert, "upper_tick": cert["upper_tick"] - 1})
    raw = case.to_dict()
    raw["holding"]["W1"][1] = None
    relaxed, _ = Continuation.from_dict(raw).prepare()
    assert not verify_bound(relaxed, cert)
