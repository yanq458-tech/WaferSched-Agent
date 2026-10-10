"""Performance integrals reconstructed exclusively from actual event snapshots."""

import math


def calculate_metrics(trace: list[dict]) -> dict:
    if not trace or trace[0]["time"] != 0:
        raise ValueError("Metrics need a complete trace starting at time zero")
    end = trace[-1]["time"]
    initial = trace[0]["state_after"]
    processing = {name: 0.0 for name in initial["chambers"]}
    blocking = dict(processing)
    waiting = {name: 0.0 for name in initial["wafers"]}
    robot_seconds = 0.0
    robot_recovery_seconds = 0.0
    active_phases = {"picking", "moving_empty", "moving_loaded", "placing"}
    wafer_action_phases = {"picking", "moving_loaded", "placing"}
    for left, right in zip(trace, trace[1:]):
        interval = right["time"] - left["time"]
        if not math.isfinite(interval) or interval < 0:
            raise ValueError("Event log time is not monotone and finite")
        state = left["state_after"]
        for chamber_id, chamber in state["chambers"].items():
            if chamber["status"] == "processing":
                processing[chamber_id] += interval
            elif chamber["status"] == "blocked":
                blocking[chamber_id] += interval
        robot = state["robot"]
        if robot["busy"] and robot["phase"] in active_phases:
            robot_seconds += interval
        elif robot["busy"] and robot["phase"] == "waiting_recovery":
            robot_recovery_seconds += interval
        for wafer_id, wafer in state["wafers"].items():
            physically_transported = (
                robot["busy"] and robot["phase"] in wafer_action_phases
                and robot["active_wafer"] == wafer_id
            )
            if (wafer["released"] and wafer["completed_at"] is None
                    and wafer["status"] != "processing" and not physically_transported):
                waiting[wafer_id] += interval
    final = trace[-1]["state_after"]
    completed = [name for name, wafer in final["wafers"].items()
                 if wafer["completed_at"] is not None]
    released = [name for name, wafer in final["wafers"].items() if wafer["released"]]
    all_completed = len(completed) == len(final["wafers"])
    chamber_utilization = {name: value / end if end else None
                           for name, value in processing.items()}
    return {
        "window_start_seconds": 0.0, "window_end_seconds": end,
        "window_duration_seconds": end, "completed_wafers": len(completed),
        "released_wafers": len(released), "unfinished_wafers": len(final["wafers"]) - len(completed),
        "makespan_seconds": max((final["wafers"][name]["completed_at"] for name in completed),
                                default=0.0) if all_completed else None,
        "finite_batch_wph": len(completed) * 3600 / end if end else None,
        "chamber_processing_seconds": processing,
        "chamber_utilization": chamber_utilization,
        "mean_chamber_utilization": (sum(processing.values()) / (len(processing) * end)
                                      if end else None),
        "robot_action_seconds": robot_seconds,
        "robot_utilization": robot_seconds / end if end else None,
        "robot_recovery_wait_seconds": robot_recovery_seconds,
        "wafer_waiting_seconds": waiting,
        "average_waiting_seconds": (sum(waiting[name] for name in completed) / len(completed)
                                    if completed else None),
        "released_average_waiting_seconds": (sum(waiting[name] for name in released) / len(released)
                                             if released else None),
        "chamber_blocking_seconds": blocking,
        "blocking_seconds": sum(blocking.values()),
        "blocking_rate": sum(blocking.values()) / (len(blocking) * end) if end else None,
        "throughput_semantics": "finite_batch_not_steady_state",
        "utilization_semantics": "active_processing_only_blocking_and_downtime_excluded_from_numerator",
        "waiting_semantics": "released_not_completed_not_processing_not_active_pick_loaded_move_or_place",
    }
