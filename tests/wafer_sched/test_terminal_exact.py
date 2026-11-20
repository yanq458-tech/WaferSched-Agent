from dataclasses import replace
from time import perf_counter

import pytest

from wafer_sched.recovery.conflict_evidence import best_bound
from wafer_sched.recovery.milp_reference import reference_incident
from wafer_sched.recovery.study_data import terminal_case
from wafer_sched.recovery.terminal_exact import (
    last_load_bound,
    solve_terminal,
    terminal_domain,
    verify_workload,
    workload,
)


@pytest.mark.parametrize("count,seed", [(2, 2), (3, 4), (2, 0), (3, 3)])
def test_compact_vs_independent_integer_model(count, seed):
    case = terminal_case(count, seed)
    p, h = case.prepare()
    domain = terminal_domain(p)
    result = solve_terminal(case, p, h, domain, best_bound(p), perf_counter() + 5)
    if result["status"] == "INFEASIBLE_AT_ZERO":
        assert reference_incident(case, 0)["status"] == "INFEASIBLE"
    elif result["status"] == "FINITE":
        rho = result["latest_repair_delay_seconds"]
        assert result["makespan_optimal"]
        assert result["makespan_seconds"] == reference_incident(case, rho)["makespan_seconds"]
        assert reference_incident(case, rho + 1 / p.scale)["status"] == "INFEASIBLE"
    else:
        assert result["status"] == "UNBOUNDED"
        assert reference_incident(case, result["witness_repair_delay_seconds"])["verified"]


@pytest.mark.parametrize("count,seed", [(8, 1), (8, 7), (12, 1), (12, 7)])
def test_deadline_prefix_arithmetic(count, seed):
    p, _ = terminal_case(count, seed).prepare()
    domain = terminal_domain(p)
    cert = workload(domain)
    assert cert["earliest_last_pick_end_tick"] > cert["deadline_tick"]
    assert verify_workload(p, cert)
    assert not verify_workload(p, dict(cert, prior_unloads=0))
    assert not verify_workload(p, dict(cert, wafers=[*cert["wafers"], "missing"]))
    assert not verify_workload(p, dict(cert, targets=cert["targets"][1:]))
    jobs, *times = domain
    assert workload(([replace(j, due=None) for j in jobs], *times)) is None


@pytest.mark.parametrize("count,seed", [(8, 10), (12, 4), (12, 10)])
def test_pending_window_certificate(count, seed):
    from wafer_sched.recovery.terminal_exact import pending_conflict, verify_pending

    case = terminal_case(count, seed)
    p, _ = case.prepare()
    domain = terminal_domain(p)
    cert = pending_conflict(p, domain)
    assert cert["available_sum_tick"] < cert["required_sum_tick"]
    assert verify_pending(p, cert)
    assert not verify_pending(p, dict(cert, required_sum_tick=cert["required_sum_tick"] + 1))
    jobs, *times = domain
    assert pending_conflict(p, ([replace(j, residence=None) for j in jobs], *times)) is None


def test_pending_conflict_checked_by_independently_formulated_scip():
    from wafer_sched.recovery.continuation import Continuation
    from wafer_sched.recovery.terminal_exact import pending_conflict, verify_pending

    raw = terminal_case(3, 3).to_dict()
    for wafer in raw["residency"]:
        raw["residency"][wafer] = [5, 1]
    for chamber in raw["config"]["chambers"]:
        for recipe in chamber["processing_times"]:
            if recipe.startswith("finish"):
                chamber["processing_times"][recipe] = 1.25
    case = Continuation.from_dict(raw)
    p, _ = case.prepare()
    domain = terminal_domain(p)
    assert verify_pending(p, pending_conflict(p, domain))
    assert reference_incident(case, 0)["status"] == "INFEASIBLE"


def test_packing_cut_and_applicability():
    p, _ = terminal_case(12, 2).prepare()
    domain = terminal_domain(p)
    cap = last_load_bound(p, domain)
    assert cap["upper_tick"] < best_bound(p)["upper_tick"] and cap["min_pending"] >= 1
    jobs, *times = domain
    assert last_load_bound(p, ([replace(j, due=None) for j in jobs], *times)) is None
    from wafer_sched.recovery.continuation import Continuation

    raw = terminal_case(4, 2).to_dict()
    raw["config"]["chambers"][-1]["processing_times"]["finish0"] = 0.125
    raw["config"]["wafers"][0]["route"][-1]["chambers"].append(raw["config"]["chambers"][-1]["id"])
    outside, _ = Continuation.from_dict(raw).prepare()
    assert terminal_domain(outside) is None


@pytest.mark.parametrize("seed", [2, 6])
def test_zero_feasibility_without_packing_matches_scip(seed):
    from ortools.sat.python import cp_model
    from wafer_sched.recovery.terminal_exact import build_zero

    case = terminal_case(2, seed)
    p, _ = case.prepare()
    bundle = build_zero(p, terminal_domain(p))
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    status = solver.solve(bundle.model)
    assert status in (cp_model.OPTIMAL, cp_model.INFEASIBLE)
    ref = reference_incident(case, 0)
    assert solver.status_name(status) == ref["status"]


def test_zero_budget_is_unknown_and_keeps_upper():
    case = terminal_case(8, 4)
    p, h = case.prepare()
    result = solve_terminal(case, p, h, terminal_domain(p), best_bound(p), perf_counter())
    assert result["status"] == "UNKNOWN"
    assert not result["verification_valid"] and result["finite_upper_seconds"] is not None
