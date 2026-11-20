"""Construct a sufficient unboundedness witness on healthy terminal chambers."""

from dataclasses import dataclass
from functools import lru_cache
from time import perf_counter

from ..cpsat_model import ticks
from .dispatch import replay_incident
from .model import dimensions
from .replay import replay_recovery


@dataclass(frozen=True)
class Job:
    wafer: str
    stage: int
    source: str
    ready: int
    due: int | None
    choices: tuple
    residence: int | None
    hold_in: int | None
    hold_out: int | None


def terminal_jobs(p, *, healthy_only=True):
    """Only disjoint source/terminal roles, no sealed or occupied failed chamber."""
    snap = p.snapshot
    if snap["robot"]["carrying"] or snap["chambers"][p.failed_chamber]["wafer_id"]:
        return []
    chambers = {c.chamber_id: c for c in p.config.chambers}
    occupied = {c for c, s in snap["chambers"].items() if s["wafer_id"] is not None}
    scale = p.scale

    def limit(x):
        return None if x is None else ticks(x, scale)

    jobs = []
    for spec in p.config.wafers:
        wid = spec.wafer_id
        state = snap["wafers"][wid]
        loc = state["location"]
        if loc not in occupied:
            return []
        chamber = snap["chambers"][loc]
        active = chamber["status"] == "processing"
        stage = state["stage"] + int(active)
        if stage != len(spec.route) - 1 or stage < 1:
            return []
        ready = p.relative_tick(
            chamber["ready_at"] if active else state["processing_records"][-1]["end"]
        )
        source_limit = limit(p.residency[wid][stage - 1])
        route = spec.route[stage]
        if not healthy_only and occupied.intersection(route.chambers):
            return []
        choices = tuple(
            (c, ticks(chambers[c].processing_time(route.recipe), scale))
            for c in route.chambers
            if (not healthy_only or c != p.failed_chamber) and c not in occupied
        )
        if not choices:
            return []
        jobs.append(
            Job(
                wid,
                stage,
                loc,
                ready,
                None if source_limit is None else ready + source_limit,
                choices,
                limit(p.residency[wid][stage]),
                limit(p.holding[wid][stage]),
                limit(p.holding[wid][stage + 1]),
            )
        )
    return jobs


def find_healthy_schedule(p, deadline):
    jobs = terminal_jobs(p)
    if not jobs:
        return None, {"outcome": "inapplicable", "blocks_tested": 0}
    scale = p.scale
    robot = p.config.robot
    pick, place = ticks(robot.pick_seconds, scale), ticks(robot.place_seconds, scale)

    @lru_cache(maxsize=None)
    def travel(a, b):
        return ticks(robot.travel(a, b), scale)

    def simulate(sequence, now, pos):
        ready = {}
        transfers = []
        processes = []
        for job, dest, duration, unload in sequence:
            if unload:
                source, target, release, stage, hold = (
                    dest,
                    "OUT",
                    ready[job.wafer],
                    job.stage + 1,
                    job.hold_out,
                )
                due = None if job.residence is None else release + job.residence
            else:
                source, target, release, stage, hold = (
                    job.source,
                    dest,
                    job.ready,
                    job.stage,
                    job.hold_in,
                )
                due = job.due
            start = max(now + travel(pos, source), release)
            taken = start + pick
            putting = taken + travel(source, target)
            end = putting + place
            if (due is not None and taken > due) or (hold is not None and end - taken > hold):
                return None
            transfers.append(
                dict(
                    wafer_id=job.wafer,
                    stage=stage,
                    source=source,
                    destination=target,
                    initially_carried=False,
                    pick_start=start,
                    pick_end=taken,
                    place_start=putting,
                    place_end=end,
                )
            )
            if not unload:
                ready[job.wafer] = end + duration
                processes.append(
                    dict(
                        wafer_id=job.wafer,
                        stage=stage,
                        chamber=target,
                        start=end,
                        end=end + duration,
                    )
                )
            now, pos = end, target
        return transfers, processes, now

    def patterns(first, others):
        for a, pa in first.choices:
            x = (first, a, pa, False)
            out_x = (first, a, pa, True)
            yield [x, out_x]
            for second in others:
                for b, pb in second.choices:
                    if a == b:
                        continue
                    y = (second, b, pb, False)
                    out_y = (second, b, pb, True)
                    yield [x, y, out_x, out_y]
                    yield [x, y, out_y, out_x]

    tested = 0
    # Try two deterministic priorities; no exclusion is exported to the full solver.
    for order in (
        lambda j: (float("inf") if j.due is None else j.due, j.wafer),
        lambda j: (min(v for _, v in j.choices), j.wafer),
    ):
        pending = sorted(jobs, key=order)
        now, pos = 0, p.snapshot["robot"]["position"]
        schedule = dict(ticks_per_second=scale, transfers=[], processes=[])
        while pending:
            best = None
            for seq in patterns(pending[0], pending[1:]):
                if perf_counter() >= deadline:
                    return None, dict(outcome="probe_budget", blocks_tested=tested)
                tested += 1
                result = simulate(seq, now, pos)
                if result is None:
                    continue
                steps, procs, end = result
                served = {v["wafer_id"] for v in procs}
                if any(
                    j.wafer not in served
                    and j.due is not None
                    and max(end + travel("OUT", j.source), j.ready) + pick > j.due
                    for j in pending
                ):
                    continue
                score = ((end - now) / len(served), end)
                if best is None or score < best[0]:
                    best = (score, steps, procs, end, served)
            if best is None:
                break
            _, steps, procs, now, served = best
            schedule["transfers"].extend(steps)
            schedule["processes"].extend(procs)
            pending = [j for j in pending if j.wafer not in served]
            pos = "OUT"
        if not pending:
            schedule["makespan_tick"] = now
            return schedule, dict(outcome="candidate", blocks_tested=tested)
    return None, dict(outcome="no_candidate", blocks_tested=tested)


