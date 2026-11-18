"""Proved necessary workload bound for a deliberately narrow terminal subclass."""

from ..cpsat_model import ticks


def pickup_conflict(problem):
    """All k initially occupied chambers due by d require k complete picks.

    Even with zero travel and immediate readiness, the gripper must place
    k-1 times between picks and once first if it starts loaded.
    """
    scale = problem.scale
    deadlines = []
    for loc, chamber in problem.snapshot["chambers"].items():
        wid = chamber["wafer_id"]
        if wid is None:
            continue
        wafer = problem.snapshot["wafers"][wid]
        active = chamber["status"] == "processing"
        stage = wafer["stage"] if active else wafer["stage"]-1
        limit = problem.residency[wid][stage]
        if limit is None:
            continue
        ready = chamber["ready_at"] if active else wafer["processing_records"][stage]["end"]
        deadlines.append((problem.relative_tick(ready)+ticks(limit, scale), wid))
    loaded = int(problem.snapshot["robot"]["carrying"] is not None)
    robot = problem.config.robot
    ordered = sorted(deadlines)
    for k, (deadline, _) in enumerate(ordered, 1):
        required = k*ticks(robot.pick_seconds, scale)+(k-1+loaded)*ticks(robot.place_seconds, scale)
        if required > deadline:
            return {"required_ticks": required, "deadline_tick": deadline,
                    "wafer_ids": [wid for _, wid in ordered[:k]]}
    return None


def joint_bound(problem):
    """Return None outside ALL checked hypotheses; never prune from a conjecture.

    For r>D, all source wafers must be evacuated before any final processing
    completes. At most m healthy chambers plus one gripper can hold them.
    For n=m+1, if j is held, k healthy removals after loading F need 2k-1
    robot time. Their relaxed deadlines give r <= d_j-1+q_(k)-2k.
    """
    cfg, snap, scale = problem.config, problem.snapshot, problem.scale
    if cfg.robot.pick_seconds != 1 or cfg.robot.place_seconds != 1:
        return None
    locations = ["LOAD", "OUT", *snap["chambers"]]
    if any(cfg.robot.travel(a, b) != 0 for a in locations for b in locations):
        return None
    if snap["robot"]["carrying"]:
        return None
    chambers = {c.chamber_id: c for c in cfg.chambers}
    targets, ds, ps, deltas = None, [], [], []
    for spec in cfg.wafers:
        w = snap["wafers"][spec.wafer_id]
        loc, stage = w["location"], w["stage"]
        if (loc not in chambers or snap["chambers"][loc]["status"] != "blocked"
                or stage != len(spec.route)-1 or stage < 1):
            return None
        step = spec.route[stage]
        eligible = set(step.chambers)
        if targets is None:
            targets = eligible
        if targets != eligible or problem.failed_chamber not in eligible:
            return None
        if any(snap["chambers"][c]["wafer_id"] is not None for c in eligible):
            return None
        d, delta = problem.residency[spec.wafer_id][stage-1:stage+1]
        if d is None or delta is None:
            return None
        deadline = problem.relative_tick(w["processing_records"][-1]["end"]) + ticks(d, scale)
        durations = {ticks(chambers[c].processing_time(step.recipe), scale) for c in eligible}
        if deadline <= 0 or len(durations) != 1 or delta < 1:
            return None
        ds.append(deadline)
        ps.append(durations.pop())
        deltas.append(ticks(delta, scale))
    n, m, D = len(ds), len(targets)-1, max(ds)
    if m < 1 or any(p < D for p in ps) or n < m+1:
        return None
    if n > m+1:
        return {"kind": "evacuation_capacity", "upper_tick": D, "n": n, "m": m,
                "D_tick": D, "proof": "r>D requires n<=m+1 occupied healthy slots/gripper"}
    candidates = []
    for j in range(n):
        qs = sorted(ps[i] + deltas[i] for i in range(n) if i != j)
        candidates.append(min(ds[j] - scale + q - 2*k*scale
                              for k, q in enumerate(qs, 1)))
    return {"kind": "joint_healthy_removal_workload", "upper_tick": max(D, max(candidates)),
            "n": n, "m": m, "D_tick": D, "d_ticks": ds, "p_ticks": ps,
            "delta_ticks": deltas, "per_held_wafer_upper_ticks": candidates,
            "proof": "r>D => r<=min_k(d_j-1+q_(k)^(-j)-2k); disjoin over held j"}


def symmetric_formula(problem):
    certificate = joint_bound(problem)
    if not certificate or certificate["kind"] != "joint_healthy_removal_workload":
        return None
    d, p, delta = (certificate[key] for key in ("d_ticks", "p_ticks", "delta_ticks"))
    scale, m = problem.scale, certificate["m"]
    if (len(set(d)) != 1 or len(set(p)) != 1 or len(set(delta)) != 1
            or d[0] < (2*m+1)*scale
            or any(v is not None for row in problem.holding.values() for v in row)):
        return None
    return (d[0] + p[0] + delta[0] - (2*m+1)*scale) / scale
