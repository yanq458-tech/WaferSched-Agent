"""Matched deterministic policies with/without graph execution. No LLM calls."""

from time import perf_counter
from typing import TypedDict
from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context

from ..cpsat_model import UnsupportedModel
from .conflict_evidence import best_bound, verify_bound
from .continuation import BrokenDeadline
from .direct import direct
from .healthy_witness import lift_witness, verified_bypass
from .dispatch import recover


class PolicyState(TypedDict):
    stop: bool


def adaptive(case, budget, graph=False, observe=None, *, try_bypass=True):
    deadline = perf_counter() + budget
    history = []
    probe_trace = []
    best = {"status": "UNKNOWN"}
    try:
        p, prefix = case.prepare()
    except (UnsupportedModel, BrokenDeadline):
        return direct(case, budget)
    if p is None:
        return direct(case, budget)
    cert = best_bound(p)
    if cert and not verify_bound(p, cert):
        raise ValueError("Invalid route certificate")
    upper = prefix["offset"] + cert["upper_tick"] / p.scale if cert else None
    first_delay = upper if upper is not None and upper >= 0 else 0
    stopped = False

    def step(_state):
        nonlocal best, stopped
        left = deadline - perf_counter()
        if left <= 0:
            return {"stop": True}
        if try_bypass and not cert and not history and not probe_trace:
            # Leave the exact fallback its budget if constructive scheduling stalls.
            plan, report = verified_bypass(case, p, prefix, min(deadline, perf_counter() + .12 * budget))
            probe_trace.append({"tool": "healthy_completion", **report})
            if plan is not None:
                best = plan
                if observe:
                    observe(best)
                return {"stop": True}
            left = deadline - perf_counter()
            if left <= 0:
                return {"stop": True}
        if not history:
            amount = min(left, 0.28 * budget)
            result = recover(case, "solve", repair=first_delay, per_query=amount, total=amount)
            history.append(
                dict(
                    tool="fixed_delay",
                    reason="test_certified_upper" if cert else "seek_initial_witness",
                    delay=first_delay,
                    allocation=amount,
                    status=result["status"],
                )
            )
            if result.get("verification_valid"):
                best = dict(result)
                at_cap = upper is not None and first_delay == upper
                stopped = at_cap and bool(result.get("makespan_optimal"))
                best.update(
                    status="FINITE" if at_cap else "UNKNOWN",
                    verified_feasible_lower_seconds=first_delay,
                    latest_repair_delay_seconds=upper if at_cap else None,
                    finite_upper_seconds=upper,
                )
            elif first_delay == 0 and result["status"] == "INFEASIBLE":
                best = dict(status="INFEASIBLE_AT_ZERO")
                stopped = True
        elif best.get("status") == "FINITE":
            trial = recover(case, "solve", repair=first_delay, per_query=left, total=left)
            history.append(
                dict(
                    tool="minimize_at_proved_boundary",
                    reason="upper_witness_not_makespan_optimal",
                    allocation=left,
                    status=trial["status"],
                )
            )
            if (
                trial.get("verification_valid")
                and trial["makespan_seconds"] <= best["makespan_seconds"]
            ):
                best.update(trial)
                best["status"] = "FINITE"
            stopped = True
        else:
            feedback = history[-1]["status"]
            result = direct(case, max(0, left), incumbent=best)
            history.append(
                dict(
                    tool="maximize_repair",
                    reason=f"fixed_delay_returned_{feedback}",
                    allocation=left,
                    status=result["status"],
                    verified_hint=result.get("incumbent_hint", False),
                )
            )
            old = best
            best = result
            if old.get("verification_valid") and not result.get("verification_valid"):
                if result["status"] == "INFEASIBLE_AT_ZERO":
                    raise RuntimeError("Contradiction with verified initial witness")
                best = {
                    **result,
                    **old,
                    "finite_upper_seconds": result.get("finite_upper_seconds", upper),
                }
            stopped = True
        if try_bypass and not cert and best.get('status') == 'UNKNOWN' and best.get('verification_valid'):
            lifted = lift_witness(case, p, prefix, best)
            if lifted:
                best, evidence = lifted
                history.append(evidence)
                stopped = True
        if observe:
            observe(best)
        return {"stop": stopped}

    if graph:
        flow = StateGraph(PolicyState)
        flow.add_node("solve_and_assess_feedback", step)
        flow.add_edge(START, "solve_and_assess_feedback")
        flow.add_conditional_edges(
            "solve_and_assess_feedback", lambda s: END if s["stop"] else "solve_and_assess_feedback"
        )
        with tracing_context(enabled=False):
            flow.compile().invoke({"stop": False})
    else:
        while not step({})["stop"]:
            pass
    if cert:
        best["certificate"] = cert
    best["policy_trace"] = [*probe_trace, *history]
    return best
