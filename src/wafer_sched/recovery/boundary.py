"""Certified monotone search. An UNKNOWN query never moves an infeasible bound."""

from dataclasses import replace
from time import perf_counter

from ..config import seconds
from ..cpsat_solver import SolverOptions
from .model import dimensions
from .solver import solve_recovery


def repair_boundary(problem, options=None, *, total_seconds=60, use_joint_bound=False,
                    on_query=None):
    seconds(total_seconds, "total_seconds")
    options = options or SolverOptions(max_seconds=5)
    started = perf_counter()
    scale = problem.scale
    cap = dimensions(problem)[2]
    history, best = [], None
    low, high = None, None

    def query(tick):
        nonlocal best
        remaining = total_seconds - (perf_counter() - started)
        if remaining <= 0:
            return None
        result = solve_recovery(problem, tick / scale,
            replace(options, max_seconds=min(options.max_seconds, remaining)),
            minimize_makespan=False, use_joint_bound=use_joint_bound)
        history.append({"query_tick": tick, **result.metadata})
        if result.feasible:
            best = result
        if on_query:
            on_query(len(history)-1, result)
        return result

    def finish(status):
        return {"status": status, "ticks_per_second": scale,
                "latest_repair_delay_seconds": low / scale if status == "FINITE" else None,
                "latest_repair_absolute_seconds": problem.now + low / scale if status == "FINITE" else None,
                "verified_feasible_lower_seconds": low / scale if low is not None else None,
                "proven_infeasible_upper_seconds": high / scale if high is not None else None,
                "boundary_error_seconds": (high-low-1)/scale if low is not None and high is not None else None,
                "finite_cap_tick": cap, "history": history,
                "best": best.summary() if best else None,
                "total_seconds": perf_counter()-started,
                "budget_semantics": "solver allocations capped; build/replay overhead included but not interruptible"}

    result = query(0)
    if result is None:
        return finish("UNKNOWN")
    if result.metadata["status"] == "INFEASIBLE":
        return finish("INFEASIBLE_AT_ZERO")
    if not result.feasible:
        return finish("UNKNOWN")
    low = 0
    result = query(cap + 1)
    if result is None:
        return finish("UNKNOWN")
    if result.feasible:
        low = cap + 1
        return finish("UNBOUNDED")
    if result.metadata["status"] != "INFEASIBLE":
        return finish("UNKNOWN")
    high = cap + 1
    while high - low > 1:
        mid = (low + high) // 2
        result = query(mid)
        if result is None:
            return finish("UNKNOWN")
        if result.feasible:
            low = mid
        elif result.metadata["status"] == "INFEASIBLE":
            high = mid
        else:
            return finish("UNKNOWN")
    return finish("FINITE")
