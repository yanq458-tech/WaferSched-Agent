"""Evidence-driven solver for large finite terminal suffixes. Ordinary and graph drivers share steps."""

from time import perf_counter
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langsmith import tracing_context

from .. import terminal_exact
from ..conflict_evidence import best_bound
from ..continuation import Continuation
from ..dispatch import replay_incident
from ..replay import replay_recovery
from .replay_state import FeedbackIncident
from ..study_policy import adaptive
from . import capacity, exact, grid, exclusive_check


class Progress(TypedDict):
    stop: bool


def solve(incident, budget, mode="agent", *, incumbent=None, first_probe=None, advisor=None, goal_advisor=None, incident_class=FeedbackIncident, grid_executable=None, query_selector=None, conflict_checker=None):
    if mode not in {"fixed", "plain", "agent"}:
        raise ValueError(mode)
    start = perf_counter()
    deadline = start + budget
    case = incident if type(incident) is incident_class else incident_class(
        **{k: getattr(incident, k) for k in Continuation.__dataclass_fields__})
    from ..continuation import BrokenDeadline
    from ...cpsat_model import UnsupportedModel

    try:
        p, prefix = case.prepare()
    except (BrokenDeadline, UnsupportedModel):
        return adaptive(
            incident, max(0, deadline - perf_counter()), graph=mode == "agent", fast=True
        )
    domain = terminal_exact.terminal_domain(p) if p else None
    cert = best_bound(p) if domain else None
    if (
        not domain
        or len(domain[0]) <= 14
        or not cert
        or cert["upper_tick"] < 0
        or any(None in (j.due, j.residence, j.hold_in) for j in domain[0])
    ):
        return adaptive(
            incident, max(0, deadline - perf_counter()), graph=mode == "agent", fast=True
        )
    jobs, P, L, d = domain
    scale = p.scale
    offset = prefix["offset"]
    short_feedback = budget <= 1 and mode != "fixed"
    conflict_certificate = None
    trace = []
    best = {}
    lo = -1
    hi = cert["upper_tick"]
    asked = set()

    def keep(plan, q, check=None):
        nonlocal best, lo
        # In this domain only placements in F depend on its repair. Replay a lifted witness.
        gate = min(
            (s["place_start"] for s in plan["transfers"] if s["destination"] == p.failed_chamber),
            default=None,
        )
        if gate is None:
            raise ValueError("Mandatory failed load missing")
        if gate < q or gate > hi:
            raise ValueError(("Invalid bound or witness", gate, q, hi))
        if gate < lo or (
            gate == lo
            and best
            and best["best"]["schedule"]["makespan_tick"] <= plan["makespan_tick"]
        ):
            return
        if check is None or gate != q:
            check = replay_recovery(p, gate / scale, plan)
        if not check["valid"]:
            raise ValueError(check["errors"])
        verified = dict(
            schedule=plan, verification={k: v for k, v in check.items() if k != "trace"}
        )
        value = dict(
            verification_valid=True,
            best=verified,
            witness_repair_delay_seconds=offset + gate / scale,
            verified_feasible_lower_seconds=offset + gate / scale,
            makespan_seconds=offset + plan["makespan_tick"] / scale,
        )
        replay_incident(case, prefix, value, verified)
        best, lo = value, gate

    def pilot(_):
        nonlocal best, lo, hi, conflict_certificate
        if incumbent:
            plan = incumbent["schedule"]
            keep(plan, round((incumbent["witness_repair"] - offset) * scale))
            trace.append(dict(tool="replay_development_incumbent", lower_tick=lo))
        conflict = terminal_exact.workload(domain) or terminal_exact.pending_conflict(p, domain)
        if not conflict:
            conflict = next(iter(exclusive_check.certificate(p, domain)), None)
        if conflict:
            if conflict_checker is not None and not conflict_checker(p, conflict):
                raise ValueError("Invalid terminal conflict certificate")
            conflict_certificate = conflict
            if best:
                raise ValueError("Conflict contradicted a witness")
            hi = -1
            trace.append(dict(tool=conflict["kind"], **conflict))
            return {"stop": True}
        if short_feedback:
            trace.append(dict(tool="pilot_feedback", status="ROUTE_UPPER_AVAILABLE",
                              has_witness=bool(best), lower_tick=lo, upper_tick=hi))
            return {"stop": hi == lo or perf_counter() >= deadline}
        result = terminal_exact.solve_terminal(
            case, p, prefix, domain, cert, min(deadline, start + 0.15 * budget)
        )
        if result is None:
            raise ValueError("Unsupported terminal horizon")
        trace.extend(result["trace"])
        if result["status"] == "INFEASIBLE_AT_ZERO":
            if best:
                raise ValueError("Inconsistent zero-repair result")
            hi = -1
        elif result.get("verification_valid"):
            q = round((result["witness_repair_delay_seconds"] - offset) * scale)
            if q > lo or (q == lo and result["makespan_seconds"] < best["makespan_seconds"]):
                lo = q
                best = result.copy()
        if result.get("finite_upper_seconds") is not None:
            hi = min(hi, round((result["finite_upper_seconds"] - offset) * scale))
        trace.append(
            dict(
                tool="pilot_feedback",
                status=result["status"],
                has_witness=bool(best),
                lower_tick=lo,
                upper_tick=hi,
            )
        )
        if lo > hi:
            raise ValueError("Pilot bounds crossed")
        return {"stop": hi <= lo or perf_counter() >= deadline}

    relaxed = False

    def tighten(_):
        nonlocal hi, relaxed
        if short_feedback and not asked:
            trace.append(dict(tool="defer_upper_relaxation", reason="try_existing_cap_before_model_build"))
            return {"stop": False}
        if mode != "fixed" and not best and not asked:
            trace.append(dict(tool="defer_upper_relaxation", reason="first_seek_zero_feasibility"))
            return {"stop": False}
        relaxed = True
        capacity_start = perf_counter() if goal_advisor is not None else None
        hi, event = capacity.bound(
            p, domain, hi, min(deadline, perf_counter() + min(1.3, 0.065 * budget))
        )
        trace.append(event)
        if goal_advisor is not None:
            goal_advisor.record_local(capacity_start, perf_counter(), None)
        if lo > hi:
            raise ValueError("Relaxation contradicted verified schedule")
        return {"stop": hi == lo or perf_counter() >= deadline}

    def next_query():
        if short_feedback and not asked:
            return hi, "short_budget_certified_upper"
        if mode != "fixed" and lo < 0 and 0 not in asked:
            return 0, "no_verified_witness"
        if hi not in asked:
            return hi, "test_certified_upper"
        if lo < 0 and 0 not in asked:
            return 0, "seek_zero_after_upper"
        mid = (hi + max(lo, 0) + 1) // 2
        if mid not in asked:
            return mid, "probe_open_interval"
        return None, "queries_exhausted"

    def apply_goal(goal, default, until):
        nonlocal hi
        if goal == "tighten_upper":
            last_capacity = next((e for e in reversed(trace) if e["tool"] == "prefix_capacity_relaxation"), {})
            if last_capacity.get("status") != "OPTIMAL":
                before = perf_counter()
                hi, event = capacity.bound(p, domain, hi, min(until, before + 0.45 * max(0, until-before)))
                trace.append({**event, "requested_by": goal})
                if hi < lo:
                    raise ValueError("Goal relaxation contradicted verified schedule")
            q = hi
        elif goal == "find_witness":
            q = max(0, lo+1)
        else:
            return default
        trace.append(dict(tool="execute_advised_goal", goal=goal, repair_tick=q,
                          default_tick=default, lower_tick=lo, upper_tick=hi))
        return q

    def probe(_):
        nonlocal lo, hi
        if asked and not relaxed and tighten({})["stop"]:
            return {"stop": True}
        q, reason = next_query()
        left = deadline - perf_counter()
        if q is None or left <= 0:
            return {"stop": True}
        if query_selector is not None:
            tick, event = query_selector(domain, p.failed_chamber, lo, hi, scale, short_feedback,
                                         asked, trace, q)
            if not 0 <= tick <= hi or tick <= lo or tick in asked:
                raise ValueError("Selector returned an inadmissible query")
            trace.append(event)
            if tick != q:
                reason = "learned_" + event["chosen"]
            q = tick
            left = deadline - perf_counter()
            if left <= 0:
                return {"stop": True}
        exact_first = False
        if advisor is not None:
            suggestion = advisor.poll(lo, hi, asked, deadline)
            if suggestion is not None:
                q, selected = suggestion
                exact_first = selected.tool == "exact"
                reason = "async_deepseek_" + selected.target
        if first_probe is not None and not asked:
            # The optional planner can select a local query; it cannot set a bound.
            options = {"upper": hi, "middle": (hi + max(lo, 0) + 1) // 2}
            if lo < 0:
                options["zero"] = 0
            context = dict(wip=len(jobs), ticks_per_second=scale, lower_tick=lo, upper_tick=hi,
                           options=options, default_tick=q, remaining_seconds=round(left, 3),
                           feedback=trace[-3:])
            choice, event = first_probe(context, deadline)
            trace.append(event)
            left = deadline - perf_counter()
            if left <= 0 or event["outcome"] == "expired":
                return {"stop": True}
            if choice is not None:
                q = options[choice.target]
                exact_first = choice.tool == "exact"
                reason = "deepseek_" + choice.target
        goal = goal_advisor.take(deadline) if goal_advisor is not None else None
        if goal:
            q = apply_goal(goal, q, deadline)
            if lo == hi or perf_counter() >= deadline:
                return {"stop": True}
            left = max(0, deadline - perf_counter())
            reason, exact_first = "advised_" + goal, True
        asked.add(q)
        until = perf_counter() + left * (0.65 if len(asked) == 1 else 0.95)
        trace.append(
            dict(
                tool="choose_second_method",
                policy=mode,
                method="primal_zero_feasibility" if q == 0 else "bound_attainment",
                reason=reason,
                repair_tick=q,
                lower_tick=lo,
                upper_tick=hi,
            )
        )
        plan = None
        if grid_executable and short_feedback and q==hi and not exact_first:
            from .short_retest import grid_hint
            plan=grid_hint(p,domain,q,min(deadline,perf_counter()+0.35*left),grid_executable)
            trace.append(dict(tool="compiled_grid_cover",repair_tick=q,status="WITNESS" if plan else "NO_WITNESS"))
        if plan is None and not exact_first:
            plan, tries = grid.construct(
                p, domain, q, min(until, perf_counter() + min(3, 0.28 * max(0, until - perf_counter())))
            )
            trace.append(
                dict(
                    tool="grid_satisfaction",
                    repair_tick=q,
                    attempts=tries,
                    status="WITNESS" if plan else "NO_WITNESS",
                )
            )
        if plan:
            keep(plan, q)
        elif perf_counter() < until:
            if advisor is not None and not exact_first:
                # The local pilot left an open interval and a constructive probe just failed.
                advisor.on_stall(lo, hi, asked, q, len(jobs), scale, tries, deadline)
            if goal_advisor is not None and not goal:
                goal = goal_advisor.take(until)
                if goal:
                    q = apply_goal(goal, q, until)
                    if lo == hi or perf_counter() >= deadline:
                        return {"stop": True}
                    asked.add(q)
            monitor = goal_advisor or advisor
            local_start = perf_counter() if monitor is not None else None
            if goal == "find_witness":
                st, plan, check, note = exact.fixed_query(p, domain, q, until, seed=1)
            else:
                st, plan, check, note = exact.fixed_query(p, domain, q, until)
            if monitor is not None:
                monitor.record_local(local_start, perf_counter(), q)
            trace.append(dict(tool="strengthened_fixed_repair", repair_tick=q, **note))
            if plan:
                keep(plan, q, check)
            elif st == "INFEASIBLE":
                hi = min(hi, q - 1)
            if goal_advisor is not None:
                goal_advisor.after_query(lo, hi, q, trace, domain, scale, p.failed_chamber, deadline)

        if lo > hi:
            raise ValueError("Fixed-query bounds crossed")
        return {"stop": lo == hi or perf_counter() >= deadline or len(asked) >= 6}

    if mode == "agent":
        g = StateGraph(Progress)
        for name, fn in (("pilot", pilot), ("capacity", tighten), ("probe", probe)):
            g.add_node(name, fn)
        g.add_edge(START, "pilot")
        for source, target in (("pilot", "capacity"), ("capacity", "probe"), ("probe", "probe")):
            g.add_conditional_edges(
                source,
                lambda s: "done" if s["stop"] else "continue",
                {"done": END, "continue": target},
            )
        with tracing_context(enabled=False):
            g.compile().invoke({"stop": False})
    else:
        if not pilot({})["stop"] and not tighten({})["stop"]:
            while not probe({})["stop"]:
                pass
    monitor = goal_advisor or advisor
    if monitor is not None and monitor.event is not None:
        trace.append(monitor.event.copy())
    out = {
        **best,
        "trace": trace,
        "certificate": conflict_certificate or cert,
        "finite_upper_seconds": offset + hi / scale if hi >= 0 else None,
        "status": "INFEASIBLE_AT_ZERO" if hi < 0 else "FINITE" if lo == hi else "UNKNOWN",
        "latest_repair_delay_seconds": offset + hi / scale if lo == hi and hi >= 0 else None,
    }
    if hi == lo and best:
        unavoidable = max(
            (
                hi + L + min(t for c, t in j.choices) + P + d + L
                for j in jobs
                if all(c == p.failed_chamber for c, t in j.choices)
            ),
            default=0,
        )
        out["makespan_optimal"] = (
            bool(best.get("makespan_optimal"))
            or best["best"]["schedule"]["makespan_tick"] == unavoidable
        )
    else:
        out["makespan_optimal"] = False
    return out
