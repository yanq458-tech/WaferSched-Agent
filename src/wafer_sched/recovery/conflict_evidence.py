"""Exact two-wafer upper bound, with independently checked disjunction coverage."""

from itertools import product
from ..cpsat_model import ticks


def _facts(p):
    """Suffix with one carried wafer K and one chamber wafer J, one process each."""
    snap, cfg = p.snapshot, p.config
    carried = snap["robot"]["carrying"]
    if not carried or len(cfg.wafers) != 2:
        return None
    k, j = sorted(cfg.wafers, key=lambda w: w.wafer_id != carried)
    wk, wj = (snap["wafers"][w.wafer_id] for w in (k, j))
    source = wj["location"]
    if source not in snap["chambers"] or snap["chambers"][source]["status"] != "blocked":
        return None
    if wk["stage"] != len(k.route) - 1 or wj["stage"] != len(j.route) - 1 or wj["stage"] < 1:
        return None
    ak, aj = k.route[-1], j.route[-1]
    if source in set(ak.chambers) | set(aj.chambers):
        return None
    deadline, residence = p.residency[j.wafer_id][-2], p.residency[k.wafer_id][-1]
    if deadline is None or residence is None:
        return None

    def tick(v):
        return ticks(v, p.scale)

    chambers = {c.chamber_id: c for c in cfg.chambers}
    return dict(
        K=carried,
        J=j.wafer_id,
        S=source,
        F=p.failed_chamber,
        pos=snap["robot"]["position"],
        AK=ak.chambers,
        AJ=aj.chambers,
        D=p.relative_tick(wj["processing_records"][-1]["end"]) + tick(deadline),
        delta=tick(residence),
        P=tick(cfg.robot.pick_seconds),
        L=tick(cfg.robot.place_seconds),
        p={c: tick(chambers[c].processing_time(ak.recipe)) for c in ak.chambers},
        d=lambda a, b: tick(cfg.robot.travel(a, b)),
    )


def chain_bound(problem):
    f = _facts(problem)
    if not f:
        return None
    rows, values = [], []
    for k, j in product(f["AK"], f["AJ"]):
        t = f["d"](k, f["S"]) + f["P"]
        if k == f["F"]:
            kind, val = "repair_before_first_placement", f["D"] - t - f["L"]
        else:
            earliest = f["d"](f["pos"], k) + f["L"] + f["p"][k]
            if earliest <= f["D"]:
                return None
            if j == k:
                kind, val = "destination_still_occupied", None
            elif j == f["F"]:
                kind = "repair_before_second_placement"
                val = f["D"] - t + f["p"][k] + f["delta"] - f["L"] - f["d"](j, k) - f["P"]
            else:
                return None
        rows.append(dict(carried_to=k, other_to=j, reason=kind, upper_tick=val))
        if val is not None:
            values.append(val)
    if not values:
        return None
    return dict(
        kind="two_wafer_repair_chain",
        carried=f["K"],
        other=f["J"],
        deadline_tick=f["D"],
        ticks_per_second=problem.scale,
        branches=rows,
        upper_tick=max(values),
    )


def check_chain(problem, cert):
    """Check all route pairs against primitive inequalities at the first excluded tick."""
    f = _facts(problem)
    if not f or not isinstance(cert, dict):
        return False
    if (
        cert.get("carried"),
        cert.get("other"),
        cert.get("deadline_tick"),
        cert.get("ticks_per_second"),
        cert.get("kind"),
    ) != (f["K"], f["J"], f["D"], problem.scale, "two_wafer_repair_chain"):
        return False
    if type(cert.get("upper_tick")) is not int:
        return False
    pairs = set(product(f["AK"], f["AJ"]))
    bounds = []
    for row in cert.get("branches", []):
        k, j = row.get("carried_to"), row.get("other_to")
        if (k, j) not in pairs:
            return False
        pairs.remove((k, j))
        cap = row.get("upper_tick")
        if k == f["F"]:
            cost = f["L"] + f["d"](k, f["S"]) + f["P"]
            if row.get("reason") != "repair_before_first_placement" or cap != f["D"] - cost:
                return False
        else:
            if f["d"](f["pos"], k) + f["L"] + f["p"][k] <= f["D"]:
                return False
            if j == k:
                if row.get("reason") != "destination_still_occupied" or cap is not None:
                    return False
                continue
            if j != f["F"] or row.get("reason") != "repair_before_second_placement":
                return False
            latest_loaded = f["D"] - f["P"] - f["d"](k, f["S"])
            latest_extracted = latest_loaded + f["p"][k] + f["delta"]
            if type(cap) is not int or cap + f["L"] + f["d"](j, k) + f["P"] != latest_extracted:
                return False
        bounds.append(cap)
    return not pairs and bool(bounds) and max(bounds) == cert["upper_tick"]


