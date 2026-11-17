"""Independent tick-by-tick exhaustive oracle for tiny terminal examples.

No CP variables, pruning criterion or simulator transitions are used here.
Zero-time moves make robot location irrelevant; every pick, place and wait is
enumerated. This is a deliberately separate small-instance implementation.
"""

from collections import deque
from time import perf_counter


def enumerate_terminal(problem, repair_delay, *, max_states=500000):
    cfg, snap = problem.config, problem.snapshot
    locations = ["LOAD", "OUT", *snap["chambers"]]
    if (cfg.robot.pick_seconds != 1 or cfg.robot.place_seconds != 1
            or any(cfg.robot.travel(a, b) for a in locations for b in locations)
            or snap["robot"]["carrying"]
            or any(v is not None for row in problem.holding.values() for v in row)):
        raise ValueError("Oracle requires unit picks/places, zero moves, no holding bound or payload")
    if problem.scale != 1 or type(repair_delay) is not int or repair_delay < 0:
        raise ValueError("Oracle accepts integer seconds only")
    ids, sources, deadlines, ps, deltas, eligible = [], [], [], [], [], []
    targets = sorted({c for w in cfg.wafers for c in w.route[-1].chambers})
    chamber_cfg = {c.chamber_id: c for c in cfg.chambers}
    for w in cfg.wafers:
        state = snap["wafers"][w.wafer_id]
        if (state["location"] not in snap["chambers"] or state["stage"] != len(w.route)-1
                or state["stage"] < 1 or snap["chambers"][state["location"]]["status"] != "blocked"):
            raise ValueError("Oracle requires each source wafer to have exactly one final process")
        limits = problem.residency[w.wafer_id]
        if limits[-2] is None or limits[-1] is None:
            raise ValueError("Oracle requires finite source and final residency limits")
        ids.append(w.wafer_id)
        sources.append(state["location"])
        deadlines.append(int(state["processing_records"][-1]["end"] - problem.now + limits[-2]))
        ps.append({c: int(chamber_cfg[c].processing_time(w.route[-1].recipe)) for c in w.route[-1].chambers})
        deltas.append(int(limits[-1]))
        eligible.append(set(w.route[-1].chambers))
    if any(snap["chambers"][c]["wafer_id"] is not None for c in targets):
        raise ValueError("Oracle targets must initially be empty")
    n = len(ids)
    # A complete schedule can discard all unnecessary idle gaps. The generic
    # difference-constraint horizon is derived independently with generous slack.
    max_constant = 1 + repair_delay + sum(abs(d) for d in deadlines) + sum(deltas)
    max_constant += sum(sum(row.values()) for row in ps)
    horizon = (10*n+1)*max_constant
    # time, remaining sources bitset, targets (wafer, process end), held (wafer, done), output bitset
    initial = (0, (1 << n)-1, tuple((-1, 0) for _ in targets), (-1, False), 0)
    queue, seen = deque([initial]), {initial}
    started = perf_counter()
    while queue:
        state = queue.popleft()
        t, src, occupied, held, out = state
        if out == (1 << n)-1:
            return {"status": "FEASIBLE", "makespan_seconds": t, "states": len(seen),
                    "seconds": perf_counter()-started}
        if len(seen) >= max_states:
            return {"status": "UNKNOWN", "reason": "enumeration_state_budget", "states": len(seen),
                    "seconds": perf_counter()-started}
        if t >= horizon:
            continue
        candidates = [(t+1, src, occupied, held, out)]  # every integer wait
        if held[0] < 0:
            for i in range(n):
                if src & (1 << i) and t+1 <= deadlines[i]:
                    candidates.append((t+1, src ^ (1 << i), occupied, (i, False), out))
            for k, (i, ready) in enumerate(occupied):
                if i >= 0 and ready <= t and t+1 <= ready+deltas[i]:
                    row = list(occupied)
                    row[k] = (-1, 0)
                    candidates.append((t+1, src, tuple(row), (i, True), out))
        elif held[1]:
            candidates.append((t+1, src, occupied, (-1, False), out | (1 << held[0])))
        else:
            i = held[0]
            for k, chamber in enumerate(targets):
                if (occupied[k][0] < 0 and chamber in eligible[i]
                        and (chamber != problem.failed_chamber or t >= repair_delay)):
                    row = list(occupied)
                    row[k] = (i, t+1+ps[i][chamber])
                    candidates.append((t+1, src, tuple(row), (-1, False), out))
        for candidate in candidates:
            nt, ns, nc, _, _ = candidate
            if any(ns & (1 << i) and nt >= deadlines[i] for i in range(n)):
                continue  # a remaining source still needs one full pickup tick
            if any(i >= 0 and nt >= ready+deltas[i] for i, ready in nc):
                continue
            if candidate not in seen:
                seen.add(candidate)
                queue.append(candidate)
    return {"status": "INFEASIBLE", "states": len(seen), "seconds": perf_counter()-started}
