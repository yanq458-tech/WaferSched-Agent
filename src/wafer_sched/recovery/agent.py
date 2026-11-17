"""Offline LangGraph loop, reusing SkillRegistry and CFAR acceptance.

No LLM client or credentials are loaded. Planner decisions are executed, logged,
and causally depend on the immediately preceding numerical result.
"""

import hashlib
import json
from time import perf_counter
from typing import TypedDict

from ..agent.feedback import FeedbackEvaluator
from ..agent.skills import SkillRegistry
from ..config import seconds
from ..cpsat_solver import SolverOptions
from .bounds import joint_bound
from .model import dimensions
from .solver import solve_recovery


class RecoveryExactSkill:
    name = "RecoveryExactSkill"

    def run(self, problem, repair_delay, options, **kwargs):
        return solve_recovery(problem, repair_delay, options, **kwargs)


class RecoveryPlanner:
    def propose(self, *, phase, low, high, probe, budget, previous_status, joint):
        tick = 0 if phase == "zero" else probe if phase == "probe" else (
            (low+high)//2 if phase == "bisect" else low)
        return {"phase": phase, "query_tick": tick, "max_seconds": budget,
                "minimize_makespan": phase == "optimize", "use_joint_bound": joint,
                "previous_status": previous_status,
                "reason": ("previous UNKNOWN: increase the same query's proof budget" if previous_status == "UNKNOWN"
                           else {"zero": "test immediate repair before boundary search",
                                 "probe": "verified zero-delay solution: test a proved upper probe",
                                 "bisect": "numerical feasibility bracket: choose its midpoint",
                                 "optimize": "boundary certified: minimize makespan at that boundary"}[phase])}


class GraphState(TypedDict, total=False):
    round: int
    terminal: bool


def run_recovery_agent(problem, *, total_seconds=60, initial_seconds=.05,
                       max_query_seconds=5, max_rounds=64, on_query=None):
    from langgraph.graph import END, START, StateGraph
    from langsmith import tracing_context
    for value in (total_seconds, initial_seconds, max_query_seconds):
        seconds(value, "agent budget")
    if max_query_seconds <= 0 or initial_seconds > max_query_seconds or max_rounds < 1:
        raise ValueError("Invalid agent search budgets")
    registry = SkillRegistry()
    registry.skills[RecoveryExactSkill.name] = RecoveryExactSkill()
    evaluator, planner = FeedbackEvaluator(), RecoveryPlanner()
    started = perf_counter()
    certificate = joint_bound(problem)
    cap = dimensions(problem)[2]
    probe = certificate["upper_tick"]+1 if certificate else cap+1
    phase, low, high, budget = "zero", None, None, initial_seconds
    boundary_status, stop_reason = "UNKNOWN", None
    best, last, proposal = None, None, None
    history, signatures, incumbents = [], set(), {}
    digest = hashlib.sha256(json.dumps(problem.to_dict(), sort_keys=True).encode()).hexdigest()

    def plan(state):
        nonlocal proposal, stop_reason
        remaining = total_seconds - (perf_counter()-started)
        if remaining <= 0 or len(history) >= max_rounds or phase == "done":
            stop_reason = stop_reason or ("completed" if phase == "done" else "budget_exhausted")
            return {"terminal": True}
        proposal = registry.invoke("ResearchPlanningSkill", planner, phase=phase, low=low, high=high,
            probe=probe, budget=min(budget, remaining), previous_status=last.metadata["status"] if last else None,
            joint=certificate is not None)
        signature = (proposal["query_tick"], proposal["max_seconds"], proposal["minimize_makespan"])
        if signature in signatures:
            stop_reason = "no_untried_search_budget"
            return {"terminal": True}
        signatures.add(signature)
        return {"terminal": False}

    def execute(state):
        nonlocal last
        last = registry.invoke("RecoveryExactSkill", problem, proposal["query_tick"]/problem.scale,
            SolverOptions(max_seconds=proposal["max_seconds"], log_search=True),
            minimize_makespan=proposal["minimize_makespan"], use_joint_bound=proposal["use_joint_bound"])
        if on_query:
            on_query(len(history), last)
        return {"round": len(history)+1}

    def feedback(state):
        nonlocal phase, low, high, budget, boundary_status, stop_reason, best
        status, tick = last.metadata["status"], proposal["query_tick"]
        accepted = None
        if last.feasible:
            candidate = {"verification": {"valid": True, "complete": True},
                         "config_sha256": digest, "window_seconds": tick,
                         "metrics": {"makespan_seconds": last.metadata["makespan_seconds"]},
                         "wall_seconds": last.metadata["total_seconds"]}
            accepted = evaluator.evaluate(candidate, incumbents.get(tick))
            if accepted["accepted"]:
                incumbents[tick] = candidate
                if best is None or tick >= round(best.metadata["repair_delay_seconds"]*problem.scale):
                    best = last
            if (last.metadata.get("makespan_optimal") and best is not None
                    and tick == round(best.metadata["repair_delay_seconds"]*problem.scale)):
                # A proof upgrade matters even if CFAR's equal-objective cost tie-break rejects it.
                best = last
                accepted["proof_upgrade"] = True
        history.append({"round": len(history)+1, "proposal": dict(proposal),
                        "result": last.metadata, "cfar_acceptance": accepted,
                        "verification_valid": last.replay["valid"] if last.replay else None})
        if status == "UNKNOWN":
            if budget >= max_query_seconds:
                phase, stop_reason = "done", "query_budget_exhausted"
            else:
                budget = min(max_query_seconds, max(.05, budget*4))
            return {}
        if status not in {"OPTIMAL", "FEASIBLE", "INFEASIBLE"}:
            phase, stop_reason = "done", "solver_or_verification_failure"
            return {}
        if phase == "zero":
            if status == "INFEASIBLE":
                boundary_status, phase = "INFEASIBLE_AT_ZERO", "done"
            else:
                low, phase = 0, "probe"
        elif phase == "probe":
            if last.feasible:
                if certificate:
                    phase, stop_reason = "done", "contradiction_with_joint_bound"
                else:
                    boundary_status, low, phase = "UNBOUNDED", tick, "done"
            else:
                high, phase = tick, "bisect"
        elif phase == "bisect":
            if last.feasible:
                low = tick
            else:
                high = tick
        elif phase == "optimize":
            if status == "OPTIMAL":
                phase = "done"
            elif status == "INFEASIBLE":
                phase, stop_reason = "done", "contradiction_with_verified_boundary_witness"
            elif budget < max_query_seconds:
                budget = min(max_query_seconds, max(.05, budget*4))
            else:
                phase, stop_reason = "done", "makespan_proof_budget_exhausted"
        if phase == "bisect" and high-low == 1:
            boundary_status, phase = "FINITE", "optimize"
        return {}

    graph = StateGraph(GraphState)
    graph.add_node("plan", plan)
    graph.add_node("execute", execute)
    graph.add_node("feedback", feedback)
    graph.add_edge(START, "plan")
    graph.add_conditional_edges("plan", lambda s: "end" if s["terminal"] else "execute",
                                {"end": END, "execute": "execute"})
    graph.add_edge("execute", "feedback")
    graph.add_edge("feedback", "plan")
    # Also suppress telemetry when the parent shell has LangSmith tracing enabled.
    with tracing_context(enabled=False):
        graph.compile().invoke({"round": 0}, {"recursion_limit": 3*max_rounds+5})
    return {"status": boundary_status, "stop_reason": stop_reason,
            "latest_repair_delay_seconds": low/problem.scale if boundary_status == "FINITE" else None,
            "latest_repair_absolute_seconds": problem.now+low/problem.scale if boundary_status == "FINITE" else None,
            "verified_feasible_lower_seconds": low/problem.scale if low is not None else None,
            "proven_infeasible_upper_seconds": high/problem.scale if high is not None else None,
            "best": best.summary() if best else None, "history": history, "skill_calls": registry.calls,
            "total_seconds": perf_counter()-started, "mode": "offline_deterministic_langgraph_cfar",
            "llm_calls": 0, "token_usage": None, "api_cost": 0,
            "ppo": "not_applicable: historical policy environment excludes faults and hard residency"}