def _deadlines(problem):
    for spec in problem.config.wafers:
        wid = spec.wafer_id
        state = problem.snapshot["wafers"][wid]
        loc = state["location"]
        chamber = problem.snapshot["chambers"].get(loc)
        if chamber is None:
            continue
        processing = chamber["status"] == "processing"
        stage = state["stage"] + int(processing)
        limit = problem.residency[wid][stage - 1]
        if limit is None:
            continue
        completion = chamber["ready_at"] if processing else state["processing_records"][-1]["end"]
        deadline = problem.relative_tick(completion) + ticks(limit, problem.scale)
        yield spec, loc, stage, deadline


def deadline_bounds(p):
    """Mandatory release bounds that remain necessary with arbitrary other WIP."""
    for spec, loc, stage, D in _deadlines(p):
        wid = spec.wafer_id
        if loc == p.failed_chamber and getattr(p, "sealed_finished", False):
            cost = ticks(p.config.robot.pick_seconds, p.scale)
            yield dict(kind="sealed_pick", wafer=wid, deadline_tick=D, upper_tick=D - cost)
        if stage < len(spec.route) and set(spec.route[stage].chambers) == {p.failed_chamber}:
            hold = p.holding[wid][stage]
            if hold is not None:
                H = ticks(hold, p.scale)
                L = ticks(p.config.robot.place_seconds, p.scale)
                yield dict(
                    kind="mandatory_load",
                    wafer=wid,
                    deadline_tick=D,
                    holding_tick=H,
                    upper_tick=D + H - L,
                )


def propagated_bounds(p):
    """Propagate latest pick completion through finite holds, processing and residence."""
    scale = p.scale
    chambers = {c.chamber_id: c for c in p.config.chambers}
    place = ticks(p.config.robot.place_seconds, scale)
    for spec, loc, stage, original_due in _deadlines(p):
        wid = spec.wafer_id
        due = original_due
        steps = []
        for k in range(stage, len(spec.route)):
            op = spec.route[k]
            hold = p.holding[wid][k]
            if hold is None:
                break
            hold = ticks(hold, scale)
            if k > stage and set(op.chambers) == {p.failed_chamber}:
                yield dict(
                    kind="propagated_mandatory_load",
                    wafer=wid,
                    start_stage=stage,
                    failed_stage=k,
                    deadline_tick=original_due,
                    steps=list(steps),
                    final_hold_tick=hold,
                    place_tick=place,
                    upper_tick=due + hold - place,
                )
                break
            residence = p.residency[wid][k]
            if residence is None:
                break
            duration = max(
                ticks(chambers[c].processing_time(op.recipe), scale) for c in op.chambers
            )
            residence = ticks(residence, scale)
            due += hold + duration + residence
            steps.append(
                dict(
                    stage=k,
                    hold_tick=hold,
                    process_max_tick=duration,
                    residence_tick=residence,
                    latest_pick_end_tick=due,
                )
            )


def verify_bound(p, cert):
    if cert.get("kind") == "propagated_mandatory_load":
        return any(candidate == cert for candidate in propagated_bounds(p))
    if cert.get("kind") == "two_wafer_repair_chain":
        return check_chain(p, cert)
    for spec, loc, k, due in _deadlines(p):
        if spec.wafer_id != cert.get("wafer") or due != cert.get("deadline_tick"):
            continue
        cap = cert.get("upper_tick")
        if type(cap) is not int:
            return False
        if cert.get("kind") == "sealed_pick":
            return (
                loc == p.failed_chamber
                and getattr(p, "sealed_finished", False)
                and cap + ticks(p.config.robot.pick_seconds, p.scale) == due
            )
        if cert.get("kind") == "mandatory_load" and k < len(spec.route):
            hold = p.holding[spec.wafer_id][k]
            return (
                set(spec.route[k].chambers) == {p.failed_chamber}
                and hold is not None
                and cert.get("holding_tick") == ticks(hold, p.scale)
                and cap + ticks(p.config.robot.place_seconds, p.scale) == due + cert["holding_tick"]
            )
    return False


def best_bound(p):
    candidates = list(deadline_bounds(p))
    chain = chain_bound(p)
    if chain:
        candidates.append(chain)
    if any(not verify_bound(p, cert) for cert in candidates):
        raise RuntimeError("A generated proof did not pass the arithmetic checker")
    return min(candidates, key=lambda c: c["upper_tick"], default=None)