def verified_bypass(case, p, prefix, deadline):
    plan, trace = find_healthy_schedule(p, deadline)
    if plan is None:
        return None, trace
    gated = any(p.failed_chamber in (t["source"], t["destination"]) for t in plan["transfers"])
    if gated:
        raise RuntimeError("Healthy witness uses failed chamber")
    # The schedule is independent of repair. Also exercise the original finite-cap certificate.
    sentinel = (dimensions(p)[2] + 1) / p.scale
    out = _certify(case, p, prefix, sentinel, plan)
    trace.update(
        outcome="verified_unbounded",
        proof="complete_schedule_uses_no_failed_chamber",
        repair_probe_seconds=out["witness_repair_delay_seconds"],
    )
    return out, trace


def _certify(case, p, prefix, sentinel, plan):
    replay = replay_recovery(p, sentinel, plan)
    if not replay["valid"]:
        raise RuntimeError(f"Constructed bypass failed suffix replay: {replay['errors']}")
    best = dict(schedule=plan, verification={k: v for k, v in replay.items() if k != "trace"})
    repair = prefix["offset"] + sentinel
    out = dict(
        status="UNBOUNDED",
        verification_valid=True,
        best=best,
        makespan_optimal=False,
        latest_repair_delay_seconds=None,
        finite_upper_seconds=None,
        verified_feasible_lower_seconds=repair,
        witness_repair_delay_seconds=repair,
        makespan_seconds=prefix["offset"] + plan["makespan_tick"] / p.scale,
    )
    replay_incident(case, prefix, out, best)
    return out


def lift_witness(case, p, prefix, result):
    """Upgrade a verified finite-delay witness only if the repair-dependent tail is shiftable."""
    from copy import deepcopy

    if not result.get("verification_valid"):
        return None
    plan = result["best"]["schedule"]
    steps = plan["transfers"]
    if not steps:
        return None
    failed = p.failed_chamber
    touches = [i for i, t in enumerate(steps) if failed in (t["source"], t["destination"])]
    cert = dict(tool="lift_witness", outcome="verified_unbounded")
    if not touches:
        cert["proof"] = "complete_schedule_uses_no_failed_chamber"
    elif len(steps) >= 2 and touches == [len(steps) - 2, len(steps) - 1]:
        load, unload = steps[-2:]
        wid = load["wafer_id"]
        if (
            load["source"] == failed
            or load["destination"] != failed
            or unload["source"] != failed
            or unload["destination"] != "OUT"
            or unload["wafer_id"] != wid
            or p.holding[wid][load["stage"]] is not None
        ):
            return None
        completed = {t["wafer_id"] for t in steps[:-2] if t["destination"] == "OUT"}
        if completed != {w.wafer_id for w in p.config.wafers} - {wid}:
            return None
        cert.update(
            proof="unlimited_hold_before_final_failed_chamber",
            wafer=wid,
            pickup_end=load["pick_end"],
            original_place_start=load["place_start"],
            other_wafers_completed=sorted(completed),
            ticks_per_second=p.scale,
        )
    else:
        return None
    sentinel_tick = dimensions(p)[2] + 1
    if touches:
        plan = deepcopy(plan)
        load, unload = plan["transfers"][-2:]
        shift = max(0, sentinel_tick - load["place_start"])
        for key in ("place_start", "place_end"):
            load[key] += shift
        for key in ("pick_start", "pick_end", "place_start", "place_end"):
            unload[key] += shift
        for row in plan["processes"]:
            if row["wafer_id"] == wid and row["stage"] == load["stage"]:
                row["start"] += shift
                row["end"] += shift
        plan["makespan_tick"] += shift
    out = _certify(case, p, prefix, sentinel_tick / p.scale, plan)
    cert["repair_probe_seconds"] = out["witness_repair_delay_seconds"]
    return out, cert
