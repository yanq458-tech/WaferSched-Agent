"""Controlled timed-plan replay through ORIGINAL Simulator methods only."""

from dataclasses import dataclass, asdict
import math

from .actions import Action
from .simulator import Simulator


@dataclass
class ReplayResult:
    simulator: Simulator
    report: dict
    decisions: list


def replay_schedule(config, schedule, *, seed=0, simulator=None):
    sim = simulator if simulator is not None else Simulator(config, seed=seed)
    expected = Simulator(config, seed=seed).snapshot()
    if sim.config != config or sim.snapshot() != expected:
        raise ValueError("Static schedule replay requires the original empty batch initial state")
    issues, decisions = [], []
    scale = schedule.get("ticks_per_second")
    if type(scale) is not int or scale <= 0:
        raise ValueError("Schedule scale must be a positive integer")
    tolerance = 1e-7
    entries = schedule.get("transfers", [])
    for index, entry in enumerate(entries):
        target = entry["start_tick"] / scale
        if target < sim.state.time - tolerance:
            issues.append({"index": index, "code": "plan_time_regression", "planned": target, "actual": sim.state.time})
            break
        # run_until adds a real boundary event, draining every earlier physical event.
        sim.run_until(max(target, sim.state.time))
        action = Action(entry["kind"], entry["wafer_id"], entry["destination"], entry["source"])
        legal = sim.validate_action(action)
        decisions.append({"index": index, "time": sim.state.time, "action": asdict(action),
                          "legal": asdict(legal), "planned": entry})
        if not legal:
            issues.append({"index": index, "code": legal.code, "reason": legal.reason})
            break
        if sim.state.robot.position != entry["previous_position"]:
            issues.append({"index": index, "code": "robot_position_mismatch"})
            break
        if sim.state.wafers[entry["wafer_id"]].stage != entry["stage"]:
            issues.append({"index": index, "code": "stage_mismatch"})
            break
        sim.submit(action)
        steps = 0
        while sim.state.robot.busy:
            if steps > 100000 or not sim.advance_next():
                issues.append({"index": index, "code": "robot_cannot_finish"})
                break
            steps += 1
        if issues:
            break
        end = entry["end_tick"] / scale
        if not math.isclose(sim.state.time, end, rel_tol=0, abs_tol=tolerance):
            issues.append({"index": index, "code": "transfer_end_mismatch", "planned": end, "actual": sim.state.time})
            break
    if not sim.completed and not issues:
        issues.append({"code": "incomplete_plan"})
    # No fallback, altered state, or silently repaired plan.
    return ReplayResult(sim, {"valid": not issues and sim.completed and bool(sim.validate_state()),
                              "issues": issues, "actions_executed": len(decisions),
                              "constraint_violations": sum(not row["legal"]["valid"] for row in decisions),
                              "deadlock": sim.detect_deadlock() if not sim.completed else None}, decisions)
