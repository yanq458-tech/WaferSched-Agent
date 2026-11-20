"""Independent chamber-disjunction integer program for small recovery suffixes."""

from itertools import combinations, product
from math import prod
from time import perf_counter

from ortools.linear_solver import pywraplp

from ..cpsat_model import ticks
from .replay import replay_recovery


def reference(problem, delay, seconds=10, assignment_limit=256):
    start = perf_counter()
    scale = problem.scale

    def tick(x):
        return ticks(x, scale)

    repair = tick(delay)
    snap, cfg = problem.snapshot, problem.config
    chambers = {c.chamber_id: c for c in cfg.chambers}
    robot = cfg.robot
    pick, place = tick(robot.pick_seconds), tick(robot.place_seconds)
    jobs, domains = [], []
    for w in cfg.wafers:
        state = snap["wafers"][w.wafer_id]
        loc = state["location"]
        active = loc in chambers and snap["chambers"][loc]["status"] == "processing"
        first = state["stage"] + int(active)
        for k in range(first, len(w.route) + 1):
            jobs.append((w, k, k == first, loc))
            domains.append(w.route[k].chambers if k < len(w.route) else ("OUT",))
    count = prod(map(len, domains))
    if count > assignment_limit:
        return {"status": "SIZE_LIMIT", "assignments": count}

    def travel(a, b):
        return tick(robot.travel(a, b))

    places = ["LOAD", "OUT", *chambers]
    max_trip = max(travel(a, b) for a in places for b in places)
    best, closed, tried = None, True, 0
    for destinations in product(*domains):
        remaining = seconds - (perf_counter() - start)
        if remaining <= 0:
            closed = False
            break
        m = pywraplp.Solver.CreateSolver("SCIP")
        m.SetNumThreads(1)
        m.SetSolverSpecificParametersAsString("limits/gap = 0\nlimits/absgap = 0")
        offsets = [
            abs(problem.relative_tick(t))
            for c in snap["chambers"].values()
            for t in [c.get("ready_at")]
            if t is not None
        ]
        offsets.extend(
            abs(problem.relative_tick(rec["end"]))
            for w in snap["wafers"].values()
            for rec in w["processing_records"]
        )
        if snap.get("carrying_since") is not None:
            offsets.append(abs(problem.relative_tick(snap["carrying_since"])))
        durations = [tick(t) for c in cfg.chambers for _, t in c.processing_times]
        limits = [
            tick(t)
            for table in (problem.residency, problem.holding)
            for row in table.values()
            for t in row
            if t is not None
        ]
        # Simple path bound in the difference graph, including the fixed release.
        horizon = (6 * len(jobs) + 3) * (
            1
            + repair
            + max(offsets, default=0)
            + max(durations, default=0)
            + max(limits, default=0)
            + pick
            + place
            + max_trip
        )
        if horizon + max_trip >= 2**48:
            return {"status": "SIZE_LIMIT", "reason": "MILP numeric range"}
        big = horizon + max_trip
        occupied = {c: [] for c in chambers}
        starts, ends, sources, rows, proc = [], [], [], [], []
        max_end = m.IntVar(0, horizon, "Cmax")
        for i, ((w, k, initial, loc), dest) in enumerate(zip(jobs, destinations)):
            wid = w.wafer_id
            carried = initial and loc == "ROBOT"
            source = (
                (snap["robot"]["position"] if carried else loc) if initial else destinations[i - 1]
            )
            u, v, s, e = [m.IntVar(0, horizon, f"{tag}{i}") for tag in "uvse"]
            starts.append(u)
            ends.append(e)
            sources.append(source)
            m.Add(v == u + (0 if carried else pick))
            m.Add(u >= travel(snap["robot"]["position"], source))
            if carried:
                m.Add(u == 0)
            m.Add(s >= v + travel(source, dest))
            m.Add(e == s + place)
            m.Add(max_end >= e)
            if dest == problem.failed_chamber:
                m.Add(s >= repair)
            holding = problem.holding[wid][k]
            if holding is not None:
                origin = problem.relative_tick(snap["carrying_since"]) if carried else v
                m.Add(e <= origin + tick(holding))
            if not initial or loc in chambers:
                if initial:
                    c = snap["chambers"][loc]
                    stamp = (
                        c["ready_at"]
                        if c["status"] == "processing"
                        else snap["wafers"][wid]["processing_records"][-1]["end"]
                    )
                    ready = problem.relative_tick(stamp)
                    occupied[loc].append((0, v))
                    if loc == problem.failed_chamber and getattr(problem, "sealed_finished", False):
                        m.Add(u >= repair)
                else:
                    ready = ends[i - 1] + tick(
                        chambers[source].processing_time(w.route[k - 1].recipe)
                    )
                    occupied[source].append((rows[i - 1][2], v))
                    proc.append((wid, k - 1, source, ends[i - 1], ready))
                m.Add(u >= ready)
                limit = problem.residency[wid][k - 1]
                if limit is not None:
                    m.Add(v <= ready + tick(limit))
            rows.append((u, v, s, e, carried))
        for i, j in combinations(range(len(jobs)), 2):
            order = m.BoolVar("")
            m.Add(starts[j] >= ends[i] + travel(destinations[i], sources[j]) - big * (1 - order))
            m.Add(starts[i] >= ends[j] + travel(destinations[j], sources[i]) - big * order)
        for intervals in occupied.values():
            for (a, b), (c, d) in combinations(intervals, 2):
                order = m.BoolVar("")
                m.Add(c >= b - horizon * (1 - order))
                m.Add(a >= d - horizon * order)
        m.Minimize(max_end)
        remaining = seconds - (perf_counter() - start)
        if remaining <= 0:
            closed = False
            break
        m.SetTimeLimit(max(1, int(1000 * remaining)))
        status = m.Solve()
        tried += 1
        if status == m.INFEASIBLE:
            continue
        closed &= status == m.OPTIMAL
        if status not in (m.FEASIBLE, m.OPTIMAL):
            continue

        def value(var):
            return round(var.solution_value())

        schedule = {
            "ticks_per_second": scale,
            "makespan_tick": max(value(e) for e in ends),
            "transfers": [],
            "processes": [],
        }
        for i, (w, k, _, _) in enumerate(jobs):
            u, v, s, e, carried = rows[i]
            schedule["transfers"].append(
                dict(
                    wafer_id=w.wafer_id,
                    stage=k,
                    source=sources[i],
                    destination=destinations[i],
                    pick_start=value(u),
                    pick_end=value(v),
                    place_start=value(s),
                    place_end=value(e),
                    initially_carried=carried,
                )
            )
        schedule["transfers"].sort(key=lambda row: row["pick_start"])
        for wid, k, chamber, a, b in proc:
            schedule["processes"].append(
                dict(wafer_id=wid, stage=k, chamber=chamber, start=value(a), end=value(b))
            )
        replay = replay_recovery(problem, delay, schedule)
        if not replay["valid"]:
            raise RuntimeError(f"Independent MILP witness failed replay: {replay['errors']}")
        if best is None or schedule["makespan_tick"] < best["makespan_tick"]:
            best = schedule
    status = (
        ("OPTIMAL" if closed else "FEASIBLE") if best else ("INFEASIBLE" if closed else "UNKNOWN")
    )
    return dict(
        status=status,
        assignments=count,
        tried=tried,
        schedule=best,
        verified=best is not None,
        makespan_seconds=best["makespan_tick"] / scale if best else None,
    )


def reference_incident(incident, repair, seconds=10, assignment_limit=256):
    """External incident time, with full replay and the same exact input clock."""
    from fractions import Fraction
    from math import lcm
    from ..config import seconds as nonnegative
    from ..cpsat_model import UnsupportedModel
    from .continuation import BrokenDeadline, delta
    from .dispatch import replay_incident

    nonnegative(repair, "repair")
    try:
        p, prefix = incident.prepare()
        if p is None:
            return dict(
                status="OPTIMAL", verified=True, makespan_seconds=prefix["completion_delay"]
            )
        p.clock_scale = lcm(p.clock_scale, Fraction(str(repair)).denominator)
        p.scale
    except UnsupportedModel as exc:
        return dict(status="UNSUPPORTED", reason=str(exc))
    except BrokenDeadline as exc:
        return dict(status="INFEASIBLE", reason=str(exc))
    delay = max(0, delta(repair, prefix["offset"]))
    out = reference(p, delay, seconds, assignment_limit)
    if out.get("verified"):
        replay = replay_recovery(p, delay, out["schedule"])
        out["witness_repair_delay_seconds"] = repair
        out["makespan_seconds"] += prefix["offset"]
        replay_incident(incident, prefix, out, {"verification": replay})
    return out
