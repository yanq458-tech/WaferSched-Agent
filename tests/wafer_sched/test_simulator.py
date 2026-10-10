"""Time/occupation assertions against hand-computed physical schedules."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from wafer_sched import Action, EquipmentConfig, Simulator, load_config
from wafer_sched.driver import run_validation_driver
from wafer_sched.metrics import calculate_metrics
from wafer_sched.verification import validate_state

DEMO = Path(__file__).resolve().parents[2] / "configs/wafer_sched/minimal_demo.json"


def equipment(*, count=1, process=5, times=(1, 1, 1), downtimes=(), release=0):
    return EquipmentConfig.from_dict({
        "robot": dict(zip(("pick_seconds", "move_seconds", "place_seconds"), times)),
        "chambers": [
            {"id": "A", "processing_times": {"a": process}},
            {"id": "B", "processing_times": {"b": process}},
        ],
        "wafers": [{"id": f"W{index + 1}", "release_seconds": release,
                    "route": [{"recipe": "a", "chambers": ["A"]}]}
                   for index in range(count)],
        "downtimes": list(downtimes),
    })


def finish_robot(simulator, action):
    result = simulator.submit(action)
    assert result.valid, result.reason
    while simulator.state.robot.busy:
        assert simulator.advance_next()


def parallel_equipment(process=10):
    original = equipment(count=2, process=process)
    second = replace(original.wafers[1], route=(replace(original.wafers[1].route[0],
                                                      recipe="b", chambers=("B",)),))
    return replace(original, wafers=(original.wafers[0], second))


def test_single_wafer_two_stage_theoretical_time_and_exact_metrics():
    original = load_config(DEMO)
    simulator = Simulator(replace(original, wafers=original.wafers[:1]))
    assert run_validation_driver(simulator)["status"] == "completed"
    # Three transfers * (pick1 + move1 + place1) + clean4 + rinse6 = 19.
    metrics = calculate_metrics(simulator.trace)
    assert metrics["makespan_seconds"] == 19
    assert metrics["finite_batch_wph"] == pytest.approx(3600 / 19)
    assert metrics["robot_action_seconds"] == 9
    assert metrics["robot_utilization"] == pytest.approx(9 / 19)
    assert metrics["chamber_processing_seconds"] == {"CLEAN": 4, "RINSE": 6}
    assert metrics["chamber_utilization"] == pytest.approx({"CLEAN": 4 / 19, "RINSE": 6 / 19})
    assert metrics["blocking_seconds"] == 2  # Process complete -> pick complete, 1s per chamber.
    assert metrics["average_waiting_seconds"] == 0
    wafer = simulator.state.wafers["W1"]
    assert [(row["start"], row["end"]) for row in wafer.processing_records] == [(3, 7), (10, 16)]
    assert [(row["start"], row["end"]) for row in wafer.transfer_records] == [(0, 3), (7, 10), (16, 19)]
    assert wafer.location == "OUT" and wafer.stage == 2 and wafer.completed_at == 19
    assert simulator.validate_state()


def test_two_wafers_sequential_processing_includes_empty_repositioning():
    simulator = Simulator(equipment(count=2))
    assert run_validation_driver(simulator)["status"] == "completed"
    # W1 0..11; OUT->LOAD 11..12, W2 input 12..15, process 15..20, output 20..23.
    metrics = calculate_metrics(simulator.trace)
    assert metrics["makespan_seconds"] == 23
    assert metrics["chamber_processing_seconds"] == {"A": 10, "B": 0}
    assert metrics["robot_action_seconds"] == 13
    assert metrics["wafer_waiting_seconds"] == {"W1": 0, "W2": 12}
    assert metrics["average_waiting_seconds"] == 6
    assert metrics["blocking_seconds"] == 2
    assert simulator.state.wafers["W1"].completed_at == 11
    assert simulator.state.wafers["W2"].completed_at == 23


def test_chambers_process_in_parallel_with_exact_overlap_and_utilization():
    simulator = Simulator(parallel_equipment())
    assert run_validation_driver(simulator)["status"] == "completed"
    first = simulator.state.wafers["W1"].processing_records[0]
    second = simulator.state.wafers["W2"].processing_records[0]
    assert (first["start"], first["end"]) == (3, 13)
    assert (second["start"], second["end"]) == (7, 17)
    assert min(first["end"], second["end"]) - max(first["start"], second["start"]) == 6
    metrics = calculate_metrics(simulator.trace)
    assert metrics["makespan_seconds"] == 21
    assert metrics["chamber_utilization"] == pytest.approx({"A": 10 / 21, "B": 10 / 21})
    assert metrics["robot_action_seconds"] == 15
    assert metrics["average_waiting_seconds"] == 3
    assert metrics["blocking_seconds"] == 4


def test_robot_mutex_rejects_without_mutating_state_queue_or_log():
    simulator = Simulator(equipment(count=2))
    assert simulator.submit(Action.transfer("W1", "A"))
    before, trace = simulator.snapshot(), deepcopy(simulator.trace)
    assert simulator.submit(Action.transfer("W2", "A")).code == "robot_busy"
    assert simulator.snapshot() == before and simulator.trace == trace
    assert simulator.state.robot.busy and simulator.state.robot.carrying is None
    simulator.run_until(1)
    assert simulator.state.robot.carrying == "W1"
    assert simulator.state.wafers["W1"].location == "ROBOT"
    assert simulator.state.chambers["A"].wafer_id is None


def test_chamber_reservation_and_capacity_remain_owned_until_pick_complete():
    simulator = Simulator(equipment(count=2))
    simulator.submit(Action.transfer("W1", "A"))
    assert simulator.state.chambers["A"].reservation == "W1"
    simulator.run_until(3)
    assert simulator.state.chambers["A"].wafer_id == "W1"
    assert simulator.state.chambers["A"].reservation is None
    assert simulator.validate_action(Action.transfer("W2", "A")).code == "chamber_full"
    simulator.run_until(8)
    assert simulator.state.chambers["A"].status == "blocked"
    assert simulator.state.wafers["W1"].location == "A"
    simulator.submit(Action.unload("W1"))
    assert simulator.state.chambers["A"].wafer_id == "W1"
    simulator.run_until(8.5)
    assert simulator.state.chambers["A"].wafer_id == "W1"
    simulator.run_until(9)
    assert simulator.state.chambers["A"].wafer_id is None


def test_illegal_empty_pick_and_empty_gripper_place_have_specific_reasons():
    simulator = Simulator(equipment())
    before = simulator.snapshot()
    assert simulator.submit(Action.place("W1", "A")).code == "robot_not_carrying"
    assert simulator.snapshot() == before
    finish_robot(simulator, Action.move("A"))
    before = simulator.snapshot()
    assert simulator.submit(Action.pick("W1", "A")).code == "empty_chamber"
    assert simulator.snapshot() == before


def test_process_order_and_unfinished_processing_are_enforced():
    original = load_config(DEMO)
    simulator = Simulator(replace(original, wafers=original.wafers[:1]))
    assert simulator.submit(Action.transfer("W1", "RINSE")).code == "route_order"
    assert simulator.submit(Action.unload("W1")).code == "route_incomplete"
    finish_robot(simulator, Action.transfer("W1", "CLEAN"))
    assert simulator.state.time == 3
    assert simulator.state.chambers["CLEAN"].remaining == 4
    before = simulator.snapshot()
    assert simulator.submit(Action.transfer("W1", "RINSE")).code == "process_unfinished"
    assert simulator.snapshot() == before
    simulator.run_until(7)
    assert simulator.state.wafers["W1"].stage == 1
    assert simulator.validate_action(Action.transfer("W1", "CLEAN")).code == "route_order"


def test_same_seed_produces_identical_event_log_and_metrics():
    first, second = Simulator(load_config(DEMO), seed=7), Simulator(load_config(DEMO), seed=7)
    run_validation_driver(first)
    run_validation_driver(second)
    assert first.trace == second.trace
    assert calculate_metrics(first.trace) == calculate_metrics(second.trace)


def test_simultaneous_completion_precedes_new_process_start_stably():
    simulator = Simulator(parallel_equipment(process=4))
    finish_robot(simulator, Action.transfer("W1", "A"))
    finish_robot(simulator, Action.transfer("W2", "B"))
    events = [row["event"] for row in simulator.trace if row["time"] == 7]
    assert events == ["ChamberProcessComplete", "RobotPlaceComplete", "ChamberProcessStart"]
    assert simulator.state.wafers["W1"].stage == 1
    assert simulator.state.wafers["W2"].stage == 0
    assert simulator.state.chambers["B"].remaining == 4
    assert len({event.sequence for event in simulator.state.events}) == len(simulator.state.events)


def test_physical_cycle_is_reported_as_potential_deadlock_with_resource_reasons():
    original = parallel_equipment(process=2)
    first = replace(original.wafers[0], route=original.wafers[0].route + original.wafers[1].route)
    second = replace(original.wafers[1], route=original.wafers[1].route + original.wafers[0].route)
    simulator = Simulator(replace(original, wafers=(first, second)))
    outcome = run_validation_driver(simulator)
    assert outcome["status"] == "deadlocked"
    assert simulator.state.time == 9
    assert simulator.state.deadlock["code"] == "no_progress_action_or_future_event"
    assert {entry["rejections"][0]["code"] for entry in simulator.state.deadlock["waits"]} == {"chamber_full"}
    assert simulator.trace[-1]["event"] == "PotentialDeadlock"
    assert simulator.validate_state()
    metrics = calculate_metrics(simulator.trace)
    assert metrics["makespan_seconds"] is None and metrics["completed_wafers"] == 0
    assert metrics["chamber_processing_seconds"] == {"A": 2, "B": 2}


def test_future_processing_and_arrival_are_waits_not_deadlocks():
    simulator = Simulator(equipment(release=5))
    assert simulator.detect_deadlock() is None
    assert simulator.legal_actions() == (Action.wait(),)
    assert simulator.submit(Action.transfer("W1", "A")).code == "wafer_not_released"
    simulator.submit(Action.wait())
    assert simulator.state.time == 5
    finish_robot(simulator, Action.transfer("W1", "A"))
    assert simulator.state.time == 8
    assert simulator.detect_deadlock() is None
    assert simulator.state.chambers["A"].remaining == 5
    run_validation_driver(simulator)
    metrics = calculate_metrics(simulator.trace)
    assert metrics["makespan_seconds"] == 16
    assert metrics["average_waiting_seconds"] == 0  # Unreleased time excluded.


def test_clock_advances_by_queued_boundary_without_skipping_operations():
    simulator = Simulator(equipment())
    simulator.submit(Action.transfer("W1", "A"))
    simulator.run_until(2)
    assert simulator.state.time == 2
    assert simulator.state.robot.phase == "placing"
    assert simulator.state.robot.carrying == "W1"
    assert simulator.state.chambers["A"].wafer_id is None
    assert [row["time"] for row in simulator.trace] == sorted(row["time"] for row in simulator.trace)
    before = simulator.snapshot()
    with pytest.raises(ValueError):
        simulator.run_until(1)
    assert simulator.snapshot() == before
    simulator.state.time = 1
    assert simulator.validate_state().code == "clock_regression"


def test_explicit_primitives_enforce_payload_position_and_full_records():
    simulator = Simulator(equipment(count=2))
    finish_robot(simulator, Action.pick("W1", "LOAD"))
    assert simulator.state.time == 1 and simulator.state.robot.carrying == "W1"
    assert simulator.validate_action(Action.pick("W2", "LOAD")).code == "gripper_occupied"
    assert simulator.validate_action(Action.place("W1", "A")).code == "robot_position"
    finish_robot(simulator, Action.move("A"))
    assert simulator.validate_action(Action.place("W2", "A")).code == "payload_mismatch"
    finish_robot(simulator, Action.place("W1", "A"))
    simulator.run_until(8)
    finish_robot(simulator, Action.pick("W1", "A"))
    finish_robot(simulator, Action.move("OUT"))
    finish_robot(simulator, Action.place("W1", "OUT"))
    assert simulator.state.wafers["W1"].completed_at == 11
    assert len(simulator.state.wafers["W1"].transfer_records) == 2
    assert simulator.validate_state()


def test_repeated_chamber_route_requires_two_distinct_processes():
    original = equipment(process=2)
    chamber = replace(original.chambers[0], processing_times=(("a", 2), ("repeat", 3)))
    wafer = replace(original.wafers[0], route=original.wafers[0].route + (
        replace(original.wafers[0].route[0], recipe="repeat"),))
    simulator = Simulator(replace(original, chambers=(chamber, original.chambers[1]), wafers=(wafer,)))
    assert run_validation_driver(simulator)["status"] == "completed"
    assert simulator.state.time == 13
    assert [row["recipe"] for row in simulator.state.wafers["W1"].processing_records] == ["a", "repeat"]
    assert calculate_metrics(simulator.trace)["chamber_processing_seconds"]["A"] == 5


@pytest.mark.parametrize("downtimes,expected_time", [
    ([{"chamber": "A", "start": 4, "end": 7}], 14),
    ([{"chamber": "A", "start": 4, "end": 5},
      {"chamber": "A", "start": 5, "end": 7}], 14),
    ([{"chamber": "A", "start": 8, "end": 10}], 13),
])
def test_processing_pause_retains_remaining_time_and_active_processing_integral(downtimes, expected_time):
    simulator = Simulator(equipment(downtimes=downtimes))
    assert run_validation_driver(simulator)["status"] == "completed"
    metrics = calculate_metrics(simulator.trace)
    assert metrics["makespan_seconds"] == expected_time
    assert metrics["chamber_processing_seconds"]["A"] == 5
    assert metrics["robot_action_seconds"] == 6
    assert metrics["average_waiting_seconds"] == expected_time - 11
    assert len(simulator.state.wafers["W1"].processing_records) == 1


def test_failure_during_loaded_move_holds_wafer_and_reservation_until_recovery():
    simulator = Simulator(equipment(downtimes=[{"chamber": "A", "start": 2, "end": 5}]))
    simulator.submit(Action.transfer("W1", "A"))
    simulator.run_until(3)
    assert simulator.state.robot.phase == "waiting_recovery"
    assert simulator.state.robot.carrying == "W1"
    assert simulator.state.chambers["A"].wafer_id is None
    assert simulator.state.chambers["A"].reservation == "W1"
    assert simulator.state.wafers["W1"].location == "ROBOT"
    run_validation_driver(simulator)
    metrics = calculate_metrics(simulator.trace)
    assert metrics["makespan_seconds"] == 14
    assert metrics["robot_action_seconds"] == 6
    assert metrics["robot_recovery_wait_seconds"] == 3
    assert metrics["average_waiting_seconds"] == 3
    assert [row["time"] for row in simulator.trace if row["event"] == "RobotPlaceStart"] == [5, 13]


def test_failure_mid_placement_preserves_unfinished_place_duration():
    simulator = Simulator(equipment(times=(1, 1, 2),
                                    downtimes=[{"chamber": "A", "start": 3, "end": 6}]))
    simulator.submit(Action.transfer("W1", "A"))
    simulator.run_until(3)
    assert simulator.state.robot.phase == "waiting_recovery"
    assert simulator.state.robot.place_remaining == 1
    assert simulator.state.robot.carrying == "W1"
    run_validation_driver(simulator)
    metrics = calculate_metrics(simulator.trace)
    assert metrics["makespan_seconds"] == 16
    assert metrics["robot_action_seconds"] == 8
    assert metrics["robot_recovery_wait_seconds"] == 3
    assert metrics["chamber_processing_seconds"]["A"] == 5
    assert [row["time"] for row in simulator.trace if row["event"] == "RobotPlaceComplete"] == [7, 16]


def test_zero_durations_settle_finitely_without_fabricating_wph():
    simulator = Simulator(equipment(process=0, times=(0, 0, 0)))
    assert run_validation_driver(simulator)["status"] == "completed"
    metrics = calculate_metrics(simulator.trace)
    assert metrics["makespan_seconds"] == 0
    assert metrics["completed_wafers"] == 1
    assert metrics["finite_batch_wph"] is None
    assert metrics["robot_utilization"] is None
    assert metrics["blocking_seconds"] == 0
    assert len(simulator.trace) < 30


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True])
def test_invalid_durations_rejected_at_configuration_boundary(value):
    with pytest.raises(ValueError):
        equipment(times=(value, 1, 1))
    with pytest.raises(ValueError):
        equipment(process=value)


def test_configuration_rejects_unsupported_capacity_and_invalid_routes():
    original = equipment()
    with pytest.raises(ValueError, match="robot capacity"):
        replace(original, robot=replace(original.robot, capacity=2))
    with pytest.raises(ValueError, match="chamber capacity"):
        replace(original, chambers=(replace(original.chambers[0], capacity=2),))
    with pytest.raises(ValueError, match="does not support"):
        replace(original, wafers=(replace(original.wafers[0], route=(
            replace(original.wafers[0].route[0], recipe="b"),)),))


def test_state_validation_detects_lost_duplicate_and_incomplete_wafer_records():
    simulator = Simulator(equipment())
    corrupted = deepcopy(simulator.state)
    corrupted.wafers.clear()
    assert not validate_state(corrupted, simulator.config)
    corrupted = deepcopy(simulator.state)
    corrupted.robot.carrying = "W1"
    assert not validate_state(corrupted, simulator.config)
    run_validation_driver(simulator)
    corrupted = deepcopy(simulator.state)
    corrupted.wafers["W1"].transfer_records.pop()
    assert "full transfer records" in validate_state(corrupted, simulator.config).reason
    assert simulator.validate_state()


def test_observations_are_detached_and_all_catalogue_actions_are_legal():
    simulator = Simulator(load_config(DEMO))
    observation = simulator.snapshot()
    observation["wafers"]["W1"]["stage"] = 100
    observation["chambers"]["CLEAN"]["wafer_id"] = "unknown"
    assert simulator.state.wafers["W1"].stage == 0
    assert simulator.state.chambers["CLEAN"].wafer_id is None
    assert all(simulator.validate_action(action) for action in simulator.legal_actions())


def test_time_budget_reports_truncation_and_censored_batch_metrics():
    simulator = Simulator(equipment())
    outcome = run_validation_driver(simulator, max_time=2)
    assert outcome == {"status": "truncated", "reason": "time_budget"}
    metrics = calculate_metrics(simulator.trace)
    assert metrics["window_duration_seconds"] == 2
    assert metrics["makespan_seconds"] is None
    assert metrics["completed_wafers"] == 0
    assert metrics["average_waiting_seconds"] is None
    assert metrics["robot_action_seconds"] == 2
    assert metrics["chamber_processing_seconds"]["A"] == 0


def test_metrics_reject_regressed_event_log_and_do_not_use_config_values():
    simulator = Simulator(equipment())
    run_validation_driver(simulator)
    trace = deepcopy(simulator.trace)
    assert calculate_metrics(trace)["makespan_seconds"] == 11
    trace[-1]["time"] = -1
    with pytest.raises(ValueError, match="monotone"):
        calculate_metrics(trace)


def test_demo_exact_event_metrics_and_complete_records():
    simulator = Simulator(load_config(DEMO))
    assert run_validation_driver(simulator)["status"] == "completed"
    metrics = calculate_metrics(simulator.trace)
    assert metrics["makespan_seconds"] == 47
    assert metrics["finite_batch_wph"] == pytest.approx(10800 / 47)
    assert metrics["robot_action_seconds"] == 33
    assert metrics["chamber_processing_seconds"] == {"CLEAN": 12, "RINSE": 18}
    assert metrics["chamber_blocking_seconds"] == {"CLEAN": 9, "RINSE": 5}
    assert metrics["wafer_waiting_seconds"] == {"W1": 1, "W2": 15, "W3": 28}
    assert metrics["average_waiting_seconds"] == pytest.approx(44 / 3)
    for wafer in simulator.state.wafers.values():
        assert len(wafer.processing_records) == 2
        assert len(wafer.transfer_records) == 3
        assert wafer.stage == 2 and wafer.location == "OUT"
    starts = [row for row in simulator.trace if row["event"].startswith("Robot")
              and row["event"].endswith("Start")]
    assert sum(row["end_time"] - row["start_time"] for row in starts) == 33
    assert all(left["end_time"] <= right["start_time"] for left, right in zip(starts, starts[1:]))


def test_three_chamber_serial_route_has_theoretical_21_second_completion():
    config = EquipmentConfig.from_dict({
        "robot": {"pick_seconds": 1, "move_seconds": 1, "place_seconds": 1},
        "chambers": [{"id": key, "processing_times": {key: duration}}
                     for key, duration in (("A", 2), ("B", 3), ("C", 4))],
        "wafers": [{"id": "W", "route": [{"recipe": key, "chambers": [key]}
                                           for key in ("A", "B", "C")]}],
    })
    simulator = Simulator(config)
    run_validation_driver(simulator)
    metrics = calculate_metrics(simulator.trace)
    assert metrics["makespan_seconds"] == 4 * 3 + 2 + 3 + 4 == 21
    assert metrics["chamber_processing_seconds"] == {"A": 2, "B": 3, "C": 4}
    assert metrics["robot_action_seconds"] == 12
    assert metrics["blocking_seconds"] == 3
    assert len(simulator.state.wafers["W"].processing_records) == 3


def test_unavailable_initial_chamber_rejects_new_work_and_recovers_at_exact_time():
    simulator = Simulator(equipment(downtimes=[{"chamber": "A", "start": 0, "end": 5}]))
    before = simulator.snapshot()
    assert simulator.submit(Action.transfer("W1", "A")).code == "chamber_unavailable"
    assert simulator.snapshot() == before
    assert simulator.detect_deadlock() is None
    run_validation_driver(simulator)
    assert calculate_metrics(simulator.trace)["makespan_seconds"] == 16
    assert calculate_metrics(simulator.trace)["average_waiting_seconds"] == 5


def test_extended_observation_window_keeps_makespan_separate_from_wph_denominator():
    simulator = Simulator(equipment())
    run_validation_driver(simulator)
    simulator.run_until(20)
    metrics = calculate_metrics(simulator.trace)
    assert metrics["makespan_seconds"] == 11
    assert metrics["window_duration_seconds"] == 20
    assert metrics["finite_batch_wph"] == 180
    assert metrics["chamber_utilization"]["A"] == 0.25
    assert metrics["robot_utilization"] == 0.3


def test_idle_held_wafer_time_counts_as_waiting_and_not_robot_action():
    simulator = Simulator(equipment())
    finish_robot(simulator, Action.pick("W1", "LOAD"))
    simulator.run_until(4)
    metrics = calculate_metrics(simulator.trace)
    assert simulator.state.robot.carrying == "W1" and not simulator.state.robot.busy
    assert metrics["robot_action_seconds"] == 1
    assert metrics["wafer_waiting_seconds"]["W1"] == 3
    assert metrics["released_average_waiting_seconds"] == 3


def test_state_validator_rejects_mismatched_wafer_process_status():
    simulator = Simulator(equipment())
    finish_robot(simulator, Action.transfer("W1", "A"))
    corrupted = deepcopy(simulator.state)
    corrupted.wafers["W1"].status = "waiting"
    assert "statuses disagree" in validate_state(corrupted, simulator.config).reason
