"""Independent cross-check against actual pick/place/process event records."""

import math

from .metrics import calculate_metrics
from .schedule_adapter import replay_schedule


def validate_solution(config, result, *, seed=0):
    if result.schedule is None:
        return None, {"valid": False, "reason": "no_solver_schedule", "solver_status": result.metadata["status"]}
    replay = replay_schedule(config, result.schedule, seed=seed)
    sim = replay.simulator
    issues = list(replay.report["issues"])
    scale = result.schedule["ticks_per_second"]

    def check(field, expected, actual, **context):
        equal = math.isclose(expected, actual, rel_tol=0, abs_tol=1e-7) if isinstance(expected, (int, float)) else expected == actual
        if not equal:
            issues.append({"code": field + "_mismatch", "expected": expected, "actual": actual, **context})

    for planned in result.schedule["processes"]:
        records = sim.state.wafers[planned["wafer_id"]].processing_records
        if len(records) <= planned["stage"]:
            issues.append({"code": "missing_process", "planned": planned})
            continue
        actual = records[planned["stage"]]
        for key in ("start", "end"):
            check("process_" + key, planned[key + "_tick"] / scale, actual[key], wafer=planned["wafer_id"], stage=planned["stage"])
        check("process_chamber", planned["chamber"], actual["chamber"])
    for planned in result.schedule["transfers"]:
        records = sim.state.wafers[planned["wafer_id"]].transfer_records
        if len(records) <= planned["stage"]:
            issues.append({"code": "missing_transfer", "planned": planned})
            continue
        actual = records[planned["stage"]]
        for key in ("start", "end", "source", "destination"):
            expected = planned[key + "_tick"] / scale if key in {"start", "end"} else planned[key]
            check("transfer_" + key, expected, actual[key])
        picks = [row for row in sim.trace if row["event"] == "RobotPickComplete"
                 and row["wafer_id"] == planned["wafer_id"]
                 and row["time"] >= actual["start"] - 1e-7 and row["time"] <= actual["end"] + 1e-7]
        if len(picks) != 1:
            issues.append({"code": "pick_record_count", "planned": planned})
        else:
            check("pick_end", planned["pick_end_tick"] / scale, picks[0]["time"])
    metrics = calculate_metrics(sim.trace)
    if metrics["makespan_seconds"] is not None:
        check("makespan", result.metadata["objective_seconds"], metrics["makespan_seconds"])
        check("schedule_makespan", result.schedule["makespan_tick"] / scale, metrics["makespan_seconds"])
    valid = replay.report["valid"] and not issues
    report = {**replay.report, "valid": valid, "issues": issues,
              "solver_status": result.metadata["status"], "predicted_makespan_seconds": result.metadata["objective_seconds"],
              "actual_makespan_seconds": metrics["makespan_seconds"], "metrics_from_original_events": metrics,
              "global_optimum_of_supported_instance": valid and result.metadata["status"] == "OPTIMAL" and not result.metadata["restricted_model"]}
    return replay, report
