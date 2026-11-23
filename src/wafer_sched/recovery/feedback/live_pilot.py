"""Opt-in single-call DeepSeek tool selection on a finite terminal recovery snapshot."""

import argparse
import json
from pathlib import Path
from time import perf_counter
from typing import Literal

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context
from pydantic import Field, ValidationError
from typing_extensions import TypedDict

from ...langgraph_agent.llm import LLMClient, LLMSettings, LLMUnavailable
from ...langgraph_agent.schemas import ClosedModel, Limits
from ..conflict_evidence import best_bound
from ..continuation import Continuation
from ..dispatch import replay_incident
from ..replay import replay_recovery
from ..terminal_exact import terminal_domain
from . import capacity, exact, grid


class Choice(ClosedModel):
    tool: Literal["construct_at_upper", "cp_sat_at_upper"]
    reason: str = Field(min_length=1, max_length=300)


class State(TypedDict, total=False):
    decision: dict
    result: dict


def run(case, client):
    p, prefix = case.prepare()
    domain = terminal_domain(p) if p is not None else None
    if not domain or len(domain[0]) < 2 or any(
        None in (j.due, j.residence, j.hold_in) for j in domain[0]
    ):
        raise ValueError("Requires a terminal snapshot with finite quality windows")
    cert = best_bound(p)
    if not cert or cert["kind"] != "mandatory_load" or cert["upper_tick"] < 0:
        raise ValueError("Requires a nonnegative certified mandatory-load upper bound")
    upper, feedback = capacity.bound(p, domain, cert["upper_tick"], perf_counter() + 1.5)
    base = dict(route_certificate=cert, capacity_feedback=feedback, scale=p.scale,
                suffix_offset_seconds=prefix["offset"], status="UNKNOWN")
    if upper < 0:
        return {**base, "status": "INFEASIBLE_AT_ZERO"}
    repair = upper / p.scale
    base["upper_seconds"] = prefix["offset"] + repair

    def plan(_):
        context = {
            "task": "Select one local tool to test whether the certified repair upper bound is attainable.",
            "wip": len(domain[0]), "ticks_per_second": p.scale,
            "eligible_terminal_count": len({c for j in domain[0] for c, _ in j.choices}),
            "capacity_solver_feedback": feedback, "verified_incumbent": False,
            "tools": {
                "construct_at_upper": "Fast grid witness construction; failure leaves the boundary open.",
                "cp_sat_at_upper": "Exact fixed-repair feasibility; can exclude this tick but may time out.",
            },
            "tool_seconds": 5, "instruction": "Select exactly one tool and briefly justify in one sentence.",
        }
        try:
            raw, _ = client.call("recovery_tool_selection", context, Choice, 25)
            decision = Choice.model_validate(raw).model_dump()
        except (LLMUnavailable, ValidationError) as error:
            return {"result": {**base, "reason": type(error).__name__}}
        return {"decision": decision}

    def execute(state):
        decision = state["decision"]
        deadline = perf_counter() + 5
        if decision["tool"] == "construct_at_upper":
            schedule, attempts = grid.construct(p, domain, upper, deadline)
            evidence = {"attempts": attempts, "status": "WITNESS" if schedule else "NO_WITNESS"}
        else:
            _, schedule, _, evidence = exact.fixed_query(p, domain, upper, deadline)
        result = {**base, "decision": decision, "tool_feedback": evidence}
        if schedule is not None:
            check = replay_recovery(p, repair, schedule)
            if not check["valid"]:
                raise ValueError("Suffix replay failed")
            result.update(witness_repair_delay_seconds=base["upper_seconds"],
                          makespan_seconds=prefix["offset"] + schedule["makespan_tick"] / p.scale)
            replay_incident(case, prefix, result, {"verification": check})
            result.update(status="FINITE", schedule=schedule, both_replays_passed=True)
        elif evidence["status"] == "INFEASIBLE":
            if upper == 0:
                result.update(status="INFEASIBLE_AT_ZERO", upper_seconds=None)
            else:
                result["upper_seconds"] = prefix["offset"] + (upper - 1) / p.scale
        return {"result": result}

    workflow = StateGraph(State)
    workflow.add_node("plan", plan)
    workflow.add_node("execute", execute)
    workflow.add_edge(START, "plan")
    workflow.add_conditional_edges("plan", lambda s: "execute" if s.get("decision") else END)
    workflow.add_edge("execute", END)
    with tracing_context(enabled=False):
        return workflow.compile().invoke({})["result"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("incident", type=Path)
    parser.add_argument("--out", type=Path, required=True, help="New directory for local evidence")
    parser.add_argument("--live", action="store_true", help="Authorize at most one DeepSeek model request")
    args = parser.parse_args()
    if not args.live:
        parser.error("Network access requires --live")
    case = Continuation.from_dict(json.loads(args.incident.read_bytes()))
    settings = LLMSettings.from_local(Path(".env"), {"max_output_tokens": 160, "timeout_seconds": 25})
    if (not settings.configured or settings.base_url.rstrip("/") not in
            {"https://api.deepseek.com", "https://api.deepseek.com/v1"} or settings.model != "deepseek-flash"):
        parser.error("Requires project-local DeepSeek Flash configuration")
    args.out.mkdir(parents=True, exist_ok=False)
    client = LLMClient(settings, Limits(max_llm_calls=1, max_total_tokens=5000, max_api_usd=0.002),
                       args.out / "llm_calls.jsonl")
    start = perf_counter()
    result = run(case, client)
    result.update(input_file=args.incident.name, wall_seconds=perf_counter()-start, usage=client.totals())
    (args.out / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf8")
    print(json.dumps({k: result.get(k) for k in ("status", "decision", "upper_seconds",
                     "both_replays_passed", "usage")}, ensure_ascii=True))


if __name__ == "__main__":
    main()
