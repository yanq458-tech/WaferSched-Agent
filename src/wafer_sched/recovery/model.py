"""Warm-state extension of the existing OR-Tools interval/circuit approach.

Unlike the historical macro model, placement may wait after pickup. Chamber
ownership begins at place START, not at pickup or empty-robot positioning.
"""

from dataclasses import dataclass

from ortools.sat.python import cp_model

from ..cpsat_model import ticks


@dataclass
class RecoveryModel:
    model: object
    tasks: list
    processes: list
    locations: tuple
    makespan: object
    scale: int
    horizon: int
    finite_cap: int


def dimensions(problem):
    """Conservative finite-bound certificate; see docs/recovery.md for proof."""
    scale = problem.scale
    count, constants = 0, [1]
    for w in problem.config.wafers:
        state = problem.snapshot["wafers"][w.wafer_id]
        loc = state["location"]
        active = loc in problem.snapshot["chambers"] and (
            problem.snapshot["chambers"][loc]["status"] == "processing")
        count += len(w.route) - state["stage"] - int(active) + 1
        if state["processing_records"]:
            constants.append(abs(problem.relative_tick(state["processing_records"][-1]["end"])))
    robot = problem.config.robot
    locations = ("LOAD", "OUT", *(c.chamber_id for c in problem.config.chambers))
    constants += [ticks(robot.pick_seconds, scale), ticks(robot.place_seconds, scale)]
    constants += [ticks(robot.travel(a, b), scale) for a in locations for b in locations]
    constants += [ticks(v, scale) for c in problem.config.chambers for _, v in c.processing_times]
    constants += [ticks(v, scale) for mapping in (problem.residency, problem.holding)
                  for row in mapping.values() for v in row if v is not None]
    constants += [abs(problem.relative_tick(c["ready_at"]))
                  for c in problem.snapshot["chambers"].values() if c["ready_at"] is not None]
    if problem.snapshot.get("carrying_since") is not None:
        constants.append(abs(problem.relative_tick(problem.snapshot["carrying_since"])))
    # Four transfer time vertices, <= one process vertex per transfer, and origin.
    vertices, constant = 5 * count + 1, sum(constants)
    return vertices, constant, vertices * constant


