from time import perf_counter
import pytest
from ortools.sat.python import cp_model
from wafer_sched.recovery.feedback.capacity import bound
from wafer_sched.recovery.feedback.exact import fixed_query
from wafer_sched.recovery.feedback.grid import construct
from wafer_sched.recovery.terminal_exact import terminal_domain, build
from wafer_sched.recovery.study_data import terminal_case
from wafer_sched.recovery.conflict_evidence import best_bound


@pytest.mark.parametrize("n,seed", [(2, 2), (3, 4), (4, 2), (5, 4), (6, 2), (6, 6)])
def test_necessary_relaxation_and_fixed_queries_against_original(n, seed):
    p, _ = terminal_case(n, seed).prepare()
    domain = terminal_domain(p)
    cap = best_bound(p)["upper_tick"]
    bundle = build(p, domain, cap)
    s = cp_model.CpSolver()
    s.parameters.num_search_workers = 1
    s.parameters.max_time_in_seconds = 15
    st = s.solve(bundle.model)
    assert st in (cp_model.OPTIMAL, cp_model.INFEASIBLE)
    optimum = s.value(bundle.repair_variable) if st == cp_model.OPTIMAL else -1
    relaxed, _ = bound(p, domain, cap, perf_counter() + 5)
    assert optimum <= relaxed <= cap
    for q in {max(0, optimum), optimum + 1}:
        status, plan, checked, _ = fixed_query(p, domain, q, perf_counter() + 6)
        if q <= optimum:
            assert plan and checked["valid"]
        else:
            assert status == "INFEASIBLE" and plan is None


def test_failed_construction_cannot_prove_infeasibility():
    p, _ = terminal_case(4, 4).prepare()
    plan, _ = construct(p, terminal_domain(p), 0, perf_counter() - 1)
    assert plan is None
