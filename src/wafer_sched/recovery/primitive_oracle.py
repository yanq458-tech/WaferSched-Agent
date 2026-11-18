"""Tiny-instance shortest path on primitive moves, picks, places and one-tick waits.

No CP model, joint bound, search controller or CP schedule enters the oracle.
Time beyond the observation horizon gives UNKNOWN unless every branch has died.
"""

from fractions import Fraction
from heapq import heappop, heappush
from math import lcm

from ..cpsat_model import time_scale
from .continuation import checks, BrokenDeadline


def enumerate_incident(case, repair, *, horizon=60, max_states=150000):
    sim = case.at_fault()
    fault = sim.state.time
    robot = sim.state.robot
    sim.run_until(max(robot.phase_end if robot.busy else fault, fault + case.dispatch_lag))
    try:
        picks = checks(sim.trace, case.residency, case.holding)
    except BrokenDeadline:
        return {"status": "INFEASIBLE", "states": 0}
    if sim.completed:
        return {"status": "OPTIMAL", "states": 1,
                "makespan_seconds": max(w.completed_at for w in sim.state.wafers.values()) - fault}
    cfg = case.config
    specs = cfg.wafers
    chambers = {c.chamber_id: c for c in cfg.chambers}
    dates = [fault, sim.state.time, repair, *picks.values()]
    rows = []
    for spec in specs:
        w = sim.state.wafers[spec.wafer_id]
        loc, stage = w.location, w.stage
        if loc in chambers:
            c = sim.state.chambers[loc]
            ready = c.ready_at if c.status == "processing" else w.processing_records[-1]["end"]
            stage += int(c.status == "processing")
        else:
            ready = picks.get(spec.wafer_id, fault)
        rows.append((loc, stage, ready))
        dates.append(ready)
        dates.extend(
            v for v in case.residency[spec.wafer_id] + case.holding[spec.wafer_id] if v is not None
        )
    scale = lcm(time_scale(cfg), *(Fraction(str(v)).denominator for v in dates))

    def tick(t):
        x = Fraction(str(t)) * scale
        assert x.denominator == 1
        return int(x)

    state = (
        tick(sim.state.time) - tick(fault),
        robot.position,
        tuple((loc, s, tick(ready) - tick(fault)) for loc, s, ready in rows),
    )
    queue, seen = [state], {state}
    truncated = False
    while queue:
        t, pos, rows = heappop(queue)
        if all(row[0] == "OUT" for row in rows):
            return {"status": "OPTIMAL", "makespan_seconds": t / scale, "states": len(seen)}
        successors = []
        carrying = any(loc == "ROBOT" for loc, _, _ in rows)
        expired = False
        for i, (loc, stage, ready) in enumerate(rows):
            w = specs[i]
            if loc in chambers:
                limit = case.residency[w.wafer_id][stage - 1]
                end = t + tick(cfg.robot.pick_seconds)
                if limit is not None and end > ready + tick(limit):
                    expired = True
                    break
                sealed = (
                    case.policy == "sealed_finished"
                    and loc == case.failed_chamber
                    and t < tick(repair)
                )
                if not carrying and loc == pos and ready <= t and not sealed:
                    successors.append(
                        (end, pos, rows[:i] + (("ROBOT", stage, end),) + rows[i + 1 :])
                    )
            elif loc == "ROBOT":
                limit = case.holding[w.wafer_id][stage]
                end = t + tick(cfg.robot.place_seconds)
                if limit is not None and end > ready + tick(limit):
                    expired = True
                    break
                eligible = w.route[stage].chambers if stage < len(w.route) else ("OUT",)
                if (
                    pos not in eligible
                    or (pos == case.failed_chamber and t < tick(repair))
                    or (pos in chambers and any(r[0] == pos for r in rows))
                ):
                    continue
                if pos == "OUT":
                    new = (pos, stage, 0)
                else:
                    duration = chambers[pos].processing_time(w.route[stage].recipe)
                    new = (pos, stage + 1, end + tick(duration))
                successors.append((end, pos, rows[:i] + (new,) + rows[i + 1 :]))
        if expired:
            continue
        successors.append((t + 1, pos, rows))
        for dest in ("LOAD", "OUT", *chambers):
            if dest != pos:
                successors.append((t + tick(cfg.robot.travel(pos, dest)), dest, rows))
        for step in successors:
            if step[0] > tick(horizon):
                truncated = True
            elif step not in seen:
                seen.add(step)
                heappush(queue, step)
        if len(seen) > max_states:
            return {"status": "UNKNOWN", "reason": "state_budget", "states": len(seen)}
    return {"status": "UNKNOWN" if truncated else "INFEASIBLE", "states": len(seen)}