def build_recovery_model(problem, repair_tick, *, minimize_makespan=True):
    scale = problem.scale
    vertices, constant, cap = dimensions(problem)
    horizon = vertices * (constant + repair_tick + 1)
    if horizon >= 2**50:
        raise ValueError("Recovery horizon exceeds the checked integer range")
    model = cp_model.CpModel()
    locations = ("LOAD", "OUT", *(c.chamber_id for c in problem.config.chambers))
    index = {k: i for i, k in enumerate(locations)}
    chambers = {c.chamber_id: c for c in problem.config.chambers}
    occupancy = {c: [] for c in chambers}
    tasks, processes, robot_intervals = [], [], []
    pick = ticks(problem.config.robot.pick_seconds, scale)
    place = ticks(problem.config.robot.place_seconds, scale)
    travel = [ticks(problem.config.robot.travel(a, b), scale)
              for a in locations for b in locations]

    def var(name, lo=0, hi=horizon):
        return model.new_int_var(lo, hi, name)

    def distance(a, b, label):
        ix = var(label + "_index", 0, len(travel)-1)
        model.add(ix == a * len(locations) + b)
        out = var(label, 0, max(travel))
        model.add_element(ix, travel, out)
        return out

    def interval(start, end, label, present=None):
        length = var(label + "_size")
        model.add(length == end - start)
        if present is None:
            return model.new_interval_var(start, length, end, label)
        return model.new_optional_interval_var(start, length, end, present, label)

    for spec in problem.config.wafers:
        wid = spec.wafer_id
        state = problem.snapshot["wafers"][wid]
        loc, stage = state["location"], state["stage"]
        active = loc in chambers and problem.snapshot["chambers"][loc]["status"] == "processing"
        next_stage = stage + int(active)
        chosen = {s: model.new_int_var_from_domain(cp_model.Domain.from_values(
            [index[c] for c in spec.route[s].chambers]), f"chamber_{wid}_{s}")
            for s in range(next_stage, len(spec.route))}
        own_tasks = []
        for s in range(next_stage, len(spec.route)+1):
            label = f"{wid}_{s}"
            initial = s == next_stage
            carrying = initial and loc == "ROBOT"
            source = index[problem.snapshot["robot"]["position"] if carrying else loc] if initial else chosen[s-1]
            dest = index["OUT"] if s == len(spec.route) else chosen[s]
            ps, pe, ls, le = [var(x + label) for x in ("pick_start_", "pick_end_", "place_start_", "place_end_")]
            model.add(pe == ps + (0 if carrying else pick))
            if carrying:
                model.add(ps == 0)
            model.add(ls >= pe + distance(source, dest, "loaded_" + label))
            model.add(le == ls + place)
            hold = problem.holding[wid][s]
            if hold is not None:
                origin = problem.relative_tick(problem.snapshot["carrying_since"]) if carrying else pe
                model.add(le <= origin + ticks(hold, scale))
            if s < len(spec.route) and problem.failed_chamber in spec.route[s].chambers:
                uses_failure = model.new_bool_var("uses_failed_" + label)
                model.add(dest == index[problem.failed_chamber]).only_enforce_if(uses_failure)
                model.add(dest != index[problem.failed_chamber]).only_enforce_if(uses_failure.Not())
                model.add(ls >= repair_tick).only_enforce_if(uses_failure)
            task = dict(wafer_id=wid, stage=s, source=source, destination=dest,
                        pick_start=ps, pick_end=pe, place_start=ls, place_end=le,
                        initially_carried=carrying)
            tasks.append(task)
            own_tasks.append(task)
            robot_intervals.append(interval(ps, le, "robot_" + label))

        first = own_tasks[0]
        if loc in chambers:
            completion = (problem.snapshot["chambers"][loc]["ready_at"] if active
                          else state["processing_records"][-1]["end"])
            ready = problem.relative_tick(completion)
            model.add(first["pick_start"] >= max(0, ready))
            if loc == problem.failed_chamber and getattr(problem, "sealed_finished", False):
                model.add(first["pick_start"] >= repair_tick)
            limit = problem.residency[wid][next_stage-1]
            if limit is not None:
                model.add(first["pick_end"] <= ready + ticks(limit, scale))
            occupancy[loc].append(interval(0, first["pick_end"], "initial_" + wid))
        for task, following in zip(own_tasks, own_tasks[1:]):
            s = task["stage"]
            end = var(f"process_end_{wid}_{s}")
            model.add(following["pick_start"] >= end)
            limit = problem.residency[wid][s]
            if limit is not None:
                model.add(following["pick_end"] <= end + ticks(limit, scale))
            for key in spec.route[s].chambers:
                present = model.new_bool_var(f"use_{wid}_{s}_{key}")
                model.add(task["destination"] == index[key]).only_enforce_if(present)
                model.add(task["destination"] != index[key]).only_enforce_if(present.Not())
                duration = ticks(chambers[key].processing_time(spec.route[s].recipe), scale)
                model.add(end == task["place_end"] + duration).only_enforce_if(present)
                occupancy[key].append(interval(task["place_start"], following["pick_end"],
                                                f"occupied_{wid}_{s}_{key}", present))
            processes.append(dict(wafer_id=wid, stage=s, chamber=task["destination"],
                                  start=task["place_end"], end=end))
    for row in occupancy.values():
        model.add_no_overlap(row)
    model.add_no_overlap(robot_intervals)
    arcs = []
    for i, task in enumerate(tasks, 1):
        first = model.new_bool_var(f"first_{i}")
        last = model.new_bool_var(f"last_{i}")
        arcs += [(0, i, first), (i, 0, last)]
        model.add(task["pick_start"] >= distance(
            index[problem.snapshot["robot"]["position"]], task["source"],
            f"initial_empty_{i}")).only_enforce_if(first)
        if task["initially_carried"]:
            model.add(first == 1)
        for j, other in enumerate(tasks, 1):
            if i == j:
                continue
            arc = model.new_bool_var(f"arc_{i}_{j}")
            arcs.append((i, j, arc))
            model.add(other["pick_start"] >= task["place_end"] + distance(
                task["destination"], other["source"], f"empty_{i}_{j}")).only_enforce_if(arc)
    model.add_circuit(arcs)
    makespan = var("makespan")
    model.add_max_equality(makespan, [t["place_end"] for t in tasks])
    if minimize_makespan:
        model.minimize(makespan)
    return RecoveryModel(model, tasks, processes, locations, makespan, scale, horizon, cap)
