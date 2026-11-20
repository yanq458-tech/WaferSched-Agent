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
from ..short_budget import PreparedIncident
from ..study_policy import adaptive
from . import capacity, exact, grid


class Progress(TypedDict):
    stop: bool


def solve(incident, budget, mode="agent", *, incumbent=None):
    if mode not in {"fixed", "plain", "agent"}:
        raise ValueError(mode)
    start = perf_counter()
    deadline = start + budget
    case = PreparedIncident(**{k: getattr(incident, k) for k in Continuation.__dataclass_fields__})
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
        nonlocal best, lo, hi
        if incumbent:
            plan = incumbent["schedule"]
            keep(plan, round((incumbent["witness_repair"] - offset) * scale))
            trace.append(dict(tool="replay_development_incumbent", lower_tick=lo))
        conflict = terminal_exact.workload(domain) or terminal_exact.pending_conflict(p, domain)
        if conflict:
            if best:
                raise ValueError("Conflict contradicted a witness")
            hi = -1
            trace.append(dict(tool=conflict["kind"], **conflict))
            return {"stop": True}
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
        if mode != "fixed" and not best and not asked:
            trace.append(dict(tool="defer_upper_relaxation", reason="first_seek_zero_feasibility"))
            return {"stop": False}
        relaxed = True
        hi, event = capacity.bound(
            p, domain, hi, min(deadline, perf_counter() + min(1.3, 0.065 * budget))
        )
        trace.append(event)
        if lo > hi:
            raise ValueError("Relaxation contradicted verified schedule")
        return {"stop": hi == lo or perf_counter() >= deadline}

    def next_query():
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

    def probe(_):
        nonlocal lo, hi
        if asked and not relaxed and tighten({})["stop"]:
            return {"stop": True}
        q, reason = next_query()
        left = deadline - perf_counter()
        if q is None or left <= 0:
            return {"stop": True}
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
            st, plan, check, note = exact.fixed_query(p, domain, q, until)
            trace.append(dict(tool="strengthened_fixed_repair", repair_tick=q, **note))
            if plan:
                keep(plan, q, check)
            elif st == "INFEASIBLE":
                hi = min(hi, q - 1)

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
    out = {
        **best,
        "trace": trace,
        "certificate": cert,
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
