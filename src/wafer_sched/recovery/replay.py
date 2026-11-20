"""Independent original-engine replay plus hard residency/holding checks."""

import math
from contextvars import ContextVar

from ..actions import Action
from ..cpsat_model import ticks

# Optional read-only observer for matched timing experiments.
witness_observer = ContextVar("recovery_witness_observer", default=None)


def replay_recovery(problem, repair_delay, schedule):
    sim = problem.simulator(repair_delay)
    scale = problem.scale
    if schedule["ticks_per_second"] != scale:
        raise ValueError("Schedule uses a different exact time scale")
    errors, decisions = [], []

    def perform(action, start_tick, expected_end):
        target = problem.now + start_tick / scale
        if (getattr(problem, "sealed_finished", False) and action.kind == "pick"
                and action.source == problem.failed_chamber and start_tick < ticks(repair_delay, scale)):
            raise ValueError("Cannot extract from a sealed chamber before repair")
        if sim.state.time > target + 1e-8:
            raise ValueError("Schedule overlaps an unfinished action")
        sim.run_until(max(sim.state.time, target))
        result = sim.submit(action)
        if not result:
            raise ValueError(f"{action}: {result.code}: {result.reason}")
        while sim.state.robot.busy:
            if not sim.advance_next():
                raise ValueError("Robot action has no completion event")
        if not math.isclose(sim.state.time, problem.now + expected_end / scale, abs_tol=1e-8):
            raise ValueError("Solver timing disagrees with independent engine")
        decisions.append({"time": target, "action": action.__dict__, "valid": True})

    try:
        end = 0
        for t in schedule["transfers"]:
            source, dest = t["source"], t["destination"]
            if not t["initially_carried"]:
                travel = problem.config.robot.travel(sim.state.robot.position, source)
                # Empty positioning may happen before the wafer finishes processing.
                if sim.state.robot.position != source:
                    perform(Action.move(source), end, end + ticks(travel, scale))
                perform(Action.pick(t["wafer_id"], source), t["pick_start"], t["pick_end"])
            travel = problem.config.robot.travel(sim.state.robot.position, dest)
            if sim.state.robot.position != dest:
                perform(Action.move(dest), t["pick_end"], t["pick_end"] + ticks(travel, scale))
            perform(Action.place(t["wafer_id"], dest), t["place_start"], t["place_end"])
            end = t["place_end"]
        if not sim.completed:
            errors.append("Not all effective WIP completed every remaining operation")
        if not math.isclose(sim.state.time - problem.now, schedule["makespan_tick"] / scale,
                            abs_tol=1e-8):
            errors.append("Makespan mismatch")
    except (ValueError, RuntimeError) as exc:
        errors.append(str(exc))

    holding = {}
    if problem.snapshot["robot"]["carrying"]:
        holding[problem.snapshot["robot"]["carrying"]] = problem.snapshot["carrying_since"]
    for row in sim.trace:
        wid = row["wafer_id"]
        if row["event"] == "RobotPickComplete":
            holding[wid] = row["time"]
            before = row["state_before"]["wafers"][wid]
            if row["source"] in sim.state.chambers:
                stage = before["stage"] - 1
                ready = before["processing_records"][stage]["end"]
                limit = problem.residency[wid][stage]
                if limit is not None and row["time"] > ready + limit + 1e-8:
                    errors.append(f"{wid}/{stage}: hard residency violated at PickComplete")
        if row["event"] == "RobotPlaceComplete":
            stage = row["state_before"]["wafers"][wid]["stage"]
            limit = problem.holding[wid][stage]
            if wid not in holding:
                errors.append(f"{wid}: missing pickup history")
            elif limit is not None and row["time"] > holding[wid] + limit + 1e-8:
                errors.append(f"{wid}/{stage}: hard holding limit violated")
            holding.pop(wid, None)
    state_report = sim.validate_state()
    if not state_report:
        errors.append(state_report.reason)
    observer = witness_observer.get()
    if observer is not None and not errors:
        observer()
    return {"valid": not errors, "errors": errors, "completed": sim.completed,
            "makespan_seconds": sim.state.time - problem.now,
            "decisions": decisions, "trace": sim.trace}
